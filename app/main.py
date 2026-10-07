from contextlib import asynccontextmanager
import hashlib
import secrets
from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, inspect
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session
from app.database import Base, engine, get_db, SessionLocal
from app.models import *
from app.schemas import *
from app.catalog import SOFTWARE, APPLICATIONS, ACCESS_ROLES
from app.workflows import audit, owned_request, create_workflow, expire_tasks, provision_access
from auth import (get_current_user, require_admin, hash_password, verify_password,
                  create_access_token, validate_config, bearer)
from agent import UnsafeRequest
from services.password import get_password_service, PasswordIntegrationError
import config

@asynccontextmanager
async def lifespan(app):
    validate_config()
    Base.metadata.create_all(engine)  # Additive: existing users schema stays intact.
    columns = {table: {column["name"] for column in inspect(engine).get_columns(table)}
               for table in ("helpdesk_requests", "access_requests")}
    with engine.begin() as connection:
        if "password_started_at" not in columns["helpdesk_requests"]:
            connection.execute(text(
                "ALTER TABLE helpdesk_requests ADD COLUMN password_started_at TIMESTAMP NULL"
            ))
        if "requested_role" not in columns["access_requests"]:
            connection.execute(text(
                "ALTER TABLE access_requests ADD COLUMN requested_role VARCHAR(40) "
                "NOT NULL DEFAULT 'jira_user'"
            ))
    with SessionLocal() as db:
        for key in SOFTWARE:
            if not db.get(SoftwarePolicy, key):
                db.add(SoftwarePolicy(key=key))
        for key in APPLICATIONS:
            if not db.get(ApplicationPolicy, key):
                db.add(ApplicationPolicy(key=key))
        db.commit()
    yield

app = FastAPI(title="AutoDeskAI", version="1.0.0", lifespan=lifespan,
    description="Authenticated, policy-controlled IT workflows integrated with Entra ID and Jira.")

@app.middleware("http")
async def strip_api_prefix(request: Request, call_next):
    path = request.scope["path"]
    if path == "/api" or path.startswith("/api/"):
        request.scope["path"] = path[4:] or "/"
        raw_path = request.scope.get("raw_path")
        if raw_path is not None:
            request.scope["raw_path"] = raw_path[4:] or b"/"
    return await call_next(request)

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
    return JSONResponse(status_code=503, content={"detail": "Local AI unavailable or returned invalid output. Please retry."})

@app.get("/", tags=["Health"])
def root():
    return {"message": "AutoDeskAI Backend is running"}

@app.get("/db-test", tags=["Health"])
def database_test(db: Session = Depends(get_db), user=Depends(require_admin)):
    db.execute(text("SELECT 1"))
    return {"status": "success"}

@app.post("/auth/register", response_model=UserOut, status_code=201, tags=["Authentication"])
def register(payload: Register, db: Session = Depends(get_db)):
    return create_user(payload, db)

def create_user(payload: Register, db: Session, allow_reserved_provider_account=False):
    reserved = {config.ENTRA_TEST_ACCOUNT_UPN, config.JIRA_TEST_ACCOUNT_EMAIL} - {""}
    if payload.email in reserved and not allow_reserved_provider_account:
        raise HTTPException(403, "Provider test accounts must be created by an administrator")
    user = User(name=payload.name.strip(), email=payload.email,
                password_hash=hash_password(payload.password.get_secret_value()), role="employee")
    db.add(user)
    try:
        db.flush()
        audit(db, user.id, "USER_REGISTERED", "user", user.id, "COMPLETED")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered") from None
    return user

@app.post("/auth/login", response_model=TokenOut, tags=["Authentication"])
def login(payload: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    valid = verify_password(payload.password.get_secret_value(),
                            user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        audit(db, user.id if user else None, "LOGIN_FAILED", "user", user.id if user else None, "FAILED")
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    audit(db, user.id, "LOGIN_SUCCESS", "user", user.id, "COMPLETED")
    db.commit()
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))

DUMMY_HASH = hash_password(secrets.token_urlsafe(32))

@app.get("/auth/me", response_model=UserOut, tags=["Authentication"])
def me(user=Depends(get_current_user)):
    return user

@app.get("/auth/entra/config", tags=["Authentication"])
def entra_config(user=Depends(get_current_user)):
    return {"enabled": bool(config.ENTRA_TENANT_ID and config.ENTRA_CLIENT_ID),
            "tenant_id": config.ENTRA_TENANT_ID, "client_id": config.ENTRA_CLIENT_ID}

@app.get("/users", response_model=list[UserOut], tags=["Admin"])
@app.get("/admin/users", response_model=list[UserOut], tags=["Admin"])
def users(user=Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.id).limit(500)).all()

@app.post('/users', response_model=UserOut, status_code=201, tags=['Admin'],
          description='Legacy user creation route, now administrator-only and requires a password.')
def admin_create_user(payload: Register, user=Depends(require_admin), db: Session = Depends(get_db)):
    return create_user(payload, db, allow_reserved_provider_account=True)

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

@app.post("/requests", response_model=RequestOut, status_code=201, tags=["Requests"])
@app.post("/ai/request", response_model=RequestOut, status_code=201, tags=["Requests"])
def new_request(payload: RequestIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return create_workflow(db, user, payload)
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
    return db.scalars(select(HelpdeskRequest).where(HelpdeskRequest.user_id == user.id)
                      .order_by(HelpdeskRequest.id.desc()).limit(200)).all()

@app.get("/admin/requests", response_model=list[RequestOut], tags=["Admin"])
def all_requests(user=Depends(require_admin), db: Session = Depends(get_db)):
    expire_tasks(db)
    return db.scalars(select(HelpdeskRequest).order_by(HelpdeskRequest.id.desc()).limit(500)).all()

@app.get("/requests/{request_id}", response_model=RequestOut, tags=["Requests"])
def request_detail(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    expire_tasks(db)
    return owned_request(db, request_id, user)

@app.get("/requests/{request_id}/history", response_model=list[AuditOut], tags=["Requests"])
def history(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    owned_request(db, request_id, user)
    return db.scalars(select(AuditLog).where(AuditLog.resource_type == "request",
        AuditLog.resource_id == request_id).order_by(AuditLog.id)).all()

@app.post("/requests/{request_id}/cancel", response_model=RequestOut, tags=["Requests"])
def cancel_request(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(HelpdeskRequest).where(
        HelpdeskRequest.id == request_id
    ).with_for_update())
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Request not found")
    cancellable = row.status == "AWAITING_APPROVAL"
    if row.intent == "SOFTWARE_INSTALL" and row.status == "PENDING":
        if not row.task or row.task.status != "PENDING":
            raise HTTPException(409, "Installation is already being processed")
        row.task.status = "CANCELLED"
        row.task.completed_at = now()
        cancellable = True
    elif row.intent == "PASSWORD_RESET" and row.status == "PENDING":
        cancellable = row.password_started_at is None
    elif row.intent == "PASSWORD_CHANGE" and row.status == "PENDING":
        cancellable = True
    if not cancellable:
        raise HTTPException(409, "Request can no longer be cancelled")
    row.status = "CANCELLED"
    row.message = "Request cancelled before execution."
    if row.access:
        row.access.status = "CANCELLED"
        row.access.decision_reason = row.message
    audit(db, user.id, "REQUEST_CANCELLED", "request", row.id, "CANCELLED")
    db.commit()
    db.refresh(row)
    return row

@app.post("/admin/requests/{request_id}/approval", response_model=RequestOut, tags=["Admin"])
def access_approval(request_id: int, payload: ApprovalIn, user=Depends(require_admin),
                    db: Session = Depends(get_db)):
    row = db.scalar(select(HelpdeskRequest).where(
        HelpdeskRequest.id == request_id
    ).with_for_update())
    if not row or row.intent != "ACCESS_REQUEST" or not row.access:
        raise HTTPException(404, "Access request not found")
    if row.status != "AWAITING_APPROVAL":
        raise HTTPException(409, "Access request is not awaiting approval")
    if not payload.approved:
        row.status = row.access.status = "REJECTED"
        row.message = row.access.decision_reason = "Project Admin access was rejected by an administrator."
        audit(db, user.id, "ACCESS_APPROVAL_REJECTED", "request", row.id, "REJECTED")
        db.commit()
        db.refresh(row)
        return row
    policy = db.get(ApplicationPolicy, row.access.application)
    request_user = db.get(User, row.user_id)
    if (not policy or not policy.enabled or not request_user or
            request_user.email.lower() != config.JIRA_TEST_ACCOUNT_EMAIL or
            (policy.required_role != "employee" and request_user.role != "admin")):
        row.status = row.access.status = "REJECTED"
        row.message = row.access.decision_reason = "Jira access policy or test-account eligibility changed."
        audit(db, user.id, "ACCESS_APPROVAL_REJECTED", "request", row.id, "REJECTED",
              "Eligibility or policy recheck failed")
        db.commit()
        db.refresh(row)
        return row
    audit(db, user.id, "ACCESS_APPROVED", "request", row.id, "APPROVED",
          row.access.requested_role)
    db.commit()
    return provision_access(db, row, row.access, user.id)

def _owned_password_request(request_id, user, db, intent):
    row = db.scalar(select(HelpdeskRequest).where(
        HelpdeskRequest.id == request_id
    ).with_for_update())
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Request not found")
    if row.intent != intent:
        raise HTTPException(409, "Not the requested password workflow")
    if not config.ENTRA_TEST_ACCOUNT_UPN or user.email.lower() != config.ENTRA_TEST_ACCOUNT_UPN:
        raise HTTPException(403, "Only the configured Entra test account can use this workflow")
    if row.status != "PENDING":
        raise HTTPException(409, "Password workflow is not pending")
    return row

@app.post("/requests/{request_id}/password/reset/start", response_model=PasswordActionOut, tags=["Requests"],
          description="Starts Microsoft's hosted SSPR flow. AutoDeskAI never receives the new password.")
def password_reset_start(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = _owned_password_request(request_id, user, db, "PASSWORD_RESET")
    try:
        redirect_url = get_password_service().reset_url()
    except PasswordIntegrationError as error:
        audit(db, user.id, "PASSWORD_RESET_START_FAILED", "request", row.id, "FAILED",
              "Entra SSPR configuration unavailable")
        db.commit()
        raise HTTPException(503, str(error)) from None
    if row.password_started_at:
        return PasswordActionOut(request=row, redirect_url=redirect_url)
    row.password_started_at = now()
    row.message = "Complete Microsoft's recovery/MFA flow, then return here to verify the reset."
    audit(db, user.id, "PASSWORD_RESET_STARTED", "request", row.id, "PENDING", "Microsoft-hosted SSPR")
    db.commit()
    db.refresh(row)
    return PasswordActionOut(request=row, redirect_url=redirect_url)

@app.post("/requests/{request_id}/password/reset/verify", response_model=PasswordActionOut,
          tags=["Requests"], description="Verifies SSPR completion from Entra's password-change timestamp.")
def password_reset_verify(request_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = _owned_password_request(request_id, user, db, "PASSWORD_RESET")
    if not row.password_started_at:
        raise HTTPException(409, "Start the Microsoft-hosted recovery flow first")
    try:
        verified = get_password_service().verify_reset(row.password_started_at)
    except PasswordIntegrationError as error:
        audit(db, user.id, "PASSWORD_RESET_VERIFICATION_FAILED", "request", row.id, "FAILED",
              "Entra verification unavailable")
        db.commit()
        raise HTTPException(503, str(error)) from None
    if verified:
        row.status = "COMPLETED"
        row.message = "Microsoft Entra confirmed the password reset."
        audit(db, user.id, "PASSWORD_RESET_COMPLETED", "request", row.id, "COMPLETED",
              "Entra password-change timestamp verified")
    else:
        row.message = "Reset not yet verified. Complete the Microsoft flow, then retry verification."
        audit(db, user.id, "PASSWORD_RESET_VERIFICATION_PENDING", "request", row.id, "PENDING")
    db.commit()
    db.refresh(row)
    return PasswordActionOut(request=row, verified=verified)

@app.post("/requests/{request_id}/password/change", response_model=RequestOut, tags=["Requests"],
          description="Changes the dedicated Entra test account password using delegated Graph access.")
def password_change(request_id: int, payload: PasswordChangeIn,
                    entra_access_token: str = Header(alias="X-Entra-Access-Token", min_length=1),
                    user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = _owned_password_request(request_id, user, db, "PASSWORD_CHANGE")
    current_password = payload.current_password.get_secret_value()
    new_password = payload.new_password.get_secret_value()
    if current_password == new_password:
        raise HTTPException(422, "The new password must differ from the current password")
    row.status = "PROCESSING"
    row.message = "Microsoft Entra is processing the password change."
    audit(db, user.id, "PASSWORD_CHANGE_STARTED", "request", row.id, "PROCESSING")
    db.commit()
    try:
        get_password_service().change_password(entra_access_token, current_password, new_password)
    except PermissionError as error:
        row.status = "FAILED"
        row.message = "Microsoft Entra did not authorize the password change."
        audit(db, user.id, "PASSWORD_CHANGE_REJECTED", "request", row.id, "FAILED",
              "Entra identity did not match the configured test account")
        db.commit()
        raise HTTPException(403, str(error)) from None
    except PasswordIntegrationError as error:
        row.status = "FAILED"
        row.message = "Microsoft Entra could not confirm the password change."
        audit(db, user.id, "PASSWORD_CHANGE_FAILED", "request", row.id, "FAILED",
              "Entra rejected the password change or verification failed")
        db.commit()
        raise HTTPException(502, str(error)) from None
    row.status = "COMPLETED"
    row.message = "Microsoft Entra confirmed the password change."
    audit(db, user.id, "PASSWORD_CHANGE_COMPLETED", "request", row.id, "COMPLETED",
          "Delegated Entra Graph response confirmed")
    db.commit()
    db.refresh(row)
    return row

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
    rows = db.scalars(select(SoftwareTask).where(SoftwareTask.device_id == device.id,
        SoftwareTask.status == "PENDING").with_for_update(skip_locked=True).limit(10)).all()
    dispatched = []
    for task in rows:
        policy = db.get(SoftwarePolicy, task.software)
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
    result = (
        f"Simulated installation completed; no OS changes made."
        if payload.success and payload.simulated
        else f"{SOFTWARE[task.software]['display_name']} installation verified on endpoint."
        if payload.success
        else "Simulated installation failed; no OS changes made."
        if payload.simulated
        else "Endpoint installation failed or could not be verified."
    )
    if task.status in ("COMPLETED", "FAILED"):
        if task.status == status and task.result == result:
            return task
        raise HTTPException(409, "Task already finalized")
    if task.status == "VERIFYING":
        if task.result != result:
            raise HTTPException(409, "Conflicting endpoint result during verification")
    elif task.status == "PROCESSING":
        task.status = task.request.status = "VERIFYING"
        task.result = result
        task.request.message = "Endpoint result received; verifying the installation report."
        audit(db, task.request.user_id, "SOFTWARE_INSTALL_VERIFYING", "request",
              task.request_id, "VERIFYING", "Authenticated owning device report")
        db.commit()
    else:
        raise HTTPException(409, "Task was not dispatched")
    task.status = task.request.status = status
    task.result = task.request.message = result
    task.completed_at = now()
    audit(db, task.request.user_id, "SOFTWARE_INSTALL_" + status, "request", task.request_id,
          status, "Simulation" if payload.simulated else "Endpoint result")
    db.commit()
    return task

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
            "applications": [{"key": p.key, "enabled": p.enabled, "required_role": p.required_role,
                              "roles": [{"key": key, "display_name": role["display_name"]}
                                        for key, role in ACCESS_ROLES.items()]}
                        for p in db.scalars(select(ApplicationPolicy)) if p.key in APPLICATIONS]}

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
    if key not in APPLICATIONS:
        raise HTTPException(400, "Unknown application")
    row = db.get(ApplicationPolicy, key)
    row.enabled, row.required_role = payload.enabled, payload.required_role
    audit(db, user.id, "APPLICATION_POLICY_UPDATED", "policy", None, "COMPLETED", key)
    db.commit()
    return {"key": key, "enabled": row.enabled, "required_role": row.required_role}
