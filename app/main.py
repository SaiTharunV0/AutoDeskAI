from contextlib import asynccontextmanager
import hashlib
import hmac
import secrets
import json
from urllib.parse import urlsplit
from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import select, text, or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session, selectinload
from app.database import Base, engine, get_db, SessionLocal, upgrade_user_profile, upgrade_query_indexes, upgrade_application_access
from app.models import *
from app.schemas import *
from app.catalog import SOFTWARE, APPLICATIONS
from app.workflows import audit, owned_request, create_workflow, expire_tasks, correct_legacy_password_requests
from app.access import catalog_view, save_policy, submit_access, decide_access, retry_provisioning, correct_legacy_access_requests
from auth import (get_current_user, require_admin, hash_password, verify_password,
                  create_access_token, validate_config, bearer)
from agent import UnsafeRequest, close_model_client
import config

@asynccontextmanager
async def lifespan(app):
    validate_config()
    Base.metadata.create_all(engine)
    upgrade_user_profile()
    upgrade_application_access()
    upgrade_query_indexes()
    with SessionLocal() as db:
        correct_legacy_password_requests(db)
        correct_legacy_access_requests(db)
        for key in SOFTWARE:
            if not db.get(SoftwarePolicy, key):
                db.add(SoftwarePolicy(key=key))
        for key in APPLICATIONS:
            if not db.get(ApplicationPolicy, key):
                db.add(ApplicationPolicy(key=key, display_name=APPLICATIONS[key] + ' (example)',
                    description='Example catalog entry. No live provisioning integration is configured.'))
        if not db.get(AppSetting, 'ticket_closure_mode'):
            db.add(AppSetting(key='ticket_closure_mode', value='AUTOMATIC'))
        db.flush()
        for row in db.scalars(select(ApplicationPolicy)):
            recorded = db.scalar(select(AccessPolicyRevision.id).where(
                AccessPolicyRevision.application_key == row.key,
                AccessPolicyRevision.version == row.version))
            if not recorded:
                db.add(AccessPolicyRevision(application_key=row.key, version=row.version,
                    actor_id=None, snapshot_json=json.dumps(catalog_view(row), sort_keys=True)))
        db.commit()
    try:
        yield
    finally:
        close_model_client()
        engine.dispose()

app = FastAPI(title="AutoDeskAI", version="1.0.0", lifespan=lifespan,
    description="Authenticated IT workflows. Password actions use Microsoft-hosted experiences; completion is not verified here.")
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Pydantic's default error body can echo input, including submitted passwords.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})

@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable. Please retry."})

@app.exception_handler(UnsafeRequest)
async def unsafe_error(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

@app.exception_handler(RuntimeError)
async def service_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "AI service unavailable or returned invalid output. Please retry."})

@app.get("/", tags=["Health"])
def root():
    return {"message": "AutoDeskAI Backend is running"}

@app.get("/db-test", tags=["Health"])
def database_test(db: Session = Depends(get_db), user=Depends(require_admin)):
    db.execute(text("SELECT 1"))
    return {"status": "success"}

def create_registered_user(payload: Register, db: Session):
    duplicates = db.execute(select(User.email, User.username).where(or_(
        User.email == payload.email, User.username == payload.username))).all()
    if any(row.email == payload.email for row in duplicates):
        raise HTTPException(409, 'Email already registered')
    if any(row.username == payload.username for row in duplicates):
        raise HTTPException(409, 'Username already taken')
    user = User(name=f'{payload.first_name} {payload.last_name}', first_name=payload.first_name,
                last_name=payload.last_name, date_of_birth=payload.date_of_birth,
                username=payload.username, email=payload.email,
                password_hash=hash_password(payload.password.get_secret_value()), role=payload.account_role)
    db.add(user)
    try:
        db.flush()
        audit(db, user.id, "ADMIN_REGISTERED" if payload.account_role == "admin" else "USER_REGISTERED",
              "user", user.id, "COMPLETED")
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Email or username already registered') from None
    return user

@app.post("/auth/register", response_model=TokenOut, status_code=201, tags=["Authentication"])
def register(payload: Register, db: Session = Depends(get_db)):
    if payload.account_role == "admin":
        invite = payload.admin_invite_code.get_secret_value() if payload.admin_invite_code else ""
        if not config.ADMIN_REGISTRATION_CODE:
            raise HTTPException(503, "Administrator registration is not configured.")
        if not hmac.compare_digest(invite.encode("utf-8"), config.ADMIN_REGISTRATION_CODE.encode("utf-8")):
            raise HTTPException(403, "Administrator invite code is invalid.")
    user = create_registered_user(payload, db)
    audit(db, user.id, "LOGIN_SUCCESS", "user", user.id, "COMPLETED")
    db.commit()
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))

@app.post("/auth/login", response_model=TokenOut, tags=["Authentication"])
def login(payload: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(
        User.email == payload.identifier if '@' in payload.identifier else User.username == payload.identifier))
    valid = verify_password(payload.password.get_secret_value(),
                            user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        audit(db, user.id if user else None, "LOGIN_FAILED", "user", user.id if user else None, "FAILED")
        db.commit()
        raise HTTPException(401, 'Username/email or password is wrong')
    if payload.expected_role and user.role != payload.expected_role:
        audit(db, user.id, "LOGIN_PORTAL_MISMATCH", "user", user.id, "FAILED",
              "Account used the wrong sign-in portal")
        db.commit()
        raise HTTPException(403, 'This account cannot sign in through the selected portal.')
    audit(db, user.id, "LOGIN_SUCCESS", "user", user.id, "COMPLETED")
    db.commit()
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))

DUMMY_HASH = hash_password(secrets.token_urlsafe(32))

@app.get("/auth/me", response_model=UserOut, tags=["Authentication"])
def me(user=Depends(get_current_user)):
    return user

@app.get("/users", response_model=list[UserOut], tags=["Admin"])
@app.get("/admin/users", response_model=list[UserOut], tags=["Admin"])
def users(user=Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.id).limit(500)).all()

@app.post('/users', response_model=UserOut, status_code=201, tags=['Admin'],
          description='Legacy user creation route, now administrator-only and requires a password.')
def admin_create_user(payload: Register, user=Depends(require_admin), db: Session = Depends(get_db)):
    created = create_registered_user(payload, db)
    db.commit()
    return created

@app.put('/users/{user_id}', response_model=UserOut, tags=['Admin'])
def update_user(user_id: int, payload: UserUpdate, user=Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, 'User not found')
    target.name, target.email = payload.name.strip(), payload.email
    audit(db, user.id, 'USER_UPDATED', 'user', target.id, 'COMPLETED')
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Email already registered') from None
    return target

@app.delete('/users/{user_id}', tags=['Admin'], description='Deletes only unused legacy accounts; referenced accounts are retained for audit integrity.')
def delete_user(user_id: int, user=Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, 'User not found')
    if user.id == user_id or any(db.scalar(select(model).where(column == user_id).limit(1))
        for model, column in ((AuditLog, AuditLog.user_id), (Device, Device.owner_user_id),
                              (HelpdeskRequest, HelpdeskRequest.user_id), (AccessRequest, AccessRequest.user_id))):
        raise HTTPException(409, 'Account has retained history or is the active administrator')
    db.delete(target)
    audit(db, user.id, 'USER_DELETED', 'user', user_id, 'COMPLETED')
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Account has retained history') from None
    return {'status': 'success'}

@app.post("/requests", response_model=RequestOut | ChatOut, status_code=201, tags=["Requests"])
@app.post("/ai/request", response_model=RequestOut | ChatOut, status_code=201, tags=["Requests"])
def new_request(payload: RequestIn, response: Response, user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = create_workflow(db, user, payload)
        if isinstance(result, ChatOut):
            response.status_code = 200
        return result
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(HelpdeskRequest).where(HelpdeskRequest.user_id == user.id,
                                  HelpdeskRequest.idempotency_key == payload.idempotency_key))
        if existing:
            return existing
        raise

@app.get("/requests", response_model=list[RequestOut], tags=["Requests"])
def own_requests(user=Depends(get_current_user), db: Session = Depends(get_db)):
    expire_tasks(db)
    return db.scalars(select(HelpdeskRequest).options(selectinload(HelpdeskRequest.task)).where(HelpdeskRequest.user_id == user.id)
                      .order_by(HelpdeskRequest.id.desc()).limit(200)).all()

@app.get("/admin/requests", response_model=list[RequestOut], tags=["Admin"])
def all_requests(user=Depends(require_admin), db: Session = Depends(get_db)):
    expire_tasks(db)
    return db.scalars(select(HelpdeskRequest).options(selectinload(HelpdeskRequest.task))
                      .order_by(HelpdeskRequest.id.desc()).limit(500)).all()

@app.get("/requests/{request_id}", response_model=RequestOut, tags=["Requests"])
def request_detail(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    expire_tasks(db)
    return owned_request(db, request_id, user)

@app.post('/requests/{request_id}/close', response_model=RequestOut, tags=['Requests'])
def employee_close_ticket(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    request = db.scalar(select(HelpdeskRequest).where(
        HelpdeskRequest.id == request_id, HelpdeskRequest.user_id == user.id
    ).with_for_update())
    if not request:
        raise HTTPException(404, 'Request not found')
    closable = {'COMPLETED', 'FAILED', 'REJECTED', 'AWAITING_USER_ACTION',
                'NEEDS_CLARIFICATION', 'APPROVED_PROVISIONING_REQUIRED'}
    if request.status not in closable:
        raise HTTPException(409, 'This ticket is still being handled and cannot be closed yet')
    previous_status = request.status
    request.status = 'CLOSED'
    request.message = (request.message + ' Employee marked this ticket closed.')[:500]
    audit(db, user.id, 'TICKET_CLOSED_BY_EMPLOYEE', 'request', request.id, 'CLOSED', previous_status)
    db.commit()
    return request

@app.get("/requests/{request_id}/history", response_model=list[AuditOut], tags=["Requests"])
def history(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    owned_request(db, request_id, user)
    return db.scalars(select(AuditLog).where(AuditLog.resource_type == "request",
        AuditLog.resource_id == request_id).order_by(AuditLog.id)).all()

MICROSOFT_PASSWORD_URLS = {
    "PASSWORD_CHANGE": "https://myaccount.microsoft.com/",
}

def configured_sspr_url():
    value = config.MICROSOFT_SSPR_URL
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname != "passwordreset.microsoftonline.com"
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.fragment):
            raise ValueError
        return value
    except (ValueError, TypeError):
        return None

@app.get("/auth/password-recovery", tags=["Authentication"],
         description="Public Microsoft Entra SSPR destination for the logged-out recovery screen.")
def password_recovery_configuration():
    url = configured_sspr_url()
    return {"available": bool(url), "url": url}

@app.post("/requests/{request_id}/password/action", response_model=PasswordActionOut, tags=["Requests"],
          description="Return the Microsoft-hosted action for the authenticated owner. Opening it does not prove completion.")
def password_action(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(HelpdeskRequest, request_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Request not found")
    if row.intent not in (*MICROSOFT_PASSWORD_URLS, "PASSWORD_RESET"):
        raise HTTPException(409, "Not a password workflow")
    if row.status != "AWAITING_USER_ACTION":
        raise HTTPException(409, "Workflow is not awaiting user action")
    url = (configured_sspr_url() if row.intent == "PASSWORD_RESET"
           else MICROSOFT_PASSWORD_URLS[row.intent])
    if not url:
        raise HTTPException(503, "Organization password recovery is unavailable. Contact your IT administrator.")
    audit(db, user.id, row.intent + "_LINK_OPENED", "request", row.id, row.status,
          "Microsoft-hosted action issued; completion unverified")
    db.commit()
    return PasswordActionOut(request_id=row.id, status=row.status,
        url=url, message=row.message)

@app.get("/devices", response_model=list[DeviceOut], tags=["Devices"])
def own_devices(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Device).where(Device.owner_user_id == user.id)).all()

@app.post("/agent/register", response_model=DeviceEnrollment, status_code=201, tags=["Endpoint agent"],
          description="Administrator enrolls a device for an employee. Token is returned once; only its digest is stored.")
def enroll(payload: DeviceIn, user=Depends(require_admin), db: Session = Depends(get_db)):
    owner = payload.owner_user_id or user.id
    if not db.get(User, owner):
        raise HTTPException(404, "Owner not found")
    token = secrets.token_urlsafe(48)
    device = Device(device_id=payload.device_id, hostname=payload.hostname, owner_user_id=owner,
        os_info=payload.os_info, token_hash=hashlib.sha256(token.encode()).hexdigest(),
        last_seen=now() - timedelta(seconds=config.DEVICE_OFFLINE_SECONDS + 1))
    db.add(device)
    try:
        db.flush()
        audit(db, user.id, "DEVICE_REGISTERED", "device", device.id, "COMPLETED")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Device already registered") from None
    return DeviceEnrollment(device=DeviceOut.model_validate(device), agent_token=token)

def current_device(credentials=Depends(bearer), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(401, "Agent token required")
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    device = db.scalar(select(Device).where(Device.token_hash == digest, Device.status == "ACTIVE"))
    if not device:
        raise HTTPException(401, "Invalid or disabled device")
    return device

@app.get("/agent/heartbeat", response_model=DeviceOut, tags=["Endpoint agent"])
def heartbeat(device=Depends(current_device), db: Session = Depends(get_db)):
    device.last_seen = now()
    db.commit()
    return device

@app.get("/agent/tasks", response_model=list[TaskOut], tags=["Endpoint agent"],
          description="Atomically claims pending tasks belonging to this device; policy is rechecked at dispatch.")
def tasks(device=Depends(current_device), db: Session = Depends(get_db)):
    expire_tasks(db)
    device.last_seen = now()
    rows = db.scalars(select(SoftwareTask).options(selectinload(SoftwareTask.request)).where(SoftwareTask.device_id == device.id,
        SoftwareTask.status == "PENDING").with_for_update(skip_locked=True).limit(10)).all()
    policies = {policy.key: policy for policy in db.scalars(select(SoftwarePolicy).where(
        SoftwarePolicy.key.in_({task.software for task in rows})))} if rows else {}
    dispatched = []
    for task in rows:
        policy = policies.get(task.software)
        if not policy or not policy.enabled or task.software not in SOFTWARE:
            task.status = task.request.status = "REJECTED"
            task.result = task.request.message = "Software approval was revoked before dispatch."
            audit(db, task.request.user_id, "SOFTWARE_INSTALL_REJECTED", "request", task.request_id, "REJECTED")
            continue
        task.status = task.request.status = "PROCESSING"
        task.started_at = now()
        task.request.message = "Endpoint agent is processing the installation."
        audit(db, task.request.user_id, "SOFTWARE_INSTALL_STARTED", "request", task.request_id, "PROCESSING")
        dispatched.append(task)
    db.commit()
    return dispatched

@app.post("/agent/tasks/{task_id}/result", response_model=TaskOut, tags=["Endpoint agent"])
def task_result(task_id: int, payload: ResultIn, device=Depends(current_device), db: Session = Depends(get_db)):
    expire_tasks(db)
    task = db.scalar(select(SoftwareTask).where(SoftwareTask.id == task_id,
        SoftwareTask.device_id == device.id).with_for_update())
    if not task:
        raise HTTPException(404, "Task not found")
    status = "COMPLETED" if payload.success else "FAILED"
    result = ("Simulated installation completed; no OS changes made." if payload.success else "Endpoint installation failed.")
    if not payload.simulated:
        raise HTTPException(400, "This prototype accepts simulation results only")
    if task.status in ("COMPLETED", "FAILED"):
        if task.status == status and task.result == result:
            return task
        raise HTTPException(409, "Task already finalized")
    if task.status != "PROCESSING":
        raise HTTPException(409, "Task was not dispatched")
    task.status = status
    closure_setting = db.get(AppSetting, 'ticket_closure_mode')
    request_status = ('AWAITING_ADMIN_CLOSE' if payload.success and closure_setting
                      and closure_setting.value == 'ADMIN_CONFIRMATION' else status)
    task.request.status = request_status
    task.result = result
    task.request.message = (result + ' Waiting for an administrator to close this ticket.'
                            if request_status == 'AWAITING_ADMIN_CLOSE' else result)
    task.completed_at = now()
    audit(db, task.request.user_id, "SOFTWARE_INSTALL_" + status, "request", task.request_id, request_status, "Simulation")
    db.commit()
    return task

@app.get('/admin/settings/ticket-closure', tags=['Admin'])
def get_ticket_closure_setting(user=Depends(require_admin), db: Session = Depends(get_db)):
    setting = db.get(AppSetting, 'ticket_closure_mode')
    return {'mode': setting.value if setting else 'AUTOMATIC'}

@app.put('/admin/settings/ticket-closure', tags=['Admin'])
def update_ticket_closure_setting(payload: TicketClosureSettingIn, user=Depends(require_admin),
                                  db: Session = Depends(get_db)):
    setting = db.get(AppSetting, 'ticket_closure_mode')
    if not setting:
        setting = AppSetting(key='ticket_closure_mode', value=payload.mode)
        db.add(setting)
    else:
        setting.value = payload.mode
    audit(db, user.id, 'TICKET_CLOSURE_POLICY_UPDATED', 'settings', None, 'COMPLETED', payload.mode)
    db.commit()
    return {'mode': setting.value}

@app.post('/admin/requests/{request_id}/close', response_model=RequestOut, tags=['Admin'])
def close_ticket(request_id: int, user=Depends(require_admin), db: Session = Depends(get_db)):
    request = db.scalar(select(HelpdeskRequest).where(HelpdeskRequest.id == request_id).with_for_update())
    if not request:
        raise HTTPException(404, 'Request not found')
    if request.status != 'AWAITING_ADMIN_CLOSE' or request.intent != 'SOFTWARE_INSTALL':
        raise HTTPException(409, 'This ticket is not awaiting administrator closure')
    request.status = 'COMPLETED'
    request.message = 'Ticket closed by an administrator after confirming the reported installation result.'
    audit(db, user.id, 'TICKET_CLOSED_BY_ADMIN', 'request', request.id, 'COMPLETED')
    db.commit()
    return request

@app.get("/admin/devices", response_model=list[DeviceOut], tags=["Admin"])
def admin_devices(user=Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(Device).order_by(Device.id).limit(500)).all()

@app.patch("/admin/devices/{device_id}", response_model=DeviceOut, tags=["Admin"])
def device_state(device_id: int, payload: DeviceState, user=Depends(require_admin), db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    device.status = payload.status
    audit(db, user.id, "DEVICE_STATUS_UPDATED", "device", device.id, "COMPLETED")
    db.commit()
    return device

@app.get("/admin/audit", response_model=list[AuditOut], tags=["Admin"])
def audit_logs(user=Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(500)).all()

@app.get("/catalog", tags=["Requests"])
def catalog(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return {"software": [{"key": p.key, "display_name": SOFTWARE[p.key]["display_name"], "enabled": p.enabled}
                        for p in db.scalars(select(SoftwarePolicy)) if p.key in SOFTWARE],
            "applications": [{key: value for key, value in catalog_view(p).items() if key != 'config_ref'}
                        for p in db.scalars(select(ApplicationPolicy))]}

@app.put("/admin/software/{key}", tags=["Admin"])
def software_policy(key: str, payload: PolicyIn, user=Depends(require_admin), db: Session = Depends(get_db)):
    if key not in SOFTWARE:
        raise HTTPException(400, "Only predefined installer capabilities can be approved")
    row = db.get(SoftwarePolicy, key)
    row.enabled = payload.enabled
    audit(db, user.id, "SOFTWARE_POLICY_UPDATED", "policy", None, "COMPLETED", key)
    db.commit()
    return {"key": key, "enabled": row.enabled}

@app.put("/admin/applications/{key}", tags=["Admin"])
def application_policy(key: str, payload: PolicyIn, user=Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(ApplicationPolicy, key)
    if not row:
        raise HTTPException(404, "Unknown application")
    values = catalog_view(row)
    values.pop('version')
    return save_policy(db, row, ApplicationIn(**{
        **values, 'enabled': payload.enabled, 'required_role': payload.required_role}), user.id)

@app.get('/access/applications', tags=['Application access'])
def requestable_applications(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return [{key: value for key, value in catalog_view(row).items() if key != 'config_ref'}
            for row in db.scalars(select(ApplicationPolicy).where(
        ApplicationPolicy.enabled == True).order_by(ApplicationPolicy.display_name))
        if row.required_role == 'employee' or user.role == 'admin']

@app.post('/access/requests', response_model=AccessOut, status_code=201, tags=['Application access'])
def create_access_request(payload: AccessSubmit, user=Depends(get_current_user),
                          db: Session = Depends(get_db)):
    return submit_access(db, user, payload.application, payload.requested_role,
        payload.justification, payload.duration_days, payload.idempotency_key)

@app.get('/access/requests', response_model=list[AccessOut], tags=['Application access'])
def my_access_requests(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(AccessRequest).where(AccessRequest.user_id == user.id)
        .order_by(AccessRequest.id.desc()).limit(500)).all()

@app.get('/access/requests/{access_id}', response_model=AccessOut, tags=['Application access'])
def my_access_request(access_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(AccessRequest, access_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, 'Access request not found')
    return row

@app.get('/admin/access/applications', tags=['Admin application access'])
def all_applications(user=Depends(require_admin), db: Session = Depends(get_db)):
    return [catalog_view(row) for row in db.scalars(select(ApplicationPolicy).order_by(ApplicationPolicy.key))]

@app.post('/admin/access/applications', status_code=201, tags=['Admin application access'])
def add_application(payload: ApplicationIn, user=Depends(require_admin), db: Session = Depends(get_db)):
    if db.get(ApplicationPolicy, payload.key):
        raise HTTPException(409, 'Application ID already exists')
    return save_policy(db, ApplicationPolicy(key=payload.key), payload, user.id)

@app.put('/admin/access/applications/{key}', tags=['Admin application access'])
def edit_application(key: str, payload: ApplicationIn, user=Depends(require_admin), db: Session = Depends(get_db)):
    if payload.key != key:
        raise HTTPException(422, 'Application ID cannot be changed')
    row = db.scalar(select(ApplicationPolicy).where(ApplicationPolicy.key == key).with_for_update())
    if not row:
        raise HTTPException(404, 'Application not found')
    return save_policy(db, row, payload, user.id)

@app.get('/admin/access/applications/{key}/revisions', tags=['Admin application access'])
def policy_revisions(key: str, user=Depends(require_admin), db: Session = Depends(get_db)):
    return [{'version': row.version, 'actor_id': row.actor_id, 'snapshot': json.loads(row.snapshot_json),
             'created_at': row.created_at} for row in db.scalars(select(AccessPolicyRevision).where(
                AccessPolicyRevision.application_key == key).order_by(AccessPolicyRevision.version.desc()))]

@app.get('/admin/access/requests', response_model=list[AccessOut], tags=['Admin application access'])
def all_access_requests(user=Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(AccessRequest).order_by(AccessRequest.id.desc()).limit(500)).all()

@app.get('/admin/access/pending', response_model=list[AccessOut], tags=['Admin application access'])
def pending_access_requests(user=Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(AccessRequest).where(AccessRequest.status == 'AWAITING_ADMIN')
        .order_by(AccessRequest.id).limit(500)).all()

@app.post('/admin/access/requests/{access_id}/decision', response_model=AccessOut, tags=['Admin application access'])
def admin_access_decision(access_id: int, payload: AccessDecisionIn, user=Depends(require_admin),
                          db: Session = Depends(get_db)):
    if payload.decision == 'REJECT' and len(payload.reason.strip()) < 5:
        raise HTTPException(422, 'Enter a rejection reason of at least 5 characters')
    return decide_access(db, access_id, user, payload.decision, payload.reason)

@app.post('/admin/access/requests/{access_id}/provisioning/retry', response_model=AccessOut,
          tags=['Admin application access'])
def admin_retry_provisioning(access_id: int, user=Depends(require_admin), db: Session = Depends(get_db)):
    return retry_provisioning(db, access_id, user)
