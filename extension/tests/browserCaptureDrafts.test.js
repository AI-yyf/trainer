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
  workspaceId = 'workspace-a',
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
    getWorkspaceId: () => workspaceId,
    fetchPendingDrafts: async (requestedPort, requestedWorkspace) => {
      fetches.push({ port: requestedPort, workspaceId: requestedWorkspace });
      return { drafts };
    },
    acknowledgeDrafts: async (requestedPort, requestedWorkspace, ids) => {
      if (ackError) {
        throw new Error(ackError);
      }
      acknowledged.push({ port: requestedPort, workspaceId: requestedWorkspace, ids });
    },
    forwardDraft: async (draft) => {
      if (forwardError && forwardError(draft.text)) {
        throw new Error(`forward failed for ${draft.text}`);
      }
      forwarded.push(draft);
    },
    onError: (message) => errors.push(message),
  });
  return { poller, forwarded, acknowledged, errors, fetches };
}

test('parsePendingDrafts keeps only drafts with an id, non-empty text and their workspace', () => {
  const { parsePendingDrafts } = loadPoller();

  assert.deepEqual(
    parsePendingDrafts({
      drafts: [
        { id: 'draft-1', workspace_id: 'workspace-a', text: 'first draft' },
        { id: 'draft-2', workspace_id: 'workspace-a', text: '   ' },
        { id: '', workspace_id: 'workspace-a', text: 'no id' },
        { id: 'draft-3', workspace_id: 'workspace-a' },
        null,
        'nope',
        { id: 'draft-4', text: 'second draft' },
        { id: 'draft-5', workspace_id: '  workspace-b  ', text: 'third draft' },
      ],
    }),
    [
      { id: 'draft-1', text: 'first draft', workspaceId: 'workspace-a' },
      { id: 'draft-4', text: 'second draft', workspaceId: '' },
      { id: 'draft-5', text: 'third draft', workspaceId: 'workspace-b' },
    ],
  );
  assert.deepEqual(parsePendingDrafts(undefined), []);
  assert.deepEqual(parsePendingDrafts({ drafts: 'not-an-array' }), []);
});

test('drafts are read and acknowledged scoped to the runtime workspace', async () => {
  const harness = createHarness({
    workspaceId: 'workspace-scoped',
    drafts: [
      { id: 'draft-1', workspace_id: 'workspace-scoped', text: 'first draft' },
      { id: 'draft-2', workspace_id: 'workspace-scoped', text: 'second draft' },
    ],
  });

  const result = await harness.poller.pollOnce();

  assert.deepEqual(result, { state: 'forwarded', forwarded: 2, acknowledged: 2 });
  assert.deepEqual(harness.fetches, [{ port: 34891, workspaceId: 'workspace-scoped' }]);
  assert.deepEqual(
    harness.forwarded.map((draft) => draft.text),
    ['first draft', 'second draft'],
  );
  assert.deepEqual(harness.acknowledged, [
    { port: 34891, workspaceId: 'workspace-scoped', ids: ['draft-1', 'draft-2'] },
  ]);
  assert.deepEqual(harness.errors, []);
});

test('a draft for another workspace is never forwarded and never acknowledged', async () => {
  const harness = createHarness({
    workspaceId: 'workspace-a',
    drafts: [
      { id: 'draft-a', workspace_id: 'workspace-a', text: 'for A' },
      { id: 'draft-b', workspace_id: 'workspace-b', text: 'for B' },
    ],
  });

  const result = await harness.poller.pollOnce();

  assert.equal(result.forwarded, 1);
  assert.deepEqual(
    harness.forwarded.map((draft) => draft.text),
    ['for A'],
  );
  assert.deepEqual(harness.acknowledged, [
    { port: 34891, workspaceId: 'workspace-a', ids: ['draft-a'] },
  ]);
  assert.deepEqual(harness.errors, [
    '1 queued draft(s) belong to another workspace and stay queued',
  ]);
});

test('a workbench without a runtime workspace makes no requests at all', async () => {
  const harness = createHarness({ workspaceId: '', drafts: [{ id: 'draft-1', text: 'x' }] });

  assert.deepEqual(await harness.poller.pollOnce(), {
    state: 'unscoped',
    forwarded: 0,
    acknowledged: 0,
  });
  assert.deepEqual(harness.fetches, []);
  assert.deepEqual(harness.forwarded, []);
  assert.deepEqual(harness.acknowledged, []);
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
  assert.deepEqual(
    harness.forwarded.map((draft) => draft.text),
    ['healthy'],
  );
  assert.deepEqual(harness.acknowledged, [
    { port: 34891, workspaceId: 'workspace-a', ids: ['draft-2'] },
  ]);
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
    getWorkspaceId: () => 'workspace-a',
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

test('a receipt confirms delivery and resolves the pending wait', async () => {
  const { DraftReceiptChannel } = loadPoller();
  const channel = new DraftReceiptChannel();
  const wait = channel.waitForReceipt('draft-1', 1_000);
  channel.notify('draft-1');
  assert.equal(await wait, true);

  // A late receipt for an already-settled wait is simply dropped.
  channel.notify('draft-1');

  const never = channel.waitForReceipt('draft-2', 5);
  assert.equal(await never, false);
});

test('the capture runtime forwards pending drafts as ui/coachDraftPrefill and acknowledges after the receipt', async () => {
  const { createBrowserCaptureRuntime } = loadRuntime();
  const { BROWSER_CAPTURE } = require(constantsModulePath);
  const posts = [];
  const requests = [];
  let runtime;
  runtime = createBrowserCaptureRuntime({
    sidecarClient: {
      async getJson(port, requestPath) {
        requests.push({ kind: 'get', port, requestPath });
        return {
          drafts: [
            { id: 'draft-7', workspace_id: 'workspace-runtime', text: 'prefilled coach draft' },
          ],
        };
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
    getWorkspaceId: () => 'workspace-runtime',
    workbench: {
      show: async () => undefined,
      // Simulate the webview: applying the prefill answers the receipt.
      postMessage: async (message) => {
        posts.push(message);
        runtime.notifyDraftApplied(message.draftId);
      },
      isVisible: () => true,
    },
    outputChannel: { appendLine() {} },
  });

  try {
    const result = await runtime.drafts.pollOnce();

    assert.equal(result.forwarded, 1);
    assert.equal(result.acknowledged, 1);
    assert.deepEqual(posts, [
      { type: 'ui/coachDraftPrefill', draftId: 'draft-7', text: 'prefilled coach draft' },
    ]);
    assert.deepEqual(requests, [
      {
        kind: 'get',
        port: 34891,
        requestPath: `${BROWSER_CAPTURE.pendingDraftsPath}?workspace_id=workspace-runtime`,
      },
      {
        kind: 'post',
        port: 34891,
        requestPath: BROWSER_CAPTURE.pendingDraftsAckPath,
        body: { workspace_id: 'workspace-runtime', ids: ['draft-7'] },
      },
    ]);
  } finally {
    runtime.dispose();
  }
});

test('a forwarded draft is acknowledged only after the workbench receipt arrives', async () => {
  const { createBrowserCaptureRuntime } = loadRuntime();
  const { BROWSER_CAPTURE } = require(constantsModulePath);
  const posts = [];
  const requests = [];
  const runtime = createBrowserCaptureRuntime({
    sidecarClient: {
      async getJson(port, requestPath) {
        requests.push({ kind: 'get', port, requestPath });
        return { drafts: [{ id: 'draft-9', workspace_id: 'workspace-x', text: 'waiting draft' }] };
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
    getWorkspaceId: () => 'workspace-x',
    workbench: {
      show: async () => undefined,
      postMessage: async (message) => {
        posts.push(message);
      },
      isVisible: () => true,
    },
    outputChannel: { appendLine() {} },
    receiptTimeoutMs: 2_000,
  });

  try {
    const poll = runtime.drafts.pollOnce();
    // Let the poll pass post the prefill and start waiting for its receipt.
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));

    assert.deepEqual(posts, [
      { type: 'ui/coachDraftPrefill', draftId: 'draft-9', text: 'waiting draft' },
    ]);
    // No receipt yet: the queue entry must still be pending server-side.
    assert.deepEqual(
      requests.filter((entry) => entry.kind === 'post'),
      [],
    );

    runtime.notifyDraftApplied('draft-9');
    const result = await poll;

    assert.equal(result.forwarded, 1);
    assert.equal(result.acknowledged, 1);
    assert.deepEqual(
      requests.filter((entry) => entry.kind === 'post'),
      [
        {
          kind: 'post',
          port: 34891,
          requestPath: BROWSER_CAPTURE.pendingDraftsAckPath,
          body: { workspace_id: 'workspace-x', ids: ['draft-9'] },
        },
      ],
    );
  } finally {
    runtime.dispose();
  }
});

test('a draft whose receipt never arrives stays unacknowledged and is reported', async () => {
  const { createBrowserCaptureRuntime } = loadRuntime();
  const posts = [];
  const requests = [];
  const logLines = [];
  const runtime = createBrowserCaptureRuntime({
    sidecarClient: {
      async getJson() {
        return { drafts: [{ id: 'draft-11', workspace_id: 'workspace-y', text: 'lost draft' }] };
      },
      async postJson(port, requestPath, body) {
        requests.push({ requestPath, body });
        return {};
      },
      async deleteJson() {
        return {};
      },
    },
    getSidecarStatus: () => ({ lifecycle: 'ready', port: 34891 }),
    ensureSidecarPort: async () => 34891,
    getWorkspaceId: () => 'workspace-y',
    workbench: {
      show: async () => undefined,
      postMessage: async (message) => {
        posts.push(message);
      },
      isVisible: () => true,
    },
    outputChannel: { appendLine: (line) => logLines.push(line) },
    receiptTimeoutMs: 20,
  });

  try {
    const result = await runtime.drafts.pollOnce();

    assert.deepEqual(posts, [
      { type: 'ui/coachDraftPrefill', draftId: 'draft-11', text: 'lost draft' },
    ]);
    assert.equal(result.forwarded, 0);
    assert.equal(result.acknowledged, 0);
    assert.deepEqual(requests, []);
    assert.equal(
      logLines.some((line) => line.includes('draft-11 was not confirmed by the workbench')),
      true,
      logLines.join('\n'),
    );
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
    getWorkspaceId: () => 'workspace-a',
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
    getWorkspaceId: () => 'workspace-a',
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
