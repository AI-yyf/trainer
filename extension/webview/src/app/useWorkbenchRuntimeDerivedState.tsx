import {
  useCallback,
  useEffect,
  useMemo,
  useRef
} from "react";

import { trainerCommands } from "../../../../shared/src/commands";
import {
  derivePlanOrientation,
  formalPlanIsLiveRuntimeIdentity,
  formalTaskIsLiveRuntimeIdentity,
  independentTrainingSelectionIsLive,
  leftoverCoachConversationIsNotLive,
  leftoverCoachTurnChromeIsNotLive,
  leftoverFirstLookHeadlineIsNotLive,
  leftoverMintingSuggestedActionsAreNotLive,
  leftoverResourceLibraryListIsNotLive,
  leftoverResourceSandboxStateIsNotLive,
  leftoverResourceSelectedDetailIsNotLive,
  leftoverSettingsLearnerProjectOnboardingIsNotLive,
  leftoverSettingsProfileRhythmIsNotLive,
  leftoverSuggestedActionsIsNotLive,
  leftoverTaskGuideFocusIsNotLive,
  leftoverTrainingHandoffChromeIsNotLive,
  leftoverTransferSkillIsNotLive,
  liveEvidenceBinding,
  liveFormalPlanCadence,
  liveFormalPlanFrozen,
  liveFormalPlanStages,
  liveFormalPlanSummary,
  liveFormalPlanTitle,
  liveTrainingFocusFallback,
  liveTrainingFormalSummary,
  liveTrainingSourceFallback,
  liveTrainingTitleFallback,
  lockRecoveredPlanVerifyItems,
  preferRecoveredCoachTaskChrome,
  preferRecoveredCoachTurnChrome,
  preferRecoveredPlanRuntimeFacts,
  preferRecoveredTransferSkill,
  pressureAdaptsWithoutInventingLiveObjects,
  resolveLivePlanStageChrome,
  scopeEvidenceQueueToRuntimeStep,
  streakAdaptsWithoutInventingLiveObjects,
  type PlanOrientationAction
} from "../../../../shared/src/planOrientationGovernance";
import { resolveResourceOpenTarget } from "../../../../shared/src/resourceOpen";
import { resourceRecordIsAcknowledgedUpload } from "../../../../shared/src/resourceWorkbenchGovernance";
import {
  deriveResourcesOrientation,
  resolveResourcesBindingIds,
  type ResourcesOrientationAction,
} from "../../../../shared/src/resourcesOrientationGovernance";
import { normalizeTransferSkillStateRecord } from "../../../../shared/src/transferSkillGovernance";
import {
  planRuntimeStatusFromRecovery
} from "../../../../shared/src/workspaceRecoveryGovernance";
import type { PlanReviewItem } from "../components/plan/CoachPlanView";
import { formatReviewDueLabel } from "../components/settings/useCoachSettingsViewState";
import { composerDockDraftScope } from "../lib/composerDock";
import { normalizeTrainingStateTextFields } from "../lib/hostText";
import {
  appUiCopy
} from "../lib/i18n/appUiCopy";
import { resolvePlanComposerCopy } from "../lib/i18n/planComposerCopy";
import { sanitizeBogusLearningStep } from "../lib/learningSummary";
import { resolveTurnNextStepRequiresConfirmation } from "../lib/nextStepConfirmation";
import {
  postMessage
} from "../lib/vscode";
import {
  type PlanComposerMode
} from "./useLearningPlanController";

// ContextMenu type imported from useMenuState
import {
  type WorkbenchCtxAfterE2
} from "./App";
import {
  WorkbenchDataSnapshot,
  compactCoachLine,
  isLanguageAlignedUiText,
  isTerminallyTruncatedText,
  livePlanUpdatePendingMessage,
  localizeConversationMessage,
  normalizeInlineComparisonText,
  restoredTrainingCard,
  toPlanReviewItem,
  triggerResourceUpload
} from "./appHelpers";

export function useWorkbenchRuntimeDerivedState(ctx: WorkbenchCtxAfterE2) {
  const {
    planComposerMode,
    data,
    layout,
    trainingRestoreContext,
    setActiveView,
    closeLearningDrawer,
    setComposerDraft,
    setOperationMessage,
    optimisticTurns,
    setCoachContextTransition,
    setPlanComposerMode,
    setCoachPlanContext,
    requestResourceIndex,
    streaming,
    isBrowserPreview,
    activeView,
    t,
    sendRecoveredPlanResumeRef,
    composerSessionKey,
    selectedResourceContextIds,
    resourceConversationContextIds,
    coachRuntimeContextSignatureRef,
    uploadFilesInputRef,
    uploadFolderInputRef,
    pendingLivePlanTaskMintRef,
    requestCoachComposerFocus,
    draft,
    resourcesViewSearchQuery,
  } = ctx;
  const hasFormalPlan = data.hasFormalPlan;
  const activePlanStage = hasFormalPlan
    ? (data.plan.currentStageId
        ? data.plan.stages.find((stage) => stage.id === data.plan.currentStageId)
        : undefined) ??
      data.plan.stages.find((stage) => stage.status === "active") ??
      data.plan.stages[0]
    : undefined;
  const planRuntimeStatus = data.planRuntimeStatus;
  const recoveredRuntime =
    planRuntimeStatus?.recovered === true ||
    Boolean(
      planRuntimeStatusFromRecovery(
        data.memory.workspace?.latestPlanRuntime,
        data.memory.workspace?.workspaceId ?? data.workspaceTrainingState?.workspaceId ?? "",
      ),
    );
  const runtimeCurrentStage = planRuntimeStatus?.currentStage;
  const runtimeCurrentThread = planRuntimeStatus?.currentMainThread;
  const leftoverChromeIdentity = {
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
    runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
    planId: data.plan.id,
    planCurrentStep: data.plan.currentStep,
  };
  const leftoverTaskChromeNotLive = leftoverTaskGuideFocusIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: leftoverChromeIdentity.runtimeCurrentStep,
  });
  const independentTrainingSelectionLive = independentTrainingSelectionIsLive({
    workspaceId: data.memory.workspace?.workspaceId,
    selectedCardId: data.workspaceTrainingState?.selectedCardId,
    selection: data.memory.workspace?.liveTrainingSelection,
  });
  const explicitTrainingRestoreLive = Boolean(
    trainingRestoreContext?.target &&
      restoredTrainingCard(
        normalizeTrainingStateTextFields(data.workspaceTrainingState),
        trainingRestoreContext,
      ),
  );
  const leftoverTrainingHandoffChromeNotLive = leftoverTrainingHandoffChromeIsNotLive(
    leftoverChromeIdentity,
  ) && !independentTrainingSelectionLive && !explicitTrainingRestoreLive;
  const leftoverResourceSelectedDetailNotLive = leftoverResourceSelectedDetailIsNotLive(
    leftoverChromeIdentity,
  );
  const leftoverResourceSandboxStateNotLive = leftoverResourceSandboxStateIsNotLive(
    leftoverChromeIdentity,
  );
  const leftoverResourceLibraryListNotLive =
    leftoverResourceLibraryListIsNotLive({
      recovered: recoveredRuntime,
      runtimeCurrentStep: leftoverChromeIdentity.runtimeCurrentStep,
    }) || leftoverTrainingHandoffChromeNotLive;
  const leftoverSettingsProfileRhythmNotLive = !data.sessionHistoryRestored && leftoverSettingsProfileRhythmIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverSettingsLearnerProjectOnboardingNotLive = !data.sessionHistoryRestored && leftoverSettingsLearnerProjectOnboardingIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverCoachConversationNotLive = !data.sessionHistoryRestored && leftoverCoachConversationIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverSuggestedActionsNotLive = leftoverSuggestedActionsIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverFirstLookHeadlineNotLive = leftoverFirstLookHeadlineIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const leftoverTransferSkillNotLive = leftoverTransferSkillIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const liveTransferState = preferRecoveredTransferSkill({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
    transfer:
      normalizeTransferSkillStateRecord(data.workspaceTrainingState?.latestTransferState) ??
      normalizeTransferSkillStateRecord(data.memory.workspace?.latestTransferState),
  });
  const liveConversation = leftoverCoachConversationNotLive ? [] : data.conversation;
  const liveFirstLookSummary = leftoverFirstLookHeadlineNotLive
    ? undefined
    : data.memory.workspaceUnderstanding?.firstLookSummary;
  const firstLookSummary = liveFirstLookSummary;
  const localizedConversation = useMemo(
    () => liveConversation.map((message) => localizeConversationMessage(message, t, layout.composerLanguage)),
    [layout.composerLanguage, liveConversation, t],
  );
  // Conversation length when the current stream started. The completion patch
  // merges the finished turn into the conversation while the streaming UI is
  // still up; entries past this base are represented by the optimistic echo
  // and the live streaming slot so nothing remounts at completion.
  const streamBaseLengthRef = useRef<number | null>(null);
  if (streaming.isStreaming) {
    if (streamBaseLengthRef.current === null) {
      streamBaseLengthRef.current = data.conversation.length;
    }
  } else {
    streamBaseLengthRef.current = null;
  }
  const coachRenderConversation = useMemo(() => {
    let list = localizedConversation;
    if (
      streaming.isStreaming &&
      streamBaseLengthRef.current !== null &&
      list.length > streamBaseLengthRef.current
    ) {
      // Hide only the duplicate assistant reply that the live streaming slot
      // already renders. The user's just-sent turn must stay visible even when
      // it lands in the snapshot after the stream began.
      list = list.filter(
        (message, index) =>
          index < (streamBaseLengthRef.current ?? 0) || message.role === "user",
      );
    }
    // Learning replies are no longer a separate lane: every turn belongs to
    // the one conversation. sourceView remains provenance, not a filter.
    const now = Date.now();
    const pendingTurns = optimisticTurns.filter((entry) => now - entry.createdAt <= 120_000);
    const pendingMessages = pendingTurns
      .filter((entry) => {
        // Confirm against the raw server conversation; the localized list may
        // rewrite bodies but never reorders or drops entries.
        if (entry.baseLength >= liveConversation.length) {
          return true;
        }
        return !liveConversation
          .slice(entry.baseLength)
          .some((item) => item.role === "user" && item.body.trim() === entry.body.trim());
      })
      .map((entry) => ({
        id: entry.id,
        role: "user" as const,
        author: t.you,
        body: entry.body,
        ...(entry.imagePreviews?.length ? { imagePreviews: entry.imagePreviews } : {}),
        timestamp: "",
      }));
    return pendingMessages.length > 0 ? [...list, ...pendingMessages] : list;
  }, [liveConversation, localizedConversation, optimisticTurns, streaming.isStreaming, t]);
  const liveCoachTaskChrome = preferRecoveredCoachTaskChrome({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
    taskTitle: data.task.title,
    ideaSummary: data.implementationGuide?.ideaSummary,
    scopeBoundary: data.implementationGuide?.scopeBoundary,
    guideCurrentStep: data.implementationGuide?.currentStep,
    teachingGoal: data.implementationGuide?.teachingGoal,
    successSignal: data.implementationGuide?.successSignal,
    fallbackStep: data.implementationGuide?.fallbackStep,
    currentFocus: data.coachFocus?.currentFocus,
    activeTask: data.coachFocus?.activeTask,
    nextStep: data.coachFocus?.nextStep,
    activeStage: data.coachFocus?.activeStage,
  });
  const leftoverCoachTurnChromeNotLive = leftoverCoachTurnChromeIsNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
  });
  const latestCoachArtifact = useMemo(() => {
    const preferredArtifactKinds = new Set([
      "idea_implementation",
      "project_adaptation",
      "project_idea",
      "principle",
      "plan_update",
      "next_step",
      "review",
    ]);

    for (let index = data.conversation.length - 1; index >= 0; index -= 1) {
      const message = data.conversation[index];
      if (message.role !== "assistant" || !message.artifacts?.length) {
        continue;
      }

      const preferredArtifact = message.artifacts.find((artifact) =>
        preferredArtifactKinds.has(artifact.kind),
      );
      if (preferredArtifact) {
        return preferredArtifact;
      }

      return message.artifacts[0];
    }

    return undefined;
  }, [data.conversation]);
  // Grounding downgrade (DESIGN.md §2.5): union of the webview-visible
  // carriers for the latest turn — host-mapped coach turn / next-step hint and
  // the streaming terminal frame. Message-level artifact metadata is read by
  // the bubble itself.
  const coachTurnNextStepRequiresConfirmation = resolveTurnNextStepRequiresConfirmation({
    coachTurnRequiresConfirmation: data.coachTurn?.requiresConfirmation,
    nextStepHintRequiresConfirmation: data.nextStepHint?.requiresConfirmation,
    streamingCompletionRequiresConfirmation: streaming.completionNextStepRequiresConfirmation,
  });
  const liveCoachTurnChrome = preferRecoveredCoachTurnChrome({
    recovered: recoveredRuntime,
    runtimeCurrentStep: planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep,
    coachTurnNextStep: data.coachTurn?.nextStep,
    coachTurnSummary: data.coachTurn?.summary,
    coachTurnTeachingGoal: data.coachTurn?.teachingGoal,
    coachTurnEncouragement: data.coachTurn?.encouragement,
    coachTurnActiveStage: data.coachTurn?.activeStage,
    coachingStateNextStep: data.coachingState?.nextStep,
    coachingStateSummary: data.coachingState?.summary,
    coachingStateTeachingGoal: data.coachingState?.teachingGoal,
    coachingStateEncouragement: data.coachingState?.encouragement,
    evaluationNextStep: data.evaluation.nextStep,
    nextStepHintTitle: data.nextStepHint?.title,
    nextStepHintSummary: data.nextStepHint?.summary,
    resumeThread: data.coachTurn?.resumeThread ?? data.coachingState?.resumeThread,
    supportStrategy: data.coachTurn?.supportStrategy ?? data.coachingState?.supportStrategy,
    reviewQueueSummary:
      data.coachTurn?.reviewQueueSummary ??
      data.reviewQueueSummary ??
      planRuntimeStatus?.reviewQueueSummary,
    artifactTeaser: latestCoachArtifact?.teaser,
    artifactRationale: latestCoachArtifact?.rationale,
    continuitySummary: data.coachFocus?.continuitySummary,
    coachJudgmentSummary: planRuntimeStatus?.coachJudgment?.summary,
    coachJudgmentTeachingGoal: planRuntimeStatus?.coachJudgment?.teachingGoal,
  });
  const formattedNextReviewDue = useMemo(
    () => formatReviewDueLabel(data.nextReviewDue, layout.composerLanguage),
    [data.nextReviewDue, layout.composerLanguage],
  );
  const activeThreadFocus = data.memory.activeThread?.focusArea;
  const activeThreadSummary = data.memory.activeThread?.summary;
  const activeThreadNextStep = data.memory.activeThread?.nextStep;
  const memoryEvidence = (data as WorkbenchDataSnapshot).memory.memoryEvidence.slice(0, 2);
  const resolvedCoachSummary =
    liveCoachTurnChrome.coachJudgmentSummary ??
    liveCoachTurnChrome.coachTurnSummary ??
    (leftoverCoachTurnChromeNotLive ? undefined : activeThreadSummary) ??
    liveCoachTurnChrome.coachingStateSummary ??
    liveCoachTaskChrome.currentFocus;
  const resolvedCoachNextStep = sanitizeBogusLearningStep(
    planRuntimeStatus?.nextTrainingAction ??
      runtimeCurrentThread?.nextStep ??
      liveCoachTurnChrome.coachTurnNextStep ??
      (leftoverCoachTurnChromeNotLive ? undefined : activeThreadNextStep) ??
      liveCoachTurnChrome.coachingStateNextStep ??
      liveCoachTaskChrome.nextStep ??
      (leftoverTaskChromeNotLive ? undefined : data.task.nextActionLabel),
  );
  const resolvedCoachReview = leftoverCoachTurnChromeNotLive
    ? undefined
    : liveCoachTurnChrome.reviewQueueSummary ??
      data.coachFocus?.reviewRhythm ??
      data.memory.reviewRhythm;
  const resolvedCoachFocus =
    runtimeCurrentThread?.focusArea ??
    (leftoverTaskChromeNotLive ? undefined : activeThreadFocus) ??
    liveCoachTaskChrome.currentFocus ??
    liveCoachTaskChrome.activeTask ??
    (leftoverTaskChromeNotLive ? undefined : data.memory.currentFocus);
  const resolvedCoachStage =
    runtimeCurrentStage?.title ??
    liveCoachTaskChrome.activeStage ??
    liveCoachTurnChrome.coachTurnActiveStage;
  const latestArtifactTeaser = liveCoachTurnChrome.artifactTeaser;
  const runtimeCurrentStepRaw = planRuntimeStatus?.currentStep ?? runtimeCurrentThread?.currentStep;
  const runtimeWhyNowRaw = planRuntimeStatus?.whyNow ?? runtimeCurrentThread?.whyNow;
  const runtimeCurrentStep = isLanguageAlignedUiText(layout.composerLanguage, runtimeCurrentStepRaw)
    ? sanitizeBogusLearningStep(runtimeCurrentStepRaw)
    : undefined;
  const runtimeWhyNow = isLanguageAlignedUiText(layout.composerLanguage, runtimeWhyNowRaw)
    ? runtimeWhyNowRaw
    : undefined;
  const runtimeVerifyItems = useMemo(
    () =>
      [
        ...(planRuntimeStatus?.verifyMethod ?? []),
        ...(runtimeCurrentThread?.verifyMethod ?? []),
      ].filter((item, index, array): item is string => Boolean(item) && array.indexOf(item) === index),
    [planRuntimeStatus?.verifyMethod, runtimeCurrentThread?.verifyMethod],
  );
  const runtimeBlockedReason =
    planRuntimeStatus?.blockedReason ??
    runtimeCurrentThread?.blockedReason ??
    runtimeCurrentThread?.blocker;
  const runtimeNextAfterCurrent =
    planRuntimeStatus?.nextAfterCurrent ?? runtimeCurrentThread?.nextAfterCurrent;
  const recoveredDisplayFacts = useMemo(
    () =>
      preferRecoveredPlanRuntimeFacts({
        recovered: recoveredRuntime,
        runtime: {
          currentStep: runtimeCurrentStep,
          whyNow: runtimeWhyNow,
          nextAfterCurrent: runtimeNextAfterCurrent,
          blockedReason: runtimeBlockedReason,
          verifyMethod: runtimeVerifyItems,
        },
        plan: {
          currentStep: sanitizeBogusLearningStep(data.plan.currentStep),
          whyNow: data.plan.whyNow,
          nextAfterCurrent: data.plan.nextAfterCurrent,
          blockedReason: data.plan.blockedReason,
          verifyMethod: data.plan.verifyMethod,
        },
      }),
    [
      data.plan.blockedReason,
      data.plan.currentStep,
      data.plan.nextAfterCurrent,
      data.plan.verifyMethod,
      data.plan.whyNow,
      recoveredRuntime,
      runtimeBlockedReason,
      runtimeCurrentStep,
      runtimeNextAfterCurrent,
      runtimeVerifyItems,
      runtimeWhyNow,
    ],
  );
  const formalPlanIdentity = useMemo(
    () => ({
      recovered: recoveredRuntime,
      runtimeCurrentStep: runtimeCurrentStepRaw,
      planCurrentStep: data.plan.currentStep,
      runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
      planId: data.plan.id,
    }),
    [
      data.memory.workspace?.latestPlanRuntime?.planId,
      data.plan.currentStep,
      data.plan.id,
      runtimeCurrentStepRaw,
      recoveredRuntime,
    ],
  );
  const formalPlanLive = formalPlanIsLiveRuntimeIdentity(formalPlanIdentity);
  const livePlanFrozen = liveFormalPlanFrozen({
    ...formalPlanIdentity,
    frozen: data.plan.frozen,
  });
  const livePlanTitle = liveFormalPlanTitle({
    ...formalPlanIdentity,
    planTitle: data.plan.title,
  });
  const livePlanSummary = liveFormalPlanSummary({
    ...formalPlanIdentity,
    planSummary: data.plan.summary,
  });
  const liveTrainingSummary = liveTrainingFormalSummary({
    ...formalPlanIdentity,
    planSummary: data.plan.summary,
  });
  const liveTrainingSource = liveTrainingSourceFallback({
    ...formalPlanIdentity,
    planSummary: data.plan.summary,
  });
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: recoveredRuntime,
    runtimeCurrentStep: recoveredDisplayFacts.currentStep,
    taskTitle: data.task.title,
  });
  const leftoverSuggestedActionNotLive =
    (Boolean(recoveredRuntime) && !formalPlanLive && !liveTask) ||
    streakAdaptsWithoutInventingLiveObjects({
      failureStreak: data.memory.coachingAdaptation?.failureStreak,
      successStreak: data.memory.coachingAdaptation?.successStreak,
      streakBlocksLiveObjectMint:
        data.memory.coachingAdaptation?.streakBlocksLiveObjectMint === true ||
        data.coachFocus?.streakBlocksLiveObjectMint === true,
      livePlan: formalPlanLive,
      liveTask,
      liveCard: Boolean(data.workspaceTrainingState?.selectedCardId?.trim()),
    }) ||
    pressureAdaptsWithoutInventingLiveObjects({
      timeBudget: data.memory.coachingAdaptation?.timeBudget,
      taskUrgency: data.memory.coachingAdaptation?.taskUrgency,
      pressureBlocksLiveObjectMint:
        data.memory.coachingAdaptation?.pressureBlocksLiveObjectMint === true ||
        data.coachFocus?.pressureBlocksLiveObjectMint === true,
      livePlan: formalPlanLive,
      liveTask,
      liveCard: Boolean(data.workspaceTrainingState?.selectedCardId?.trim()),
    }) ||
    data.memory.coachingAdaptation?.closedLoopReturnBlocksTaskMint === true ||
    data.coachFocus?.closedLoopReturnBlocksTaskMint === true;
  const leftoverMintingSuggestedActionsNotLive = leftoverMintingSuggestedActionsAreNotLive({
    recovered: recoveredRuntime,
    runtimeCurrentStep: recoveredDisplayFacts.currentStep,
    runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
    planId: data.plan.id,
    planCurrentStep: data.plan.currentStep,
    taskTitle: data.task.title,
  });
  const liveSuggestedActions = leftoverSuggestedActionsNotLive
    ? []
    : leftoverMintingSuggestedActionsNotLive || leftoverSuggestedActionNotLive
      ? data.suggestedActions.filter(
          (item) => !["plan", "task", "next_task", "card"].includes(String(item.action ?? "")),
        )
      : data.suggestedActions;
  const liveTrainingTitle = liveTrainingTitleFallback({
    ...formalPlanIdentity,
    planTitle: data.plan.title,
    taskTitle: data.task.title,
  });
  const liveTrainingFocus = liveTrainingFocusFallback({
    ...formalPlanIdentity,
    taskTitle: data.task.title,
    coachFocus: resolvedCoachFocus,
    memoryFocus: data.memory.currentFocus,
  });
  const livePlanStages = liveFormalPlanStages({
    ...formalPlanIdentity,
    stages: data.plan.stages,
  });
  const livePlanCadence = liveFormalPlanCadence({
    ...formalPlanIdentity,
    cadence: data.plan.cadence,
  });
  const liveCoachStage =
    resolvedCoachStage ?? (formalPlanLive ? activePlanStage?.title : undefined);
  const liveStageChrome = useMemo(
    () =>
      resolveLivePlanStageChrome({
        recovered: recoveredRuntime,
        runtimeCurrentStep: recoveredDisplayFacts.currentStep,
        planCurrentStep: data.plan.currentStep,
        planStageTitle: activePlanStage?.title,
        planStageGoal: activePlanStage?.objective,
        runtimePlanId: formalPlanIdentity.runtimePlanId,
        planId: formalPlanIdentity.planId,
      }),
    [
      activePlanStage?.objective,
      activePlanStage?.title,
      data.plan.currentStep,
      formalPlanIdentity.planId,
      formalPlanIdentity.runtimePlanId,
      recoveredDisplayFacts.currentStep,
      recoveredRuntime,
    ],
  );
  const leftoverPlanNotLive = Boolean(recoveredRuntime) && !formalPlanLive;
  const visibleFormalPlan = useMemo(() => {
    if (!hasFormalPlan) {
      return null;
    }
    if (leftoverPlanNotLive && !recoveredDisplayFacts.currentStep) {
      return null;
    }
    if (!recoveredRuntime) {
      return data.plan;
    }
    return {
      ...data.plan,
      frozen: livePlanFrozen,
      title: livePlanTitle,
      summary: livePlanSummary,
      cadence: livePlanCadence,
      currentStep: recoveredDisplayFacts.currentStep,
      whyNow: recoveredDisplayFacts.whyNow ?? "",
      nextAfterCurrent: recoveredDisplayFacts.nextAfterCurrent ?? "",
      blockedReason: recoveredDisplayFacts.blockedReason ?? "",
      verifyMethod: recoveredDisplayFacts.verifyMethod ?? [],
      currentStageId:
        formalPlanLive && liveStageChrome.stageIsCurrent ? data.plan.currentStageId : undefined,
      stages: livePlanStages,
    };
  }, [
    data.plan,
    formalPlanLive,
    hasFormalPlan,
    livePlanCadence,
    livePlanFrozen,
    livePlanStages,
    livePlanSummary,
    livePlanTitle,
    leftoverPlanNotLive,
    liveStageChrome.stageIsCurrent,
    recoveredDisplayFacts,
    recoveredRuntime,
  ]);
  const liveEvidenceQueue = useMemo(
    () =>
      scopeEvidenceQueueToRuntimeStep({
        queue: data.memory.evidenceQueue,
        recovered: recoveredRuntime,
        currentStep: recoveredDisplayFacts.currentStep,
      }),
    [data.memory.evidenceQueue, recoveredDisplayFacts.currentStep, recoveredRuntime],
  );
  const planWhyNow = useMemo(() => {
    const verifyAdvance = planRuntimeStatus?.verifyPlanAdvance;
    const verifySentence = [verifyAdvance?.what, verifyAdvance?.why]
      .map((item) => item?.trim())
      .filter(Boolean)
      .join(" — ");
    if (verifyAdvance?.advanced && verifySentence) {
      return verifySentence;
    }
    if (recoveredRuntime && recoveredDisplayFacts.currentStep) {
      return recoveredDisplayFacts.whyNow;
    }
    return (
      recoveredDisplayFacts.whyNow ??
      runtimeWhyNow ??
      liveCoachTurnChrome.artifactRationale ??
      liveCoachTaskChrome.teachingGoal ??
      liveCoachTurnChrome.coachJudgmentTeachingGoal ??
      liveCoachTurnChrome.coachTurnTeachingGoal ??
      resolvedCoachSummary ??
      (leftoverTaskChromeNotLive ? undefined : data.plan.summary)
    );
  }, [
    liveCoachTurnChrome.coachTurnTeachingGoal,
    data.plan.summary,
    leftoverTaskChromeNotLive,
    liveCoachTaskChrome.teachingGoal,
    liveCoachTurnChrome.artifactRationale,
    planRuntimeStatus?.verifyPlanAdvance,
    recoveredDisplayFacts.currentStep,
    recoveredDisplayFacts.whyNow,
    recoveredRuntime,
    resolvedCoachSummary,
    liveCoachTurnChrome.coachJudgmentTeachingGoal,
    runtimeWhyNow,
  ]);
  const verifyPlanAdvanceNext = planRuntimeStatus?.verifyPlanAdvance?.advanced
    ? sanitizeBogusLearningStep(planRuntimeStatus.verifyPlanAdvance.next?.trim()) || "" : "";
  const planVerifyItems = useMemo(() => {
    const items = lockRecoveredPlanVerifyItems({
      recovered: recoveredRuntime,
      currentStep: recoveredDisplayFacts.currentStep,
      verifyMethod: recoveredDisplayFacts.verifyMethod,
      fallbacks: [
        recoveredDisplayFacts.verifyMethod ?? [],
        data.plan.verifyMethod ?? [],
        leftoverCoachTurnChromeNotLive ? [] : latestCoachArtifact?.verification ?? [],
        liveCoachTaskChrome.successSignal ? [liveCoachTaskChrome.successSignal] : [],
        liveCoachTurnChrome.evaluationNextStep ? [liveCoachTurnChrome.evaluationNextStep] : [],
      ],
    });
    return items
      .filter((item) => !isTerminallyTruncatedText(item))
      .filter((item, index, values) => Boolean(item) && values.indexOf(item) === index)
      .slice(0, 3);
  }, [
    liveCoachTurnChrome.evaluationNextStep,
    data.plan.verifyMethod,
    liveCoachTaskChrome.successSignal,
    leftoverCoachTurnChromeNotLive,
    latestCoachArtifact?.verification,
    recoveredDisplayFacts.currentStep,
    recoveredDisplayFacts.verifyMethod,
    recoveredRuntime,
  ]);
  const planReviewReason = useMemo(
    () =>
      planRuntimeStatus?.reviewPoints?.[0]?.taskHint ??
      planRuntimeStatus?.reviewPoints?.[0]?.focusArea ??
      planRuntimeStatus?.reviewPoints?.[0]?.reason ??
      liveCoachTaskChrome.fallbackStep ??
      data.memory.dueReviews[0]?.taskHint ??
      data.memory.dueReviews[0]?.focusArea ??
      data.memory.dueReviews[0]?.reason ??
      data.memory.reviewSummary,
    [
      data.memory.dueReviews,
      data.memory.reviewSummary,
      liveCoachTaskChrome.fallbackStep,
      planRuntimeStatus?.reviewPoints,
    ],
  );
  const planReviewItems = useMemo<PlanReviewItem[]>(
    () =>
      (planRuntimeStatus?.reviewPoints?.length ? planRuntimeStatus.reviewPoints : data.memory.dueReviews)
        .slice(0, 4)
        .map((item, index) => toPlanReviewItem(item, index, layout.composerLanguage)),
    [data.memory.dueReviews, layout.composerLanguage, planRuntimeStatus?.reviewPoints],
  );
  const planReviewWindowLead = useMemo(() => {
    const primary = planReviewItems[0];
    if (!primary) {
      return (
        formattedNextReviewDue ??
        resolvedCoachReview ??
        (leftoverCoachTurnChromeNotLive ? undefined : data.reviewQueueSummary) ??
        (leftoverCoachTurnChromeNotLive ? undefined : data.memory.reviewRhythm)
      );
    }
    return [
      primary.meta,
      primary.taskHint,
      primary.focusArea,
    ].filter(Boolean)[0] ?? primary.title;
  }, [
    data.memory.reviewRhythm,
    data.reviewQueueSummary,
    leftoverCoachTurnChromeNotLive,
    formattedNextReviewDue,
    planReviewItems,
    resolvedCoachReview,
  ]);
  const planReturnPathLead = useMemo(() => {
    const returnTarget =
      recoveredRuntime && recoveredDisplayFacts.currentStep
        ? recoveredDisplayFacts.nextAfterCurrent
        : recoveredDisplayFacts.nextAfterCurrent ??
          runtimeNextAfterCurrent ??
          planReviewWindowLead ??
          resolvedCoachReview ??
          liveCoachTurnChrome.evaluationNextStep;
    if (!returnTarget) {
      return appUiCopy(layout.composerLanguage, "带验证结果回 Coach，再推进。");
    }
    return appUiCopy(layout.composerLanguage, "回到 Coach：{v}").replace("{v}", returnTarget);
  }, [
    liveCoachTurnChrome.evaluationNextStep,
    layout.composerLanguage,
    planReviewWindowLead,
    recoveredDisplayFacts.currentStep,
    recoveredDisplayFacts.nextAfterCurrent,
    recoveredRuntime,
    resolvedCoachReview,
    runtimeNextAfterCurrent,
  ]);
  const rememberedCoachSummary = useMemo(() => {
    const lines = [
      leftoverSettingsLearnerProjectOnboardingNotLive
        ? null
        : data.profile.targetProject
          ? appUiCopy(layout.composerLanguage, "你现在主要在推进：{v}").replace("{v}", data.profile.targetProject)
          : null,
      leftoverSettingsProfileRhythmNotLive
        ? null
        : data.profile.preferredLearningMode
          ? appUiCopy(layout.composerLanguage, "你更希望我这样带：{v}").replace("{v}", data.profile.preferredLearningMode)
          : null,
      leftoverSettingsProfileRhythmNotLive
        ? null
        : data.profile.preferredRhythm
          ? appUiCopy(layout.composerLanguage, "你想保持的节奏：{v}").replace("{v}", data.profile.preferredRhythm)
          : null,
      leftoverSettingsLearnerProjectOnboardingNotLive
        ? null
        : data.profile.onboardingRequest
          ? appUiCopy(layout.composerLanguage, "这轮最想推进的是：{v}").replace("{v}", data.profile.onboardingRequest)
          : null,
    ].filter((item): item is string => Boolean(item));
    if (!lines.length) {
      return undefined;
    }
    return (
      <div className="coach-plan-view__signal-feed">
        {lines.slice(0, 3).map((line) => (
          <div key={line} className="coach-plan-view__support-feed-item">
            <p>{line}</p>
          </div>
        ))}
      </div>
    );
  }, [
    data.profile.onboardingRequest,
    data.profile.preferredLearningMode,
    data.profile.preferredRhythm,
    data.profile.targetProject,
    layout.composerLanguage,
    leftoverSettingsLearnerProjectOnboardingNotLive,
    leftoverSettingsProfileRhythmNotLive,
  ]);
  const coachStrategyLines = useMemo(
    () =>
      [
        compactCoachLine(
          appUiCopy(layout.composerLanguage, "当前主线依据"),
          memoryEvidence.join(" · "),
          layout.composerLanguage,
        ),
        compactCoachLine(
          appUiCopy(layout.composerLanguage, "下一轮会怎么续上"),
          liveCoachTurnChrome.resumeThread,
          layout.composerLanguage,
        ),
        compactCoachLine(
          appUiCopy(layout.composerLanguage, "回应方式会偏向"),
          liveCoachTurnChrome.supportStrategy,
          layout.composerLanguage,
        ),
      ].filter((item): item is string => Boolean(item)),
    [
      memoryEvidence,
      liveCoachTurnChrome.resumeThread,
      liveCoachTurnChrome.supportStrategy,
      layout.composerLanguage,
    ],
  );
  const coachSummaryText = useMemo(() => {
    if (!resolvedCoachSummary) {
      return undefined;
    }
    const firstLine = resolvedCoachSummary.split("\n").find((line) => line.trim().length > 0)?.trim();
    return firstLine || resolvedCoachSummary;
  }, [resolvedCoachSummary]);
  const resolvedCoachStateSummary = useMemo(() => {
    if (coachStrategyLines.length === 0) {
      return coachSummaryText;
    }
    return [coachSummaryText, ...coachStrategyLines].filter(Boolean).join("\n");
  }, [coachStrategyLines, coachSummaryText]);
  const coachRuntimeContextSignature = [
    runtimeCurrentStage?.id,
    runtimeCurrentStage?.title,
    runtimeCurrentThread?.focusArea,
    runtimeCurrentStep,
    runtimeCurrentThread?.nextStep,
    runtimeNextAfterCurrent,
    planRuntimeStatus?.nextTrainingAction,
  ]
    .map((value) => normalizeInlineComparisonText(value))
    .filter(Boolean)
    .join("\u001f");
  useEffect(() => {
    const previousSignature = coachRuntimeContextSignatureRef.current;
    if (previousSignature === undefined) {
      coachRuntimeContextSignatureRef.current = coachRuntimeContextSignature;
      return;
    }
    if (previousSignature === coachRuntimeContextSignature) {
      return;
    }

    coachRuntimeContextSignatureRef.current = coachRuntimeContextSignature;
    setCoachContextTransition(
      coachRuntimeContextSignature && data.conversation.length > 0
        ? {
            signature: coachRuntimeContextSignature,
            conversationLength: data.conversation.length,
          }
        : undefined,
    );
  }, [coachRuntimeContextSignature, data.conversation.length]);
  const openPlanComposerMode = useCallback(
    (mode: PlanComposerMode) => {
      const learningScope = composerDockDraftScope("coach", composerSessionKey);
      const existingLearningDraft = (layout.composerDraftScope === learningScope
        ? draft : layout.composerDrafts?.[learningScope] ?? "").trim();
      closeLearningDrawer();
      setActiveView("coach");
      setPlanComposerMode(mode);
      setCoachPlanContext(mode);
      // Never destroy an unsent Learning draft. The plan context chip still tells
      // the learner why the composer kept their words; clearing the draft and
      // choosing the action again applies the canned prompt.
      if (!existingLearningDraft) {
        const modeCopy = resolvePlanComposerCopy(layout.composerLanguage).modes[mode];
        const prompt =
          mode === "blocker" ? modeCopy.secondaryPrompt.prompt : modeCopy.primaryPrompt.prompt;
        setComposerDraft(prompt, learningScope);
      }
      requestCoachComposerFocus();
    },
    [
      activeView,
      closeLearningDrawer,
      composerSessionKey,
      draft,
      layout.composerDrafts,
      layout.composerLanguage,
      requestCoachComposerFocus,
      setActiveView,
    ],
  );
  const handlePlanOrientationAction = useCallback(
    (action: PlanOrientationAction | string | null) => {
      if (!action) {
        return;
      }
      if (action === "generate_plan") {
        openPlanComposerMode("generate");
        return;
      }
      if (action === "continue_without_plan") {
        setActiveView("coach");
        requestCoachComposerFocus();
        return;
      }
      if (action === "clear_blocker" || action === "continue_step") {
        sendRecoveredPlanResumeRef.current(action);
        return;
      }
      if (action === "wait") {
        openPlanComposerMode("evidence");
        if (isBrowserPreview) {
          setOperationMessage({
            tone: "info",
            message:
              appUiCopy(layout.composerLanguage, "预览不能改真实数据，请回 VS Code。请在输入框里核对证据。"),
          }, "plan");
        }
        return;
      }
      if (action === "adopt_evidence") {
        const pendingEvidenceId = liveEvidenceQueue.pending[0]?.id?.trim();
        if (pendingEvidenceId) {
          postMessage({
            type: "command/execute",
            payload: {
              commandId: trainerCommands.evidenceAdopt,
              payload: { evidenceId: pendingEvidenceId },
            },
          });
          return;
        }
        openPlanComposerMode("evidence");
        return;
      }
      if (action === "open_training") {
        setActiveView("training");
        return;
      }
      if (action === "unfreeze_plan" && livePlanFrozen) {
        pendingLivePlanTaskMintRef.current = {
          commandId: trainerCommands.updatePlan,
        };
        setOperationMessage({
          tone: "info",
          message: livePlanUpdatePendingMessage(layout.composerLanguage),
        }, "plan");
        postMessage({
          type: "plan/freeze",
          payload: { frozen: false },
        });
      }
    },
    [
      liveEvidenceQueue.pending,
      livePlanFrozen,
      layout.composerLanguage,
      isBrowserPreview,
      openPlanComposerMode,
      postMessage,
      requestCoachComposerFocus,
      setActiveView,
      setOperationMessage,
    ],
  );
  const handleResourcesOrientationAction = useCallback(
    (action: ResourcesOrientationAction | string) => {
      if (action === "open_coach") {
        setActiveView("coach");
        return;
      }
      if (action === "import_resource") {
        triggerResourceUpload({
          browserPreview: isBrowserPreview,
          payloadMode: "files",
          filesInputRef: uploadFilesInputRef,
          folderInputRef: uploadFolderInputRef,
        });
        return;
      }
      if (action === "retry_index") {
        void requestResourceIndex();
        return;
      }
      if (action === "open_resource") {
        const resourceId = resourceConversationContextIds.find((id) =>
          data.resources.some((resource) => resource.id === id),
        );
        if (resourceId && !isBrowserPreview) {
          postMessage({
            type: "resource/open",
            payload: { resourceId },
          });
        }
        return;
      }
      if (action === "open_plan") {
        setActiveView("plan");
        return;
      }
      if (action === "open_training") {
        setActiveView("training");
      }
    },
    [
      data.resources,
      isBrowserPreview,
      postMessage,
      requestResourceIndex,
      resourceConversationContextIds,
      setActiveView,
    ],
  );
  const planOrientation = useMemo(
    () =>
      derivePlanOrientation({
        hasFormalPlan: hasFormalPlan && formalPlanLive,
        frozen: livePlanFrozen,
        planCurrentStep: data.plan.currentStep,
        planId: data.plan.id,
        runtimePlanId: data.memory.workspace?.latestPlanRuntime?.planId,
        blockedReason: recoveredDisplayFacts.blockedReason,
        currentStep: recoveredDisplayFacts.currentStep,
        whyNow: recoveredDisplayFacts.whyNow,
        nextAfterCurrent: recoveredDisplayFacts.nextAfterCurrent,
        evidenceBinding: liveEvidenceBinding({
          binding: data.memory.workspace?.latestPlanRuntime?.evidenceBinding,
          pendingIds: liveEvidenceQueue.pending.map((item) => item.id),
          recovered: recoveredRuntime,
          currentStep: recoveredDisplayFacts.currentStep,
        }),
        pendingEvidenceIds: liveEvidenceQueue.pending.map((item) => item.id),
        pendingEvidenceCount: liveEvidenceQueue.pending.length,
        verifyMethod: recoveredDisplayFacts.verifyMethod,
        recoveredRuntime,
        resumeState: planRuntimeStatus?.resumeState,
        transferState: liveTransferState,
        firstLookRecommendedNext: liveFirstLookSummary?.recommendedNextStep,
        firstLookWhy: liveFirstLookSummary?.whyThisGuess,
        language: layout.composerLanguage,
      }),
    [
      liveEvidenceQueue.pending.length,
      data.memory.workspace?.latestPlanRuntime,
      leftoverTransferSkillNotLive,
      liveTransferState,
      data.memory.workspace?.latestTransferState,
      livePlanFrozen,
      data.plan.currentStep,
      data.plan.id,
      recoveredDisplayFacts,
      data.workspaceTrainingState?.latestTransferState,
      hasFormalPlan,
      layout.composerLanguage,
      leftoverFirstLookHeadlineNotLive,
      liveFirstLookSummary?.recommendedNextStep,
      liveFirstLookSummary?.whyThisGuess,
      recoveredRuntime,
      planRuntimeStatus?.resumeState,
    ],
  );
  const liveResources = leftoverResourceLibraryListNotLive
    ? data.resources.filter(resourceRecordIsAcknowledgedUpload)
    : data.resources;
  const liveSandboxState = leftoverResourceSandboxStateNotLive
    ? undefined
    : data.memory.sandboxState;
  const resourcesOrientation = useMemo(() => {
    const selectedResourceId = selectedResourceContextIds.find((id) =>
      liveResources.some((resource) => resource.id === id),
    );
    const selectedResource = liveResources.find((resource) => resource.id === selectedResourceId);
    const searchWorkspaceId = data.resourceSearch?.workspaceId;
    const currentWorkspaceId =
      data.memory.workspace?.workspaceId ?? data.workspaceTrainingState?.workspaceId;
    const bindings = resolveResourcesBindingIds({
      selectedResourceId: selectedResource?.id,
      selectedCitationId: selectedResource?.citationId,
      planEvidenceBinding: data.memory.workspace?.latestPlanRuntime?.evidenceBinding,
      livePendingEvidenceIds: liveEvidenceQueue.pending.map((item) => item.id),
      recoveredRuntime,
      currentStep: recoveredDisplayFacts.currentStep,
      trainingTargetId: data.workspaceTrainingState?.latestTrainingHandoff?.targetId,
      trainingTargetKind: data.workspaceTrainingState?.latestTrainingHandoff?.targetKind,
      trainingSourceChain: data.workspaceTrainingState?.latestTrainingHandoff?.sourceChain,
    });
    return deriveResourcesOrientation({
      // r2-g2-0: the library header total counts distinct resources — the same
      // distinct-leaf source the tree group badges use, so the header number
      // always equals the sum of the group badges.
      resourceCount: new Set(liveResources.map((resource) => resource.id)).size,
      selectedResourceId: selectedResource?.id,
      selectedResourceTitle: selectedResource?.title,
      indexState: selectedResource?.indexState,
      resourceStatus: selectedResource?.status,
      trustState: selectedResource?.trustState,
      freshness: selectedResource?.freshness,
      qualityFlags: selectedResource?.qualityFlags,
      searchQuery: data.resourceSearch?.query.trim() === resourcesViewSearchQuery.trim()
        ? resourcesViewSearchQuery : undefined,
      searchHitCount: data.resourceSearch?.hits.length ?? data.resourceSearch?.total,
      searchWorkspaceId,
      currentWorkspaceId,
      canOpenResource: Boolean(
        selectedResource && resolveResourceOpenTarget(selectedResource).kind !== "unavailable",
      ),
      boundPlanId: bindings.boundPlanId,
      boundTrainingCardId: bindings.boundTrainingCardId,
      language: layout.composerLanguage,
      materialRecommendation: data.memory.coachingAdaptation?.materialRecommendation,
      transferSceneCount: data.memory.coachingAdaptation?.transferSceneCount,
      transferState: liveTransferState?.state,
    });
  }, [
    data.memory.coachingAdaptation?.materialRecommendation,
    data.memory.coachingAdaptation?.transferSceneCount,
    leftoverResourceLibraryListNotLive,
    leftoverResourceSandboxStateNotLive,
    liveResources,
    data.memory.workspace?.latestPlanRuntime?.evidenceBinding,
    leftoverTransferSkillNotLive,
    liveTransferState?.state,
    data.memory.workspace?.latestTransferState?.state,
    liveEvidenceQueue.pending,
    recoveredDisplayFacts.currentStep,
    recoveredRuntime,
    data.memory.workspace?.workspaceId,
    data.resourceSearch,
    resourcesViewSearchQuery,
    data.workspaceTrainingState?.latestTrainingHandoff,
    data.workspaceTrainingState?.workspaceId,
    layout.composerLanguage,
    resourceConversationContextIds,
  ]);
  // The training state crosses the host boundary, so its text fields are
  // normalized once here: a malformed field must not blank the conversation
  // at the moment a practice settles.
  const planHasFormalThread =
    hasFormalPlan &&
    Boolean(activePlanStage?.title?.trim() || data.plan.summary.trim() || data.plan.stages.length > 0);
  const planIsFrozen = hasFormalPlan && livePlanFrozen;
  const resolvedPlanComposerMode: PlanComposerMode = !planHasFormalThread && planComposerMode !== "generate"
    ? recoveredRuntime && (planComposerMode === "blocker" || planComposerMode === "evidence")
      ? planComposerMode
      : "explain"
    : planIsFrozen && planComposerMode === "generate"
      ? "explain"
      : planComposerMode;

  return {
    planHasFormalThread,
    planIsFrozen,
    resolvedPlanComposerMode,
    hasFormalPlan,
    activePlanStage,
    planRuntimeStatus,
    recoveredRuntime,
    runtimeCurrentStage,
    leftoverChromeIdentity,
    independentTrainingSelectionLive,
    leftoverTrainingHandoffChromeNotLive,
    leftoverResourceSelectedDetailNotLive,
    leftoverResourceLibraryListNotLive,
    leftoverSettingsProfileRhythmNotLive,
    liveFirstLookSummary,
    firstLookSummary,
    coachRenderConversation,
    liveCoachTaskChrome,
    leftoverCoachTurnChromeNotLive,
    latestCoachArtifact,
    coachTurnNextStepRequiresConfirmation,
    liveCoachTurnChrome,
    formattedNextReviewDue,
    resolvedCoachSummary,
    resolvedCoachNextStep,
    resolvedCoachReview,
    resolvedCoachFocus,
    resolvedCoachStage,
    latestArtifactTeaser,
    runtimeWhyNow,
    runtimeVerifyItems,
    runtimeBlockedReason,
    runtimeNextAfterCurrent,
    recoveredDisplayFacts,
    formalPlanIdentity,
    formalPlanLive,
    livePlanFrozen,
    livePlanTitle,
    livePlanSummary,
    liveTrainingSummary,
    liveTrainingSource,
    liveTask,
    leftoverSuggestedActionNotLive,
    liveSuggestedActions,
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
  };
}
