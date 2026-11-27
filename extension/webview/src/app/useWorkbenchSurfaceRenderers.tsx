import {
  Suspense,
  useCallback,
  useMemo,
  useRef,
  type ReactNode
} from "react";
import { MessageRichContent } from "../components/coach/MessageRichContent";
import { InlinePracticeAnswer } from "../components/learning/InlinePracticeAnswer";
import { InlineProgressCard } from "../components/learning/InlineProgressCard";
import { LearningStrip } from "../components/learning/LearningStrip";
import { readTrainingCardList,readTrainingCardText } from "../lib/boundTrainingCardFacts";
import { resourceVersionCopy } from "../lib/i18n/resourceVersionCopy";
import { unifiedComposerCopy } from "../lib/i18n/unifiedComposerCopy";
import {
  executeLearningPrimaryAction,
  resolveLearningPrimaryAction,
  type LearningFacts,
} from "../lib/learningActionResolver";
import { SystemState } from "../templates/SystemState";

import { trainerCommands } from "../../../../shared/src/commands";
import {
  sanitizeErrorSurfaceText
} from "../../../../shared/src/errorSurfaceSanitizer";
import {
  liveEvidenceBinding
} from "../../../../shared/src/planOrientationGovernance";
import {
  CoachConversationView,
  type CoachArtifactBlockData
} from "../components/coach";
import {
  ArrowRightIcon,
  ChevronRightIcon
} from "../components/icons";
import { TrainingCardLibrary,type TrainingCardLibraryAction } from "../components/training/TrainingCardLibrary";
import { composerDockDraftScope } from "../lib/composerDock";
import {
  appUiCopy
} from "../lib/i18n/appUiCopy";
import { resolvePlanComposerCopy } from "../lib/i18n/planComposerCopy";
import { COACH_MESSAGE_ACTION_LABELS } from "../lib/i18n/segments/coachMessageBubbleCopy";
import { deriveLearningSummary } from "../lib/learningSummary";
import { coachViewLabel,planViewLabel,resourcesViewLabel,settingsViewLabel,trainingViewLabel } from "../lib/viewLabels";
import {
  postDebugVisibleFacts,
  postMessage
} from "../lib/vscode";
import { templateCopy } from "../templates/templateCopy";
import {
  blockedComposerPresenceMessage,
  providerRecoveryLocale,
  providerRecoverySummary,
} from "./providerRecoveryCopy";
import { useWorkbenchState } from "./useWorkbenchState";

// ContextMenu type imported from useMenuState
import {
  type WorkbenchCtxAfterK3
} from "./App";
import {
  CoachPlanView,
  DockedView,
  ResourcesWorkbenchView,
  TrainingWorkbenchView,
  ViewFallback,
  activeStageObjectiveText,
  coachFirstComposerPlaceholder,
  composerHintText,
  defaultPromptText,
  focusComposerInput,
  livePlanUpdatePendingMessage,
  localizeUiViewReferences,
  pickFirstText,
  planComposerDraftReplacementCopy,
  sendStatuslineText,
  trainingComposerModeText,
  trainingFilePracticeText,
  trainingHandoffComposerText,
  triggerResourceUpload,
  truncateInlineText
} from "./appHelpers";

export function useWorkbenchSurfaceRenderers(ctx: WorkbenchCtxAfterK3) {
  const {
    data,
    layout,
    resourceOrganizationPending,
    resourceRestoreContext,
    trainingReviewQueueRequested,
    beginTrainingReview,
    syncStatus,
    setActiveView,
    openLearningDrawer,
    closeLearningDrawer,
    setResourceRestoreContext,
    setComposerDraft,
    setOperationMessage,
    trainingComposerFlashMode,
    trainingComposerPracticeReturnMode,
    trainingVerifyNotice,
    setTrainingVerifyNotice,
    remoteVerification,
    beginRemoteVerification,
    stopRemoteVerification,
    trainingPersistencePending,
    requestTrainingPersistence,
    trainerWorkspaceAdmission,
    resourceWriteAccess,
    workspaceSessionBlocked,
    workspaceSessionBlockMessage,
    openWorkspaceAdmission,
    runWorkspaceAdmissionCommand,
    pendingMessageAction,
    lastTurnView,
    setCoachPlanContext,
    pendingPlanComposerDraftReplacement,
    requestResourceMutation,
    requestResourceIndex,
    requestResourceSearch,
    requestBrowserPreviewResourceSearch,
    requestResourceTrainingHandoff,
    handleBrowserUrlImport,
    resourceCaptureFocusOptions,
    captureResourceIntoLibrary,
    requestLibraryMigration,
    listLibraryFolders,
    createLibraryFolder,
    renameLibraryFolder,
    deleteLibraryFolder,
    revealLibraryPath,
    organizeLibraryResource,
    exportLibraryResource,
    streaming,
    syncIdentity,
    setOpenMenu,
    isBrowserPreview,
    activeView,
    t,
    goalMode,
    goalText,
    composerSessionKey,
    goalDraftPending,
    inlinePracticeCollapsed,
    setInlinePracticeCollapsed,
    researchBriefToOpen,
    selectedResourceContextIds,
    setSelectedResourceContextIds,
    setResourceConversationContextIds,
    uploadFilesInputRef,
    uploadFolderInputRef,
    pendingLivePlanTaskMintRef,
    requestCoachComposerFocus,
    browserPreviewFixture,
    canOpenInEditor,
    openViewInEditor,
    expandToEditorLabel,
    openProviderSetup,
    planText,
    handleResourceSelectionChange,
    handleCoachMessageAction,
    handleReviewQueueAction,
    handleTrainingCardStatusTransition,
    draft,
    resourcesViewSearchQuery,
    setResourcesViewSearchQuery,
    requestPlanComposerGuidance,
    confirmPlanComposerDraftReplacement,
    cancelPlanComposerDraftReplacement,
    providerSendState,
    providerCanCoachNow,
    providerCanMutateFormalPlan,
    formalPlanCapabilityMessage,
    providerBlockReason,
    blockedComposerGuidance,
    providerCoachNotice,
    providerSetupState,
    displayConnectionState,
    shouldShowNeutralEmptyState,
    coachWelcomeVisible,
    isFirstCoachConversation,
    hasFormalPlan,
    activePlanStage,
    planRuntimeStatus,
    recoveredRuntime,
    runtimeCurrentStage,
    leftoverTrainingHandoffChromeNotLive,
    leftoverResourceLibraryListNotLive,
    liveFirstLookSummary,
    coachRenderConversation,
    liveCoachTaskChrome,
    leftoverCoachTurnChromeNotLive,
    latestCoachArtifact,
    coachTurnNextStepRequiresConfirmation,
    liveCoachTurnChrome,
    formattedNextReviewDue,
    resolvedCoachSummary,
    resolvedCoachNextStep,
    resolvedCoachFocus,
    resolvedCoachStage,
    latestArtifactTeaser,
    runtimeBlockedReason,
    runtimeNextAfterCurrent,
    recoveredDisplayFacts,
    formalPlanLive,
    livePlanFrozen,
    livePlanTitle,
    livePlanSummary,
    liveTrainingSource,
    liveTask,
    liveTrainingTitle,
    liveTrainingFocus,
    liveCoachStage,
    liveStageChrome,
    leftoverPlanNotLive,
    visibleFormalPlan,
    liveEvidenceQueue,
    planWhyNow,
    verifyPlanAdvanceNext,
    planVerifyItems,
    planReviewReason,
    planReviewItems,
    planReviewWindowLead,
    planReturnPathLead,
    rememberedCoachSummary,
    resolvedCoachStateSummary,
    openPlanComposerMode,
    handlePlanOrientationAction,
    handleResourcesOrientationAction,
    planOrientation,
    liveResources,
    liveSandboxState,
    resourcesOrientation,
    trainingState,
    selectedTrainingCardCandidate,
    trainingRestoreForeground,
    reviewArtifactForeground,
    activeTrainingReviewArtifact,
    trainingCardType,
    activeTrainingCardId,
    selectedTrainingRouteCard,
    activityDraftKey,
    setComposerHintLevels,
    composerHintLevel,
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
    trainingApiHints,
    trainingSelfCheck,
    trainingFilesToTouch,
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
    trainingFlashPrompt,
    trainingTargetSkill,
    liveTrainingSkill,
    trainingProblemStatement,
    trainingComposerSelectedVerifyItem,
    hasTrainingCard,
    hasRenderableTrainingCard,
    boundTrainingCardFacts,
    resolvedReviewArtifact,
    trainingComposerTalkMode,
    trainingComposerUsesAnswerMode,
    trainingComposerPracticeInputMode,
    trainingComposerFilePracticeMode,
    trainingComposerReflectMode,
    trainingComposerReturnMode,
    composerUsesTrainingFlow,
    sendAnalysis,
    sendBlocked,
    handleGenerateTrainingCard,
    handleNextTrainingCard,
    handleGeneratePlanStepCard,
    composerSendBlocked,
    coachBlockingSurface,
    handleSuggestedAction,
    resourceVersionCheck,
    setResourceVersionCheck,
    resourceVersionCheckRequest,
    attemptLifecycle,
    handleHintReveal,
    handleVerifyTrainingFromIde,
    handleResumeTrainingInCoach,
    selectedResourceNavigationLabel,
    activePlanComposerMode,
    onboardingWizard,
    workspaceAdmissionContent,
    providerSetupAction,
  } = ctx;
  const trainingCardSettled = Boolean(
    hasTrainingCard &&
    (trainingState?.latestLearningVerifiedResult ||
      trainingState?.latestLearningPartialProgress ||
      trainingState?.latestLearningBlocker ||
      normalizedTrainingNextHopStatus === "continued_in_chat"),
  );
  const coachSuperEntryContent = (embedded = false) => {
    if (embedded || workspaceSessionBlocked) {
      return null;
    }
    if (shouldShowNeutralEmptyState) {
      if (onboardingWizard) {
        // Unified cold-start wizard covers the fresh-user ladder; the
        // scenario-aware recovery block below stays for saved connections.
        return (
          <div
            className={`coach-empty-state ${
              displayConnectionState === "starting"
                ? "coach-empty-state--welcome"
                : "coach-empty-state--blocked"
            }`}
          >
            {onboardingWizard}
          </div>
        );
      }
      // Scenario-aware, localized setup copy (first-run "连接模型", missing key,
      // backend starting, …) instead of a single error-flavoured sentence.
      const setupTitle = providerSetupState.title;
      // A categorized provider failure names its class (invalid key, rate
      // limit, …) instead of the generic check-connection line.
      const setupDetail =
        (data.connection.state === "connected" && providerSendState.blocked ? providerSendState.reason?.trim() : undefined) ||
        providerSetupState.detail;
      const setupActionLabel =
        providerSetupState.actionLabel ||
        (layout.composerLanguage === "zh-CN" ? "检查连接" : providerSetupAction.primary.label);
      return (
        <div
          className={`coach-empty-state ${
            displayConnectionState === "starting"
              ? "coach-empty-state--welcome"
              : "coach-empty-state--blocked"
          }`}
        >
          <p>{setupTitle}</p>
          {setupDetail && setupDetail !== setupTitle ? (
            <p className="coach-empty-state__detail">{setupDetail}</p>
          ) : null}
          <button className="button button--accent" type="button" onClick={() => openProviderSetup()}>
            {setupActionLabel}
          </button>
        </div>
      );
    }
    if (coachWelcomeVisible) {
      return (
        <div className="coach-empty-state coach-empty-state--welcome coach-empty-state--conversation">
          <h2>{appUiCopy(layout.composerLanguage, "你在做什么？")}</h2>
          <p className="coach-empty-state__lead">
            {appUiCopy(layout.composerLanguage, "可以从当前代码、一篇文章或一个问题开始。")}
          </p>
        </div>
      );
    }
    return null;
  };

  const handleCoachArtifactOpen = (artifact: CoachArtifactBlockData) => {
    // “Set as practice” explicitly creates a card for the live plan step.
    // A normal task turn is intentionally blocked after Return; it must not
    // mint a parallel TaskSpec or leave this button stuck in review-only mode.
    if (
      (artifact.kind === "task" || artifact.kind === "next_step") &&
      (!artifact.recommendedAction || artifact.recommendedAction === "task") &&
      formalPlanLive && !livePlanFrozen &&
      activePlanStage?.id && data.plan.id &&
      recoveredDisplayFacts.currentStep?.trim()
    ) {
      handleGenerateTrainingCard(
        activePlanStage?.title ?? artifact.focusArea,
        recoveredDisplayFacts.currentStep,
        {
          planId: data.plan.id,
          stageId: activePlanStage.id,
          step: recoveredDisplayFacts.currentStep,
          revision: data.plan.revision,
        },
      );
      return;
    }
    if (artifact.recommendedAction) {
      handleSuggestedAction(artifact.recommendedAction, {
        focusArea: artifact.focusArea,
      });
      return;
    }
    if (artifact.kind === "plan" || artifact.kind === "plan_update") {
      setActiveView("plan");
      return;
    }
    if (artifact.kind === "evaluation" || artifact.kind === "review") {
      handleSuggestedAction("review", {
        focusArea: artifact.focusArea,
      });
      return;
    }
    if (artifact.kind === "task" || artifact.kind === "next_step") {
      handleSuggestedAction("task", {
        focusArea: artifact.focusArea,
      });
    }
  };
  // Stable identity for memoized conversation children; behavior stays fresh
  // through the ref so memo never serves a stale closure.
  const handleCoachArtifactOpenRef = useRef(handleCoachArtifactOpen);
  handleCoachArtifactOpenRef.current = handleCoachArtifactOpen;
  const stableHandleCoachArtifactOpen = useCallback(
    (artifact: CoachArtifactBlockData) => handleCoachArtifactOpenRef.current(artifact),
    [],
  );

  const renderCoachConversationPane = (className: string, embedded = false) => (
    <CoachConversationView
      messages={coachRenderConversation}
      className={className}
      surfaceTone="quiet"
      eyebrow={undefined}
      title={undefined}
      subtitle={undefined}
      openArtifactLabel={appUiCopy(layout.composerLanguage, "\u5c55\u5f00")}
      userLabel={t.you}
      assistantLabel={t.trainer}
      systemLabel={appUiCopy(layout.composerLanguage, "\u7cfb\u7edf")}
      language={layout.composerLanguage}
      emptyState={embedded || workspaceSessionBlocked ? null : coachSuperEntryContent(false)}
      streamingMessage={
        streaming.isStreaming
          ? {
              // R3: the in-flight body comes from the view's own store
              // subscription; App never selects per-chunk content.
              body: "",
              author: t.trainer,
              timestamp: t.streaming,
              role: "assistant",
              roleLabel: t.trainer,
            }
          : null
      }
      liveContentFromStore
      onArtifactOpen={stableHandleCoachArtifactOpen}
      onMessageAction={handleCoachMessageAction}
      pendingMessageAction={pendingMessageAction}
      turnNextStepRequiresConfirmation={coachTurnNextStepRequiresConfirmation}
      resources={data.resources}
      footer={
        hasTrainingCard || (trainingReviewQueueRequested && trainingReviewItems.length > 0) ? (
          <div
            className="inline-practice-slot"
            data-inline-practice="true"
            data-inline-practice-collapsed={inlinePracticeCollapsed ? "true" : "false"}
          >
            {inlinePracticeCollapsed ? (
              <div className="inline-practice-slot__header">
                <span className="inline-practice-slot__summary">
                  {appUiCopy(layout.composerLanguage, "当前练习")}
                  {visibleTrainingCardTitle || liveTrainingTitle
                    ? ` · ${visibleTrainingCardTitle || liveTrainingTitle}`
                    : ""}
                </span>
                <button
                  type="button"
                  className="inline-practice-slot__toggle"
                  data-inline-practice-toggle="true"
                  aria-expanded="false"
                  onClick={() => setInlinePracticeCollapsed(false)}
                >
                  {appUiCopy(layout.composerLanguage, "展开练习")}
                </button>
              </div>
            ) : (
              <>
                <div className="inline-practice-slot__header inline-practice-slot__header--expanded">
                  <button
                    type="button"
                    className="inline-practice-slot__toggle"
                    data-inline-practice-toggle="true"
                    aria-expanded="true"
                    onClick={() => setInlinePracticeCollapsed(true)}
                  >
                    {appUiCopy(layout.composerLanguage, "收起练习")}
                  </button>
                </div>
                {renderTrainingView(true)}
                {trainingCardSettled ? (
                  <InlineProgressCard
                    language={layout.composerLanguage}
                    rows={learningSummary.progressRows}
                    evidenceCount={learningSummary.evidenceCount}
                    achievement={learningSummary.latestAchievement}
                    onOpen={() => {
                      setOpenMenu(undefined);
                      openLearningDrawer("progress");
                    }}
                  />
                ) : null}
              </>
            )}
          </div>
        ) : undefined
      }
    />
  );

  const renderContextualResultRail = (view: "plan" | "resources" | "training" | "settings") => {
    const isTraining = view === "training";
    const isResources = view === "resources";
    const isSettings = view === "settings";
    const isZh = layout.composerLanguage === "zh-CN";
    const textLimit = isZh ? 28 : 56;
    // Leftover-not-live (recovered without live selected_card_id / leftover stored note)
    // must not paint leftover dump as a live skip/grade/reflect/return object.
    // Quiet leftover sentence stays on the Training pane. Do not invent a card.
    const leftoverTrainingActivityNotLive =
      leftoverTrainingHandoffChromeNotLive ||
      (data.workspaceProjection?.hasCardAuthority
        ? !String(data.workspaceProjection.selectedCardId ?? "").trim()
        : Boolean(recoveredRuntime) && !String(trainingState?.selectedCardId ?? "").trim());
    const blockerValue = isTraining
      ? leftoverTrainingActivityNotLive
        ? undefined
        : pickFirstText(
          trainingState?.latestLearningBlocker,
          trainingState?.latestTrainingHandoff?.blockedBy,
          activeTrainingReviewArtifact?.blockedReason,
          runtimeBlockedReason,
        )
      : isSettings
        ? undefined
      : runtimeBlockedReason ??
        (leftoverCoachTurnChromeNotLive
          ? undefined
          : data.coachTurn?.blocker ?? data.coachingState?.blocker);
    const resultValue = isTraining
      ? leftoverTrainingActivityNotLive
        ? undefined
        : pickFirstText(
          trainingState?.latestLearningVerifiedResult,
          activeTrainingReviewArtifact?.verifiedResult,
          trainingState?.latestLearningPartialProgress,
          activeTrainingReviewArtifact?.partialProgress,
        )
      : isSettings
        ? undefined
      : latestArtifactTeaser ??
        (leftoverCoachTurnChromeNotLive ? undefined : latestCoachArtifact?.title) ??
        resolvedCoachSummary;
    // A stream belongs to the active session, not to the view where it was
    // started. Keep the live reply visible when the learner switches views
    // while the agent is still working; the completed-result guard below still
    // prevents stale Coach results from cluttering the Resources surface.
    // The preview truncates from the start, so reading the latest content here
    // (scheduled by the coarse bucket) is exact for what this line shows.
    const liveValue = streaming.isStreaming
      ? truncateInlineText(streaming.streamMessageId?.startsWith("training_")
          ? ""
          : useWorkbenchState.getState().streaming.streamedContent || "", textLimit)
      : undefined;
    const activitySource = liveValue ?? blockerValue ?? resultValue;
    const activityValue =
      isTraining && !liveValue
        ? activitySource?.trim()
        : truncateInlineText(activitySource, textLimit);
    const isPlanContextWorthSurfacing = view !== "plan" || Boolean(liveValue || blockerValue);
    const isResourcesContextWorthSurfacing =
      !isResources || streaming.isStreaming || lastTurnView === "resources";
    const isSettingsContextWorthSurfacing = !isSettings || Boolean(liveValue);
    if (
      !activityValue ||
      !isPlanContextWorthSurfacing ||
      !isResourcesContextWorthSurfacing ||
      !isSettingsContextWorthSurfacing ||
      (isTraining && !liveValue)
    ) {
      return null;
    }
    const activityLabel = liveValue
      ? t.viewContextWorking
      : blockerValue
        ? t.viewContextBlocker
        : t.viewContextLatest;
    const activityTone = liveValue ? "activity" : blockerValue ? "blocker" : "result";

    return (
      <section
        className={`view-context-rail view-context-rail--${view}`}
        data-view-context-rail={view}
        aria-label={`${
          view === "plan"
            ? planViewLabel(layout.composerLanguage)
            : isResources
              ? resourcesViewLabel(layout.composerLanguage)
              : isSettings
                ? settingsViewLabel(layout.composerLanguage)
                : trainingViewLabel(layout.composerLanguage)
        } ${t.viewContextCoach}`}
        aria-live={streaming.isStreaming ? "polite" : undefined}
      >
        <div className="view-context-rail__facts">
          <div className={`view-context-rail__fact view-context-rail__fact--${activityTone}`} title={activityValue}>
            <span>{activityLabel}</span>
            <strong>{activityValue}</strong>
          </div>
        </div>
        {isTraining ? null : (
        <button
          className="view-context-rail__open-coach"
          data-view-context-rail-open-coach
          type="button"
          onClick={() => {
            setActiveView(
              view === "settings" && lastTurnView && lastTurnView !== "settings"
                ? lastTurnView
                : "coach",
            );
            requestCoachComposerFocus();
          }}
        >
          {t.openCoach}
        </button>
        )}
      </section>
    );
  };

  const renderDockedView = (view: DockedView, content: ReactNode) => {
    return (
      <section
        className={`view-stack view-stack--${view} view-stack--content-${layout.learningSurfaceAlignment} view-stack--single`}
      >
        <div className="view-stack__primary">
          {content}
        </div>
      </section>
    );
  };

  const renderCoachRootView = () => (
    <section className="coach-view">
      {coachBlockingSurface === "workspace-admission" && onboardingWizard ? (
        // R1①: on a true cold start the wizard's workspace step owns the
        // root-selection ask; the admission panel must not stack under it
        // (its reconciliation details stay available once the wizard clears).
        <div className="coach-onboarding">{onboardingWizard}</div>
      ) : coachBlockingSurface === "workspace-admission" && workspaceAdmissionContent ? (
        <>
          <div className="coach-workspace-admission">{workspaceAdmissionContent}</div>
          {!providerCanCoachNow && providerCoachNotice ? (
            <button
              className="button button--ghost coach-workspace-admission__provider-action"
              type="button"
              onClick={openProviderSetup}
            >
              <span>{providerSetupState.actionLabel}</span>
              <strong>{providerCoachNotice.message}</strong>
            </button>
          ) : null}
        </>
      ) : null}
      <LearningStrip
        language={layout.composerLanguage}
        goalTitle={learningSummary.goalTitle}
        currentStep={learningSummary.goalStep}
        goalText={goalMode || goalDraftPending ? goalText : undefined}
        dueCount={learningSummary.dueCount}
        onOpen={() => {
          setOpenMenu(undefined);
          openLearningDrawer(layout.learningSection ?? "goal");
        }}
      />
      {renderCoachConversationPane("coach-pane", false)}
    </section>
  );

  const contextualComposerSummary = () => {
    if (!latestCoachArtifact || leftoverCoachTurnChromeNotLive) {
      return sendStatuslineText(sendAnalysis, data, layout, t);
    }
    const action = latestCoachArtifact.recommendedAction
      ? appUiCopy(layout.composerLanguage, "现在顺着这条结果继续：{v}").replace(
          "{v}",
          () => latestCoachArtifact.title,
        )
      : appUiCopy(layout.composerLanguage, "当前主线：{v}").replace(
          "{v}",
          () => latestCoachArtifact.title,
        );
    return latestArtifactTeaser ? `${action} · ${latestArtifactTeaser}` : action;
  };

  const composerSurfaceHint = () => {
    if (providerSendState.warning && !providerSendState.blocked) {
      return providerSendState.warning;
    }
    if (draft.trim().length === 0) {
      return undefined;
    }
    if (latestCoachArtifact) {
      return contextualComposerSummary();
    }
    if (sendAnalysis.target === "local_command" || sendAnalysis.intent !== "coach") {
      return sendStatuslineText(sendAnalysis, data, layout, t);
    }
    if (data.resources.length > 0) {
      return composerHintText(sendAnalysis, data, layout, t);
    }
    return undefined;
  };

  const providerRecoveryReason =
    providerBlockReason ??
    (providerSendState.blocked
      ? providerRecoverySummary(
          data.providerConfig,
          layout.composerLanguage,
          data.connection.state,
        ).detail
      : providerSendState.reason?.trim());
  void providerRecoveryReason;
  const trainingComposerModeTextCopy = trainingComposerModeText(layout.composerLanguage);
  const blockedComposerFallback =
    sendBlocked && !workspaceSessionBlocked
      ? providerRecoveryLocale(layout.composerLanguage).draftWhilePaused
      : providerCanCoachNow && !providerBlockReason
      ? isFirstCoachConversation
        ? coachFirstComposerPlaceholder[layout.composerLanguage]
        : activeView === "plan"
          ? t.composerPlaceholderPlan
          : t.composerPlaceholder
      : activeView === "plan"
        ? appUiCopy(layout.composerLanguage, "先记下下一条计划备注。")
        : activeView === "training"
          ? trainingComposerModeTextCopy.genericPlaceholder
          : providerRecoveryLocale(layout.composerLanguage).draftWhilePaused;
  const blockedComposerPresenceDetail =
    activeView === "coach"
      ? localizeUiViewReferences(
          blockedComposerPresenceMessage(
            data.providerConfig,
            layout.composerLanguage,
            data.connection.state,
          ),
          layout.composerLanguage,
        ) ??
        blockedComposerPresenceMessage(
          data.providerConfig,
          layout.composerLanguage,
          data.connection.state,
        )
      : blockedComposerGuidance;
  const blockedComposerPresenceCopy = workspaceSessionBlocked
    ? workspaceSessionBlockMessage ?? blockedComposerPresenceDetail
    : blockedComposerPresenceDetail;
  const compactUtilityComposerPlaceholder =
    sendBlocked
      ? blockedComposerFallback
      : activeView === "resources"
        ? appUiCopy(layout.composerLanguage, "围绕资料提问或生成讲稿")
        : activeView === "training"
          ? trainingComposerModeTextCopy.genericPlaceholder
          : activeView === "plan"
            ? appUiCopy(layout.composerLanguage, "写下这一步")
            : blockedComposerFallback;
  const refinedUtilityComposerPlaceholder =
    activeView === "resources"
      ? appUiCopy(layout.composerLanguage, "围绕资料提问或生成讲稿")
      : activeView === "plan"
        ? appUiCopy(layout.composerLanguage, "写下这一步")
        : compactUtilityComposerPlaceholder;
  const unifiedCopy = unifiedComposerCopy[layout.composerLanguage];
  const trainingFilePracticeTextCopy = trainingFilePracticeText(layout.composerLanguage);
  const trainingHandoffComposerTextCopy = trainingHandoffComposerText(layout.composerLanguage);
  const resolvedTrainingComposerPlaceholder = trainingComposerUsesAnswerMode
    ? trainingComposerFlashMode === "choice"
      ? trainingComposerModeTextCopy.choicePlaceholder
      : trainingComposerFlashMode === "fill"
        ? trainingComposerModeTextCopy.fillPlaceholder
        : trainingComposerModeTextCopy.shortAnswerPlaceholder
    : trainingComposerStudyMode
      ? trainingComposerModeTextCopy.studyPlaceholder
    : trainingComposerPracticeInputMode
      ? trainingComposerFilePracticeMode
        ? unifiedCopy.filePracticePrompt
        : unifiedCopy.activityPrompt
    : trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnPlaceholder
    : trainingComposerReflectMode
      ? trainingHandoffComposerTextCopy.reflectPlaceholder
    : trainingComposerSelectedVerifyItem
      ? trainingComposerModeTextCopy.verificationPlaceholder.replace(
          "{item}",
          truncateInlineText(
            trainingComposerSelectedVerifyItem,
            layout.composerLanguage === "zh-CN" ? 20 : 40,
          ) ?? trainingComposerSelectedVerifyItem,
        )
      : trainingComposerModeTextCopy.genericPlaceholder;
  const resolvedCompactUtilityComposerPlaceholder =
    trainingComposerTalkMode
      ? trainingComposerModeTextCopy.talkPlaceholder
      : composerUsesTrainingFlow && !composerSendBlocked
      ? resolvedTrainingComposerPlaceholder
      : activeView === "resources"
        ? appUiCopy(layout.composerLanguage, "围绕资料提问或生成讲稿")
        : activeView === "plan"
          ? appUiCopy(layout.composerLanguage, "写下这一步")
          : refinedUtilityComposerPlaceholder;
  const planSummarySource =
    formalPlanLive
      ? activePlanStage?.title ?? resolvedCoachStage ?? resolvedCoachFocus ?? livePlanSummary
      : recoveredDisplayFacts.currentStep || livePlanTitle;
  const planSummaryTruncated = truncateInlineText(
    planSummarySource,
    layout.composerLanguage === "zh-CN" ? 24 : 48,
  );
  const resolvedUtilityComposerSummary =
    activeView === "resources"
      ? selectedResourceNavigationLabel
        ? appUiCopy(layout.composerLanguage, "资料：{v}").replace(
            "{v}",
            () => selectedResourceNavigationLabel,
          )
        : appUiCopy(layout.composerLanguage, "资料：先让教练定位文件")
      : activeView === "plan"
        ? planSummaryTruncated
          ? appUiCopy(layout.composerLanguage, "计划：{v}").replace("{v}", () => planSummaryTruncated)
          : appUiCopy(layout.composerLanguage, "计划：解释当前阶段")
        : activeView === "coach"
          ? contextualComposerSummary()
          : undefined;
  const studyFocusSource =
    trainingTargetSkill ?? trainingScenarioPackLabel ?? trainingProblemStatement;
  const studyFocusText =
    truncateInlineText(studyFocusSource, layout.composerLanguage === "zh-CN" ? 22 : 44) ??
    studyFocusSource;
  const returnModeText = truncateInlineText(
    trainingReturnWithText ?? trainingSuccessSignal ?? trainingCoachBridge.ctaLabel,
    layout.composerLanguage === "zh-CN" ? 26 : 52,
  );
  const reflectFallbackText = truncateInlineText(
    trainingFallbackActionText ??
      trainingComposerSelectedVerifyItem ??
      trainingState?.latestLearningBlocker,
    layout.composerLanguage === "zh-CN" ? 26 : 52,
  );
  const currentCheckText =
    truncateInlineText(
      trainingComposerSelectedVerifyItem,
      layout.composerLanguage === "zh-CN" ? 26 : 52,
    ) ?? trainingComposerSelectedVerifyItem;
  const resolvedComposerSummary = trainingComposerTalkMode
    ? appUiCopy(layout.composerLanguage, "\u8bad\u7ec3 \u00b7 \u4e0e\u6559\u7ec3\u5bf9\u8bdd")
    : composerUsesTrainingFlow
    ? trainingComposerUsesAnswerMode
      ? appUiCopy(
          layout.composerLanguage,
          trainingComposerFlashMode === "choice"
            ? "作答方式：选择"
            : trainingComposerFlashMode === "fill"
              ? "作答方式：填空"
              : "作答方式：简答",
        )
      : trainingComposerPracticeInputMode
        ? trainingComposerFilePracticeMode
          ? appUiCopy(
              layout.composerLanguage,
              trainingComposerPracticeReturnMode === "result" ? "动手：结果记录" : "动手：遇到的问题",
            )
          : appUiCopy(
              layout.composerLanguage,
              trainingComposerPracticeReturnMode === "result" ? "动手：结果" : "动手：遇到的问题",
            )
      : trainingComposerStudyMode
        ? studyFocusText
          ? appUiCopy(layout.composerLanguage, "学习聚焦：{v}").replace("{v}", () => studyFocusText)
          : appUiCopy(layout.composerLanguage, "学习聚焦：当前卡片")
      : trainingComposerReturnMode
        ? returnModeText
          ? appUiCopy(layout.composerLanguage, "回流：{v}").replace("{v}", () => returnModeText)
          : appUiCopy(layout.composerLanguage, "回流：带回结果")
      : trainingComposerReflectMode
        ? trainingComposerReflectReason === "flash_answered"
          ? appUiCopy(layout.composerLanguage, "\u590d\u76d8\uff1a\u538b\u6210\u4e00\u6761\u89c4\u5219")
          : trainingComposerReflectReason === "skipped"
            ? appUiCopy(layout.composerLanguage, "\u590d\u76d8\uff1a\u6536\u7d27\u5165\u53e3")
            : trainingComposerReflectReason === "verification_passed"
              ? appUiCopy(layout.composerLanguage, "\u590d\u76d8\uff1a\u5df2\u9a8c\u8bc1\u7684\u89c4\u5219")
            : reflectFallbackText
              ? appUiCopy(layout.composerLanguage, "复盘：{v}").replace("{v}", () => reflectFallbackText)
              : appUiCopy(layout.composerLanguage, "复盘：收紧遇到的问题")
      : trainingComposerSelectedVerifyItem
        ? appUiCopy(layout.composerLanguage, "当前检查：{v}").replace("{v}", () => currentCheckText)
        : appUiCopy(layout.composerLanguage, "\u8bb0\u4e0b\u8fd9\u4e00\u8f6e\u7684\u7ed3\u679c\u3002")
    : resolvedUtilityComposerSummary;
  const laneAwareComposerSummary =
    trainingComposerTalkMode || composerUsesTrainingFlow
      ? resolvedComposerSummary
      : activeView === "resources"
        ? resolvedComposerSummary
        : activeView === "plan"
          ? activePlanComposerMode.summary
          : resolvedComposerSummary;
  const resolvedComposerAccessibilityLabel = trainingComposerTalkMode
    ? trainingComposerModeTextCopy.talkAccessibilityLabel
    : composerUsesTrainingFlow
    ? trainingComposerUsesAnswerMode
      ? trainingComposerModeTextCopy.answerAccessibilityLabel
      : trainingComposerPracticeInputMode
        ? trainingComposerModeTextCopy.genericAccessibilityLabel
      : trainingComposerStudyMode
        ? trainingComposerModeTextCopy.studyAccessibilityLabel
      : trainingComposerReturnMode
        ? trainingHandoffComposerTextCopy.returnAccessibilityLabel
      : trainingComposerReflectMode
        ? trainingHandoffComposerTextCopy.reflectAccessibilityLabel
      : trainingComposerModeTextCopy.genericAccessibilityLabel
    : t.composerAccessibility;
  const refinedComposerAccessibilityLabel = composerUsesTrainingFlow
    ? resolvedComposerAccessibilityLabel
    : activeView === "plan"
      ? appUiCopy(layout.composerLanguage, "提交计划讨论、生成或证据整理请求")
      : activeView === "resources"
        ? appUiCopy(layout.composerLanguage, "提交资料定位、整理、下载或转卡请求")
        : activeView === "coach"
          ? t.composerAccessibility
          : activeView === "training"
            ? trainingComposerModeTextCopy.genericAccessibilityLabel
          : appUiCopy(layout.composerLanguage, "提交当前视图请求");
  const laneAwareComposerAccessibilityLabel =
    trainingComposerTalkMode || composerUsesTrainingFlow
      ? resolvedComposerAccessibilityLabel
      : activeView === "plan"
        ? activePlanComposerMode.accessibilityLabel
        : activeView === "resources"
          ? refinedComposerAccessibilityLabel
          : refinedComposerAccessibilityLabel;
  const localizedTrainingComposerAccessibilityLabel =
    !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnAccessibilityLabel
      : !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReflectMode
        ? trainingHandoffComposerTextCopy.reflectAccessibilityLabel
        : laneAwareComposerAccessibilityLabel;
  const localizedTrainingComposerSubmitAriaLabel =
    !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnSubmitAriaLabel
      : !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReflectMode
        ? trainingHandoffComposerTextCopy.reflectSubmitAriaLabel
        : trainingComposerTalkMode || composerUsesTrainingFlow
          ? localizedTrainingComposerAccessibilityLabel
          : activeView === "training"
            ? trainingComposerModeTextCopy.genericAccessibilityLabel
          : activeView === "resources"
            ? refinedComposerAccessibilityLabel
          : appUiCopy(layout.composerLanguage, activeView === "coach" ? "发送消息" : "发送请求");
  const localizedTrainingComposerSummary =
    !trainingComposerTalkMode && composerUsesTrainingFlow && trainingComposerReturnMode
      ? trainingHandoffComposerTextCopy.returnSummary
      : laneAwareComposerSummary;
  const allowEmptyTrainingReturnSubmission =
    composerUsesTrainingFlow &&
    trainingComposerReturnMode &&
    trainingHandoffReturnRequired &&
    Boolean(activeTrainingCardId);
  // Compact single-card action surface (Phase-C training slice): the Start/
  // Verify buttons are rendered inside TrainingWorkbenchView from the
  // eight-language surface labels; the card reports status transitions and
  // verification requests through the handler below.
  const handleVerifyCurrentFileFromCard = () => {
    if (data.workspace?.isRemoteWorkspace && !isBrowserPreview) {
      // The controller owns the running guard, panel state and request identity.
      beginRemoteVerification(activeTrainingCardId ?? "");
      return;
    }
    if (isBrowserPreview) {
      setTrainingVerifyNotice(
        appUiCopy(layout.composerLanguage, "预览不能验证当前文件；真实工作区中将运行验证。"),
      );
      return;
    }
    handleVerifyTrainingFromIde();
  };
  // P1.4 candidate management: merge / mark important / priority. The host
  // command posts one management call to the sidecar; the card record and the
  // ledger stay server-owned. In preview the commands are observed but not
  // executed by the fixture.
  const handleTrainingLibraryAction = (
    cardId: string,
    action: TrainingCardLibraryAction,
    edits?: { prompt?: string; acceptanceCriteria?: string[] },
  ) => {
    void requestTrainingPersistence(trainerCommands.trainingCardLibrary, { cardId, action, ...edits })
      .catch((error) => setOperationMessage({
        tone: "error",
        message: sanitizeErrorSurfaceText(error instanceof Error ? error.message : String(error), layout.composerLanguage),
      }, "training"));
  };
  const handleMarkCandidateImportant = useCallback((cardId: string, important: boolean) => {
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.trainingCardMarkImportant, payload: { cardId, important } },
    });
  }, []);
  const handleSetCandidatePriority = useCallback((cardId: string, priority: number) => {
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.trainingCardSetPriority, payload: { cardId, priority } },
    });
  }, []);
  const handleMergeCandidateDuplicates = useCallback((keepCardId: string, duplicateCardIds: string[]) => {
    postMessage({
      type: "command/execute",
      payload: { commandId: trainerCommands.trainingCardMerge, payload: { keepCardId, duplicateCardIds } },
    });
  }, []);
  const handleStopRemoteVerification = () => {
    stopRemoteVerification();
  };
  const trainingVerifyFileVisible =
    hasTrainingCard && trainingCardType === "practice" && effectiveTrainingSubmode !== "learn-primer";
  // §26: Learning 下一步 → [开始练习] navigates to Training Focus.
  const trainingPrimaryAction = !hasTrainingCard ? undefined : (
    <button
      className="button button--accent"
      type="button"
      onClick={() => {
        setActiveView("training");
        const cardId = data.workspaceTrainingState?.selectedCardId?.trim();
        if (cardId && !isBrowserPreview && !trainingComposerReturnMode) {
          attemptLifecycle.startOrRecover(cardId, {
            filePath: data.liveContext?.activeFile ?? undefined,
          });
        }
      }}
    >
      <span className="button__icon" aria-hidden="true"><ArrowRightIcon size={14} /></span>
      <span>{appUiCopy(layout.composerLanguage, "开始练习")}</span>
    </button>
  );

  const showComposerTrainingVerify =
    activeView === "training" &&
    Boolean(hasTrainingCard) &&
    !leftoverTrainingHandoffChromeNotLive &&
    trainingCardType === "practice" &&
    trainingPracticeVerificationMode === "file" &&
    (trainingComposerPhase === "try" || trainingComposerPhase === "verify");
  const trainingCoachActionLabel = trainingHandoffReflectionRequired
    ? t.trainingRecordStep
    : trainingHandoffReturnRequired
      ? t.trainingReturnToCoach
      : trainingComposerPhase === "return"
      ? t.trainingReturnToCoach
      : trainingCoachBridge.ctaLabel;
  const trainingCoachAction = (
    <>
      <button
        className={`button ${trainingCardVerified || trainingCardBlocked ? "button--accent" : "button--ghost"}`}
        type="button"
        onClick={handleResumeTrainingInCoach}
      >
        <span className="button__icon" aria-hidden="true"><ChevronRightIcon size={14} /></span>
        <span>{trainingCoachActionLabel}</span>
      </button>
    </>
  );

  const renderResourcesView = () => {
    const versionCheck = resourceVersionCheck?.scope === composerSessionKey ? resourceVersionCheck : undefined;
    const copy = resourceVersionCopy[layout.composerLanguage];
    const currentResources = versionCheck ? new Map(liveResources.map((resource) => [resource.id, resource])) : undefined;
    return (
      <section className="resources-view">
        {versionCheck ? (
          <section className="unified-resource-versions" aria-label={copy.title} data-resource-version-check>
            <header className="resource-version-header">
              <strong>{copy.title}</strong>
              <button className="template-back" type="button" onClick={() => {
                resourceVersionCheckRequest.current?.abort();
                setResourceVersionCheck(undefined);
              }}>{copy.close}</button>
            </header>
            <p role="status" className="template-metadata">
              {versionCheck.phase === "checking" ? `${copy.checking} · ${versionCheck.items.length}/${versionCheck.total}`
                : versionCheck.phase === "interrupted" ? copy.interrupted
                : versionCheck.total === 0 ? copy.empty : `${versionCheck.items.length}/${versionCheck.total}`}
            </p>
            {versionCheck.items.length > 0 ? (
              <ul>{versionCheck.items.map((result) => {
                const resource = currentResources?.get(result.resource_id);
                const status = !resource ? "missing"
                  : (resource.versionId ?? "") !== result.version_id || (resource.contentHash ?? "") !== result.content_hash
                    ? "stale" : result.status;
                const basis = result.basis && (status === "changed" || status === "unchanged") ? copy.basis[result.basis] : "";
                return (
                  <li key={result.resource_id} data-resource-version-status={status}>
                    {status === "changed" ? (
                      <button className="template-back" type="button" onClick={() => {
                        setResourceVersionCheck(undefined);
                        setResourceRestoreContext({ surface: "detail", resourceId: result.resource_id });
                      }}>{result.title}</button>
                    ) : <span>{result.title}</span>}
                    <span className="template-metadata" title={result.version_id}>
                      {basis ? `${copy.status[status]} · ${basis}` : copy.status[status]}
                    </span>
                  </li>
                );
              })}</ul>
            ) : null}
          </section>
        ) : null}
        <Suspense
          fallback={<ViewFallback label={resourcesViewLabel(layout.composerLanguage)} language={layout.composerLanguage} />}
        >
          <ResourcesWorkbenchView
          language={layout.composerLanguage}
          resources={liveResources}
          researchBriefs={data.memory.researchBriefs}
          researchBriefToOpen={researchBriefToOpen?.workspaceId === data.memory.workspace?.workspaceId ? researchBriefToOpen : undefined}
          resourceSearch={data.resourceSearch}
          submittedSearchQuery={resourcesViewSearchQuery}
          onSearchQueryChange={setResourcesViewSearchQuery}
          onClearSearch={() => setResourcesViewSearchQuery("")}
          orientation={
            leftoverResourceLibraryListNotLive && resourcesOrientation
              ? {
                  ...resourcesOrientation,
                  why: appUiCopy(
                    layout.composerLanguage,
                    "资料库只显示已确认导入的资料。",
                  ),
                  primaryAction: "open_coach",
                  primaryActionLabel: t.openCoach,
                }
              : resourcesOrientation
          }
          leftoverNote={
            leftoverResourceLibraryListNotLive
              ? appUiCopy(layout.composerLanguage, "资料库只显示已确认导入的资料。")
              : undefined
          }
          onOrientationAction={handleResourcesOrientationAction}
          deletedResources={data.deletedResources}
          sandboxState={liveSandboxState}
          resourceWriteAccess={resourceWriteAccess}
          onChooseWorkspaceRoot={
            trainerWorkspaceAdmission?.status === "root-missing"
              ? () => runWorkspaceAdmissionCommand(trainerCommands.chooseTrainerWorkspaceRoot)
              : undefined
          }
          restoreContext={resourceRestoreContext}
          onDebugVisibleFacts={(facts) =>
            activeView === "resources" ? postDebugVisibleFacts({ activeView: "resources", resources: facts }) : undefined
          }
          organizationConfirm={
            resourceOrganizationPending?.pending && !leftoverResourceLibraryListNotLive
              ? {
                  operationCount: resourceOrganizationPending.operationCount,
                  onConfirm: () =>
                    postMessage({
                      type: "command/execute",
                      payload: {
                        commandId: trainerCommands.confirmResourceOrganization,
                        payload: { responseLanguage: layout.composerLanguage },
                      },
                    }),
                  onCancel: () =>
                    postMessage({
                      type: "command/execute",
                      payload: {
                        commandId: trainerCommands.cancelResourceOrganization,
                      },
                    }),
                }
              : undefined
          }
          isBrowserPreview={browserPreviewFixture}
          onStartTrainingFromResource={
            browserPreviewFixture ? undefined : requestResourceTrainingHandoff
          }
          onOpenTraining={() => setActiveView("training")}
          onAskCoach={(resourceIds) => {
            setSelectedResourceContextIds(resourceIds);
            setResourceConversationContextIds(resourceIds);
            setActiveView("coach");
            requestCoachComposerFocus();
          }}
          onJoinLearning={(resourceIds) => {
            const scope = composerDockDraftScope("plan", composerSessionKey);
            useWorkbenchState.getState().writeComposerResourceRefs(scope, resourceIds);
            setCoachPlanContext("explain");
            setActiveView("plan");
            requestCoachComposerFocus();
          }}
          initialResourceContextIds={selectedResourceContextIds}
          onResourceSelectionChange={handleResourceSelectionChange}
          onRestoreContextChange={setResourceRestoreContext}
          onSearchResources={
            isBrowserPreview
              ? browserPreviewFixture
                ? undefined
                : requestBrowserPreviewResourceSearch
              : requestResourceSearch
          }
          onImportFiles={() =>
            triggerResourceUpload({
              browserPreview: isBrowserPreview,
              payloadMode: "files",
              filesInputRef: uploadFilesInputRef,
              folderInputRef: uploadFolderInputRef,
            })
          }
          onImportFolder={() =>
            triggerResourceUpload({
              browserPreview: isBrowserPreview,
              payloadMode: "folder",
              folder: true,
              filesInputRef: uploadFilesInputRef,
              folderInputRef: uploadFolderInputRef,
            })
          }
          onImportWorkspace={
            isBrowserPreview
              ? undefined
              : () =>
                  triggerResourceUpload({
                    browserPreview: false,
                    payloadMode: "workspace",
                    filesInputRef: uploadFilesInputRef,
                    folderInputRef: uploadFolderInputRef,
                  })
          }
          onImportToFolder={
            isBrowserPreview
              ? undefined
              : (mode, targetFolder) =>
                  triggerResourceUpload({
                    browserPreview: false,
                    payloadMode: mode,
                    folder: mode === "folder",
                    targetFolder,
                    filesInputRef: uploadFilesInputRef,
                    folderInputRef: uploadFolderInputRef,
                  })
          }
          onImportUrl={() =>
            isBrowserPreview ? void handleBrowserUrlImport() : triggerResourceUpload({
              browserPreview: false,
              payloadMode: "url",
              filesInputRef: uploadFilesInputRef,
              folderInputRef: uploadFolderInputRef,
            })
          }
          onCaptureResource={
            isBrowserPreview && browserPreviewFixture
              ? // The fixture preview shows the entry but refuses to change real
                // resources: the dialog is reachable, the mutation is honest.
                async () => ({
                  ok: false,
                  message: appUiCopy(
                    layout.composerLanguage,
                    "浏览器预览不会改变真实资料。请在 VS Code 侧栏中操作。",
                  ),
                })
              : captureResourceIntoLibrary
          }
          captureFocusOptions={resourceCaptureFocusOptions}
          onOrganizeResource={
            isBrowserPreview && browserPreviewFixture ? undefined : organizeLibraryResource
          }
          onExportResource={
            isBrowserPreview && browserPreviewFixture ? undefined : exportLibraryResource
          }
          onMigrateLibrary={
            isBrowserPreview && browserPreviewFixture ? undefined : requestLibraryMigration
          }
          onListLibraryFolders={
            (isBrowserPreview && browserPreviewFixture) || activeView !== "resources"
              ? undefined
              : listLibraryFolders
          }
          onCreateLibraryFolder={
            isBrowserPreview && browserPreviewFixture ? undefined : createLibraryFolder
          }
          onRenameLibraryFolder={
            isBrowserPreview && browserPreviewFixture ? undefined : renameLibraryFolder
          }
          onDeleteLibraryFolder={
            isBrowserPreview && browserPreviewFixture ? undefined : deleteLibraryFolder
          }
          onRevealSavedPath={isBrowserPreview && browserPreviewFixture ? undefined : revealLibraryPath}
          isLiveBrowserPreview={isBrowserPreview && !browserPreviewFixture}
          onExpandToEditor={canOpenInEditor ? () => openViewInEditor("resources") : undefined}
          expandToEditorLabel={expandToEditorLabel}
          onOpenResource={(resourceId, options) =>
            postMessage({
              type: "resource/open",
              payload: { resourceId, ...options },
            })
          }
          onRefreshResources={
            isBrowserPreview
              ? () => {
                  postMessage({
                    type: "command/execute",
                    payload: {
                      commandId: trainerCommands.indexResources,
                    },
                  });
                }
              : requestResourceIndex
          }
          onRefreshDeletedResources={
            isBrowserPreview
              ? undefined
              : () => {
                  postMessage({
                    type: "command/execute",
                    payload: {
                      commandId: trainerCommands.refreshResourceTrash,
                    },
                  });
                }
          }
          onDeleteResources={
            isBrowserPreview
              ? undefined
              : (resourceIds) => requestResourceMutation("delete", resourceIds)
          }
          onRestoreResources={
            isBrowserPreview
              ? undefined
              : (resourceIds) => requestResourceMutation("restore", resourceIds)
          }
          deleteUnavailableReason={
            isBrowserPreview
              ? appUiCopy(layout.composerLanguage, "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u5220\u9664\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u6267\u884c\u3002")
              : undefined
          }
          restoreUnavailableReason={
            isBrowserPreview
              ? appUiCopy(layout.composerLanguage, "\u6d4f\u89c8\u5668\u9884\u89c8\u4e0d\u4f1a\u6062\u590d\u771f\u5b9e\u8d44\u6599\u3002\u8bf7\u5728 VS Code \u4fa7\u680f\u4e2d\u6267\u884c\u3002")
              : undefined
          }
          />
        </Suspense>

      </section>
    );
  };

  const trainingHintLadderForCard = !reviewArtifactForeground && hasTrainingCard && !trainingComposerReturnMode
    ? readTrainingCardList(boundTrainingCardFacts, "hintLadder", () => trainingHintLadder) : [];
  const handleTrainingHintReveal = (level: number) => {
    setComposerHintLevels((levels) => ({ ...levels, [activityDraftKey]: level }));
    handleHintReveal(level);
  };

  const renderTrainingView = (inline = false) => {
    const libraryCards = trainingState?.trainingCardCandidates ?? [];
    const hasLibrary = (!isBrowserPreview || !browserPreviewFixture) && libraryCards.some(
      (card) => !card.mergedInto && card.status !== "archived" && card.reviewState !== "rejected",
    );
    const title = hasRenderableTrainingCard
      ? readTrainingCardText(boundTrainingCardFacts, "title", () => pickFirstText(
          visibleTrainingCardTitle,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : liveTrainingHandoffChrome.cardTitle,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingHandoff?.cardTitle,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingNextHop?.cardTitle,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingNextHop?.title,
          liveTrainingTitle,
          formalPlanLive || liveTask ? resolvedCoachFocus : undefined,
        )) ?? trainingViewLabel(layout.composerLanguage)
      : trainingViewLabel(layout.composerLanguage);
    const currentStep = hasRenderableTrainingCard
      ? boundTrainingCardFacts
        ? boundTrainingCardFacts.text.problemStatement ??
          boundTrainingCardFacts.text.suggestedWorkspaceAction ??
          boundTrainingCardFacts.text.deliverable ?? ""
        : pickFirstText(
          trainingProblemStatement,
          trainingSuggestedWorkspaceAction,
          trainingDeliverables[0],
          selectedTrainingCardCandidate?.deliverable,
          selectedTrainingRouteCard?.deliverable,
        ) ?? ""
      : "";
    const localizedSuggestedWorkspaceAction = hasRenderableTrainingCard
      ? readTrainingCardText(boundTrainingCardFacts, "suggestedWorkspaceAction", () => trainingSuggestedWorkspaceAction)
      : undefined;
    const localizedScenario = hasRenderableTrainingCard
      ? boundTrainingCardFacts
        ? boundTrainingCardFacts.text.scenario ?? boundTrainingCardFacts.text.scenarioPack
        : pickFirstText(
          trainingScenario,
          trainingScenarioPackLabel,
        )
      : undefined;
    const localizedWhyNow = hasRenderableTrainingCard
      ? readTrainingCardText(boundTrainingCardFacts, "whyNow", () => liveTrainingWhy)
      : undefined;
    const localizedSourceSummary = hasRenderableTrainingCard
      ? pickFirstText(leftoverTrainingHandoffChromeNotLive
            ? undefined
            : liveTrainingHandoffChrome.handoffSummary,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingHandoff?.handoffSummary,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : liveTrainingHandoffChrome.nextHopHandoffSummary,
          leftoverTrainingHandoffChromeNotLive
            ? undefined
            : trainingState?.latestTrainingNextHop?.handoffSummary,
          liveTrainingCoachChrome,
          liveTrainingSource,
        )
      : undefined;
    const localizedCurrentFocus = hasTrainingCard
      // A matching card's technical focus remains authoritative across locale
      // changes, including a settings refresh that clears the recovered flag.
      ? readTrainingCardText(boundTrainingCardFacts, "focusArea", () => pickFirstText(
          selectedTrainingCardCandidate && selectedTrainingCardCandidate.cardId === activeTrainingCardId
            ? selectedTrainingCardCandidate.focusArea : undefined,
          selectedTrainingRouteCard && selectedTrainingRouteCard.cardId === activeTrainingCardId
            ? selectedTrainingRouteCard.focusArea : undefined,
        ) ?? pickFirstText(
          leftoverTrainingFocusChromeNotLive ? undefined : liveTrainingFocusChrome.latestLearningFocusArea,
          leftoverTrainingFocusChromeNotLive ? undefined : liveTrainingFocusChrome.cardFocusArea,
          leftoverTrainingFocusChromeNotLive
            ? undefined
            : liveTrainingFocusChrome.teachingDecisionFocusArea,
          leftoverTrainingFocusChromeNotLive
            ? undefined
            : liveTrainingFocusChrome.learnerStateActiveFocus,
          liveTrainingCurrentFocus,
          liveTrainingFocus,
        ) ?? pickFirstText(
          liveTrainingCurrentFocus,
          liveTrainingFocus,
        ))
      : undefined;

    const cardLibrary = !inline && hasLibrary ? (
          <TrainingCardLibrary
            language={layout.composerLanguage}
            cards={libraryCards}
            selectedCardId={activeTrainingCardId}
            busy={trainingPersistencePending}
            onAction={handleTrainingLibraryAction}
            onImportance={handleMarkCandidateImportant}
            onPriority={handleSetCandidatePriority}
            onMerge={handleMergeCandidateDuplicates}
          />
    ) : null;
    return (
      <section className={`training-view${inline ? " training-view--inline" : ""}`}>
        {!inline && !hasRenderableTrainingCard ? cardLibrary : null}
        <Suspense fallback={<ViewFallback label={t.training} language={layout.composerLanguage} />}>
          <TrainingWorkbenchView
          language={layout.composerLanguage}
          cardType={trainingCardType}
          trainingSubmode={effectiveTrainingSubmode}
          cardOnly={true}
          response={resolvedReviewArtifact ? (
            <SystemState kind="success" title={templateCopy[layout.composerLanguage].reviewRecorded}
              detail={trainingState?.reviewArtifact?.verifiedResult ?? trainingState?.reviewArtifact?.summary}
              action={{ label: templateCopy[layout.composerLanguage].askCoach, onClick: handleResumeTrainingInCoach }} />
          ) : (
            <InlinePracticeAnswer
              language={layout.composerLanguage}
              reflectMode={trainingComposerReflectMode}
              onFocusComposer={focusComposerInput}
              prompt={trainingComposerReflectMode ? (
                <MessageRichContent body={
                  // P4 review artifact foreground: the review's own summary is the
                  // recall ask — show it as the reflection prompt instead of an
                  // empty body when no candidate reflection prompt exists.
                  reviewArtifactForeground && trainingState?.reviewArtifact?.summary?.trim()
                    ? trainingState.reviewArtifact.summary
                    : readTrainingCardText(boundTrainingCardFacts, "reflectionPrompt", () => trainingReflectionPrompt) ?? ""
                } language={layout.composerLanguage} />
              ) : undefined}
            />
          )}
          cardId={activeTrainingCardId}
          selectedCardStatus={effectiveSelectedTrainingCardStatus}
          onCardStatusTransition={leftoverTrainingHandoffChromeNotLive ? undefined : handleTrainingCardStatusTransition}
          siblingCandidates={
            inline || leftoverTrainingHandoffChromeNotLive
              ? undefined
              : (trainingState?.trainingCardCandidates ?? []).filter((candidate) =>
                  candidate.cardId !== activeTrainingCardId &&
                  candidate.status === "candidate" &&
                  !candidate.mergedInto)
          }
          cardImportant={selectedTrainingCardCandidate?.important ?? false}
          cardPriorityValue={selectedTrainingCardCandidate?.cardPriority ?? 0}
          onMarkImportant={inline ? undefined : handleMarkCandidateImportant}
          onSetPriority={inline ? undefined : handleSetCandidatePriority}
          onMergeDuplicates={inline ? undefined : handleMergeCandidateDuplicates}
          onVerifyCurrentFile={reviewArtifactForeground ? undefined : handleVerifyCurrentFileFromCard}
          remoteVerification={remoteVerification}
          onStopRemoteVerification={handleStopRemoteVerification}
          onHintReveal={handleTrainingHintReveal}
          revealedHints={composerHintLevel}
          card={{
            title,
            currentStep,
            learningFamily: trainingLearningFamily,
            learningSubtype: trainingLearningSubtype,
            whyThisCard: reviewArtifactForeground ? trainingState?.reviewArtifact?.guardrail : localizedWhyNow,
            targetSkill: readTrainingCardText(boundTrainingCardFacts, "targetSkill", () => liveTrainingSkill),
            problemStatement: reviewArtifactForeground ? trainingState?.reviewArtifact?.summary
              : readTrainingCardText(boundTrainingCardFacts, "problemStatement", () => trainingProblemStatement),
            suggestedWorkspaceAction: localizedSuggestedWorkspaceAction,
            scenario: localizedScenario,
            whyNow: reviewArtifactForeground ? trainingState?.reviewArtifact?.guardrail : localizedWhyNow,
            sourceSummary: localizedSourceSummary,
            sourceDetail:
              hasRenderableTrainingCard
                ? pickFirstText(leftoverTrainingHandoffChromeNotLive
                      ? undefined
                      : liveTrainingHandoffChrome.handoffSummary,
                    leftoverTrainingHandoffChromeNotLive
                      ? undefined
                      : trainingState?.latestTrainingHandoff?.handoffSummary,
                    leftoverTrainingHandoffChromeNotLive
                      ? undefined
                      : liveTrainingHandoffChrome.nextHopHandoffSummary,
                  )
                : undefined,
            apiHints: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "apiHints", () => trainingApiHints) : [],
            selfCheck: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "selfCheck", () => trainingSelfCheck) : [],
            deliverable: reviewArtifactForeground ? trainingState?.reviewArtifact?.summary : hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "deliverable", () => trainingDeliverable) : undefined,
            deliverables: reviewArtifactForeground ? selectedTrainingCardCandidate?.learnerDeliverables ?? [] : hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "learnerDeliverables", () => trainingDeliverables) : [],
            validationMethod: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "validationMethod", () => trainingValidationMethod) : undefined,
            verificationMethod: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "verificationMethod", () => trainingVerificationMethod) : undefined,
            verifyItems: reviewArtifactForeground ? selectedTrainingCardCandidate?.verificationSteps ?? [] : hasTrainingCard ? boundTrainingCardFacts ? boundTrainingCardFacts.lists.verificationSteps ?? boundTrainingCardFacts.lists.acceptanceCriteria ?? [] : authoritativeVerifyItems : [],
            successSignal: reviewArtifactForeground ? trainingState?.reviewArtifact?.verifiedResult : hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "successSignal", () => trainingSuccessSignal) : undefined,
            returnWith: reviewArtifactForeground ? trainingState?.reviewArtifact?.nextSelfImplementationRule : hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "returnWith", () => trainingReturnWithText) : undefined,
            nextAfterCompletion: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "nextAfterCompletion", () => trainingNextAfterCompletionText) : undefined,
            fallbackAction: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "fallbackAction", () => trainingFallbackActionText) : undefined,
            filesToTouch: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "filesToTouch", () => trainingFilesToTouch) : [],
            hintLadder: trainingHintLadderForCard,
            commonMistakes: !reviewArtifactForeground && hasTrainingCard ? readTrainingCardList(boundTrainingCardFacts, "commonMistakes", () => trainingCommonMistakes) : [],
            stuckRecovery: reviewArtifactForeground ? trainingState?.reviewArtifact?.guardrail : hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "stuckRecovery", () => trainingStuckRecovery) : undefined,
            outcome: !reviewArtifactForeground && hasTrainingCard ? trainingOutcomeCard : undefined,
            nextHop:
              hasRenderableTrainingCard && !trainingRestoreForeground && !reviewArtifactForeground
                ? trainingNextHopCard
                : undefined,
            flashPrompt: trainingFlashPrompt,
            expectedSymbols: trainingCardType === "practice" ? readTrainingCardList(boundTrainingCardFacts, "expectedSymbols", () => practiceExpectedSymbols) : [],
            scenarioPackLabel: hasTrainingCard ? readTrainingCardText(boundTrainingCardFacts, "scenarioPack", () => trainingScenarioPackLabel) : undefined,
            currentFocus: localizedCurrentFocus,
          }}
          handoff={{
            latestTrainingHandoffStatus:
              reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : trainingState?.latestTrainingHandoff?.handoffStatus,
            latestTrainingVerificationState:
              reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : trainingState?.latestTrainingHandoff?.verificationState,
            latestTrainingLearningPhase:
              reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? selectedTrainingCardCandidate?.learningPhase
                : (trainingState?.latestTrainingHandoff?.learningPhase ??
                  selectedTrainingCardCandidate?.learningPhase),
            latestTrainingReliability:
              activeTrainingCardId && trainingState?.latestTrainingReliability?.cardId === activeTrainingCardId
                ? trainingState.latestTrainingReliability
                : undefined,
            reliabilityInFlight: trainingPersistencePending,
            latestTrainingNextHopStatus:
              reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : trainingState?.latestTrainingNextHop?.status,
            latestTrainingNextHopReason:
              !reviewArtifactForeground &&
              !trainingRestoreReplacesSelectedCard &&
              trainingState?.latestTrainingNextHop?.status === "blocked"
                ? trainingState.latestTrainingNextHop.statusReason
                : undefined,
            latestTrainingBlockedBy:
              leftoverTrainingHandoffChromeNotLive ||
              reviewArtifactForeground ||
              trainingRestoreReplacesSelectedCard
                ? undefined
                : liveTrainingHandoffChrome.blocker ??
                  trainingState?.latestTrainingHandoff?.blockedBy,
            latestVerifiedResult:
              reviewArtifactForeground
                ? undefined
                : trainingRestoreReplacesSelectedCard
                ? undefined
                : trainingState?.latestLearningVerifiedResult,
            latestLearningBlocker:
              (reviewArtifactForeground ? trainingState?.reviewArtifact?.blockedReason : undefined) ??
              (leftoverTrainingHandoffChromeNotLive || reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : pickFirstText(
                    liveTrainingHandoffChrome.blocker,
                    trainingState?.latestLearningBlocker,
                  ) || liveTrainingHandoffChrome.blocker || trainingState?.latestLearningBlocker || (
                    activeTrainingCardId && trainingState?.latestTrainingNextHop?.candidateId === activeTrainingCardId &&
                    trainingState?.latestTrainingNextHop?.status === "verification_required"
                      ? trainingState?.latestTrainingNextHop?.statusReason || trainingState?.latestTrainingNextHop?.summary
                      : undefined
                  )),
            verificationNotice: trainingVerifyNotice,
            latestLearningFollowup:
              leftoverTrainingHandoffChromeNotLive || reviewArtifactForeground || trainingRestoreReplacesSelectedCard
                ? undefined
                : pickFirstText(
                    liveTrainingHandoffChrome.followup,
                    trainingState?.latestLearningFollowup,
                  ),
          }}
          // The practice card lives inline in the conversation now, so the
          // due-review queue it opens must live there too: "Start review" is
          // reachable from the learning drawer's practice section.
          reviewItems={trainingReviewItems}
          onReviewQueueAction={(payload) => {
            if (payload.action === "accept") beginTrainingReview();
            handleReviewQueueAction(payload);
          }}
          reviewSummary={pickFirstText(
            formattedNextReviewDue,
            data.memory.reviewSummary,
          )}
          primaryAction={
            leftoverTrainingHandoffChromeNotLive ? (
              <button
                className="button button--accent"
                type="button"
                aria-label={t.openCoach}
                onClick={() => {
                  setActiveView("coach");
                  requestCoachComposerFocus();
                }}
              >
                <span className="button__icon" aria-hidden="true"><ChevronRightIcon size={14} /></span>
                <span>{t.openCoach}</span>
              </button>
            ) : trainingPrimaryAction
          }
          leftoverNote={leftoverTrainingHandoffChromeNotLive ? t.leftoverNotLive : undefined}
          actions={hasTrainingCard ? trainingCoachAction : undefined}
          emptyState={
            leftoverTrainingHandoffChromeNotLive || (hasLibrary && !workspaceSessionBlocked) ? undefined : (
            <SystemState kind={workspaceSessionBlocked ? "workspace-required" : "empty"} title={t.trainingEmptyTitle} detail={workspaceSessionBlockMessage || t.trainingEmptyDescription}
              action={{ label: workspaceSessionBlocked ? t.settings : COACH_MESSAGE_ACTION_LABELS[layout.composerLanguage]["training-card"], onClick: () => workspaceSessionBlocked ? openWorkspaceAdmission() : handleGenerateTrainingCard() }} />
            )
          }
          onNextCard={handleNextTrainingCard}
          />
        </Suspense>
        {!inline && hasRenderableTrainingCard ? cardLibrary : null}
      </section>
    );
  };

  // Domain controller owns priority; views receive one complete descriptor.
  const learningFacts: LearningFacts = {
    scope: {
      workspaceId: syncIdentity?.workspaceId ?? data.memory.workspace?.workspaceId ?? data.workspaceTrainingState?.workspaceId ?? composerSessionKey,
      sessionId: syncIdentity?.sessionId ?? data.sessionLabel,
      generation: String(syncIdentity?.generation ?? data.runtimeDataGeneration ?? "unversioned"),
    },
    language: layout.composerLanguage,
    workspace: { ready: !workspaceSessionBlocked, detail: workspaceSessionBlockMessage },
    provider: {
      ready: providerCanCoachNow,
      canGeneratePlan: providerCanMutateFormalPlan,
      detail: providerCanCoachNow ? formalPlanCapabilityMessage : providerBlockReason ?? providerSetupState.detail,
    },
    freshness: syncStatus,
    // An idle sidecar starts on demand; a verified provider still permits work.
    connection: data.connection.state === "connected" ||
      data.connection.state === "starting" ||
      (data.connection.state === "offline" && providerCanCoachNow)
        ? "ready" : "offline",
    connectionRecovery: {
      title: providerSetupState.title,
      label: t.openSettings,
      detail: providerSetupState.detail,
    },
    plan: {
      state: hasFormalPlan ? livePlanFrozen ? "frozen" : "active" : "absent",
      id: formalPlanLive ? data.plan.id : undefined,
      revision: formalPlanLive ? data.plan.revision : undefined,
      currentStep: verifyPlanAdvanceNext || recoveredDisplayFacts.currentStep ||
        (!recoveredRuntime ? liveCoachTaskChrome.currentStep || resolvedCoachNextStep : undefined),
      blocker: recoveredDisplayFacts.blockedReason,
      completion: planVerifyItems,
    },
    evidence: {
      pending: liveEvidenceQueue.pending.map(item => ({
        id: item.id, summary: item.summary, source: item.source,
        sourceCardId: item.sourceCardId, verified: item.verified,
        verificationSource: item.verificationSource, outcome: item.outcome,
      })),
      blockingId: planRuntimeStatus?.resumeState === "waiting"
        ? liveEvidenceBinding({ binding: data.memory.workspace?.latestPlanRuntime?.evidenceBinding,
            pendingIds: liveEvidenceQueue.pending.map(item => item.id), recovered: recoveredRuntime,
            currentStep: recoveredDisplayFacts.currentStep }) || undefined
        : undefined,
    },
    training: hasTrainingCard && activeTrainingCardId
      ? {
          workspaceId: trainingState?.workspaceId ?? data.memory.workspace?.workspaceId ?? "",
          cardId: activeTrainingCardId,
          title: readTrainingCardText(boundTrainingCardFacts, "title", () => visibleTrainingCardTitle ?? selectedTrainingCardCandidate?.title) ?? trainingViewLabel(layout.composerLanguage),
          status: normalizedTrainingNextHopStatus === "continued_in_chat" || resolvedReviewArtifact
            ? "completed" : trainingHandoffReturnRequired || trainingComposerReturnMode
              ? "return_pending" : "active",
        }
      : undefined,
    dueReview: planReviewItems.find(item => item.surfaceMode === "due"),
    firstLookStep: !recoveredRuntime ? liveFirstLookSummary?.recommendedNextStep : undefined,
    operationPending: streaming.isStreaming || trainingPersistencePending || Boolean(pendingLivePlanTaskMintRef.current),
  };
  const learningFactsRef = useRef(learningFacts);
  learningFactsRef.current = learningFacts;
  const learningPrimaryAction = resolveLearningPrimaryAction(learningFacts);
  const runLearningPrimaryAction = () => executeLearningPrimaryAction(
    learningPrimaryAction, learningFactsRef.current, {
      chooseWorkspace: openWorkspaceAdmission,
      configureProvider: openProviderSetup,
      restoreState: () => postMessage({ type: "request/bootstrap" }),
      openTraining: () => {
        closeLearningDrawer();
        setActiveView("coach");
        window.requestAnimationFrame(() => {
          document
            .querySelector('[data-inline-practice="true"]')
            ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
      },
      resumePlan: () => handlePlanOrientationAction("unfreeze_plan"),
      resolveBlocker: () => handlePlanOrientationAction("clear_blocker"),
      adoptEvidence: (evidenceId) => postMessage({ type: "command/execute", payload: {
        commandId: trainerCommands.evidenceAdopt, payload: { evidenceId },
      } }),
      continueStep: (step) => {
        closeLearningDrawer();
        if (planRuntimeStatus?.recovered && planRuntimeStatus.currentStep?.trim() === step) {
          handlePlanOrientationAction("continue_step");
        } else {
          requestPlanComposerGuidance(step, "stage");
        }
      },
      continueWithoutPlan: () => {
        closeLearningDrawer();
        handlePlanOrientationAction("continue_without_plan");
      },
      startReview: () => {
        useWorkbenchState.getState().openTrainingReviewQueue();
        closeLearningDrawer();
      },
      returnToCoach: () => {
        closeLearningDrawer();
        handleResumeTrainingInCoach();
      },
      generatePlan: () => {
        closeLearningDrawer();
        handlePlanOrientationAction("generate_plan");
      },
      confirmStep: () => openPlanComposerMode("explain"),
    },
  );
  const renderPlanView = () => (
    <section className="plan-view">
      <Suspense fallback={<ViewFallback label={t.plan} language={layout.composerLanguage} />}>
        <CoachPlanView
        plan={workspaceSessionBlocked ? null : visibleFormalPlan}
        showRoadmap={false}
        variant="drawer"
        primaryAction={{
          label: templateCopy[layout.composerLanguage].nextAction,
          title: learningPrimaryAction.title,
          detail: <div data-plan-fact="next">{learningPrimaryAction.detail}</div>,
          action: { id: learningPrimaryAction.intent, label: learningPrimaryAction.label,
            disabled: learningPrimaryAction.disabled, busy: learningPrimaryAction.busy,
            onClick: runLearningPrimaryAction },
        }}
        onPracticePlanStep={
          formalPlanLive &&
          !livePlanFrozen &&
          activePlanStage?.id &&
          data.plan.id &&
          recoveredDisplayFacts.currentStep?.trim() &&
          learningPrimaryAction.intent === "continue_step"
            ? handleGeneratePlanStepCard
            : undefined
        }
        primaryEvidenceId={learningPrimaryAction.target.evidenceId}
        projection={data.workspaceTrainingState?.skillProjection}
        onNavigateToView={setActiveView}
        onReviewQueueAction={handleReviewQueueAction}
        className="plan-pane"
        compactPrimary
        onExpandToEditor={canOpenInEditor ? () => openViewInEditor("plan") : undefined}
        expandToEditorLabel={expandToEditorLabel}
        leftoverNote={leftoverPlanNotLive
          ? learningPracticeReadyToContinue
            ? templateCopy[layout.composerLanguage].practiceReadyToContinue
            : t.leftoverNotLive
          : undefined}
        eyebrow=""
        title={
          workspaceSessionBlocked || !hasFormalPlan
            ? t.plan
            : formalPlanLive
              ? data.plan.title
              : livePlanTitle
        }
        titleNote={undefined}
        composerDraftReplacement={
          pendingPlanComposerDraftReplacement
            ? {
                source: pendingPlanComposerDraftReplacement.source,
                ...planComposerDraftReplacementCopy(
                  layout.composerLanguage,
                  pendingPlanComposerDraftReplacement.targetTitle,
                ),
                onConfirm: confirmPlanComposerDraftReplacement,
                onCancel: cancelPlanComposerDraftReplacement,
              }
            : undefined
        }
        goalLabel={t.currentFocus}
        goalSummary={
          // Stage/plan-level objective only. The concrete next-step sentence is
          // owned by the nextStep prop below — never duplicated here.
          <p>{resolvedCoachFocus || activeStageObjectiveText(activePlanStage, livePlanSummary)}</p>
        }
        liveStageIsCurrent={liveStageChrome.stageIsCurrent}
        goalHint={planText.goalHint}
        emptyState={
          <p className="muted">
            {planText.emptyState(coachViewLabel(layout.composerLanguage))}
          </p>
        }
        overviewLabel={planText.overviewLabel}
        currentStageLabel={planText.currentStageLabel}
        currentStageHint={planText.currentStageHint}
        nextStepLabel={t.currentTask}
        nextStepHint={planText.nextStepHint}
        stagesLabel={planText.stagesLabel}
        coachingStateLabel={t.coachState}
        pathLabel={planText.pathLabel}
        pathHint={planText.pathHint}
        whyNowLabel={planText.whyNowLabel}
        verifyLabel={t.acceptance}
        reviewWindowLabel={planText.reviewWindowLabel}
        planAtGlanceLabel={t.currentFocus}
        planAtGlanceHint={planText.planAtGlanceHint}
        stageProgressLabel={planText.stageProgressLabel}
        reviewQueueCountLabel={planText.reviewQueueCountLabel}
        currentFocusLabel={t.currentFocus}
        reviewFocusLabel={planText.reviewFocusLabel}
        pathSummaryLabel={planText.pathSummaryLabel}
        pathSummaryHint={planText.pathSummaryHint}
        returnLabel={planText.returnLabel}
        nowLabel={t.nextMove}
        revisitSummaryLabel={planText.revisitSummaryLabel}
        reviewLabel={planText.reviewLabel}
        weakSpotsLabel={t.weakSpots}
        winsLabel={t.recentWins}
        teachingObservationsLabel={t.teachingObservations}
        supportSummaryLabel={planText.supportSummaryLabel}
        supportHint={planText.supportHint}
        rememberedSummaryLabel={planText.rememberedSummaryLabel}
        notesLabel={planText.notesLabel}
        stageStatusLabels={{
          done: t.stageDone,
          active: t.stageActive,
          queued: t.stageQueued,
        }}
        actions={[
          {
            id: "plan-ask-coach",
            label: templateCopy[layout.composerLanguage].askCoach,
            tone: "ghost" as const,
            onClick: () => openPlanComposerMode("explain"),
          },
          {
            id: "plan-adjust",
            label: templateCopy[layout.composerLanguage].adjustPlan,
            tone: "ghost" as const,
            disabled: !providerCanMutateFormalPlan,
            detail: providerCanMutateFormalPlan ? undefined : formalPlanCapabilityMessage,
            onClick: () => openPlanComposerMode("generate"),
          },
          ...(liveEvidenceQueue.pending.length > 0 && formalPlanLive && !livePlanFrozen && !workspaceSessionBlocked
            ? [{ id: "plan-ask-evidence", tone: "ghost" as const,
                label: resolvePlanComposerCopy(layout.composerLanguage).modes.evidence.primaryPrompt.label,
                disabled: !providerCanCoachNow || syncStatus !== "current",
                onClick: () => openPlanComposerMode("evidence") }]
            : []),
          ...(!hasFormalPlan || !livePlanFrozen
            ? [{ id: "refresh-plan", label: t.generatePlan, tone: "ghost" as const,
                disabled: !providerCanMutateFormalPlan || workspaceSessionBlocked || syncStatus !== "current",
                detail: providerCanMutateFormalPlan ? undefined : formalPlanCapabilityMessage,
                onClick: () => handlePlanOrientationAction("generate_plan") }]
            : []),
          ...(hasFormalPlan && formalPlanLive && !livePlanFrozen
            ? [{ id: "plan-next-task", label: planText.nextTaskLabel, tone: "ghost" as const,
                disabled: !providerCanCoachNow || workspaceSessionBlocked || syncStatus !== "current",
                onClick: () => {
                  setActiveView("coach");
                  setComposerDraft(
                    defaultPromptText("next_task", layout.composerLanguage, activePlanStage?.title),
                  );
                  requestCoachComposerFocus();
                }, }]
            : []),
          ...(hasFormalPlan && formalPlanLive && !livePlanFrozen && !workspaceSessionBlocked
            ? [
                {
                  id: livePlanFrozen ? "resume-plan" : "freeze-plan",
                  label: livePlanFrozen ? appUiCopy(layout.composerLanguage, "解冻计划") : t.planFreeze,
                  tone: "ghost" as const,
                  onClick: () => {
                    pendingLivePlanTaskMintRef.current = {
                      commandId: trainerCommands.updatePlan,
                    };
                    setOperationMessage({
                      tone: "info",
                      message: livePlanUpdatePendingMessage(layout.composerLanguage),
                    }, "plan");
                    postMessage({
                      type: "plan/freeze",
                      payload: { frozen: !livePlanFrozen },
                    });
                  },
                },
              ]
            : []),
        ]}
        onStageSelect={(stage) => {
          requestPlanComposerGuidance(stage.title, "stage");
        }}
        nextStep={
          <>
            <p>
              {verifyPlanAdvanceNext ||
                (learningFacts.plan.currentStep || learningFacts.firstLookStep || latestArtifactTeaser)}
            </p>
            {runtimeBlockedReason ? (
              <p className="inline-note">{runtimeBlockedReason}</p>
            ) : null}
          </>
        }
        whyNow={
          <>
            <p>{planWhyNow || (recoveredRuntime ? planOrientation.why : undefined)}</p>
            {recoveredRuntime ? null : liveCoachTaskChrome.scopeBoundary ? (
              <p className="inline-note">{liveCoachTaskChrome.scopeBoundary}</p>
            ) : latestCoachArtifact?.focusArea ? (
              <p className="inline-note">{latestCoachArtifact.focusArea}</p>
            ) : runtimeCurrentStage?.goal ? (
              <p className="inline-note">{runtimeCurrentStage.goal}</p>
            ) : liveCoachStage ? (
              <p className="inline-note">{liveCoachStage}</p>
            ) : null}
          </>
        }
        verifyNow={
          planVerifyItems.length ? (
            <ul className="coach-plan-inline-list">
              {planVerifyItems.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : liveCoachTurnChrome.evaluationNextStep ? (
            <p>{liveCoachTurnChrome.evaluationNextStep}</p>
          ) : undefined
        }
        returnPath={<p>{planReturnPathLead}</p>}
        reviewWindow={
          <>
            <p>{runtimeNextAfterCurrent || planReviewWindowLead}</p>
            {runtimeNextAfterCurrent && planReviewReason ? (
              <p className="inline-note">{planReviewReason}</p>
            ) : !runtimeNextAfterCurrent && planReviewReason ? (
              <p className="inline-note">{planReviewReason}</p>
            ) : null}
          </>
        }
        coachingStateSummary={
          resolvedCoachStateSummary ? (
            <div className="coach-plan-view__signal-feed">
              {resolvedCoachStateSummary ? (
                <div className="coach-plan-view__support-feed-item">
                  <p>{resolvedCoachSummary ?? resolvedCoachStateSummary.split("\n").filter(Boolean)[0]}</p>
                </div>
              ) : null}
            </div>
          ) : undefined
        }
        rememberedSummary={rememberedCoachSummary}
        memorySummary={undefined}
        reviewRhythm={undefined}
        detailsSummaryLabel={planText.detailsSummaryLabel}
        dueReviewItems={planReviewItems}
        dueReviewSummaryLabel={planText.dueReviewItems(planReviewItems.length)}
        teachingObservations={data.memory.teachingObservations.slice(0, 3)}
        weakSpots={data.memory.weakSpots.slice(0, 3)}
        recentWins={data.memory.recentWins.slice(0, 3)}
        trajectoryLabel={planText.trajectoryLabel}
        trajectoryItems={(data.projectSources ?? []).slice(0, 3).map((source) => ({
          id: source.sourceUrl || source.title,
          label: source.title,
          value: source.repoHint || source.sourceUrl,
          detail: source.fitReason || source.trainingValue,
        }))}
        globalPlan={data.globalPlan}
        projectPlanLink={data.projectPlanLink}
        onCreateGlobalPlan={
          isBrowserPreview
            ? undefined
            : () =>
                postMessage({
                  type: "command/execute",
                  payload: { commandId: trainerCommands.createGlobalPlan },
                })
        }
        onLinkCurrentProjectPlan={
          isBrowserPreview
            ? undefined
            : () =>
                postMessage({
                  type: "command/execute",
                  payload: { commandId: trainerCommands.linkCurrentProjectPlan },
                })
        }
        projectSubplans={(data.memory.subplans ?? []).map((subplan) => {
          const activeStage =
            subplan.stages.find((stage) => stage.status === "active") ?? subplan.stages[0];
          return {
            id: subplan.id,
            title: subplan.title,
            status:
              subplan.status === "active"
                ? ("active" as const)
                : subplan.status === "draft"
                  ? ("pending" as const)
                  : ("frozen" as const),
            nextStep: activeStage?.objective,
            frozenReason:
              subplan.status === "completed"
                ? planText.subplanComplete
                : subplan.status === "archived"
                  ? planText.subplanArchived
                  : undefined,
          };
        })}
        projectSubplansLabel={planText.projectSubplansLabel}
        onProjectSubplanSelect={(subplan) => {
          requestPlanComposerGuidance(subplan.title, "project-subplan");
        }}
        evidenceQueue={liveEvidenceQueue}
        planChangeCandidates={data.memory.planChangeCandidates}
        evidenceActions={{
          onRefreshQueue: () =>
            postMessage({
              type: "command/execute",
              payload: { commandId: trainerCommands.evidenceRefreshQueue },
            }),
          onAdoptEvidence: (evidenceId) =>
            postMessage({
              type: "command/execute",
              payload: {
                commandId: trainerCommands.evidenceAdopt,
                payload: { evidenceId },
              },
            }),
          onDeferEvidence: (evidenceId, reason) =>
            postMessage({
              type: "command/execute",
              payload: {
                commandId: trainerCommands.evidenceDefer,
                payload: { evidenceId, reason },
              },
            }),
          onRejectEvidence: (evidenceId, reason) =>
            postMessage({
              type: "command/execute",
              payload: {
                commandId: trainerCommands.evidenceReject,
                payload: { evidenceId, reason },
              },
            }),
        }}
        />
        </Suspense>
    </section>
  );

  const learningSummary = useMemo(
    () => deriveLearningSummary({
      language: layout.composerLanguage,
      planTitle: livePlanTitle,
      currentStep: learningFacts.plan.currentStep,
      frozen: livePlanFrozen,
      dueCount: planReviewItems.filter((item) => item.surfaceMode !== "ahead" && item.surfaceMode !== "digest").length,
      dueCardTitle: hasTrainingCard ? visibleTrainingCardTitle : undefined,
      projection: data.workspaceTrainingState?.skillProjection,
    }),
    [
      data.workspaceTrainingState?.skillProjection,
      hasTrainingCard,
      layout.composerLanguage,
      learningFacts.plan.currentStep,
      livePlanFrozen,
      livePlanTitle,
      planReviewItems,
      visibleTrainingCardTitle,
    ],
  );

  const learningPracticeReadyToContinue = Boolean(
    boundTrainingCardFacts?.bound !== false && boundTrainingCardFacts && trainingCardType === "practice" && recoveredRuntime &&
    syncStatus === "current" && learningPrimaryAction.intent === "resume_training" &&
    learningPrimaryAction.target.cardId === boundTrainingCardFacts.cardId &&
    !learningPrimaryAction.disabled && !learningPrimaryAction.busy,
  );

  return {
    renderContextualResultRail,
    renderDockedView,
    renderCoachRootView,
    composerSurfaceHint,
    blockedComposerFallback,
    blockedComposerPresenceDetail,
    blockedComposerPresenceCopy,
    unifiedCopy,
    trainingFilePracticeTextCopy,
    trainingHandoffComposerTextCopy,
    resolvedTrainingComposerPlaceholder,
    resolvedCompactUtilityComposerPlaceholder,
    localizedTrainingComposerAccessibilityLabel,
    localizedTrainingComposerSubmitAriaLabel,
    localizedTrainingComposerSummary,
    allowEmptyTrainingReturnSubmission,
    handleVerifyCurrentFileFromCard,
    trainingVerifyFileVisible,
    showComposerTrainingVerify,
    renderResourcesView,
    trainingHintLadderForCard,
    learningPrimaryAction,
    runLearningPrimaryAction,
    renderPlanView,
    learningSummary,
  };
}
