'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const providerConfigStoreModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'provider',
  'providerConfigStore.js',
);

class FakeEventEmitter {
  constructor() {
    this.listeners = new Set();
    this.event = (listener) => {
      this.listeners.add(listener);
      return {
        dispose: () => this.listeners.delete(listener),
      };
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
    setKeysForSync() {
      return undefined;
    },
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

function createWorkspaceRoot() {
  const workspaceRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-provider-store-'));
  fs.mkdirSync(path.join(workspaceRoot, '.vscode'), { recursive: true });
  fs.writeFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), '{}\n', 'utf8');
  return workspaceRoot;
}

function createVscodeMock(workspaceRoot) {
  return {
    EventEmitter: FakeEventEmitter,
    env: {
      remoteName: undefined,
    },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: workspaceRoot } }],
    },
    window: {
      async showInputBox() {
        return undefined;
      },
    },
  };
}

function createExtensionContext(globalState) {
  return {
    globalState,
    secrets: createSecrets(),
  };
}

test('ProviderConfigStore preserves modelCapabilities through save, active profile conversion, and workspace sync', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  const config = {
    name: 'OpenAI',
    label: 'OpenAI',
    protocol: 'openai_responses',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyRef: 'openai.default',
    credentialMode: 'ui_proxy',
    model: 'gpt-4.1-mini',
    availableModels: ['gpt-4.1-mini', 'gpt-4.1'],
    modelAliases: { 'coach-fast': 'gpt-4.1-mini' },
    modelCapabilities: {
      'gpt-4.1-mini': {
        chat: true,
        responses: true,
        vision: true,
        embeddings: false,
        tools: true,
        jsonSchema: true,
        streaming: true,
        structuredOutput: true,
      },
      'gpt-4.1': {
        chat: true,
        responses: true,
        vision: true,
        embeddings: false,
        tools: true,
        jsonSchema: true,
        streaming: true,
        structuredOutput: true,
      },
    },
    taskBindings: { coach_reply: { alias: 'coach-fast' } },
    requestDefaults: { reasoningEffort: 'medium' },
    capabilities: {
      chat: true,
      responses: true,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: true,
      streaming: true,
      structuredOutput: true,
    },
  };

  await store.saveConfig(config, 'sk-test');

  assert.deepEqual(store.getConfig().modelCapabilities, config.modelCapabilities);
  assert.deepEqual(store.getConfig().requestDefaults, {});
  assert.deepEqual(store.getActiveProfileConfig().modelCapabilities, config.modelCapabilities);
  assert.deepEqual(store.getActiveProfile().modelCapabilities, config.modelCapabilities);
  assert.equal(store.getConfig().capabilities.structuredOutput, true);

  const workspaceConfig = JSON.parse(
    fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8'),
  );
  assert.deepEqual(workspaceConfig.provider.modelCapabilities, config.modelCapabilities);
  assert.equal(workspaceConfig.provider.capabilities.structuredOutput, true);
});

test('ProviderConfigStore preserves OpenAI-compatible model token limits across save and workspace reload', async () => {
  const cases = [
    {
      name: 'MiniMax',
      model: 'MiniMax-M3',
      contextWindowTokens: 1000000,
      maxOutputTokens: 16384,
    },
    {
      name: 'Qwen',
      model: 'Qwen2.5-72B-Instruct',
      contextWindowTokens: 131072,
      maxOutputTokens: 8192,
    },
    {
      name: 'DeepSeek',
      model: 'deepseek-chat',
      contextWindowTokens: 64000,
      maxOutputTokens: 8192,
    },
    {
      name: 'Ollama Llama',
      model: 'meta-llama/Llama-3.3-70B-Instruct',
      contextWindowTokens: 131072,
      maxOutputTokens: 8192,
    },
  ];

  for (const modelCase of cases) {
    const workspaceRoot = createWorkspaceRoot();
    const { ProviderConfigStore } = loadWithVscodeMock(
      providerConfigStoreModulePath,
      createVscodeMock(workspaceRoot),
    );
    const globalState = createGlobalState();
    const extensionContext = createExtensionContext(globalState);
    const store = new ProviderConfigStore(extensionContext);
    const expectedRequestDefaults =
      modelCase.name === 'MiniMax'
        ? {
            max_tokens: 65536,
            extra_body: {
              thinking: {
                type: 'disabled',
              },
            },
          }
        : { max_tokens: 65536 };
    const config = {
      name: modelCase.name,
      label: modelCase.name,
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://api.example.com/v1',
      apiKeyRef: 'provider.default',
      credentialMode: 'ui_proxy',
      model: modelCase.model,
      availableModels: [modelCase.model],
      modelAliases: {},
      modelTokenLimits: {
        [modelCase.model]: {
          contextWindowTokens: modelCase.contextWindowTokens,
          maxOutputTokens: modelCase.maxOutputTokens,
        },
      },
      requestDefaults: { max_tokens: 65536 },
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        streaming: true,
      },
    };

    await store.saveConfig(config, 'sk-test');

    const saved = store.getConfig();
    assert.equal(saved.contextWindowTokens, modelCase.contextWindowTokens);
    assert.equal(saved.maxOutputTokens, modelCase.maxOutputTokens);
    assert.deepEqual(saved.modelTokenLimits[modelCase.model], {
      contextWindowTokens: modelCase.contextWindowTokens,
      maxOutputTokens: modelCase.maxOutputTokens,
    });
    assert.deepEqual(saved.requestDefaults, expectedRequestDefaults);

    const workspaceConfig = JSON.parse(
      fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8'),
    );
    assert.equal(workspaceConfig.provider.contextWindowTokens, modelCase.contextWindowTokens);
    assert.equal(workspaceConfig.provider.maxOutputTokens, modelCase.maxOutputTokens);
    assert.deepEqual(workspaceConfig.provider.modelTokenLimits[modelCase.model], {
      contextWindowTokens: modelCase.contextWindowTokens,
      maxOutputTokens: modelCase.maxOutputTokens,
    });
    assert.deepEqual(workspaceConfig.provider.requestDefaults, expectedRequestDefaults);

    const reloaded = new ProviderConfigStore(extensionContext).getConfig();
    assert.equal(reloaded.contextWindowTokens, modelCase.contextWindowTokens);
    assert.equal(reloaded.maxOutputTokens, modelCase.maxOutputTokens);
  }
});

test('ProviderConfigStore rehydrates workspace override modelCapabilities from trainer.json', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  await store.saveConfig(
    {
      name: 'OpenAI',
      label: 'OpenAI',
      protocol: 'openai_responses',
      baseUrl: 'https://api.openai.com/v1',
      apiKeyRef: 'openai.default',
      credentialMode: 'ui_proxy',
      model: 'gpt-4.1-mini',
      modelCapabilities: {
        'gpt-4.1-mini': {
          chat: true,
          responses: true,
          vision: false,
          embeddings: false,
          tools: true,
          jsonSchema: true,
          streaming: true,
        },
      },
      capabilities: {
        chat: true,
        responses: true,
        vision: true,
        embeddings: false,
        tools: true,
        jsonSchema: true,
        streaming: true,
      },
    },
    undefined,
  );

  fs.writeFileSync(
    path.join(workspaceRoot, '.vscode', 'trainer.json'),
    `${JSON.stringify(
      {
        provider: {
          name: 'OpenAI',
          baseUrl: 'https://api.openai.com/v1',
          apiKeyRef: 'openai.default',
          model: 'gpt-4.1-mini',
          requestDefaults: { reasoningEffort: 'medium' },
          modelCapabilities: {
          'gpt-4.1-mini': {
            chat: true,
            responses: true,
            vision: true,
            embeddings: false,
            tools: true,
            jsonSchema: true,
            streaming: true,
            structuredOutput: true,
          },
        },
        capabilities: {
          chat: true,
          responses: true,
          vision: true,
          embeddings: false,
          tools: true,
          jsonSchema: true,
          streaming: true,
          structuredOutput: true,
        },
        },
      },
      null,
      2,
    )}\n`,
    'utf8',
  );

  assert.equal(store.getConfig().modelCapabilities['gpt-4.1-mini'].vision, true);
  assert.equal(store.getConfig().modelCapabilities['gpt-4.1-mini'].structuredOutput, true);
  assert.deepEqual(store.getConfig().requestDefaults, {});
});

test('ProviderConfigStore seeds workspace override defaults from the shared protocol helper', async () => {
  const workspaceRoot = createWorkspaceRoot();
  fs.writeFileSync(
    path.join(workspaceRoot, '.vscode', 'trainer.json'),
    `${JSON.stringify(
      {
        provider: {
          name: 'OpenAI',
          baseUrl: 'https://api.openai.com/v1',
          apiKeyRef: 'openai.default',
          model: 'gpt-4.1-mini',
        },
      },
      null,
      2,
    )}\n`,
    'utf8',
  );

  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  const config = store.getConfig();

  assert.ok(config);
  assert.equal(config?.protocol, undefined);
  assert.deepEqual(config?.capabilities, {
    chat: false,
    responses: false,
    vision: false,
    embeddings: false,
    tools: false,
    jsonSchema: false,
    streaming: false,
    structuredOutput: false,
    thinking: false,
  });
});

test('ProviderConfigStore imports an active profile registry and exposes the effective profile config', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  await store.importProfileRegistry({
    activeProfileId: 'minimax-primary',
    profiles: [
      {
        id: 'minimax-primary',
        label: 'MiniMax',
        protocol: 'openai_chat_completions_compatible',
        mode: 'direct',
        credentialMode: 'ui_proxy',
        baseUrl: 'https://api.minimaxi.com/v1',
        apiKeyRef: 'minimax.default',
        model: 'MiniMax-M3',
        catalogSource: 'provider_live',
        cacheTtlSeconds: 43200,
        modelAliases: { 'coach-fast': 'MiniMax-M2.7-highspeed' },
        availableModels: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
        allowedModels: [],
        deniedModels: [],
        taskBindings: {
          coach_reply: {
            alias: 'coach-fast',
            fallbackAliases: ['coach-deep'],
            requiredCapabilities: ['streaming'],
          },
        },
        requestDefaults: {
          extra_body: {
            thinking: {
              type: 'disabled',
            },
          },
        },
        capabilities: {
          chat: true,
          responses: false,
          vision: false,
          embeddings: false,
          tools: false,
          jsonSchema: false,
          structuredOutput: true,
          streaming: true,
        },
        modelCapabilities: {
          'MiniMax-M3': {
            chat: true,
            responses: false,
            vision: false,
            embeddings: false,
            tools: false,
            jsonSchema: false,
            structuredOutput: true,
            streaming: true,
          },
        },
      },
    ],
    switchHistory: [
      {
        entryId: 'entry-1',
        fromProfileId: '',
        toProfileId: 'minimax-primary',
        reason: 'initial_setup',
        timestamp: '2026-06-28T00:00:00.000Z',
      },
    ],
  });
  await extensionContext.secrets.store('trainer.provider.apiKey.minimax.default', 'sk-minimax');

  const config = store.getConfig();

  assert.ok(config);
  assert.equal(config?.profileId, 'minimax-primary');
  assert.equal(config?.name, 'MiniMax');
  assert.equal(config?.profileCount, 1);
  assert.equal(config?.providerProfiles?.[0]?.model, 'MiniMax-M3');
  assert.deepEqual(config?.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
  assert.equal((await store.getApiKey())?.trim(), 'sk-minimax');
});

test('ProviderConfigStore keeps workspace_secret credentials out of persisted provider state', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);
  const apiKey = 'test-secret-workspace-only';

  const created = await store.createProfileFromConfig(
    {
      name: 'Workspace Secure Provider',
      label: 'Workspace Secure Provider',
      protocol: 'openai_chat_completions_compatible',
      credentialMode: 'workspace_secret',
      baseUrl: 'http://127.0.0.1:1234/v1',
      apiKeyRef: 'workspace-secure.default',
      model: 'test-model',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        structuredOutput: false,
        streaming: true,
      },
    },
    apiKey,
  );

  assert.ok(created);
  assert.equal((await store.getApiKey())?.trim(), apiKey);
  assert.match(created.apiKeyRef, /^trainer\.provider\.[0-9a-f-]{36}$/i);
  assert.equal(
    extensionContext.secrets._store.get(`trainer.provider.apiKey.${created.apiKeyRef}`),
    apiKey,
  );

  const globalProviderConfig = globalState.get('trainer.provider.config');
  const registry = globalState.get('trainer.provider.profileRegistry');
  const workspaceConfig = fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8');

  assert.equal(JSON.stringify(globalProviderConfig).includes(apiKey), false);
  assert.equal(JSON.stringify(registry).includes(apiKey), false);
  assert.equal(workspaceConfig.includes(apiKey), false);
  assert.equal(registry.profiles[0].credentialMode, 'workspace_secret');
  assert.equal(registry.profiles[0].apiKeyRef, created.apiKeyRef);
});

test('ProviderConfigStore rewrites the active profile when saving an imported profile-backed config', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  await store.importProfileRegistry({
    activeProfileId: 'minimax-primary',
    profiles: [
      {
        id: 'minimax-primary',
        label: 'MiniMax',
        protocol: 'openai_chat_completions_compatible',
        mode: 'direct',
        credentialMode: 'ui_proxy',
        baseUrl: 'https://api.minimaxi.com/v1',
        apiKeyRef: 'minimax.default',
        model: 'MiniMax-M3',
        catalogSource: 'provider_live',
        cacheTtlSeconds: 43200,
        modelAliases: { 'coach-fast': 'MiniMax-M2.7-highspeed' },
        availableModels: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
        allowedModels: [],
        deniedModels: [],
        taskBindings: {
          coach_reply: {
            alias: 'coach-fast',
            fallbackAliases: ['coach-deep'],
            requiredCapabilities: ['streaming'],
          },
        },
        requestDefaults: {
          extra_body: {
            thinking: {
              type: 'disabled',
            },
          },
        },
        capabilities: {
          chat: true,
          responses: false,
          vision: false,
          embeddings: false,
          tools: false,
          jsonSchema: false,
          structuredOutput: true,
          streaming: true,
        },
        modelCapabilities: {
          'MiniMax-M3': {
            chat: true,
            responses: false,
            vision: false,
            embeddings: false,
            tools: false,
            jsonSchema: false,
            structuredOutput: true,
            streaming: true,
          },
        },
      },
    ],
    switchHistory: [],
  });

  const current = store.getConfig();
  assert.ok(current);

  await store.saveConfig(
    {
      ...current,
      model: 'MiniMax-M3-Pro',
      availableModels: ['MiniMax-M2.7-highspeed', 'MiniMax-M3-Pro'],
    },
    'sk-minimax-updated',
  );

  const next = store.getConfig();
  const registry = globalState.get('trainer.provider.profileRegistry');
  const workspaceConfig = JSON.parse(
    fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8'),
  );

  assert.ok(next);
  assert.equal(next?.profileId, 'minimax-primary');
  assert.equal(next?.model, 'MiniMax-M3-Pro');
  assert.equal(next?.providerProfiles?.[0]?.model, 'MiniMax-M3-Pro');
  assert.equal(registry.profiles[0].model, 'MiniMax-M3-Pro');
  assert.equal(workspaceConfig.provider.profileId, 'minimax-primary');
  assert.equal(workspaceConfig.provider.model, 'MiniMax-M3-Pro');
  assert.equal((await store.getApiKey())?.trim(), 'sk-minimax-updated');
});

test('ProviderConfigStore gives an explicit saved profile label priority over the active profile label', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const store = new ProviderConfigStore(createExtensionContext(globalState));

  await store.importProfileRegistry({
    activeProfileId: 'minimax-core',
    profiles: [
      {
        id: 'minimax-core',
        label: 'MiniMax Core',
        protocol: 'openai_chat_completions_compatible',
        mode: 'direct',
        credentialMode: 'ui_proxy',
        baseUrl: 'https://api.minimaxi.com/v1',
        apiKeyRef: 'minimax.default',
        model: 'MiniMax-M3',
        availableModels: ['MiniMax-M3'],
        allowedModels: [],
        deniedModels: [],
        modelAliases: {},
        taskBindings: {},
        capabilities: {
          chat: true,
          responses: true,
          vision: false,
          embeddings: false,
          tools: false,
          jsonSchema: false,
          structuredOutput: true,
          streaming: true,
        },
        modelCapabilities: {},
      },
    ],
    switchHistory: [],
  });

  const current = store.getConfig();
  assert.ok(current);
  await store.saveConfig(
    {
      ...current,
      name: 'custom-openai-compatible',
      label: 'custom-openai-compatible',
      profileLabel: 'custom-openai-compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'preview-chat',
    },
    'sk-custom-profile',
  );

  const next = store.getConfig();
  const registry = globalState.get('trainer.provider.profileRegistry');
  const workspaceConfig = JSON.parse(
    fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8'),
  );

  assert.equal(next?.profileId, 'minimax-core');
  assert.equal(next?.name, 'custom-openai-compatible');
  assert.equal(next?.profileLabel, 'custom-openai-compatible');
  assert.equal(registry.profiles[0].label, 'custom-openai-compatible');
  assert.equal(workspaceConfig.provider.name, 'custom-openai-compatible');
  assert.equal(workspaceConfig.provider.label, 'custom-openai-compatible');
});

test('ProviderConfigStore creates and activates a reusable profile from a config draft', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  const created = await store.createProfileFromConfig(
    {
      name: 'MiniMax',
      label: 'MiniMax',
      profileLabel: 'MiniMax',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'http://47.107.101.18:3000/v1',
      apiKeyRef: 'minimax.default',
      credentialMode: 'ui_proxy',
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
      requestDefaults: {
        extra_body: {
          thinking: {
            type: 'disabled',
          },
        },
      },
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        streaming: true,
        structuredOutput: false,
      },
      modelCapabilities: {
        'MiniMax-M3': {
          chat: true,
          responses: true,
          vision: false,
          embeddings: false,
          tools: false,
          jsonSchema: false,
          streaming: true,
          structuredOutput: false,
        },
      },
    },
    'sk-minimax',
  );

  const registry = globalState.get('trainer.provider.profileRegistry');
  const workspaceConfig = JSON.parse(
    fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8'),
  );

  assert.ok(created);
  assert.equal(created?.profileLabel, 'MiniMax');
  assert.equal(store.getConfig()?.profileId, created?.profileId);
  assert.equal(registry.activeProfileId, created?.profileId);
  assert.equal(registry.profiles.length, 1);
  assert.equal(registry.profiles[0].model, 'MiniMax-M3');
  assert.equal(workspaceConfig.provider.profileId, created?.profileId);
  assert.equal(workspaceConfig.provider.model, 'MiniMax-M3');
  assert.deepEqual(workspaceConfig.provider.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
  assert.equal((await store.getApiKey())?.trim(), 'sk-minimax');
});

test('ProviderConfigStore clears profile credentials, caches, and active profile state together', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  const created = await store.createProfileFromConfig(
    {
      name: 'Clearable Provider',
      label: 'Clearable Provider',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'http://127.0.0.1:1234/v1',
      apiKeyRef: 'clearable.default',
      model: 'clearable-model',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        structuredOutput: false,
        streaming: true,
      },
    },
    'sk-clearable',
  );

  assert.ok(created);
  await store.saveModelCache(created, {
    availableModels: ['clearable-model'],
    apiKey: 'sk-clearable',
  });
  await store.saveLastTestResult(created, {
    ok: true,
    status: 'connected',
    detail: 'Provider reachable.',
    checkedAt: '2026-07-10T00:00:00.000Z',
    providerName: 'Clearable Provider',
    baseUrl: 'http://127.0.0.1:1234/v1',
    model: 'clearable-model',
  });

  await store.clearAllProfiles();

  assert.equal(extensionContext.secrets._store.has('trainer.provider.apiKey.clearable.default'), false);
  assert.equal(store.getConfig(), undefined);
  assert.equal(globalState.get('trainer.provider.profileRegistry'), undefined);
  assert.equal(globalState.get('trainer.provider.config'), undefined);
  assert.deepEqual(globalState.get('trainer.provider.modelCache'), {});
  assert.deepEqual(globalState.get('trainer.provider.lastTestResult'), {});
  const workspaceConfig = JSON.parse(
    fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8'),
  );
  assert.equal(Object.hasOwn(workspaceConfig, 'provider'), false);
});

test('ProviderConfigStore leaves a standalone provider untouched when clearing an empty profile registry', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  await store.saveConfig(
    {
      name: 'Standalone Provider',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'http://127.0.0.1:1234/v1',
      apiKeyRef: 'standalone.default',
      model: 'standalone-model',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        structuredOutput: false,
        streaming: true,
      },
    },
    'sk-standalone',
  );

  await store.clearAllProfiles();

  assert.equal((await store.getApiKey())?.trim(), 'sk-standalone');
  assert.equal(store.getConfig()?.name, 'Standalone Provider');
  assert.equal(extensionContext.secrets._store.has('trainer.provider.apiKey.standalone.default'), true);
});

test('ProviderConfigStore seeds stable MiniMax requestDefaults for custom gateway configs', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);

  await store.saveConfig(
    {
      name: 'custom-minimax-gateway',
      label: 'Custom MiniMax Gateway',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'http://47.107.101.18:3000/v1',
      apiKeyRef: 'custom-minimax-gateway.default',
      credentialMode: 'ui_proxy',
      model: 'MiniMax-M3',
      requestDefaults: {
        thinking: { type: 'enabled' },
        extra_body: {
          thinking: { type: 'enabled' },
          gateway_option: 'keep-me',
        },
      },
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        streaming: true,
        structuredOutput: false,
      },
    },
    'sk-minimax',
  );

  const config = store.getConfig();
  const workspaceConfig = JSON.parse(
    fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8'),
  );

  assert.ok(config);
  assert.deepEqual(config.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
      gateway_option: 'keep-me',
    },
  });
  assert.deepEqual(workspaceConfig.provider.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
      gateway_option: 'keep-me',
    },
  });
});

test('ProviderConfigStore gives distinct profiles opaque key refs even when Chinese labels share a legacy slug', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);
  const capabilities = {
    chat: true,
    responses: false,
    vision: false,
    embeddings: false,
    tools: false,
    jsonSchema: false,
    structuredOutput: false,
    streaming: true,
  };

  const first = await store.createProfileFromConfig(
    {
      name: '中文服务一',
      label: '中文服务一',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://first.example/v1',
      model: 'first-model',
      apiKeyRef: '-.default',
      capabilities,
    },
    'sk-first',
  );
  const second = await store.createProfileFromConfig(
    {
      name: '中文服务二',
      label: '中文服务二',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://second.example/v1',
      model: 'second-model',
      apiKeyRef: '-.default',
      capabilities,
    },
    'sk-second',
  );

  assert.ok(first);
  assert.ok(second);
  assert.notEqual(first.apiKeyRef, second.apiKeyRef);
  assert.match(first.apiKeyRef, /^trainer\.provider\.[0-9a-f-]{36}$/i);
  assert.match(second.apiKeyRef, /^trainer\.provider\.[0-9a-f-]{36}$/i);
  assert.equal(
    extensionContext.secrets._store.get(`trainer.provider.apiKey.${first.apiKeyRef}`),
    'sk-first',
  );
  assert.equal(
    extensionContext.secrets._store.get(`trainer.provider.apiKey.${second.apiKeyRef}`),
    'sk-second',
  );
  assert.equal(extensionContext.secrets._store.has('trainer.provider.apiKey.-.default'), false);
});

test('ProviderConfigStore reads workspace baseUrl overrides without persisting the API key', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const extensionContext = createExtensionContext(globalState);
  const store = new ProviderConfigStore(extensionContext);
  const apiKey = 'test-only-workspace-secret';

  await store.saveConfig(
    {
      name: 'Base Provider',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://base.example/v1',
      apiKeyRef: 'base-provider.default',
      model: 'base-model',
      capabilities: {
        chat: true,
        responses: false,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        structuredOutput: false,
        streaming: true,
      },
    },
    apiKey,
  );

  fs.writeFileSync(
    path.join(workspaceRoot, '.vscode', 'trainer.json'),
    `${JSON.stringify(
      {
        provider: {
          name: 'Workspace Provider',
          baseUrl: 'https://workspace.example/v1/',
          model: 'workspace-model',
        },
      },
      null,
      2,
    )}\n`,
    'utf8',
  );

  const config = store.getConfig();
  assert.ok(config);
  assert.equal(config.baseUrl, 'https://workspace.example/v1');
  assert.equal(config.model, 'workspace-model');
  assert.equal((await store.getApiKey())?.trim(), apiKey);
  assert.equal(extensionContext.secrets._store.get(`trainer.provider.apiKey.${config.apiKeyRef}`), apiKey);
  assert.equal(JSON.stringify(globalState.get('trainer.provider.config')).includes(apiKey), false);
  assert.equal(
    fs.readFileSync(path.join(workspaceRoot, '.vscode', 'trainer.json'), 'utf8').includes(apiKey),
    false,
  );
});

test('ProviderConfigStore last-test is isolated by workspace and provider profile, not fingerprint', async () => {
  const workspaceRoot = createWorkspaceRoot();
  const { ProviderConfigStore } = loadWithVscodeMock(
    providerConfigStoreModulePath,
    createVscodeMock(workspaceRoot),
  );
  const globalState = createGlobalState();
  const store = new ProviderConfigStore(createExtensionContext(globalState));
  const sharedConfig = {
    name: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://example.test/v1',
    apiKeyRef: 'minimax.default',
    model: 'MiniMax-M2.7',
    profileId: 'profile-a',
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      structuredOutput: false,
      streaming: true,
    },
  };

  store.setActiveWorkspaceId('workspace-a');
  await store.saveLastTestResult(sharedConfig, {
    ok: true,
    status: 'connected',
    detail: 'Workspace A last-test',
    checkedAt: '2026-08-25T00:00:00.000Z',
    providerName: 'MiniMax',
    baseUrl: 'http://example.test/v1',
    model: 'MiniMax-M2.7',
    apiKey: 'should-never-persist',
  });

  const storedA = store.getLastTestResult(sharedConfig, { workspaceId: 'workspace-a' });
  assert.equal(storedA?.ok, true);
  assert.equal(storedA?.workspaceId, 'workspace-a');
  assert.equal(storedA?.profileId, 'profile-a');
  assert.equal('apiKey' in (storedA ?? {}), false);
  assert.equal(
    JSON.stringify(globalState.get('trainer.provider.lastTestResult') ?? {}).includes('should-never-persist'),
    false,
  );
  const returned = await store.saveLastTestResult(
    { ...sharedConfig, profileId: 'profile-return-strip' },
    {
      ok: true,
      status: 'connected',
      detail: 'return-strip',
      checkedAt: '2026-08-25T00:00:00.000Z',
      providerName: 'MiniMax',
      baseUrl: 'http://example.test/v1',
      model: 'MiniMax-M2.7',
      apiKey: 'should-never-return',
    },
    { workspaceId: 'workspace-return-strip' },
  );
  assert.equal('apiKey' in (returned ?? {}), false);
  assert.equal(returned?.detail, 'return-strip');

  store.setActiveWorkspaceId('workspace-b');
  assert.equal(store.getLastTestResult(sharedConfig, { workspaceId: 'workspace-b' }), undefined);
  assert.equal(store.getLastTestResult({ ...sharedConfig, profileId: 'profile-b' }, { workspaceId: 'workspace-a' }), undefined);
  assert.equal(store.getLastTestResult(sharedConfig, { workspaceId: 'workspace-a' })?.detail, 'Workspace A last-test');
});
