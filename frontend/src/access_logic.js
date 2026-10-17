export const accessStatusLabel = value => (value || '').replaceAll('_', ' ');
export const pendingAccessRequests = rows => rows.filter(row => row.status === 'AWAITING_ADMIN');

export function buildAccessPayload(application, role, justification, duration, idempotencyKey) {
  const days = Number(duration);
  if (!application || !application.requestable_roles.includes(role)) throw new Error('Select a requestable role.');
  if (!Number.isInteger(days) || days < 1 || days > application.max_duration_days) throw new Error('Choose an allowed duration.');
  if (justification.length > 500) throw new Error('Business justification is too long.');
  return {application: application.key, requested_role: role, justification,
    duration_days: days, idempotency_key: idempotencyKey};
}

export function buildPolicyPayload(form) {
  const payload = {...form};
  delete payload.version;
  if (!payload.requestable_roles.length || payload.default_duration_days > payload.max_duration_days)
    throw new Error('Choose at least one role and a valid default duration.');
  if (payload.human_roles.some(role => !payload.requestable_roles.includes(role)))
    throw new Error('Human approval roles must be requestable.');
  return payload;
}

export function buildDecisionPayload(decision, reason) {
  const trimmed = reason.trim();
  if (!['APPROVE', 'REJECT'].includes(decision) || trimmed.length < 5)
    throw new Error('Enter an approval or rejection reason of at least 5 characters.');
  return {decision, reason: trimmed};
}
