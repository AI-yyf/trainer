import type { ReviewQueueActionSnapshot, ReviewQueueItem } from "./models";

type ReviewQueueSource = NonNullable<ReviewQueueItem["source"]>;
type ReviewQueueSeverity = NonNullable<ReviewQueueItem["severity"]>;
type ReviewQueueSurfaceMode = NonNullable<ReviewQueueItem["surfaceMode"]>;
type ReviewQueueAction = ReviewQueueActionSnapshot["action"];
type ReviewQueueOutcome = ReviewQueueActionSnapshot["outcome"];

export interface SharedReviewQueueItemLike {
  concept: string;
  reason: string;
  dueAt?: string;
  source?: ReviewQueueSource;
  severity?: ReviewQueueSeverity;
  surfaceMode?: ReviewQueueSurfaceMode;
  taskHint?: string;
  focusArea?: string;
  linkedContext?: string[];
  intervalDays?: number;
  masteryScore?: number;
  stability?: number;
  difficulty?: number;
  retrievability?: number;
  fsrsState?: string;
}

export interface SharedReviewQueueActionLike {
  actionId: string;
  concept: string;
  action?: ReviewQueueAction;
  outcome?: ReviewQueueOutcome;
  focusArea?: string;
  taskHint?: string;
  note?: string;
  source?: string;
  createdAt?: string;
}

export interface SharedReviewQueueFocusGroup<T extends SharedReviewQueueItemLike = SharedReviewQueueItemLike> {
  focusArea: string;
  items: T[];
  topItem: T;
  highCount: number;
  dueCount: number;
  weaknessCount: number;
  needsMorePracticeCount: number;
  recentActionCount: number;
  recoveryScore: number;
}

interface ItemPrioritySignals {
  recoveryPressure: number;
  completionPenalty: number;
  recentActionCount: number;
  needsMorePracticeCount: number;
}

const SOURCE_PRIORITY: Record<ReviewQueueSource, number> = {
  weakness: 0,
  reflection: 1,
  mastery: 2,
  plan: 3,
};

function normalizeValue(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function isGenericActionConcept(value: string): boolean {
  return value === "review-item" || value === "review-focus-group" || value === "review-batch" || value === "review-recovery-batch";
}

function itemFocusArea<T extends SharedReviewQueueItemLike>(item: T, fallbackFocusLabel: string): string {
  return item.focusArea?.trim() || item.concept.trim() || fallbackFocusLabel;
}

function surfaceRank(value: ReviewQueueSurfaceMode | undefined): number {
  if (value === "due") {
    return 0;
  }
  if (value === "ahead") {
    return 1;
  }
  return 2;
}

function severityRank(value: ReviewQueueSeverity | undefined): number {
  if (value === "high") {
    return 0;
  }
  if (value === "medium") {
    return 1;
  }
  return 2;
}

function sourceRank(value: ReviewQueueSource | undefined): number {
  if (!value) {
    return SOURCE_PRIORITY.plan + 1;
  }
  return SOURCE_PRIORITY[value];
}

function dueAtValue(value: string | undefined): string {
  return value?.trim() || "9999-12-31T00:00:00+00:00";
}

function actionRecencyWeight(index: number): number {
  return Math.max(4 - index, 1);
}

function matchesActionToItem<T extends SharedReviewQueueItemLike>(
  action: SharedReviewQueueActionLike,
  item: T,
  fallbackFocusLabel: string,
): boolean {
  const actionConcept = normalizeValue(action.concept);
  const actionFocusArea = normalizeValue(action.focusArea);
  const itemConcept = normalizeValue(item.concept);
  const itemFocus = normalizeValue(itemFocusArea(item, fallbackFocusLabel));
  if (actionConcept && actionConcept === itemConcept) {
    return true;
  }
  if (actionConcept && !isGenericActionConcept(actionConcept)) {
    return false;
  }
  return Boolean(actionFocusArea && actionFocusArea === itemFocus);
}

function collectItemPrioritySignals<T extends SharedReviewQueueItemLike>(
  item: T,
  recentActions: readonly SharedReviewQueueActionLike[],
  fallbackFocusLabel: string,
): ItemPrioritySignals {
  let recoveryPressure = 0;
  let completionPenalty = 0;
  let recentActionCount = 0;
  let needsMorePracticeCount = 0;

  recentActions.forEach((action, index) => {
    if (!matchesActionToItem(action, item, fallbackFocusLabel)) {
      return;
    }
    const weight = actionRecencyWeight(index);
    recentActionCount += 1;
    if (action.action === "reset" || action.outcome === "needs_more_practice") {
      recoveryPressure += 3 * weight;
      needsMorePracticeCount += 1;
      return;
    }
    if (action.action === "snooze" || action.outcome === "deferred") {
      recoveryPressure += 2 * weight;
      return;
    }
    if (action.action === "skip" || action.outcome === "dismissed") {
      recoveryPressure += weight;
      return;
    }
    if (action.action === "done" || action.outcome === "completed") {
      completionPenalty += weight;
      return;
    }
    if (action.action === "accept" || action.outcome === "queued") {
      recoveryPressure += weight;
    }
  });

  return {
    recoveryPressure,
    completionPenalty,
    recentActionCount,
    needsMorePracticeCount,
  };
}

function itemSortKey<T extends SharedReviewQueueItemLike>(
  item: T,
  recentActions: readonly SharedReviewQueueActionLike[],
  fallbackFocusLabel: string,
): [number, number, number, number, number, number, string, string, string] {
  const signals = collectItemPrioritySignals(item, recentActions, fallbackFocusLabel);
  const masteryScore =
    typeof item.masteryScore === "number" && !Number.isNaN(item.masteryScore)
      ? item.masteryScore
      : 1.1;
  return [
    surfaceRank(item.surfaceMode),
    severityRank(item.severity),
    masteryScore,
    -signals.recoveryPressure,
    signals.completionPenalty,
    sourceRank(item.source),
    dueAtValue(item.dueAt),
    itemFocusArea(item, fallbackFocusLabel).toLowerCase(),
    item.concept.toLowerCase(),
  ];
}

function compareTuple(left: readonly (number | string)[], right: readonly (number | string)[]): number {
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const leftValue = left[index];
    const rightValue = right[index];
    if (leftValue === rightValue) {
      continue;
    }
    if (typeof leftValue === "number" && typeof rightValue === "number") {
      return leftValue - rightValue;
    }
    return String(leftValue ?? "").localeCompare(String(rightValue ?? ""));
  }
  return 0;
}

function groupRecoveryScore<T extends SharedReviewQueueItemLike>(
  items: readonly T[],
  recentActions: readonly SharedReviewQueueActionLike[],
  fallbackFocusLabel: string,
): number {
  const topItem = items[0];
  const topSignals = collectItemPrioritySignals(topItem, recentActions, fallbackFocusLabel);
  return (
    (topItem.surfaceMode === "due" ? 6 : topItem.surfaceMode === "ahead" ? 3 : 1) +
    (topItem.severity === "high" ? 5 : topItem.severity === "medium" ? 3 : 1) +
    topSignals.recoveryPressure +
    items.filter((item) => item.surfaceMode === "due").length * 2 +
    items.filter((item) => item.severity === "high").length * 2 +
    items.filter((item) => item.source === "weakness").length +
    topSignals.needsMorePracticeCount * 3
  );
}

export function groupReviewQueueByFocusArea<T extends SharedReviewQueueItemLike>(
  items: readonly T[],
  recentActions: readonly SharedReviewQueueActionLike[] = [],
  fallbackFocusLabel = "Ungrouped",
): SharedReviewQueueFocusGroup<T>[] {
  const grouped = new Map<string, T[]>();
  for (const item of items) {
    const focusArea = itemFocusArea(item, fallbackFocusLabel);
    const current = grouped.get(focusArea) ?? [];
    current.push(item);
    grouped.set(focusArea, current);
  }

  return [...grouped.entries()]
    .map(([focusArea, groupItems]) => {
      const topItem = groupItems[0];
      const recentActionCount = groupItems.reduce(
        (sum, item) =>
          sum + collectItemPrioritySignals(item, recentActions, fallbackFocusLabel).recentActionCount,
        0,
      );
      const needsMorePracticeCount = groupItems.reduce(
        (sum, item) =>
          sum +
          collectItemPrioritySignals(item, recentActions, fallbackFocusLabel).needsMorePracticeCount,
        0,
      );
      return {
        focusArea,
        items: groupItems,
        topItem,
        highCount: groupItems.filter((item) => item.severity === "high").length,
        dueCount: groupItems.filter((item) => item.surfaceMode === "due").length,
        weaknessCount: groupItems.filter((item) => item.source === "weakness").length,
        needsMorePracticeCount,
        recentActionCount,
        recoveryScore: groupRecoveryScore(groupItems, recentActions, fallbackFocusLabel),
      };
    })
    .sort((left, right) => {
      if (left.recoveryScore !== right.recoveryScore) {
        return right.recoveryScore - left.recoveryScore;
      }
      return compareTuple(
        itemSortKey(left.topItem, recentActions, fallbackFocusLabel),
        itemSortKey(right.topItem, recentActions, fallbackFocusLabel),
      );
    });
}
