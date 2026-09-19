'use strict';

// Ported from the webview-side spec so these assertions actually execute under
// node --test (the webview package has no test runner).

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const providerThinkingModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'providerThinking.js',
);

const {
  describeProviderThinking,
  normalizeProviderThinking,
  updateProviderThinking,
} = require(providerThinkingModulePath);

const base = { protocol: 'openai_responses', model: 'gpt-5', supported: true };

test('does not treat a known model catalog entry as thinking evidence', () => {
  const context = { protocol: 'openai_responses', model: 'listed-model', knownModels: ['listed-model'] };
  assert.equal(describeProviderThinking(context, { reasoningEffort: 'high' }), undefined);
  assert.deepEqual(normalizeProviderThinking({ reasoningEffort: 'high' }, context).requestDefaults, {});
  assert.deepEqual(updateProviderThinking(context, {}, { mode: 'enabled', reasoningEffort: 'high' }), {});
});

test('describes only explicit or live-confirmed native controls', () => {
  assert.equal(describeProviderThinking(base, { reasoningEffort: 'high' })?.kind, 'reasoning_effort');
  assert.equal(
    describeProviderThinking({ protocol: 'openai_chat_completions_compatible', model: 'unknown' }, {}),
    undefined,
  );
  assert.equal(
    describeProviderThinking(
      { protocol: 'openai_responses', model: 'listed-model', knownModels: ['listed-model'], modelCapability: true },
      { reasoningEffort: 'high' },
    )?.kind,
    'reasoning_effort',
  );
  assert.equal(
    describeProviderThinking(
      { protocol: 'openai_responses', model: 'live-model', liveEvidence: true },
      { reasoningEffort: 'high' },
    )?.kind,
    'reasoning_effort',
  );
});

test('does not treat a successful chat probe as thinking evidence', () => {
  const context = { protocol: 'openai_chat_completions_compatible', model: 'gateway-model' };
  assert.equal(describeProviderThinking(context, { reasoningEffort: 'high' }), undefined);
  assert.deepEqual(updateProviderThinking(context, {}, { mode: 'enabled', reasoningEffort: 'high' }), {});
});

test('accepts only an observed thinking capability as live evidence', () => {
  const context = {
    protocol: 'openai_chat_completions_compatible',
    model: 'reasoning-model',
    liveEvidence: true,
  };
  assert.equal(describeProviderThinking(context, { reasoningEffort: 'high' })?.kind, 'reasoning_effort');
});

test('round trips effort and budget fields', () => {
  assert.deepEqual(
    updateProviderThinking(base, {}, { mode: 'enabled', reasoningEffort: 'high' }),
    { reasoning_effort: 'high' },
  );
  assert.deepEqual(
    updateProviderThinking(
      { protocol: 'anthropic_messages', model: 'claude-4', supported: true },
      {},
      { mode: 'enabled', budgetTokens: 4096 },
    ),
    { thinking: { type: 'enabled', budget_tokens: 4096 } },
  );
});

test('keeps MiniMax thinking disabled until live evidence', () => {
  const result = normalizeProviderThinking({}, { providerName: 'MiniMax', model: 'MiniMax-M3' });
  assert.deepEqual(result.requestDefaults, { extra_body: { thinking: { type: 'disabled' } } });
  assert.equal(result.reason, 'disabled');
});

test('emits MiniMax extra_body.thinking enabled only with live evidence', () => {
  const result = normalizeProviderThinking(
    { thinking: { mode: 'enabled' } },
    { providerName: 'MiniMax', model: 'MiniMax-M2.7', liveEvidence: true },
  );
  assert.deepEqual(result.requestDefaults, { extra_body: { thinking: { type: 'enabled' } } });
  assert.equal(result.reason, 'emitted');
  assert.equal(result.requestDefaults.reasoning_effort, undefined);
});
