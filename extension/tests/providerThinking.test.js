'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modulePath = path.resolve(__dirname, '..', 'dist', 'shared', 'src', 'providerThinking.js');

test('normalizeProviderThinking emits protocol-specific fields only for known models', () => {
  const { normalizeProviderThinking } = require(modulePath);
  const cases = [
    ['openai_responses', { reasoning_effort: 'high' }],
    ['anthropic_messages', { thinking: { type: 'enabled', budget_tokens: 2048 } }],
    ['gemini_generate_content', { generationConfig: { thinkingConfig: { includeThoughts: true, thinkingBudget: 2048 } } }],
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

test('normalizeProviderThinkingConfig preserves explicit disabled/auto modes with retained effort', () => {
  const { normalizeProviderThinkingConfig } = require(modulePath);
  // The composer/settings chips spread the current config when switching mode,
  // so the chosen effort rides along on "off" and "auto" — the mode itself
  // must survive instead of being re-derived as "enabled" from that effort.
  assert.deepEqual(
    normalizeProviderThinkingConfig(
      { mode: 'disabled', reasoningEffort: 'high' },
      'openai_chat_completions_compatible',
    ),
    { mode: 'disabled', reasoningEffort: 'high' },
  );
  assert.deepEqual(
    normalizeProviderThinkingConfig(
      { mode: 'auto', reasoningEffort: 'high' },
      'openai_chat_completions_compatible',
    ),
    { mode: 'auto', reasoningEffort: 'high' },
  );
  assert.deepEqual(
    normalizeProviderThinkingConfig(
      { mode: 'disabled', budgetTokens: 4096 },
      'anthropic_messages',
    ),
    { mode: 'disabled', budgetTokens: 4096 },
  );
  assert.deepEqual(
    normalizeProviderThinkingConfig(
      { mode: 'auto', budgetTokens: 4096 },
      'gemini_generate_content',
    ),
    { mode: 'auto', budgetTokens: 4096 },
  );
});

test('normalizeProviderThinkingConfig keeps wire-shape parsing and rejects stray-key flat shapes', () => {
  const { normalizeProviderThinkingConfig } = require(modulePath);
  // Wire markers in request defaults still parse as enabled intent.
  assert.deepEqual(
    normalizeProviderThinkingConfig({ reasoning_effort: 'high' }, 'openai_responses'),
    { mode: 'enabled', reasoningEffort: 'high' },
  );
  assert.deepEqual(
    normalizeProviderThinkingConfig(
      { thinking: { type: 'disabled' } },
      'anthropic_messages',
    ),
    { mode: 'disabled' },
  );
  // A stray "mode" key alongside unrelated params is not the persisted shape.
  assert.equal(
    normalizeProviderThinkingConfig({ mode: 'enabled', temperature: 0.5 }, 'openai_responses'),
    undefined,
  );
});
