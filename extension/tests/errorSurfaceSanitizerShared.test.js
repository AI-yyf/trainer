'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  describeSafeStructuredValue,
  isAuthoritativeAck,
  sanitizeErrorSurface,
  sanitizeErrorSurfaceJson,
  sanitizeErrorSurfaceText,
  sanitizeHostToolResult,
  waitingComposerEnqueueFailureSurface,
  waitingComposerEnqueueFailureText,
} = require('../dist/shared/src/errorSurfaceSanitizer.js');

const FAKE_KEY = 'sk-test-not-a-real-key-aaaaaaaa';
const FAKE_BEARER = 'Bearer fake-token-zzzzzzzzzzzz';

test('key-like strings are redacted and remain explainable', () => {
  const surface = sanitizeErrorSurface(
    `Connection failed with ${FAKE_KEY} and ${FAKE_BEARER}`,
    { language: 'en-US' },
  );
  assert.equal(surface.kind, 'secret');
  assert.doesNotMatch(surface.message, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(surface.message, /fake-token-zzzzzzzzzzzz/);
  assert.match(surface.message, /redacted/i);
  assert.match(surface.next, /Settings/i);
  assert.equal(surface.authoritative, false);

  const text = sanitizeErrorSurfaceText(`api_key=${FAKE_KEY}`, 'en-US');
  assert.doesNotMatch(text, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.match(text, /Settings|redacted|secret/i);
});

test('traceback dumps are not shown', () => {
  const surface = sanitizeErrorSurface(
    'Traceback (most recent call last):\n  File "app.py", line 12, in run\n    raise RuntimeError("boom")\nRuntimeError: boom',
    { language: 'en-US' },
  );
  assert.equal(surface.kind, 'traceback');
  assert.doesNotMatch(surface.message, /Traceback|File "|RuntimeError|boom/);
  assert.match(surface.next, /Settings|Try again/i);
  assert.ok(surface.message.trim().length > 0);
});

test('raw JSON bodies are not shown', () => {
  const surface = sanitizeErrorSurface(
    '{"choices":[{"message":{"content":"hidden"}}],"token":"fake-token-zzzz"}',
    { language: 'en-US' },
  );
  assert.equal(surface.kind, 'json_body');
  assert.doesNotMatch(surface.message, /choices|fake-token-zzzz|\{/);
  assert.match(surface.why, /JSON|response/i);
  assert.ok(surface.next.length > 0);
});

test('think-text leaks are removed', () => {
  const surface = sanitizeErrorSurface(
    `<think>internal plan with ${FAKE_KEY}</think>`,
    { language: 'en-US' },
  );
  assert.equal(surface.kind, 'thinking');
  assert.doesNotMatch(surface.message, /internal plan|sk-test-not-a-real-key|<think>/);
});

test('success without authoritative ack is not success', () => {
  const surface = sanitizeErrorSurface('OK', { language: 'en-US', acknowledged: false });
  assert.equal(surface.kind, 'unverified');
  assert.doesNotMatch(surface.message, /^(ok|success|ready)$/i);
  assert.match(surface.message, /not confirmed|not success/i);
  assert.equal(isAuthoritativeAck({ ok: true }), false);
  assert.equal(isAuthoritativeAck({ ok: true, acked: true }), true);
});

test('human errors stay explainable after sanitizing', () => {
  const surface = sanitizeErrorSurface(
    'The current API key is invalid. Open Settings and update the provider connection.',
    { language: 'en-US' },
  );
  assert.equal(surface.kind, 'safe');
  assert.match(surface.message, /invalid/i);
  assert.match(surface.message, /Settings/i);
});

test('plan candidate values stay explainable without dumping JSON or keys', () => {
  const safe = describeSafeStructuredValue(
    { title: 'Shrink the next step', nextStep: 'Open Plan and confirm the candidate' },
    'en-US',
    'No visible diff.',
  );
  assert.match(safe, /Shrink the next step/);
  assert.doesNotMatch(safe, /\{/);

  const leaked = describeSafeStructuredValue(
    {
      title: 'Keep the current slice',
      api_key: FAKE_KEY,
      dump: `Traceback (most recent call last):\n  File "app.py", line 12\n{"choices":[{"token":"hidden"}]}`,
    },
    'en-US',
    'No visible diff.',
  );
  assert.doesNotMatch(leaked, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(leaked, /Traceback|File "|choices/);
  assert.match(leaked, /Keep the current slice|hidden|Settings|diff/i);
});

test('tool args JSON redacts secret fields', () => {
  const rendered = sanitizeErrorSurfaceJson({
    path: 'src/app.ts',
    api_key: FAKE_KEY,
    note: 'read this file',
  });
  assert.doesNotMatch(rendered, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.match(rendered, /src\/app\.ts|redacted/i);
});

test('host tool results keep safe fields and strip leaks before postMessage', () => {
  const leak = [
    'Traceback (most recent call last):',
    '  File "app.py", line 12, in run',
    `api_key=${FAKE_KEY}`,
    '{"choices":[{"message":{"content":"hidden"}}]}',
  ].join('\n');
  const cleaned = sanitizeHostToolResult(
    {
      ok: false,
      hits: ['safe-hit'],
      error: leak,
      api_key: FAKE_KEY,
    },
    'en-US',
  );
  assert.equal(cleaned.ok, false);
  assert.deepEqual(cleaned.hits, ['safe-hit']);
  assert.equal(cleaned.api_key, '[redacted]');
  const rendered = JSON.stringify(cleaned);
  assert.doesNotMatch(rendered, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(rendered, /Traceback \(most recent call last\)/);
  assert.doesNotMatch(rendered, /"choices"/);
  assert.match(String(cleaned.error), /failed|hidden|Settings|Try again|connection/i);

  const dump = sanitizeHostToolResult(
    { choices: [{ message: { content: 'hidden' } }], token: FAKE_KEY },
    'en-US',
  );
  assert.doesNotMatch(JSON.stringify(dump), /choices|sk-test-not-a-real-key-aaaaaaaa/);
  assert.match(String(dump.error), /hidden|Settings|Try again|connection/i);
});

test('error-surface copy is localized and still leak-free', () => {
  const leak = [
    'Traceback (most recent call last):',
    '  File "app.py", line 12, in run',
    `api_key=${FAKE_KEY}`,
  ].join('\n');
  const english = sanitizeErrorSurfaceText(leak, 'en-US');
  const languages = ['zh-CN', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
  for (const language of languages) {
    const visible = sanitizeErrorSurfaceText(leak, language);
    assert.doesNotMatch(visible, /sk-test-not-a-real-key-aaaaaaaa/);
    assert.doesNotMatch(visible, /Traceback \(most recent call last\)/);
    assert.ok(visible.trim().length > 0);
    assert.notEqual(visible, english);
  }
  assert.match(sanitizeErrorSurfaceText(leak, 'ja-JP'), /失敗|非表示|設定/);
  assert.match(sanitizeErrorSurfaceText(leak, 'es-ES'), /falló|ocultaron|Ajustes/i);
});

test('waiting composer enqueue failures stay explainable without inventing success', () => {
  const down = waitingComposerEnqueueFailureSurface('Sidecar is not running.', 'en-US');
  assert.equal(down.authoritative, false);
  assert.match(down.message, /Sidecar is not running/);
  assert.match(down.why, /waiting for evidence|No pending item/i);
  assert.match(down.next, /Retry in the evidence composer/);

  const leak = waitingComposerEnqueueFailureText(
    [
      'Traceback (most recent call last):',
      '  File "app.py", line 12, in run',
      `{"detail":"boom","token":"${FAKE_KEY}"}`,
    ].join('\n'),
    'en-US',
  );
  assert.doesNotMatch(leak, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(leak, /Traceback|File "|\{"detail"/);
  assert.match(leak, /hidden|failed|not queued/i);
  assert.match(leak, /Retry in the evidence composer/);
  assert.doesNotMatch(leak, /\b(ok|success|ready)\b/i);
});
