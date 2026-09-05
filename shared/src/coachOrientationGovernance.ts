import {
  applyTransferSkillToCoachOrientation,
  type TransferSkillStateRecord,
} from "./transferSkillGovernance";
import { coachOrientationCopy } from "./orientationCopy";

export type CoachOrientationObject =
  | "provider"
  | "workspace"
  | "conversation"
  | "plan"
  | "training";

export type CoachOrientationState =
  | "needs_setup"
  | "waiting"
  | "working"
  | "blocked"
  | "ready"
  | "interrupted";

export type CoachOrientationAction =
  | "open_settings"
  | "open_plan"
  | "open_training"
  | "compose"
  | "wait"
  | "retry"
  | "resume_checkpoint";

export interface CoachOrientationInput {
  sidecarStatus?: string;
  hasProviderModel?: boolean;
  providerSendBlocked?: boolean;
  providerBlockReason?: string;
  workspaceBlocked?: boolean;
  workspaceBlockReason?: string;
  streaming?: boolean;
  checkpointRecovery?: boolean;
  conversationCount?: number;
  planBlockedReason?: string;
  planCurrentStep?: string;
  planWhyNow?: string;
  activeThreadFocus?: string;
  trainingReliabilityPhase?: string;
  operationReliabilityPhase?: string;
  operationReliabilityOutcome?: string;
  trainingLearningPhase?: string;
  trainingHandoffStatus?: string;
  selectedCardTitle?: string;
  language?: string;
  transferState?: TransferSkillStateRecord;
  firstLookRecommendedNext?: string;
  firstLookWhy?: string;
}

export interface CoachOrientationRecord {
  objectKind: CoachOrientationObject;
  objectLabel: string;
  state: CoachOrientationState;
  why: string;
  primaryAction: CoachOrientationAction;
  primaryActionLabel: string;
  nextStep: string;
  advancedWhere: string;
  source: "snapshot";
  revision: number;
}

const OBJECTS = new Set<CoachOrientationObject>([
  "provider",
  "workspace",
  "conversation",
  "plan",
  "training",
]);

const STATES = new Set<CoachOrientationState>([
  "needs_setup",
  "waiting",
  "working",
  "blocked",
  "ready",
  "interrupted",
]);

const ACTIONS = new Set<CoachOrientationAction>([
  "open_settings",
  "open_plan",
  "open_training",
  "compose",
  "wait",
  "retry",
  "resume_checkpoint",
]);

function text(value: string | undefined): string {
  return value?.trim() ?? "";
}

function normalizeSidecarStatus(value: string | undefined): string {
  return text(value).toLowerCase();
}

function normalizePhase(value: string | undefined): string {
  return text(value).toLowerCase().replace(/-/g, "_");
}

export function normalizeCoachOrientationRecord(
  value: unknown,
): CoachOrientationRecord | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const objectKind = text(typeof record.objectKind === "string" ? record.objectKind : typeof record.object_kind === "string" ? record.object_kind : "");
  const state = text(typeof record.state === "string" ? record.state : "");
  const primaryAction = text(
    typeof record.primaryAction === "string"
      ? record.primaryAction
      : typeof record.primary_action === "string"
        ? record.primary_action
        : "",
  );
  if (
    !OBJECTS.has(objectKind as CoachOrientationObject) ||
    !STATES.has(state as CoachOrientationState) ||
    !ACTIONS.has(primaryAction as CoachOrientationAction)
  ) {
    return undefined;
  }
  const objectLabel = text(
    typeof record.objectLabel === "string"
      ? record.objectLabel
      : typeof record.object_label === "string"
        ? record.object_label
        : "",
  );
  const why = text(typeof record.why === "string" ? record.why : "");
  const nextStep = text(
    typeof record.nextStep === "string"
      ? record.nextStep
      : typeof record.next_step === "string"
        ? record.next_step
        : "",
  );
  if (!objectLabel || !why || !nextStep) {
    return undefined;
  }
  const revision =
    typeof record.revision === "number" && Number.isFinite(record.revision) ? record.revision : 1;
  return {
    objectKind: objectKind as CoachOrientationObject,
    objectLabel,
    state: state as CoachOrientationState,
    why,
    primaryAction: primaryAction as CoachOrientationAction,
    primaryActionLabel: text(
      typeof record.primaryActionLabel === "string"
        ? record.primaryActionLabel
        : typeof record.primary_action_label === "string"
          ? record.primary_action_label
          : "",
    ),
    nextStep,
    advancedWhere: text(
      typeof record.advancedWhere === "string"
        ? record.advancedWhere
        : typeof record.advanced_where === "string"
          ? record.advanced_where
          : "",
    ),
    source: "snapshot",
    revision,
  };
}

function record(input: {
  objectKind: CoachOrientationObject;
  objectLabel: string;
  state: CoachOrientationState;
  why: string;
  primaryAction: CoachOrientationAction;
  primaryActionLabel: string;
  nextStep: string;
  advancedWhere: string;
  revision?: number;
}): CoachOrientationRecord {
  return {
    ...input,
    source: "snapshot",
    revision: input.revision ?? 1,
  };
}

export function deriveCoachOrientation(input: CoachOrientationInput): CoachOrientationRecord {
  return applyTransferSkillToCoachOrientation(deriveCoachOrientationBase(input), input.transferState);
}

function deriveCoachOrientationBase(input: CoachOrientationInput): CoachOrientationRecord {
  const copy = coachOrientationCopy(input.language);
  const sidecar = normalizeSidecarStatus(input.sidecarStatus);
  const cardTitle = text(input.selectedCardTitle);
  const reliabilityPhase = normalizePhase(input.trainingReliabilityPhase);
  const learningPhase = normalizePhase(input.trainingLearningPhase);
  const handoffStatus = normalizePhase(input.trainingHandoffStatus);
  const planBlocked = text(input.planBlockedReason);
  const planStep = text(input.planCurrentStep);
  const planWhy = text(input.planWhyNow);
  const threadFocus = text(input.activeThreadFocus);
  const conversationCount = input.conversationCount ?? 0;
  const firstLookNext = text(input.firstLookRecommendedNext);
  const firstLookWhy = text(input.firstLookWhy);
  const leftoverTrainingNotLiveForBoundPlan = Boolean(planStep) && !cardTitle;

  if (sidecar === "error") {
    return record({
      objectKind: "workspace",
      objectLabel: copy.runtime,
      state: "blocked",
      why: copy.sidecarUnavailable,
      primaryAction: "open_settings",
      primaryActionLabel: copy.openSettings,
      nextStep: copy.restoreSidecar,
      advancedWhere: copy.settingsRuntime,
    });
  }
  if (sidecar === "starting" || sidecar === "unknown") {
    return record({
      objectKind: "workspace",
      objectLabel: copy.runtime,
      state: "waiting",
      why: copy.sidecarStarting,
      primaryAction: "wait",
      primaryActionLabel: copy.wait,
      nextStep: copy.waitUntilReady,
      advancedWhere: copy.settingsRuntime,
    });
  }
  if (!input.hasProviderModel || input.providerSendBlocked) {
    return record({
      objectKind: "provider",
      objectLabel: copy.provider,
      state: "needs_setup",
      why: text(input.providerBlockReason) || copy.noProvider,
      primaryAction: "open_settings",
      primaryActionLabel: copy.openSettings,
      nextStep: copy.saveAndTestProvider,
      advancedWhere: copy.settingsProvider,
    });
  }
  if (input.workspaceBlocked) {
    return record({
      objectKind: "workspace",
      objectLabel: copy.workspace,
      state: "blocked",
      why: text(input.workspaceBlockReason) || copy.workspaceBlocked,
      primaryAction: "open_settings",
      primaryActionLabel: copy.openWorkspace,
      nextStep: copy.resolveWorkspace,
      advancedWhere: copy.settingsWorkspace,
    });
  }
  if (input.checkpointRecovery) {
    return record({
      objectKind: "conversation",
      objectLabel: copy.thisTurn,
      state: "interrupted",
      why: copy.turnInterrupted,
      primaryAction: "resume_checkpoint",
      primaryActionLabel: copy.resume,
      nextStep: copy.resumeCheckpoint,
      advancedWhere: copy.coachCheckpoint,
    });
  }
  if (input.streaming) {
    return record({
      objectKind: "conversation",
      objectLabel: threadFocus || copy.thisTurn,
      state: "working",
      why: copy.coachWorking,
      primaryAction: "wait",
      primaryActionLabel: copy.waitReply,
      nextStep: copy.waitTurnEnd,
      advancedWhere: copy.conversation,
    });
  }
  const operationPhase = normalizePhase(input.operationReliabilityPhase);
  if (
    operationPhase === "intent" ||
    operationPhase === "pending" ||
    operationPhase === "executing"
  ) {
    return record({
      objectKind: "conversation",
      objectLabel: threadFocus || copy.thisTurn,
      state: "working",
      why: copy.coachWorking,
      primaryAction: "wait",
      primaryActionLabel: copy.waitReply,
      nextStep: copy.waitTurnEnd,
      advancedWhere: copy.conversation,
    });
  }
  const operationOutcome = (input.operationReliabilityOutcome ?? "").trim().toLowerCase();
  if (
    operationPhase === "failed" ||
    (operationPhase === "acked" &&
      (operationOutcome === "failure" || operationOutcome === "timeout"))
  ) {
    return record({
      objectKind: "provider",
      objectLabel: copy.provider,
      state: "blocked",
      why: text(input.providerBlockReason) || copy.noProvider,
      primaryAction: "open_settings",
      primaryActionLabel: copy.openSettings,
      nextStep: copy.saveAndTestProvider,
      advancedWhere: copy.settingsProvider,
    });
  }
  if (
    !leftoverTrainingNotLiveForBoundPlan &&
    (reliabilityPhase === "intent" ||
      reliabilityPhase === "pending" ||
      reliabilityPhase === "executing")
  ) {
    return record({
      objectKind: "training",
      objectLabel: cardTitle || copy.currentTrainingCard,
      state: "waiting",
      why: copy.trainingAwaitingAck,
      primaryAction: "wait",
      primaryActionLabel: copy.waitAck,
      nextStep: copy.waitSnapshot,
      advancedWhere: copy.trainingSaveStatus,
    });
  }
  if (!leftoverTrainingNotLiveForBoundPlan && (reliabilityPhase === "failed" || reliabilityPhase === "cancelled")) {
    return record({
      objectKind: "training",
      objectLabel: cardTitle || copy.currentTrainingCard,
      state: "blocked",
      why: copy.trainingSaveUnacked,
      primaryAction: "retry",
      primaryActionLabel: copy.retryTraining,
      nextStep: copy.resubmitTraining,
      advancedWhere: copy.trainingSaveStatus,
    });
  }
  if (
    !leftoverTrainingNotLiveForBoundPlan &&
    (handoffStatus === "ready_to_return" || learningPhase === "return")
  ) {
    return record({
      objectKind: "training",
      objectLabel: cardTitle || copy.currentTrainingCard,
      state: "ready",
      why: copy.returnDue,
      primaryAction: "open_training",
      primaryActionLabel: copy.completeReturn,
      nextStep: copy.completeReturnInTraining,
      advancedWhere: copy.trainingReturn,
    });
  }
  if (
    !leftoverTrainingNotLiveForBoundPlan &&
    (learningPhase === "reflect" || handoffStatus === "needs_reflection")
  ) {
    return record({
      objectKind: "training",
      objectLabel: cardTitle || copy.currentTrainingCard,
      state: "ready",
      why: copy.reflectionMissing,
      primaryAction: "open_training",
      primaryActionLabel: copy.openReflect,
      nextStep: copy.writeEvidence,
      advancedWhere: copy.trainingReflect,
    });
  }
  if (
    !leftoverTrainingNotLiveForBoundPlan &&
    (learningPhase === "verify" || handoffStatus === "needs_verification")
  ) {
    return record({
      objectKind: "training",
      objectLabel: cardTitle || copy.currentTrainingCard,
      state: "waiting",
      why: copy.verifyWaiting,
      primaryAction: "open_training",
      primaryActionLabel: copy.openVerify,
      nextStep: copy.verifyThenReflect,
      advancedWhere: copy.trainingVerify,
    });
  }
  if (planBlocked) {
    return record({
      objectKind: "plan",
      objectLabel: planStep || threadFocus || copy.currentPlan,
      state: "blocked",
      why: planBlocked,
      primaryAction: "open_plan",
      primaryActionLabel: copy.openPlan,
      nextStep: copy.clearBlocker,
      advancedWhere: copy.planEvidenceBlockers,
    });
  }
  if (!leftoverTrainingNotLiveForBoundPlan && (learningPhase === "try" || learningPhase === "learn")) {
    return record({
      objectKind: "training",
      objectLabel: cardTitle || copy.currentTrainingCard,
      state: "ready",
      why: learningPhase === "learn" ? copy.learnStep : copy.tryStep,
      primaryAction: "open_training",
      primaryActionLabel: copy.openTraining,
      nextStep: learningPhase === "learn" ? copy.readThenStart : copy.smallestChange,
      advancedWhere: copy.trainingCurrentCard,
    });
  }
  if (planStep) {
    return record({
      objectKind: "plan",
      objectLabel: planStep,
      state: "ready",
      why: planWhy || copy.currentThread,
      primaryAction: "open_plan",
      primaryActionLabel: copy.openPlan,
      nextStep: copy.continueOrCheckPlan,
      advancedWhere: copy.planCurrentStep,
    });
  }
  if (firstLookNext) {
    return record({
      objectKind: "conversation",
      objectLabel: copy.firstLookProject,
      state: "ready",
      why: firstLookWhy || copy.firstLookWhy,
      primaryAction: "compose",
      primaryActionLabel: copy.startSpeak,
      nextStep: firstLookNext,
      advancedWhere: copy.firstLookWhere,
    });
  }
  if (threadFocus) {
    return record({
      objectKind: "conversation",
      objectLabel: threadFocus,
      state: "ready",
      why: copy.currentThread,
      primaryAction: "compose",
      primaryActionLabel: copy.continueSpeak,
      nextStep: copy.continueOrCheckPlan,
      advancedWhere: copy.coachDetailsInPlan,
    });
  }
  if (conversationCount === 0) {
    return record({
      objectKind: "conversation",
      objectLabel: copy.coachConversation,
      state: "ready",
      why: copy.noCurrentTurn,
      primaryAction: "compose",
      primaryActionLabel: copy.startSpeak,
      nextStep: copy.sayWhatToLearn,
      advancedWhere: copy.planTrainingAfterObject,
    });
  }
  return record({
    objectKind: "conversation",
    objectLabel: copy.thisConversation,
    state: "ready",
    why: copy.currentIsConversation,
    primaryAction: "compose",
    primaryActionLabel: copy.continueSpeak,
    nextStep: copy.askOrReturn,
    advancedWhere: copy.planTraining,
  });
}

export function coachOrientationTone(
  state: CoachOrientationState,
): "blocker" | "activity" | "context" {
  if (state === "blocked" || state === "needs_setup" || state === "interrupted") {
    return "blocker";
  }
  if (state === "working" || state === "waiting") {
    return "activity";
  }
  return "context";
}
