const test = require('node:test');
const assert = require('node:assert/strict');
const {
  describeProviderThinking,
  updateProviderThinking,
  thinkingProtocolSupportsWire,
} = require('../dist/shared/src/providerThinking.js');

const CAPABLE = { supported: true };

test('openai_responses emits reasoning.effort for all levels', () => {
  for (const effort of ['low', 'medium', 'high']) {
    const out = updateProviderThinking(
      { protocol: 'openai_responses', model: 'o3', ...CAPABLE },
      {},
      { mode: 'enabled', reasoningEffort: effort },
    );
    assert.deepEqual(out.reasoning, { effort });
  }
});

test('openai compatible chat emits reasoning_effort', () => {
  const out = updateProviderThinking(
    { protocol: 'openai_chat_completions_compatible', model: 'deepseek-reasoner', ...CAPABLE },
    {},
    { mode: 'enabled', reasoningEffort: 'high' },
  );
  assert.equal(out.reasoning_effort, 'high');
});

test('anthropic emits thinking budget object', () => {
  const out = updateProviderThinking(
    { protocol: 'anthropic_messages', model: 'claude-sonnet-4', ...CAPABLE },
    {},
    { mode: 'enabled', budgetTokens: 8000 },
  );
  assert.deepEqual(out.thinking, { type: 'enabled', budget_tokens: 8000 });
});

test('gemini emits thinkingConfig', () => {
  const out = updateProviderThinking(
    { protocol: 'gemini_generate_content', model: 'gemini-2.5-pro', ...CAPABLE },
    {},
    { mode: 'enabled', budgetTokens: 4096 },
  );
  assert.deepEqual(out.thinkingConfig, { includeThoughts: true, thinkingBudget: 4096 });
});

test('disabled mode strips thinking fields but preserves unrelated defaults', () => {
  const prior = { reasoning: { effort: 'high' }, temperature: 0.2 };
  const out = updateProviderThinking(
    { protocol: 'openai_responses', model: 'o3', ...CAPABLE },
    prior,
    { mode: 'disabled' },
  );
  assert.equal(out.reasoning, undefined);
  assert.equal(out.temperature, 0.2);
});

test('unsupported model never emits thinking fields (safe default)', () => {
  const out = updateProviderThinking(
    { protocol: 'openai_responses', model: 'gpt-4o-mini', supported: false },
    {},
    { mode: 'enabled', reasoningEffort: 'high' },
  );
  assert.equal(out.reasoning, undefined);
});

test('descriptor exposes effort options only for reasoning-effort protocols', () => {
  const openai = describeProviderThinking(
    { protocol: 'openai_responses', model: 'o3', ...CAPABLE },
    { reasoning: { effort: 'medium' } },
  );
  assert.deepEqual(openai.effortOptions, ['low', 'medium', 'high']);
  const anthropic = describeProviderThinking(
    { protocol: 'anthropic_messages', model: 'claude-sonnet-4', ...CAPABLE },
    { thinking: { type: 'enabled', budget_tokens: 8000 } },
  );
  assert.equal(anthropic.kind, 'thinking_budget');
  assert.equal(anthropic.effortOptions, undefined);
});

test('wire support covers openai/anthropic/gemini families', () => {
  for (const p of ['openai_responses', 'openai_chat_completions', 'openai_chat_completions_compatible', 'anthropic_messages', 'gemini_generate_content']) {
    assert.equal(thinkingProtocolSupportsWire(p), true, p);
  }
});
