import type {
  ActiveWorkbenchView,
  BootstrapData,
  BrowserUploadResourceInput,
  CapabilityFlags,
  CoachDefaults,
  ComposerLanguage,
  CoachSettingsRequest,
  CoachFocusView,
  CoachTurnSummaryView,
  ConversationArtifactKind,
  ConversationMessage,
  HostMessage,
  ImplementationGuide,
  PrincipleNote,
  ProviderConfigView,
  ProviderLastTestResult,
  ProviderProtocol,
  ProjectAdaptationGuide,
  ProjectIdea,
  PlanRuntimeReviewPoint,
  ResourceRecord,
  ResourceSearchState,
  SandboxPreview,
  SessionMessageRequest,
  StreamCompleteEvent,
  StreamErrorEvent,
  SuggestedAction,
} from "./types";
import {
  createEmptyTrainerStreamingState,
  normalizeTrainerMessageParts,
  normalizeNextStepHint,
} from "../../../../shared/src/protocol";
import {
  defaultCapabilitiesForProtocol,
  normalizeProviderProtocol,
  providerProtocolFamily,
} from "../../../../shared/src/providerProtocols";
import { providerErrorHint } from "../../../../shared/src/providerStatus";
import { normalizeProviderRequestDefaults } from "../../../../shared/src/providerRequestDefaults";
import {
  applyProviderModelCatalog,
  mergeProviderModelTokenLimits,
  normalizeProviderModelTokenLimits,
  resolveProviderModelTokenState,
} from "../../../../shared/src/providerModelTokenLimits";
import { evaluateProviderModelPolicy } from "../../../../shared/src/providerModelPolicy";
import {
  normalizeResourceSearchMode,
  resourceSearchModeRequest,
  type ResourceSearchMode,
} from "../../../../shared/src/resourceSearch";
import { normalizeProviderCapabilityTruth } from "../../../../shared/src/providerTest";
import { isComposerLanguage } from "../../../../shared/src/types";
import { normalizeCoachOrientationRecord } from "../../../../shared/src/coachOrientationGovernance";
import { normalizeTransferSkillStateRecord } from "../../../../shared/src/transferSkillGovernance";
import {
  normalizePlanRuntimeRecovery,
  normalizePlanRuntimeResumeState,
  normalizeProviderCapabilityRecovery,
  recoverStreamingCheckpointAfterRestart,
  selectPlanRuntimeForScope,
  selectProviderCapabilityForScope,
  selectStreamingCheckpointForScope,
} from "../../../../shared/src/workspaceRecoveryGovernance";
import {
  browserPreviewCoachCopy,
  buildGoalAwarePreviewPlanPatch,
  resolveBrowserPreviewGoal,
  runBrowserPreviewAction,
  type BrowserPreviewBootstrap,
  type BrowserPreviewPatch,
} from "./browserPreviewActions";
export { runBrowserPreviewAction };
import { resolveCopy } from "./i18n/copy";
import {
  getInjectedBootstrapState,
  getPersistedState,
  persistBrowserPreviewProviderConfig,
} from "./vscode";

const DEV_SIDECAR_PORT = 34891;
const DEV_SIDECAR_PORT_MAX = 34911;
const DEV_SIDECAR_HEALTH_TIMEOUT_MS = 700;
const DEV_WORKSPACE_ID_PREFIX = "trainer-web-preview";
const DEV_WORKSPACE_NAME = "Trainer Preview";
const MAX_BROWSER_UPLOADS = 100;
const PREVIEW_PROVIDER_SECRETS_STORAGE_KEY = "trainer:webview:preview:provider-secrets";
const PREVIEW_DEFAULT_PROVIDER_NAME = "custom-openai-compatible";
const PREVIEW_WORKSPACE_ID_STORAGE_KEY = "trainer:webview:preview:workspace-id";
const PREVIEW_LIVE_SESSION_ID_STORAGE_KEY = "trainer:webview:preview:live-session-id";
const PREVIEW_PROVIDER_MODEL_CACHE_TTL_MS = 12 * 60 * 60 * 1000;
const PREVIEW_FIXTURE_MODEL_OPTIONS = [
  "preview-chat",
  "preview-reasoning",
  "preview-vision",
] as const;
type BrowserPreviewActiveStream = {
  controller: AbortController;
  reader?: ReadableStreamDefaultReader<Uint8Array>;
  sidecarBaseUrl?: string;
  streamId?: string;
};

const activeBrowserPreviewStreams = new Map<string, BrowserPreviewActiveStream>();
let resolvedDevSidecarPort: number | undefined;
let sidecarProbePromise: Promise<string> | undefined;
let transientPreviewWorkspaceId: string | undefined;

export function registerBrowserPreviewStream(
  messageId: string,
  controller: AbortController,
  remote?: { sidecarBaseUrl: string; streamId: string },
): void {
  activeBrowserPreviewStreams.set(messageId, {
    controller,
    sidecarBaseUrl: remote?.sidecarBaseUrl,
    streamId: remote?.streamId,
  });
}

export function attachBrowserPreviewStreamReader(
  messageId: string,
  reader: ReadableStreamDefaultReader<Uint8Array>,
): void {
  const active = activeBrowserPreviewStreams.get(messageId);
  if (active) {
    active.reader = reader;
  }
}

export function releaseBrowserPreviewStream(messageId: string): void {
  activeBrowserPreviewStreams.delete(messageId);
}

export function cancelBrowserPreviewStream(messageId?: string): boolean {
  const active = messageId
    ? activeBrowserPreviewStreams.get(messageId)
    : Array.from(activeBrowserPreviewStreams.values())[0];
  if (!active) {
    return false;
  }
  if (active.sidecarBaseUrl && active.streamId && typeof fetch === "function") {
    // Abort only stops this browser's reader. Ask the local Sidecar to stop the
    // provider turn as well so a cancelled stream does not keep consuming work.
    void fetch(`${active.sidecarBaseUrl}/stream/cancel`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ stream_id: active.streamId }),
      keepalive: true,
    }).catch(() => undefined);
  }
  active.controller.abort();
  void active.reader?.cancel().catch(() => undefined);
  return true;
}
const INTERNAL_COACH_META_MARKERS = [
  "current coaching focus:",
  "current focus:",
  "current focus to continue:",
  "review rhythm:",
  "memory scope is",
  "preferred teaching asset:",
  "reusable teaching asset:",
  "resume the live thread around",
  "evidence to anchor on:",
  "build on the verified result:",
  "keep the blocker in view:",
  "coach confidence:",
  "this follows the teaching lane from",
  "reuse the saved teaching asset",
  "\u5f53\u524d\u805a\u7126\uff1a",
  "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
  "\u590d\u4e60\u8282\u594f\uff1a",
  "\u8bb0\u5fc6\u8303\u56f4\u662f",
] as const;
const INTERNAL_COACH_META_LABELS = new Set([
  "project implementation",
  "idea implementation guidance",
  "project idea mining",
  "existing project adaptation",
  "project adaptation",
  "principle explanation",
  "review and reflection coaching",
  "plan and review rhythm",
  "next step after review",
  "task execution coaching",
  "next task coaching",
  "general coaching",
]);
type CoachScenario =
  | "general"
  | "onboarding"
  | "idea_implementation"
  | "project_idea"
  | "project_adaptation"
  | "project_sourcing"
  | "principle"
  | "remote_workspace"
  | "debug_loop"
  | "function_guidance"
  | "review"
  | "plan"
  | "task"
  | "next_task";
type WorkspaceTrainingStateView = NonNullable<BootstrapData["workspaceTrainingState"]>;
type TrainingHandoffStateView = NonNullable<WorkspaceTrainingStateView["latestTrainingHandoff"]>;
type TrainingNextHopStateView = NonNullable<WorkspaceTrainingStateView["latestTrainingNextHop"]>;
type TrainingCardCandidateStateView = NonNullable<
  WorkspaceTrainingStateView["trainingCardCandidates"]
>[number];
type ActiveTrainingCardRoutingStateView = NonNullable<
  WorkspaceTrainingStateView["activeTrainingCardRouting"]
>;
type TrainingBlockedCardCandidateStateView = NonNullable<
  NonNullable<ActiveTrainingCardRoutingStateView["blockedCandidates"]>
>[number];
type TrainingEventLedgerEntryStateView = NonNullable<
  WorkspaceTrainingStateView["trainingEventLedger"]
>[number];
type EvidenceQueueStateView = NonNullable<BootstrapData["memory"]["evidenceQueue"]>;
type EvidenceItemStateView = NonNullable<EvidenceQueueStateView["pending"]>[number];
type ReviewArtifactStateView = NonNullable<WorkspaceTrainingStateView["reviewArtifact"]>;
type ScenarioLabStateView = NonNullable<WorkspaceTrainingStateView["scenarioLab"]>;
type TheoryDrillStateView = NonNullable<WorkspaceTrainingStateView["theoryDrill"]>;
type TheoryDrillQuestionStateView = NonNullable<TheoryDrillStateView["questions"]>[number];

function normalizeCoachSurfaceCandidate(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

const COACH_SURFACE_NOISE_MARKERS = [
  "\uFFFD",
  "\u9227",
  "\u5053",
  "\u95B8",
  "\u9420",
  "\u5A11",
  "\u7F02",
  "\u6FDE",
  "\u745C",
  "\u7EF1",
  "\u9852",
  "\u9350",
] as const;

function looksLikeCoachSurfaceNoise(value: string): boolean {
  if (!value) {
    return false;
  }
  if (/[\uE000-\uF8FF]/u.test(value)) {
    return true;
  }
  let markerHits = 0;
  for (const marker of COACH_SURFACE_NOISE_MARKERS) {
    if (value.includes(marker)) {
      markerHits += 1;
      if (markerHits >= 2) {
        return true;
      }
    }
  }
  return false;
}

function normalizeCoachSurfaceText(value: unknown): string | undefined {
  const text = asString(value);
  if (!text) {
    return undefined;
  }
  const paragraphs = text
    .split(/\n\s*\n/g)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  const keptParagraphs: string[] = [];
  for (const paragraph of paragraphs) {
    const keptLines: string[] = [];
    for (const rawLine of paragraph.split(/\n+/g)) {
      const normalizedLine = normalizeCoachSurfaceCandidate(rawLine);
      const line = stripLeadingCoachMetaPrefix(normalizedLine);
      if (!line) {
        continue;
      }
      if (line === normalizedLine && isInternalCoachMeta(line)) {
        continue;
      }
      const keptFragments = line
        .split(/(?<=[.!?\u3002\uff01\uff1f])\s+/g)
        .map((fragment) => stripLeadingCoachMetaPrefix(fragment))
        .filter((fragment) => fragment && !isInternalCoachMeta(fragment));
      if (keptFragments.length === 0) {
        continue;
      }
      keptLines.push(keptFragments.join(" ").replace(/\s+([,.;:!?])/g, "$1").trim());
    }
    if (keptLines.length > 0) {
      keptParagraphs.push(keptLines.join("\n"));
    }
  }
  const cleaned = keptParagraphs.join("\n\n").trim();
  if (!cleaned) {
    return undefined;
  }
  const normalized = stripLeadingCoachMetaPrefix(cleaned) || undefined;
  if (!normalized || looksLikeCoachSurfaceNoise(normalized)) {
    return undefined;
  }
  return normalized;
}

function isInternalCoachMeta(value: string): boolean {
  const normalized = normalizeCoachSurfaceCandidate(value);
  if (!normalized) {
    return false;
  }
  const lowered = normalized.toLowerCase().replace(/^[-:*_#>\s]+|[-:*_#>\s]+$/g, "");
  if (INTERNAL_COACH_META_LABELS.has(lowered)) {
    return true;
  }
  return INTERNAL_COACH_META_MARKERS.some((marker) => lowered.includes(marker.toLowerCase()));
}

function stripLeadingCoachMetaPrefix(value: string): string {
  const normalized = normalizeCoachSurfaceCandidate(value);
  const matched = INTERNAL_COACH_META_MARKERS.find((marker) =>
    normalized.toLowerCase().startsWith(marker.toLowerCase()),
  );
  if (!matched) {
    return normalized;
  }
  return normalized.slice(matched.length).trim();
}
type WorkspaceUnderstandingView = NonNullable<BootstrapData["memory"]["workspaceUnderstanding"]>;
type FirstLookSummaryView = NonNullable<WorkspaceUnderstandingView["firstLookSummary"]>;
type PreviewProviderActionResult = {
  sessionId: string;
  messages: HostMessage[];
};
type PreviewProviderModelCache = {
  availableModels: string[];
  resolvedModel?: string;
  modelTokenLimits?: ProviderConfigView["modelTokenLimits"];
  modelListStatus: ProviderConfigView["modelListStatus"];
  modelListDetail?: string;
  cacheFetchedAt?: string;
  cacheExpiresAt?: string;
  cacheSource?: ProviderConfigView["cacheSource"];
  modelErrorCategory?: string;
  modelStatusCode?: number;
  modelRetryable?: boolean;
};
type PreviewProviderSecretsStore = {
  apiKeysByProvider: Record<string, string>;
  modelCachesByProvider: Record<string, PreviewProviderModelCache>;
  lastTestsByProviderModel: Record<string, ProviderLastTestResult>;
};

// Browser preview is a development harness. Keep credentials process-local and clear legacy storage.
let previewProviderSecretsInMemory: PreviewProviderSecretsStore = {
  apiKeysByProvider: {},
  modelCachesByProvider: {},
  lastTestsByProviderModel: {},
};
const previewFixtureConversationsBySession = new Map<string, ConversationMessage[]>();
const previewFixtureGoalsBySession = new Map<string, string>();
type FixturePreviewStatePatch = Partial<Pick<
  BootstrapData,
  | "conversation"
  | "task"
  | "coachFocus"
  | "coachingState"
  | "coachTurn"
>>;
type FixturePreviewReply = {
  body: string;
  summary: string;
  nextStep: string;
};
type FixturePreviewNextTaskResult = {
  goal: string;
  task?: BootstrapData["task"];
  reply: FixturePreviewReply;
};
type PreviewProviderDraftInput = {
  name?: string;
  protocol?: string;
  baseUrl?: string;
  model?: string;
  contextWindowTokens?: number | null;
  maxOutputTokens?: number | null;
  modelTokenLimits?: ProviderConfigView["modelTokenLimits"];
  credentialMode?: ProviderConfigView["credentialMode"];
  allowedModels?: string[];
  deniedModels?: string[];
  catalogModels?: string[];
  embeddingModel?: string;
  catalogSource?: ProviderConfigView["catalogSource"];
  cacheTtlSeconds?: number | null;
  apiKey?: string;
  capabilities?: ProviderConfigView["capabilities"] | Record<string, unknown>;
  requestDefaults?: Record<string, unknown>;
};

function previewSidecarPortOverride(): number | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  const raw = new URLSearchParams(window.location.search).get("sidecarPort")?.trim();
  if (!raw || !/^\d{1,5}$/.test(raw)) {
    return undefined;
  }
  const port = Number(raw);
  return Number.isInteger(port) && port >= DEV_SIDECAR_PORT && port <= DEV_SIDECAR_PORT_MAX
    ? port
    : undefined;
}

function baseUrl(): string {
  const port = resolvedDevSidecarPort ?? previewSidecarPortOverride() ?? DEV_SIDECAR_PORT;
  return `http://127.0.0.1:${port}`;
}

/** Resolve the extension-managed sidecar port before a live preview request. */
export async function ensureBrowserPreviewSidecar(): Promise<string> {
  if (typeof window === "undefined" || window.__TRAINER_BROWSER_PREVIEW__ !== true) {
    return baseUrl();
  }
  if (isBrowserPreviewFixture()) {
    return baseUrl();
  }
  if (resolvedDevSidecarPort !== undefined) {
    return baseUrl();
  }
  if (sidecarProbePromise) {
    return sidecarProbePromise;
  }

  const override = previewSidecarPortOverride();
  const candidates = override
    ? [override]
    : Array.from({ length: DEV_SIDECAR_PORT_MAX - DEV_SIDECAR_PORT + 1 }, (_, index) => DEV_SIDECAR_PORT + index);
  sidecarProbePromise = (async () => {
    for (const port of candidates) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), DEV_SIDECAR_HEALTH_TIMEOUT_MS);
      try {
        const response = await fetch(`http://127.0.0.1:${port}/health`, {
          method: "GET",
          signal: controller.signal,
        });
        if (response.ok) {
          resolvedDevSidecarPort = port;
          return `http://127.0.0.1:${port}`;
        }
      } catch {
        // Probe the next extension-managed port.
      } finally {
        clearTimeout(timeoutId);
      }
    }
    throw previewRequestError("session", "sidecar unavailable");
  })();
  try {
    return await sidecarProbePromise;
  } finally {
    sidecarProbePromise = undefined;
  }
}

export function browserPreviewSidecarBaseUrl(): string {
  return baseUrl();
}

function previewWorkspaceId(): string {
  if (typeof window === "undefined") {
    return DEV_WORKSPACE_ID_PREFIX;
  }
  try {
    const existing = window.sessionStorage.getItem(PREVIEW_WORKSPACE_ID_STORAGE_KEY)?.trim();
    if (existing) {
      return existing;
    }
    const nextId = `${DEV_WORKSPACE_ID_PREFIX}-${Math.random().toString(36).slice(2, 10)}`;
    window.sessionStorage.setItem(PREVIEW_WORKSPACE_ID_STORAGE_KEY, nextId);
    return nextId;
  } catch {
    // Session storage can be blocked in an embedded browser; retain a per-page workspace instead.
    transientPreviewWorkspaceId ??= `${DEV_WORKSPACE_ID_PREFIX}-${Math.random().toString(36).slice(2, 10)}`;
    return transientPreviewWorkspaceId;
  }
}

function readStoredLivePreviewSessionId(): string | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  try {
    return window.sessionStorage.getItem(PREVIEW_LIVE_SESSION_ID_STORAGE_KEY)?.trim() || undefined;
  } catch {
    // Preview storage can be unavailable in embedded or privacy-restricted browser contexts.
    return undefined;
  }
}

function storeLivePreviewSessionId(sessionId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.setItem(PREVIEW_LIVE_SESSION_ID_STORAGE_KEY, sessionId);
  } catch {
    // A live request still works when the browser cannot persist the resume anchor.
  }
}

function asJsonHeaders(): HeadersInit {
  return {
    "content-type": "application/json",
  };
}

export function browserUploadLimit(): number {
  return MAX_BROWSER_UPLOADS;
}

function resolvePreviewLanguage(): ComposerLanguage {
  const persisted = getPersistedState();
  return isComposerLanguage(persisted?.composerLanguage)
    ? persisted.composerLanguage
    : "en-US";
}

function previewText(english: string, chinese: string): string {
  return resolvePreviewLanguage() === "zh-CN" ? chinese : english;
}

function requireAllowedPreviewProviderModel(
  model: string,
  policy: Pick<ProviderConfigView, "allowedModels" | "deniedModels">,
): void {
  const evaluation = evaluateProviderModelPolicy(model, policy);
  if (evaluation.reason === "denied") {
    throw new Error(
      previewText(
        "This model is blocked for this connection. Choose another model or check the connection settings.",
        "这个模型已被当前连接禁用。请选择其他模型，或检查连接设置。",
      ),
    );
  }
  if (evaluation.reason === "not_allowed") {
    throw new Error(
      previewText(
        "This model is not available for this connection. Choose one of its allowed models or check the connection settings.",
        "这个模型不在当前连接可用的模型范围内。请选择允许使用的模型，或检查连接设置。",
      ),
    );
  }
}

type PreviewRequestFailureScope =
  | "session"
  | "bootstrap"
  | "send"
  | "resource_search"
  | "settings"
  | "models"
  | "provider_test"
  | "upload";
type PreviewFailureCategory = NonNullable<StreamErrorEvent["category"]> | "malformed_response";

const SAFE_PREVIEW_PROVIDER_ERROR_CATEGORIES = new Set([
  "invalid_key_or_permission",
  "invalid_api_key",
  "authentication_failed",
  "rate_limit",
  "timeout",
  "network",
  "network_error",
  "malformed_response",
  "model_unsupported",
  "model_not_supported",
  "model_not_found",
  "workspace_trust",
  "sidecar_unavailable",
  "language_corruption",
  "language_probe_inconclusive",
  "empty_response",
  "reasoning_leak",
  "reasoning_budget_exhausted",
  "truncated_or_empty",
  "context_length_exceeded",
  "provider_error",
]);

function normalizePreviewProviderErrorCategory(value: unknown): string | undefined {
  const category = typeof value === "string" ? value.trim().toLowerCase() : undefined;
  return category && SAFE_PREVIEW_PROVIDER_ERROR_CATEGORIES.has(category) ? category : undefined;
}

function classifyPreviewRequestFailure(
  detail: string,
  statusCode: number | undefined,
  scope: PreviewRequestFailureScope,
): PreviewFailureCategory {
  const normalized = detail.toLowerCase();
  if (
    statusCode === 401 ||
    statusCode === 403 ||
    /invalid[_\s-]?api[_\s-]?key|incorrect api key|unauthorized|forbidden/.test(normalized)
  ) {
    return "invalid_key_or_permission";
  }
  if (statusCode === 429 || /rate limit|too many requests/.test(normalized)) {
    return "rate_limit";
  }
  if (
    /model[_\s-]?(?:unsupported|not found)|unsupported model|does not exist.*model/.test(normalized) ||
    ((scope === "models" || scope === "provider_test") && statusCode === 404)
  ) {
    return "model_unsupported";
  }
  if (/malformed response|unexpected token|invalid json/.test(normalized)) {
    return "malformed_response";
  }
  if (statusCode === 408 || statusCode === 504 || /timed out|timeout|deadline exceeded/.test(normalized)) {
    return "timeout";
  }
  if (/network|fetch failed|econn|connection refused|dns/.test(normalized)) {
    return "network";
  }
  return "provider_error";
}

function previewFailureMessage(category: string | undefined): string {
  const language = resolvePreviewLanguage();
  return (
    providerErrorHint({ modelErrorCategory: category }, language) ??
    providerErrorHint({ modelErrorCategory: "network" }, language) ??
    previewText("This step did not finish. Check the connection and try again.", "这一步没有完成。检查连接后再试一次。")
  );
}

function previewProviderSuccessMessage(kind: "models" | "test"): string {
  const copy = resolveCopy(resolvePreviewLanguage());
  return kind === "models" ? copy.modelReady : copy.providerConnected;
}

function previewProviderResultDetail(
  kind: "models" | "test",
  ok: boolean,
  category: string | undefined,
): string {
  return ok ? previewProviderSuccessMessage(kind) : previewFailureMessage(category ?? "provider_error");
}

function previewRequestError(
  scope: PreviewRequestFailureScope,
  detail: string,
  statusCode?: number,
): Error {
  return new Error(previewFailureMessage(classifyPreviewRequestFailure(detail, statusCode, scope)));
}

function previewErrorDetail(error: unknown): string {
  return error instanceof Error ? error.message : "";
}

async function fetchPreview(
  input: RequestInfo | URL,
  init: RequestInit,
  scope: PreviewRequestFailureScope,
): Promise<Response> {
  try {
    const resolvedSidecarUrl = await ensureBrowserPreviewSidecar();
    const requestUrl = new URL(input.toString());
    if (requestUrl.hostname === "127.0.0.1" && requestUrl.port) {
      requestUrl.port = new URL(resolvedSidecarUrl).port;
    }
    return await fetch(requestUrl, init);
  } catch (error) {
    throw previewRequestError(scope, previewErrorDetail(error));
  }
}

async function throwPreviewHttpFailure(
  response: Response,
  scope: PreviewRequestFailureScope,
): Promise<never> {
  let detail = "";
  try {
    detail = await response.text();
  } catch {
    // The response body is only used to choose a safe recovery message.
  }
  throw previewRequestError(scope, detail, response.status);
}

async function readPreviewJson<T>(
  response: Response,
  scope: PreviewRequestFailureScope,
): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw previewRequestError(scope, "malformed response", response.status);
  }
}

function normalizePreviewRequestDefaults(
  provider: {
    name?: string;
    baseUrl?: string;
    model?: string;
  },
  requestDefaults: unknown,
): Record<string, unknown> {
  return normalizeProviderRequestDefaults(provider, requestDefaults);
}

function normalizePreviewBaseUrl(value: string | undefined): string {
  return (value ?? "").trim().replace(/\/+$/, "");
}

function requirePreviewProviderProtocol(value: string | undefined): ProviderProtocol {
  const protocol = normalizeProviderProtocol(value);
  if (!protocol) {
    throw new Error(
      previewText(
        "Select a chat protocol first. Unknown gateways are not assumed OpenAI-compatible.",
        "请先选择聊天协议。未知网关不会被默认成 OpenAI 兼容。",
      ),
    );
  }
  return protocol;
}

function hasSamePreviewCredentialTransport(
  current: Pick<ProviderConfigView, "baseUrl" | "protocol"> | undefined,
  draft: Pick<ProviderConfigView, "baseUrl" | "protocol">,
): boolean {
  if (!current) {
    return false;
  }
  return (
    normalizePreviewBaseUrl(current.baseUrl) === normalizePreviewBaseUrl(draft.baseUrl) &&
    normalizeProviderProtocol(current.protocol) === normalizeProviderProtocol(draft.protocol)
  );
}

function previewProviderSecrets(): PreviewProviderSecretsStore {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY);
    } catch {
      // Storage may be unavailable in hardened preview environments.
    }
  }

  return {
    apiKeysByProvider: { ...previewProviderSecretsInMemory.apiKeysByProvider },
    modelCachesByProvider: { ...previewProviderSecretsInMemory.modelCachesByProvider },
    lastTestsByProviderModel: { ...previewProviderSecretsInMemory.lastTestsByProviderModel },
  };
}

function savePreviewProviderSecrets(next: PreviewProviderSecretsStore): void {
  previewProviderSecretsInMemory = {
    apiKeysByProvider: { ...next.apiKeysByProvider },
    modelCachesByProvider: { ...next.modelCachesByProvider },
    lastTestsByProviderModel: { ...next.lastTestsByProviderModel },
  };
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY);
    } catch {
      // Storage may be unavailable in hardened preview environments.
    }
  }
}

function previewProviderKey(input: {
  profileId?: string;
  name?: string;
  baseUrl?: string;
  protocol?: string;
}): string {
  const profileId = input.profileId?.trim();
  if (profileId) {
    return `profile:${profileId}`;
  }
  const name = input.name?.trim().toLowerCase() || "provider";
  const baseUrl = normalizePreviewBaseUrl(input.baseUrl).toLowerCase() || "base";
  const protocol = normalizeProviderProtocol(input.protocol);
  return `provider:${protocol ?? "unverified"}:${name}:${baseUrl}`;
}

function previewProviderModelKey(input: {
  profileId?: string;
  name?: string;
  baseUrl?: string;
  protocol?: string;
  model?: string;
}): string {
  const model = input.model?.trim().toLowerCase() || "model";
  return `${previewProviderKey(input)}:model:${model}`;
}

function persistedPreviewProviderRecord(): Record<string, unknown> | undefined {
  const persisted = getPersistedState();
  return asRecord(persisted?.previewProviderConfig);
}

function bootstrapPreviewProviderRecord(): Record<string, unknown> | undefined {
  const bootstrap = getInjectedBootstrapState<BootstrapData>();
  return asRecord(asRecord(bootstrap)?.providerConfig);
}

function activePreviewProviderRecord(): Record<string, unknown> | undefined {
  return persistedPreviewProviderRecord() ?? bootstrapPreviewProviderRecord();
}

function browserPreviewMayUseProtocolCapabilityDefaults(): boolean {
  if (typeof window === "undefined") {
    return true;
  }
  // Fail-closed: VS Code webview (acquireVsCodeApi present, no preview flag)
  // must never invent protocol defaults from this module.
  if (
    typeof window.acquireVsCodeApi === "function" &&
    window.__TRAINER_BROWSER_PREVIEW__ !== true
  ) {
    return false;
  }
  return true;
}

const UNVERIFIED_PREVIEW_CAPABILITIES: CapabilityFlags = {
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

function previewProtocolCapabilityDefaults(
  protocol: ProviderProtocol | undefined,
): CapabilityFlags {
  if (!browserPreviewMayUseProtocolCapabilityDefaults()) {
    return { ...UNVERIFIED_PREVIEW_CAPABILITIES };
  }
  return defaultCapabilitiesForProtocol(protocol);
}

function normalizeCapabilityFlags(
  value: unknown,
  protocol: ProviderProtocol | undefined,
): ProviderConfigView["capabilities"] {
  const record = asRecord(value);
  const fallback = previewProtocolCapabilityDefaults(protocol);
  return {
    chat: asBoolean(record?.chat) ?? fallback.chat,
    responses: asBoolean(record?.responses) ?? fallback.responses,
    vision: asBoolean(record?.vision) ?? fallback.vision,
    embeddings: asBoolean(record?.embeddings) ?? fallback.embeddings,
    tools: asBoolean(record?.tools) ?? fallback.tools,
    jsonSchema: asBoolean(record?.jsonSchema) ?? fallback.jsonSchema,
    structuredOutput: asBoolean(record?.structuredOutput) ?? fallback.structuredOutput,
    streaming: asBoolean(record?.streaming) ?? fallback.streaming,
  };
}

function normalizeProviderProfiles(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({ ...item }));
}

function toModelListStatus(
  value: string | undefined,
  fallback: ProviderConfigView["modelListStatus"] = "idle",
): ProviderConfigView["modelListStatus"] {
  if (value === "loading" || value === "ready" || value === "error") {
    return value;
  }
  return fallback;
}

function asProviderLastTestResult(value: unknown): ProviderLastTestResult | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const checkedAt =
    asString(record.checkedAt) ?? asString(record.checked_at) ?? new Date().toISOString();
  const providerName = asString(record.providerName) ?? asString(record.provider_name) ?? "";
  const baseUrl = asString(record.baseUrl) ?? asString(record.base_url) ?? "";
  const model = asString(record.model) ?? "";
  const protocolText = asString(record.protocol);
  const protocol = protocolText ? normalizeProviderProtocol(protocolText) : undefined;
  if (!providerName || !baseUrl || !model) {
    return undefined;
  }
  const capabilityTruth = normalizeProviderCapabilityTruth(record);
  return {
    ok: asBoolean(record.ok) ?? false,
    status:
      asString(record.status) ?? (asBoolean(record.ok) ? "connected" : "failed"),
    detail: asString(record.detail) ?? "",
    checkedAt,
    workspaceId: asString(record.workspaceId) ?? asString(record.workspace_id),
    profileId:
      asString(record.profileId) ??
      asString(record.profile_id) ??
      asString(record.providerProfileId) ??
      asString(record.provider_profile_id),
    providerName,
    baseUrl,
    model,
    protocol,
    protocolFamily:
      asString(record.protocolFamily) ??
      asString(record.protocol_family) ??
      (protocol ? providerProtocolFamily(protocol) : undefined),
    errorCategory: asString(record.errorCategory) ?? asString(record.error_category),
    retryable: asBoolean(record.retryable),
    statusCode: asNumber(record.statusCode) ?? asNumber(record.status_code),
    responseLanguage:
      toComposerLanguage(asString(record.responseLanguage) ?? asString(record.response_language)),
    capabilityEvidence: capabilityTruth.capabilityEvidence,
    toolsReady: capabilityTruth.toolsReady,
    toolProbeStatus: capabilityTruth.toolProbeStatus,
    streamingReady: capabilityTruth.streamingReady,
    streamProbeStatus: capabilityTruth.streamProbeStatus,
  };
}

function isCompatiblePreviewLastTestResult(
  provider: Pick<ProviderConfigView, "name" | "baseUrl" | "model" | "protocol">,
  result: ProviderLastTestResult | undefined,
): boolean {
  if (!result) {
    return false;
  }
  const resultProtocol = result.protocol ? normalizeProviderProtocol(result.protocol) : undefined;
  return (
    result.providerName.trim().toLowerCase() === provider.name.trim().toLowerCase() &&
    normalizePreviewBaseUrl(result.baseUrl).toLowerCase() ===
      normalizePreviewBaseUrl(provider.baseUrl).toLowerCase() &&
    result.model.trim().toLowerCase() === provider.model.trim().toLowerCase() &&
    (!resultProtocol || resultProtocol === normalizeProviderProtocol(provider.protocol))
  );
}

function buildPreviewProviderDashboard(
  currentProfile: Record<string, unknown> | undefined,
  profiles: Array<Record<string, unknown>>,
  fallback: unknown,
  diagnostics: string[] | undefined,
): Record<string, unknown> | undefined {
  const base = asRecord(fallback);
  const next: Record<string, unknown> = {
    ...(base ?? {}),
    currentProfile: currentProfile ? { ...currentProfile } : base?.currentProfile,
    templateCount: asNumber(base?.templateCount ?? base?.template_count) ?? 0,
    taskBindingCount: asNumber(base?.taskBindingCount ?? base?.task_binding_count) ?? 0,
    diagnostics: diagnostics ?? asStringArray(base?.diagnostics) ?? [],
    profileCount: profiles.length,
  };
  return next;
}

function buildPreviewProviderView(value: unknown): ProviderConfigView | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const protocol = normalizeProviderProtocol(asString(record.protocol));
  const name = asString(record.name) ?? "";
  const baseUrl = normalizePreviewBaseUrl(asString(record.baseUrl));
  const model = asString(record.model) ?? "";
  const profileId = asString(record.profileId) ?? undefined;
  const profiles = normalizeProviderProfiles(record.providerProfiles);
  const providerKey = previewProviderKey({
    profileId,
    name,
    baseUrl,
    protocol,
  });
  const providerModelKey = previewProviderModelKey({
    profileId,
    name,
    baseUrl,
    protocol,
    model,
  });
  const secretStore = previewProviderSecrets();
  const cache = secretStore.modelCachesByProvider[providerKey];
  const inlineModels = asStringArray(record.availableModels) ?? [];
  const availableModels = Array.from(
    new Set([...inlineModels, ...(cache?.availableModels ?? [])].filter(Boolean)),
  );
  const capabilities = normalizeCapabilityFlags(record.capabilities, protocol);
  const lastTest =
    asProviderLastTestResult(record.lastTestResult) ??
    secretStore.lastTestsByProviderModel[providerModelKey];
  const cachedModelTokenLimits = cache?.modelTokenLimits;
  const inlineModelTokenLimits = record.modelTokenLimits as ProviderConfigView["modelTokenLimits"];
  const effectiveModelTokenLimits = mergeProviderModelTokenLimits(
    inlineModelTokenLimits,
    cachedModelTokenLimits,
  );
  const activeProfile =
    profiles.find((item) => asString(item.id) === profileId) ??
    profiles[0];
  const requestDefaults = normalizePreviewRequestDefaults(
    { name, baseUrl, model },
    record.requestDefaults,
  );
  const tokenState = resolveProviderModelTokenState(
    {
      model,
      contextWindowTokens: asNumber(record.contextWindowTokens),
      maxOutputTokens: asNumber(record.maxOutputTokens),
      modelTokenLimits: effectiveModelTokenLimits,
    },
    model,
    {
      modelTokenLimits: effectiveModelTokenLimits,
      hasModelTokenLimits: hasOwn(record, "modelTokenLimits") || Boolean(cachedModelTokenLimits),
      contextWindowTokens: asNumber(record.contextWindowTokens),
      maxOutputTokens: asNumber(record.maxOutputTokens),
      hasContextWindowTokens: hasOwn(record, "contextWindowTokens"),
      hasMaxOutputTokens: hasOwn(record, "maxOutputTokens"),
    },
  );

  return {
    configured: Boolean(name && baseUrl && model),
    name,
    baseUrl,
    model,
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    apiKeyConfigured:
      Boolean(secretStore.apiKeysByProvider[providerKey]?.trim()) ||
      (isBrowserPreviewFixture() && asBoolean(record.apiKeyConfigured) === true),
    capabilities,
    requestDefaults,
    protocol,
    protocolFamily:
      asString(record.protocolFamily) ?? providerProtocolFamily(protocol),
    credentialMode:
      asString(record.credentialMode) === "workspace_secret"
        ? "workspace_secret"
        : "ui_proxy",
    allowedModels:
      asStringArray(record.allowedModels) ??
      asStringArray(activeProfile?.allowedModels) ??
      undefined,
    deniedModels:
      asStringArray(record.deniedModels) ??
      asStringArray(activeProfile?.deniedModels) ??
      undefined,
    catalogModels:
      asStringArray(record.catalogModels) ??
      asStringArray(activeProfile?.catalogModels) ??
      undefined,
    modelAliases:
      (asRecord(record.modelAliases) as Record<string, string> | undefined) ??
      (asRecord(activeProfile?.modelAliases) as Record<string, string> | undefined) ??
      undefined,
    profileId,
    profileLabel:
      asString(record.profileLabel) ??
      asString(activeProfile?.label) ??
      (name || undefined),
    profileMode: asString(record.profileMode) ?? asString(activeProfile?.mode) ?? undefined,
    profileCount:
      asNumber(record.profileCount) ?? (profiles.length > 0 ? profiles.length : undefined),
    availableModels,
    resolvedModel:
      asString(record.resolvedModel) ??
      cache?.resolvedModel ??
      (model || undefined),
    modelCapabilities:
      (asRecord(record.modelCapabilities) as Record<string, ProviderConfigView["capabilities"]>) ??
      undefined,
    modelTokenLimits: tokenState.modelTokenLimits,
    taskBindings:
      (asRecord(record.taskBindings) as Record<string, unknown> | undefined) ??
      (asRecord(activeProfile?.taskBindings) as Record<string, unknown> | undefined) ??
      undefined,
    embeddingModel:
      asString(record.embeddingModel) ??
      asString(activeProfile?.embeddingModel) ??
      undefined,
    catalogSource:
      (asString(record.catalogSource) as ProviderConfigView["catalogSource"] | undefined) ??
      (asString(activeProfile?.catalogSource) as ProviderConfigView["catalogSource"] | undefined) ??
      undefined,
    cacheTtlSeconds:
      asNumber(record.cacheTtlSeconds) ??
      asNumber(activeProfile?.cacheTtlSeconds) ??
      undefined,
    modelListStatus: toModelListStatus(
      asString(record.modelListStatus) ?? cache?.modelListStatus,
      availableModels.length > 0 ? "ready" : "idle",
    ),
    modelListDetail: asString(record.modelListDetail) ?? cache?.modelListDetail,
    cacheFetchedAt: asString(record.cacheFetchedAt) ?? cache?.cacheFetchedAt,
    cacheExpiresAt: asString(record.cacheExpiresAt) ?? cache?.cacheExpiresAt,
    cacheSource:
      (asString(record.cacheSource) as ProviderConfigView["cacheSource"] | undefined) ??
      cache?.cacheSource,
    modelErrorCategory:
      asString(record.modelErrorCategory) ?? cache?.modelErrorCategory,
    modelStatusCode:
      asNumber(record.modelStatusCode) ?? cache?.modelStatusCode,
    modelRetryable:
      asBoolean(record.modelRetryable) ?? cache?.modelRetryable,
    workspaceSecretConfigured: asBoolean(record.workspaceSecretConfigured),
    protocolDiagnostic: asRecord(record.protocolDiagnostic) ?? undefined,
    taskBindingDiagnostics:
      Array.isArray(record.taskBindingDiagnostics) &&
      record.taskBindingDiagnostics.every((item) => Boolean(asRecord(item)))
        ? (record.taskBindingDiagnostics as Array<Record<string, unknown>>)
        : undefined,
    modelDiagnostics:
      Array.isArray(record.modelDiagnostics) &&
      record.modelDiagnostics.every((item) => Boolean(asRecord(item)))
        ? (record.modelDiagnostics as Array<Record<string, unknown>>)
        : undefined,
    modelTest: asRecord(record.modelTest) ?? undefined,
    modelListing: asRecord(record.modelListing) ?? undefined,
    diagnostics: asStringArray(record.diagnostics) ?? undefined,
    warnings: asStringArray(record.warnings) ?? undefined,
    profileHistory:
      Array.isArray(record.profileHistory) &&
      record.profileHistory.every((item) => Boolean(asRecord(item)))
        ? (record.profileHistory as Array<Record<string, unknown>>)
        : undefined,
    providerProfiles: profiles.length > 0 ? profiles : undefined,
    providerDashboard: buildPreviewProviderDashboard(
      activeProfile,
      profiles,
      record.providerDashboard,
      asStringArray(record.diagnostics) ?? undefined,
    ),
    lastTestResult: isCompatiblePreviewLastTestResult(
      {
        name,
        baseUrl,
        model,
        protocol,
      },
      lastTest,
    )
      ? lastTest
      : undefined,
  };
}

function buildPreviewProviderOverride() {
  const storedProvider = buildPreviewProviderView(activePreviewProviderRecord());
  if (!storedProvider?.configured) {
    return undefined;
  }
  const transport = buildPreviewProviderTransport(storedProvider);
  return transport
    ? {
        ...transport,
        view: storedProvider,
      }
    : undefined;
}

function buildPreviewProviderTransport(
  providerConfig: ProviderConfigView,
  apiKeyOverride?: string,
) {
  const providerKey = previewProviderKey({
    profileId: providerConfig.profileId,
    name: providerConfig.name,
    baseUrl: providerConfig.baseUrl,
    protocol: providerConfig.protocol,
  });
  const apiKey = apiKeyOverride?.trim() || previewProviderSecrets().apiKeysByProvider[providerKey]?.trim() || undefined;
  return {
    apiKey,
    provider: {
      name: providerConfig.name,
      baseUrl: providerConfig.baseUrl,
      model: providerConfig.model,
      contextWindowTokens: providerConfig.contextWindowTokens,
      maxOutputTokens: providerConfig.maxOutputTokens,
      modelTokenLimits: providerConfig.modelTokenLimits,
      protocol: providerConfig.protocol,
      apiKeyRef: `${providerKey}.default`,
      requestDefaults: normalizePreviewRequestDefaults(providerConfig, providerConfig.requestDefaults),
      capabilities: providerConfig.capabilities,
    },
  };
}

function buildPreviewProfileRecord(
  input: {
    id: string;
    label: string;
    name: string;
    protocol: ProviderProtocol;
    baseUrl: string;
    model: string;
    availableModels: string[];
    contextWindowTokens?: number;
    maxOutputTokens?: number;
    modelTokenLimits?: ProviderConfigView["modelTokenLimits"];
    capabilities: ProviderConfigView["capabilities"];
    requestDefaults?: Record<string, unknown>;
    mode?: string;
    credentialMode?: ProviderConfigView["credentialMode"];
    modelAliases?: ProviderConfigView["modelAliases"];
    taskBindings?: ProviderConfigView["taskBindings"];
    allowedModels?: string[];
    deniedModels?: string[];
    embeddingModel?: string;
    catalogSource?: ProviderConfigView["catalogSource"];
    cacheTtlSeconds?: number;
  },
): Record<string, unknown> {
  const requestDefaults = normalizePreviewRequestDefaults(input, input.requestDefaults);
  return {
    id: input.id,
    label: input.label,
    name: input.name,
    protocol: input.protocol,
    mode: input.mode ?? "direct",
    credentialMode: input.credentialMode ?? "ui_proxy",
    baseUrl: input.baseUrl,
    apiKeyRef: `${input.id}.default`,
    model: input.model,
    availableModels: Array.from(new Set(input.availableModels.filter(Boolean))),
    contextWindowTokens: input.contextWindowTokens,
    maxOutputTokens: input.maxOutputTokens,
    modelTokenLimits: input.modelTokenLimits,
    capabilities: input.capabilities,
    requestDefaults,
    modelAliases: input.modelAliases ?? {},
    taskBindings: input.taskBindings ?? {},
    allowedModels: input.allowedModels ?? [],
    deniedModels: input.deniedModels ?? [],
    embeddingModel: input.embeddingModel,
    catalogSource: input.catalogSource ?? "provider_live",
    cacheTtlSeconds: input.cacheTtlSeconds,
  };
}

export function browserPreviewProviderRequestOverride() {
  const override = buildPreviewProviderOverride();
  if (!override) {
    return undefined;
  }
  return {
    provider: override.provider,
    apiKey: override.apiKey,
  };
}

function buildPreviewProviderPatch(
  providerConfig: ProviderConfigView,
): Partial<BootstrapData> {
  return {
    // The preview sidecar transport and a tested model are different facts.
    // Preserve the transport state supplied by bootstrap; Settings derives
    // model readiness exclusively from ProviderConfig.lastTestResult.
    providerConfig,
  };
}

function buildPreviewProviderResult(
  sessionId: string,
  providerConfig: ProviderConfigView,
  status: { tone: "info" | "success" | "error"; message: string },
): PreviewProviderActionResult {
  return {
    sessionId,
    messages: [
      {
        type: "state/patch",
        payload: buildPreviewProviderPatch(providerConfig),
      },
      {
        type: "operation/status",
        payload: status,
      },
    ],
  };
}

function uniquePreviewProfileId(
  name: string,
  profiles: Array<Record<string, unknown>>,
): string {
  const base =
    name
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "provider";
  const taken = new Set(
    profiles
      .map((item) => asString(item.id)?.trim())
      .filter((item): item is string => Boolean(item)),
  );
  if (!taken.has(base)) {
    return base;
  }
  let index = 2;
  while (taken.has(`${base}-${index}`)) {
    index += 1;
  }
  return `${base}-${index}`;
}

function storePreviewProviderApiKey(
  providerConfig: Pick<ProviderConfigView, "profileId" | "name" | "baseUrl" | "protocol">,
  apiKey: string | undefined,
): void {
  if (apiKey === undefined) {
    return;
  }
  const next = previewProviderSecrets();
  const providerKey = previewProviderKey(providerConfig);
  if (apiKey.trim()) {
    next.apiKeysByProvider[providerKey] = apiKey.trim();
  } else {
    delete next.apiKeysByProvider[providerKey];
  }
  savePreviewProviderSecrets(next);
}

function storePreviewProviderLastTest(
  providerConfig: Pick<ProviderConfigView, "profileId" | "name" | "baseUrl" | "protocol" | "model">,
  result: ProviderLastTestResult,
): void {
  const next = previewProviderSecrets();
  next.lastTestsByProviderModel[previewProviderModelKey(providerConfig)] = result;
  savePreviewProviderSecrets(next);
}

function storePreviewProviderModelCache(
  providerConfig: Pick<ProviderConfigView, "profileId" | "name" | "baseUrl" | "protocol">,
  cache: PreviewProviderModelCache,
): void {
  const next = previewProviderSecrets();
  next.modelCachesByProvider[previewProviderKey(providerConfig)] = cache;
  savePreviewProviderSecrets(next);
}

function clearPreviewProviderSecrets(): void {
  previewProviderSecretsInMemory = {
    apiKeysByProvider: {},
    modelCachesByProvider: {},
    lastTestsByProviderModel: {},
  };
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(PREVIEW_PROVIDER_SECRETS_STORAGE_KEY);
    } catch {
      // Storage may be unavailable in hardened preview environments.
    }
  }
}

function buildPreviewProviderStatusResult(
  sessionId: string,
  status: { tone: "info" | "success" | "error"; message: string },
): PreviewProviderActionResult {
  return {
    sessionId,
    messages: [
      {
        type: "operation/status",
        payload: status,
      },
    ],
  };
}

function buildPreviewDraftProvider(
  draft: PreviewProviderDraftInput,
  current?: ProviderConfigView,
): ProviderConfigView {
  const protocol = normalizeProviderProtocol(draft.protocol ?? current?.protocol);
  const name = draft.name?.trim() || current?.name?.trim() || PREVIEW_DEFAULT_PROVIDER_NAME;
  const baseUrl = normalizePreviewBaseUrl(
    draft.baseUrl !== undefined ? draft.baseUrl : current?.baseUrl,
  );
  const model = draft.model !== undefined ? draft.model.trim() : current?.model ?? "";
  const sameTransportAsCurrent = Boolean(
    current &&
      protocol === normalizeProviderProtocol(current.protocol) &&
      baseUrl === normalizePreviewBaseUrl(current.baseUrl),
  );
  const draftAvailableModels =
    draft.catalogModels ?? (sameTransportAsCurrent ? current?.availableModels : undefined) ?? [];
  const draftCatalogModels =
    draft.catalogModels ?? (sameTransportAsCurrent ? current?.catalogModels : undefined) ?? [];
  const provider = buildPreviewProviderView({
    ...(current ?? {}),
    configured: false,
    name,
    baseUrl,
    model,
    protocol,
    availableModels: draftAvailableModels,
    catalogModels: draftCatalogModels,
    allowedModels: draft.allowedModels ?? current?.allowedModels,
    deniedModels: draft.deniedModels ?? current?.deniedModels,
    capabilities: draft.capabilities ?? current?.capabilities,
    requestDefaults: draft.requestDefaults ?? current?.requestDefaults,
  });
  if (!provider) {
    throw new Error("Preview provider draft could not be prepared.");
  }
  return provider;
}

function buildPreviewDraftModelResult(
  sessionId: string,
  current: ProviderConfigView | undefined,
  refreshed: { detail?: string; provider: ProviderConfigView; ok: boolean },
): PreviewProviderActionResult {
  const baseProvider =
    current ??
    buildPreviewProviderView({
      configured: false,
      name: "",
      baseUrl: "",
      model: "",
      protocol: "openai_chat_completions_compatible",
      capabilities: previewProtocolCapabilityDefaults("openai_chat_completions_compatible"),
      availableModels: [],
    });
  if (!baseProvider) {
    throw new Error("Preview provider draft model refresh could not preserve provider state.");
  }
  const draftProtocol = normalizeProviderProtocol(refreshed.provider.protocol);
  const draftListing = {
    source: "draft",
    name: refreshed.provider.name,
    baseUrl: refreshed.provider.baseUrl,
    protocol: draftProtocol,
    protocolFamily: providerProtocolFamily(draftProtocol),
    model: refreshed.provider.model,
    availableModels: refreshed.provider.availableModels,
    resolvedModel: refreshed.provider.resolvedModel,
    modelTokenLimits: refreshed.provider.modelTokenLimits,
    fetchedAt: refreshed.provider.cacheFetchedAt,
    errorCategory: refreshed.provider.modelErrorCategory,
    retryable: refreshed.provider.modelRetryable,
    statusCode: refreshed.provider.modelStatusCode,
    status: refreshed.provider.modelListStatus,
  };
  const providerConfig = {
    ...baseProvider,
    availableModels: baseProvider.configured
      ? baseProvider.availableModels
      : refreshed.provider.availableModels,
    modelListStatus: refreshed.provider.modelListStatus,
    modelListDetail: refreshed.provider.modelListDetail,
    cacheFetchedAt: refreshed.provider.cacheFetchedAt,
    cacheExpiresAt: refreshed.provider.cacheExpiresAt,
    cacheSource: refreshed.provider.cacheSource,
    modelErrorCategory: refreshed.provider.modelErrorCategory,
    modelStatusCode: refreshed.provider.modelStatusCode,
    modelRetryable: refreshed.provider.modelRetryable,
    modelListing: draftListing,
  };
  return {
    sessionId,
    messages: [
      {
        type: "state/patch",
        payload: { providerConfig },
      },
      {
        type: "operation/status",
        payload: {
          tone: refreshed.ok ? "success" : "error",
          message:
            refreshed.detail ??
            previewText("Model refresh completed.", "模型列表已刷新。"),
        },
      },
    ],
  };
}

function clearPreviewProviderRuntimeState(providerKey: string): void {
  const next = previewProviderSecrets();
  delete next.apiKeysByProvider[providerKey];
  delete next.modelCachesByProvider[providerKey];
  for (const key of Object.keys(next.lastTestsByProviderModel)) {
    if (key.startsWith(`${providerKey}:model:`)) {
      delete next.lastTestsByProviderModel[key];
    }
  }
  savePreviewProviderSecrets(next);
}

function upsertPreviewProfile(
  profiles: Array<Record<string, unknown>>,
  profile: Record<string, unknown>,
): Array<Record<string, unknown>> {
  const profileId = asString(profile.id)?.trim();
  if (!profileId) {
    return profiles;
  }
  const next = profiles.map((item) => ({ ...item }));
  const existingIndex = next.findIndex((item) => asString(item.id)?.trim() === profileId);
  if (existingIndex >= 0) {
    next.splice(existingIndex, 1, { ...profile });
    return next;
  }
  return [{ ...profile }, ...next];
}

function appendPreviewProfileHistory(
  history: Array<Record<string, unknown>> | undefined,
  fromProfileId: string | undefined,
  toProfileId: string,
  reason: string,
): Array<Record<string, unknown>> {
  return [
    {
      entryId: `history-${Date.now()}`,
      fromProfileId,
      toProfileId,
      reason,
      timestamp: new Date().toISOString(),
    },
    ...(history ?? []).map((item) => ({ ...item })),
  ].slice(0, 20);
}

export function inBrowserPreviewMode(): boolean {
  return typeof window !== "undefined" && !window.acquireVsCodeApi;
}

/** Fixture previews own their bootstrap locally; live previews must use the Sidecar. */
export function isBrowserPreviewFixtureMode(): boolean {
  return isBrowserPreviewFixture();
}

function isBrowserPreviewFixture(): boolean {
  if (typeof window === "undefined" || window.__TRAINER_BROWSER_PREVIEW__ !== true) {
    return false;
  }
  const previewSearch = new URLSearchParams(window.location.search);
  if (previewSearch.get("live") === "1") {
    return false;
  }
  return Boolean(window.__TRAINER_BOOTSTRAP__) && typeof window.__TRAINER_BOOTSTRAP__ === "object";
}

function compactPreviewGoal(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= 120) {
    return normalized;
  }
  return `${normalized.slice(0, 119).trimEnd()}...`;
}

function looksLikePreviewGoal(value: string): boolean {
  const normalized = value.toLowerCase();
  return [
    "i want",
    "i'd like",
    "want to learn",
    "want to build",
    "my goal",
    "learn ",
    "build ",
    "make ",
    "start ",
    "become ",
    "想学",
    "想做",
    "我要",
    "我想",
    "帮我",
    "做一个",
    "做个",
    "学会",
    "入门",
    "想在",
    "目标",
    "希望",
  ].some((marker) => normalized.includes(marker));
}

function fixturePreviewTimestamp(language: ComposerLanguage): string {
  switch (language) {
    case "zh-CN":
      return "刚刚";
    case "es-ES":
      return "Ahora mismo";
    case "fr-FR":
      return "A l'instant";
    case "de-DE":
      return "Gerade eben";
    case "ja-JP":
      return "たった今";
    case "ko-KR":
      return "방금";
    case "pt-BR":
      return "Agora mesmo";
    case "en-US":
    default:
      return "Just now";
  }
}

function resolveFixturePreviewGoal(request: SessionMessageRequest, sessionId: string): string {
  const candidate = compactPreviewGoal(request.text);
  const saved = previewFixtureGoalsBySession.get(sessionId);
  if (looksLikePreviewGoal(candidate)) {
    previewFixtureGoalsBySession.set(sessionId, candidate);
    return candidate;
  }
  if (saved) {
    return saved;
  }
  return browserPreviewCoachCopy(request.responseLanguage ?? resolvePreviewLanguage()).fallbackGoal;
}

function fixturePreviewReply(
  request: SessionMessageRequest,
  fixtureGoal?: string,
  options?: {
    continuation?: boolean;
    activeTask?: string;
  },
): FixturePreviewReply {
  const language = request.responseLanguage ?? resolvePreviewLanguage();
  const copy = browserPreviewCoachCopy(language);
  if (request.attachments && request.attachments.length > 0) {
    const body =
      language === "zh-CN"
        ? "已经看到附图。先说图里实际有什么、哪里不清楚，再给最小下一步。"
        : "Inspect the attached image. First say what is actually visible and what is unclear, then give the smallest next step.";
    return {
      summary: body,
      nextStep: copy.nextAfterCurrent,
      body,
    };
  }
  const goal =
    fixtureGoal ||
    compactPreviewGoal(request.text) ||
    copy.fallbackGoal;
  const planMode = request.planComposerMode;
  if (request.activeView === "plan" && planMode) {
    const modeCopy =
      language === "zh-CN"
        ? {
            explain: "本地预览已记录这次计划解释讨论；正式计划保持不变。",
            evidence: "本地预览已记录这条证据讨论；正式计划保持不变。",
            blocker: "本地预览已记录这个 blocker，并保留当前正式计划不变。",
            generate: "本地预览已生成一份候选计划草案；它尚未写入正式计划。",
          }
        : {
            explain: "The local preview recorded this plan explanation; the formal plan is unchanged.",
            evidence: "The local preview recorded this evidence discussion; the formal plan is unchanged.",
            blocker: "The local preview recorded this blocker; the formal plan remains unchanged.",
            generate: "The local preview generated a candidate plan draft; it has not been written to the formal plan.",
          };
    const body = modeCopy[planMode];
    return {
      summary: modeCopy[planMode],
      nextStep:
        planMode === "generate"
          ? language === "zh-CN"
            ? "检查候选草案后，再通过正式计划能力明确确认。"
            : "Review the candidate draft, then explicitly confirm it through formal-plan capability."
          : copy.nextAfterCurrent,
      body,
    };
  }
  if (options?.continuation) {
    const activeTask = options.activeTask?.trim();
    const nextStep = activeTask
      ? copy.taskReady(activeTask)
      : copy.nextAfterCurrent;
    return {
      summary: copy.planSummary,
      nextStep,
      body: `${copy.planSummary}\n\n${goal}\n\n${nextStep}`,
    };
  }
  const nextStep = copy.nextAfterCurrent;
  return {
    summary: copy.planSummary,
    nextStep,
    body: `${copy.planSummary}\n\n${goal}\n\n${nextStep}`,
  };
}

function fixturePreviewGoalStart(
  request: SessionMessageRequest,
  goal: string,
): { patch: BrowserPreviewPatch; result: FixturePreviewNextTaskResult } {
  const language = request.responseLanguage ?? resolvePreviewLanguage();
  const copy = browserPreviewCoachCopy(language);
  const bootstrap =
    getInjectedBootstrapState<BrowserPreviewBootstrap>() ?? ({} as BrowserPreviewBootstrap);
  const patch = buildGoalAwarePreviewPlanPatch(bootstrap, language, goal);
  const task = patch.task;
  if (!task) {
    throw new Error("Preview starter plan did not produce a current task.");
  }
  const summary = copy.generateSucceeded;
  const nextStep = copy.taskReady(task.title);
  return {
    patch,
    result: {
      goal,
      task,
      reply: {
        summary,
        nextStep,
        body: `${copy.generateSucceeded}\n\n${task.title}\n${task.description}\n\n${copy.nextAfterCurrent}`,
      },
    },
  };
}

function fixturePreviewNextTaskResult(
  request: SessionMessageRequest,
): FixturePreviewNextTaskResult {
  const language = request.responseLanguage ?? resolvePreviewLanguage();
  const copy = browserPreviewCoachCopy(language);
  const bootstrap =
    getInjectedBootstrapState<BrowserPreviewBootstrap>() ?? ({} as BrowserPreviewBootstrap);
  const goal = resolveBrowserPreviewGoal(bootstrap, language);
  const result = runBrowserPreviewAction({ type: "task/next" }, bootstrap, language);
  const task = result.patch?.task;

  if (!task) {
    const nextStep = copy.missingPlan;
    const message = result.message.trim();
    return {
      goal,
      reply: {
        summary: message,
        nextStep,
        body: message === nextStep.trim() ? message : `${message}\n\n${nextStep}`,
      },
    };
  }

  const acceptance =
    task.acceptanceCriteria[0] ??
    copy.verification;
  return {
    goal,
    task,
    reply: {
      summary: result.message,
      nextStep: task.nextActionLabel,
      body: `${copy.taskReady(task.title)}\n\n${task.description}\n\n${acceptance}`,
    },
  };
}

function fixturePreviewStatePatch(
  request: SessionMessageRequest,
  sessionId: string,
  conversation: ConversationMessage[],
  reply: FixturePreviewReply,
  nextTaskResult?: FixturePreviewNextTaskResult,
): FixturePreviewStatePatch {
  const responseLanguage = request.responseLanguage ?? "en-US";
  const isChinese = responseLanguage === "zh-CN";
  if (nextTaskResult) {
    const task = nextTaskResult.task;
    const taskReady = Boolean(task);
    return {
      conversation,
      ...(task ? { task } : {}),
      coachFocus: {
        currentFocus: nextTaskResult.goal,
        nextStep: reply.nextStep,
        activeTask: task?.title,
        scenario: taskReady ? "next_task" : "plan",
        relationshipStage: taskReady ? "active" : "intake",
        firstTurnPriority: taskReady
          ? isChinese
            ? "\u5148\u5b8c\u6210\u5f53\u524d\u4efb\u52a1\u7684\u6700\u5c0f\u53ef\u89c1\u7ed3\u679c\uff0c\u518d\u56de\u5230\u4e3b\u7ebf\u3002"
            : "Finish the smallest visible result for the current task, then return to the main thread."
          : isChinese
            ? "\u5148\u751f\u6210\u6b63\u5f0f\u8ba1\u5212\uff0c\u518d\u51b3\u5b9a\u5f53\u524d\u4efb\u52a1\u3002"
            : "Create the formal plan before choosing the current task.",
        language: responseLanguage,
      },
      coachingState: {
        scenario: taskReady ? "next_task" : "plan",
        answerMode: "guided",
        learnerSignal: taskReady ? "steady" : "uncertain",
        summary: reply.summary,
        nextStep: reply.nextStep,
        encouragement: taskReady
          ? isChinese
            ? "\u4e00\u6b21\u53ea\u5b8c\u6210\u8fd9\u4e00\u5c0f\u6b65\uff0c\u5b8c\u6210\u540e\u518d\u7ee7\u7eed\u3002"
            : "Complete this one small step, then continue."
          : isChinese
            ? "\u5148\u628a\u65b9\u5411\u56fa\u5b9a\u6210\u6b63\u5f0f\u8ba1\u5212\uff0c\u4e0b\u4e00\u6b65\u5c31\u4f1a\u6e05\u695a\u3002"
            : "Fix the direction as a formal plan first; the next step will become clear.",
        updatedAt: new Date().toISOString(),
      },
      coachTurn: {
        scenario: taskReady ? "next_task" : "plan",
        learnerSignal: taskReady ? "steady" : "uncertain",
        summary: reply.summary,
        nextStep: reply.nextStep,
        encouragement: taskReady
          ? isChinese
            ? "\u5b8c\u6210\u8fd9\u4e00\u5c0f\u6b65\u540e\uff0c\u518d\u5e26\u7740\u7ed3\u679c\u7ee7\u7eed\u3002"
            : "Finish this small step, then continue with the result."
          : isChinese
            ? "\u5148\u751f\u6210\u6b63\u5f0f\u8ba1\u5212\uff0c\u518d\u7ee7\u7eed\u3002"
            : "Create the formal plan first, then continue.",
        activeTask: task?.title,
        artifactKinds: [taskReady ? "task" : "plan"],
        suggestedActionTypes: [taskReady ? "next_task" : "plan"],
        backgroundMode: "embedded",
      },
    };
  }
  const goal =
    resolveFixturePreviewGoal(request, sessionId) ||
    (isChinese ? "你想开始学习的目标" : "your learning goal");
  const intakeId = `browser-preview-intake-${sessionId}`;
  const taskTitle = isChinese
    ? `为「${goal}」安排第一周的起步成果`
    : `Prepare a first-week outcome for "${goal}"`;
  const verification = isChinese
    ? "说清楚每周能投入的时间，以及第一周想完成的成果。"
    : "State your weekly time and the outcome you want to finish in week one.";

  return {
    conversation,
    task: {
      id: `task-${intakeId}`,
      title: taskTitle,
      description: isChinese
        ? "先确认你的基础、每周时间和第一周能完成的小成果。"
        : "First confirm your current level, weekly time, and one small outcome you can finish in week one.",
      constraints: [
        isChinese ? "不需要先提供代码、报错或文件。" : "No code, error, or file is needed first.",
      ],
      acceptanceCriteria: [verification],
      nextActionLabel: isChinese ? "补充每周时间" : "Add weekly time",
    },
    coachFocus: {
      currentFocus: goal,
      nextStep: reply.nextStep,
      activeTask: taskTitle,
      scenario: "onboarding",
      relationshipStage: "intake",
      firstTurnPriority: isChinese
        ? "先了解目标、基础和可投入时间，再安排学习路径。"
        : "Understand the goal, starting point, and available time before choosing a learning path.",
      language: responseLanguage,
    },
    coachingState: {
      scenario: "onboarding",
      answerMode: "guided",
      learnerSignal: "curious",
      summary: reply.summary,
      nextStep: reply.nextStep,
      encouragement: isChinese
        ? "先从能完成的一小步开始，方向会越来越清楚。"
        : "Start with one finishable step, and the path will become clearer.",
      updatedAt: new Date().toISOString(),
    },
    coachTurn: {
      scenario: "onboarding",
      learnerSignal: "curious",
      summary: reply.summary,
      nextStep: reply.nextStep,
      encouragement: isChinese
        ? "先从能完成的一小步开始，方向会越来越清楚。"
        : "Start with one finishable step, and the path will become clearer.",
      activeTask: taskTitle,
      artifactKinds: ["task"],
      suggestedActionTypes: ["task"],
      backgroundMode: "embedded",
    },
  };
}

function fixturePreviewConversation(
  request: SessionMessageRequest,
  sessionId: string,
): { patch: FixturePreviewStatePatch; reply: FixturePreviewReply } {
  const existing = previewFixtureConversationsBySession.get(sessionId);
  const injected = getInjectedBootstrapState<BootstrapData>();
  const priorGoal = previewFixtureGoalsBySession.get(sessionId);
  const candidate = compactPreviewGoal(request.text);
  const hasFormalPlan = Boolean(
    (injected as BrowserPreviewBootstrap | undefined)?.hasFormalPlan || injected?.plan?.stages?.length,
  );
  const startsNewGoal = Boolean(candidate) && !hasFormalPlan && (!priorGoal || looksLikePreviewGoal(candidate));
  const nextTaskResult = request.intent === "next_task" ? fixturePreviewNextTaskResult(request) : undefined;
  const fixtureGoal = nextTaskResult?.goal ?? resolveFixturePreviewGoal(request, sessionId);
  const starter =
    !nextTaskResult && startsNewGoal && fixtureGoal
      ? fixturePreviewGoalStart(request, fixtureGoal)
      : undefined;
  const hasContinuation = Boolean(existing?.some((message) => message.role === "user")) || hasFormalPlan;
  const reply =
    nextTaskResult?.reply ??
    starter?.result.reply ??
    fixturePreviewReply(request, fixtureGoal, {
      continuation: hasContinuation,
      activeTask: injected?.task?.title,
    });
  const hasStarterPlan =
    (injected as BrowserPreviewBootstrap | undefined)?.hasFormalPlan === true ||
    Boolean(injected?.plan?.stages?.length);
  const continuationResult =
    !nextTaskResult && !starter && hasContinuation && hasStarterPlan && injected?.task
      ? { goal: fixtureGoal, task: injected.task, reply }
      : undefined;
  const conversation = existing
    ? [...existing]
    : Array.isArray(injected?.conversation)
      ? injected.conversation.map((message) => ({ ...message }))
      : [];
  const idPrefix = `browser-preview-${Date.now()}`;
  const language = request.responseLanguage ?? resolvePreviewLanguage();
  const timestamp = fixturePreviewTimestamp(language);
  const nextConversation = [
    ...conversation,
    {
      id: `${idPrefix}-user`,
      role: "user" as const,
      author: resolveCopy(language).you,
      body: request.text.trim(),
      timestamp,
    },
    {
      id: `${idPrefix}-assistant`,
      role: "assistant" as const,
      author: "Trainer",
      body: reply.body,
      timestamp,
    },
  ];
  previewFixtureConversationsBySession.set(sessionId, nextConversation);
  const patch = fixturePreviewStatePatch(
    request,
    sessionId,
    nextConversation,
    reply,
    nextTaskResult ?? starter?.result ?? continuationResult,
  );
  const mergedPatch = starter ? { ...starter.patch, ...patch } : patch;
  if (request.activeView === "plan" && request.planComposerMode === "generate" && !request.formalPlanMutation) {
    const language = request.responseLanguage ?? resolvePreviewLanguage();
    const candidateLabel =
      language === "zh-CN" ? "候选计划草案（未写入正式计划）" : "Candidate plan draft (not written to the formal plan)";
    mergedPatch.coachTurn = {
      ...mergedPatch.coachTurn,
      scenario: "plan",
      learnerSignal: "curious",
      summary: reply.summary,
      nextStep: reply.nextStep,
      activeTask: candidateLabel,
      artifactKinds: ["plan"],
      suggestedActionTypes: ["plan"],
    };
  }
  if (injected) {
    window.__TRAINER_BOOTSTRAP__ = {
      ...injected,
      ...mergedPatch,
    };
  }
  return { patch: mergedPatch, reply };
}

let inFlightPreviewSessionStart: Promise<string> | null = null;

export async function ensureBrowserPreviewSession(existingSessionId?: string): Promise<string> {
  if (existingSessionId?.trim()) {
    return existingSessionId;
  }
  const workspaceId = previewWorkspaceId();

  if (isBrowserPreviewFixture()) {
    return `browser-preview-local-${workspaceId}`;
  }
  const storedSessionId = readStoredLivePreviewSessionId();
  if (storedSessionId) {
    return storedSessionId;
  }

  // Deduplicate concurrent session-start calls: without this, two callers racing
  // through this path each POST /session/start and the workspace ends up with
  // split session identities (writes land on session A, reads on session B).
  if (inFlightPreviewSessionStart) {
    return inFlightPreviewSessionStart;
  }

  inFlightPreviewSessionStart = (async () => {
    try {
      const response = await fetchPreview(`${baseUrl()}/session/start`, {
        method: "POST",
        headers: asJsonHeaders(),
        body: JSON.stringify({
          workspace_id: workspaceId,
          workspace_name: DEV_WORKSPACE_NAME,
        }),
      }, "session");

      if (!response.ok) {
        await throwPreviewHttpFailure(response, "session");
      }

      const payload = await readPreviewJson<{ session_id?: string }>(response, "session");
      if (!payload.session_id) {
        throw previewRequestError("session", "malformed response", response.status);
      }
      storeLivePreviewSessionId(payload.session_id);
      return payload.session_id;
    } finally {
      inFlightPreviewSessionStart = null;
    }
  })();
  return inFlightPreviewSessionStart;
}

export async function fetchBrowserPreviewBootstrap(
  sessionId?: string,
  forceLive = false,
): Promise<{ sessionId: string; message: HostMessage }> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const workspaceId = previewWorkspaceId();
  const previewBootstrap =
    typeof window !== "undefined"
      ? (window as Window & { __TRAINER_BOOTSTRAP__?: unknown }).__TRAINER_BOOTSTRAP__
      : undefined;
  if (!forceLive && previewBootstrap && typeof previewBootstrap === "object") {
    return {
      sessionId: resolvedSessionId,
      message: {
        type: "bootstrap",
        payload: structuredClone(previewBootstrap) as BootstrapData,
      },
    };
  }
  const responseLanguage = resolvePreviewLanguage();
  const settingsResponse = await fetchPreview(`${baseUrl()}/memory/settings`, {
    method: "POST",
    headers: asJsonHeaders(),
    body: JSON.stringify({
      session_id: resolvedSessionId,
      workspace_id: workspaceId,
      response_language: responseLanguage,
    }),
  }, "bootstrap");
  if (!settingsResponse.ok) {
    await throwPreviewHttpFailure(settingsResponse, "bootstrap");
  }
  const snapshotResponse = await fetchPreview(
    `${baseUrl()}/memory/summary?session_id=${encodeURIComponent(resolvedSessionId)}&workspace_id=${encodeURIComponent(
      workspaceId,
    )}`,
    {},
    "bootstrap",
  );
  if (!snapshotResponse.ok) {
    await throwPreviewHttpFailure(snapshotResponse, "bootstrap");
  }
  const snapshot = await readPreviewJson(snapshotResponse, "bootstrap");
  return {
    sessionId: resolvedSessionId,
    message: {
      type: "bootstrap",
      payload: mapSnapshotToBootstrap(snapshot),
    },
  };
}

export interface BrowserPreviewResourceSearchRequest {
  query: string;
  requestId: string;
  mode?: ResourceSearchMode;
  topK?: number;
}

export async function searchBrowserPreviewResources(
  request: BrowserPreviewResourceSearchRequest,
  sessionId?: string,
): Promise<{ sessionId: string; message: HostMessage }> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const query = request.query.trim();
  if (!query) {
    throw previewRequestError("resource_search", "query is empty");
  }

  if (isBrowserPreviewFixture()) {
    const injected = window.__TRAINER_BOOTSTRAP__;
    const bootstrap =
      injected && typeof injected === "object"
        ? (injected as BootstrapData)
        : undefined;
    const normalizedQuery = query.toLocaleLowerCase();
    const hits = (bootstrap?.resources ?? []).filter((resource) =>
      [resource.title, resource.summary, resource.source, ...(resource.tags ?? [])]
        .filter((value): value is string => Boolean(value))
        .some((value) => value.toLocaleLowerCase().includes(normalizedQuery)),
    );
    const resourceSearch: ResourceSearchState = {
      requestId: request.requestId,
      workspaceId: undefined,
      query,
      total: hits.length,
      rankingStrategy: "fixture_local",
      filters: {},
      hits,
    };
    if (bootstrap) {
      window.__TRAINER_BOOTSTRAP__ = { ...bootstrap, resourceSearch };
    }
    return {
      sessionId: resolvedSessionId,
      message: { type: "state/patch", payload: { resourceSearch } },
    };
  }

  const workspaceId = previewWorkspaceId();
  const mode = normalizeResourceSearchMode(request.mode);
  const modeRequest = resourceSearchModeRequest(mode);
  const response = await fetchPreview(`${baseUrl()}/resource/search`, {
    method: "POST",
    headers: asJsonHeaders(),
    body: JSON.stringify({
      session_id: resolvedSessionId,
      workspace_id: workspaceId,
      query,
      top_k: request.topK ?? 10,
      ...(modeRequest.trustState ? { trust_state: modeRequest.trustState } : {}),
      ...(modeRequest.indexState ? { index_state: modeRequest.indexState } : {}),
    }),
  }, "resource_search");
  if (!response.ok) {
    await throwPreviewHttpFailure(response, "resource_search");
  }

  const payload = await readPreviewJson(response, "resource_search");
  const resourceSearch = normalizePreviewResourceSearchResult(
    payload,
    query,
    request.requestId,
  );
  return {
    sessionId: resolvedSessionId,
    message: { type: "state/patch", payload: { resourceSearch } },
  };
}

export async function sendBrowserPreviewMessage(
  request: SessionMessageRequest,
  sessionId?: string,
): Promise<{ sessionId: string; message: HostMessage }> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  if (isBrowserPreviewFixture()) {
    const fixture = fixturePreviewConversation(request, resolvedSessionId);
    return {
      sessionId: resolvedSessionId,
      message: {
        type: "state/patch",
        payload: fixture.patch,
      },
    };
  }
  const workspaceId = previewWorkspaceId();
  const requestPath = usesSessionMessageRoute(request) ? "/session/message" : "/turn";
  const providerOverride = buildPreviewProviderOverride();
  const response = await fetchPreview(`${baseUrl()}${requestPath}`, {
    method: "POST",
    headers: asJsonHeaders(),
    body: JSON.stringify({
      ...browserPreviewTurnPayload(request, resolvedSessionId, workspaceId),
      ...(providerOverride
        ? {
            provider: providerOverride.provider,
            api_key: providerOverride.apiKey,
          }
        : {}),
    }),
  }, "send");

  if (!response.ok) {
    await throwPreviewHttpFailure(response, "send");
  }

  const payload = await readPreviewJson(response, "send");
  return {
    sessionId: resolvedSessionId,
    message: {
      type: "state/patch",
      payload: mapTurnPayloadToPatch(payload),
    },
  };
}

export async function saveBrowserPreviewCoachSettings(
  request: CoachSettingsRequest,
  sessionId?: string,
): Promise<{ sessionId: string; message: HostMessage }> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const workspaceId = previewWorkspaceId();
  const response = await fetchPreview(`${baseUrl()}/memory/settings`, {
    method: "POST",
    headers: asJsonHeaders(),
    body: JSON.stringify({
      session_id: resolvedSessionId,
      workspace_id: workspaceId,
      response_language: request.responseLanguage,
      answer_mode: request.answerMode,
      teaching_style: request.teachingStyle,
      coach_defaults: request.coachDefaults
        ? {
            memory_scope: request.coachDefaults.memoryScope,
            working_set_mode: request.coachDefaults.workingSetMode,
            review_cadence: request.coachDefaults.reviewCadence,
            review_reminder_mode: request.coachDefaults.reviewReminderMode,
            workspace_memory_toggles: request.coachDefaults.workspaceMemoryToggles,
          }
        : undefined,
      follow_current_file: request.followCurrentFile,
      context_detail: request.contextDetail,
      include_current_file: request.includeCurrentFile,
      include_selection: request.includeSelection,
      include_diagnostics: request.includeDiagnostics,
      include_related_files: request.includeRelatedFiles,
    }),
  }, "settings");

  if (!response.ok) {
    await throwPreviewHttpFailure(response, "settings");
  }

  const snapshot = await readPreviewJson(response, "settings");
  return {
    sessionId: resolvedSessionId,
    message: {
      type: "state/patch",
      payload: mapSnapshotToBootstrap(snapshot),
    },
  };
}

async function saveBrowserPreviewProviderCore(
  draft: PreviewProviderDraftInput,
  sessionId: string | undefined,
  mode: "save" | "profile" | "template",
): Promise<PreviewProviderActionResult> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const current = buildPreviewProviderView(activePreviewProviderRecord());
  const protocol = normalizeProviderProtocol(draft.protocol ?? current?.protocol);
  if (!protocol) {
    throw new Error(
      previewText(
        "Select a chat protocol before saving. A gateway connection type is not a protocol, and unknown gateways are not assumed OpenAI-compatible.",
        "保存前请先选择聊天协议。网关连接类型不是协议，未知网关不会被默认成 OpenAI 兼容。",
      ),
    );
  }
  const name = draft.name?.trim() || current?.name?.trim() || PREVIEW_DEFAULT_PROVIDER_NAME;
  const baseUrl = normalizePreviewBaseUrl(draft.baseUrl ?? current?.baseUrl);
  const model = (draft.model ?? current?.model ?? "").trim();

  if (!baseUrl || !model) {
    throw new Error(
      previewText(
        "Add the service root and model before saving.",
        "请先填写服务地址并选择模型。",
      ),
    );
  }

  const allowedModels = draft.allowedModels ?? current?.allowedModels ?? [];
  const deniedModels = draft.deniedModels ?? current?.deniedModels ?? [];
  if (mode !== "profile") {
    // Profile saves preserve draft metadata even when the chosen model is
    // currently unavailable; the stricter policy gate stays on save-and-use.
    requireAllowedPreviewProviderModel(model, { allowedModels, deniedModels });
  }

  const profiles = normalizeProviderProfiles(current?.providerProfiles);
  const capabilities = normalizeCapabilityFlags(
    draft.capabilities ?? current?.capabilities,
    protocol,
  );
  const sameTransport =
    Boolean(current) &&
    current?.name.trim() === name &&
    normalizePreviewBaseUrl(current.baseUrl) === baseUrl &&
    normalizeProviderProtocol(current.protocol) === protocol;
  const profileId =
    mode === "save" && current?.profileId?.trim()
      ? current.profileId.trim()
      : uniquePreviewProfileId(name, profiles);
  const profileLabel = name;
  const profileMode = current?.profileMode ?? "direct";
  const credentialMode = draft.credentialMode ?? current?.credentialMode ?? "ui_proxy";
  const embeddingModel =
    typeof draft.embeddingModel === "string"
      ? draft.embeddingModel.trim() || undefined
      : current?.embeddingModel;
  const catalogSource = draft.catalogSource ?? current?.catalogSource ?? "provider_live";
  const cacheTtlSeconds =
    typeof draft.cacheTtlSeconds === "number" && Number.isFinite(draft.cacheTtlSeconds) && draft.cacheTtlSeconds > 0
      ? Math.round(draft.cacheTtlSeconds)
      : current?.cacheTtlSeconds;
  const requestDefaults = normalizePreviewRequestDefaults(
    { name, baseUrl, model },
    asRecord(draft.requestDefaults) ?? current?.requestDefaults ?? {},
  );
  const currentProviderKey = current
    ? previewProviderKey({
        profileId: current.profileId,
        name: current.name,
        baseUrl: current.baseUrl,
        protocol: current.protocol,
      })
    : undefined;

  if (mode === "save" && currentProviderKey && !sameTransport) {
    clearPreviewProviderRuntimeState(currentProviderKey);
  }

  const nextProviderKey = previewProviderKey({
    profileId,
    name,
    baseUrl,
    protocol,
  });
  const storedSecrets = previewProviderSecrets();
  const currentApiKey = currentProviderKey
    ? storedSecrets.apiKeysByProvider[currentProviderKey]?.trim()
    : undefined;
  const nextApiKey =
    draft.apiKey?.trim() || (mode === "save" || sameTransport ? currentApiKey : undefined);
  const cachedModels = storedSecrets.modelCachesByProvider[nextProviderKey]?.availableModels ?? [];
  const availableModels = Array.from(
    new Set(
      [
        model,
        ...(sameTransport ? current?.availableModels ?? [] : []),
        ...cachedModels,
      ].filter(Boolean),
    ),
  );
  const tokenState = resolveProviderModelTokenState(sameTransport ? current : undefined, model, {
    modelTokenLimits: draft.modelTokenLimits,
    hasModelTokenLimits: hasOwn(draft, "modelTokenLimits"),
    contextWindowTokens: draft.contextWindowTokens,
    maxOutputTokens: draft.maxOutputTokens,
    hasContextWindowTokens: hasOwn(draft, "contextWindowTokens"),
    hasMaxOutputTokens: hasOwn(draft, "maxOutputTokens"),
  });
  const profileRecord = buildPreviewProfileRecord({
    id: profileId,
    label: profileLabel,
    name,
    protocol,
    baseUrl,
    model,
    availableModels,
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    modelTokenLimits: tokenState.modelTokenLimits,
    capabilities,
    requestDefaults,
    mode: profileMode,
    credentialMode,
    modelAliases: current?.modelAliases,
    taskBindings: current?.taskBindings,
    allowedModels,
    deniedModels,
    embeddingModel,
    catalogSource,
    cacheTtlSeconds,
  });
  const nextProfiles = upsertPreviewProfile(profiles, profileRecord);
  // Carry over a compatible last test. Draft tests are stored under the
  // transport key (no profileId), so look there too and re-scope the result
  // onto the saved profile — mirroring the VS Code host, where the scoped
  // last-test store survives the draft -> saved transition.
  const carriedLastTest = (() => {
    const fromCurrent =
      sameTransport &&
      isCompatiblePreviewLastTestResult(
        { name, baseUrl, model, protocol },
        current?.lastTestResult,
      )
        ? current?.lastTestResult
        : undefined;
    const fromDraftKey =
      storedSecrets.lastTestsByProviderModel[
        previewProviderModelKey({ name, baseUrl, protocol, model })
      ];
    const compatible =
      fromCurrent ??
      (isCompatiblePreviewLastTestResult({ name, baseUrl, model, protocol }, fromDraftKey)
        ? fromDraftKey
        : undefined);
    if (!compatible) {
      return undefined;
    }
    return {
      ...compatible,
      workspaceId: previewWorkspaceId(),
      profileId,
    };
  })();
  if (carriedLastTest) {
    storePreviewProviderLastTest({ profileId, name, baseUrl, protocol, model }, carriedLastTest);
  }
  const nextRaw: Record<string, unknown> = {
    ...(current ?? {}),
    configured: true,
    name,
    baseUrl,
    model,
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    modelTokenLimits: tokenState.modelTokenLimits,
    protocol,
    protocolFamily: providerProtocolFamily(protocol),
    credentialMode,
    capabilities,
    requestDefaults,
    allowedModels,
    deniedModels,
    embeddingModel,
    catalogSource,
    cacheTtlSeconds,
    profileId,
    profileLabel,
    profileMode,
    profileCount: nextProfiles.length,
    providerProfiles: nextProfiles,
    providerDashboard: buildPreviewProviderDashboard(profileRecord, nextProfiles, current?.providerDashboard, undefined),
    availableModels,
    resolvedModel: model,
    modelListStatus:
      availableModels.length > 1 ? "ready" : sameTransport ? current?.modelListStatus ?? "idle" : "idle",
    modelListDetail: sameTransport ? current?.modelListDetail : undefined,
    cacheFetchedAt: sameTransport ? current?.cacheFetchedAt : undefined,
    cacheExpiresAt: sameTransport ? current?.cacheExpiresAt : undefined,
    cacheSource: sameTransport ? current?.cacheSource : undefined,
    modelErrorCategory: sameTransport ? current?.modelErrorCategory : undefined,
    modelStatusCode: sameTransport ? current?.modelStatusCode : undefined,
    modelRetryable: sameTransport ? current?.modelRetryable : undefined,
    lastTestResult: carriedLastTest,
  };
  if (draft.apiKey !== undefined) {
    storePreviewProviderApiKey(
      {
        profileId,
        name,
        baseUrl,
        protocol,
      },
      draft.apiKey,
    );
  } else if (nextApiKey) {
    storePreviewProviderApiKey(
      {
        profileId,
        name,
        baseUrl,
        protocol,
      },
      nextApiKey,
    );
  }

  const nextProvider = buildPreviewProviderView(nextRaw);
  if (!nextProvider) {
    throw new Error("Preview provider state could not be prepared.");
  }
  persistBrowserPreviewProviderConfig(nextProvider);

  const message =
    mode === "profile"
      ? previewText(
          `Saved '${profileLabel}' as a provider profile.`,
          "Saved provider profile.",
        )
      : mode === "template"
        ? previewText(
            "MiniMax template is ready. Add an API key before testing.",
            "已填好 MiniMax 模板。填好 API key 后再测试。",
          )
        : nextProvider.apiKeyConfigured
          ? previewText(
              "Provider saved. You can test it or send a coach turn now.",
              "\u63d0\u4f9b\u5546\u5df2\u4fdd\u5b58\u3002\u73b0\u5728\u53ef\u4ee5\u6d4b\u8bd5\u8fde\u63a5\u6216\u53d1\u9001\u6559\u7ec3\u6d88\u606f\u3002",
            )
          : previewText(
              "Provider saved. Add an API key before testing or sending.",
              "\u63d0\u4f9b\u5546\u5df2\u4fdd\u5b58\u3002\u8bf7\u5148\u6dfb\u52a0 API key\uff0c\u518d\u6d4b\u8bd5\u6216\u53d1\u9001\u3002",
            );

  return buildPreviewProviderResult(resolvedSessionId, nextProvider, {
    tone: "success",
    message,
  });
}

export async function saveBrowserPreviewProvider(
  draft: PreviewProviderDraftInput,
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  return saveBrowserPreviewProviderCore(draft, sessionId, "save");
}

export async function saveBrowserPreviewProviderProfile(
  draft: PreviewProviderDraftInput,
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  return saveBrowserPreviewProviderCore(draft, sessionId, "profile");
}

export async function useBrowserPreviewProviderTemplate(
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  return saveBrowserPreviewProviderCore(
    {
      name: "MiniMax",
      protocol: "openai_chat_completions_compatible",
      baseUrl: "https://api.minimaxi.com/v1",
      model: "MiniMax-M3",
    },
    sessionId,
    "template",
  );
}

export async function refreshBrowserPreviewProviderProfiles(
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const current = buildPreviewProviderView(activePreviewProviderRecord());
  if (!current) {
    return {
      sessionId: resolvedSessionId,
      messages: [
        {
          type: "operation/status",
          payload: {
            tone: "info",
            message: "No provider profiles are saved yet.",
          },
        },
      ],
    };
  }

  return buildPreviewProviderResult(resolvedSessionId, current, {
    tone: "success",
    message: previewText(
      "Provider profiles refreshed.",
      "已刷新 provider profiles。",
    ),
  });
}

export async function switchBrowserPreviewProviderProfile(
  profileId: string,
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const current = buildPreviewProviderView(activePreviewProviderRecord());
  if (!current?.configured) {
    throw new Error(
      previewText(
        "Save a provider before switching profiles.",
        "先保存 provider，再切换 profile。",
      ),
    );
  }

  const normalizedProfileId = profileId.trim();
  if (!normalizedProfileId) {
    throw new Error(previewText("Profile id is required.", "需要先提供 profile id。"));
  }

  const profiles = normalizeProviderProfiles(current.providerProfiles);
  const target = profiles.find((item) => asString(item.id) === normalizedProfileId);
  if (!target) {
    throw new Error(
      previewText(
        `Provider profile '${normalizedProfileId}' was not found.`,
        "Provider profile 不存在。",
      ),
    );
  }

  const protocol = normalizeProviderProtocol(asString(target.protocol) ?? current.protocol);
  if (!protocol) {
    throw new Error(
      previewText(
        "Select a chat protocol before switching this connection. Unknown gateways are not assumed OpenAI-compatible.",
        "切换前请先选择聊天协议。未知网关不会被默认成 OpenAI 兼容。",
      ),
    );
  }
  const name = asString(target.name) ?? asString(target.label) ?? current.name;
  const baseUrl = normalizePreviewBaseUrl(asString(target.baseUrl) ?? current.baseUrl);
  const model = asString(target.model) ?? current.model;
  const allowedModels = asStringArray(target.allowedModels) ?? [];
  const deniedModels = asStringArray(target.deniedModels) ?? [];
  requireAllowedPreviewProviderModel(model, { allowedModels, deniedModels });
  const capabilities = normalizeCapabilityFlags(target.capabilities ?? current.capabilities, protocol);
  const cache = previewProviderSecrets().modelCachesByProvider[
    previewProviderKey({
      profileId: normalizedProfileId,
      name,
      baseUrl,
      protocol,
    })
  ];
  const availableModels = Array.from(
    new Set(
      [
        model,
        ...(asStringArray(target.availableModels) ?? []),
        ...(cache?.availableModels ?? []),
      ].filter(Boolean),
    ),
  );
  const history = appendPreviewProfileHistory(
    current.profileHistory,
    current.profileId,
    normalizedProfileId,
    "preview_switch",
  );
  const tokenState = resolveProviderModelTokenState(
    {
      model,
      contextWindowTokens: asNumber(target.contextWindowTokens),
      maxOutputTokens: asNumber(target.maxOutputTokens),
      modelTokenLimits: target.modelTokenLimits as ProviderConfigView["modelTokenLimits"],
    },
    model,
    {
      modelTokenLimits: target.modelTokenLimits as ProviderConfigView["modelTokenLimits"],
      hasModelTokenLimits: hasOwn(target, "modelTokenLimits"),
      contextWindowTokens: asNumber(target.contextWindowTokens),
      maxOutputTokens: asNumber(target.maxOutputTokens),
      hasContextWindowTokens: hasOwn(target, "contextWindowTokens"),
      hasMaxOutputTokens: hasOwn(target, "maxOutputTokens"),
    },
  );
  const nextRaw: Record<string, unknown> = {
    ...(current ?? {}),
    configured: true,
    name,
    baseUrl,
    model,
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    modelTokenLimits: tokenState.modelTokenLimits,
    protocol,
    protocolFamily: providerProtocolFamily(protocol),
    credentialMode:
      asString(target.credentialMode) === "workspace_secret"
        ? "workspace_secret"
        : "ui_proxy",
    capabilities,
    requestDefaults: normalizePreviewRequestDefaults(
      { name, baseUrl, model },
      asRecord(target.requestDefaults) ?? current.requestDefaults ?? {},
    ),
    allowedModels,
    deniedModels,
    profileId: normalizedProfileId,
    profileLabel: asString(target.label) ?? name,
    profileMode: asString(target.mode) ?? "direct",
    profileCount: profiles.length,
    providerProfiles: profiles,
    providerDashboard: buildPreviewProviderDashboard(target, profiles, current.providerDashboard, undefined),
    profileHistory: history,
    availableModels,
    resolvedModel: cache?.resolvedModel ?? model,
    modelListStatus: cache?.modelListStatus ?? (availableModels.length > 1 ? "ready" : "idle"),
    modelListDetail: cache?.modelListDetail,
    cacheFetchedAt: cache?.cacheFetchedAt,
    cacheExpiresAt: cache?.cacheExpiresAt,
    cacheSource: cache?.cacheSource,
    modelErrorCategory: cache?.modelErrorCategory,
    modelStatusCode: cache?.modelStatusCode,
    modelRetryable: cache?.modelRetryable,
  };
  let nextProvider = buildPreviewProviderView(nextRaw);
  if (!nextProvider) {
    throw new Error("Preview provider profile switch failed.");
  }

  let tone: "success" | "info" = "success";
  let message = previewText(
    `Switched to '${nextProvider.profileLabel ?? nextProvider.name}'.`,
    `已切换到「${nextProvider.profileLabel ?? nextProvider.name}」。`,
  );
  const switchedTransport = buildPreviewProviderTransport(nextProvider);
  if (switchedTransport.apiKey?.trim()) {
    try {
      const refreshed = await refreshPreviewProviderModelState(nextProvider);
      nextProvider = refreshed.provider;
      message =
        refreshed.detail ??
        previewText(
          `Switched to '${nextProvider.profileLabel ?? nextProvider.name}' and refreshed models.`,
          `已切换到「${nextProvider.profileLabel ?? nextProvider.name}」，并刷新了模型列表。`,
        );
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      tone = "info";
      message = previewText(
        `Switched to '${nextProvider.profileLabel ?? nextProvider.name}', but live model refresh still needs attention. ${detail}`,
        `已切换到「${nextProvider.profileLabel ?? nextProvider.name}」，但 live model refresh 还需要处理。${detail}`,
      );
    }
  }

  return buildPreviewProviderResult(resolvedSessionId, nextProvider, {
    tone,
    message,
  });
}

export async function switchBrowserPreviewProviderModel(
  model: string,
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const current = buildPreviewProviderView(activePreviewProviderRecord());
  if (!current?.configured) {
    throw new Error(
      previewText(
        "Save a provider before switching models.",
        "先保存 provider，再切换模型。",
      ),
    );
  }

  const nextModel = model.trim();
  if (!nextModel) {
    throw new Error(
      previewText("Model is required.", "需要先提供 model。"),
    );
  }

  requireAllowedPreviewProviderModel(nextModel, current);

  const nextModelTokenState = resolveProviderModelTokenState(current, nextModel, {
    hasContextWindowTokens: false,
    hasMaxOutputTokens: false,
    hasModelTokenLimits: false,
  });
  const profiles = normalizeProviderProfiles(current.providerProfiles);
  const nextProfiles =
    current.profileId?.trim()
      ? upsertPreviewProfile(
          profiles,
          buildPreviewProfileRecord({
            id: current.profileId.trim(),
            label: current.profileLabel?.trim() || current.name,
            name: current.name,
            protocol: requirePreviewProviderProtocol(current.protocol),
            baseUrl: current.baseUrl,
            model: nextModel,
            availableModels: Array.from(
              new Set([nextModel, ...current.availableModels].filter(Boolean)),
            ),
            contextWindowTokens: nextModelTokenState.contextWindowTokens,
            maxOutputTokens: nextModelTokenState.maxOutputTokens,
            modelTokenLimits: nextModelTokenState.modelTokenLimits,
            capabilities: current.capabilities,
            requestDefaults: current.requestDefaults,
            mode: current.profileMode,
            credentialMode: current.credentialMode,
          }),
        )
      : profiles;
  const nextRaw: Record<string, unknown> = {
    ...(current ?? {}),
    model: nextModel,
    contextWindowTokens: nextModelTokenState.contextWindowTokens,
    maxOutputTokens: nextModelTokenState.maxOutputTokens,
    modelTokenLimits: nextModelTokenState.modelTokenLimits,
    resolvedModel: nextModel,
    availableModels: Array.from(new Set([nextModel, ...current.availableModels].filter(Boolean))),
    providerProfiles: nextProfiles,
    profileCount: nextProfiles.length > 0 ? nextProfiles.length : current.profileCount,
    lastTestResult:
      isCompatiblePreviewLastTestResult(
        {
          name: current.name,
          baseUrl: current.baseUrl,
          model: nextModel,
          protocol: current.protocol,
        },
        current.lastTestResult,
      )
        ? current.lastTestResult
        : undefined,
  };
  const nextProvider = buildPreviewProviderView(nextRaw);
  if (!nextProvider) {
    throw new Error("Preview model switch failed.");
  }

  return buildPreviewProviderResult(resolvedSessionId, nextProvider, {
    tone: "success",
    message: previewText(
      `Using model '${nextModel}'.`,
      `已切换到模型「${nextModel}」。`,
    ),
  });
}

type PreviewProviderModelRefresh = {
  ok: boolean;
  detail?: string;
  listedModels?: string[];
  resolvedModel?: string;
  modelTokenLimits?: ProviderConfigView["modelTokenLimits"];
  cacheSource?: ProviderConfigView["cacheSource"];
  modelErrorCategory?: string;
  modelStatusCode?: number;
  modelRetryable?: boolean;
};

function previewFixtureModelOptions(current: ProviderConfigView): string[] {
  const configuredModels = [
    current.model,
    ...(current.catalogModels ?? []),
    ...current.availableModels,
  ]
    .map((model) => model.trim())
    .filter(Boolean);

  return Array.from(
    new Set(configuredModels.length > 0 ? configuredModels : PREVIEW_FIXTURE_MODEL_OPTIONS),
  );
}

function completePreviewProviderModelRefresh(
  current: ProviderConfigView,
  refresh: PreviewProviderModelRefresh,
): {
  ok: boolean;
  detail?: string;
  provider: ProviderConfigView;
} {
  const resolvedModel = refresh.resolvedModel ?? current.model;
  requireAllowedPreviewProviderModel(resolvedModel, current);
  const discoveredModelTokenLimits = refresh.modelTokenLimits;
  const availableModels = Array.from(
    new Set([
      resolvedModel,
      current.model,
      ...current.availableModels,
      ...(refresh.listedModels ?? []),
    ].filter(Boolean)),
  );
  const cacheFetchedAt = new Date().toISOString();
  const cacheExpiresAt = new Date(Date.now() + PREVIEW_PROVIDER_MODEL_CACHE_TTL_MS).toISOString();
  const cache: PreviewProviderModelCache = {
    availableModels,
    resolvedModel,
    modelTokenLimits: discoveredModelTokenLimits,
    modelListStatus: refresh.ok ? "ready" : "error",
    modelListDetail: refresh.detail,
    cacheFetchedAt,
    cacheExpiresAt,
    cacheSource: refresh.ok ? refresh.cacheSource : undefined,
    modelErrorCategory: refresh.modelErrorCategory,
    modelStatusCode: refresh.modelStatusCode,
    modelRetryable: refresh.modelRetryable,
  };
  storePreviewProviderModelCache(current, cache);
  const resolvedProviderState = applyProviderModelCatalog(current, {
    resolvedModel,
    modelTokenLimits: discoveredModelTokenLimits,
  });
  const profiles = normalizeProviderProfiles(current.providerProfiles);
  const nextProfiles =
    current.profileId?.trim()
      ? upsertPreviewProfile(
          profiles,
          buildPreviewProfileRecord({
            id: current.profileId.trim(),
            label: current.profileLabel?.trim() || current.name,
            name: current.name,
            protocol: requirePreviewProviderProtocol(current.protocol),
            baseUrl: current.baseUrl,
            model: resolvedModel,
            availableModels,
            contextWindowTokens: resolvedProviderState.contextWindowTokens,
            maxOutputTokens: resolvedProviderState.maxOutputTokens,
            modelTokenLimits: resolvedProviderState.modelTokenLimits,
            capabilities: current.capabilities,
            requestDefaults: current.requestDefaults,
            mode: current.profileMode,
            credentialMode: current.credentialMode,
          }),
        )
      : profiles;
  const nextRaw: Record<string, unknown> = {
    ...(current ?? {}),
    model: resolvedModel,
    contextWindowTokens: resolvedProviderState.contextWindowTokens,
    maxOutputTokens: resolvedProviderState.maxOutputTokens,
    modelTokenLimits: resolvedProviderState.modelTokenLimits,
    resolvedModel,
    availableModels,
    providerProfiles: nextProfiles,
    profileCount: nextProfiles.length > 0 ? nextProfiles.length : current.profileCount,
    modelListStatus: cache.modelListStatus,
    modelListDetail: cache.modelListDetail,
    cacheFetchedAt,
    cacheExpiresAt,
    cacheSource: cache.cacheSource,
    modelErrorCategory: cache.modelErrorCategory,
    modelStatusCode: cache.modelStatusCode,
    modelRetryable: cache.modelRetryable,
  };
  const nextProvider = buildPreviewProviderView(nextRaw);
  if (!nextProvider) {
    throw new Error("Preview model refresh could not update provider state.");
  }

  return {
    ok: refresh.ok,
    detail: refresh.detail,
    provider: nextProvider,
  };
}

async function refreshPreviewProviderModelState(
  current: ProviderConfigView,
  apiKeyOverride?: string,
): Promise<{
  ok: boolean;
  detail?: string;
  provider: ProviderConfigView;
}> {
  if (isBrowserPreviewFixture()) {
    return completePreviewProviderModelRefresh(current, {
      ok: true,
      detail: previewText(
        "Browser preview refreshed a local model list. Run a real connection test in VS Code before coaching.",
        "浏览器预览已刷新本地模型列表；开始对话前请在 VS Code 中完成真实连接测试。",
      ),
      listedModels: previewFixtureModelOptions(current),
      resolvedModel: current.model.trim() || undefined,
      cacheSource: "cache",
    });
  }

  const transport = buildPreviewProviderTransport(current, apiKeyOverride);
  if (!transport.apiKey?.trim()) {
    throw new Error(
      previewText(
        "Add an API key before refreshing models.",
        "先补一个 API key，再刷新模型列表。",
      ),
    );
  }

  const response = await fetchPreview(`${baseUrl()}/provider/models`, {
    method: "POST",
    headers: asJsonHeaders(),
    body: JSON.stringify({
      provider: transport.provider,
      api_key: transport.apiKey,
    }),
  }, "models");
  if (!response.ok) {
    await throwPreviewHttpFailure(response, "models");
  }

  const payload = asRecord(await readPreviewJson(response, "models")) ?? {};
  const ok = asBoolean(payload.ok) ?? false;
  const errorCategory = normalizePreviewProviderErrorCategory(payload.error_category);
  return completePreviewProviderModelRefresh(current, {
    ok,
    detail: previewProviderResultDetail("models", ok, errorCategory),
    listedModels: asStringArray(payload.available_models) ?? [],
    resolvedModel: asString(payload.resolved_model) ?? current.model,
    modelTokenLimits: normalizeProviderModelTokenLimits(
      payload.model_token_limits ?? payload.modelTokenLimits,
    ) as ProviderConfigView["modelTokenLimits"] | undefined,
    cacheSource: "live",
    modelErrorCategory: errorCategory,
    modelStatusCode: asNumber(payload.status_code),
    modelRetryable: asBoolean(payload.retryable),
  });
}

export async function refreshBrowserPreviewProviderModels(
  draftOrSessionId?: PreviewProviderDraftInput | string,
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  const draft = typeof draftOrSessionId === "string" ? undefined : draftOrSessionId;
  const resolvedSessionId = await ensureBrowserPreviewSession(
    typeof draftOrSessionId === "string" ? draftOrSessionId : sessionId,
  );
  const providerOverride = buildPreviewProviderOverride();
  if (draft) {
    const current = providerOverride?.view ?? buildPreviewProviderView(activePreviewProviderRecord());
    const draftProvider = buildPreviewDraftProvider(draft, current);
    const draftApiKey =
      draft.apiKey?.trim() ||
      (hasSamePreviewCredentialTransport(providerOverride?.view, draftProvider)
        ? providerOverride?.apiKey
        : undefined);
    if (!draftProvider.baseUrl) {
      throw new Error(previewText("Add a service root before finding models.", "先填写服务根地址，再查找模型。"));
    }
    if (!draftApiKey?.trim()) {
      throw new Error(previewText("Add an API key before finding models.", "先填写 API key，再查找模型。"));
    }
    const refreshed = await refreshPreviewProviderModelState(
      draftProvider,
      draftApiKey,
    );
    return buildPreviewDraftModelResult(resolvedSessionId, current, refreshed);
  }
  if (!providerOverride?.view.configured) {
    throw new Error(
      previewText(
        "Save a provider before refreshing models.",
        "先保存 provider，再刷新模型列表。",
      ),
    );
  }

  const refreshed = await refreshPreviewProviderModelState(providerOverride.view);

  return buildPreviewProviderResult(resolvedSessionId, refreshed.provider, {
    tone: refreshed.ok ? "success" : "error",
    message:
      refreshed.detail ??
      previewText("Model refresh completed.", "模型列表已刷新。"),
  });
}

type PreviewProviderTest = {
  ok: boolean;
  status?: string;
  detail?: string;
  diagnostics?: string[];
  errorCategory?: string;
  retryable?: boolean;
  statusCode?: number;
  capability_evidence?: unknown;
  capabilityEvidence?: unknown;
  tools_ready?: boolean;
  toolsReady?: boolean;
  tool_probe_status?: unknown;
  toolProbeStatus?: unknown;
  streaming_ready?: boolean;
  streamingReady?: boolean;
  stream_probe_status?: unknown;
  streamProbeStatus?: unknown;
};

function completePreviewProviderTest(
  current: ProviderConfigView,
  previewTest: PreviewProviderTest,
  persist = true,
): { detail: string; provider: ProviderConfigView; ok: boolean } {
  const errorCategory = normalizePreviewProviderErrorCategory(previewTest.errorCategory);
  const detail =
    previewTest.detail ??
    previewText("Provider test completed.", "provider 测试已完成。");
  const capabilityTruth = normalizeProviderCapabilityTruth(previewTest);
  const toolsEvidence = capabilityTruth.capabilityEvidence.find(
    (entry) => entry.name.trim().toLowerCase() === "tools",
  );
  const streamingEvidence = capabilityTruth.capabilityEvidence.find((entry) => {
    const name = entry.name.trim().toLowerCase();
    return name === "streaming" || name === "stream";
  });
  const capabilities = {
    ...current.capabilities,
    ...(toolsEvidence?.state === "verified" && toolsEvidence.observed === true
      ? { tools: true }
      : toolsEvidence?.state === "unsupported" || toolsEvidence?.state === "disabled"
        ? { tools: false }
        : {}),
    ...(streamingEvidence?.state === "verified" && streamingEvidence.observed === true
      ? { streaming: true }
      : streamingEvidence?.state === "unsupported" || streamingEvidence?.state === "disabled"
        ? { streaming: false }
        : {}),
  };
  const lastTestResult: ProviderLastTestResult = {
    ok: previewTest.ok,
    status: previewTest.ok ? "connected" : "failed",
    detail,
    checkedAt: new Date().toISOString(),
    // Scope the result exactly like the VS Code host does
    // (providerWebviewCommands.ts stamps workspaceId + profileId), otherwise
    // selectScopedSettingsLastTest rejects it and the UI shows "Never tested".
    workspaceId: previewWorkspaceId(),
    profileId: current.profileId,
    providerName: current.name,
    baseUrl: current.baseUrl,
    model: current.model,
    protocol: normalizeProviderProtocol(current.protocol),
    protocolFamily: providerProtocolFamily(normalizeProviderProtocol(current.protocol)),
    errorCategory,
    retryable: previewTest.retryable,
    statusCode: previewTest.statusCode,
    responseLanguage: resolvePreviewLanguage(),
    capabilityEvidence: capabilityTruth.capabilityEvidence,
    toolsReady: capabilityTruth.toolsReady,
    toolProbeStatus: capabilityTruth.toolProbeStatus,
    streamingReady: capabilityTruth.streamingReady,
    streamProbeStatus: capabilityTruth.streamProbeStatus,
  };
  if (persist) {
    storePreviewProviderLastTest(current, lastTestResult);
  }

  const nextProvider = buildPreviewProviderView({
    ...(current ?? {}),
    capabilities,
    lastTestResult,
    diagnostics: previewTest.ok ? current.diagnostics : [detail],
  });
  if (!nextProvider) {
    throw new Error("Preview provider test could not update provider state.");
  }

  return { detail, provider: nextProvider, ok: lastTestResult.ok };
}

export async function testBrowserPreviewProvider(
  draftOrSessionId?: PreviewProviderDraftInput | string,
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  const draft = typeof draftOrSessionId === "string" ? undefined : draftOrSessionId;
  const resolvedSessionId = await ensureBrowserPreviewSession(
    typeof draftOrSessionId === "string" ? draftOrSessionId : sessionId,
  );
  const providerOverride = buildPreviewProviderOverride();
  if (draft) {
    const current = buildPreviewDraftProvider(draft, providerOverride?.view);
    const apiKey =
      draft.apiKey?.trim() ||
      (hasSamePreviewCredentialTransport(providerOverride?.view, current)
        ? providerOverride?.apiKey
        : undefined);
    if (!current.baseUrl || !current.model) {
      throw new Error(previewText("Choose a model before testing this draft.", "先选择模型，再测试这组草稿连接。"));
    }
    if (!apiKey?.trim()) {
      throw new Error(previewText("Add an API key before testing this draft.", "先填写 API key，再测试这组草稿连接。"));
    }
    if (isBrowserPreviewFixture()) {
      return buildPreviewProviderStatusResult(resolvedSessionId, {
        tone: "info",
        message: previewText(
          "Browser preview cannot verify this draft connection. Test it in VS Code; the draft was not saved.",
          "浏览器预览无法验证这组草稿连接；请在 VS Code 中测试，草稿未保存。",
        ),
      });
    }
    const transport = buildPreviewProviderTransport(current, apiKey);
    const response = await fetchPreview(`${baseUrl()}/provider/test`, {
      method: "POST",
      headers: asJsonHeaders(),
      body: JSON.stringify({
        provider: transport.provider,
        api_key: transport.apiKey,
        response_language: resolvePreviewLanguage(),
      }),
    }, "provider_test");
    if (!response.ok) {
      await throwPreviewHttpFailure(response, "provider_test");
    }
    const payload = asRecord(await readPreviewJson(response, "provider_test")) ?? {};
    const ok = asBoolean(payload.ok) ?? false;
    const errorCategory = normalizePreviewProviderErrorCategory(payload.error_category);
    // Persist draft test results just like the VS Code host does
    // (saveLastTestResult runs for drafts too). saveBrowserPreviewProviderCore
    // later migrates this entry onto the saved profile key.
    const completed = completePreviewProviderTest(current, {
      ok,
      detail: previewProviderResultDetail("test", ok, errorCategory),
      errorCategory,
      retryable: asBoolean(payload.retryable),
      statusCode: asNumber(payload.status_code),
      capability_evidence: payload.capability_evidence ?? payload.capabilityEvidence,
      tools_ready: asBoolean(payload.tools_ready) ?? asBoolean(payload.toolsReady),
      tool_probe_status: payload.tool_probe_status ?? payload.toolProbeStatus,
      streaming_ready: asBoolean(payload.streaming_ready) ?? asBoolean(payload.streamingReady),
      stream_probe_status: payload.stream_probe_status ?? payload.streamProbeStatus,
    }, true);
    const stateProvider = providerOverride?.view ?? current;
    return {
      sessionId: resolvedSessionId,
      messages: [
        {
          type: "state/patch",
          payload: {
            providerConfig: {
              ...stateProvider,
              lastTestResult: completed.provider.lastTestResult,
              capabilities: completed.provider.capabilities,
            },
          },
        },
        {
          type: "operation/status",
          payload: {
            tone: completed.ok ? "success" : "error",
            message: completed.detail,
          },
        },
      ],
    };
  }
  if (!providerOverride?.view.configured) {
    throw new Error(
      previewText(
        "Save a provider before testing it.",
        "先保存 provider，再测试连接。",
      ),
    );
  }

  const current = providerOverride.view;
  if (isBrowserPreviewFixture()) {
    return buildPreviewProviderStatusResult(resolvedSessionId, {
      tone: "info",
      message: previewText(
        "Browser preview cannot verify a real connection. Test it in VS Code before coaching.",
        "浏览器预览无法验证真实连接；开始对话前请在 VS Code 中测试。",
      ),
    });
  }

  const response = await fetchPreview(`${baseUrl()}/provider/test`, {
    method: "POST",
    headers: asJsonHeaders(),
    body: JSON.stringify({
      provider: providerOverride.provider,
      api_key: providerOverride.apiKey,
      response_language: resolvePreviewLanguage(),
    }),
  }, "provider_test");
  if (!response.ok) {
    await throwPreviewHttpFailure(response, "provider_test");
  }

  const payload = asRecord(await readPreviewJson(response, "provider_test")) ?? {};
  const ok = asBoolean(payload.ok) ?? false;
  const errorCategory = normalizePreviewProviderErrorCategory(payload.error_category);
  const completed = completePreviewProviderTest(current, {
    ok,
    detail: previewProviderResultDetail("test", ok, errorCategory),
    errorCategory,
    retryable: asBoolean(payload.retryable),
    statusCode: asNumber(payload.status_code),
    capability_evidence: payload.capability_evidence ?? payload.capabilityEvidence,
    tools_ready: asBoolean(payload.tools_ready) ?? asBoolean(payload.toolsReady),
    tool_probe_status: payload.tool_probe_status ?? payload.toolProbeStatus,
    streaming_ready: asBoolean(payload.streaming_ready) ?? asBoolean(payload.streamingReady),
    stream_probe_status: payload.stream_probe_status ?? payload.streamProbeStatus,
  });

  return buildPreviewProviderResult(resolvedSessionId, completed.provider, {
    tone: completed.ok ? "success" : "error",
    message: completed.detail,
  });
}

export async function clearBrowserPreviewProvider(
  sessionId?: string,
): Promise<PreviewProviderActionResult> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  clearPreviewProviderSecrets();

  const providerConfig: ProviderConfigView = {
    configured: false,
    name: "",
    baseUrl: "",
    model: "",
    apiKeyConfigured: false,
    capabilities: previewProtocolCapabilityDefaults("openai_chat_completions_compatible"),
    availableModels: [],
    resolvedModel: undefined,
    modelListStatus: "idle",
    modelListDetail: undefined,
    cacheFetchedAt: undefined,
    cacheExpiresAt: undefined,
    cacheSource: undefined,
    modelErrorCategory: undefined,
    modelStatusCode: undefined,
    modelRetryable: undefined,
    protocol: "openai_chat_completions_compatible",
    protocolFamily: providerProtocolFamily("openai_chat_completions_compatible"),
    credentialMode: "ui_proxy",
    providerProfiles: [],
    providerDashboard: buildPreviewProviderDashboard(undefined, [], undefined, []),
  };

  return buildPreviewProviderResult(resolvedSessionId, providerConfig, {
    tone: "success",
    message: previewText(
      "Cleared the preview provider state.",
      "",
    ),
  });
}

function classifyPreviewStreamFailure(detail: string, statusCode?: number): NonNullable<StreamErrorEvent["category"]> {
  return classifyPreviewRequestFailure(detail, statusCode, "send");
}

function safePreviewStreamFailure(detail: string, statusCode?: number): StreamErrorEvent {
  const category = classifyPreviewStreamFailure(detail, statusCode);
  return {
    error: category,
    category,
    statusCode,
    retryable: category === "rate_limit" || category === "timeout" || category === "network" || category === "provider_error",
  };
}

function previewStreamStatusMessage(
  phase: string | undefined,
  responseLanguage: string | undefined,
): string | undefined {
  const messages = responseLanguage === "zh-CN"
    ? {
        preparing_context: "\u6b63\u5728\u51c6\u5907\u5f53\u524d\u5de5\u4f5c\u533a\u548c\u5b66\u4e60\u4e0a\u4e0b\u6587\u3002",
        requesting_model: "\u6b63\u5728\u5411\u5df2\u914d\u7f6e\u7684\u6a21\u578b\u8bf7\u6c42\u56de\u590d\u3002",
      }
    : {
        preparing_context: "Preparing the current workspace and learning context.",
        requesting_model: "Requesting a reply from the configured model.",
      };
  return phase === "preparing_context" || phase === "requesting_model"
    ? messages[phase]
    : undefined;
}

export async function streamBrowserPreviewMessage(
  request: SessionMessageRequest,
  sessionId: string,
  callbacks: {
    onStart: (message: HostMessage) => void;
    onChunk: (message: HostMessage) => void;
    onComplete: (message: HostMessage, nextSessionId: string) => void;
    onError: (message: HostMessage) => void;
    onCancelled?: (message: HostMessage) => void;
  },
): Promise<void> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const messageId = `stream-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const controller = new AbortController();
  registerBrowserPreviewStream(messageId, controller);

  try {
    callbacks.onStart({ type: "stream/start", payload: { messageId } });

  const emitStreamError = (detail: string, statusCode?: number): void => {
    callbacks.onError({
      type: "stream/error",
      payload: {
        ...safePreviewStreamFailure(detail, statusCode),
        messageId,
      },
    });
  };
  const emitStreamCancelled = (): void => {
    callbacks.onCancelled?.({ type: "stream/cancelled", payload: { messageId } });
  };

  if (isBrowserPreviewFixture()) {
    if (controller.signal.aborted) {
      emitStreamCancelled();
      return;
    }
    const fixture = fixturePreviewConversation(request, resolvedSessionId);
    const splitAt = Math.max(1, Math.ceil(fixture.reply.body.length / 2));
    callbacks.onChunk({
      type: "stream/chunk",
      payload: { messageId, chunk: fixture.reply.body.slice(0, splitAt) },
    });
    if (controller.signal.aborted) {
      emitStreamCancelled();
      return;
    }
    callbacks.onChunk({
      type: "stream/chunk",
      payload: { messageId, chunk: fixture.reply.body.slice(splitAt) },
    });
    callbacks.onComplete(
      {
        type: "stream/complete",
        payload: {
          messageId,
          tokens: fixture.reply.body.length,
          summary: fixture.reply.summary,
          nextStep: fixture.reply.nextStep,
        },
      },
      resolvedSessionId,
    );
    callbacks.onComplete(
      {
        type: "state/patch",
        payload: fixture.patch,
      },
      resolvedSessionId,
    );
    return;
  }

  const workspaceId = previewWorkspaceId();

  const requestPath = usesSessionMessageRoute(request)
    ? "/session/message/stream"
    : "/turn/stream";
  const providerOverride = buildPreviewProviderOverride();
  let response: Response;
  try {
    await ensureBrowserPreviewSidecar();
    registerBrowserPreviewStream(messageId, controller, {
      sidecarBaseUrl: baseUrl(),
      streamId: messageId,
    });
    response = await fetch(`${baseUrl()}${requestPath}`, {
      method: "POST",
      headers: {
        ...asJsonHeaders(),
        accept: "text/event-stream",
      },
      body: JSON.stringify({
        ...browserPreviewTurnPayload(request, resolvedSessionId, workspaceId),
        stream: true,
        stream_id: messageId,
        ...(providerOverride
          ? {
              provider: providerOverride.provider,
              api_key: providerOverride.apiKey,
            }
        : {}),
      }),
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      emitStreamCancelled();
      return;
    }
    emitStreamError(previewErrorDetail(error));
    return;
  }

  if (!response.ok || !response.body) {
    if (controller.signal.aborted) {
      emitStreamCancelled();
      return;
    }
    let detail = "";
    try {
      detail = await response.text();
    } catch {
      // A safe stream failure still reaches the user when no body can be read.
    }
    emitStreamError(detail, response.status);
    return;
  }

  const reader = response.body.getReader();
  attachBrowserPreviewStreamReader(messageId, reader);
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let pendingCarriageReturn = false;
  let sawCompletion = false;
  let streamFailed = false;

  const emitMessageBlock = (block: string) => {
    if (!block.trim()) {
      return;
    }
    let eventName = "message";
    let eventData = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        eventData = line.slice(5).trimStart();
      }
    }

    if (!eventData) {
      return;
    }

    if (streamFailed || sawCompletion) {
      return;
    }

    if (eventName === "complete") {
      let parsed: { tokens?: number; response?: unknown };
      try {
        parsed = JSON.parse(eventData) as { tokens?: number; response?: unknown };
      } catch {
        streamFailed = true;
        emitStreamError("malformed response");
        return;
      }
      sawCompletion = true;
      const responseRecord =
        parsed.response && typeof parsed.response === "object"
          ? (parsed.response as Record<string, unknown>)
          : undefined;
      const agentRecord =
        responseRecord?.agent && typeof responseRecord.agent === "object"
          ? (responseRecord.agent as Record<string, unknown>)
          : responseRecord?.agent_meta && typeof responseRecord.agent_meta === "object"
            ? (responseRecord.agent_meta as Record<string, unknown>)
            : undefined;
      const rawToolEvents = Array.isArray(agentRecord?.tool_events) ? agentRecord.tool_events : [];
      const toolCount = rawToolEvents.filter((item) => {
        return Boolean(
          item && typeof item === "object" && (item as Record<string, unknown>).type === "tool_call",
        );
      }).length;
      callbacks.onComplete(
        {
          type: "stream/complete",
          payload: {
            messageId,
            tokens: parsed.tokens ?? 0,
            agentic: Boolean(agentRecord?.agentic),
            summary:
              typeof agentRecord?.summary === "string" && agentRecord.summary.trim().length > 0
                ? agentRecord.summary.trim()
                : undefined,
            nextStep:
              typeof agentRecord?.next_step === "string" && agentRecord.next_step.trim().length > 0
                ? agentRecord.next_step.trim()
                : typeof agentRecord?.nextStep === "string" && agentRecord.nextStep.trim().length > 0
                  ? agentRecord.nextStep.trim()
                  : undefined,
            stopReason:
              typeof agentRecord?.stop_reason === "string" && agentRecord.stop_reason.trim().length > 0
                ? agentRecord.stop_reason.trim()
                : typeof agentRecord?.stopReason === "string" && agentRecord.stopReason.trim().length > 0
                  ? agentRecord.stopReason.trim()
                  : undefined,
            toolCount: toolCount > 0 ? toolCount : undefined,
          } satisfies StreamCompleteEvent,
        },
        resolvedSessionId,
      );
      if (parsed.response) {
        callbacks.onComplete(
          {
            type: "state/patch",
            payload: mapTurnPayloadToPatch(parsed.response),
          },
          resolvedSessionId,
        );
      }
      return;
    }

    if (eventName === "tool_call") {
      try {
        const parsed = JSON.parse(eventData) as {
          id?: string;
          name?: string;
          arguments?: unknown;
          step?: number;
        };
        callbacks.onChunk({
          type: "stream/tool_call",
          payload: {
            messageId,
            id: typeof parsed.id === "string" ? parsed.id : "",
            name: typeof parsed.name === "string" ? parsed.name : "",
            arguments: parsed.arguments,
            step: typeof parsed.step === "number" ? parsed.step : undefined,
          },
        });
      } catch {
        // Best effort: ignore malformed agent events.
      }
      return;
    }

    if (eventName === "tool_result") {
      try {
        const parsed = JSON.parse(eventData) as {
          id?: string;
          name?: string;
          ok?: boolean;
          result?: unknown;
          step?: number;
        };
        callbacks.onChunk({
          type: "stream/tool_result",
          payload: {
            messageId,
            id: typeof parsed.id === "string" ? parsed.id : "",
            name: typeof parsed.name === "string" ? parsed.name : "",
            ok: Boolean(parsed.ok),
            result: parsed.result,
            step: typeof parsed.step === "number" ? parsed.step : undefined,
          },
        });
      } catch {
        // ignore
      }
      return;
    }

    if (eventName === "step") {
      try {
        const parsed = JSON.parse(eventData) as {
          index?: number;
          stop_reason?: string | null;
        };
        callbacks.onChunk({
          type: "stream/step",
          payload: {
            messageId,
            index: typeof parsed.index === "number" ? parsed.index : 0,
            stop_reason: parsed.stop_reason ?? undefined,
          },
        });
      } catch {
        // ignore
      }
      return;
    }

    if (eventName === "status") {
      try {
        const parsed = JSON.parse(eventData) as { phase?: unknown };
        const phase = typeof parsed.phase === "string" ? parsed.phase : undefined;
        const message = previewStreamStatusMessage(phase, request.responseLanguage);
        if (message) {
          callbacks.onChunk({
            type: "operation/status",
            payload: { tone: "info", message },
          });
        }
      } catch {
        // Ignore malformed status events because they never represent user-visible reply text.
      }
      return;
    }

    if (eventName === "error") {
      streamFailed = true;
      emitStreamError(eventData);
      return;
    }

    let parsed: { chunk?: string };
    try {
      parsed = JSON.parse(eventData) as { chunk?: string };
    } catch {
      streamFailed = true;
      emitStreamError("malformed response");
      return;
    }
    callbacks.onChunk({
      type: "stream/chunk",
      payload: { messageId, chunk: parsed.chunk ?? "" },
    });
  };

  const appendSseText = (text: string, final = false) => {
    if (pendingCarriageReturn) {
      // A CRLF boundary can span two ReadableStream chunks.
      if (text.startsWith("\n")) {
        text = text.slice(1);
      }
      buffer += "\n";
      pendingCarriageReturn = false;
    }

    if (!final && text.endsWith("\r")) {
      text = text.slice(0, -1);
      pendingCarriageReturn = true;
    }

    buffer += text.replace(/\r\n?/g, "\n");
  };

  const drainSseBlocks = () => {
    let markerIndex = buffer.indexOf("\n\n");
    while (markerIndex !== -1) {
      const block = buffer.slice(0, markerIndex);
      buffer = buffer.slice(markerIndex + 2);
      emitMessageBlock(block);
      markerIndex = buffer.indexOf("\n\n");
    }
  };

  while (true) {
    let result: ReadableStreamReadResult<Uint8Array>;
    try {
      result = await reader.read();
    } catch (error) {
      if (controller.signal.aborted) {
        emitStreamCancelled();
        return;
      }
      if (!streamFailed) {
        streamFailed = true;
        emitStreamError(previewErrorDetail(error) || "stream read failed");
      }
      return;
    }
    const { done, value } = result;
    if (done) {
      break;
    }
    appendSseText(decoder.decode(value, { stream: true }));
    drainSseBlocks();
    if (streamFailed || sawCompletion) {
      return;
    }
  }

  if (streamFailed || sawCompletion) {
    return;
  }

  if (controller.signal.aborted) {
    emitStreamCancelled();
    return;
  }

  appendSseText(decoder.decode(), true);
  if (pendingCarriageReturn) {
    buffer += "\n";
    pendingCarriageReturn = false;
  }
  drainSseBlocks();
  if (buffer.trim()) {
    emitMessageBlock(buffer);
  }
  if (!streamFailed && !sawCompletion) {
    streamFailed = true;
    emitStreamError("malformed response: stream ended before completion");
  }
  } finally {
    releaseBrowserPreviewStream(messageId);
  }
}

function usesSessionMessageRoute(request: SessionMessageRequest): boolean {
  return resolveBrowserPreviewTurnIntent(request) === "coach" &&
    (!request.activeView || request.activeView === "coach");
}

function browserPreviewTurnPayload(
  request: SessionMessageRequest,
  sessionId: string,
  workspaceId: string,
): Record<string, unknown> {
  return {
    session_id: sessionId,
    workspace_id: workspaceId,
    // Both stream routes require this field; keep it in the shared transport payload.
    message: request.text,
    intent: resolveBrowserPreviewTurnIntent(request),
    goals: request.goals ?? [],
    formal_plan_mutation: request.formalPlanMutation === true,
    active_view: request.activeView,
    resource_ids: request.resourceIds ?? [],
    resource_composer_intent: resourceComposerIntentPayload(request),
    include_current_file: request.includeCurrentFile,
    include_selection: request.includeSelection,
    include_diagnostics: request.includeDiagnostics,
    include_related_files: request.includeRelatedFiles,
    context_detail: request.contextDetail,
    response_language: request.responseLanguage,
    answer_mode: request.answerMode,
    teaching_style: request.teachingStyle,
    coach_defaults: request.coachDefaults,
    attachments: request.attachments,
    use_agent_loop: request.useAgentLoop,
    request_id: request.requestId,
    plan_runtime_recovery: request.planRuntimeRecovery,
  };
}

function resolveBrowserPreviewTurnIntent(
  request: SessionMessageRequest,
): NonNullable<SessionMessageRequest["intent"]> {
  if (request.intent) {
    return request.intent;
  }
  return request.activeView === "resources" && request.resourceComposerIntent
    ? "resources"
    : "coach";
}

function resourceComposerIntentPayload(request: SessionMessageRequest):
  | { mode: "locate" | "download" | "organize" | "cards"; resource_ids: string[] }
  | undefined {
  const intent = request.resourceComposerIntent;
  if (!intent) {
    return undefined;
  }
  return {
    mode: intent.mode,
    resource_ids: intent.resourceIds ?? [],
  };
}

function fixtureUploadTitle(value: string): string {
  const segments = value
    .trim()
    .replace(/\\/g, "/")
    .split("/")
    .filter((segment) => segment && segment !== "." && segment !== "..");
  return segments[segments.length - 1] ?? "Imported resource";
}

function fixtureUploadId(title: string, index: number, usedIds: Set<string>): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "resource";
  const base = `preview-resource-${slug}-${index + 1}`;
  let candidate = base;
  let duplicate = 2;
  while (usedIds.has(candidate)) {
    candidate = `${base}-${duplicate}`;
    duplicate += 1;
  }
  usedIds.add(candidate);
  return candidate;
}

function fixtureUploadedResource(
  file: BrowserUploadResourceInput,
  index: number,
  usedIds: Set<string>,
  updatedAt: string,
): ResourceRecord {
  const source = file.source?.trim() || file.name.trim() || "Imported resource";
  const title = fixtureUploadTitle(source);
  const sourceSegments = source
    .replace(/\\/g, "/")
    .split("/")
    .filter((segment) => segment && segment !== "." && segment !== "..");

  return {
    id: fixtureUploadId(title, index, usedIds),
    title,
    kind: file.kind,
    status: "ready",
    summary: previewText(
      "A local browser-preview copy. It was not saved to your workspace.",
      "浏览器预览中的本地副本，不会保存到工作区。",
    ),
    source,
    collectionPath: ["Imported", ...sourceSegments].join("/"),
    collectionRoot: "Browser preview",
    sourceItems: [source],
    tags: file.tags ?? [],
    sourceType: "file",
    freshness: "fresh",
    indexState: "indexed",
    previewTier: "metadata",
    previewKind: file.kind,
    canInjectTrainingCard: false,
    updatedAt,
  };
}

export async function uploadBrowserPreviewResources(
  files: BrowserUploadResourceInput[],
  sessionId?: string,
): Promise<{
  sessionId: string;
  patch: Partial<BootstrapData>;
  uploadedCount: number;
  indexedCount: number;
  failedIndexCount: number;
  failedUploadCount: number;
  failedUploads: Array<{ fileName: string; message: string }>;
  truncated: boolean;
}> {
  const resolvedSessionId = await ensureBrowserPreviewSession(sessionId);
  const limitedFiles = files.slice(0, MAX_BROWSER_UPLOADS);

  if (isBrowserPreviewFixture()) {
    const injected = window.__TRAINER_BOOTSTRAP__;
    const bootstrap =
      injected && typeof injected === "object"
        ? (injected as BrowserPreviewBootstrap)
        : ({} as BrowserPreviewBootstrap);
    const currentResources = Array.isArray(bootstrap.resources) ? bootstrap.resources : [];
    const usedIds = new Set(currentResources.map((resource) => resource.id));
    const updatedAt = new Date().toISOString();
    const importedResources = limitedFiles.map((file, index) =>
      fixtureUploadedResource(file, index, usedIds, updatedAt),
    );
    const resources = [...currentResources, ...importedResources];

    window.__TRAINER_BOOTSTRAP__ = {
      ...bootstrap,
      resources,
    };

    return {
      sessionId: resolvedSessionId,
      patch: { resources },
      uploadedCount: importedResources.length,
      indexedCount: importedResources.length,
      failedIndexCount: 0,
      failedUploadCount: 0,
      failedUploads: [],
      truncated: files.length > MAX_BROWSER_UPLOADS,
    };
  }

  const workspaceId = previewWorkspaceId();
  const uploadedRecords: ResourceRecord[] = [];
  const failedUploads: Array<{ fileName: string; message: string }> = [];
  let indexedCount = 0;
  let failedIndexCount = 0;

  for (const file of limitedFiles) {
    let uploaded: ResourceRecord;
    try {
      const uploadResponse = await fetchPreview(`${baseUrl()}/resource/upload`, {
        method: "POST",
        headers: asJsonHeaders(),
        body: JSON.stringify({
          session_id: resolvedSessionId,
          workspace_id: workspaceId,
          kind: file.kind,
          name: file.name,
          source: file.source ?? file.name,
          ...(file.kind === "url"
            ? { source_type: "url" }
            : {
                content: file.content,
                content_encoding: file.contentEncoding ?? "utf-8",
              }),
          tags: file.tags ?? [],
        }),
      }, "upload");

      if (!uploadResponse.ok) {
        await throwPreviewHttpFailure(uploadResponse, "upload");
      }

      uploaded = await readPreviewJson<ResourceRecord>(uploadResponse, "upload");
    } catch (error) {
      failedUploads.push({
        fileName: file.name,
        message: previewErrorDetail(error) || previewFailureMessage("provider_error"),
      });
      continue;
    }

    uploadedRecords.push(uploaded);

    try {
      const indexResponse = await fetchPreview(`${baseUrl()}/resource/index`, {
        method: "POST",
        headers: asJsonHeaders(),
        body: JSON.stringify({
          session_id: resolvedSessionId,
          workspace_id: workspaceId,
          resource_id: uploaded.id,
          enable_network: uploaded.kind === "url",
        }),
      }, "upload");

      if (indexResponse.ok) {
        const indexed = await readPreviewJson<ResourceRecord>(indexResponse, "upload");
        const existingIndex = uploadedRecords.findIndex((item) => item.id === indexed.id);
        if (existingIndex >= 0) {
          uploadedRecords[existingIndex] = indexed;
        }
        if (isCompletedBrowserPreviewResourceIndex(indexed)) {
          indexedCount += 1;
        } else {
          failedIndexCount += 1;
        }
      } else {
        failedIndexCount += 1;
      }
    } catch {
      failedIndexCount += 1;
    }
  }

  if (limitedFiles.length > 0 && uploadedRecords.length === 0) {
    throw new Error(
      failedUploads[0]?.message ?? previewFailureMessage("provider_error"),
    );
  }

  const summaryResponse = await fetchPreview(
    `${baseUrl()}/memory/summary?session_id=${encodeURIComponent(resolvedSessionId)}&workspace_id=${encodeURIComponent(
      workspaceId,
    )}`,
    {},
    "upload",
  );
  if (!summaryResponse.ok) {
    await throwPreviewHttpFailure(summaryResponse, "upload");
  }
  const snapshot = await readPreviewJson(summaryResponse, "upload");
  const payload = mapSnapshotToBootstrap(snapshot);
  return {
    sessionId: resolvedSessionId,
    patch: {
      resources: payload.resources,
      memory: payload.memory,
      workspaceTrainingState: payload.workspaceTrainingState,
      plan: payload.plan,
      conversation: payload.conversation,
      suggestedActions: payload.suggestedActions,
      reviewQueueSummary: payload.reviewQueueSummary,
      nextReviewDue: payload.nextReviewDue,
    },
    uploadedCount: uploadedRecords.length,
    indexedCount,
    failedIndexCount,
    failedUploadCount: failedUploads.length,
    failedUploads,
    truncated: files.length > MAX_BROWSER_UPLOADS,
  };
}

function isCompletedBrowserPreviewResourceIndex(resource: ResourceRecord): boolean {
  const record = asRecord(resource);
  return (
    (asString(record?.parse_status) ?? asString(record?.parseStatus)) === "parsed" &&
    (asString(record?.index_status) ?? asString(record?.indexStatus)) === "indexed"
  );
}

function mapSnapshotToBootstrap(snapshot: unknown): BootstrapData {
  const record = asRecord(snapshot);
  const profile = asRecord(record?.profile);
  const plan = asRecord(record?.plan);
  const memory = asRecord(record?.memory);
  const provider = asRecord(record?.provider);
  const previewProvider = buildPreviewProviderView(activePreviewProviderRecord());
  const fallbackCapabilities = previewProtocolCapabilityDefaults("openai_chat_completions_compatible");
  const baseProviderConfig: ProviderConfigView = {
    configured: Boolean(provider),
    name: asString(provider?.name) ?? "",
    baseUrl: "",
    model: asString(provider?.model) ?? "",
    apiKeyConfigured: false,
    capabilities: fallbackCapabilities,
    availableModels: [],
    resolvedModel: undefined,
    modelListStatus: "idle",
    modelListDetail: undefined,
    cacheFetchedAt: undefined,
    cacheExpiresAt: undefined,
    cacheSource: undefined,
    modelErrorCategory: undefined,
    modelStatusCode: undefined,
    modelRetryable: undefined,
    protocol: "openai_chat_completions_compatible",
    protocolFamily: providerProtocolFamily("openai_chat_completions_compatible"),
    credentialMode: "ui_proxy",
  };
  const effectiveProviderConfig = previewProvider ?? baseProviderConfig;
  const effectiveProviderProtocol = normalizeProviderProtocol(effectiveProviderConfig.protocol);

  const planStagesRaw = Array.isArray(plan?.stages) ? plan?.stages : [];
  const currentTask = asRecord(record?.current_task);
  const evaluation = asRecord(record?.evaluation);
  const messages = Array.isArray(record?.messages) ? record?.messages : [];

  // The live preview owns a session-scoped workspace identity. When the sidecar
  // has no workspace record yet (fresh session), fail-open here so scoped
  // selectors (provider last-test, capability verdicts) can resolve against
  // the same workspace id the preview already uses for its API calls.
  const mappedMemoryWorkspace = asMemoryWorkspace(memory?.workspace);
  const scopedPreviewWorkspaceId = mappedMemoryWorkspace?.workspaceId?.trim() || previewWorkspaceId();
  const memoryWorkspace: BootstrapData["memory"]["workspace"] = {
    ...(mappedMemoryWorkspace ?? {}),
    workspaceId: scopedPreviewWorkspaceId,
  };
  const mappedWorkspaceTrainingState = mapWorkspaceTrainingState(memory, undefined);
  const workspaceTrainingState: BootstrapData["workspaceTrainingState"] = {
    ...(mappedWorkspaceTrainingState ?? {}),
    workspaceId: mappedWorkspaceTrainingState?.workspaceId ?? scopedPreviewWorkspaceId,
  };
  const previewSandboxRoot = `sandbox:/${scopedPreviewWorkspaceId}`;
  const previewSandboxState: BootstrapData["memory"]["sandboxState"] = {
    ready: true,
    rootPath: previewSandboxRoot,
    sandboxRootPath: previewSandboxRoot,
    activeWorkspaceRoot: previewSandboxRoot,
    authority: {
      authoritySource: "browser_preview",
      authorityMode: "trainer_sandbox",
      authorityScope: "trainer_sandbox",
      resourceWriteAllowed: true,
      resourceWriteEvidence: {
        operation: "write",
        scope: "trainer_sandbox",
        targetRoot: previewSandboxRoot,
        allowed: true,
        reason: "browser_preview",
      },
      permissionLevel: "workspace",
      allowedOperations: ["read", "write"],
      nextSafeAction: "continue",
    },
  };

  return {
    workspaceName: DEV_WORKSPACE_NAME,
    sessionLabel: "Preview session",
    connection: {
      state: "connected",
      provider: {
        name: effectiveProviderConfig.name || asString(provider?.name) || "Preview sidecar",
        model:
          effectiveProviderConfig.resolvedModel?.trim() ||
          effectiveProviderConfig.model ||
          asString(provider?.model) ||
          "Not configured",
        capabilities: effectiveProviderConfig.capabilities,
        protocol: effectiveProviderProtocol,
        protocolFamily:
          effectiveProviderConfig.protocolFamily ?? providerProtocolFamily(effectiveProviderProtocol),
      },
    },
    providerConfig: effectiveProviderConfig,
    liveContext: {
      activeFile: undefined,
      activeLanguageId: undefined,
      selectionRange: undefined,
      selectionPreview: undefined,
      diagnosticsSummary: "",
      documentVersion: undefined,
      recentFiles: [],
      recentEditedFiles: [],
      relatedFiles: [],
      diagnosticErrors: undefined,
      diagnosticWarnings: undefined,
    },
    profile: {
      learnerName:
        asString(memory?.workspace && asRecord(memory.workspace)?.learner_name) ??
        asString(memory?.workspace && asRecord(memory.workspace)?.learnerName) ??
        "",
      goals: asStringArray(profile?.long_term_goals) ?? [],
      weeklyHours: asNumber(profile?.weekly_hours) ?? 4,
      preferredStyle: asString(profile?.teaching_style) ?? "",
      answerPolicy: toAnswerPolicy(asString(profile?.answer_policy)),
      focusAreas: asStringArray(profile?.preferred_libraries) ?? [],
      targetProject:
        asString(profile?.target_project) ??
        asString(memory?.workspace && asRecord(memory.workspace)?.project_context) ??
        asString(memory?.workspace && asRecord(memory.workspace)?.projectContext) ??
        undefined,
      preferredRhythm:
        asString(memory?.workspace && asRecord(memory.workspace)?.preferred_rhythm) ??
        asString(memory?.workspace && asRecord(memory.workspace)?.preferredRhythm) ??
        undefined,
      preferredLearningMode:
        asString(memory?.workspace && asRecord(memory.workspace)?.preferred_learning_mode) ??
        asString(memory?.workspace && asRecord(memory.workspace)?.preferredLearningMode) ??
        undefined,
      onboardingRequest:
        asString(memory?.workspace && asRecord(memory.workspace)?.onboarding_request) ??
        asString(memory?.workspace && asRecord(memory.workspace)?.onboardingRequest) ??
        undefined,
      projectContext:
        asString(memory?.workspace && asRecord(memory.workspace)?.project_context) ??
        asString(memory?.workspace && asRecord(memory.workspace)?.projectContext) ??
        undefined,
    },
    plan: {
      id: asString(plan?.id) ?? asString(plan?.plan_id) ?? "preview-plan",
      title: asString(plan?.title) ?? "Training plan",
      frozen: asBoolean(plan?.frozen) ?? false,
      cadence: asString(plan?.cadence) ?? "",
      summary: normalizeCoachSurfaceText(plan?.summary) ?? "",
      currentStep: normalizeCoachSurfaceText(plan?.current_step) ?? undefined,
      whyNow: normalizeCoachSurfaceText(plan?.why_now) ?? undefined,
      verifyMethod: asStringArray(plan?.verify_method) ?? undefined,
      blockedReason: normalizeCoachSurfaceText(plan?.blocked_reason) ?? undefined,
      nextAfterCurrent: normalizeCoachSurfaceText(plan?.next_after_current) ?? undefined,
      stages: planStagesRaw.map((item, index) => {
        const stage = asRecord(item);
        const status = asString(stage?.status);
        return {
          id: asString(stage?.id) ?? `stage-${index + 1}`,
          title: asString(stage?.title) ?? `Stage ${index + 1}`,
          objective: asString(stage?.goal) ?? "",
          status: status === "active" ? "active" : status === "completed" ? "done" : "queued",
        } as const;
      }),
      currentStageId: asString(plan?.current_stage_id) ?? undefined,
    },
    task: {
      id: asString(currentTask?.id) ?? "preview-task",
      title: asString(currentTask?.title) ?? "",
      description: asString(currentTask?.natural_language_goal) ?? "",
      constraints: asStringArray(currentTask?.constraints) ?? [],
      acceptanceCriteria:
        asStringArray(currentTask?.verification_strategy) ??
        asStringArray(currentTask?.outputs) ??
        [],
      nextActionLabel: "Continue",
    },
    evaluation: {
      headline: asString(evaluation?.summary) ?? "",
      summary: asString(evaluation?.summary) ?? "",
      passRate: 0,
      updatedAt: "Just now",
      checks: [],
      nextStep: asString(evaluation?.next_step) ?? "",
    },
    memory: {
      currentFocus:
        normalizeCoachSurfaceText(memory?.current_focus) ??
        normalizeCoachSurfaceText(memory?.recent_summary) ??
        "",
      weakSpots: asStringArray(memory?.weaknesses) ?? [],
      recentWins: asStringArray(memory?.recent_wins) ?? [],
      reviewSummary: normalizeCoachSurfaceText(memory?.review_rhythm) ?? "",
      reviewRhythm: normalizeCoachSurfaceText(memory?.review_rhythm) ?? "",
      dueReviews: asDueReviews(memory?.due_reviews),
      teachingObservations: asStringArray(memory?.teaching_observations) ?? [],
      coachAnchor: asString(memory?.coach_anchor) ?? undefined,
      topWeakness: asString(memory?.top_weakness) ?? undefined,
      lowestMasteryConcepts: asStringArray(memory?.lowest_mastery_concepts) ?? [],
      dueReviewCount: asNumber(memory?.due_review_count) ?? 0,
      paceSignal: asString(memory?.pace_signal) ?? undefined,
      activeThread: asActiveThread(memory?.active_thread),
      memoryEvidence: asStringArray(memory?.memory_evidence) ?? [],
      workspaceUnderstanding: mapWorkspaceUnderstanding(
        memory?.workspace_understanding ?? memory?.workspaceUnderstanding,
      ),
      workspace: memoryWorkspace,
      sandboxState: previewSandboxState,
      sandboxPreview: mapSandboxPreview(memory?.sandbox_preview ?? memory?.sandboxPreview),
    } as BootstrapData["memory"],
    workspaceTrainingState,
    coachingState: asCoachingState(record?.coaching_state),
    learnerState: undefined,
    affectState: undefined,
    teachingDecision: undefined,
    toneDecision: undefined,
    implementationGuide: mapImplementationGuide(record?.implementation_guide),
    projectIdeas: mapProjectIdeas(record?.project_ideas) ?? [],
    projectAdaptationGuide: mapProjectAdaptationGuide(
      record?.project_adaptation_guide ?? record?.adaptation_guide,
    ),
    principleNotes: mapPrincipleNote(record?.principle_notes ?? record?.principle_note),
    coachTurn: asCoachTurn(record?.coach_turn),
    coachFocus: asCoachFocus(record?.coach_context),
    coachOrientation:
      normalizeCoachOrientationRecord(record?.coach_orientation) ??
      normalizeCoachOrientationRecord(record?.coachOrientation) ??
      normalizeCoachOrientationRecord(asRecord(memory?.workspace)?.latest_coach_orientation) ??
      normalizeCoachOrientationRecord(asRecord(memory?.workspace)?.latestCoachOrientation),
    planRuntimeStatus: asPlanRuntimeStatus(record?.plan_runtime_status),
    reviewQueueSummary: normalizeCoachSurfaceText(record?.review_queue_summary) ?? "",
    nextReviewDue: asString(record?.next_review_due) ?? undefined,
    streamingState: createEmptyTrainerStreamingState(),
    resources: mapResources(memory?.resources),
    conversation: messages.map((item, index) => mapConversationMessage(item, index)),
    suggestedActions: [],
    commands: [],
  };
}

function mapTurnPayloadToPatch(payload: unknown): Partial<BootstrapData> {
  const record = asRecord(payload);
  const snapshot = asRecord(record?.snapshot);
  const reply = asRecord(record?.reply);
  const base = mapSnapshotToBootstrap(snapshot ?? {});
  const mappedConversation =
    base.conversation.length > 0
      ? base.conversation
      : reply
        ? [
            mapConversationMessage(reply, 0),
          ]
        : [];

  return {
    conversation: mappedConversation,
    memory: base.memory,
    workspaceTrainingState: base.workspaceTrainingState,
    profile: base.profile,
    plan: base.plan,
    task: base.task,
    evaluation: base.evaluation,
    coachingState: base.coachingState,
    coachTurn: base.coachTurn,
    coachFocus: base.coachFocus,
    coachOrientation:
      normalizeCoachOrientationRecord(record?.coach_orientation) ??
      normalizeCoachOrientationRecord(snapshot?.coach_orientation) ??
      base.coachOrientation,
    planRuntimeStatus: base.planRuntimeStatus,
    implementationGuide:
      mapImplementationGuide(
        record?.implementation_guide ??
          snapshot?.implementation_guide ??
          asRecord(record?.pedagogy)?.implementation_guide,
      ) ?? base.implementationGuide,
    projectIdeas:
      mapProjectIdeas(
        record?.project_ideas ??
          snapshot?.project_ideas ??
          asRecord(record?.pedagogy)?.project_ideas,
      ) ?? base.projectIdeas,
    projectAdaptationGuide:
      mapProjectAdaptationGuide(
        record?.project_adaptation_guide ??
          record?.adaptation_guide ??
          snapshot?.project_adaptation_guide ??
          snapshot?.adaptation_guide ??
          asRecord(record?.pedagogy)?.project_adaptation_guide ??
          asRecord(record?.pedagogy)?.adaptation_guide,
      ) ?? base.projectAdaptationGuide,
    principleNotes:
      mapPrincipleNote(
        record?.principle_notes ??
          record?.principle_note ??
          snapshot?.principle_notes ??
          snapshot?.principle_note ??
          asRecord(record?.pedagogy)?.principle_notes ??
          asRecord(record?.pedagogy)?.principle_note,
      ) ?? base.principleNotes,
    resources: base.resources,
    reviewQueueSummary: base.reviewQueueSummary,
    nextReviewDue: base.nextReviewDue,
  };
}

export function mapSandboxPreview(value: unknown): SandboxPreview | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const structuredData =
    asRecord(record.structured_data) ??
    asRecord(record.structuredData) ??
    undefined;
  const metadata = asRecord(record.metadata) ?? undefined;

  return {
    path: asString(record.path) ?? "",
    relativePath: asString(record.relative_path) ?? asString(record.relativePath) ?? undefined,
    title: asString(record.title) ?? undefined,
    fileKind: asString(record.file_kind) ?? asString(record.fileKind) ?? undefined,
    previewTier: asString(record.preview_tier) ?? asString(record.previewTier) ?? undefined,
    previewKind: asString(record.preview_kind) ?? asString(record.previewKind) ?? undefined,
    languageHint: asString(record.language_hint) ?? asString(record.languageHint) ?? undefined,
    renderedFrom: asString(record.rendered_from) ?? asString(record.renderedFrom) ?? undefined,
    content: asString(record.content) ?? undefined,
    excerpt: asString(record.excerpt) ?? undefined,
    html: asString(record.html) ?? undefined,
    isBinary: asBoolean(record.is_binary) ?? asBoolean(record.isBinary) ?? undefined,
    isEditable: asBoolean(record.is_editable) ?? asBoolean(record.isEditable) ?? undefined,
    canNativeOpen:
      asBoolean(record.can_native_open) ?? asBoolean(record.canNativeOpen) ?? undefined,
    structuredData,
    metadata,
    assetUri: asString(record.asset_uri) ?? asString(record.assetUri) ?? undefined,
  };
}

function mapWorkspaceTrainingState(
  value: unknown,
  fallback: BootstrapData["workspaceTrainingState"],
): BootstrapData["workspaceTrainingState"] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const workspaceRecord = asRecord(record.workspace);
  const activeTrainingCardRouting = mapActiveTrainingCardRouting(
    record.active_training_card_routing ?? record.activeTrainingCardRouting,
    fallback?.activeTrainingCardRouting,
  );
  const mapped: WorkspaceTrainingStateView = {
    workspaceId:
      asString(workspaceRecord?.workspace_id) ??
      asString(workspaceRecord?.workspaceId) ??
      fallback?.workspaceId,
    latestConversationHandoff: mapTrainingHandoff(
      workspaceRecord?.latest_conversation_handoff ?? workspaceRecord?.latestConversationHandoff,
      fallback?.latestConversationHandoff,
    ),
    latestTrainingHandoff: mapTrainingHandoff(
      workspaceRecord?.latest_training_handoff ?? workspaceRecord?.latestTrainingHandoff,
      fallback?.latestTrainingHandoff,
    ),
    latestTrainingReliability: mapTrainingReliability(
      workspaceRecord?.latest_training_reliability ?? workspaceRecord?.latestTrainingReliability,
      fallback?.latestTrainingReliability,
    ),
    latestTransferState:
      normalizeTransferSkillStateRecord(
        workspaceRecord?.latest_transfer_state ?? workspaceRecord?.latestTransferState,
      ) ?? fallback?.latestTransferState,
    latestTrainingNextHop: mapTrainingNextHop(
      workspaceRecord?.latest_training_next_hop ?? workspaceRecord?.latestTrainingNextHop,
      fallback?.latestTrainingNextHop,
    ),
    latestTrainingSubmode:
      asString(workspaceRecord?.latest_training_submode) ??
      asString(workspaceRecord?.latestTrainingSubmode) ??
      fallback?.latestTrainingSubmode,
    latestLearningFocusArea:
      asString(workspaceRecord?.latest_learning_focus_area) ??
      asString(workspaceRecord?.latestLearningFocusArea) ??
      fallback?.latestLearningFocusArea,
    latestLearningFollowup:
      asString(workspaceRecord?.latest_learning_followup) ??
      asString(workspaceRecord?.latestLearningFollowup) ??
      fallback?.latestLearningFollowup,
    latestLearningVerifiedResult:
      asString(workspaceRecord?.latest_learning_verified_result) ??
      asString(workspaceRecord?.latestLearningVerifiedResult) ??
      fallback?.latestLearningVerifiedResult,
    latestLearningBlocker:
      asString(workspaceRecord?.latest_learning_blocker) ??
      asString(workspaceRecord?.latestLearningBlocker) ??
      fallback?.latestLearningBlocker,
    latestLearningAbandonReason:
      asString(workspaceRecord?.latest_learning_abandon_reason) ??
      asString(workspaceRecord?.latestLearningAbandonReason) ??
      fallback?.latestLearningAbandonReason,
    latestLearningPartialProgress:
      asString(workspaceRecord?.latest_learning_partial_progress) ??
      asString(workspaceRecord?.latestLearningPartialProgress) ??
      fallback?.latestLearningPartialProgress,
    selectedCardId:
      asString(workspaceRecord?.selected_card_id) ??
      asString(workspaceRecord?.selectedCardId) ??
      fallback?.selectedCardId,
    selectedCardType:
      activeTrainingCardRouting?.selectedCard?.type ??
      toTrainingCardType(
        asString(workspaceRecord?.selected_card_type) ??
          asString(workspaceRecord?.selectedCardType),
      ) ?? fallback?.selectedCardType,
    selectedCardTitle:
      asString(workspaceRecord?.selected_card_title) ??
      asString(workspaceRecord?.selectedCardTitle) ??
      fallback?.selectedCardTitle,
    selectedCardStatus:
      asString(workspaceRecord?.selected_card_status) ??
      asString(workspaceRecord?.selectedCardStatus) ??
      fallback?.selectedCardStatus,
    trainingCardCandidates: mapTrainingCardCandidates(
      record.training_card_candidates ?? record.trainingCardCandidates,
      fallback?.trainingCardCandidates,
    ),
    activeTrainingCardRouting,
    trainingEventLedger: mapTrainingEventLedger(
      record.training_event_ledger ?? record.trainingEventLedger,
      fallback?.trainingEventLedger,
    ),
    reviewArtifact: mapReviewArtifact(
      record.review_artifact ?? record.reviewArtifact,
      fallback?.reviewArtifact,
    ),
    scenarioLab: mapScenarioLab(
      record.scenario_lab ?? record.scenarioLab,
      fallback?.scenarioLab,
    ),
    theoryDrill: mapTheoryDrill(
      record.theory_drill ?? record.theoryDrill,
      fallback?.theoryDrill,
    ),
    dueReviews:
      record.due_reviews === undefined && record.dueReviews === undefined
        ? fallback?.dueReviews
        : asDueReviews(record.due_reviews ?? record.dueReviews),
  };

  const routedCardType = activeTrainingCardRouting?.selectedCard?.type;
  if (routedCardType) {
    mapped.selectedCardType = routedCardType;
  }

  if (!hasWorkspaceTrainingStateContent(mapped)) {
    return fallback;
  }

  return mapped;
}

function toTrainingReliabilityPhase(
  value: string | undefined,
): NonNullable<WorkspaceTrainingStateView["latestTrainingReliability"]>["phase"] {
  if (
    value === "intent" ||
    value === "pending" ||
    value === "executing" ||
    value === "succeeded" ||
    value === "failed" ||
    value === "acked" ||
    value === "cancelled"
  ) {
    return value;
  }
  return undefined;
}

function toTrainingReliabilityOutcome(
  value: string | undefined,
): NonNullable<WorkspaceTrainingStateView["latestTrainingReliability"]>["outcome"] {
  if (
    value === "success" ||
    value === "failure" ||
    value === "cancelled" ||
    value === "timeout" ||
    value === ""
  ) {
    return value;
  }
  return undefined;
}

function mapTrainingReliability(
  value: unknown,
  fallback: WorkspaceTrainingStateView["latestTrainingReliability"],
): WorkspaceTrainingStateView["latestTrainingReliability"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }
  const requestId =
    asString(record.request_id) ?? asString(record.requestId) ?? fallback?.requestId;
  if (!requestId) {
    return fallback;
  }
  return {
    requestId,
    idempotencyKey:
      asString(record.idempotency_key) ?? asString(record.idempotencyKey) ?? fallback?.idempotencyKey,
    commandId: asString(record.command_id) ?? asString(record.commandId) ?? fallback?.commandId,
    cardId: asString(record.card_id) ?? asString(record.cardId) ?? fallback?.cardId,
    handoffId: asString(record.handoff_id) ?? asString(record.handoffId) ?? fallback?.handoffId,
    phase: toTrainingReliabilityPhase(asString(record.phase)) ?? fallback?.phase,
    revision: asNumber(record.revision) ?? fallback?.revision,
    snapshotRevision:
      asNumber(record.snapshot_revision) ??
      asNumber(record.snapshotRevision) ??
      fallback?.snapshotRevision,
    createdAt: asString(record.created_at) ?? asString(record.createdAt) ?? fallback?.createdAt,
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
    ackedAt: asString(record.acked_at) ?? asString(record.ackedAt) ?? fallback?.ackedAt,
    timeoutAt: asString(record.timeout_at) ?? asString(record.timeoutAt) ?? fallback?.timeoutAt,
    cancelRequested:
      asBoolean(record.cancel_requested) ??
      asBoolean(record.cancelRequested) ??
      fallback?.cancelRequested,
    outcome: toTrainingReliabilityOutcome(asString(record.outcome)) ?? fallback?.outcome,
    error: asString(record.error) ?? fallback?.error,
    recoverable: asBoolean(record.recoverable) ?? fallback?.recoverable,
    recoveryAction:
      asString(record.recovery_action) ?? asString(record.recoveryAction) ?? fallback?.recoveryAction,
    learningPhase:
      asString(record.learning_phase) ?? asString(record.learningPhase) ?? fallback?.learningPhase,
  };
}

function mapTrainingHandoff(
  value: unknown,
  fallback: WorkspaceTrainingStateView["latestTrainingHandoff"],
): WorkspaceTrainingStateView["latestTrainingHandoff"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: TrainingHandoffStateView = {
    handoffId:
      asString(record.handoff_id) ?? asString(record.handoffId) ?? fallback?.handoffId,
    learningPhase:
      toTrainingLearningPhase(asString(record.learning_phase) ?? asString(record.learningPhase)) ??
      fallback?.learningPhase,
    candidateId:
      asString(record.candidate_id) ?? asString(record.candidateId) ?? fallback?.candidateId,
    candidateType:
      toTrainingConversationCandidateType(
        asString(record.candidate_type) ?? asString(record.candidateType),
      ) ?? fallback?.candidateType,
    targetKind:
      asString(record.target_kind) ?? asString(record.targetKind) ?? fallback?.targetKind,
    targetId: asString(record.target_id) ?? asString(record.targetId) ?? fallback?.targetId,
    continueIn:
      toTrainingContinueIn(asString(record.continue_in) ?? asString(record.continueIn)) ??
      fallback?.continueIn,
    acceptedInto:
      asString(record.accepted_into) ?? asString(record.acceptedInto) ?? fallback?.acceptedInto,
    handoffStatus:
      asString(record.handoff_status) ?? asString(record.handoffStatus) ?? fallback?.handoffStatus,
    handoffSummary:
      asString(record.handoff_summary) ??
      asString(record.handoffSummary) ??
      fallback?.handoffSummary,
    blockedBy: asString(record.blocked_by) ?? asString(record.blockedBy) ?? fallback?.blockedBy,
    coachOnly: asBoolean(record.coach_only) ?? asBoolean(record.coachOnly) ?? fallback?.coachOnly,
    cardType:
      toTrainingCardType(asString(record.card_type) ?? asString(record.cardType)) ??
      fallback?.cardType,
    cardTitle: asString(record.card_title) ?? asString(record.cardTitle) ?? fallback?.cardTitle,
    scenarioPack:
      asString(record.scenario_pack) ?? asString(record.scenarioPack) ?? fallback?.scenarioPack,
    learnerDeliverables:
      asStringArray(record.learner_deliverables ?? record.learnerDeliverables) ??
      fallback?.learnerDeliverables,
    verificationSteps:
      asStringArray(record.verification_steps ?? record.verificationSteps) ??
      fallback?.verificationSteps,
    successSignal:
      asString(record.success_signal) ?? asString(record.successSignal) ?? fallback?.successSignal,
    returnWith: asString(record.return_with) ?? asString(record.returnWith) ?? fallback?.returnWith,
    nextAfterCompletion:
      asString(record.next_after_completion) ??
      asString(record.nextAfterCompletion) ??
      fallback?.nextAfterCompletion,
    fallbackAction:
      asString(record.fallback_action) ?? asString(record.fallbackAction) ?? fallback?.fallbackAction,
    returnMode:
      toTrainingReturnMode(asString(record.return_mode) ?? asString(record.returnMode)) ??
      fallback?.returnMode,
    returnSummary:
      asString(record.return_summary) ?? asString(record.returnSummary) ?? fallback?.returnSummary,
    judgedAt:
      asString(record.judged_at) ??
      asString(record.judgedAt) ??
      asString(record.fed_back_at) ??
      asString(record.fedBackAt) ??
      fallback?.judgedAt,
    sourceChain: asStringArray(record.source_chain ?? record.sourceChain) ?? fallback?.sourceChain,
  };

  return hasTrainingHandoffContent(mapped) ? mapped : undefined;
}

function mapTrainingNextHop(
  value: unknown,
  fallback: WorkspaceTrainingStateView["latestTrainingNextHop"],
): WorkspaceTrainingStateView["latestTrainingNextHop"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: TrainingNextHopStateView = {
    candidateId:
      asString(record.candidate_id) ?? asString(record.candidateId) ?? fallback?.candidateId,
    candidateType:
      toTrainingNextHopCandidateType(
        asString(record.candidate_type) ?? asString(record.candidateType),
      ) ?? fallback?.candidateType,
    title: asString(record.title) ?? fallback?.title,
    summary: normalizeCoachSurfaceText(record.summary) ?? fallback?.summary,
    whyNow:
      normalizeCoachSurfaceText(record.why_now) ??
      normalizeCoachSurfaceText(record.whyNow) ??
      fallback?.whyNow,
    projectScope:
      toTrainingProjectScope(asString(record.project_scope) ?? asString(record.projectScope)) ??
      fallback?.projectScope,
    continueIn:
      toTrainingNextHopContinueIn(
        asString(record.continue_in) ?? asString(record.continueIn),
      ) ?? fallback?.continueIn,
    targetKind:
      asString(record.target_kind) ?? asString(record.targetKind) ?? fallback?.targetKind,
    targetId: asString(record.target_id) ?? asString(record.targetId) ?? fallback?.targetId,
    acceptedInto:
      asString(record.accepted_into) ?? asString(record.acceptedInto) ?? fallback?.acceptedInto,
    status: toTrainingNextHopStatus(asString(record.status)) ?? fallback?.status,
    statusReason:
      asString(record.status_reason) ?? asString(record.statusReason) ?? fallback?.statusReason,
    blockedBy: asString(record.blocked_by) ?? asString(record.blockedBy) ?? fallback?.blockedBy,
    handoffStatus:
      asString(record.handoff_status) ?? asString(record.handoffStatus) ?? fallback?.handoffStatus,
    handoffSummary:
      asString(record.handoff_summary) ??
      asString(record.handoffSummary) ??
      fallback?.handoffSummary,
    coachOnly: asBoolean(record.coach_only) ?? asBoolean(record.coachOnly) ?? fallback?.coachOnly,
    cardType:
      toTrainingCardType(asString(record.card_type) ?? asString(record.cardType)) ??
      fallback?.cardType,
    cardTitle: asString(record.card_title) ?? asString(record.cardTitle) ?? fallback?.cardTitle,
    scenarioPack:
      asString(record.scenario_pack) ?? asString(record.scenarioPack) ?? fallback?.scenarioPack,
    returnMode:
      toTrainingReturnMode(asString(record.return_mode) ?? asString(record.returnMode)) ??
      fallback?.returnMode,
    returnSummary:
      asString(record.return_summary) ?? asString(record.returnSummary) ?? fallback?.returnSummary,
    judgedAt: asString(record.judged_at) ?? asString(record.judgedAt) ?? fallback?.judgedAt,
    reviewArtifactId:
      asString(record.review_artifact_id) ??
      asString(record.reviewArtifactId) ??
      fallback?.reviewArtifactId,
    reviewArtifactStatus:
      asString(record.review_artifact_status) ??
      asString(record.reviewArtifactStatus) ??
      fallback?.reviewArtifactStatus,
    reviewRecoveryMode:
      asString(record.review_recovery_mode) ??
      asString(record.reviewRecoveryMode) ??
      fallback?.reviewRecoveryMode,
    planEvidenceId:
      asString(record.plan_evidence_id) ?? asString(record.planEvidenceId) ?? fallback?.planEvidenceId,
    nextAfterCompletion:
      asString(record.next_after_completion) ??
      asString(record.nextAfterCompletion) ??
      fallback?.nextAfterCompletion,
    fallbackAction:
      asString(record.fallback_action) ?? asString(record.fallbackAction) ?? fallback?.fallbackAction,
    sourceChain: asStringArray(record.source_chain ?? record.sourceChain) ?? fallback?.sourceChain,
  };

  return hasTrainingNextHopContent(mapped) ? mapped : undefined;
}

function mapTrainingCardCandidates(
  value: unknown,
  fallback: WorkspaceTrainingStateView["trainingCardCandidates"],
): WorkspaceTrainingStateView["trainingCardCandidates"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Array.isArray(value)) {
    return fallback;
  }

  return value.reduce<TrainingCardCandidateStateView[]>((items, entry) => {
    const record = asRecord(entry);
    const cardId = asString(record?.card_id) ?? asString(record?.cardId) ?? asString(record?.id);
    const title = asString(record?.title);
    const type = toTrainingCardType(
      asString(record?.card_type) ?? asString(record?.cardType) ?? asString(record?.type),
    );
    if (!cardId || !title || !type) {
      return items;
    }
    items.push({
      cardId,
      type,
      title,
      whyNow:
        normalizeCoachSurfaceText(record?.why_now) ??
        normalizeCoachSurfaceText(record?.whyNow) ??
        undefined,
      status: asString(record?.status) ?? undefined,
      learningPhase:
        toTrainingLearningPhase(
          asString(record?.learning_phase) ?? asString(record?.learningPhase),
        ) ?? undefined,
      ...mapTrainingCardVerificationFields(record),
    });
    return items;
  }, []);
}

type TrainingCardVerificationFields = Pick<
  TrainingCardCandidateStateView,
  | "focusArea"
  | "targetSkill"
  | "scenario"
  | "problemStatement"
  | "suggestedWorkspaceAction"
  | "apiHints"
  | "constraints"
  | "deliverable"
  | "selfCheck"
  | "expectedAnswerShape"
  | "validationMethod"
  | "verificationMethod"
  | "filesToTouch"
  | "learnerDeliverables"
  | "verificationSteps"
  | "successSignal"
  | "expectedSymbols"
>;

function mapTrainingCardVerificationFields(
  record: Record<string, unknown> | undefined,
  fallback?: Partial<TrainingCardVerificationFields>,
): Partial<TrainingCardVerificationFields> {
  if (!record) {
    return fallback ?? {};
  }
  return {
    focusArea: asString(record.focus_area) ?? asString(record.focusArea) ?? fallback?.focusArea,
    targetSkill: asString(record.target_skill) ?? asString(record.targetSkill) ?? fallback?.targetSkill,
    scenario: asString(record.scenario) ?? fallback?.scenario,
    problemStatement:
      asString(record.problem_statement) ?? asString(record.problemStatement) ?? fallback?.problemStatement,
    suggestedWorkspaceAction:
      asString(record.suggested_workspace_action) ??
      asString(record.suggestedWorkspaceAction) ??
      fallback?.suggestedWorkspaceAction,
    apiHints: asStringArray(record.api_hints ?? record.apiHints) ?? fallback?.apiHints,
    constraints: asStringArray(record.constraints) ?? fallback?.constraints,
    deliverable: asString(record.deliverable) ?? fallback?.deliverable,
    selfCheck: asStringArray(record.self_check ?? record.selfCheck) ?? fallback?.selfCheck,
    expectedAnswerShape:
      asString(record.expected_answer_shape) ??
      asString(record.expectedAnswerShape) ??
      fallback?.expectedAnswerShape,
    validationMethod:
      asString(record.validation_method) ??
      asString(record.validationMethod) ??
      fallback?.validationMethod,
    verificationMethod:
      asString(record.verification_method) ??
      asString(record.verificationMethod) ??
      fallback?.verificationMethod,
    filesToTouch:
      asStringArray(record.files_to_touch ?? record.filesToTouch) ?? fallback?.filesToTouch,
    learnerDeliverables:
      asStringArray(record.learner_deliverables ?? record.learnerDeliverables) ??
      fallback?.learnerDeliverables,
    verificationSteps:
      asStringArray(record.verification_steps ?? record.verificationSteps) ??
      fallback?.verificationSteps,
    successSignal:
      asString(record.success_signal) ?? asString(record.successSignal) ?? fallback?.successSignal,
    expectedSymbols:
      asStringArray(record.expected_symbols ?? record.expectedSymbols) ?? fallback?.expectedSymbols,
  };
}

function mapEvidenceQueue(
  value: unknown,
  fallback: BootstrapData["memory"]["evidenceQueue"],
): BootstrapData["memory"]["evidenceQueue"] {
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }
  return {
    pending: mapEvidenceItems(record.pending, fallback?.pending),
    deferred: mapEvidenceItems(record.deferred, fallback?.deferred),
    adopted: mapEvidenceItems(record.adopted, fallback?.adopted),
    rejected: mapEvidenceItems(record.rejected, fallback?.rejected),
    history: mapEvidenceItems(record.history, fallback?.history),
    totalCount: asNumber(record.total_count) ?? asNumber(record.totalCount) ?? fallback?.totalCount ?? 0,
  };
}

function mapEvidenceItems(
  value: unknown,
  fallback: EvidenceItemStateView[] | undefined,
): EvidenceItemStateView[] {
  if (!Array.isArray(value)) {
    return fallback ?? [];
  }
  return value.reduce<EvidenceItemStateView[]>((items, entry) => {
    const record = asRecord(entry);
    const id = asString(record?.id);
    const summary = asString(record?.summary);
    if (!id || !summary) {
      return items;
    }
    items.push({
      id,
      workspaceId: asString(record?.workspace_id) ?? asString(record?.workspaceId) ?? undefined,
      summary,
      source: asString(record?.source) ?? "card_result",
      sourceCardId: asString(record?.source_card_id) ?? asString(record?.sourceCardId) ?? undefined,
      concepts: asStringArray(record?.concepts) ?? [],
      outcome: asString(record?.outcome) ?? "partial",
      confidence: asNumber(record?.confidence) ?? 0,
      timestamp: asString(record?.timestamp) ?? undefined,
      targetPlanStageId:
        asString(record?.target_plan_stage_id) ?? asString(record?.targetPlanStageId) ?? undefined,
      adopted: asBoolean(record?.adopted) ?? undefined,
      adoptedAt: asString(record?.adopted_at) ?? asString(record?.adoptedAt) ?? null,
      deferredAt: asString(record?.deferred_at) ?? asString(record?.deferredAt) ?? null,
      deferralReason:
        asString(record?.deferral_reason) ?? asString(record?.deferralReason) ?? undefined,
      rejectedAt: asString(record?.rejected_at) ?? asString(record?.rejectedAt) ?? null,
      rejectionReason:
        asString(record?.rejection_reason) ?? asString(record?.rejectionReason) ?? undefined,
    });
    return items;
  }, []);
}

function mapActiveTrainingCardRouting(
  value: unknown,
  fallback: WorkspaceTrainingStateView["activeTrainingCardRouting"],
): WorkspaceTrainingStateView["activeTrainingCardRouting"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const selectedCard = asRecord(record.selected_card ?? record.selectedCard);
  const mapped: ActiveTrainingCardRoutingStateView = {
    selectedCardId:
      asString(record.selected_card_id) ??
      asString(record.selectedCardId) ??
      fallback?.selectedCardId,
    selectedCard: selectedCard
      ? {
          cardId:
            asString(selectedCard.card_id) ??
            asString(selectedCard.cardId) ??
            fallback?.selectedCard?.cardId,
          title: asString(selectedCard.title) ?? fallback?.selectedCard?.title,
          type:
            toTrainingCardType(
              asString(selectedCard.card_type) ??
                asString(selectedCard.cardType) ??
                asString(selectedCard.type),
            ) ?? fallback?.selectedCard?.type,
          ...mapTrainingCardVerificationFields(selectedCard, fallback?.selectedCard),
        }
      : fallback?.selectedCard,
    whyThisCard:
      asString(record.why_this_card) ?? asString(record.whyThisCard) ?? fallback?.whyThisCard,
    blockedCandidates: mapTrainingBlockedCandidates(
      record.blocked_candidates ?? record.blockedCandidates,
      fallback?.blockedCandidates,
    ),
    fallbackAction:
      asString(record.fallback_action) ?? asString(record.fallbackAction) ?? fallback?.fallbackAction,
    candidateCount:
      asNumber(record.candidate_count) ?? asNumber(record.candidateCount) ?? fallback?.candidateCount,
    eligibleCount:
      asNumber(record.eligible_count) ?? asNumber(record.eligibleCount) ?? fallback?.eligibleCount,
  };

  return hasActiveTrainingCardRoutingContent(mapped) ? mapped : undefined;
}

function mapTrainingBlockedCandidates(
  value: unknown,
  fallback: ActiveTrainingCardRoutingStateView["blockedCandidates"],
): ActiveTrainingCardRoutingStateView["blockedCandidates"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Array.isArray(value)) {
    return fallback;
  }

  return value.reduce<TrainingBlockedCardCandidateStateView[]>((items, entry) => {
    const record = asRecord(entry);
    const cardId = asString(record?.card_id) ?? asString(record?.cardId);
    const title = asString(record?.title);
    const type = toTrainingCardType(asString(record?.type) ?? asString(record?.card_type));
    if (!cardId || !title || !type) {
      return items;
    }
    items.push({
      cardId,
      type,
      title,
      reasons: asStringArray(record?.reasons) ?? [],
    });
    return items;
  }, []);
}

function mapTrainingEventLedger(
  value: unknown,
  fallback: WorkspaceTrainingStateView["trainingEventLedger"],
): WorkspaceTrainingStateView["trainingEventLedger"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Array.isArray(value)) {
    return fallback;
  }

  return value.reduce<TrainingEventLedgerEntryStateView[]>((items, entry) => {
    const record = asRecord(entry);
    if (!record) {
      return items;
    }
    const mapped: TrainingEventLedgerEntryStateView = {
      eventId: asString(record.event_id) ?? asString(record.eventId) ?? undefined,
      eventType: asString(record.event_type) ?? asString(record.eventType) ?? undefined,
      candidateId: asString(record.candidate_id) ?? asString(record.candidateId) ?? undefined,
      candidateStatus:
        asString(record.candidate_status) ?? asString(record.candidateStatus) ?? undefined,
      candidateStatusReason:
        asString(record.candidate_status_reason) ??
        asString(record.candidateStatusReason) ??
        undefined,
      candidateContinueIn:
        toTrainingContinueIn(
          asString(record.candidate_continue_in) ?? asString(record.candidateContinueIn),
        ) ?? undefined,
      candidateType:
        toTrainingConversationCandidateType(
          asString(record.candidate_type) ?? asString(record.candidateType),
        ) ?? undefined,
      selectedCardId:
        asString(record.selected_card_id) ?? asString(record.selectedCardId) ?? undefined,
      selectedCardType:
        toTrainingCardType(
          asString(record.selected_card_type) ?? asString(record.selectedCardType),
        ) ?? undefined,
      selectedCardTitle:
        asString(record.selected_card_title) ?? asString(record.selectedCardTitle) ?? undefined,
      cardCandidateId:
        asString(record.card_candidate_id) ?? asString(record.cardCandidateId) ?? undefined,
      cardCandidateType:
        toTrainingCardType(
          asString(record.card_candidate_type) ?? asString(record.cardCandidateType),
        ) ?? undefined,
      cardCandidateTitle:
        asString(record.card_candidate_title) ?? asString(record.cardCandidateTitle) ?? undefined,
      whyThisCard:
        asString(record.why_this_card) ?? asString(record.whyThisCard) ?? undefined,
      learnerDeliverables:
        asStringArray(record.learner_deliverables ?? record.learnerDeliverables) ?? undefined,
      verificationSteps:
        asStringArray(record.verification_steps ?? record.verificationSteps) ?? undefined,
      successSignal:
        asString(record.success_signal) ?? asString(record.successSignal) ?? undefined,
      expectedSymbols:
        asStringArray(record.expected_symbols ?? record.expectedSymbols) ?? undefined,
      filesToTouch:
        asStringArray(record.files_to_touch ?? record.filesToTouch) ?? undefined,
      returnWith: asString(record.return_with) ?? asString(record.returnWith) ?? undefined,
      nextAfterCompletion:
        asString(record.next_after_completion) ??
        asString(record.nextAfterCompletion) ??
        undefined,
      fallbackAction:
        asString(record.fallback_action) ?? asString(record.fallbackAction) ?? undefined,
      planEvidenceId:
        asString(record.plan_evidence_id) ?? asString(record.planEvidenceId) ?? undefined,
      reviewArtifactId:
        asString(record.review_artifact_id) ?? asString(record.reviewArtifactId) ?? undefined,
      reviewArtifactStatus:
        asString(record.review_artifact_status) ??
        asString(record.reviewArtifactStatus) ??
        undefined,
      reviewRecoveryMode:
        asString(record.review_recovery_mode) ??
        asString(record.reviewRecoveryMode) ??
        undefined,
      judgedAt: asString(record.judged_at) ?? asString(record.judgedAt) ?? undefined,
      sourceChain: asStringArray(record.source_chain ?? record.sourceChain) ?? undefined,
      returnMode:
        toTrainingReturnMode(asString(record.return_mode) ?? asString(record.returnMode)) ??
        undefined,
      returnSummary:
        asString(record.return_summary) ?? asString(record.returnSummary) ?? undefined,
      candidateTargetKind:
        asString(record.candidate_target_kind) ?? asString(record.candidateTargetKind) ?? undefined,
      candidateTargetId:
        asString(record.candidate_target_id) ?? asString(record.candidateTargetId) ?? undefined,
      candidateProjectScope:
        toTrainingProjectScope(
          asString(record.candidate_project_scope) ?? asString(record.candidateProjectScope),
        ) ?? undefined,
      candidateBlockedBy:
        asString(record.candidate_blocked_by) ?? asString(record.candidateBlockedBy) ?? undefined,
      candidateAcceptedInto:
        asString(record.candidate_accepted_into) ??
        asString(record.candidateAcceptedInto) ??
        undefined,
      candidateWhyNow:
        asString(record.candidate_why_now) ?? asString(record.candidateWhyNow) ?? undefined,
      candidateTitle:
        asString(record.candidate_title) ?? asString(record.candidateTitle) ?? undefined,
      statusSummary:
        asString(record.status_summary) ?? asString(record.statusSummary) ?? undefined,
      statusDetail:
        asString(record.status_detail) ?? asString(record.statusDetail) ?? undefined,
      statusKind: asString(record.status_kind) ?? asString(record.statusKind) ?? undefined,
      blockedCandidates: mapTrainingBlockedCandidates(
        record.blocked_candidates ?? record.blockedCandidates,
        undefined,
      ),
      createdAt: asString(record.created_at) ?? asString(record.createdAt) ?? undefined,
    };

    if (hasTrainingEventLedgerEntryContent(mapped)) {
      items.push(mapped);
    }
    return items;
  }, []);
}

function mapReviewArtifact(
  value: unknown,
  fallback: WorkspaceTrainingStateView["reviewArtifact"],
): WorkspaceTrainingStateView["reviewArtifact"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: ReviewArtifactStateView = {
    id: asString(record.id) ?? fallback?.id,
    title: asString(record.title) ?? fallback?.title,
    focusArea: asString(record.focus_area) ?? asString(record.focusArea) ?? fallback?.focusArea,
    source: asString(record.source) ?? fallback?.source,
    status: asString(record.status) ?? fallback?.status,
    summary: normalizeCoachSurfaceText(record.summary) ?? fallback?.summary,
    rootCause: asString(record.root_cause) ?? asString(record.rootCause) ?? fallback?.rootCause,
    guardrail: asString(record.guardrail) ?? fallback?.guardrail,
    nextSelfImplementationRule:
      asString(record.next_self_implementation_rule) ??
      asString(record.nextSelfImplementationRule) ??
      fallback?.nextSelfImplementationRule,
    recommendedRecoveryMode:
      asString(record.recommended_recovery_mode) ??
      asString(record.recommendedRecoveryMode) ??
      fallback?.recommendedRecoveryMode,
    recommendedActions:
      asStringArray(record.recommended_actions ?? record.recommendedActions) ??
      fallback?.recommendedActions,
    verifiedResult:
      asString(record.verified_result) ?? asString(record.verifiedResult) ?? fallback?.verifiedResult,
    blockedReason:
      asString(record.blocked_reason) ?? asString(record.blockedReason) ?? fallback?.blockedReason,
    partialProgress:
      asString(record.partial_progress) ??
      asString(record.partialProgress) ??
      fallback?.partialProgress,
    lastAction:
      asString(record.last_action) ?? asString(record.lastAction) ?? fallback?.lastAction,
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
  };

  return hasReviewArtifactContent(mapped) ? mapped : undefined;
}

function mapScenarioLab(
  value: unknown,
  fallback: WorkspaceTrainingStateView["scenarioLab"],
): WorkspaceTrainingStateView["scenarioLab"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: ScenarioLabStateView = {
    id: asString(record.id) ?? fallback?.id,
    title: asString(record.title) ?? fallback?.title,
    focusArea: asString(record.focus_area) ?? asString(record.focusArea) ?? fallback?.focusArea,
    status: asString(record.status) ?? fallback?.status,
    successSignal:
      asString(record.success_signal) ?? asString(record.successSignal) ?? fallback?.successSignal,
    reviewOutcome:
      asString(record.review_outcome) ?? asString(record.reviewOutcome) ?? fallback?.reviewOutcome,
    learnerDeliverables:
      asStringArray(record.learner_deliverables ?? record.learnerDeliverables) ??
      fallback?.learnerDeliverables,
    verificationSteps:
      asStringArray(record.verification_steps ?? record.verificationSteps) ??
      fallback?.verificationSteps,
    migrateBackGuidance:
      asStringArray(record.migrate_back_guidance ?? record.migrateBackGuidance) ??
      fallback?.migrateBackGuidance,
    dependencyKeys:
      asStringArray(record.dependency_keys ?? record.dependencyKeys) ?? fallback?.dependencyKeys,
    relatedApis:
      asStringArray(record.related_apis ?? record.relatedApis) ?? fallback?.relatedApis,
    lastAction:
      asString(record.last_action) ?? asString(record.lastAction) ?? fallback?.lastAction,
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
  };

  return hasScenarioLabContent(mapped) ? mapped : undefined;
}

function mapTheoryDrill(
  value: unknown,
  fallback: WorkspaceTrainingStateView["theoryDrill"],
): WorkspaceTrainingStateView["theoryDrill"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  const record = asRecord(value);
  if (!record) {
    return fallback;
  }

  const mapped: TheoryDrillStateView = {
    id: asString(record.id) ?? fallback?.id,
    title: asString(record.title) ?? fallback?.title,
    focusArea: asString(record.focus_area) ?? asString(record.focusArea) ?? fallback?.focusArea,
    status: asString(record.status) ?? fallback?.status,
    summary: normalizeCoachSurfaceText(record.summary) ?? fallback?.summary,
    successSignal:
      asString(record.success_signal) ?? asString(record.successSignal) ?? fallback?.successSignal,
    returnWith:
      asString(record.return_with) ?? asString(record.returnWith) ?? fallback?.returnWith,
    questions: mapTheoryDrillQuestions(record.questions, fallback?.questions),
    lastAction:
      asString(record.last_action) ?? asString(record.lastAction) ?? fallback?.lastAction,
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt) ?? fallback?.updatedAt,
  };

  return hasTheoryDrillContent(mapped) ? mapped : undefined;
}

function mapTheoryDrillQuestions(
  value: unknown,
  fallback: TheoryDrillStateView["questions"],
): TheoryDrillStateView["questions"] {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Array.isArray(value)) {
    return fallback;
  }

  return value.reduce<TheoryDrillQuestionStateView[]>((items, entry) => {
    const record = asRecord(entry);
    const prompt = asString(record?.prompt);
    if (!prompt) {
      return items;
    }
    items.push({
      id: asString(record?.question_id) ?? asString(record?.questionId) ?? asString(record?.id),
      prompt,
      choices: asStringArray(record?.choices) ?? asStringArray(record?.options) ?? undefined,
      answer: asString(record?.answer) ?? undefined,
      explanation: asString(record?.explanation) ?? undefined,
    });
    return items;
  }, []);
}

function hasWorkspaceTrainingStateContent(value: WorkspaceTrainingStateView): boolean {
  return Boolean(
    value.workspaceId ||
      value.latestConversationHandoff ||
      value.latestTrainingHandoff ||
      value.latestTrainingReliability ||
      value.latestTrainingNextHop ||
      value.latestTrainingSubmode ||
      value.latestLearningFocusArea ||
      value.latestLearningFollowup ||
      value.latestLearningVerifiedResult ||
      value.latestLearningBlocker ||
      value.latestLearningAbandonReason ||
      value.latestLearningPartialProgress ||
      value.selectedCardId ||
      value.selectedCardTitle ||
      value.selectedCardStatus ||
      value.trainingCardCandidates?.length ||
      value.activeTrainingCardRouting ||
      value.trainingEventLedger?.length ||
      value.reviewArtifact ||
      value.scenarioLab ||
      value.theoryDrill ||
      value.dueReviews?.length,
  );
}

function hasTrainingHandoffContent(value: TrainingHandoffStateView): boolean {
  return Boolean(
    value.candidateId ||
      value.candidateType ||
      value.targetKind ||
      value.targetId ||
      value.continueIn ||
      value.acceptedInto ||
      value.handoffStatus ||
      value.handoffSummary ||
      value.blockedBy ||
      value.cardType ||
      value.cardTitle ||
      value.scenarioPack ||
      value.learnerDeliverables?.length ||
      value.verificationSteps?.length ||
      value.successSignal ||
      value.returnWith ||
      value.nextAfterCompletion ||
      value.fallbackAction ||
      value.returnMode ||
      value.returnSummary ||
      value.judgedAt ||
      value.sourceChain?.length ||
      value.coachOnly ||
      value.learningPhase ||
      value.handoffId,
  );
}

function hasTrainingNextHopContent(value: TrainingNextHopStateView): boolean {
  return Boolean(
    value.candidateId ||
      value.candidateType ||
      value.title ||
      value.summary ||
      value.whyNow ||
      value.projectScope ||
      value.continueIn ||
      value.targetKind ||
      value.targetId ||
      value.acceptedInto ||
      value.status ||
      value.statusReason ||
      value.blockedBy ||
      value.handoffStatus ||
      value.handoffSummary ||
      value.cardType ||
      value.cardTitle ||
      value.scenarioPack ||
      value.returnMode ||
      value.returnSummary ||
      value.judgedAt ||
      value.reviewArtifactId ||
      value.reviewArtifactStatus ||
      value.reviewRecoveryMode ||
      value.planEvidenceId ||
      value.nextAfterCompletion ||
      value.fallbackAction ||
      value.sourceChain?.length ||
      value.coachOnly,
  );
}

function hasActiveTrainingCardRoutingContent(value: ActiveTrainingCardRoutingStateView): boolean {
  return Boolean(
      value.selectedCardId ||
      value.selectedCard?.title ||
      value.selectedCard?.type ||
      value.selectedCard?.expectedSymbols?.length ||
      value.selectedCard?.apiHints?.length ||
      value.selectedCard?.learnerDeliverables?.length ||
      value.selectedCard?.verificationSteps?.length ||
      value.selectedCard?.successSignal ||
      value.whyThisCard ||
      value.blockedCandidates?.length ||
      value.fallbackAction ||
      value.candidateCount ||
      value.eligibleCount,
  );
}

function hasTrainingEventLedgerEntryContent(value: TrainingEventLedgerEntryStateView): boolean {
  return Boolean(
    value.eventId ||
      value.eventType ||
      value.candidateId ||
      value.candidateStatus ||
      value.selectedCardId ||
      value.cardCandidateId ||
      value.whyThisCard ||
      value.learnerDeliverables?.length ||
      value.verificationSteps?.length ||
      value.successSignal ||
      value.expectedSymbols?.length ||
      value.filesToTouch?.length ||
      value.returnWith ||
      value.nextAfterCompletion ||
      value.fallbackAction ||
      value.reviewArtifactId ||
      value.planEvidenceId ||
      value.statusSummary ||
      value.statusDetail ||
      value.createdAt,
  );
}

function hasReviewArtifactContent(value: ReviewArtifactStateView): boolean {
  return Boolean(
    value.id ||
      value.title ||
      value.focusArea ||
      value.source ||
      value.status ||
      value.summary ||
      value.rootCause ||
      value.guardrail ||
      value.nextSelfImplementationRule ||
      value.recommendedRecoveryMode ||
      value.recommendedActions?.length ||
      value.verifiedResult ||
      value.blockedReason ||
      value.partialProgress ||
      value.lastAction ||
      value.updatedAt,
  );
}

function hasScenarioLabContent(value: ScenarioLabStateView): boolean {
  return Boolean(
    value.id ||
      value.title ||
      value.focusArea ||
      value.status ||
      value.successSignal ||
      value.reviewOutcome ||
      value.learnerDeliverables?.length ||
      value.verificationSteps?.length ||
      value.migrateBackGuidance?.length ||
      value.dependencyKeys?.length ||
      value.relatedApis?.length ||
      value.lastAction ||
      value.updatedAt,
  );
}

function hasTheoryDrillContent(value: TheoryDrillStateView): boolean {
  return Boolean(
    value.id ||
      value.title ||
      value.focusArea ||
      value.status ||
      value.summary ||
      value.successSignal ||
      value.returnWith ||
      value.questions?.length ||
      value.lastAction ||
      value.updatedAt,
  );
}

function asMemoryWorkspace(value: unknown): BootstrapData["memory"]["workspace"] | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const coachDefaultsRecord = asRecord(record.coach_defaults);
  const toggles = asRecord(coachDefaultsRecord?.workspace_memory_toggles ?? record.workspace_memory_toggles);
  const coachDefaults: CoachDefaults | undefined =
    coachDefaultsRecord || record.memory_scope || record.working_set_mode || record.review_cadence || record.review_reminder_mode
      ? {
          memoryScope: toMemoryScope(asString(coachDefaultsRecord?.memory_scope ?? record.memory_scope)) ?? "project",
          workingSetMode:
            toWorkingSetMode(asString(coachDefaultsRecord?.working_set_mode ?? record.working_set_mode)) ?? "balanced",
          reviewCadence:
            toReviewCadence(asString(coachDefaultsRecord?.review_cadence ?? record.review_cadence)) ?? "steady",
          reviewReminderMode:
            toReviewReminderMode(
              asString(coachDefaultsRecord?.review_reminder_mode ?? record.review_reminder_mode),
            ) ?? "due",
          workspaceMemoryToggles: {
            decisions: asBoolean(toggles?.decisions) ?? true,
            patterns: asBoolean(toggles?.patterns) ?? true,
            resources: asBoolean(toggles?.resources) ?? true,
          },
        }
      : undefined;

  return {
    responseLanguage: toComposerLanguage(asString(record.response_language)),
    answerMode: toAnswerPolicy(asString(record.answer_mode)),
    followCurrentFile: asBoolean(record.follow_current_file) ?? undefined,
    contextDetail: toContextDetail(asString(record.context_detail)),
    includeCurrentFile: asBoolean(record.include_current_file) ?? undefined,
    includeSelection: asBoolean(record.include_selection) ?? undefined,
    includeDiagnostics: asBoolean(record.include_diagnostics) ?? undefined,
    includeRelatedFiles: asBoolean(record.include_related_files) ?? undefined,
    learnerName: asString(record.learner_name) ?? asString(record.learnerName),
    projectContext: asString(record.project_context) ?? asString(record.projectContext),
    preferredRhythm: asString(record.preferred_rhythm) ?? asString(record.preferredRhythm),
    preferredLearningMode:
      asString(record.preferred_learning_mode) ?? asString(record.preferredLearningMode),
    onboardingRequest: asString(record.onboarding_request) ?? asString(record.onboardingRequest),
    latestTransferState: normalizeTransferSkillStateRecord(
      record.latest_transfer_state ?? record.latestTransferState,
    ),
    workspaceId: asString(record.workspace_id) ?? asString(record.workspaceId),
    latestPlanRuntime: (() => {
      const workspaceId = asString(record.workspace_id) ?? asString(record.workspaceId);
      const raw = record.latest_plan_runtime ?? record.latestPlanRuntime;
      return workspaceId ? selectPlanRuntimeForScope(raw, { workspaceId }) : normalizePlanRuntimeRecovery(raw);
    })(),
    latestProviderCapability: (() => {
      const workspaceId = asString(record.workspace_id) ?? asString(record.workspaceId);
      const recordValue = normalizeProviderCapabilityRecovery(
        record.latest_provider_capability ?? record.latestProviderCapability,
      );
      return workspaceId ? selectProviderCapabilityForScope(recordValue, { workspaceId }) : recordValue;
    })(),
    latestStreamingCheckpoint: (() => {
      const workspaceId = asString(record.workspace_id) ?? asString(record.workspaceId);
      const raw = record.latest_streaming_checkpoint ?? record.latestStreamingCheckpoint;
      return workspaceId
        ? selectStreamingCheckpointForScope(raw, { workspaceId })
        : recoverStreamingCheckpointAfterRestart(raw);
    })(),
    coachDefaults,
  };
}

function mapFirstLookSummary(value: unknown): FirstLookSummaryView | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const folderRole = asString(record.folder_role) ?? asString(record.folderRole);
  const projectTypeGuess = asString(record.project_type_guess) ?? asString(record.projectTypeGuess);
  const confidence = asNumber(record.confidence);
  const whyThisGuess = asString(record.why_this_guess) ?? asString(record.whyThisGuess) ?? "";
  const entryPoints = asStringArray(record.entry_points) ?? asStringArray(record.entryPoints) ?? [];
  const directoryAnchors =
    asStringArray(record.directory_anchors) ?? asStringArray(record.directoryAnchors) ?? [];
  const coreModulesOrMaterials =
    asStringArray(record.core_modules_or_materials) ?? asStringArray(record.coreModulesOrMaterials) ?? [];
  const riskZones = asStringArray(record.risk_zones) ?? asStringArray(record.riskZones) ?? [];
  const trainingOpportunities =
    asStringArray(record.training_opportunities) ?? asStringArray(record.trainingOpportunities) ?? [];
  const unknowns = asStringArray(record.unknowns) ?? [];
  const recommendedNextStep =
    asString(record.recommended_next_step) ?? asString(record.recommendedNextStep) ?? "";
  const classificationMethod = asString(record.classification_method) ?? asString(record.classificationMethod);
  const classifiedAt = asString(record.classified_at) ?? asString(record.classifiedAt) ?? "";

  if (
    !folderRole &&
    !projectTypeGuess &&
    confidence === undefined &&
    !whyThisGuess &&
    entryPoints.length === 0 &&
    directoryAnchors.length === 0 &&
    coreModulesOrMaterials.length === 0 &&
    riskZones.length === 0 &&
    trainingOpportunities.length === 0 &&
    unknowns.length === 0 &&
    !recommendedNextStep &&
    !classificationMethod &&
    !classifiedAt
  ) {
    return undefined;
  }

  return {
    folderRole: (folderRole as FirstLookSummaryView["folderRole"]) ?? "mixed_uncertain",
    projectTypeGuess: (projectTypeGuess as FirstLookSummaryView["projectTypeGuess"]) ?? "unknown",
    confidence: confidence ?? 0,
    whyThisGuess,
    entryPoints,
    directoryAnchors,
    coreModulesOrMaterials,
    riskZones,
    trainingOpportunities,
    unknowns,
    recommendedNextStep,
    classificationMethod:
      classificationMethod === "llm_enhanced" ? "llm_enhanced" : "heuristic",
    classifiedAt: classifiedAt || new Date().toISOString(),
  };
}

function mapWorkspaceUnderstanding(value: unknown): WorkspaceUnderstandingView | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const firstLookSummary = mapFirstLookSummary(
    record.first_look_summary ?? record.firstLookSummary,
  );
  const repoSummary = asString(record.repo_summary) ?? asString(record.repoSummary) ?? "";
  const entryPoints = asStringArray(record.entry_points) ?? asStringArray(record.entryPoints) ?? [];
  const featureLanes = asStringArray(record.feature_lanes) ?? asStringArray(record.featureLanes) ?? [];
  const riskZones = asStringArray(record.risk_zones) ?? asStringArray(record.riskZones) ?? [];
  const trainingOpportunities =
    asStringArray(record.training_opportunities) ?? asStringArray(record.trainingOpportunities) ?? [];
  const resourceBrief = asString(record.resource_brief) ?? asString(record.resourceBrief) ?? "";

  if (
    !repoSummary &&
    entryPoints.length === 0 &&
    featureLanes.length === 0 &&
    riskZones.length === 0 &&
    trainingOpportunities.length === 0 &&
    !resourceBrief &&
    !firstLookSummary
  ) {
    return undefined;
  }

  return {
    repoSummary: repoSummary || "",
    entryPoints,
    featureLanes,
    riskZones,
    trainingOpportunities,
    resourceBrief: resourceBrief || "",
    firstLookSummary,
    updatedAt:
      asString(record.updated_at) ??
      asString(record.updatedAt) ??
      new Date().toISOString(),
  };
}

function mapImplementationGuide(value: unknown): ImplementationGuide | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  return {
    ideaSummary: asString(record.idea_summary) ?? "",
    scopeBoundary: asString(record.scope_boundary) ?? "",
    mvpDefinition: asString(record.mvp_definition) ?? "",
    currentStep: normalizeCoachSurfaceText(record.current_step) ?? "",
    nextSteps: asStringArray(record.next_steps) ?? [],
    validationStrategy: asStringArray(record.validation_strategy) ?? [],
    openQuestions: asStringArray(record.open_questions) ?? [],
    codebaseEntryPoints: asStringArray(record.codebase_entry_points) ?? undefined,
    riskNotes: asStringArray(record.risk_notes) ?? undefined,
    teachingGoal: normalizeCoachSurfaceText(record.teaching_goal) ?? undefined,
    successSignal: asString(record.success_signal) ?? undefined,
    fallbackStep: normalizeCoachSurfaceText(record.fallback_step) ?? undefined,
  };
}

function mapProjectIdeas(value: unknown): ProjectIdea[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const ideas = value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item, index) => ({
      id: asString(item.id) ?? `project-idea-${index + 1}`,
      title: asString(item.title) ?? "Project idea",
      summary: normalizeCoachSurfaceText(item.summary) ?? "",
      sourceArea: asString(item.source_area) ?? "",
      ideaKind: toProjectIdeaKind(asString(item.idea_kind)),
      learningValue: asString(item.learning_value) ?? "",
      engineeringValue: asString(item.engineering_value) ?? "",
      difficulty: asString(item.difficulty) ?? "",
      suggestedScope: asString(item.suggested_scope) ?? "",
      firstStep: asString(item.first_step) ?? "",
      acceptanceSignals: asStringArray(item.acceptance_signals) ?? [],
      whyNow: normalizeCoachSurfaceText(item.why_now) ?? "",
    }));
  return ideas.length ? ideas : undefined;
}

function mapProjectAdaptationGuide(value: unknown): ProjectAdaptationGuide | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  return {
    targetOutcome: asString(record.target_outcome) ?? "",
    currentConstraints: asStringArray(record.current_constraints) ?? [],
    affectedAreas: asStringArray(record.affected_areas) ?? [],
    preserveAreas: asStringArray(record.preserve_areas) ?? [],
    firstMigrationStep: asString(record.first_migration_step) ?? "",
    migrationSequence: asStringArray(record.migration_sequence) ?? [],
    validationCheckpoints: asStringArray(record.validation_checkpoints) ?? [],
    rollbackNotes: asStringArray(record.rollback_notes) ?? [],
  };
}

function mapPrincipleNote(value: unknown): PrincipleNote | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  return {
    currentPrinciple:
      asString(record.current_principle) ?? asString(record.principle) ?? "",
    whyItMatters:
      asString(record.why_it_matters) ?? asString(record.why_this_approach) ?? "",
    commonMistake:
      asString(record.common_mistake) ?? asString(record.common_wrong_intuition) ?? "",
    applyNow:
      asString(record.apply_now) ?? asString(record.follow_up_exercise) ?? "",
    transferTargets:
      asStringArray(record.transfer_targets) ?? asStringArray(record.related_checks) ?? [],
    concreteAnchor: asString(record.concrete_anchor) ?? "",
    transferableLesson:
      asString(record.transferable_lesson) ?? asString(record.transfer_lesson) ?? "",
    relatedChecks: asStringArray(record.related_checks) ?? [],
    sourceAssetTitle: asString(record.source_asset_title) ?? "",
  };
}

function mapResources(value: unknown): ResourceRecord[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => {
      const parseStatus = asString(item.parse_status);
      const indexStatus = asString(item.index_status);
      return {
        id: asString(item.id) ?? `resource-${Math.random().toString(36).slice(2, 8)}`,
        title: asString(item.name) ?? "Resource",
        kind: toResourceKind(asString(item.kind)),
        status:
          parseStatus === "failed" || indexStatus === "failed"
            ? "attention"
            : parseStatus !== "parsed" || indexStatus !== "indexed"
              ? "indexing"
              : "ready",
        summary: asString(item.summary) ?? "",
        source: asString(item.source),
        sandboxPath: asString(item.sandbox_path) ?? asString(item.sandboxPath) ?? undefined,
        sandboxOrigin: asString(item.sandbox_origin) ?? asString(item.sandboxOrigin) ?? undefined,
        sandboxSyncedAt: asString(item.sandbox_synced_at) ?? asString(item.sandboxSyncedAt) ?? undefined,
        sandboxDirty: asBoolean(item.sandbox_dirty) ?? asBoolean(item.sandboxDirty) ?? undefined,
        canonicalSource: asString(item.canonical_source) ?? asString(item.canonicalSource) ?? undefined,
        collectionPath: asString(item.collection_path) ?? asString(item.collectionPath) ?? undefined,
        collectionRoot: asString(item.collection_root) ?? asString(item.collectionRoot) ?? undefined,
        sourceType: asString(item.source_type) ?? asString(item.sourceType) ?? undefined,
        fileType: asString(item.file_type) ?? asString(item.fileType) ?? undefined,
        trustState: asString(item.trust_state) ?? asString(item.trustState) ?? undefined,
        trustScore: asNumber(item.trust_score) ?? asNumber(item.trustScore) ?? undefined,
        freshness: normalizePreviewFreshness(asString(item.freshness)),
        indexState: indexStatus,
        citationId: asString(item.citation_id) ?? asString(item.citationId) ?? undefined,
        previewTier: normalizePreviewTier(asString(item.preview_tier) ?? asString(item.previewTier)),
        previewKind: asString(item.preview_kind) ?? asString(item.previewKind) ?? undefined,
        rankScore: asNumber(item.rank_score) ?? asNumber(item.rankScore) ?? undefined,
        rankReasons: asStringArray(item.rank_reasons ?? item.rankReasons),
        matchSummary: asString(item.match_summary) ?? asString(item.matchSummary) ?? undefined,
        canInjectTrainingCard:
          asBoolean(item.can_inject_training_card) ?? asBoolean(item.canInjectTrainingCard) ?? undefined,
        qualityFlags: asStringArray(item.quality_flags ?? item.qualityFlags),
        tags: asStringArray(item.tags),
        warnings: asStringArray(item.warnings),
        sourceItems: asStringArray(item.source_items ?? item.sourceItems),
        extractedArtifactPath:
          asString(item.extracted_artifact_path) ?? asString(item.extractedArtifactPath) ?? undefined,
        updatedAt: asString(item.updated_at) ?? asString(item.updatedAt) ?? undefined,
      };
    });
}

function normalizePreviewResourceSearchResult(
  value: unknown,
  fallbackQuery: string,
  requestId?: string,
): ResourceSearchState {
  const record = asRecord(value);
  const rawHits = Array.isArray(record?.hits)
    ? record.hits
    : Array.isArray(record?.results)
      ? record.results
      : [];
  const hits = rawHits
    .map((item) => normalizePreviewResourceSearchHit(item))
    .filter((item): item is ResourceSearchState["hits"][number] => Boolean(item));
  return {
    ...(requestId ? { requestId } : {}),
    workspaceId: asString(record?.workspace_id) ?? asString(record?.workspaceId),
    query: asString(record?.query) ?? fallbackQuery,
    total: asNumber(record?.total) ?? hits.length,
    rankingStrategy: asString(record?.ranking_strategy) ?? asString(record?.rankingStrategy) ?? "lexical_first",
    filters: normalizePreviewSearchFilters(record?.filters),
    hits,
  };
}

function normalizePreviewSearchFilters(value: unknown): Record<string, string> {
  const record = asRecord(value);
  if (!record) {
    return {};
  }
  const filters: Record<string, string> = {};
  for (const [key, rawValue] of Object.entries(record)) {
    if (typeof rawValue === "string" && rawValue.trim()) {
      filters[key] = rawValue.trim();
    }
  }
  return filters;
}

function normalizePreviewResourceSearchHit(
  value: unknown,
): ResourceSearchState["hits"][number] | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const id = asString(record.id) ?? asString(record.resource_id) ?? asString(record.resourceId);
  const title =
    asString(record.title) ??
    asString(record.name) ??
    asString(record.resource_title) ??
    asString(record.resourceTitle);
  if (!id || !title) {
    return undefined;
  }
  const indexState = asString(record.index_state) ?? asString(record.indexState);
  const rawStatus = asString(record.status) ?? asString(record.parse_status) ?? asString(record.parseStatus);
  const status: ResourceRecord["status"] =
    rawStatus === "ready" || rawStatus === "indexing" || rawStatus === "attention"
      ? rawStatus
      : indexState === "indexed"
        ? "ready"
        : indexState === "failed"
          ? "attention"
          : "indexing";
  return {
    id,
    title,
    kind: toResourceKind(asString(record.kind) ?? asString(record.preview_kind) ?? asString(record.previewKind)),
    status,
    summary:
      asString(record.summary) ??
      asString(record.match_summary) ??
      asString(record.matchSummary) ??
      "",
    source: asString(record.source) ?? asString(record.path),
    collectionPath: asString(record.collection_path) ?? asString(record.collectionPath),
    collectionRoot: asString(record.collection_root) ?? asString(record.collectionRoot),
    canonicalSource: asString(record.canonical_source) ?? asString(record.canonicalSource),
    sourceType: asString(record.source_type) ?? asString(record.sourceType),
    fileType: asString(record.file_type) ?? asString(record.fileType),
    projectScope: asString(record.project_scope) ?? asString(record.projectScope),
    trustState: asString(record.trust_state) ?? asString(record.trustState),
    trustScore: asNumber(record.trust_score) ?? asNumber(record.trustScore),
    freshness: normalizePreviewFreshness(asString(record.freshness)),
    indexState,
    citationId: asString(record.citation_id) ?? asString(record.citationId),
    previewTier: normalizePreviewTier(asString(record.preview_tier) ?? asString(record.previewTier)),
    previewKind: asString(record.preview_kind) ?? asString(record.previewKind),
    rankScore: asNumber(record.rank_score) ?? asNumber(record.rankScore),
    rankReasons: asStringArray(record.rank_reasons ?? record.rankReasons),
    matchSummary: asString(record.match_summary) ?? asString(record.matchSummary),
    canInjectTrainingCard:
      asBoolean(record.can_inject_training_card) ?? asBoolean(record.canInjectTrainingCard),
    qualityFlags: asStringArray(record.quality_flags ?? record.qualityFlags),
    sandboxPath: asString(record.sandbox_path) ?? asString(record.sandboxPath),
    sandboxOrigin: asString(record.sandbox_origin) ?? asString(record.sandboxOrigin),
    sandboxSyncedAt: asString(record.sandbox_synced_at) ?? asString(record.sandboxSyncedAt),
    sandboxDirty: asBoolean(record.sandbox_dirty) ?? asBoolean(record.sandboxDirty),
    extractedArtifactPath:
      asString(record.extracted_artifact_path) ?? asString(record.extractedArtifactPath),
    updatedAt: asString(record.updated_at) ?? asString(record.updatedAt),
    sourceItems: asStringArray(record.source_items ?? record.sourceItems),
    tags: asStringArray(record.tags),
    warnings: asStringArray(record.warnings),
  };
}

function normalizePreviewFreshness(value: string | undefined): ResourceRecord["freshness"] {
  return value === "fresh" || value === "stale" || value === "unknown" ? value : undefined;
}

function normalizePreviewTier(value: string | undefined): ResourceRecord["previewTier"] {
  return value === "rich" || value === "converted" || value === "metadata" ? value : undefined;
}

function mapConversationMessage(value: unknown, index: number): ConversationMessage {
  const message = asRecord(value);
  const metadata = asRecord(message?.metadata);
  const roleValue = asString(message?.role);
  const role: ConversationMessage["role"] =
    roleValue === "user" || roleValue === "system" || roleValue === "assistant"
      ? roleValue
      : "assistant";
  return {
    id: asString(message?.id) ?? `message-${index + 1}`,
    role,
    author:
      role === "user"
        ? ""
        : role === "system"
          ? "System"
          : "Trainer",
    body: asString(message?.content) ?? "",
    timestamp: formatTimestamp(asString(message?.created_at) ?? asString(message?.timestamp)),
    sourceView: normalizeConversationSourceView(asString(metadata?.active_view)),
    parts: mapMessageParts(metadata),
    artifacts: mapArtifacts(metadata?.artifacts),
    contextNote: asString(metadata?.context_note) ?? undefined,
    support: buildSupport(metadata),
  };
}

function mapMessageParts(
  metadata: Record<string, unknown> | undefined,
): ConversationMessage["parts"] | undefined {
  if (!metadata) {
    return undefined;
  }
  return normalizeTrainerMessageParts(metadata.parts);
}

function mapArtifacts(value: unknown) {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const artifacts: NonNullable<ConversationMessage["artifacts"]> = value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({
      kind: toArtifactKind(asString(item.kind)),
      title: asString(item.title) ?? "Artifact",
      summary: normalizeCoachSurfaceText(item.summary) ?? undefined,
      content: asString(item.content) ?? undefined,
      bullets: asStringArray(item.bullets) ?? [],
      teaser: asString(item.teaser) ?? undefined,
      recommendedAction: toSuggestedActionType(asString(item.recommended_action)),
      rationale: asString(item.rationale) ?? undefined,
      focusArea: normalizeCoachSurfaceText(item.focus_area) ?? undefined,
      verification: asStringArray(item.verification) ?? [],
      metadata: asRecord(item.metadata),
    }));
  return artifacts.length > 0 ? artifacts : undefined;
}

function buildSupport(metadata: Record<string, unknown> | undefined) {
  if (!metadata) {
    return undefined;
  }
  const coachFocus = asRecord(metadata.coach_focus);
  const lines = [
    coachFocus && normalizeCoachSurfaceText(coachFocus.current_focus)
      ? `Current focus: ${normalizeCoachSurfaceText(coachFocus.current_focus)}`
      : undefined,
    coachFocus && normalizeCoachSurfaceText(coachFocus.next_step)
      ? `Next step: ${normalizeCoachSurfaceText(coachFocus.next_step)}`
      : undefined,
    coachFocus && normalizeCoachSurfaceText(coachFocus.review_rhythm)
      ? `Review rhythm: ${normalizeCoachSurfaceText(coachFocus.review_rhythm)}`
      : undefined,
  ].filter((line): line is string => Boolean(line));
  if (lines.length === 0) {
    return undefined;
  }
  return {
    preview: lines[0],
    lines,
  };
}

function toArtifactKind(value: string | undefined): ConversationArtifactKind {
  if (
    value === "task" ||
    value === "plan" ||
    value === "evaluation" ||
    value === "note" ||
    value === "idea_implementation" ||
    value === "project_idea" ||
    value === "project_adaptation" ||
    value === "project_source" ||
    value === "principle" ||
    value === "review" ||
    value === "plan_update" ||
    value === "next_step"
  ) {
    return value;
  }
  return "note";
}

function toSuggestedActionType(value: string | undefined): SuggestedAction["action"] | undefined {
  if (
    value === "plan" ||
    value === "next_task" ||
    value === "review" ||
    value === "hint" ||
    value === "retry_review" ||
    value === "task"
  ) {
    return value;
  }
  return undefined;
}

function asDueReviews(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({
      concept: asString(item.concept) ?? "review",
      reason: asString(item.reason) ?? "",
      dueAt: asString(item.due_at) ?? undefined,
      source: toReviewSource(asString(item.source)),
      severity: toReviewSeverity(asString(item.severity)),
      surfaceMode: toReviewSurfaceMode(asString(item.surface_mode)),
      taskHint: asString(item.task_hint) ?? undefined,
      focusArea: asString(item.focus_area) ?? undefined,
      linkedContext: toLinkedContext(item.linked_context),
      intervalDays: asNumber(item.interval_days) ?? undefined,
      masteryScore: asNumber(item.mastery_score) ?? undefined,
    }));
}

function toReviewSurfaceMode(
  value: string | undefined,
): "due" | "ahead" | "digest" | undefined {
  if (value === "due" || value === "ahead" || value === "digest") {
    return value;
  }
  return undefined;
}

function toLinkedContext(value: unknown): string[] | undefined {
  if (Array.isArray(value)) {
    const entries = value
      .map((item) => asString(item))
      .filter((item): item is string => Boolean(item?.trim()))
      .map((item) => item.trim());
    return entries.length ? entries : undefined;
  }
  const single = asString(value)?.trim();
  if (!single) {
    return undefined;
  }
  return single
    .split("|")
    .map((part) => part.trim())
    .filter(Boolean);
}

function toReviewSource(
  value: string | undefined,
): "weakness" | "mastery" | "reflection" | "plan" {
  if (value === "mastery" || value === "reflection" || value === "plan") {
    return value;
  }
  return "weakness";
}

function toReviewSeverity(value: string | undefined): "low" | "medium" | "high" {
  if (value === "low" || value === "high") {
    return value;
  }
  return "medium";
}

function asCoachingState(value: unknown) {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const scenario = asString(record.scenario);
  const answerMode = asString(record.answer_mode);
  const learnerSignal = asString(record.learner_signal);
  return {
    scenario:
      scenario === "idea_implementation" ||
      scenario === "project_idea" ||
      scenario === "project_adaptation" ||
      scenario === "project_sourcing" ||
      scenario === "remote_workspace" ||
      scenario === "debug_loop" ||
      scenario === "function_guidance" ||
      scenario === "principle" ||
      scenario === "review" ||
      scenario === "plan" ||
      scenario === "task" ||
      scenario === "next_task"
        ? scenario
        : "general",
    answerMode:
      answerMode === "balanced" || answerMode === "direct" ? answerMode : "guided",
    learnerSignal:
      learnerSignal === "blocked" ||
      learnerSignal === "uncertain" ||
      learnerSignal === "curious"
        ? learnerSignal
        : "steady",
    summary: normalizeCoachSurfaceText(record.summary) ?? "",
    nextStep: normalizeCoachSurfaceText(record.next_step) ?? "",
    encouragement: normalizeCoachSurfaceText(record.encouragement) ?? "",
    interventionStrategy: normalizeCoachSurfaceText(record.intervention_strategy) ?? undefined,
    teachingGoal: normalizeCoachSurfaceText(record.teaching_goal) ?? undefined,
    resumeThread: normalizeCoachSurfaceText(record.resume_thread) ?? undefined,
    decision: asString(record.decision) ?? undefined,
    blocker: normalizeCoachSurfaceText(record.blocker) ?? undefined,
    teachingNote: normalizeCoachSurfaceText(record.teaching_note) ?? undefined,
    confidence: asString(record.confidence) ?? undefined,
    evidence: asStringArray(record.evidence) ?? undefined,
    supportStrategy: normalizeCoachSurfaceText(record.support_strategy) ?? undefined,
    updatedAt: asString(record.updated_at) ?? new Date().toISOString(),
  } as const;
}

function asCoachTurn(value: unknown) {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const scenario = asString(record.scenario);
  const learnerSignal = asString(record.learner_signal);
  const tone = asString(record.tone);
  const verbosity = asString(record.verbosity_bias);
  return {
    scenario: toCoachScenario(scenario),
    learnerSignal:
      learnerSignal === "blocked" ||
      learnerSignal === "uncertain" ||
      learnerSignal === "curious"
        ? learnerSignal
        : "steady",
    summary: normalizeCoachSurfaceText(record.summary) ?? "",
    nextStep: normalizeCoachSurfaceText(record.next_step) ?? "",
    encouragement: normalizeCoachSurfaceText(record.encouragement) ?? undefined,
    interventionStrategy: normalizeCoachSurfaceText(record.intervention_strategy) ?? undefined,
    teachingGoal: normalizeCoachSurfaceText(record.teaching_goal) ?? undefined,
    resumeThread: normalizeCoachSurfaceText(record.resume_thread) ?? undefined,
    decision: asString(record.decision) ?? undefined,
    blocker: normalizeCoachSurfaceText(record.blocker) ?? undefined,
    teachingNote: normalizeCoachSurfaceText(record.teaching_note) ?? undefined,
    confidence: asString(record.confidence) ?? undefined,
    evidence: asStringArray(record.evidence) ?? undefined,
    supportStrategy: normalizeCoachSurfaceText(record.support_strategy) ?? undefined,
    decisionReason: asString(record.decision_reason) ?? undefined,
    tone:
      tone === "encouraging" || tone === "concise_rescue" || tone === "reflective"
        ? tone
        : "steady",
    verbosityBias:
      verbosity === "short" || verbosity === "expanded" ? verbosity : "medium",
    activeStage: asString(record.active_stage) ?? undefined,
    activeTask: asString(record.active_task) ?? undefined,
    dueReviewCount: asNumber(record.due_review_count) ?? undefined,
    reviewQueueSummary: normalizeCoachSurfaceText(record.review_queue_summary) ?? undefined,
    failingChecks: asStringArray(record.failing_checks) ?? [],
    artifactKinds: asArtifactKinds(record.artifact_kinds),
    suggestedActionTypes: asSuggestedActionTypes(record.suggested_action_types),
    backgroundMode: "embedded" as const,
  } satisfies CoachTurnSummaryView;
}

function asCoachFocus(value: unknown) {
  const source = asRecord(value);
  const focus = asRecord(source?.coach_focus ?? value);
  if (!focus) {
    return undefined;
  }
  const scenario = asString(focus.scenario);
  return {
    currentFocus: normalizeCoachSurfaceText(focus.current_focus) ?? undefined,
    reviewRhythm: normalizeCoachSurfaceText(focus.review_rhythm) ?? undefined,
    nextStep: normalizeCoachSurfaceText(focus.next_step) ?? undefined,
    activeStage: asString(focus.active_stage) ?? undefined,
    activeTask: asString(focus.active_task) ?? undefined,
    scenario: toCoachScenario(scenario),
    relationshipStage:
      asString(focus.relationship_stage) === "active" ? "active" : asString(focus.relationship_stage) === "intake" ? "intake" : undefined,
    firstTurnPriority: asString(focus.first_turn_priority) ?? undefined,
    strategyPreferenceSummary: normalizeCoachSurfaceText(focus.strategy_preference_summary) ?? undefined,
    continuitySummary: normalizeCoachSurfaceText(focus.continuity_summary) ?? undefined,
    recentTeachingSignals: asStringArray(focus.recent_teaching_signals) ?? [],
    teachingObservations: asStringArray(focus.teaching_observations) ?? [],
    recentWins: asStringArray(focus.recent_wins) ?? [],
    dueReviewCount: asNumber(focus.due_review_count) ?? undefined,
    language: asString(focus.language) ?? undefined,
  } satisfies CoachFocusView;
}

function asPlanRuntimeStatus(value: unknown): BootstrapData["planRuntimeStatus"] | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const currentStage = asRecord(record.current_stage);
  const currentMainThread = asRecord(record.current_main_thread);
  const coachJudgment = asRecord(record.coach_judgment);
  const reviewPoints = Array.isArray(record.review_points)
    ? record.review_points
        .map((item) => {
          const point = asRecord(item);
          if (!point) {
            return undefined;
          }
          return {
            concept: asString(point.concept) ?? "",
            reason: asString(point.reason) ?? "",
            severity:
              asString(point.severity) === "low" ||
              asString(point.severity) === "high" ||
              asString(point.severity) === "medium"
                ? (asString(point.severity) as "low" | "medium" | "high")
                : undefined,
            dueAt: asString(point.due_at) ?? undefined,
            source: asString(point.source) ?? undefined,
            surfaceMode:
              asString(point.surface_mode) === "ahead" ||
              asString(point.surface_mode) === "digest" ||
              asString(point.surface_mode) === "due"
                ? (asString(point.surface_mode) as "due" | "ahead" | "digest")
                : undefined,
            taskHint: asString(point.task_hint) ?? undefined,
            focusArea: asString(point.focus_area) ?? undefined,
            linkedContext: asStringArray(point.linked_context) ?? undefined,
            intervalDays: asNumber(point.interval_days) ?? undefined,
            masteryScore: asNumber(point.mastery_score) ?? undefined,
          };
        })
        .filter(Boolean)
    : [];

  return {
    currentStage: currentStage
      ? {
          id: asString(currentStage.id) ?? undefined,
          title: asString(currentStage.title) ?? undefined,
          goal: asString(currentStage.goal) ?? undefined,
          status: asString(currentStage.status) ?? undefined,
        }
      : undefined,
    currentMainThread: currentMainThread
      ? {
          scenario: asString(currentMainThread.scenario) ?? undefined,
          focusArea: normalizeCoachSurfaceText(currentMainThread.focus_area) ?? undefined,
          summary: normalizeCoachSurfaceText(currentMainThread.summary) ?? undefined,
          nextStep: normalizeCoachSurfaceText(currentMainThread.next_step) ?? undefined,
          blocker: normalizeCoachSurfaceText(currentMainThread.blocker) ?? undefined,
          currentStep: normalizeCoachSurfaceText(currentMainThread.current_step) ?? undefined,
          whyNow: normalizeCoachSurfaceText(currentMainThread.why_now) ?? undefined,
          verifyMethod: asStringArray(currentMainThread.verify_method) ?? undefined,
          blockedReason:
            normalizeCoachSurfaceText(currentMainThread.blocked_reason) ??
            normalizeCoachSurfaceText(currentMainThread.blocker) ??
            undefined,
          nextAfterCurrent: normalizeCoachSurfaceText(currentMainThread.next_after_current) ?? undefined,
          verifiedResult: normalizeCoachSurfaceText(currentMainThread.verified_result) ?? undefined,
        }
      : undefined,
    reviewPoints: reviewPoints as PlanRuntimeReviewPoint[],
    coachJudgment: coachJudgment
      ? {
          summary: normalizeCoachSurfaceText(coachJudgment.summary) ?? undefined,
          teachingGoal: normalizeCoachSurfaceText(coachJudgment.teaching_goal) ?? undefined,
          interventionStrategy: asString(coachJudgment.intervention_strategy) ?? undefined,
          supportStrategy: normalizeCoachSurfaceText(coachJudgment.support_strategy) ?? undefined,
          resumeThread: normalizeCoachSurfaceText(coachJudgment.resume_thread) ?? undefined,
        }
      : undefined,
    nextStepHint: normalizeNextStepHint(record.next_step_hint ?? record.nextStepHint),
    nextTrainingAction: asString(record.next_training_action) ?? undefined,
    reviewQueueSummary: normalizeCoachSurfaceText(record.review_queue_summary) ?? undefined,
    nextReviewDue: normalizeCoachSurfaceText(record.next_review_due) ?? undefined,
    currentStep:
      normalizeCoachSurfaceText(record.current_step) ??
      normalizeCoachSurfaceText(currentMainThread?.current_step) ??
      undefined,
    whyNow:
      normalizeCoachSurfaceText(record.why_now) ??
      normalizeCoachSurfaceText(currentMainThread?.why_now) ??
      undefined,
    verifyMethod:
      asStringArray(record.verify_method) ??
      asStringArray(currentMainThread?.verify_method) ??
      undefined,
    blockedReason:
      normalizeCoachSurfaceText(record.blocked_reason) ??
      normalizeCoachSurfaceText(currentMainThread?.blocked_reason) ??
      normalizeCoachSurfaceText(currentMainThread?.blocker) ??
      undefined,
    nextAfterCurrent:
      normalizeCoachSurfaceText(record.next_after_current) ??
      normalizeCoachSurfaceText(currentMainThread?.next_after_current) ??
      undefined,
    recovered: record.recovered === true,
    currentStageId:
      asString(record.current_stage_id) ??
      asString(record.currentStageId) ??
      undefined,
    resumeState:
      normalizePlanRuntimeResumeState(record.resume_state ?? record.resumeState) ??
      (record.recovered === true ? "interrupted" : undefined),
    requestId: asString(record.request_id) ?? asString(record.requestId) ?? undefined,
    revision: asNumber(record.revision) ?? undefined,
  };
}

function asActiveThread(value: unknown) {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  return {
    scenario: asString(record.scenario) ?? undefined,
    focusArea: normalizeCoachSurfaceText(record.focus_area) ?? undefined,
    summary: normalizeCoachSurfaceText(record.summary) ?? undefined,
    nextStep: normalizeCoachSurfaceText(record.next_step) ?? undefined,
    blocker: normalizeCoachSurfaceText(record.blocker) ?? undefined,
    verifiedResult: normalizeCoachSurfaceText(record.verified_result) ?? undefined,
    decision: asString(record.decision) ?? undefined,
    teachingNote: normalizeCoachSurfaceText(record.teaching_note) ?? undefined,
    confidence: asString(record.confidence) ?? undefined,
    evidence: asStringArray(record.evidence) ?? undefined,
    updatedAt: asString(record.updated_at) ?? undefined,
  };
}

function asArtifactKinds(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (
      item,
    ): item is
      | "task"
      | "plan"
      | "evaluation"
      | "note"
      | "idea_implementation"
      | "project_idea"
      | "project_adaptation"
      | "principle"
      | "review"
      | "plan_update"
      | "next_step" =>
      typeof item === "string" &&
      [
        "task",
        "plan",
        "evaluation",
        "note",
        "idea_implementation",
        "project_idea",
        "project_adaptation",
        "principle",
        "review",
        "plan_update",
        "next_step",
      ].includes(item),
  );
}

function asSuggestedActionTypes(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (
      item,
    ): item is "plan" | "next_task" | "review" | "hint" | "retry_review" | "task" =>
      typeof item === "string" &&
      ["plan", "next_task", "review", "hint", "retry_review", "task"].includes(item),
  );
}

function toCoachScenario(value: string | undefined): CoachScenario {
  if (
    value === "idea_implementation" ||
    value === "project_idea" ||
    value === "project_adaptation" ||
    value === "project_sourcing" ||
    value === "principle" ||
    value === "remote_workspace" ||
    value === "debug_loop" ||
    value === "function_guidance" ||
    value === "review" ||
    value === "plan" ||
    value === "task" ||
    value === "next_task"
  ) {
    return value;
  }
  return "general";
}

function toProjectIdeaKind(
  value: string | undefined,
): ProjectIdea["ideaKind"] {
  if (
    value === "refactor" ||
    value === "test" ||
    value === "architecture" ||
    value === "developer_experience"
  ) {
    return value;
  }
  return "feature";
}

function toResourceKind(value: string | undefined): ResourceRecord["kind"] {
  if (
    value === "pdf" ||
    value === "image" ||
    value === "markdown" ||
    value === "text" ||
    value === "code" ||
    value === "url"
  ) {
    return value;
  }
  return "text";
}

function toAnswerPolicy(value: string | undefined): BootstrapData["profile"]["answerPolicy"] {
  if (value === "auto") {
    return "auto";
  }
  if (value === "coach-first") {
    return "coach-first";
  }
  if (value === "balanced" || value === "direct") {
    return value;
  }
  return "auto";
}

function normalizeConversationSourceView(value: string | undefined): ActiveWorkbenchView | undefined {
  return value === "coach" ||
    value === "plan" ||
    value === "resources" ||
    value === "training" ||
    value === "settings"
    ? value
    : undefined;
}

function toComposerLanguage(value: string | undefined): ComposerLanguage | undefined {
  return isComposerLanguage(value) ? value : undefined;
}

function toContextDetail(
  value: string | undefined,
): "focused" | "balanced" | "full" | undefined {
  if (value === "focused" || value === "balanced" || value === "full") {
    return value;
  }
  return undefined;
}

function toMemoryScope(
  value: string | undefined,
): "project" | "personal" | "session" | undefined {
  if (value === "project" || value === "personal" || value === "session") {
    return value;
  }
  return undefined;
}

function toWorkingSetMode(
  value: string | undefined,
): "focused" | "balanced" | "broad" | undefined {
  if (value === "focused" || value === "balanced" || value === "broad") {
    return value;
  }
  return undefined;
}

function toReviewCadence(
  value: string | undefined,
): "light" | "steady" | "active" | undefined {
  if (value === "light" || value === "steady" || value === "active") {
    return value;
  }
  return undefined;
}

function toReviewReminderMode(
  value: string | undefined,
): "due" | "ahead" | "digest" | undefined {
  if (value === "due" || value === "ahead" || value === "digest") {
    return value;
  }
  return undefined;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
}

function hasOwn(value: unknown, key: PropertyKey): boolean {
  return Boolean(value) && Object.prototype.hasOwnProperty.call(value, key);
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function asStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  return value.filter((item): item is string => typeof item === "string");
}

function toTrainingConversationCandidateType(
  value: string | undefined,
): TrainingHandoffStateView["candidateType"] {
  if (
    value === "project_context_candidate" ||
    value === "resource_import_candidate" ||
    value === "evidence_candidate" ||
    value === "flash_candidate" ||
    value === "practice_candidate" ||
    value === "coach_visible_status" ||
    value === "micro_drill_prompt" ||
    value === "card_invocation"
  ) {
    return value;
  }
  return undefined;
}

function toTrainingCardType(
  value: string | undefined,
): TrainingCardCandidateStateView["type"] | undefined {
  if (value === "practice" || value === "flash") {
    return value;
  }
  return undefined;
}

function toTrainingLearningPhase(
  value: string | undefined,
): NonNullable<TrainingHandoffStateView>["learningPhase"] {
  if (
    value === "learn" ||
    value === "try" ||
    value === "verify" ||
    value === "reflect" ||
    value === "return"
  ) {
    return value;
  }
  return undefined;
}

function toTrainingContinueIn(
  value: string | undefined,
): TrainingHandoffStateView["continueIn"] {
  if (
    value === "chat" ||
    value === "training" ||
    value === "plan" ||
    value === "resources" ||
    value === "none"
  ) {
    return value;
  }
  return undefined;
}

function toTrainingNextHopCandidateType(
  value: string | undefined,
): TrainingNextHopStateView["candidateType"] {
  if (
    value === "evidence_candidate" ||
    value === "flash_candidate" ||
    value === "practice_candidate"
  ) {
    return value;
  }
  return undefined;
}

function toTrainingProjectScope(
  value: string | undefined,
): TrainingNextHopStateView["projectScope"] {
  if (
    value === "global" ||
    value === "current_project" ||
    value === "project_subplan" ||
    value === "sandbox" ||
    value === "unknown"
  ) {
    return value;
  }
  return undefined;
}

function toTrainingNextHopContinueIn(
  value: string | undefined,
): TrainingNextHopStateView["continueIn"] {
  if (value === "chat" || value === "training" || value === "plan") {
    return value;
  }
  return undefined;
}

function toTrainingNextHopStatus(
  value: string | undefined,
): TrainingNextHopStateView["status"] {
  if (
    value === "created" ||
    value === "surfaced" ||
    value === "accepted" ||
    value === "continued_in_chat" ||
    value === "verification_required" ||
    value === "reflection_required" ||
    value === "return_required" ||
    value === "dismissed" ||
    value === "deferred" ||
    value === "blocked" ||
    value === "expired" ||
    value === "archived"
  ) {
    return value;
  }
  return undefined;
}

function toTrainingReturnMode(
  value: string | undefined,
): TrainingHandoffStateView["returnMode"] {
  if (
    value === "result" ||
    value === "blocker" ||
    value === "verification_required" ||
    value === "reflection_required" ||
    value === "return_required"
  ) {
    return value;
  }
  return undefined;
}

function formatTimestamp(value: string | undefined): string {
  if (!value) {
    return "Just now";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
