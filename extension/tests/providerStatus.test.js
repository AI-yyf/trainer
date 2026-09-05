'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const providerStatusModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'providerStatus.js',
);

test('describeProviderDiagnosticVerdict surfaces a blocked protocol summary', () => {
  const { describeProviderDiagnosticVerdict } = require(providerStatusModulePath);

  const verdict = describeProviderDiagnosticVerdict(
    {
      protocolDiagnostic: { supported: false },
      taskBindingDiagnostics: [{ supported: true }],
      modelDiagnostics: [{ supported: true }],
      modelListStatus: 'ready',
    },
    'en-US',
  );

  assert.equal(verdict.tone, 'fail');
  assert.equal(verdict.status, 'Protocol blocked');
  assert.match(verdict.detail, /Protocol blocked/);
  assert.match(verdict.detail, /1 task bindings?/i);
  assert.match(verdict.detail, /1 model diagnostics?/i);
});

test('describeProviderProtocolSummary explains family and endpoint', () => {
  const { describeProviderProtocolSummary } = require(providerStatusModulePath);

  const summary = describeProviderProtocolSummary(
    {
      protocol: 'openai_responses',
      protocolDiagnostic: {
        protocol: 'openai_responses',
        protocolFamily: 'openai',
        endpointHint: '/v1/responses',
        transport: 'direct',
        supported: true,
        notes: ['Responses mode uses typed input parts.'],
      },
    },
    'en-US',
  );

  assert.equal(summary.tone, 'pass');
  assert.equal(summary.status, 'OpenAI Responses');
  assert.match(summary.detail, /openai family/i);
  assert.match(summary.detail, /direct/i);
  assert.match(summary.detail, /\/v1\/responses/i);
  assert.match(summary.detail, /typed input parts/i);
});

test('describeProviderProfileSummary surfaces current profile and history', () => {
  const { describeProviderProfileSummary } = require(providerStatusModulePath);

  const summary = describeProviderProfileSummary(
    {
      profileId: 'active-fast',
      profileLabel: 'Active Fast',
      profileMode: 'direct',
      profileCount: 3,
      profileHistory: [
        {
          entryId: 'entry-1',
          fromProfileId: 'legacy',
          toProfileId: 'active-fast',
          reason: 'initial_setup',
          timestamp: '2026-06-12T00:00:00.000Z',
        },
      ],
    },
    'en-US',
  );

  assert.equal(summary.tone, 'pass');
  assert.equal(summary.status, 'Active Fast');
  assert.match(summary.detail, /Profile ID: active-fast/);
  assert.match(summary.detail, /Mode: direct/);
  assert.match(summary.detail, /Profiles: 3/);
  assert.match(summary.detail, /History: 1/);
  assert.match(summary.detail, /Latest switch: legacy -> active-fast/);
});

test('describeProviderConnectionSummary combines profile protocol and verdict', () => {
  const { describeProviderConnectionSummary } = require(providerStatusModulePath);

  const summary = describeProviderConnectionSummary(
    {
      providerName: 'OpenAI',
      profileSummary: {
        status: 'Active Fast',
        tone: 'pass',
        detail: 'Profile ID: active-fast',
      },
      protocolSummary: {
        status: 'OpenAI Responses',
        tone: 'pass',
        detail: 'openai family',
      },
      modelTestSummary: 'Model test: passed',
      diagnosticVerdict: {
        status: 'Passed',
        tone: 'pass',
        detail: 'Protocol checked',
      },
      configured: true,
      apiKeyConfigured: true,
      apiKeySavedLabel: 'Saved',
      apiKeyMissingLabel: 'Missing',
    },
    'Not configured',
  );

  assert.match(summary, /OpenAI/);
  assert.match(summary, /Active Fast/);
  assert.match(summary, /OpenAI Responses/);
  assert.match(summary, /Model test: passed/);
  assert.match(summary, /Passed/);
  assert.match(summary, /Saved/);
});

test('describeProviderSetupSummary combines draft provider fields', () => {
  const { describeProviderSetupSummary } = require(providerStatusModulePath);

  const summary = describeProviderSetupSummary(
    {
      providerName: 'OpenAI',
      draftName: 'OpenAI Draft',
      selectedProtocolLabel: 'Responses',
      credentialModeLabel: 'UI proxy',
      model: 'gpt-4.1-mini',
      providerSaved: true,
      apiKeyConfigured: false,
      apiKeyMissingLabel: 'Missing',
    },
    'Not configured',
  );

  assert.match(summary, /OpenAI/);
  assert.match(summary, /Responses/);
  assert.match(summary, /UI proxy/);
  assert.match(summary, /gpt-4.1-mini/);
  assert.match(summary, /Missing/);
});

test('describeProviderCapabilityCapsule compresses provider v2 status into one line', () => {
  const {
    describeProviderCapabilityCapsule,
    describeProviderDiagnosticVerdict,
    describeProviderProfileSummary,
    describeProviderProtocolSummary,
  } = require(providerStatusModulePath);

  const profileSummary = describeProviderProfileSummary(
    {
      profileId: 'active-fast',
      profileLabel: 'Active Fast',
      profileMode: 'direct',
      profileCount: 3,
      profileHistory: [
        {
          fromProfileId: 'legacy',
          toProfileId: 'active-fast',
        },
      ],
    },
    'en-US',
  );
  const protocolSummary = describeProviderProtocolSummary(
    {
      protocol: 'anthropic_messages',
      protocolDiagnostic: {
        protocol: 'anthropic_messages',
        protocolFamily: 'anthropic',
        endpointHint: '/v1/messages',
        transport: 'direct',
        supported: true,
      },
    },
    'en-US',
  );
  const diagnosticVerdict = describeProviderDiagnosticVerdict(
    {
      protocolDiagnostic: { supported: true },
      taskBindingDiagnostics: [{ supported: true }],
      modelDiagnostics: [{ supported: true }],
      modelTest: { ok: true },
      modelListStatus: 'ready',
    },
    'en-US',
  );

  const summary = describeProviderCapabilityCapsule(
    {
      providerName: 'OpenAI',
      profileSummary,
      protocolSummary,
      diagnosticsVerdict: diagnosticVerdict,
      profileCount: 3,
      templateCount: 2,
      taskBindingCount: 4,
      lastTestSummary: 'Last test: passed',
      capabilityState: 'Ready',
    },
    'Not configured',
  );

  assert.match(summary, /OpenAI/);
  assert.match(summary, /Active Fast/);
  assert.match(summary, /Anthropic Messages/);
  assert.match(summary, /Passed/);
  assert.match(summary, /Profiles: 3/);
  assert.match(summary, /Templates: 2/);
  assert.match(summary, /Task bindings: 4/);
  assert.match(summary, /Last test: passed/);
  assert.match(summary, /Ready/);
});

test('describeProviderDiagnosticVerdict marks blocked task binding and model counts', () => {
  const { describeProviderDiagnosticVerdict } = require(providerStatusModulePath);

  const verdict = describeProviderDiagnosticVerdict(
    {
      protocolDiagnostic: { supported: true },
      taskBindingDiagnostics: [{ supported: true }, { supported: false }],
      modelDiagnostics: [{ supported: false }, { supported: true }, { supported: true }],
      modelListStatus: 'ready',
    },
    'en-US',
  );

  assert.equal(verdict.tone, 'fail');
  assert.equal(verdict.status, 'Task binding blocked');
  assert.match(verdict.detail, /2 task bindings? \(1 blocked\)/i);
  assert.match(verdict.detail, /3 model diagnostics? \(1 blocked\)/i);
});

test('describeProviderDiagnosticVerdict surfaces a passed summary', () => {
  const { describeProviderDiagnosticVerdict } = require(providerStatusModulePath);

  const verdict = describeProviderDiagnosticVerdict(
    {
      protocolDiagnostic: { supported: true },
      taskBindingDiagnostics: [{ supported: true }],
      modelDiagnostics: [{ supported: true }],
      modelTest: { ok: true },
      modelListStatus: 'ready',
    },
    'en-US',
  );

  assert.equal(verdict.tone, 'pass');
  assert.equal(verdict.status, 'Passed');
  assert.match(verdict.detail, /Protocol checked/);
  assert.match(verdict.detail, /Model list ready/);
});

test('providerErrorHint localizes model availability failures for non-English surfaces', () => {
  const { providerErrorHint } = require(providerStatusModulePath);

  const hint = providerErrorHint(
    {
      modelErrorCategory: 'model_not_found',
      modelListDetail: 'The endpoint is reachable, but this gateway does not currently have an available channel for the model.',
    },
    'es-ES',
  );

  assert.equal(
    hint,
    'El endpoint responde, pero este gateway no tiene ahora mismo un canal disponible para ese modelo.',
  );
});

test('providerErrorHint uses plain zh-CN copy for malformed responses', () => {
  const { providerErrorHint } = require(providerStatusModulePath);

  const hint = providerErrorHint(
    {
      modelErrorCategory: 'malformed_response',
      modelListDetail: 'ignored fallback',
    },
    'zh-CN',
  );

  assert.equal(hint, '收到的回复暂时无法使用。稍后再试，或换一个模型。');
  assert.doesNotMatch(hint ?? '', /OpenAI|protocol|协议/);
});

test('describeProviderSendState keeps zh-CN recovery hints clear and actionable', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: [],
      modelListStatus: 'error',
      modelErrorCategory: 'network',
    },
    'zh-CN',
  );

  assert.equal(state.blocked, true);
  assert.match(state.reason ?? '', /连不上模型/);
  assert.match(state.reason ?? '', /检查连接/);
  assert.doesNotMatch(state.reason ?? '', /provider|base URL/);
});

test('describeProviderSendState keeps raw technical failure details out of Chinese recovery copy', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: [],
      modelListStatus: 'error',
      modelListDetail: 'HTTP 502 gateway diagnostic: base URL refused the provider request.',
    },
    'zh-CN',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.reason, '到“设置”检查连接后再试。');
  assert.doesNotMatch(state.reason ?? '', /HTTP|gateway|provider|base URL|diagnostic/i);
});

test('describeProviderSendState does not treat empty New API URL and model as configured', () => {
  const { describeProviderSendState, providerTransportIsConfigured } = require(providerStatusModulePath);

  assert.equal(
    providerTransportIsConfigured({ name: 'New API', baseUrl: '', model: '' }),
    false,
  );
  assert.equal(
    providerTransportIsConfigured({
      name: 'New API',
      baseUrl: 'http://127.0.0.1:3000/v1',
      model: 'kimi-k3',
    }),
    true,
  );

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'New API',
      baseUrl: '',
      model: '',
      availableModels: [],
      modelListStatus: 'idle',
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'missing_provider');
});

test('describeProviderSendState distinguishes saved profiles from an active provider', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: false,
      apiKeyConfigured: false,
      model: '',
      profileCount: 3,
      providerProfiles: [{ id: 'minimax-core' }, { id: 'openai-mini' }],
      availableModels: [],
      modelListStatus: 'idle',
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'missing_provider');
  assert.match(state.reason ?? '', /no saved connection is selected/i);
  assert.match(state.reason ?? '', /settings/i);
});

test('describeProviderSendState keeps an unlisted, untested configured model visibly unverified', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: [],
      modelListStatus: 'idle',
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
  assert.match(state.reason ?? '', /has not been confirmed yet/i);
});

test('describeProviderSendState keeps a discovered but untested model visibly unverified', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
  assert.match(state.reason ?? '', /has not been confirmed yet/i);
});

test('describeProviderSendState blocks coaching when the last connectivity test is missing', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'kimi-k3',
      availableModels: ['kimi-k3'],
      modelListStatus: 'ready',
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
  assert.match(state.reason ?? '', /has not been confirmed yet/i);
});

test('describeProviderSendState accepts a current, targeted provider test when model discovery is unavailable', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);
  const now = Date.parse('2026-07-13T10:00:00.000Z');

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      availableModels: [],
      modelListStatus: 'idle',
      lastTestResult: {
        ok: true,
        status: 'passed',
        checkedAt: '2026-07-13T09:45:00.000Z',
        providerName: 'MiniMax',
        baseUrl: 'https://api.minimaxi.com/v1',
        model: 'MiniMax-M3',
        protocol: 'openai_chat_completions_compatible',
        responseLanguage: 'en-US',
      },
    },
    'en-US',
    now,
  );

  assert.equal(state.blocked, false);
  assert.equal(state.status, 'ready');
});

test('describeProviderSendState keeps a tested current model usable when model listing fails', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);
  const now = Date.parse('2026-07-13T10:00:00.000Z');

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      availableModels: [],
      modelListStatus: 'error',
      modelErrorCategory: 'model_listing_unavailable',
      lastTestResult: {
        ok: true,
        status: 'passed',
        checkedAt: '2026-07-13T09:45:00.000Z',
        providerName: 'MiniMax',
        baseUrl: 'https://api.minimaxi.com/v1',
        model: 'MiniMax-M3',
        protocol: 'openai_chat_completions_compatible',
        responseLanguage: 'en-US',
      },
    },
    'en-US',
    now,
  );

  assert.equal(state.blocked, false);
  assert.equal(state.status, 'degraded_error');
  assert.match(state.warning ?? '', /current model passed its connection test/i);
  assert.match(state.warning ?? '', /model list is unavailable/i);
});

test('describeProviderSendState does not treat a legacy successful test as ready', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      lastTestResult: {
        ok: true,
        status: 'passed',
      },
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
  assert.match(state.reason ?? '', /has not been confirmed yet/i);
});

test('describeProviderTestReadiness expires and invalidates a test for another connection', () => {
  const { describeProviderTestReadiness } = require(providerStatusModulePath);
  const now = Date.parse('2026-07-13T10:00:00.000Z');
  const provider = {
    configured: true,
    apiKeyConfigured: true,
    name: 'MiniMax',
    baseUrl: 'https://api.minimaxi.com/v1',
    model: 'MiniMax-M3',
    protocol: 'openai_chat_completions_compatible',
    availableModels: ['MiniMax-M3'],
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'passed',
      checkedAt: '2026-07-13T09:29:59.999Z',
      providerName: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      responseLanguage: 'en-US',
    },
  };

  const stale = describeProviderTestReadiness(provider, 'en-US', now);
  const mismatched = describeProviderTestReadiness(
    { ...provider, baseUrl: 'https://gateway.example.test/v1' },
    'en-US',
    now,
  );

  assert.equal(stale.freshness, 'stale');
  assert.equal(stale.ready, false);
  assert.equal(mismatched.freshness, 'stale');
  assert.equal(mismatched.targetsCurrentConnection, false);
  assert.equal(mismatched.ready, false);
});

test('describeProviderSendState blocks an expired successful test before cached-model degradation', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);
  const now = Date.parse('2026-07-13T10:00:00.000Z');

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'error',
      modelErrorCategory: 'network',
      lastTestResult: {
        ok: true,
        status: 'passed',
        checkedAt: '2026-07-13T09:29:59.999Z',
        providerName: 'MiniMax',
        baseUrl: 'https://api.minimaxi.com/v1',
        model: 'MiniMax-M3',
        protocol: 'openai_chat_completions_compatible',
        responseLanguage: 'en-US',
      },
    },
    'en-US',
    now,
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
});

test('describeProviderSendState requires a current zh-CN probe before Chinese coaching is ready', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);
  const now = Date.parse('2026-07-13T10:00:00.000Z');
  const provider = {
    configured: true,
    apiKeyConfigured: true,
    name: 'MiniMax',
    baseUrl: 'https://api.minimaxi.com/v1',
    model: 'MiniMax-M3',
    protocol: 'openai_chat_completions_compatible',
    availableModels: ['MiniMax-M3'],
    modelListStatus: 'ready',
    lastTestResult: {
      ok: true,
      status: 'passed',
      checkedAt: '2026-07-13T09:45:00.000Z',
      providerName: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      responseLanguage: 'en-US',
    },
  };

  const englishState = describeProviderSendState(provider, 'en-US', now);
  const chineseState = describeProviderSendState(provider, 'zh-CN', now);
  const verifiedChineseState = describeProviderSendState(
    {
      ...provider,
      lastTestResult: { ...provider.lastTestResult, responseLanguage: 'zh-CN' },
    },
    'zh-CN',
    now,
  );

  assert.equal(englishState.status, 'ready');
  assert.equal(chineseState.blocked, true);
  assert.equal(chineseState.status, 'blocked_error');
  assert.equal(verifiedChineseState.status, 'ready');
});

test('describeProviderSendState blocks coaching when the latest provider test failed authentication', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      lastTestResult: {
        ok: false,
        status: 'authentication_failed',
        errorCategory: 'authentication_failed',
        detail: 'Token status unavailable.',
        retryable: false,
      },
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
  assert.match(state.reason ?? '', /connection cannot be used|key and access/i);
});

test('describeProviderSendState blocks a reachable provider that returns only hidden reasoning', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'thinking-model',
      availableModels: ['thinking-model'],
      modelListStatus: 'error',
      modelErrorCategory: 'empty_response',
      modelListDetail: '<think>provider diagnostic containing a secret</think>',
      lastTestResult: {
        ok: false,
        status: 'reasoning_leak',
        errorCategory: 'reasoning_leak',
        detail: '<think>provider diagnostic containing a secret</think>',
        retryable: false,
      },
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
  assert.match(state.reason ?? '', /no usable reply/i);
  assert.match(state.reason ?? '', /choose another model/i);
  assert.doesNotMatch(state.reason ?? '', /think|secret|diagnostic/i);
});

test('describeProviderSendState blocks a reasoning leak even when the model list is ready', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'thinking-model',
      availableModels: ['thinking-model'],
      modelListStatus: 'ready',
      lastTestResult: {
        ok: false,
        status: 'reasoning_leak',
        errorCategory: 'reasoning_leak',
        detail: '<think>hidden provider diagnostic</think>',
        retryable: false,
      },
    },
    'en-US',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
  assert.match(state.reason ?? '', /no usable reply/i);
  assert.doesNotMatch(state.reason ?? '', /think|diagnostic/i);
});

test('describeProviderSendState keeps English coaching available when the latest zh-CN integrity probe failed', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      lastTestResult: {
        ok: false,
        status: 'language_corruption',
        errorCategory: 'language_corruption',
        detail:
          'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
        retryable: false,
        responseLanguage: 'zh-CN',
      },
    },
    'en-US',
  );

  assert.equal(state.blocked, false);
  assert.equal(state.status, 'degraded_error');
  assert.match(state.warning ?? '', /english can still work/i);
  assert.match(state.warning ?? '', /switch connections/i);
});

test('describeProviderSendState still blocks zh-CN coaching when the latest zh-CN integrity probe failed', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      lastTestResult: {
        ok: false,
        status: 'language_corruption',
        errorCategory: 'language_corruption',
        detail:
          'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
        retryable: false,
        responseLanguage: 'zh-CN',
      },
    },
    'zh-CN',
  );

  assert.equal(state.blocked, true);
  assert.equal(state.status, 'blocked_error');
  assert.ok((state.reason ?? '').length > 0);
});

test('describeProviderSendState keeps coaching available when zh-CN integrity is not fully verified yet', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      lastTestResult: {
        ok: false,
        status: 'language_probe_inconclusive',
        errorCategory: 'language_probe_inconclusive',
        detail:
          'Language integrity probe was inconclusive. The provider replied, but it did not preserve the mixed CJK/ASCII probe text exactly enough for Trainer to trust it.',
        retryable: false,
        responseLanguage: 'zh-CN',
      },
    },
    'en-US',
  );

  assert.equal(state.blocked, false);
  assert.equal(state.status, 'degraded_error');
  assert.match(state.warning ?? '', /chinese messages are not fully confirmed|test again/i);
});

test('describeProviderSendState keeps zh-CN coaching in warning mode when integrity is inconclusive', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      lastTestResult: {
        ok: false,
        status: 'language_probe_inconclusive',
        errorCategory: 'language_probe_inconclusive',
        detail:
          'Language integrity probe was inconclusive. The provider replied, but it did not preserve the mixed CJK/ASCII probe text exactly enough for Trainer to trust it.',
        retryable: false,
        responseLanguage: 'zh-CN',
      },
    },
    'zh-CN',
  );

  assert.equal(state.blocked, false);
  assert.equal(state.status, 'degraded_error');
  assert.ok((state.warning ?? '').length > 0);
});

test('describeProviderSendState blocks current connectivity failures after a fresh provider test', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);

  const now = Date.parse('2026-07-13T10:00:00.000Z');
  const provider = {
    configured: true,
    apiKeyConfigured: true,
    name: 'MiniMax',
    baseUrl: 'https://api.minimaxi.com/v1',
    model: 'MiniMax-M3',
    protocol: 'openai_chat_completions_compatible',
    availableModels: ['MiniMax-M3'],
    modelListStatus: 'ready',
  };

  for (const failure of [
    {
      status: 'network_error',
      errorCategory: 'network_error',
      detail: 'Connection reset by peer.',
      expected: /cannot reach the model/i,
    },
    {
      status: 'timeout',
      errorCategory: 'timeout',
      detail: 'The service took too long to reply.',
      expected: /took too long to reply/i,
    },
  ]) {
    const state = describeProviderSendState(
      {
        ...provider,
        lastTestResult: {
          ok: false,
          status: failure.status,
          errorCategory: failure.errorCategory,
          detail: failure.detail,
          retryable: true,
          checkedAt: '2026-07-13T09:45:00.000Z',
          providerName: 'MiniMax',
          baseUrl: 'https://api.minimaxi.com/v1',
          model: 'MiniMax-M3',
          protocol: 'openai_chat_completions_compatible',
        },
      },
      'en-US',
      now,
    );

    assert.equal(state.blocked, true);
    assert.equal(state.status, 'blocked_error');
    assert.match(state.reason ?? '', failure.expected);
  }
});

test('describeProviderSendState keeps a stale connectivity failure degraded until a fresh current test confirms it', () => {
  const { describeProviderSendState } = require(providerStatusModulePath);
  const now = Date.parse('2026-07-13T10:00:00.000Z');

  const state = describeProviderSendState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      lastTestResult: {
        ok: false,
        status: 'network_error',
        errorCategory: 'network_error',
        detail: 'Connection reset by peer.',
        retryable: true,
        checkedAt: '2026-07-13T09:29:59.999Z',
        providerName: 'MiniMax',
        baseUrl: 'https://api.minimaxi.com/v1',
        model: 'MiniMax-M3',
        protocol: 'openai_chat_completions_compatible',
      },
    },
    'en-US',
    now,
  );

  assert.equal(state.blocked, false);
  assert.equal(state.status, 'degraded_error');
  assert.match(state.warning ?? '', /latest check did not finish/i);
  assert.match(state.warning ?? '', /cannot reach the model/i);
});

test('describeProviderImageInputState returns localized image guidance', () => {
  const { describeProviderImageInputState } = require(providerStatusModulePath);
  const now = Date.parse('2026-07-13T10:00:00.000Z');

  const untested = describeProviderImageInputState(
    {
      configured: true,
      apiKeyConfigured: true,
      model: 'MiniMax-M3',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      capabilities: { vision: false, tools: true },
    },
    'ja-JP',
    now,
  );
  assert.equal(untested.status, 'setup_required');

  const state = describeProviderImageInputState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      model: 'MiniMax-M3',
      protocol: 'openai_chat_completions_compatible',
      availableModels: ['MiniMax-M3'],
      modelListStatus: 'ready',
      capabilities: { vision: false, tools: true },
      lastTestResult: {
        ok: true,
        status: 'passed',
        checkedAt: '2026-07-13T09:45:00.000Z',
        providerName: 'MiniMax',
        baseUrl: 'https://api.minimaxi.com/v1',
        model: 'MiniMax-M3',
        protocol: 'openai_chat_completions_compatible',
        responseLanguage: 'ja-JP',
      },
    },
    'ja-JP',
    now,
  );

  assert.equal(state.status, 'missing_vision');
  assert.match(state.reason, /視覚|vision/);
  assert.match(state.detail, /画像|vision/);
});

test('describeProviderCapabilityMatrix compresses aliases bindings and model coverage', () => {
  const { describeProviderCapabilityMatrix } = require(providerStatusModulePath);

  const summary = describeProviderCapabilityMatrix(
    {
      modelAliases: {
        'coach-fast': 'gpt-5-mini',
        'coach-deep': 'gpt-5.4',
      },
      taskBindings: {
        coach_reply: {
          alias: 'coach-fast',
          fallbackAliases: ['coach-deep'],
          requiredCapabilities: ['streaming', 'structuredOutput'],
        },
        coach_critique: {
          alias: 'coach-deep',
        },
      },
      modelCapabilities: {
        'gpt-5-mini': {
          chat: true,
          responses: true,
          streaming: true,
          tools: false,
          vision: false,
          embeddings: false,
          jsonSchema: false,
        },
      },
      capabilityFlags: {
        chat: true,
        responses: true,
        streaming: true,
        tools: true,
        vision: false,
        embeddings: false,
        jsonSchema: true,
      },
    },
    'en-US',
  );

  assert.equal(summary.aliasSummary, 'coach-fast->gpt-5-mini | coach-deep->gpt-5.4');
  assert.match(summary.taskBindingSummary, /coach_reply->alias coach-fast \| required streaming\+structuredOutput \| fallback coach-deep/);
  assert.equal(summary.modelCapabilitySummary, 'gpt-5-mini[Capabilities: chat | responses | streaming]');
  assert.equal(summary.capabilitySummary, 'Capabilities: chat | responses | streaming | tools | json schema');
});

test('describeProviderCapabilityMatrixGroups returns grouped matrix entries', () => {
  const { describeProviderCapabilityMatrixGroups } = require(providerStatusModulePath);

  const summary = describeProviderCapabilityMatrixGroups(
    {
      modelAliases: {
        'coach-fast': 'gpt-5-mini',
        'coach-deep': 'gpt-5.4',
      },
      taskBindings: {
        coach_reply: {
          alias: 'coach-fast',
          fallbackAliases: ['coach-deep'],
          requiredCapabilities: ['streaming', 'structuredOutput'],
        },
        coach_critique: {
          alias: 'coach-deep',
        },
      },
      modelCapabilities: {
        'gpt-5-mini': {
          chat: true,
          responses: true,
          streaming: true,
          tools: false,
          vision: false,
          embeddings: false,
          jsonSchema: false,
        },
      },
      capabilityFlags: {
        chat: true,
        responses: true,
        streaming: true,
        tools: true,
        vision: false,
        embeddings: false,
        jsonSchema: true,
      },
    },
    'en-US',
  );

  assert.deepEqual(summary.aliases, [
    { label: 'coach-fast', detail: 'gpt-5-mini' },
    { label: 'coach-deep', detail: 'gpt-5.4' },
  ]);
  assert.deepEqual(summary.taskBindings[0], {
    label: 'coach_reply',
    detail: 'alias coach-fast | required streaming+structuredOutput | fallback coach-deep',
  });
  assert.equal(summary.modelCapabilities[0].label, 'gpt-5-mini');
  assert.match(summary.modelCapabilities[0].detail, /Capabilities: chat/);
  assert.deepEqual(summary.capabilityFlags, ['chat', 'responses', 'streaming', 'tools', 'json schema']);
});

test('provider setup summaries use plain language across every supported surface language', () => {
  const {
    describeProviderCapabilityMatrix,
    describeProviderCapabilityMatrixGroups,
    describeProviderDiagnosticVerdict,
    describeProviderProfileSummary,
    describeProviderProtocolSummary,
  } = require(providerStatusModulePath);

  const cases = [
    {
      language: 'zh-CN',
      ready: '已就绪',
      diagnostic: '连接已检查',
      protocol: 'OpenAI 响应接口',
      protocolDetail: 'OpenAI 兼容连接',
      profile: '已保存连接: 2',
      task: '教练回复',
      capability: '可用功能: 对话 | 实时输出',
    },
    {
      language: 'en-US',
      ready: 'Passed',
      diagnostic: 'Protocol checked',
      protocol: 'OpenAI Responses',
      protocolDetail: 'openai family',
      profile: 'Profiles: 2',
      task: 'coach_reply',
      capability: 'Capabilities: chat | streaming',
    },
    {
      language: 'es-ES',
      ready: 'Listo',
      diagnostic: 'Conexión comprobada',
      protocol: 'Respuestas de OpenAI',
      protocolDetail: 'Conexión compatible con OpenAI',
      profile: 'Conexiones guardadas: 2',
      task: 'respuesta del coach',
      capability: 'Funciones disponibles: chat | respuesta en directo',
    },
    {
      language: 'fr-FR',
      ready: 'Prêt',
      diagnostic: 'Connexion vérifiée',
      protocol: 'Réponses OpenAI',
      protocolDetail: 'Connexion compatible OpenAI',
      profile: 'Connexions enregistrées: 2',
      task: 'réponse du coach',
      capability: 'Fonctions disponibles: conversation | réponse en direct',
    },
    {
      language: 'de-DE',
      ready: 'Bereit',
      diagnostic: 'Verbindung geprüft',
      protocol: 'OpenAI-Antworten',
      protocolDetail: 'OpenAI-kompatible Verbindung',
      profile: 'Gespeicherte Verbindungen: 2',
      task: 'Coach-Antwort',
      capability: 'Verfügbare Funktionen: Chat | Live-Antwort',
    },
    {
      language: 'ja-JP',
      ready: '準備完了',
      diagnostic: '接続を確認済み',
      protocol: 'OpenAI 応答API',
      protocolDetail: 'OpenAI 互換接続',
      profile: '保存済みの接続: 2',
      task: 'コーチの回答',
      capability: '利用できる機能: 会話 | ストリーミング',
    },
    {
      language: 'ko-KR',
      ready: '준비됨',
      diagnostic: '연결 확인됨',
      protocol: 'OpenAI 응답 API',
      protocolDetail: 'OpenAI 호환 연결',
      profile: '저장된 연결: 2',
      task: '코치 답변',
      capability: '사용 가능한 기능: 대화 | 실시간 응답',
    },
    {
      language: 'pt-BR',
      ready: 'Pronto',
      diagnostic: 'Conexão verificada',
      protocol: 'Respostas OpenAI',
      protocolDetail: 'Conexão compatível com OpenAI',
      profile: 'Conexões salvas: 2',
      task: 'resposta do coach',
      capability: 'Recursos disponíveis: chat | resposta ao vivo',
    },
  ];

  for (const expected of cases) {
    const diagnostic = describeProviderDiagnosticVerdict(
      {
        protocolDiagnostic: { supported: true },
        taskBindingDiagnostics: [{ supported: true }],
        modelDiagnostics: [{ supported: true }],
        modelTest: { ok: true },
        modelListStatus: 'ready',
      },
      expected.language,
    );
    const protocol = describeProviderProtocolSummary(
      {
        protocol: 'openai_responses',
        protocolDiagnostic: {
          protocol: 'openai_responses',
          protocolFamily: 'openai',
          transport: 'direct',
          endpointHint: '/v1/responses',
          notes: ['Responses mode uses typed input parts.'],
          supported: true,
        },
      },
      expected.language,
    );
    const profile = describeProviderProfileSummary(
      {
        profileId: 'active-fast',
        profileLabel: 'Active Fast',
        profileMode: 'direct',
        profileCount: 2,
        profileHistory: [
          {
            fromProfileId: 'legacy',
            toProfileId: 'active-fast',
          },
        ],
      },
      expected.language,
    );
    const matrix = describeProviderCapabilityMatrix(
      {
        taskBindings: {
          coach_reply: {
            alias: 'coach-fast',
            requiredCapabilities: ['streaming', 'structuredOutput'],
          },
        },
        modelCapabilities: {
          'gpt-5-mini': {
            chat: true,
            streaming: true,
          },
        },
        capabilityFlags: {
          chat: true,
          streaming: true,
        },
      },
      expected.language,
    );
    const groups = describeProviderCapabilityMatrixGroups(
      {
        taskBindings: {
          coach_reply: {
            alias: 'coach-fast',
          },
        },
      },
      expected.language,
    );

    assert.equal(diagnostic.status, expected.ready);
    assert.match(diagnostic.detail, new RegExp(expected.diagnostic));
    assert.equal(protocol.status, expected.protocol);
    assert.match(protocol.detail, new RegExp(expected.protocolDetail));
    assert.match(profile.detail, new RegExp(expected.profile));
    assert.equal(groups.taskBindings[0].label, expected.task);
    assert.match(matrix.capabilitySummary, new RegExp(expected.capability));

    if (expected.language !== 'en-US') {
      assert.doesNotMatch(
        diagnostic.detail,
        /Protocol checked|task binding|model diagnostic|Model list ready/,
      );
      assert.doesNotMatch(protocol.detail, /\/v1\/responses|typed input parts/);
      assert.doesNotMatch(matrix.taskBindingSummary, /coach_reply|structuredOutput/);
    }
  }
});

test('describeProviderProfileSummary does not mark an empty connection as ready', () => {
  const { describeProviderProfileSummary } = require(providerStatusModulePath);

  const summary = describeProviderProfileSummary({}, 'zh-CN');

  assert.equal(summary.tone, 'warn');
  assert.equal(summary.status, '未命名连接');
  assert.match(summary.detail, /已保存连接: 0/);
});
