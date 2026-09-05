import { z } from "zod";
import { SUPPORTED_LANGUAGES } from "../../../../shared/src/types";
import { stripProviderSnapshotSecrets } from "../../../../shared/src/hostLastTestGovernance";

import type {
  CoachDefaults,
  DebugVisibleWorkbenchFacts,
  HostMessage,
  PersistedWorkbenchState,
  WebviewAction,
} from "./types";
import { normalizeSidebarView, normalizeTeachingStyle } from "./types";

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
    __TRAINER_BROWSER_PREVIEW__?: boolean;
    __TRAINER_PREVIEW_STORAGE_KEY__?: string;
    __TRAINER_PREVIEW_APPLY_HOST_MESSAGE__?: (message: unknown) => void;
    __TRAINER_WEBVIEW_READY__?: boolean;
  }
}

const hostMessageSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("bootstrap"),
    payload: z.any(),
  }),
  z.object({
    type: z.literal("state/patch"),
    payload: z.any(),
  }),
  z.object({
    type: z.literal("operation/status"),
    payload: z.object({
      tone: z.enum(["info", "success", "error"]),
      message: z.string(),
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
      messageId: z.string().optional(),
      chunk: z.string(),
    }),
  }),
  z.object({
    type: z.literal("stream/complete"),
    payload: z.object({
      messageId: z.string().optional(),
      tokens: z.number(),
      agentic: z.boolean().optional(),
      summary: z.string().optional(),
      nextStep: z.string().optional(),
      stopReason: z.string().optional(),
      toolCount: z.number().optional(),
    }),
  }),
  z.object({
    type: z.literal("stream/error"),
    payload: z.object({
      messageId: z.string().optional(),
      error: z.string(),
      category: z.string().optional(),
      statusCode: z.number().optional(),
      retryable: z.boolean().optional(),
      reliabilityPhase: z.string().optional(),
      reliabilityOutcome: z.string().optional(),
    }),
  }),
  z.object({
    type: z.literal("stream/cancelled"),
    payload: z.object({
      messageId: z.string().optional(),
    }),
  }),
  z.object({
    type: z.literal("stream/tool_call"),
    payload: z.object({
      messageId: z.string().optional(),
      id: z.string(),
      name: z.string(),
      arguments: z.unknown().optional(),
      step: z.number().optional(),
    }),
  }),
  z.object({
    type: z.literal("stream/tool_result"),
    payload: z.object({
      messageId: z.string().optional(),
      id: z.string(),
      name: z.string(),
      ok: z.boolean(),
      result: z.unknown().optional(),
      step: z.number().optional(),
    }),
  }),
  z.object({
    type: z.literal("stream/step"),
    payload: z.object({
      messageId: z.string().optional(),
      index: z.number(),
      stop_reason: z.union([z.string(), z.null()]).optional(),
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

export function postMessage(action: WebviewAction): void {
  const api = getVsCodeApi();
  if (api) {
    api.postMessage(action);
    return;
  }

  window.dispatchEvent(
    new CustomEvent("trainer:webview-action", {
      detail: action,
    }),
  );
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
    listener(parsed.data as HostMessage);
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

export function inVsCodeWebview(): boolean {
  return Boolean(getVsCodeApi());
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
    },
    composerDraft: state.composerDraft ?? "",
    previewProviderConfig: stripProviderSnapshotSecrets(state.previewProviderConfig),
  };
}
