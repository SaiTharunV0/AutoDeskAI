from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from app.models import (HelpdeskRequest, SoftwareTask, AccessRequest, AuditLog, Device,
                        SoftwarePolicy, ApplicationPolicy, now)
from app.catalog import SOFTWARE, APPLICATIONS, software_key
from schema import AgentResponse, Intent
from agent import process_request, safe_message, UnsafeRequest
import config

def audit(db, user_id, action, resource_type, resource_id, status, details=""):
    db.add(AuditLog(user_id=user_id, action=action, resource_type=resource_type,
                    resource_id=resource_id, status=status, details=details))

def owned_request(db, request_id, user):
    request = db.get(HelpdeskRequest, request_id)
    if not request or (user.role != "admin" and request.user_id != user.id):
        raise HTTPException(404, "Request not found")
    return request

def expire_tasks(db):
    cutoff = now() - timedelta(seconds=config.TASK_TIMEOUT_SECONDS)
    tasks = db.scalars(select(SoftwareTask).where(
        SoftwareTask.status.in_(["PENDING", "PROCESSING"]), SoftwareTask.created_at < cutoff
    ).with_for_update()).all()
    for task in tasks:
        task.status = task.request.status = "FAILED"
        task.result = task.request.message = "Endpoint task timed out; completion was not confirmed."
        task.completed_at = now()
        audit(db, task.request.user_id, "SOFTWARE_INSTALL_FAILED", "request", task.request_id, "FAILED", "Task timeout")
    db.commit()

def create_workflow(db, user, payload):
    existing = db.scalar(select(HelpdeskRequest).where(HelpdeskRequest.user_id == user.id,
                           HelpdeskRequest.idempotency_key == payload.idempotency_key))
    if existing:
        return existing
    try:
        safe = safe_message(payload.message)
    except UnsafeRequest:
        audit(db, user.id, 'REQUEST_REJECTED', 'service', None, 'REJECTED', 'Unsupported action or credential-like input')
        db.commit()
        raise
    previous = None
    if payload.previous_request_id:
        prior = owned_request(db, payload.previous_request_id, user)
        if prior.user_id != user.id or prior.status != "NEEDS_CLARIFICATION":
            raise HTTPException(409, "Previous request is not awaiting clarification")
        previous = AgentResponse(intent=Intent.CLARIFICATION, message=prior.message)
    try:
        result = process_request(payload.message, previous)
    except RuntimeError:
        audit(db, user.id, "AI_REQUEST_FAILED", "service", None, "FAILED", "AI unavailable or malformed output")
        db.commit()
        raise
    request = HelpdeskRequest(user_id=user.id, intent=result.intent.value,
                              idempotency_key=payload.idempotency_key)
    db.add(request)
    db.flush()
    if result.intent in (Intent.PASSWORD_CHANGE, Intent.PASSWORD_RESET):
        request.status = "PENDING"
        request.message = "Confirm the simulated password workflow. No identity-provider password will change."
        audit(db, user.id, result.intent.value + "_REQUESTED", "request", request.id, "PENDING")
    elif result.intent == Intent.SOFTWARE_INSTALL:
        key = software_key(result.software)
        policy = db.get(SoftwarePolicy, key) if key else None
        # Even a fabricated model response cannot select a target absent from input.
        if not key or key not in safe.split() or not policy or not policy.enabled:
            request.status, request.message = "REJECTED", "Software is not approved."
        else:
            device = db.get(Device, payload.device_id) if payload.device_id else None
            if not device or device.owner_user_id != user.id or device.status != "ACTIVE":
                request.status, request.message = "REJECTED", "Select an active device registered to your account."
            elif device.last_seen < now() - timedelta(seconds=config.DEVICE_OFFLINE_SECONDS):
                request.status, request.message = "FAILED", "Device is offline. Start its agent and retry."
            else:
                request.status, request.message = "PENDING", "Approved installation queued for your endpoint agent."
                db.add(SoftwareTask(request_id=request.id, device_id=device.id, software=key))
        audit(db, user.id, "SOFTWARE_INSTALL_REQUESTED", "request", request.id, request.status)
    elif result.intent == Intent.ACCESS_REQUEST:
        key = (result.application or "").strip().lower()
        policy = db.get(ApplicationPolicy, key) if key in APPLICATIONS else None
        allowed = bool(key in safe.split() and policy and policy.enabled and
                       (policy.required_role == "employee" or user.role == "admin"))
        request.status = "COMPLETED" if allowed else "REJECTED"
        request.message = ("Access approved in the demo policy service; no external application was provisioned."
                           if allowed else "Application access rejected by backend policy.")
        db.add(AccessRequest(request_id=request.id, user_id=user.id,
            application=key if key in APPLICATIONS else "unknown", status=request.status,
            decision_reason=request.message))
        audit(db, user.id, "ACCESS_REQUESTED", "request", request.id, "PENDING")
        audit(db, user.id, "ACCESS_GRANTED" if allowed else "ACCESS_REJECTED", "request", request.id, request.status)
    elif result.intent == Intent.CLARIFICATION:
        request.status = "NEEDS_CLARIFICATION"
        # Never relay arbitrary model prose or credentials back into history.
        if result.message == "Please request one workflow at a time.":
            request.message = result.message
        elif "access" in safe or (previous and "application" in previous.message):
            request.message = "Which application do you need access to? Supported: Tableau."
        elif any(word in safe.split() for word in ("install", "installed", "setup", "download")):
            request.message = "Which software would you like to install? Supported: Visual Studio Code."
        else:
            request.message = "Please specify password change/reset, software installation, or application access."
        audit(db, user.id, "CLARIFICATION_REQUESTED", "request", request.id, request.status)
    else:
        request.status = "COMPLETED"
        request.message = "I can help with password change/reset, approved software installation, and application access."
        audit(db, user.id, "CHAT", "request", request.id, request.status)
    db.commit()
    db.refresh(request)
    return request
