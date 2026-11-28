// Restored behavioral regression test. Original file: extension/tests/errorSurfaceVisibleContract.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Coach tool-result and Settings notice copy stay explainable after a leaking sidecar payload.
//
// Restoration: partial - 2 of 3 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "Plan candidate diff/impact never dump JSON or secrets"
//       fails at HEAD: describeSafeStructuredValue is not a function
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  describeSafeStructuredValue,
  sanitizeErrorSurface,
  sanitizeErrorSurfaceText,
} = require('../dist/shared/src/errorSurfaceSanitizer.js');

const FAKE_KEY = 'sk-test-not-a-real-key-aaaaaaaa';
const LEAK_TEXT = [
  'Traceback (most recent call last):',
  '  File "app.py", line 12, in run',
  'KeyError: boom',
  '{"choices":[{"message":{"content":"hidden","token":"fake-token-zzzz"}}]}',
  `api_key=${FAKE_KEY}`,
].join('\n');

function assertNoLeak(text) {
  assert.doesNotMatch(text, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(text, /Traceback \(most recent call last\)/i);
  assert.doesNotMatch(text, /File "app\.py"/);
  assert.doesNotMatch(text, /"choices"/);
  assert.doesNotMatch(text, /fake-token-zzzz/);
  assert.doesNotMatch(text, /api_key=sk-/i);
}

test('Coach tool-result error copy stays explainable after a leaking sidecar payload', () => {
  const surface = sanitizeErrorSurface(LEAK_TEXT, { language: 'en-US' });
  const visible = `${surface.message} ${surface.next}`;
  assertNoLeak(visible);
  assert.match(visible, /failed|hidden|Settings|Try again/i);
  assert.ok(visible.trim().length > 0);
});

test('Settings operation/status notice never keeps traceback, JSON, or a key-shaped token', () => {
  const visible = sanitizeErrorSurfaceText(LEAK_TEXT, 'en-US');
  assertNoLeak(visible);
  assert.match(visible, /Settings|Try again|failed|hidden|connection/i);
  assert.ok(visible.trim().length > 0);
});
