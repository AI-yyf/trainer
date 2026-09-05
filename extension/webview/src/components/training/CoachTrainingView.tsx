import { useEffect, useMemo, useState } from "react";

import {
  buildTransferEvidenceDraft,
  type TransferEvidenceDraft,
  type TransferWorkspaceOption,
} from "../../../../../shared/src/transferEvidenceGovernance";
import {
  summarizeTrainingNextHopCopy,
  summarizeWaitingCoachJudgment,
} from "../../../../../shared/src/coachLanguage";
import {
  compactTrainingCardText,
  summarizeTrainingCardLead,
  summarizeTrainingScenarioPack,
  type NarrowSidebarCopyLanguage,
} from "../../../../../shared/src/trainingCardCopy";
import {
  resolveTrainingHandoff,
  resolveTrainingNextHop,
  type TrainingEventLedgerEntrySummary,
} from "../../../../../shared/src/trainingHandoffGovernance";
import { summarizeReviewQueueTruth } from "../../../../../shared/src/reviewQueueGovernance";
import { buildTrainingRestoreOrchestrationSteps } from "../../../../../shared/src/trainingRecoveryGovernance";
import { ActionButton } from "../common";
import { BooksIcon } from "../icons";
import { DiagnosticsIcon, LightningIcon } from "../icons";
import { CoachFlashView } from "../flash";
import type { FlashPracticeBridge } from "../flash/CoachFlashView";
import { CoachPracticeView } from "../practice";
import { StatusPill } from "../StatusPill";
import { WorkspaceAuthoritySummary } from "../coach/parts/WorkspaceAuthoritySummary";
import type {
  PracticeCoachBridge,
  PracticeFileVerificationRequest,
} from "../practice/CoachPracticeView";
import type { TrainingReturnPayload } from "../../../../../shared/src/trainingReturn";
import type { TrainingCardStatus } from "../../../../../shared/src/trainingCardRouting";
import { isValidCardTransition } from "../../../../../shared/src/trainingCardRouting";
import { preferRecoveredTrainingFocusChrome } from "../../../../../shared/src/planOrientationGovernance";
import type {
  ComposerLanguage,
  DebugVisibleTrainingFacts,
  DependencyMastery,
  DependencySkillMap,
  DependencySkillMapHistoryEntry,
  EvidencePack,
  FlashcardAttempt,
  FlashcardDeck,
  FlashcardRecoveryMode,
  ImplementationGuide,
  LearningOutcome,
  MemoryLayerView,
  ReviewArtifact,
  ReviewArtifactHistoryEntry,
  ReviewQueueAction,
  ReviewQueueItem,
  ScenarioLab,
  ScenarioLabHistoryEntry,
  TaskSpec,
  TeachingDecision,
  TheoryDrillHistoryEntry,
  TheoryDrillSnapshot,
  TrainingEventLedgerEntry,
  TrainingNextHopSummary,
  TrainingSubmode,
  WorkspaceAuthority,
  WorkspaceUnderstanding,
} from "../../lib/types";
import { useTranslation } from "../../lib/i18n/useTranslation";

type TrainingSurfaceMode = "project" | "flash";
type TrainingConversationCandidateType =
  | "project_context_candidate"
  | "resource_import_candidate"
  | "evidence_candidate"
  | "flash_candidate"
  | "practice_candidate"
  | "coach_visible_status"
  | "micro_drill_prompt"
  | "card_invocation";
type TrainingLedgerContinueIn = "chat" | "training" | "plan" | "resources" | "none";
type TrainingLedgerProjectScope =
  | "global"
  | "current_project"
  | "project_subplan"
  | "sandbox"
  | "unknown";

type WorkspaceTrainingState = {
  workspaceId?: string;
  latestConversationHandoff?: {
    candidateId?: string;
    candidateType?: TrainingConversationCandidateType;
    targetKind?: string;
    targetId?: string;
    continueIn?: "chat" | "training" | "plan" | "resources" | "none";
    acceptedInto?: string;
    handoffStatus?: string;
    handoffSummary?: string;
    blockedBy?: string;
    coachOnly?: boolean;
    cardType?: "practice" | "flash";
    cardTitle?: string;
    learnerDeliverables?: string[];
    verificationSteps?: string[];
    successSignal?: string;
    returnWith?: string;
    nextAfterCompletion?: string;
    fallbackAction?: string;
  };
  latestConversationCandidateId?: string;
  latestConversationCandidateType?: TrainingConversationCandidateType;
  latestTrainingHandoff?: {
    candidateId?: string;
    candidateType?: TrainingConversationCandidateType;
    targetKind?: string;
    targetId?: string;
    continueIn?: "chat" | "training" | "plan" | "resources" | "none";
    acceptedInto?: string;
    handoffStatus?: string;
    handoffSummary?: string;
    blockedBy?: string;
    coachOnly?: boolean;
    cardType?: "practice" | "flash";
    cardTitle?: string;
    scenarioPack?: string;
    learnerDeliverables?: string[];
    verificationSteps?: string[];
    successSignal?: string;
    returnWith?: string;
    nextAfterCompletion?: string;
    fallbackAction?: string;
    returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
    returnSummary?: string;
    fedBackAt?: string;
    waitingCoachJudgment?: boolean;
    sourceChain?: string[];
  };
  latestTrainingNextHop?: {
    candidateId?: string;
    candidateType?: "evidence_candidate" | "flash_candidate" | "practice_candidate";
    title?: string;
    summary?: string;
    whyNow?: string;
    projectScope?: "global" | "current_project" | "project_subplan" | "sandbox" | "unknown";
    continueIn?: "chat" | "training" | "plan";
    targetKind?: string;
    targetId?: string;
    acceptedInto?: string;
    status?:
      | "created"
      | "surfaced"
      | "accepted"
      | "continued_in_chat"
      | "verification_required"
      | "reflection_required"
      | "return_required"
      | "dismissed"
      | "deferred"
      | "blocked"
      | "expired"
      | "archived";
    statusReason?: string;
    blockedBy?: string;
    handoffStatus?: string;
    handoffSummary?: string;
    coachOnly?: boolean;
    cardType?: "practice" | "flash";
    cardTitle?: string;
    scenarioPack?: string;
    returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
    returnSummary?: string;
    judgedAt?: string;
    reviewArtifactId?: string;
    reviewArtifactStatus?: string;
    reviewRecoveryMode?: string;
    planEvidenceId?: string;
    nextAfterCompletion?: string;
    fallbackAction?: string;
    sourceChain?: string[];
    /** Humanized training metrics */
    streakDays?: number;
    cardsMastered?: number;
    practiceMinutes?: number;
    todayProgress?: number;
    nextReviewAt?: string;
  };
  latestTrainingSubmode?: TrainingSubmode;
  latestFlashcardBridge?: string;
  latestFlashcardRecoveryMode?: FlashcardRecoveryMode;
  latestLearningFollowup?: string;
  latestLearningFocusArea?: string;
  latestLearningScenario?: string;
  latestLearningVerifiedResult?: string;
  latestTransferEvidenceId?: string;
  latestTransferSourceWorkspaceId?: string;
  latestTransferTargetWorkspaceId?: string;
  latestTransferVerifiedResult?: string;
  latestTransferBlockedReason?: string;
  latestLearningBlocker?: string;
  latestLearningAbandonReason?: string;
  latestLearningPartialProgress?: string;
  selectedCardId?: string;
  selectedCardType?: "practice" | "flash";
  selectedCardTitle?: string;
  selectedCardStatus?: TrainingCardStatus;
  theoryDrill?: TheoryDrillSnapshot;
  theoryDrillHistory?: TheoryDrillHistoryEntry[];
  scenarioLab?: ScenarioLab;
  reviewArtifact?: ReviewArtifact;
  dependencySkillMaps?: DependencySkillMap[];
  dependencySkillMapHistory?: DependencySkillMapHistoryEntry[];
  dueReviews?: ReviewQueueItem[];
  reviewQueueActions?: ReviewQueueAction[];
  scenarioLabHistory?: ScenarioLabHistoryEntry[];
  reviewArtifactHistory?: ReviewArtifactHistoryEntry[];
  trainingCardCandidates?: unknown[];
  activeTrainingCardRouting?: unknown;
  trainingEventLedger?: TrainingEventLedgerEntry[];
};

export interface CoachTrainingViewProps {
  language: ComposerLanguage;
  task?: TaskSpec;
  isLoading?: boolean;
  workspaceUnderstanding?: WorkspaceUnderstanding;
  evidencePack?: EvidencePack;
  teachingDecision?: TeachingDecision;
  recoveredRuntime?: boolean;
  runtimeCurrentStep?: string;
  implementationGuide?: ImplementationGuide;
  dependencyMastery: DependencyMastery[];
  learningOutcomes: LearningOutcome[];
  memoryLayers?: MemoryLayerView[];
  workspaceAuthority?: WorkspaceAuthority;
  reviewSummary?: string;
  practiceBusy?: boolean;
  flashBusy?: boolean;
  transferWorkspaceOptions?: TransferWorkspaceOption[];
  flashDeck?: FlashcardDeck;
  recentFlashAttempts: FlashcardAttempt[];
  flashPracticeBridge?: FlashPracticeBridge;
  workspaceTrainingState?: WorkspaceTrainingState;
  initialTrainingSubmode?: TrainingSubmode;
  onTrainingSubmodeChange?: (submode: TrainingSubmode) => void;
  onRefreshTask: (focusArea?: string) => void;
  onQuickStartTraining?: (mode: "flash" | "practice" | "review") => void;
  onOpenCoachFromPractice?: (bridge: PracticeCoachBridge) => void;
  onRefreshDeck: () => void;
  onSubmitFlashAnswer: (payload: {
    cardId: string;
    learnerAnswer?: string;
    selectedOptionIndex?: number;
    selectedOptionIndices?: number[];
    fillBlankAnswers?: Record<number, string>;
    sortOrder?: number[];
  }) => void;
  onSubmitTheoryDrillAnswer: (payload: {
    theoryDrillId: string;
    questionId: string;
    learnerAnswer?: string;
    selectedOptionIndex?: number;
  }) => void;
  onTheoryDrillAction?: (payload: {
    theoryDrillId: string;
    action: "archive" | "reopen" | "restore_history";
    note?: string;
    historyEntryId?: string;
    historyVersion?: number;
  }) => void;
  onOpenCoachFromFlash?: () => void;
  onOpenCoachBridgeFromFlash?: (bridge: PracticeCoachBridge) => void;
  onOpenPracticeFromFlash?: (bridge: FlashPracticeBridge) => void;
  onCreateFlashcard?: (payload: {
    question: string;
    answerMode: "text" | "single_choice" | "multiple_choice" | "fill_blank" | "sorting" | "true_false";
    options?: string[];
    expectedAnswer?: string;
    correctOptionIndex?: number;
    correctOptionIndices?: number[];
    correctSortOrder?: number[];
    fillBlankAnswers?: Record<number, string>;
    hintLadder?: string[];
    context?: string;
  }) => void;
  onOpenResources?: () => void;
  onOpenReviewCoach?: (focusArea?: string) => void;
  onReviewQueueAction?: (payload: {
    concept: string;
    action: "accept" | "snooze" | "done" | "skip" | "reset";
    scope?: "single" | "all_due" | "focus_area";
    batchLimit?: number;
    focusArea?: string;
    taskHint?: string;
    note?: string;
  }) => void;
  onScenarioLabAction?: (payload: {
    scenarioLabId: string;
    action: "start" | "complete" | "archive" | "reopen" | "review" | "restore_history";
    note?: string;
    reviewOutcome?: string;
    historyEntryId?: string;
    historyVersion?: number;
  }) => void;
  onReviewArtifactAction?: (payload: {
    reviewArtifactId: string;
    action: "updated" | "reviewed" | "resolved" | "reopened" | "archived" | "restore_history";
    note?: string;
    historyEntryId?: string;
    historyVersion?: number;
    editPatch?: Record<string, unknown>;
  }) => void;
  onDependencySkillMapAction?: (payload: {
    dependencyKey: string;
    action:
      | "restore_history"
      | "send_to_flashcards"
      | "start_scenario_lab"
      | "request_verification"
      | "reset_basics";
    note?: string;
    historyEntryId?: string;
    historyVersion?: number;
    focusItemKey?: string;
    relatedApi?: string;
    scenario?: string;
  }) => void;
  onTrainingRestoreOrchestration?: (payload: {
    runId: string;
    note?: string;
    dryRun?: boolean;
    steps: ReturnType<typeof buildTrainingRestoreOrchestrationSteps>;
  }) => void;
  onCardStatusTransition?: (cardId: string, newStatus: TrainingCardStatus, reason?: string) => void;
  onVerifyCurrentFile?: (request: PracticeFileVerificationRequest) => void;
  debugRestoreTarget?: "theory_drill" | "scenario_lab" | "review_artifact" | "next_hop";
  debugTheoryDrillId?: string;
  debugScenarioLabId?: string;
  debugReviewArtifactId?: string;
  debugRestoredNextHop?: WorkspaceTrainingState["latestTrainingNextHop"];
  onDebugVisibleFacts?: (facts: DebugVisibleTrainingFacts) => void;
}

function isChinese(language: ComposerLanguage): boolean {
  return language === "zh-CN";
}

function normalizeText(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized ? normalized : undefined;
}

function areTransferDraftsEqual(
  left?: TransferEvidenceDraft,
  right?: TransferEvidenceDraft,
): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right) {
    return false;
  }
  return (
    left.dependencyKey === right.dependencyKey &&
    left.sourceWorkspaceId === right.sourceWorkspaceId &&
    left.targetWorkspaceId === right.targetWorkspaceId &&
    left.sourceContext === right.sourceContext &&
    left.targetContext === right.targetContext &&
    left.verifiedResult === right.verifiedResult &&
    left.evidenceSummary === right.evidenceSummary &&
    left.focusItemKey === right.focusItemKey &&
    left.relatedApi === right.relatedApi &&
    left.scenario === right.scenario
  );
}

function normalizeMode(value?: TrainingSubmode): TrainingSurfaceMode {
  return value === "flash" ? "flash" : "project";
}

function text(language: ComposerLanguage, zh: string, en: string): string {
  return isChinese(language) ? zh : en;
}

function nextHopStatusLabel(
  language: ComposerLanguage,
  status?: "created" | "surfaced" | "accepted" | "continued_in_chat" | "verification_required" | "reflection_required" | "return_required" | "dismissed" | "deferred" | "blocked" | "expired" | "archived",
): string | undefined {
  if (!status) {
    return undefined;
  }
  const labels = isChinese(language)
    ? {
        created: "已创建",
        surfaced: "已浮现",
        accepted: "已接受",
        continued_in_chat: "已回到对话",
        verification_required: "还需验证",
        reflection_required: "先复盘一下",
        return_required: "带回教练",
        dismissed: "已忽略",
        deferred: "已延后",
        blocked: "已阻塞",
        expired: "已过期",
        archived: "已归档",
      }
    : {
        created: "Created",
        surfaced: "Surfaced",
        accepted: "Accepted",
        continued_in_chat: "Back in coach",
        verification_required: "Needs a check",
        reflection_required: "Reflect first",
        return_required: "Return to coach",
        dismissed: "Dismissed",
        deferred: "Deferred",
        blocked: "Blocked",
        expired: "Expired",
        archived: "Archived",
      };
  return labels[status];
}

function nextHopContinueLabel(
  language: ComposerLanguage,
  continueIn?: "chat" | "training" | "plan",
): string | undefined {
  if (!continueIn) {
    return undefined;
  }
  if (continueIn === "chat") {
    return isChinese(language) ? "回到对话" : "Return to coach";
  }
  return continueIn === "plan"
    ? isChinese(language)
      ? "继续计划"
      : "Continue in plan"
    : isChinese(language)
      ? "继续训练"
      : "Continue training";
}

function nextHopScopeLabel(
  language: ComposerLanguage,
  scope?: "global" | "current_project" | "project_subplan" | "sandbox" | "unknown",
): string | undefined {
  if (!scope) {
    return undefined;
  }
  const labels = isChinese(language)
    ? {
        global: "全局",
        current_project: "当前项目",
        project_subplan: "项目子计划",
        sandbox: "沙箱",
        unknown: "未标注",
      }
    : {
        global: "Global",
        current_project: "Current project",
        project_subplan: "Project subplan",
        sandbox: "Sandbox",
        unknown: "Unknown",
      };
  return labels[scope];
}

function memoryLayerStatusTone(status: MemoryLayerView["status"]): "connected" | "pending" | "offline" {
  if (status === "active") {
    return "connected";
  }
  if (status === "quiet") {
    return "pending";
  }
  return "offline";
}

function memoryLayerStatusLabel(language: ComposerLanguage, status: MemoryLayerView["status"]): string {
  if (status === "active") {
    return "Active";
  }
  if (status === "quiet") {
    return "Quiet";
  }
  return "Empty";
}

function memoryLayerInjectionLabel(language: ComposerLanguage, canInjectTrainingCard: boolean): string {
  return canInjectTrainingCard
    ? "Can inject training card"
    : "Reference only";
}

function toTrainingLedgerContinueIn(value?: string): TrainingLedgerContinueIn | undefined {
  return value === "chat" ||
    value === "training" ||
    value === "plan" ||
    value === "resources" ||
    value === "none"
    ? value
    : undefined;
}

function toTrainingLedgerProjectScope(value?: string): TrainingLedgerProjectScope | undefined {
  return value === "global" ||
    value === "current_project" ||
    value === "project_subplan" ||
    value === "sandbox" ||
    value === "unknown"
    ? value
    : undefined;
}

function stageLabel(language: ComposerLanguage, stage?: DependencyMastery["masteryStage"]): string {
  const labels = {
    understood: "Understood",
    recalled: "Recalled",
    practiced: "Practiced",
    applied: "Applied",
    transferable: "Transferable",
  } as const;
  return stage ? labels[stage] : "Not established";
}

function nextActionForStage(stage?: DependencyMastery["masteryStage"]): "mark_practiced" | "mark_applied" | "mark_transferable" {
  if (stage === "practiced") {
    return "mark_applied";
  }
  if (stage === "applied" || stage === "transferable") {
    return "mark_transferable";
  }
  return "mark_practiced";
}

function summarizeLatestReviewQueueAction(
  language: ComposerLanguage,
  reviewQueueActions: ReviewQueueAction[] | undefined,
  trainingEventLedger: TrainingEventLedgerEntry[] | undefined,
): string | undefined {
  const latestLedgerEvent = [...(trainingEventLedger ?? [])]
    .filter((entry) => entry.eventType === "review_queue_action_recorded")
    .sort((left, right) => Date.parse(right.createdAt ?? right.timestamp) - Date.parse(left.createdAt ?? left.timestamp))[0];
  const latestAction = [...(reviewQueueActions ?? [])]
    .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt))[0];
  const concept =
    normalizeText(latestAction?.concept) ||
    normalizeText(latestAction?.focusArea) ||
    normalizeText(latestLedgerEvent?.attemptTargetTitle) ||
    normalizeText(latestLedgerEvent?.attemptTargetId);
  const action =
    normalizeText(latestAction?.action) ||
    normalizeText(latestLedgerEvent?.learnerAnswerPreview) ||
    normalizeText(latestLedgerEvent?.statusKind);
  const note =
    normalizeText(latestAction?.note) ||
    normalizeText(latestLedgerEvent?.feedback) ||
    normalizeText(latestAction?.taskHint);
  if (!concept || !action) {
    return undefined;
  }
  const actionLabel =
    action === "reset"
      ? "reset into a smaller review loop"
      : action === "accept"
        ? "pulled back into training"
        : action === "snooze"
          ? "deferred for later review"
          : action === "done"
            ? "marked complete for this round"
            : action === "skip"
              ? "skipped for now"
              : action;
  return note
    ? `Latest review move: ${concept}, ${actionLabel}. ${note}`
    : `Latest review move: ${concept}, ${actionLabel}.`;
}

function actionLabel(language: ComposerLanguage, action: "mark_practiced" | "mark_applied" | "mark_transferable"): string {
  const isChinese = language === "zh-CN";
  if (action === "mark_practiced") {
    return isChinese ? "验证这次练习" : "Verify this practice";
  }
  if (action === "mark_applied") {
    return isChinese ? "验证这次应用" : "Verify this application";
  }
  return isChinese ? "请求验证迁移证据" : "Request transfer verification";
}

function formatReviewDate(value?: string): string | undefined {
  if (!value) {
    return undefined;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatReviewPercent(value?: number): string | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return undefined;
  }
  return `${Math.round(value * 100)}%`;
}

function firstDependency(
  maps: DependencySkillMap[] | undefined,
  mastery: DependencyMastery[],
): {
  dependencyKey: string;
  dependencyName: string;
  masteryStage?: DependencyMastery["masteryStage"];
  masteryScore: number;
  confidence: number;
  projectFirstCut?: string;
  suggestedScenarioLab?: string;
  prioritySummary?: string;
  relatedApi?: string;
  scenario?: string;
} | undefined {
  const map = maps?.[0];
  const record = map
    ? mastery.find((item) => item.dependencyKey === map.dependencyKey)
    : mastery[0];
  if (map) {
    const transferItem = (map.topReviewItems ?? []).find((item) => item.layer === "transfer");
    return {
      dependencyKey: map.dependencyKey,
      dependencyName: map.dependencyName ?? "",
      masteryStage: record?.masteryStage ?? map.masteryStage ?? "understood",
      masteryScore: record?.masteryScore ?? map.masteryScore ?? 0,
      confidence: record?.confidence ?? map.confidence ?? 0,
      projectFirstCut: map.projectFirstCut,
      suggestedScenarioLab: map.suggestedScenarioLab,
      prioritySummary: map.prioritySummary,
      relatedApi: transferItem?.relatedApi,
      scenario: transferItem?.scenario,
    };
  }
  if (!record) {
    return undefined;
  }
  return {
    dependencyKey: record.dependencyKey,
    dependencyName: record.dependencyName,
    masteryStage: record.masteryStage,
    masteryScore: record.masteryScore,
    confidence: record.confidence ?? 0,
    projectFirstCut: (record.currentUseCases ?? [])[0],
    prioritySummary: (record.weakestPoints ?? [])[0],
    relatedApi: (record.currentApis ?? [])[0],
    scenario: (record.practiceScenarios ?? [])[0],
  };
}

function buildCoachReturnBridge(input: {
  language: ComposerLanguage;
  task?: TaskSpec;
  selectedCardId?: string;
  selectedCardType?: "practice" | "flash";
  selectedCardTitle?: string;
  focusArea?: string;
  latestVerifiedResult?: string;
  latestReturnWith?: string;
  latestSuccessSignal?: string;
  latestLearningBlocker?: string;
  latestLearningPartialProgress?: string;
}): PracticeCoachBridge {
  const focus = normalizeText(input.focusArea) || input.task?.title || "";
  const cardId = normalizeText(input.selectedCardId) || input.task?.id || "";
  const cardType = input.selectedCardType || "practice";
  const cardTitle = normalizeText(input.selectedCardTitle) || input.task?.title || "";
  const summaryLines = [
    input.latestVerifiedResult
      ? text(input.language, `验证结果：${input.latestVerifiedResult}`, `Verification result: ${input.latestVerifiedResult}`)
      : undefined,
    input.latestLearningBlocker
      ? text(input.language, `当前卡点：${input.latestLearningBlocker}`, `Current blocker: ${input.latestLearningBlocker}`)
      : undefined,
    input.latestReturnWith
      ? text(input.language, `带回：${input.latestReturnWith}`, `Bring back: ${input.latestReturnWith}`)
      : undefined,
    input.latestSuccessSignal
      ? text(input.language, `通过信号：${input.latestSuccessSignal}`, `Pass signal: ${input.latestSuccessSignal}`)
      : undefined,
  ].filter((item): item is string => Boolean(item));

  const trainingReturn: TrainingReturnPayload | undefined = input.latestVerifiedResult
    ? {
        cardId,
        cardType,
        cardTitle,
        returnMode: "result",
        summary: input.latestVerifiedResult,
        verifiedResult: input.latestVerifiedResult,
        source: "training_bridge",
      }
    : input.latestLearningBlocker || input.latestLearningPartialProgress
      ? {
          cardId,
          cardType,
          cardTitle,
          returnMode: "blocker",
          summary: input.latestLearningPartialProgress || input.latestLearningBlocker || "",
          blocker: input.latestLearningBlocker || undefined,
          source: "training_bridge",
        }
      : undefined;

  return {
    title: text(input.language, `把「${focus}」带回教练判断`, `Bring "${focus}" back to coach`),
    prompt: text(
      input.language,
      `继续围绕「${focus}」教我，保持 coach-only，不替我改代码。先判断这张卡的结果，再决定下一步。`,
      `Keep coaching me on "${focus}" and stay coach-only. Do not edit code for me. Judge the result of this card first, then choose the next step.`,
    ),
    detail: text(
      input.language,
      "让教练判断它是通过、部分通过、降级、计划证据，还是需要回到闪卡巩固。",
      "Let the coach judge whether this was a pass, partial pass, downgrade, plan evidence, or flash reinforcement.",
    ),
    ctaLabel: text(input.language, "回到教练", "Return to coach"),
    summaryLines,
    trainingReturn,
  };
}

function compactWorkspaceRouteLabel(
  language: ComposerLanguage,
  workspaceId: string | undefined,
): string {
  const normalized = workspaceId?.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return text(language, "当前工作区", "Current workspace");
  }
  return normalized.length <= 36 ? normalized : `${normalized.slice(0, 33).trimEnd()}...`;
}

function isTrainingCardStatus(value: unknown): value is TrainingCardStatus {
  return (
    value === "candidate" ||
    value === "active" ||
    value === "needs_primer" ||
    value === "answered" ||
    value === "implemented" ||
    value === "completed" ||
    value === "reviewed" ||
    value === "fed_back" ||
    value === "archived" ||
    value === "skipped" ||
    value === "blocked"
  );
}

function pickVisibleFlashAttempt(deck?: FlashcardDeck): FlashcardAttempt | undefined {
  if (!deck || !Array.isArray(deck.cards) || deck.cards.length === 0) {
    return undefined;
  }
  const unanswered = deck.cards.find((candidate) => candidate.status === "unanswered" || !candidate.status);
  return unanswered ?? deck.cards[0];
}

export function CoachTrainingView({
  language,
  task,
  isLoading = false,
  workspaceUnderstanding,
  evidencePack,
  teachingDecision,
  recoveredRuntime,
  runtimeCurrentStep,
  implementationGuide,
  dependencyMastery,
  learningOutcomes,
  memoryLayers = [],
  workspaceAuthority,
  reviewSummary,
  practiceBusy = false,
  flashBusy = false,
  transferWorkspaceOptions = [],
  flashDeck,
  recentFlashAttempts,
  flashPracticeBridge,
  workspaceTrainingState,
  initialTrainingSubmode,
  onTrainingSubmodeChange,
  onRefreshTask,
  onQuickStartTraining,
  onOpenCoachFromPractice,
  onRefreshDeck,
  onSubmitFlashAnswer,
  onOpenCoachFromFlash,
  onOpenCoachBridgeFromFlash,
  onOpenPracticeFromFlash,
  onCreateFlashcard,
  onOpenResources,
  onDependencySkillMapAction,
  onCardStatusTransition,
  onVerifyCurrentFile,
  debugRestoreTarget,
  debugTheoryDrillId,
  debugScenarioLabId,
  debugReviewArtifactId,
  debugRestoredNextHop,
  onDebugVisibleFacts,
}: CoachTrainingViewProps) {
  const [mode, setMode] = useState<TrainingSurfaceMode>(normalizeMode(initialTrainingSubmode));
  const dependency = firstDependency(workspaceTrainingState?.dependencySkillMaps, dependencyMastery);
  const [transferDraft, setTransferDraft] = useState<TransferEvidenceDraft | undefined>(undefined);
  const [pendingCardStatusTransition, setPendingCardStatusTransition] = useState<{
    cardId: string;
    cardType: "practice" | "flash";
    sourceStatus: TrainingCardStatus;
    newStatus: TrainingCardStatus;
    requestedAt: number;
  } | null>(null);
  const cardStatusBusy = pendingCardStatusTransition !== null;
  const { ledgerSummary, routingSummary } = useMemo(
    () => {
      const nextRoutingSummary = workspaceTrainingState?.activeTrainingCardRouting as
        | {
            selectedCardId?: string;
            selectedCard?: { title?: string; type?: "practice" | "flash" };
            whyThisCard?: string;
            blockedCandidates?: Array<{
              cardId: string;
              type: "practice" | "flash";
              title: string;
              reasons: string[];
            }>;
            fallbackAction?: string;
            candidateCount?: number;
            eligibleCount?: number;
          }
        | undefined;
      const nextLedgerSummary = workspaceTrainingState?.trainingEventLedger?.map(
        (entry): TrainingEventLedgerEntrySummary => ({
        eventType: entry.eventType,
        candidateId: entry.candidateId,
        candidateStatus: entry.candidateStatus,
        candidateStatusReason: entry.candidateStatusReason,
        statusKind: entry.statusKind,
        statusSummary: entry.statusSummary,
        statusDetail: entry.statusDetail,
        candidateContinueIn:
          toTrainingLedgerContinueIn(entry.candidateContinueIn),
        candidateTargetKind: entry.candidateTargetKind,
        candidateTargetId: entry.candidateTargetId,
        candidateProjectScope: toTrainingLedgerProjectScope(entry.candidateProjectScope),
        candidateBlockedBy: entry.candidateBlockedBy,
        candidateAcceptedInto: entry.candidateAcceptedInto,
        candidateWhyNow: entry.candidateWhyNow,
        candidateTitle: entry.candidateTitle,
        candidateType:
          entry.candidateType === "project_context_candidate" ||
          entry.candidateType === "resource_import_candidate" ||
          entry.candidateType === "evidence_candidate" ||
          entry.candidateType === "flash_candidate" ||
          entry.candidateType === "practice_candidate" ||
          entry.candidateType === "coach_visible_status" ||
          entry.candidateType === "micro_drill_prompt" ||
          entry.candidateType === "card_invocation"
            ? (entry.candidateType as "project_context_candidate" | "resource_import_candidate" | "evidence_candidate" | "flash_candidate" | "practice_candidate" | "coach_visible_status" | "micro_drill_prompt" | "card_invocation")
            : undefined,
        selectedCardId: entry.selectedCardId,
        selectedCardType: (entry.selectedCardType === "practice" || entry.selectedCardType === "flash"
          ? entry.selectedCardType
          : undefined) as "practice" | "flash" | undefined,
        selectedCardTitle: entry.selectedCardTitle,
        cardCandidateId: entry.cardCandidateId,
        cardCandidateType: entry.cardCandidateType === "practice" ? "practice" : entry.cardCandidateType === "flash" ? "flash" : undefined,
        cardCandidateTitle: entry.cardCandidateTitle,
        whyThisCard: entry.whyThisCard,
        nextAfterCompletion: entry.nextAfterCompletion,
        fallbackAction: entry.fallbackAction,
        returnMode: entry.returnMode === "result" ? "result" : entry.returnMode === "blocker" ? "blocker" : undefined,
        returnSummary: entry.returnSummary,
        judgedAt: entry.judgedAt,
        sourceChain: entry.sourceChain,
        blockedCandidates: entry.blockedCandidates,
        createdAt: entry.createdAt,
      }));
      return { ledgerSummary: nextLedgerSummary, routingSummary: nextRoutingSummary };
    },
    [workspaceTrainingState?.activeTrainingCardRouting, workspaceTrainingState?.trainingEventLedger],
  );
  const resolvedHandoff = useMemo(
    () =>
      resolveTrainingHandoff({
        latestTrainingHandoff: workspaceTrainingState?.latestTrainingHandoff,
        latestConversationHandoff: workspaceTrainingState?.latestConversationHandoff,
        latestTrainingSubmode: workspaceTrainingState?.latestTrainingSubmode,
        selectedCardId: workspaceTrainingState?.selectedCardId,
        selectedCardType: workspaceTrainingState?.selectedCardType,
        selectedCardTitle: workspaceTrainingState?.selectedCardTitle,
        trainingCardCandidates: Array.isArray(workspaceTrainingState?.trainingCardCandidates)
          ? (workspaceTrainingState?.trainingCardCandidates as Array<{
              id: string;
              type: "practice" | "flash";
              title: string;
              whyNow?: string;
            }>)
          : undefined,
        activeTrainingCardRouting: routingSummary,
        trainingEventLedger: ledgerSummary,
      }),
    [
      ledgerSummary,
      routingSummary,
      workspaceTrainingState?.latestConversationHandoff,
      workspaceTrainingState?.latestTrainingHandoff,
      workspaceTrainingState?.latestTrainingSubmode,
      workspaceTrainingState?.selectedCardId,
      workspaceTrainingState?.selectedCardTitle,
      workspaceTrainingState?.selectedCardType,
      workspaceTrainingState?.trainingCardCandidates,
    ],
  );
  const resolvedNextHop = useMemo(
    () =>
      resolveTrainingNextHop({
        language,
        latestTrainingNextHop:
          debugRestoreTarget === "next_hop" && debugRestoredNextHop
            ? debugRestoredNextHop
            : workspaceTrainingState?.latestTrainingNextHop,
        trainingEventLedger: ledgerSummary,
      }),
    [debugRestoreTarget, debugRestoredNextHop, language, workspaceTrainingState?.latestTrainingNextHop, workspaceTrainingState?.trainingEventLedger],
  );
  const restoredNextHopSource =
    debugRestoreTarget === "next_hop"
      ? debugRestoredNextHop ?? workspaceTrainingState?.latestTrainingNextHop
      : undefined;
  const nextHopDisplay = useMemo(() => {
    if (!restoredNextHopSource) {
      return resolvedNextHop;
    }

    const displayCopy = summarizeTrainingNextHopCopy(language, {
      title: restoredNextHopSource.title || restoredNextHopSource.cardTitle || resolvedNextHop.title,
      summary:
        restoredNextHopSource.summary ||
        restoredNextHopSource.returnSummary ||
        restoredNextHopSource.handoffSummary ||
        resolvedNextHop.summary,
      nextAfterCompletion:
        restoredNextHopSource.nextAfterCompletion || resolvedNextHop.nextAfterCompletion,
      whyNow: restoredNextHopSource.whyNow || resolvedNextHop.whyNow,
      statusReason: restoredNextHopSource.statusReason || resolvedNextHop.statusReason,
      blockedBy: restoredNextHopSource.blockedBy || resolvedNextHop.blockedBy,
      handoffSummary: restoredNextHopSource.handoffSummary || resolvedNextHop.handoffSummary,
      fallbackAction: restoredNextHopSource.fallbackAction || resolvedNextHop.fallbackAction,
    });
    const hasStructuredTarget = Boolean(
      restoredNextHopSource.candidateType ||
        restoredNextHopSource.targetKind ||
        restoredNextHopSource.targetId ||
        restoredNextHopSource.continueIn ||
        restoredNextHopSource.status ||
        restoredNextHopSource.reviewArtifactId ||
        restoredNextHopSource.planEvidenceId,
    );
    return {
      ...resolvedNextHop,
      shouldRender: true,
      hasRenderableCopy: Boolean(
        displayCopy.title || displayCopy.summary || displayCopy.detail || restoredNextHopSource.cardTitle,
      ),
      hasStructuredTarget: resolvedNextHop.hasStructuredTarget || hasStructuredTarget,
      candidateId: restoredNextHopSource.candidateId || resolvedNextHop.candidateId,
      candidateType: restoredNextHopSource.candidateType || resolvedNextHop.candidateType,
      title: displayCopy.title || resolvedNextHop.title,
      summary: displayCopy.summary || resolvedNextHop.summary,
      whyNow: displayCopy.detail || resolvedNextHop.whyNow,
      projectScope: restoredNextHopSource.projectScope || resolvedNextHop.projectScope,
      continueIn: restoredNextHopSource.continueIn || resolvedNextHop.continueIn,
      targetKind: restoredNextHopSource.targetKind || resolvedNextHop.targetKind,
      targetId: restoredNextHopSource.targetId || resolvedNextHop.targetId,
      acceptedInto: restoredNextHopSource.acceptedInto || resolvedNextHop.acceptedInto,
      status: restoredNextHopSource.status || resolvedNextHop.status,
      statusReason: restoredNextHopSource.statusReason || resolvedNextHop.statusReason,
      blockedBy: restoredNextHopSource.blockedBy || resolvedNextHop.blockedBy,
      handoffStatus: restoredNextHopSource.handoffStatus || resolvedNextHop.handoffStatus,
      handoffSummary: restoredNextHopSource.handoffSummary || resolvedNextHop.handoffSummary,
      coachOnly: restoredNextHopSource.coachOnly ?? resolvedNextHop.coachOnly,
      cardType: restoredNextHopSource.cardType || resolvedNextHop.cardType,
      cardTitle: restoredNextHopSource.cardTitle || resolvedNextHop.cardTitle || displayCopy.title,
      returnMode: restoredNextHopSource.returnMode || resolvedNextHop.returnMode,
      returnSummary: restoredNextHopSource.returnSummary || resolvedNextHop.returnSummary,
      judgedAt: restoredNextHopSource.judgedAt || resolvedNextHop.judgedAt,
      reviewArtifactId: restoredNextHopSource.reviewArtifactId || resolvedNextHop.reviewArtifactId,
      reviewArtifactStatus:
        restoredNextHopSource.reviewArtifactStatus || resolvedNextHop.reviewArtifactStatus,
      reviewRecoveryMode: restoredNextHopSource.reviewRecoveryMode || resolvedNextHop.reviewRecoveryMode,
      planEvidenceId: restoredNextHopSource.planEvidenceId || resolvedNextHop.planEvidenceId,
      nextAfterCompletion:
        restoredNextHopSource.nextAfterCompletion || resolvedNextHop.nextAfterCompletion,
      fallbackAction: restoredNextHopSource.fallbackAction || resolvedNextHop.fallbackAction,
      sourceChain:
        restoredNextHopSource.sourceChain?.map((item) => item.trim()).filter(Boolean) ??
        resolvedNextHop.sourceChain,
      canContinue:
        resolvedNextHop.canContinue ||
        Boolean(
          restoredNextHopSource.continueIn &&
            restoredNextHopSource.status &&
            ["created", "surfaced", "deferred", "blocked"].includes(restoredNextHopSource.status),
        ),
    };
  }, [language, resolvedNextHop, restoredNextHopSource]);
  const isNextHopRestoreForeground = Boolean(restoredNextHopSource);

  useEffect(() => {
    setMode(normalizeMode(initialTrainingSubmode));
  }, [initialTrainingSubmode]);

  const liveTrainingFocusChrome = preferRecoveredTrainingFocusChrome({
    recovered: recoveredRuntime,
    runtimeCurrentStep,
    teachingDecisionFocusArea: teachingDecision?.focusArea,
    latestLearningFocusArea: workspaceTrainingState?.latestLearningFocusArea,
  });
  const focus = normalizeText(
    liveTrainingFocusChrome.latestLearningFocusArea ||
      liveTrainingFocusChrome.teachingDecisionFocusArea,
  );

  const latestTransfer = dependency
    ? dependencyMastery.find((item) => item.dependencyKey === dependency.dependencyKey)
    : undefined;

  const defaultTransferDraft = useMemo(
    () =>
      dependency
        ? buildTransferEvidenceDraft({
            currentWorkspaceId: workspaceTrainingState?.workspaceId,
            coachFocus: focus,
            returnTarget:
              workspaceTrainingState?.latestLearningVerifiedResult ||
              workspaceTrainingState?.latestLearningFollowup,
            dependency,
            workspaceOptions: transferWorkspaceOptions,
            latestTransfer: {
              sourceWorkspaceId:
                workspaceTrainingState?.latestTransferSourceWorkspaceId ||
                latestTransfer?.latestTransferSourceWorkspaceId,
              targetWorkspaceId:
                workspaceTrainingState?.latestTransferTargetWorkspaceId ||
                latestTransfer?.latestTransferTargetWorkspaceId,
              verifiedResult:
                workspaceTrainingState?.latestTransferVerifiedResult ||
                latestTransfer?.latestTransferVerifiedResult,
            },
            latestEvidence: latestTransfer?.transferEvidence?.[0],
            weakItem: {
              label: dependency.prioritySummary,
              relatedApi: dependency.relatedApi,
              scenario: dependency.scenario,
              nextAction: dependency.projectFirstCut,
            },
          })
        : undefined,
    [
      dependency,
      focus,
      latestTransfer,
      transferWorkspaceOptions,
      workspaceTrainingState?.latestLearningFollowup,
      workspaceTrainingState?.latestLearningVerifiedResult,
      workspaceTrainingState?.latestTransferSourceWorkspaceId,
      workspaceTrainingState?.latestTransferTargetWorkspaceId,
      workspaceTrainingState?.latestTransferVerifiedResult,
      workspaceTrainingState?.workspaceId,
    ],
  );

  useEffect(() => {
    if (!defaultTransferDraft) {
      setTransferDraft((current) => (current ? undefined : current));
      return;
    }
    setTransferDraft((current) => {
      if (!current || current.dependencyKey !== defaultTransferDraft.dependencyKey) {
        return defaultTransferDraft;
      }
      const currentTarget = normalizeText(current.targetWorkspaceId);
      const defaultTarget = normalizeText(defaultTransferDraft.targetWorkspaceId);
      const mergedDraft: TransferEvidenceDraft = {
        ...current,
        sourceWorkspaceId: normalizeText(current.sourceWorkspaceId) || defaultTransferDraft.sourceWorkspaceId,
        targetWorkspaceId:
          !currentTarget || currentTarget === normalizeText(current.sourceWorkspaceId)
            ? defaultTarget || current.targetWorkspaceId
            : current.targetWorkspaceId,
        sourceContext: normalizeText(current.sourceContext) || defaultTransferDraft.sourceContext,
        targetContext: normalizeText(current.targetContext) || defaultTransferDraft.targetContext,
        verifiedResult: normalizeText(current.verifiedResult) || defaultTransferDraft.verifiedResult,
        evidenceSummary: normalizeText(current.evidenceSummary) || defaultTransferDraft.evidenceSummary,
        focusItemKey: normalizeText(current.focusItemKey) || defaultTransferDraft.focusItemKey,
        relatedApi: normalizeText(current.relatedApi) || defaultTransferDraft.relatedApi,
        scenario: normalizeText(current.scenario) || defaultTransferDraft.scenario,
      };
      return areTransferDraftsEqual(current, mergedDraft) ? current : mergedDraft;
    });
  }, [defaultTransferDraft]);

  const transferReady = Boolean(
    normalizeText(transferDraft?.sourceWorkspaceId) &&
      normalizeText(transferDraft?.targetWorkspaceId) &&
      normalizeText(transferDraft?.verifiedResult) &&
      normalizeText(transferDraft?.sourceWorkspaceId) !== normalizeText(transferDraft?.targetWorkspaceId),
  );
  const stageAction = nextActionForStage(dependency?.masteryStage);
  const canSubmitStage = Boolean(onDependencySkillMapAction && dependency);
  const canSubmitTransfer = Boolean(canSubmitStage && transferDraft && transferReady);

  const trainingPausedByResourceRisk = resolvedHandoff.pausedByResourceRisk;
  const handoffContractVisible = Boolean(
    resolvedHandoff.learnerDeliverables.length ||
      resolvedHandoff.verificationSteps.length ||
      resolvedHandoff.successSignal ||
      resolvedHandoff.returnWith ||
      resolvedHandoff.nextAfterCompletion,
  );
  const routeWorkspaceLabel = compactWorkspaceRouteLabel(language, workspaceTrainingState?.workspaceId);
  const showTrainingRouteStrip = Boolean(
    !isNextHopRestoreForeground &&
      resolvedHandoff.shouldRender &&
      (trainingPausedByResourceRisk ||
        resolvedHandoff.selectedCardId ||
        resolvedHandoff.selectedCardTitle ||
        workspaceTrainingState?.selectedCardId ||
        workspaceTrainingState?.selectedCardTitle),
  );
  const primaryCardTitle =
    (isNextHopRestoreForeground
      ? nextHopDisplay.cardTitle || nextHopDisplay.title || nextHopDisplay.summary
      : resolvedHandoff.selectedCardTitle) ||
    workspaceTrainingState?.selectedCardTitle ||
    text(language, "等待训练路由确认当前卡片", "Waiting for the training router to confirm the card");
  const primaryCardReason = trainingPausedByResourceRisk
    ? text(
        language,
        "这张训练卡被资料风险暂停。继续前先刷新来源资料。",
        "This training card is paused by resource risk. Refresh the source material before continuing.",
      )
    : isNextHopRestoreForeground
      ? nextHopDisplay.whyNow ||
        nextHopDisplay.handoffSummary ||
        nextHopDisplay.summary ||
        text(
          language,
          "恢复的下一步已经成为前景，旧的理论、场景和复习对象不再抢占当前卡片。",
          "The restored next hop is now the foreground, so legacy theory, scenario, and review objects no longer take over the lane.",
        )
      : resolvedHandoff.whyThisCard ||
        resolvedHandoff.handoffSummary ||
        text(
          language,
          "这张卡来自对话交接，训练页现在只聚焦这一张当前卡。",
          "This card came from conversation, and training now stays focused on this single current card.",
        );
  const primaryCardTypeLabel =
    (isNextHopRestoreForeground ? nextHopDisplay.cardType : resolvedHandoff.selectedCardType) === "flash"
      ? text(language, "闪卡", "Flash card")
      : text(language, "练习卡", "Practice card");
  const resourceRiskReason =
    resolvedHandoff.resourceRiskReason ||
    resolvedHandoff.blockedReason ||
    text(
      language,
      "关联资料已经过期或可信度不足。继续训练卡前，先在资料页刷新。",
      "A linked resource is stale or not trusted enough. Refresh it in Resources before continuing this training card.",
    );
  const practiceCoachBridge = buildCoachReturnBridge({
    language,
    task,
    selectedCardId:
      (isNextHopRestoreForeground ? nextHopDisplay.targetId || nextHopDisplay.candidateId : resolvedHandoff.selectedCardId) ||
      workspaceTrainingState?.selectedCardId,
    selectedCardType:
      (isNextHopRestoreForeground ? nextHopDisplay.cardType : resolvedHandoff.selectedCardType) ||
      workspaceTrainingState?.selectedCardType,
    selectedCardTitle:
      (isNextHopRestoreForeground ? primaryCardTitle : resolvedHandoff.selectedCardTitle) ||
      workspaceTrainingState?.selectedCardTitle,
    focusArea: focus,
    latestVerifiedResult: workspaceTrainingState?.latestLearningVerifiedResult,
    latestReturnWith: resolvedHandoff.returnWith,
    latestSuccessSignal: resolvedHandoff.successSignal,
    latestLearningBlocker: workspaceTrainingState?.latestLearningBlocker,
    latestLearningPartialProgress: workspaceTrainingState?.latestLearningPartialProgress,
  });
  const nextHopCopy = summarizeTrainingNextHopCopy(language, {
    title:
      nextHopDisplay.title ||
      nextHopDisplay.summary ||
      nextHopDisplay.nextAfterCompletion,
    summary:
      nextHopDisplay.summary ||
      nextHopDisplay.returnSummary ||
      nextHopDisplay.handoffSummary ||
      nextHopDisplay.nextAfterCompletion,
    nextAfterCompletion:
      nextHopDisplay.nextAfterCompletion,
    whyNow: nextHopDisplay.whyNow,
    statusReason: nextHopDisplay.statusReason,
    blockedBy: nextHopDisplay.blockedBy,
    handoffSummary: nextHopDisplay.handoffSummary,
    fallbackAction: nextHopDisplay.fallbackAction,
  });
  const completionNextHopMeta = [
    nextHopStatusLabel(language, nextHopDisplay.status),
    nextHopContinueLabel(language, nextHopDisplay.continueIn),
    nextHopScopeLabel(language, nextHopDisplay.projectScope),
  ].filter((item): item is string => Boolean(item));
  const nextHopHasStructuredAuthority = Boolean(
    nextHopDisplay.hasStructuredTarget ||
      nextHopDisplay.candidateType ||
      nextHopDisplay.targetKind ||
      nextHopDisplay.targetId ||
      nextHopDisplay.continueIn ||
      nextHopDisplay.status ||
      nextHopDisplay.reviewArtifactId ||
      nextHopDisplay.planEvidenceId,
  );
  const nextHopShouldRender = Boolean(nextHopDisplay.shouldRender || nextHopHasStructuredAuthority);
  const completionNextHopDetail = normalizeText(
    nextHopShouldRender
      ? nextHopCopy.detail ||
          nextHopDisplay.handoffSummary ||
          nextHopDisplay.whyNow ||
          nextHopDisplay.statusReason ||
          nextHopDisplay.summary
      : undefined,
  );
  const completionNextHop = normalizeText(
    nextHopShouldRender
      ? nextHopCopy.title ||
          nextHopCopy.summary ||
          nextHopDisplay.title ||
      nextHopDisplay.summary ||
      nextHopDisplay.cardTitle
      : undefined,
  );
  const nextHopPrimaryTitle = normalizeText(
    completionNextHop ||
      nextHopDisplay.cardTitle ||
      nextHopDisplay.title ||
      nextHopDisplay.summary ||
      (nextHopShouldRender
        ? text(language, "下一步已经成形", "Next hop materialized")
        : undefined),
  );
  const coachJudgmentPending = false;
  const coachJudgmentSummary = normalizeText(
    summarizeWaitingCoachJudgment(language, {
      returnSummary: workspaceTrainingState?.latestTrainingHandoff?.returnSummary,
      handoffSummary: workspaceTrainingState?.latestTrainingHandoff?.handoffSummary,
    }).summary,
  );
  const latestReviewQueueActionSummary = useMemo(
    () =>
      summarizeLatestReviewQueueAction(
        language,
        workspaceTrainingState?.reviewQueueActions,
        workspaceTrainingState?.trainingEventLedger,
      ),
    [language, workspaceTrainingState?.reviewQueueActions, workspaceTrainingState?.trainingEventLedger],
  );
  const latestReviewQueueLedgerEvent = useMemo(
    () =>
      [...(workspaceTrainingState?.trainingEventLedger ?? [])]
        .filter((entry) => entry.eventType === "review_queue_action_recorded")
        .sort((left, right) => Date.parse(right.createdAt ?? right.timestamp) - Date.parse(left.createdAt ?? left.timestamp))[0],
    [workspaceTrainingState?.trainingEventLedger],
  );
  const singleCardImmersive = true;
  const routeStripCollapsedByDefault = true;
  const cardOnlyMode = true;
  const secondaryPanelsCollapsedByDefault = true;
  const [secondaryPanelsOpen, setSecondaryPanelsOpen] = useState(false);
  // chainExpanded stays collapsed by default; route + mastery panels live behind the
  // mastery toggle and the route details summary, so we no longer expose a setter.
  const chainExpanded = false;
  const [masteryPanelVisible, setMasteryPanelVisible] = useState(false);
  const visibleTheoryDrill =
    !isNextHopRestoreForeground &&
    workspaceTrainingState?.theoryDrill &&
    (!debugTheoryDrillId || workspaceTrainingState.theoryDrill.id === debugTheoryDrillId)
      ? workspaceTrainingState.theoryDrill
      : undefined;
  const visibleScenarioLab =
    !isNextHopRestoreForeground &&
    workspaceTrainingState?.scenarioLab &&
    (!debugScenarioLabId || workspaceTrainingState.scenarioLab.id === debugScenarioLabId)
      ? workspaceTrainingState.scenarioLab
      : undefined;
  const visibleReviewArtifact =
    !isNextHopRestoreForeground &&
    workspaceTrainingState?.reviewArtifact &&
    (!debugReviewArtifactId || workspaceTrainingState.reviewArtifact.id === debugReviewArtifactId)
      ? workspaceTrainingState.reviewArtifact
      : undefined;
  const visibleTheoryQuestion =
    visibleTheoryDrill && Array.isArray(visibleTheoryDrill.questions) && visibleTheoryDrill.questions.length > 0
      ? visibleTheoryDrill.questions[
          Math.max(
            0,
            Math.min(
              visibleTheoryDrill.currentQuestionIndex ?? 0,
              visibleTheoryDrill.questions.length - 1,
            ),
          )
        ]
      : undefined;
  const visibleActiveSubmode =
    debugRestoreTarget === "theory_drill"
      ? "flash"
      : debugRestoreTarget === "scenario_lab" ||
          debugRestoreTarget === "review_artifact" ||
          debugRestoreTarget === "next_hop" ||
          isNextHopRestoreForeground
        ? "practice"
        : workspaceTrainingState?.latestTrainingSubmode;
  const nextHopVisible = Boolean(
    nextHopShouldRender &&
      (nextHopPrimaryTitle ||
        completionNextHopDetail ||
        nextHopDisplay.handoffSummary ||
        nextHopDisplay.whyNow ||
        nextHopDisplay.status ||
        nextHopDisplay.targetId ||
        nextHopDisplay.candidateId ||
        nextHopDisplay.reviewArtifactId ||
        nextHopDisplay.planEvidenceId ||
        (debugRestoreTarget === "next_hop" &&
          (debugRestoredNextHop?.status ||
            nextHopDisplay.status ||
            debugRestoredNextHop?.targetId ||
            nextHopDisplay.targetId ||
            debugRestoredNextHop?.candidateId ||
            nextHopDisplay.candidateId))),
  );
  const visiblePracticeTask =
    isNextHopRestoreForeground && (completionNextHop || nextHopDisplay.cardTitle || nextHopDisplay.summary) && task
      ? {
          ...task,
          id: nextHopDisplay.targetId || nextHopDisplay.candidateId || task.id,
          title: nextHopDisplay.cardTitle || completionNextHop || task.title,
          description:
            nextHopDisplay.summary ||
            nextHopDisplay.handoffSummary ||
            nextHopDisplay.whyNow ||
            task.description,
          nextActionLabel:
            nextHopDisplay.continueIn === "plan"
              ? text(language, "回到计划继续", "Continue in plan")
              : nextHopDisplay.continueIn === "chat"
                ? text(language, "回到对话继续", "Return to coach")
                : text(language, "继续训练", "Continue training"),
          constraints:
            task.constraints.length > 0
              ? task.constraints
              : [
                  nextHopDisplay.whyNow ||
                    text(
                      language,
                      "恢复的下一步必须留在前景，不再回退到旧链路。",
                      "The restored next hop must stay in the foreground; do not fall back to the old chain.",
                    ),
                ].filter((item): item is string => Boolean(item)),
          acceptanceCriteria:
            (task.acceptanceCriteria ?? []).length > 0
              ? task.acceptanceCriteria
              : [
                  nextHopDisplay.nextAfterCompletion ||
                    nextHopDisplay.returnSummary ||
                    nextHopDisplay.handoffSummary ||
                    text(
                      language,
                      "训练视图需要直接展示并解释当前下一步。",
                      "The training view should directly show and explain the current next hop.",
                    ),
                ].filter((item): item is string => Boolean(item)),
        }
      : task;
  const reviewTruth = useMemo(
    () =>
      summarizeReviewQueueTruth(
        workspaceTrainingState?.dueReviews ?? [],
        latestReviewQueueActionSummary,
        language,
      ),
    [language, latestReviewQueueActionSummary, workspaceTrainingState?.dueReviews],
  );
  const effectiveReviewSummary = useMemo(() => {
    const uniqueLines: string[] = [];
    for (const candidate of [reviewSummary, reviewTruth?.headline, reviewTruth?.detail]) {
      const normalized = normalizeText(candidate);
      if (!normalized || uniqueLines.includes(normalized)) {
        continue;
      }
      uniqueLines.push(normalized);
    }
    return uniqueLines.length ? uniqueLines.join(" ") : undefined;
  }, [reviewSummary, reviewTruth?.detail, reviewTruth?.headline]);
  const visibleFlashCard = useMemo(() => pickVisibleFlashAttempt(flashDeck), [flashDeck]);
  const normalizedTrainingCardCandidates = useMemo(() => {
    if (!Array.isArray(workspaceTrainingState?.trainingCardCandidates)) {
      return [];
    }
    const normalizedCandidates: Array<{
      id: string;
      type?: "practice" | "flash";
      status?: TrainingCardStatus;
    }> = [];
    for (const entry of workspaceTrainingState.trainingCardCandidates) {
      if (!entry || typeof entry !== "object") {
        continue;
      }
      const candidate = entry as {
        id?: string;
        cardId?: string;
        type?: string;
        card_type?: string;
        status?: unknown;
      };
      const id = normalizeText(candidate.id ?? candidate.cardId);
      if (!id) {
        continue;
      }
      const type =
        candidate.type === "flash" || candidate.card_type === "flash"
          ? "flash"
          : candidate.type === "practice" || candidate.card_type === "practice"
            ? "practice"
            : undefined;
      const status = isTrainingCardStatus(candidate.status) ? candidate.status : undefined;
      normalizedCandidates.push({ id, type, status });
    }
    return normalizedCandidates;
  }, [workspaceTrainingState?.trainingCardCandidates]);

  const selectedCardMeta = useMemo(() => {
    if (
      !workspaceTrainingState?.selectedCardId ||
      !Array.isArray(workspaceTrainingState.trainingCardCandidates)
    ) {
      return undefined;
    }
    const normalizedSelectedId = normalizeText(workspaceTrainingState.selectedCardId);
    for (const entry of workspaceTrainingState.trainingCardCandidates) {
      if (!entry || typeof entry !== "object") continue;
      const candidate = entry as {
        id?: string;
        cardId?: string;
        focus_area?: string;
        focusArea?: string;
        target_skill?: string;
        targetSkill?: string;
        scenario_pack?: string;
        scenarioPack?: string;
        why_now?: string;
        whyNow?: string;
        source_chain?: string[];
        sourceChain?: string[];
        feedback_targets?: string[];
        feedbackTargets?: string[];
      };
      const id = normalizeText(candidate.id ?? candidate.cardId);
      if (id === normalizedSelectedId) {
        return {
          focusArea: candidate.focus_area ?? candidate.focusArea ?? "",
          targetSkill: candidate.target_skill ?? candidate.targetSkill ?? "",
          scenarioPack: candidate.scenario_pack ?? candidate.scenarioPack ?? "",
          whyNow: candidate.why_now ?? candidate.whyNow ?? "",
          sourceChain: Array.isArray(candidate.source_chain)
            ? candidate.source_chain
            : Array.isArray(candidate.sourceChain)
              ? candidate.sourceChain
              : undefined,
          feedbackTargets: Array.isArray(candidate.feedback_targets)
            ? candidate.feedback_targets
            : Array.isArray(candidate.feedbackTargets)
              ? candidate.feedbackTargets
              : undefined,
        };
      }
    }
    return undefined;
  }, [workspaceTrainingState?.selectedCardId, workspaceTrainingState?.trainingCardCandidates]);
  const scenarioPackLabel = useMemo(
    () =>
      summarizeTrainingScenarioPack(
        language,
        selectedCardMeta?.scenarioPack ??
          workspaceTrainingState?.latestTrainingHandoff?.scenarioPack ??
          workspaceTrainingState?.latestTrainingNextHop?.scenarioPack,
      ),
    [
      language,
      selectedCardMeta?.scenarioPack,
      workspaceTrainingState?.latestTrainingHandoff?.scenarioPack,
      workspaceTrainingState?.latestTrainingNextHop?.scenarioPack,
    ],
  );

  const selectedDueReview = useMemo(() => {
    const dueReviews = workspaceTrainingState?.dueReviews;
    if (!Array.isArray(dueReviews) || dueReviews.length === 0) {
      return undefined;
    }

    const selectedKeys = [
      selectedCardMeta?.focusArea,
      selectedCardMeta?.targetSkill,
      selectedCardMeta?.whyNow,
      selectedCardMeta?.sourceChain?.[0],
      workspaceTrainingState?.selectedCardTitle,
    ]
      .map((value) => normalizeText(value)?.toLowerCase())
      .filter((value): value is string => Boolean(value));

    if (selectedKeys.length === 0) {
      return undefined;
    }

    for (const review of dueReviews) {
      const reviewKeys = [review.focusArea, review.concept, review.taskHint]
        .map((value) => normalizeText(value)?.toLowerCase())
        .filter((value): value is string => Boolean(value));
      if (
        reviewKeys.some((key) => selectedKeys.includes(key)) ||
        selectedKeys.some((key) => reviewKeys.includes(key))
      ) {
        return review;
      }
    }

    return undefined;
  }, [
    selectedCardMeta?.sourceChain,
    selectedCardMeta?.focusArea,
    selectedCardMeta?.targetSkill,
    selectedCardMeta?.whyNow,
    workspaceTrainingState?.dueReviews,
    workspaceTrainingState?.selectedCardTitle,
  ]);

  const visibleMemoryLayers = useMemo(() => memoryLayers.slice(0, 4), [memoryLayers]);

  function resolveTrainingCardStatus(
    cardId: string | undefined,
    cardType: "practice" | "flash",
  ): TrainingCardStatus {
    const normalizedCardId = normalizeText(cardId);
    const selectedCardId = normalizeText(workspaceTrainingState?.selectedCardId);
    const selectedCardType = workspaceTrainingState?.selectedCardType;

    if (
      normalizedCardId &&
      selectedCardId === normalizedCardId &&
      (!selectedCardType || selectedCardType === cardType) &&
      workspaceTrainingState?.selectedCardStatus
    ) {
      return workspaceTrainingState.selectedCardStatus;
    }

    const candidateStatus = normalizedTrainingCardCandidates.find(
      (candidate) =>
        candidate.id === normalizedCardId &&
        (!candidate.type || candidate.type === cardType) &&
        candidate.status,
    )?.status;
    if (candidateStatus) {
      return candidateStatus;
    }

    if (cardType === "flash") {
      const flashStatus = visibleFlashCard?.status;
      return visibleFlashCard?.cardId === normalizedCardId &&
        flashStatus &&
        flashStatus !== "unanswered"
        ? "answered"
        : "active";
    }

    return "active";
  }

  const visibleCardType = mode === "flash" ? "flash" : "practice";
  const visibleCardId = normalizeText(
    mode === "flash" ? visibleFlashCard?.cardId : visiblePracticeTask?.id,
  );
  const visibleCardStatus = resolveTrainingCardStatus(visibleCardId, visibleCardType);
  useEffect(() => {
    if (!pendingCardStatusTransition) {
      return;
    }
    if (
      !visibleCardId ||
      visibleCardId !== pendingCardStatusTransition.cardId ||
      visibleCardType !== pendingCardStatusTransition.cardType
    ) {
      setPendingCardStatusTransition(null);
      return;
    }
    if (visibleCardStatus === pendingCardStatusTransition.newStatus) {
      setPendingCardStatusTransition(null);
      return;
    }
    if (
      visibleCardStatus !== pendingCardStatusTransition.sourceStatus &&
      visibleCardStatus !== pendingCardStatusTransition.newStatus
    ) {
      setPendingCardStatusTransition(null);
    }
  }, [pendingCardStatusTransition, visibleCardId, visibleCardStatus, visibleCardType]);

  useEffect(() => {
    if (!pendingCardStatusTransition) {
      return;
    }
    const timeoutId = window.setTimeout(() => {
      setPendingCardStatusTransition((current) =>
        current?.requestedAt === pendingCardStatusTransition.requestedAt ? null : current,
      );
    }, 4000);
    return () => window.clearTimeout(timeoutId);
  }, [pendingCardStatusTransition]);

  useEffect(() => {
    onDebugVisibleFacts?.({
      surfaceMode: mode,
      activeSubmode: visibleActiveSubmode,
      visibleCaption:
        (coachJudgmentPending ? coachJudgmentSummary : latestReviewQueueActionSummary) ?? undefined,
      latestReviewQueueActionSummary,
      coachJudgmentPending,
      coachJudgmentSummary,
      selectedCardTitle:
        workspaceTrainingState?.selectedCardTitle ??
        resolvedHandoff.selectedCardTitle ??
        primaryCardTitle,
      routeWorkspaceLabel,
      theoryDrillVisible: Boolean(visibleTheoryDrill),
      theoryDrillId: visibleTheoryDrill?.id,
      theoryDrillTitle: visibleTheoryDrill?.title,
      theoryDrillStatus: visibleTheoryDrill?.status,
      theoryQuestionPrompt: visibleTheoryQuestion?.prompt,
      theoryQuestionKnowledgeType: visibleTheoryQuestion?.knowledgeType,
      scenarioLabVisible: Boolean(visibleScenarioLab),
      scenarioLabId: visibleScenarioLab?.id,
      scenarioLabTitle: visibleScenarioLab?.title,
      scenarioLabStatus: visibleScenarioLab?.status,
      scenarioLabScenario: visibleScenarioLab?.scenario,
      reviewArtifactVisible: Boolean(visibleReviewArtifact),
      reviewArtifactId: visibleReviewArtifact?.id,
      reviewArtifactStatus: visibleReviewArtifact?.status,
      reviewArtifactSummary:
        visibleReviewArtifact?.summary ?? visibleReviewArtifact?.verifiedResult ?? visibleReviewArtifact?.blocker,
      nextHopVisible,
      nextHopTitle: nextHopVisible ? nextHopPrimaryTitle : undefined,
      nextHopStatus: nextHopDisplay.status ?? debugRestoredNextHop?.status,
      nextHopContinueIn: nextHopDisplay.continueIn ?? debugRestoredNextHop?.continueIn,
      nextHopCardTitle: nextHopDisplay.cardTitle ?? debugRestoredNextHop?.cardTitle,
      nextHopCandidateType: nextHopDisplay.candidateType ?? debugRestoredNextHop?.candidateType,
      nextHopTargetKind: nextHopDisplay.targetKind ?? debugRestoredNextHop?.targetKind,
      nextHopTargetId: nextHopDisplay.targetId ?? debugRestoredNextHop?.targetId,
      nextHopReviewArtifactId:
        nextHopDisplay.reviewArtifactId ?? debugRestoredNextHop?.reviewArtifactId,
      nextHopPlanEvidenceId: nextHopDisplay.planEvidenceId ?? debugRestoredNextHop?.planEvidenceId,
      latestReviewQueueEventType: latestReviewQueueLedgerEvent?.eventType,
      latestReviewQueueAttemptKind: latestReviewQueueLedgerEvent?.attemptKind,
      latestReviewQueueAuthoritySource: latestReviewQueueLedgerEvent?.authoritySource,
      latestReviewQueueCurrentSubmode: latestReviewQueueLedgerEvent?.currentSubmode,
      singleCardImmersive,
      routeStripCollapsedByDefault,
      cardOnlyMode,
      secondaryPanelsCollapsedByDefault,
      secondaryPanelsOpen,
    });
  }, [
    cardOnlyMode,
    coachJudgmentPending,
    coachJudgmentSummary,
    latestReviewQueueActionSummary,
    latestReviewQueueLedgerEvent,
    mode,
    onDebugVisibleFacts,
    primaryCardTitle,
    routeStripCollapsedByDefault,
    resolvedHandoff.selectedCardTitle,
    nextHopDisplay.candidateType,
    nextHopDisplay.cardTitle,
    nextHopDisplay.continueIn,
    nextHopDisplay.fallbackAction,
    nextHopDisplay.handoffSummary,
    nextHopDisplay.hasRenderableCopy,
    nextHopDisplay.hasStructuredTarget,
    nextHopDisplay.planEvidenceId,
    nextHopDisplay.reviewArtifactId,
    nextHopDisplay.summary,
    nextHopDisplay.status,
    nextHopDisplay.title,
    nextHopDisplay.targetId,
    nextHopDisplay.targetKind,
    nextHopDisplay.whyNow,
    nextHopHasStructuredAuthority,
    nextHopPrimaryTitle,
    nextHopShouldRender,
    debugRestoredNextHop,
    routeWorkspaceLabel,
    secondaryPanelsCollapsedByDefault,
    secondaryPanelsOpen,
    singleCardImmersive,
    visibleReviewArtifact,
    visibleScenarioLab,
    visibleTheoryDrill,
    visibleTheoryQuestion,
    visibleActiveSubmode,
    workspaceTrainingState?.selectedCardTitle,
    nextHopVisible,
  ]);

  function setModeAndNotify(next: TrainingSurfaceMode): void {
    setMode(next);
    onTrainingSubmodeChange?.(next === "flash" ? "flash" : "practice");
  }

  function submitDependencyAction(): void {
    if (!onDependencySkillMapAction || !dependency) {
      return;
    }
    if (stageAction !== "mark_transferable") {
      if (onVerifyCurrentFile && visibleCardId && visibleCardType === "practice") {
        onVerifyCurrentFile({
          cardId: visibleCardId,
          cardTitle: primaryCardTitle,
          acceptanceCriteria: resolvedHandoff.verificationSteps,
          learnerDeliverables: resolvedHandoff.learnerDeliverables,
        });
        return;
      }
      onDependencySkillMapAction({
        dependencyKey: dependency.dependencyKey,
        action: "request_verification",
        note: text(
          language,
          "已记录为待验证。请回到当前练习并使用“验证当前文件”。",
          "Recorded as waiting for verification. Return to the current practice and use Verify current file.",
        ),
      });
      return;
    }
    if (!transferDraft || !transferReady) {
      return;
    }
    onDependencySkillMapAction({
      dependencyKey: dependency.dependencyKey,
      action: "request_verification",
      note: text(
        language,
        `已提交迁移说明，等待 Trainer 验证：${transferDraft.evidenceSummary}`,
        `Transfer note submitted for Trainer verification: ${transferDraft.evidenceSummary}`,
      ),
      relatedApi: transferDraft.relatedApi,
      scenario: transferDraft.scenario,
      focusItemKey: transferDraft.focusItemKey,
    });
  }

  function handleCardStatusTransition(cardId: string, newStatus: TrainingCardStatus, reason?: string): void {
    if (!onCardStatusTransition) {
      return;
    }
    const normalizedCardId = normalizeText(cardId);
    if (!normalizedCardId) {
      return;
    }
    const currentCardType = mode === "flash" ? "flash" : "practice";
    if (visibleCardId && visibleCardId !== normalizedCardId) {
      return;
    }
    const currentStatus = resolveTrainingCardStatus(normalizedCardId, currentCardType);
    if (!isValidCardTransition(currentStatus, newStatus)) {
      return;
    }
    setPendingCardStatusTransition({
      cardId: normalizedCardId,
      cardType: currentCardType,
      sourceStatus: currentStatus,
      newStatus,
      requestedAt: Date.now(),
    });
    try {
      onCardStatusTransition(normalizedCardId, newStatus, reason);
    } catch (error) {
      setPendingCardStatusTransition(null);
      throw error;
    }
  }

  // Loading state - when connection is starting and no task yet
  if (isLoading && !task) {
    return (
      <section className="section-block training-state training-state--loading" aria-busy="true">
        <div className="training-skeleton-lines" aria-hidden="true">
          <span className="skeleton training-skeleton-line" />
          <span className="skeleton training-skeleton-line" />
          <span className="skeleton training-skeleton-line training-skeleton-line--short" />
        </div>
        <p className="training-state__text">
          {language === "zh-CN" ? "正在准备训练内容..." : "Preparing training content..."}
        </p>
      </section>
    );
  }

  // Empty state - when connection is ready but no task
  if (!task) {
    return (
      <section className="section-block training-state training-state--empty">
        <span className="training-state__icon" aria-hidden="true"><BooksIcon size={32} /></span>
        <strong className="training-state__title">
          {language === "zh-CN" ? "没有当前训练任务" : "No active training task"}
        </strong>
        <p className="training-state__text">
          {language === "zh-CN"
            ? "从计划开始，或生成训练卡。"
            : "Start from the plan or generate a card."}
        </p>
        <div className="training-state__suggestions">
          <button
            className="training-state__suggestion-btn training-state__suggestion-btn--primary"
            onClick={() => onQuickStartTraining?.("flash")}
            type="button"
          >
            <BooksIcon size={14} />
            {language === "zh-CN" ? "开始训练" : "Start training"}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="training-view training-view--minimal practice-view practice-view--compact">
      {/* Compact progress line - one row, no dots */}
      {normalizedTrainingCardCandidates.length > 1 && !trainingPausedByResourceRisk ? (
        <div className="training-progress-line" role="status" aria-label={language === "zh-CN" ? "训练进度" : "Training progress"}>
          {(() => {
            const currentIdx = normalizedTrainingCardCandidates.findIndex(
              (c) => c.id === workspaceTrainingState?.selectedCardId,
            );
            const display = currentIdx >= 0 ? currentIdx + 1 : 1;
            const total = normalizedTrainingCardCandidates.length;
            return language === "zh-CN" ? `第 ${display} / ${total} 张` : `Card ${display} of ${total}`;
          })()}
        </div>
      ) : null}

      {/* Current chain strip removed: title and chain context now live inside the card. */}

      {scenarioPackLabel ? (
        <div className="training-next-move">
          <span className="training-next-move__label">
            {text(language, "先学习", "Learn first")}
          </span>
          <strong>
            {text(language, "场景包", "Scenario pack")} · {scenarioPackLabel}
          </strong>
          <p>
            {text(
              language,
              "先读完这组场景的学习摘要，再进入下面的测试。",
              "Read the learning summary for this scenario family before you use the test below.",
            )}
          </p>
        </div>
      ) : null}

      {/* Main training content */}
      {trainingPausedByResourceRisk ? null : mode === "flash" ? (
        <CoachFlashView
          language={language}
          deck={flashDeck}
          dependencyMastery={dependencyMastery}
          recentAttempts={recentFlashAttempts}
          busy={flashBusy}
          practiceBridge={flashPracticeBridge}
           cardStatus={visibleCardStatus}
           onCardStatusTransition={handleCardStatusTransition}
           onVerifyCurrentFile={onVerifyCurrentFile}
           cardStatusBusy={cardStatusBusy}
          onRefreshDeck={onRefreshDeck}
          onSubmitAnswer={onSubmitFlashAnswer}
          onOpenCoach={() => {
            onOpenCoachBridgeFromFlash?.(practiceCoachBridge);
            onOpenCoachFromFlash?.();
          }}
          onOpenPractice={onOpenPracticeFromFlash}
          onCreateFlashcard={onCreateFlashcard}
          compact
          cardOnly
          sourceChain={selectedCardMeta?.sourceChain ?? workspaceTrainingState?.latestTrainingNextHop?.sourceChain ?? workspaceTrainingState?.latestTrainingHandoff?.sourceChain}
          whyNow={selectedCardMeta?.whyNow ?? workspaceTrainingState?.latestTrainingNextHop?.whyNow}
          targetSkill={selectedCardMeta?.targetSkill || undefined}
          feedbackTargets={selectedCardMeta?.feedbackTargets}
          scenarioPackLabel={scenarioPackLabel}
        />
      ) : (
        <CoachPracticeView
          language={language}
            task={
              isNextHopRestoreForeground && (completionNextHop || nextHopDisplay.cardTitle || nextHopDisplay.summary)
                ? {
                    ...task,
                    id: nextHopDisplay.targetId || nextHopDisplay.candidateId || task.id,
                    title: nextHopDisplay.cardTitle || completionNextHop || task.title,
                    description:
                      nextHopDisplay.summary ||
                      nextHopDisplay.handoffSummary ||
                      nextHopDisplay.whyNow ||
                      task.description,
                    nextActionLabel:
                      nextHopDisplay.continueIn === "plan"
                        ? text(language, "回到计划继续", "Continue in plan")
                        : nextHopDisplay.continueIn === "chat"
                          ? text(language, "回到对话继续", "Return to coach")
                          : text(language, "继续训练", "Continue training"),
                    constraints:
                      task.constraints.length > 0
                        ? task.constraints
                        : [
                            nextHopDisplay.whyNow ||
                      text(language, "恢复的下一步必须留在前景，不再回退到旧链路。", "The restored next hop must stay in the foreground; do not fall back to the old chain."),
                          ].filter((item): item is string => Boolean(item)),
                    acceptanceCriteria:
                      (task.acceptanceCriteria ?? []).length > 0
                        ? task.acceptanceCriteria
                        : [
                            nextHopDisplay.nextAfterCompletion ||
                              nextHopDisplay.returnSummary ||
                              nextHopDisplay.handoffSummary ||
                      text(language, "训练视图需要直接展示并解释当前下一步。", "The training view should directly show and explain the current next hop."),
                          ].filter((item): item is string => Boolean(item)),
                  }
                : task
            }
          workspaceUnderstanding={workspaceUnderstanding}
          evidencePack={evidencePack}
          teachingDecision={teachingDecision}
          recoveredRuntime={recoveredRuntime}
          runtimeCurrentStep={runtimeCurrentStep}
          implementationGuide={implementationGuide}
          dependencyMastery={dependencyMastery}
          learningOutcomes={learningOutcomes}
          reviewSummary={effectiveReviewSummary}
          reviewMeta={reviewTruth?.meta}
          latestReviewActionSummary={reviewTruth?.latestAction}
          latestVerifiedResult={workspaceTrainingState?.latestLearningVerifiedResult}
          latestLearningFollowup={workspaceTrainingState?.latestLearningFollowup}
          latestReturnWith={resolvedHandoff.returnWith}
          latestSuccessSignal={resolvedHandoff.successSignal}
          latestNextHop={completionNextHop}
          latestNextHopMeta={completionNextHopMeta}
          latestNextHopDetail={completionNextHopDetail}
          latestLearnerDeliverables={resolvedHandoff.learnerDeliverables}
          latestVerificationSteps={resolvedHandoff.verificationSteps}
          reviewArtifact={
            workspaceTrainingState?.reviewArtifact
              ? {
                  summary: workspaceTrainingState.reviewArtifact.summary,
                  verifiedResult: workspaceTrainingState.reviewArtifact.verifiedResult,
                  blocker: workspaceTrainingState.reviewArtifact.blocker,
                  abandonReason: workspaceTrainingState.reviewArtifact.abandonReason,
                  partialProgress: workspaceTrainingState.reviewArtifact.partialProgress,
                  rootCause: workspaceTrainingState.reviewArtifact.rootCause,
                  nextSelfImplementationRule:
                    workspaceTrainingState.reviewArtifact.nextSelfImplementationRule,
                  recommendedActions: workspaceTrainingState.reviewArtifact.recommendedActions,
                  status: workspaceTrainingState.reviewArtifact.status,
                }
              : undefined
          }
          cardStatus={visibleCardStatus}
          onCardStatusTransition={handleCardStatusTransition}
          cardStatusBusy={cardStatusBusy}
          onRefreshTask={onRefreshTask}
          onOpenCoach={onOpenCoachFromPractice}
          onOpenFlash={() => setModeAndNotify("flash")}
          busy={practiceBusy}
          compact
          cardOnly
          cardSourceChain={selectedCardMeta?.sourceChain ?? (Array.isArray(task?.metadata?.sourceChain) ? (task.metadata.sourceChain as string[]) : undefined)}
          cardWhyNow={selectedCardMeta?.whyNow ?? primaryCardReason}
          cardTargetSkill={selectedCardMeta?.targetSkill || undefined}
          cardFeedbackTargets={selectedCardMeta?.feedbackTargets}
          scenarioPackLabel={scenarioPackLabel}
        />
      )}

      {/* Post-card next-hop button removed; the back-end automatically advances after each card. */}

      {resolvedHandoff.shouldRender && showTrainingRouteStrip && chainExpanded ? (
        <details
          className="training-active-card-route training-active-card-route--collapsed"
          aria-label={text(language, "对话到训练的交接", "Chat-to-training handoff")}
        >
          <summary className="training-active-card-route__pill">
            <span className="training-active-card-route__pill-label">{text(language, "来源", "Origin")}</span>
            <span className="training-active-card-route__pill-title">{primaryCardTitle}</span>
          </summary>
          <div className="training-active-card-route__header">
            <div>
              <span className="eyebrow">{text(language, "对话交接", "Conversation handoff")}</span>
              <strong>{primaryCardTitle}</strong>
            </div>
            <p>{primaryCardReason}</p>
          </div>
          <div className="training-active-card-route__factors">
            <div className="training-active-card-route__factor">
              <span>{text(language, "工作区", "Workspace")}</span>
              <strong>{routeWorkspaceLabel}</strong>
            </div>
            <div className="training-active-card-route__factor">
              <span>{text(language, "类型", "Type")}</span>
              <strong>{primaryCardTypeLabel}</strong>
            </div>
            <div className="training-active-card-route__factor">
              <span>{text(language, "路由", "Routing")}</span>
              <strong>
                {text(language, "候选", "Candidates")} {resolvedHandoff.candidateCount} /{" "}
                {text(language, "可用", "Eligible")} {resolvedHandoff.eligibleCount}
              </strong>
            </div>
            <div className="training-active-card-route__factor">
              <span>{text(language, "边界", "Boundary")}</span>
              <strong>
                {resolvedHandoff.coachOnly
                  ? text(language, "coach-only", "coach-only")
                  : text(language, "引导式", "guided")}
              </strong>
            </div>
          </div>
          <p className="training-active-card-route__compact-note">
            {text(
              language,
              "默认只保留来源和边界摘要。交付物与验证保持可展开，让单卡主线仍然是第一优先。",
              "By default this keeps only source and boundary summary. Deliverables and verification stay expandable so the single-card lane remains primary.",
            )}
          </p>
          {handoffContractVisible ? (
            <details className="training-active-card-route__details">
              <summary>{text(language, "查看卡片契约和验证", "Show the card contract and verification")}</summary>
              <div className="training-active-card-route__details-body">
                <div className="training-active-card-route__contract">
                  {resolvedHandoff.learnerDeliverables.length ? (
                    <article className="training-active-card-route__contract-card">
                      <span className="eyebrow">{text(language, "你交付", "You deliver")}</span>
                      <ul>
                        {resolvedHandoff.learnerDeliverables.slice(0, 3).map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </article>
                  ) : null}
                  {resolvedHandoff.verificationSteps.length ? (
                    <article className="training-active-card-route__contract-card">
                      <span className="eyebrow">{text(language, "这样验证", "Verify like this")}</span>
                      <ul>
                        {resolvedHandoff.verificationSteps.slice(0, 3).map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </article>
                  ) : null}
                  <article className="training-active-card-route__contract-card">
                    <span className="eyebrow">{text(language, "带回", "Bring back")}</span>
                    <p>
                      {resolvedHandoff.returnWith ||
                        resolvedHandoff.nextAfterCompletion ||
                        resolvedHandoff.successSignal ||
                        text(
                          language,
                          "把这张卡的结果和验证输出带回来，再让教练判断是复习、升级，还是写入计划证据。",
                          "Bring back the result of this card plus the verification output, then let the coach decide whether to review, level up, or feed it back into plan evidence.",
                        )}
                    </p>
                  </article>
                </div>
              </div>
            </details>
          ) : null}
          {trainingPausedByResourceRisk ? (
            <div className="training-resource-risk-gate" role="status" aria-live="polite">
              <strong>{text(language, "训练已暂停", "Training paused")}</strong>
              <p>{resourceRiskReason}</p>
              <p>
                {text(
                  language,
                  "Trainer 不会继续从过期资料路由训练卡，也不会假装这张卡仍然安全可继续。",
                  "Trainer will not keep routing cards from stale material or pretend this card is still safe to continue.",
                )}
              </p>
              <div className="training-command-center__actions">
                <ActionButton
                  fullWidth={false}
                  tone="accent"
                  icon={<BooksIcon size={14} />}
                  label={text(language, "打开资料", "Open Resources")}
                  detail={text(
                    language,
                    "先用资料页修正来源，再强制继续",
                    "Use resources as support before forcing the route",
                  )}
                  type="button"
                  disabled={!onOpenResources}
                  onClick={() => onOpenResources?.()}
                />
                <ActionButton
                  fullWidth={false}
                  tone="ghost"
                  icon={<LightningIcon size={14} />}
                  label={text(language, "刷新训练路由", "Refresh training route")}
                  detail={text(
                    language,
                    "重新收紧这张卡的下一步",
                    "Tighten the next step for this card again",
                  )}
                  type="button"
                  onClick={() => onRefreshTask(focus)}
                />
              </div>
            </div>
          ) : null}
          {resolvedHandoff.blockedCandidate ? (
            <p className="practice-card__note">
              {text(language, "同轮还有候选卡被阻塞：", "Some same-turn candidates were blocked: ")}
              {resolvedHandoff.blockedCandidate.title}
              {resolvedHandoff.blockedReason ? ` | ${resolvedHandoff.blockedReason}` : ""}
            </p>
          ) : null}
        </details>
      ) : null}

      {!masteryPanelVisible && dependency ? (
        <div className="training-mastery-toggle-wrap">
          <button
            className="button button--ghost button--micro"
            type="button"
            onClick={() => setMasteryPanelVisible(true)}
          >
            {text(language, "迁移评估 ->", "Transfer assessment ->")}
          </button>
        </div>
      ) : null}

      {masteryPanelVisible && (
        <details
          className="section-block training-status-card training-status-card--secondary training-status-card--collapsible training-mastery-evidence"
          open={secondaryPanelsOpen}
          onToggle={(event) => {
            setSecondaryPanelsOpen((event.currentTarget as HTMLDetailsElement).open);
          }}
        >
        <summary>
          <span className="eyebrow">{text(language, "依赖/API 掌握度", "Dependency/API mastery")}</span>
          <strong>
            {dependency
              ? `${dependency.dependencyName} 路 ${stageLabel(language, dependency.masteryStage)}`
              : text(language, "等待训练证据", "Waiting for training evidence")}
          </strong>
          <span className="training-mastery-evidence__summary">
            {dependency
              ? compactTrainingCardText(
                  language,
                  dependency.projectFirstCut ||
                    dependency.prioritySummary ||
                  text(language, "只使用当前卡片关联的证据", "Only evidence tied to the current card"),
                  { maxLength: 58 },
                ) ||
                text(language, "只使用当前卡片关联的证据", "Only evidence tied to the current card")
              : text(language, "当前卡片产出证据后再展开", "Expand after the current card produces evidence")}
          </span>
        </summary>
        <div className="training-collapsible__content">
          {dependency ? (
            <>
              <div className="training-command-center__grid">
                <article className="training-command-center__card">
                  <span className="eyebrow">{text(language, "当前阶段", "Current stage")}</span>
                  <strong>{stageLabel(language, dependency.masteryStage)}</strong>
                  <p className="training-command-center__detail">
                    {text(
                      language,
                      "理解、回忆、练习、应用、迁移是不同证据层。完成次数本身不等于掌握。",
                      "Understanding, recall, practice, application, and transfer are evidence layers. Completion count is not mastery.",
                    )}
                  </p>
                </article>
                <article className="training-command-center__card">
                  <span className="eyebrow">{text(language, "下一步", "Next step")}</span>
                  <strong>{dependency.projectFirstCut || dependency.prioritySummary || text(language, "继续当前卡片", "Continue the current card")}</strong>
                  <p className="training-command-center__detail">
                    {dependency.relatedApi || dependency.scenario || text(language, "先完成一个由学习者自己掌握的切片，再记录证据。", "Finish a learner-owned slice before recording evidence.")}
                  </p>
                </article>
              </div>
              {stageAction === "mark_transferable" && transferDraft ? (
                <div className="training-transfer-evidence">
                  <div className="training-transfer-evidence__header">
                    <strong>{text(language, "迁移说明（待验证）", "Transfer note (waiting for verification)")}</strong>
                    <span className="practice-chip">{transferReady ? text(language, "可提交说明", "Ready to submit note") : text(language, "需要补充", "Needs details")}</span>
                  </div>
                  {workspaceTrainingState?.latestTransferBlockedReason ? (
                    <p className="practice-card__note">{workspaceTrainingState.latestTransferBlockedReason}</p>
                  ) : null}
                  <p className="practice-card__note">
                    {text(
                      language,
                      "填写说明不会直接改变掌握记录，提交后由 Trainer 验证。",
                      "A note does not change mastery by itself. Trainer verifies it after submission.",
                    )}
                  </p>
                  <div className="training-transfer-evidence__fields">
                    <label className="training-transfer-evidence__field">
                      <span>{text(language, "源工作区", "Source workspace")}</span>
                      <input type="text" value={transferDraft.sourceWorkspaceId} readOnly />
                    </label>
                    <label className="training-transfer-evidence__field">
                      <span>{text(language, "目标工作区", "Target workspace")}</span>
                      <select
                        value={transferDraft.targetWorkspaceId}
                        onChange={(event) =>
                          setTransferDraft((current) =>
                            current ? { ...current, targetWorkspaceId: event.target.value } : current,
                          )
                        }
                      >
                        <option value="">{text(language, "选择目标工作区", "Choose target workspace")}</option>
                        {transferWorkspaceOptions.map((option) => (
                          <option key={option.workspaceId} value={option.workspaceId}>
                            {option.label}
                            {option.recommended ? text(language, "（推荐）", " (Recommended)") : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="training-transfer-evidence__field">
                      <span>{text(language, "迁移说明", "Transfer note")}</span>
                      <textarea
                        rows={3}
                        value={transferDraft.verifiedResult}
                        onChange={(event) =>
                          setTransferDraft((current) =>
                            current ? { ...current, verifiedResult: event.target.value } : current,
                          )
                        }
                      />
                    </label>
                    <label className="training-transfer-evidence__field">
                      <span>{text(language, "补充说明", "Evidence note")}</span>
                      <textarea
                        rows={2}
                        value={transferDraft.evidenceSummary}
                        onChange={(event) =>
                          setTransferDraft((current) =>
                            current ? { ...current, evidenceSummary: event.target.value } : current,
                          )
                        }
                      />
                    </label>
                  </div>
                </div>
              ) : null}
              <div className="training-command-center__actions">
                <button
                  className="button"
                  type="button"
                  disabled={stageAction === "mark_transferable" ? !canSubmitTransfer : !canSubmitStage}
                  onClick={submitDependencyAction}
                >
                  {actionLabel(language, stageAction)}
                </button>
                <details className="training-mastery-evidence__more">
                  <summary>{text(language, "更多动作", "More actions")}</summary>
                  <div className="training-command-center__actions training-command-center__actions--secondary">
                    <button
                      className="button button--ghost"
                      type="button"
                      disabled={!onDependencySkillMapAction}
                      onClick={() =>
                        onDependencySkillMapAction?.({
                          dependencyKey: dependency.dependencyKey,
                          action: "send_to_flashcards",
                          note: text(language, "把当前薄弱点送回闪卡巩固。", "Push the current weak spot back into flashcards."),
                        })
                      }
                    >
                      {text(language, "送去闪卡", "Send to flashcards")}
                    </button>
                    <button
                      className="button button--ghost"
                      type="button"
                      disabled={!onDependencySkillMapAction}
                      onClick={() =>
                        onDependencySkillMapAction?.({
                          dependencyKey: dependency.dependencyKey,
                          action: "start_scenario_lab",
                          note: text(language, "先用一个最小场景把它稳定下来。", "Stabilize this with a minimum scenario first."),
                        })
                      }
                    >
                      {text(language, "场景实验", "Scenario lab")}
                    </button>
                  </div>
                </details>
              </div>
            </>
          ) : (
            <p className="practice-card__note">
              {text(
                language,
                "完成后显示掌握证据和下一步。",
                "Completion shows mastery evidence and the next step.",
              )}
            </p>
          )}
        </div>
      </details>
      )}
    </section>
  );
}
