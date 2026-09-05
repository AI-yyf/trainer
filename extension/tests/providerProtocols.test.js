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
