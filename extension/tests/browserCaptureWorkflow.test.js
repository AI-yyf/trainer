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
