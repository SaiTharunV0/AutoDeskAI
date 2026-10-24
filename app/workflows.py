from datetime import timedelta
import json
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.models import (HelpdeskRequest, SoftwareTask, AccessRequest, AuditLog, Device, UserNotification,
                        SoftwarePolicy, ApplicationPolicy, now)
from app.catalog import SOFTWARE, APPLICATIONS, EXAMPLE_APPLICATIONS, software_key
from app.schemas import ChatOut
from schema import AgentResponse, Intent
from agent import process_request, safe_message, UnsafeRequest
from app.chat_limits import check_chat_rate, record_out_of_scope, reset_out_of_scope
import config

def audit(db, user_id, action, resource_type, resource_id, status, details=""):
    db.add(AuditLog(user_id=user_id, action=action, resource_type=resource_type,
                    resource_id=resource_id, status=status, details=details))

def close_rejected_request(db, request, source='AUTODESKAI'):
    """Keep the decision in history without asking employees to confirm a denial."""
    if request.status != 'REJECTED':
        return
    request.status = 'CLOSED'
    request.resolved = None
    request.resolution_reporter = None
    request.rejection_source = source
    request.message = request.message[:440] + ' I have closed this ticket; no confirmation is needed.'
    audit(db, request.user_id, 'REJECTED_TICKET_CLOSED', 'request', request.id,
          'CLOSED', 'Rejected automatically; no employee resolution reported')


def close_legacy_rejections(db):
    for request in db.scalars(select(HelpdeskRequest).where(HelpdeskRequest.status == 'REJECTED')):
        source = 'ADMIN' if request.access and request.access.approver_id else 'AUTODESKAI'
        close_rejected_request(db, request, source)
    db.commit()


def reject_pending_software_requests(db):
    """Stop unfinished simulated installations while the workflow is unavailable."""
    rows = db.scalars(select(HelpdeskRequest).options(selectinload(HelpdeskRequest.task)).where(
        HelpdeskRequest.intent == 'SOFTWARE_INSTALL',
        HelpdeskRequest.status.in_(('PENDING', 'PROCESSING', 'RETRY_ACTION_REQUIRED')))).all()
    for request in rows:
        if request.task and request.task.status in ('PENDING', 'PROCESSING'):
            request.task.status = 'REJECTED'
            request.task.result = 'Software installation is not implemented yet.'
        request.status = 'REJECTED'
        request.message = "Software installation isn't implemented yet, so I can't install software for you right now."
        audit(db, request.user_id, 'SOFTWARE_INSTALL_REJECTED', 'request', request.id,
              'REJECTED', 'Unfinished simulation closed after workflow disabled')
        close_rejected_request(db, request)
    if rows:
        db.commit()


def owned_request(db, request_id, user):
    request = db.get(HelpdeskRequest, request_id)
    if not request or (request.user_id != user.id and
                       (user.role != "admin" or request.intent in ("PASSWORD_CHANGE", "PASSWORD_RESET"))):
        raise HTTPException(404, "Request not found")
    return request

def expire_tasks(db):
    cutoff = now() - timedelta(seconds=config.TASK_TIMEOUT_SECONDS)
    tasks = db.scalars(select(SoftwareTask).options(selectinload(SoftwareTask.request)).where(
        SoftwareTask.status.in_(["PENDING", "PROCESSING"]), SoftwareTask.created_at < cutoff
    ).with_for_update(skip_locked=True)).all()
    for task in tasks:
        task.status = task.request.status = "FAILED"
        task.result = task.request.message = "Endpoint task timed out; completion was not confirmed."
        task.completed_at = now()
        audit(db, task.request.user_id, "SOFTWARE_INSTALL_FAILED", "request", task.request_id, "FAILED", "Task timeout")
    if tasks:
        db.commit()

def correct_legacy_password_requests(db):
    rows = db.scalars(select(HelpdeskRequest).where(
        HelpdeskRequest.intent.in_(("PASSWORD_CHANGE", "PASSWORD_RESET")),
        HelpdeskRequest.status.in_(("PENDING", "COMPLETED")),
        HelpdeskRequest.message.in_((
            "Confirm the simulated password workflow. No identity-provider password will change.",
            "Simulated password operation completed. Your actual login password is unchanged."
        )))).all()
    for row in rows:
        row.status = "AWAITING_USER_ACTION"
        row.message = "Legacy simulation did not change a Microsoft password. Continue at Microsoft; completion cannot be verified here."
        audit(db, row.user_id, "PASSWORD_LEGACY_STATUS_CORRECTED", "request", row.id,
              row.status, "Prior simulation was not a provider result")
    if rows:
        db.commit()

def create_workflow(db, user, payload):
    existing = db.scalar(select(HelpdeskRequest).where(HelpdeskRequest.user_id == user.id,
                           HelpdeskRequest.idempotency_key == payload.idempotency_key))
    if existing:
        return existing
    open_ticket = db.scalar(select(HelpdeskRequest).where(
        HelpdeskRequest.user_id == user.id, HelpdeskRequest.status != 'CLOSED'
    ).order_by(HelpdeskRequest.id).limit(1))
    continuing_clarification = (open_ticket and open_ticket.status == 'NEEDS_CLARIFICATION'
                                and payload.previous_request_id == open_ticket.id)
    if open_ticket and not continuing_clarification:
        raise HTTPException(409, 'Please finish your current request and confirm whether it worked before starting another.')
    check_chat_rate(db, user.id, payload.message)
    try:
        safe = safe_message(payload.message)
    except UnsafeRequest:
        record_out_of_scope(db, user.id)
        audit(db, user.id, 'REQUEST_REJECTED', 'service', None, 'REJECTED', 'Unsupported action or credential-like input')
        db.commit()
        raise
    if "password" in safe.split():
        recent = db.scalar(select(func.count(HelpdeskRequest.id)).where(
            HelpdeskRequest.user_id == user.id,
            HelpdeskRequest.intent.in_(("PASSWORD_CHANGE", "PASSWORD_RESET")),
            HelpdeskRequest.created_at >= now() - timedelta(hours=1)))
        if recent >= 5:
            audit(db, user.id, "PASSWORD_REQUEST_RATE_LIMITED", "service", None, "REJECTED")
            db.commit()
            raise HTTPException(429, "Too many password requests. Try again later.")
    previous = None
    clarification_application = None
    if payload.previous_request_id:
        prior = owned_request(db, payload.previous_request_id, user)
        if prior.user_id != user.id or prior.status != "NEEDS_CLARIFICATION":
            raise HTTPException(409, "Previous request is not awaiting clarification")
        previous = AgentResponse(intent=Intent.CLARIFICATION, message=prior.message)
        if 'which application' in prior.message.lower():
            answer = ' '.join(payload.message.lower().strip().split()).strip(' .?!')
            policies = db.scalars(select(ApplicationPolicy)).all()
            names = {key: {display.lower()} for key, display in
                     {**APPLICATIONS, **EXAMPLE_APPLICATIONS}.items()}
            for policy in policies:
                names.setdefault(policy.key, set()).update((policy.key,
                    policy.display_name.lower().removesuffix(' (example)')))
            clarification_application = next((key for key, aliases in names.items()
                if any(answer in (alias, f'access to {alias}', f'i need access to {alias}')
                       for alias in aliases)), None)
            if not clarification_application:
                return ChatOut(message=f"Let's finish your current access request first. {prior.message}")
            safe = f'access {clarification_application}'
    # All work so far is read-only. Return the pooled connection while the model
    # runs; a slow model call should not monopolize a PostgreSQL connection.
    db.commit()
    try:
        result = (AgentResponse(intent=Intent.ACCESS_REQUEST, application=clarification_application,
                                message='Access request identified.') if clarification_application
                  else process_request(payload.message, previous))
    except RuntimeError:
        audit(db, user.id, "AI_REQUEST_FAILED", "service", None, "FAILED", "AI unavailable or malformed output")
        db.commit()
        raise
    if result.intent == Intent.UNSUPPORTED:
        record_out_of_scope(db, user.id)
        return ChatOut(message=result.message)
    reset_out_of_scope(db, user.id)
    if result.intent == Intent.REQUEST_STATUS:
        rows = db.scalars(select(HelpdeskRequest).where(HelpdeskRequest.user_id == user.id)
                          .order_by(HelpdeskRequest.id.desc()).limit(10)).all()
        if not rows:
            return ChatOut(message="You don’t have any requests yet. I can help with organization password change/reset and application access. Software installation is not implemented yet.")
        lines = [f"#{row.id} · {row.intent.replace('_', ' ').title()} · {row.status.replace('_', ' ').title()}"
                 for row in rows]
        return ChatOut(message="Your 10 most recent request statuses:\n" + "\n".join(lines))
    if result.intent == Intent.CHAT:
        return ChatOut(message=result.message)
    if previous and result.intent == Intent.CLARIFICATION:
        return ChatOut(message=f"Let's finish your current request first. {prior.message}")
    if clarification_application:
        request = prior
        request.intent = result.intent.value
        request.original_message = safe[:200]
        audit(db, user.id, 'CLARIFICATION_ANSWERED', 'request', request.id,
              request.status, 'Application identified')
    else:
        request = HelpdeskRequest(user_id=user.id, intent=result.intent.value,
                                  original_message=safe[:200], idempotency_key=payload.idempotency_key)
        db.add(request)
        db.flush()
    if previous and not clarification_application:
        prior.status = 'CLOSED'
        prior.message = (prior.message + f' Clarification received; follow-up ticket #{request.id} opened.')[:500]
        audit(db, user.id, 'CLARIFICATION_FOLLOWUP_CREATED', 'request', prior.id, 'CLOSED',
              f'Follow-up ticket {request.id}')
    if result.intent in (Intent.PASSWORD_CHANGE, Intent.PASSWORD_RESET):
        request.status = "AWAITING_USER_ACTION"
        request.message = ("Continue at Microsoft My Account to change your organization password. "
                           if result.intent == Intent.PASSWORD_CHANGE else
                           "Continue at Microsoft Self-Service Password Reset to recover your organization account. ") + \
                          "When you return, let me know whether it worked. I can't check the result at Microsoft."
        audit(db, user.id, result.intent.value + "_REQUESTED", "request", request.id, request.status)
    elif result.intent == Intent.SOFTWARE_INSTALL:
        request.status = 'REJECTED'
        request.message = "Software installation isn't implemented yet, so I can't install software for you right now."
        audit(db, user.id, 'SOFTWARE_INSTALL_REJECTED', 'request', request.id,
              request.status, 'Installation workflow unavailable; no task created')
    elif result.intent == Intent.ACCESS_REQUEST:
        key = (result.application or "").strip().lower()
        policy = db.get(ApplicationPolicy, key) if key in safe.split() else None
        if not policy or not policy.enabled or (policy.required_role == 'admin' and user.role != 'admin'):
            request.status, request.message = 'REJECTED', "This application is not authorised for access through AutoDeskAI, so I can't grant access to it."
            audit(db, user.id, 'ACCESS_REJECTED', 'request', request.id, request.status)
            db.add(UserNotification(user_id=user.id, request_id=request.id,
                kind='ACCESS_REJECTED', title='Application access rejected',
                message='This application is not authorised for access through AutoDeskAI. Your request was rejected and closed.'))
        else:
            from app.access import submit_access
            role = json.loads(policy.requestable_roles_json)[0]
            submit_access(db, user, key, role, '', policy.default_duration_days,
                          payload.idempotency_key, existing_request=request)
    elif result.intent == Intent.CLARIFICATION:
        request.status = "NEEDS_CLARIFICATION"
        # Never relay arbitrary model prose or credentials back into history.
        if result.message == "Please request one workflow at a time.":
            request.message = result.message
        elif "access" in safe or (previous and "application" in previous.message):
            request.message = "Which application do you need access to? I can help you request Tableau access."
        elif any(word in safe.split() for word in ("install", "installed", "setup", "download")):
            request.message = "Which software would you like to install? I can help with Visual Studio Code."
        else:
            request.message = "Please specify password change/reset, software installation, or application access."
        audit(db, user.id, "CLARIFICATION_REQUESTED", "request", request.id, request.status)
    elif result.intent == Intent.UNSUPPORTED:
        request.status = "REJECTED"
        request.message = "This request is not supported."
        audit(db, user.id, "UNSUPPORTED_REQUEST", "request", request.id, request.status)
    close_rejected_request(db, request)
    db.commit()
    return request
