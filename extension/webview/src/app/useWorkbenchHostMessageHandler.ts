import {
  useCallback,
  useEffect,
  useRef,
  useState
} from "react";

import {
  composeTrainingCoachBridgeDraft
} from "../../../../shared/src/trainingCoachBridge";
import { composerDockDraftScope,docksComposer } from "../lib/composerDock";
import { resolveTextDirection } from "../lib/i18n/direction";
import {
  detectPlanRevisionConflict,
  parseLivePlanTaskGateMarker,
  resolveOperationMessageSurface,
  type OperationMessageSurface
} from "../lib/operationMessageGovernance";
import type {
  HostMessage,
  MessageAttachment
} from "../lib/types";
import {
  persistBrowserPreviewProviderConfig,
  postMessage
} from "../lib/vscode";
import { useComposerHistoryNavigation } from "./useComposerHistoryNavigation";
import {
  type PlanComposerDraftReplacement
} from "./useLearningPlanController";
import { useTrainingCommands } from "./useTrainingCommands";
import { useWorkbenchState } from "./useWorkbenchState";

// ContextMenu type imported from useMenuState
import {
  type WorkbenchCtxAfterK0
} from "./App";
import {
  OPEN_RESOURCE_SYNC_TIMEOUT_MS,
  focusComposerInput,
  isEditingAnotherField,
  parseLearningFeedbackStatus,
  parseResourceOperationStatus,
  readBrowserPreviewLocationOverrides,
  sanitizeHostFailureMessage,
  waitForResourceInSnapshot
} from "./appHelpers";

export function useWorkbenchHostMessageHandler(ctx: WorkbenchCtxAfterK0) {
  const {
    data,
    layout,
    hasReceivedHostState,
    setActiveView,
    closeLearningDrawer,
    setComposerDraft,
    setComposerLanguage,
    applyRawHostMessage,
    handleRemoteVerificationHostMessage,
    handleRemoteVerificationCommandFailure,
    requestTrainingPersistence,
    resolveTrainingPersistenceAck,
    settingsActionState,
    setCompanionInstallState,
    pendingPostAdmissionSendRef,
    handleProviderSpeedTestMessage,
    requestProviderApiKeyFocus,
    clearOptimisticTurns,
    clearPendingMessageActionUnless,
    pendingPlanComposerDraftReplacement,
    setPendingPlanComposerDraftReplacement,
    resolveResourceOperationStatus,
    resolveResourceTrainingHandoffMessage,
    resolveLibraryFolderOperation,
    resolveLibraryMigrationOperation,
    syncIdentity,
    setDismissedComposerDeck,
    isBrowserPreview,
    activeView,
    setComposerModelActionDensity,
    composerSessionKey,
    hostMessageSequenceRef,
    setUserFeedbackState,
    userFeedbackPendingKindRef,
    userFeedbackTimeoutRef,
    userFeedbackRequestIdRef,
    browserPreviewLocationOverridesAppliedRef,
    requestCoachComposerFocus,
    localizedResourceOperationFallback,
    planText,
  } = ctx;
  useEffect(() => () => {
    window.clearTimeout(userFeedbackTimeoutRef.current);
  }, []);
  const applySessionListRef = useRef<((payload: unknown) => void) | undefined>(undefined);
  const applyHostMessage = useCallback(
    (message: HostMessage, isProviderActionOverride = false) => {
      hostMessageSequenceRef.current += 1;
      // Reply uploads settle through their request-id acknowledgement. An
      // unrelated status (for example Trash refresh) must not enable duplicates.
      if (message.type === "operation/status" || message.type === "stream/start") {
        clearPendingMessageActionUnless([":save-resource", ":save-research-brief"]);
      }
      if (message.type === "remoteCompanion/state") {
        setCompanionInstallState(
          message.payload.state as import("../../../../shared/src/companionInstallState").CompanionInstallState,
        );
        return;
      }
      // §三: the training-card controller owns remote-verification state and
      // its request identity; it consumes every remoteVerification/* message.
      if (handleRemoteVerificationHostMessage(message)) {
        return;
      }
      if (message.type === "training/resourceHandoff") {
        resolveResourceTrainingHandoffMessage(message.payload);
        return;
      }
      // Folder space answers (list/create/rename/delete) settle their request.
      if (message.type === "library/folders") {
        resolveLibraryFolderOperation(message.payload);
        return;
      }
      // The Markdown-only migration answers settle their request the same way.
      if (message.type === "library/migration") {
        resolveLibraryMigrationOperation(message.payload);
        return;
      }
      if (message.type === "training/persistenceAck") {
        resolveTrainingPersistenceAck(message);
        return;
      }
      if (handleProviderSpeedTestMessage(message)) {
        return;
      }
      if (message.type === "session/list") {
        applySessionListRef.current?.(message.payload);
        return;
      }
      const learningFeedbackStatus = parseLearningFeedbackStatus(message);
      if (
        learningFeedbackStatus &&
        userFeedbackRequestIdRef.current === learningFeedbackStatus.requestId
      ) {
        userFeedbackRequestIdRef.current = undefined;
        window.clearTimeout(userFeedbackTimeoutRef.current);
        setUserFeedbackState((current) => current.busy ? { busy: false, submittedKind: userFeedbackPendingKindRef.current } : current);
        return;
      }
      const resourceOperationStatus = parseResourceOperationStatus(
        message,
        localizedResourceOperationFallback,
      );
      const resolvedMessage = resolveResourceOperationStatus(message);
      if (
        resolvedMessage.type === "ui/restoreView" &&
        resolvedMessage.payload.focusProviderApiKey
      ) {
        requestProviderApiKeyFocus();
      }
      let hostOperationSurface: OperationMessageSurface | undefined;
      if (message.type === "operation/status") {
        if (message.payload.tone === "error") {
          pendingPostAdmissionSendRef.current = null;
        }
        // §三: the training-card controller settles a failed remote-verification
        // request; a failure that belongs to another card aborts the message.
        if (handleRemoteVerificationCommandFailure(message) === "abort") {
          return;
        }
        // §四十四: a store-written banner inherits its host domain. Resource
        // operation results (upload/index/delete/restore acks) render only in
        // Library — the Library view already reports its own mutation status —
        // and plan-state failures (revision conflict, live-plan gate) render
        // only in Learning. Stream-scoped non-errors clear the banner instead
        // of setting one, so they never claim a scope.
        //
        // The scope is derived from the RAW text (sanitization rewrites the
        // markers) and travels into the store write below, atomically with the
        // message — no separate surface state to go stale.
        const hostSurfaceScope = resolveOperationMessageSurface({ message: message.payload.message,
          planStateFailure: Boolean(detectPlanRevisionConflict(message.payload.message) || parseLivePlanTaskGateMarker(message.payload.message)),
          resourceOperation: Boolean(resourceOperationStatus && resourceOperationStatus.kind !== "search"),
        });
        if (!(message.payload.surface === "stream" && message.payload.tone !== "error")) {
          hostOperationSurface = hostSurfaceScope;
        }
      }
      // A library deep link may beat the refreshed snapshot into this webview:
      // ask for a fresh bootstrap, give the resource a bounded moment to
      // arrive, and only then let the landing report it as missing.
      if (resolvedMessage.type === "ui/openResource") {
        const deepLinkResourceId = String(resolvedMessage.resourceId ?? "").trim();
        const alreadySynced = deepLinkResourceId
          ? useWorkbenchState
              .getState()
              .data.resources.some((resource) => resource.id === deepLinkResourceId)
          : false;
        if (deepLinkResourceId && !alreadySynced) {
          postMessage({ type: "request/bootstrap" });
          void waitForResourceInSnapshot(
            deepLinkResourceId,
            OPEN_RESOURCE_SYNC_TIMEOUT_MS,
          ).then(() => {
            applyRawHostMessage(resolvedMessage);
          });
          return;
        }
      }
      if (resolvedMessage.type === "stream/error") {
        clearOptimisticTurns();
      }
      if (
        resolvedMessage.type === "operation/status" &&
        resolvedMessage.payload.tone === "error" &&
        useWorkbenchState.getState().streaming.isStreaming &&
        !useWorkbenchState.getState().streaming.streamMessageId
      ) {
        clearOptimisticTurns();
      }
      if (resourceOperationStatus?.kind !== "search" && resourceOperationStatus?.kind !== "check-versions") {
        applyRawHostMessage(
          sanitizeHostFailureMessage(
            resolvedMessage,
            layout.composerLanguage,
            Boolean(isProviderActionOverride || settingsActionState?.targets.includes("provider")),
            resourceOperationStatus?.kind,
          ),
          { operationSurface: hostOperationSurface },
        );
      }
      if (resolvedMessage.type === "ui/coachPrompt" && typeof window !== "undefined") {
        requestCoachComposerFocus();
      }
      // Browser-captured drafts land in the same composer (prefilled, not sent).
      // Focus follows only when the user is not typing somewhere else.
      if (
        resolvedMessage.type === "ui/coachDraftPrefill" &&
        typeof window !== "undefined" &&
        !isEditingAnotherField()
      ) {
        requestCoachComposerFocus();
      }
    },
    [
      applyRawHostMessage,
      clearOptimisticTurns,
      handleProviderSpeedTestMessage,
      handleRemoteVerificationCommandFailure,
      handleRemoteVerificationHostMessage,
      layout.composerLanguage,
      localizedResourceOperationFallback,
      requestCoachComposerFocus,
      requestProviderApiKeyFocus,
      resolveLibraryFolderOperation,
      resolveLibraryMigrationOperation,
      resolveResourceOperationStatus,
      resolveResourceTrainingHandoffMessage,
      resolveTrainingPersistenceAck,
      settingsActionState,
    ],
  );
  const showComposerShell = docksComposer(activeView);
  const composerShellRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const shell = composerShellRef.current;
    if (!showComposerShell || !shell) return;
    const updateDensity = () => {
      const width = shell.getBoundingClientRect().width;
      setComposerModelActionDensity(width < 430 ? "compact" : "default");
    };
    updateDensity();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateDensity);
      return () => window.removeEventListener("resize", updateDensity);
    }
    const observer = new ResizeObserver(updateDensity);
    observer.observe(shell);
    return () => observer.disconnect();
  }, [activeView, showComposerShell]);
  const openTrainingCoachBridge = useCallback(
    (bridge: Parameters<typeof composeTrainingCoachBridgeDraft>[0]) => {
      setActiveView("coach");
      setComposerDraft(composeTrainingCoachBridgeDraft(bridge));
      requestCoachComposerFocus();
    },
    [requestCoachComposerFocus, setActiveView, setComposerDraft],
  );
  const {
    onRefreshTask: requestTrainingCardGeneration,
    onReviewQueueAction: handleReviewQueueAction,
    onCardStatusTransition: handleTrainingCardStatusTransition,
  } = useTrainingCommands(setActiveView, {
    onOpenCoachWithBridge: openTrainingCoachBridge,
    requestTrainingPersistence,
  });
  const draft = layout.composerDraft;
  const surfaceInstanceKey = `${composerSessionKey}\u0000${data.runtimeDataGeneration ?? ""}`;
  const composerDraftScope = composerDockDraftScope(activeView, composerSessionKey);
  const browserComposerSource = layout.composerBrowserSources?.[composerDraftScope];
  const attachmentScope = syncIdentity
    ? JSON.stringify([syncIdentity.generation, syncIdentity.workspaceId, syncIdentity.sessionId, composerDraftScope])
    : composerDraftScope;
  const [composerAttachmentBank, setComposerAttachmentBank] = useState<Record<string, MessageAttachment[]>>({});
  const composerAttachments = composerAttachmentBank[attachmentScope] ?? [];
  const setComposerAttachments = (attachments: MessageAttachment[]) => {
    setComposerAttachmentBank((bank) => ({ ...bank, [attachmentScope]: attachments }));
  };
  const [resourceSearchBySession, setResourceSearchBySession] = useState<Record<string, string>>({});
  const resourcesViewSearchQuery = resourceSearchBySession[composerSessionKey] ?? "";
  const setResourcesViewSearchQuery = (query: string) => {
    setResourceSearchBySession((scoped) => ({ ...scoped, [composerSessionKey]: query }));
  };
  useEffect(() => {
    if (hasReceivedHostState && data.sessionLabel) {
      useWorkbenchState.getState().selectComposerDraftScope(composerDraftScope);
    }
  }, [composerDraftScope, data.sessionLabel, hasReceivedHostState]);
  const normalizedDraft = draft.trim();
  useEffect(() => {
    if (activeView === "plan" && normalizedDraft) {
      return;
    }

    setPendingPlanComposerDraftReplacement(undefined);
  }, [activeView, normalizedDraft]);

  const applyPlanComposerGuidance = (targetTitle: string) => {
    closeLearningDrawer();
    setActiveView("coach");
    setPendingPlanComposerDraftReplacement(undefined);
    setComposerDraft(planText.stageGuidancePrompt(targetTitle), composerDockDraftScope("coach", composerSessionKey));
    requestCoachComposerFocus();
  };
  const requestPlanComposerGuidance = (
    targetTitle: string,
    source: PlanComposerDraftReplacement["source"],
  ) => {
    const normalizedTargetTitle = targetTitle.trim();
    if (!normalizedTargetTitle) {
      return;
    }

    if (normalizedDraft) {
      setPendingPlanComposerDraftReplacement({ source, targetTitle: normalizedTargetTitle });
      return;
    }

    applyPlanComposerGuidance(normalizedTargetTitle);
  };
  const confirmPlanComposerDraftReplacement = () => {
    if (!pendingPlanComposerDraftReplacement) {
      return;
    }

    applyPlanComposerGuidance(pendingPlanComposerDraftReplacement.targetTitle);
  };
  const cancelPlanComposerDraftReplacement = () => {
    setPendingPlanComposerDraftReplacement(undefined);
    window.requestAnimationFrame(() => {
      focusComposerInput();
    });
  };
  // §四十八: sent-message history navigation lives in useComposerHistoryNavigation.
  const { resetComposerHistoryNavigation, navigateComposerHistory } =
    useComposerHistoryNavigation({
      conversation: data.conversation,
      draft,
      setComposerDraft,
    });
  const handleComposerDraftChange = useCallback(
    (nextDraft: string) => {
      resetComposerHistoryNavigation();
      setDismissedComposerDeck(undefined);
      setComposerDraft(nextDraft);
    },
    [resetComposerHistoryNavigation, setComposerDraft],
  );
  const previewDirectionOverride = isBrowserPreview
    ? readBrowserPreviewLocationOverrides().direction
    : undefined;
  const uiDirection = previewDirectionOverride ?? resolveTextDirection(layout.composerLanguage);
  const applyBrowserPreviewLocationOverrides = useCallback(() => {
    if (!isBrowserPreview) {
      return;
    }

    // URL parameters establish the initial preview state only. Do not replay
    // them after an async bootstrap or a user setting change has landed.
    if (browserPreviewLocationOverridesAppliedRef.current) {
      return;
    }
    browserPreviewLocationOverridesAppliedRef.current = true;

    const overrides = readBrowserPreviewLocationOverrides();
    if (overrides.composerLanguage) {
      setComposerLanguage(overrides.composerLanguage);
    }
    if (overrides.activeView) {
      setActiveView(overrides.activeView);
    }
  }, [isBrowserPreview, setActiveView, setComposerLanguage]);
  const applyPreviewHostMessages = useCallback(
    (messages: HostMessage[], isProviderAction = false) => {
      for (const message of messages) {
        applyHostMessage(message, isProviderAction);
        if (
          isProviderAction &&
          message.type === "state/patch" &&
          message.payload &&
          typeof message.payload === "object" &&
          "providerConfig" in message.payload
        ) {
          const providerConfig = message.payload.providerConfig;
          useWorkbenchState.getState().patchData({ providerConfig });
          persistBrowserPreviewProviderConfig(providerConfig);
        }
      }
    },
    [applyHostMessage],
  );
  return {
    requestTrainingCardGeneration,
    handleReviewQueueAction,
    handleTrainingCardStatusTransition,
    applySessionListRef,
    applyHostMessage,
    showComposerShell,
    composerShellRef,
    draft,
    surfaceInstanceKey,
    composerDraftScope,
    browserComposerSource,
    attachmentScope,
    composerAttachments,
    setComposerAttachments,
    resourcesViewSearchQuery,
    setResourcesViewSearchQuery,
    normalizedDraft,
    requestPlanComposerGuidance,
    confirmPlanComposerDraftReplacement,
    cancelPlanComposerDraftReplacement,
    navigateComposerHistory,
    handleComposerDraftChange,
    uiDirection,
    applyBrowserPreviewLocationOverrides,
    applyPreviewHostMessages,
  };
}
