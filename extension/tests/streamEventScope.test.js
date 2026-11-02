'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { isCurrentStreamEvent } = require('../dist/shared/src/streamEventScope.js');

test('stream completion accepts the active id and rejects a stale id', () => {
  const active = { isStreaming: true, streamMessageId: 'msg-active' };
  assert.equal(isCurrentStreamEvent(active, 'msg-active'), true);
  assert.equal(isCurrentStreamEvent(active, 'msg-stale'), false);
});

test('a cleared stream id still accepts completion while the stream is active', () => {
  // A host snapshot may clear streamMessageId before the terminal complete
  // frame. The completion is the only remaining identity; ignoring it leaves
  // the webview stuck in "streaming" and hides the persisted reply.
  assert.equal(isCurrentStreamEvent({ isStreaming: true }, 'msg-complete'), true);
  assert.equal(isCurrentStreamEvent({ isStreaming: false }, 'msg-complete'), false);
});

test('missing completion ids stay accepted for legacy replay frames', () => {
  assert.equal(isCurrentStreamEvent({ isStreaming: true }, undefined), true);
  assert.equal(isCurrentStreamEvent({ isStreaming: true, streamMessageId: 'msg-active' }, undefined), true);
});
