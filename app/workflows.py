from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from app.models import (HelpdeskRequest, SoftwareTask, AccessRequest, AuditLog, Device,
                        SoftwarePolicy, ApplicationPolicy, now)
from app.catalog import SOFTWARE, APPLICATIONS, ACCESS_ROLES, software_key
from schema import AgentResponse, Intent
from agent import process_request, safe_message, UnsafeRequest
from services.access import AccessIntegrationError, get_access_service
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
        SoftwareTask.status.in_(["PENDING", "PROCESSING", "VERIFYING"]),
        SoftwareTask.created_at < cutoff
    ).with_for_update()).all()
    for task in tasks:
        task.status = task.request.status = "FAILED"
        task.result = task.request.message = "Endpoint task timed out; completion was not confirmed."
        task.completed_at = now()
        audit(db, task.request.user_id, "SOFTWARE_INSTALL_FAILED", "request", task.request_id, "FAILED", "Task timeout")
    db.commit()


def provision_access(db, request, access, actor_id):
    request.status = access.status = "PROCESSING"
    request.message = access.decision_reason = "Jira is assigning the predefined project role."
    audit(db, actor_id, "ACCESS_PROVISIONING_STARTED", "request", request.id, "PROCESSING")
    db.commit()
    try:
        verified = get_access_service(access.application).provision(access.requested_role)
    except AccessIntegrationError:
        verified = False
    if verified:
        request.status = access.status = "COMPLETED"
        request.message = access.decision_reason = (
            f"{ACCESS_ROLES[access.requested_role]['display_name']} access was verified in Jira."
        )
        audit(db, actor_id, "ACCESS_GRANTED", "request", request.id, "COMPLETED", access.requested_role)
    else:
        request.status = access.status = "FAILED"
        request.message = access.decision_reason = (
            "Jira did not confirm the requested project role. Contact your administrator before retrying."
        )
        audit(db, actor_id, "ACCESS_PROVISIONING_FAILED", "request", request.id, "FAILED",
              "Provider error or role verification failed")
    db.commit()
    db.refresh(request)
    return request


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
                              original_message=safe[:200], idempotency_key=payload.idempotency_key)
    db.add(request)
    db.flush()
    if result.intent in (Intent.PASSWORD_CHANGE, Intent.PASSWORD_RESET):
        request.status = "PENDING"
        request.message = ("Continue to Microsoft Entra self-service password reset."
                           if result.intent == Intent.PASSWORD_RESET
                           else "Change your password using the dedicated Entra test account.")
        audit(db, user.id, result.intent.value + "_REQUESTED", "request", request.id, "PENDING")
    elif result.intent == Intent.SOFTWARE_INSTALL:
        key = software_key(result.software)
        policy = db.get(SoftwarePolicy, key) if key else None
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
        role_key = (result.access_role or "").strip().lower()
        policy = db.get(ApplicationPolicy, key) if key in APPLICATIONS else None
        valid_target = key in safe.split() and role_key in ACCESS_ROLES and role_key in safe.split()
        eligible = bool(policy and policy.enabled and
                        (policy.required_role == "employee" or user.role == "admin"))
        test_account = bool(config.JIRA_TEST_ACCOUNT_EMAIL and
                            user.email.lower() == config.JIRA_TEST_ACCOUNT_EMAIL)
        if not valid_target or not eligible or not test_account:
            request.status = "REJECTED"
            request.message = ("Only the configured Jira test account is eligible for access provisioning."
                               if not test_account else "Application or role access rejected by backend policy.")
            access_status = "REJECTED"
        elif role_key == "project_admin":
            request.status = access_status = "AWAITING_APPROVAL"
            request.message = "Project Admin access requires administrator approval."
        else:
            request.status, access_status = "PENDING", "PENDING"
            request.message = "Jira role request validated; provisioning will start now."
        decision = request.message
        access = AccessRequest(request_id=request.id, user_id=user.id,
            application=key if key in APPLICATIONS else "unknown",
            requested_role=role_key if role_key in ACCESS_ROLES else "jira_user",
            status=access_status, decision_reason=decision)
        db.add(access)
        audit(db, user.id, "ACCESS_REQUESTED", "request", request.id, request.status)
        if request.status == "REJECTED":
            audit(db, user.id, "ACCESS_REJECTED", "request", request.id, "REJECTED")
        elif request.status == "AWAITING_APPROVAL":
            audit(db, user.id, "ACCESS_AWAITING_APPROVAL", "request", request.id, request.status)
        else:
            db.flush()
            db.commit()
            db.refresh(access)
            return provision_access(db, request, access, user.id)
    elif result.intent == Intent.CLARIFICATION:
        request.status = "NEEDS_CLARIFICATION"
        if result.message == "Please request one workflow at a time.":
            request.message = result.message
        elif "jira role" in result.message.lower():
            request.message = "Which Jira role do you need: Jira User, Developer, or Project Admin?"
        elif "jira" in safe or "access" in safe:
            request.message = "Which Jira role do you need: Jira User, Developer, or Project Admin?"
        elif any(word in safe.split() for word in ("install", "installed", "setup", "download")):
            request.message = "Which software would you like to install? Supported: Visual Studio Code and Google Chrome."
        else:
            request.message = "Please specify password change/reset, software installation, or Jira access and a predefined role."
        audit(db, user.id, "CLARIFICATION_REQUESTED", "request", request.id, request.status)
    else:
        request.status = "COMPLETED"
        request.message = "I can help with Entra password change/reset, approved software installation, and Jira access."
        audit(db, user.id, "CHAT", "request", request.id, request.status)
    db.commit()
    db.refresh(request)
    return request
