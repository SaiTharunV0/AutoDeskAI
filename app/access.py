"""Deterministic application access decisions. No provider grants real access."""
import json
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models import AccessRequest, ApplicationPolicy, HelpdeskRequest, AccessPolicyRevision, User, now
from app.workflows import audit
from app.provisioning import provision

OPEN_STATES = ('AWAITING_ADMIN', 'APPROVED_PROVISIONING_REQUIRED')

def attempt_provision(db, policy, access):
    access.provision_attempts = (access.provision_attempts or 0) + 1
    access.last_provision_attempt_at = now()
    try:
        result = provision(policy, access)
        status = result.status if result.status in ('SIMULATED', 'NOT_CONFIGURED', 'FAILED', 'TIMEOUT') else 'FAILED'
    except TimeoutError:
        status = 'TIMEOUT'
    except Exception:
        status = 'FAILED'
    access.provisioning_status = status
    audit(db, None, 'ACCESS_PROVISIONING_ATTEMPT', 'request', access.request_id,
          status, f'Provider {policy.provider_type}; no verified grant')

def catalog_view(row):
    return {
        'key': row.key, 'display_name': row.display_name or row.key.title(),
        'description': row.description, 'enabled': row.enabled, 'required_role': row.required_role,
        'requestable_roles': json.loads(row.requestable_roles_json),
        'allowed_groups': json.loads(row.allowed_groups_json),
        'default_duration_days': row.default_duration_days, 'max_duration_days': row.max_duration_days,
        'approval_mode': row.approval_mode, 'conditions': json.loads(row.conditions_json),
        'fallback': row.fallback, 'human_roles': json.loads(row.human_roles_json),
        'risk': row.risk, 'provider_type': row.provider_type, 'config_ref': row.config_ref,
        'auto_allowed': row.auto_allowed, 'version': row.version,
    }

def save_policy(db, row, payload, actor_id):
    values = payload.model_dump(exclude={'key'})
    for name, value in values.items():
        if name in ('requestable_roles', 'allowed_groups', 'conditions', 'human_roles'):
            setattr(row, name + '_json', json.dumps(value, sort_keys=True))
        else:
            setattr(row, name, value)
    row.version = (row.version or 0) + 1 if row.version else 1
    db.add(row)
    db.flush()
    db.add(AccessPolicyRevision(application_key=row.key, version=row.version,
        actor_id=actor_id, snapshot_json=json.dumps(catalog_view(row), sort_keys=True)))
    audit(db, actor_id, 'ACCESS_POLICY_UPDATED', 'application', None, 'COMPLETED',
          f'{row.key} version {row.version}')
    db.commit()
    return catalog_view(row)

def evaluate(row, user, requested_role, justification, duration_days):
    conditions = json.loads(row.conditions_json)
    checks = {}
    checks['enabled'] = row.enabled
    checks['requestable_role'] = requested_role in json.loads(row.requestable_roles_json)
    checks['duration'] = 1 <= duration_days <= row.max_duration_days
    checks['account_role'] = row.required_role == 'employee' or user.role == 'admin'
    checks['automatic_eligible'] = row.auto_allowed and requested_role not in json.loads(row.human_roles_json) and row.risk != 'HIGH'
    checks['allowed_groups'] = None if json.loads(row.allowed_groups_json) else True
    if 'min_justification_length' in conditions:
        checks['justification'] = len(justification.strip()) >= conditions['min_justification_length']
    if 'max_duration_days' in conditions:
        checks['condition_duration'] = duration_days <= conditions['max_duration_days']
    if conditions.get('require_verified_mfa'):
        checks['verified_mfa'] = None  # No trusted MFA claim in the local JWT.
    if conditions.get('required_groups'):
        checks['required_groups'] = None  # No trusted directory group source.
    if conditions.get('employment_status'):
        checks['employment_status'] = None  # No verified HR source.
    human_required = row.approval_mode == 'ADMIN_ONLY' or row.risk == 'HIGH' or requested_role in json.loads(row.human_roles_json)
    approved = (not human_required and row.approval_mode in ('AUTOMATIC', 'CONDITIONAL')
                and all(value is True for value in checks.values()))
    decision = ('AUTOMATIC_APPROVAL' if approved else
                'REQUIRE_ADMIN_APPROVAL' if human_required or row.fallback == 'REQUIRE_ADMIN_APPROVAL' else 'DENY')
    return {'policy_id': row.key, 'policy_version': row.version, 'conditions': checks,
            'mode': row.approval_mode, 'decision': decision, 'fallback': row.fallback,
            'evaluated_at': now().isoformat() + 'Z', 'actor': 'POLICY_EVALUATOR'}

def submit_access(db, user, application, requested_role, justification, duration_days, idempotency_key,
                  existing_request=None):
    # Serialize submissions for one requester in PostgreSQL; the request key also
    # protects retries when the first response is lost.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = None if existing_request else db.scalar(select(HelpdeskRequest).where(HelpdeskRequest.user_id == user.id,
        HelpdeskRequest.idempotency_key == idempotency_key))
    if existing:
        if not existing.access:
            raise HTTPException(409, 'Idempotency key belongs to another workflow')
        if (existing.access.application != application.lower().strip()
                or existing.access.requested_role != requested_role
                or existing.access.justification != justification.strip()
                or existing.access.duration_days != duration_days):
            raise HTTPException(409, 'Idempotency key was reused with different request details')
        return existing.access
    if not existing_request:
        open_ticket = db.scalar(select(HelpdeskRequest).where(
            HelpdeskRequest.user_id == user.id, HelpdeskRequest.status != 'CLOSED'
        ).order_by(HelpdeskRequest.id).limit(1))
        if open_ticket:
            raise HTTPException(409, 'Please finish your current request and confirm whether it worked before starting another.')
    row = db.get(ApplicationPolicy, application.lower().strip())
    if not row or not row.enabled:
        raise HTTPException(404, 'Application is unavailable')
    if row.required_role == 'admin' and user.role != 'admin':
        raise HTTPException(403, 'Application is restricted to administrators')
    if requested_role not in json.loads(row.requestable_roles_json):
        raise HTTPException(422, 'Role is not requestable')
    if duration_days > row.max_duration_days:
        raise HTTPException(422, 'Duration exceeds the allowed maximum')
    duplicate = db.scalar(select(AccessRequest).where(AccessRequest.user_id == user.id,
        AccessRequest.application == row.key, AccessRequest.requested_role == requested_role,
        AccessRequest.status.in_(OPEN_STATES)))
    if duplicate:
        raise HTTPException(409, 'An active request for this application and role already exists')
    evaluation = evaluate(row, user, requested_role, justification, duration_days)
    decision = evaluation['decision']
    status = ('APPROVED_PROVISIONING_REQUIRED' if decision == 'AUTOMATIC_APPROVAL' else
              'AWAITING_ADMIN' if decision == 'REQUIRE_ADMIN_APPROVAL' else 'REJECTED')
    reason = ('Your access request is approved. Access still needs to be set up before you can use the application.'
              if decision == 'AUTOMATIC_APPROVAL' else
              'I’ve sent your request to an administrator for review. I’ll update you when they decide.' if status == 'AWAITING_ADMIN' else
              'This access request is not authorised under your organisation’s policy.')
    request = existing_request or HelpdeskRequest(user_id=user.id, intent='ACCESS_REQUEST',
        original_message=f'Application access: {row.display_name or row.key}',
        idempotency_key=idempotency_key)
    request.status, request.message = status, reason
    db.add(request)
    db.flush()
    access = AccessRequest(request_id=request.id, user_id=user.id, application=row.key,
        requested_role=requested_role, justification=justification.strip(), duration_days=duration_days,
        status=status, approval_route='AUTOMATIC' if decision == 'AUTOMATIC_APPROVAL' else 'ADMIN',
        policy_version=row.version, evaluation_json=json.dumps(evaluation, sort_keys=True),
        decision_reason=reason, provisioning_status='NOT_STARTED',
        decision_at=now() if status != 'AWAITING_ADMIN' else None)
    db.add(access)
    if status == 'APPROVED_PROVISIONING_REQUIRED':
        attempt_provision(db, row, access)
    audit(db, user.id, 'ACCESS_REQUESTED', 'request', request.id, status, f'{row.key} / {requested_role}')
    audit(db, None, 'ACCESS_POLICY_EVALUATED', 'request', request.id, status,
          f'{row.key} v{row.version}: {decision}')
    from app.workflows import close_rejected_request
    close_rejected_request(db, request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(HelpdeskRequest).where(HelpdeskRequest.user_id == user.id,
            HelpdeskRequest.idempotency_key == idempotency_key))
        if existing and existing.access:
            return existing.access
        raise
    return access

def decide_access(db, access_id, admin, decision, reason):
    access = db.scalar(select(AccessRequest).where(AccessRequest.id == access_id).with_for_update())
    if not access:
        raise HTTPException(404, 'Access request not found')
    if access.user_id == admin.id:
        raise HTTPException(403, 'Administrators cannot approve their own requests')
    if access.status != 'AWAITING_ADMIN':
        raise HTTPException(409, 'This request has already been decided')
    status = 'APPROVED_PROVISIONING_REQUIRED' if decision == 'APPROVE' else 'REJECTED'
    policy = db.get(ApplicationPolicy, access.application)
    access.status = access.request.status = status
    access.approver_id = admin.id
    access.decision_at = now()
    access.decision_reason = reason.strip()
    access.request.message = (f'Approved by an administrator. Real provisioning is required.'
                              if decision == 'APPROVE' else f'Your administrator couldn’t approve this request. {reason.strip()}')[:500]
    if decision == 'APPROVE' and policy:
        attempt_provision(db, policy, access)
    else:
        access.provisioning_status = 'NOT_CONFIGURED' if decision == 'APPROVE' else 'NOT_STARTED'
    audit(db, admin.id, 'ACCESS_ADMIN_APPROVED' if decision == 'APPROVE' else 'ACCESS_ADMIN_REJECTED',
          'request', access.request_id, status, reason.strip())
    from app.workflows import close_rejected_request
    close_rejected_request(db, access.request, source='ADMIN')
    db.commit()
    return access

def retry_provisioning(db, access_id, admin):
    access = db.scalar(select(AccessRequest).where(AccessRequest.id == access_id).with_for_update())
    if not access:
        raise HTTPException(404, 'Access request not found')
    if access.status != 'APPROVED_PROVISIONING_REQUIRED' or access.provisioning_status not in ('FAILED', 'TIMEOUT'):
        raise HTTPException(409, 'Provisioning retry is not available')
    policy = db.get(ApplicationPolicy, access.application)
    if not policy:
        raise HTTPException(409, 'Application configuration is unavailable')
    attempt_provision(db, policy, access)
    audit(db, admin.id, 'ACCESS_PROVISIONING_RETRIED', 'request', access.request_id,
          access.provisioning_status, f'Attempt {access.provision_attempts}')
    db.commit()
    return access

def correct_legacy_access_requests(db):
    """Legacy demo approval was never an external grant."""
    rows = db.scalars(select(AccessRequest).where(AccessRequest.status == 'COMPLETED',
        AccessRequest.decision_reason.like('%no external application was provisioned%'))).all()
    for access in rows:
        access.status = access.request.status = 'APPROVED_PROVISIONING_REQUIRED'
        access.provisioning_status = 'SIMULATED'
        access.approval_route = 'LEGACY_DEMO'
        access.request.message = 'Legacy demo approval did not provision external access.'
        audit(db, None, 'ACCESS_LEGACY_STATUS_CORRECTED', 'request', access.request_id,
              access.status, 'Prior demo completion was not an external grant')
    if rows:
        db.commit()
