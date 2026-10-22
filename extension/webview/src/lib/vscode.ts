import type { WebviewSyncCursor, WebviewOperationIdentity } from "../../../../shared/src/webviewSync";
import { z } from "zod";
import { SUPPORTED_LANGUAGES } from "../../../../shared/src/types";
import { stripProviderSnapshotSecrets } from "../../../../shared/src/hostLastTestGovernance";
import { normalizeTrainerCustomSkills } from "../../../../shared/src/skillCatalog";
import { trainerCommands } from "../../../../shared/src/commands";

import type {
  CoachDefaults,
  DebugVisibleWorkbenchFacts,
  HostMessage,
  LocalUsageInsights,
  PersistedWorkbenchState,
  WebviewAction,
} from "./types";
import { COACH_DRAFT_APPLIED_LIMIT, normalizeSidebarView, normalizeTeachingStyle } from "./types";

interface VsCodeApi {
  getState(): PersistedWorkbenchState | undefined;
  setState(state: PersistedWorkbenchState): void;
  postMessage(
    message:
      | WebviewAction
      | { type: "webview/ready" }
      | { type: "debug/visibleFacts"; payload: DebugVisibleWorkbenchFacts }
      | { type: "debug/error"; payload: { source: string; message: string; stack?: string } },
  ): void;
}

declare global {
  interface Window {
    acquireVsCodeApi?: () => VsCodeApi;
    __TRAINER_BOOTSTRAP__?: unknown;
    __TRAINER_SURFACE__?: string;
    __TRAINER_BROWSER_PREVIEW__?: boolean;
    __TRAINER_PREVIEW_STORAGE_KEY__?: string;
    __TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?: (message: unknown) => void;
    __TRAINER_WEBVIEW_READY__?: boolean;
  }
}

const syncEnvelopeSchema = z.object({
  generation: z.number().int().positive(), revision: z.number().int().positive(),
  baseRevision: z.number().int().nonnegative(), messageId: z.string().min(1),
  workspaceId: z.string(), sessionId: z.string(),
});

const operationIdentitySchema = z.object({
  requestId: z.string().min(1).max(128), generation: z.number().int().nonnegative(),
  workspaceId: z.string(), sessionId: z.string(), targetId: z.string().optional(), commandId: z.string().optional(), revision: z.number().int().nonnegative(),
});
const scopeSchema = z.object({ generation: z.number().int().nonnegative(), revision: z.number().int().nonnegative(),
  messageId: z.string(), workspaceId: z.string(), sessionId: z.string() });
const operationPhaseSchema = z.enum(["pending", "running", "succeeded", "failed", "interrupted", "cancelled"]);
const hostMessageSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("remoteVerification/started"), payload: z.object({
    sessionId: z.string(), cardId: z.string().min(1).optional(),
    spec: z.object({ executable: z.string(), args: z.array(z.string()) }),
  }) }),
  z.object({ type: z.literal("remoteVerification/stream"), payload: z.object({
    sessionId: z.string(), cardId: z.string().min(1).optional(),
    stream: z.enum(["stdout", "stderr"]), text: z.string(),
  }) }),
  z.object({ type: z.literal("remoteVerification/finished"), payload: z.object({
    sessionId: z.string(), cardId: z.string().min(1).optional(),
    state: z.enum(["completed", "cancelled", "timed_out", "spawn_failed", "connection_lost"]),
    exitCode: z.number().nullable(), passed: z.boolean().optional(), summary: z.string(),
  }) }),
  z.object({ type: z.literal("remoteCompanion/state"), payload: z.object({
    state: z.enum(["not_installed", "installing", "await_reload", "preparing", "ready", "version_incompatible", "connection_lost", "upgrade_available"]),
    remoteName: z.string().optional(),
  }) }),
  z.object({ type: z.literal("operation/lifecycle"), payload: z.object({
    identity: operationIdentitySchema, phase: operationPhaseSchema,
  }) }),
  z.object({ type: z.literal("state/syncStatus"), payload: z.object({
    status: z.enum(["current", "recovering", "stale"]), generation: z.number().int().positive(),
  }) }),
  z.object({ type: z.literal("stageMaterials/settled"), payload: z.object({
    workspaceId: z.string(), planId: z.string(), stageId: z.string(),
  }) }),
  z.object({ type: z.literal("skills/draftResult"), payload: z.object({
    requestId: z.string(), ok: z.boolean(), message: z.string().optional(),
    draft: z.object({ trigger: z.string(), title: z.string(), detail: z.string(), prompt: z.string(),
      source: z.enum(["model", "template"]) }).optional(),
  }) }),
  z.object({ type: z.literal("browserCapture/statusResult"), payload: z.object({
    prepared: z.boolean(), paired: z.boolean(),
    capturedCount: z.number().nullable().optional(), version: z.string().optional(),
  }) }),
  z.object({ type: z.literal("insights/localUsageResult"), payload: z.object({
    requestId: z.string(), ok: z.boolean(), message: z.string().optional(),
    insights: z.object({
      window_days: z.number().int(), window_start: z.string(), window_end: z.string(),
      total_events: z.number().int(), active_days: z.number().int(), streak_days: z.number().int(),
      totals: z.record(z.string(), z.number()),
      daily: z.array(z.object({
        date: z.string(), practice_submissions: z.number().int(),
        stage_advances: z.number().int(), evidence_adopted: z.number().int(),
        resources_indexed: z.number().int(), any_activity: z.boolean(),
      })),
      last_activity_at: z.string().nullable(),
    }).optional(),
  }) }),
  z.object({
    type: z.literal("bootstrap"),
    sync: syncEnvelopeSchema.optional(),
    payload: z.any(),
  }),
  z.object({
    type: z.literal("state/patch"),
    sync: syncEnvelopeSchema.optional(),
    payload: z.any(),
  }),
  z.object({
    type: z.literal("operation/status"),
    payload: z.object({
      tone: z.enum(["info", "success", "error"]),
      message: z.string(),
      phase: z.string().optional(),
      surface: z.enum(["global", "stream"]).optional(),
      providerTest: z
        .object({
          ok: z.boolean().nullish().transform((value) => value ?? undefined),
          errorCategory: z.string().nullish().transform((value) => value ?? undefined),
          statusCode: z.number().nullish().transform((value) => value ?? undefined),
          retryable: z.boolean().nullish().transform((value) => value ?? undefined),
        })
        .optional(),
    }),
  }),
  z.object({
    type: z.literal("training/resourceHandoff"),
    payload: z.object({
      requestId: z.string(),
      resourceId: z.string(),
      outcome: z.enum(["ready", "blocked", "not-current", "failed"]),
      generatedCardId: z.string().optional(),
      selectedCardId: z.string().optional(),
    }),
  }),
  z.object({
    type: z.literal("training/persistenceAck"),
    payload: z.object({
      requestId: z.string(),
      commandId: z.string(),
      ok: z.boolean(),
      data: z.any().optional(),
      message: z.string().optional(),
    }),
  }),
  z.object({
    type: z.literal("provider/speedTest"),
    payload: z.object({
      results: z.array(
        z.object({
          url: z.string(),
          latencyMs: z.number().nullable(),
          status: z.number().nullable(),
          error: z.string().nullable(),
        }),
      ),
    }),
  }),
  z.object({
    type: z.literal("session/list"),
    payload: z.object({
      ok: z.boolean(),
      sessions: z.array(
        z.object({
          session_id: z.string(),
          summary: z.string(),
          message_count: z.number(),
          updated_at: z.string().nullable().optional(),
          is_active: z.boolean().optional(),
          latest_user_message: z.string().optional(),
          latest_assistant_message: z.string().optional(),
        }),
      ),
      message: z.string().optional(),
    }),
  }),
  z.object({
    type: z.literal("ui/restoreView"),
    payload: z.any(),
  }),
  z.object({
    type: z.literal("ui/coachPrompt"),
    payload: z.object({
      draft: z.string(),
      source: z.enum(["commandPalette", "recovery"]).optional(),
    }),
  }),
  z.object({
    type: z.literal("stream/start"),
    payload: z.object({
      messageId: z.string(),
    }),
  }),
  z.object({
    type: z.literal("stream/chunk"),
    payload: z.object({
      messageId: z.string().nullish().transform((value) => value ?? undefined),
      chunk: z.string(),
    }),
  }),
  z.object({
    type: z.literal("stream/complete"),
    payload: z.object({
      messageId: z.string().nullish().transform((value) => value ?? undefined),
      tokens: z.number(),
      agentic: z.boolean().nullish().transform((value) => value ?? undefined),
      summary: z.string().nullish().transform((value) => value ?? undefined),
      nextStep: z.string().nullish().transform((value) => value ?? undefined),
      stopReason: z.string().nullish().transform((value) => value ?? undefined),
      toolCount: z.number().nullish().transform((value) => value ?? undefined),
      reliabilityPhase: z.string().nullish().transform((value) => value ?? undefined),
      reliabilityOutcome: z.string().nullish().transform((value) => value ?? undefined),
    }),
  }),
  z.object({
    type: z.literal("stream/error"),
    payload: z.object({
      messageId: z.string().nullish().transform((value) => value ?? undefined),
      error: z.string(),
      category: z.string().nullish().transform((value) => value ?? undefined),
      statusCode: z.number().nullish().transform((value) => value ?? undefined),
      retryable: z.boolean().nullish().transform((value) => value ?? undefined),
      reliabilityPhase: z.string().nullish().transform((value) => value ?? undefined),
      reliabilityOutcome: z.string().nullish().transform((value) => value ?? undefined),
    }),
  }),
  z.object({
    type: z.literal("stream/cancelled"),
    payload: z.object({
      messageId: z.string().nullish().transform((value) => value ?? undefined),
    }),
  }),
  z.object({
    type: z.literal("stream/tool_call"),
    payload: z.object({
      messageId: z.string().nullish().transform((value) => value ?? undefined),
      id: z.string(),
      name: z.string(),
      arguments: z.unknown().optional(),
      step: z.number().nullish().transform((value) => value ?? undefined),
    }),
  }),
  z.object({
    type: z.literal("stream/tool_result"),
    payload: z.object({
      messageId: z.string().nullish().transform((value) => value ?? undefined),
      id: z.string(),
      name: z.string(),
      ok: z.boolean(),
      result: z.unknown().optional(),
      step: z.number().nullish().transform((value) => value ?? undefined),
    }),
  }),
  z.object({
    type: z.literal("stream/step"),
    payload: z.object({
      messageId: z.string().nullish().transform((value) => value ?? undefined),
      index: z.number(),
      stop_reason: z.union([z.string(), z.null()]).optional(),
    }),
  }),
  // Library folder answers (list/create/rename/delete), correlated by the
  // request's operationId. Without this entry the schema silently dropped the
  // host's answers and every folder operation timed out as "unconfirmed".
  z.object({
    type: z.literal("library/folders"),
    payload: z.object({
      operationId: z.string().optional(),
      ok: z.boolean(),
      folders: z.unknown().optional(),
      message: z.string().optional(),
    }),
  }),
  // Deep link (vscode://.../library/<id>): flat by contract with
  // `extension/src/browserCapture/deepLink.ts`.
  z.object({
    type: z.literal("ui/openResource"),
    resourceId: z.string(),
  }),
  // Browser-captured coach draft: flat by contract with
  // `extension/src/browserCapture/draftPoller.ts`. `draftId` is optional so a
  // receipt-less prefill still applies (it just cannot be acknowledged).
  z.object({
    type: z.literal("ui/coachDraftPrefill"),
    text: z.string(),
    draftId: z.string().optional(),
  }),
  z.object({
    type: z.literal("resourceOrganization/pending"),
    payload: z.object({
      pending: z.boolean(),
      operationCount: z.number().optional(),
    }),
  }),
]);

const STORAGE_KEY = "trainer:webview";
const PREVIEW_HOST_MESSAGE_EVENT = "trainer:host-message";
const DEFAULT_COACH_DEFAULTS: CoachDefaults = {
  memoryScope: "project",
  workingSetMode: "balanced",
  reviewCadence: "steady",
  reviewReminderMode: "due",
  workspaceMemoryToggles: {
    decisions: true,
    patterns: true,
    resources: true,
  },
};

let vscodeApi = window.acquireVsCodeApi?.();

function getVsCodeApi(): VsCodeApi | undefined {
  // Browser Preview installs its compatible API after the sidecar module graph
  // has loaded. Keep the VS Code singleton semantics while allowing that late
  // bridge to be captured before the first user action.
  if (!vscodeApi && typeof window.acquireVsCodeApi === "function") {
    vscodeApi = window.acquireVsCodeApi();
  }
  return vscodeApi;
}

function getStorageKey(): string {
  if (window.__TRAINER_BROWSER_PREVIEW__ && window.__TRAINER_PREVIEW_STORAGE_KEY__) {
    return window.__TRAINER_PREVIEW_STORAGE_KEY__;
  }
  return STORAGE_KEY;
}

export function getInjectedBootstrapState<T>(): T | undefined {
  return window.__TRAINER_BOOTSTRAP__ as T | undefined;
}

export function getPersistedState():
  | PersistedWorkbenchState
  | undefined {
  const api = getVsCodeApi();
  if (api) {
    const state = api.getState();
    return state ? normalizePersistedState(state) : undefined;
  }

  const raw = window.localStorage.getItem(getStorageKey());
  if (!raw) {
    return undefined;
  }

  try {
    return normalizePersistedState(JSON.parse(raw) as PersistedWorkbenchState);
  } catch {
    return undefined;
  }
}

export function setPersistedState(state: PersistedWorkbenchState): void {
  const normalizedState = normalizePersistedState(state);
  const api = getVsCodeApi();
  if (api) {
    api.setState(normalizedState);
    return;
  }

  window.localStorage.setItem(getStorageKey(), JSON.stringify(normalizedState));
}

export function persistBrowserPreviewProviderConfig(providerConfig: unknown): void {
  if (!window.__TRAINER_BROWSER_PREVIEW__ || !window.__TRAINER_PREVIEW_STORAGE_KEY__) {
    return;
  }
  const safeProviderConfig = stripProviderSnapshotSecrets(providerConfig);
  try {
    const storageKey = window.__TRAINER_PREVIEW_STORAGE_KEY__;
    const raw = window.localStorage.getItem(storageKey);
    const current = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({ ...current, previewProviderConfig: safeProviderConfig }),
    );
    const bootstrap = window.__TRAINER_BOOTSTRAP__;
    if (bootstrap && typeof bootstrap === "object" && !Array.isArray(bootstrap)) {
      window.__TRAINER_BOOTSTRAP__ = { ...bootstrap, providerConfig: safeProviderConfig };
    }
  } catch {
    // Browser preview remains usable when storage is unavailable.
  }
}

let hostSyncScope: WebviewSyncCursor | undefined;
let operationRequestSequence = 0;
export function adoptHostSyncScope(scope: WebviewSyncCursor): void { hostSyncScope = scope; }

export function postMessage(action: WebviewAction): WebviewOperationIdentity | undefined {
  const api = getVsCodeApi();
  if (api) {
    const scope = hostSyncScope;
    // Flow-control messages never carry an operation identity: the ACK
    // handshake, bootstrap requests, live-follow toggles and the draft
    // delivery receipt are answered by dedicated host handling, not by the
    // scoped command lifecycle.
    const tracked =
      scope &&
      action.type !== "state/ack" &&
      action.type !== "request/bootstrap" &&
      action.type !== "ui/liveFollow" &&
      action.type !== "ui/coachDraftPrefillApplied";
    if (tracked && !action.operation) {
      const payload = "payload" in action && action.payload && typeof action.payload === "object"
        ? action.payload as Record<string, unknown> : undefined;
      const commandPayload = payload?.payload && typeof payload.payload === "object"
        ? payload.payload as Record<string, unknown> : payload;
      const target = commandPayload?.cardId ?? commandPayload?.resourceId ?? commandPayload?.planId ?? commandPayload?.expectedCardId;
      const operation: WebviewOperationIdentity = { generation: scope.generation, workspaceId: scope.workspaceId,
        sessionId: scope.sessionId, revision: scope.revision,
        commandId: typeof payload?.commandId === "string" ? payload.commandId : action.type,
        requestId: `webview-${Date.now()}-${++operationRequestSequence}`,
        ...(typeof target === "string" ? { targetId: target } : {}),
      };
      api.postMessage({ ...action, operation });
      return operation;
    } else api.postMessage(action);
    return action.operation;
  }

  window.dispatchEvent(
    new CustomEvent("trainer:webview-action", {
      detail: action,
    }),
  );
  return action.operation;
}

export function announceReady(): void {
  const api = getVsCodeApi();
  if (api) {
    api.postMessage({ type: "webview/ready" });
  }
}

export function reportWebviewError(error: {
  source: string;
  message: string;
  stack?: string;
}): void {
  const api = getVsCodeApi();
  if (api) {
    api.postMessage({
      type: "debug/error",
      payload: error,
    });
  }
}

export function postDebugVisibleFacts(payload: DebugVisibleWorkbenchFacts): void {
  const api = getVsCodeApi();
  if (api) {
    api.postMessage({
      type: "debug/visibleFacts",
      payload,
    });
  }
}

export function subscribeToHostMessages(
  listener: (message: HostMessage) => void,
): () => void {
  const previewBridgeEnabled = window.__TRAINER_BROWSER_PREVIEW__ === true;
  const deliver = (value: unknown) => {
    const parsed = hostMessageSchema.safeParse(value);
    if (!parsed.success) {
      return;
    }
    const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
    const scope = scopeSchema.safeParse(raw.scope);
    const operation = operationIdentitySchema.safeParse(raw.operation);
    const operationPhase = operationPhaseSchema.safeParse(raw.operationPhase);
    listener({ ...parsed.data,
      ...(scope.success ? { scope: scope.data } : {}),
      ...(operation.success ? { operation: operation.data } : {}),
      ...(operationPhase.success ? { operationPhase: operationPhase.data } : {}),
    } as HostMessage);
  };
  const handler = (event: MessageEvent<unknown>) => {
    deliver(event.data);
  };
  const previewHandler = (event: Event) => {
    deliver((event as CustomEvent<unknown>).detail);
  };

  window.addEventListener("message", handler);
  if (previewBridgeEnabled) {
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ = deliver;
    window.addEventListener(PREVIEW_HOST_MESSAGE_EVENT, previewHandler);
  }

  return () => {
    window.removeEventListener("message", handler);
    if (previewBridgeEnabled) {
      delete window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__;
      window.removeEventListener(PREVIEW_HOST_MESSAGE_EVENT, previewHandler);
    }
  };
}

export function requestNativeSkillDraft(description: string): Promise<{
  trigger: string; title: string; detail: string; prompt: string; source: "model" | "template";
}> {
  const requestId = `skill-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  return new Promise((resolve, reject) => {
    const unsubscribe = subscribeToHostMessages((message) => {
      if (message.type !== "skills/draftResult" || message.payload.requestId !== requestId) return;
      window.clearTimeout(timeoutId);
      unsubscribe();
      if (message.payload.ok && message.payload.draft) resolve(message.payload.draft);
      else reject(new Error(message.payload.message ?? "Skill generation failed."));
    });
    const timeoutId = window.setTimeout(() => {
      unsubscribe();
      reject(new Error("Skill generation timed out. Please retry."));
    }, 60_000);
    try {
      postMessage({ type: "command/execute", payload: {
        commandId: trainerCommands.generateSkillDraft, payload: { requestId, description },
      } });
    } catch (error) {
      window.clearTimeout(timeoutId);
      unsubscribe();
      reject(error);
    }
  });
}

export function inVsCodeWebview(): boolean {
  return Boolean(getVsCodeApi());
}

/**
 * Request the local usage insights snapshot (P1 #12, §6.1). A read-only
 * ledger aggregation served by the sidecar; coarse counts only, nothing
 * leaves the machine. Rejects with a displayable message on failure.
 */
export function requestLocalUsageInsights(windowDays: number): Promise<LocalUsageInsights> {
  const requestId = `insights-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  return new Promise((resolve, reject) => {
    const unsubscribe = subscribeToHostMessages((message) => {
      if (message.type !== "insights/localUsageResult" || message.payload.requestId !== requestId) return;
      window.clearTimeout(timeoutId);
      unsubscribe();
      if (message.payload.ok && message.payload.insights) resolve(message.payload.insights);
      else reject(new Error(message.payload.message ?? "Local usage data is unavailable right now."));
    });
    const timeoutId = window.setTimeout(() => {
      unsubscribe();
      reject(new Error("Local usage insights timed out. Please retry."));
    }, 15_000);
    try {
      postMessage({ type: "command/execute", payload: {
        commandId: trainerCommands.refreshLocalUsage, payload: { requestId, windowDays },
      } });
    } catch (error) {
      window.clearTimeout(timeoutId);
      unsubscribe();
      reject(error);
    }
  });
}

/**
 * Which host surface this bundle instance runs on. The sidebar view is the
 * default; the host marks the open-in-editor panel (`__TRAINER_SURFACE__`)
 * so the shell can swap the expand control for a "back to sidebar" control.
 */
export function getWorkbenchSurface(): "sidebar" | "editor" {
  return window.__TRAINER_SURFACE__ === "editor" ? "editor" : "sidebar";
}

/** Editor-panel surface only: ask the host to collapse back into the sidebar. */
export function requestCollapseToSidebar(): void {
  postMessage({ type: "ui/collapseToSidebar" });
}

function normalizePersistedState(state: PersistedWorkbenchState): PersistedWorkbenchState {
  return {
    ...state,
    themePreference: state.themePreference ?? "system",
    learningSurfaceAlignment: state.learningSurfaceAlignment === "right" ? "right" : "left",
    activeView: normalizeSidebarView(state.activeView),
    composerLanguage: SUPPORTED_LANGUAGES.includes(state.composerLanguage)
      ? state.composerLanguage
      : "en-US",
    composerAnswerMode:
      state.composerAnswerMode === "auto" ||
      state.composerAnswerMode === "coach-first" ||
      state.composerAnswerMode === "balanced" ||
      state.composerAnswerMode === "direct"
        ? state.composerAnswerMode
        : "auto",
    teachingStyle: normalizeTeachingStyle(state.teachingStyle),
    includeCurrentFile: state.includeCurrentFile ?? true,
    includeSelection: state.includeSelection ?? true,
    includeDiagnostics: state.includeDiagnostics ?? true,
    includeRelatedFiles: state.includeRelatedFiles ?? true,
    contextDetail:
      state.contextDetail === "focused" || state.contextDetail === "full"
        ? state.contextDetail
        : "balanced",
    followCurrentFile: state.followCurrentFile ?? true,
    coachDefaults: {
      memoryScope:
        state.coachDefaults?.memoryScope === "personal" || state.coachDefaults?.memoryScope === "session"
          ? state.coachDefaults.memoryScope
          : DEFAULT_COACH_DEFAULTS.memoryScope,
      workingSetMode:
        state.coachDefaults?.workingSetMode === "focused" || state.coachDefaults?.workingSetMode === "broad"
          ? state.coachDefaults.workingSetMode
          : DEFAULT_COACH_DEFAULTS.workingSetMode,
      reviewCadence:
        state.coachDefaults?.reviewCadence === "light" || state.coachDefaults?.reviewCadence === "active"
          ? state.coachDefaults.reviewCadence
          : DEFAULT_COACH_DEFAULTS.reviewCadence,
      reviewReminderMode:
        state.coachDefaults?.reviewReminderMode === "ahead" || state.coachDefaults?.reviewReminderMode === "digest"
          ? state.coachDefaults.reviewReminderMode
          : DEFAULT_COACH_DEFAULTS.reviewReminderMode,
      workspaceMemoryToggles: {
        decisions:
          state.coachDefaults?.workspaceMemoryToggles?.decisions ??
          DEFAULT_COACH_DEFAULTS.workspaceMemoryToggles.decisions,
        patterns:
          state.coachDefaults?.workspaceMemoryToggles?.patterns ??
          DEFAULT_COACH_DEFAULTS.workspaceMemoryToggles.patterns,
        resources:
          state.coachDefaults?.workspaceMemoryToggles?.resources ??
          DEFAULT_COACH_DEFAULTS.workspaceMemoryToggles.resources,
      },
      // Preserve absence so a stale persisted state never overwrites newer
      // server-side skills with an empty list on the next turn payload.
      ...(state.coachDefaults?.customSkills === undefined
        ? {}
        : { customSkills: normalizeTrainerCustomSkills(state.coachDefaults.customSkills) }),
    },
    composerDraft: state.composerDraft ?? "",
    appliedDraftIds: Array.isArray(state.appliedDraftIds)
      ? state.appliedDraftIds
          .filter((id): id is string => typeof id === "string" && id.trim().length > 0)
          .slice(-COACH_DRAFT_APPLIED_LIMIT)
      : undefined,
    previewProviderConfig: stripProviderSnapshotSecrets(state.previewProviderConfig),
  };
}
