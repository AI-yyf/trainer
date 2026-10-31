'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../../browser-extension/shared.js');

test('capture queue retains destination and intent through storage and replay', () => {
  const item = C.createQueueItem({url:'https://example.com/a',kind:'web',workspaceId:'project-a',workspaceName:'A',focusId:'stage-a',captureMode:'link',clientCaptureId:'capture-1'});
  const stored = JSON.parse(JSON.stringify(C.enqueueCapture([], item).queue[0]));
  assert.equal(stored.workspaceId, 'project-a');
  assert.equal(stored.workspaceName, 'A');
  assert.equal(stored.captureMode, 'link');
  const payload = C.buildCapturePayload(stored);
  assert.equal(payload.workspace_id, 'project-a');
  assert.equal(payload.capture_mode, 'link');
  assert.equal(payload.bind_focus_id, 'stage-a');
  assert.equal(payload.client_capture_id, 'capture-1');
});

test('queue dedupe preserves distinct destination, focus, excerpt and link intentions', () => {
  const source = {url:'https://example.com/a',kind:'web',workspaceId:'a',focusId:'one'};
  for (const changed of [{workspaceId:'b'},{focusId:'two'},{captureMode:'link'},{selection:'different excerpt'}]) {
    assert.notEqual(C.buildDedupKey(source), C.buildDedupKey({...source,...changed}));
  }
});

test('GitHub current-page capture preserves files, issues and branches', () => {
  assert.equal(C.detectKind('https://github.com/acme/research'), 'github_repo');
  for (const suffix of ['/blob/main/src/train.py#L80','/issues/12','/tree/feature/docs']) {
    assert.equal(C.detectKind('https://github.com/acme/research'+suffix), 'web');
    assert.equal(C.githubRepositoryUrl('https://github.com/acme/research'+suffix), 'https://github.com/acme/research');
  }
});

test('queue rotation lets a retryable head item yield to later work', () => {
  const a = { clientCaptureId: 'a' };
  const b = { clientCaptureId: 'b' };
  assert.deepEqual(
    C.rotateQueueItem([a, b], 'a').map((item) => item.clientCaptureId),
    ['b', 'a'],
  );
  assert.deepEqual(
    C.rotateQueueItem([a, b], 'b').map((item) => item.clientCaptureId),
    ['a', 'b'],
  );
  const da = { clientDraftId: 'a' };
  const db = { clientDraftId: 'b' };
  assert.deepEqual(
    C.rotateDraft([da, db], 'a').map((item) => item.clientDraftId),
    ['b', 'a'],
  );
});

test('auto-pair prefers the focused sidecar and keeps discovery order on ties', () => {
  const older = { baseUrl: 'a', hasSession: true, focusAt: 100 };
  const newer = { baseUrl: 'b', hasSession: true, focusAt: 200 };
  const noSession = { baseUrl: 'c', hasSession: false, focusAt: 999 };
  assert.deepEqual(
    C.rankAutoPairCandidates([older, newer]).map((item) => item.baseUrl),
    ['b', 'a'],
  );
  assert.deepEqual(
    C.rankAutoPairCandidates([noSession, older, newer]).map((item) => item.baseUrl),
    ['b', 'a', 'c'],
  );
  const tieA = { baseUrl: 'a', hasSession: true, focusAt: 200 };
  const tieB = { baseUrl: 'b', hasSession: true, focusAt: 200 };
  assert.deepEqual(
    C.rankAutoPairCandidates([tieA, tieB]).map((item) => item.baseUrl),
    ['a', 'b'],
  );
});
