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

export function useTrainingWorkbenchDerivedState(ctx: WorkbenchCtxAfterE3) {
  const {
    data,
    layout,
    trainingRestoreContext,
    trainingReviewQueueRequested,
    syncStatus,
    syncCursor,
    setComposerDraft,
    setTrainingComposerFlashMode,
    trainingComposerVerifyIndex,
    setTrainingComposerVerifyIndex,
    setTrainingComposerPracticeReturnMode,
    setTrainingComposerRoute,
    displayedTrainingCardIdRef,
    resetRemoteVerification,
    activeView,
    t,
    composerSessionKey,
    inlinePracticeCollapsed,
    setInlinePracticeCollapsed,
    selectedResourceContextIds,
    pendingTrainingHandoffSubmissionRef,
    draft,
    browserComposerSource,
    recoveredRuntime,
    leftoverChromeIdentity,
    independentTrainingSelectionLive,
    leftoverTrainingHandoffChromeNotLive,
    resolvedCoachSummary,
    runtimeWhyNow,
    runtimeVerifyItems,
    recoveredDisplayFacts,
    formalPlanIdentity,
    liveTrainingSummary,
    liveTrainingTitle,
    liveTrainingFocus,
    planVerifyItems,
  } = ctx;
  const trainingState = normalizeTrainingStateTextFields(data.workspaceTrainingState);
  const rawTrainingRouteCard = trainingState?.activeTrainingCardRouting?.selectedCard;
  const normalizedTrainingSubmode = normalizeSharedTrainingSubmode(
    trainingState?.latestTrainingSubmode,
  );
  const shouldPrioritizeReviewArtifact = Boolean(
    trainingState?.reviewArtifact?.id &&
      trainingState.reviewArtifact.status !== "archived" &&
      (normalizedTrainingSubmode === "review-queue" || normalizedTrainingSubmode === "review"),
  );
  const restoredTrainingCardCandidate = useMemo(
    () => restoredTrainingCard(trainingState, trainingRestoreContext),
    [trainingRestoreContext, trainingState],
  );
  const selectedTrainingCardCandidate = useMemo(() => {
    const restoredCard = restoredTrainingCardCandidate;
    // An explicit restore target owns the foreground. The store retires that
    // intent when a later patch selects another card, so a restored card never
    // outlives the live selection it was restoring.
    if (trainingRestoreContext?.target && restoredCard) {
      return restoredCard;
    }
    if (shouldPrioritizeReviewArtifact && trainingState?.reviewArtifact?.id) {
      return restoredTrainingCard(trainingState, {
        target: "review_artifact",
        reviewArtifactId: trainingState.reviewArtifact.id,
      });
    }
    const candidates = trainingState?.trainingCardCandidates;
    if (!candidates?.length) {
      return restoredCard;
    }

    const selectedCardId = trainingState?.selectedCardId?.trim();
    const routeSelectedCardId = rawTrainingRouteCard?.cardId?.trim();

    // Leftover stored cards / title / current_step must not count as live selectedCardId.
    // Live only when runtime still carries a matching card id — never candidates[0] fallback.
    if (selectedCardId) {
      const selectedById = candidates.find((card) =>
        formalCardIsLiveRuntimeIdentity({
          cardId: card.cardId,
          selectedCardId,
          cardTitle: card.title,
        }),
      );
      if (selectedById) {
        return selectedById;
      }
    }

    if (routeSelectedCardId && routeSelectedCardId === selectedCardId) {
      const selectedByRouteId = candidates.find((card) =>
        formalCardIsLiveRuntimeIdentity({
          cardId: card.cardId,
          selectedCardId: routeSelectedCardId,
          cardTitle: card.title,
        }),
      );
      if (selectedByRouteId) {
        return selectedByRouteId;
      }
    }

    return restoredCard;
  }, [restoredTrainingCardCandidate, shouldPrioritizeReviewArtifact, trainingState]);
  const trainingRestoreForeground = Boolean(
    trainingRestoreContext?.target &&
      restoredTrainingCardCandidate?.cardId &&
      selectedTrainingCardCandidate?.cardId === restoredTrainingCardCandidate.cardId,
  );
  const reviewArtifactForeground = Boolean(
    trainingState?.reviewArtifact?.id &&
      selectedTrainingCardCandidate?.cardId === trainingState.reviewArtifact.id &&
      (shouldPrioritizeReviewArtifact ||
        (trainingRestoreForeground && trainingRestoreContext?.target === "review_artifact")),
  );
  // A retained review is history unless that exact review is the foreground card.
  const activeTrainingReviewArtifact = reviewArtifactForeground
    ? trainingState?.reviewArtifact
    : undefined;
  const trainingLedgerEntry =
    trainingState?.trainingEventLedger?.find((entry) => entry.selectedCardId === trainingState?.selectedCardId) ??
    trainingState?.trainingEventLedger?.find((entry) => entry.cardCandidateId === trainingState?.selectedCardId) ??
    trainingState?.trainingEventLedger?.[0];
  const trainingCardType = reviewArtifactForeground || trainingRestoreForeground
    ? (selectedTrainingCardCandidate?.type ?? "practice")
    : (trainingState?.selectedCardType ??
      rawTrainingRouteCard?.type ??
      selectedTrainingCardCandidate?.type ??
      "practice");
  const activeTrainingCardId = reviewArtifactForeground || trainingRestoreForeground
    ? selectedTrainingCardCandidate?.cardId
    : (trainingState?.selectedCardId ??
      (rawTrainingRouteCard?.cardId &&
      rawTrainingRouteCard.cardId === trainingState?.selectedCardId
        ? rawTrainingRouteCard.cardId
        : undefined));
  // Authored facts are only safe to show when the route card is the active
  // card. A foreign/unbound route card must not lend its text to the selected
  // identity (the P1 caught by trainer-bound-card-facts).
  const selectedTrainingRouteCard =
    rawTrainingRouteCard?.cardId && rawTrainingRouteCard.cardId === activeTrainingCardId
      ? rawTrainingRouteCard
      : undefined;
  displayedTrainingCardIdRef.current = activeTrainingCardId;
  // §三: a card or scope change invalidates the in-flight remote verification
  // panel; the controller owns that state and clears it here.
  useEffect(() => {
    resetRemoteVerification();
  }, [activeTrainingCardId, syncCursor.generation, syncCursor.workspaceId, syncCursor.sessionId, resetRemoteVerification]);
  const activityDraftKey = `${composerSessionKey}\u0000${activeTrainingCardId ?? "unselected"}`;
  const activityDraft = layout.activityDrafts?.[activityDraftKey] ?? "";
  const [composerHintLevels, setComposerHintLevels] = useState<Record<string, number>>({});
  const composerHintLevel = composerHintLevels[activityDraftKey] ?? 0;
  const [activityAttachmentBank, setActivityAttachmentBank] = useState<Record<string, MessageAttachment[]>>({});
  const activityAttachments = activityAttachmentBank[activityDraftKey] ?? [];
  const setActivityAttachments = (attachments: MessageAttachment[]) => {
    setActivityAttachmentBank((bank) => ({ ...bank, [activityDraftKey]: attachments }));
  };
  const setActivityDraft = useCallback((value: string) => {
    useWorkbenchState.getState().setActivityDraft(activityDraftKey, value);
  }, [activityDraftKey]);
  const trainingRestoreReplacesSelectedCard = Boolean(
    trainingRestoreForeground &&
      activeTrainingCardId &&
      activeTrainingCardId !== trainingState?.selectedCardId,
  );
  const restoredTrainingCardStatus = trainingRestoreForeground
    ? trainingRestoreContext?.target === "scenario_lab"
      ? trainingState?.scenarioLab?.status
      : trainingRestoreContext?.target === "theory_drill"
        ? trainingState?.theoryDrill?.status
        : trainingRestoreContext?.target === "review_artifact"
          ? trainingState?.reviewArtifact?.status
          : trainingState?.latestTrainingNextHop?.status
    : undefined;
  const effectiveTrainingSubmode = reviewArtifactForeground
    ? "review"
    : trainingRestoreForeground
      ? trainingRestoreContext?.target === "theory_drill"
        ? "flash"
        : trainingRestoreContext?.target === "scenario_lab"
          ? "scenario"
          : trainingRestoreContext?.target === "review_artifact"
            ? "review"
            : (trainingState?.latestTrainingSubmode ??
              (trainingCardType === "flash" ? "flash" : "practice"))
      : trainingState?.latestTrainingSubmode;
  const effectiveSelectedTrainingCardStatus = reviewArtifactForeground
    ? (trainingState?.reviewArtifact?.status === "resolved" ? "reviewed" : "active")
    : (trainingRestoreForeground
      ? (restoredTrainingCardStatus ?? "active")
      : trainingState?.selectedCardStatus);
  const visibleTrainingCardTitle = reviewArtifactForeground
    ? selectedTrainingCardCandidate?.title
    : liveTrainingNextChallengeTitle({
    ...formalPlanIdentity,
    recovered: formalPlanIdentity.recovered && !independentTrainingSelectionLive,
    planTitle: data.plan.title,
    taskTitle: data.task.title,
    cardTitle: pickFirstText(
      trainingRestoreForeground ? selectedTrainingCardCandidate?.title : undefined,
      leftoverTrainingHandoffChromeNotLive ? undefined : trainingState?.selectedCardTitle,
      leftoverTrainingHandoffChromeNotLive ? undefined : selectedTrainingRouteCard?.title,
      leftoverTrainingHandoffChromeNotLive && !trainingRestoreForeground
        ? undefined
        : selectedTrainingCardCandidate?.title,
    ),
  });
  const trainingLearningSubtype = resolveTrainingLearningSubtype(
    selectedTrainingCardCandidate?.learningSubtype,
    selectedTrainingRouteCard?.learningSubtype,
    trainingState?.activeTrainingCardRouting?.selectedCard?.learningSubtype,
  );
  const trainingLearningFamily = resolveTrainingLearningFamily(
    selectedTrainingCardCandidate,
    selectedTrainingRouteCard,
    trainingState?.activeTrainingCardRouting?.selectedCard,
  );
  const trainingPracticeVerificationMode = resolveTrainingPracticeVerificationMode({
    cardType: trainingCardType,
    learningFamily: trainingLearningFamily,
    learningSubtype: trainingLearningSubtype,
    filesToTouch: selectedTrainingCardCandidate?.filesToTouch,
    apiHints: selectedTrainingCardCandidate?.apiHints,
    expectedSymbols: selectedTrainingCardCandidate?.expectedSymbols,
  });
  const trainingScenarioPackLabel = pickFirstText(
    selectedTrainingCardCandidate?.scenarioPack,
    selectedTrainingRouteCard?.scenarioPack,
    trainingState?.latestTrainingHandoff?.scenarioPack,
    trainingState?.latestTrainingNextHop?.scenarioPack,
  );
  const trainingSuggestedWorkspaceAction = pickFirstText(
    selectedTrainingCardCandidate?.suggestedWorkspaceAction,
    selectedTrainingRouteCard?.suggestedWorkspaceAction,
  );
  const trainingScenario = pickFirstText(
    selectedTrainingCardCandidate?.scenario,
    selectedTrainingRouteCard?.scenario,
    leftoverTrainingHandoffChromeNotLive
      ? undefined
      : trainingState?.latestTrainingNextHop?.summary,
  );
  const coachTrainingInlineAction = useMemo(() => {
    if (leftoverTrainingHandoffChromeNotLive) {
      return null;
    }
    const selectedCardId = activeTrainingCardId;
    if (!selectedCardId) {
      return null;
    }
    const selectedCardTitle = visibleTrainingCardTitle;
    if (!selectedCardTitle) {
      return null;
    }
    const rationale = pickFirstText(
      trainingRestoreForeground ? selectedTrainingCardCandidate?.whyNow : undefined,
      leftoverTrainingHandoffChromeNotLive
        ? undefined
        : trainingState?.activeTrainingCardRouting?.whyThisCard,
      trainingRestoreForeground ? undefined : trainingLedgerEntry?.candidateWhyNow,
      leftoverTrainingHandoffChromeNotLive ? undefined : selectedTrainingCardCandidate?.whyNow,
      leftoverTrainingHandoffChromeNotLive ? undefined : selectedTrainingRouteCard?.deliverable,
    );
    return {
      label: t.trainingOpenCurrentCard,
      title: rationale ?? selectedCardTitle,
    };
  }, [
    activeTrainingCardId,
    leftoverTrainingHandoffChromeNotLive,
    selectedTrainingRouteCard?.cardId,
    selectedTrainingCardCandidate?.title,
    selectedTrainingCardCandidate?.whyNow,
    trainingState?.activeTrainingCardRouting?.selectedCardId,
    trainingLedgerEntry?.candidateWhyNow,
    selectedTrainingRouteCard?.deliverable,
    selectedTrainingRouteCard?.title,
    trainingState?.activeTrainingCardRouting?.whyThisCard,
    trainingState?.selectedCardId,
    trainingState?.selectedCardTitle,
    trainingRestoreForeground,
    t.trainingOpenCurrentCard,
    visibleTrainingCardTitle,
  ]);
  const trainingApiHints = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.apiHints ?? []),
    ...(selectedTrainingRouteCard?.apiHints ?? []),
  ]);
  const trainingSelfCheck = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.selfCheck ?? []),
    ...(selectedTrainingRouteCard?.selfCheck ?? []),
  ]);
  const trainingFilesToTouch =
    selectedTrainingCardCandidate?.filesToTouch ?? selectedTrainingRouteCard?.filesToTouch ?? [];
  const composerMentionItems = useMemo<ComposerMentionItem[]>(() => {
    const items: ComposerMentionItem[] = [];
    const seen = new Set<string>();
    const copy = unifiedComposerCopy[layout.composerLanguage];
    const chinese = layout.composerLanguage === "zh-CN";
    if (data.workspaceName) {
      items.push({ id: "context:project", kind: "context", label: data.workspaceName, insertText: chinese ? "当前项目" : "project" });
    }
    if (layout.includeCurrentFile && data.liveContext.activeFile) {
      items.push({ id: "context:file", kind: "context", label: copy.file, detail: data.liveContext.activeFile,
        insertText: chinese ? "当前文件" : "current-file" });
    }
    if (layout.includeSelection && data.liveContext.selectionRange) {
      items.push({ id: "context:selection", kind: "context", label: copy.selection, detail: data.liveContext.selectionRange,
        insertText: chinese ? "选中内容" : "selection" });
    }
    if (browserComposerSource) {
      items.push({ id: "context:browser", kind: "context", label: browserComposerSource.title || browserComposerSource.url,
        insertText: chinese ? "浏览器选段" : "browser" });
    }
    for (const resource of data.resources) {
      const resourceId = resource.id?.trim();
      const name = resource.title?.trim();
      if (!resourceId || !name) {
        continue;
      }
      const key = `resource:${resourceId}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      items.push({
        id: key,
        kind: "resource",
        label: name,
        detail: resource.kind,
        insertText: name,
        resourceId,
      });
    }
    const fileCandidates = [
      data.liveContext.activeFile,
      ...(data.liveContext.recentFiles ?? []),
      ...(data.liveContext.recentEditedFiles ?? []),
      ...(data.liveContext.relatedFiles ?? []),
      ...trainingFilesToTouch,
    ];
    for (const rawPath of fileCandidates) {
      const filePath = rawPath?.trim();
      if (!filePath) {
        continue;
      }
      const key = `file:${filePath}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      items.push({
        id: key,
        kind: "file",
        label: filePath.split(/[\\/]/).pop() || filePath,
        detail: filePath,
        insertText: filePath,
        path: filePath,
      });
    }
    return items;
  }, [browserComposerSource, data.liveContext, data.resources, data.workspaceName, layout.composerLanguage,
    layout.includeCurrentFile, layout.includeSelection, trainingFilesToTouch]);
  const composerResourceScopeFor = (view: ActiveWorkbenchView) => view === "training" && activeTrainingCardId
    ? activityDraftKey : composerDockDraftScope(view, composerSessionKey);
  const composerResourceIdsFor = (view: ActiveWorkbenchView): string[] => {
    const scope = composerResourceScopeFor(view);
    const implicit = view === "resources" ? selectedResourceContextIds : [];
    return [...new Set([...(layout.composerResourceRefs?.[scope] ?? []), ...implicit])]
      .filter((id) => data.resources.some((resource) => resource.id === id))
      .slice(0, RESOURCE_COMPOSER_MAX_IDS);
  };
  const activeComposerResourceIds = composerResourceIdsFor(activeView);
  const handleComposerMentionSelect = (item: ComposerMentionItem) => {
    if (item.resourceId) {
      useWorkbenchState.getState().writeComposerResourceRefs(composerResourceScopeFor(activeView), [item.resourceId]);
    }
  };
  const trainingHintLadder = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.hintLadder ?? []),
    ...(selectedTrainingRouteCard?.hintLadder ?? []),
  ]);
  const trainingCommonMistakes = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    ...(selectedTrainingCardCandidate?.commonMistakes ?? []),
    ...(selectedTrainingRouteCard?.commonMistakes ?? []),
  ]);
  const trainingStuckRecovery = pickFirstText(
    selectedTrainingCardCandidate?.stuckRecovery,
    selectedTrainingRouteCard?.stuckRecovery,
  );
  const trainingReflectionPrompt = pickFirstText(
    selectedTrainingCardCandidate?.reflectionPrompt,
    selectedTrainingRouteCard?.reflectionPrompt,
  );
  const trainingWhyThisCard = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        trainingState?.activeTrainingCardRouting?.whyThisCard,
        trainingLedgerEntry?.whyThisCard,
      );
  const trainingDeliverable = pickFirstText(
    selectedTrainingCardCandidate?.deliverable,
    selectedTrainingRouteCard?.deliverable,
  );
  const trainingValidationMethod = pickFirstText(
    selectedTrainingCardCandidate?.validationMethod,
    selectedTrainingRouteCard?.validationMethod,
  );
  const trainingVerificationMethod = pickFirstText(
    selectedTrainingCardCandidate?.verificationMethod,
    selectedTrainingRouteCard?.verificationMethod,
  );
  const trainingDeliverables = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    trainingDeliverable,
    ...(selectedTrainingCardCandidate?.learnerDeliverables ?? []),
    ...(selectedTrainingRouteCard?.learnerDeliverables ?? []),
    ...(trainingLedgerEntry?.learnerDeliverables ?? []),
  ]);
  const cardScopedVerifyItems = pickLanguageAlignedTrainingList(layout.composerLanguage, [
    trainingValidationMethod,
    trainingVerificationMethod,
    ...(selectedTrainingCardCandidate?.verificationSteps ?? []),
    ...(selectedTrainingRouteCard?.verificationSteps ?? []),
    ...(trainingLedgerEntry?.verificationSteps ?? []),
  ]);
  const contextualTrainingVerifyItems =
    trainingCardType === "flash"
      ? []
      : pickLanguageAlignedTrainingList(layout.composerLanguage, [
          ...runtimeVerifyItems,
          ...planVerifyItems,
        ]);
  const authoritativeVerifyItems =
    cardScopedVerifyItems.length > 0 ? cardScopedVerifyItems : contextualTrainingVerifyItems;
  const trainingCardWhy = leftoverTrainingHandoffChromeNotLive
    ? pickFirstText(
        runtimeWhyNow,
        recoveredRuntime ? recoveredDisplayFacts.whyNow : undefined,
      )
    : pickFirstText(
        trainingWhyThisCard,
        selectedTrainingCardCandidate?.whyNow,
        trainingState?.latestTrainingNextHop?.whyNow,
        runtimeWhyNow,
        recoveredRuntime ? recoveredDisplayFacts.whyNow : undefined,
      );
  const liveTrainingWhy = liveTrainingWhyNow({
    ...formalPlanIdentity,
    taskTitle: data.task.title,
    cardWhy: trainingCardWhy,
    liveWhy: liveTrainingSummary || resolvedCoachSummary,
  });
  const liveTrainingCoachChrome = liveTrainingCoachSummary({
    ...formalPlanIdentity,
    taskTitle: data.task.title,
    coachSummary: resolvedCoachSummary,
  });
  const liveTrainingHandoffChrome = preferRecoveredTrainingHandoffChrome({
    ...leftoverChromeIdentity,
    recovered: !independentTrainingSelectionLive && leftoverChromeIdentity.recovered,
    successSignal: pickFirstText(
      trainingState?.latestTrainingHandoff?.successSignal,
      selectedTrainingCardCandidate?.successSignal,
      selectedTrainingRouteCard?.successSignal,
      trainingLedgerEntry?.successSignal,
    ),
    returnWith: pickFirstText(
      selectedTrainingCardCandidate?.returnWith,
      selectedTrainingRouteCard?.returnWith,
      trainingState?.latestTrainingHandoff?.returnWith,
    ),
    cardTitle: pickFirstText(
      trainingState?.latestTrainingHandoff?.cardTitle,
      trainingState?.latestTrainingNextHop?.cardTitle,
      trainingState?.latestTrainingNextHop?.title,
    ),
    selectedCardTitle: trainingState?.selectedCardTitle,
    followup: trainingState?.latestLearningFollowup,
    blocker: pickFirstText(
      trainingState?.latestLearningBlocker,
      trainingState?.latestTrainingHandoff?.blockedBy,
    ),
    handoffSummary: trainingState?.latestTrainingHandoff?.handoffSummary,
    nextAfterCompletion: pickFirstText(
      selectedTrainingCardCandidate?.nextAfterCompletion,
      selectedTrainingRouteCard?.nextAfterCompletion,
      trainingState?.activeTrainingCardRouting?.nextAfterCompletion,
      trainingState?.latestTrainingHandoff?.nextAfterCompletion,
    ),
    fallbackAction: pickFirstText(
      trainingState?.activeTrainingCardRouting?.fallbackAction,
      trainingState?.latestTrainingHandoff?.fallbackAction,
    ),
    nextHopTitle: trainingState?.latestTrainingNextHop?.title,
    nextHopCardTitle: trainingState?.latestTrainingNextHop?.cardTitle,
    nextHopHandoffSummary: trainingState?.latestTrainingNextHop?.handoffSummary,
    nextHopNextAfterCompletion: trainingState?.latestTrainingNextHop?.nextAfterCompletion,
    nextHopFallbackAction: trainingState?.latestTrainingNextHop?.fallbackAction,
    routingNextAfterCompletion: trainingState?.activeTrainingCardRouting?.nextAfterCompletion,
    routingFallbackAction: trainingState?.activeTrainingCardRouting?.fallbackAction,
    whyThisCard: trainingState?.activeTrainingCardRouting?.whyThisCard,
    ledgerWhyThisCard: trainingLedgerEntry?.whyThisCard,
    returnSummary: trainingState?.latestTrainingHandoff?.returnSummary,
    nextHopReturnSummary: trainingState?.latestTrainingNextHop?.returnSummary,
    nextHopSummary: trainingState?.latestTrainingNextHop?.summary,
    nextHopWhyNow: trainingState?.latestTrainingNextHop?.whyNow,
  });
  const trainingReturnWithText = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        liveTrainingHandoffChrome.returnWith,
        selectedTrainingCardCandidate?.returnWith,
        selectedTrainingRouteCard?.returnWith,
        trainingState?.latestTrainingHandoff?.returnWith,
      );
  const trainingNextAfterCompletionText = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        liveTrainingHandoffChrome.nextAfterCompletion,
        liveTrainingHandoffChrome.nextHopNextAfterCompletion,
        liveTrainingHandoffChrome.routingNextAfterCompletion,
        selectedTrainingCardCandidate?.nextAfterCompletion,
        selectedTrainingRouteCard?.nextAfterCompletion,
        trainingState?.activeTrainingCardRouting?.nextAfterCompletion,
        trainingState?.latestTrainingHandoff?.nextAfterCompletion,
        trainingState?.latestTrainingNextHop?.nextAfterCompletion,
      );
  const trainingFallbackActionText = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        liveTrainingHandoffChrome.fallbackAction,
        liveTrainingHandoffChrome.nextHopFallbackAction,
        liveTrainingHandoffChrome.routingFallbackAction,
        trainingState?.activeTrainingCardRouting?.fallbackAction,
        trainingState?.latestTrainingHandoff?.fallbackAction,
        trainingState?.latestTrainingNextHop?.fallbackAction,
        selectedTrainingCardCandidate?.stuckRecovery,
        selectedTrainingRouteCard?.stuckRecovery,
      );
  const trainingSuccessSignal = leftoverTrainingHandoffChromeNotLive
    ? undefined
    : pickFirstText(
        liveTrainingHandoffChrome.successSignal,
        trainingState?.latestTrainingHandoff?.successSignal,
        selectedTrainingCardCandidate?.successSignal,
        selectedTrainingRouteCard?.successSignal,
        trainingLedgerEntry?.successSignal,
      );
  const authoritativeDueReviews =
    trainingState?.dueReviews?.length ? trainingState.dueReviews : data.memory.dueReviews;
  const primaryDueReview = authoritativeDueReviews[0];
  const primaryDueReviewTitle = primaryDueReview
    ? reviewConceptLabel(primaryDueReview.concept) ?? t.reviewQueue
    : undefined;
  const trainingReviewItems = useMemo<TrainingReviewItem[]>(
    () =>
      authoritativeDueReviews.slice(0, 4).map((item, index) => ({
        id: `training-review-${index}-${item.concept}`,
        title: reviewConceptLabel(item.concept) ?? t.reviewQueue,
        concept: item.concept,
        focusArea: item.focusArea ?? item.concept,
        taskHint: pickFirstText(item.taskHint, item.reason) ?? item.reason,
        due: item.dueAt,
        evidenceBasis: item.evidenceBasis,
        fsrs:
          item.evidenceBasis === "fsrs_recall"
            ? { intervalDays: item.intervalDays, masteryScore: item.masteryScore }
            : undefined,
        detail: pickFirstText(item.taskHint, item.reason),
        meta: joinInlineMeta(
          pickLanguageAlignedTrainingList(layout.composerLanguage, [item.focusArea, item.severity, item.dueAt]),
        ),
      })),
    [authoritativeDueReviews, layout.composerLanguage, t.reviewQueue],
  );
  const trainingStatusMeta = joinInlineMeta([
    trainingCardStatusLabel(effectiveSelectedTrainingCardStatus, layout.composerLanguage),
    trainingHandoffStatusLabel(
      trainingRestoreReplacesSelectedCard
        ? undefined
        : trainingState?.latestTrainingHandoff?.handoffStatus,
      layout.composerLanguage,
    ),
    localizeTrainingNextHopLabel(
      layout.composerLanguage,
      "status",
      trainingRestoreReplacesSelectedCard
        ? undefined
        : trainingState?.latestTrainingNextHop?.status,
    ),
  ]);
  const trainingExecutionState = useMemo(
    () =>
      deriveTrainingExecutionState({
        cardType: trainingCardType,
        trainingSubmode: effectiveTrainingSubmode,
        selectedCardStatus: effectiveSelectedTrainingCardStatus,
        latestTrainingHandoffStatus: reviewArtifactForeground || trainingRestoreReplacesSelectedCard
          ? undefined
          : trainingState?.latestTrainingHandoff?.handoffStatus,
        latestTrainingNextHopStatus: reviewArtifactForeground || trainingRestoreReplacesSelectedCard
          ? undefined
          : trainingState?.latestTrainingNextHop?.status,
        latestTrainingVerificationState:
          reviewArtifactForeground || trainingRestoreReplacesSelectedCard
            ? undefined
            : trainingState?.latestTrainingHandoff?.verificationState,
        latestTrainingBlockedBy:
          reviewArtifactForeground || trainingRestoreReplacesSelectedCard
            ? undefined
            : (trainingState?.latestTrainingHandoff?.blockedBy ??
              trainingState?.latestTrainingNextHop?.blockedBy),
        latestVerifiedResult: reviewArtifactForeground
          ? undefined
          : (trainingRestoreReplacesSelectedCard
            ? undefined
            : trainingState?.latestLearningVerifiedResult),
        latestLearningBlocker: reviewArtifactForeground
          ? trainingState?.reviewArtifact?.blockedReason
          : (trainingRestoreReplacesSelectedCard
            ? undefined
            : trainingState?.latestLearningBlocker),
        learningPhase: reviewArtifactForeground
          // A foreground review artifact is always a reflection: the learner
          // records what they recalled. The review-artifact card is built with
          // the reflect phase, so the card's own phase never contradicts it.
          ? "reflect"
          : trainingRestoreReplacesSelectedCard
            ? selectedTrainingCardCandidate?.learningPhase
            : (trainingState?.latestTrainingHandoff?.learningPhase ??
              selectedTrainingCardCandidate?.learningPhase),
      }),
    [
      trainingCardType,
      effectiveSelectedTrainingCardStatus,
      effectiveTrainingSubmode,
      reviewArtifactForeground,
      trainingRestoreReplacesSelectedCard,
      trainingState?.latestLearningBlocker,
      trainingState?.latestLearningVerifiedResult,
      trainingState?.latestTrainingHandoff?.handoffStatus,
      trainingState?.latestTrainingHandoff?.verificationState,
      trainingState?.latestTrainingHandoff?.learningPhase,
      trainingState?.latestTrainingHandoff?.blockedBy,
      selectedTrainingCardCandidate?.learningPhase,
      trainingState?.latestTrainingNextHop?.status,
      trainingState?.latestTrainingNextHop?.blockedBy,
      trainingState?.latestTrainingSubmode,
      trainingState?.reviewArtifact?.blockedReason,
      trainingState?.reviewArtifact?.verifiedResult,
      trainingState?.selectedCardStatus,
    ],
  );
  const normalizedTrainingCardStatus = trainingExecutionState.selectedStatus;
  const normalizedTrainingHandoffStatus = trainingExecutionState.handoffStatus;
  const normalizedTrainingNextHopStatus = trainingExecutionState.nextHopStatus;
  const trainingHandoffReflectionRequired =
    !leftoverTrainingHandoffChromeNotLive &&
    (normalizedTrainingHandoffStatus === "needs_reflection" ||
      normalizedTrainingNextHopStatus === "reflection_required");
  const trainingHandoffReturnRequired =
    !leftoverTrainingHandoffChromeNotLive &&
    (normalizedTrainingHandoffStatus === "ready_to_return" ||
      normalizedTrainingNextHopStatus === "return_required");
  const trainingHandoffId = trainingState?.latestTrainingHandoff?.handoffId?.trim();
  const trainingOutcomeCard: TrainingSummaryCard | undefined = trainingRestoreReplacesSelectedCard
    ? undefined
    : (() => {
    if (trainingExecutionState.verification.status === "self_reported") {
      const selfReportedSummary = pickFirstText(
        trainingState?.latestTrainingHandoff?.returnSummary,
        trainingState?.latestTrainingHandoff?.handoffSummary,
        trainingState?.latestLearningPartialProgress,
        trainingState?.latestLearningFollowup,
      );
      if (selfReportedSummary) {
        return {
          title: appUiCopy(layout.composerLanguage, "自我报告结果"),
          detail: selfReportedSummary,
          meta: trainingStatusMeta,
        };
      }
    }
    const verifiedResult = pickFirstText(
      trainingState?.latestLearningVerifiedResult,
      activeTrainingReviewArtifact?.verifiedResult,
      activeTrainingCardId && trainingState?.scenarioLab?.id === activeTrainingCardId
        ? trainingState?.scenarioLab?.reviewOutcome : undefined,
    );
    if (verifiedResult) {
      return {
        title: trainingExecutionState.pendingPlanConfirmation
          ? appUiCopy(layout.composerLanguage, "已验证，待计划确认")
          : appUiCopy(layout.composerLanguage, "已验证结果"),
        detail: verifiedResult,
        meta: trainingStatusMeta,
      };
    }

    const blocker = pickFirstText(
      trainingState?.latestLearningBlocker,
      trainingState?.latestTrainingHandoff?.blockedBy,
      trainingState?.latestTrainingNextHop?.statusReason,
      trainingState?.latestTrainingNextHop?.blockedBy,
      activeTrainingReviewArtifact?.blockedReason,
    );
    if (blocker) {
      return {
        title: appUiCopy(layout.composerLanguage, "当前阻塞"),
        detail: blocker,
        meta: trainingStatusMeta,
      };
    }

    const partialProgress = pickFirstText(
      trainingState?.latestLearningPartialProgress,
      activeTrainingReviewArtifact?.partialProgress,
    );
    if (partialProgress) {
      return {
        title: appUiCopy(layout.composerLanguage, "当前进展"),
        detail: partialProgress,
        meta: trainingStatusMeta,
      };
    }

    return undefined;
    })();
  const trainingNextHopCard: TrainingSummaryCard | undefined =
    leftoverTrainingHandoffChromeNotLive ||
    trainingRestoreReplacesSelectedCard ||
    !trainingState?.latestTrainingNextHop
      ? undefined
      : {
          title:
            pickFirstText(
              liveTrainingHandoffChrome.nextHopTitle,
              liveTrainingHandoffChrome.nextHopCardTitle,
              trainingState.latestTrainingNextHop.title,
              trainingState.latestTrainingNextHop.cardTitle,
            ) ??
            localizeTrainingNextHopLabel(layout.composerLanguage, "target_kind", "next_hop") ??
            localizeTrainingNextHopLabel(layout.composerLanguage, "fallback_title"),
          detail: pickFirstText(
            liveTrainingHandoffChrome.nextHopSummary,
            liveTrainingHandoffChrome.nextHopWhyNow,
            liveTrainingHandoffChrome.nextHopReturnSummary,
            liveTrainingHandoffChrome.nextHopNextAfterCompletion,
            liveTrainingHandoffChrome.nextHopHandoffSummary,
            leftoverTrainingHandoffChromeNotLive
              ? undefined
              : trainingState.latestTrainingNextHop.summary,
            leftoverTrainingHandoffChromeNotLive
              ? undefined
              : trainingState.latestTrainingNextHop.whyNow,
            leftoverTrainingHandoffChromeNotLive
              ? undefined
              : trainingState.latestTrainingNextHop.returnSummary,
            leftoverTrainingHandoffChromeNotLive
              ? undefined
              : trainingState.latestTrainingNextHop.nextAfterCompletion,
          ),
          meta: joinInlineMeta([
            localizeTrainingNextHopLabel(
              layout.composerLanguage,
              "status",
              trainingState.latestTrainingNextHop.status,
            ),
            localizeTrainingNextHopLabel(
              layout.composerLanguage,
              "continue_in",
              trainingState.latestTrainingNextHop.continueIn,
            ),
            localizeTrainingNextHopLabel(
              layout.composerLanguage,
              "project_scope",
              trainingState.latestTrainingNextHop.projectScope,
            ),
            trainingState.latestLearningFocusArea,
          ]),
        };
  const practiceExpectedSymbols = trainingExpectedSymbols(
    selectedTrainingCardCandidate?.expectedSymbols,
    selectedTrainingRouteCard?.expectedSymbols,
    trainingLedgerEntry?.expectedSymbols,
  );
  const trainingCardVerified = trainingExecutionState.verified;
  const trainingCardBlocked = trainingExecutionState.blocked;
  const trainingCardSkipped = trainingExecutionState.skipped;
  const trainingNeedsPrimer = trainingExecutionState.needsPrimer;
  const trainingComposerReflectReason = trainingExecutionState.reflectReason;
  const trainingComposerPhase = trainingExecutionState.composerPhase;
  const trainingComposerStudyMode =
    trainingCardType === "practice" && trainingComposerPhase === "learn";
  const leftoverTrainingFocusChromeNotLive = leftoverTrainingFocusChromeIsNotLive(
    leftoverChromeIdentity,
  );
  const liveTrainingFocusChrome = preferRecoveredTrainingFocusChrome({
    ...leftoverChromeIdentity,
    teachingDecisionFocusArea: data.teachingDecision?.focusArea,
    learnerStateActiveFocus: data.learnerState?.activeFocus,
    latestLearningFocusArea: trainingState?.latestLearningFocusArea,
    cardFocusArea: pickFirstText(
      selectedTrainingCardCandidate?.focusArea,
      selectedTrainingRouteCard?.focusArea,
    ),
  });
  const liveTrainingCurrentFocus = leftoverTrainingFocusChromeNotLive
    ? liveTrainingFocus
    : pickFirstText(
        liveTrainingFocusChrome.latestLearningFocusArea,
        liveTrainingFocusChrome.cardFocusArea,
        liveTrainingFocusChrome.teachingDecisionFocusArea,
        liveTrainingFocusChrome.learnerStateActiveFocus,
        liveTrainingFocus,
      );
  const trainingCoachBridge = useMemo(
    () =>
      buildTrainingCoachBridge({
        language: layout.composerLanguage,
        cardId: activeTrainingCardId,
        cardType: trainingCardType === "flash" ? "flash" : "practice",
        taskTitle: visibleTrainingCardTitle ?? liveTrainingTitle,
        focusArea: liveTrainingCurrentFocus,
        cardTitle: visibleTrainingCardTitle,
        learnerDeliverables: trainingDeliverables,
        verificationSteps: authoritativeVerifyItems,
        successSignal: leftoverTrainingHandoffChromeNotLive
          ? undefined
          : ((trainingRestoreReplacesSelectedCard
              ? undefined
              : liveTrainingHandoffChrome.successSignal) ??
            selectedTrainingCardCandidate?.successSignal ??
            selectedTrainingRouteCard?.successSignal),
        returnWith: leftoverTrainingHandoffChromeNotLive
          ? undefined
          : ((trainingRestoreReplacesSelectedCard
              ? undefined
              : liveTrainingHandoffChrome.returnWith) ??
            selectedTrainingCardCandidate?.returnWith ??
            selectedTrainingRouteCard?.returnWith),
        latestVerifiedResult:
          trainingRestoreReplacesSelectedCard
            ? undefined
            : (trainingState?.latestLearningVerifiedResult ?? activeTrainingReviewArtifact?.verifiedResult),
        latestSubmittedResult:
          selectedTrainingCardCandidate?.learnerAnswer ?? selectedTrainingRouteCard?.learnerAnswer,
        reflection:
          !trainingRestoreReplacesSelectedCard &&
          activeTrainingCardId === (
            trainingState?.latestTrainingHandoff?.cardId ??
            trainingState?.latestTrainingHandoff?.candidateId
          )
            ? trainingState?.latestTrainingHandoff?.reflection
            : undefined,
        latestFollowup:
          leftoverTrainingHandoffChromeNotLive || trainingRestoreReplacesSelectedCard
            ? undefined
            : (liveTrainingHandoffChrome.followup ??
              trainingState?.latestLearningFollowup ??
              trainingState?.latestTrainingNextHop?.nextAfterCompletion),
        reviewSummary: trainingRestoreReplacesSelectedCard
          ? undefined
          : activeTrainingReviewArtifact?.summary,
        reviewBlocker:
          leftoverTrainingHandoffChromeNotLive || trainingRestoreReplacesSelectedCard
            ? undefined
            : (liveTrainingHandoffChrome.blocker ??
              trainingState?.latestLearningBlocker ??
              activeTrainingReviewArtifact?.blockedReason),
        reviewPartialProgress:
          trainingRestoreReplacesSelectedCard
            ? undefined
            : (trainingState?.latestLearningPartialProgress ??
              activeTrainingReviewArtifact?.partialProgress),
        reviewRootCause: trainingRestoreReplacesSelectedCard
          ? undefined
          : activeTrainingReviewArtifact?.rootCause,
        reviewNextRule: trainingRestoreReplacesSelectedCard
          ? undefined
          : activeTrainingReviewArtifact?.nextSelfImplementationRule,
        reviewRecommendedActions: trainingRestoreReplacesSelectedCard
          ? undefined
          : activeTrainingReviewArtifact?.recommendedActions,
        reviewStatus:
          trainingCardVerified
            ? "resolved"
            : trainingCardBlocked || activeTrainingReviewArtifact?.status === "active"
              ? "active"
              : activeTrainingReviewArtifact?.status === "archived"
                ? "archived"
                : undefined,
      }),
    [
      activeTrainingCardId,
      activeTrainingReviewArtifact,
      authoritativeVerifyItems,
      leftoverTrainingHandoffChromeNotLive,
      liveTrainingCurrentFocus,
      liveTrainingFocus,
      liveTrainingHandoffChrome.blocker,
      liveTrainingHandoffChrome.followup,
      liveTrainingHandoffChrome.returnWith,
      liveTrainingHandoffChrome.successSignal,
      liveTrainingTitle,
      layout.composerLanguage,
      selectedTrainingCardCandidate?.focusArea,
      selectedTrainingCardCandidate?.learnerAnswer,
      selectedTrainingCardCandidate?.returnWith,
      selectedTrainingCardCandidate?.successSignal,
      selectedTrainingCardCandidate?.title,
      selectedTrainingRouteCard?.focusArea,
      selectedTrainingRouteCard?.learnerAnswer,
      selectedTrainingRouteCard?.returnWith,
      selectedTrainingRouteCard?.successSignal,
      selectedTrainingRouteCard?.title,
      trainingCardBlocked,
      trainingCardType,
      trainingCardVerified,
      trainingDeliverables,
      trainingRestoreReplacesSelectedCard,
      trainingState?.latestLearningBlocker,
      trainingState?.latestLearningFocusArea,
      trainingState?.latestLearningFollowup,
      trainingState?.latestLearningPartialProgress,
      trainingState?.latestLearningVerifiedResult,
      trainingState?.latestTrainingHandoff?.returnWith,
      trainingState?.latestTrainingHandoff?.cardId,
      trainingState?.latestTrainingHandoff?.candidateId,
      trainingState?.latestTrainingHandoff?.reflection,
      trainingState?.latestTrainingHandoff?.successSignal,
      trainingState?.latestTrainingNextHop?.nextAfterCompletion,
      activeTrainingReviewArtifact?.blockedReason,
      activeTrainingReviewArtifact?.nextSelfImplementationRule,
      activeTrainingReviewArtifact?.partialProgress,
      activeTrainingReviewArtifact?.recommendedActions,
      activeTrainingReviewArtifact?.rootCause,
      activeTrainingReviewArtifact?.status,
      activeTrainingReviewArtifact?.summary,
      activeTrainingReviewArtifact?.verifiedResult,
      trainingState?.selectedCardId,
      trainingState?.selectedCardTitle,
      visibleTrainingCardTitle,
    ],
  );
  const selectedTrainingFlashCard =
    trainingCardType === "flash"
      ? (selectedTrainingCardCandidate?.type === "flash"
          ? selectedTrainingCardCandidate
          : selectedTrainingRouteCard?.type === "flash"
            ? selectedTrainingRouteCard
            : undefined)
      : undefined;
  const activeTheoryDrill =
    trainingState?.theoryDrill?.id && trainingState.theoryDrill.id === activeTrainingCardId
      ? trainingState.theoryDrill
      : undefined;
  const flashQuestion = activeTheoryDrill?.questions?.[0];
  const trainingFlashPrompt = pickFirstText(
    selectedTrainingFlashCard?.question,
    flashQuestion?.prompt,
    selectedTrainingFlashCard?.problemStatement,
    selectedTrainingFlashCard?.scenario,
  );
  const trainingTargetSkill = pickFirstText(
    selectedTrainingCardCandidate?.targetSkill,
    selectedTrainingRouteCard?.targetSkill,
    trainingState?.activeTrainingCardRouting?.selectedCard?.targetSkill,
    leftoverTrainingFocusChromeNotLive ? undefined : liveTrainingFocusChrome.cardFocusArea,
  );
  const liveTrainingSkill = liveTrainingTargetSkill({
    ...formalPlanIdentity,
    taskTitle: data.task.title,
    cardSkill: trainingTargetSkill,
    liveFocus: liveTrainingFocus,
  });
  const trainingProblemStatement = pickFirstText(
    trainingCardType === "flash" ? trainingFlashPrompt : undefined,
    selectedTrainingCardCandidate?.problemStatement,
    selectedTrainingRouteCard?.problemStatement,
    trainingState?.activeTrainingCardRouting?.selectedCard?.problemStatement,
    trainingFlashPrompt,
    selectedTrainingCardCandidate?.question,
    selectedTrainingRouteCard?.question,
  );
  const trainingFlashChoices =
    selectedTrainingFlashCard?.choices?.length ? selectedTrainingFlashCard.choices : flashQuestion?.choices;
  const normalizedTrainingFlashChoices = useMemo(
    () =>
      (trainingFlashChoices ?? [])
        .map((choice) => choice.trim())
        .filter((choice): choice is string => Boolean(choice)),
    [trainingFlashChoices],
  );
  const normalizedTrainingFlashChoicesKey = normalizedTrainingFlashChoices.join("\u0000");
  const trainingComposerVerifyItems = authoritativeVerifyItems.slice(0, 4);
  const trainingComposerSelectedVerifyItem =
    trainingComposerVerifyItems[trainingComposerVerifyIndex] ?? trainingComposerVerifyItems[0];
  const hasTrainingCard = leftoverTrainingHandoffChromeNotLive
    ? false
    : Boolean(
        (trainingState?.selectedCardId?.trim() &&
          (selectedTrainingCardCandidate || rawTrainingRouteCard)) ||
          (trainingRestoreContext?.target && restoredTrainingCardCandidate),
      );
  const hasRenderableTrainingCard = leftoverTrainingHandoffChromeNotLive
    ? false
    : hasTrainingCard || Boolean(trainingState?.latestTrainingNextHop);
  const boundTrainingCardFacts = useMemo(() => {
    const resolved = resolveBoundTrainingCardFacts({
      eligible: hasTrainingCard && syncStatus === "current" &&
        !reviewArtifactForeground && trainingCardType !== "flash",
      activeCardId: activeTrainingCardId,
      candidate: selectedTrainingCardCandidate,
      routeCard: selectedTrainingRouteCard,
    });
    if (resolved) {
      return resolved;
    }
    // The card shell may still be visible (selected identity), but no authored
    // fact is eligible. Return an empty bound shell instead of undefined so
    // readTrainingCardText/List cannot fall back to foreign/stale legacy data.
    if (
      hasTrainingCard &&
      activeTrainingCardId &&
      !reviewArtifactForeground &&
      trainingCardType !== "flash"
    ) {
      return { cardId: activeTrainingCardId, text: {}, lists: {}, bound: false };
    }
    return undefined;
  }, [hasTrainingCard, syncStatus, reviewArtifactForeground, trainingCardType,
    activeTrainingCardId, selectedTrainingCardCandidate, selectedTrainingRouteCard]);
  useEffect(() => {
    const shouldPublishTrainingFacts =
      activeView === "coach" &&
      (hasTrainingCard ||
        Boolean(trainingRestoreContext?.target) ||
        (layout.learningDrawerOpen === true && layout.learningSection === "practice"));
    if (!shouldPublishTrainingFacts) {
      return;
    }
    const scenarioLabVisible = Boolean(
      trainingState?.scenarioLab?.id &&
        selectedTrainingCardCandidate?.cardId === trainingState.scenarioLab.id,
    );
    const theoryDrillVisible = Boolean(
      trainingState?.theoryDrill?.id &&
        selectedTrainingCardCandidate?.cardId === trainingState.theoryDrill.id,
    );
    const reviewArtifactVisible = Boolean(
      trainingState?.reviewArtifact?.id &&
        selectedTrainingCardCandidate?.cardId === trainingState.reviewArtifact.id,
    );
    const nextHopVisible = Boolean(
      trainingState?.latestTrainingNextHop &&
        selectedTrainingCardCandidate?.cardId ===
          (trainingState.latestTrainingNextHop.targetId ??
            trainingState.latestTrainingNextHop.candidateId ??
            "next-hop"),
    );
    const restoreKind =
      trainingRestoreContext?.target ??
      (nextHopVisible
        ? "next_hop"
        : scenarioLabVisible
          ? "scenario_lab"
          : theoryDrillVisible
            ? "theory_drill"
            : reviewArtifactVisible
              ? "review_artifact"
              : undefined);
    const activeSubmode =
      effectiveTrainingSubmode ?? (trainingCardType === "flash" ? "flash" : "practice");
    const facts: DebugVisibleTrainingFacts = {
      surface: "training",
      activeView: "training",
      restoreKind,
      surfaceMode: "project",
      activeSubmode,
      visibleTitle: visibleTrainingCardTitle,
      visibleSummary: trainingProblemStatement,
      scenarioLabVisible,
      scenarioLabId: scenarioLabVisible ? trainingState?.scenarioLab?.id : undefined,
      scenarioLabTitle: scenarioLabVisible ? trainingState?.scenarioLab?.title : undefined,
      scenarioLabStatus: scenarioLabVisible ? trainingState?.scenarioLab?.status : undefined,
      scenarioLabScenario: scenarioLabVisible
        ? trainingState?.scenarioLab?.summary
        : undefined,
      theoryDrillVisible,
      theoryDrillId: theoryDrillVisible ? trainingState?.theoryDrill?.id : undefined,
      theoryDrillTitle: theoryDrillVisible ? trainingState?.theoryDrill?.title : undefined,
      theoryDrillStatus: theoryDrillVisible ? trainingState?.theoryDrill?.status : undefined,
      theoryQuestionPrompt: theoryDrillVisible ? trainingState?.theoryDrill?.questions?.[0]?.prompt : undefined,
      reviewArtifactVisible,
      reviewArtifactId: reviewArtifactVisible ? trainingState?.reviewArtifact?.id : undefined,
      reviewArtifactStatus: reviewArtifactVisible ? trainingState?.reviewArtifact?.status : undefined,
      nextHopVisible,
      nextHopTitle: nextHopVisible ? visibleTrainingCardTitle : undefined,
      nextHopStatus: nextHopVisible ? trainingState?.latestTrainingNextHop?.status : undefined,
      nextHopContinueIn: nextHopVisible
        ? trainingState?.latestTrainingNextHop?.continueIn
        : undefined,
      nextHopCandidateType: nextHopVisible
        ? trainingState?.latestTrainingNextHop?.candidateType
        : undefined,
      nextHopTargetKind: nextHopVisible ? trainingState?.latestTrainingNextHop?.targetKind : undefined,
      nextHopTargetId: nextHopVisible ? trainingState?.latestTrainingNextHop?.targetId : undefined,
      nextHopReviewArtifactId: nextHopVisible
        ? trainingState?.latestTrainingNextHop?.reviewArtifactId
        : undefined,
      nextHopPlanEvidenceId: nextHopVisible
        ? trainingState?.latestTrainingNextHop?.planEvidenceId
        : undefined,
      singleCardImmersive: true,
      routeStripCollapsedByDefault: true,
      cardOnlyMode: true,
      secondaryPanelsCollapsedByDefault: true,
    };
    postDebugVisibleFacts({ activeView: "training", training: facts });
  }, [
    activeView,
    hasTrainingCard,
    layout.learningDrawerOpen,
    layout.learningSection,
    selectedTrainingCardCandidate?.cardId,
    selectedTrainingCardCandidate?.title,
    trainingCardType,
    effectiveTrainingSubmode,
    trainingProblemStatement,
    trainingRestoreContext?.target,
    trainingState?.latestTrainingNextHop,
    trainingState?.latestTrainingSubmode,
    trainingState?.reviewArtifact,
    trainingState?.scenarioLab,
    trainingState?.selectedCardTitle,
    trainingState?.theoryDrill,
    visibleTrainingCardTitle,
  ]);
  useEffect(() => {
    setInlinePracticeCollapsed(false);
  }, [activeTrainingCardId, trainingReviewQueueRequested]);
  const resolvedReviewArtifact = reviewArtifactForeground && trainingState?.reviewArtifact?.status === "resolved";
  const trainingComposerEnabled = activeView === "training" && hasTrainingCard;
  const trainingComposerTalkMode = false; // Explicit requests are routed directly from the shared input.
  const trainingComposerUsesAnswerMode = trainingComposerPhase === "answer";
  const trainingComposerPracticeInputMode =
    trainingCardType === "practice" && trainingComposerPhase === "try";
  const trainingComposerManualPracticeMode =
    trainingComposerPracticeInputMode && trainingPracticeVerificationMode === "manual";
  const trainingComposerFilePracticeMode =
    trainingComposerPracticeInputMode && trainingPracticeVerificationMode === "file";
  const trainingComposerReflectMode = trainingComposerPhase === "reflect";
  const trainingComposerReturnMode = trainingComposerPhase === "return";
  const inlinePracticeAwaitingComposerSubmission =
    activeView === "coach" &&
    hasTrainingCard &&
    !inlinePracticeCollapsed &&
    !resolvedReviewArtifact &&
    (trainingComposerUsesAnswerMode || trainingComposerReflectMode);
  useEffect(() => {
    const pending = pendingTrainingHandoffSubmissionRef.current;
    if (!pending || pending.cardId !== trainingState?.selectedCardId) {
      return;
    }

    const completed =
      pending.phase === "reflect"
        ? trainingHandoffReturnRequired
        : normalizedTrainingNextHopStatus === "continued_in_chat";
    if (!completed) {
      return;
    }

    pendingTrainingHandoffSubmissionRef.current = undefined;
    if (pending.phase === "return") {
      // Draft handoff only: the bridge draft waits in the coach composer
      // (stored per scope). Navigation and focus stay with the learner — the
      // training card shows its own explicit "回到对话" exit.
      setComposerDraft(composeTrainingCoachBridgeDraft(trainingCoachBridge), composerSessionKey);
      return;
    }

    setActivityDraft("");
  }, [
    normalizedTrainingNextHopStatus,
    setComposerDraft,
    setActivityDraft,
    trainingCoachBridge,
    trainingHandoffReturnRequired,
    trainingState?.selectedCardId,
  ]);
  useEffect(() => {
    setTrainingComposerVerifyIndex(0);
    setTrainingComposerRoute("card");
    setTrainingComposerFlashMode(
      trainingCardType === "flash" && normalizedTrainingFlashChoices.length > 0 ? "choice" : "short",
    );
    setTrainingComposerPracticeReturnMode(
      trainingCardBlocked && !trainingCardVerified ? "blocked" : "result",
    );
  }, [
    normalizedTrainingFlashChoicesKey,
    trainingCardBlocked,
    trainingCardType,
    trainingCardVerified,
    trainingState?.selectedCardId,
  ]);
  return {
    trainingState,
    selectedTrainingCardCandidate,
    trainingRestoreForeground,
    reviewArtifactForeground,
    activeTrainingReviewArtifact,
    trainingCardType,
    activeTrainingCardId,
    selectedTrainingRouteCard,
    activityDraftKey,
    activityDraft,
    setComposerHintLevels,
    composerHintLevel,
    activityAttachments,
    setActivityAttachments,
    setActivityDraft,
    trainingRestoreReplacesSelectedCard,
    effectiveTrainingSubmode,
    effectiveSelectedTrainingCardStatus,
    visibleTrainingCardTitle,
    trainingLearningSubtype,
    trainingLearningFamily,
    trainingPracticeVerificationMode,
    trainingScenarioPackLabel,
    trainingSuggestedWorkspaceAction,
    trainingScenario,
    coachTrainingInlineAction,
    trainingApiHints,
    trainingSelfCheck,
    trainingFilesToTouch,
    composerMentionItems,
    composerResourceIdsFor,
    activeComposerResourceIds,
    handleComposerMentionSelect,
    trainingHintLadder,
    trainingCommonMistakes,
    trainingStuckRecovery,
    trainingReflectionPrompt,
    trainingDeliverable,
    trainingValidationMethod,
    trainingVerificationMethod,
    trainingDeliverables,
    authoritativeVerifyItems,
    liveTrainingWhy,
    liveTrainingCoachChrome,
    liveTrainingHandoffChrome,
    trainingReturnWithText,
    trainingNextAfterCompletionText,
    trainingFallbackActionText,
    trainingSuccessSignal,
    trainingReviewItems,
    normalizedTrainingNextHopStatus,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingHandoffId,
    trainingOutcomeCard,
    trainingNextHopCard,
    practiceExpectedSymbols,
    trainingCardVerified,
    trainingCardBlocked,
    trainingComposerReflectReason,
    trainingComposerPhase,
    trainingComposerStudyMode,
    leftoverTrainingFocusChromeNotLive,
    liveTrainingFocusChrome,
    liveTrainingCurrentFocus,
    trainingCoachBridge,
    activeTheoryDrill,
    flashQuestion,
    trainingFlashPrompt,
    trainingTargetSkill,
    liveTrainingSkill,
    trainingProblemStatement,
    normalizedTrainingFlashChoices,
    trainingComposerSelectedVerifyItem,
    hasTrainingCard,
    hasRenderableTrainingCard,
    boundTrainingCardFacts,
    resolvedReviewArtifact,
    trainingComposerEnabled,
    trainingComposerTalkMode,
    trainingComposerUsesAnswerMode,
    trainingComposerPracticeInputMode,
    trainingComposerManualPracticeMode,
    trainingComposerFilePracticeMode,
    trainingComposerReflectMode,
    trainingComposerReturnMode,
    inlinePracticeAwaitingComposerSubmission,
  };
}
