'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const providerRestoreStateModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'providerRestoreState.js',
);

const { buildRestoredProviderConfigView } = require(providerRestoreStateModulePath);

function createBaseProviderConfig() {
  return {
    configured: true,
    name: 'MiMo',
    baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
    model: 'mimo-v2.5',
    apiKeyConfigured: true,
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    availableModels: [],
    resolvedModel: undefined,
    modelListStatus: 'idle',
    modelListDetail: undefined,
  };
}

test('restored provider state keeps cached empty-response failures blocked', () => {
  const restored = buildRestoredProviderConfigView({
    baseProviderConfig: createBaseProviderConfig(),
    cache: {
      providerFingerprint: 'mimo',
      availableModels: ['mimo-v2.5'],
      resolvedModel: 'mimo-v2.5',
      fetchedAt: '2026-06-05T00:00:00.000Z',
      expiresAt: '2026-06-05T12:00:00.000Z',
      source: 'cache',
      lastError: 'Coach reply unusable: empty_response: Provider stream ended without any usable final coaching content.',
      lastErrorCategory: 'empty_response',
      lastStatusCode: 502,
      retryable: false,
    },
    cacheUsable: false,
  });

  assert.equal(restored.modelListStatus, 'error');
  assert.equal(restored.modelErrorCategory, 'empty_response');
  assert.equal(restored.cacheSource, 'cache');
  assert.match(restored.modelListDetail ?? '', /empty_response/i);
  assert.deepEqual(restored.availableModels, []);
});

test('restored provider state keeps last failed reply probe blocked until a new probe succeeds', () => {
  const restored = buildRestoredProviderConfigView({
    baseProviderConfig: createBaseProviderConfig(),
    cacheUsable: false,
    lastTestResult: {
      ok: false,
      status: 'truncated_or_empty',
      detail:
        'Provider reachable, but the final coaching reply was truncated before any usable final content arrived.',
      checkedAt: '2026-06-05T00:00:00.000Z',
      providerName: 'MiMo',
      baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
      model: 'mimo-v2.5',
      errorCategory: 'truncated_or_empty',
      retryable: false,
      statusCode: 502,
    },
  });

  assert.equal(restored.modelListStatus, 'error');
  assert.equal(restored.modelErrorCategory, 'truncated_or_empty');
  assert.match(restored.modelListDetail ?? '', /truncated|usable/i);
});

test('restored provider state does not let cached models override a failed live reply probe', () => {
  const restored = buildRestoredProviderConfigView({
    baseProviderConfig: createBaseProviderConfig(),
    cache: {
      providerFingerprint: 'mimo',
      availableModels: ['mimo-v2.5'],
      resolvedModel: 'mimo-v2.5',
      fetchedAt: '2026-06-05T00:00:00.000Z',
      expiresAt: '2026-06-05T12:00:00.000Z',
      source: 'cache',
    },
    cacheUsable: true,
    lastTestResult: {
      ok: false,
      status: 'empty_response',
      detail: 'Provider reachable, but returned empty content for model mimo-v2.5.',
      checkedAt: '2026-06-05T00:00:00.000Z',
      providerName: 'MiMo',
      baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
      model: 'mimo-v2.5',
      errorCategory: 'empty_response',
      retryable: false,
      statusCode: 502,
    },
  });

  assert.equal(restored.modelListStatus, 'error');
  assert.equal(restored.modelErrorCategory, 'empty_response');
  assert.equal(restored.resolvedModel, undefined);
  assert.deepEqual(restored.availableModels, []);
  assert.match(restored.modelListDetail ?? '', /empty content|final/i);
});

test('restored provider state keeps language-corruption failures blocked until the provider path changes', () => {
  const restored = buildRestoredProviderConfigView({
    baseProviderConfig: createBaseProviderConfig(),
    cacheUsable: true,
    cache: {
      providerFingerprint: 'mimo',
      availableModels: ['mimo-v2.5'],
      resolvedModel: 'mimo-v2.5',
      fetchedAt: '2026-06-05T00:00:00.000Z',
      expiresAt: '2026-06-05T12:00:00.000Z',
      source: 'cache',
    },
    lastTestResult: {
      ok: false,
      status: 'language_corruption',
      detail:
        'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
      checkedAt: '2026-06-05T00:00:00.000Z',
      providerName: 'MiMo',
      baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
      model: 'mimo-v2.5',
      errorCategory: 'language_corruption',
      retryable: false,
      statusCode: 200,
    },
  });

  assert.equal(restored.modelListStatus, 'error');
  assert.equal(restored.modelErrorCategory, 'language_corruption');
  assert.equal(restored.resolvedModel, undefined);
  assert.deepEqual(restored.availableModels, []);
  assert.match(restored.modelListDetail ?? '', /question marks|corrupted chinese input/i);
});

test('restored provider state keeps model-not-found failures blocked until the gateway changes', () => {
  const restored = buildRestoredProviderConfigView({
    baseProviderConfig: createBaseProviderConfig(),
    cacheUsable: false,
    lastTestResult: {
      ok: false,
      status: 'model_not_found',
      detail: 'The gateway is reachable, but no available channel exists for model mimo-v2.5.',
      checkedAt: '2026-06-05T00:00:00.000Z',
      providerName: 'MiMo',
      baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1',
      model: 'mimo-v2.5',
      errorCategory: 'model_not_found',
      retryable: false,
      statusCode: 503,
    },
  });

  assert.equal(restored.modelListStatus, 'error');
  assert.equal(restored.modelErrorCategory, 'model_not_found');
  assert.match(restored.modelListDetail ?? '', /available channel|model/i);
  assert.deepEqual(restored.availableModels, []);
});
