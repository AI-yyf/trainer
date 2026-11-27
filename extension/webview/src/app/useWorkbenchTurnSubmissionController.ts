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

export function useWorkbenchTurnSenderAndHistory(ctx: WorkbenchCtxAfterK2) {
  const {
    resolvedPlanComposerMode,
    data,
    layout,
    hasReceivedHostState,
    setActiveView,
    setComposerDraft,
    setOperationMessage,
    trainingPersistencePending,
    trainerWorkspaceAdmission,
    workspaceSessionBlocked,
    workspaceSessionBlockMessage,
    openWorkspaceAdmission,
    clearOptimisticTurns,
    appendOptimisticTurn,
    previewSessionId,
    setPreviewSessionId,
    setLastTurnView,
    planComposerMode,
    streaming,
    setOpenMenu,
    isBrowserPreview,
    activeView,
    streamResumeDraftRef,
    sendRecoveredPlanResumeRef,
    goalMode,
    goalText,
    composerSessionKey,
    handleSubmitRef,
    sendTurnRef,
    coachComposerFocusRequestRef,
    requestCoachComposerFocus,
    applySessionListRef,
    applyHostMessage,
    showComposerShell,
    draft,
    composerDraftScope,
    composerAttachments,
    setComposerAttachments,
    normalizedDraft,
    providerCanCoachNow,
    providerSupportsFormalPlanTools,
    providerToolsExplicitlyUnsupported,
    agentToolsCapabilityMessage,
    providerBlockReason,
    blockedComposerGuidance,
    planRuntimeStatus,
    leftoverSuggestedActionNotLive,
    openPlanComposerMode,
    composerResourceIdsFor,
    composerUsesTrainingFlow,
    capabilitySendBlocked,
  } = ctx;
  const sendTurn = ({
    text,
    intent,
    intentSource = "explicit",
    goals,
    stream = true,
    activeView: activeViewOverride,
    includeCurrentFile,
    includeDiagnostics,
    contextDetail,
    formalPlanMutation,
    planComposerMode,
    planRuntimeRecovery,
    resourceComposerIntent,
    resourceIds: resourceIdsOverride,
    attachments,
    goalMode: turnGoalMode,
    goalText: turnGoalText,
  }: {
    text: string;
    intent: "coach" | "next_task" | "review" | "plan" | "task";
    intentSource?: "explicit" | "inferred" | "none";
    goals?: string[];
    stream?: boolean;
    activeView?: ActiveWorkbenchView;
    includeCurrentFile?: boolean;
    includeDiagnostics?: boolean;
    contextDetail?: "focused" | "balanced" | "full";
    formalPlanMutation?: boolean;
    planComposerMode?: "explain" | "generate" | "evidence" | "blocker";
    planRuntimeRecovery?: RecoveredPlanResumeTurn;
    resourceComposerIntent?: ResourceComposerIntent;
    resourceIds?: string[];
    attachments?: MessageAttachment[];
    goalMode?: boolean;
    goalText?: string;
  }) => {
    if (workspaceSessionBlocked && !canConverseBeforeAdmission(trainerWorkspaceAdmission?.status, {
      text, intent, formalPlanMutation, goalMode: turnGoalMode,
      activeView: activeViewOverride ?? activeView, resourceComposerIntent,
    })) {
      openWorkspaceAdmission();
      setOperationMessage({
        tone: "info",
        message: workspaceSessionBlockMessage ?? blockedComposerGuidance,
      });
      return;
    }

    if (!providerCanCoachNow || providerBlockReason || capabilitySendBlocked) {
      useWorkbenchState.getState().requestSettingsCategory("connection");
      setActiveView("settings");
      setOperationMessage({
        tone: "info",
        message: blockedComposerGuidance,
      });
      return;
    }

    const turnActiveView = activeViewOverride ?? activeView;
    const recoveredResume =
      planRuntimeRecovery?.recovered === true && planRuntimeRecovery.formalPlanMutation === false
        ? planRuntimeRecovery
        : undefined;
    const resolvedFormalPlanMutation = recoveredResume ? false : formalPlanMutation;
    // The four workbench views share one real streaming conversation surface.
    // View context and selected resources ground ordinary discussion, while
    // explicit formal-plan mutations need executable tools.
    const requiresVerifiedAgentTools = Boolean(resolvedFormalPlanMutation);
    const laneNeedsVerifiedTools =
      turnActiveView === "resources" ||
      turnActiveView === "plan" ||
      intent === "plan";
    if (requiresVerifiedAgentTools && !providerSupportsFormalPlanTools) {
      setOperationMessage({
        tone: "info",
        message: agentToolsCapabilityMessage,
      });
      return;
    }
    const resourceIds = resourceComposerIntent?.resourceIds ?? resourceIdsOverride ?? composerResourceIdsFor(turnActiveView);
    const resolvedResourceComposerIntent = resourceComposerIntent
      ? {
          ...resourceComposerIntent,
          resourceIds: resourceIds.slice(0, RESOURCE_COMPOSER_MAX_IDS),
        }
      : undefined;
    if (
      resourceComposerIntent &&
      resourceIds.length > RESOURCE_COMPOSER_MAX_IDS
    ) {
      setOperationMessage({
        tone: "info",
        message:
          appUiCopy(layout.composerLanguage, "资源上下文最多带入 12 份，已使用前 12 份。"),
      });
    }
    const selectionRequested = Boolean(data.liveContext.selectionRange) && /选区|选中内容|这段代码|\bselection\b|highlighted/i.test(text);
    const resolvedIncludeCurrentFile =
      includeCurrentFile ??
      (layout.includeCurrentFile && (shouldAttachCurrentFile(text, intent) || /@current-file\b/i.test(text) ||
        (layout.includeSelection && selectionRequested)));
    const effectiveStream = stream;
    const payload = {
      text,
      intent,
      intentSource,
      goals,
      resourceIds,
      resourceComposerIntent: resolvedResourceComposerIntent,
      includeCurrentFile: resolvedIncludeCurrentFile,
      includeSelection: resolvedIncludeCurrentFile && layout.includeSelection && selectionRequested,
      includeDiagnostics: includeDiagnostics ?? layout.includeDiagnostics,
      includeRelatedFiles: layout.includeRelatedFiles &&
        ((contextDetail ?? layout.contextDetail) === "full" || /相关文件|related files|surrounding files/i.test(text)),
      contextDetail: contextDetail ?? layout.contextDetail,
      responseLanguage: layout.composerLanguage,
      answerMode: layout.composerAnswerMode,
      goalMode: turnGoalMode === true,
      goalText:
        turnGoalMode === true
          ? (turnGoalText?.trim() || goalText.trim() || normalizedDraft.trim()).slice(0, 240) || undefined
          : undefined,
      teachingStyle: layout.teachingStyle,
      coachDefaults: layout.coachDefaults,
      activeView: turnActiveView,
      formalPlanMutation: resolvedFormalPlanMutation,
      planComposerMode:
        turnActiveView === "plan" ? planComposerMode ?? resolvedPlanComposerMode : undefined,
      planRuntimeRecovery: recoveredResume,
      attachments: attachments?.length ? attachments : undefined,
      useAgentLoop:
        resolvedResourceComposerIntent?.mode === "analyze" || providerToolsExplicitlyUnsupported
          ? false
          : requiresVerifiedAgentTools
            ? true
            : undefined,
      requestId: `coach-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    };
    setLastTurnView(turnActiveView);
    streamResumeDraftRef.current = text;
    // Local echo: the user's turn shows up instantly; the server-confirmed
    // copy lands at the same list position when the snapshot merges.
    // Every reply belongs to the one conversation: the surface only decides
    // where the learner reads it.
    appendOptimisticTurn(
      text,
      "coach",
      (attachments ?? [])
        .filter(
          (item) =>
            item.kind === "image" &&
            typeof item.dataBase64 === "string" &&
            item.dataBase64.trim().length > 0 &&
            /^image\/(?:png|jpeg|jpg|webp|gif)$/i.test(item.mimeType),
        )
        .slice(0, 4)
        .map((item) => ({
          id: item.id,
          ...(item.name ? { name: item.name } : {}),
          mimeType: item.mimeType,
          dataUrl: `data:${item.mimeType};base64,${item.dataBase64}`,
        })),
    );
    useWorkbenchState.getState().beginOptimisticStream();

    if (isBrowserPreview) {
      if (stream) {
        void requireBrowserPreviewAdapter().then((browserPreview) =>
          browserPreview.streamBrowserPreviewMessage(payload, previewSessionId ?? "", {
          onStart: (message) => applyHostMessage(message),
          onChunk: (message) => applyHostMessage(message),
          onComplete: (message, nextSessionId) => {
            setPreviewSessionId(nextSessionId);
            applyHostMessage(message);
          },
          onError: (message) => applyHostMessage(message),
          onCancelled: (message) => applyHostMessage(message),
          }),
        ).catch(() => {
          clearOptimisticTurns();
          useWorkbenchState.getState().resetStream();
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("send", layout.composerLanguage),
          });
        });
        return;
      }

      void requireBrowserPreviewAdapter()
        .then((browserPreview) => browserPreview.sendBrowserPreviewMessage(payload, previewSessionId))
        .then(({ sessionId, message }) => {
          setPreviewSessionId(sessionId);
          applyHostMessage(message);
          useWorkbenchState.getState().endStream();
        })
        .catch(() => {
          clearOptimisticTurns();
          useWorkbenchState.getState().resetStream();
          setOperationMessage({
            tone: "error",
            message: recoverableFailureMessage("send", layout.composerLanguage),
          });
        });
      return;
    }

    postMessage(
      effectiveStream
        ? {
            type: "session/sendStreamMessage",
            payload: {
              ...payload,
              stream: true,
            },
          }
        : {
            type: "session/sendMessage",
            payload,
          },
    );
  };

  sendTurnRef.current = sendTurn;

  sendRecoveredPlanResumeRef.current = (action) => {
    const resume = buildRecoveredPlanResumeTurn(action, {
      recovered: planRuntimeStatus?.recovered === true,
      currentStep: planRuntimeStatus?.currentStep,
      currentStepId: planRuntimeStatus?.currentStageId,
      blockedReason: planRuntimeStatus?.blockedReason,
      whyNow: planRuntimeStatus?.whyNow,
    });
    if (!resume) {
      openPlanComposerMode(action === "clear_blocker" ? "blocker" : "explain");
      return;
    }
    // The plan resume is a Chat turn: the plan card lives in the learning
    // drawer, so the answer belongs to the one conversation.
    setActiveView("coach");
    requestCoachComposerFocus();
    sendTurn({
      text: recoveredPlanResumeMessage(resume, layout.composerLanguage),
      intent: "plan",
      activeView: "coach",
      stream: true,
      formalPlanMutation: false,
      planComposerMode: action === "clear_blocker" ? "blocker" : "explain",
      planRuntimeRecovery: resume,
    });
  };

  const sendTrainingFeedback = (input: TrainingFeedbackPromptInput) => {
    sendTurn({
      text: buildTrainingFeedbackPrompt(layout.composerLanguage, input),
      intent: "coach",
      activeView: "training",
      stream: true,
      includeCurrentFile: false,
      includeDiagnostics: false,
      contextDetail: "focused",
    });
  };

  const handleSuggestedAction = (
    action: SuggestedAction["action"],
    options?: Pick<SuggestedAction, "prompt" | "focusArea">,
  ) => {
    const prompt = options?.prompt;
    const focusArea = options?.focusArea;
    const reviewOnlyDraft =
      prompt ??
      (appUiCopy(layout.composerLanguage, "先继续当前复习项，不要新开正式任务。"));
    // Suggested actions prefill the composer draft; pressing send stays with
    // the learner. Pure navigation actions keep their navigate-only behavior.
    if (action === "hint") {
      setActiveView("coach");
      setComposerDraft(
        prompt ??
          (appUiCopy(layout.composerLanguage, "请继续给我一个更小、更具体的下一步。")),
      );
      requestCoachComposerFocus();
      return;
    }

    if (action === "plan") {
      setActiveView("plan");
      setComposerDraft(
        prompt ??
          (appUiCopy(layout.composerLanguage, "请先和我讨论这条计划的阶段、证据和验证方式；在我明确生成前不要改正式计划。")),
      );
      return;
    }

    if (action === "next_task") {
      setActiveView("coach");
      if (leftoverSuggestedActionNotLive) {
        setComposerDraft(reviewOnlyDraft);
        requestCoachComposerFocus();
        return;
      }
      setComposerDraft(prompt ?? defaultPromptText("next_task", layout.composerLanguage, focusArea));
      requestCoachComposerFocus();
      return;
    }

    if (action === "review" || action === "retry_review") {
      setActiveView("coach");
      setComposerDraft(prompt ?? defaultPromptText("review", layout.composerLanguage, focusArea));
      requestCoachComposerFocus();
      return;
    }

    setActiveView("coach");
    if (leftoverSuggestedActionNotLive) {
      setComposerDraft(reviewOnlyDraft);
      requestCoachComposerFocus();
      return;
    }
    setComposerDraft(prompt ?? defaultPromptText("task", layout.composerLanguage, focusArea));
    requestCoachComposerFocus();
  };

  const { preview: composerActionPreview, setPreview: setComposerActionPreview,
    requestPreview: requestComposerActionPreview, confirmPreview: confirmComposerActionPreview } = useComposerActionPreview();
  const [resourceVersionCheck, setResourceVersionCheck] = useState<{
    scope: string; total: number; phase: "checking" | "done" | "interrupted";
    items: (ResourceVersionCheckResult & { title: string })[];
  }>();
  const [learningFileVerification, setLearningFileVerification] = useState<{
    scope: string; report: BootstrapData["evaluation"]; passed: boolean;
  }>();
  const resourceVersionCheckRequest = useRef<AbortController>();
  useEffect(() => () => resourceVersionCheckRequest.current?.abort(), [composerSessionKey]);

  const { items: queuedFollowUps, setItems: setQueuedFollowUps } = useComposerQueue(composerSessionKey,
    streaming.isStreaming || isOperationReliabilityInFlight(streaming.reliabilityPhase) ||
    trainingPersistencePending || Boolean(composerActionPreview), handleSubmitRef);
  const queueCurrentComposerDraft = useCallback(() => {
    if (composerUsesTrainingFlow) {
      return;
    }
    const textToQueue = draft.trim();
    const attachmentsToQueue = composerAttachments;
    if (!textToQueue && attachmentsToQueue.length === 0) {
      return;
    }
    setQueuedFollowUps((current) => [
      ...current,
      {
        id: `queued-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        text: textToQueue,
        attachments: attachmentsToQueue,
      },
    ]);
    setComposerDraft("", composerDraftScope);
    setComposerAttachments([]);
  }, [composerAttachments, composerDraftScope, composerUsesTrainingFlow, draft, setComposerDraft]);
  const linkingSourceInFlight = useRef(false);
  // Re-arm the bootstrap request guard only on the false -> true transition of
  // host-state reception. In browser preview `hasReceivedHostState` starts
  // true, so an unconditional reset here disarmed the guard on mount and every
  // subsequent `requestBootstrapOnce` call re-posted `request/bootstrap`,
  // driving a continuous POST /memory/settings + GET /memory/summary loop.
  const hostStateReceivedOnceRef = useRef(hasReceivedHostState);
  useEffect(() => {
    if (!hasReceivedHostState) {
      return;
    }
    if (hostStateReceivedOnceRef.current) {
      return;
    }
    hostStateReceivedOnceRef.current = true;
    resetBootstrapRequestSent();
  }, [hasReceivedHostState]);

  useEffect(() => {
    if (!showComposerShell || !coachComposerFocusRequestRef.current) {
      return;
    }
    coachComposerFocusRequestRef.current = false;
    const handle = window.requestAnimationFrame(() => {
      focusComposerInput();
    });

    return () => window.cancelAnimationFrame(handle);
  }, [activeView, hasReceivedHostState, showComposerShell]);

  const runComposerCommand = (command: LocalCommandSuggestion) => {
    command.run();
    setComposerDraft("");
    setOpenMenu(undefined);
    window.requestAnimationFrame(() => {
      focusComposerInput();
    });
  };

  const handleNewChatStart = useCallback(() => {
    clearOptimisticTurns();
    useWorkbenchState.getState().resetStream();
  }, [clearOptimisticTurns]);

  const {
    coachSessions,
    coachSessionsStatus,
    coachSessionsMessage,
    applySessionList,
    requestCoachSessions,
    toggleComposerHistoryMenu,
    activateCoachSession,
    startNewCoachChat,
  } = useCoachHistory({
    isBrowserPreview,
    composerLanguage: layout.composerLanguage,
    previewSessionId,
    conversationCount: data.conversation.length,
    cacheScope: data.workspaceName,
    setOpenMenu,
    setOperationMessage,
    onNewChatStart: handleNewChatStart,
  });
  applySessionListRef.current = (payload: unknown) => applySessionList(payload);
  return {
    coachSessions,
    coachSessionsStatus,
    coachSessionsMessage,
    requestCoachSessions,
    toggleComposerHistoryMenu,
    activateCoachSession,
    startNewCoachChat,
    sendTurn,
    sendTrainingFeedback,
    handleSuggestedAction,
    resourceVersionCheck,
    setResourceVersionCheck,
    setLearningFileVerification,
    resourceVersionCheckRequest,
    composerActionPreview,
    setComposerActionPreview,
    requestComposerActionPreview,
    confirmComposerActionPreview,
    queuedFollowUps,
    setQueuedFollowUps,
    queueCurrentComposerDraft,
    linkingSourceInFlight,
    runComposerCommand,
  };
}

export function createWorkbenchSubmitHandler(ctx: WorkbenchCtxAfterE7) {
  const {
    composerActionPreview,
    setComposerActionPreview,
    requestComposerActionPreview,
    data,
    layout,
    syncCursor,
    setActiveView,
    setComposerDraft,
    setOperationMessage,
    trainingComposerFlashMode,
    trainingPersistencePending,
    requestTrainingPersistence,
    pendingPostAdmissionSendRef,
    trainerWorkspaceAdmission,
    canCaptureGoalBeforeWorkspaceSetup,
    canChatBeforeProjectAdmission,
    workspaceSessionBlocked,
    workspaceSessionBlockMessage,
    openWorkspaceAdmission,
    previewSessionId,
    planComposerMode,
    coachPlanContext,
    setCoachPlanContext,
    requestResourceMutation,
    requestResourceTrainingHandoff,
    refreshPreviewResources,
    beginResourceOperationStatusWait,
    captureResourceIntoLibrary,
    organizeLibraryResource,
    streaming,
    setDismissedComposerDeck,
    isBrowserPreview,
    activeView,
    t,
    goalMode,
    goalText,
    goalPaused,
    startGoal,
    composerSessionKey,
    goalDraftPending,
    handleSubmitRef,
    pendingLivePlanTaskMintRef,
    requestCoachComposerFocus,
    browserPreviewFixture,
    handleTrainingCardStatusTransition,
    draft,
    composerDraftScope,
    browserComposerSource,
    attachmentScope,
    composerAttachments,
    setComposerAttachments,
    setResourcesViewSearchQuery,
    normalizedDraft,
    providerImageInputState,
    capabilityVerdict,
    providerCanCoachNow,
    providerCanMutateFormalPlan,
    formalPlanCapabilityMessage,
    providerBlockReason,
    blockedComposerGuidance,
    activePlanStage,
    planRuntimeStatus,
    recoveredRuntime,
    leftoverTrainingHandoffChromeNotLive,
    recoveredDisplayFacts,
    formalPlanLive,
    livePlanFrozen,
    liveTrainingTitle,
    liveEvidenceQueue,
    liveResources,
    trainingState,
    selectedTrainingCardCandidate,
    reviewArtifactForeground,
    trainingCardType,
    activeTrainingCardId,
    activityDraftKey,
    activityDraft,
    setComposerHintLevels,
    composerHintLevel,
    activityAttachments,
    setActivityAttachments,
    setActivityDraft,
    visibleTrainingCardTitle,
    trainingPracticeVerificationMode,
    trainingFilesToTouch,
    activeComposerResourceIds,
    authoritativeVerifyItems,
    trainingHandoffReturnRequired,
    trainingComposerPhase,
    activeTheoryDrill,
    flashQuestion,
    trainingFlashPrompt,
    trainingProblemStatement,
    normalizedTrainingFlashChoices,
    trainingComposerSelectedVerifyItem,
    hasTrainingCard,
    trainingComposerUsesAnswerMode,
    trainingComposerPracticeInputMode,
    trainingComposerReflectMode,
    trainingComposerReturnMode,
    inlinePracticeAwaitingComposerSubmission,
    localCommandMap,
    trainerSkillContext,
    availableSkillCatalog,
    composerUsesTrainingFlow,
    analyzeComposerDraft,
    sendTurn,
    sendTrainingFeedback,
    resourceVersionCheck,
    setResourceVersionCheck,
    setLearningFileVerification,
    resourceVersionCheckRequest,
    queueCurrentComposerDraft,
    linkingSourceInFlight,
    handleHintReveal,
    handleSubmitTrainingEvidence,
    selectedResourceNavigationLabel,
    dockStageProgressLabel,
    dockAnchorControl,
    allowEmptyTrainingReturnSubmission,
    handleVerifyCurrentFileFromCard,
    trainingHintLadderForCard,
    runLearningPrimaryAction,
  } = ctx;
  const handleSubmit = async (
    confirmedActionKey?: string,
    overrideSubmission?: { text: string; attachments?: MessageAttachment[] },
  ) => {
    if (!overrideSubmission && (streaming.isStreaming || isOperationReliabilityInFlight(streaming.reliabilityPhase))) {
      if (!trainingPersistencePending && !composerUsesTrainingFlow) {
        queueCurrentComposerDraft();
      }
      return;
    }
    if (trainingPersistencePending) return;
    const rawText = overrideSubmission
      ? overrideSubmission.text
      : composerUsesTrainingFlow
        ? activityDraft
        : draft;
    const normalizedDraft = rawText.trim();
    const submissionAnalysis = analyzeComposerDraft(normalizedDraft);
    const submissionAttachments = overrideSubmission
      ? (overrideSubmission.attachments ?? [])
      : composerUsesTrainingFlow
        ? activityAttachments
        : composerAttachments;
    const browserPrefill = browserComposerSource?.prefill;
    const instruction = browserPrefill ? normalizedDraft.replace(browserPrefill, "").trim() : normalizedDraft;
    const startsGoal = activeView === "coach" && goalDraftPending && Boolean(instruction) &&
      !/^[/$]/u.test(instruction);
    const unified = startsGoal
      ? { kind: "message" as const }
      : resolveUnifiedComposerIntent(instruction, activeView, {
          inlineTrainingActive: inlinePracticeAwaitingComposerSubmission,
        });
    const resourceAnalysis = unified.kind === "resource-turn" && unified.mode === "analyze";
    const practiceAfterLink = unified.kind === "resource-link" && unified.practiceAfterLink === true;
    if (confirmedActionKey && (composerActionPreview?.scope !== attachmentScope || composerActionPreview.text !== normalizedDraft)) return;
    const clearSubmission = () => {
      if (overrideSubmission) {
        return;
      }
      const { layout: current } = useWorkbenchState.getState();
      if (composerUsesTrainingFlow) {
        if ((current.activityDrafts?.[activityDraftKey] ?? "") === activityDraft) setActivityDraft("");
        setActivityAttachments([]);
      } else {
        const currentDraft = current.composerDraftScope === composerDraftScope
          ? current.composerDraft : current.composerDrafts?.[composerDraftScope];
        if ((currentDraft ?? "") === draft) setComposerDraft("", composerDraftScope);
        setComposerAttachments([]);
      }
    };
    const hasImageAttachments = submissionAttachments.length > 0;
    const allowEmptyTrainingReturnSubmission =
      composerUsesTrainingFlow &&
      trainingComposerReturnMode &&
      trainingHandoffReturnRequired &&
      Boolean(trainingState?.selectedCardId);
    if (!normalizedDraft && !hasImageAttachments && !allowEmptyTrainingReturnSubmission) {
      return;
    }

    const unboundConversation = unified.kind === "message" && !startsGoal &&
      canConverseBeforeAdmission(trainerWorkspaceAdmission?.status, {
        text: normalizedDraft, intent: submissionAnalysis.intent, activeView,
        goalMode: goalMode || goalDraftPending,
      });
    if (canCaptureGoalBeforeWorkspaceSetup && normalizedDraft && !unboundConversation) {
      openWorkspaceAdmission();
      setOperationMessage({
        tone: "info",
        message: t.workspaceAdmissionGoalSaved,
      });
      return;
    }

    if (canChatBeforeProjectAdmission && normalizedDraft && !unboundConversation) {
      // Zero-friction cold start: gently bind this project inside <LibraryRoot>
      // (zero writes inside the code repo) while preserving the learner's draft,
      // and auto-send the queued first message as soon as admission finishes.
      const hasResolvedProjectPath = Boolean(trainerWorkspaceAdmission?.projectPath?.trim());
      pendingPostAdmissionSendRef.current = {
        text: normalizedDraft,
        attachments: submissionAttachments,
        draftScope: composerDraftScope,
        goalMode: Boolean(goalMode || goalDraftPending),
        goalText: goalMode || goalDraftPending ? goalText : undefined,
        activeView: activeView === "resources" ? "resources" : "coach",
      };
      if (!isBrowserPreview) {
        postMessage({
          type: "command/execute",
          payload: hasResolvedProjectPath
            ? {
                commandId: trainerCommands.adoptWorkspaceProject,
                payload: { adoptionMode: "managed", responseLanguage: layout.composerLanguage },
              }
            : {
                commandId: trainerCommands.chooseWorkspaceProject,
              },
        });
      }
      setOperationMessage({
        tone: "info",
        message: appUiCopy(
          layout.composerLanguage,
          hasResolvedProjectPath
            ? "正在将当前项目关联到学习文件夹，完成后将自动发送。"
            : "请先选择要关联的项目文件夹，完成后将自动发送。",
        ),
      });
      return;
    }

    if (workspaceSessionBlocked && !unboundConversation) {
      openWorkspaceAdmission();
      setOperationMessage({
        tone: "info",
        message: workspaceSessionBlockMessage ?? blockedComposerGuidance,
      });
      return;
    }

    if (allowEmptyTrainingReturnSubmission && !normalizedDraft && !hasImageAttachments) {
      try {
        await handleSubmitTrainingEvidence("");
      } catch {
        setOperationMessage({
          tone: "error",
          message: trainingPersistenceFailureMessage(layout.composerLanguage),
        });
      }
      return;
    }

    const localCommandDefinition = hasImageAttachments
      ? undefined
      : findSidebarControlCommand(normalizedDraft);
    const localCommand = localCommandDefinition
      ? localCommandMap.get(localCommandDefinition.id)
      : undefined;

    if (localCommand) {
      localCommand.run();
      clearSubmission();
      return;
    }

    const submittedSkillTrigger = normalizedDraft.split(/\s+/, 1)[0] ?? "";
    const submittedSkill =
      submittedSkillTrigger.startsWith("$")
        ? availableSkillCatalog.find((skill) =>
            skill.trigger.toLowerCase() === submittedSkillTrigger.toLowerCase() &&
            (!skill.when || skill.when(trainerSkillContext)),
          )
        : undefined;

    if (submittedSkill) {
      const targetView = skillSectionTargetView(submittedSkill.section);
      const followupText = normalizedDraft.slice(submittedSkillTrigger.length).trim();
      const skillPrompt =
        resolveTrainerSkillText(submittedSkill.prompt, layout.composerLanguage) ||
        resolveTrainerSkillText(submittedSkill.detail, layout.composerLanguage) ||
        resolveTrainerSkillText(submittedSkill.title, layout.composerLanguage);
      const formalPlanSkill = submittedSkill.commandId === trainerCommands.generatePlan;

      if (formalPlanSkill && !providerCanMutateFormalPlan) {
        setOperationMessage({
          tone: "info",
          message: formalPlanCapabilityMessage,
        });
        return;
      }

      if (submittedSkill.commandId === trainerCommands.sendStreamMessage) {
        if (!providerCanCoachNow || providerBlockReason) {
          setOperationMessage({
            tone: "info",
            message: blockedComposerGuidance,
          });
          return;
        }

        const skillMessageText = [skillPrompt, followupText].filter(Boolean).join("\n\n");

        setActiveView(targetView);
        sendTurn({
          text: skillMessageText,
          intent: "coach",
          activeView: targetView,
          stream: true,
          attachments: submissionAttachments,
        });
      } else if (followupText || hasImageAttachments) {
        if (!providerCanCoachNow || providerBlockReason) {
          setOperationMessage({
            tone: "info",
            message: blockedComposerGuidance,
          });
          return;
        }

        const intent =
          submittedSkill.commandId === trainerCommands.evaluateCurrentFile ||
          submittedSkill.commandId === trainerCommands.evaluateSelection
            ? "review"
            : submittedSkill.commandId === trainerCommands.generatePlan
              ? "plan"
              : submittedSkill.commandId === trainerCommands.nextTask
                ? "next_task"
                : submittedSkill.commandId === trainerCommands.taskSpecify ||
                    submittedSkill.commandId === trainerCommands.trainingGenerateCard ||
                    submittedSkill.section === "Training"
                  ? "task"
                  : submittedSkill.section === "Plan"
                    ? "plan"
                    : "coach";
        const skillMessageText = [skillPrompt, followupText].filter(Boolean).join("\n\n");

        setActiveView(targetView);
        sendTurn({
          text: skillMessageText,
          intent,
          activeView: targetView,
          stream: true,
          formalPlanMutation: formalPlanSkill,
          attachments: submissionAttachments,
        });
      } else {
        const isLivePlanTaskMint =
          submittedSkill.commandId === trainerCommands.nextTask ||
          submittedSkill.commandId === trainerCommands.taskSpecify;
        const isGenerateCard = submittedSkill.commandId === trainerCommands.trainingGenerateCard;
        const isPlanUpdate = submittedSkill.commandId === trainerCommands.updatePlan;
        setActiveView(targetView);
        if (isLivePlanTaskMint || isGenerateCard || isPlanUpdate) {
          pendingLivePlanTaskMintRef.current = { commandId: submittedSkill.commandId, scope: composerDraftScope, draft: rawText };
          setOperationMessage({
            tone: "info",
            message: isGenerateCard
              ? trainingGenerateCardPendingMessage(layout.composerLanguage)
              : isPlanUpdate
                ? livePlanUpdatePendingMessage(layout.composerLanguage)
                : livePlanTaskMintPendingMessage(layout.composerLanguage),
          });
        }
        postMessage({
          type: "command/execute",
          payload: {
            commandId: submittedSkill.commandId,
            payload: submittedSkill.payload,
          },
        });
        if (isLivePlanTaskMint || isGenerateCard || isPlanUpdate) {
          // Keep draft until authoritative success/failure ack (intent→pending→ack).
          return;
        }
      }

      setComposerDraft("");
      setComposerAttachments([]);
      setDismissedComposerDeck(undefined);
      return;
    }

    const submissionScope = useWorkbenchState.getState().syncCursor;
    const inOriginalScope = (view: ActiveWorkbenchView) => {
      const current = useWorkbenchState.getState();
      return current.layout.activeView === view && current.syncCursor.generation === submissionScope.generation &&
        current.syncCursor.workspaceId === submissionScope.workspaceId && current.syncCursor.sessionId === submissionScope.sessionId;
    };
    const startLinkedPractice = async (
      source: { resourceId: string; versionId?: string; contentHash?: string }, stageId: string, planId: string,
    ) => {
      const currentPlan = useWorkbenchState.getState().data.plan;
      const step = recoveredDisplayFacts.currentStep?.trim();
      const { resourceId, versionId, contentHash } = source;
      const result = versionId && contentHash && step && currentPlan.id === planId &&
        currentPlan.currentStageId === stageId && !currentPlan.frozen && currentPlan.revision !== undefined
        ? await requestResourceTrainingHandoff(resourceId, "practice", instruction, {
          expectedResourceVersion: { versionId, contentHash },
          planBinding: { planId, stageId, step, revision: currentPlan.revision },
          filePractice: shouldAttachCurrentFile(instruction),
        }) : undefined;
      if (result?.outcome !== "ready" && inOriginalScope("plan")) {
        setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].linkedPracticeFailed }, "plan");
      }
    };
    const saveCapturedSource = browserComposerSource && !hasImageAttachments &&
      (unified.kind === "resource-link" || /(?:保存|导入|入库|加入|纳入).{0,24}(?:资料库|学习|计划)|\b(?:save|add|import)\b.{0,40}\b(?:library|learning plan|study plan)\b/i.test(instruction));
    if (confirmedActionKey && composerActionPreview?.kind === "browser" && !saveCapturedSource) {
      setComposerActionPreview(undefined);
      setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].stale });
      return;
    }
    if (saveCapturedSource && browserComposerSource) {
      if (linkingSourceInFlight.current) return;
      const linkLearning = unified.kind === "resource-link" || /学习|计划|learning plan|study plan/i.test(instruction);
      const wantsPractice = unified.kind === "practice";
      const stage = linkLearning && formalPlanLive && !livePlanFrozen ? activePlanStage : undefined;
      const revision = data.plan?.revision;
      if (linkLearning && (!stage?.id || !data.plan?.id || revision === undefined)) {
        setOperationMessage({ tone: "info", message: templateCopy[layout.composerLanguage].currentLearning });
        setActiveView("plan");
        return;
      }
      if (stage) {
        const key = JSON.stringify([attachmentScope, browserComposerSource.id, stage.id, data.plan.id, revision, normalizedDraft]);
        if (!confirmedActionKey) {
          requestComposerActionPreview({ kind: "browser", key, scope: attachmentScope, text: normalizedDraft,
            detail: [stage.title, browserComposerSource.title || browserComposerSource.url].join(" · ") }, overrideSubmission);
          return;
        }
        setComposerActionPreview(undefined);
        if (confirmedActionKey !== key) {
          setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].stale });
          return;
        }
      }
      linkingSourceInFlight.current = true;
      try {
        const outcome = await captureResourceIntoLibrary({
          url: browserComposerSource.url,
          title: browserComposerSource.title,
          browserSource: browserComposerSource,
          focusId: stage?.id,
          planBinding: stage && revision !== undefined ? { planId: data.plan.id, revision } : undefined,
        });
        if (!inOriginalScope(activeView)) return;
        if (!outcome.ok || !outcome.resourceId) {
          setOperationMessage({ tone: "error", message: outcome.message || recoverableFailureMessage("send", layout.composerLanguage) });
          return;
        }
        if (stage && outcome.focusBinding !== "bound" && outcome.focusBinding !== "already_bound") {
          setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].stale });
          return;
        }
        const target = stage ? "plan" : "resources";
        const scope = composerDockDraftScope(target, composerSessionKey);
        const resourceId = outcome.resourceId;
        useWorkbenchState.getState().writeComposerResourceRefs(scope, [resourceId]);
        useWorkbenchState.getState().clearComposerBrowserSource(composerDraftScope, browserComposerSource.id);
        clearSubmission();
        setActiveView(target);
        if (practiceAfterLink && stage) {
          await startLinkedPractice({ ...outcome, resourceId }, stage.id, data.plan.id);
        } else if (wantsPractice) {
          const result = await requestResourceTrainingHandoff(resourceId, "practice", instruction);
          if (result.outcome !== "ready") setOperationMessage({ tone: "info", message: t.trainingEmptyDescription });
        }
      } finally {
        linkingSourceInFlight.current = false;
      }
      return;
    }

    if (!hasImageAttachments && unified.kind === "resource-link") {
      if (linkingSourceInFlight.current) return;
      const targets = data.resources.filter((resource) => activeComposerResourceIds.includes(resource.id));
      const stage = formalPlanLive && !livePlanFrozen ? activePlanStage : undefined;
      const planId = data.plan?.id;
      const revision = data.plan?.revision;
      if (!targets.length || !stage || !planId || revision === undefined) {
        setComposerActionPreview(undefined);
        setOperationMessage({
          tone: "info",
          message: targets.length ? templateCopy[layout.composerLanguage].currentLearning
            : unifiedComposerCopy[layout.composerLanguage].selectResources,
        });
        return;
      }
      const sources = targets.map((resource) => ({
        resource_id: resource.id, version_id: resource.versionId ?? "", content_hash: resource.contentHash ?? "",
      }));
      if (practiceAfterLink && (sources.length !== 1 || !sources[0].version_id || !sources[0].content_hash)) {
        setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].selectIndexedSource });
        return;
      }
      const key = JSON.stringify([attachmentScope, stage.id, planId, revision, sources, normalizedDraft]);
      if (!confirmedActionKey) {
        requestComposerActionPreview({ kind: "library", key, scope: attachmentScope, text: normalizedDraft,
          detail: [stage.title, ...targets.map((resource) => resource.title)].join(" · ") }, overrideSubmission);
        return;
      }
      setComposerActionPreview(undefined);
      if (confirmedActionKey !== key) {
        setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].stale });
        return;
      }
      const workspaceId = data.memory.workspace?.workspaceId;
      const operation = beginResourceOperationStatusWait("link-learning", CAPTURE_CONFIRMATION_TIMEOUT_MS);
      linkingSourceInFlight.current = true;
      try {
        const payload = { workspace_id: workspaceId, plan_id: planId, expected_revision: revision,
          stage_id: stage.id, sources, __trainerResourceOperationId: operation.requestId };
        if (!isBrowserPreview) {
          postMessage({ type: "command/execute", payload: { commandId: trainerCommands.linkResourceToLearning, payload } });
          await operation.done;
          if (operation.hasTimedOut()) throw new Error(recoverableFailureMessage("send", layout.composerLanguage));
        } else if (!browserPreviewFixture) {
          const browserPreview = await requireBrowserPreviewAdapter();
          const baseUrl = await browserPreview.ensureBrowserPreviewSidecar();
          const response = await fetch(`${baseUrl}/resources/link-learning`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...payload, session_id: previewSessionId }),
          });
          if (!response.ok) throw new Error(describeSidecarFailure(await response.json()));
          await refreshPreviewResources();
        } else {
          throw new Error(recoverableFailureMessage("send", layout.composerLanguage));
        }
        if (!inOriginalScope(activeView)) return;
        clearSubmission();
        useWorkbenchState.getState().writeComposerResourceRefs(composerDockDraftScope("plan", composerSessionKey), targets.map((resource) => resource.id));
        setActiveView("plan");
        if (practiceAfterLink) {
          const source = sources[0];
          await startLinkedPractice({ resourceId: source.resource_id, versionId: source.version_id,
            contentHash: source.content_hash }, stage.id, planId);
        }
      } catch (error) {
        if (inOriginalScope(activeView)) {
          setOperationMessage({ tone: "error", message: sanitizeErrorSurfaceText(error instanceof Error ? error.message : String(error), layout.composerLanguage) });
        }
      } finally {
        operation.settle();
        linkingSourceInFlight.current = false;
      }
      return;
    }

    if (!hasImageAttachments && (unified.kind === "resource-delete" || unified.kind === "resource-move")) {
      const ids = activeComposerResourceIds;
      const targets = data.resources.filter((resource) => ids.includes(resource.id));
      if (!targets.length || (unified.kind === "resource-move" && !unified.group)) {
        setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].selectResources }, "resources");
        return;
      }
      const key = JSON.stringify([attachmentScope, unified, targets.map((resource) => [resource.id, resource.versionId, resource.contentHash])]);
      if (!confirmedActionKey) {
        requestComposerActionPreview({ kind: "library", key, scope: attachmentScope, text: normalizedDraft,
          detail: targets.map((resource) => resource.title).join(" · ") }, overrideSubmission);
        return;
      }
      setComposerActionPreview(undefined);
      if (confirmedActionKey !== key) {
        setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].stale }, "resources");
        return;
      }
      const workspaceBefore = syncCursor.workspaceId;
      try {
        if (unified.kind === "resource-delete") {
          await requestResourceMutation("delete", ids);
        } else {
          for (const target of targets) {
            if (useWorkbenchState.getState().syncCursor.workspaceId !== workspaceBefore) return;
            const outcome = await organizeLibraryResource(target.id, { action: "set_group", group: unified.group });
            if (!outcome.ok) throw new Error(outcome.message || recoverableFailureMessage("send", layout.composerLanguage));
          }
        }
        if (useWorkbenchState.getState().syncCursor.workspaceId === workspaceBefore) clearSubmission();
      } catch (error) {
        setOperationMessage({ tone: "error", message: sanitizeErrorSurfaceText(error instanceof Error ? error.message : String(error), layout.composerLanguage) }, "resources");
      }
      return;
    }

    if (!hasImageAttachments && unified.kind === "resource-versions") {
      if (resourceVersionCheck?.scope === composerSessionKey && resourceVersionCheck.phase === "checking") return;
      const targets = liveResources.filter((resource) =>
        !activeComposerResourceIds.length || activeComposerResourceIds.includes(resource.id),
      );
      const initial = {
        scope: composerSessionKey, total: targets.length,
        items: [] as (ResourceVersionCheckResult & { title: string })[],
      };
      setActiveView("resources");
      setResourceVersionCheck({ ...initial, phase: targets.length ? "checking" : "done" });
      clearSubmission();
      if (!targets.length) return;

      const controller = new AbortController();
      resourceVersionCheckRequest.current?.abort();
      resourceVersionCheckRequest.current = controller;
      const workspaceId = data.memory.workspace?.workspaceId;
      const items = [...initial.items];
      try {
        for (let start = 0; start < targets.length && !controller.signal.aborted; start += 4) {
          const batch = targets.slice(start, start + 4);
          const sources = batch.map((resource) => ({
            resource_id: resource.id, version_id: resource.versionId ?? "", content_hash: resource.contentHash ?? "",
          }));
          let results: ResourceVersionCheckResult[] | undefined;
          if (!isBrowserPreview) {
            const operation = beginResourceOperationStatusWait("check-versions", RESOURCE_VERSION_CHECK_TIMEOUT_MS);
            try {
              postMessage({ type: "command/execute", payload: {
                commandId: trainerCommands.checkResourceVersions,
                payload: { workspace_id: workspaceId, sources, __trainerResourceOperationId: operation.requestId },
              } });
              await operation.done;
              results = operation.versionResults();
            } finally {
              operation.settle();
            }
          } else if (!browserPreviewFixture) {
            const preview = await requireBrowserPreviewAdapter();
            const baseUrl = await preview.ensureBrowserPreviewSidecar();
            const response = await fetch(`${baseUrl}/resources/check-versions`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ workspace_id: workspaceId, session_id: previewSessionId, sources }),
              signal: AbortSignal.any([controller.signal, AbortSignal.timeout(RESOURCE_VERSION_CHECK_TIMEOUT_MS)]),
            });
            if (response.ok) results = resourceVersionResultsSchema.parse(await response.json());
          }
          if (controller.signal.aborted) return;
          if (!results || results.length !== sources.length) throw new Error("Version check result is incomplete.");
          for (const [index, result] of results.entries()) {
            const expected = sources[index];
            if (result.resource_id !== expected.resource_id || result.version_id !== expected.version_id ||
                result.content_hash !== expected.content_hash) {
              throw new Error("Version check result does not match the requested source.");
            }
            items.push({ ...result, title: batch[index].title });
          }
          setResourceVersionCheck({
            ...initial, items: [...items], phase: items.length === targets.length ? "done" : "checking",
          });
        }
      } catch {
        if (!controller.signal.aborted) setResourceVersionCheck({ ...initial, items: [...items], phase: "interrupted" });
      }
      return;
    }

    if (!hasImageAttachments && unified.kind === "resource-search") {
      // Resource search belongs to the Resources view. Chat no longer owns a
      // separate learning-results disclosure.
      setActiveView("resources");
      if (unified.query) {
        setResourcesViewSearchQuery(unified.query);
        clearSubmission();
      }
      requestCoachComposerFocus();
      return;
    }

    if (!hasImageAttachments && unified.kind === "continue") {
      const trainingCardContext = activeView === "training" || inlinePracticeAwaitingComposerSubmission;
      if (trainingCardContext && trainingComposerPhase === "learn" && activeTrainingCardId && !leftoverTrainingHandoffChromeNotLive) {
        handleTrainingCardStatusTransition(activeTrainingCardId, "active", "start_step");
      } else if (trainingCardContext && trainingComposerReturnMode && trainingHandoffReturnRequired) {
        await handleSubmitTrainingEvidence("").catch(() =>
          setOperationMessage({ tone: "error", message: trainingPersistenceFailureMessage(layout.composerLanguage) }, "training"));
      } else {
        setActiveView("plan");
        runLearningPrimaryAction();
      }
      clearSubmission();
      return;
    }

    if (!hasImageAttachments && unified.kind === "review") {
      useWorkbenchState.getState().openTrainingReviewQueue();
      clearSubmission();
      return;
    }

    if (!hasImageAttachments && unified.kind === "verify") {
      if (activeTrainingCardId && hasTrainingCard && !leftoverTrainingHandoffChromeNotLive &&
          (activeView === "training" || inlinePracticeAwaitingComposerSubmission) && trainingCardType === "practice" &&
          (trainingPracticeVerificationMode === "file" || trainingFilesToTouch.length > 0) &&
          (trainingComposerPhase === "try" || trainingComposerPhase === "verify")) {
        handleVerifyCurrentFileFromCard();
      } else if (!isBrowserPreview) {
        if (activeView === "plan" || activeView === "training" || activeView === "progress") {
          setLearningFileVerification(undefined);
          try {
            const result = await requestTrainingPersistence(trainerCommands.evaluateCurrentFile, {});
            if (inOriginalScope(activeView) && result && typeof result === "object" &&
                "passed" in result && typeof result.passed === "boolean") {
              setLearningFileVerification({ scope: attachmentScope,
                report: useWorkbenchState.getState().data.evaluation, passed: result.passed });
            }
          } catch (error) {
            if (inOriginalScope(activeView)) {
              setOperationMessage({ tone: "error", message: sanitizeErrorSurfaceText(error instanceof Error ? error.message : String(error), layout.composerLanguage) });
            }
            return;
          }
        } else {
          postMessage({ type: "command/execute", payload: { commandId: trainerCommands.evaluateCurrentFile } });
        }
      } else {
        setOperationMessage({
          tone: "info",
          message: appUiCopy(layout.composerLanguage, isBrowserPreview
            ? "预览不能验证当前文件；真实工作区中将运行验证。" : "没有可验证的当前文件。"),
        });
      }
      clearSubmission();
      return;
    }

    if (!hasImageAttachments && unified.kind === "hint" && (composerUsesTrainingFlow || inlinePracticeAwaitingComposerSubmission)) {
      const revealed = trainingHintLadderForCard[Math.min(composerHintLevel, trainingHintLadderForCard.length - 1)];
      if (revealed) {
        const level = Math.min(composerHintLevel + 1, trainingHintLadderForCard.length);
        setComposerHintLevels((levels) => ({ ...levels, [activityDraftKey]: level }));
        handleHintReveal(level);
        clearSubmission();
        return;
      }
    }

    const submitsActivity =
      ((composerUsesTrainingFlow && !trainingComposerReturnMode) || inlinePracticeAwaitingComposerSubmission) &&
      (hasImageAttachments || unified.kind === "blocker" || (unified.kind === "message" &&
        (trainingComposerUsesAnswerMode || trainingComposerReflectMode ||
          (composerUsesTrainingFlow && (trainingComposerPracticeInputMode || interpretTrainingComposerCardCommand(normalizedDraft))))));
    if (submitsActivity) {
      if (trainingPersistencePending) {
        return;
      }

      const trainingCardCommand = interpretTrainingComposerCardCommand(normalizedDraft);
      const trainingCardTransition = leftoverTrainingHandoffChromeNotLive
        ? undefined
        : handleTrainingCardStatusTransition;
      const appliedTrainingCardCommand =
        trainingCardCommand?.kind === "skip"
          ? applyTrainingCardSkip(
              trainingCardTransition,
              activeTrainingCardId,
              layout.composerLanguage,
            )
          : trainingCardCommand?.kind === "grade" && !trainingComposerUsesAnswerMode
            ? applyTrainingCardGrade(
                trainingCardTransition,
                activeTrainingCardId,
                layout.composerLanguage,
                trainingCardCommand.grade,
              )
            : false;
      if (appliedTrainingCardCommand) {
        setActivityDraft("");
        setActivityAttachments([]);
        return;
      }

      if (hasImageAttachments) {
        if (!providerCanCoachNow || providerBlockReason) {
          setOperationMessage({
            tone: "info",
            message: blockedComposerGuidance,
          });
          return;
        }

        if (!providerImageInputState.supported) {
          setOperationMessage({
            tone: "info",
            message:
              providerImageInputState.detail ??
              providerImageInputState.reason ??
              (appUiCopy(layout.composerLanguage, "当前连接还不能验证图片。")),
          });
          return;
        }

        sendTurn({
          text: buildScratchPaperVerificationPrompt(layout.composerLanguage, {
            cardTitle: visibleTrainingCardTitle ?? liveTrainingTitle,
            learnerNote: normalizedDraft,
            verificationItems: authoritativeVerifyItems,
          }),
          intent: "review",
          activeView: "training",
          stream: true,
          includeCurrentFile: false,
          includeDiagnostics: false,
          contextDetail: "focused",
          attachments: submissionAttachments,
        });
        clearSubmission();
        return;
      }

      if (
        (!trainingComposerReflectMode && !trainingComposerReturnMode) &&
        (!providerCanCoachNow || providerBlockReason)
      ) {
        setOperationMessage({
          tone: "info",
          message: blockedComposerGuidance,
        });
        return;
      }

      if (trainingComposerUsesAnswerMode) {
        const normalizedAnswer = normalizedDraft;
        const selectedOptionIndex =
          trainingComposerFlashMode === "choice"
            ? normalizedTrainingFlashChoices.findIndex(
                (choice) =>
                  normalizeInlineComparisonText(choice) === normalizeInlineComparisonText(normalizedAnswer),
              )
            : -1;
        try {
          await requestTrainingPersistence(
            activeTheoryDrill?.id
              ? trainerCommands.trainingTheoryDrillAnswer
              : trainerCommands.trainingFlashcardAnswer,
            activeTheoryDrill?.id
              ? {
                  theoryDrillId: activeTheoryDrill.id,
                  questionId: flashQuestion?.id,
                  learnerAnswer: normalizedAnswer,
                  selectedOptionIndex: selectedOptionIndex >= 0 ? selectedOptionIndex : undefined,
                }
              : {
                  cardId: activeTrainingCardId,
                  learnerAnswer: normalizedAnswer,
                  selectedOptionIndex: selectedOptionIndex >= 0 ? selectedOptionIndex : undefined,
                },
          );
        } catch {
          setOperationMessage({
            tone: "error",
            message: trainingPersistenceFailureMessage(layout.composerLanguage),
          });
          return;
        }
        sendTrainingFeedback({
          phase: "answer",
          cardTitle: visibleTrainingCardTitle ?? liveTrainingTitle,
          question: flashQuestion?.prompt ?? trainingFlashPrompt ?? trainingProblemStatement,
          learnerAnswer: normalizedAnswer,
          evidenceItems: authoritativeVerifyItems,
        });
        clearSubmission();
      } else {
        let shouldStartFeedback = false;
        try {
          shouldStartFeedback = await handleSubmitTrainingEvidence(normalizedDraft, unified.kind === "blocker" ? "blocked" : "result");
        } catch {
          setOperationMessage({
            tone: "error",
            message: trainingPersistenceFailureMessage(layout.composerLanguage),
          });
          return;
        }
        if (!shouldStartFeedback) {
          clearSubmission();
          return;
        }
        sendTrainingFeedback({
          phase: trainingComposerReflectMode ? "reflection" : "evidence",
          cardTitle: visibleTrainingCardTitle ?? liveTrainingTitle,
          question: reviewArtifactForeground
            ? trainingState?.reviewArtifact?.summary
            : trainingComposerSelectedVerifyItem ?? trainingProblemStatement,
          learnerAnswer: normalizedDraft,
          evidenceItems: reviewArtifactForeground
            ? selectedTrainingCardCandidate?.verificationSteps ?? []
            : authoritativeVerifyItems,
        });
        clearSubmission();
      }
      return;
    }

    const waitingComposerEvidence = !resourceAnalysis &&
      coachPlanContext === "evidence" &&
      recoveredRuntime &&
      planRuntimeStatus?.resumeState === "waiting" &&
      Boolean(planRuntimeStatus?.currentStep?.trim()) &&
      liveEvidenceQueue.pending.length === 0;
    if (waitingComposerEvidence) {
      const submitted = normalizedDraft.trim();
      if (!submitted || trainingPersistencePending) {
        return;
      }
      try {
        await requestTrainingPersistence(trainerCommands.evidenceEnqueue, {
          waitingComposer: true,
          summary: submitted,
        });
      } catch (error) {
        setOperationMessage({
          tone: "error",
          message: waitingComposerEnqueueFailureText(error, layout.composerLanguage),
        });
        return;
      }
      clearSubmission();
      return;
    }

    if (!providerCanCoachNow || providerBlockReason) {
      setOperationMessage({
        tone: "info",
        message: blockedComposerGuidance,
      });
      return;
    }

    const dockAnchor = activeView === "coach" ? null : resolveDockContextAnchor(
      activeView,
      {
        stageTitle: activePlanStage?.title,
        stageProgress: dockStageProgressLabel,
        resourceLabel: selectedResourceNavigationLabel,
      },
      dockAnchorControl.suppressed,
    );
    const analyzedIntent = composerUsesTrainingFlow || startsGoal ? "coach" :
      submissionAnalysis.intent === "local_command" ? "coach" : submissionAnalysis.intent;
    // The plan composer intent is a state, not a destination: it is set when
    // the learner picks an action on the plan card inside the learning drawer.
    const contextualPlanMode = coachPlanContext;
    const formalPlanGeneration = !resourceAnalysis &&
      (unified.kind === "plan" || contextualPlanMode === "generate" || analyzedIntent === "plan");
    const planComposerSubmission = !resourceAnalysis &&
      (formalPlanGeneration || contextualPlanMode !== undefined);
    const submittedPlanMode = formalPlanGeneration ? "generate" : contextualPlanMode ?? "explain";
    // Learning and resource replies live in the single Chat conversation. Keep
    // resource turns anchored in Chat instead of hijacking to the Resources
    // library or dropping the live streaming indicator.
    const turnView = planComposerSubmission ? "plan" : "coach";
    const resourceIds = activeComposerResourceIds;
    if (formalPlanGeneration) {
      const key = JSON.stringify([attachmentScope, composerSessionKey, data.plan?.id, data.plan?.revision,
        activeTrainingCardId, normalizedDraft, resourceIds, submissionAttachments.map((item) => item.id)]);
      if (!confirmedActionKey) {
        requestComposerActionPreview({ kind: "plan", key, scope: attachmentScope, text: normalizedDraft, detail: data.plan?.title }, overrideSubmission);
        return;
      }
      setComposerActionPreview(undefined);
      if (confirmedActionKey !== key) {
        setOperationMessage({ tone: "info", message: unifiedComposerCopy[layout.composerLanguage].stale });
        return;
      }
    }
    const previewPlanCandidateGeneration =
      formalPlanGeneration && isBrowserPreview && Boolean(window.__TRAINER_BOOTSTRAP__);
    if (formalPlanGeneration && !previewPlanCandidateGeneration && !providerCanMutateFormalPlan) {
      setOperationMessage({
        tone: "info",
        message: formalPlanCapabilityMessage,
      });
      return;
    }
    if (formalPlanGeneration && !previewPlanCandidateGeneration && !capabilityVerdict.formalPlan) {
      setOperationMessage({
        tone: "info",
        message: formalPlanCapabilityMessage,
      });
      return;
    }
    // Explicit confirmed formal-plan generation opens the learning drawer on
    // the goal section; ordinary discussion turns stay in Chat so the modal
    // drawer never pops over a live streaming reply.
    if (formalPlanGeneration) {
      setActiveView("plan");
    } else if (activeView !== "coach" && activeView !== "training" && !resourceAnalysis) {
      setActiveView("coach");
    }
    const intent = resourceAnalysis ? "coach" : formalPlanGeneration ? "plan" : analyzedIntent;
    const rawMessageText =
      (composerUsesTrainingFlow || startsGoal ? normalizedDraft : submissionAnalysis.draftBody) ||
      (hasImageAttachments
        ? buildGenericImageReviewPrompt(layout.composerLanguage, normalizedDraft)
        : defaultPromptText(intent, layout.composerLanguage));
    const messageText = appendDockAnchor(rawMessageText, dockAnchor);
    const capturedContext = browserComposerSource && !messageText.includes(browserComposerSource.url)
      ? [browserComposerSource.url, ...browserComposerSource.selection.split(/\r?\n/u).filter(Boolean).map((line) => "> " + line)].join("\n")
      : undefined;
    if (startsGoal && browserPreviewFixture) {
      startGoal(instruction.slice(0, 240));
    }
    sendTurn({
      text: capturedContext ? messageText + "\n\n" + capturedContext : messageText,
      intent,
      intentSource: formalPlanGeneration || planComposerSubmission ? "explicit" : submissionAnalysis.intentSource,
      goals: formalPlanGeneration ? data.profile.goals : undefined,
      activeView: turnView,
      stream: true,
      formalPlanMutation: formalPlanGeneration && !previewPlanCandidateGeneration,
      planComposerMode: planComposerSubmission ? submittedPlanMode : undefined,
      resourceComposerIntent: unified.kind === "resource-turn"
        ? { mode: unified.mode, resourceIds }
        : unified.kind === "practice" && resourceIds.length > 0
          ? { mode: "analyze", resourceIds }
          : activeView === "resources" ? { mode: "locate", resourceIds } : undefined,
      resourceIds,
      includeDiagnostics: intent === "review" ? true : undefined,
      contextDetail: intent === "review" ? "full" : undefined,
      attachments: submissionAttachments,
      goalMode: turnView === "coach" && intent === "coach" ? startsGoal || (goalMode && !goalPaused) : undefined,
      goalText: startsGoal ? instruction : undefined,
    });
    clearSubmission();
    setCoachPlanContext(undefined);
  };

  handleSubmitRef.current = handleSubmit;
  return {
    handleSubmit,
  };
}
