'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const bridgeModulePath = path.resolve(__dirname, '..', 'dist', 'extension', 'src', 'core', 'webviewBridge.js');
const commandRegistryModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'commandRegistry.js',
);
const resourceCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'resourceCommands.js',
);
const workbenchDataModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchData.js',
);
const fixtureHtmlPath = path.resolve(__dirname, 'fixtures', 'webview-index.html');
const { patchHostState } = require(workbenchDataModulePath);

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
      capabilities: {
        chat: true,
        responses: true,
        vision: true,
        embeddings: true,
        tools: false,
        jsonSchema: false,
        streaming: true,
      },
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
        provider: {
          name: 'OpenAI',
          model: 'gpt-4.1-mini',
          capabilities: {
            chat: true,
            responses: true,
            vision: true,
            embeddings: true,
            tools: false,
            jsonSchema: false,
            streaming: true,
          },
        },
      },
      liveContext: {
        activeFile: 'extension/src/core/webviewBridge.ts',
        activeLanguageId: 'typescript',
        diagnosticsSummary: '0 errors, 1 warnings',
        documentVersion: 3,
      },
      profile: {
        learnerName: 'You',
        goals: ['Ship reliable bridge tests'],
        weeklyHours: 4,
        preferredStyle: 'Coach first',
        answerPolicy: 'coach-first',
        focusAreas: ['extension-host'],
      },
      plan: {
        id: 'plan-1',
        title: 'Bridge hardening',
        frozen: false,
        cadence: '4 hours / week',
        summary: 'Add bridge verification.',
        stages: [],
      },
      task: {
        id: 'task-1',
        title: 'Verify workbench messaging',
        description: 'Cover host/webview contracts.',
        constraints: ['Keep it lightweight'],
        acceptanceCriteria: ['Bootstrap and patch messages stay stable'],
        nextActionLabel: 'Evaluate current file',
      },
      evaluation: {
        headline: 'No evaluation run yet',
        summary: 'Pending',
        passRate: 0,
        updatedAt: 'Now',
        checks: [],
        nextStep: 'Run tests',
      },
      memory: {
        currentFocus: 'Bridge reliability',
        weakSpots: [],
        recentWins: [],
        reviewSummary: 'Ready',
      },
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
  const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'trainer-webview-test-'));
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
  let disposeHandler = () => {};
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
    onDidDispose(handler) {
      disposeHandler = handler;
      return { dispose() {} };
    },
    onDidChangeVisibility(handler) {
      visibilityHandler = handler;
      return { dispose() {} };
    },
    dispose() {
      disposeHandler();
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

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function flushAsyncBridgeWork() {
  await new Promise((resolve) => setImmediate(resolve));
}

function createVscodeMock(overrides = {}) {
  const executedCommands = [];

  const base = {
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
      async executeCommand(commandId) {
        executedCommands.push(commandId);
        return undefined;
      },
    },
  };

  return {
    ...base,
    ...overrides,
    Uri: {
      ...base.Uri,
      ...(overrides.Uri || {}),
    },
    commands: {
      ...base.commands,
      ...(overrides.commands || {}),
    },
    __executedCommands: executedCommands,
  };
}

test('resolveWebviewView wires HTML and posts bootstrap state', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const executed = [];
  const commandRegistry = {
    async execute() {
      executed.push('executed');
      return { ok: true, message: 'noop' };
    },
  };
  const outputLines = [];
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    commandRegistry,
    () => createBootstrapState(),
    { appendLine(line) { outputLines.push(line); } },
  );

  await controller.resolveWebviewView(harness.view);

  assert.match(harness.view.webview.html, /window\.__TRAINER_BOOTSTRAP__/);
  assert.equal(harness.postedMessages[0].type, 'bootstrap');
  assert.equal(executed.length, 0);
  assert.deepEqual(outputLines, [
    '[webview] resolve start',
    '[webview] html refreshed (resolve)',
    '[webview] html ready',
    '[webview] bootstrap posted',
  ]);
});

test('show reveals the trainer sidebar container and focus command when available', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.show();

  assert.deepEqual(vscodeMock.__executedCommands, [
    'workbench.view.extension.trainer',
    'trainer.sidebar.focus',
  ]);
});

test('request/bootstrap posts a full state patch without executing host commands', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const executedCommands = [];
  let refreshCalls = 0;
  const commandRegistry = {
    async execute(commandId) {
      executedCommands.push(commandId);
      return { ok: true, message: 'noop' };
    },
  };
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    commandRegistry,
    () => createBootstrapState(),
    { appendLine() {} },
  );
  controller.setRefreshHandler(async () => {
    refreshCalls += 1;
  });

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({ type: 'request/bootstrap' });
  await flushAsyncBridgeWork();

  assert.equal(executedCommands.length, 0);
  assert.equal(refreshCalls, 1);
  assert.equal(harness.postedMessages[0].type, 'bootstrap');
  assert.equal(harness.postedMessages[1].type, 'state/patch');
});

test('settings auto-prime executes quietly without posting operation status', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const commandCalls = [];
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute(commandId, payload) {
        commandCalls.push({ commandId, payload });
        return { ok: true, message: 'Primed quietly.' };
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'settings/primeProviderModels',
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(commandCalls, [
    {
      commandId: 'trainer.provider.primeModels',
      payload: undefined,
    },
  ]);
  assert.equal(
    harness.postedMessages.some((message) => message.type === 'operation/status'),
    false,
  );
  assert.equal(harness.postedMessages[0].type, 'state/patch');
});

test('visibility recovery rehydrates empty html and syncs state again', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const outputLines = [];
  let refreshCalls = 0;
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createBootstrapState(),
    { appendLine(line) { outputLines.push(line); } },
  );
  controller.setRefreshHandler(async () => {
    refreshCalls += 1;
  });

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;
  harness.view.webview.html = '';

  harness.triggerVisibility(true);
  await sleep(320);
  await flushAsyncBridgeWork();

  assert.match(harness.view.webview.html, /window\.__TRAINER_BOOTSTRAP__/);
  assert.ok(refreshCalls >= 1);
  assert.ok(harness.postedMessages.some((message) => message.type === 'bootstrap'));
  assert.ok(harness.postedMessages.some((message) => message.type === 'state/patch'));
  assert.ok(outputLines.some((line) => /\[webview\] visible -> rehydrating state/.test(line)));
});

test('visibility rehydration keeps rendered html when the lifecycle is already healthy', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  let refreshCalls = 0;
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createBootstrapState(),
    { appendLine() {} },
  );
  controller.setRefreshHandler(async () => {
    refreshCalls += 1;
  });

  await controller.resolveWebviewView(harness.view);
  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncBridgeWork();

  const initialHtml = harness.view.webview.html;
  harness.postedMessages.length = 0;

  harness.triggerVisibility(true);
  await sleep(320);
  await flushAsyncBridgeWork();

  assert.equal(harness.view.webview.html, initialHtml);
  assert.ok(refreshCalls >= 1);
  assert.ok(harness.postedMessages.some((message) => message.type === 'bootstrap'));
  assert.ok(harness.postedMessages.some((message) => message.type === 'state/patch'));
});

test('visibility rehydration posts the latest in-progress streaming truth', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  let currentState = createBootstrapState();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => currentState,
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncBridgeWork();

  const initialHtml = harness.view.webview.html;
  currentState = createBootstrapState({
    streamingState: {
      isStreaming: true,
      streamMessageId: 'msg-running-visibility',
      streamedContent: 'Checking the workspace context...',
      agentStep: 1,
      agentActivity: [
        {
          id: 'inspect-plan',
          name: 'inspect_plan',
          status: 'succeeded',
          result: { summary: 'Plan anchor found.' },
          step: 1,
        },
        {
          id: 'recall-memory',
          name: 'recall_memory',
          status: 'running',
          step: 1,
        },
      ],
    },
  });
  harness.postedMessages.length = 0;

  harness.triggerVisibility(true);
  await sleep(320);
  await flushAsyncBridgeWork();

  const bootstrap = harness.postedMessages.find((message) => message.type === 'bootstrap');
  const patch = harness.postedMessages.find((message) => message.type === 'state/patch');
  assert.equal(harness.view.webview.html, initialHtml);
  assert.equal(bootstrap.payload.streamingState.isStreaming, true);
  assert.equal(bootstrap.payload.streamingState.streamMessageId, 'msg-running-visibility');
  assert.equal(bootstrap.payload.streamingState.streamedContent, 'Checking the workspace context...');
  assert.equal(bootstrap.payload.streamingState.agentStep, 1);
  assert.equal(bootstrap.payload.streamingState.agentActivity[0].name, 'inspect_plan');
  assert.equal(
    bootstrap.payload.streamingState.agentActivity[0].result.summary,
    'Plan anchor found.',
  );
  assert.equal(bootstrap.payload.streamingState.agentActivity[1].name, 'recall_memory');
  assert.equal(bootstrap.payload.streamingState.agentActivity[1].status, 'running');
  assert.deepEqual(patch.payload.streamingState, bootstrap.payload.streamingState);
});

test('visibility recovery with empty html rehydrates the latest completed streaming snapshot', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  let currentState = createBootstrapState();
  let refreshCalls = 0;
  const outputLines = [];
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => currentState,
    { appendLine(line) { outputLines.push(line); } },
  );
  controller.setRefreshHandler(async () => {
    refreshCalls += 1;
  });

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;
  currentState = createBootstrapState({
    streamingState: {
      isStreaming: false,
      streamMessageId: 'msg-complete-visibility',
      streamedContent: 'Apply the smallest verified patch.',
      completionSummary: 'Checked the workspace context first.',
      completionNextStep: 'Apply the smallest verified patch.',
      toolCount: 2,
      agentic: true,
      agentActivity: [
        {
          id: 'inspect-plan',
          name: 'inspect_plan',
          status: 'succeeded',
          result: { summary: 'Plan anchor found.' },
          step: 0,
        },
      ],
    },
  });
  harness.view.webview.html = '';

  harness.triggerVisibility(true);
  await sleep(320);
  await flushAsyncBridgeWork();

  const bootstrap = harness.postedMessages.find((message) => message.type === 'bootstrap');
  const patch = harness.postedMessages.find((message) => message.type === 'state/patch');
  assert.match(harness.view.webview.html, /window\.__TRAINER_BOOTSTRAP__/);
  assert.ok(refreshCalls >= 1);
  assert.ok(outputLines.some((line) => /\[webview\] visible -> rehydrating state/.test(line)));
  assert.equal(bootstrap.payload.streamingState.isStreaming, false);
  assert.equal(bootstrap.payload.streamingState.streamMessageId, 'msg-complete-visibility');
  assert.equal(
    bootstrap.payload.streamingState.completionSummary,
    'Checked the workspace context first.',
  );
  assert.equal(
    bootstrap.payload.streamingState.completionNextStep,
    'Apply the smallest verified patch.',
  );
  assert.equal(bootstrap.payload.streamingState.toolCount, 2);
  assert.equal(bootstrap.payload.streamingState.agentic, true);
  assert.equal(bootstrap.payload.streamingState.agentActivity[0].result.summary, 'Plan anchor found.');
  assert.deepEqual(patch.payload.streamingState, bootstrap.payload.streamingState);
});

test('plan freeze messages route through the registry and emit status then patch', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const commandCalls = [];
  const commandRegistry = {
    async execute(commandId, payload) {
      commandCalls.push({ commandId, payload });
      return { ok: true, message: 'Plan frozen.' };
    },
  };
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    commandRegistry,
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'plan/freeze',
    payload: { frozen: true },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(commandCalls, [
    {
      commandId: 'trainer.plan.update',
      payload: { frozen: true },
    },
  ]);
  assert.equal(harness.postedMessages[0].type, 'operation/status');
  assert.equal(harness.postedMessages[0].payload.message, 'Plan frozen.');
  assert.equal(harness.postedMessages[1].type, 'state/patch');
});

test('webview template setup syncs state before restoring Settings focus to the API key', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const commandRegistry = {
    async execute(commandId, payload) {
      assert.equal(commandId, 'trainer.provider.useTemplate');
      assert.deepEqual(payload, { templateLabel: 'MiniMax', skipPicker: true });
      return {
        ok: true,
        message: 'Provider template applied.',
        ui: { focusProviderApiKey: true },
      };
    },
  };
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    commandRegistry,
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.provider.useTemplate',
      payload: { templateLabel: 'MiniMax', skipPicker: true },
    },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(harness.postedMessages.map((message) => message.type), [
    'state/patch',
    'ui/restoreView',
    'operation/status',
  ]);
  assert.deepEqual(harness.postedMessages[1], {
    type: 'ui/restoreView',
    payload: { activeView: 'settings', focusProviderApiKey: true },
  });
});

test('cancelled resource commands only resync the view without showing an error', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const commandRegistry = {
    async execute() {
      return { ok: false, cancelled: true };
    },
  };
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    commandRegistry,
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'resource/upload',
    payload: { mode: 'files' },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(harness.postedMessages.map((message) => message.type), ['state/patch']);
});

test('resource mutations echo their operation id in success and failure status messages', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const commandCalls = [];
  const commandRegistry = {
    async execute(commandId, payload) {
      commandCalls.push({ commandId, payload });
      return { ok: false, message: 'Could not delete the selected resource.' };
    },
  };
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    commandRegistry,
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.resource.delete',
      payload: {
        resourceIds: ['resource-1'],
        __trainerResourceOperationId: 'resource-operation-test-1',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(commandCalls, [
    {
      commandId: 'trainer.resource.delete',
      payload: {
        resourceIds: ['resource-1'],
        __trainerResourceOperationId: 'resource-operation-test-1',
      },
    },
  ]);
  assert.deepEqual(harness.postedMessages[0], {
    type: 'operation/status',
    payload: {
      tone: 'error',
      message:
        '[[trainer-resource-operation:delete:resource-operation-test-1]] Could not delete the selected resource.',
    },
  });
  assert.equal(harness.postedMessages[1].type, 'state/patch');
});

test('resource indexing echoes its operation id so the webview can release its busy state', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute() {
        return { ok: true, message: 'Resource index refreshed.' };
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.resource.index',
      payload: { __trainerResourceOperationId: 'resource-index-bridge-1' },
    },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(harness.postedMessages[0], {
    type: 'operation/status',
    payload: {
      tone: 'success',
      message:
        '[[trainer-resource-operation:index:resource-index-bridge-1]] Resource index refreshed.',
    },
  });
  assert.equal(harness.postedMessages[1].type, 'state/patch');
});

test('resource search statuses echo their request id', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute() {
        return { ok: true, message: 'Found 1 ranked resource.' };
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.resource.search',
      payload: {
        query: 'notes',
        requestId: 'resource-search-bridge-1',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(harness.postedMessages[0], {
    type: 'operation/status',
    payload: {
      tone: 'success',
      message:
        '[[trainer-resource-operation:search:resource-search-bridge-1]] Found 1 ranked resource.',
    },
  });
  assert.equal(harness.postedMessages[1].type, 'state/patch');
});

test('resource search failures echo their request id', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute() {
        return { ok: false, message: 'Workspace trust is required to search resources.' };
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.resource.search',
      payload: {
        query: 'notes',
        requestId: 'resource-search-failure-1',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(harness.postedMessages[0], {
    type: 'operation/status',
    payload: {
      tone: 'error',
      message:
        '[[trainer-resource-operation:search:resource-search-failure-1]] Workspace trust is required to search resources.',
    },
  });
});

test('training persistence acknowledgement follows the reconciled state snapshot', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  let revision = 0;
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute(commandId, payload) {
        assert.equal(commandId, 'trainer.training.flashcardAnswer');
        assert.equal(payload.cardId, 'card-1');
        assert.equal(payload.learnerAnswer, 'The route validates input first.');
        revision += 1;
        return { ok: true, message: 'Flashcard answer recorded.' };
      },
    },
    () => {
      const state = createBootstrapState();
      state.bootstrap.memory.currentFocus = `revision-${revision}`;
      return state;
    },
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.training.flashcardAnswer',
      payload: {
        cardId: 'card-1',
        learnerAnswer: 'The route validates input first.',
        __trainerTrainingPersistenceId: 'training-persistence-bridge-1',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.equal(harness.postedMessages[0].type, 'state/patch');
  assert.equal(harness.postedMessages[0].payload.memory.currentFocus, 'revision-1');
  assert.deepEqual(harness.postedMessages[1], {
    type: 'training/persistenceAck',
    payload: {
      requestId: 'training-persistence-bridge-1',
      commandId: 'trainer.training.flashcardAnswer',
      ok: true,
    },
  });
  assert.deepEqual(harness.postedMessages[2], {
    type: 'operation/status',
    payload: {
      tone: 'success',
      message: 'Flashcard answer recorded.',
    },
  });
});

test('failed training persistence acknowledgement stays failed after state reconciliation', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute() {
        return { ok: false, message: 'The training handoff is not ready to return.' };
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.training.return',
      payload: {
        cardId: 'card-1',
        handoffId: 'handoff-1',
        __trainerTrainingPersistenceId: 'training-persistence-bridge-failure-1',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.equal(harness.postedMessages[0].type, 'state/patch');
  assert.deepEqual(harness.postedMessages[1], {
    type: 'training/persistenceAck',
    payload: {
      requestId: 'training-persistence-bridge-failure-1',
      commandId: 'trainer.training.return',
      ok: false,
      message: 'The training handoff is not ready to return.',
    },
  });
  assert.deepEqual(harness.postedMessages[2], {
    type: 'operation/status',
    payload: {
      tone: 'error',
      message: 'The training handoff is not ready to return.',
    },
  });
});

test('resource command exceptions return a correlated safe failure status', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute() {
        throw new Error('F:\\private\\outside-resource.md');
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.resource.delete',
      payload: {
        resourceIds: ['resource-1'],
        __trainerResourceOperationId: 'resource-operation-exception-1',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(harness.postedMessages[0], {
    type: 'operation/status',
    payload: {
      tone: 'error',
      message:
        '[[trainer-resource-operation:delete:resource-operation-exception-1]] Trainer could not complete this action. Try again.',
    },
  });
  assert.equal(harness.postedMessages[1].type, 'state/patch');
  assert.doesNotMatch(JSON.stringify(harness.postedMessages[0]), /private|outside-resource/);
});

test('resource delete and restore messages reach the sidecar and return reconciled snapshots', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const sidecarCalls = [];
  const workspaceId = 'F:\\trainer\\workspace-a';
  const resource = {
    id: 'resource-1',
    title: 'Notes',
    kind: 'markdown',
    status: 'ready',
    summary: 'Coach notes',
    source: 'F:\\trainer\\notes.md',
    sandboxPath: 'F:\\trainer\\sandboxes\\workspace-a\\notes.md',
  };
  let deleted = false;
  let hostState = createBootstrapState();
  hostState.workspace = { ...hostState.workspace, workspaceFolder: workspaceId };
  hostState.bootstrap.resources = [resource];
  hostState.bootstrap.deletedResources = [];
  hostState.bootstrap.memory = {
    ...hostState.bootstrap.memory,
    selectedResourceDetail: resource,
  };

  const vscodeMock = createVscodeMock({
    commands: {
      registerCommand() {
        return { dispose() {} };
      },
    },
  });
  const { CommandRegistry } = loadWithVscodeMock(commandRegistryModulePath, vscodeMock);
  const { deleteResourceCommand, restoreResourceCommand } = loadWithVscodeMock(
    resourceCommandsModulePath,
    vscodeMock,
  );
  let controller;
  const resourceContext = {
    workbench: {
      async syncState() {
        await controller.syncState();
      },
      resolveWebviewUriForPath() {
        return undefined;
      },
    },
    trainerWorkspace: {
      getRoot() {
        return workspaceId;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 8765 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        sidecarCalls.push({ method: 'POST', port, requestPath, body });
        if (requestPath === '/resource/delete') {
          deleted = true;
          return { removed: true, detail: 'Resource moved to Trash.' };
        }
        if (requestPath === '/resource/restore') {
          deleted = false;
          return {
            restored: true,
            resource: {
              id: body.resource_id,
              kind: 'markdown',
              name: 'Notes',
              source: resource.source,
              parse_status: 'ready',
              index_status: 'ready',
              sandbox_path: resource.sandboxPath,
            },
            sandbox_state: {
              root_path: workspaceId,
              sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\resources\\workspace-a',
              ready: true,
              nodes: [],
            },
          };
        }
        throw new Error(`Unexpected resource mutation route: ${requestPath}`);
      },
      async getJson(port, requestPath) {
        sidecarCalls.push({ method: 'GET', port, requestPath });
        if (requestPath.startsWith('/memory/summary?')) {
          return { memory: { resources: deleted ? [] : [resource] } };
        }
        if (requestPath.startsWith('/resource/trash?')) {
          return {
            workspace_id: workspaceId,
            items: deleted
              ? [{ resource_id: resource.id, title: resource.title, recoverable: true }]
              : [],
          };
        }
        throw new Error(`Unexpected resource query route: ${requestPath}`);
      },
    },
    getHostState() {
      return hostState;
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      hostState = patchHostState(hostState, patch);
    },
  };
  const registry = new CommandRegistry({ appendLine() {} });
  registry.setContext(resourceContext);
  const extensionContext = { subscriptions: [] };
  registry.register(extensionContext, 'trainer.resource.delete', deleteResourceCommand);
  registry.register(extensionContext, 'trainer.resource.restore', restoreResourceCommand);
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    registry,
    () => hostState,
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.resource.delete',
      payload: { resourceIds: [resource.id], __trainerResourceOperationId: 'resource-delete-1' },
    },
  });
  await flushAsyncBridgeWork();
  await flushAsyncBridgeWork();

  const deleteStatus = harness.postedMessages.find(
    (message) =>
      message.type === 'operation/status' && /trainer-resource-operation:delete:resource-delete-1/.test(message.payload.message),
  );
  const deleteSnapshot = harness.postedMessages.find(
    (message) =>
      message.type === 'state/patch' &&
      message.payload.resources.length === 0 &&
      message.payload.deletedResources?.some((item) => item.resourceId === resource.id),
  );
  assert.equal(deleteStatus?.payload.tone, 'success', deleteStatus?.payload.message);
  assert.match(deleteStatus?.payload.message ?? '', /Deleted 1 resource\./);
  assert.ok(deleteSnapshot, 'the delete must return a Trash-backed state patch');

  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.resource.restore',
      payload: { resourceIds: [resource.id], __trainerResourceOperationId: 'resource-restore-1' },
    },
  });
  await flushAsyncBridgeWork();
  await flushAsyncBridgeWork();

  const restoreStatus = harness.postedMessages.find(
    (message) =>
      message.type === 'operation/status' && /trainer-resource-operation:restore:resource-restore-1/.test(message.payload.message),
  );
  const restoredSnapshot = [...harness.postedMessages]
    .reverse()
    .find((message) => message.type === 'state/patch');
  assert.equal(restoreStatus?.payload.tone, 'success', restoreStatus?.payload.message);
  assert.match(restoreStatus?.payload.message ?? '', /Restored 1 resource\./);
  assert.equal(restoredSnapshot?.payload.resources.some((item) => item.id === resource.id), true);
  assert.deepEqual(restoredSnapshot?.payload.deletedResources, []);

  assert.deepEqual(
    sidecarCalls.filter((call) => call.method === 'POST'),
    [
      {
        method: 'POST',
        port: 8765,
        requestPath: '/resource/delete',
        body: { session_id: 'session-1', workspace_id: workspaceId, resource_id: resource.id },
      },
      {
        method: 'POST',
        port: 8765,
        requestPath: '/resource/restore',
        body: { session_id: 'session-1', workspace_id: workspaceId, resource_id: resource.id },
      },
    ],
  );
  registry.dispose();
});

test('debug snapshot keeps the latest restore payload and outbound message types', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  assert.equal(harness.view.title, 'Trainer');
  await controller.postMessage({
    type: 'ui/restoreView',
    payload: {
      sessionId: 'session-2',
      activeView: 'coach',
      trainingSubmode: 'review',
    },
  });
  await controller.postMessage({
    type: 'operation/status',
    payload: { tone: 'success', message: 'Trainer restored the current view.' },
  });
  await harness.dispatchMessage({
    type: 'debug/visibleFacts',
    payload: {
      activeView: 'training',
      training: {
        surface: 'training',
        activeView: 'training',
        restoreKind: 'next_hop',
        visibleTitle: 'Next hop restored',
      },
    },
  });

  const snapshot = controller.getDebugSnapshot();
  assert.equal(snapshot.bootstrapNonce >= 1, true);
  assert.equal(snapshot.viewVisible, true);
  assert.equal(snapshot.lastPostedMessageType, 'operation/status');
  assert.deepEqual(snapshot.recentOutboundMessageTypes.slice(-3), [
    'bootstrap',
    'ui/restoreView',
    'operation/status',
  ]);
  assert.deepEqual(snapshot.lastRestorePayload, {
    sessionId: 'session-2',
    activeView: 'coach',
    trainingSubmode: 'review',
  });
  assert.deepEqual(snapshot.lastOperationStatusPayload, {
    tone: 'success',
    message: 'Trainer restored the current view.',
  });
  assert.deepEqual(snapshot.lastVisibleFactsPayload, {
    activeView: 'training',
    training: {
      surface: 'training',
      activeView: 'training',
      restoreKind: 'next_hop',
      visibleTitle: 'Next hop restored',
    },
  });
});

test('queued restore is replayed after a webview reports ready', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createBootstrapState(),
    { appendLine() {} },
  );
  const payload = {
    activeView: 'training',
    trainingRestoreTarget: 'scenario_lab',
    scenarioLabId: 'scenario-restore-1',
  };

  await controller.resolveWebviewView(harness.view);
  await controller.postMessage({ type: 'ui/restoreView', payload });
  await harness.dispatchMessage({ type: 'webview/ready' });
  await flushAsyncBridgeWork();

  const restores = harness.postedMessages.filter((message) => message.type === 'ui/restoreView');
  assert.equal(restores.length, 2);
  assert.deepEqual(restores.at(-1).payload, payload);
});

test('unknown webview messages are logged to the output channel', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const outputLines = [];
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createBootstrapState(),
    { appendLine(line) { outputLines.push(line); } },
  );

  await controller.resolveWebviewView(harness.view);

  await harness.dispatchMessage({ type: 'unknown/message' });
  await flushAsyncBridgeWork();

  assert.match(outputLines.at(-1), /\[webview\] Unknown message:/);
});

test('host logs redact api keys from unknown messages and debug errors', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const outputLines = [];
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const leakKey = 'sk-test-not-a-real-key-aaaaaaaa';

  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    { async execute() { return { ok: true, message: 'noop' }; } },
    () => createBootstrapState(),
    { appendLine(line) { outputLines.push(line); } },
  );

  await controller.resolveWebviewView(harness.view);
  outputLines.length = 0;

  await harness.dispatchMessage({
    type: 'unknown/leak',
    payload: { apiKey: leakKey, authorization: `Bearer ${leakKey}` },
  });
  await flushAsyncBridgeWork();
  assert.match(outputLines.at(-1), /\[webview\] Unknown message:/);
  assert.doesNotMatch(outputLines.at(-1), /sk-test-not-a-real-key-aaaaaaaa/);

  outputLines.length = 0;
  await harness.dispatchMessage({
    type: 'debug/error',
    payload: {
      source: 'privacy',
      message: `failed with ${leakKey}`,
      stack: `Error: api_key=${leakKey}`,
    },
  });
  await flushAsyncBridgeWork();
  assert.match(outputLines.at(-1), /\[webview:privacy\]/);
  assert.doesNotMatch(outputLines.join('\n'), /sk-test-not-a-real-key-aaaaaaaa/);
});

test('resource training handoff waits for state sync and only reports the selected generated card as ready', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const commandCalls = [];
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute(commandId, payload) {
        commandCalls.push({ commandId, payload });
        return {
          ok: true,
          data: {
            success: true,
            generatedCardId: 'card-from-resource',
            selectedCardId: 'card-from-resource',
          },
        };
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;
  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.training.generateCard',
      payload: {
        source: 'resource_knowledge',
        cardType: 'flash',
        resourceId: 'resource-42',
        __trainerResourceTrainingHandoffId: 'resource-training-bridge-1',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.deepEqual(commandCalls, [
    {
      commandId: 'trainer.training.generateCard',
      payload: {
        source: 'resource_knowledge',
        cardType: 'flash',
        resourceId: 'resource-42',
        __trainerResourceTrainingHandoffId: 'resource-training-bridge-1',
      },
    },
  ]);
  assert.deepEqual(harness.postedMessages.map((message) => message.type), [
    'state/patch',
    'training/resourceHandoff',
  ]);
  assert.deepEqual(harness.postedMessages[1], {
    type: 'training/resourceHandoff',
    payload: {
      requestId: 'resource-training-bridge-1',
      resourceId: 'resource-42',
      outcome: 'ready',
      generatedCardId: 'card-from-resource',
      selectedCardId: 'card-from-resource',
    },
  });
});

test('resource training handoff stays in Resources when a different card is active', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute() {
        return {
          ok: true,
          data: {
            success: true,
            generatedCardId: 'generated-card',
            selectedCardId: 'already-active-card',
          },
        };
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;
  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.training.generateCard',
      payload: {
        resourceId: 'resource-42',
        __trainerResourceTrainingHandoffId: 'resource-training-bridge-2',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.equal(harness.postedMessages.at(-1).type, 'training/resourceHandoff');
  assert.equal(harness.postedMessages.at(-1).payload.outcome, 'not-current');
  assert.equal(harness.postedMessages.some((message) => message.type === 'operation/status'), false);
});

test('resource training handoff returns a linked failure when generation throws', async () => {
  const extensionPath = await createExtensionFixtureDir();
  const harness = createViewHarness();
  const vscodeMock = createVscodeMock();
  const { WorkbenchSidebarController } = loadWithVscodeMock(bridgeModulePath, vscodeMock);
  const controller = new WorkbenchSidebarController(
    { extensionPath, extensionUri: { fsPath: extensionPath } },
    {
      async execute() {
        throw new Error('sidecar unavailable');
      },
    },
    () => createBootstrapState(),
    { appendLine() {} },
  );

  await controller.resolveWebviewView(harness.view);
  harness.postedMessages.length = 0;
  await harness.dispatchMessage({
    type: 'command/execute',
    payload: {
      commandId: 'trainer.training.generateCard',
      payload: {
        resourceId: 'resource-42',
        __trainerResourceTrainingHandoffId: 'resource-training-bridge-3',
      },
    },
  });
  await flushAsyncBridgeWork();

  assert.equal(harness.postedMessages.at(-1).type, 'training/resourceHandoff');
  assert.equal(harness.postedMessages.at(-1).payload.outcome, 'failed');
  assert.equal(harness.postedMessages.at(-1).payload.reason, 'connection');
  assert.equal(harness.postedMessages.some((message) => message.type === 'operation/status'), false);
});
