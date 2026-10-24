import test from 'node:test';
import assert from 'node:assert/strict';
import {readChatHistory, saveChatHistory, clearChatHistory, replyForOpenTicket} from './chat_flow.js';

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
