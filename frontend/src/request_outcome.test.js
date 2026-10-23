import test from 'node:test';
import assert from 'node:assert/strict';
import {requestOutcome, requestResolution} from './request_outcome.js';

test('closed rejected and completed tickets retain their distinct outcomes', () => {
  assert.deepEqual(requestOutcome({status: 'CLOSED', resolved: null,
    message: "This application is not authorised. I have closed this ticket; no confirmation is needed."}),
    {label: 'Rejected', code: 'rejected'});
  assert.deepEqual(requestOutcome({status: 'CLOSED', resolved: true, message: 'Ticket closed.'}),
    {label: 'Completed', code: 'completed'});
  assert.deepEqual(requestOutcome({status: 'CLOSED', resolved: null, message: 'Clarification received.'}),
    {label: 'Closed', code: 'closed'});
});

test('an open password request shows the employee action', () => {
  assert.deepEqual(requestOutcome({status: 'AWAITING_USER_ACTION'}),
    {label: 'Awaiting user action', code: 'awaiting_user_action'});
});

test('rejected requests name the deciding party in the resolution', () => {
  assert.equal(requestResolution({status: 'CLOSED', rejection_source: 'AUTODESKAI'}),
    'Rejected by AutoDeskAI under admin configuration');
  assert.equal(requestResolution({status: 'CLOSED', rejection_source: 'ADMIN'}),
    'Rejected by administrator');
});
