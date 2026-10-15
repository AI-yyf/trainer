import type { ProviderProtocol } from './models';
import { normalizeProviderProtocol, providerProtocolFamily } from './providerProtocols';

export type ProviderThinkingMode = 'disabled' | 'enabled' | 'auto';
export type ProviderThinkingBudget = number | 'auto';

/** Protocol-neutral thinking intent stored in a profile. */
export interface ProviderThinkingConfig {
  mode: ProviderThinkingMode;
  budgetTokens?: ProviderThinkingBudget;
  reasoningEffort?: 'low' | 'medium' | 'high';
}

/** Normalize the protocol-neutral persisted shape from camelCase/snake_case inputs. */
export function normalizeProviderThinkingConfig(
  value: unknown,
  protocol?: ProviderProtocol | string,
): ProviderThinkingConfig | undefined {
  const input = record(value);
  if (!input) return undefined;
  // The persisted thinkingConfig field is already flat ({mode, budgetTokens?,
  // reasoningEffort?}). When every key is a config key, the explicit mode is
  // authoritative — otherwise readConfig re-derives "enabled" from a retained
  // effort/budget field and silently flips an "off"/"auto" choice back on.
  // Extra keys disqualify the flat shape, so stray request-defaults params
  // can't masquerade as intent; those inputs fall through to readConfig.
  let normalized: ProviderThinkingConfig | undefined;
  const flatMode = input.mode;
  if (
    (flatMode === 'disabled' || flatMode === 'enabled' || flatMode === 'auto')
    && Object.keys(input).every(
      (key) => key === 'mode' || key === 'budgetTokens' || key === 'reasoningEffort',
    )
  ) {
    normalized = { mode: flatMode };
    const budget = positiveBudget(input.budgetTokens);
    if (budget) normalized.budgetTokens = budget;
    const effort = input.reasoningEffort;
    if (effort === 'low' || effort === 'medium' || effort === 'high') {
      normalized.reasoningEffort = effort;
    }
  } else {
    normalized = readConfig(input).config;
  }
  if (!normalized) return undefined;
  normalized = { ...normalized };
  const normalizedProtocol = normalizeProviderProtocol(protocol);
  if (normalizedProtocol === 'anthropic_messages' || normalizedProtocol === 'gemini_generate_content') {
    delete normalized.reasoningEffort;
  } else if (normalizedProtocol === 'openai_responses' || providerProtocolFamily(normalizedProtocol) === 'openai') {
    delete normalized.budgetTokens;
  } else {
    delete normalized.budgetTokens;
    delete normalized.reasoningEffort;
  }
  return normalized;
}

export interface ProviderThinkingEvidenceEntry {
  name?: unknown;
  declared?: unknown;
  observed?: unknown;
  state?: unknown;
}

export interface ProviderThinkingNormalizationContext {
  protocol?: ProviderProtocol | string;
  model?: string;
  providerName?: string;
  baseUrl?: string;
  /** Model catalog entries are not capability evidence and are intentionally ignored. */
  knownModels?: readonly string[];
  /** Explicitly verified model support; absent means conservative behavior. */
  supported?: boolean;
  /** Explicit thinking capability for the selected model. */
  modelCapability?: boolean;
  /** Explicit thinking capability declared by the provider profile. */
  profileCapability?: boolean;
  /** Thinking capability observed by a live provider probe. */
  liveEvidence?: boolean;
  /** Raw capability evidence from the latest connection probe. */
  capabilityEvidence?: readonly ProviderThinkingEvidenceEntry[];
  /** Compatibility shape for callers carrying a capability object. */
  modelCapabilities?: { thinking?: boolean };
  profileCapabilities?: { thinking?: boolean };
}

/**
 * Smart-adaptation verdict for the thinking control (P0 model experience):
 *
 * - `supported` — the model is declared or probe-verified to support thinking.
 *   The control is shown and restores the last choice.
 * - `unsupported` — a live probe explicitly observed that thinking is rejected
 *   (`state=unsupported` / `observed=false`). The control is hidden.
 * - `unknown` — no declaration and no conclusive evidence. The control stays
 *   hidden until a probe has actually assessed thinking.
 *
 * Deliberately NOT `unsupported`: the protocol-default `capabilities.thinking
 * === false` (e.g. the OpenAI-compatible default) and a model-capability entry
 * that merely mirrors it (server routes fill `model_capabilities[model]` from
 * the profile flags, `provider.py:110`). Those are absence of evidence, not a
 * verdict.
 */
export type ProviderThinkingSupport = 'supported' | 'unsupported' | 'unknown';

function thinkingEvidenceEntry(
  context: ProviderThinkingNormalizationContext,
): ProviderThinkingEvidenceEntry | undefined {
  const evidence = context.capabilityEvidence;
  if (!Array.isArray(evidence)) {
    return undefined;
  }
  return evidence.find(
    (entry) =>
      entry &&
      typeof entry === 'object' &&
      String(entry.name ?? '').trim().toLowerCase() === 'thinking',
  );
}

export function classifyProviderThinkingSupport(
  context: ProviderThinkingNormalizationContext,
): ProviderThinkingSupport {
  const entry = thinkingEvidenceEntry(context);
  if (entry) {
    if (entry.state === 'verified' && entry.observed === true) {
      return 'supported';
    }
    if (entry.state === 'unsupported' || entry.observed === false) {
      return 'unsupported';
    }
  }
  if (
    context.liveEvidence === true ||
    context.modelCapability === true ||
    context.profileCapability === true ||
    context.supported === true ||
    context.modelCapabilities?.thinking === true ||
    context.profileCapabilities?.thinking === true
  ) {
    return 'supported';
  }
  if (
    context.modelCapability === false ||
    context.profileCapability === false ||
    context.supported === false
  ) {
    return 'unsupported';
  }
  return 'unknown';
}

/**
 * True when a connection probe has actually assessed thinking for this
 * connection+model (any verdict). "Unknown → 探测过再显示": the control only
 * appears once a probe has run, so a fresh manual model never silently carries
 * invented wire fields.
 */
export function providerThinkingProbeObserved(
  context: ProviderThinkingNormalizationContext,
): boolean {
  return Boolean(thinkingEvidenceEntry(context));
}

/**
 * Whether a thinking config may be written to the wire for this context.
 *
 * An explicitly unsupported model never emits. Supported and unknown models
 * both emit an *explicit* learner choice: the control is user intent, not an
 * inferred default, and a gateway that dislikes the field is absorbed by the
 * sidecar's negotiated replay (server/app/llm/provider/thinking.py classifies
 * the rejection, remembers the working policy, and replays once). Hiding the
 * wire write behind probe evidence only ever produced a control that did
 * nothing — the exact "cannot adjust thinking strength" complaint.
 */
export function providerThinkingMayEmit(
  context: ProviderThinkingNormalizationContext,
): boolean {
  return classifyProviderThinkingSupport(context) !== 'unsupported';
}

export interface ProviderThinkingNormalization {
  config?: ProviderThinkingConfig;
  requestDefaults: Record<string, unknown>;
  migrated: boolean;
  emitted: boolean;
  reason: 'emitted' | 'disabled' | 'unknown_model' | 'unsupported_protocol' | 'invalid';
}

export interface ProviderThinkingDescriptor {
  protocol: ProviderProtocol;
  kind: 'reasoning_effort' | 'thinking_budget' | 'gemini_thinking' | 'minimax_thinking';
  config: ProviderThinkingConfig;
  effortOptions?: readonly ('low' | 'medium' | 'high')[];
  budgetMin?: number;
  budgetMax?: number;
  nativeModelFamily?: 'deepseek' | 'qwen' | 'kimi' | 'glm' | 'mistral';
  advanced: boolean;
  disabled?: boolean;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function clone(value: unknown): unknown {
  const object = record(value);
  if (object) {
    const result: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(object)) result[key] = clone(entry);
    return result;
  }
  return Array.isArray(value) ? value.map(clone) : value;
}

function positiveBudget(value: unknown): ProviderThinkingBudget | undefined {
  if (value === 'auto') return value;
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : undefined;
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function readConfig(input: Record<string, unknown>): { config?: ProviderThinkingConfig; migrated: boolean; invalid: boolean } {
  const old = record(input.thinking) ?? record(record(input.extra_body)?.thinking);
  const generationConfig = record(input.generationConfig) ?? record(input.generation_config);
  const geminiThinking =
    record(generationConfig?.thinkingConfig) ??
    record(generationConfig?.thinking_config) ??
    record(input.thinkingConfig) ??
    record(input.thinking_config);
  const wireReasoning = record(input.reasoning);
  const effort = input.reasoningEffort ?? input.reasoning_effort ?? wireReasoning?.effort;
  const budget = positiveBudget(
    old?.budgetTokens ??
      old?.budget_tokens ??
      input.thinkingBudget ??
      input.thinking_budget ??
      geminiThinking?.thinkingBudget ??
      geminiThinking?.thinking_budget,
  );
  const includeThoughts = geminiThinking?.includeThoughts ?? geminiThinking?.include_thoughts;
  const rawMode =
    old?.mode ??
    old?.type ??
    (includeThoughts === false ? 'disabled' : includeThoughts === true ? 'enabled' : undefined);
  const mode: ProviderThinkingMode | undefined =
    rawMode === 'disabled' || rawMode === 'enabled' || rawMode === 'auto'
      ? rawMode
      : old
        ? old.enabled === false
          ? 'disabled'
          : old.enabled === true
            ? 'enabled'
            : undefined
        : undefined;
  const reasoningEffort = effort === 'low' || effort === 'medium' || effort === 'high' ? effort : undefined;
  const hadLegacy = hasOwn(input, 'thinkingBudget') || hasOwn(input, 'thinking_budget') ||
    hasOwn(input, 'reasoningEffort') || hasOwn(input, 'reasoning_effort') || Boolean(old) ||
    Boolean(geminiThinking);
  if (!mode && !budget && !reasoningEffort) return { migrated: hadLegacy, invalid: hadLegacy, config: undefined };
  return {
    migrated: hadLegacy,
    invalid: false,
    config: { mode: mode ?? (budget || reasoningEffort ? 'enabled' : 'auto'), ...(budget ? { budgetTokens: budget } : {}), ...(reasoningEffort ? { reasoningEffort } : {}) },
  };
}

export function removeThinkingFields(target: Record<string, unknown>): void {
  for (const key of [
    'thinking',
    'thinkingBudget',
    'thinking_budget',
    'reasoning',
    'reasoningEffort',
    'reasoning_effort',
    'thinkingConfig',
    'thinking_config',
  ]) delete target[key];
  // Replace (never mutate) nested containers: callers pass shallow copies, so
  // in-place edits would leak into the source record.
  const extra = record(target.extra_body);
  if (extra) {
    const next = { ...extra };
    delete next.thinking;
    target.extra_body = next;
  }
  // thinkingConfig lives under generationConfig on the Gemini wire path; strip
  // only that key so unrelated generation defaults (tokens, temperature) stay.
  for (const key of ['generationConfig', 'generation_config']) {
    const generation = record(target[key]);
    if (!generation) {
      continue;
    }
    const next = { ...generation };
    delete next.thinkingConfig;
    delete next.thinking_config;
    if (Object.keys(next).length === 0) {
      delete target[key];
    } else {
      target[key] = next;
    }
  }
}

function emitMiniMaxThinking(target: Record<string, unknown>, config: ProviderThinkingConfig): void {
  const extra = record(target.extra_body) ?? {};
  extra.thinking = { type: config.mode === 'enabled' ? 'enabled' : 'disabled' };
  target.extra_body = extra;
}

// Anthropic rejects thinking.type=enabled without budget_tokens, so an explicit
// "on" must always carry a concrete budget.
const ANTHROPIC_DEFAULT_THINKING_BUDGET = 4096;

// `thinking` is filtered out of every request-defaults wire path except
// anthropic, where {type:'disabled'} is the documented explicit-disable — so
// the marker doubles as intent persistence and (on anthropic/gemini) the
// correct wire shape.
export function applyDisabledThinkingMarker(
  target: Record<string, unknown>,
  protocol?: ProviderProtocol | string,
): void {
  target.thinking = { type: 'disabled' };
  if (normalizeProviderProtocol(protocol) === 'gemini_generate_content') {
    const generation = record(target.generationConfig) ?? {};
    generation.thinkingConfig = { includeThoughts: false };
    target.generationConfig = generation;
  }
}

function emitThinking(target: Record<string, unknown>, protocol: ProviderProtocol, config: ProviderThinkingConfig): boolean {
  if (config.mode !== 'enabled') return false;
  const budget = config.budgetTokens;
  if (protocol === 'openai_responses') {
    // The send path reads the flat reasoning_effort alias and maps it onto the
    // wire `reasoning` object — nesting it here would never reach the request.
    target.reasoning_effort = config.reasoningEffort ?? 'medium';
  } else if (protocol === 'anthropic_messages') {
    target.thinking = {
      type: 'enabled',
      budget_tokens: typeof budget === 'number' ? budget : ANTHROPIC_DEFAULT_THINKING_BUDGET,
    };
  } else if (protocol === 'gemini_generate_content') {
    // Gemini consumes thinking config inside generationConfig; a top-level
    // thinkingConfig key is dropped by the send path.
    const generation = record(target.generationConfig) ?? {};
    generation.thinkingConfig = {
      includeThoughts: true,
      ...(typeof budget === 'number' ? { thinkingBudget: budget } : {}),
    };
    target.generationConfig = generation;
  } else if (protocol === 'openai_chat_completions' || protocol === 'openai_chat_completions_compatible') {
    target.reasoning_effort = config.reasoningEffort ?? 'medium';
  } else {
    return false;
  }
  return true;
}

export function normalizeProviderThinking(
  requestDefaults: unknown,
  context: ProviderThinkingNormalizationContext = {},
): ProviderThinkingNormalization {
  const source = record(requestDefaults) ?? {};
  const target = clone(source) as Record<string, unknown>;
  const parsed = readConfig(source);
  removeThinkingFields(target);
  const protocol = normalizeProviderProtocol(context.protocol);
  const minimax = /minimax/i.test(`${context.providerName ?? ''} ${context.baseUrl ?? ''} ${context.model ?? ''}`);
  if (minimax) {
    const requested = parsed.config ?? { mode: 'disabled' as const };
    const enable = requested.mode === 'enabled' && providerThinkingMayEmit(context);
    const config: ProviderThinkingConfig = { ...requested, mode: enable ? 'enabled' : 'disabled' };
    emitMiniMaxThinking(target, config);
    return {
      config,
      requestDefaults: target,
      migrated: parsed.migrated,
      emitted: true,
      reason: enable ? 'emitted' : requested.mode === 'enabled' ? 'unknown_model' : 'disabled',
    };
  }
  if (!protocol) {
    return {
      config: parsed.config,
      requestDefaults: target,
      migrated: parsed.migrated,
      emitted: false,
      reason: 'unsupported_protocol',
    };
  }
  if (parsed.invalid || !parsed.config) return { requestDefaults: target, migrated: parsed.migrated, emitted: false, reason: parsed.invalid ? 'invalid' : 'disabled' };
  if (!providerThinkingMayEmit(context)) return { config: parsed.config, requestDefaults: target, migrated: parsed.migrated, emitted: false, reason: 'unknown_model' };
  // Disabled (and explicit auto) carry no wire fields — report the parsed mode
  // back so descriptors can render the choice instead of falling to 'auto'.
  // An explicit "off" restores its marker so the choice survives normalization.
  if (parsed.config.mode !== 'enabled') {
    if (parsed.config.mode === 'disabled') {
      applyDisabledThinkingMarker(target, protocol);
    }
    return { config: parsed.config, requestDefaults: target, migrated: parsed.migrated, emitted: false, reason: 'disabled' };
  }
  if (emitThinking(target, protocol, parsed.config)) return { config: parsed.config, requestDefaults: target, migrated: parsed.migrated, emitted: true, reason: 'emitted' };
  return { config: parsed.config, requestDefaults: target, migrated: parsed.migrated, emitted: false, reason: 'unsupported_protocol' };
}

export function thinkingProtocolSupportsWire(protocol: ProviderProtocol | string | undefined): boolean {
  const normalized = normalizeProviderProtocol(protocol);
  if (!normalized) return false;
  return ['openai_responses', 'anthropic_messages', 'gemini_generate_content'].includes(normalized)
    || providerProtocolFamily(normalized) === 'openai';
}

export function describeProviderThinking(
  context: ProviderThinkingNormalizationContext,
  requestDefaults: unknown,
): ProviderThinkingDescriptor | undefined {
  const normalized = normalizeProviderThinking(requestDefaults, context);
  const protocol = normalizeProviderProtocol(context.protocol);
  const minimax = /minimax/i.test(`${context.providerName ?? ''} ${context.baseUrl ?? ''} ${context.model ?? ''}`);
  if (minimax) {
    const config = normalized.config ?? { mode: 'disabled' as const };
    return {
      protocol: protocol ?? 'openai_chat_completions_compatible',
      kind: 'minimax_thinking',
      config,
      advanced: true,
      disabled: config.mode !== 'enabled',
    };
  }
  if (!protocol || !normalized.config || normalized.reason === 'unknown_model' || normalized.reason === 'unsupported_protocol') return undefined;
  if (protocol === 'openai_responses') {
    return { protocol, kind: 'reasoning_effort', config: normalized.config, effortOptions: ['low', 'medium', 'high'], advanced: true };
  }
  if (protocol === 'anthropic_messages') {
    return { protocol, kind: 'thinking_budget', config: normalized.config, budgetMin: 1, budgetMax: 200000, advanced: true };
  }
  if (protocol === 'gemini_generate_content') {
    return { protocol, kind: 'gemini_thinking', config: normalized.config, budgetMin: 1, budgetMax: 32768, advanced: true };
  }
  if (protocol === 'openai_chat_completions' || protocol === 'openai_chat_completions_compatible') {
    return { protocol, kind: 'reasoning_effort', config: normalized.config, effortOptions: ['low', 'medium', 'high'], advanced: true };
  }
  return undefined;
}

/**
 * Build a descriptor for a connection with no thinking fields in its wire
 * defaults — e.g. the user never chose a mode, or capability evidence is
 * absent so nothing could be emitted. Returns undefined when the protocol
 * cannot carry thinking at all, so callers can distinguish "no choice yet"
 * from "unsupported transport".
 */
export function synthesizeProviderThinkingDescriptor(
  context: ProviderThinkingNormalizationContext,
  config: ProviderThinkingConfig = { mode: 'auto' },
): ProviderThinkingDescriptor | undefined {
  const protocol = normalizeProviderProtocol(context.protocol);
  const minimax = /minimax/i.test(`${context.providerName ?? ''} ${context.baseUrl ?? ''} ${context.model ?? ''}`);
  if (minimax) {
    return {
      protocol: protocol ?? 'openai_chat_completions_compatible',
      kind: 'minimax_thinking',
      config,
      advanced: true,
      disabled: config.mode !== 'enabled',
    };
  }
  if (!protocol || !thinkingProtocolSupportsWire(protocol)) return undefined;
  if (protocol === 'anthropic_messages') {
    return { protocol, kind: 'thinking_budget', config, budgetMin: 1, budgetMax: 200000, advanced: true };
  }
  if (protocol === 'gemini_generate_content') {
    return { protocol, kind: 'gemini_thinking', config, budgetMin: 1, budgetMax: 32768, advanced: true };
  }
  return { protocol, kind: 'reasoning_effort', config, effortOptions: ['low', 'medium', 'high'], advanced: true };
}

export function updateProviderThinking(
  context: ProviderThinkingNormalizationContext,
  requestDefaults: unknown,
  config: ProviderThinkingConfig,
): Record<string, unknown> {
  const current = record(requestDefaults) ?? {};
  const next = clone(current) as Record<string, unknown>;
  removeThinkingFields(next);
  const protocol = normalizeProviderProtocol(context.protocol);
  const minimax = /minimax/i.test(`${context.providerName ?? ''} ${context.baseUrl ?? ''} ${context.model ?? ''}`);
  if (minimax) {
    const enable = config.mode === 'enabled' && providerThinkingMayEmit(context);
    emitMiniMaxThinking(next, { ...config, mode: enable ? 'enabled' : 'disabled' });
    return next;
  }
  if (!protocol || !providerThinkingMayEmit(context)) return next;
  if (config.mode === 'auto') return next;
  if (config.mode === 'disabled') {
    applyDisabledThinkingMarker(next, protocol);
    return next;
  }
  emitThinking(next, protocol, config);
  return next;
}
