'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modulePath = path.resolve(__dirname, '..', 'dist', 'shared', 'src', 'providerThinking.js');

test('normalizeProviderThinking emits protocol-specific fields only for known models', () => {
  const { normalizeProviderThinking } = require(modulePath);
  const cases = [
    ['openai_responses', { reasoning: { effort: 'high' } }],
    ['anthropic_messages', { thinking: { type: 'enabled', budget_tokens: 2048 } }],
    ['gemini_generate_content', { thinkingConfig: { includeThoughts: true, thinkingBudget: 2048 } }],
  ];

  for (const [protocol, expected] of cases) {
    const result = normalizeProviderThinking(
      { thinking: { mode: 'enabled', budget_tokens: 2048 }, reasoningEffort: 'high', keep: true },
      { protocol, model: 'known-model', supported: true },
    );
    assert.deepEqual(result.requestDefaults, { ...expected, keep: true });
    assert.equal(result.emitted, true);
  }
});

test('normalizeProviderThinking migrates legacy fields and omits unknown-model thinking', () => {
  const { normalizeProviderThinking } = require(modulePath);
  const result = normalizeProviderThinking(
    { reasoningEffort: 'medium', thinkingBudget: 1024, keep: 'yes' },
    { protocol: 'openai_responses', model: 'vendor-new-model' },
  );
  assert.deepEqual(result.config, { mode: 'enabled', budgetTokens: 1024, reasoningEffort: 'medium' });
  assert.deepEqual(result.requestDefaults, { keep: 'yes' });
  assert.equal(result.reason, 'unknown_model');
  assert.equal(result.migrated, true);
});

test('normalizeProviderThinking preserves MiniMax disabled wire contract', () => {
  const { normalizeProviderThinking } = require(modulePath);
  const result = normalizeProviderThinking(
    { thinking: { mode: 'enabled' }, extra_body: { option: 'keep' } },
    { protocol: 'openai_chat_completions_compatible', providerName: 'MiniMax', model: 'MiniMax-M3' },
  );
  assert.deepEqual(result.requestDefaults, {
    extra_body: { option: 'keep', thinking: { type: 'disabled' } },
  });
  assert.equal(result.reason, 'unknown_model');
});

test('normalizeProviderThinking does not mutate the input defaults', () => {
  const { normalizeProviderThinking } = require(modulePath);
  const input = { reasoningEffort: 'low', nested: { keep: true } };
  normalizeProviderThinking(input, { protocol: 'openai_responses', model: 'known', supported: true });
  assert.deepEqual(input, { reasoningEffort: 'low', nested: { keep: true } });
});
