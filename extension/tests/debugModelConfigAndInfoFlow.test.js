'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const {
  resolveEffectiveTokenBudgetProfile,
} = require('../dist/shared/src/smartTokenBudget.js');
const {
  inferProviderModelAdaptation,
} = require('../dist/shared/src/providerModelAdaptation.js');
const {
  normalizeProviderThinking,
  updateProviderThinking,
} = require('../dist/shared/src/providerThinking.js');
const {
  providerEndpointIdentity,
} = require('../dist/shared/src/providerConnectionIdentity.js');
const {
  providerBaseUrlIsLocalService,
  providerTestTargetsSameTransport,
  providerTestTargetsCurrentConnection,
} = require('../dist/shared/src/providerStatus.js');
const {
  requestsLearningPlanChange,
} = require('../dist/shared/src/learnerInstructions.js');

const providerConfigStoreModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'provider',
  'providerConfigStore.js',
);
const sessionCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'sessionCommands.js',
);

class FakeEventEmitter {
  constructor() {
    this.listeners = new Set();
    this.event = (listener) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
  }
  fire(value) {
    for (const listener of this.listeners) {
      listener(value);
    }
  }
  dispose() {
    this.listeners.clear();
  }
}

function createGlobalState(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    _store: store,
    setKeysForSync() {},
    get(key) {
      return store.get(key);
    },
    async update(key, value) {
      if (value === undefined) {
        store.delete(key);
        return;
      }
      store.set(key, value);
    },
  };
}

function createSecrets() {
  const store = new Map();
  return {
    _store: store,
    async get(key) {
      return store.get(key);
    },
    async store(key, value) {
      store.set(key, value);
    },
    async delete(key) {
      store.delete(key);
    },
  };
}

function createIsolatedStore() {
  const workspaceRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-debug-ws-'));
  fs.mkdirSync(path.join(workspaceRoot, '.vscode'), { recursive: true });
  fs.writeFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), '{}\n', 'utf8');
  const fileStoreRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-debug-file-'));
  process.env.TRAINER_FILE_STORE_ROOT = fileStoreRoot;

  const { ProviderConfigStore } = loadWithVscodeMock(providerConfigStoreModulePath, {
    EventEmitter: FakeEventEmitter,
    env: { remoteName: undefined },
    workspace: { workspaceFolders: [{ uri: { fsPath: workspaceRoot } }] },
    window: { async showInputBox() { return undefined; } },
  });
  const globalState = createGlobalState();
  const secrets = createSecrets();
  const store = new ProviderConfigStore({ globalState, secrets });
  return { store, secrets, workspaceRoot, fileStoreRoot };
}

test('smartTokenBudget yields strictly distinct low < medium < high tiers on default 64K output', () => {
  const profile = resolveEffectiveTokenBudgetProfile({
    protocol: 'anthropic_messages',
    model: 'claude-sonnet-4-20250514',
    configuredMaxOutputTokens: 65_536,
  });
  assert.ok(
    profile.thinkingBudget.low < profile.thinkingBudget.medium,
    `expected low (${profile.thinkingBudget.low}) < medium (${profile.thinkingBudget.medium})`,
  );
  assert.ok(
    profile.thinkingBudget.medium < profile.thinkingBudget.high,
    `expected medium (${profile.thinkingBudget.medium}) < high (${profile.thinkingBudget.high})`,
  );
});

test('providerModelAdaptation gates Claude thinking to 3.7 and 4+ generations', () => {
  const claude35 = inferProviderModelAdaptation({
    protocol: 'anthropic_messages',
    model: 'claude-3-5-sonnet-20241022',
  });
  const claude37 = inferProviderModelAdaptation({
    protocol: 'anthropic_messages',
    model: 'claude-3-7-sonnet-20250219',
  });
  const claude4 = inferProviderModelAdaptation({
    protocol: 'anthropic_messages',
    model: 'claude-sonnet-4-20250514',
  });
  assert.equal(claude35.supportsThinking, false);
  assert.equal(claude37.supportsThinking, true);
  assert.equal(claude4.supportsThinking, true);
});

test('MiniMax defaults to thinking disabled but respects explicit auto mode in updateProviderThinking', () => {
  const ctx = {
    protocol: 'anthropic_messages',
    baseUrl: 'https://api.minimax.chat/anthropic',
    model: 'MiniMax-M2.7',
  };
  const normalized = normalizeProviderThinking({}, ctx);
  assert.equal(normalized.config?.mode, 'disabled');

  const updated = updateProviderThinking(ctx, { thinking: { type: 'disabled' } }, { mode: 'auto' });
  assert.equal(updated.thinking, undefined);
  assert.equal(updated.extra_body, undefined);
});

test('providerEndpointIdentity handles undefined/null and local URL detection supports scheme-less & .localhost', () => {
  assert.equal(providerEndpointIdentity(undefined), '');
  assert.equal(providerEndpointIdentity(null), '');
  assert.equal(providerBaseUrlIsLocalService('localhost:11434'), true);
  assert.equal(providerBaseUrlIsLocalService('127.0.0.1:1234/v1'), true);
  assert.equal(providerBaseUrlIsLocalService('http://ollama.localhost:11434/v1'), true);
  assert.equal(providerBaseUrlIsLocalService('https://api.openai.com/v1'), false);
  assert.equal(providerBaseUrlIsLocalService('https://evil-localhost.com/v1'), false);
});

test('provider transport and connection equality ignore display-name renames', () => {
  const active = {
    name: 'Work OpenAI Renamed',
    protocol: 'openai_responses',
    baseUrl: 'https://api.openai.com/v1/',
    model: 'gpt-5-mini',
    lastTestResult: {
      ok: true,
      status: 'ready',
      detail: 'ok',
      checkedAt: new Date().toISOString(),
      providerName: 'Original OpenAI Name',
      protocol: 'openai_responses',
      baseUrl: 'https://api.openai.com/v1',
      model: 'gpt-5-mini',
    },
  };
  assert.equal(providerTestTargetsSameTransport(active), true);
  assert.equal(providerTestTargetsCurrentConnection(active), true);
});

test('ProviderConfigStore.clear preserves SecretStorage keys still used by remaining profiles', async () => {
  const { store, secrets } = createIsolatedStore();
  await store.createProfileFromConfig(
    {
      name: 'Profile A',
      protocol: 'openai_responses',
      baseUrl: 'https://api.openai.com/v1',
      model: 'gpt-5-mini',
      apiKeyRef: 'shared.openai.key',
    },
    'sk-shared-secret',
  );
  await store.createProfileFromConfig(
    {
      name: 'Profile B',
      protocol: 'openai_responses',
      baseUrl: 'https://api.openai.com/v1',
      model: 'gpt-5',
      apiKeyRef: 'shared.openai.key',
    },
    'sk-shared-secret',
  );
  const registryBefore = store.getProfileRegistrySnapshot();
  assert.equal(registryBefore.profiles.length, 2);
  await store.switchActiveProfile(registryBefore.profiles[0].id);

  await store.clear();
  const registryAfter = store.getProfileRegistrySnapshot();
  assert.equal(registryAfter.profiles.length, 2);
  assert.equal(registryAfter.activeProfileId, '');
  assert.ok(
    Array.from(secrets._store.values()).includes('sk-shared-secret'),
    'SecretStorage key referenced by remaining profiles must not be deleted',
  );
  await store.switchActiveProfile(registryAfter.profiles[1].id);
  assert.equal(await store.getApiKey(), 'sk-shared-secret');
});

test('ProviderConfigStore.getWorkspaceOverrideConfig preserves full extended provider fields', async () => {
  const { store, workspaceRoot } = createIsolatedStore();
  const trainerJsonPath = path.join(workspaceRoot, '.vscode', 'trainer.json');
  fs.writeFileSync(
    trainerJsonPath,
    JSON.stringify({
      provider: {
        name: 'Workspace Claude',
        protocol: 'anthropic_messages',
        baseUrl: 'https://api.anthropic.com/v1',
        model: 'claude-sonnet-4-20250514',
        credentialMode: 'ui_proxy',
        cacheTtlSeconds: 600,
        availableModels: ['claude-sonnet-4-20250514'],
        allowedModels: ['claude-sonnet-4-20250514'],
        deniedModels: ['claude-3-haiku'],
        modelAliases: { fast: 'claude-sonnet-4-20250514' },
        taskBindings: { coach_reply: { alias: 'fast', fallbackAliases: [] } },
        thinkingConfig: { mode: 'enabled', budgetTokens: 8192 },
        modelThinkingConfig: { 'claude-sonnet-4-20250514': { mode: 'enabled', budgetTokens: 8192 } },
        requestDefaults: { temperature: 0.2, maxTokens: 16384 },
        modelCapabilities: { 'claude-sonnet-4-20250514': { vision: true, thinking: true } },
      },
    }),
    'utf8',
  );
  const override = await store.getWorkspaceOverrideConfig();
  assert.ok(override);
  assert.equal(override.credentialMode, 'ui_proxy');
  assert.equal(override.cacheTtlSeconds, 600);
  assert.deepEqual(override.allowedModels, ['claude-sonnet-4-20250514']);
  assert.deepEqual(override.deniedModels, ['claude-3-haiku']);
  assert.deepEqual(override.thinkingConfig, { mode: 'enabled', budgetTokens: 8192 });
  assert.equal(override.requestDefaults?.temperature, 0.2);
  assert.equal(override.requestDefaults?.maxTokens, 16384);
  assert.equal(override.modelCapabilities?.['claude-sonnet-4-20250514']?.vision, true);
  assert.equal(override.modelCapabilities?.['claude-sonnet-4-20250514']?.thinking, true);
});

test('ProviderConfigStore.saveConfig honors explicit clearing of thinkingConfig and requestDefaults', async () => {
  const { store } = createIsolatedStore();
  await store.saveConfig(
    {
      name: 'Claude',
      protocol: 'anthropic_messages',
      baseUrl: 'https://api.anthropic.com/v1',
      model: 'claude-sonnet-4-20250514',
      apiKeyRef: 'claude.clear.test',
      thinkingConfig: { mode: 'enabled', budgetTokens: 4096 },
      requestDefaults: { temperature: 0.3 },
    },
    'sk-ant-test',
  );

  await store.saveConfig({
    name: 'Claude',
    protocol: 'anthropic_messages',
    baseUrl: 'https://api.anthropic.com/v1',
    model: 'claude-sonnet-4-20250514',
    apiKeyRef: 'claude.clear.test',
    thinkingConfig: undefined,
    requestDefaults: undefined,
  });
  const saved = store.getConfig();
  assert.ok(saved);
  assert.equal(saved.thinkingConfig, undefined);
  assert.equal(saved.requestDefaults?.temperature, undefined);
});

test('requestsLearningPlanChange ignores engineering test/migration plans without learning context', () => {
  assert.equal(requestsLearningPlanChange('Create a migration plan for PostgreSQL'), false);
  assert.equal(requestsLearningPlanChange('Write a test plan for checkout API'), false);
  assert.equal(requestsLearningPlanChange('Draft a release plan for v2.0'), false);
  assert.equal(requestsLearningPlanChange('帮我做一个迁移计划'), false);
  assert.equal(requestsLearningPlanChange('Create a learning plan for Rust ownership'), true);
  assert.equal(requestsLearningPlanChange('帮我制定一个两周学习计划学 Rust'), true);
});

test('cancelStreamMessageCommand bumps generation and preserves partialContent even without messageId', async () => {
  const { cancelStreamMessageCommand } = loadWithVscodeMock(sessionCommandsModulePath, {
    window: { showErrorMessage() {}, showInformationMessage() {} },
    workspace: { workspaceFolders: [] },
  });
  const posted = [];
  const synced = [];
  const bumped = [];
  let streamingState = {
    isStreaming: true,
    streamMessageId: 'msg-active',
    streamedContent: 'Partial answer already generated...',
    agentActivity: [],
  };
  const hostState = {
    sessionId: 'session-1',
    bootstrap: {
      coachDefaults: { responseLanguage: 'zh-CN' },
      memory: { workspace: {} },
    },
  };
  const context = {
    hostState,
    getHostState: () => hostState,
    getStreamingState: () => streamingState,
    setStreamingState: (next) => {
      streamingState = next;
    },
    workbench: {
      postMessage: async (msg) => {
        posted.push(msg);
        return true;
      },
      bumpCoachStreamGeneration: (reason) => {
        bumped.push(reason);
        return 2;
      },
      syncState: async () => {
        synced.push(true);
      },
    },
    sidecarClient: {
      post: async () => ({ ok: true }),
    },
    syncState: async () => {
      synced.push(true);
    },
  };

  const result = await cancelStreamMessageCommand(context, {});
  assert.equal(result.ok, true);
  const cancelMsg = posted.find((item) => item && item.type === 'stream/cancelled');
  assert.ok(cancelMsg, 'expected stream/cancelled message');
  assert.equal(cancelMsg.payload.messageId, 'msg-active');
  assert.equal(cancelMsg.payload.partialContent, 'Partial answer already generated...');
  assert.equal(streamingState.isStreaming, false);
  assert.equal(synced.length, 1);

  // Also test cancelling an optimistic/pre-SSE stream with no streamMessageId yet.
  posted.length = 0;
  streamingState = {
    isStreaming: true,
    streamMessageId: undefined,
    streamedContent: 'Early partial...',
    agentActivity: [],
  };
  const noIdResult = await cancelStreamMessageCommand(context, {});
  assert.equal(noIdResult.ok, true);
  assert.equal(streamingState.isStreaming, false);
  const noIdCancel = posted.find((item) => item && item.type === 'stream/cancelled');
  assert.ok(noIdCancel);
  assert.equal(noIdCancel.payload.partialContent, 'Early partial...');
});
