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
  const parsed = readConfig(input);
  if (!parsed.config) return undefined;
  const normalized = { ...parsed.config };
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
  /** Compatibility shape for callers carrying a capability object. */
  modelCapabilities?: { thinking?: boolean };
  profileCapabilities?: { thinking?: boolean };
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

function thinkingSupported(context: ProviderThinkingNormalizationContext): boolean {
  return context.liveEvidence === true ||
    context.modelCapability === true ||
    context.profileCapability === true ||
    context.modelCapabilities?.thinking === true ||
    context.profileCapabilities?.thinking === true ||
    context.supported === true;
}

function readConfig(input: Record<string, unknown>): { config?: ProviderThinkingConfig; migrated: boolean; invalid: boolean } {
  const old = record(input.thinking) ?? record(record(input.extra_body)?.thinking);
  const wireReasoning = record(input.reasoning);
  const effort = input.reasoningEffort ?? input.reasoning_effort ?? wireReasoning?.effort;
  const budget = positiveBudget(
    old?.budgetTokens ?? old?.budget_tokens ?? input.thinkingBudget ?? input.thinking_budget,
  );
  const rawMode = old?.mode ?? old?.type;
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
    hasOwn(input, 'reasoningEffort') || hasOwn(input, 'reasoning_effort') || Boolean(old);
  if (!mode && !budget && !reasoningEffort) return { migrated: hadLegacy, invalid: hadLegacy, config: undefined };
  return {
    migrated: hadLegacy,
    invalid: false,
    config: { mode: mode ?? (budget || reasoningEffort ? 'enabled' : 'auto'), ...(budget ? { budgetTokens: budget } : {}), ...(reasoningEffort ? { reasoningEffort } : {}) },
  };
}

function removeThinkingFields(target: Record<string, unknown>): void {
  for (const key of ['thinking', 'thinkingBudget', 'thinking_budget', 'reasoningEffort', 'reasoning_effort']) delete target[key];
  const extra = record(target.extra_body);
  if (extra) {
    delete extra.thinking;
    target.extra_body = extra;
  }
  delete target.thinkingConfig;
  delete target.thinking_config;
}

function emitMiniMaxThinking(target: Record<string, unknown>, config: ProviderThinkingConfig): void {
  const extra = record(target.extra_body) ?? {};
  extra.thinking = { type: config.mode === 'enabled' ? 'enabled' : 'disabled' };
  target.extra_body = extra;
}

function emitThinking(target: Record<string, unknown>, protocol: ProviderProtocol, config: ProviderThinkingConfig): boolean {
  if (config.mode === 'disabled') return false;
  const budget = config.budgetTokens;
  if (protocol === 'openai_responses') {
    target.reasoning = { ...(config.reasoningEffort ? { effort: config.reasoningEffort } : {}) };
  } else if (protocol === 'anthropic_messages') {
    const thinking = { type: 'enabled', budget_tokens: typeof budget === 'number' ? budget : undefined };
    if (thinking.budget_tokens === undefined) delete thinking.budget_tokens;
    target.thinking = thinking;
  } else if (protocol === 'gemini_generate_content') {
    target.thinkingConfig = { includeThoughts: true, ...(typeof budget === 'number' ? { thinkingBudget: budget } : {}) };
  } else if (protocol === 'openai_chat_completions' || protocol === 'openai_chat_completions_compatible') {
    if (!config.reasoningEffort) return false;
    target.reasoning_effort = config.reasoningEffort;
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
    const enable = requested.mode === 'enabled' && thinkingSupported(context);
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
  if (!thinkingSupported(context)) return { config: parsed.config, requestDefaults: target, migrated: parsed.migrated, emitted: false, reason: 'unknown_model' };
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
    const enable = config.mode === 'enabled' && thinkingSupported(context);
    emitMiniMaxThinking(next, { ...config, mode: enable ? 'enabled' : 'disabled' });
    return next;
  }
  if (!protocol || config.mode === 'disabled' || config.mode === 'auto' || !thinkingSupported(context)) return next;
  emitThinking(next, protocol, config);
  return next;
}
