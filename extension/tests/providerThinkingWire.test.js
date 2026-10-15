const test = require('node:test');
const assert = require('node:assert/strict');
const {
  classifyProviderThinkingSupport,
  describeProviderThinking,
  providerThinkingMayEmit,
  providerThinkingProbeObserved,
  updateProviderThinking,
  thinkingProtocolSupportsWire,
} = require('../dist/shared/src/providerThinking.js');

const CAPABLE = { supported: true };

test('openai_responses emits flat reasoning_effort for all levels', () => {
  for (const effort of ['low', 'medium', 'high']) {
    const out = updateProviderThinking(
      { protocol: 'openai_responses', model: 'o3', ...CAPABLE },
      {},
      { mode: 'enabled', reasoningEffort: effort },
    );
    assert.equal(out.reasoning_effort, effort);
    assert.equal(out.reasoning, undefined);
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

test('gemini emits generationConfig.thinkingConfig', () => {
  const out = updateProviderThinking(
    { protocol: 'gemini_generate_content', model: 'gemini-2.5-pro', ...CAPABLE },
    {},
    { mode: 'enabled', budgetTokens: 4096 },
  );
  assert.deepEqual(out.generationConfig, {
    thinkingConfig: { includeThoughts: true, thinkingBudget: 4096 },
  });
});

test('gemini enabled config round-trips through the descriptor', () => {
  const defaults = updateProviderThinking(
    { protocol: 'gemini_generate_content', model: 'gemini-2.5-pro', ...CAPABLE },
    {},
    { mode: 'enabled', budgetTokens: 4096 },
  );
  const descriptor = describeProviderThinking(
    { protocol: 'gemini_generate_content', model: 'gemini-2.5-pro', ...CAPABLE },
    defaults,
  );
  assert.equal(descriptor.config.mode, 'enabled');
  assert.equal(descriptor.config.budgetTokens, 4096);
});

test('disabled mode persists an explicit marker but preserves unrelated defaults', () => {
  const prior = { reasoning_effort: 'high', temperature: 0.2 };
  const out = updateProviderThinking(
    { protocol: 'openai_responses', model: 'o3', ...CAPABLE },
    prior,
    { mode: 'disabled' },
  );
  assert.equal(out.reasoning_effort, undefined);
  assert.deepEqual(out.thinking, { type: 'disabled' });
  assert.equal(out.temperature, 0.2);
  const descriptor = describeProviderThinking(
    { protocol: 'openai_responses', model: 'o3', ...CAPABLE },
    out,
  );
  assert.equal(descriptor.config.mode, 'disabled');
});

test('gemini disabled mode writes an explicit wire disable and keeps other generation settings', () => {
  const prior = {
    generationConfig: { thinkingConfig: { includeThoughts: true, thinkingBudget: 4096 }, topP: 0.9 },
  };
  const out = updateProviderThinking(
    { protocol: 'gemini_generate_content', model: 'gemini-2.5-pro', ...CAPABLE },
    prior,
    { mode: 'disabled' },
  );
  assert.deepEqual(out.generationConfig.thinkingConfig, { includeThoughts: false });
  assert.equal(out.generationConfig.topP, 0.9);
  assert.deepEqual(out.thinking, { type: 'disabled' });
  const descriptor = describeProviderThinking(
    { protocol: 'gemini_generate_content', model: 'gemini-2.5-pro', ...CAPABLE },
    out,
  );
  assert.equal(descriptor.config.mode, 'disabled');
});

test('unsupported model never emits thinking fields (safe default)', () => {
  const out = updateProviderThinking(
    { protocol: 'openai_responses', model: 'gpt-4o-mini', supported: false },
    {},
    { mode: 'enabled', reasoningEffort: 'high' },
  );
  assert.equal(out.reasoning_effort, undefined);
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

// --- Smart adaptation (P0 model experience) ---------------------------------
// The protocol-default `capabilities.thinking === false` (and a model entry that
// mirrors it) is absence of evidence, not a verdict; only probe evidence rules.

test('protocol-default thinking:false stays an unknown verdict, not unsupported', () => {
  const context = {
    protocol: 'openai_chat_completions_compatible',
    model: 'manual-model',
    profileCapabilities: { thinking: false },
    modelCapabilities: { thinking: false },
  };
  // Catalog defaults mark every model thinking:false — absence of evidence.
  // The verdict stays unknown, and unknown models carry an explicit choice.
  assert.equal(classifyProviderThinkingSupport(context), 'unknown');
  assert.equal(providerThinkingMayEmit(context), true);
});

test('probe evidence classifies supported and unsupported verdicts', () => {
  const verified = {
    protocol: 'openai_chat_completions_compatible',
    model: 'manual-model',
    capabilityEvidence: [{ name: 'thinking', declared: false, observed: true, state: 'verified' }],
  };
  assert.equal(classifyProviderThinkingSupport(verified), 'supported');
  assert.equal(providerThinkingMayEmit(verified), true);

  const rejected = {
    protocol: 'openai_chat_completions_compatible',
    model: 'manual-model',
    capabilityEvidence: [{ name: 'thinking', declared: false, observed: false, state: 'unsupported' }],
  };
  assert.equal(classifyProviderThinkingSupport(rejected), 'unsupported');
  assert.equal(providerThinkingMayEmit(rejected), false);
});

test('declared model or profile thinking support is a supported verdict', () => {
  assert.equal(
    classifyProviderThinkingSupport({
      protocol: 'openai_responses',
      model: 'o3',
      modelCapabilities: { thinking: true },
    }),
    'supported',
  );
  assert.equal(
    classifyProviderThinkingSupport({
      protocol: 'anthropic_messages',
      model: 'claude-sonnet-4',
      profileCapabilities: { thinking: true },
    }),
    'supported',
  );
});

test('unknown model shows the control, and probe verdicts still gate to unsupported', () => {
  const unprobed = {
    protocol: 'openai_chat_completions_compatible',
    model: 'manual-model',
  };
  // Absence of evidence is not a verdict: the control renders for unknown
  // models (protocol-level gating only), and an explicit choice may emit —
  // a rejecting gateway is absorbed by the sidecar's negotiated replay.
  assert.equal(providerThinkingProbeObserved(unprobed), false);
  assert.equal(providerThinkingMayEmit(unprobed), true);

  // A probe that assessed thinking but stayed inconclusive ("unverified")
  // stays unknown and may emit as well.
  const inconclusive = {
    ...unprobed,
    capabilityEvidence: [{ name: 'thinking', declared: false, observed: null, state: 'unverified' }],
  };
  assert.equal(providerThinkingProbeObserved(inconclusive), true);
  assert.equal(classifyProviderThinkingSupport(inconclusive), 'unknown');
  assert.equal(providerThinkingMayEmit(inconclusive), true);
});

test('probed-unknown model round-trips an explicit strength choice to the wire', () => {
  const context = {
    protocol: 'openai_chat_completions_compatible',
    model: 'deepseek-reasoner',
    capabilityEvidence: [{ name: 'thinking', declared: false, observed: null, state: 'unverified' }],
  };
  const defaults = updateProviderThinking(
    context,
    { temperature: 0.2 },
    { mode: 'enabled', reasoningEffort: 'high' },
  );
  assert.equal(defaults.reasoning_effort, 'high');
  assert.equal(defaults.temperature, 0.2);
  const descriptor = describeProviderThinking(context, defaults);
  assert.equal(descriptor.config.mode, 'enabled');
  assert.equal(descriptor.config.reasoningEffort, 'high');
});

test('unprobed unknown model carries an explicit choice; auto stays silent', () => {
  const context = {
    protocol: 'openai_chat_completions_compatible',
    model: 'manual-model',
  };
  // Explicit learner intent emits even without probe evidence: the sidecar's
  // negotiated replay handles a gateway that rejects the field.
  const explicit = updateProviderThinking(
    context,
    {},
    { mode: 'enabled', reasoningEffort: 'high' },
  );
  assert.equal(explicit.reasoning_effort, 'high');

  // "auto" (and a disabled choice on a non-MiniMax wire) still writes no
  // thinking field — the safe default is unchanged.
  const auto = updateProviderThinking(context, {}, { mode: 'auto' });
  assert.equal(auto.reasoning_effort, undefined);
  assert.equal(auto.thinking, undefined);
});

test('probe-unsupported model refuses the choice even after a probed verdict', () => {
  const context = {
    protocol: 'openai_chat_completions_compatible',
    model: 'manual-model',
    capabilityEvidence: [{ name: 'thinking', declared: false, observed: false, state: 'unsupported' }],
  };
  const defaults = updateProviderThinking(
    context,
    {},
    { mode: 'enabled', reasoningEffort: 'high' },
  );
  assert.equal(defaults.reasoning_effort, undefined);
});
