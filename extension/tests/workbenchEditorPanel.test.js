'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const panelModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchPanel.js',
);
const fixtureHtmlPath = path.resolve(__dirname, 'fixtures', 'webview-index.html');

async function createExtensionFixtureDir() {
  const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'trainer-panel-test-'));
  const distDir = path.join(tempRoot, 'webview', 'dist');
  await fs.mkdir(path.join(distDir, 'assets'), { recursive: true });
  await fs.copyFile(fixtureHtmlPath, path.join(distDir, 'index.html'));
  await fs.writeFile(path.join(distDir, 'assets', 'index.js'), 'console.log("fixture");\n', 'utf8');
  await fs.writeFile(path.join(distDir, 'assets', 'index.css'), 'body { color: white; }\n', 'utf8');
  return tempRoot;
}

function createHostState() {
  return {
    provider: undefined,
    sidecar: { lifecycle: 'ready', host: '127.0.0.1', port: 8765, canStart: true },
    workspace: {
      trusted: true,
      workspaceFolder: 'F:\\trainer',
      activeFile: 'extension/src/core/workbenchPanel.ts',
      activeLanguageId: 'typescript',
      diagnosticErrors: 0,
      diagnosticWarnings: 0,
      documentVersion: 1,
    },
    sessionId: 'session-panel-1',
    streamingState: { isStreaming: false, streamedContent: '', agentActivity: [] },
    bootstrap: {
      workspaceName: 'trainer',
      sessionLabel: 'Panel session',
      connection: { state: 'connected' },
      liveContext: { activeFile: 'extension/src/core/workbenchPanel.ts' },
      plan: { id: 'plan-1', title: 'Panel plan', frozen: false, stages: [] },
      task: undefined,
      memory: { currentFocus: 'Panel surface', weakSpots: [], recentWins: [] },
      resources: [],
      conversation: [],
      streamingState: { isStreaming: false, streamedContent: '', agentActivity: [] },
    },
  };
}

function createPanelHarness({ autoAck = true } = {}) {
  const postedMessages = [];
  const webview = {
    html: '',
    options: undefined,
    cspSource: 'vscode-webview://panel',
    async postMessage(message) {
      postedMessages.push(message);
      if (autoAck && message.sync) {
        queueMicrotask(() => messageHandler({ type: 'state/ack', payload: {
          ...message.sync, status: 'applied', appliedRevision: message.sync.revision,
        } }));
      }
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
  };
  let messageHandler = () => {};
  let disposeHandler = () => {};
  let viewStateHandler = () => {};
  let disposed = false;
  const panel = {
    webview,
    active: true,
    visible: true,
    title: 'Trainer',
    revealCalls: 0,
    reveal() {
      panel.revealCalls += 1;
    },
    onDidDispose(handler) {
      disposeHandler = handler;
      return { dispose() {} };
    },
    onDidChangeViewState(handler) {
      viewStateHandler = handler;
      return { dispose() {} };
    },
    dispose() {
      if (disposed) {
        return;
      }
      disposed = true;
      disposeHandler();
    },
    get isDisposed() {
      return disposed;
    },
  };
  return {
    panel,
    postedMessages,
    async dispatchMessage(message) {
      await messageHandler(message);
    },
    triggerViewState() {
      viewStateHandler();
    },
  };
}

function createVscodeMock({ panelHarness }) {
  const executedCommands = [];
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
    ViewColumn: { Active: -1 },
    window: {
      createWebviewPanel(viewType, title, column, options) {
        const created = { viewType, title, column, options };
        panelHarness.created = created;
        return panelHarness.panel;
      },
    },
    commands: {
      async executeCommand(commandId) {
        executedCommands.push(commandId);
        return undefined;
      },
    },
    __executedCommands: executedCommands,
  };
}

async function flushAsyncWork() {
  await new Promise((resolve) => setImmediate(resolve));
}

test('open() creates a full-width panel on the same webview bundle and focuses the requested view', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createPanelHarness();
  const vscodeMock = createVscodeMock({ panelHarness: harness });
  const outputLines = [];
  const { WorkbenchEditorPanel } = loadWithVscodeMock(panelModulePath, vscodeMock);
  const panel = new WorkbenchEditorPanel(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createHostState(),
    { appendLine(line) { outputLines.push(line); } },
    async () => undefined,
  );

  await panel.open('resources');

  assert.deepEqual(harness.created, {
    viewType: 'trainer.workbench',
    title: 'Trainer',
    column: -1,
    options: {
      enableScripts: true,
      localResourceRoots: [{ fsPath: extensionPath }],
      retainContextWhenHidden: true,
    },
  });
  assert.match(harness.panel.webview.html, /window\.__TRAINER_BOOTSTRAP__/);
  assert.match(harness.panel.webview.html, /window\.__TRAINER_SURFACE__ = "editor"/);

  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncWork();

  const restore = harness.postedMessages.find((message) => message.type === 'ui/restoreView');
  assert.deepEqual(restore.payload, { activeView: 'resources' });
  const bootstrap = harness.postedMessages.find((message) => message.type === 'bootstrap');
  assert.equal(bootstrap.sync.baseRevision, 0);
  assert.equal(bootstrap.payload.sessionLabel, 'Panel session');
  panel.dispose();
});

test('panel commands route through the shared registry and post a reconciled state patch', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createPanelHarness();
  const commandCalls = [];
  const vscodeMock = createVscodeMock({ panelHarness: harness });
  const { WorkbenchEditorPanel } = loadWithVscodeMock(panelModulePath, vscodeMock);
  let state = createHostState();
  const panel = new WorkbenchEditorPanel(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute(commandId, payload) {
        commandCalls.push({ commandId, payload });
        state = { ...state, bootstrap: { ...state.bootstrap, memory: { ...state.bootstrap.memory, currentFocus: 'Panel command ran' } } };
        return { ok: true, message: 'Resource opened.' };
      },
    },
    () => state,
    { appendLine() {} },
    async () => undefined,
  );

  await panel.open('resources');
  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncWork();
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({ type: 'resource/open', payload: { resourceId: 'resource-9' } });
  await flushAsyncWork();

  assert.deepEqual(commandCalls, [
    { commandId: 'trainer.resource.open', payload: { resourceId: 'resource-9' } },
  ]);
  assert.deepEqual(
    harness.postedMessages.map((message) => message.type),
    ['operation/status', 'state/patch'],
  );
  assert.equal(harness.postedMessages[0].payload.tone, 'success');
  assert.equal(harness.postedMessages[1].payload.memory.currentFocus, 'Panel command ran');
  panel.dispose();
});

test('collapseToSidebar disposes the panel and reveals the sidebar host', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createPanelHarness();
  const vscodeMock = createVscodeMock({ panelHarness: harness });
  let revealCalls = 0;
  const { WorkbenchEditorPanel } = loadWithVscodeMock(panelModulePath, vscodeMock);
  const panel = new WorkbenchEditorPanel(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createHostState(),
    { appendLine() {} },
    async () => { revealCalls += 1; },
  );

  await panel.open('plan');
  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncWork();

  await harness.dispatchMessage({ type: 'ui/collapseToSidebar' });
  await flushAsyncWork();

  assert.equal(panel.isOpen, false);
  assert.equal(harness.panel.isDisposed, true);
  assert.equal(revealCalls, 1);
  panel.dispose();
});

test('a second open() reuses and reveals the existing panel', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createPanelHarness();
  const vscodeMock = createVscodeMock({ panelHarness: harness });
  const { WorkbenchEditorPanel } = loadWithVscodeMock(panelModulePath, vscodeMock);
  const panel = new WorkbenchEditorPanel(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createHostState(),
    { appendLine() {} },
    async () => undefined,
  );

  await panel.open('plan');
  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncWork();
  harness.postedMessages.length = 0;

  await panel.open('resources');
  await flushAsyncWork();

  assert.equal(harness.panel.revealCalls, 1);
  const restore = harness.postedMessages.find((message) => message.type === 'ui/restoreView');
  assert.deepEqual(restore.payload, { activeView: 'resources' });
  panel.dispose();
});
