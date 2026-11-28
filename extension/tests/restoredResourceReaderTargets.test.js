// Restored behavioral regression test. Original file: extension/tests/resourceReaderTargets.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Reader target resolution: saved captures open in VS Code.
//
// Restoration: whole - all 1 original test definitions, code and assertions unchanged.
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveResourceOpenTarget } = require('../dist/shared/src/resourceOpen.js');

test('reading opens saved captures in VS Code', () => {
  // The /tmp/... values are opaque string fixtures for a pure mapping
  // function — resolveResourceOpenTarget never touches the filesystem — so
  // they stay platform-neutral and need no os.tmpdir() indirection.
  const captured = { kind: 'url', source: 'https://example.com/guide', sandboxPath: '/tmp/captured-guide.md' };
  assert.deepEqual(resolveResourceOpenTarget(captured),
    { kind: 'vscode', source: '/tmp/captured-guide.md' });
  assert.deepEqual(resolveResourceOpenTarget({ kind: 'url', source: 'https://example.com/guide' }),
    { kind: 'unavailable', reason: 'capture_required' });
  assert.deepEqual(resolveResourceOpenTarget({ kind: 'markdown', source: '/tmp/guide.md' }),
    { kind: 'vscode', source: '/tmp/guide.md' });
  assert.deepEqual(resolveResourceOpenTarget({ kind: 'url', source: 'invalid' }),
    { kind: 'unavailable', reason: 'missing_source' });
});
