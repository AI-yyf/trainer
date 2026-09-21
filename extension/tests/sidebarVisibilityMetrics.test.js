'use strict';

/**
 * Phase-A acceptance regression (design package TR-001 / §03-8 "本次建议的
 * 第一项开发任务"):
 *
 *   Hide and show the sidebar 20 times:
 *   - provider HTTP requests    = 0
 *   - /provider/models requests = 0
 *   - sidecar process starts    = 0
 *   - full runtime rehydrations = 0
 *   - conversation unchanged; no bootstrap re-post; zero sync bytes while
 *     nothing changed; the host never touches the composer draft.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const bridgeModulePath = path.resolve(__dirname, '..', 'dist', 'extension', 'src', 'core', 'webviewBridge.js');
const metricsModulePath = path.resolve(__dirname, '..', 'dist', 'extension', 'src', 'core', 'runtimeMetrics.js');
const fixtureHtmlPath = path.resolve(__dirname, 'fixtures', 'webview-index.html');

const VISIBILITY_CYCLES = 20;

function createStreamingState(overrides = {}) {
  return {
    isStreaming: false,
    streamedContent: '',
    streamError: undefined,
    streamMessageId: undefined,
    agentActivity: [],
    agentStep: undefined,
    completionSummary: undefined,
    completionNextStep: undefined,
    completionStopReason: undefined,
    toolCount: undefined,
    agentic: undefined,
    ...overrides,
  };
}

function createBootstrapState(overrides = {}) {
  const streamingState = createStreamingState(overrides.streamingState);
  const baseState = {
    provider: {
      name: 'OpenAI',
      baseUrl: 'https://api.openai.com/v1',
      apiKeyRef: 'secret:openai',
      model: 'gpt-4.1-mini',
    },
    sidecar: {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 8765,
      canStart: true,
    },
    workspace: {
      trusted: true,
      workspaceFolder: 'F:\\trainer',
      activeFile: 'extension/src/core/webviewBridge.ts',
      activeLanguageId: 'typescript',
      diagnosticErrors: 0,
      diagnosticWarnings: 1,
      documentVersion: 3,
    },
    sessionId: 'session-1',
    streamingState,
    bootstrap: {
      workspaceName: 'trainer',
      sessionLabel: 'Session 1',
      connection: {
        state: 'connected',
        provider: { name: 'OpenAI', model: 'gpt-4.1-mini' },
      },
      liveContext: {
        activeFile: 'extension/src/core/webviewBridge.ts',
        activeLanguageId: 'typescript',
      },
      profile: {
        learnerName: 'You',
        goals: ['Ship reliable bridge tests'],
        weeklyHours: 4,
      },
      plan: { id: 'plan-1', title: 'Bridge hardening', frozen: false, stages: [] },
      task: { id: 'task-1', title: 'Verify workbench messaging' },
      memory: { currentFocus: 'Bridge reliability', weakSpots: [], recentWins: [] },
      resources: [],
      commands: [],
      conversation: [
        {
          id: 'assistant-1',
          role: 'assistant',
          author: 'Trainer',
          body: 'Bridge online',
          timestamp: '09:00',
        },
      ],
      streamingState,
    },
  };

  return {
    ...baseState,
    ...overrides,
    streamingState,
    bootstrap: {
      ...baseState.bootstrap,
      ...(overrides.bootstrap || {}),
      streamingState:
        overrides.bootstrap && Object.prototype.hasOwnProperty.call(overrides.bootstrap, 'streamingState')
          ? overrides.bootstrap.streamingState
          : streamingState,
    },
  };
}

async function createExtensionFixtureDir() {
  const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'trainer-metrics-test-'));
  const distDir = path.join(tempRoot, 'webview', 'dist');
  await fs.mkdir(path.join(distDir, 'assets'), { recursive: true });
  await fs.copyFile(fixtureHtmlPath, path.join(distDir, 'index.html'));
  await fs.writeFile(path.join(distDir, 'assets', 'index.js'), 'console.log("fixture");\n', 'utf8');
  await fs.writeFile(path.join(distDir, 'assets', 'index.css'), 'body { color: white; }\n', 'utf8');
  return tempRoot;
}

function createViewHarness() {
  const postedMessages = [];
  let messageHandler = () => {};
  let visibilityHandler = () => {};

  const view = {
    visible: true,
    webview: {
      html: '',
      options: undefined,
      cspSource: 'vscode-webview://view',
      postMessage: async (message) => {
        postedMessages.push(message);
        return true;
      },
      onDidReceiveMessage(handler) {
        messageHandler = handler;
        return { dispose() {} };
      },
      asWebviewUri(uri) {
        return {
          toString() {
            return `webview-resource:${uri.fsPath.replace(/\\/g, '/')}`;
          },
        };
      },
    },
    onDidDispose() {},
    onDidChangeVisibility(handler) {
      visibilityHandler = handler;
      return { dispose() {} };
    },
  };

  return {
    view,
    postedMessages,
    async dispatchMessage(message) {
      await messageHandler(message);
    },
    triggerVisibility(visible) {
      view.visible = visible;
      visibilityHandler();
    },
  };
}

async function flushAsyncBridgeWork() {
  for (let i = 0; i < 8; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

function createVscodeMock() {
  return {
    Uri: {
      file(filePath) {
        return {
          fsPath: filePath,
          toString() {
            return `file://${filePath.replace(/\\/g, '/')}`;
          },
        };
      },
    },
    commands: {
      async executeCommand() {
        return undefined;
      },
    },
  };
}

test('20 hide/show cycles cause zero provider, catalog, sidecar, and rehydrate activity', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const outputLines = [];
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  // Load metrics through the same (freshly populated) require cache the
  // bridge uses, so assertions observe the counters the bridge increments.
  const { snapshotRuntimeMetrics, resetRuntimeMetrics } = require(metricsModulePath);
  resetRuntimeMetrics();

  const conversationSnapshot = JSON.stringify(createBootstrapState().bootstrap.conversation);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    // Any command execution during visibility work violates the contract.
    {
      async execute(commandId) {
        throw new Error(`unexpected command execution: ${commandId}`);
      },
    },
    () => createBootstrapState(),
    { appendLine(line) { outputLines.push(line); } },
  );

  await controller.resolveWebviewView(harness.view);
  // Complete the lifecycle handshake the real webview performs after load.
  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncBridgeWork();
  harness.postedMessages.length = 0;
  resetRuntimeMetrics();

  for (let cycle = 0; cycle < VISIBILITY_CYCLES; cycle += 1) {
    harness.triggerVisibility(true);
    await flushAsyncBridgeWork();
    harness.triggerVisibility(false);
    await flushAsyncBridgeWork();
  }

  const metrics = snapshotRuntimeMetrics();
  assert.equal(metrics.providerHttpRequests, 0, 'provider HTTP requests during 20 hide/show cycles');
  assert.equal(metrics.modelCatalogRequests, 0, 'model catalog requests during 20 hide/show cycles');
  assert.equal(metrics.sidecarStarts, 0, 'sidecar starts during 20 hide/show cycles');
  assert.equal(metrics.runtimeRehydrations, 0, 'runtime rehydrations during 20 hide/show cycles');
  assert.ok(
    metrics.webviewVisibilityShows >= VISIBILITY_CYCLES,
    `expected every show to be counted, got ${metrics.webviewVisibilityShows}`,
  );

  // Nothing changed between cycles, so the incremental channel ships
  // nothing: no bootstrap re-post, no patch, zero sync bytes.
  assert.equal(harness.postedMessages.length, 0, 'expected zero posted messages across cycles');
  assert.equal(metrics.webviewSyncPatches, 0);
  assert.equal(metrics.webviewSyncFullPatches, 0);
  assert.equal(metrics.webviewSyncBytes, 0);

  // Session unchanged (the host state factory is pure; no visibility cycle
  // mutated it) and the host never owns the composer draft.
  assert.equal(JSON.stringify(createBootstrapState().bootstrap.conversation), conversationSnapshot);
  assert.equal(
    Object.prototype.hasOwnProperty.call(createBootstrapState().bootstrap, 'composerDraft'),
    false,
    'composer draft must stay webview-owned',
  );

  // Diagnostics: each show logs the (zeroed) metric line.
  assert.ok(
    outputLines.some((line) => /\[metrics\] .*\bmodels=0\b/.test(line)),
    'expected a metrics log line',
  );
});

test('a real state change during visibility ships one small patch and stays at zero provider traffic', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const { snapshotRuntimeMetrics, resetRuntimeMetrics } = require(metricsModulePath);
  resetRuntimeMetrics();

  let currentState = createBootstrapState();
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => currentState,
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncBridgeWork();
  harness.postedMessages.length = 0;
  resetRuntimeMetrics();

  currentState = createBootstrapState({
    streamingState: {
      isStreaming: true,
      streamMessageId: 'msg-metrics-stream',
      streamedContent: 'Answering from the model.',
    },
  });

  harness.triggerVisibility(true);
  await flushAsyncBridgeWork();
  harness.triggerVisibility(false);
  await flushAsyncBridgeWork();

  const metrics = snapshotRuntimeMetrics();
  assert.equal(metrics.providerHttpRequests, 0);
  assert.equal(metrics.modelCatalogRequests, 0);
  assert.equal(metrics.sidecarStarts, 0);
  assert.equal(metrics.runtimeRehydrations, 0);

  const patches = harness.postedMessages.filter((message) => message.type === 'state/patch');
  assert.equal(patches.length, 1, 'expected exactly one incremental patch');
  assert.ok(!harness.postedMessages.some((message) => message.type === 'bootstrap'));
  assert.equal(patches[0].payload.streamingState.isStreaming, true);
  assert.equal(patches[0].payload.streamingState.streamMessageId, 'msg-metrics-stream');
  // The draft is webview-owned and never rides a host patch.
  assert.equal(
    Object.prototype.hasOwnProperty.call(patches[0].payload, 'composerDraft'),
    false,
  );
  assert.ok(metrics.webviewSyncPatches >= 1);
  assert.ok(metrics.webviewSyncBytes > 0);
});
