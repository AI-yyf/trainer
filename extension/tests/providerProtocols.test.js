'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const sharedProviderProtocolsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'providerProtocols.js',
);

test('provider protocol helpers normalize protocol selection and capability defaults', async () => {
  const {
    SUPPORTED_PROVIDER_PROTOCOLS,
    defaultCapabilitiesForProtocol,
    defaultTaskBindingRequiredCapabilities,
    normalizeProviderProtocol,
    providerProtocolEndpointHint,
    providerProtocolFamily,
  } = require(sharedProviderProtocolsModulePath);

  assert.deepEqual(SUPPORTED_PROVIDER_PROTOCOLS, [
    'openai_responses',
    'openai_chat_completions',
    'anthropic_messages',
    'openai_chat_completions_compatible',
    'gemini_generate_content',
  ]);

  assert.equal(normalizeProviderProtocol('unknown-value'), undefined);
  assert.equal(normalizeProviderProtocol(undefined), undefined);
  assert.equal(providerProtocolFamily('openai_responses'), 'openai');
  assert.equal(providerProtocolFamily('anthropic_messages'), 'anthropic');
  assert.equal(providerProtocolFamily('gemini_generate_content'), 'gemini');
  assert.equal(providerProtocolEndpointHint('openai_responses'), '/v1/responses');
  assert.equal(providerProtocolEndpointHint('anthropic_messages'), '/v1/messages');
  assert.equal(providerProtocolEndpointHint('gemini_generate_content'), 'google.genai.models.generate_content');

  assert.equal(defaultCapabilitiesForProtocol('openai_responses').responses, true);
  assert.equal(defaultCapabilitiesForProtocol('openai_responses').structuredOutput, true);
  assert.equal(defaultCapabilitiesForProtocol('anthropic_messages').jsonSchema, false);
  assert.equal(defaultCapabilitiesForProtocol('anthropic_messages').structuredOutput, false);
  assert.equal(defaultCapabilitiesForProtocol('openai_chat_completions_compatible').chat, true);
  assert.equal(defaultCapabilitiesForProtocol('openai_chat_completions_compatible').structuredOutput, false);
  assert.equal(defaultCapabilitiesForProtocol('openai_chat_completions_compatible').tools, false);
  assert.equal(defaultCapabilitiesForProtocol('openai_chat_completions_compatible').vision, false);
  assert.deepEqual(defaultTaskBindingRequiredCapabilities('openai_responses', 'coach_reply'), [
    'structuredOutput',
    'streaming',
  ]);
  assert.deepEqual(defaultTaskBindingRequiredCapabilities('anthropic_messages', 'coach_reply'), [
    'streaming',
  ]);
  assert.deepEqual(defaultTaskBindingRequiredCapabilities('openai_chat_completions_compatible', 'coach_reply'), [
    'streaming',
  ]);
  assert.deepEqual(defaultTaskBindingRequiredCapabilities('openai_chat_completions_compatible', 'resource_rerank'), [
    'streaming',
  ]);
});

test('scheme-less provider base URLs stay scheme-less for the sidecar to resolve', async () => {
  const { normalizeProviderBaseUrl, looksLikeSchemelessProviderUrl } = await import(
    sharedProviderProtocolsModulePath
  );

  // The transport (sidecar) probes and owns scheme resolution; a blind https
  // guess here silently breaks http-only relays, so hosts stay as typed.
  assert.equal(normalizeProviderBaseUrl('minimax.redfast.top'), 'minimax.redfast.top');
  assert.equal(normalizeProviderBaseUrl('api.deepseek.com/v1'), 'api.deepseek.com/v1');
  assert.equal(normalizeProviderBaseUrl('localhost:1234/v1'), 'localhost:1234/v1');
  assert.equal(normalizeProviderBaseUrl('  minimax.redfast.top  '), 'minimax.redfast.top');

  // Pasted full request endpoints still collapse to the service root.
  assert.equal(
    normalizeProviderBaseUrl('http://minimax.redfast.top/v1/chat/completions'),
    'http://minimax.redfast.top/v1',
  );
  assert.equal(normalizeProviderBaseUrl('https://api.deepseek.com/v1/'), 'https://api.deepseek.com/v1');
  assert.equal(normalizeProviderBaseUrl(''), '');
});

test('looksLikeSchemelessProviderUrl recognizes service hosts pasted without a scheme', async () => {
  const { looksLikeSchemelessProviderUrl } = await import(sharedProviderProtocolsModulePath);

  assert.equal(looksLikeSchemelessProviderUrl('minimax.redfast.top'), true);
  assert.equal(looksLikeSchemelessProviderUrl('api.deepseek.com/v1'), true);
  assert.equal(looksLikeSchemelessProviderUrl('localhost:1234/v1'), true);
  assert.equal(looksLikeSchemelessProviderUrl('127.0.0.1:8099'), true);
  assert.equal(looksLikeSchemelessProviderUrl('ollama:11434'), true);
  assert.equal(looksLikeSchemelessProviderUrl('https://api.deepseek.com/v1'), false);
  assert.equal(looksLikeSchemelessProviderUrl('ftp://example.com'), false);
  assert.equal(looksLikeSchemelessProviderUrl('sk-abc123def456'), false);
  assert.equal(looksLikeSchemelessProviderUrl('not a host'), false);
  assert.equal(looksLikeSchemelessProviderUrl(''), false);
});
