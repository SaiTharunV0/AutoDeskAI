"""Run with ``python -m app.github_expiry`` from a scheduled service."""
from sqlalchemy import or_, select
from app.database import SessionLocal
from app.models import AccessRequest, AuditLog, now
from app.github_provider import GitHubOrganizationProvider


def expire_github_access(db, provider=None, *, at=None):
    at = at or now()
    provider = provider or GitHubOrganizationProvider()
    ids = db.scalars(select(AccessRequest.id).where(
        AccessRequest.application == 'github', AccessRequest.expires_at <= at,
        AccessRequest.provisioning_status.in_(('GRANTED', 'EXPIRED_REVOKE_FAILED')),
    ).order_by(AccessRequest.id).limit(100)).all()
    outcomes = []
    for access_id in ids:
        access = db.scalar(select(AccessRequest).where(AccessRequest.id == access_id).with_for_update())
        if not access or access.provisioning_status not in ('GRANTED', 'EXPIRED_REVOKE_FAILED'):
            db.rollback()
            continue
        # Membership is shared across requests. An unexpired grant must not be removed.
        other = db.scalar(select(AccessRequest.id).where(
            AccessRequest.id != access.id, AccessRequest.application == 'github',
            AccessRequest.github_user_id == access.github_user_id,
            AccessRequest.provider_resource == access.provider_resource,
            or_(AccessRequest.expires_at > at, AccessRequest.expires_at.is_(None)),
            AccessRequest.provisioning_status == 'GRANTED').limit(1))
        if other:
            outcome = 'SHARED_MEMBERSHIP'
        elif not access.provider_managed:
            outcome = 'UNMANAGED_MEMBERSHIP'
        else:
            result = provider.revoke(access)
            outcome = 'REVOKED' if result.status == 'REVOKED' and result.verified else 'EXPIRED_REVOKE_FAILED'
        access.provisioning_status = outcome
        access.status = 'EXPIRED' if outcome in ('REVOKED', 'UNMANAGED_MEMBERSHIP', 'SHARED_MEMBERSHIP') else 'EXPIRED_REVOKE_FAILED'
        db.add(AuditLog(user_id=None, action='GITHUB_ACCESS_EXPIRY', resource_type='request',
                        resource_id=access.request_id, status=outcome,
                        details='Scheduled expiry; provider result recorded without credentials'))
        db.commit()
        outcomes.append((access_id, outcome))
    return outcomes


if __name__ == '__main__':
    with SessionLocal() as session:
        results = expire_github_access(session)
    print(f'GitHub expiry checked {len(results)} grants; {sum(state == "EXPIRED_REVOKE_FAILED" for _, state in results)} failures')
