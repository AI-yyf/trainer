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

test('capture worker keeps recoverable failures across restarts and reuses the capture ID', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const vm = require('node:vm');
  const root = path.resolve(__dirname, '../../browser-extension');
  const files = Object.fromEntries(['shared.js', 'background.js'].map((name) =>
    [name, fs.readFileSync(path.join(root, name), 'utf8')],
  ));
  const storage = {
    [C.STORAGE_KEYS.baseUrl]: C.SIDECAR.defaultBaseUrl,
    [C.STORAGE_KEYS.credential]: 'fixture-credential',
    [C.STORAGE_KEYS.workspaceId]: '',
  };
  const submitted = [];
  let online = false;
  let rejectFolder = true;
  const response = (status, body) => ({
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  });
  const noop = () => undefined;
  function worker() {
    let onMessage;
    const chrome = {
      storage: {
        local: {
          async get(defaults) {
            return Object.fromEntries(Object.entries(defaults).map(([key, value]) =>
              [key, structuredClone(storage[key] ?? value)],
            ));
          },
          async set(updates) { Object.assign(storage, structuredClone(updates)); },
          async remove(keys) {
            for (const key of Array.isArray(keys) ? keys : [keys]) delete storage[key];
          },
        },
      },
      notifications: { create: noop, onClicked: { addListener: noop } },
      contextMenus: { onClicked: { addListener: noop } },
      action: { setBadgeText: noop, setBadgeBackgroundColor: noop },
      alarms: { get: async () => true, onAlarm: { addListener: noop } },
      runtime: {
        getURL: (value) => value,
        onMessage: { addListener: (handler) => { onMessage = handler; } },
        onInstalled: { addListener: noop },
        onStartup: { addListener: noop },
      },
    };
    const context = vm.createContext({
      console, chrome, URL, AbortController, setTimeout, clearTimeout,
      importScripts: (name) => vm.runInContext(files[name], context),
      async fetch(input, request) {
        const url = new URL(input);
        if (!online || url.origin !== C.SIDECAR.defaultBaseUrl) throw new Error('offline');
        if (url.pathname !== '/resources/capture') return response(200, { workspace_id: 'workspace-a' });
        const payload = JSON.parse(request.body);
        submitted.push(payload);
        if (rejectFolder && payload.download) {
          return response(403, { detail: { code: 'read_only', message: 'Choose a writable folder.' } });
        }
        return response(200, {
          resource_id: 'resource-fixture',
          parse_status: 'parsed',
          index_status: payload.download ? 'indexed' : 'pending',
          ...(payload.download ? { saved_path: `${payload.target_dir}paper.pdf` } : {}),
        });
      },
    });
    context.self = context;
    vm.runInContext(files['background.js'], context);
    return (message) => new Promise((resolve) => onMessage(message, {}, (value) =>
      resolve(structuredClone(value)),
    ));
  }

  let send = worker();
  const queued = await send({
    type: 'trainer:capture', url: 'https://example.com/paper.pdf',
    kind: 'pdf', download: true, targetDir: 'Locked', title: 'Paper',
  });
  assert.equal(queued.status, 'queued');
  assert.equal((await send({ type: 'trainer:state' })).queueCount, 1);

  online = true;
  storage[C.STORAGE_KEYS.workspaceId] = 'workspace-a';
  const delivery = await send({ type: 'trainer:flush' });
  assert.equal(delivery.ok, false);
  assert.equal(delivery.rejected, 1);
  assert.equal(delivery.remaining, 0);
  assert.equal(storage[C.STORAGE_KEYS.credential], 'fixture-credential');

  send = worker();
  const persisted = await send({ type: 'trainer:state' });
  const [failed] = persisted.failedCaptures;
  assert.equal(failed.clientCaptureId, queued.clientCaptureId);
  assert.equal(failed.workspaceId, 'workspace-a');
  assert.match(failed.lastError, /writable folder/);

  const invalid = await send({
    type: 'trainer:capture-failure-retry', clientCaptureId: failed.clientCaptureId,
    targetDir: '../outside',
  });
  assert.equal(invalid.invalid, true);
  assert.equal(invalid.state.failedCaptures.length, 1);
  assert.equal(submitted.length, 1);

  rejectFolder = false;
  const retried = await send({
    type: 'trainer:capture-failure-retry', clientCaptureId: failed.clientCaptureId,
    targetDir: 'Notes',
  });
  assert.equal(retried.status, 'ok');
  assert.equal(retried.state.failedCaptures.length, 0);
  assert.match(retried.message, /Notes\/paper\.pdf/);
  assert.deepEqual(submitted.map((item) => item.client_capture_id), [failed.clientCaptureId, failed.clientCaptureId]);
  assert.deepEqual(submitted.map((item) => item.target_dir), ['Locked/', 'Notes/']);

  const received = await send({ type: 'trainer:capture', url: 'https://example.com/article' });
  assert.equal(received.status, 'received');
  assert.match(received.message, /Indexing is still unconfirmed/);

  rejectFolder = true;
  const failedNow = await send({
    type: 'trainer:capture', url: 'https://example.com/another.pdf',
    kind: 'pdf', download: true, targetDir: 'Locked',
  });
  assert.equal(failedNow.status, 'failed');
  const failureState = await send({ type: 'trainer:state' });
  const removed = await send({
    type: 'trainer:capture-failure-remove',
    clientCaptureId: failureState.failedCaptures[0].clientCaptureId,
  });
  assert.equal(removed.ok, true);
  assert.equal(removed.state.failedCaptures.length, 0);
  assert.equal(submitted.length, 4);
});
