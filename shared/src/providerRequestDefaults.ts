import type { ProviderProtocol } from './models';
import { normalizeProviderThinking } from './providerThinking';

export interface ProviderRequestDefaultsIdentity {
  name?: string;
  baseUrl?: string;
  model?: string;
  protocol?: ProviderProtocol | string;
  knownModels?: readonly string[];
  thinkingSupported?: boolean;
}

const MINIMAX_PROVIDER_REQUEST_DEFAULTS: Record<string, unknown> = {
  extra_body: {
    thinking: {
      type: "disabled",
    },
  },
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function cloneRequestDefaults(value: Record<string, unknown>): Record<string, unknown> {
  const cloned: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value)) {
    const record = asRecord(entry);
    cloned[key] = record ? cloneRequestDefaults(record) : entry;
  }
  return cloned;
}

export function isMiniMaxLikeProvider(identity: ProviderRequestDefaultsIdentity): boolean {
  return /minimax/i.test(`${identity.name ?? ""} ${identity.baseUrl ?? ""} ${identity.model ?? ""}`);
}

export function mergeProviderRequestDefaults(
  base: Record<string, unknown>,
  override: Record<string, unknown>,
): Record<string, unknown> {
  const merged = cloneRequestDefaults(base);
  for (const [key, value] of Object.entries(override)) {
    const baseRecord = asRecord(merged[key]);
    const overrideRecord = asRecord(value);
    if (baseRecord && overrideRecord) {
      merged[key] = mergeProviderRequestDefaults(baseRecord, overrideRecord);
      continue;
    }
    merged[key] = overrideRecord ? cloneRequestDefaults(overrideRecord) : value;
  }
  return merged;
}

export function normalizeProviderRequestDefaults(
  identity: ProviderRequestDefaultsIdentity,
  requestDefaults: unknown,
): Record<string, unknown> {
  const normalized = asRecord(requestDefaults) ?? {};
  const thinking = normalizeProviderThinking(normalized, {
    protocol: identity.protocol,
    model: identity.model,
    providerName: identity.name,
    baseUrl: identity.baseUrl,
    knownModels: identity.knownModels,
    supported: identity.thinkingSupported,
  });
  if (!isMiniMaxLikeProvider(identity) && !identity.protocol) {
    return cloneRequestDefaults(normalized);
  }
  if (!isMiniMaxLikeProvider(identity)) {
    return thinking.requestDefaults;
  }

  const merged = mergeProviderRequestDefaults(MINIMAX_PROVIDER_REQUEST_DEFAULTS, thinking.requestDefaults);
  const extraBody = asRecord(merged.extra_body);
  const thinkingType = asRecord(extraBody?.thinking)?.type;
  merged.extra_body = {
    ...(extraBody ? cloneRequestDefaults(extraBody) : {}),
    thinking: { type: thinkingType === "enabled" ? "enabled" : "disabled" },
  };
  return merged;
}
