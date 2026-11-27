import { trainerCommands } from "../../../../shared/src/commands";
import type { WebviewSyncEnvelope } from "../../../../shared/src/webviewSync";

import {
  registerWorkbenchHostTransport,
  type WorkbenchHostTransport,
} from "./hostTransport";
import {
  mapSidecarSnapshotToBootstrapData,
  type BrowserTabLiveSummary,
  type RedactedWorkspaceProviderSummary,
} from "./sidecarSnapshotMapper";
import type {
  BootstrapData,
  CoachSessionSummary,
  ComposerLanguage,
  HostMessage,
  PersistedWorkbenchState,
  ResourceDetailRecord,
  ResourceSearchState,
  SessionMessageRequest,
  StreamMessageRequest,
  WebviewAction,
} from "./types";

const WEBVIEW_STATE_STORAGE_KEY = "trainer:sidepanel:webviewState";
const SESSION_STORAGE_KEY = "trainer.sidepanel.session";
const HOST_DEEP_LINK_BASE = "vscode://local.trainer-extension/";

const AUTH_KEYS = {
  baseUrl: "trainerCapture.baseUrl",
  credential: "trainerCapture.credential",
  workspaceId: "trainerCapture.workspaceId",
  workspaceName: "trainerCapture.workspaceName",
} as const;

interface BrowserPairedAuth {
  baseUrl: string;
  credential: string;
  workspaceId: string;
  workspaceName: string;
}

interface ChromeTabLike {
  id?: number;
  url?: string;
  title?: string;
  active?: boolean;
}

interface ChromeExtensionGlobals {
  storage?: {
    local?: {
      get(
        keys: string | string[] | Record<string, unknown>,
        callback?: (items: Record<string, unknown>) => void,
      ): Promise<Record<string, unknown>> | void;
      set(items: Record<string, unknown>, callback?: () => void): Promise<void> | void;
    };
    onChanged?: {
      addListener(
        listener: (changes: Record<string, { oldValue?: unknown; newValue?: unknown }>, areaName: string) => void,
      ): void;
      removeListener(
        listener: (changes: Record<string, { oldValue?: unknown; newValue?: unknown }>, areaName: string) => void,
      ): void;
    };
  };
  runtime?: {
    sendMessage(message: Record<string, unknown>, callback?: (response: unknown) => void): Promise<unknown> | void;
    lastError?: { message?: string };
  };
  tabs?: {
    query(queryInfo: Record<string, unknown>): Promise<ChromeTabLike[]>;
    create?(createProperties: { url: string }): Promise<ChromeTabLike> | void;
    onActivated?: {
      addListener(listener: () => void): void;
      removeListener(listener: () => void): void;
    };
    onUpdated?: {
      addListener(listener: (tabId: number, changeInfo: Record<string, unknown>, tab: ChromeTabLike) => void): void;
      removeListener(listener: (tabId: number, changeInfo: Record<string, unknown>, tab: ChromeTabLike) => void): void;
    };
  };
}

function getChromeApi(): ChromeExtensionGlobals | undefined {
  const candidate = (globalThis as { chrome?: ChromeExtensionGlobals }).chrome;
  return candidate && typeof candidate === "object" ? candidate : undefined;
}

function isHttpUrl(url: string | undefined): url is string {
  if (typeof url !== "string" || !url.trim()) {
    return false;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

async function storageGet(defaults: Record<string, unknown>): Promise<Record<string, unknown>> {
  const storage = getChromeApi()?.storage?.local;
  if (!storage) {
    return { ...defaults };
  }
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value: unknown) => {
      if (settled) return;
      settled = true;
      resolve(
        value && typeof value === "object"
          ? { ...defaults, ...(value as Record<string, unknown>) }
          : { ...defaults },
      );
    };
    try {
      const maybePromise = storage.get(defaults, finish);
      if (maybePromise && typeof (maybePromise as Promise<Record<string, unknown>>).then === "function") {
        void (maybePromise as Promise<Record<string, unknown>>).then(finish, () => finish(defaults));
      }
    } catch {
      finish(defaults);
    }
  });
}

async function storageSet(items: Record<string, unknown>): Promise<void> {
  const storage = getChromeApi()?.storage?.local;
  if (!storage) {
    return;
  }
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    try {
      const maybePromise = storage.set(items, finish);
      if (maybePromise && typeof (maybePromise as Promise<void>).then === "function") {
        void (maybePromise as Promise<void>).then(finish, finish);
      }
    } catch {
      finish();
    }
  });
}

async function sendRuntimeMessage(message: Record<string, unknown>): Promise<Record<string, unknown>> {
  const runtime = getChromeApi()?.runtime;
  if (!runtime || typeof runtime.sendMessage !== "function") {
    return {};
  }
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value: unknown) => {
      if (settled) return;
      settled = true;
      resolve(value && typeof value === "object" ? (value as Record<string, unknown>) : {});
    };
    try {
      const maybePromise = runtime.sendMessage(message, (response) => {
        if (getChromeApi()?.runtime?.lastError) {
          finish({});
          return;
        }
        finish(response);
      });
      if (maybePromise && typeof (maybePromise as Promise<unknown>).then === "function") {
        void (maybePromise as Promise<unknown>).then(finish, () => finish({}));
      }
    } catch {
      finish({});
    }
  });
}

const SIDEPANEL_BRIDGE_COPY: Record<
  ComposerLanguage,
  { connectInVsCode: string; openedSettingsInVsCode: string }
> = {
  "zh-CN": {
    connectInVsCode: "请先在 VS Code 中打开 Trainer 完成连接。",
    openedSettingsInVsCode: "已在 VS Code 中打开 Trainer 设置以管理模型与工作区连接。",
  },
  "en-US": {
    connectInVsCode: "Open Trainer in VS Code first to connect this workspace.",
    openedSettingsInVsCode: "Opened Trainer Settings in VS Code to manage model and workspace connection.",
  },
  "es-ES": {
    connectInVsCode: "Abre primero Trainer en VS Code para conectar este espacio de trabajo.",
    openedSettingsInVsCode: "Se abrió Ajustes de Trainer en VS Code para gestionar el modelo y el espacio de trabajo.",
  },
  "fr-FR": {
    connectInVsCode: "Ouvrez d'abord Trainer dans VS Code pour connecter cet espace de travail.",
    openedSettingsInVsCode: "Réglages Trainer ouverts dans VS Code pour gérer le modèle et l'espace de travail.",
  },
  "de-DE": {
    connectInVsCode: "Öffne zuerst Trainer in VS Code, um diesen Arbeitsbereich zu verbinden.",
    openedSettingsInVsCode: "Trainer-Einstellungen in VS Code geöffnet, um Modell und Arbeitsbereich zu verwalten.",
  },
  "ja-JP": {
    connectInVsCode: "先に VS Code で Trainer を開いて接続してください。",
    openedSettingsInVsCode: "モデルとワークスペースを管理するため VS Code で Trainer 設定を開きました。",
  },
  "ko-KR": {
    connectInVsCode: "먼저 VS Code에서 Trainer를 열어 연결을 완료하세요.",
    openedSettingsInVsCode: "모델 및 작업 공간 연결을 관리하기 위해 VS Code에서 Trainer 설정을 열었습니다.",
  },
  "pt-BR": {
    connectInVsCode: "Abra primeiro o Trainer no VS Code para conectar este espaço de trabalho.",
    openedSettingsInVsCode: "Configurações do Trainer abertas no VS Code para gerenciar o modelo e o espaço de trabalho.",
  },
};

function resolveCurrentLanguage(persisted: PersistedWorkbenchState | undefined): ComposerLanguage {
  if (persisted?.composerLanguage) {
    return persisted.composerLanguage;
  }
  if (typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("zh")) {
    return "zh-CN";
  }
  return "en-US";
}

export interface ChromeSidePanelPlatformAdapter {
  storageGet?: (defaults: Record<string, unknown>) => Promise<Record<string, unknown>>;
  storageSet?: (items: Record<string, unknown>) => Promise<void>;
  sendRuntimeMessage?: (message: Record<string, unknown>) => Promise<Record<string, unknown>>;
  queryActiveTab?: () => Promise<ChromeTabLike | undefined>;
  fetchFn?: typeof fetch;
}

export interface CreateChromeSidePanelTransportOptions {
  initialPersistedState?: PersistedWorkbenchState;
  platform?: ChromeSidePanelPlatformAdapter;
}

/**
 * Creates a `WorkbenchHostTransport` that mounts the exact VS Code React
 * sidebar (`extension/webview`) inside the Browser Extension MV3 `sidePanel`.
 *
 * Key guarantees:
 * 1. Zero global content-script dependency: passive tab metadata uses
 *    `chrome.tabs.query` (title/URL only), and webpage selection/anchor context
 *    is extracted strictly on demand via `trainer:extract-tab-context`
 *    (`chrome.scripting.executeScript`) when the learner sends a message.
 * 2. Zero provider secrets in the browser: every call speaks Bearer-scoped
 *    `/browser/chat/*` on the local Sidecar.
 */
export function createChromeSidePanelTransport(
  options: CreateChromeSidePanelTransportOptions = {},
): WorkbenchHostTransport {
  let persistedState = options.initialPersistedState;
  const platform = options.platform;
  const getFromStorage = platform?.storageGet ?? storageGet;
  const setInStorage = platform?.storageSet ?? storageSet;
  const sendToRuntime = platform?.sendRuntimeMessage ?? sendRuntimeMessage;
  const doFetch = platform?.fetchFn ?? fetch;
  const listeners = new Set<(message: unknown) => void>();

  let syncGeneration = 1;
  let syncRevision = 0;
  let activeSessionId = "";
  let activeWorkspaceId = "browser-workspace";
  let currentAuth: BrowserPairedAuth | null = null;
  let activeTabMeta: { id?: number; url: string; title: string } | null = null;
  let latestBootstrap: BootstrapData | undefined;
  let activeStreamAbort: AbortController | null = null;
  let activeStreamId = "";

  const nextSyncEnvelope = (workspaceId = activeWorkspaceId, sessionId = activeSessionId): WebviewSyncEnvelope => {
    const baseRevision = syncRevision;
    syncRevision += 1;
    return {
      generation: syncGeneration,
      revision: syncRevision,
      baseRevision,
      messageId: `sidepanel-sync-${syncGeneration}-${syncRevision}`,
      workspaceId: workspaceId || "browser-workspace",
      sessionId: sessionId || "browser-session",
    };
  };

  const emitHostMessage = (message: HostMessage): void => {
    for (const listener of listeners) {
      listener(message);
    }
  };

  const readPassiveActiveTab = async (): Promise<{ id?: number; url: string; title: string } | null> => {
    try {
      const tab = platform?.queryActiveTab
        ? await platform.queryActiveTab()
        : (await getChromeApi()?.tabs?.query?.({ active: true, currentWindow: true }))?.[0];
      if (!tab || !isHttpUrl(tab.url)) {
        activeTabMeta = null;
        return null;
      }
      activeTabMeta = {
        id: typeof tab.id === "number" ? tab.id : undefined,
        url: tab.url,
        title: typeof tab.title === "string" ? tab.title : tab.url,
      };
      return activeTabMeta;
    } catch {
      activeTabMeta = null;
      return null;
    }
  };

  const extractTabContextOnDemand = async (): Promise<BrowserTabLiveSummary | undefined> => {
    const tab = await readPassiveActiveTab();
    if (!tab) {
      return undefined;
    }
    if (typeof tab.id !== "number") {
      return { url: tab.url, title: tab.title };
    }
    const extracted = await sendToRuntime({
      type: "trainer:extract-tab-context",
      tabId: tab.id,
      url: tab.url,
    });
    const pageContext =
      extracted.pageContext && typeof extracted.pageContext === "object"
        ? (extracted.pageContext as Record<string, unknown>)
        : undefined;
    const resolvedUrl =
      typeof pageContext?.url === "string" && isHttpUrl(pageContext.url)
        ? pageContext.url
        : tab.url;
    const resolvedTitle =
      typeof pageContext?.title === "string" && pageContext.title.trim()
        ? pageContext.title.trim()
        : tab.title;
    const selection =
      typeof pageContext?.selection === "string" && pageContext.selection.trim()
        ? pageContext.selection.trim()
        : undefined;
    return {
      url: resolvedUrl,
      title: resolvedTitle,
      ...(selection ? { selection } : {}),
    };
  };

  const loadPairedAuth = async (allowAutoPair = true): Promise<{
    auth: BrowserPairedAuth | null;
    needsPairing: boolean;
  }> => {
    const readStored = async (): Promise<BrowserPairedAuth | null> => {
      const stored = await getFromStorage({
        [AUTH_KEYS.baseUrl]: "",
        [AUTH_KEYS.credential]: "",
        [AUTH_KEYS.workspaceId]: "",
        [AUTH_KEYS.workspaceName]: "",
      });
      const baseUrl = String(stored[AUTH_KEYS.baseUrl] ?? "").trim().replace(/\/+$/, "");
      const credential = String(stored[AUTH_KEYS.credential] ?? "").trim();
      if (!baseUrl || !credential) {
        return null;
      }
      const workspaceId = String(stored[AUTH_KEYS.workspaceId] ?? "").trim() || "browser-workspace";
      const workspaceName = String(stored[AUTH_KEYS.workspaceName] ?? "").trim() || workspaceId;
      return { baseUrl, credential, workspaceId, workspaceName };
    };

    let auth = await readStored();
    let needsPairing = false;
    if (!auth && allowAutoPair) {
      const auto = await sendToRuntime({ type: "trainer:auto-pair" });
      needsPairing = auto.needsPairing === true;
      auth = await readStored();
    }
    if (auth) {
      const stateInfo = await sendToRuntime({ type: "trainer:state" });
      if (typeof stateInfo.workspaceName === "string" && stateInfo.workspaceName.trim()) {
        auth.workspaceName = stateInfo.workspaceName.trim();
      }
    }
    currentAuth = auth;
    return { auth, needsPairing };
  };

  const loadStoredSessionId = async (): Promise<string> => {
    const stored = await getFromStorage({ [SESSION_STORAGE_KEY]: "" });
    return String(stored[SESSION_STORAGE_KEY] ?? "").trim();
  };

  const saveStoredSessionId = async (sessionId: string): Promise<void> => {
    activeSessionId = sessionId;
    await setInStorage({ [SESSION_STORAGE_KEY]: sessionId });
  };

  const emitOfflineBootstrap = async (needsPairing: boolean): Promise<void> => {
    const tab = await readPassiveActiveTab();
    const payload = mapSidecarSnapshotToBootstrapData(
      {},
      {
        workspaceId: activeWorkspaceId,
        workspaceName: currentAuth?.workspaceName || "Trainer",
        paired: false,
        needsPairing,
        activeTab: tab,
      },
    );
    latestBootstrap = payload;
    emitHostMessage({
      type: "bootstrap",
      sync: nextSyncEnvelope(activeWorkspaceId, activeSessionId || "offline"),
      payload,
    });
  };

  const fetchBootstrapSnapshot = async (
    requestedSessionId?: string,
    optionsOverride?: { createNewSession?: boolean },
  ): Promise<BootstrapData | undefined> => {
    const { auth, needsPairing } = await loadPairedAuth(true);
    if (!auth) {
      await emitOfflineBootstrap(needsPairing);
      return undefined;
    }

    if (auth.workspaceId && auth.workspaceId !== activeWorkspaceId) {
      syncGeneration += 1;
      syncRevision = 0;
      activeWorkspaceId = auth.workspaceId;
    }

    const tab = await readPassiveActiveTab();
    const targetSession =
      optionsOverride?.createNewSession
        ? ""
        : (requestedSessionId ?? activeSessionId) || (await loadStoredSessionId());

    try {
      let response: Response;
      if (optionsOverride?.createNewSession) {
        response = await doFetch(`${auth.baseUrl}/browser/chat/session/new`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${auth.credential}`,
          },
          body: JSON.stringify({}),
          cache: "no-store",
        });
      } else {
        const params = new URLSearchParams();
        if (targetSession) {
          params.set("session_id", targetSession);
        }
        const query = params.toString();
        response = await doFetch(
          `${auth.baseUrl}/browser/chat/bootstrap${query ? `?${query}` : ""}`,
          {
            headers: { Authorization: `Bearer ${auth.credential}` },
            cache: "no-store",
          },
        );
      }

      if (response.status === 401) {
        // Attempt one transparent auto-pair in case the sidecar restarted.
        const retryAuth = await sendToRuntime({ type: "trainer:auto-pair" });
        const refreshed = await loadPairedAuth(false);
        if (!refreshed.auth) {
          await emitOfflineBootstrap(retryAuth.needsPairing === true);
          return undefined;
        }
        return fetchBootstrapSnapshot(targetSession, optionsOverride);
      }

      if (!response.ok) {
        await emitOfflineBootstrap(false);
        return undefined;
      }

      const snapshot = (await response.json()) as Record<string, unknown>;
      const resolvedSession = String(
        snapshot.session_id ?? snapshot.sessionId ?? targetSession ?? "",
      ).trim();
      if (resolvedSession) {
        await saveStoredSessionId(resolvedSession);
      }
      const workspaceProvider =
        snapshot.workspace_provider && typeof snapshot.workspace_provider === "object"
          ? (snapshot.workspace_provider as RedactedWorkspaceProviderSummary)
          : undefined;

      const payload = mapSidecarSnapshotToBootstrapData(snapshot, {
        workspaceId: auth.workspaceId,
        workspaceName: auth.workspaceName,
        paired: true,
        activeTab: tab,
        workspaceProvider,
      });
      latestBootstrap = payload;
      emitHostMessage({
        type: "bootstrap",
        sync: nextSyncEnvelope(auth.workspaceId, resolvedSession || "default"),
        payload,
      });
      return payload;
    } catch {
      await emitOfflineBootstrap(false);
      return undefined;
    }
  };

  const handleStreamingSend = async (
    request: StreamMessageRequest | SessionMessageRequest,
  ): Promise<void> => {
    const language = resolveCurrentLanguage(persistedState);
    const { auth } = await loadPairedAuth(true);
    if (!auth) {
      emitHostMessage({
        type: "operation/status",
        payload: {
          tone: "error",
          message: (SIDEPANEL_BRIDGE_COPY[language] ?? SIDEPANEL_BRIDGE_COPY["en-US"]).connectInVsCode,
        },
      });
      return;
    }

    const messageId = `browser-stream-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    activeStreamId = messageId;
    activeStreamAbort?.abort();
    const abortController = new AbortController();
    activeStreamAbort = abortController;

    emitHostMessage({
      type: "stream/start",
      payload: { messageId },
    });

    // Strictly on-demand webpage context extraction: read selection ONLY when
    // the user explicitly sends a turn with current-file/page context enabled.
    const pageContext =
      request.includeCurrentFile !== false
        ? await extractTabContextOnDemand()
        : undefined;

    const body: Record<string, unknown> = {
      ...(activeSessionId ? { session_id: activeSessionId } : {}),
      message: request.text,
      stream_id: messageId,
      request_id: request.requestId ?? messageId,
      ...(request.responseLanguage ? { response_language: request.responseLanguage } : {}),
      ...(pageContext ? { page_context: pageContext } : {}),
    };

    try {
      const response = await doFetch(`${auth.baseUrl}/browser/chat/message/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          Authorization: `Bearer ${auth.credential}`,
        },
        body: JSON.stringify(body),
        cache: "no-store",
        signal: abortController.signal,
      });

      if (!response.ok || !response.body) {
        const detail = await response.text().catch(() => "");
        throw new Error(detail || `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let settledInlineSnapshot = false;
      let sawTerminalFrame = false;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          let eventName = "message";
          let dataText = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) {
              eventName = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataText += line.slice(5).trim();
            }
          }
          if (!dataText) continue;
          let parsed: Record<string, unknown>;
          try {
            parsed = JSON.parse(dataText) as Record<string, unknown>;
          } catch {
            continue;
          }

          const frameType = typeof parsed.type === "string" ? parsed.type : eventName;
          if (typeof parsed.chunk === "string" && parsed.chunk.length > 0) {
            emitHostMessage({
              type: "stream/chunk",
              payload: { messageId, chunk: parsed.chunk },
            });
          } else if (frameType === "stage") {
            emitHostMessage({
              type: "stream/stage",
              payload: {
                messageId,
                kind: parsed.kind as
                  | "think"
                  | "reason"
                  | "retrieve"
                  | "download"
                  | "organize"
                  | "cards"
                  | "finalize"
                  | undefined,
                toolName: typeof parsed.tool_name === "string" ? parsed.tool_name : undefined,
              },
            });
          } else if (frameType === "tool_call") {
            emitHostMessage({
              type: "stream/tool_call",
              payload: {
                messageId,
                id: String(parsed.id ?? `tool-${Date.now()}`),
                name: String(parsed.name ?? "tool"),
                arguments: parsed.arguments,
                step: typeof parsed.step === "number" ? parsed.step : undefined,
              },
            });
          } else if (frameType === "tool_result") {
            emitHostMessage({
              type: "stream/tool_result",
              payload: {
                messageId,
                id: String(parsed.id ?? `tool-${Date.now()}`),
                name: String(parsed.name ?? "tool"),
                ok: parsed.ok !== false,
                result: parsed.result,
                step: typeof parsed.step === "number" ? parsed.step : undefined,
              },
            });
          } else if (frameType === "step") {
            emitHostMessage({
              type: "stream/step",
              payload: {
                messageId,
                index: typeof parsed.index === "number" ? parsed.index : 0,
                stop_reason:
                  typeof parsed.stop_reason === "string" || parsed.stop_reason === null
                    ? parsed.stop_reason
                    : undefined,
              },
            });
          } else if (frameType === "error") {
            sawTerminalFrame = true;
            emitHostMessage({
              type: "stream/error",
              payload: {
                messageId,
                error: String(parsed.message ?? parsed.detail ?? "Stream failed."),
                retryable: typeof parsed.retryable === "boolean" ? parsed.retryable : true,
              },
            });
          } else if (frameType === "complete" || parsed.response) {
            sawTerminalFrame = true;
            const responseObj =
              parsed.response && typeof parsed.response === "object"
                ? (parsed.response as Record<string, unknown>)
                : undefined;
            const inlineSnapshot =
              responseObj?.snapshot && typeof responseObj.snapshot === "object"
                ? (responseObj.snapshot as Record<string, unknown>)
                : undefined;
            if (inlineSnapshot) {
              const tab = await readPassiveActiveTab();
              const mapped = mapSidecarSnapshotToBootstrapData(inlineSnapshot, {
                workspaceId: auth.workspaceId,
                workspaceName: auth.workspaceName,
                paired: true,
                activeTab: tab,
                workspaceProvider: latestBootstrap?.providerConfig
                  ? {
                      configured: latestBootstrap.providerConfig.configured,
                      name: latestBootstrap.providerConfig.name,
                      model: latestBootstrap.providerConfig.model,
                      protocol: latestBootstrap.providerConfig.protocol,
                      apiKeyConfigured: latestBootstrap.providerConfig.apiKeyConfigured,
                      capabilities: latestBootstrap.providerConfig
                        .capabilities as unknown as Record<string, unknown>,
                    }
                  : undefined,
              });
              latestBootstrap = mapped;
              settledInlineSnapshot = true;
              emitHostMessage({
                type: "state/patch",
                sync: nextSyncEnvelope(auth.workspaceId, activeSessionId || "default"),
                payload: mapped,
              });
            }
            emitHostMessage({
              type: "stream/complete",
              payload: {
                messageId,
                tokens: typeof parsed.tokens === "number" ? parsed.tokens : 0,
                stopReason:
                  typeof parsed.stop_reason === "string"
                    ? parsed.stop_reason
                    : "completed",
              },
            });
          }
        }
      }

      if (!settledInlineSnapshot) {
        await fetchBootstrapSnapshot(activeSessionId);
      }
      if (!sawTerminalFrame) {
        emitHostMessage({
          type: "stream/complete",
          payload: { messageId, tokens: 0, stopReason: "completed" },
        });
      }
    } catch (error) {
      if (abortController.signal.aborted) {
        return;
      }
      emitHostMessage({
        type: "stream/error",
        payload: {
          messageId,
          error: error instanceof Error ? error.message : String(error),
          retryable: true,
        },
      });
    } finally {
      if (activeStreamAbort === abortController) {
        activeStreamAbort = null;
        activeStreamId = "";
      }
    }
  };

  const handleCancelStream = async (messageId?: string): Promise<void> => {
    const streamToCancel = messageId || activeStreamId;
    activeStreamAbort?.abort();
    activeStreamAbort = null;
    activeStreamId = "";
    emitHostMessage({
      type: "stream/cancelled",
      payload: { ...(streamToCancel ? { messageId: streamToCancel } : {}) },
    });
    if (currentAuth && streamToCancel) {
      await doFetch(`${currentAuth.baseUrl}/browser/chat/cancel`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${currentAuth.credential}`,
        },
        body: JSON.stringify({
          ...(activeSessionId ? { session_id: activeSessionId } : {}),
          stream_id: streamToCancel,
        }),
      }).catch(() => undefined);
    }
  };

  const openInVsCode = async (targetPath = "coach"): Promise<void> => {
    await sendToRuntime({
      type: "trainer:open",
      url: `${HOST_DEEP_LINK_BASE}${targetPath.replace(/^\/+/, "")}`,
    });
  };

  const handleTrainingCommand = async (
    commandId: string,
    rawPayload: Record<string, unknown>,
  ): Promise<void> => {
    const requestId =
      typeof rawPayload.__trainerTrainingPersistenceId === "string"
        ? rawPayload.__trainerTrainingPersistenceId
        : `training-${Date.now()}`;
    if (!currentAuth) {
      emitHostMessage({
        type: "training/persistenceAck",
        payload: { requestId, commandId, ok: false, message: "Not connected" },
      });
      return;
    }

    let lanePath = "";
    let body: Record<string, unknown> = {};
    if (commandId === trainerCommands.trainingAttemptStart) {
      lanePath = "/training/attempt/start";
      body = {
        card_id: rawPayload.cardId ?? rawPayload.card_id,
        ...(activeSessionId ? { session_id: activeSessionId } : {}),
      };
    } else if (commandId === trainerCommands.trainingFlashcardAnswer) {
      lanePath = "/training/flashcard/answer";
      body = {
        card_id: rawPayload.cardId ?? rawPayload.card_id,
        learner_answer: rawPayload.learnerAnswer ?? rawPayload.answer ?? "",
        ...(typeof rawPayload.selectedOptionIndex === "number"
          ? { selected_option_index: rawPayload.selectedOptionIndex }
          : {}),
        ...(Array.isArray(rawPayload.selectedOptionIndices)
          ? { selected_option_indices: rawPayload.selectedOptionIndices }
          : {}),
      };
    } else if (
      commandId === trainerCommands.trainingPracticeReturn ||
      commandId === trainerCommands.trainingReturn
    ) {
      lanePath = "/training/practice-return";
      body = {
        card_id: rawPayload.cardId ?? rawPayload.card_id,
        passed: rawPayload.passed !== false,
        summary: String(rawPayload.summary ?? rawPayload.note ?? ""),
        next_step: String(rawPayload.nextStep ?? ""),
        focus_area: String(rawPayload.focusArea ?? ""),
        evidence_source: "learner_return",
      };
    }

    if (!lanePath) {
      emitHostMessage({
        type: "training/persistenceAck",
        payload: { requestId, commandId, ok: true },
      });
      return;
    }

    try {
      const response = await doFetch(`${currentAuth.baseUrl}/browser/chat${lanePath}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${currentAuth.credential}`,
        },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      emitHostMessage({
        type: "training/persistenceAck",
        payload: {
          requestId,
          commandId,
          ok: response.ok,
          data,
        },
      });
      if (response.ok) {
        await fetchBootstrapSnapshot(activeSessionId);
      }
    } catch (error) {
      emitHostMessage({
        type: "training/persistenceAck",
        payload: {
          requestId,
          commandId,
          ok: false,
          message: error instanceof Error ? error.message : String(error),
        },
      });
    }
  };

  const handleCommandExecute = async (commandId: string, rawPayload: unknown): Promise<void> => {
    const payload =
      rawPayload && typeof rawPayload === "object"
        ? (rawPayload as Record<string, unknown>)
        : {};
    const language = resolveCurrentLanguage(persistedState);

    if (commandId === trainerCommands.listCoachSessions || commandId === "trainer.session.list") {
      const { auth } = await loadPairedAuth(true);
      if (!auth) {
        emitHostMessage({
          type: "session/list",
          payload: { ok: false, sessions: [] },
        });
        return;
      }
      const response = await doFetch(`${auth.baseUrl}/browser/chat/sessions`, {
        headers: { Authorization: `Bearer ${auth.credential}` },
        cache: "no-store",
      }).catch(() => null);
      const body = response && response.ok ? await response.json().catch(() => []) : [];
      const sessions: CoachSessionSummary[] = Array.isArray(body)
        ? body
        : Array.isArray((body as { sessions?: unknown }).sessions)
          ? ((body as { sessions: CoachSessionSummary[] }).sessions)
          : [];
      emitHostMessage({
        type: "session/list",
        payload: { ok: Boolean(response?.ok), sessions },
      });
      return;
    }

    if (commandId === trainerCommands.newCoachSession || commandId === "trainer.session.new") {
      await fetchBootstrapSnapshot("", { createNewSession: true });
      return;
    }

    if (commandId === trainerCommands.activateCoachSession || commandId === "trainer.session.select") {
      const nextSessionId = String(payload.sessionId ?? payload.session_id ?? "").trim();
      await fetchBootstrapSnapshot(nextSessionId);
      return;
    }

    if (commandId === trainerCommands.searchResources) {
      const operationId = String(payload.__trainerResourceOperationId ?? payload.requestId ?? `search-${Date.now()}`);
      const query = String(payload.query ?? "").trim();
      if (!currentAuth || !query) {
        return;
      }
      const response = await doFetch(`${currentAuth.baseUrl}/browser/chat/resource/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${currentAuth.credential}`,
        },
        body: JSON.stringify({
          ...(activeSessionId ? { session_id: activeSessionId } : {}),
          query,
          top_k: typeof payload.topK === "number" ? payload.topK : 10,
        }),
      }).catch(() => null);
      if (response?.ok) {
        const result = (await response.json().catch(() => ({}))) as Record<string, unknown>;
        const hitsRaw = Array.isArray(result.hits) ? result.hits : [];
        const resourceSearch: ResourceSearchState = {
          requestId: operationId,
          workspaceId: currentAuth.workspaceId,
          query,
          total: typeof result.total === "number" ? result.total : hitsRaw.length,
          filters: {},
          hits: hitsRaw as ResourceDetailRecord[],
        };
        emitHostMessage({
          type: "state/patch",
          sync: nextSyncEnvelope(currentAuth.workspaceId, activeSessionId || "default"),
          payload: { resourceSearch },
        });
        emitHostMessage({
          type: "operation/status",
          payload: {
            tone: "success",
            message: `[[trainer-resource-operation:search:${operationId}]] OK`,
          },
        });
      }
      return;
    }

    if (
      commandId === trainerCommands.captureResource ||
      commandId === "trainer.browserCapture.captureActiveTab"
    ) {
      const url = typeof payload.url === "string" ? payload.url.trim() : "";
      const captureOutcome = url
        ? await sendToRuntime({
            type: "trainer:capture",
            url,
            title: typeof payload.title === "string" ? payload.title : "",
          })
        : await sendToRuntime({ type: "trainer:capture-tab" });
      await fetchBootstrapSnapshot(activeSessionId);
      const operationId =
        typeof payload.__trainerResourceOperationId === "string"
          ? payload.__trainerResourceOperationId
          : undefined;
      if (operationId) {
        const ok =
          captureOutcome.status === "ok" ||
          captureOutcome.status === "duplicated" ||
          captureOutcome.status === "queued";
        emitHostMessage({
          type: "operation/status",
          payload: {
            tone: ok ? "success" : "error",
            message: `[[trainer-resource-operation:capture:${operationId}]] ${
              String(captureOutcome.message ?? (ok ? "Captured" : "Capture failed"))
            }`,
          },
        });
      }
      return;
    }

    if (commandId === "trainer.browserCapture.status") {
      emitHostMessage({
        type: "browserCapture/statusResult",
        payload: {
          prepared: true,
          paired: Boolean(currentAuth),
          capturedCount: latestBootstrap?.resources.length ?? null,
        },
      });
      return;
    }

    if (commandId.startsWith("trainer.training.") || commandId.startsWith("trainer.evidence.")) {
      await handleTrainingCommand(commandId, payload);
      return;
    }

    if (
      commandId.startsWith("trainer.provider.") ||
      commandId.startsWith("trainer.workspace.") ||
      commandId === "trainer.config.openWorkspace"
    ) {
      await openInVsCode("settings");
      emitHostMessage({
        type: "operation/status",
        payload: {
          tone: "info",
          message: (SIDEPANEL_BRIDGE_COPY[language] ?? SIDEPANEL_BRIDGE_COPY["en-US"]).openedSettingsInVsCode,
        },
      });
    }
  };

  const dispatchAction = async (rawMessage: unknown): Promise<void> => {
    if (!rawMessage || typeof rawMessage !== "object" || !("type" in rawMessage)) {
      return;
    }
    const action = rawMessage as WebviewAction | { type: string; payload?: unknown };
    switch (action.type) {
      case "webview/ready":
        return;
      case "request/bootstrap":
        await fetchBootstrapSnapshot(activeSessionId || undefined);
        return;
      case "session/sendStreamMessage":
        await handleStreamingSend((action as { payload: StreamMessageRequest }).payload);
        return;
      case "session/sendMessage":
        await handleStreamingSend((action as { payload: SessionMessageRequest }).payload);
        return;
      case "session/cancelStreamMessage":
        await handleCancelStream(
          (action as { payload?: { messageId?: string } }).payload?.messageId,
        );
        return;
      case "command/execute": {
        const cmd = (action as { payload: { commandId: string; payload?: unknown } }).payload;
        await handleCommandExecute(cmd.commandId, cmd.payload);
        return;
      }
      case "resource/upload": {
        await sendToRuntime({ type: "trainer:capture-tab" });
        await fetchBootstrapSnapshot(activeSessionId);
        return;
      }
      case "resource/open": {
        const openPayload = (action as { payload: { resourceId: string } }).payload;
        const resource = latestBootstrap?.resources.find(
          (item) => item.id === openPayload.resourceId,
        );
        const externalUrl = resource?.canonicalSource ?? resource?.source;
        if (isHttpUrl(externalUrl) && getChromeApi()?.tabs?.create) {
          void getChromeApi()?.tabs?.create?.({ url: externalUrl });
        } else {
          await openInVsCode(`library/${encodeURIComponent(openPayload.resourceId)}`);
        }
        return;
      }
      default:
        return;
    }
  };

  return {
    id: "chrome-sidepanel",
    surface: "browser-sidepanel",
    isNativeHost: true,
    getState: () => persistedState,
    setState: (next) => {
      persistedState = next;
      void setInStorage({ [WEBVIEW_STATE_STORAGE_KEY]: next });
    },
    postMessage: (message) => {
      void dispatchAction(message);
    },
    subscribe: (listener) => {
      listeners.add(listener);

      const handleTabSwitch = () => {
        void readPassiveActiveTab().then((tab) => {
          if (!latestBootstrap) return;
          const activeFile = tab
            ? (() => {
                try {
                  const host = new URL(tab.url).hostname;
                  return tab.title ? `${tab.title} (${host})` : tab.url;
                } catch {
                  return tab.title || tab.url;
                }
              })()
            : undefined;
          emitHostMessage({
            type: "state/patch",
            sync: nextSyncEnvelope(activeWorkspaceId, activeSessionId || "default"),
            payload: {
              liveContext: {
                ...latestBootstrap.liveContext,
                activeFile,
                recentFiles: tab?.url ? [tab.url] : [],
              },
            },
          });
        });
      };

      const handleTabUpdated = (_tabId: number, changeInfo: Record<string, unknown>, tab: ChromeTabLike) => {
        if (tab?.active && (changeInfo.status === "complete" || changeInfo.title || changeInfo.url)) {
          handleTabSwitch();
        }
      };

      const handleStorageChanged = (
        changes: Record<string, { oldValue?: unknown; newValue?: unknown }>,
        areaName: string,
      ) => {
        if (areaName !== "local") return;
        if (
          changes[AUTH_KEYS.credential] ||
          changes[AUTH_KEYS.baseUrl] ||
          changes[AUTH_KEYS.workspaceId]
        ) {
          void fetchBootstrapSnapshot();
        }
      };

      const chromeApi = getChromeApi();
      chromeApi?.tabs?.onActivated?.addListener(handleTabSwitch);
      chromeApi?.tabs?.onUpdated?.addListener(handleTabUpdated);
      chromeApi?.storage?.onChanged?.addListener(handleStorageChanged);

      return () => {
        listeners.delete(listener);
        chromeApi?.tabs?.onActivated?.removeListener(handleTabSwitch);
        chromeApi?.tabs?.onUpdated?.removeListener(handleTabUpdated);
        chromeApi?.storage?.onChanged?.removeListener(handleStorageChanged);
      };
    },
  };
}

/**
 * Hydrates persisted Side Panel workbench state from `chrome.storage.local` and
 * registers the unified Chrome Side Panel `WorkbenchHostTransport` before the
 * React application mounts.
 */
export async function installChromeSidePanelTransport(): Promise<WorkbenchHostTransport> {
  if (typeof window !== "undefined") {
    window.__TRAINER_SURFACE__ = "browser-sidepanel";
  }
  const stored = await storageGet({ [WEBVIEW_STATE_STORAGE_KEY]: null });
  const rawState = stored[WEBVIEW_STATE_STORAGE_KEY];
  const initialPersistedState =
    rawState && typeof rawState === "object"
      ? (rawState as PersistedWorkbenchState)
      : undefined;
  const transport = createChromeSidePanelTransport({ initialPersistedState });
  registerWorkbenchHostTransport(transport);
  return transport;
}
