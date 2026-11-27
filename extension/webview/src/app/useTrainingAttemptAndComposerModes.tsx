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

export function useTrainingAttemptAndComposerModes(ctx: WorkbenchCtxAfterE5a) {
  const {
    planHasFormalThread,
    planIsFrozen,
    resolvedPlanComposerMode,
    data,
    layout,
    setActiveView,
    setComposerDraft,
    clearDockReturnNotice,
    setContextDetail,
    setIncludeRelatedFiles,
    setFollowCurrentFile,
    setOperationMessage,
    trainingComposerFlashMode,
    trainingComposerPracticeReturnMode,
    setTrainingComposerRoute,
    setTrainingVerifyNotice,
    requestTrainingPersistence,
    planComposerMode,
    streaming,
    openMenu,
    setOpenMenu,
    selectedCommandIndex,
    setSelectedCommandIndex,
    dismissedComposerDeck,
    setDismissedComposerDeck,
    isBrowserPreview,
    activeView,
    t,
    composerDeckRef,
    streamResumeDraftRef,
    resourceConversationContextIds,
    composerModelSearchRef,
    uploadFilesInputRef,
    uploadFolderInputRef,
    pendingTrainingHandoffSubmissionRef,
    requestCoachComposerFocus,
    draft,
    composerDraftScope,
    composerHasSavedProfiles,
    composerProviderCopy,
    composerProviderMenuItems,
    composerModelQuery,
    setComposerModelQuery,
    filteredComposerProviderMenuItems,
    composerThinkingDescriptor,
    refreshComposerProviderModels,
    setComposerThinking,
    switchComposerProviderModel,
    switchComposerProviderModelForProfile,
    hasFormalPlan,
    activePlanStage,
    recoveredRuntime,
    leftoverTrainingHandoffChromeNotLive,
    leftoverResourceSelectedDetailNotLive,
    latestCoachArtifact,
    resolvedCoachFocus,
    resolvedCoachStage,
    recoveredDisplayFacts,
    formalPlanLive,
    livePlanFrozen,
    livePlanTitle,
    livePlanSummary,
    leftoverSuggestedActionNotLive,
    liveSuggestedActions,
    liveResources,
    liveSandboxState,
    trainingState,
    selectedTrainingCardCandidate,
    reviewArtifactForeground,
    trainingCardType,
    activeTrainingCardId,
    selectedTrainingRouteCard,
    activityDraft,
    setActivityDraft,
    visibleTrainingCardTitle,
    coachTrainingInlineAction,
    trainingFilesToTouch,
    trainingDeliverables,
    authoritativeVerifyItems,
    trainingNextAfterCompletionText,
    trainingFallbackActionText,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingHandoffId,
    practiceExpectedSymbols,
    trainingCardVerified,
    trainingCardBlocked,
    trainingComposerReflectReason,
    trainingComposerStudyMode,
    trainingCoachBridge,
    normalizedTrainingFlashChoices,
    trainingComposerSelectedVerifyItem,
    boundTrainingCardFacts,
    trainingComposerUsesAnswerMode,
    trainingComposerManualPracticeMode,
    trainingComposerFilePracticeMode,
    trainingComposerReflectMode,
    trainingComposerReturnMode,
    customSkills,
    availableSkillCatalog,
    selectSkillSuggestion,
    openSkillSettings,
    composerUsesTrainingFlow,
    activeSkillDraft,
    matchingLocalSkills,
    matchingLocalCommands,
    handleSuggestedAction,
    runComposerCommand,
  } = ctx;
  // Phase-D training attempt lifecycle: entering a formal card starts/resumes
  // an attempt; the Try draft is throttled into attempt updates; hints bump
  // the assistance level; return closes the lifecycle. Identity fields are
  // derived server-side from the persisted attempt.
  // Rules of Hooks: call the hook at top level. It returns a stable identity
  // (internal useMemo), so the dependent effects below do not re-fire per render.
  const attemptLifecycle = useTrainingAttemptLifecycle();
  // The start/recover effect reads the active file as a snapshot only; keeping
  // it in a ref avoids making a file switch restart the attempt.
  const attemptStartFilePathRef = useRef<string | undefined>(data.liveContext?.activeFile);
  attemptStartFilePathRef.current = data.liveContext?.activeFile;

  // When a formal training card becomes active, start or resume its attempt.
  useEffect(() => {
    if (activeView !== "training" || !activeTrainingCardId || isBrowserPreview || trainingComposerReturnMode || reviewArtifactForeground) {
      return;
    }
    attemptLifecycle.startOrRecover(activeTrainingCardId, {
      filePath: attemptStartFilePathRef.current ?? undefined,
    });
  }, [activeView, activeTrainingCardId, attemptLifecycle, isBrowserPreview, trainingComposerReturnMode, reviewArtifactForeground]);

  const handleHintReveal = useCallback(
    (hintLevel: number) => {
      if (!activeTrainingCardId || isBrowserPreview) {
        return;
      }
      const clamped = Math.min(3, Math.max(1, hintLevel));
      attemptLifecycle.updateAssistance(activeTrainingCardId, `hint_level_${clamped}`);
    },
    [activeTrainingCardId, attemptLifecycle, isBrowserPreview],
  );

  const checkRemoteRunnerBoundary = useCallback((): string | null => {
    // TR-100: remote workspace without a runner must not silently verify.
    const wsRoot = data.memory.workspace?.workspaceId ?? "";
    if (!wsRoot) return null;
    // VS Code remote workspaces use vscode-remote:// or ssh:// URI schemes.
    const isRemote = wsRoot.startsWith("vscode-remote://") || wsRoot.startsWith("ssh://");
    if (!isRemote) return null;
    return "Remote workspace detected but no remote verification runner is available. Trainer will not run local checks against a remote project.";
  }, [data.memory.workspace?.workspaceId]);

  const handleVerifyTrainingFromIde = useCallback(() => {
    const boundaryNotice = checkRemoteRunnerBoundary();
    if (boundaryNotice) {
      // The card owns this notice; the surface is no longer pre-set — the
      // following verify failure carries the training marker and scopes itself.
      setTrainingVerifyNotice(boundaryNotice);
      return;
    }
    if (isBrowserPreview || leftoverTrainingHandoffChromeNotLive || !activeTrainingCardId) {
      const notice = leftoverTrainingHandoffChromeNotLive
        ? appUiCopy(layout.composerLanguage, "验证未通过：当前训练卡片不是实时状态。")
        : !activeTrainingCardId
          ? appUiCopy(layout.composerLanguage, "没有可验证的当前文件。")
          : appUiCopy(layout.composerLanguage, "预览不能验真实工作区文件。请回 VS Code 打开文件后再验证。");
      setTrainingVerifyNotice(notice);
      return;
    }
    postMessage({
      type: "command/execute",
      payload: {
        commandId: trainerCommands.evaluateCurrentFile,
        payload: {
          source: "training",
          trainingPhase: "verify",
          cardId: activeTrainingCardId,
          cardTitle: readTrainingCardText(boundTrainingCardFacts, "title", () => visibleTrainingCardTitle),
          acceptanceCriteria: boundTrainingCardFacts
            ? boundTrainingCardFacts.lists.acceptanceCriteria ?? boundTrainingCardFacts.lists.verificationSteps ?? []
            : selectedTrainingCardCandidate?.acceptanceCriteria?.length
              ? selectedTrainingCardCandidate.acceptanceCriteria
              : selectedTrainingRouteCard?.acceptanceCriteria?.length
                ? selectedTrainingRouteCard.acceptanceCriteria
                : authoritativeVerifyItems,
          learnerDeliverables: readTrainingCardList(boundTrainingCardFacts, "learnerDeliverables", () => trainingDeliverables),
          expectedSymbols: trainingCardType === "practice" ? readTrainingCardList(boundTrainingCardFacts, "expectedSymbols", () => practiceExpectedSymbols) : [],
          filesToTouch: readTrainingCardList(boundTrainingCardFacts, "filesToTouch", () => trainingFilesToTouch),
        },
      },
    });
  }, [
    leftoverTrainingHandoffChromeNotLive,
    activeTrainingCardId,
    boundTrainingCardFacts,
    authoritativeVerifyItems,
    selectedTrainingCardCandidate?.acceptanceCriteria,
    selectedTrainingRouteCard?.acceptanceCriteria,
    isBrowserPreview,
    layout.composerLanguage,
    trainingFilesToTouch,
    practiceExpectedSymbols,
    setOperationMessage,
    trainingCardType,
    trainingDeliverables,
    visibleTrainingCardTitle,
  ]);

  const handleSubmitTrainingEvidence = useCallback(async (evidence: string, returnMode = trainingComposerPracticeReturnMode): Promise<boolean> => {
    if (leftoverTrainingHandoffChromeNotLive) {
      return false;
    }
    const normalizedEvidence = evidence.trim();
    if (reviewArtifactForeground && trainingState?.reviewArtifact?.id) {
      if (!normalizedEvidence) {
        return false;
      }
      await requestTrainingPersistence(trainerCommands.trainingReviewArtifactAction, {
        reviewArtifactId: trainingState.reviewArtifact.id,
        action: "resolved",
        note: normalizedEvidence,
      });
      return true;
    }
    const shouldSubmitTrainingHandoffReturn =
      trainingComposerReturnMode &&
      trainingHandoffReturnRequired &&
      Boolean(activeTrainingCardId);
    if (shouldSubmitTrainingHandoffReturn && activeTrainingCardId) {
      pendingTrainingHandoffSubmissionRef.current = {
        phase: "return",
        cardId: activeTrainingCardId,
      };
      try {
        await requestTrainingPersistence(trainerCommands.trainingReturn, {
          cardId: activeTrainingCardId,
          handoffId: trainingHandoffId ?? "",
        });
      } catch (error) {
        pendingTrainingHandoffSubmissionRef.current = undefined;
        throw error;
      }
      return false;
    }

    if (!normalizedEvidence) {
      return false;
    }

    const practiceResultMode = returnMode === "result";
    const practiceBlockedMode = returnMode === "blocked";

    const shouldSubmitTrainingHandoffReflection =
      trainingComposerReflectMode &&
      trainingHandoffReflectionRequired &&
      Boolean(activeTrainingCardId);
    if (shouldSubmitTrainingHandoffReflection && activeTrainingCardId) {
      pendingTrainingHandoffSubmissionRef.current = {
        phase: "reflect",
        cardId: activeTrainingCardId,
      };
      try {
        await requestTrainingPersistence(trainerCommands.trainingReflect, {
          cardId: activeTrainingCardId,
          handoffId: trainingHandoffId ?? "",
          reflection: normalizedEvidence,
        });
      } catch (error) {
        pendingTrainingHandoffSubmissionRef.current = undefined;
        throw error;
      }
      return false;
    }

    if (trainingComposerStudyMode && activeTrainingCardId) {
      await requestTrainingPersistence(trainerCommands.trainingCardStatusTransition, {
        cardId: activeTrainingCardId,
        newStatus: "active",
        reason: "study_note_submitted",
      });
    }

    const shouldReviewAnsweredFlash =
      trainingComposerReflectMode &&
      trainingComposerReflectReason === "flash_answered" &&
      activeTrainingCardId;

    if (shouldReviewAnsweredFlash && activeTrainingCardId) {
      await requestTrainingPersistence(trainerCommands.trainingCardStatusTransition, {
        cardId: activeTrainingCardId,
        newStatus: "reviewed",
        reason: "flash_reflection_submitted",
      });
    }

    const shouldSubmitManualPracticeReturn =
      trainingComposerManualPracticeMode && activeTrainingCardId;
    const shouldSubmitBlockedFilePracticeReturn =
      trainingComposerFilePracticeMode && practiceBlockedMode && activeTrainingCardId;

    let authoritativePracticeStatus: string | undefined;
    if ((shouldSubmitManualPracticeReturn || shouldSubmitBlockedFilePracticeReturn) && activeTrainingCardId) {
      const passed = Boolean(shouldSubmitManualPracticeReturn && practiceResultMode);
      // commandId: trainerCommands.trainingPracticeReturn — persist the single-card practice return.
      const response = await requestTrainingPersistence(trainerCommands.trainingPracticeReturn, {
        cardId: activeTrainingCardId,
        passed,
        summary: normalizedEvidence,
        nextStep: passed
          ? (trainingNextAfterCompletionText ?? trainingState?.latestLearningFollowup ?? "")
          : (trainingFallbackActionText ?? trainingState?.latestLearningFollowup ?? ""),
        focusArea:
          trainingState?.latestLearningFocusArea ??
          selectedTrainingCardCandidate?.focusArea ??
          selectedTrainingRouteCard?.focusArea ??
          resolvedCoachFocus ??
          "",
        failedChecks:
          passed || !trainingComposerSelectedVerifyItem
            ? []
            : [trainingComposerSelectedVerifyItem],
        evidenceSource: "learner_return",
      });
      const workspace =
        response && typeof response === "object" && !Array.isArray(response)
          ? (response as { workspace?: unknown }).workspace
          : undefined;
      const selectedCardStatus =
        workspace && typeof workspace === "object" && !Array.isArray(workspace)
          ? (workspace as { selected_card_status?: unknown }).selected_card_status
          : undefined;
      authoritativePracticeStatus =
        typeof selectedCardStatus === "string" ? selectedCardStatus : undefined;
    }

    const manualPracticePassed =
      trainingComposerManualPracticeMode && practiceResultMode;
    const manualPracticeBlocked =
      trainingComposerManualPracticeMode && practiceBlockedMode;
    const filePracticeBlocked = trainingComposerFilePracticeMode && practiceBlockedMode;
    const trainingFailureOutcome =
      manualPracticeBlocked ||
      filePracticeBlocked ||
      trainingCardBlocked ||
      authoritativePracticeStatus === "blocked";
    const trainingPassOutcome =
      authoritativePracticeStatus === "active" ||
      (!authoritativePracticeStatus && trainingCardVerified);

    await requestTrainingPersistence(trainerCommands.evidenceEnqueue, {
      source: "learning_signal",
      summary: normalizedEvidence,
      concepts: [
        trainingState?.latestLearningFocusArea,
        selectedTrainingCardCandidate?.focusArea,
        resolvedCoachFocus,
      ].filter((value): value is string => Boolean(value?.trim())),
      outcome: trainingFailureOutcome ? "fail" : trainingPassOutcome ? "pass" : "note",
      sourceCardId: activeTrainingCardId,
      targetPlanStageId: activePlanStage?.id,
      confidence: trainingPassOutcome ? 0.86 : trainingFailureOutcome ? 0.52 : 0.68,
    });
    return true;
  }, [
    activePlanStage?.id,
    activeTrainingCardId,
    leftoverTrainingHandoffChromeNotLive,
    requestTrainingPersistence,
    reviewArtifactForeground,
    resolvedCoachFocus,
    selectedTrainingCardCandidate?.focusArea,
    selectedTrainingRouteCard?.focusArea,
    trainingComposerFilePracticeMode,
    trainingComposerReflectMode,
    trainingComposerReflectReason,
    trainingComposerReturnMode,
    trainingCardBlocked,
    trainingComposerManualPracticeMode,
    trainingComposerPracticeReturnMode,
    trainingComposerSelectedVerifyItem,
    trainingComposerStudyMode,
    trainingCardVerified,
    trainingFallbackActionText,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingHandoffId,
    trainingNextAfterCompletionText,
    trainingState?.latestLearningFocusArea,
    trainingState?.latestLearningFollowup,
    trainingState?.reviewArtifact?.id,
  ]);

  const handleResumeTrainingInCoach = useCallback(() => {
    if (leftoverTrainingHandoffChromeNotLive) {
      setActiveView("coach");
      requestCoachComposerFocus();
      return;
    }
    if (reviewArtifactForeground && trainingState?.reviewArtifact?.status === "resolved") {
      const title = trainingState.reviewArtifact.title ?? trainingState.reviewArtifact.focusArea ?? "review";
      const result = trainingState.reviewArtifact.verifiedResult ?? trainingState.reviewArtifact.summary ?? "";
      setActiveView("coach");
      setComposerDraft(
        appUiCopy(layout.composerLanguage, "我完成了“{t}”的回顾。结论：{r}\n\n请帮我安排下一步。")
          .replace("{t}", () => title)
          .replace("{r}", () => result),
      );
      requestCoachComposerFocus();
      return;
    }

    if (trainingHandoffReflectionRequired) {
      setTrainingComposerRoute("card");
      setActivityDraft("");
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
      return;
    }

    if (trainingHandoffReturnRequired && trainingState?.selectedCardId) {
      void handleSubmitTrainingEvidence("").catch(() => {
        setOperationMessage({
          tone: "error",
          message: trainingPersistenceFailureMessage(layout.composerLanguage),
        });
      });
      return;
    }

    setActiveView("coach");
    setComposerDraft(composeTrainingCoachBridgeDraft(trainingCoachBridge));
    requestCoachComposerFocus();
  }, [
    handleSubmitTrainingEvidence,
    layout.composerLanguage,
    leftoverTrainingHandoffChromeNotLive,
    requestCoachComposerFocus,
    reviewArtifactForeground,
    setActiveView,
    setComposerDraft,
    setOperationMessage,
    trainingCoachBridge,
    trainingHandoffReflectionRequired,
    trainingHandoffReturnRequired,
    trainingState?.reviewArtifact?.focusArea,
    trainingState?.reviewArtifact?.status,
    trainingState?.reviewArtifact?.summary,
    trainingState?.reviewArtifact?.title,
    trainingState?.reviewArtifact?.verifiedResult,
    trainingState?.selectedCardId,
  ]);

  const queueComposerPrompt = useCallback(
    (prompt: string) => {
      setOpenMenu(undefined);
      setComposerDraft(prompt);
      window.requestAnimationFrame(() => {
        focusComposerInput();
      });
    },
    [setComposerDraft],
  );

  const selectedResourceNavigationLabel = leftoverResourceSelectedDetailNotLive
    ? undefined
    : truncateInlineText(
        data.memory.selectedResourceDetail?.title ??
          data.memory.selectedResourceDetail?.sandboxPath ??
          liveSandboxState?.selectedPath,
        layout.composerLanguage === "zh-CN" ? 22 : 46,
      ) ??
      truncateInlineText(
        data.memory.selectedResourceDetail?.source,
        layout.composerLanguage === "zh-CN" ? 22 : 46,
      );
  const dockStageProgressLabel = hasFormalPlan && activePlanStage
    ? PLAN_COPY[layout.composerLanguage].stageProgress
        .replace(
          "{index}",
          String(
            data.plan.stages.findIndex((stage) => stage.id === activePlanStage.id) + 1,
          ),
        )
        .replace("{total}", String(data.plan.stages.length))
    : null;
  const dockAnchorControl = useComposerDockAnchor(
    activeView,
    activePlanStage?.title,
    dockStageProgressLabel,
    selectedResourceNavigationLabel,
  );
  const resourceConversationContextLabel = useMemo(() => {
    if (resourceConversationContextIds.length === 0) {
      return undefined;
    }
    const selectedNames = resourceConversationContextIds
      .map((resourceId) => liveResources.find((resource) => resource.id === resourceId)?.title?.trim())
      .filter((title): title is string => Boolean(title));
    const total = resourceConversationContextIds.length;
    const visibleNames = selectedNames.slice(0, 2);
    const overflowCount = Math.max(total - visibleNames.length, 0);
    if (layout.composerLanguage === "zh-CN") {
      const names = visibleNames.join("、");
      return names
        ? `已带入资料：${names}${overflowCount > 0 ? ` 等 ${total} 份` : ""}`
        : `已带入 ${total} 份资料`;
    }
    const names = visibleNames.join(", ");
    return names
      ? `Resource context: ${names}${overflowCount > 0 ? ` +${overflowCount}` : ""}`
      : `${total} resource${total === 1 ? "" : "s"} attached`;
  }, [layout.composerLanguage, liveResources, resourceConversationContextIds]);
  const planComposerModes = useMemo<UtilityComposerModeOption<PlanComposerMode>[]>(() => {
    const planComposerText = resolvePlanComposerCopy(layout.composerLanguage);
    const isZh = layout.composerLanguage === "zh-CN";
    const stageLabel =
      truncateInlineText(
        formalPlanLive
          ? activePlanStage?.title ?? resolvedCoachStage ?? resolvedCoachFocus ?? livePlanSummary
          : recoveredDisplayFacts.currentStep || livePlanTitle,
        isZh ? 22 : 48,
      ) ?? planComposerText.currentThread;
    const explainMode = planComposerText.modes.explain;
    const generateMode = planComposerText.modes.generate;
    const evidenceMode = planComposerText.modes.evidence;
    const blockerMode = planComposerText.modes.blocker;
    const modes: UtilityComposerModeOption<PlanComposerMode>[] = [
      {
        id: "explain",
        label: explainMode.label,
        header: stageLabel,
        summary: `${planComposerText.planLabel} · ${explainMode.label}`,
        hint: explainMode.hint,
        placeholder: explainMode.placeholder,
        accessibilityLabel: explainMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-explain-stage",
            label: explainMode.primaryPrompt.label,
            prompt: explainMode.primaryPrompt.prompt,
          },
          {
            id: "plan-why-now",
            label: explainMode.secondaryPrompt.label,
            prompt: explainMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "generate",
        label: generateMode.label,
        header: generateMode.header,
        summary: `${planComposerText.planLabel} · ${generateMode.label}`,
        hint: generateMode.hint,
        placeholder: generateMode.placeholder,
        accessibilityLabel: generateMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-generate",
            label: generateMode.primaryPrompt.label,
            prompt: generateMode.primaryPrompt.prompt,
          },
          {
            id: "plan-restructure",
            label: generateMode.secondaryPrompt.label,
            prompt: generateMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "evidence",
        label: evidenceMode.label,
        header: evidenceMode.header,
        summary: `${planComposerText.planLabel} · ${evidenceMode.label}`,
        hint: evidenceMode.hint,
        placeholder: evidenceMode.placeholder,
        accessibilityLabel: evidenceMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-evidence-note",
            label: evidenceMode.primaryPrompt.label,
            prompt: evidenceMode.primaryPrompt.prompt,
          },
          {
            id: "plan-adoption-gap",
            label: evidenceMode.secondaryPrompt.label,
            prompt: evidenceMode.secondaryPrompt.prompt,
          },
        ],
      },
      {
        id: "blocker",
        label: blockerMode.label,
        header: blockerMode.header,
        summary: `${planComposerText.planLabel} · ${blockerMode.label}`,
        hint: blockerMode.hint,
        placeholder: blockerMode.placeholder,
        accessibilityLabel: blockerMode.accessibilityLabel,
        prompts: [
          {
            id: "plan-shrink-next",
            label: blockerMode.primaryPrompt.label,
            prompt: blockerMode.primaryPrompt.prompt,
          },
          {
            id: "plan-blocker",
            label: blockerMode.secondaryPrompt.label,
            prompt: blockerMode.secondaryPrompt.prompt,
          },
        ],
      },
    ];
    return planIsFrozen ? modes.filter((mode) => mode.id !== "generate") : modes;
  }, [
    activePlanStage?.title,
    data.plan.stages.length,
    formalPlanLive,
    livePlanSummary,
    livePlanTitle,
    layout.composerLanguage,
    recoveredDisplayFacts.currentStep,
    resolvedCoachFocus,
    resolvedCoachStage,
  ]);
  const activePlanComposerMode =
    planComposerModes.find((mode) => mode.id === resolvedPlanComposerMode) ??
    planComposerModes[0];
  const renderTrainingComposerAccessory = () => {
    if (!composerUsesTrainingFlow) {
      return null;
    }

    if (
      trainingComposerUsesAnswerMode &&
      trainingComposerFlashMode === "choice" &&
      normalizedTrainingFlashChoices.length > 0
    ) {
      return (
        <section
          className="composer-training-panel composer-training-panel--choices-only"
          aria-label={appUiCopy(layout.composerLanguage, "训练选项")}
        >
          <div className="composer-context-strip__chips composer-context-strip__chips--training-choice">
            {normalizedTrainingFlashChoices.slice(0, 4).map((choice, index) => {
              const isActive = normalizeInlineComparisonText(choice) === normalizeInlineComparisonText(activityDraft);
              return (
                <button
                  key={`${choice}:${index}`}
                  className={`composer-context-chip ${isActive ? "is-active" : "is-enabled"}`.trim()}
                  type="button"
                  aria-pressed={isActive}
                  onClick={() => {
                    setActivityDraft(choice);
                    window.requestAnimationFrame(() => {
                      focusComposerInput();
                    });
                  }}
                >
                  <span>{String.fromCharCode(65 + index)}</span>
                  <span className="composer-context-chip__label">{choice}</span>
                </button>
              );
            })}
          </div>
        </section>
      );
    }

    return null;
  };

  const handleCancelStream = useCallback((options?: { restoreDraft?: boolean }) => {
    if (!streaming.isStreaming) {
      return;
    }
    const shouldRestoreDraft =
      options && typeof options === "object" && "restoreDraft" in options
        ? options.restoreDraft !== false
        : true;
    const resumeDraft = streamResumeDraftRef.current;
    if (shouldRestoreDraft && resumeDraft.trim() && !draft.trim()) {
      // Restore the sent text only when the learner has not already started
      // editing a new draft while the reply was in flight.
      setComposerDraft(resumeDraft);
    }
    postMessage({
      type: "session/cancelStreamMessage",
      payload: streaming.streamMessageId ? { messageId: streaming.streamMessageId } : undefined,
    });
  }, [draft, setComposerDraft, streaming.isStreaming, streaming.streamMessageId]);

  const streamWasActiveRef = useRef(streaming.isStreaming);
  // §3.7 red line 5 (stay mode): the store owns the stay-send marker and the
  // returnToSurface notice (raised inside the stream/complete reducer, so a
  // batched fixture completion still closes the loop); the App only navigates
  // or dismisses.
  const handleDockReturnViewReply = useCallback(() => {
    clearDockReturnNotice();
    setActiveView("coach");
  }, [clearDockReturnNotice, setActiveView]);
  const handleDockReturnDismiss = useCallback(() => clearDockReturnNotice(), [clearDockReturnNotice]);
  useEffect(() => {
    if (!openMenu) {
      return;
    }
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpenMenu(undefined);
      }
    };
    document.addEventListener("keydown", dismiss, true);
    return () => document.removeEventListener("keydown", dismiss, true);
  }, [openMenu, setOpenMenu]);

  useEffect(() => {
    const wasActive = streamWasActiveRef.current;
    streamWasActiveRef.current = streaming.isStreaming;
    if (wasActive && !streaming.isStreaming && streaming.completionStopReason !== "cancelled") {
      streamResumeDraftRef.current = "";
    }
  }, [streaming.completionStopReason, streaming.isStreaming]);

  const renderComposerAccessory = () => {
    if (!openMenu) {
      return null;
    }

    if (openMenu === "resources") {
      return (
        <ComposerResourcesMenu
          copy={t}
          composerLanguage={layout.composerLanguage}
          localize={appUiCopy}
          resources={data.resources}
          isBrowserPreview={isBrowserPreview}
          uploadInputRefs={{ filesInputRef: uploadFilesInputRef, folderInputRef: uploadFolderInputRef }}
          uploadLimit={RESOURCE_UPLOAD_LIMIT}
          onTriggerUpload={triggerResourceUpload}
        />
      );
    }

    if (openMenu === "model") {
      return (
        <ComposerModelMenu
          copy={t}
          providerCopy={composerProviderCopy}
          composerLanguage={layout.composerLanguage}
          localize={appUiCopy}
          localizeAlt={appUiAltCopy}
          providerConfig={data.providerConfig}
          menuItems={composerProviderMenuItems}
          filteredMenuItems={filteredComposerProviderMenuItems}
          hasSavedProfiles={composerHasSavedProfiles}
          modelQuery={composerModelQuery}
          onModelQueryChange={setComposerModelQuery}
          modelSearchRef={composerModelSearchRef}
          thinkingDescriptor={composerThinkingDescriptor}
          onThinkingChange={setComposerThinking}
          onRefreshModels={refreshComposerProviderModels}
          onSwitchModel={switchComposerProviderModel}
          onSwitchProviderModel={switchComposerProviderModelForProfile}
          initialOptionLimit={COMPOSER_MODEL_PICKER_INITIAL_OPTION_LIMIT}
        />
      );
    }

    return (
      <ComposerContextMenu
        copy={t}
        contextSummary={sendContextShortSummary(data, layout, t) ?? ""}
        relatedFilesCount={data.liveContext.relatedFiles.length}
        includeRelatedFiles={layout.includeRelatedFiles}
        followCurrentFile={layout.followCurrentFile}
        contextDetail={layout.contextDetail}
        onToggleRelatedFiles={() => setIncludeRelatedFiles(!layout.includeRelatedFiles)}
        onToggleFollowCurrentFile={() => setFollowCurrentFile(!layout.followCurrentFile)}
        onContextDetailChange={setContextDetail}
      />
    );
  };

  const unifiedCommandSuggestions = unifiedComposerCommands(composerUsesTrainingFlow ? activityDraft : draft, layout.composerLanguage);
  const selectUnifiedCommand = (command: string) => {
    const value = command + " ";
    if (composerUsesTrainingFlow) setActivityDraft(value);
    else setComposerDraft(value, composerDraftScope);
    setDismissedComposerDeck("command");
    requestCoachComposerFocus();
  };
  const renderCommandDeck = () => {
    if (
      dismissedComposerDeck === "command" ||
      !((composerUsesTrainingFlow ? activityDraft : draft).trim().startsWith("/")) ||
      (unifiedCommandSuggestions.length === 0 && (composerUsesTrainingFlow || matchingLocalCommands.length === 0))
    ) {
      return null;
    }

    return (
      <div ref={composerDeckRef} className="command-deck" role="list" aria-label={t.slashCommands}>
        <div className="command-deck__header">
          <strong>{t.slashCommands}</strong>
          <span className="command-deck__hint">
            {appUiCopy(layout.composerLanguage, "Enter 执行，Tab 补全。")}
          </span>
        </div>
        <div className="command-deck__list">
          {unifiedCommandSuggestions.map((command) => (
            <button key={command} type="button" className="command-deck__item"
              onClick={() => selectUnifiedCommand(command)}>
              <span className="command-deck__command">{command}</span>
            </button>
          ))}
          {(composerUsesTrainingFlow ? [] : matchingLocalCommands).map((command) => (
            <button
              key={command.command}
              className={`command-deck__item ${
                matchingLocalCommands[selectedCommandIndex]?.command === command.command ? "is-active" : ""
              }`}
              type="button"
              aria-label={`${command.command}: ${command.title}`}
              title={[command.command, command.title, command.description].filter(Boolean).join(" · ")}
              onMouseEnter={() => {
                const index = matchingLocalCommands.findIndex((item) => item.command === command.command);
                if (index >= 0) {
                  setSelectedCommandIndex(index);
                }
              }}
              onClick={() => {
                runComposerCommand(command);
              }}
            >
              <span className="command-deck__command">{command.command}</span>
              <span className="command-deck__body">
                <strong>{command.title}</strong>
                <span>{command.description}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  };

  const renderSkillDeck = () => {
    if (dismissedComposerDeck === "skill" || !activeSkillDraft.startsWith("$")) return null;
    const draftTriggerToken = trainerSkillTriggerToken(activeSkillDraft) ?? "$";
    const creatableTrigger = draftTriggerToken.length > 1 && !availableSkillCatalog.some((skill) => skill.trigger.toLowerCase() === draftTriggerToken.toLowerCase()) ? draftTriggerToken : undefined;
    const customSkillIds = new Set(customSkills.map((skill) => skill.id));
    return <CommandPalette containerRef={composerDeckRef} label={appUiCopy(layout.composerLanguage, "技能")}
      groupLabel={appUiCopy(layout.composerLanguage, "技能")}
      empty={appUiCopy(layout.composerLanguage, "没有匹配到 skill。继续输入，或者直接当作普通消息发送。")}
      moreLabel={appUiCopy(layout.composerLanguage, "↓ 还有 {n} 条")}
      selectedIndex={selectedCommandIndex} onHighlight={setSelectedCommandIndex}
      entries={matchingLocalSkills.map((skill) => ({ id: skill.id, trigger: skill.trigger,
        title: resolveTrainerSkillText(skill.title, layout.composerLanguage),
        detail: resolveTrainerSkillText(skill.detail, layout.composerLanguage),
        icon: <SkillCubeIcon size={16} />,
        tag: customSkillIds.has(skill.id) ? appUiCopy(layout.composerLanguage, "个人") : undefined,
        onSelect: () => selectSkillSuggestion(skill) }))}
      footer={<><button type="button" className="template-back" onClick={() => openSkillSettings(creatableTrigger)}>{creatableTrigger ? appUiCopy(layout.composerLanguage, "创建技能 {v}").replace("{v}", creatableTrigger) : appUiCopy(layout.composerLanguage, "管理技能")}</button></>} />;
  };

  const renderSuggestedActions = () => {
    if (latestCoachArtifact && !coachTrainingInlineAction) {
      return null;
    }

    if (!coachTrainingInlineAction && liveSuggestedActions.length === 0) {
      return null;
    }

    const visibleActions = liveSuggestedActions;
    return (
      <div className="suggested-inline">
        {leftoverSuggestedActionNotLive ? (
          <p
            className="coach-leftover-note"
            data-coach-leftover-note="true"
            role="status"
            aria-live="polite"
          >
            {t.leftoverNotLiveHint}
          </p>
        ) : null}
        <div className="suggested-actions">
          {coachTrainingInlineAction ? (
            <button
              className="button button--ghost"
              type="button"
              title={coachTrainingInlineAction.title}
              onClick={() => setActiveView("training")}
            >
              {coachTrainingInlineAction.label}
            </button>
          ) : (
            visibleActions.slice(0, 1).map((item) => (
              <button
                key={item.id}
                className="button button--ghost"
                type="button"
                title={item.rationale ?? item.focusArea ?? item.prompt ?? item.label}
                onClick={() =>
                  handleSuggestedAction(item.action, {
                    prompt: item.prompt,
                    focusArea: item.focusArea,
                  })
                }
              >
                {appUiCopy(layout.composerLanguage, "接着做：{v}").replace("{v}", item.label)}
              </button>
            ))
          )}
        </div>
      </div>
    );
  };

  return {
    attemptLifecycle,
    handleHintReveal,
    handleVerifyTrainingFromIde,
    handleSubmitTrainingEvidence,
    handleResumeTrainingInCoach,
    selectedResourceNavigationLabel,
    dockStageProgressLabel,
    dockAnchorControl,
    activePlanComposerMode,
    handleCancelStream,
    renderComposerAccessory,
    unifiedCommandSuggestions,
    selectUnifiedCommand,
    renderCommandDeck,
    renderSkillDeck,
  };
}
