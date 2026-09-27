/**
 * Composer draft history navigation (§四十八: extracted from App.tsx).
 *
 * Arrow-up/arrow-down walks previously sent user messages. The in-progress
 * draft is stashed on the first "previous" step and restored when navigation
 * runs past the newest message. Any history growth resets the cursor.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";

export function useComposerHistoryNavigation(options: {
  conversation: ReadonlyArray<{ role: string; body: string }>;
  draft: string;
  setComposerDraft: (draft: string) => void;
}) {
  const { conversation, draft, setComposerDraft } = options;
  const composerHistoryCursorRef = useRef<number | undefined>(undefined);
  const composerHistoryScratchDraftRef = useRef("");
  const sentMessageHistoryLengthRef = useRef(0);

  const sessionSentMessageHistory = useMemo(
    () =>
      conversation
        .filter((message) => message.role === "user")
        .map((message) => message.body.trim())
        .filter(Boolean),
    [conversation],
  );

  const resetComposerHistoryNavigation = useCallback(() => {
    composerHistoryCursorRef.current = undefined;
    composerHistoryScratchDraftRef.current = "";
  }, []);

  useEffect(() => {
    if (sentMessageHistoryLengthRef.current === sessionSentMessageHistory.length) {
      return;
    }
    sentMessageHistoryLengthRef.current = sessionSentMessageHistory.length;
    resetComposerHistoryNavigation();
  }, [resetComposerHistoryNavigation, sessionSentMessageHistory.length]);

  const navigateComposerHistory = useCallback(
    (direction: "previous" | "next") => {
      if (sessionSentMessageHistory.length === 0) {
        return false;
      }

      const currentIndex = composerHistoryCursorRef.current;
      if (direction === "previous") {
        const nextIndex =
          currentIndex === undefined
            ? sessionSentMessageHistory.length - 1
            : currentIndex > 0
              ? currentIndex - 1
              : undefined;
        if (nextIndex === undefined) {
          return false;
        }
        if (currentIndex === undefined) {
          composerHistoryScratchDraftRef.current = draft;
        }
        composerHistoryCursorRef.current = nextIndex;
        setComposerDraft(sessionSentMessageHistory[nextIndex] ?? "");
        return true;
      }

      if (currentIndex === undefined) {
        return false;
      }
      const nextIndex = currentIndex + 1;
      if (nextIndex >= sessionSentMessageHistory.length) {
        composerHistoryCursorRef.current = undefined;
        setComposerDraft(composerHistoryScratchDraftRef.current);
        composerHistoryScratchDraftRef.current = "";
        return true;
      }

      composerHistoryCursorRef.current = nextIndex;
      setComposerDraft(sessionSentMessageHistory[nextIndex] ?? "");
      return true;
    },
    [draft, sessionSentMessageHistory, setComposerDraft],
  );

  return { sessionSentMessageHistory, resetComposerHistoryNavigation, navigateComposerHistory };
}
