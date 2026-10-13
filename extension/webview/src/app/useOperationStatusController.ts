import { useCallback, useEffect, useRef } from "react";

import type { TrainerOperationMessage } from "../../../../shared/src/protocol";
import {
  resolveOperationMessageSurface,
  sanitizeOperationFailureMessage,
  type OperationMessageSurface,
} from "../lib/operationMessageGovernance";
import { normalizeSidebarView } from "../lib/types";
import { useWorkbenchState } from "./useWorkbenchState";

/**
 * Operation-status controller (DESIGN.md §3, round 2).
 *
 * The store owns the single channel: `operationMessage` + `operationMessageSurface`
 * are written together, so a scoped notice can never inherit another domain's
 * scope (§四十四). This hook owns the interaction layer around it:
 *
 * - the atomic setter (sanitize + resolve the surface from the RAW text, then
 *   write message and surface in one store update),
 * - banner visibility for the active view,
 * - the leave animation and error-until-dismissed / notice-self-dismiss rules.
 *
 * Every writer goes through the store action, so the invariant holds the same
 * way for host messages (App passes the pre-sanitization surface into
 * `applyHostMessage`) and for local notices.
 */

type OperationMessage = TrainerOperationMessage;

export interface OperationStatusController {
  operationMessage?: OperationMessage;
  operationMessageSurface: OperationMessageSurface;
  /** True while the banner belongs to the active view ("global" always shows). */
  operationMessageVisible: boolean;
  /**
   * Writes message + surface atomically. `surface` is optional only for
   * messages whose text carries a trainer marker (auto-scoped); callers that
   * know their domain must name it.
   */
  setOperationMessage: (message?: OperationMessage, surface?: OperationMessageSurface) => void;
  dismissOperationMessage: () => void;
}

export function useOperationStatusController(): OperationStatusController {
  const operationMessage = useWorkbenchState((state) => state.operationMessage);
  const operationMessageSurface = useWorkbenchState((state) => state.operationMessageSurface);
  const activeView = useWorkbenchState((state) => normalizeSidebarView(state.layout.activeView));
  const composerLanguage = useWorkbenchState((state) => state.layout.composerLanguage);
  const operationMessageDismissTimerRef = useRef<number>();

  const setOperationMessage = useCallback(
    (message?: OperationMessage, surface?: OperationMessageSurface) => {
      // Resolve the scope on the raw text (sanitization rewrites markers), then
      // hand the explicit surface to the store together with the message.
      const resolvedSurface = resolveOperationMessageSurface(message?.message, surface);
      useWorkbenchState.getState().setOperationMessage(
        message ? sanitizeOperationFailureMessage(message, composerLanguage) : undefined,
        resolvedSurface,
      );
    },
    [composerLanguage],
  );

  // Success/info notices self-dismiss; errors stay until explicitly closed.
  // Both paths wait out the exit beat before the message is removed.
  const dismissOperationMessage = useCallback(() => {
    const expected = useWorkbenchState.getState().operationMessage;
    if (!expected) return;
    window.clearTimeout(operationMessageDismissTimerRef.current);
    operationMessageDismissTimerRef.current = window.setTimeout(() => {
      operationMessageDismissTimerRef.current = undefined;
      useWorkbenchState.getState().clearOperationMessage(expected);
    }, 180);
  }, []);

  useEffect(() => {
    // A later notice owns its dismissal; an earlier pending exit must not
    // remove the message that replaced it.
    window.clearTimeout(operationMessageDismissTimerRef.current);
    operationMessageDismissTimerRef.current = undefined;
    return () => window.clearTimeout(operationMessageDismissTimerRef.current);
  }, [operationMessage]);

  useEffect(() => {
    if (!operationMessage || operationMessage.tone === "error") {
      return;
    }
    const timer = window.setTimeout(() => dismissOperationMessage(), 5000);
    return () => window.clearTimeout(timer);
  }, [operationMessage, dismissOperationMessage]);

  return {
    operationMessage,
    operationMessageSurface,
    operationMessageVisible:
      operationMessageSurface === "global" || operationMessageSurface === activeView,
    setOperationMessage,
    dismissOperationMessage,
  };
}
