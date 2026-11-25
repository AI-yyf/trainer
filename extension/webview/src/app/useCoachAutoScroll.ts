import { useEffect, useRef, type MutableRefObject, type RefObject } from "react";
import type { ActiveWorkbenchView } from "../lib/types";
import { getSurfaceScrollElement, resolveCoachBottomScrollTop } from "./useSurfaceScroll";
import { useWorkbenchState } from "./useWorkbenchState";

/** Auto-follow owns live turns; saved reading positions belong to useSurfaceScroll. */
export function useCoachAutoScroll({
  viewContentRef, activeView, scope, conversationLength, lastMessageRole,
  optimisticLength, isStreaming, coachAutoScrollPinnedRef, restoringSavedPosition,
}: {
  viewContentRef: RefObject<HTMLElement>;
  activeView: ActiveWorkbenchView;
  scope: string;
  conversationLength: number;
  lastMessageRole?: string;
  optimisticLength: number;
  isStreaming: boolean;
  coachAutoScrollPinnedRef: MutableRefObject<boolean>;
  restoringSavedPosition: RefObject<boolean>;
}) {
  const coachWasStreamingRef = useRef(false);
  const coachViewIdentityRef = useRef<string | null>(null);
  const coachConversationLengthRef = useRef(0);
  const coachOptimisticLengthRef = useRef(0);
  // The imperative streaming subscription below reads the active view without
  // re-subscribing; keep the latest value in a ref.
  const activeViewRef = useRef(activeView);
  activeViewRef.current = activeView;

  useEffect(() => {
    const viewChanged =
      coachViewIdentityRef.current !== null && coachViewIdentityRef.current !== activeView;
    coachViewIdentityRef.current = activeView;
    if (activeView !== "coach") {
      return;
    }

    const container = viewContentRef.current && getSurfaceScrollElement(viewContentRef.current, "coach");
    if (!container) {
      return;
    }

    // Stick-to-bottom only while the reader is already at (or near) the
    // bottom; scrolling up during a stream must stay respected.
    const isPinnedToBottom = () =>
      resolveCoachBottomScrollTop(container) - container.scrollTop < 120;

    let lastScrollTop = container.scrollTop;
    const handleScroll = () => {
      if (restoringSavedPosition.current) return;
      const currentScrollTop = container.scrollTop;
      const scrolledUp = currentScrollTop < lastScrollTop - 4;
      lastScrollTop = currentScrollTop;
      if (scrolledUp) {
        coachAutoScrollPinnedRef.current = false;
      } else if (isPinnedToBottom()) {
        coachAutoScrollPinnedRef.current = true;
      }
    };
    container.addEventListener("scroll", handleScroll, { passive: true });

    // A send always reveals the turn the learner just started, even when they
    // were reading older messages. Once streaming is running, the pin follows
    // their scroll position again so browsing history stays respected.
    const streamingStarted = isStreaming && !coachWasStreamingRef.current;
    const streamingEnded = !isStreaming && coachWasStreamingRef.current;
    coachWasStreamingRef.current = isStreaming;
    // The learner's own turn must always be visible, even when the streaming
    // edge was already consumed (a restored stream, or a mount that happened
    // mid-turn). Otherwise the reply lands below the fold and the thread looks
    // stuck.
    const serverConversationGrew = conversationLength > coachConversationLengthRef.current;
    const optimisticGrew = optimisticLength > coachOptimisticLengthRef.current;
    coachConversationLengthRef.current = conversationLength;
    coachOptimisticLengthRef.current = optimisticLength;
    const conversationGrew = serverConversationGrew || optimisticGrew;
    const learnerTurn =
      optimisticGrew ||
      (serverConversationGrew &&
        lastMessageRole === "user");
    const previouslyPinned = coachAutoScrollPinnedRef.current;
    coachAutoScrollPinnedRef.current =
      (streamingStarted && !viewChanged) ||
      learnerTurn ||
      ((conversationGrew || streamingEnded) && !viewChanged && previouslyPinned) ||
      isPinnedToBottom();
    if (restoringSavedPosition.current && !streamingStarted && !optimisticGrew) {
      coachAutoScrollPinnedRef.current = false;
    }
    const scrollToBottom = () => {
      if (restoringSavedPosition.current) return;
      container.scrollTop = resolveCoachBottomScrollTop(container);
      lastScrollTop = container.scrollTop;
    };
    if (coachAutoScrollPinnedRef.current && (streamingStarted || learnerTurn || conversationGrew || streamingEnded)) {
      scrollToBottom();
    }
    const handle = window.requestAnimationFrame(() => {
      if (coachAutoScrollPinnedRef.current) {
        scrollToBottom();
      }
    });
    const settle =
      streamingStarted || conversationGrew || streamingEnded
        ? window.setTimeout(() => {
            if (coachAutoScrollPinnedRef.current) {
              scrollToBottom();
            }
          }, 90)
        : undefined;

    return () => {
      window.cancelAnimationFrame(handle);
      if (settle !== undefined) {
        window.clearTimeout(settle);
      }
      container.removeEventListener("scroll", handleScroll);
    };
  }, [activeView, conversationLength, optimisticLength, isStreaming, lastMessageRole, scope, viewContentRef, coachAutoScrollPinnedRef, restoringSavedPosition]);

  // Per-chunk content and agent stages are not part of App's subscription;
  // the stick-to-bottom pin follows the store directly so every live stage
  // transition, tool call, and chunk re-sticks without an App re-render.
  useEffect(() => {
    let rafHandle: number | undefined;
    const unsubscribe = useWorkbenchState.subscribe((state, previous) => {
      const streamProgressed =
        state.streaming.streamedContent !== previous.streaming.streamedContent ||
        state.streaming.agentActivity.length !== previous.streaming.agentActivity.length ||
        state.streaming.liveStageKind !== previous.streaming.liveStageKind ||
        (state.streaming.isStreaming && !previous.streaming.isStreaming);
      if (!streamProgressed) {
        return;
      }
      if (activeViewRef.current !== "coach" || !coachAutoScrollPinnedRef.current || restoringSavedPosition.current) {
        return;
      }
      const container =
        viewContentRef.current && getSurfaceScrollElement(viewContentRef.current, "coach");
      if (!container) {
        return;
      }
      container.scrollTop = resolveCoachBottomScrollTop(container);
      if (rafHandle !== undefined) {
        window.cancelAnimationFrame(rafHandle);
      }
      rafHandle = window.requestAnimationFrame(() => {
        rafHandle = undefined;
        if (activeViewRef.current === "coach" && coachAutoScrollPinnedRef.current && !restoringSavedPosition.current) {
          container.scrollTop = resolveCoachBottomScrollTop(container);
        }
      });
    });
    return () => {
      if (rafHandle !== undefined) {
        window.cancelAnimationFrame(rafHandle);
      }
      unsubscribe();
    };
  }, [coachAutoScrollPinnedRef, restoringSavedPosition, viewContentRef]);

}
