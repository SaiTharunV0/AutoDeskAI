const historyPrefix = 'autodeskai.chat.';
const maxHistory = 200;

export function readChatHistory(storage, userId) {
  try {
    const rows = JSON.parse(storage.getItem(historyPrefix + userId) || '[]');
    if (!Array.isArray(rows)) return [];
    return rows.slice(-maxHistory).filter(row =>
      (row?.r === 'user' || row?.r === 'bot') && typeof row.t === 'string'
    ).map(row => ({r: row.r, t: row.t.slice(0, 2000),
      ...(Number.isInteger(row.id) ? {id: row.id} : {}),
      ...(typeof row.status === 'string' ? {status: row.status} : {})}));
  } catch { return []; }
}

export function saveChatHistory(storage, userId, messages) {
  try { storage.setItem(historyPrefix + userId, JSON.stringify(messages.slice(-maxHistory))); }
  catch { /* Storage can be disabled or full. The in-memory chat still works. */ }
}

export function clearChatHistory(storage, userId) {
  try { storage.removeItem(historyPrefix + userId); } catch { /* Storage can be disabled. */ }
}

const asksForNextStep = text => /\b(what|how|where|next|continue|link|microsoft|instructions|steps)\b/i.test(text)
  && /\b(next|do|now|continue|link|microsoft|instructions|steps)\b/i.test(text);

export function replyForOpenTicket(ticket, text) {
  if (ticket.intent?.startsWith('PASSWORD_') && ticket.status === 'AWAITING_USER_ACTION') {
    if (asksForNextStep(text)) return {message:
      'Choose Continue at Microsoft on your password request. When you return, you can tell me whether it worked.', showResolution: false};
    const newRequest = /\b(access to|install|software|application|another request|new request)\b/i.test(text);
    if (!newRequest && /\b(password|microsoft|reset|change|worked|working|resolved|verification|sign.?in)\b/i.test(text))
      return {message: 'I understand. Your password request is still open.', showResolution: false};
    if (!ticket.password_action_opened_at) return {message:
      'Please choose Continue at Microsoft for your current password request first. I can ask whether it worked after you return.', showResolution: false};
    return {message:
      'Before we start another request, please tell me whether the Microsoft password action resolved your issue.', showResolution: true};
  }
  if (['COMPLETED', 'FAILED', 'APPROVED_PROVISIONING_REQUIRED'].includes(ticket.status))
    return {message: 'Before we start another request, please confirm whether your previous issue was resolved.', showResolution: true};
  return {message: 'Your current request is still being handled. Let’s finish that first, then I can help with the next one.', showResolution: false};
}
