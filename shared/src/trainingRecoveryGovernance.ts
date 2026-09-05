import type {
  DependencySkillMapHistoryEntry,
  DependencySkillItemSnapshot,
  DependencySkillMapSnapshot,
  FlashcardRecoveryMode,
  ReviewArtifactHistoryEntry,
  ReviewArtifactSnapshot,
  ScenarioLab,
  ScenarioLabHistoryEntry,
  TheoryDrillHistoryEntry,
  TrainingSubmode,
} from "./models";
import type { SharedReviewQueueRecoveryCandidate } from "./reviewQueueGovernance";

export interface TrainingRecoveryReviewItemLike {
  concept: string;
  reason: string;
  dueAt?: string;
  source?: "weakness" | "mastery" | "reflection" | "plan";
  severity?: "low" | "medium" | "high";
  surfaceMode?: "due" | "ahead" | "digest";
  taskHint?: string;
  focusArea?: string;
  linkedContext?: string[];
  intervalDays?: number;
  masteryScore?: number;
}

export interface TrainingRecoveryReviewActionLike {
  actionId: string;
  concept: string;
  action: "accept" | "snooze" | "done" | "skip" | "reset";
  outcome: "queued" | "completed" | "needs_more_practice" | "deferred" | "dismissed";
  focusArea?: string;
  taskHint?: string;
  note?: string;
  source?: string;
  createdAt?: string;
}

export type TrainingRecoveryStepKind =
  | "review"
  | "flashcards"
  | "scenario_lab"
  | "review_queue_batch"
  | "review_queue_item"
  | "transfer"
  | "project_return";

export type TrainingRecoveryActionKind =
  | "open_review"
  | "open_flashcards"
  | "start_scenario_lab"
  | "pull_review_batch"
  | "pull_review_item"
  | "refresh_practice";

export interface TrainingRecoveryRouteStep {
  id: string;
  kind: TrainingRecoveryStepKind;
  targetSubmode: TrainingSubmode;
  focusArea?: string;
  dependencyName?: string;
  concept?: string;
  scenario?: string;
  focusItemKey?: string;
  relatedApi?: string;
  reviewScope?: "single" | "focus_area";
  batchLimit?: number;
  reason: string;
  primaryAction: string;
  completionSignal: string;
  nextHop?: TrainingSubmode;
  actionKind: TrainingRecoveryActionKind;
}

export interface TrainingRecoveryRoute {
  focusArea?: string;
  dependencyName?: string;
  stallReason: string;
  returnTarget: string;
  currentSubmode?: TrainingSubmode;
  recommendedStartSubmode: TrainingSubmode;
  steps: TrainingRecoveryRouteStep[];
}

export interface TrainingRecoveryRouteInput {
  latestTrainingSubmode?: TrainingSubmode;
  latestFlashcardRecoveryMode?: FlashcardRecoveryMode;
  latestLearningFollowup?: string;
  latestLearningFocusArea?: string;
  latestLearningScenario?: string;
  latestLearningVerifiedResult?: string;
  latestLearningBlocker?: string;
  latestLearningAbandonReason?: string;
  latestLearningPartialProgress?: string;
  latestFlashcardBridge?: string;
  reviewArtifact?: ReviewArtifactSnapshot;
  scenarioLab?: ScenarioLab;
  topDueReview?: TrainingRecoveryReviewItemLike;
  topSkillMap?: DependencySkillMapSnapshot;
  topSkillItems?: DependencySkillItemSnapshot[];
  theoryWeakItems?: DependencySkillItemSnapshot[];
  practiceWeakItems?: DependencySkillItemSnapshot[];
  transferWeakItems?: DependencySkillItemSnapshot[];
  recentNeedsMorePractice?: TrainingRecoveryReviewActionLike[];
  reviewRecoveryCandidate?: SharedReviewQueueRecoveryCandidate<TrainingRecoveryReviewItemLike>;
}

export interface TrainingRestoreOrchestrationStep {
  action:
    | "restore_dependency_skill_map"
    | "restore_scenario_lab"
    | "restore_theory_drill"
    | "restore_review_artifact";
  itemId: string;
  dependencyKey?: string;
  scenarioLabId?: string;
  theoryDrillId?: string;
  reviewArtifactId?: string;
  entryId?: string;
  version?: number;
}

export interface TrainingRestoreOrchestrationInput {
  currentDependencyKey?: string;
  dependencySkillMapHistory?: DependencySkillMapHistoryEntry[];
  scenarioLabHistory?: ScenarioLabHistoryEntry[];
  theoryDrillHistory?: TheoryDrillHistoryEntry[];
  reviewArtifactHistory?: ReviewArtifactHistoryEntry[];
  maxSteps?: number;
}

function compactText(value?: string): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function firstText(...values: Array<string | undefined>): string | undefined {
  for (const value of values) {
    const trimmed = compactText(value);
    if (trimmed) {
      return trimmed;
    }
  }
  return undefined;
}

function hasSnapshot(value?: { beforeSnapshot?: Record<string, unknown>; afterSnapshot?: Record<string, unknown> }): boolean {
  return Boolean(value?.afterSnapshot || value?.beforeSnapshot);
}

function pushStep(
  steps: TrainingRecoveryRouteStep[],
  step?: TrainingRecoveryRouteStep,
): void {
  if (!step) {
    return;
  }
  if (steps.some((item) => item.id === step.id)) {
    return;
  }
  steps.push(step);
}

function pushRestoreStep(
  steps: TrainingRestoreOrchestrationStep[],
  step?: TrainingRestoreOrchestrationStep,
): void {
  if (!step?.itemId || !step.entryId) {
    return;
  }
  if (steps.some((item) => item.action === step.action && item.entryId === step.entryId)) {
    return;
  }
  steps.push(step);
}

function dependencyRestorePriority(
  entry: DependencySkillMapHistoryEntry,
  currentDependencyKey?: string,
): number {
  const current = compactText(currentDependencyKey)?.toLowerCase();
  const dependencyKey = compactText(entry.dependencyKey)?.toLowerCase();
  let score = 0;
  if (current && dependencyKey === current) {
    score += 1000;
  }
  if (hasSnapshot(entry)) {
    score += 100;
  }
  if (entry.action === "restore_history") {
    score -= 10;
  }
  score += Math.max(0, entry.version ?? 0);
  if (entry.createdAt) {
    const timestamp = Date.parse(entry.createdAt);
    if (Number.isFinite(timestamp)) {
      score += timestamp / 1_000_000_000_000;
    }
  }
  return score;
}

function restoreHistoryPriority(entry: {
  version?: number;
  createdAt?: string;
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
}): number {
  let score = 0;
  if (hasSnapshot(entry)) {
    score += 100;
  }
  score += Math.max(0, entry.version ?? 0);
  if (entry.createdAt) {
    const timestamp = Date.parse(entry.createdAt);
    if (Number.isFinite(timestamp)) {
      score += timestamp / 1_000_000_000_000;
    }
  }
  return score;
}

function latestRestorableHistoryEntry<T extends {
  version?: number;
  createdAt?: string;
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
}>(entries?: T[]): T | undefined {
  return [...(entries ?? [])]
    .filter((item) => hasSnapshot(item))
    .sort((a, b) => restoreHistoryPriority(b) - restoreHistoryPriority(a))[0];
}

export function buildTrainingRestoreOrchestrationSteps(
  input: TrainingRestoreOrchestrationInput,
): TrainingRestoreOrchestrationStep[] {
  const maxSteps = Math.max(1, Math.min(8, input.maxSteps ?? 4));
  const steps: TrainingRestoreOrchestrationStep[] = [];

  const dependencyEntries = [...(input.dependencySkillMapHistory ?? [])]
    .filter((item) => hasSnapshot(item) && Boolean(compactText(item.dependencyKey)))
    .sort(
      (a, b) =>
        dependencyRestorePriority(b, input.currentDependencyKey) -
        dependencyRestorePriority(a, input.currentDependencyKey),
    );
  const seenDependencies = new Set<string>();
  for (const entry of dependencyEntries) {
    const dependencyKey = (entry.dependencyKey ?? "").trim().toLowerCase();
    if (!dependencyKey || seenDependencies.has(dependencyKey)) {
      continue;
    }
    seenDependencies.add(dependencyKey);
    pushRestoreStep(steps, {
      itemId: entry.entryId ?? entry.id ?? entry.dependencyKey ?? "dependency-skill-map",
      action: "restore_dependency_skill_map",
      dependencyKey: entry.dependencyKey ?? "",
      entryId: entry.entryId ?? entry.id ?? entry.dependencyKey ?? "dependency-skill-map",
      version: entry.version ?? 0,
    });
    if (steps.length >= maxSteps) {
      return steps;
    }
  }

  const scenarioEntry = latestRestorableHistoryEntry(input.scenarioLabHistory);
  if (scenarioEntry) {
    pushRestoreStep(steps, {
      itemId: scenarioEntry.entryId ?? scenarioEntry.id ?? scenarioEntry.scenarioLabId ?? "scenario-lab",
      action: "restore_scenario_lab",
      scenarioLabId: scenarioEntry.scenarioLabId,
      entryId: scenarioEntry.entryId ?? scenarioEntry.id ?? scenarioEntry.scenarioLabId ?? "scenario-lab",
      version: scenarioEntry.version ?? 0,
    });
  }

  const theoryEntry = latestRestorableHistoryEntry(input.theoryDrillHistory);
  if (steps.length < maxSteps && theoryEntry) {
    pushRestoreStep(steps, {
      itemId: theoryEntry.entryId ?? theoryEntry.id ?? theoryEntry.theoryDrillId ?? "theory-drill",
      action: "restore_theory_drill",
      theoryDrillId: theoryEntry.theoryDrillId,
      entryId: theoryEntry.entryId ?? theoryEntry.id ?? theoryEntry.theoryDrillId ?? "theory-drill",
      version: theoryEntry.version ?? 0,
    });
  }

  const reviewEntry = latestRestorableHistoryEntry(input.reviewArtifactHistory);
  if (steps.length < maxSteps && reviewEntry) {
    pushRestoreStep(steps, {
      itemId: reviewEntry.entryId ?? reviewEntry.id ?? reviewEntry.reviewArtifactId ?? "review-artifact",
      action: "restore_review_artifact",
      reviewArtifactId: reviewEntry.reviewArtifactId,
      entryId: reviewEntry.entryId ?? reviewEntry.id ?? reviewEntry.reviewArtifactId ?? "review-artifact",
      version: reviewEntry.version ?? 0,
    });
  }

  return steps.slice(0, maxSteps);
}

function projectReturnAction(input: TrainingRecoveryRouteInput): string {
  return (
    firstText(
      input.topSkillMap?.projectFirstCut,
      input.topDueReview?.taskHint,
      input.reviewArtifact?.nextSelfImplementationRule,
      input.latestLearningFollowup,
      input.topSkillItems?.[0]?.nextActions?.[0],
    ) ??
    "Implement the next thin real slice yourself and verify it before widening scope."
  );
}

function projectReturnSignal(input: TrainingRecoveryRouteInput): string {
  return (
    firstText(
      input.latestLearningVerifiedResult,
      input.reviewArtifact?.verifiedResult,
      input.scenarioLab?.successSignal,
      input.topDueReview?.reason,
    ) ??
    "The slice is verified and produces a new review, flashcard, or review-queue signal."
  );
}

export function buildTrainingRecoveryRoute(
  input: TrainingRecoveryRouteInput,
): TrainingRecoveryRoute {
  const theoryItem = input.theoryWeakItems?.[0];
  const practiceItem = input.practiceWeakItems?.[0];
  const transferItem = input.transferWeakItems?.[0];
  const reviewArtifact = input.reviewArtifact;
  const reviewRecoveryCandidate = input.reviewRecoveryCandidate;
  const focusArea =
    firstText(
      reviewArtifact?.focusArea,
      input.scenarioLab?.focusArea,
      reviewRecoveryCandidate?.focusArea,
      input.topDueReview?.focusArea,
      input.latestLearningFocusArea,
      practiceItem?.scenario,
      theoryItem?.scenario,
    ) ?? input.topSkillMap?.dependencyName;
  const dependencyName = input.topSkillMap?.dependencyName;
  const needsReview =
    Boolean(reviewArtifact) &&
    Boolean(
      reviewArtifact?.blocker ||
        reviewArtifact?.abandonReason ||
        reviewArtifact?.partialProgress ||
        reviewArtifact?.rootCause ||
        reviewArtifact?.guardrail ||
        reviewArtifact?.recommendedRecoveryMode === "review" ||
        input.latestTrainingSubmode === "review",
    );
  const needsFlash =
    input.latestFlashcardRecoveryMode === "flashcards" ||
    reviewArtifact?.recommendedRecoveryMode === "flashcards" ||
    Boolean(theoryItem);
  const needsScenario =
    input.latestFlashcardRecoveryMode === "scenario_lab_or_project" ||
    reviewArtifact?.recommendedRecoveryMode === "scenario_lab_or_project" ||
    Boolean(input.scenarioLab) ||
    Boolean(practiceItem) ||
    Boolean(input.topSkillMap?.suggestedScenarioLab);
  const needsReviewQueue =
    reviewArtifact?.recommendedRecoveryMode === "review_queue" ||
    reviewRecoveryCandidate?.mode === "focus_area_batch" ||
    reviewRecoveryCandidate?.mode === "single_item" ||
    Boolean(input.topDueReview) ||
    Boolean(input.recentNeedsMorePractice?.length);
  const needsTransfer =
    input.latestFlashcardRecoveryMode === "transfer" ||
    reviewArtifact?.recommendedRecoveryMode === "transfer" ||
    Boolean(transferItem);

  const stallReason =
    firstText(
      reviewArtifact?.blocker,
      input.latestLearningBlocker,
      reviewArtifact?.abandonReason,
      input.latestLearningAbandonReason,
      reviewArtifact?.rootCause,
      theoryItem?.gaps?.[0],
      practiceItem?.gaps?.[0],
      transferItem?.gaps?.[0],
      input.topDueReview?.reason,
      input.recentNeedsMorePractice?.[0]?.note,
      input.latestFlashcardBridge,
      input.latestLearningPartialProgress,
      reviewArtifact?.partialProgress,
      input.latestLearningFollowup,
    ) ?? "Stabilize the current weak spot before widening the engineering scope.";
  const returnTarget = projectReturnAction(input);
  const steps: TrainingRecoveryRouteStep[] = [];

  if (needsReview) {
    pushStep(steps, {
      id: "review-artifact",
      kind: "review",
      targetSubmode: "review",
      focusArea,
      dependencyName,
      scenario: firstText(reviewArtifact?.scenario, input.latestLearningScenario),
      reason:
        firstText(
          reviewArtifact?.blocker,
          reviewArtifact?.abandonReason,
          reviewArtifact?.rootCause,
          reviewArtifact?.summary,
          input.latestLearningPartialProgress,
        ) ?? stallReason,
      primaryAction:
        firstText(
          reviewArtifact?.guardrail,
          reviewArtifact?.nextSelfImplementationRule,
          reviewArtifact?.recommendedActions?.[0],
        ) ?? "Write the blocker, guardrail, and next self-implementation rule before switching lanes.",
      completionSignal:
        firstText(
          reviewArtifact?.nextSelfImplementationRule,
          reviewArtifact?.guardrail,
          reviewArtifact?.verifiedResult,
        ) ?? "You can explain why the last loop stalled and what you must guard in the next self-implementation.",
      nextHop: needsFlash ? "flash" : needsScenario ? "practice" : needsReviewQueue ? "review_queue" : "practice",
      actionKind: "open_review",
    });
  }

  if (needsFlash) {
    pushStep(steps, {
      id: `flashcards-${theoryItem?.key ?? dependencyName ?? focusArea ?? "theory"}`,
      kind: "flashcards",
      targetSubmode: "flash",
      focusArea: focusArea ?? theoryItem?.label,
      dependencyName,
      concept: theoryItem?.label,
      scenario: theoryItem?.scenario,
      focusItemKey: theoryItem?.key,
      relatedApi: theoryItem?.relatedApi,
      reason:
        firstText(
          theoryItem?.gaps?.[0],
          input.latestFlashcardBridge,
          reviewArtifact?.recommendedActions?.[0],
          input.topSkillMap?.prioritySummary,
        ) ?? "The next engineering slice would still be weak on API or parameter semantics.",
      primaryAction:
        firstText(
          theoryItem?.nextActions?.[0],
          theoryItem?.canonicalAnswer,
        ) ?? "Answer the next card in your own words and keep the API, parameter, or return semantics precise.",
      completionSignal:
        firstText(
          theoryItem?.acceptedAnswers?.[0],
          theoryItem?.nextActions?.[0],
        ) ?? "You can answer one due theory card correctly without falling back to copied wording.",
      nextHop: needsScenario ? "practice" : needsReviewQueue ? "review_queue" : "practice",
      actionKind: "open_flashcards",
    });
  }

  if (needsScenario) {
    const scenarioFocus =
      firstText(
        input.scenarioLab?.focusArea,
        practiceItem?.label,
        practiceItem?.scenario,
        input.topSkillMap?.suggestedScenarioLab,
        focusArea,
      ) ?? dependencyName;
    pushStep(steps, {
      id: `scenario-lab-${scenarioFocus ?? "practice"}`,
      kind: "scenario_lab",
      targetSubmode: "practice",
      focusArea: focusArea ?? scenarioFocus,
      dependencyName,
      concept: practiceItem?.label,
      scenario: firstText(input.scenarioLab?.scenario, practiceItem?.scenario, input.latestLearningScenario),
      focusItemKey: practiceItem?.key,
      relatedApi: practiceItem?.relatedApi,
      reason:
        firstText(
          practiceItem?.gaps?.[0],
          input.scenarioLab?.whyNow,
          input.topSkillMap?.suggestedScenarioLab,
          reviewArtifact?.recommendedActions?.[0],
        ) ?? "The concept exists, but it still needs a minimum real scenario before it can survive inside the project.",
      primaryAction:
        firstText(
          input.scenarioLab?.learnerDeliverables?.[0],
          input.topSkillMap?.suggestedScenarioLab,
          input.topSkillMap?.projectFirstCut,
          practiceItem?.nextActions?.[0],
        ) ?? "Build the minimum scenario yourself and keep the implementation boundary narrow.",
      completionSignal:
        firstText(
          input.scenarioLab?.successSignal,
          input.scenarioLab?.verificationSteps?.[0],
          practiceItem?.nextActions?.[0],
        ) ?? "The minimum scenario passes its first verification and is ready to migrate back into the real project.",
      nextHop: needsReviewQueue ? "review_queue" : needsTransfer ? "practice" : "practice",
      actionKind: "start_scenario_lab",
    });
  }

  if (needsReviewQueue) {
    if (reviewRecoveryCandidate?.mode === "focus_area_batch") {
      pushStep(steps, {
        id: `review-queue-batch-${reviewRecoveryCandidate.focusArea ?? focusArea ?? "batch"}`,
        kind: "review_queue_batch",
        targetSubmode: "review_queue",
        focusArea: reviewRecoveryCandidate.focusArea ?? focusArea,
        dependencyName,
        concept: reviewRecoveryCandidate.item?.concept,
        scenario: reviewRecoveryCandidate.item?.focusArea,
        reviewScope: "focus_area",
        batchLimit: reviewRecoveryCandidate.itemCount,
        reason:
          firstText(
            input.recentNeedsMorePractice?.[0]?.note,
            reviewRecoveryCandidate.item?.reason,
            input.topDueReview?.reason,
          ) ?? "The same weak area keeps resurfacing, so it should be recovered as one batch instead of one fragmented item at a time.",
        primaryAction:
          firstText(
            reviewRecoveryCandidate.item?.taskHint,
            input.topDueReview?.taskHint,
          ) ?? "Accept the whole focus-area batch back into the training lane before widening scope.",
        completionSignal:
          reviewRecoveryCandidate.itemCount > 1
            ? `The batch is queued and you can name the first ${reviewRecoveryCandidate.focusArea ?? "focus"} item you will implement next.`
            : "The queued batch has a clear first implementation target.",
        nextHop: needsTransfer ? "practice" : "practice",
        actionKind: "pull_review_batch",
      });
    } else {
      const reviewItem = reviewRecoveryCandidate?.item ?? input.topDueReview;
      if (reviewItem) {
        pushStep(steps, {
          id: `review-queue-item-${reviewItem.concept}`,
          kind: "review_queue_item",
          targetSubmode: "review_queue",
          focusArea: reviewItem.focusArea ?? focusArea,
          dependencyName,
          concept: reviewItem.concept,
          scenario: reviewItem.focusArea,
          reviewScope: "single",
          batchLimit: 1,
          reason:
            firstText(
              reviewItem.reason,
              input.recentNeedsMorePractice?.[0]?.note,
            ) ?? "One due point still needs to be pulled back into the training lane before you brute-force the next slice.",
          primaryAction:
            firstText(reviewItem.taskHint) ?? "Pull this item into the training lane and turn it into the next concrete task.",
          completionSignal:
            firstText(reviewItem.reason) ??
            "The item is queued with a concrete task hint and a verify-first implementation target.",
          nextHop: needsTransfer ? "practice" : "practice",
          actionKind: "pull_review_item",
        });
      }
    }
  }

  if (needsTransfer) {
    pushStep(steps, {
      id: `transfer-${transferItem?.key ?? dependencyName ?? focusArea ?? "project"}`,
      kind: "transfer",
      targetSubmode: "practice",
      focusArea: focusArea ?? transferItem?.label,
      dependencyName,
      concept: transferItem?.label,
      scenario: firstText(transferItem?.scenario, input.latestLearningScenario),
      focusItemKey: transferItem?.key,
      relatedApi: transferItem?.relatedApi,
      reason:
        firstText(
          transferItem?.gaps?.[0],
          input.topSkillMap?.projectFirstCut,
          input.latestLearningFollowup,
        ) ?? "You still need one transfer drill before this skill can survive outside the original scenario.",
      primaryAction:
        firstText(
          transferItem?.nextActions?.[0],
          input.topSkillMap?.projectFirstCut,
        ) ?? "Use the same dependency or API in a different module or scenario without copying the previous implementation.",
      completionSignal:
        firstText(
          input.latestLearningVerifiedResult,
          transferItem?.nextActions?.[0],
        ) ?? "You can explain why the same API choice still holds in the new scenario and verify the slice.",
      nextHop: "practice",
      actionKind: "refresh_practice",
    });
  }

  pushStep(steps, {
    id: `project-return-${focusArea ?? dependencyName ?? "next-slice"}`,
    kind: "project_return",
    targetSubmode: "practice",
    focusArea,
    dependencyName,
    scenario: input.latestLearningScenario,
    reason:
      firstText(
        input.latestLearningFollowup,
        input.topSkillMap?.projectFirstCut,
        input.topDueReview?.taskHint,
      ) ?? "The recovery loop is only complete when you land the next real project slice yourself.",
    primaryAction: returnTarget,
    completionSignal: projectReturnSignal(input),
    nextHop: "review",
    actionKind: "refresh_practice",
  });

  return {
    focusArea,
    dependencyName,
    stallReason,
    returnTarget,
    currentSubmode: input.latestTrainingSubmode,
    recommendedStartSubmode: steps[0]?.targetSubmode ?? "practice",
    steps,
  };
}
