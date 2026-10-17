import test from 'node:test';
import assert from 'node:assert/strict';
import {CHAT_MESSAGE_LIMIT, chatComposerState} from './chat.js';

test('chat composer enforces the 2,000 character limit and exposes a counter', () => {
  assert.equal(chatComposerState('x'.repeat(CHAT_MESSAGE_LIMIT), false).count, CHAT_MESSAGE_LIMIT);
  assert.equal(chatComposerState('x'.repeat(CHAT_MESSAGE_LIMIT), false).disabled, false);
  assert.equal(chatComposerState('x'.repeat(CHAT_MESSAGE_LIMIT + 1), false).overLimit, true);
  assert.equal(chatComposerState('x'.repeat(CHAT_MESSAGE_LIMIT + 1), false).disabled, true);
});

test('busy processing and Retry-After disable duplicate sends and show rate feedback', () => {
  assert.equal(chatComposerState('hello', true).disabled, true);
  const limited = chatComposerState('hello', false, 12);
  assert.equal(limited.disabled, true);
  assert.match(limited.hint, /12 seconds/);
});

test('composer advertises only the implemented helpdesk scope', () => {
  assert.match(chatComposerState('', false).hint, /password change\/reset/);
  assert.match(chatComposerState('', false).hint, /request statuses/);
  assert.match(chatComposerState('', false).hint, /out of scope/);
});
