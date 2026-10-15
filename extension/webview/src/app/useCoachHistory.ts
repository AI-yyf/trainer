import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { postMessage } from "../lib/vscode";
import { trainerCommands } from "../../../../shared/src/commands";
import type { CoachSessionSummary } from "../lib/types";

export type CoachHistoryStatus = "idle" | "loading" | "ready" | "error";

export type ComposerContextMenu =
  | "context"
  | "resources"
  | "model"
  | "history"
  | undefined;

export interface CoachSessionListPayload {
  sessions: CoachSessionSummary[];
  ok?: boolean;
  message?: string;
}

const HISTORY_CACHE_PREFIX = "trainer.coachHistory.v1.";

function historyCacheKey(cacheScope: string): string {
  return `${HISTORY_CACHE_PREFIX}${cacheScope.trim() || "default"}`;
}

function readCachedSessions(cacheScope: string): CoachSessionSummary[] {
  try {
    const raw = window.localStorage.getItem(historyCacheKey(cacheScope));
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as { sessions?: unknown };
    return Array.isArray(parsed?.sessions) ? (parsed.sessions as CoachSessionSummary[]) : [];
  } catch {
    return [];
  }
}

function writeCachedSessions(cacheScope: string, sessions: CoachSessionSummary[]): void {
  try {
    window.localStorage.setItem(
      historyCacheKey(cacheScope),
      JSON.stringify({ savedAt: Date.now(), sessions }),
    );
  } catch {
    // Cache write failure only costs first-open latency, never correctness.
  }
}

/** Pure: the synthetic entry the browser preview shows for the live chat. */
export function buildPreviewSessionEntry(input: {
  previewSessionId: string | undefined;
  zh: boolean;
  conversationCount: number;
}): CoachSessionSummary {
  return {
    session_id: input.previewSessionId || "preview-session",
    summary: input.zh ? "当前会话" : "Current conversation",
    message_count: input.conversationCount,
    updated_at: new Date().toISOString(),
    is_active: true,
  };
}

/** Pure: reduce a host "session/list" message into the list state. */
export function applySessionListPayload(
  payload: CoachSessionListPayload | undefined,
): {
  sessions: CoachSessionSummary[];
  status: CoachHistoryStatus;
  message: string | undefined;
} {
  const payloadRecord = payload && typeof payload === "object" ? payload : undefined;
  return {
    sessions: Array.isArray(payloadRecord?.sessions) ? payloadRecord.sessions : [],
    status: payloadRecord?.ok ? "ready" : "error",
    message: payloadRecord?.message,
  };
}

export interface UseCoachHistoryInput {
  isBrowserPreview: boolean;
  composerLanguage: "zh-CN" | string;
  previewSessionId: string | undefined;
  conversationCount: number;
  /** Cache scope: the workspace name, so another window never sees foreign sessions. */
  cacheScope: string;
  setOpenMenu: Dispatch<SetStateAction<ComposerContextMenu | undefined>>;
  setOperationMessage: (message: {
    tone: "info" | "error";
    message: string;
  }) => void;
}

export interface CoachHistoryController {
  coachSessions: CoachSessionSummary[];
  coachSessionsStatus: CoachHistoryStatus;
  coachSessionsMessage: string | undefined;
  applySessionList: (payload: unknown) => void;
  requestCoachSessions: () => void;
  toggleComposerHistoryMenu: () => void;
  activateCoachSession: (sessionId: string) => void;
  startNewCoachChat: () => void;
}

/**
 * §六十三/§14: session-history state and actions. Extracted from App.tsx so
 * the mega-file stops growing; behavior is identical to the inlined version.
 */
export function useCoachHistory(input: UseCoachHistoryInput): CoachHistoryController {
  const {
    isBrowserPreview,
    composerLanguage,
    previewSessionId,
    conversationCount,
    cacheScope,
    setOpenMenu,
    setOperationMessage,
  } = input;
  const zh = composerLanguage === "zh-CN";

  // The cached list hydrates synchronously: the first click renders instantly,
  // and the refresh below silently replaces it with the authoritative list.
  const [coachSessions, setCoachSessions] = useState<CoachSessionSummary[]>(() =>
    readCachedSessions(cacheScope),
  );
  const [coachSessionsStatus, setCoachSessionsStatus] = useState<CoachHistoryStatus>(() =>
    coachSessions.length > 0 ? "ready" : "idle",
  );
  const [coachSessionsMessage, setCoachSessionsMessage] = useState<string>();
  const prefetchedRef = useRef(false);

  const applySessionList = useCallback(
    (payload: unknown) => {
      const next = applySessionListPayload(payload as CoachSessionListPayload);
      setCoachSessions(next.sessions);
      setCoachSessionsStatus(next.status);
      setCoachSessionsMessage(next.message);
      if (next.status === "ready" && next.sessions.length > 0) {
        writeCachedSessions(cacheScope, next.sessions);
      }
    },
    [cacheScope],
  );

  const requestCoachSessions = useCallback(() => {
    // With a hydrated cache the refresh stays quiet: the list remains on
    // screen while the authoritative fetch runs, so the click never waits.
    setCoachSessionsStatus((current) =>
      current === "ready" || current === "loading" ? current : "loading",
    );
    setCoachSessionsMessage(undefined);
    if (isBrowserPreview) {
      setCoachSessions([
        buildPreviewSessionEntry({
          previewSessionId,
          zh,
          conversationCount,
        }),
      ]);
      setCoachSessionsStatus("ready");
      return;
    }
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.listCoachSessions },
    });
  }, [conversationCount, isBrowserPreview, previewSessionId, zh]);

  // Prefetch once on mount: the cache warms (and the sidecar starts warming)
  // long before the first history click.
  useEffect(() => {
    if (prefetchedRef.current || isBrowserPreview) {
      return;
    }
    prefetchedRef.current = true;
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.listCoachSessions },
    });
  }, [isBrowserPreview]);

  const toggleComposerHistoryMenu = useCallback(() => {
    setOpenMenu((current: ComposerContextMenu) => {
      const next = current === "history" ? undefined : "history";
      if (next === "history") {
        requestCoachSessions();
      }
      return next;
    });
  }, [requestCoachSessions, setOpenMenu]);

  const activateCoachSession = useCallback(
    (sessionId: string) => {
      const trimmed = sessionId.trim();
      if (!trimmed) {
        return;
      }
      setOpenMenu(undefined);
      if (isBrowserPreview) {
        return;
      }
      postMessage({
        type: "command/execute",
        payload: {
          commandId: trainerCommands.activateCoachSession,
          payload: { sessionId: trimmed },
        },
      });
    },
    [isBrowserPreview, setOpenMenu],
  );

  const startNewCoachChat = useCallback(() => {
    setOpenMenu(undefined);
    if (isBrowserPreview) {
      setOperationMessage({
        tone: "info",
        message: zh
          ? "预览模式不会创建新会话。"
          : "Preview mode does not create new conversations.",
      });
      return;
    }
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.newCoachSession },
    });
  }, [isBrowserPreview, setOpenMenu, zh]);

  return {
    coachSessions,
    coachSessionsStatus,
    coachSessionsMessage,
    applySessionList,
    requestCoachSessions,
    toggleComposerHistoryMenu,
    activateCoachSession,
    startNewCoachChat,
  };
}
