import test from 'node:test';
import assert from 'node:assert/strict';
import {readChatHistory, saveChatHistory, clearChatHistory, replyForOpenTicket, appendAdminDecisions} from './chat_flow.js';

test('password resolution waits for the Microsoft action and a later request', () => {
  const ticket = {intent: 'PASSWORD_RESET', status: 'AWAITING_USER_ACTION'};
  assert.equal(replyForOpenTicket(ticket, 'I need Tableau access').showResolution, false);
  ticket.password_action_opened_at = '2026-10-24T10:00:00';
  assert.equal(replyForOpenTicket(ticket, 'What should I do next?').showResolution, false);
  assert.equal(replyForOpenTicket(ticket, 'The password reset is still not working').showResolution, false);
  assert.equal(replyForOpenTicket(ticket, 'I need Tableau access').showResolution, true);
});

test('chat history survives reload in the same browser session and is user-scoped', () => {
  const data = new Map();
  const storage = {getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key)};
  saveChatHistory(storage, 1, [{r: 'user', t: 'hi'}, {r: 'bot', t: 'Hello'}]);
  assert.deepEqual(readChatHistory(storage, 1), [{r: 'user', t: 'hi'}, {r: 'bot', t: 'Hello'}]);
  assert.deepEqual(readChatHistory(storage, 2), []);
  clearChatHistory(storage, 1);
  assert.deepEqual(readChatHistory(storage, 1), []);
});

test('saved access clarification uses the current application choice question', () => {
  const old = 'Which application do you need access to? For GitHub, use Application Access to enter your GitHub username.';
  const data = new Map([['autodeskai.chat.1', JSON.stringify([{r: 'bot', t: old, id: 4}])]]);
  const storage = {getItem: key => data.get(key) ?? null};
  assert.equal(readChatHistory(storage, 1)[0].t, 'Which application do you need access to: GitHub or Jira?');
});

test('admin approvals and rejections appear once for chat requests and survive reload', () => {
  const original = [{r: 'user', t: 'I need Jira access'},
    {r: 'bot', t: 'Sent to an administrator', id: 7, status: 'AWAITING_ADMIN'},
    {r: 'bot', t: 'Another request', id: 8, status: 'AWAITING_ADMIN'}];
  const requests = [
    {id: 7, intent: 'ACCESS_REQUEST', status: 'CLOSED', resolution_reporter: 'ADMIN', resolved: null,
      message: 'An administrator approved this request. Access is still being set up.'},
    {id: 8, intent: 'ACCESS_REQUEST', status: 'CLOSED', rejection_source: 'ADMIN',
      message: 'An administrator rejected this request. This ticket is closed.'},
    {id: 9, intent: 'ACCESS_REQUEST', status: 'CLOSED', resolution_reporter: 'ADMIN', resolved: null,
      message: 'An administrator approved this request.'},
  ];
  const updated = appendAdminDecisions(original, requests);
  assert.deepEqual(updated.filter(row => row.decision === 'ADMIN').map(row => row.id), [8, 7]);
  assert.match(updated.at(-1).t, /approved/);
  assert.strictEqual(appendAdminDecisions(updated, requests), updated);
  const data = new Map();
  const storage = {getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key)};
  saveChatHistory(storage, 1, updated);
  assert.strictEqual(appendAdminDecisions(readChatHistory(storage, 1), requests).length, updated.length);
});

test('later provider verification still identifies an administrator approval', () => {
  const chat = [{r: 'bot', t: 'Review requested', id: 12}];
  const requests = [{id: 12, intent: 'ACCESS_REQUEST', status: 'CLOSED',
    resolution_reporter: 'ADMIN', resolved: null, message: 'GitHub organization membership was verified.'}];
  assert.match(appendAdminDecisions(chat, requests)[1].t, /administrator approved/);
});

test('existing rejection reply is marked and duplicate saved replies are removed', () => {
  const message = 'Your administrator couldn’t approve this request. This ticket is closed.';
  const requests = [{id: 13, intent: 'ACCESS_REQUEST', status: 'CLOSED', rejection_source: 'ADMIN', message}];
  const chat = [{r: 'bot', t: 'Sent to an administrator', id: 13, status: 'AWAITING_ADMIN'},
    {r: 'bot', t: message, id: 13, status: 'CLOSED'},
    {r: 'bot', t: message, id: 13, status: 'CLOSED', decision: 'ADMIN'}];
  const updated = appendAdminDecisions(chat, requests);
  assert.equal(updated.length, 2);
  assert.equal(updated[1].decision, 'ADMIN');
  assert.strictEqual(appendAdminDecisions(updated, requests), updated);
});
