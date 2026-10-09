from contextlib import asynccontextmanager
import hashlib
import secrets
from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session
from app.database import Base, engine, get_db, SessionLocal
from app.models import *
from app.schemas import *
from app.catalog import SOFTWARE, APPLICATIONS
from app.workflows import audit, owned_request, create_workflow, expire_tasks
from auth import (get_current_user, require_admin, hash_password, verify_password,
                  create_access_token, validate_config, bearer)
from agent import UnsafeRequest
import config

@asynccontextmanager
async def lifespan(app):
    validate_config()
    Base.metadata.create_all(engine)  # Additive: existing users schema stays intact.
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
    description="Authenticated, policy-controlled IT workflows. Password and access providers are simulated.")

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

@app.get("/users", response_model=list[UserOut], tags=["Admin"])
@app.get("/admin/users", response_model=list[UserOut], tags=["Admin"])
def users(user=Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.id).limit(500)).all()

@app.post('/users', response_model=UserOut, status_code=201, tags=['Admin'],
          description='Legacy user creation route, now administrator-only and requires a password.')
def admin_create_user(payload: Register, user=Depends(require_admin), db: Session = Depends(get_db)):
    return register(payload, db)

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

@app.post("/requests/{request_id}/password/confirm", response_model=RequestOut, tags=["Requests"],
          description="Confirms a simulated identity operation for the authenticated owner. Does not change a real password.")
def password_confirm(request_id: int, payload: PasswordConfirm, user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    row = db.scalar(select(HelpdeskRequest).where(HelpdeskRequest.id == request_id).with_for_update())
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Request not found")
    if row.intent not in ("PASSWORD_RESET", "PASSWORD_CHANGE"):
        raise HTTPException(409, "Not a password workflow")
    if row.status == "COMPLETED":
        return row
    if row.status != "PENDING":
        raise HTTPException(409, "Workflow is not pending")
    row.status = "COMPLETED"
    row.message = "Simulated password operation completed. Your actual login password is unchanged."
    audit(db, user.id, row.intent + "_COMPLETED", "request", row.id, "COMPLETED", "Simulated identity provider")
    db.commit()
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
    result = ("Simulated installation completed; no OS changes made." if payload.success else "Endpoint installation failed.")
    if not payload.simulated:
        raise HTTPException(400, "This prototype accepts simulation results only")
    if task.status in ("COMPLETED", "FAILED"):
        if task.status == status and task.result == result:
            return task
        raise HTTPException(409, "Task already finalized")
    if task.status != "PROCESSING":
        raise HTTPException(409, "Task was not dispatched")
    task.status = task.request.status = status
    task.result = task.request.message = result
    task.completed_at = now()
    audit(db, task.request.user_id, "SOFTWARE_INSTALL_" + status, "request", task.request_id, status, "Simulation")
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
            "applications": [{"key": p.key, "enabled": p.enabled, "required_role": p.required_role}
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
