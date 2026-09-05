/**
 * Provider Test Types
 *
 * Type definitions for provider live test API.
 * Reference: docs/open-source-fit-and-provider-strategy.md §5.9
 */

import type { CapabilityFlags, ProviderProtocol } from "./models";
import type { ProviderProtocolFamily } from "./providerProtocols";

export type ProviderTestErrorCategory =
  | "missing_api_key"
  | "invalid_api_key"
  | "authentication_failed"
  | "rate_limit"
  | "model_not_supported"
  | "model_not_found"
  | "context_length_exceeded"
  | "language_corruption"
  | "language_probe_inconclusive"
  | "empty_response"
  | "timeout"
  | "network_error"
  | "unknown";

export type ProviderCapabilityVerificationState =
  | "verified"
  | "unsupported"
  | "unverified"
  | "disabled";

export interface ProviderCapabilityEvidence {
  name: string;
  declared: boolean;
  observed: boolean | null;
  state: ProviderCapabilityVerificationState;
}

export interface ProviderCapabilityTruth {
  capabilityEvidence: ProviderCapabilityEvidence[];
  toolsReady: boolean;
  toolProbeStatus: ProviderCapabilityVerificationState;
  streamingReady: boolean;
  streamProbeStatus: ProviderCapabilityVerificationState;
  visionReady: boolean;
  visionProbeStatus: ProviderCapabilityVerificationState;
  thinkingReady: boolean;
  thinkingProbeStatus: ProviderCapabilityVerificationState;
}

export interface ProviderTestResponse {
  /** Whether the test succeeded */
  ok: boolean;
  /** Human-readable test result summary */
  detail: string;
  /** Error category for programmatic handling */
  error_category: ProviderTestErrorCategory | null;
  /** Whether the error is retryable */
  retryable: boolean;
  /** HTTP status code if applicable */
  status_code: number | null;
  /** Diagnostic messages from the test */
  diagnostics: string[];
  /** Whether the provider endpoint is reachable */
  provider_reachable: boolean;
  /** Whether the specified model is supported */
  model_supported: boolean;
  /** Preview of the probe response text */
  probe_reply_preview: string | null;
  /** Protocol used for the test */
  protocol: ProviderProtocol;
  /** Protocol family (openai/anthropic/gemini) */
  protocolFamily: ProviderProtocolFamily;
  /** Resolved model that was used */
  resolvedModel: string | null;
  /** Capabilities of the resolved model */
  modelCapabilities: Record<string, CapabilityFlags>;
  /** Whether task bindings are supported by this model */
  taskBindingSupported: boolean;
  /** Condensed diagnostics summary */
  diagnosticsSummary: string;
  /** Workspace secret configured indicator */
  workspace_secret_configured?: boolean | null;
  /** Capability evidence returned by the live probe. */
  capability_evidence?: ProviderCapabilityEvidence[];
  capabilityEvidence?: ProviderCapabilityEvidence[];
  /** Tools are ready only after a structured tool call was observed. */
  tools_ready?: boolean;
  toolsReady?: boolean;
  tool_probe_status?: ProviderCapabilityVerificationState;
  toolProbeStatus?: ProviderCapabilityVerificationState;
  /** Streaming is ready only after a visible incremental provider chunk was observed. */
  streaming_ready?: boolean;
  streamingReady?: boolean;
  stream_probe_status?: ProviderCapabilityVerificationState;
  streamProbeStatus?: ProviderCapabilityVerificationState;
  vision_ready?: boolean;
  visionReady?: boolean;
  vision_probe_status?: ProviderCapabilityVerificationState;
  visionProbeStatus?: ProviderCapabilityVerificationState;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asCapabilityState(value: unknown): ProviderCapabilityVerificationState | undefined {
  return value === "verified" || value === "unsupported" || value === "unverified" || value === "disabled"
    ? value
    : undefined;
}

function normalizeCapabilityEvidence(value: unknown): ProviderCapabilityEvidence[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((entry) => {
    const record = asRecord(entry);
    const name = typeof record?.name === "string" ? record.name.trim() : "";
    const state = asCapabilityState(record?.state);
    if (!name || !state) {
      return [];
    }

    return [{
      name,
      declared: record?.declared === true,
      observed: typeof record?.observed === "boolean" ? record.observed : null,
      state,
    }];
  });
}

export function normalizeProviderCapabilityTruth(value: unknown): ProviderCapabilityTruth {
  const record = asRecord(value);
  const liveOk = record?.ok === true || record?.success === true;
  const capabilityEvidence = normalizeCapabilityEvidence(
    record?.capability_evidence ?? record?.capabilityEvidence,
  );
  const toolsEvidence = capabilityEvidence.find((entry) => entry.name.toLowerCase() === "tools");
  const streamingEvidence = capabilityEvidence.find((entry) => {
    const name = entry.name.toLowerCase();
    return name === "streaming" || name === "stream";
  });
  const hasCapabilityProbeResult = liveOk ||
    record?.tools_ready !== undefined ||
    record?.toolsReady !== undefined ||
    record?.streaming_ready !== undefined ||
    record?.streamingReady !== undefined ||
    record?.vision_ready !== undefined ||
    record?.visionReady !== undefined;
  const toolsReady =
    hasCapabilityProbeResult &&
    (record?.tools_ready === true || record?.toolsReady === true) &&
    toolsEvidence?.state === "verified" &&
    toolsEvidence.observed === true;
  const streamingReady =
    hasCapabilityProbeResult &&
    (record?.streaming_ready === true || record?.streamingReady === true) &&
    streamingEvidence?.state === "verified" &&
    streamingEvidence.observed === true;
  const visionEvidence = capabilityEvidence.find((entry) => entry.name.toLowerCase() === "vision");
  const visionReady =
    liveOk &&
    (record?.vision_ready === true || record?.visionReady === true) &&
    visionEvidence?.state === "verified" &&
    visionEvidence.observed === true;
  const thinkingEvidence = capabilityEvidence.find((entry) => entry.name.toLowerCase() === "thinking");
  const thinkingReady =
    liveOk &&
    (record?.thinking_ready === true || record?.thinkingReady === true) &&
    thinkingEvidence?.state === "verified" &&
    thinkingEvidence.observed === true;

  return {
    capabilityEvidence,
    toolsReady,
    toolProbeStatus: toolsReady
      ? "verified"
      : toolsEvidence?.state === "unsupported"
        ? "unsupported"
        : toolsEvidence?.state === "disabled"
          ? "disabled"
          : "unverified",
    streamingReady,
    streamProbeStatus: streamingReady
      ? "verified"
      : streamingEvidence?.state === "unsupported"
        ? "unsupported"
        : streamingEvidence?.state === "disabled"
          ? "disabled"
          : "unverified",
    visionReady,
    visionProbeStatus: visionReady
      ? "verified"
      : visionEvidence?.state === "unsupported"
        ? "unsupported"
        : visionEvidence?.state === "disabled"
          ? "disabled"
          : "unverified",
    thinkingReady,
    thinkingProbeStatus: thinkingReady
      ? "verified"
      : thinkingEvidence?.state === "unsupported"
        ? "unsupported"
        : thinkingEvidence?.state === "disabled"
          ? "disabled"
          : "unverified",
  };
}

export interface ProviderTestRequest {
  /** Profile ID to test */
  profileId?: string;
  /** Optional API key override (for testing without stored credentials) */
  apiKey?: string;
  /** Workspace ID for credential resolution */
  workspaceId?: string;
  /** Test timeout in milliseconds */
  timeoutMs?: number;
  /** Test model override */
  testModel?: string;
}

export interface ProviderTestResult {
  /** Profile ID that was tested */
  profileId: string;
  /** Test result details */
  testResult: ProviderTestResponse;
  /** Profile diagnostics */
  diagnostics: ProviderDiagnosticsSummary;
}

export interface ProviderDiagnosticsSummary {
  profile_id: string;
  protocol: ProviderProtocol;
  protocol_family: ProviderProtocolFamily;
  base_url: string;
  supported: boolean;
  notes: string[];
  model_capabilities: Record<string, CapabilityFlags>;
  task_binding_diagnostics: ProviderTaskBindingDiagnostic[];
  workspace_secret_configured?: boolean | null;
}

export interface ProviderTaskBindingDiagnostic {
  task_binding_key: string;
  alias: string;
  resolved_model: string;
  fallback_aliases: string[];
  required_capabilities: string[];
  missing_capabilities: string[];
  supported: boolean;
  notes: string[];
}

/**
 * Map error categories to user-friendly messages
 */
export const PROVIDER_TEST_ERROR_MESSAGES: Record<ProviderTestErrorCategory, { en: string; zh: string }> = {
  missing_api_key: {
    en: "No API key provided",
    zh: "未提供 API key",
  },
  invalid_api_key: {
    en: "API key is invalid",
    zh: "API key 无效",
  },
  authentication_failed: {
    en: "Authentication failed",
    zh: "认证失败",
  },
  rate_limit: {
    en: "Rate limit exceeded",
    zh: "超出速率限制",
  },
  model_not_supported: {
    en: "Model not supported",
    zh: "模型不受支持",
  },
  model_not_found: {
    en: "Model not found on this gateway",
    zh: "这个网关上找不到该模型",
  },
  context_length_exceeded: {
    en: "Context length exceeded",
    zh: "上下文长度超出限制",
  },
  language_corruption: {
    en: "Chinese input corrupted",
    zh: "中文输入已损坏",
  },
  empty_response: {
    en: "Empty response from provider",
    zh: "provider 返回空响应",
  },
  language_probe_inconclusive: {
    en: "Chinese integrity not fully verified",
    zh: "\u4e2d\u6587\u5b8c\u6574\u6027\u5c1a\u672a\u5145\u5206\u9a8c\u8bc1",
  },
  timeout: {
    en: "Request timed out",
    zh: "请求超时",
  },
  network_error: {
    en: "Network error",
    zh: "网络错误",
  },
  unknown: {
    en: "Unknown error",
    zh: "未知错误",
  },
};

/**
 * Get error message for a category
 */
export function getTestErrorMessage(
  category: ProviderTestErrorCategory | null,
  language: "en" | "zh" = "en",
): string {
  if (category === null) {
    return language === "zh" ? "测试成功" : "Test succeeded";
  }
  return PROVIDER_TEST_ERROR_MESSAGES[category]?.[language] ?? PROVIDER_TEST_ERROR_MESSAGES[category]?.en ?? "Unknown error";
}

/**
 * Check if a test result indicates a successful test
 */
export function isTestSuccessful(result: ProviderTestResponse): boolean {
  return result.ok === true && result.provider_reachable === true && result.model_supported === true;
}

/**
 * Get retry recommendation based on test result
 */
export function shouldRetryTest(result: ProviderTestResponse): boolean {
  if (!result.ok) {
    return result.retryable === true;
  }
  return false;
}
