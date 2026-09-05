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

test('provider image input is ready when vision is verified even if tools are off', () => {
  const {
    describeProviderImageInputState,
    providerSupportsImageInput,
  } = require(providerStatusModulePath);

  assert.equal(
    providerSupportsImageInput({
      capabilities: {
        vision: true,
        tools: false,
      },
    }),
    false,
  );

  const summary = describeProviderImageInputState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'kimi',
      baseUrl: 'https://example.com/v1',
      model: 'kimi-k2.6',
      availableModels: ['kimi-k2.6'],
      modelListStatus: 'ready',
      capabilities: {
        vision: true,
        tools: false,
      },
      lastTestResult: {
        ok: true,
        status: 'connected',
        checkedAt: new Date().toISOString(),
        providerName: 'kimi',
        baseUrl: 'https://example.com/v1',
        model: 'kimi-k2.6',
        capabilityEvidence: [
          { name: 'vision', declared: true, observed: true, state: 'verified' },
          { name: 'tools', declared: true, observed: false, state: 'unsupported' },
        ],
      },
    },
    'en-US',
  );

  assert.equal(summary.supported, true);
  assert.equal(summary.status, 'ready');
});

test('provider image input stays blocked when vision is only declared, not live-verified', () => {
  const {
    describeProviderImageInputState,
    providerSupportsImageInput,
  } = require(providerStatusModulePath);

  assert.equal(
    providerSupportsImageInput({
      capabilities: {
        vision: true,
        tools: true,
      },
      lastTestResult: {
        capabilityEvidence: [
          { name: 'vision', declared: true, observed: null, state: 'unverified' },
          { name: 'tools', declared: true, observed: true, state: 'verified' },
        ],
      },
    }),
    false,
  );

  const summary = describeProviderImageInputState(
    {
      configured: true,
      apiKeyConfigured: true,
      name: 'gpt',
      baseUrl: 'https://example.com/v1',
      model: 'gpt-5.4',
      availableModels: ['gpt-5.4'],
      modelListStatus: 'ready',
      capabilities: {
        vision: true,
        tools: true,
      },
      lastTestResult: {
        ok: true,
        status: 'connected',
        checkedAt: new Date().toISOString(),
        providerName: 'gpt',
        baseUrl: 'https://example.com/v1',
        model: 'gpt-5.4',
        capabilityEvidence: [
          { name: 'vision', declared: true, observed: null, state: 'unverified' },
          { name: 'tools', declared: true, observed: true, state: 'verified' },
        ],
      },
    },
    'en-US',
  );

  assert.equal(summary.supported, false);
  assert.equal(summary.status, 'missing_vision');
  assert.match(summary.reason ?? '', /pictures cannot be sent|cannot send pictures/i);
});

test('provider image input is ready for Gemini native inlineData after vision verification', () => {
  const {
    describeProviderImageInputState,
    providerSupportsImageInput,
  } = require(providerStatusModulePath);

  const provider = {
    configured: true,
    apiKeyConfigured: true,
    name: 'gemini',
    baseUrl: 'https://generativelanguage.googleapis.com',
    model: 'gemini-2.5-pro',
    protocol: 'gemini_generate_content',
    availableModels: ['gemini-2.5-pro'],
    modelListStatus: 'ready',
    capabilities: {
      vision: true,
      tools: false,
    },
    lastTestResult: {
      ok: true,
      status: 'connected',
      checkedAt: new Date().toISOString(),
      providerName: 'gemini',
      baseUrl: 'https://generativelanguage.googleapis.com',
      model: 'gemini-2.5-pro',
      capabilityEvidence: [
        { name: 'vision', declared: true, observed: true, state: 'verified' },
        { name: 'tools', declared: true, observed: false, state: 'unsupported' },
      ],
    },
  };

  assert.equal(providerSupportsImageInput(provider), true);
  const summary = describeProviderImageInputState(provider, 'en-US');

  assert.equal(summary.supported, true);
  assert.equal(summary.status, 'ready');
  assert.match(summary.detail ?? '', /image input is ready/i);
});
