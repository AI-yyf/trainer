'use strict';

/**
 * P0 network-boundary counter guards (Task: provider lifecycle refactor).
 *
 * The send-state refactor made the provider lifecycle "save-and-go": opening
 * the workbench, saving a connection, and switching models must never touch
 * the provider network. Only two entry points may increment the boundary
 * counters:
 *
 * - an explicit "refresh models" action → /provider/models
 *   (runtimeMetrics.modelCatalogRequests)
 * - an explicit "test connection" action → /provider/test
 *   (runtimeMetrics.providerHttpRequests)
 *
 * The counters live in src/core/runtimeMetrics.ts and are exported for tests.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const providerWebviewCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'providerWebviewCommands.js',
);
const providerCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'providerCommands.js',
);
const runtimeMetricsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'runtimeMetrics.js',
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

const { createDefaultBootstrapData } = require(workbenchDataModulePath);

function metrics() {
  return require(runtimeMetricsModulePath);
}

/** Context mock mirroring providerWebviewCommands.test.js. */
function createContext(options = {}) {
  const patches = [];
  const sidecarCalls = [];
  const config = {
    name: 'Local gateway',
    label: 'Local gateway',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://localhost:1234/v1',
    apiKeyRef: 'local.default',
    model: 'gpt-4.1-mini',
    availableModels: ['gpt-4.1-mini', 'gpt-4.1'],
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: true,
      jsonSchema: false,
      streaming: true,
    },
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: '/tmp/trainer-workspace' },
    config,
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );

  return {
    sidecarCalls,
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async getJson(_port, requestPath) {
        sidecarCalls.push(requestPath);
        throw new Error('unexpected sidecar GET');
      },
      async postJson(_port, requestPath) {
        sidecarCalls.push(requestPath);
        if (options.sidecarResponse) {
          return options.sidecarResponse(requestPath);
        }
        return { ok: true, available_models: config.availableModels };
      },
    },
    providerStore: {
      getConfig() {
        return options.config ?? config;
      },
      async getResolvedConfig() {
        return options.config ?? config;
      },
      async getApiKey() {
        return 'sk-test';
      },
      async saveConfig() {},
      getProfileRegistrySnapshot() {
        return { activeProfileId: 'local-default', profiles: [], switchHistory: [] };
      },
      getModelCache() {
        return undefined;
      },
      isModelCacheFresh() {
        return false;
      },
      isModelCacheCompatible() {
        return false;
      },
      async saveModelCache(_config, payload) {
        return {
          availableModels: payload.availableModels,
          resolvedModel: payload.resolvedModel,
          fetchedAt: payload.fetchedAt,
          expiresAt: payload.expiresAt,
          source: payload.source,
        };
      },
      getLastTestResult() {
        return undefined;
      },
      async saveLastTestResult(_config, result) {
        return result;
      },
      async clearLastTestResult() {},
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: { trusted: true, workspaceFolder: '/tmp/trainer-workspace' },
      };
    },
    getSessionId() {
      return 'session-boundary';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {},
      async postMessage() {},
    },
    outputChannel: {
      appendLine() {},
    },
    __patches: patches,
  };
}

async function flushDetachedSaveFinalization() {
  const commands = require(providerWebviewCommandsModulePath);
  if (typeof commands.settleProviderSaveVerificationForTests === 'function') {
    await commands.settleProviderSaveVerificationForTests();
  }
}

test('saving a connection completes with zero provider network calls', async () => {
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(providerWebviewCommandsModulePath, {});
  const boundary = metrics();
  boundary.resetRuntimeMetrics();
  const context = createContext();

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'Local gateway',
    baseUrl: 'http://localhost:1234/v1',
    model: 'gpt-4.1-mini',
  });
  await flushDetachedSaveFinalization();

  assert.equal(result.ok, true);
  const snapshot = boundary.snapshotRuntimeMetrics();
  assert.equal(
    snapshot.providerHttpRequests,
    0,
    'saving a connection must never call /provider/test',
  );
  assert.equal(
    snapshot.modelCatalogRequests,
    0,
    'saving a connection must never call /provider/models',
  );
  assert.deepEqual(context.sidecarCalls, []);
});

test('opening (priming) provider state serves from cache only with zero network calls', async () => {
  const { primeProviderModelsState } = loadWithVscodeMock(providerWebviewCommandsModulePath, {});
  const boundary = metrics();
  boundary.resetRuntimeMetrics();
  const context = createContext();

  await primeProviderModelsState(context);

  const snapshot = boundary.snapshotRuntimeMetrics();
  assert.equal(snapshot.providerHttpRequests, 0);
  assert.equal(snapshot.modelCatalogRequests, 0);
  assert.deepEqual(context.sidecarCalls, []);
});

test('switching models applies locally with zero provider network calls', async () => {
  const { switchProviderModelCommand } = loadWithVscodeMock(providerWebviewCommandsModulePath, {});
  const boundary = metrics();
  boundary.resetRuntimeMetrics();
  const context = createContext();

  const result = await switchProviderModelCommand(context, { model: 'gpt-4.1' });
  await flushDetachedSaveFinalization();

  assert.equal(result.ok, true);
  const snapshot = boundary.snapshotRuntimeMetrics();
  assert.equal(snapshot.providerHttpRequests, 0);
  assert.equal(snapshot.modelCatalogRequests, 0);
  assert.deepEqual(context.sidecarCalls, []);
});

test('an explicit model-list refresh is the only path that calls /provider/models', async () => {
  const { refreshProviderModelsCommand } = loadWithVscodeMock(providerWebviewCommandsModulePath, {});
  const boundary = metrics();
  boundary.resetRuntimeMetrics();
  const context = createContext();

  const result = await refreshProviderModelsCommand(context);

  assert.equal(result.ok, true);
  assert.ok(context.sidecarCalls.includes('/provider/models'));
  const snapshot = boundary.snapshotRuntimeMetrics();
  assert.equal(
    snapshot.modelCatalogRequests,
    1,
    'an explicit refresh increments the /provider/models counter exactly once',
  );
  assert.equal(snapshot.providerHttpRequests, 0);
});

test('an explicit connection test is the only path that calls /provider/test', async () => {
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, {
    window: {
      showWarningMessage() {},
      showInformationMessage() {},
    },
  });
  const boundary = metrics();
  boundary.resetRuntimeMetrics();
  const context = createContext({
    sidecarResponse: (requestPath) =>
      requestPath === '/provider/test'
        ? { ok: true, status: 'connected', detail: 'The service resolved the request.' }
        : { ok: false },
  });

  const result = await testProviderCommand(context, {});

  assert.equal(result.ok, true);
  assert.ok(context.sidecarCalls.includes('/provider/test'));
  const snapshot = boundary.snapshotRuntimeMetrics();
  assert.equal(
    snapshot.providerHttpRequests,
    1,
    'an explicit test increments the /provider/test counter exactly once',
  );
  assert.equal(snapshot.modelCatalogRequests, 0);
});
