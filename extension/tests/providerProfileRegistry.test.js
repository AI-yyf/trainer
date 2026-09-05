'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const providerProfileRegistryModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'provider',
  'providerProfileRegistry.js',
);

const STORAGE_KEYS = {
  providerProfileRegistry: 'trainer.provider.profileRegistry',
  providerActiveProfileId: 'trainer.provider.activeProfileId',
  providerProfileSwitchHistory: 'trainer.provider.profileSwitchHistory',
};

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

function createVscodeMock(remoteName) {
  return {
    EventEmitter: FakeEventEmitter,
    env: {
      remoteName,
    },
  };
}

function createProfile(id, overrides = {}) {
  return {
    id,
    label: id.replace(/-/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase()),
    protocol: 'openai_responses',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyRef: `${id}.api`,
    model: 'gpt-5.1-mini',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'gpt-5.1-mini',
    },
    availableModels: ['gpt-5.1-mini'],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: { alias: 'coach-fast' },
    },
    requestDefaults: {},
    capabilities: {
      chat: true,
      responses: true,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: true,
      streaming: true,
    },
    modelCapabilities: {
      'gpt-5.1-mini': {
        chat: true,
        responses: true,
        vision: true,
        embeddings: false,
        tools: true,
        jsonSchema: true,
        streaming: true,
      },
    },
    ...overrides,
  };
}

test('getActiveProfileId prefers registry state over a stale standalone key', () => {
  const { ProviderProfileRegistry } = loadWithVscodeMock(
    providerProfileRegistryModulePath,
    createVscodeMock(),
  );
  const activeProfile = createProfile('openai-primary');
  const globalState = createGlobalState({
    [STORAGE_KEYS.providerProfileRegistry]: {
      version: '2.0.0',
      activeProfileId: activeProfile.id,
      profiles: [activeProfile],
      switchHistory: [],
      lastModified: '2026-06-10T00:00:00.000Z',
    },
    [STORAGE_KEYS.providerActiveProfileId]: 'stale-profile',
    [STORAGE_KEYS.providerProfileSwitchHistory]: [],
  });

  const registry = new ProviderProfileRegistry({
    globalState,
    secrets: createSecrets(),
  });

  assert.equal(registry.getActiveProfileId(), activeProfile.id);
  assert.equal(registry.getActiveProfile()?.id, activeProfile.id);
});

test('switchToProfile keeps registry and standalone active keys in sync', async () => {
  const { ProviderProfileRegistry } = loadWithVscodeMock(
    providerProfileRegistryModulePath,
    createVscodeMock(),
  );
  const profiles = [createProfile('openai-primary'), createProfile('anthropic-primary')];
  const globalState = createGlobalState({
    [STORAGE_KEYS.providerProfileRegistry]: {
      version: '2.0.0',
      activeProfileId: '',
      profiles,
      switchHistory: [],
      lastModified: '2026-06-10T00:00:00.000Z',
    },
    [STORAGE_KEYS.providerProfileSwitchHistory]: [],
  });

  const registry = new ProviderProfileRegistry({
    globalState,
    secrets: createSecrets(),
  });

  const switched = await registry.switchToProfile('anthropic-primary', 'manual_switch');

  assert.equal(switched, true);
  assert.equal(registry.getActiveProfileId(), 'anthropic-primary');
  assert.equal(registry.getActiveProfile()?.id, 'anthropic-primary');
  assert.equal(
    globalState.get(STORAGE_KEYS.providerProfileRegistry).activeProfileId,
    'anthropic-primary',
  );
  assert.equal(globalState.get(STORAGE_KEYS.providerActiveProfileId), 'anthropic-primary');
  assert.equal(registry.getSwitchHistory()[0].toProfileId, 'anthropic-primary');
  assert.equal(registry.getSwitchHistory()[0].reason, 'manual_switch');
});

test('clearActiveProfile clears both registry and standalone active keys', async () => {
  const { ProviderProfileRegistry } = loadWithVscodeMock(
    providerProfileRegistryModulePath,
    createVscodeMock(),
  );
  const activeProfile = createProfile('openai-primary');
  const globalState = createGlobalState({
    [STORAGE_KEYS.providerProfileRegistry]: {
      version: '2.0.0',
      activeProfileId: activeProfile.id,
      profiles: [activeProfile],
      switchHistory: [],
      lastModified: '2026-06-10T00:00:00.000Z',
    },
    [STORAGE_KEYS.providerActiveProfileId]: activeProfile.id,
    [STORAGE_KEYS.providerProfileSwitchHistory]: [],
  });

  const registry = new ProviderProfileRegistry({
    globalState,
    secrets: createSecrets(),
  });

  const cleared = await registry.clearActiveProfile('manual_clear');

  assert.equal(cleared, true);
  assert.equal(registry.getActiveProfileId(), undefined);
  assert.equal(registry.getActiveProfile(), undefined);
  assert.equal(globalState.get(STORAGE_KEYS.providerActiveProfileId), undefined);
  assert.equal(globalState.get(STORAGE_KEYS.providerProfileRegistry).activeProfileId, '');
  assert.equal(registry.getSwitchHistory()[0].toProfileId, '');
  assert.equal(registry.getSwitchHistory()[0].reason, 'manual_clear');
});

test('built-in templates expose resource rerank task binding', () => {
  const { PROVIDER_PROFILE_TEMPLATES } = loadWithVscodeMock(
    providerProfileRegistryModulePath,
    createVscodeMock(),
  );

  assert.equal(PROVIDER_PROFILE_TEMPLATES[0].taskBindings.resource_rerank.alias, 'coach-fast');
  assert.equal(PROVIDER_PROFILE_TEMPLATES[0].taskBindings.resource_rerank.fallbackAliases[0], 'coach-deep');
  assert.equal(PROVIDER_PROFILE_TEMPLATES[1].taskBindings.resource_rerank.alias, 'coach-fast');
});

test('built-in templates cover the required provider protocol set', () => {
  const { PROVIDER_PROFILE_TEMPLATES } = loadWithVscodeMock(
    providerProfileRegistryModulePath,
    createVscodeMock(),
  );

  const protocols = new Set(PROVIDER_PROFILE_TEMPLATES.map((template) => template.protocol));
  assert.ok(protocols.has('openai_responses'));
  assert.ok(protocols.has('openai_chat_completions'));
  assert.ok(protocols.has('anthropic_messages'));
  assert.ok(protocols.has('openai_chat_completions_compatible'));
  assert.ok(protocols.has('gemini_generate_content'));
});

test('MiniMax template uses the official endpoint and disables thinking for M3 requests', () => {
  const { PROVIDER_PROFILE_TEMPLATES } = loadWithVscodeMock(
    providerProfileRegistryModulePath,
    createVscodeMock(),
  );

  const minimax = PROVIDER_PROFILE_TEMPLATES.find((template) => template.label === 'MiniMax');
  assert.ok(minimax, 'expected a MiniMax template');
  assert.equal(minimax.baseUrl, 'https://api.minimaxi.com/v1');
  assert.equal(minimax.model, 'MiniMax-M3');
  assert.equal(minimax.requestDefaults.extra_body.thinking.type, 'disabled');
  assert.equal(minimax.taskBindings.coach_reply.alias, 'coach-fast');
  assert.equal(minimax.taskBindings.coach_reply.fallbackAliases[0], 'coach-deep');
});

test('built-in templates derive protocol defaults and only narrow where needed', () => {
  const { PROVIDER_PROFILE_TEMPLATES } = loadWithVscodeMock(
    providerProfileRegistryModulePath,
    createVscodeMock(),
  );

  const openaiResponses = PROVIDER_PROFILE_TEMPLATES.find((template) => template.protocol === 'openai_responses');
  const anthropic = PROVIDER_PROFILE_TEMPLATES.find((template) => template.protocol === 'anthropic_messages');
  const openrouter = PROVIDER_PROFILE_TEMPLATES.find(
    (template) => template.label === 'OpenRouter',
  );

  assert.ok(openaiResponses);
  assert.ok(anthropic);
  assert.ok(openrouter);
  assert.equal(openaiResponses.capabilities.responses, true);
  assert.equal(openaiResponses.capabilities.structuredOutput, true);
  assert.equal(anthropic.capabilities.responses, false);
  assert.equal(anthropic.capabilities.structuredOutput, false);
  assert.equal(openrouter.capabilities.tools, false);
  assert.equal(openrouter.capabilities.jsonSchema, false);
  assert.equal(openrouter.capabilities.structuredOutput, false);
  assert.deepEqual(openaiResponses.taskBindings.coach_reply.requiredCapabilities, [
    'structuredOutput',
    'streaming',
  ]);
  assert.deepEqual(anthropic.taskBindings.coach_reply.requiredCapabilities, ['streaming']);
  assert.deepEqual(openrouter.taskBindings.coach_reply.requiredCapabilities, ['streaming']);
});

test('template profiles default to workspace secret on remote workspaces', async () => {
  const { ProviderProfileRegistry } = loadWithVscodeMock(
    providerProfileRegistryModulePath,
    createVscodeMock('ssh-remote'),
  );
  const globalState = createGlobalState({
    [STORAGE_KEYS.providerProfileRegistry]: {
      version: '2.0.0',
      activeProfileId: '',
      profiles: [],
      switchHistory: [],
      lastModified: '2026-06-10T00:00:00.000Z',
    },
    [STORAGE_KEYS.providerProfileSwitchHistory]: [],
  });

  const registry = new ProviderProfileRegistry({
    globalState,
    secrets: createSecrets(),
  });

  const profile = await registry.initializeWithTemplate(0, '');

  assert.ok(profile);
  assert.equal(profile.credentialMode, 'workspace_secret');
  assert.equal(registry.getActiveProfileId(), profile.id);
  assert.equal(registry.getActiveProfile()?.id, profile.id);
  assert.equal(registry.getSwitchHistory()[0].toProfileId, profile.id);
  assert.equal(registry.getSwitchHistory()[0].reason, 'initial_setup');
});
