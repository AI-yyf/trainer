import { useCallback, useEffect, useRef, useState } from "react";

import type { ActiveWorkbenchView, ConversationMessage } from "../lib/types";

/**
 * Coach-conversation controller (DESIGN.md §3, round 3).
 *
 * Owns the conversation domain's local interaction state so App only
 * assembles: optimistic user echoes, the one-at-a-time reply action with its
 * 30s guard, the browser-preview session id, the view that produced the last
 * turn, and the context-transition signature.
 */

const PENDING_MESSAGE_ACTION_TIMEOUT_MS = 30_000;
const OPTIMISTIC_TURN_TTL_MS = 120_000;

export interface OptimisticTurn {
  id: string;
  body: string;
  baseLength: number;
  createdAt: number;
}

export interface CoachContextTransition {
  signature: string;
  conversationLength: number;
}

export function useCoachConversationController({
  conversation,
  onOptimisticTurnAppended,
}: {
  conversation: ConversationMessage[];
  /** App keeps its own scroll pin; an echo re-pins the conversation. */
  onOptimisticTurnAppended?: () => void;
}) {
  const [optimisticTurns, setOptimisticTurns] = useState<OptimisticTurn[]>([]);
  // The echo records the conversation length at send time; keep the latest
  // value in a ref so the callback stays stable across renders.
  const conversationLengthRef = useRef(conversation.length);
  conversationLengthRef.current = conversation.length;
  const appendOptimisticTurn = useCallback((body: string) => {
    const trimmed = body.trim();
    if (!trimmed) {
      return;
    }
    setOptimisticTurns((current) => [
      ...current,
      {
        id: `optimistic-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        body: trimmed,
        baseLength: conversationLengthRef.current,
        createdAt: Date.now(),
      },
    ]);
    onOptimisticTurnAppended?.();
  }, [onOptimisticTurnAppended]);

  // Drop echoes once the server-confirmed turn lands at the same position (or
  // they outlive their TTL).
  useEffect(() => {
    setOptimisticTurns((current) => {
      if (current.length === 0) {
        return current;
      }
      const now = Date.now();
      const next = current.filter((entry) => {
        if (now - entry.createdAt > OPTIMISTIC_TURN_TTL_MS) {
          return false;
        }
        if (entry.baseLength >= conversation.length) {
          return true;
        }
        const tail = conversation.slice(entry.baseLength);
        return !tail.some(
          (item) => item.role === "user" && item.body.trim() === entry.body.trim(),
        );
      });
      return next.length === current.length ? current : next;
    });
  }, [conversation]);

  const [pendingMessageAction, setPendingMessageAction] = useState<string | null>(null);
  const pendingMessageActionRef = useRef<string | null>(null);
  const pendingMessageActionTimeoutRef = useRef<number | undefined>(undefined);

  /**
   * Arms the one-at-a-time reply action. Returns false when another action is
   * still pending (the caller must not start a second one). Save-to-resource
   * settles through its own upload ack, so it skips the 30s guard.
   */
  const beginPendingMessageAction = useCallback((key: string) => {
    if (pendingMessageActionRef.current) {
      return false;
    }
    pendingMessageActionRef.current = key;
    setPendingMessageAction(key);
    if (pendingMessageActionTimeoutRef.current !== undefined) {
      window.clearTimeout(pendingMessageActionTimeoutRef.current);
    }
    if (!key.endsWith(":save-resource")) {
      pendingMessageActionTimeoutRef.current = window.setTimeout(() => {
        pendingMessageActionRef.current = null;
        setPendingMessageAction(null);
        pendingMessageActionTimeoutRef.current = undefined;
      }, PENDING_MESSAGE_ACTION_TIMEOUT_MS);
    }
    return true;
  }, []);

  const finishPendingMessageAction = useCallback(() => {
    if (pendingMessageActionTimeoutRef.current !== undefined) {
      window.clearTimeout(pendingMessageActionTimeoutRef.current);
      pendingMessageActionTimeoutRef.current = undefined;
    }
    pendingMessageActionRef.current = null;
    setPendingMessageAction(null);
  }, []);

  /**
   * An unrelated status (or a new stream) settles a stale action — except the
   * save-to-resource upload, which waits for its own request-id ack.
   */
  const clearPendingMessageActionUnless = useCallback((keepSuffix: string) => {
    if (pendingMessageActionRef.current?.endsWith(keepSuffix)) {
      return;
    }
    if (pendingMessageActionTimeoutRef.current !== undefined) {
      window.clearTimeout(pendingMessageActionTimeoutRef.current);
      pendingMessageActionTimeoutRef.current = undefined;
    }
    pendingMessageActionRef.current = null;
    setPendingMessageAction(null);
  }, []);

  const [previewSessionId, setPreviewSessionId] = useState<string>();
  const [lastTurnView, setLastTurnView] = useState<ActiveWorkbenchView>();
  const [coachContextTransition, setCoachContextTransition] = useState<CoachContextTransition>();

  useEffect(() => {
    return () => {
      if (pendingMessageActionTimeoutRef.current !== undefined) {
        window.clearTimeout(pendingMessageActionTimeoutRef.current);
        pendingMessageActionTimeoutRef.current = undefined;
      }
    };
  }, []);

  return {
    optimisticTurns,
    appendOptimisticTurn,
    pendingMessageAction,
    beginPendingMessageAction,
    finishPendingMessageAction,
    clearPendingMessageActionUnless,
    previewSessionId,
    setPreviewSessionId,
    lastTurnView,
    setLastTurnView,
    coachContextTransition,
    setCoachContextTransition,
  };
}
