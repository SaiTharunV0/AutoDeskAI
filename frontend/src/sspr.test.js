import test from 'node:test';
import assert from 'node:assert/strict';
import { validatedSsprUrl } from './sspr.js';

test('accepts configured HTTPS destination', () => {
  assert.equal(validatedSsprUrl('https://passwordreset.microsoftonline.com/'), 'https://passwordreset.microsoftonline.com/');
});

test('rejects missing, malformed, and unapproved destinations', () => {
  for (const value of ['', undefined, 'not a url', 'http://passwordreset.microsoftonline.com/',
    'https://evil.example/reset', 'https://passwordreset.microsoftonline.com.evil.example/',
    'https://user@passwordreset.microsoftonline.com/', 'javascript:alert(1)']) {
    assert.equal(validatedSsprUrl(value), null);
  }
});
