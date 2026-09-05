'use strict';

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

function createContext() {
  const patches = [];
  const syncs = [];
  const localRegistry = {
    activeProfileId: 'openai-default',
    profiles: [
      {
        id: 'openai-default',
        label: 'OpenAI',
        protocol: 'openai_responses',
        mode: 'direct',
        credentialMode: 'ui_proxy',
        baseUrl: 'https://api.openai.com/v1',
        apiKeyRef: 'openai.default',
        model: 'gpt-5-mini',
        catalogSource: 'provider_live',
        cacheTtlSeconds: 43200,
        modelAliases: { 'coach-fast': 'gpt-5-mini' },
        availableModels: ['gpt-5-mini'],
        allowedModels: [],
        deniedModels: [],
        taskBindings: {
          coach_reply: { alias: 'coach-fast', fallbackAliases: [] },
        },
        requestDefaults: { store: false },
        capabilities: {
          chat: true,
          responses: true,
          vision: true,
          embeddings: false,
          tools: true,
          jsonSchema: true,
          streaming: true,
        },
        modelCapabilities: {},
      },
    ],
    switchHistory: [
      {
        entryId: 'entry-1',
        fromProfileId: '',
        toProfileId: 'openai-default',
        reason: 'initial_setup',
        timestamp: '2026-06-12T08:00:00Z',
      },
    ],
  };

  let currentConfig = {
    name: 'Legacy',
    label: 'Legacy',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://localhost:1234/v1',
    apiKeyRef: 'legacy.default',
    model: 'gpt-4.1-mini',
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

  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    currentConfig,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );

  return {
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async getJson() {
        throw new Error('Profile refresh must not call the sidecar.');
      },
      async postJson() {
        throw new Error('Profile refresh must not call the sidecar.');
      },
    },
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async getApiKey() {
        return 'sk-test';
      },
      getProfileRegistrySnapshot() {
        return localRegistry;
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
    __patches: patches,
    __syncs: syncs,
  };
}

test('saveProviderFromWebviewCommand rejects a blocked model before changing the saved connection', async () => {
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(providerWebviewCommandsModulePath, {});
  const context = createContext();
  const savedConfigs = [];
  context.providerStore.saveConfig = async (config) => {
    savedConfigs.push(config);
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'Local gateway',
    baseUrl: 'http://localhost:1234/v1',
    model: 'MiniMax-M3',
    allowedModels: ['minimax-m3'],
    deniedModels: ['MINIMAX-M3'],
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /blocked for this connection/i);
  assert.equal(savedConfigs.length, 0);
  assert.equal(context.__patches.length, 0);
});

test('switchProviderModelCommand rejects a blocked model before it changes lookup ownership', async () => {
  const { switchProviderModelCommand } = loadWithVscodeMock(providerWebviewCommandsModulePath, {});
  const context = createContext();
  const currentConfig = {
    ...context.providerStore.getConfig(),
    model: 'allowed-model',
    availableModels: ['allowed-model', 'blocked-model'],
    allowedModels: ['allowed-model', 'blocked-model'],
    deniedModels: ['BLOCKED-MODEL'],
  };
  const savedConfigs = [];
  context.providerStore.getConfig = () => currentConfig;
  context.providerStore.saveConfig = async (config) => {
    savedConfigs.push(config);
  };

  const result = await switchProviderModelCommand(context, { model: 'blocked-model' });

  assert.equal(result.ok, false);
  assert.match(result.message, /blocked for this connection/i);
  assert.equal(savedConfigs.length, 0);
  assert.equal(context.__patches.length, 0);
});

test('refreshProviderModelsCommand keeps the selected model when the service resolves to a blocked one', async () => {
  const { refreshProviderModelsCommand } = loadWithVscodeMock(providerWebviewCommandsModulePath, {});
  const patches = [];
  const savedConfigs = [];
  const config = {
    name: 'Policy gateway',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://policy.example/v1',
    apiKeyRef: 'policy.default',
    model: 'allowed-model',
    allowedModels: ['allowed-model'],
    deniedModels: ['blocked-model'],
    availableModels: ['allowed-model'],
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
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
    config,
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  const context = {
    providerStore: {
      getConfig() {
        return config;
      },
      async getApiKey() {
        return 'sk-test';
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
          expiresAt: '2026-07-04T00:00:00.000Z',
          source: payload.source,
        };
      },
      async saveConfig(nextConfig) {
        savedConfigs.push(nextConfig);
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson() {
        return {
          ok: true,
          detail: 'The service resolved the request.',
          available_models: ['allowed-model', 'blocked-model'],
          resolved_model: 'blocked-model',
        };
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-policy';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {},
    },
  };

  const result = await refreshProviderModelsCommand(context);

  assert.equal(result.ok, true);
  assert.equal(result.data.model, 'allowed-model');
  assert.equal(savedConfigs.some((savedConfig) => savedConfig.model === 'blocked-model'), false);
  assert.deepEqual(patches[1].providerConfig.availableModels, ['allowed-model']);
  assert.match(patches[1].providerConfig.modelListDetail, /blocked for this connection/i);
});

test('saveProviderFromWebviewCommand resets capabilities when the protocol changes', async () => {
  let savedConfig;
  let savedApiKey;
  const patches = [];
  const syncs = [];
  const existingConfig = {
    name: 'mini-max',
    label: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.minimaxi.com/v1',
    apiKeyRef: 'mini-max.default',
    model: 'MiniMax-M3',
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
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    existingConfig,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return existingConfig;
      },
      async saveConfig(config, apiKey) {
        savedConfig = config;
        savedApiKey = apiKey;
      },
      async getApiKey() {
        return undefined;
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
      getLastTestResult() {
        return undefined;
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'mini-max',
    protocol: 'anthropic_messages',
    baseUrl: 'https://api.minimaxi.com/v1',
    model: 'claude-3-5-sonnet',
    capabilities: existingConfig.capabilities,
  });

  assert.equal(result.ok, true);
  assert.ok(savedConfig);
  assert.equal(savedApiKey, undefined);
  assert.equal(savedConfig.protocol, 'anthropic_messages');
  assert.deepEqual(savedConfig.catalogModels, ['claude-3-5-sonnet']);
  assert.equal(savedConfig.capabilities.chat, true);
  assert.equal(savedConfig.capabilities.responses, false);
  assert.equal(savedConfig.capabilities.vision, true);
  assert.equal(savedConfig.capabilities.tools, true);
  assert.equal(savedConfig.capabilities.jsonSchema, false);
  assert.equal(savedConfig.capabilities.structuredOutput, false);
  assert.equal(savedConfig.capabilities.streaming, true);
  assert.equal(patches[0].providerConfig.protocol, 'anthropic_messages');
  assert.equal(syncs.length, 1);
});

test('saveProviderFromWebviewCommand uses the entered connection name as the profile label', async () => {
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
    {
      name: 'MiniMax',
      label: 'MiniMax Core',
      profileLabel: 'MiniMax Core',
      profileId: 'minimax-core',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://api.minimaxi.com/v1',
      apiKeyRef: 'minimax.default',
      model: 'MiniMax-M3',
      capabilities: { chat: true, responses: true, vision: false, embeddings: false, tools: false, jsonSchema: false, structuredOutput: true, streaming: true },
    },
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  let currentConfig = {
    name: 'MiniMax',
    label: 'MiniMax Core',
    profileLabel: 'MiniMax Core',
    profileId: 'minimax-core',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.minimaxi.com/v1',
    apiKeyRef: 'minimax.default',
    model: 'MiniMax-M3',
    capabilities: { chat: true, responses: true, vision: false, embeddings: false, tools: false, jsonSchema: false, structuredOutput: true, streaming: true },
  };
  let savedConfig;
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async saveConfig(config) {
        savedConfig = config;
        currentConfig = config;
      },
      async getApiKey() {
        return undefined;
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
      getLastTestResult() {
        return undefined;
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
        workspace: { workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-profile-label';
    },
    async patchWorkbenchData() {
      return undefined;
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'custom-openai-compatible',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'preview-chat',
  });

  assert.equal(result.ok, true);
  assert.equal(savedConfig.name, 'custom-openai-compatible');
  assert.equal(savedConfig.label, 'custom-openai-compatible');
  assert.equal(savedConfig.profileLabel, 'custom-openai-compatible');
});

test('saveProviderFromWebviewCommand keeps the model list ready but blocks coaching when provider replies are unusable', async () => {
  const patches = [];
  const syncs = [];
  const savedConfigs = [];
  const savedLastTests = [];
  const requestOptions = new Map();
  let currentConfig;
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async saveConfig(config) {
        savedConfigs.push(config);
        currentConfig = { ...currentConfig, ...config };
      },
      async getApiKey() {
        return 'sk-live';
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
      getLastTestResult() {
        return savedLastTests[savedLastTests.length - 1];
      },
      async saveLastTestResult(_config, result) {
        savedLastTests.push(result);
        return result;
      },
      async clearModelCache() {
        return undefined;
      },
      async saveModelCache(_config, payload) {
        return {
          ...payload,
          fetchedAt: payload.fetchedAt ?? '2026-06-30T09:30:00.000Z',
          expiresAt: '2026-06-30T21:30:00.000Z',
        };
      },
      async clearLastTestResult() {
        return undefined;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body, options) {
        assert.equal(port, 34891);
        requestOptions.set(requestPath, options);
        if (requestPath === '/provider/models') {
          assert.equal(body.apiKey, 'sk-live');
          return {
            ok: true,
            detail: 'Fetched 2 models. Resolved configured model to MiniMax-M3.',
            available_models: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
            resolved_model: 'MiniMax-M3',
          };
        }
        if (requestPath === '/provider/test') {
          assert.equal(body.apiKey, 'sk-live');
          return {
            ok: false,
            configured: true,
            api_key_supplied: true,
            reachable: true,
            success: false,
            status: 'language_corruption',
            provider_name: 'minimax-smoke',
            detail:
              'Provider reachable, but it corrupted Chinese input into question marks before the model saw it. Trainer cannot safely coach in zh-CN on this connection yet.',
            diagnostics: ['Language integrity probe failed.'],
            error_category: 'language_corruption',
            retryable: false,
            status_code: 200,
            capability_evidence: [
              { name: 'tools', declared: true, observed: false, state: 'unsupported' },
            ],
            tools_ready: true,
            tool_probe_status: 'verified',
          };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    getHostState() {
      return {
        bootstrap: createDefaultBootstrapData(
          {
            trusted: true,
            workspaceFolder: 'F:\\trainer\\workspace-a',
          },
          currentConfig,
          {
            lifecycle: 'ready',
            host: '127.0.0.1',
            port: 34891,
            canStart: true,
          },
        ),
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'minimax-smoke',
    baseUrl: 'http://47.107.101.18:3000/v1',
    model: 'MiniMax-M3',
    apiKey: 'sk-live',
    replaceApiKey: true,
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: true,
      jsonSchema: false,
      structuredOutput: false,
      streaming: true,
    },
    requestDefaults: {
      thinking: {
        type: 'disabled',
      },
    },
  });

  assert.equal(result.ok, true);
  assert.equal(savedConfigs[0].model, 'MiniMax-M3');
  assert.equal(savedLastTests.length, 1);
  assert.equal(savedLastTests[0].status, 'language_corruption');
  assert.equal(savedLastTests[0].errorCategory, 'language_corruption');
  assert.equal(savedLastTests[0].toolsReady, false);
  assert.equal(savedLastTests[0].toolProbeStatus, 'unsupported');
  assert.deepEqual(requestOptions.get('/provider/models'), { timeoutMs: 90_000 });
  assert.deepEqual(requestOptions.get('/provider/test'), { timeoutMs: 90_000 });
  assert.match(result.message ?? '', /Loaded 2 live models/i);
  assert.match(result.message ?? '', /cannot coach with this connection yet/i);
  assert.match(result.message ?? '', /question marks/i);
  assert.equal(syncs.length, 2);
  assert.equal(patches[1].providerConfig.modelListStatus, 'ready');
  assert.equal(patches[1].providerConfig.lastTestResult.status, 'language_corruption');
  assert.equal(patches[1].providerConfig.lastTestResult.errorCategory, 'language_corruption');
});

test('saveProviderFromWebviewCommand keeps the model list ready when zh-CN integrity is not fully verified yet', async () => {
  const savedConfigs = [];
  const savedLastTests = [];
  const patches = [];
  const syncs = [];
  let currentConfig;
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async saveConfig(config, apiKey) {
        currentConfig = { ...config };
        savedConfigs.push({ ...config, apiKey });
      },
      async getApiKey() {
        return 'sk-live';
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
      getLastTestResult() {
        return undefined;
      },
      async saveLastTestResult(_config, result) {
        savedLastTests.push(result);
        return result;
      },
      async clearModelCache() {
        return undefined;
      },
      async saveModelCache(_config, payload) {
        return {
          ...payload,
          fetchedAt: payload.fetchedAt ?? '2026-06-30T09:30:00.000Z',
          expiresAt: '2026-06-30T21:30:00.000Z',
        };
      },
      async clearLastTestResult() {
        return undefined;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        assert.equal(port, 34891);
        if (requestPath === '/provider/models') {
          assert.equal(body.apiKey, 'sk-live');
          return {
            ok: true,
            detail: 'Fetched 2 models. Resolved configured model to MiniMax-M3.',
            available_models: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
            resolved_model: 'MiniMax-M3',
          };
        }
        if (requestPath === '/provider/test') {
          assert.equal(body.apiKey, 'sk-live');
          return {
            ok: false,
            configured: true,
            api_key_supplied: true,
            reachable: true,
            success: false,
            status: 'language_probe_inconclusive',
            provider_name: 'minimax-smoke',
            detail:
              'Language integrity probe was inconclusive. The provider replied, but it did not preserve the mixed CJK/ASCII probe text exactly enough for Trainer to trust it.',
            diagnostics: ['Language integrity probe was inconclusive.'],
            error_category: 'language_probe_inconclusive',
            retryable: false,
            status_code: 200,
          };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    getHostState() {
      return {
        bootstrap: createDefaultBootstrapData(
          {
            trusted: true,
            workspaceFolder: 'F:\\trainer\\workspace-a',
          },
          currentConfig,
          {
            lifecycle: 'ready',
            host: '127.0.0.1',
            port: 34891,
            canStart: true,
          },
        ),
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'minimax-smoke',
    baseUrl: 'http://47.107.101.18:3000/v1',
    model: 'MiniMax-M3',
    apiKey: 'sk-live',
    replaceApiKey: true,
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: true,
      jsonSchema: false,
      structuredOutput: false,
      streaming: true,
    },
    requestDefaults: {
      thinking: {
        type: 'disabled',
      },
    },
  });

  assert.equal(result.ok, true);
  assert.equal(savedConfigs[0].model, 'MiniMax-M3');
  assert.equal(savedLastTests.length, 1);
  assert.equal(savedLastTests[0].status, 'language_probe_inconclusive');
  assert.equal(savedLastTests[0].errorCategory, 'language_probe_inconclusive');
  assert.match(result.message ?? '', /Loaded 2 live models/i);
  assert.match(result.message ?? '', /zh-cn integrity still needs verification/i);
  assert.doesNotMatch(result.message ?? '', /cannot coach with this connection yet/i);
  assert.equal(syncs.length, 2);
  assert.equal(patches[1].providerConfig.modelListStatus, 'ready');
  assert.equal(patches[1].providerConfig.lastTestResult.status, 'language_probe_inconclusive');
  assert.equal(patches[1].providerConfig.lastTestResult.errorCategory, 'language_probe_inconclusive');
});

test('saveProviderFromWebviewCommand injects stable MiniMax defaults for custom MiniMax-like gateways', async () => {
  let savedConfig;
  const patches = [];
  const syncs = [];
  let currentConfig;
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async saveConfig(config) {
        savedConfig = config;
        currentConfig = { ...config };
      },
      async getApiKey() {
        return undefined;
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
      getLastTestResult() {
        return undefined;
      },
      async clearModelCache() {
        return undefined;
      },
    },
    getHostState() {
      return {
        bootstrap: createDefaultBootstrapData(
          {
            trusted: true,
            workspaceFolder: 'F:\\trainer\\workspace-a',
          },
          currentConfig,
          {
            lifecycle: 'ready',
            host: '127.0.0.1',
            port: 34891,
            canStart: true,
          },
        ),
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'custom-minimax-gateway',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://47.107.101.18:3000/v1',
    model: 'MiniMax-M3',
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
  });

  assert.equal(result.ok, true);
  assert.ok(savedConfig);
  assert.deepEqual(savedConfig.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
  assert.deepEqual(patches[0].providerConfig.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
  assert.equal(syncs.length, 1);
});

test('saveProviderFromWebviewCommand tests the saved model when live discovery is unavailable', async () => {
  const patches = [];
  const savedLastTests = [];
  let currentConfig;
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async saveConfig(config) {
        currentConfig = { ...config };
      },
      async getApiKey() {
        return 'test-only-key';
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
      getLastTestResult() {
        return savedLastTests[savedLastTests.length - 1];
      },
      async saveLastTestResult(_config, result) {
        savedLastTests.push(result);
        return result;
      },
      async clearModelCache() {
        return undefined;
      },
      async saveModelCache(_config, payload) {
        return {
          ...payload,
          fetchedAt: payload.fetchedAt ?? '2026-07-15T08:00:00.000Z',
          expiresAt: '2026-07-15T20:00:00.000Z',
        };
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, requestPath, body) {
        assert.equal(body.apiKey, 'test-only-key');
        assert.equal(body.response_language, 'zh-CN');
        if (requestPath === '/provider/models') {
          return {
            ok: false,
            detail: 'This gateway does not publish a model list.',
            available_models: [],
            error_category: 'model_listing_unavailable',
            retryable: false,
          };
        }
        if (requestPath === '/provider/test') {
          return {
            ok: true,
            configured: true,
            api_key_supplied: true,
            reachable: true,
            success: true,
            status: 'connected',
            provider_name: 'minimax-compatible',
            detail: 'Provider reachable. Chat probe succeeded with model MiniMax-M3.',
          };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    getHostState() {
      return {
        bootstrap: createDefaultBootstrapData(
          { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
          currentConfig,
          { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
        ),
        sidecar: { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: 'minimax-compatible',
    protocol: 'anthropic_messages',
    baseUrl: 'http://minimax.redfast.top',
    model: 'MiniMax-M3',
    apiKey: 'test-only-key',
    replaceApiKey: true,
    responseLanguage: 'zh-CN',
  });

  assert.equal(result.ok, true);
  assert.equal(savedLastTests.length, 1);
  assert.equal(savedLastTests[0].ok, true);
  assert.equal(savedLastTests[0].responseLanguage, 'zh-CN');
  assert.equal(patches[1].providerConfig.modelListStatus, 'error');
  assert.equal(patches[1].providerConfig.resolvedModel, 'MiniMax-M3');
  assert.equal(patches[1].providerConfig.lastTestResult.ok, true);
  assert.equal(patches[1].providerConfig.lastTestResult.responseLanguage, 'zh-CN');
  assert.match(result.message ?? '', /current model is connected and ready/i);
  assert.doesNotMatch(JSON.stringify(patches), /test-only-key/);
});

test('refreshProviderProfilesCommand configured snapshot declares currentView before use', () => {
  const source = require('node:fs').readFileSync(
    path.resolve(__dirname, '..', 'src', 'commands', 'providerWebviewCommands.ts'),
    'utf8',
  );
  const fnStart = source.indexOf('export async function refreshProviderProfilesCommand');
  assert.ok(fnStart >= 0, 'expected refreshProviderProfilesCommand');
  const slice = source.slice(fnStart, fnStart + 3500);
  const currentViewDecl = slice.indexOf('const currentView = context.getHostState().bootstrap.providerConfig');
  const configuredUse = slice.indexOf('const providerConfigured = providerTransportIsConfigured');
  assert.ok(currentViewDecl >= 0, 'expected currentView declaration');
  assert.ok(configuredUse > currentViewDecl, 'currentView must be initialized before the configured snapshot');
});

test('refreshProviderProfilesCommand does not mark empty New API URL and model as configured', async () => {
  const vscodeMock = {};
  const { refreshProviderProfilesCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  context.providerStore.getConfig = () => ({
    name: 'New API',
    label: 'New API',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: '',
    apiKeyRef: 'newapi.default',
    model: '',
    connectionType: 'newapi_channel_conn',
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
  });
  context.providerStore.getProfileRegistrySnapshot = () => ({
    activeProfileId: 'newapi-default',
    profiles: [
      {
        id: 'newapi-default',
        label: 'New API',
        protocol: 'openai_chat_completions_compatible',
        baseUrl: '',
        model: '',
        connectionType: 'newapi_channel_conn',
      },
    ],
    switchHistory: [],
  });

  const result = await refreshProviderProfilesCommand(context);

  assert.equal(result.ok, true);
  assert.equal(context.__patches[0].providerConfig.configured, false);
  assert.equal(context.__patches[0].providerConfig.baseUrl, '');
  assert.equal(context.__patches[0].providerConfig.model, '');
});

test('refreshProviderProfilesCommand reads the local registry without calling the sidecar', async () => {
  const vscodeMock = {};
  const { refreshProviderProfilesCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();

  const result = await refreshProviderProfilesCommand(context);

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /profiles refreshed/i);
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__syncs.length, 1);
  assert.equal(context.__patches[0].providerConfig.profileId, 'openai-default');
  assert.equal(context.__patches[0].providerConfig.profileCount, 1);
  assert.equal(context.__patches[0].providerConfig.providerProfiles.length, 1);
  assert.equal(context.__patches[0].providerConfig.profileHistory.length, 1);
  assert.deepEqual(context.__patches[0].providerConfig.providerProfiles[0].requestDefaults, { store: false });
  assert.deepEqual(context.__patches[0].providerConfig.providerDashboard.currentProfile?.requestDefaults, {
    store: false,
  });
  assert.equal(context.__patches[0].providerConfig.providerDashboard.templateCount, 0);
  assert.equal(context.__patches[0].providerConfig.providerDashboard.taskBindingCount, 0);
  assert.deepEqual(context.__patches[0].providerConfig.providerDashboard.protocolCatalog, []);
});

test('openWorkspaceConfigCommand uses the canonical activeWorkspaceRoot when no workspace folder is active', async () => {
  let writtenConfig;
  const vscodeMock = {
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
      joinPath(base, ...segments) {
        return { fsPath: path.join(base.fsPath, ...segments) };
      },
    },
    workspace: {
      workspaceFolders: [],
      fs: {
        async createDirectory() {
          return undefined;
        },
        async stat() {
          throw new Error('ENOENT');
        },
        async writeFile(_uri, content) {
          writtenConfig = Buffer.from(content).toString('utf8');
          return undefined;
        },
      },
      async openTextDocument() {
        return { uri: { fsPath: path.join('F:\\trainer-root', '.vscode', 'trainer.json') } };
      },
    },
    window: {
      async showTextDocument() {
        return undefined;
      },
    },
  };
  const { openWorkspaceConfigCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    vscodeMock,
  );
  const context = {
    providerStore: {
      getConfig() {
        return undefined;
      },
    },
    getHostState() {
      return {
        workspace: {
          activeWorkspaceRoot: 'F:\\trainer-root',
          workspaceFolder: 'F:\\trainer-fallback',
        },
      };
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const result = await openWorkspaceConfigCommand(context);

  assert.equal(result.ok, true);
  assert.equal(result.data?.path, path.join('F:\\trainer-root', '.vscode', 'trainer.json'));
  assert.ok(writtenConfig);
  const parsed = JSON.parse(writtenConfig);
  assert.equal(parsed.provider.protocol, 'openai_chat_completions_compatible');
  assert.equal(parsed.provider.capabilities.structuredOutput, false);
  assert.equal(parsed.behavior.answerMode, 'auto');
});

test('openWorkspaceConfigCommand preserves provider requestDefaults in the generated workspace config', async () => {
  let writtenConfig;
  const vscodeMock = {
    Uri: {
      file(filePath) {
        return { fsPath: filePath };
      },
      joinPath(base, ...segments) {
        return { fsPath: path.join(base.fsPath, ...segments) };
      },
    },
    workspace: {
      workspaceFolders: [],
      fs: {
        async createDirectory() {
          return undefined;
        },
        async stat() {
          throw new Error('ENOENT');
        },
        async writeFile(_uri, content) {
          writtenConfig = Buffer.from(content).toString('utf8');
          return undefined;
        },
      },
      async openTextDocument() {
        return { uri: { fsPath: path.join('F:\\trainer-root', '.vscode', 'trainer.json') } };
      },
    },
    window: {
      async showTextDocument() {
        return undefined;
      },
    },
  };
  const { openWorkspaceConfigCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    vscodeMock,
  );
  const context = {
    providerStore: {
      getConfig() {
        return {
          name: 'OpenAI',
          baseUrl: 'https://api.openai.com/v1',
          model: 'gpt-5-mini',
          capabilities: {
            chat: true,
            responses: true,
            vision: true,
            embeddings: false,
            tools: true,
            jsonSchema: true,
            streaming: true,
          },
          requestDefaults: {
            extra_body: {
              thinking: {
                type: 'disabled',
              },
            },
          },
        };
      },
    },
    getHostState() {
      return {
        workspace: {
          activeWorkspaceRoot: 'F:\\trainer-root',
          workspaceFolder: 'F:\\trainer-fallback',
        },
      };
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const result = await openWorkspaceConfigCommand(context);

  assert.equal(result.ok, true);
  assert.equal(result.data?.path, path.join('F:\\trainer-root', '.vscode', 'trainer.json'));
  assert.ok(writtenConfig);
  const parsed = JSON.parse(writtenConfig);
  assert.equal(parsed.provider.protocol, 'openai_chat_completions_compatible');
  assert.deepEqual(parsed.provider.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
  assert.equal(parsed.behavior.answerMode, 'auto');
});

test('switchProviderModelCommand persists a model chosen from the live available model list', async () => {
  let savedConfig;
  let clearedLastTestConfig;
  const patches = [];
  const syncs = [];
  let currentConfig = {
    name: 'mini-max',
    label: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://47.107.101.18:3000/v1',
    apiKeyRef: 'mini-max.default',
    model: 'MiniMax-M3',
    contextWindowTokens: 64000,
    maxOutputTokens: 8000,
    modelTokenLimits: {
      'MiniMax-M3': {
        contextWindowTokens: 64000,
        maxOutputTokens: 8000,
      },
      'MiniMax-M2.7-highspeed': {
        contextWindowTokens: 128000,
        maxOutputTokens: 12000,
      },
    },
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
    availableModels: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    currentConfig,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  bootstrap.providerConfig.availableModels = ['MiniMax-M2.7-highspeed', 'MiniMax-M3'];
  bootstrap.providerConfig.modelListStatus = 'ready';
  bootstrap.providerConfig.modelListDetail = 'Loaded 2 live models.';
  bootstrap.providerConfig.resolvedModel = 'MiniMax-M3';
  bootstrap.providerConfig.contextWindowTokens = 64000;
  bootstrap.providerConfig.maxOutputTokens = 8000;
  bootstrap.providerConfig.modelTokenLimits = currentConfig.modelTokenLimits;
  bootstrap.providerConfig.lastTestResult = {
    ok: true,
    status: 'connected',
    detail: 'Provider reachable. Chat probe succeeded.',
    checkedAt: '2026-06-30T00:00:00.000Z',
    providerName: 'mini-max',
    baseUrl: 'http://47.107.101.18:3000/v1',
    model: 'MiniMax-M3',
  };

  const { switchProviderModelCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async saveConfig(config) {
        savedConfig = config;
        currentConfig = { ...currentConfig, ...config };
      },
      async getApiKey() {
        return 'sk-test';
      },
      async clearLastTestResult(config) {
        clearedLastTestConfig = config;
      },
      getLastTestResult() {
        return undefined;
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await switchProviderModelCommand(context, {
    model: 'MiniMax-M2.7-highspeed',
  });

  assert.equal(result.ok, true);
  assert.equal(savedConfig.model, 'MiniMax-M2.7-highspeed');
  assert.deepEqual(savedConfig.catalogModels, ['MiniMax-M3', 'MiniMax-M2.7-highspeed']);
  assert.equal(savedConfig.contextWindowTokens, 128000);
  assert.equal(savedConfig.maxOutputTokens, 12000);
  assert.equal(savedConfig.modelTokenLimits['MiniMax-M2.7-highspeed'].contextWindowTokens, 128000);
  assert.equal(clearedLastTestConfig.model, 'MiniMax-M2.7-highspeed');
  assert.equal(syncs.length, 1);
  assert.equal(patches[0].providerConfig.model, 'MiniMax-M2.7-highspeed');
  assert.equal(patches[0].providerConfig.contextWindowTokens, 128000);
  assert.equal(patches[0].providerConfig.maxOutputTokens, 12000);
  assert.equal(patches[0].providerConfig.protocol, 'openai_chat_completions_compatible');
  assert.equal(patches[0].providerConfig.protocolFamily, 'openai');
  assert.equal(patches[0].providerConfig.resolvedModel, 'MiniMax-M2.7-highspeed');
  assert.deepEqual(
    patches[0].providerConfig.availableModels,
    ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
  );
  assert.equal(patches[0].providerConfig.lastTestResult, undefined);
  assert.equal(patches[0].connection.provider.model, 'MiniMax-M2.7-highspeed');
  assert.equal(patches[0].connection.provider.protocol, 'openai_chat_completions_compatible');
  assert.equal(patches[0].connection.provider.protocolFamily, 'openai');
});

test('switchProviderModelCommand accepts a model preserved in the configured model catalog', async () => {
  let savedConfig;
  const patches = [];
  const syncs = [];
  let currentConfig = {
    name: 'mini-max',
    label: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://47.107.101.18:3000/v1',
    apiKeyRef: 'mini-max.default',
    model: 'MiniMax-M3',
    contextWindowTokens: 64000,
    maxOutputTokens: 8000,
    modelTokenLimits: {
      'MiniMax-M3': {
        contextWindowTokens: 64000,
        maxOutputTokens: 8000,
      },
      'MiniMax-M4-preview': {
        contextWindowTokens: 192000,
        maxOutputTokens: 16000,
      },
    },
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
    availableModels: ['MiniMax-M3'],
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    currentConfig,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  bootstrap.providerConfig.availableModels = ['MiniMax-M3'];
  bootstrap.providerConfig.modelTokenLimits = currentConfig.modelTokenLimits;
  bootstrap.providerConfig.modelListStatus = 'ready';
  bootstrap.providerConfig.modelListDetail = 'Loaded 1 live model.';
  bootstrap.providerConfig.resolvedModel = 'MiniMax-M3';

  const { switchProviderModelCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async saveConfig(config) {
        savedConfig = config;
        currentConfig = { ...currentConfig, ...config };
      },
      async getApiKey() {
        return 'sk-test';
      },
      async clearLastTestResult() {},
      getLastTestResult() {
        return undefined;
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await switchProviderModelCommand(context, {
    model: 'MiniMax-M4-preview',
  });

  assert.equal(result.ok, true);
  assert.equal(savedConfig.model, 'MiniMax-M4-preview');
  assert.deepEqual(savedConfig.catalogModels, ['MiniMax-M3', 'MiniMax-M4-preview']);
  assert.equal(savedConfig.contextWindowTokens, 192000);
  assert.equal(savedConfig.maxOutputTokens, 16000);
  assert.equal(syncs.length, 1);
  assert.equal(patches[0].providerConfig.model, 'MiniMax-M4-preview');
  assert.equal(patches[0].providerConfig.contextWindowTokens, 192000);
  assert.equal(patches[0].providerConfig.maxOutputTokens, 16000);
  assert.equal(patches[0].providerConfig.modelListStatus, 'idle');
  assert.match(patches[0].providerConfig.modelListDetail, /Test or refresh models/i);
  assert.equal(patches[0].providerConfig.lastTestResult, undefined);
});

test('refreshProviderModelsCommand redacts key-shaped detail from message and persist', async () => {
  const FAKE_KEY = 'sk-test-not-a-real-key-dddddddd';
  const FAKE_BEARER = 'Bearer fake-token-wwwwwwwwwwww';
  const patches = [];
  const savedCaches = [];
  const config = {
    name: 'Local Compatible',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://localhost:1234/v1',
    apiKeyRef: 'trainer.default',
    model: 'demo-model',
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
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    config,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  const { refreshProviderModelsCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return config;
      },
      async getApiKey() {
        return 'sk-test';
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
        savedCaches.push(payload);
        return {
          availableModels: payload.availableModels ?? [],
          resolvedModel: payload.resolvedModel,
          fetchedAt: payload.fetchedAt,
          expiresAt: '2026-07-04T00:00:00.000Z',
          source: payload.source,
          lastError: payload.lastError,
        };
      },
      async saveConfig() {
        return undefined;
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true };
      },
    },
    sidecarClient: {
      async postJson(_port, requestPath) {
        if (requestPath === '/provider/models') {
          return {
            ok: false,
            detail: `Model list rejected ${FAKE_KEY} (${FAKE_BEARER})`,
            available_models: [],
            error_category: 'invalid_key_or_permission',
            status_code: 401,
            retryable: false,
          };
        }
        throw new Error(`Unexpected POST ${requestPath}`);
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
      if (patch.providerConfig) {
        Object.assign(bootstrap.providerConfig, patch.providerConfig);
      }
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const result = await refreshProviderModelsCommand(context);
  assert.equal(result.ok, false);
  assert.doesNotMatch(result.message ?? '', /sk-test-not-a-real-key-dddddddd/);
  assert.doesNotMatch(result.message ?? '', /fake-token-wwwwwwwwwwww/);
  assert.ok(savedCaches.length >= 1);
  assert.doesNotMatch(String(savedCaches.at(-1).lastError ?? ''), /sk-test-not-a-real-key-dddddddd/);
  assert.doesNotMatch(String(savedCaches.at(-1).lastError ?? ''), /fake-token-wwwwwwwwwwww/);
  assert.doesNotMatch(JSON.stringify(patches), /sk-test-not-a-real-key-dddddddd/);
  assert.doesNotMatch(JSON.stringify(patches), /fake-token-wwwwwwwwwwww/);
  const modelListDetail = patches
    .map((patch) => patch.providerConfig?.modelListDetail)
    .filter(Boolean)
    .at(-1);
  assert.doesNotMatch(String(modelListDetail ?? ''), /sk-test-not-a-real-key-dddddddd/);
});

test('refreshProviderModelsCommand keeps protocol identity with refreshed models', async () => {
  const patches = [];
  const syncs = [];
  const savedCaches = [];
  const config = {
    name: 'Anthropic',
    label: 'Anthropic',
    protocol: 'anthropic_messages',
    baseUrl: 'http://minimax.redfast.top',
    apiKeyRef: 'anthropic.default',
    model: 'MiniMax-M3',
    capabilities: {
      chat: true,
      responses: false,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: false,
      structuredOutput: false,
      streaming: true,
    },
    availableModels: ['MiniMax-M3'],
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    config,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  const { refreshProviderModelsCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return config;
      },
      async getApiKey() {
        return 'sk-test';
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
        savedCaches.push({ config: _config, payload });
        return {
          availableModels: payload.availableModels,
          resolvedModel: payload.resolvedModel,
          fetchedAt: payload.fetchedAt,
          expiresAt: '2026-07-04T00:00:00.000Z',
          source: payload.source,
        };
      },
      async saveConfig() {
        return undefined;
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, route, body) {
        assert.equal(route, '/provider/models');
        assert.equal(body.provider.protocol, 'anthropic_messages');
        return {
          ok: true,
          detail: 'Loaded Anthropic-compatible models.',
          available_models: ['MiniMax-M3', 'MiniMax-M2.7-highspeed'],
          resolved_model: 'MiniMax-M3',
        };
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await refreshProviderModelsCommand(context);

  assert.equal(result.ok, true);
  assert.equal(syncs.length, 2);
  assert.equal(savedCaches[0].config.protocol, 'anthropic_messages');
  assert.equal(patches[1].providerConfig.protocol, 'anthropic_messages');
  assert.equal(patches[1].providerConfig.protocolFamily, 'anthropic');
  assert.equal(patches[1].providerConfig.model, 'MiniMax-M3');
  assert.deepEqual(patches[1].providerConfig.availableModels, [
    'MiniMax-M3',
    'MiniMax-M2.7-highspeed',
  ]);
});

test('refreshProviderModelsCommand finds models from an unsaved draft without changing the saved provider', async () => {
  const patches = [];
  const syncs = [];
  const requests = [];
  const savedConfig = {
    name: 'Saved Provider',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://saved.example/v1',
    apiKeyRef: 'saved.default',
    model: 'saved-model',
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
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    savedConfig,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  const { refreshProviderModelsCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return savedConfig;
      },
      async getApiKey() {
        throw new Error('A draft with an inline key must not read the saved key.');
      },
      getModelCache() {
        throw new Error('A draft lookup must not read the persisted model cache.');
      },
      async saveConfig() {
        throw new Error('A draft lookup must not save a provider.');
      },
      async saveModelCache() {
        throw new Error('A draft lookup must not write the persisted model cache.');
      },
      async saveLastTestResult() {
        throw new Error('A draft lookup must not write test history.');
      },
      async clearLastTestResult() {
        throw new Error('A draft lookup must not clear test history.');
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, route, body) {
        requests.push({ route, body });
        assert.equal(route, '/provider/models');
        assert.equal(body.apiKey, 'sk-draft');
        assert.equal(body.provider.baseUrl, 'https://draft.example/v1');
        assert.equal(body.provider.name, 'custom-openai-compatible');
        assert.equal(body.provider.model, '');
        assert.equal(body.provider.apiKeyRef, 'trainer.provider.draft');
        assert.equal(JSON.stringify(body.provider).includes('sk-draft'), false);
        return {
          ok: true,
          detail: 'Loaded 2 models from the draft connection.',
          available_models: ['draft-fast', 'draft-reasoning'],
        };
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await refreshProviderModelsCommand(context, {
    draft: {
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://draft.example/v1/chat/completions?temporary=true',
      apiKey: 'sk-draft',
    },
  });

  assert.equal(result.ok, true);
  assert.equal(result.data.baseUrl, 'https://draft.example/v1');
  assert.equal(requests.length, 1);
  assert.equal(syncs.length, 2);
  assert.equal(patches[0].providerConfig.name, 'Saved Provider');
  assert.equal(patches[0].providerConfig.modelListStatus, 'loading');
  assert.equal((patches[1].providerConfig.availableModels ?? []).includes('draft-fast'), false);
  assert.equal(patches[1].providerConfig.modelListStatus, 'ready');
  assert.deepEqual(patches[1].providerConfig.modelListing, {
    source: 'draft',
    name: 'custom-openai-compatible',
    baseUrl: 'https://draft.example/v1',
    protocol: 'openai_chat_completions_compatible',
    protocolFamily: 'openai',
    model: '',
    availableModels: ['draft-fast', 'draft-reasoning'],
    resolvedModel: undefined,
    modelTokenLimits: undefined,
    fetchedAt: patches[1].providerConfig.modelListing.fetchedAt,
    errorCategory: undefined,
    retryable: undefined,
    statusCode: undefined,
  });
  assert.equal(JSON.stringify(patches).includes('sk-draft'), false);
});

test('refreshProviderModelsCommand keeps a newer active connection when an older lookup finishes later', async () => {
  const patches = [];
  const savedConfigs = [];
  let resolveLookup;
  let markLookupStarted;
  const lookupStarted = new Promise((resolve) => {
    markLookupStarted = resolve;
  });
  let currentConfig = {
    name: 'Provider A',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://provider-a.example/v1',
    apiKeyRef: 'provider-a.default',
    model: 'a-model',
    availableModels: ['a-model'],
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
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
    currentConfig,
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  const { refreshProviderModelsCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async getApiKey() {
        return currentConfig.apiKeyRef === 'provider-a.default' ? 'old-key' : 'new-key';
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
          ...payload,
          fetchedAt: payload.fetchedAt,
          expiresAt: '2026-07-20T00:00:00.000Z',
        };
      },
      async saveConfig(config) {
        savedConfigs.push(config);
        currentConfig = config;
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, route, body) {
        assert.equal(route, '/provider/models');
        assert.equal(body.apiKey, 'old-key');
        markLookupStarted();
        return new Promise((resolve) => {
          resolveLookup = resolve;
        });
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-stale-active-provider';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const refresh = refreshProviderModelsCommand(context);
  await lookupStarted;
  currentConfig = {
    ...currentConfig,
    name: 'Provider B',
    baseUrl: 'https://provider-b.example/v1',
    apiKeyRef: 'provider-b.default',
    model: 'b-model',
    availableModels: ['b-model'],
  };
  resolveLookup({
    ok: true,
    detail: 'Loaded Provider A models.',
    available_models: ['a-model', 'a-reasoning'],
    resolved_model: 'a-model',
  });

  const result = await refresh;

  assert.equal(result.ok, true);
  assert.equal(result.data.model, 'b-model');
  assert.deepEqual(savedConfigs, []);
  assert.equal(patches.length, 1);
  assert.equal(patches[0].providerConfig.modelListStatus, 'loading');
  assert.equal(JSON.stringify(patches).includes('old-key'), false);
});

test('fetchProviderModels does not share an in-flight lookup after the key changes on the same connection', async () => {
  const requests = [];
  let resolveFirstLookup;
  let resolveSecondLookup;
  let markBothStarted;
  const bothStarted = new Promise((resolve) => {
    markBothStarted = resolve;
  });
  const config = {
    name: 'Same Endpoint',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://same.example/v1',
    apiKeyRef: 'same.default',
    model: 'same-model',
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
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
    config,
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  const { fetchProviderModels } = loadWithVscodeMock(providerWebviewCommandsModulePath, {});
  const context = {
    providerStore: {
      getConfig() {
        return config;
      },
      async getApiKey() {
        return 'new-key';
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
          ...payload,
          fetchedAt: payload.fetchedAt,
          expiresAt: '2026-07-20T00:00:00.000Z',
        };
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, route, body) {
        assert.equal(route, '/provider/models');
        requests.push(body);
        if (requests.length === 1) {
          return new Promise((resolve) => {
            resolveFirstLookup = resolve;
          });
        }
        markBothStarted();
        return new Promise((resolve) => {
          resolveSecondLookup = resolve;
        });
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-key-rotation';
    },
    async patchWorkbenchData() {
      return undefined;
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const firstLookup = fetchProviderModels(context, config, 'old-key', { forceRefresh: true });
  const secondLookup = fetchProviderModels(context, config, 'new-key', { forceRefresh: true });
  await bothStarted;
  resolveFirstLookup({ ok: true, detail: 'Old key models.', available_models: ['old-model'] });
  resolveSecondLookup({ ok: true, detail: 'New key models.', available_models: ['new-model'] });

  const [firstResult, secondResult] = await Promise.all([firstLookup, secondLookup]);
  assert.deepEqual(requests.map((request) => request.apiKey), ['old-key', 'new-key']);
  assert.deepEqual(firstResult.availableModels, ['old-model']);
  assert.deepEqual(secondResult.availableModels, ['new-model']);
});

test('refreshProviderModelsCommand respects an active profile change before its config is materialized', async () => {
  const patches = [];
  const savedConfigs = [];
  let activeProfileId = 'profile-a';
  let resolveLookup;
  let markLookupStarted;
  const lookupStarted = new Promise((resolve) => {
    markLookupStarted = resolve;
  });
  const currentConfig = {
    profileId: 'profile-a',
    name: 'Profile A',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://profile-a.example/v1',
    apiKeyRef: 'profile-a.default',
    model: 'a-model',
    availableModels: ['a-model'],
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
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
    currentConfig,
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  const { refreshProviderModelsCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      getProfileRegistrySnapshot() {
        return { activeProfileId };
      },
      async getApiKey() {
        return 'profile-a-key';
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
          ...payload,
          fetchedAt: payload.fetchedAt,
          expiresAt: '2026-07-20T00:00:00.000Z',
        };
      },
      async saveConfig(config) {
        savedConfigs.push(config);
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson() {
        markLookupStarted();
        return new Promise((resolve) => {
          resolveLookup = resolve;
        });
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-pending-profile-switch';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const refresh = refreshProviderModelsCommand(context);
  await lookupStarted;
  activeProfileId = 'profile-b';
  resolveLookup({
    ok: true,
    detail: 'Loaded Profile A models.',
    available_models: ['a-model', 'a-reasoning'],
    resolved_model: 'a-model',
  });

  const result = await refresh;

  assert.equal(result.ok, true);
  assert.equal(result.data.profileId, 'profile-a');
  assert.deepEqual(savedConfigs, []);
  assert.equal(patches.length, 1);
  assert.equal(JSON.stringify(patches).includes('profile-a-key'), false);
});

test('refreshProviderModelsCommand ignores a lookup once a newer model switch has started', async () => {
  const patches = [];
  const savedConfigs = [];
  let resolveLookup;
  let resolveSwitchSave;
  let markLookupStarted;
  let markSwitchSaveStarted;
  const lookupStarted = new Promise((resolve) => {
    markLookupStarted = resolve;
  });
  const switchSaveStarted = new Promise((resolve) => {
    markSwitchSaveStarted = resolve;
  });
  let currentConfig = {
    name: 'Provider A',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://provider-a.example/v1',
    apiKeyRef: 'provider-a.default',
    model: 'a-model',
    availableModels: ['a-model', 'b-model'],
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
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
    currentConfig,
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  bootstrap.providerConfig.availableModels = ['a-model', 'b-model'];
  const { refreshProviderModelsCommand, switchProviderModelCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async getApiKey() {
        return 'provider-key';
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
          ...payload,
          fetchedAt: payload.fetchedAt,
          expiresAt: '2026-07-20T00:00:00.000Z',
        };
      },
      async saveConfig(config) {
        savedConfigs.push(config);
        if (config.model === 'b-model') {
          markSwitchSaveStarted();
          await new Promise((resolve) => {
            resolveSwitchSave = () => {
              currentConfig = config;
              resolve();
            };
          });
          return;
        }
        currentConfig = config;
      },
      async clearLastTestResult() {
        return undefined;
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson() {
        markLookupStarted();
        return new Promise((resolve) => {
          resolveLookup = resolve;
        });
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-pending-model-switch';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const refresh = refreshProviderModelsCommand(context);
  await lookupStarted;
  const switchModel = switchProviderModelCommand(context, { model: 'b-model' });
  await switchSaveStarted;
  resolveLookup({
    ok: true,
    detail: 'Loaded Provider A models.',
    available_models: ['a-model', 'a-reasoning'],
    resolved_model: 'a-model',
  });

  const refreshResult = await refresh;
  assert.equal(refreshResult.ok, true);
  assert.deepEqual(savedConfigs.map((config) => config.model), ['b-model']);
  assert.equal(patches.length, 1);

  resolveSwitchSave();
  const switchResult = await switchModel;
  assert.equal(switchResult.ok, true);
  assert.equal(currentConfig.model, 'b-model');
  assert.equal(JSON.stringify(patches).includes('provider-key'), false);
});

test('refreshProviderModelsCommand ignores an older draft lookup after a newer draft is requested', async () => {
  const patches = [];
  const requests = [];
  let resolveFirstLookup;
  let resolveSecondLookup;
  let markFirstStarted;
  let markSecondStarted;
  const firstStarted = new Promise((resolve) => {
    markFirstStarted = resolve;
  });
  const secondStarted = new Promise((resolve) => {
    markSecondStarted = resolve;
  });
  const savedConfig = {
    name: 'Saved Provider',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://saved.example/v1',
    apiKeyRef: 'saved.default',
    model: 'saved-model',
    availableModels: ['saved-model'],
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
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
    savedConfig,
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  const { refreshProviderModelsCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return savedConfig;
      },
      async getApiKey() {
        throw new Error('Draft discovery must not read the saved key.');
      },
      getModelCache() {
        throw new Error('Draft discovery must not read the saved cache.');
      },
      async saveConfig() {
        throw new Error('Draft discovery must not save a provider.');
      },
      async saveModelCache() {
        throw new Error('Draft discovery must not write a cache.');
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, route, body) {
        assert.equal(route, '/provider/models');
        requests.push(body);
        if (requests.length === 1) {
          markFirstStarted();
          return new Promise((resolve) => {
            resolveFirstLookup = resolve;
          });
        }
        markSecondStarted();
        return new Promise((resolve) => {
          resolveSecondLookup = resolve;
        });
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-stale-draft-provider';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const firstRefresh = refreshProviderModelsCommand(context, {
    draft: {
      baseUrl: 'https://draft-a.example/v1',
      apiKey: 'draft-key-a',
    },
  });
  await firstStarted;
  const secondRefresh = refreshProviderModelsCommand(context, {
    draft: {
      baseUrl: 'https://draft-b.example/v1',
      apiKey: 'draft-key-b',
    },
  });
  await secondStarted;
  resolveFirstLookup({
    ok: true,
    detail: 'Loaded Draft A models.',
    available_models: ['draft-a-model'],
  });

  const firstResult = await firstRefresh;
  assert.equal(firstResult.ok, true);
  assert.match(firstResult.message ?? '', /kept your newer choice/i);
  assert.equal(patches.length, 2);

  resolveSecondLookup({
    ok: true,
    detail: 'Loaded Draft B models.',
    available_models: ['draft-b-model'],
  });
  const secondResult = await secondRefresh;

  assert.equal(secondResult.ok, true);
  assert.equal(patches.length, 3);
  assert.equal(patches[2].providerConfig.modelListing.baseUrl, 'https://draft-b.example/v1');
  assert.deepEqual(patches[2].providerConfig.modelListing.availableModels, ['draft-b-model']);
  assert.equal((patches[2].providerConfig.availableModels ?? []).includes('draft-b-model'), false);
  assert.equal(JSON.stringify(patches).includes('draft-key-a'), false);
  assert.equal(JSON.stringify(patches).includes('draft-key-b'), false);
});

test('refreshProviderModelsCommand does not send an unsaved draft key before workspace trust is granted', async () => {
  const patches = [];
  let sidecarStarts = 0;
  let requests = 0;
  const savedConfig = {
    name: 'Saved Provider',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://saved.example/v1',
    apiKeyRef: 'saved.default',
    model: 'saved-model',
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
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: false,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    savedConfig,
    {
      lifecycle: 'idle',
      host: '127.0.0.1',
      canStart: true,
    },
  );
  const { refreshProviderModelsCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return savedConfig;
      },
      getModelCache() {
        throw new Error('A draft lookup must not read the persisted model cache.');
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return false;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        sidecarStarts += 1;
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson() {
        requests += 1;
        return { ok: true };
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'idle', host: '127.0.0.1', canStart: true },
        workspace: { trusted: false, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const result = await refreshProviderModelsCommand(context, {
    draft: {
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://draft.example/v1',
      apiKey: 'sk-draft',
    },
  });

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /workspace trust/i);
  assert.equal(sidecarStarts, 0);
  assert.equal(requests, 0);
  assert.equal(patches.length, 2);
  assert.equal(patches[1].providerConfig.modelErrorCategory, 'workspace_trust');
  assert.equal(JSON.stringify(patches).includes('sk-draft'), false);
});

test('saveProviderFromWebviewCommand normalizes pasted completion endpoints to service roots', async () => {
  const cases = [
    {
      protocol: 'openai_chat_completions_compatible',
      input: 'https://api.example/v1/chat/completions?temporary=true',
      expected: 'https://api.example/v1',
    },
    {
      protocol: 'openai_responses',
      input: 'https://api.example/v1/responses',
      expected: 'https://api.example/v1',
    },
    {
      protocol: 'anthropic_messages',
      input: 'https://api.example/v1/messages',
      expected: 'https://api.example/v1',
    },
    {
      protocol: 'gemini_generate_content',
      input: 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=temporary',
      expected: 'https://generativelanguage.googleapis.com/v1beta',
    },
  ];
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );

  for (const entry of cases) {
    let currentConfig;
    let savedConfig;
    const bootstrap = createDefaultBootstrapData(
      {
        trusted: true,
        workspaceFolder: 'F:\\trainer\\workspace-a',
      },
      undefined,
      {
        lifecycle: 'ready',
        host: '127.0.0.1',
        port: 34891,
        canStart: true,
      },
    );
    const context = {
      providerStore: {
        getConfig() {
          return currentConfig;
        },
        async clearModelCache() {
          return undefined;
        },
        async saveConfig(config) {
          savedConfig = config;
          currentConfig = config;
        },
        async getApiKey() {
          return undefined;
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
        getLastTestResult() {
          return undefined;
        },
      },
      getHostState() {
        return {
          bootstrap,
          sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
          workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
        };
      },
      getSessionId() {
        return 'session-1';
      },
      async patchWorkbenchData() {
        return undefined;
      },
      workbench: {
        async syncState() {
          return undefined;
        },
      },
    };

    const result = await saveProviderFromWebviewCommand(context, {
      name: '',
      protocol: entry.protocol,
      baseUrl: entry.input,
      model: 'test-model',
    });

    assert.equal(result.ok, true);
    assert.equal(savedConfig.name, 'custom-openai-compatible');
    assert.equal(savedConfig.baseUrl, entry.expected);
  }
});

test('refreshProviderModelsCommand sends SecretStorage credentials only in local sidecar request bodies for both modes', async () => {
  for (const credentialMode of ['ui_proxy', 'workspace_secret']) {
    const apiKey = `test-provider-key-${credentialMode}`;
    const requests = [];
    const patches = [];
    let currentConfig = {
      name: `Provider ${credentialMode}`,
      label: `Provider ${credentialMode}`,
      protocol: 'openai_chat_completions_compatible',
      credentialMode,
      baseUrl: 'http://127.0.0.1:1234/v1',
      apiKeyRef: `provider.${credentialMode}`,
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
      availableModels: [],
    };
    const bootstrap = createDefaultBootstrapData(
      {
        trusted: true,
        workspaceFolder: 'F:\\trainer\\workspace-a',
      },
      currentConfig,
      {
        lifecycle: 'ready',
        host: '127.0.0.1',
        port: 34891,
        canStart: true,
      },
    );
    const managedContextId = `context-provider-models-${credentialMode}`;
    bootstrap.memory.workspace = {
      ...(bootstrap.memory.workspace ?? {}),
      trainerWorkspace: {
        status: 'managed',
        contextId: managedContextId,
        canonicalProjectPath: 'f:\\trainer\\workspace-a',
        rootId: 'root-provider-models',
        projectId: 'project-provider-models',
      },
    };
    const { refreshProviderModelsCommand } = loadWithVscodeMock(
      providerWebviewCommandsModulePath,
      {},
    );
    const context = {
      providerStore: {
        getConfig() {
          return currentConfig;
        },
        async getApiKey() {
          return apiKey;
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
            expiresAt: '2026-07-10T12:00:00.000Z',
            source: payload.source,
          };
        },
        async saveConfig(nextConfig) {
          currentConfig = nextConfig;
        },
        getLastTestResult() {
          return undefined;
        },
      },
      trustGuard: {
        async ensureTrusted() {
          return true;
        },
      },
      sidecarManager: {
        async ensureRunning() {
          return { lifecycle: 'ready', port: 34891 };
        },
      },
      sidecarClient: {
        async getJson() {
          throw new Error('Provider model refresh must not load the retired dashboard endpoint.');
        },
        async postJson(_port, route, body) {
          requests.push({ route, body });
          assert.notEqual(route, '/provider/workspace-secret/save');
          assert.notEqual(route, '/provider/workspace-secret/clear');
          assert.equal(route, '/provider/models');
          return {
            ok: true,
            detail: 'Loaded test models.',
            available_models: ['test-model'],
            resolved_model: 'test-model',
          };
        },
      },
      getHostState() {
        return {
          bootstrap,
          sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
          workspace: {
            trusted: true,
            workspaceFolder: 'F:\\trainer\\workspace-a',
          },
        };
      },
      getSessionId() {
        return 'session-1';
      },
      async patchWorkbenchData(patch) {
        patches.push(patch);
      },
      workbench: {
        async syncState() {
          return undefined;
        },
      },
    };

    const result = await refreshProviderModelsCommand(context);

    assert.equal(result.ok, true);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].body.apiKey, apiKey);
    assert.equal(requests[0].body.api_key_ref, currentConfig.apiKeyRef);
    assert.equal(requests[0].body.workspace_id, managedContextId);
    assert.equal(requests[0].body.provider.credentialMode, credentialMode);
    assert.equal(JSON.stringify(requests[0].body.provider).includes(apiKey), false);
    assert.equal(JSON.stringify(patches).includes(apiKey), false);
  }
});

test('refreshProviderModelsCommand restores saved per-model limits when live refresh resolves to a different model', async () => {
  const patches = [];
  const syncs = [];
  const savedCaches = [];
  let savedConfig;
  let currentConfig = {
    name: 'mini-max',
    label: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://47.107.101.18:3000/v1',
    apiKeyRef: 'mini-max.default',
    model: 'MiniMax-M3',
    contextWindowTokens: 64000,
    maxOutputTokens: 8000,
    modelTokenLimits: {
      'MiniMax-M3': {
        contextWindowTokens: 64000,
        maxOutputTokens: 8000,
      },
    },
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
    availableModels: ['MiniMax-M3', 'retired-model'],
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    currentConfig,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  bootstrap.providerConfig.availableModels = ['MiniMax-M3'];
  bootstrap.providerConfig.modelListStatus = 'ready';
  bootstrap.providerConfig.modelListDetail = 'Loaded 1 live model.';
  bootstrap.providerConfig.resolvedModel = 'MiniMax-M3';
  bootstrap.providerConfig.contextWindowTokens = 64000;
  bootstrap.providerConfig.maxOutputTokens = 8000;
  bootstrap.providerConfig.modelTokenLimits = currentConfig.modelTokenLimits;

  const { refreshProviderModelsCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async getApiKey() {
        return 'sk-test';
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
      async saveConfig(config) {
        savedConfig = config;
        currentConfig = { ...currentConfig, ...config };
      },
      async saveModelCache(_config, payload) {
        savedCaches.push({ config: _config, payload });
        return {
          availableModels: payload.availableModels,
          resolvedModel: payload.resolvedModel,
          fetchedAt: payload.fetchedAt,
          expiresAt: '2026-07-04T00:00:00.000Z',
          source: payload.source,
        };
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, route, body) {
        assert.equal(route, '/provider/models');
        assert.equal(body.provider.model, 'MiniMax-M3');
        return {
          ok: true,
          detail: 'Fetched 2 models. Resolved configured model to MiniMax-M2.7-highspeed.',
          available_models: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
          resolved_model: 'MiniMax-M2.7-highspeed',
          model_token_limits: {
            'MiniMax-M2.7-highspeed': {
              context_window_tokens: 128000,
              max_output_tokens: 12000,
            },
          },
        };
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  const result = await refreshProviderModelsCommand(context);

  assert.equal(result.ok, true);
  assert.equal(savedConfig.model, 'MiniMax-M2.7-highspeed');
  assert.equal(savedConfig.contextWindowTokens, 128000);
  assert.equal(savedConfig.maxOutputTokens, 12000);
  assert.deepEqual(savedConfig.availableModels, ['MiniMax-M2.7-highspeed', 'MiniMax-M3']);
  assert.equal(
    savedConfig.modelTokenLimits['MiniMax-M2.7-highspeed'].contextWindowTokens,
    128000,
  );
  assert.equal(savedCaches[0].payload.modelTokenLimits['MiniMax-M2.7-highspeed'].contextWindowTokens, 128000);
  assert.equal(savedCaches[0].config.model, 'MiniMax-M2.7-highspeed');
  assert.equal(syncs.length, 2);
  assert.equal(patches[1].providerConfig.model, 'MiniMax-M2.7-highspeed');
  assert.equal(patches[1].providerConfig.contextWindowTokens, 128000);
  assert.equal(patches[1].providerConfig.maxOutputTokens, 12000);
  assert.equal(patches[1].providerConfig.resolvedModel, 'MiniMax-M2.7-highspeed');
});

test('primeProviderModelsState quietly warms the saved provider model list for Settings', async () => {
  const patches = [];
  const syncs = [];
  const savedCaches = [];
  let currentConfig = {
    name: 'MiniMax',
    label: 'MiniMax',
    protocol: 'anthropic_messages',
    baseUrl: 'http://minimax.redfast.top',
    apiKeyRef: 'anthropic.default',
    model: 'MiniMax-M3',
    capabilities: {
      chat: true,
      responses: false,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: false,
      structuredOutput: false,
      streaming: true,
    },
    availableModels: [],
  };
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    currentConfig,
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  bootstrap.providerConfig.availableModels = [];
  bootstrap.providerConfig.modelListStatus = 'idle';

  const { primeProviderModelsState } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async getApiKey() {
        return 'sk-test';
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
        savedCaches.push({ config: _config, payload });
        return {
          availableModels: payload.availableModels,
          resolvedModel: payload.resolvedModel,
          fetchedAt: payload.fetchedAt,
          expiresAt: '2026-07-06T12:00:00.000Z',
          source: payload.source,
          modelTokenLimits: payload.modelTokenLimits,
        };
      },
      async saveConfig(config) {
        currentConfig = { ...currentConfig, ...config };
      },
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, route, body) {
        assert.equal(route, '/provider/models');
        assert.equal(body.provider.protocol, 'anthropic_messages');
        return {
          ok: true,
          detail: 'Loaded 2 live models.',
          available_models: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
          resolved_model: 'MiniMax-M3',
          model_token_limits: {
            'MiniMax-M3': {
              context_window_tokens: 1048576,
              max_output_tokens: 16384,
            },
          },
        };
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: {
          trusted: true,
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        syncs.push(true);
      },
    },
  };

  await primeProviderModelsState(context);

  assert.equal(savedCaches.length, 1);
  assert.equal(syncs.length, 1);
  assert.equal(patches[0].providerConfig.modelListStatus, 'ready');
  assert.equal(patches[0].providerConfig.model, 'MiniMax-M3');
  assert.deepEqual(patches[0].providerConfig.availableModels, [
    'MiniMax-M2.7-highspeed',
    'MiniMax-M3',
  ]);
  assert.equal(patches[0].providerConfig.contextWindowTokens, 1048576);
  assert.equal(patches[0].providerConfig.maxOutputTokens, 16384);
  assert.equal(
    patches[0].providerConfig.modelTokenLimits['MiniMax-M3'].contextWindowTokens,
    1048576,
  );
});

test('saveProviderFromWebviewCommand never sends a newly saved key from an untrusted workspace', async () => {
  const { saveProviderFromWebviewCommand } = loadWithVscodeMock(
    providerWebviewCommandsModulePath,
    {},
  );
  let currentConfig;
  let savedApiKey;
  let sidecarStarts = 0;
  let requests = 0;
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: false,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    undefined,
    {
      lifecycle: 'idle',
      host: '127.0.0.1',
      canStart: true,
    },
  );
  const context = {
    providerStore: {
      getConfig() {
        return currentConfig;
      },
      async saveConfig(config, apiKey) {
        currentConfig = { ...config };
        savedApiKey = apiKey;
      },
      async getApiKey() {
        return savedApiKey;
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
      getLastTestResult() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return false;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        sidecarStarts += 1;
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson() {
        requests += 1;
        return { ok: true };
      },
    },
    getHostState() {
      return {
        bootstrap,
        sidecar: { lifecycle: 'idle', host: '127.0.0.1', canStart: true },
        workspace: { trusted: false, workspaceFolder: 'F:\\trainer\\workspace-a' },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData() {
      return undefined;
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
  };

  const result = await saveProviderFromWebviewCommand(context, {
    name: '中文服务',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://draft.example/v1',
    model: 'draft-model',
    apiKey: 'sk-local-only',
    replaceApiKey: true,
  });

  assert.equal(result.ok, true);
  assert.equal(savedApiKey, 'sk-local-only');
  assert.match(currentConfig.apiKeyRef, /^trainer\.provider\.[0-9a-f-]{36}$/i);
  assert.equal(sidecarStarts, 0);
  assert.equal(requests, 0);
  assert.match(result.message ?? '', /workspace trust/i);
});
