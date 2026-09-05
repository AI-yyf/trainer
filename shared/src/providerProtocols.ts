import type { CapabilityFlags, ProviderProtocol } from './models';

export type ProviderProtocolFamily = 'openai' | 'anthropic' | 'gemini';
export type ProviderTaskBindingKey =
  | 'coach_reply'
  | 'coach_critique'
  | 'resource_rerank'
  | 'plan_summary'
  | 'resource_embedding';

export const SUPPORTED_PROVIDER_PROTOCOLS: readonly ProviderProtocol[] = [
  'openai_responses',
  'openai_chat_completions',
  'anthropic_messages',
  'openai_chat_completions_compatible',
  'gemini_generate_content',
];

export const OPENAI_COMPATIBLE_PROTOCOL: ProviderProtocol = 'openai_chat_completions_compatible';

const SUPPORTED_PROVIDER_PROTOCOL_SET = new Set<string>(SUPPORTED_PROVIDER_PROTOCOLS);

const UNVERIFIED_CAPABILITIES: CapabilityFlags = {
  chat: false,
  responses: false,
  vision: false,
  embeddings: false,
  tools: false,
  jsonSchema: false,
  streaming: false,
  structuredOutput: false,
  thinking: false,
};

export function isSupportedProviderProtocol(
  value: ProviderProtocol | string | undefined,
): value is ProviderProtocol {
  return typeof value === 'string' && SUPPORTED_PROVIDER_PROTOCOL_SET.has(value);
}

export function normalizeProviderProtocol(
  value: ProviderProtocol | string | undefined,
): ProviderProtocol | undefined {
  return isSupportedProviderProtocol(value) ? value : undefined;
}

export function providerProtocolFamily(
  protocol: ProviderProtocol | string | undefined,
): ProviderProtocolFamily | undefined {
  const normalized = normalizeProviderProtocol(protocol);
  if (normalized === 'anthropic_messages') {
    return 'anthropic';
  }
  if (normalized === 'gemini_generate_content') {
    return 'gemini';
  }
  if (normalized === 'openai_responses' || normalized === 'openai_chat_completions' || normalized === 'openai_chat_completions_compatible') {
    return 'openai';
  }
  return undefined;
}

export function providerProtocolEndpointHint(
  protocol: ProviderProtocol | string | undefined,
): string {
  switch (normalizeProviderProtocol(protocol)) {
    case 'openai_responses':
      return '/v1/responses';
    case 'openai_chat_completions':
    case 'openai_chat_completions_compatible':
      return '/v1/chat/completions';
    case 'anthropic_messages':
      return '/v1/messages';
    case 'gemini_generate_content':
      return 'google.genai.models.generate_content';
    default:
      return '';
  }
}

export function providerProtocolCompletionLabel(
  protocol: ProviderProtocol | string | undefined,
): string {
  switch (normalizeProviderProtocol(protocol)) {
    case 'openai_responses':
      return 'OpenAI Responses';
    case 'openai_chat_completions':
      return 'OpenAI Chat Completions';
    case 'openai_chat_completions_compatible':
      return 'OpenAI-compatible chat completions';
    case 'anthropic_messages':
      return 'Anthropic Messages';
    case 'gemini_generate_content':
      return 'Gemini GenerateContent';
    default:
      return 'Protocol unverified';
  }
}

export function defaultCapabilitiesForProtocol(
  protocol: ProviderProtocol | string | undefined,
): CapabilityFlags {
  const normalized = normalizeProviderProtocol(protocol);
  if (normalized === 'openai_responses') {
    return {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: true,
      jsonSchema: true,
      streaming: true,
      structuredOutput: true,
    };
  }
  if (normalized === 'anthropic_messages') {
    return {
      chat: true,
      responses: false,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: false,
      streaming: true,
      structuredOutput: false,
    };
  }
  if (normalized === 'gemini_generate_content') {
    return {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: true,
      jsonSchema: true,
      streaming: true,
      structuredOutput: true,
    };
  }
  if (normalized === 'openai_chat_completions') {
    return {
      chat: true,
      responses: false,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: true,
      streaming: true,
      structuredOutput: true,
    };
  }
  if (normalized === 'openai_chat_completions_compatible') {
    return {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
      structuredOutput: false,
      thinking: false,
    };
  }
  return { ...UNVERIFIED_CAPABILITIES };
}

export function defaultTaskBindingRequiredCapabilities(
  protocol: ProviderProtocol | string | undefined,
  taskBindingKey: ProviderTaskBindingKey,
): string[] {
  const normalized = normalizeProviderProtocol(protocol);
  if (!normalized) {
    return [];
  }
  if (taskBindingKey === 'coach_reply') {
    if (normalized === 'openai_responses' || normalized === 'openai_chat_completions' || normalized === 'gemini_generate_content') {
      return ['structuredOutput', 'streaming'];
    }
    return ['streaming'];
  }
  if (taskBindingKey === 'resource_rerank') {
    return ['streaming'];
  }
  return [];
}
