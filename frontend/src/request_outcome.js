const rejectedClosure = 'I have closed this ticket; no confirmation is needed.';

/** The ticket status tracks its lifecycle; this describes the result or next step. */
export function requestOutcome(request) {
  const status = request.status;
  if (status === 'CLOSED') {
    if (request.rejection_source || request.message?.includes(rejectedClosure)) {
      return {label: 'Rejected', code: 'rejected'};
    }
    if (request.resolved === true || request.task?.status === 'COMPLETED') {
      return {label: 'Completed', code: 'completed'};
    }
    return {label: 'Closed', code: 'closed'};
  }

  const outcomes = {
    REJECTED: ['Rejected', 'rejected'],
    COMPLETED: ['Completed', 'completed'],
    AWAITING_USER_ACTION: ['Awaiting user action', 'awaiting_user_action'],
    NEEDS_CLARIFICATION: ['Awaiting your reply', 'needs_clarification'],
    AWAITING_ADMIN: ['Awaiting administrator', 'awaiting_admin'],
    AWAITING_ADMIN_CLOSE: ['Ready to close', 'awaiting_admin_close'],
    APPROVED_PROVISIONING_REQUIRED: ['Awaiting provisioning', 'approved_provisioning_required'],
    RETRY_ACTION_REQUIRED: ['Retry available', 'retry_action_required'],
    FAILED: ['Failed', 'failed'],
    PENDING: ['In progress', 'pending'],
    PROCESSING: ['In progress', 'processing'],
  };
  const [label, code] = outcomes[status] || [status.replaceAll('_', ' ').toLowerCase(), status.toLowerCase()];
  return {label, code};
}

export function requestResolution(request) {
  if (requestOutcome(request).code === 'rejected') {
    return request.rejection_source === 'ADMIN'
      ? 'Rejected by administrator'
      : 'Rejected by AutoDeskAI under admin configuration';
  }
  if (request.resolved === true) {
    return `Confirmed by ${request.resolution_reporter === 'ADMIN' ? 'administrator' : 'employee'}`;
  }
  if (request.resolved === false) return 'Reported unresolved';
  return request.status === 'CLOSED' ? 'Closed without a resolution report' : 'Awaiting outcome';
}
