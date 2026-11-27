import { LearningDrawer } from "../components/learning/LearningDrawer";
import { useLearningDrawerSections } from "../components/learning/useLearningDrawerSections";
import { LearningStrip } from "../components/learning/LearningStrip";
import { InlineProgressCard } from "../components/learning/InlineProgressCard";
import { InlinePracticeAnswer } from "../components/learning/InlinePracticeAnswer";
import { MessageRichContent } from "../components/coach/MessageRichContent";
import { unifiedComposerCopy } from "../lib/i18n/unifiedComposerCopy";
import { resourceVersionCopy } from "../lib/i18n/resourceVersionCopy";
import { SystemState } from "../templates/SystemState";
import {
  executeLearningPrimaryAction,
  resolveLearningPrimaryAction,
  type LearningFacts,
} from "../lib/learningActionResolver";
import { readTrainingCardList, readTrainingCardText, resolveBoundTrainingCardFacts } from "../lib/boundTrainingCardFacts";
import { CommandPalette } from "../templates/CommandPalette";
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { reviewConceptLabel } from "../lib/reviewLabel";
import { SettingsRoute } from "./SettingsRoute";
import { goalTitleFromConversation } from "../lib/coachGoalTitle";
import { researchBriefResourceIds, upsertResearchBrief } from "../../../../shared/src/researchBrief";

import { resourceRecordIsAcknowledgedUpload } from "../../../../shared/src/resourceWorkbenchGovernance";
import { trainerCommands } from "../../../../shared/src/commands";
import type { ResourceVersionCheckResult, TrainingPlanBinding } from "../../../../shared/src/models";
import { analyzeSendIntent, shouldAttachCurrentFile } from "../../../../shared/src/sendIntelligence";
import {
  filterTrainerSkills,
  resolveTrainerSkillText,
  trainerSkillTriggerToken,
} from "../../../../shared/src/skillCatalog";
import {
  buildTrainingCoachBridge,
  composeTrainingCoachBridgeDraft,
} from "../../../../shared/src/trainingCoachBridge";
import {
  deriveTrainingExecutionState,
  normalizeTrainingSubmode as normalizeSharedTrainingSubmode,
} from "../../../../shared/src/trainingExecutionGovernance";
import { localizeTrainingNextHopLabel } from "../../../../shared/src/trainingHandoffGovernance";
import {
  filterSidebarControlCommands,
  findSidebarControlCommand,
} from "../../../../shared/src/sidebarCommands";
import {
  deriveCoachOrientation,
} from "../../../../shared/src/coachOrientationGovernance";
import { isOperationReliabilityInFlight } from "../../../../shared/src/operationReliabilityGovernance";
import { resolveEffectiveTokenBudgetProfile } from "../../../../shared/src/smartTokenBudget";
import {
  buildRecoveredPlanResumeTurn,
  derivePlanOrientation,
  formalPlanIsLiveRuntimeIdentity,
  liveEvidenceBinding,
  liveFormalPlanCadence,
  liveFormalPlanFrozen,
  liveFormalPlanStages,
  liveFormalPlanSummary,
  liveFormalPlanTitle,
  formalTaskIsLiveRuntimeIdentity,
  leftoverTaskGuideFocusIsNotLive,
  leftoverCoachTurnChromeIsNotLive,
  leftoverCoachConversationIsNotLive,
  leftoverSuggestedActionsIsNotLive,
  leftoverMintingSuggestedActionsAreNotLive,
  leftoverFirstLookHeadlineIsNotLive,
  leftoverEvaluationHeadlineIsNotLive,
  leftoverStreamingCheckpointIsNotLive,
  leftoverTransferSkillIsNotLive,
  leftoverTrainingFocusChromeIsNotLive,
  leftoverTrainingHandoffChromeIsNotLive,
  independentTrainingSelectionIsLive,
  leftoverResourceSelectedDetailIsNotLive,
  leftoverResourceSandboxStateIsNotLive,
  leftoverResourceLibraryListIsNotLive,
  leftoverSettingsProfileRhythmIsNotLive,
  leftoverSettingsLearnerProjectOnboardingIsNotLive,
  streakAdaptsWithoutInventingLiveObjects,
  pressureAdaptsWithoutInventingLiveObjects,
  preferRecoveredCoachTaskChrome,
  preferRecoveredCoachTurnChrome,
  preferRecoveredTransferSkill,
  preferRecoveredTrainingFocusChrome,
  preferRecoveredTrainingHandoffChrome,
  formalCardIsLiveRuntimeIdentity,
  liveTrainingFormalSummary,
  liveTrainingSourceFallback,
  liveTrainingFocusFallback,
  liveTrainingTargetSkill,
  liveTrainingTitleFallback,
  liveTrainingNextChallengeTitle,
  liveTrainingWhyNow,
  liveTrainingCoachSummary,
  lockRecoveredPlanVerifyItems,
  preferRecoveredPlanRuntimeFacts,
  scopeEvidenceQueueToRuntimeStep,
  recoveredPlanResumeMessage,
  resolveLivePlanStageChrome,
  type PlanOrientationAction,
  type RecoveredPlanResumeTurn,
} from "../../../../shared/src/planOrientationGovernance";
import {
  deriveResourcesOrientation,
  resolveResourcesBindingIds,
  type ResourcesOrientationAction,
} from "../../../../shared/src/resourcesOrientationGovernance";
import { resolveResourceOpenTarget } from "../../../../shared/src/resourceOpen";
import {
  sanitizeErrorSurfaceText,
  waitingComposerEnqueueFailureText,
} from "../../../../shared/src/errorSurfaceSanitizer";
import {
  blockedComposerPresenceMessage,
  providerRecoveryLocale,
  providerRecoverySummary,
} from "./providerRecoveryCopy";
import { normalizeTransferSkillStateRecord } from "../../../../shared/src/transferSkillGovernance";
import { CoachHistoryDrawer } from "../components/coach/CoachHistoryDrawer";
import { UtilityOverlay } from "../templates/UtilityOverlay";
import { templateCopy } from "../templates/templateCopy";
import { viewLabels, resourcesViewLabel, coachViewLabel, planViewLabel, trainingViewLabel, settingsViewLabel } from "../lib/viewLabels";
import { WorkbenchSurfaces } from "./WorkbenchSurfaces";
import { useSurfaceScroll } from "./useSurfaceScroll";
import { useCoachAutoScroll } from "./useCoachAutoScroll";
import { useComposerActionPreview } from "./useComposerActionPreview";
import { useComposerQueue } from "./useComposerQueue";
import { canConverseBeforeAdmission } from "../../../../shared/src/conversationAdmission";
import { useCoachHistory } from "./useCoachHistory";
import { useMenuState } from "./useMenuState";
import { useComposerHistoryNavigation } from "./useComposerHistoryNavigation";
import { useCoachConversationController } from "./useCoachConversationController";
import { useComposerProviderController } from "./useComposerProviderController";
import {
  useLearningPlanController,
  type PlanComposerDraftReplacement,
  type PlanComposerMode,
} from "./useLearningPlanController";
import { useLibraryResourceController } from "./useLibraryResourceController";
import { useOperationStatusController } from "./useOperationStatusController";
import { useProviderConnectionController } from "./useProviderConnectionController";
import {
  useCoachSettingsController,
  useCoachSettingsState,
  useProviderReadinessState,
} from "./useCoachSettingsController";
import {
  useWorkspaceAdmissionFlow,
  useWorkspaceAdmissionState,
} from "./useWorkspaceAdmissionController";
import { useTrainingCardController } from "./useTrainingCardController";
import { useShallow } from "zustand/react/shallow";
import { coachReplyMarkdown } from "../lib/shareUtils";
import { formatTokenCount } from "../lib/formatUtils";
import {
  planRuntimeStatusFromRecovery,
  selectStreamingCheckpointForScope,
  streamingCheckpointToOrientation,
} from "../../../../shared/src/workspaceRecoveryGovernance";
import {
  type CoachArtifactBlockData,
  type CoachMessageAction,
  CoachConversationView,
} from "../components/coach";
import { AppShell } from "../templates/AppShell";
import { resolveUnifiedComposerIntent, unifiedComposerCommands } from "../lib/unifiedComposerIntent";
import { deriveLearningSummary, sanitizeBogusLearningStep } from "../lib/learningSummary";
import { normalizeTrainingStateTextFields } from "../lib/hostText";
import { appendDockAnchor, composerDockDraftScope, docksComposer, resolveDockContextAnchor } from "../lib/composerDock";
import { useComposerDockAnchor } from "./useComposerDockAnchor";
import { PLAN_COPY } from "../lib/i18n/segments/planInlineText";
import {
  detectPlanRevisionConflict,
  parseLivePlanTaskGateMarker,
  operationStatusMessageText,
  recoverableFailureMessage,
  resolveOperationMessageSurface,
  type OperationMessageSurface,
} from "../lib/operationMessageGovernance";
import { resolveTurnNextStepRequiresConfirmation } from "../lib/nextStepConfirmation";
import {
  CoachComposer,
  ComposerContextMenu,
  type ComposerMentionItem,
  ComposerModelMenu,
  ComposerResourcesMenu,
} from "../components/composer";
import { type UserFeedbackKind } from "../components/common/UserFeedbackDisclosure";
import { WorkbenchSurfaceButton } from "../components/common/WorkbenchSurfaceButton";
import {
  applyTrainingCardGrade,
  applyTrainingCardSkip,
  interpretTrainingComposerCardCommand,
} from "../lib/i18n/segments/trainingCardActions";
import type {
  TrainingReviewItem,
  TrainingSummaryCard,
} from "../components/training/TrainingWorkbenchView";
import { TrainingCardLibrary, type TrainingCardLibraryAction } from "../components/training/TrainingCardLibrary";
import { COACH_MESSAGE_ACTION_LABELS } from "../lib/i18n/segments/coachMessageBubbleCopy";
import {
  ArrowRightIcon,
  CheckMarkIcon,
  ChevronRightIcon,
  ResourcesIcon,
  SkillCubeIcon,
  TargetIcon,
  WarningIcon,
} from "../components/icons";
import { applyWorkbenchTheme } from "../lib/theme";
import { I18nProvider } from "../lib/i18n/context";
import { resolveCopy as resolveWorkbenchCopy } from "../lib/i18n/copy";
import { resolvePlanComposerCopy } from "../lib/i18n/planComposerCopy";
import { composerAddCopy, GOAL_MODE_COPY } from "../lib/i18n/segments/coachInlineText";
import { resolvePlanViewCopy } from "../lib/i18n/planViewCopy";
import { resolveTextDirection } from "../lib/i18n/direction";
import type {
  ActiveWorkbenchView,
  BootstrapData,
  ComposerLanguage,
  ConversationMessage,
  DebugVisibleTrainingFacts,
  HostMessage,
  MessageAttachment,
  ResourceComposerIntent,
  SuggestedAction,
} from "../lib/types";
import {
  normalizeSidebarView,
} from "../lib/types";
import {
  getInjectedBootstrapState,
  getWorkbenchSurface,
  isBrowserSidePanelSurface,
  persistBrowserPreviewProviderConfig,
  postDebugVisibleFacts,
  postMessage,
  requestCollapseToSidebar,
  subscribeToHostMessages,
  resourceVersionResultsSchema,
  inVsCodeWebview,
} from "../lib/vscode";
import {
  buildGenericImageReviewPrompt,
  buildScratchPaperVerificationPrompt,
  buildTrainingFeedbackPrompt,
  type TrainingFeedbackPromptInput,
} from "../lib/universalLearningPrompts";
import {
  appUiAltCopy,
  appUiCopy,
} from "../lib/i18n/appUiCopy";
import { isBrowserPreviewFixtureMode } from "../lib/browserPreviewMode";
import { useTrainingCommands, useTrainingAttemptLifecycle } from "./useTrainingCommands";
import { composerSessionKeyFor, useWorkbenchState } from "./useWorkbenchState";
import { formatReviewDueLabel, learnerSignalLabel } from "../components/settings/useCoachSettingsViewState";
import { ProviderConnectionContext } from "./providerConnectionContext";
import type { PlanReviewItem } from "../components/plan/CoachPlanView";

// ContextMenu type imported from useMenuState
import {
  CAPTURE_CONFIRMATION_TIMEOUT_MS,
  COACH_REPLY_BODY_MAX_CHARS,
  COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT,
  CoachPlanView,
  ComposerDeckKind,
  DirectoryInput,
  DockedView,
  LocalCommandSuggestion,
  LocalSkillSuggestion,
  OPEN_RESOURCE_SYNC_TIMEOUT_MS,
  RESOURCE_COMPOSER_MAX_IDS,
  RESOURCE_UPLOAD_LIMIT,
  ResourcesWorkbenchView,
  TrainingWorkbenchView,
  UtilityComposerModeOption,
  ViewFallback,
  WorkbenchDataSnapshot,
  activeStageObjectiveText,
  resetBootstrapRequestSent,
  coachFirstComposerPlaceholder,
  coachLaneLabel,
  coachingScenarioLabel,
  compactCoachLine,
  composerHintText,
  defaultPromptText,
  describeSidecarFailure,
  focusComposerInput,
  inBrowserPreviewEnvironment,
  isCoachCheckpointRecoveryState,
  isEditingAnotherField,
  isLanguageAlignedUiText,
  isTerminallyTruncatedText,
  joinInlineMeta,
  livePlanTaskMintPendingMessage,
  livePlanUpdatePendingMessage,
  requireBrowserPreviewAdapter,
  localizeConversationMessage,
  localizeUiViewReferences,
  normalizeInlineComparisonText,
  parseLearningFeedbackStatus,
  parseResourceOperationStatus,
  composerShortcutHint,
  pickFirstText,
  pickLanguageAlignedTrainingList,
  planComposerDraftReplacementCopy,
  readBrowserPreviewLocationOverrides,
  requestBootstrapOnce,
  resolveCoachBlockingSurface,
  resolveTheme,
  resolveTrainingLearningFamily,
  resolveTrainingLearningSubtype,
  resolveTrainingPracticeVerificationMode,
  restoredTrainingCard,
  sanitizeHostFailureMessage,
  sendContextShortSummary,
  sendStatuslineText,
  skillSectionTargetView,
  syncBootstrapLifecycleOnVisible,
  toPlanReviewItem,
  trainingCardStatusLabel,
  trainingComposerModeText,
  trainingExpectedSymbols,
  trainingFilePracticeText,
  trainingGenerateCardPendingMessage,
  trainingHandoffComposerText,
  trainingHandoffStatusLabel,
  trainingPersistenceFailureMessage,
  triggerResourceUpload,
  truncateInlineText,
  waitForResourceInSnapshot,
} from "./appHelpers";
import {
  RESOURCE_VERSION_CHECK_TIMEOUT_MS,
  type WorkbenchSendTurnInput,
  type WorkbenchCtxAfterK0,
  type WorkbenchCtxAfterK1,
  type WorkbenchCtxAfterE2,
  type WorkbenchCtxAfterE3,
  type WorkbenchCtxAfterK2,
  type WorkbenchCtxAfterE5a,
  type WorkbenchCtxAfterK3,
  type WorkbenchCtxAfterE7,
} from "./App";

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
    remoteVerification,
    handleRemoteVerificationHostMessage,
    handleRemoteVerificationCommandFailure,
    requestTrainingPersistence,
    resolveTrainingPersistenceAck,
    settingsActionState,
    companionInstallState,
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
    streaming,
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
    onRefreshDeck: handleRefreshTrainingDeck,
    onSubmitFlashAnswer: handleSubmitFlashAnswer,
    onSubmitTheoryDrillAnswer: handleSubmitTheoryDrillAnswer,
    onTheoryDrillAction: handleTheoryDrillAction,
    onOpenCoachFromPractice: handleOpenCoachFromPractice,
    onOpenCoachFromFlash: handleOpenCoachFromFlash,
    onOpenCoachBridgeFromFlash: handleOpenCoachBridgeFromFlash,
    onOpenPracticeFromFlash: handleOpenPracticeFromFlash,
    onOpenResources: handleOpenResourcesFromTraining,
    onCreateFlashcard: handleCreateFlashcard,
    onOpenReviewCoach: handleOpenReviewCoach,
    onReviewQueueAction: handleReviewQueueAction,
    onReviewArtifactAction: handleReviewArtifactAction,
    onScenarioLabAction: handleScenarioLabAction,
    onDependencySkillMapAction: handleDependencySkillMapAction,
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
