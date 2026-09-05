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

test('Plan candidate diff/impact never dump JSON or secrets', () => {
  const diff = describeSafeStructuredValue(
    {
      title: 'Keep the current slice',
      api_key: FAKE_KEY,
      dump: LEAK_TEXT,
    },
    'en-US',
    'No visible diff.',
  );
  const impact = describeSafeStructuredValue(
    {
      next: 'Open Plan and confirm or reject this candidate.',
      token: FAKE_KEY,
    },
    'en-US',
    'No visible impact.',
  );
  const reason = sanitizeErrorSurfaceText(
    'Shrink the next step after the last failed check.',
    'en-US',
  );
  const visible = `${reason}\nDiff: ${diff}\nImpact: ${impact}`;
  assertNoLeak(visible);
  assert.match(visible, /Shrink the next step|Keep the current slice|confirm/i);
  assert.doesNotMatch(visible, /\{"choices"/);
});
