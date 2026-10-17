import test from 'node:test';
import assert from 'node:assert/strict';
import {accessStatusLabel, pendingAccessRequests, buildAccessPayload, buildPolicyPayload, buildDecisionPayload} from './access_logic.js';
import {requestApi, ApiError} from './api.js';

const application = {key: 'tableau', requestable_roles: ['viewer'], max_duration_days: 90};

test('employee access form submits only an allowed role and duration', () => {
  assert.deepEqual(buildAccessPayload(application, 'viewer', 'Business reporting', 30, 'request-key'), {
    application: 'tableau', requested_role: 'viewer', justification: 'Business reporting',
    duration_days: 30, idempotency_key: 'request-key',
  });
  assert.throws(() => buildAccessPayload(application, 'admin', '', 30, 'key'), /role/);
  assert.throws(() => buildAccessPayload(application, 'viewer', '', 100, 'key'), /duration/);
});

test('policy editor rejects invalid roles and removes read-only version', () => {
  assert.deepEqual(buildPolicyPayload({requestable_roles: ['viewer'], human_roles: [],
    default_duration_days: 30, max_duration_days: 90, version: 2}), {
    requestable_roles: ['viewer'], human_roles: [], default_duration_days: 30, max_duration_days: 90,
  });
  assert.throws(() => buildPolicyPayload({requestable_roles: ['viewer'], human_roles: ['admin'],
    default_duration_days: 30, max_duration_days: 90}), /Human approval/);
});

test('approval actions require a reason and status text is readable', () => {
  assert.deepEqual(buildDecisionPayload('APPROVE', '  Business need  '),
    {decision: 'APPROVE', reason: 'Business need'});
  assert.throws(() => buildDecisionPayload('REJECT', 'no'), /reason/);
  assert.equal(accessStatusLabel('APPROVED_PROVISIONING_REQUIRED'), 'APPROVED PROVISIONING REQUIRED');
  assert.deepEqual(pendingAccessRequests([{id: 1, status: 'AWAITING_ADMIN'},
    {id: 2, status: 'APPROVED_PROVISIONING_REQUIRED'}]).map(row => row.id), [1]);
});

test('access request API uses JWT and displays server errors', async () => {
  let path, auth;
  const fetchImpl = async (url, options) => {
    path = url;auth = options.headers.get('Authorization');
    return new Response(JSON.stringify({detail: 'Role is not requestable'}),
      {status: 422, headers: {'Content-Type': 'application/json'}});
  };
  await assert.rejects(requestApi('/access/requests', {token: 'jwt', method: 'POST',
    body: JSON.stringify({application: 'tableau'}), fetchImpl}),
    error => error instanceof ApiError && error.message === 'Role is not requestable');
  assert.equal(path, '/api/access/requests');
  assert.equal(auth, 'Bearer jwt');
});
