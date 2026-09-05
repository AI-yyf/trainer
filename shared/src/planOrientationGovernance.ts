import {
  applyTransferSkillToCoachOrientation,
  describeTransferSkillState,
  type TransferSkillStateRecord,
} from "./transferSkillGovernance";
import { coachOrientationTone, type CoachOrientationState } from "./coachOrientationGovernance";
import { planOrientationCopy } from "./orientationCopy";
import type { PlanRuntimeResumeState } from "./workspaceRecoveryGovernance";

export type PlanOrientationAction =
  | "generate_plan"
  | "continue_without_plan"
  | "adopt_evidence"
  | "clear_blocker"
  | "continue_step"
  | "open_training"
  | "unfreeze_plan"
  | "wait";

export interface PlanOrientationInput {
  hasFormalPlan?: boolean;
  frozen?: boolean;
  planCurrentStep?: string;
  planId?: string;
  runtimePlanId?: string;
  blockedReason?: string;
  currentStep?: string;
  whyNow?: string;
  nextAfterCurrent?: string;
  evidenceBinding?: string;
  pendingEvidenceIds?: readonly string[];
  pendingEvidenceCount?: number;
  verifyMethod?: string[];
  recoveredRuntime?: boolean;
  resumeState?: PlanRuntimeResumeState;
  transferState?: TransferSkillStateRecord;
  firstLookRecommendedNext?: string;
  firstLookWhy?: string;
  language?: string;
}

export type PlanRuntimeDisplayFacts = {
  currentStep?: string;
  whyNow?: string;
  nextAfterCurrent?: string;
  blockedReason?: string;
  verifyMethod?: string[];
};

export function preferRecoveredPlanRuntimeFacts(input: {
  recovered?: boolean;
  runtime?: PlanRuntimeDisplayFacts;
  plan?: PlanRuntimeDisplayFacts;
}): PlanRuntimeDisplayFacts {
  const runtimeStep = text(input.runtime?.currentStep);
  if (input.recovered && runtimeStep) {
    return {
      currentStep: runtimeStep,
      whyNow: text(input.runtime?.whyNow) || undefined,
      nextAfterCurrent: text(input.runtime?.nextAfterCurrent) || undefined,
      blockedReason: text(input.runtime?.blockedReason) || undefined,
      verifyMethod: (input.runtime?.verifyMethod ?? []).map((item) => item.trim()).filter(Boolean),
    };
  }
  if (input.recovered) {
    return {
      currentStep: undefined,
      whyNow: undefined,
      nextAfterCurrent: undefined,
      blockedReason: undefined,
      verifyMethod: [],
    };
  }
  const planVerify = (input.plan?.verifyMethod ?? []).map((item) => item.trim()).filter(Boolean);
  const runtimeVerify = (input.runtime?.verifyMethod ?? []).map((item) => item.trim()).filter(Boolean);
  return {
    currentStep: runtimeStep || text(input.plan?.currentStep) || undefined,
    whyNow: text(input.runtime?.whyNow) || text(input.plan?.whyNow) || undefined,
    nextAfterCurrent: text(input.runtime?.nextAfterCurrent) || text(input.plan?.nextAfterCurrent) || undefined,
    blockedReason: text(input.runtime?.blockedReason) || text(input.plan?.blockedReason) || undefined,
    verifyMethod: runtimeVerify.length ? runtimeVerify : planVerify,
  };
}

export function lockRecoveredPlanVerifyItems(input: {
  recovered?: boolean;
  currentStep?: string;
  verifyMethod?: string[];
  fallbacks?: string[][];
}): string[] {
  const currentStep = text(input.currentStep);
  const verify = (input.verifyMethod ?? []).map((item) => item.trim()).filter(Boolean);
  if (input.recovered && currentStep) {
    return verify;
  }
  for (const group of input.fallbacks ?? []) {
    const items = group.map((item) => item.trim()).filter((item) => Boolean(item));
    if (items.length) {
      return items;
    }
  }
  return verify;
}

export type EvidenceQueueBuckets<T extends { id?: string; concepts?: string[] }> = {
  pending: T[];
  deferred: T[];
  adopted: T[];
  rejected: T[];
  history?: T[];
  totalCount?: number;
};

export function scopeEvidenceQueueToRuntimeStep<T extends { id?: string; concepts?: string[] }>(input: {
  queue?: EvidenceQueueBuckets<T>;
  recovered?: boolean;
  currentStep?: string;
}): EvidenceQueueBuckets<T> & { history: T[]; totalCount: number } {
  const queue = input.queue ?? {
    pending: [],
    deferred: [],
    adopted: [],
    rejected: [],
    history: [],
    totalCount: 0,
  };
  const currentStep = text(input.currentStep);
  const totalCount =
    queue.totalCount ??
    queue.pending.length +
      queue.deferred.length +
      queue.adopted.length +
      queue.rejected.length +
      (queue.history?.length ?? 0);
  if (!input.recovered || !currentStep) {
    return {
      pending: queue.pending,
      deferred: queue.deferred,
      adopted: queue.adopted,
      rejected: queue.rejected,
      history: queue.history ?? [],
      totalCount,
    };
  }
  const bound = (item: T) => (item.concepts ?? []).some((concept) => concept.trim() === currentStep);
  const partition = (items: T[]): [T[], T[]] => {
    const live: T[] = [];
    const historic: T[] = [];
    for (const item of items) {
      (bound(item) ? live : historic).push(item);
    }
    return [live, historic];
  };
  const [pending, pendingHistory] = partition(queue.pending);
  const [deferred, deferredHistory] = partition(queue.deferred);
  const [adopted, adoptedHistory] = partition(queue.adopted);
  const [rejected, rejectedHistory] = partition(queue.rejected);
  const history: T[] = [];
  const seen = new Set<string>();
  for (const item of [
    ...(queue.history ?? []),
    ...pendingHistory,
    ...deferredHistory,
    ...adoptedHistory,
    ...rejectedHistory,
  ]) {
    const itemId = item.id?.trim() ?? "";
    if (itemId && seen.has(itemId)) {
      continue;
    }
    if (itemId) {
      seen.add(itemId);
    }
    history.push(item);
  }
  return {
    pending,
    deferred,
    adopted,
    rejected,
    history,
    totalCount,
  };
}

export function liveEvidenceBinding(input: {
  binding?: string;
  pendingIds?: readonly string[];
  recovered?: boolean;
  currentStep?: string;
}): string {
  const binding = text(input.binding);
  if (!binding) {
    return "";
  }
  const pending = new Set((input.pendingIds ?? []).map((item) => item.trim()).filter(Boolean));
  if (!pending.has(binding)) {
    return "";
  }
  if (input.recovered && !text(input.currentStep)) {
    return "";
  }
  return binding;
}

export type LivePlanStageChrome = {
  liveCurrent: string;
  stageIsCurrent: boolean;
};

export function formalPlanIsLiveRuntimeIdentity(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
}): boolean {
  const runtimeStep = text(input.runtimeCurrentStep);
  const planStep = text(input.planCurrentStep);
  const runtimePlanId = text(input.runtimePlanId);
  const planId = text(input.planId);
  if (!input.recovered) {
    return Boolean(planStep || planId);
  }
  if (!runtimeStep) {
    return false;
  }
  if (planId) {
    return runtimePlanId === planId && (!planStep || runtimeStep === planStep);
  }
  if (planStep && runtimeStep !== planStep) {
    return false;
  }
  return Boolean(planStep);
}

export function formalCardIsLiveRuntimeIdentity(input: {
  cardId?: string;
  selectedCardId?: string;
  cardTitle?: string;
  runtimeCurrentStep?: string;
}): boolean {
  // Leftover stored card is live only when runtime still carries matching card id.
  // Title / current_step text match must never count as live selectedCardId.
  const formal = text(input.cardId);
  const carried = text(input.selectedCardId);
  if (!formal || !carried) {
    return false;
  }
  if (formal !== carried) {
    return false;
  }
  void input.cardTitle;
  void input.runtimeCurrentStep;
  return true;
}

export function liveFormalPlanFrozen(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  frozen?: boolean;
}): boolean {
  return Boolean(input.frozen) && formalPlanIsLiveRuntimeIdentity(input);
}

export function liveFormalPlanTitle(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planTitle?: string;
}): string {
  const runtimeStep = text(input.runtimeCurrentStep);
  if (!formalPlanIsLiveRuntimeIdentity(input)) {
    return runtimeStep;
  }
  return text(input.planTitle) || runtimeStep;
}

export function liveFormalPlanSummary(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planSummary?: string;
  planGoal?: string;
}): string {
  if (!formalPlanIsLiveRuntimeIdentity(input)) {
    return "";
  }
  return text(input.planSummary) || text(input.planGoal);
}

export function liveTrainingFormalSummary(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planSummary?: string;
  planGoal?: string;
}): string {
  return liveFormalPlanSummary(input);
}

export function liveTrainingSourceFallback(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planSummary?: string;
  planGoal?: string;
}): string {
  const liveSummary = liveFormalPlanSummary(input);
  if (liveSummary) {
    return liveSummary;
  }
  if (formalPlanIsLiveRuntimeIdentity(input)) {
    return "";
  }
  return text(input.runtimeCurrentStep);
}

export function formalTaskIsLiveRuntimeIdentity(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  taskTitle?: string;
}): boolean {
  const runtimeStep = text(input.runtimeCurrentStep);
  const taskTitle = text(input.taskTitle);
  if (!input.recovered) {
    return Boolean(taskTitle);
  }
  if (!runtimeStep) {
    return false;
  }
  return Boolean(taskTitle) && runtimeStep === taskTitle;
}

export function leftoverTaskGuideFocusIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return Boolean(input.recovered) && !text(input.runtimeCurrentStep);
}

export type RecoveredCoachTaskChrome = {
  liveTaskTitle: string;
  ideaSummary?: string;
  scopeBoundary?: string;
  currentStep?: string;
  teachingGoal?: string;
  successSignal?: string;
  fallbackStep?: string;
  currentFocus?: string;
  activeTask?: string;
  nextStep?: string;
  activeStage?: string;
};

export function preferRecoveredCoachTaskChrome(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  taskTitle?: string;
  ideaSummary?: string;
  scopeBoundary?: string;
  guideCurrentStep?: string;
  teachingGoal?: string;
  successSignal?: string;
  fallbackStep?: string;
  currentFocus?: string;
  activeTask?: string;
  nextStep?: string;
  activeStage?: string;
}): RecoveredCoachTaskChrome {
  const runtimeStep = text(input.runtimeCurrentStep);
  const omitLeftover = (value?: string): string => {
    const candidate = text(value);
    if (!candidate) {
      return "";
    }
    if (input.recovered && !runtimeStep) {
      return "";
    }
    if (input.recovered && candidate !== runtimeStep) {
      return "";
    }
    return candidate;
  };
  if (leftoverTaskGuideFocusIsNotLive(input)) {
    return { liveTaskTitle: "" };
  }
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: runtimeStep,
    taskTitle: input.taskTitle,
  });
  return {
    liveTaskTitle: liveTask ? text(input.taskTitle) : "",
    ideaSummary: omitLeftover(input.ideaSummary) || undefined,
    scopeBoundary: omitLeftover(input.scopeBoundary) || undefined,
    currentStep: omitLeftover(input.guideCurrentStep) || undefined,
    teachingGoal: omitLeftover(input.teachingGoal) || undefined,
    successSignal: omitLeftover(input.successSignal) || undefined,
    fallbackStep: omitLeftover(input.fallbackStep) || undefined,
    currentFocus: omitLeftover(input.currentFocus) || undefined,
    activeTask: omitLeftover(input.activeTask) || undefined,
    nextStep: omitLeftover(input.nextStep) || undefined,
    activeStage: omitLeftover(input.activeStage) || undefined,
  };
}

export function leftoverCoachTurnChromeIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return leftoverTaskGuideFocusIsNotLive(input);
}

export function leftoverCoachConversationIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return leftoverCoachTurnChromeIsNotLive(input);
}

export function leftoverSuggestedActionsIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return leftoverCoachConversationIsNotLive(input);
}

const MINTING_SUGGESTED_ACTIONS = new Set(["plan", "task", "next_task", "card"]);

export function leftoverBoundPlanCompetingIdentityLabels(input: {
  livePlanId?: string;
  liveCurrentStep?: string;
  livePlanTitle?: string;
  leftoverPlanId?: string;
  leftoverPlanTitle?: string;
  leftoverPlanStep?: string;
  leftoverCardTitles?: readonly (string | undefined)[];
}): string[] {
  const liveId = text(input.livePlanId);
  const liveStep = text(input.liveCurrentStep);
  const liveTitle = text(input.livePlanTitle);
  const leftoverId = text(input.leftoverPlanId);
  if (!leftoverId || leftoverId === liveId) {
    return [];
  }
  const labels = new Set<string>();
  const add = (value: string | undefined) => {
    const item = text(value);
    if (item && item !== liveStep && item !== liveTitle) {
      labels.add(item);
    }
  };
  add(input.leftoverPlanTitle);
  add(input.leftoverPlanStep);
  for (const title of input.leftoverCardTitles ?? []) {
    add(title);
  }
  return [...labels];
}

export function leftoverMintingSuggestedActionsAreNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  taskTitle?: string;
}): boolean {
  if (!input.recovered) {
    return false;
  }
  const livePlan = formalPlanIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: input.runtimeCurrentStep,
    planCurrentStep: input.planCurrentStep,
    runtimePlanId: input.runtimePlanId,
    planId: input.planId,
  });
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: input.runtimeCurrentStep,
    taskTitle: input.taskTitle,
  });
  return !livePlan && !liveTask;
}

export function honestSuggestedActionsWithoutLiveObject<T extends { action?: string }>(
  actions: readonly T[] | undefined,
  input: {
    recovered?: boolean;
    runtimeCurrentStep?: string;
    planCurrentStep?: string;
    runtimePlanId?: string;
    planId?: string;
    taskTitle?: string;
  },
): T[] {
  const list = [...(actions ?? [])];
  if (!leftoverMintingSuggestedActionsAreNotLive(input)) {
    return list;
  }
  return list.filter((item) => !MINTING_SUGGESTED_ACTIONS.has(String(item.action ?? "")));
}

export function leftoverFirstLookHeadlineIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return leftoverCoachConversationIsNotLive(input);
}

export function leftoverEvaluationHeadlineIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return leftoverCoachConversationIsNotLive(input);
}

export function leftoverStreamingCheckpointIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return leftoverCoachConversationIsNotLive(input);
}

export function leftoverTransferSkillIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return leftoverStreamingCheckpointIsNotLive(input);
}

function uniqueLeftoverTransferIds(values: readonly string[] | undefined): string[] {
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const value of values ?? []) {
    const trimmed = value.trim();
    if (!trimmed) {
      continue;
    }
    const key = trimmed.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push(trimmed);
  }
  return unique;
}

export function leftoverTransferSkillHasRealMultiSceneProof(
  transfer: TransferSkillStateRecord | undefined,
): boolean {
  if (!transfer) {
    return false;
  }
  const workspaceIds = uniqueLeftoverTransferIds(transfer.workspaceIds);
  return transfer.sceneCount >= 2 && workspaceIds.length >= 2;
}

export function preferRecoveredTransferSkill(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  transfer?: TransferSkillStateRecord;
}): TransferSkillStateRecord | undefined {
  const transfer = input.transfer;
  if (!transfer) {
    return undefined;
  }
  if (!leftoverTransferSkillIsNotLive(input)) {
    return transfer;
  }
  if (leftoverTransferSkillHasRealMultiSceneProof(transfer)) {
    return transfer;
  }
  if (transfer.state !== "transferable") {
    return transfer;
  }
  const copy = describeTransferSkillState("awaiting_second_scene", transfer.concept);
  return {
    ...transfer,
    state: "awaiting_second_scene",
    sceneCount: Math.max(1, Math.min(transfer.sceneCount, 1)),
    why: copy.why,
    next: copy.next,
  };
}

export type RecoveredCoachTurnChrome = {
  coachTurnNextStep?: string;
  coachTurnSummary?: string;
  coachTurnTeachingGoal?: string;
  coachTurnEncouragement?: string;
  coachTurnActiveStage?: string;
  coachingStateNextStep?: string;
  coachingStateSummary?: string;
  coachingStateTeachingGoal?: string;
  coachingStateEncouragement?: string;
  evaluationNextStep?: string;
  nextStepHintTitle?: string;
  nextStepHintSummary?: string;
  resumeThread?: string;
  supportStrategy?: string;
  reviewQueueSummary?: string;
  artifactTeaser?: string;
  artifactRationale?: string;
  continuitySummary?: string;
  coachJudgmentSummary?: string;
  coachJudgmentTeachingGoal?: string;
};

export function preferRecoveredCoachTurnChrome(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  coachTurnNextStep?: string;
  coachTurnSummary?: string;
  coachTurnTeachingGoal?: string;
  coachTurnEncouragement?: string;
  coachTurnActiveStage?: string;
  coachingStateNextStep?: string;
  coachingStateSummary?: string;
  coachingStateTeachingGoal?: string;
  coachingStateEncouragement?: string;
  evaluationNextStep?: string;
  nextStepHintTitle?: string;
  nextStepHintSummary?: string;
  resumeThread?: string;
  supportStrategy?: string;
  reviewQueueSummary?: string;
  artifactTeaser?: string;
  artifactRationale?: string;
  continuitySummary?: string;
  coachJudgmentSummary?: string;
  coachJudgmentTeachingGoal?: string;
}): RecoveredCoachTurnChrome {
  const runtimeStep = text(input.runtimeCurrentStep);
  const omitLeftover = (value?: string): string => {
    const candidate = text(value);
    if (!candidate) {
      return "";
    }
    if (input.recovered && !runtimeStep) {
      return "";
    }
    if (input.recovered && candidate !== runtimeStep) {
      return "";
    }
    return candidate;
  };
  if (leftoverCoachTurnChromeIsNotLive(input)) {
    return {};
  }
  return {
    coachTurnNextStep: omitLeftover(input.coachTurnNextStep) || undefined,
    coachTurnSummary: omitLeftover(input.coachTurnSummary) || undefined,
    coachTurnTeachingGoal: omitLeftover(input.coachTurnTeachingGoal) || undefined,
    coachTurnEncouragement: omitLeftover(input.coachTurnEncouragement) || undefined,
    coachTurnActiveStage: omitLeftover(input.coachTurnActiveStage) || undefined,
    coachingStateNextStep: omitLeftover(input.coachingStateNextStep) || undefined,
    coachingStateSummary: omitLeftover(input.coachingStateSummary) || undefined,
    coachingStateTeachingGoal: omitLeftover(input.coachingStateTeachingGoal) || undefined,
    coachingStateEncouragement: omitLeftover(input.coachingStateEncouragement) || undefined,
    evaluationNextStep: omitLeftover(input.evaluationNextStep) || undefined,
    nextStepHintTitle: omitLeftover(input.nextStepHintTitle) || undefined,
    nextStepHintSummary: omitLeftover(input.nextStepHintSummary) || undefined,
    resumeThread: omitLeftover(input.resumeThread) || undefined,
    supportStrategy: omitLeftover(input.supportStrategy) || undefined,
    reviewQueueSummary: omitLeftover(input.reviewQueueSummary) || undefined,
    artifactTeaser: omitLeftover(input.artifactTeaser) || undefined,
    artifactRationale: omitLeftover(input.artifactRationale) || undefined,
    continuitySummary: omitLeftover(input.continuitySummary) || undefined,
    coachJudgmentSummary: omitLeftover(input.coachJudgmentSummary) || undefined,
    coachJudgmentTeachingGoal: omitLeftover(input.coachJudgmentTeachingGoal) || undefined,
  };
}

export function leftoverTrainingFocusChromeIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
}): boolean {
  return leftoverTrainingHandoffChromeIsNotLive(input);
}

export type RecoveredTrainingFocusChrome = {
  teachingDecisionFocusArea?: string;
  learnerStateActiveFocus?: string;
  latestLearningFocusArea?: string;
  cardFocusArea?: string;
  taskFocusOverride?: string;
};

export function preferRecoveredTrainingFocusChrome(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
  teachingDecisionFocusArea?: string;
  learnerStateActiveFocus?: string;
  latestLearningFocusArea?: string;
  cardFocusArea?: string;
  taskFocusOverride?: string;
}): RecoveredTrainingFocusChrome {
  const runtimeStep = text(input.runtimeCurrentStep);
  const omitLeftover = (value?: string): string => {
    const candidate = text(value);
    if (!candidate) {
      return "";
    }
    if (input.recovered && !runtimeStep) {
      return "";
    }
    if (input.recovered && candidate !== runtimeStep) {
      return "";
    }
    return candidate;
  };
  if (leftoverTrainingFocusChromeIsNotLive(input)) {
    return {};
  }
  return {
    teachingDecisionFocusArea: omitLeftover(input.teachingDecisionFocusArea) || undefined,
    learnerStateActiveFocus: omitLeftover(input.learnerStateActiveFocus) || undefined,
    latestLearningFocusArea: omitLeftover(input.latestLearningFocusArea) || undefined,
    cardFocusArea: omitLeftover(input.cardFocusArea) || undefined,
    taskFocusOverride: omitLeftover(input.taskFocusOverride) || undefined,
  };
}

export function leftoverTrainingHandoffChromeIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
}): boolean {
  if (leftoverTaskGuideFocusIsNotLive(input)) {
    return true;
  }
  if (!input.recovered) {
    return false;
  }
  // Recovered-with-step without live leftover plan identity (carried plan_id)
  // stays leftover-not-live so leftover card chrome cannot dump as live Training.
  const runtimePlanId = text(input.runtimePlanId);
  const planId = text(input.planId);
  if (!runtimePlanId || runtimePlanId !== planId) {
    return true;
  }
  return !formalPlanIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: input.runtimeCurrentStep,
    planCurrentStep: input.planCurrentStep,
    runtimePlanId: input.runtimePlanId,
    planId: input.planId,
  });
}

export type RecoveredTrainingHandoffChrome = {
  successSignal?: string;
  returnWith?: string;
  cardTitle?: string;
  selectedCardTitle?: string;
  followup?: string;
  blocker?: string;
  handoffSummary?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  nextHopTitle?: string;
  nextHopCardTitle?: string;
  nextHopHandoffSummary?: string;
  nextHopNextAfterCompletion?: string;
  nextHopFallbackAction?: string;
  routingNextAfterCompletion?: string;
  routingFallbackAction?: string;
  whyThisCard?: string;
  ledgerWhyThisCard?: string;
  returnSummary?: string;
  nextHopReturnSummary?: string;
  nextHopSummary?: string;
  nextHopWhyNow?: string;
};

export function preferRecoveredTrainingHandoffChrome(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
  successSignal?: string;
  returnWith?: string;
  cardTitle?: string;
  selectedCardTitle?: string;
  followup?: string;
  blocker?: string;
  handoffSummary?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  nextHopTitle?: string;
  nextHopCardTitle?: string;
  nextHopHandoffSummary?: string;
  nextHopNextAfterCompletion?: string;
  nextHopFallbackAction?: string;
  routingNextAfterCompletion?: string;
  routingFallbackAction?: string;
  whyThisCard?: string;
  ledgerWhyThisCard?: string;
  returnSummary?: string;
  nextHopReturnSummary?: string;
  nextHopSummary?: string;
  nextHopWhyNow?: string;
}): RecoveredTrainingHandoffChrome {
  const runtimeStep = text(input.runtimeCurrentStep);
  const omitLeftover = (value?: string): string => {
    const candidate = text(value);
    if (!candidate) {
      return "";
    }
    if (input.recovered && !runtimeStep) {
      return "";
    }
    if (input.recovered && candidate !== runtimeStep) {
      return "";
    }
    return candidate;
  };
  if (leftoverTrainingHandoffChromeIsNotLive(input)) {
    return {};
  }
  return {
    successSignal: omitLeftover(input.successSignal) || undefined,
    returnWith: omitLeftover(input.returnWith) || undefined,
    cardTitle: omitLeftover(input.cardTitle) || undefined,
    selectedCardTitle: omitLeftover(input.selectedCardTitle) || undefined,
    followup: omitLeftover(input.followup) || undefined,
    blocker: omitLeftover(input.blocker) || undefined,
    handoffSummary: omitLeftover(input.handoffSummary) || undefined,
    nextAfterCompletion: omitLeftover(input.nextAfterCompletion) || undefined,
    fallbackAction: omitLeftover(input.fallbackAction) || undefined,
    nextHopTitle: omitLeftover(input.nextHopTitle) || undefined,
    nextHopCardTitle: omitLeftover(input.nextHopCardTitle) || undefined,
    nextHopHandoffSummary: omitLeftover(input.nextHopHandoffSummary) || undefined,
    nextHopNextAfterCompletion: omitLeftover(input.nextHopNextAfterCompletion) || undefined,
    nextHopFallbackAction: omitLeftover(input.nextHopFallbackAction) || undefined,
    routingNextAfterCompletion: omitLeftover(input.routingNextAfterCompletion) || undefined,
    routingFallbackAction: omitLeftover(input.routingFallbackAction) || undefined,
    whyThisCard: omitLeftover(input.whyThisCard) || undefined,
    ledgerWhyThisCard: omitLeftover(input.ledgerWhyThisCard) || undefined,
    returnSummary: omitLeftover(input.returnSummary) || undefined,
    nextHopReturnSummary: omitLeftover(input.nextHopReturnSummary) || undefined,
    nextHopSummary: omitLeftover(input.nextHopSummary) || undefined,
    nextHopWhyNow: omitLeftover(input.nextHopWhyNow) || undefined,
  };
}

export function leftoverResourceSelectedDetailIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
}): boolean {
  if (leftoverTaskGuideFocusIsNotLive(input)) {
    return true;
  }
  // Recovered-with-step is still leftover-not-live for Resources.
  // A recovered plan step is Plan identity, not Resources library identity.
  return Boolean(input.recovered);
}

export function leftoverResourceSandboxPreviewIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
}): boolean {
  return leftoverResourceSelectedDetailIsNotLive(input);
}

export function leftoverResourceSandboxStateIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
}): boolean {
  return leftoverResourceSandboxPreviewIsNotLive(input);
}

export function leftoverResourceLibraryListIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
}): boolean {
  return leftoverResourceSandboxStateIsNotLive(input);
}

export function leftoverSettingsProfileRhythmIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  if (leftoverTaskGuideFocusIsNotLive(input)) {
    return true;
  }
  // Recovered-with-step is still leftover-not-live for Settings.
  // A recovered plan step is Plan identity, not Settings identity.
  return Boolean(input.recovered);
}

export function leftoverSettingsLearnerProjectOnboardingIsNotLive(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
}): boolean {
  return leftoverSettingsProfileRhythmIsNotLive(input);
}

export function streakAdaptsWithoutInventingLiveObjects(input: {
  failureStreak?: number;
  successStreak?: number;
  /** Backend turn stamp (`streak_blocks_live_object_mint`); fail-closed over missing streak fields. */
  streakBlocksLiveObjectMint?: boolean;
  livePlan?: boolean;
  liveTask?: boolean;
  liveCard?: boolean;
}): boolean {
  if (input.streakBlocksLiveObjectMint === true) {
    return !input.livePlan && !input.liveTask && !input.liveCard;
  }
  const failureStreak = Number(input.failureStreak || 0);
  const successStreak = Number(input.successStreak || 0);
  if (failureStreak >= 2 && !input.livePlan && !input.liveTask) {
    return true;
  }
  if (successStreak >= 2 && !input.liveCard) {
    return true;
  }
  return false;
}

export function pressureAdaptsWithoutInventingLiveObjects(input: {
  timeBudget?: string;
  taskUrgency?: string;
  /** Backend turn stamp (`pressure_blocks_live_object_mint`); fail-closed over stale urgency. */
  pressureBlocksLiveObjectMint?: boolean;
  livePlan?: boolean;
  liveTask?: boolean;
  liveCard?: boolean;
}): boolean {
  const compressed =
    input.pressureBlocksLiveObjectMint === true ||
    String(input.timeBudget || "").trim().toLowerCase() === "tight" ||
    String(input.taskUrgency || "").trim().toLowerCase() === "high";
  if (!compressed) {
    return false;
  }
  return !input.livePlan && !input.liveTask && !input.liveCard;
}

export type RecoveredSettingsProfileRhythmChrome = {
  preferredRhythm?: string;
  preferredLearningMode?: string;
  memoryScope?: string;
  reviewCadence?: string;
  workingSetMode?: string;
  reviewReminderMode?: string;
};

export function preferRecoveredSettingsProfileRhythm(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  preferredRhythm?: string;
  preferredLearningMode?: string;
  memoryScope?: string;
  reviewCadence?: string;
  workingSetMode?: string;
  reviewReminderMode?: string;
}): RecoveredSettingsProfileRhythmChrome {
  if (leftoverSettingsProfileRhythmIsNotLive(input)) {
    return {};
  }
  return {
    preferredRhythm: text(input.preferredRhythm) || undefined,
    preferredLearningMode: text(input.preferredLearningMode) || undefined,
    memoryScope: text(input.memoryScope) || undefined,
    reviewCadence: text(input.reviewCadence) || undefined,
    workingSetMode: text(input.workingSetMode) || undefined,
    reviewReminderMode: text(input.reviewReminderMode) || undefined,
  };
}

export type RecoveredSettingsLearnerProjectOnboardingChrome = {
  learnerName?: string;
  targetProject?: string;
  onboardingRequest?: string;
  projectContext?: string;
};

export function preferRecoveredSettingsLearnerProjectOnboarding(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  learnerName?: string;
  targetProject?: string;
  onboardingRequest?: string;
  projectContext?: string;
}): RecoveredSettingsLearnerProjectOnboardingChrome {
  if (leftoverSettingsLearnerProjectOnboardingIsNotLive(input)) {
    return {};
  }
  return {
    learnerName: text(input.learnerName) || undefined,
    targetProject: text(input.targetProject) || undefined,
    onboardingRequest: text(input.onboardingRequest) || undefined,
    projectContext: text(input.projectContext) || undefined,
  };
}

export type RecoveredResourceSelectedDetailChrome = {
  title?: string;
  summary?: string;
  matchSummary?: string;
};

export function preferRecoveredResourceSelectedDetail(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planCurrentStep?: string;
  title?: string;
  summary?: string;
  matchSummary?: string;
}): RecoveredResourceSelectedDetailChrome {
  const runtimeStep = text(input.runtimeCurrentStep);
  const omitLeftover = (value?: string): string => {
    const candidate = text(value);
    if (!candidate) {
      return "";
    }
    if (input.recovered && !runtimeStep) {
      return "";
    }
    if (input.recovered && candidate !== runtimeStep) {
      return "";
    }
    return candidate;
  };
  if (leftoverResourceSelectedDetailIsNotLive(input)) {
    return {};
  }
  return {
    title: omitLeftover(input.title) || undefined,
    summary: omitLeftover(input.summary) || undefined,
    matchSummary: omitLeftover(input.matchSummary) || undefined,
  };
}

export function liveTrainingNextChallengeTitle(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planTitle?: string;
  taskTitle?: string;
  cardTitle?: string;
}): string {
  const runtimeStep = text(input.runtimeCurrentStep);
  if (input.recovered && !runtimeStep) {
    return "";
  }
  const livePlan = formalPlanIsLiveRuntimeIdentity(input);
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: runtimeStep,
    taskTitle: input.taskTitle,
  });
  if (input.recovered && livePlan) {
    return text(input.cardTitle);
  }
  if (input.recovered && !livePlan && !liveTask) {
    return runtimeStep;
  }
  return text(input.cardTitle) || text(input.taskTitle) || text(input.planTitle) || runtimeStep;
}

export function liveTrainingTitleFallback(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  planTitle?: string;
  taskTitle?: string;
}): string {
  const runtimeStep = text(input.runtimeCurrentStep);
  if (input.recovered && !runtimeStep) {
    return "";
  }
  const livePlan = formalPlanIsLiveRuntimeIdentity(input);
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: runtimeStep,
    taskTitle: input.taskTitle,
  });
  if (!livePlan && !liveTask) {
    return runtimeStep;
  }
  if (liveTask) {
    return text(input.taskTitle) || runtimeStep;
  }
  return text(input.planTitle) || runtimeStep;
}

export function liveTrainingFocusFallback(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  taskTitle?: string;
  coachFocus?: string;
  memoryFocus?: string;
}): string {
  const runtimeStep = text(input.runtimeCurrentStep);
  if (input.recovered && !runtimeStep) {
    return "";
  }
  const livePlan = formalPlanIsLiveRuntimeIdentity(input);
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: runtimeStep,
    taskTitle: input.taskTitle,
  });
  if (!livePlan && !liveTask) {
    return runtimeStep;
  }
  return text(input.coachFocus) || text(input.memoryFocus) || runtimeStep;
}

export function liveTrainingTargetSkill(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  taskTitle?: string;
  cardSkill?: string;
  liveFocus?: string;
}): string {
  const cardSkill = text(input.cardSkill);
  if (cardSkill) {
    return cardSkill;
  }
  const runtimeStep = text(input.runtimeCurrentStep);
  if (input.recovered && !runtimeStep) {
    return "";
  }
  const livePlan = formalPlanIsLiveRuntimeIdentity(input);
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: runtimeStep,
    taskTitle: input.taskTitle,
  });
  if (!livePlan && !liveTask) {
    return "";
  }
  return text(input.liveFocus);
}

export function liveTrainingWhyNow(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  taskTitle?: string;
  cardWhy?: string;
  liveWhy?: string;
}): string {
  const runtimeStep = text(input.runtimeCurrentStep);
  if (input.recovered && !runtimeStep) {
    return "";
  }
  const cardWhy = text(input.cardWhy);
  if (cardWhy) {
    return cardWhy;
  }
  const livePlan = formalPlanIsLiveRuntimeIdentity(input);
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: runtimeStep,
    taskTitle: input.taskTitle,
  });
  if (!livePlan && !liveTask) {
    return "";
  }
  return text(input.liveWhy);
}

export function liveTrainingCoachSummary(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  taskTitle?: string;
  coachSummary?: string;
}): string {
  const runtimeStep = text(input.runtimeCurrentStep);
  if (input.recovered && !runtimeStep) {
    return "";
  }
  const livePlan = formalPlanIsLiveRuntimeIdentity(input);
  const liveTask = formalTaskIsLiveRuntimeIdentity({
    recovered: input.recovered,
    runtimeCurrentStep: runtimeStep,
    taskTitle: input.taskTitle,
  });
  if (!livePlan && !liveTask) {
    return "";
  }
  return text(input.coachSummary);
}

export function liveFormalPlanStages<T>(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  stages?: readonly T[];
}): T[] {
  if (!formalPlanIsLiveRuntimeIdentity(input)) {
    return [];
  }
  return [...(input.stages ?? [])];
}

export function liveFormalPlanCadence(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  runtimePlanId?: string;
  planId?: string;
  cadence?: string;
}): string {
  if (!formalPlanIsLiveRuntimeIdentity(input)) {
    return "";
  }
  return text(input.cadence);
}

export function resolveLivePlanStageChrome(input: {
  recovered?: boolean;
  runtimeCurrentStep?: string;
  planCurrentStep?: string;
  planStageTitle?: string;
  planStageGoal?: string;
  runtimePlanId?: string;
  planId?: string;
}): LivePlanStageChrome {
  const runtimeStep = text(input.runtimeCurrentStep);
  const planStep = text(input.planCurrentStep);
  const stageTitle = text(input.planStageTitle);
  const stageGoal = text(input.planStageGoal);
  if (input.recovered && !runtimeStep) {
    return {
      liveCurrent: "",
      stageIsCurrent: false,
    };
  }
  if (input.recovered && runtimeStep) {
    const leftoverFormal = !formalPlanIsLiveRuntimeIdentity({
      recovered: input.recovered,
      runtimeCurrentStep: runtimeStep,
      planCurrentStep: planStep,
      runtimePlanId: input.runtimePlanId,
      planId: input.planId,
    });
    const stageIsCurrent =
      !leftoverFormal &&
      (runtimeStep === planStep || runtimeStep === stageTitle || runtimeStep === stageGoal);
    return {
      liveCurrent: runtimeStep,
      stageIsCurrent,
    };
  }
  return {
    liveCurrent: planStep || stageTitle || stageGoal,
    stageIsCurrent: Boolean(planStep || stageTitle || stageGoal),
  };
}

export interface PlanOrientationRecord {
  objectKind: "plan";
  objectLabel: string;
  state: CoachOrientationState;
  why: string;
  primaryAction: PlanOrientationAction;
  primaryActionLabel: string;
  nextStep: string;
  advancedWhere: string;
  source: "snapshot";
  revision: number;
}

const ACTIONS = new Set<PlanOrientationAction>([
  "generate_plan",
  "continue_without_plan",
  "adopt_evidence",
  "clear_blocker",
  "continue_step",
  "open_training",
  "unfreeze_plan",
  "wait",
]);

function text(value: string | undefined): string {
  return value?.trim() ?? "";
}

function record(
  input: Omit<PlanOrientationRecord, "objectKind" | "source" | "revision"> & { revision?: number },
): PlanOrientationRecord {
  return {
    objectKind: "plan",
    objectLabel: input.objectLabel,
    state: input.state,
    why: input.why,
    primaryAction: input.primaryAction,
    primaryActionLabel: input.primaryActionLabel,
    nextStep: input.nextStep,
    advancedWhere: input.advancedWhere,
    source: "snapshot",
    revision: input.revision ?? 1,
  };
}

export function normalizePlanOrientationRecord(value: unknown): PlanOrientationRecord | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const row = value as Record<string, unknown>;
  const objectLabel = text(typeof row.objectLabel === "string" ? row.objectLabel : typeof row.object_label === "string" ? row.object_label : "");
  const state = text(typeof row.state === "string" ? row.state : "");
  const why = text(typeof row.why === "string" ? row.why : "");
  const primaryAction = text(
    typeof row.primaryAction === "string"
      ? row.primaryAction
      : typeof row.primary_action === "string"
        ? row.primary_action
        : "",
  ) as PlanOrientationAction;
  const primaryActionLabel = text(
    typeof row.primaryActionLabel === "string"
      ? row.primaryActionLabel
      : typeof row.primary_action_label === "string"
        ? row.primary_action_label
        : "",
  );
  const nextStep = text(
    typeof row.nextStep === "string" ? row.nextStep : typeof row.next_step === "string" ? row.next_step : "",
  );
  if (!objectLabel || !state || !why || !ACTIONS.has(primaryAction) || !nextStep) {
    return undefined;
  }
  return {
    objectKind: "plan",
    objectLabel,
    state: state as CoachOrientationState,
    why,
    primaryAction,
    primaryActionLabel,
    nextStep,
    advancedWhere: text(
      typeof row.advancedWhere === "string"
        ? row.advancedWhere
        : typeof row.advanced_where === "string"
          ? row.advanced_where
          : "",
    ),
    source: "snapshot",
    revision: typeof row.revision === "number" && row.revision > 0 ? Math.floor(row.revision) : 1,
  };
}

export function derivePlanOrientation(input: PlanOrientationInput): PlanOrientationRecord {
  return applyTransferSkillToCoachOrientation(derivePlanOrientationBase(input), input.transferState);
}

function derivePlanOrientationBase(input: PlanOrientationInput): PlanOrientationRecord {
  const copy = planOrientationCopy(input.language);
  const currentStep = text(input.currentStep);
  const frozen = liveFormalPlanFrozen({
    recovered: input.recoveredRuntime,
    runtimeCurrentStep: currentStep,
    planCurrentStep: input.planCurrentStep,
    runtimePlanId: input.runtimePlanId,
    planId: input.planId,
    frozen: input.frozen,
  });
  const whyNow = text(input.whyNow);
  const blocked = text(input.blockedReason);
  const nextAfter = text(input.nextAfterCurrent);
  const pendingEvidence = input.pendingEvidenceCount ?? 0;
  const evidenceBinding = liveEvidenceBinding({
    binding: input.evidenceBinding,
    pendingIds: input.pendingEvidenceIds,
    recovered: input.recoveredRuntime,
    currentStep: currentStep,
  });
  const verify = (input.verifyMethod ?? []).map((item) => item.trim()).filter(Boolean);
  const resumed = input.recoveredRuntime && input.resumeState === "in_progress";
  const waitingVerify = input.recoveredRuntime && input.resumeState === "waiting";

  if (input.recoveredRuntime && !currentStep) {
    if (text(input.firstLookRecommendedNext) || input.hasFormalPlan) {
      return record({
        objectLabel: copy.currentPlan,
        state: "waiting",
        why: copy.noAuthoritativeStep,
        primaryAction: "wait",
        primaryActionLabel: copy.waitForStep,
        nextStep: copy.waitRuntimeStep,
        advancedWhere: copy.planRuntime,
      });
    }
  }

  if (input.recoveredRuntime && blocked && currentStep) {
    return record({
      objectLabel: currentStep || copy.currentPlan,
      state: resumed ? "working" : "blocked",
      why: blocked,
      primaryAction: "clear_blocker",
      primaryActionLabel: copy.clearBlocker,
      nextStep: currentStep ? copy.clearBlockerThenReturn(currentStep) : copy.clearThisBlocker,
      advancedWhere: copy.planEvidenceBlockers,
    });
  }
  if (input.recoveredRuntime && waitingVerify && currentStep) {
    if (pendingEvidence > 0) {
      return record({
        objectLabel: currentStep,
        state: "waiting",
        why: whyNow || copy.currentMainlineStep,
        primaryAction: "adopt_evidence",
        primaryActionLabel: copy.reviewEvidence,
        nextStep: verify[0] ? copy.thenVerify(verify[0]) : copy.confirmEvidenceThenStep,
        advancedWhere: copy.planEvidenceQueue,
      });
    }
    return record({
      objectLabel: currentStep,
      state: "waiting",
      why: whyNow || copy.currentMainlineStep,
      primaryAction: "wait",
      primaryActionLabel: copy.wait,
      nextStep: verify[0] ? copy.thenVerify(verify[0]) : copy.confirmEvidenceThenStep,
      advancedWhere: copy.planEvidenceQueue,
    });
  }
  if (input.recoveredRuntime && currentStep && pendingEvidence > 0) {
    return record({
      objectLabel: currentStep,
      state: "waiting",
      why: copy.pendingEvidence(pendingEvidence),
      primaryAction: "adopt_evidence",
      primaryActionLabel: copy.reviewEvidence,
      nextStep: evidenceBinding
        ? copy.confirmEvidence(evidenceBinding)
        : nextAfter || copy.confirmEvidenceThenStep,
      advancedWhere: copy.planEvidenceQueue,
    });
  }
  if (input.recoveredRuntime && currentStep) {
    return record({
      objectLabel: currentStep,
      state: resumed ? "working" : "interrupted",
      why: whyNow || copy.currentMainlineStep,
      primaryAction: "continue_step",
      primaryActionLabel: copy.continueThisStep,
      nextStep:
        nextAfter ||
        (verify[0] ? copy.thenVerify(verify[0]) : copy.finishThenVerify),
      advancedWhere: copy.planRuntime,
    });
  }

  const firstLookNext = text(input.firstLookRecommendedNext);
  const firstLookWhy = text(input.firstLookWhy);
  if (!input.hasFormalPlan && firstLookNext) {
    return record({
      objectLabel: copy.currentPlan,
      state: "ready",
      why: firstLookWhy || copy.continueWithoutPlanWhy,
      primaryAction: "continue_without_plan",
      primaryActionLabel: copy.continueWithoutPlan,
      nextStep: firstLookNext,
      advancedWhere: copy.planFirstLook,
    });
  }

  if (!input.hasFormalPlan) {
    return record({
      objectLabel: copy.learningPlan,
      state: "needs_setup",
      why: copy.noFormalPlan,
      primaryAction: "generate_plan",
      primaryActionLabel: copy.generatePlan,
      nextStep: copy.generateMainline,
      advancedWhere: copy.planEmpty,
    });
  }

  if (blocked) {
    return record({
      objectLabel: currentStep || copy.currentPlan,
      state: "blocked",
      why: blocked,
      primaryAction: "clear_blocker",
      primaryActionLabel: copy.clearBlocker,
      nextStep: currentStep ? copy.clearBlockerThenReturn(currentStep) : copy.clearThisBlocker,
      advancedWhere: copy.planEvidenceBlockers,
    });
  }

  if (frozen) {
    return record({
      objectLabel: currentStep || copy.frozenPlan,
      state: "waiting",
      why: copy.planFrozen,
      primaryAction: "unfreeze_plan",
      primaryActionLabel: copy.unfreeze,
      nextStep: currentStep || copy.frozenReviewOnly,
      advancedWhere: copy.planFrozenWhere,
    });
  }

  if (pendingEvidence > 0) {
    return record({
      objectLabel: currentStep || copy.reviewEvidence,
      state: "waiting",
      why: copy.pendingEvidence(pendingEvidence),
      primaryAction: "adopt_evidence",
      primaryActionLabel: copy.reviewEvidence,
      nextStep: evidenceBinding
        ? copy.confirmEvidence(evidenceBinding)
        : copy.confirmEvidenceThenStep,
      advancedWhere: copy.planEvidenceQueue,
    });
  }

  if (!currentStep) {
    return record({
      objectLabel: copy.currentPlan,
      state: "waiting",
      why: copy.noAuthoritativeStep,
      primaryAction: "wait",
      primaryActionLabel: copy.waitForStep,
      nextStep: copy.waitRuntimeStep,
      advancedWhere: copy.planRuntime,
    });
  }

  return record({
    objectLabel: currentStep,
    state: "ready",
    why: whyNow || copy.currentMainlineStep,
    primaryAction: "continue_step",
    primaryActionLabel: copy.continueThisStep,
    nextStep:
      nextAfter ||
      (verify[0] ? copy.thenVerify(verify[0]) : copy.finishThenVerify),
    advancedWhere: copy.planCurrentStep,
  });
}

export function planOrientationTone(state: CoachOrientationState): ReturnType<typeof coachOrientationTone> {
  return coachOrientationTone(state);
}

export type RecoveredPlanResumeAction = "continue_step" | "clear_blocker";

export interface RecoveredPlanRuntimeFacts {
  recovered?: boolean;
  formalPlanMutation?: boolean;
  currentStep?: string;
  currentStepId?: string;
  blockedReason?: string;
  whyNow?: string;
}

export interface RecoveredPlanResumeTurn {
  action: RecoveredPlanResumeAction;
  recovered: true;
  formalPlanMutation: false;
  currentStep?: string;
  currentStepId?: string;
  blockedReason?: string;
  whyNow?: string;
}

function resumeText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function buildRecoveredPlanResumeTurn(
  action: string,
  facts: RecoveredPlanRuntimeFacts | undefined,
): RecoveredPlanResumeTurn | undefined {
  if (facts?.recovered !== true) {
    return undefined;
  }
  if (facts.formalPlanMutation === true) {
    return undefined;
  }
  if (action !== "continue_step" && action !== "clear_blocker") {
    return undefined;
  }
  const currentStep = resumeText(facts.currentStep);
  const currentStepId = resumeText(facts.currentStepId);
  const blockedReason = resumeText(facts.blockedReason);
  const whyNow = resumeText(facts.whyNow);
  if (action === "continue_step" && !currentStep) {
    return undefined;
  }
  if (action === "clear_blocker" && !blockedReason) {
    return undefined;
  }
  return {
    action,
    recovered: true,
    formalPlanMutation: false,
    currentStep: currentStep || undefined,
    currentStepId: currentStepId || undefined,
    blockedReason: blockedReason || undefined,
    whyNow: whyNow || undefined,
  };
}

export function normalizeRecoveredPlanResumeTurn(value: unknown): RecoveredPlanResumeTurn | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const row = value as Record<string, unknown>;
  return buildRecoveredPlanResumeTurn(
    resumeText(row.action),
    {
      recovered: row.recovered === true,
      formalPlanMutation:
        row.formalPlanMutation === true || row.formal_plan_mutation === true,
      currentStep: resumeText(row.currentStep ?? row.current_step) || undefined,
      currentStepId: resumeText(row.currentStepId ?? row.current_step_id) || undefined,
      blockedReason: resumeText(row.blockedReason ?? row.blocked_reason) || undefined,
      whyNow: resumeText(row.whyNow ?? row.why_now) || undefined,
    },
  );
}

export function recoveredPlanResumeMessage(
  turn: RecoveredPlanResumeTurn,
  language?: string,
): string {
  const zh = (language ?? "").toLowerCase().startsWith("zh");
  if (turn.action === "clear_blocker") {
    const blocker = turn.blockedReason ?? "";
    const step = turn.currentStep
      ? zh
        ? ` 对应步骤：${turn.currentStep}。`
        : ` Current step: ${turn.currentStep}.`
      : "";
    return zh
      ? `继续处理当前卡点：${blocker}。${step}`.trim()
      : `Help me clear this blocker: ${blocker}.${step}`;
  }
  const why = turn.whyNow
    ? zh
      ? ` 为什么现在：${turn.whyNow}。`
      : ` Why now: ${turn.whyNow}.`
    : "";
  return zh
    ? `继续当前步骤：${turn.currentStep}。${why}`.trim()
    : `Continue this step: ${turn.currentStep}.${why}`;
}
