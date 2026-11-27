import {
  useEffect,
  useMemo,
  useRef
} from "react";

import { resolveEffectiveTokenBudgetProfile } from "../../../../shared/src/smartTokenBudget";
import { formatTokenCount } from "../lib/formatUtils";
import {
  appUiCopy
} from "../lib/i18n/appUiCopy";
import {
  recoverableFailureMessage
} from "../lib/operationMessageGovernance";
import { applyWorkbenchTheme } from "../lib/theme";
import type {
  BootstrapData
} from "../lib/types";
import {
  getInjectedBootstrapState,
  postMessage,
  subscribeToHostMessages
} from "../lib/vscode";
import { useCoachAutoScroll } from "./useCoachAutoScroll";
import { useSurfaceScroll } from "./useSurfaceScroll";
import { useWorkbenchState } from "./useWorkbenchState";

// ContextMenu type imported from useMenuState
import {
  type WorkbenchCtxAfterK1
} from "./App";
import {
  requestBootstrapOnce,
  requireBrowserPreviewAdapter,
  syncBootstrapLifecycleOnVisible
} from "./appHelpers";

export function useWorkbenchLifecycleEffects(ctx: WorkbenchCtxAfterK1) {
  const {
    data,
    layout,
    hasReceivedHostState,
    setComposerDraft,
    streamingContentBucket,
    operationMessage,
    setOperationMessage,
    optimisticTurns,
    previewSessionId,
    setPreviewSessionId,
    streaming,
    openMenu,
    setOpenMenu,
    setSelectedCommandIndex,
    setDismissedComposerDeck,
    isBrowserPreview,
    activeView,
    composerSessionKey,
    hostMessageSequenceRef,
    composerModelSearchRef,
    viewContentRef,
    applyHostMessageRef,
    coachAutoScrollPinnedRef,
    injectedPreviewBootstrapHydratedRef,
    pendingLivePlanTaskMintRef,
    resolvedTheme,
    applyHostMessage,
    normalizedDraft,
    applyBrowserPreviewLocationOverrides,
    setComposerModelQuery,
  } = ctx;
  // R3②: context usage used to re-tally the entire conversation plus the
  // full streamed content character-by-character on every stream chunk
  // (O(conversation + stream) per chunk, O(n²) per turn). Both tallies are
  // now cached: the conversation part recomputes only when the conversation
  // array identity changes (per turn, not per chunk), and the stream part
  // only tallies the newly appended slice (streamedContent grows
  // monotonically per streamMessageId; any shrink or id change resets it).
  // StrictMode double-invocation is safe: both caches are keyed by identity
  // and re-run with the same inputs returns the cached values untouched.
  const composerContextTallyRef = useRef<{
    conversation: typeof data.conversation | undefined;
    conversationCjk: number;
    conversationOther: number;
    streamMessageId: string | undefined;
    streamConsumedChars: number;
    streamCjk: number;
    streamOther: number;
  }>({
    conversation: undefined,
    conversationCjk: 0,
    conversationOther: 0,
    streamMessageId: undefined,
    streamConsumedChars: 0,
    streamCjk: 0,
    streamOther: 0,
  });

  const composerContextUsage = useMemo(() => {
    const provider = data.providerConfig;
    const model = provider.resolvedModel ?? provider.model;
    const explicitLimit =
      (model ? provider.modelTokenLimits?.[model]?.contextWindowTokens : undefined) ??
      provider.contextWindowTokens;
    const limit =
      explicitLimit ??
      (provider.configured || Boolean(model?.trim())
        ? resolveEffectiveTokenBudgetProfile({
            model,
            protocol: provider.protocol,
            baseUrl: provider.baseUrl,
            providerName: provider.name,
          }).effectiveContextWindowTokens
        : undefined);
    const cjkPattern = /[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]/;
    const tally = (text: string): { cjk: number; other: number } => {
      let cjk = 0;
      let other = 0;
      for (const ch of text) {
        if (cjkPattern.test(ch)) {
          cjk += 1;
        } else {
          other += 1;
        }
      }
      return { cjk, other };
    };
    const cache = composerContextTallyRef.current;
    if (cache.conversation !== data.conversation) {
      let cjk = 0;
      let other = 0;
      for (const message of data.conversation) {
        const bodyTally = tally(message.body ?? "");
        cjk += bodyTally.cjk;
        other += bodyTally.other;
        for (const attachment of message.attachments ?? []) {
          const attachmentTally = tally(attachment.value ?? "");
          cjk += attachmentTally.cjk;
          other += attachmentTally.other;
        }
        // Per-message framing overhead (role tags, separators).
        other += 16;
      }
      cache.conversation = data.conversation;
      cache.conversationCjk = cjk;
      cache.conversationOther = other;
    }
    let cjk = cache.conversationCjk;
    let other = cache.conversationOther;
    // The streaming text is read from the store when this memo re-runs (the
    // coarse bucket below schedules that; the final value lands on the
    // stream-end flip), so App itself never subscribes per chunk.
    const streamed = useWorkbenchState.getState().streaming.streamedContent ?? "";
    const streamReset =
      streaming.streamMessageId !== cache.streamMessageId ||
      streamed.length < cache.streamConsumedChars;
    if (streamReset) {
      const full = tally(streamed);
      cache.streamMessageId = streaming.streamMessageId;
      cache.streamConsumedChars = streamed.length;
      cache.streamCjk = full.cjk;
      cache.streamOther = full.other;
    } else if (streamed.length > cache.streamConsumedChars) {
      const delta = tally(streamed.slice(cache.streamConsumedChars));
      cache.streamConsumedChars = streamed.length;
      cache.streamCjk += delta.cjk;
      cache.streamOther += delta.other;
    }
    cjk += cache.streamCjk;
    other += cache.streamOther;
    // A system/pedagogy prompt is always prepended server-side.
    const systemOverhead = 1200;
    const used = Math.ceil(cjk + other / 4) + systemOverhead;
    const ratio = limit && limit > 0 ? Math.min(1, used / limit) : undefined;
    return { used, limit, ratio };
  }, [
    data.conversation,
    data.providerConfig,
    streaming.streamMessageId,
    streamingContentBucket,
    streaming.isStreaming,
  ]);

  const composerContextUsageTone = composerContextUsage.ratio === undefined
    ? "unknown"
    : composerContextUsage.ratio >= 0.85
      ? "critical"
      : composerContextUsage.ratio >= 0.6
        ? "warn"
        : "ok";

  const composerContextUsageDetail = composerContextUsage.limit
    ? appUiCopy(
        layout.composerLanguage,
        "本会话已用约 {u} 个上下文，上限约 {l}（约 {p}%）。这是按消息长度估算的近似值。",
      )
        .replace("{u}", formatTokenCount(composerContextUsage.used))
        .replace("{l}", formatTokenCount(composerContextUsage.limit))
        .replace("{p}", String(Math.round((composerContextUsage.ratio ?? 0) * 100)))
    : appUiCopy(
        layout.composerLanguage,
        "本会话已用约 {u} 个上下文（按消息长度估算）。该连接没有可靠的上下文上限，所以只显示估算值。",
      ).replace("{u}", formatTokenCount(composerContextUsage.used));

  const composerContextRingNode = (
    <svg
      viewBox="0 0 18 18"
      width="18"
      height="18"
      aria-hidden="true"
      className={`composer-context-ring composer-context-ring--${composerContextUsageTone}`}
    >
      {/* r1-g0-3: the idle ring reads as "◎" only when the track is visible —
          the old 0.18-opacity track all but vanished at 18px. */}
      <circle
        cx="9"
        cy="9"
        r="7"
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.32"
        strokeWidth="2.2"
      />
      {composerContextUsage.ratio !== undefined ? (
        <circle
          cx="9"
          cy="9"
          r="7"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeDasharray={`${(composerContextUsage.ratio * 43.98).toFixed(2)} 43.98`}
          transform="rotate(-90 9 9)"
        />
      ) : (
        <circle cx="9" cy="9" r="1.9" fill="currentColor" />
      )}
    </svg>
  );

  // History has a single header entry point (trainer-history-toggle); the
  // composer secondary row stays minimal (context usage + model switch).

  useEffect(() => {
    const pending = pendingLivePlanTaskMintRef.current;
    if (!pending || !operationMessage) {
      return;
    }
    if (operationMessage.tone === "info") {
      return;
    }
    pendingLivePlanTaskMintRef.current = undefined;
    if (operationMessage.tone === "success" && pending.scope) {
      const current = useWorkbenchState.getState().layout;
      const text = current.composerDraftScope === pending.scope ? current.composerDraft : current.composerDrafts?.[pending.scope];
      if (text === pending.draft) setComposerDraft("", pending.scope);
      setDismissedComposerDeck(undefined);
    }
  }, [operationMessage, setComposerDraft]);

  useEffect(() => {
    applyWorkbenchTheme(resolvedTheme, layout.themePreference === "system");
  }, [resolvedTheme, layout.themePreference]);

  // The host-message dispatch changes identity whenever layout values or
  // settings action state change. Keep the subscription and the one-shot
  // bootstrap request out of that churn: re-running this effect used to call
  // `requestBootstrapOnce` again after the bootstrap guard re-armed, which
  // re-posted `request/bootstrap` and produced a continuous
  // POST /memory/settings + GET /memory/summary loop against the sidecar.
  useEffect(() => {
    applyHostMessageRef.current = applyHostMessage;
  }, [applyHostMessage]);

  useEffect(() => {
    const unsubscribe = subscribeToHostMessages((message) => {
      applyHostMessageRef.current(message);
    });
    requestBootstrapOnce();
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (isBrowserPreview || hasReceivedHostState) {
      return;
    }

    const timer = window.setTimeout(() => {
      requestBootstrapOnce(true);
    }, 1800);

    return () => {
      window.clearTimeout(timer);
    };
  }, [hasReceivedHostState, isBrowserPreview]);

  useEffect(() => {
    if (isBrowserPreview) {
      return;
    }

    const handleVisibility = () => {
      if (document.visibilityState !== "visible") {
        return;
      }
      // With host state already in the store, refocusing is free: the host
      // pushes incremental patches and the runtime is never re-initialized.
      if (!hasReceivedHostState) {
        syncBootstrapLifecycleOnVisible(hasReceivedHostState);
      }
    };

    window.addEventListener("focus", handleVisibility);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("focus", handleVisibility);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [hasReceivedHostState, isBrowserPreview]);

  useEffect(() => {
    if (!isBrowserPreview) {
      return;
    }
    applyBrowserPreviewLocationOverrides();
  }, [applyBrowserPreviewLocationOverrides, isBrowserPreview]);

  // Bootstrap the live browser preview at most once per mount. The callbacks
  // below change identity on every layout/settings state change, so they are
  // read through a ref: keying this effect on them refetched the full
  // POST /memory/settings + GET /memory/summary bootstrap on every churn, and
  // `previewSessionId` resolving from undefined to a session id doubled it.
  const browserPreviewBootstrapDepsRef = useRef({
    applyHostMessage,
    applyBrowserPreviewLocationOverrides,
    setOperationMessage,
    composerLanguage: layout.composerLanguage,
    previewSessionId,
  });
  useEffect(() => {
    browserPreviewBootstrapDepsRef.current = {
      applyHostMessage,
      applyBrowserPreviewLocationOverrides,
      setOperationMessage,
      composerLanguage: layout.composerLanguage,
      previewSessionId,
    };
  });
  useEffect(() => {
    if (!isBrowserPreview) {
      return;
    }

    const {
      applyHostMessage: dispatchHostMessage,
      applyBrowserPreviewLocationOverrides: applyLocationOverrides,
      setOperationMessage: reportOperationMessage,
      composerLanguage,
      previewSessionId: bootstrapSessionId,
    } = browserPreviewBootstrapDepsRef.current;

    const injectedPreviewBootstrap = getInjectedBootstrapState<BootstrapData>();
    if (injectedPreviewBootstrap && typeof injectedPreviewBootstrap === "object") {
      if (injectedPreviewBootstrapHydratedRef.current) {
        return;
      }
      injectedPreviewBootstrapHydratedRef.current = true;
      dispatchHostMessage({
        type: "bootstrap",
        payload: structuredClone(injectedPreviewBootstrap),
      });
      applyLocationOverrides();
      return;
    }

    let cancelled = false;
    const requestSequence = hostMessageSequenceRef.current;
    void requireBrowserPreviewAdapter()
      .then((browserPreview) => browserPreview.fetchBrowserPreviewBootstrap(bootstrapSessionId))
      .then(({ sessionId, message }) => {
        if (cancelled) {
          return;
        }
        if (hostMessageSequenceRef.current !== requestSequence) {
          return;
        }
        setPreviewSessionId(sessionId);
        dispatchHostMessage(message);
        applyLocationOverrides();
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        reportOperationMessage({
          tone: "error",
          message: recoverableFailureMessage("bootstrap", composerLanguage),
        });
      });

    return () => {
      cancelled = true;
    };
  }, [isBrowserPreview]);

  useEffect(() => {
    if (isBrowserPreview) {
      return;
    }

    postMessage({
      type: "ui/liveFollow",
      payload: { enabled: layout.followCurrentFile },
    });
  }, [isBrowserPreview, layout.followCurrentFile]);

  useEffect(() => {
    setOpenMenu(undefined);
  }, [layout.activeView]);

  // Restart the view entrance animation on every view change without
  // remounting the container (remounting would drop child state).
  useEffect(() => {
    const node = viewContentRef.current;
    if (!node) {
      return;
    }
    node.classList.remove("view-content--enter");
    void node.offsetWidth;
    node.classList.add("view-content--enter");
  }, [activeView]);

  useEffect(() => {
    if (openMenu !== "model") {
      setComposerModelQuery("");
      return;
    }

    window.requestAnimationFrame(() => {
      composerModelSearchRef.current?.focus();
    });
  }, [openMenu]);

  useEffect(() => {
    setSelectedCommandIndex(0);
  }, [normalizedDraft]);

  const restoringSavedPosition = useSurfaceScroll(viewContentRef, activeView, composerSessionKey);

  useCoachAutoScroll({
    viewContentRef, activeView, scope: composerSessionKey,
    conversationLength: data.conversation.length,
    lastMessageRole: data.conversation[data.conversation.length - 1]?.role,
    optimisticLength: optimisticTurns.length, isStreaming: streaming.isStreaming,
    coachAutoScrollPinnedRef, restoringSavedPosition,
  });

  return {
    composerContextUsage,
    composerContextUsageDetail,
    composerContextRingNode,
  };
}
