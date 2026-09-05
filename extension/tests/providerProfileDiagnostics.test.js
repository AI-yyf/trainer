'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const providerProfileDiagnosticsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'providerProfileDiagnostics.js',
);

test('describeProviderProfileDiagnostics reports a healthy OpenAI profile as ready', () => {
  const { describeProviderProfileDiagnostics } = require(providerProfileDiagnosticsModulePath);

  const summary = describeProviderProfileDiagnostics({
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
    modelAliases: {
      'coach-fast': 'gpt-5-mini',
    },
    availableModels: ['gpt-5-mini'],
    allowedModels: ['gpt-5-mini'],
    deniedModels: [],
    taskBindings: {
      coach_reply: {
        alias: 'coach-fast',
        fallbackAliases: ['coach-deep'],
        requiredCapabilities: ['structuredOutput', 'streaming'],
      },
    },
    requestDefaults: {
      store: false,
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
    modelCapabilities: {
      'gpt-5-mini': {
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
  });

  assert.equal(summary.ok, true);
  assert.equal(summary.errorCount, 0);
  assert.equal(summary.warningCount, 0);
  assert.match(summary.status, /Config ready/i);
});

test('describeProviderProfileDiagnostics flags missing structured output capability', () => {
  const { describeProviderProfileDiagnostics } = require(providerProfileDiagnosticsModulePath);

  const summary = describeProviderProfileDiagnostics({
    id: 'anthropic-default',
    label: 'Anthropic',
    protocol: 'anthropic_messages',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.anthropic.com',
    apiKeyRef: 'anthropic.default',
    model: 'claude-sonnet-4-20250514',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'claude-haiku-4-5-20250514',
    },
    availableModels: ['claude-haiku-4-5-20250514', 'claude-sonnet-4-20250514'],
    allowedModels: ['claude-haiku-4-5-20250514', 'claude-sonnet-4-20250514'],
    deniedModels: [],
    taskBindings: {
      coach_reply: {
        alias: 'coach-fast',
        fallbackAliases: ['coach-deep'],
        requiredCapabilities: ['structuredOutput', 'streaming'],
      },
    },
    requestDefaults: {
      maxTokens: 4096,
      thinkingBudget: 'auto',
    },
    capabilities: {
      chat: true,
      responses: false,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: false,
      streaming: true,
      structuredOutput: false,
    },
    modelCapabilities: {
      'claude-haiku-4-5-20250514': {
        chat: true,
        responses: false,
        vision: true,
        embeddings: false,
        tools: true,
        jsonSchema: false,
        streaming: true,
        structuredOutput: false,
      },
    },
  });

  assert.equal(summary.ok, false);
  assert.ok(summary.errorCount > 0);
  assert.match(summary.status, /attention|修正/i);
  assert.ok(summary.issues.some((issue) => issue.code === 'binding_missing_capabilities'));
  assert.ok(summary.issues.some((issue) => issue.message.includes('structuredOutput')));
});

test('describeProviderProfileDiagnostics uses locale-appropriate detail separators', () => {
  const { describeProviderProfileDiagnostics } = require(providerProfileDiagnosticsModulePath);

  const summary = describeProviderProfileDiagnostics({
    id: 'empty-profile',
    label: 'Empty',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'empty.profile',
    model: '',
    catalogSource: 'manual',
    cacheTtlSeconds: 0,
    modelAliases: {},
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {},
    requestDefaults: {},
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: false,
      structuredOutput: false,
    },
    modelCapabilities: {},
  }, 'en-US');

  assert.equal(summary.ok, false);
  assert.match(summary.detail, / \u00b7 /);
});

test('describeProviderProfileDiagnostics applies model policy case-insensitively with deny precedence', () => {
  const { describeProviderProfileDiagnostics } = require(providerProfileDiagnosticsModulePath);

  const summary = describeProviderProfileDiagnostics({
    id: 'policy-profile',
    label: 'Policy profile',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://example.test/v1',
    apiKeyRef: 'policy.profile',
    model: 'MiniMax-M3',
    catalogSource: 'manual',
    cacheTtlSeconds: 0,
    modelAliases: {},
    availableModels: ['MiniMax-M3'],
    allowedModels: [' minimax-m3 '],
    deniedModels: ['MINIMAX-M3'],
    taskBindings: {},
    requestDefaults: {},
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
      structuredOutput: false,
    },
    modelCapabilities: {},
  });

  assert.ok(summary.issues.some((issue) => issue.code === 'model_denied'));
  assert.equal(summary.issues.some((issue) => issue.code === 'model_not_allowed'), false);
});

test('describeProviderProfileDiagnostics matches catalog models despite case and surrounding whitespace', () => {
  const { describeProviderProfileDiagnostics } = require(providerProfileDiagnosticsModulePath);

  const summary = describeProviderProfileDiagnostics({
    id: 'normalized-catalog-profile',
    label: 'Normalized catalog profile',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://example.test/v1',
    apiKeyRef: 'normalized.catalog.profile',
    model: ' MiniMax-M3 ',
    catalogSource: 'manual',
    cacheTtlSeconds: 0,
    modelAliases: {
      fast: ' minimax-m3 ',
    },
    availableModels: ['minimax-m3'],
    allowedModels: ['MINIMAX-M3'],
    deniedModels: [],
    taskBindings: {
      coach_reply: {
        alias: 'fast',
        fallbackAliases: [],
        requiredCapabilities: [],
      },
    },
    requestDefaults: {},
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
      structuredOutput: false,
    },
    modelCapabilities: {},
  });

  assert.equal(summary.issues.some((issue) => issue.code === 'model_not_listed'), false);
  assert.equal(summary.issues.some((issue) => issue.code === 'binding_model_not_listed'), false);
  assert.equal(summary.issues.some((issue) => issue.code === 'model_not_allowed'), false);
  assert.equal(summary.issues.some((issue) => issue.code === 'binding_model_not_allowed'), false);
});

