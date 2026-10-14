'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const draftPollerModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'browserCapture',
  'draftPoller.js',
);
const runtimeModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'browserCapture',
  'runtime.js',
);
const constantsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'constants.js',
);

const VSCODE_MOCK = { window: {}, workspace: {}, commands: {} };

function loadPoller() {
  return loadWithVscodeMock(draftPollerModulePath, VSCODE_MOCK);
}

function loadRuntime() {
  return loadWithVscodeMock(runtimeModulePath, VSCODE_MOCK);
}

function createHarness({
  visible = true,
  port = 34891,
  drafts = [],
  forwardError,
  ackError,
} = {}) {
  const forwarded = [];
  const acknowledged = [];
  const errors = [];
  const fetches = [];
  const poller = new (loadPoller().BrowserDraftPoller)({
    // `port: null` models a stopped sidecar (no port yet).
    getSidecarPort: () => (port === null ? undefined : port),
    isWorkbenchVisible: () => visible,
    fetchPendingDrafts: async (requestedPort) => {
      fetches.push(requestedPort);
      return { drafts };
    },
    acknowledgeDrafts: async (requestedPort, ids) => {
      if (ackError) {
        throw new Error(ackError);
      }
      acknowledged.push({ port: requestedPort, ids });
    },
    forwardDraft: async (text) => {
      if (forwardError && forwardError(text)) {
        throw new Error(`forward failed for ${text}`);
      }
      forwarded.push(text);
    },
    onError: (message) => errors.push(message),
  });
  return { poller, forwarded, acknowledged, errors, fetches };
}

test('parsePendingDrafts keeps only drafts with an id and non-empty text', () => {
  const { parsePendingDrafts } = loadPoller();

  assert.deepEqual(
    parsePendingDrafts({
      drafts: [
        { id: 'draft-1', text: 'first draft' },
        { id: 'draft-2', text: '   ' },
        { id: '', text: 'no id' },
        { id: 'draft-3' },
        null,
        'nope',
        { id: 'draft-4', text: 'second draft' },
      ],
    }),
    [
      { id: 'draft-1', text: 'first draft' },
      { id: 'draft-4', text: 'second draft' },
    ],
  );
  assert.deepEqual(parsePendingDrafts(undefined), []);
  assert.deepEqual(parsePendingDrafts({ drafts: 'not-an-array' }), []);
});

test('drafts are forwarded and acknowledged while the workbench is visible', async () => {
  const harness = createHarness({
    drafts: [
      { id: 'draft-1', text: 'first draft' },
      { id: 'draft-2', text: 'second draft' },
    ],
  });

  const result = await harness.poller.pollOnce();

  assert.deepEqual(result, { state: 'forwarded', forwarded: 2, acknowledged: 2 });
  assert.deepEqual(harness.forwarded, ['first draft', 'second draft']);
  assert.deepEqual(harness.acknowledged, [{ port: 34891, ids: ['draft-1', 'draft-2'] }]);
  assert.deepEqual(harness.errors, []);
});

test('a hidden workbench and a stopped sidecar cost zero requests', async () => {
  const hidden = createHarness({ visible: false, drafts: [{ id: 'draft-1', text: 'x' }] });
  assert.deepEqual(await hidden.poller.pollOnce(), { state: 'hidden', forwarded: 0, acknowledged: 0 });
  assert.deepEqual(hidden.fetches, []);

  const stopped = createHarness({ port: null, drafts: [{ id: 'draft-1', text: 'x' }] });
  assert.deepEqual(await stopped.poller.pollOnce(), {
    state: 'no-sidecar',
    forwarded: 0,
    acknowledged: 0,
  });
  assert.deepEqual(stopped.fetches, []);
});

test('an empty queue posts nothing and acknowledges nothing', async () => {
  const harness = createHarness({ drafts: [] });

  assert.deepEqual(await harness.poller.pollOnce(), { state: 'empty', forwarded: 0, acknowledged: 0 });
  assert.deepEqual(harness.forwarded, []);
  assert.deepEqual(harness.acknowledged, []);
});

test('a draft that fails to forward stays unacknowledged for the next tick', async () => {
  const harness = createHarness({
    drafts: [
      { id: 'draft-1', text: 'poison' },
      { id: 'draft-2', text: 'healthy' },
    ],
    forwardError: (text) => text === 'poison',
  });

  const result = await harness.poller.pollOnce();

  assert.deepEqual(result, { state: 'forwarded', forwarded: 1, acknowledged: 1 });
  assert.deepEqual(harness.forwarded, ['healthy']);
  assert.deepEqual(harness.acknowledged, [{ port: 34891, ids: ['draft-2'] }]);
  assert.deepEqual(harness.errors, ['forward failed for poison']);
});

test('an ack failure never reports the drafts as acknowledged', async () => {
  const harness = createHarness({
    drafts: [{ id: 'draft-1', text: 'draft' }],
    ackError: 'ack rejected',
  });

  const result = await harness.poller.pollOnce();

  assert.equal(result.forwarded, 1);
  assert.equal(result.acknowledged, 0);
  assert.deepEqual(harness.acknowledged, []);
  assert.deepEqual(harness.errors, ['ack rejected']);
});

test('the interval is visibility-driven and disposed cleanly', () => {
  const { BrowserDraftPoller } = loadPoller();
  const scheduled = [];
  const cleared = [];
  let ticks = 0;
  const poller = new BrowserDraftPoller({
    getSidecarPort: () => 34891,
    isWorkbenchVisible: () => false,
    fetchPendingDrafts: async () => ({ drafts: [] }),
    acknowledgeDrafts: async () => undefined,
    forwardDraft: async () => undefined,
    setIntervalFn: (handler, intervalMs) => {
      scheduled.push({ handler, intervalMs });
      return { handler, intervalMs };
    },
    clearIntervalFn: (timer) => {
      cleared.push(timer.intervalMs);
    },
  });

  poller.start();
  poller.start();
  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].intervalMs, 3000);

  scheduled[0].handler();
  assert.equal(typeof scheduled[0].handler, 'function');
  ticks += 1;

  poller.stop();
  poller.stop();
  assert.deepEqual(cleared, [3000]);
  assert.equal(poller.running, false);
  assert.equal(ticks, 1);
});

test('the capture runtime forwards pending drafts as ui/coachDraftPrefill and acknowledges them', async () => {
  const { createBrowserCaptureRuntime } = loadRuntime();
  const { BROWSER_CAPTURE } = require(constantsModulePath);
  const posts = [];
  const requests = [];
  const runtime = createBrowserCaptureRuntime({
    sidecarClient: {
      async getJson(port, requestPath) {
        requests.push({ kind: 'get', port, requestPath });
        return { drafts: [{ id: 'draft-7', text: 'prefilled coach draft' }] };
      },
      async postJson(port, requestPath, body) {
        requests.push({ kind: 'post', port, requestPath, body });
        return {};
      },
      async deleteJson() {
        return {};
      },
    },
    getSidecarStatus: () => ({ lifecycle: 'ready', port: 34891 }),
    ensureSidecarPort: async () => 34891,
    workbench: {
      show: async () => undefined,
      postMessage: async (message) => {
        posts.push(message);
      },
      isVisible: () => true,
    },
    outputChannel: { appendLine() {} },
  });

  try {
    const result = await runtime.drafts.pollOnce();

    assert.equal(result.forwarded, 1);
    assert.deepEqual(posts, [{ type: 'ui/coachDraftPrefill', text: 'prefilled coach draft' }]);
    assert.deepEqual(requests, [
      { kind: 'get', port: 34891, requestPath: BROWSER_CAPTURE.pendingDraftsPath },
      {
        kind: 'post',
        port: 34891,
        requestPath: BROWSER_CAPTURE.pendingDraftsAckPath,
        body: { ids: ['draft-7'] },
      },
    ]);
  } finally {
    runtime.dispose();
  }
});

test('the capture runtime stays silent while no workbench surface is visible', async () => {
  const { createBrowserCaptureRuntime } = loadRuntime();
  const posts = [];
  const requests = [];
  const runtime = createBrowserCaptureRuntime({
    sidecarClient: {
      async getJson(port, requestPath) {
        requests.push(requestPath);
        return { drafts: [{ id: 'draft-1', text: 'ignored while hidden' }] };
      },
      async postJson() {
        return {};
      },
      async deleteJson() {
        return {};
      },
    },
    getSidecarStatus: () => ({ lifecycle: 'ready', port: 34891 }),
    ensureSidecarPort: async () => 34891,
    workbench: {
      show: async () => undefined,
      postMessage: async (message) => {
        posts.push(message);
      },
      isVisible: () => false,
    },
    outputChannel: { appendLine() {} },
  });

  try {
    assert.equal((await runtime.drafts.pollOnce()).state, 'hidden');
    assert.deepEqual(posts, []);
    assert.deepEqual(requests, []);
  } finally {
    runtime.dispose();
  }
});

test('the capture runtime deep link converges on the same workbench delivery path', async () => {
  const { createBrowserCaptureRuntime } = loadRuntime();
  const events = [];
  const runtime = createBrowserCaptureRuntime({
    sidecarClient: {
      async getJson() {
        return {};
      },
      async postJson() {
        return {};
      },
      async deleteJson() {
        return {};
      },
    },
    getSidecarStatus: () => ({ lifecycle: 'stopped' }),
    ensureSidecarPort: async () => {
      throw new Error('not used');
    },
    workbench: {
      show: async () => {
        events.push('show');
      },
      postMessage: async (message) => {
        events.push(message);
      },
      isVisible: () => true,
    },
    outputChannel: { appendLine() {} },
  });

  try {
    await runtime.handleDeepLink({
      path: '/library/res-1',
      toString: () => 'vscode://local.trainer-extension/library/res-1',
    });
    assert.deepEqual(events, ['show', { type: 'ui/openResource', resourceId: 'res-1' }]);
  } finally {
    runtime.dispose();
  }
});
