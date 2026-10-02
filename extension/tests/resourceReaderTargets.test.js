'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveResourceOpenTarget } = require('../dist/shared/src/resourceOpen.js');

test('reading opens captured URL content in VS Code and preserves uncaptured external URLs', () => {
  assert.deepEqual(resolveResourceOpenTarget({ kind: 'url', source: 'https://example.com/guide', sandboxPath: '/tmp/captured-guide.md' }),
    { kind: 'vscode', source: '/tmp/captured-guide.md' });
  assert.deepEqual(resolveResourceOpenTarget({ kind: 'url', source: 'https://example.com/guide' }),
    { kind: 'browser', source: 'https://example.com/guide' });
  assert.deepEqual(resolveResourceOpenTarget({ kind: 'markdown', source: '/tmp/guide.md' }),
    { kind: 'vscode', source: '/tmp/guide.md' });
  assert.deepEqual(resolveResourceOpenTarget({ kind: 'url', source: 'invalid' }),
    { kind: 'unavailable', reason: 'invalid_url' });
});
