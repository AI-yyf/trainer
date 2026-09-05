'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const workbenchDataModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchData.js',
);
const providerStatusModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'providerStatus.js',
);

const {
  createDefaultBootstrapData,
  applyDerivedHostState,
} = require(workbenchDataModulePath);
const { describeProviderSendState } = require(providerStatusModulePath);

function createWorkspace() {
  return {
    trusted: true,
    workspaceFolder: '/workspace/trainer',
    activeFile: '/workspace/trainer/extension/src/core/workbenchData.ts',
    activeLanguageId: 'typescript',
    diagnosticErrors: 0,
    diagnosticWarnings: 0,
    documentVersion: 1,
    recentFiles: [],
    recentEditedFiles: [],
    relatedFiles: [],
  };
}

function createProvider() {
  return {
    name: 'MiMo',
    baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
    apiKeyRef: 'mimo.default',
    model: 'MiMo-V2.5',
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
}

test('default bootstrap explains that provider setup is required before coaching works', () => {
  const bootstrap = createDefaultBootstrapData(createWorkspace());

  assert.equal(bootstrap.connection.state, 'offline');
  assert.equal(bootstrap.providerConfig.configured, false);
  assert.match(bootstrap.coachingState.summary, /连接|connect/i);
  assert.match(bootstrap.coachingState.nextStep, /provider|API key|连接/i);
});

test('applyDerivedHostState preserves unavailable sidecar truth state instead of pretending connected', () => {
  const bootstrap = createDefaultBootstrapData(createWorkspace(), createProvider(), {
    lifecycle: 'unavailable',
    host: '127.0.0.1',
    canStart: false,
    detail: 'No Trainer sidecar binary or server source could be found.',
  });

  const next = applyDerivedHostState(
    bootstrap,
    createProvider(),
    {
      lifecycle: 'unavailable',
      host: '127.0.0.1',
      canStart: false,
      detail: 'No Trainer sidecar binary or server source could be found.',
    },
    createWorkspace(),
    'session-1',
    false,
  );

  assert.equal(next.connection.state, 'offline');
  assert.equal(next.providerConfig.configured, true);
  assert.equal(next.providerConfig.apiKeyConfigured, false);
});

test('provider send state blocks clearly when provider is missing', () => {
  const result = describeProviderSendState(
    {
      configured: false,
      apiKeyConfigured: false,
      model: '',
      availableModels: [],
      modelListStatus: 'idle',
    },
    'en-US',
  );

  assert.equal(result.blocked, true);
  assert.equal(result.status, 'missing_provider');
  assert.match(result.reason ?? '', /model connection is not set up yet/i);
  assert.match(result.reason ?? '', /finish it in settings/i);
});

test('provider send state blocks clearly when api key is missing', () => {
  const result = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: false,
      baseUrl: 'https://gateway.example/v1',
      model: 'MiMo-V2.5',
      availableModels: [],
      modelListStatus: 'idle',
    },
    'en-US',
  );

  assert.equal(result.blocked, true);
  assert.equal(result.status, 'missing_api_key');
  assert.match(result.reason ?? '', /connection is not complete yet/i);
  assert.match(result.reason ?? '', /add the key in settings/i);
});

test('provider send state treats either missing transport field as provider setup', () => {
  for (const provider of [
    { baseUrl: 'https://gateway.example/v1', model: '' },
    { baseUrl: '', model: 'model-only' },
  ]) {
    const result = describeProviderSendState(
      {
        configured: true,
        apiKeyConfigured: true,
        ...provider,
        availableModels: [],
        modelListStatus: 'idle',
      },
      'en-US',
    );

    assert.equal(result.blocked, true);
    assert.equal(result.status, 'missing_provider');
  }
});
