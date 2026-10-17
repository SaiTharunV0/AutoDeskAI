import test from 'node:test';
import assert from 'node:assert/strict';
import {requestApi, GATEWAY_ERROR, SESSION_ERROR, TIMEOUT_ERROR} from './api.js';

test('API preserves JWT and JSON headers and does not retry mutations', async () => {
  let calls = 0;
  await assert.rejects(requestApi('/requests', {token: 'test-token', method: 'POST', body: '{}',
    fetchImpl: async (url, options) => {
      calls++;
      assert.equal(url, '/api/requests');
      assert.equal(options.headers.get('Authorization'), 'Bearer test-token');
      assert.equal(options.headers.get('Content-Type'), 'application/json');
      return new Response('<html>Bad Gateway</html>', {status: 502});
    },
  }), {message: GATEWAY_ERROR, status: 502});
  assert.equal(calls, 1);
});

test('API distinguishes invalid credentials from expired sessions', async () => {
  const fetchImpl = async () => new Response(JSON.stringify({detail: 'Username/email or password is wrong'}), {status: 401});
  await assert.rejects(requestApi('/auth/login', {fetchImpl}), {message: 'Username/email or password is wrong'});
  await assert.rejects(requestApi('/requests', {fetchImpl, token: 'expired'}), {message: SESSION_ERROR});
});

test('logged-out recovery configuration request sends no JWT', async () => {
  const response = await requestApi('/auth/password-recovery', {fetchImpl: async (url, options) => {
    assert.equal(url, '/api/auth/password-recovery');
    assert.equal(options.headers.has('Authorization'), false);
    return new Response(JSON.stringify({available: true, url: 'https://passwordreset.microsoftonline.com/'}), {status: 200});
  }});
  assert.equal(response.available, true);
});

test('timeout covers the response body and is reported clearly', async () => {
  await assert.rejects(requestApi('/requests', {timeoutMs: 5, fetchImpl: async (_, {signal}) => ({
    ok: true, status: 200, text: () => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }),
  })}), {message: TIMEOUT_ERROR});
});

test('caller cancellation stays silent and stops the active fetch', async () => {
  const controller = new AbortController();
  const result = requestApi('/devices', {signal: controller.signal, fetchImpl: (_, {signal}) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  })});
  controller.abort();
  await assert.rejects(result, {name: 'AbortError'});
});
