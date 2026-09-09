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
      return 'Gemini GenerateContent (not Google-native by default)';
    default:
      return 'Protocol unverified';
  }
}

/**
 * Match a host-style authority a user typed without a scheme:
 * dotted domains ("api.deepseek.com/v1"), "localhost:1234", IPv4, or a bare
 * single-label hostname with an explicit port ("ollama:11434"). Used by the
 * settings form to recognize service addresses pasted into the wrong field.
 * Scheme resolution itself belongs to the sidecar transport, which probes
 * the host instead of guessing.
 */
const SCHEMELESS_PROVIDER_HOST_PATTERN =
  /^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})(?::\d{1,5})?(?:\/\S*)?$/i;

/**
 * Single-label hostname with an explicit port ("ollama:11434/v1") — a local
 * or forwarded service address.
 */
const SCHEMELESS_LOCAL_HOST_WITH_PORT_PATTERN = /^[a-z0-9][a-z0-9-]*(?::\d{1,5})(?:\/\S*)?$/i;

/** True when the value reads like a service host that is merely missing "http(s)://". */
export function looksLikeSchemelessProviderUrl(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || /\s/.test(trimmed) || /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)) {
    return false;
  }
  if (SCHEMELESS_PROVIDER_HOST_PATTERN.test(trimmed)) {
    return true;
  }
  return SCHEMELESS_LOCAL_HOST_WITH_PORT_PATTERN.test(trimmed);
}

/**
 * Canonicalize a user-entered base URL for the given protocol. Scheme-less
 * hosts are preserved as the user typed them — the sidecar transport resolves
 * the scheme by probing, because a blind https guess silently breaks
 * http-only relays. Paste-full endpoint URLs ("…/v1/chat/completions") collapse
 * to the service root so a draft connection test and the saved config exercise
 * the same base URL — and so the client appending the endpoint suffix does not
 * double it.
 */
export function normalizeProviderBaseUrl(
  baseUrl: string,
  protocol: ProviderProtocol | string | undefined = 'openai_chat_completions_compatible',
): string {
  const trimmed = baseUrl.trim();
  if (!trimmed) {
    return '';
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return trimmed.replace(/\/+$/, '');
    }

    const normalizedProtocol = normalizeProviderProtocol(protocol);
    let pathname = parsed.pathname.replace(/\/+$/, '');
    const loweredPathname = pathname.toLowerCase();
    if (
      normalizedProtocol === 'openai_responses' ||
      normalizedProtocol === 'openai_chat_completions' ||
      normalizedProtocol === 'openai_chat_completions_compatible'
    ) {
      for (const suffix of ['/chat/completions', '/responses']) {
        if (loweredPathname.endsWith(suffix)) {
          pathname = pathname.slice(0, -suffix.length) || '/';
          break;
        }
      }
    } else if (
      normalizedProtocol === 'anthropic_messages' &&
      loweredPathname.endsWith('/messages')
    ) {
      pathname = pathname.slice(0, -'/messages'.length) || '/';
    } else if (
      normalizedProtocol === 'gemini_generate_content' &&
      loweredPathname.endsWith(':generatecontent')
    ) {
      const modelMarker = '/models/';
      const markerIndex = loweredPathname.lastIndexOf(modelMarker);
      if (markerIndex >= 0) {
        pathname = pathname.slice(0, markerIndex) || '/';
      }
    }

    parsed.pathname = pathname || '/';
    parsed.search = '';
    parsed.hash = '';
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return trimmed.replace(/\/+$/, '');
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
