const historyPrefix = 'autodeskai.chat.';
const maxHistory = 200;
const oldAccessQuestion = 'Which application do you need access to? For GitHub, use Application Access to enter your GitHub username.';
const accessQuestion = 'Which application do you need access to: GitHub or Jira?';

export function readChatHistory(storage, userId) {
  try {
    const rows = JSON.parse(storage.getItem(historyPrefix + userId) || '[]');
    if (!Array.isArray(rows)) return [];
    return rows.slice(-maxHistory).filter(row =>
      (row?.r === 'user' || row?.r === 'bot') && typeof row.t === 'string'
    ).map(row => ({r: row.r, t: (row.t === oldAccessQuestion ? accessQuestion : row.t).slice(0, 2000),
      ...(Number.isInteger(row.id) ? {id: row.id} : {}),
      ...(typeof row.status === 'string' ? {status: row.status} : {}),
      ...(row.decision === 'ADMIN' ? {decision: 'ADMIN'} : {})}));
  } catch { return []; }
}

export function saveChatHistory(storage, userId, messages) {
  try { storage.setItem(historyPrefix + userId, JSON.stringify(messages.slice(-maxHistory))); }
  catch { /* Storage can be disabled or full. The in-memory chat still works. */ }
}

export function clearChatHistory(storage, userId) {
  try { storage.removeItem(historyPrefix + userId); } catch { /* Storage can be disabled. */ }
}

export function appendAdminDecisions(chat, requests) {
  const chatRequests = new Set(chat.filter(row => row.r === 'bot' && Number.isInteger(row.id)).map(row => row.id));
  const announced = new Set(chat.filter(row => row.decision === 'ADMIN').map(row => row.id));
  const updates = [];
  for (const request of [...requests].reverse()) {
    if (!chatRequests.has(request.id) || announced.has(request.id) || request.status !== 'CLOSED') continue;
    let message;
    if (request.rejection_source === 'ADMIN') {
      message = request.message || 'An administrator rejected your request. This ticket is closed.';
    } else if (request.resolution_reporter === 'ADMIN' && request.intent === 'ACCESS_REQUEST' && request.resolved == null) {
      message = request.message?.startsWith('An administrator approved')
        ? request.message
        : `An administrator approved your application access request. ${request.message || 'Check Application Access for provisioning status.'}`;
    } else if (request.resolution_reporter === 'ADMIN' && request.resolved === true) {
      message = request.message || 'An administrator marked your request resolved and closed the ticket.';
    }
    if (message) {
      updates.push({r: 'bot', t: message, id: request.id, status: request.status, decision: 'ADMIN'});
      announced.add(request.id);
    }
  }
  return updates.length ? [...chat, ...updates] : chat;
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
      'I can help with that after you choose Resolved or Not resolved for your current request below.', showResolution: true};
  }
  if (['COMPLETED', 'FAILED', 'APPROVED_PROVISIONING_REQUIRED'].includes(ticket.status))
    return {message: 'I can help with that after you choose Resolved or Not resolved for your current request below.', showResolution: true};
  return {message: 'Your current request is still being handled. Let’s finish that first, then I can help with the next one.', showResolution: false};
}
