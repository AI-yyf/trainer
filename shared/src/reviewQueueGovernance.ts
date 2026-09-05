import type { ReviewQueueActionSnapshot, ReviewQueueItem } from "./models";
import type { ComposerLanguage } from "./types";

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

export type SharedReviewQueueFilterMode =
  | "all"
  | "high"
  | "focus"
  | "weakness"
  | "mastery"
  | "reflection"
  | "plan"
  | "due"
  | "ahead"
  | "digest";

export interface SharedReviewQueueSummary {
  totalItems: number;
  highCount: number;
  dueCount: number;
  aheadCount: number;
  digestCount: number;
  focusGroupCount: number;
  needsMorePracticeCount: number;
  bySource: Record<ReviewQueueSource, number>;
  bySurface: Record<ReviewQueueSurfaceMode, number>;
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

export interface SharedReviewQueueRecoveryCandidate<
  T extends SharedReviewQueueItemLike = SharedReviewQueueItemLike,
> {
  mode: "none" | "single_item" | "focus_area_batch";
  item?: T;
  focusArea?: string;
  itemCount: number;
  highCount: number;
  dueCount: number;
  weaknessCount: number;
  needsMorePracticeCount: number;
  recentActionCount: number;
  recoveryScore: number;
}

export interface ReviewQueueTruthSummary {
  headline?: string;
  detail?: string;
  latestAction?: string;
  meta: string[];
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

const SOURCE_LIST: ReviewQueueSource[] = ["weakness", "mastery", "reflection", "plan"];
const SURFACE_LIST: ReviewQueueSurfaceMode[] = ["due", "ahead", "digest"];

function normalizeValue(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function formatReviewDueLabel(value: string | undefined, language: ComposerLanguage): string | undefined {
  if (!value) {
    return undefined;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return language === "zh-CN"
    ? date.toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : date.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function percentLabel(value: number, language: ComposerLanguage): string {
  const normalized = Math.max(0, Math.min(1, value));
  const percent = Math.round(normalized * 100);
  return language === "zh-CN" ? `${percent}%` : `${percent}%`;
}

function stateLabel(value: string | undefined, language: ComposerLanguage): string | undefined {
  if (!value) {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  const labels: Record<string, { zh: string; en: string }> = {
    learning: { zh: "学习中", en: "Learning" },
    review: { zh: "复习中", en: "Review" },
    relearning: { zh: "回补中", en: "Relearning" },
  };
  const entry = labels[normalized];
  return entry ? (language === "zh-CN" ? entry.zh : entry.en) : value;
}

function intervalLabel(days: number, language: ComposerLanguage): string {
  if (days <= 1) {
    return language === "zh-CN" ? "今天回看" : "Review today";
  }
  return language === "zh-CN" ? `${days} 天间隔` : `${days}d interval`;
}

function retrievabilityDetail(value: number, language: ComposerLanguage): string {
  return language === "zh-CN"
    ? `当前可回忆率约 ${percentLabel(value, language)}。`
    : `Estimated recall right now is ${percentLabel(value, language)}.`;
}

function dueDetail(
  item: SharedReviewQueueItemLike,
  language: ComposerLanguage,
): string | undefined {
  const dueLabel = formatReviewDueLabel(item.dueAt, language);
  if (!dueLabel) {
    return undefined;
  }
  const target = item.taskHint?.trim() || item.focusArea?.trim() || item.concept.trim();
  return language === "zh-CN"
    ? `${target} 下次建议回看时间：${dueLabel}。`
    : `Next suggested review for ${target}: ${dueLabel}.`;
}

export function summarizeReviewQueueTruth<T extends SharedReviewQueueItemLike>(
  items: readonly T[],
  latestAction: string | undefined,
  language: ComposerLanguage = "en-US",
): ReviewQueueTruthSummary | undefined {
  const primary = items[0];
  if (!primary && !latestAction) {
    return undefined;
  }

  const meta = [
    typeof primary?.retrievability === "number"
      ? language === "zh-CN"
        ? `可回忆率 ${percentLabel(primary.retrievability, language)}`
        : `Recall ${percentLabel(primary.retrievability, language)}`
      : undefined,
    typeof primary?.intervalDays === "number" && primary.intervalDays > 0
      ? intervalLabel(primary.intervalDays, language)
      : undefined,
    stateLabel(primary?.fsrsState, language),
  ].filter((item): item is string => Boolean(item));

  const detail =
    (typeof primary?.retrievability === "number"
      ? retrievabilityDetail(primary.retrievability, language)
      : undefined) ??
    dueDetail(primary, language);

  const headline = primary
    ? dueDetail(primary, language) ??
      (language === "zh-CN"
        ? `${primary.concept.trim() || "当前主题"} 仍在复习队列里。`
        : `${primary.concept.trim() || "This topic"} is still in the review queue.`)
    : undefined;

  return {
    headline,
    detail,
    latestAction,
    meta,
  };
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

export function prioritizeReviewQueueItems<T extends SharedReviewQueueItemLike>(
  items: readonly T[],
  recentActions: readonly SharedReviewQueueActionLike[] = [],
  fallbackFocusLabel = "Ungrouped",
): T[] {
  return [...items].sort((left, right) =>
    compareTuple(
      itemSortKey(left, recentActions, fallbackFocusLabel),
      itemSortKey(right, recentActions, fallbackFocusLabel),
    ),
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

export function summarizeReviewQueueItems<T extends SharedReviewQueueItemLike>(
  items: readonly T[],
  recentActions: readonly SharedReviewQueueActionLike[] = [],
  fallbackFocusLabel = "Ungrouped",
): SharedReviewQueueSummary {
  const bySource: SharedReviewQueueSummary["bySource"] = {
    weakness: 0,
    mastery: 0,
    reflection: 0,
    plan: 0,
  };
  const bySurface: SharedReviewQueueSummary["bySurface"] = {
    due: 0,
    ahead: 0,
    digest: 0,
  };
  let needsMorePracticeCount = 0;
  for (const item of items) {
    if (item.source) {
      bySource[item.source] += 1;
    }
    if (item.surfaceMode) {
      bySurface[item.surfaceMode] += 1;
    }
    needsMorePracticeCount += collectItemPrioritySignals(
      item,
      recentActions,
      fallbackFocusLabel,
    ).needsMorePracticeCount;
  }

  return {
    totalItems: items.length,
    highCount: items.filter((item) => item.severity === "high").length,
    dueCount: items.filter((item) => item.surfaceMode === "due").length,
    aheadCount: items.filter((item) => item.surfaceMode === "ahead").length,
    digestCount: items.filter((item) => item.surfaceMode === "digest").length,
    focusGroupCount: groupReviewQueueByFocusArea(items, recentActions, fallbackFocusLabel).length,
    needsMorePracticeCount,
    bySource,
    bySurface,
  };
}

export function filterReviewQueueItems<T extends SharedReviewQueueItemLike>(
  items: readonly T[],
  filter: SharedReviewQueueFilterMode,
  focusGroups: readonly SharedReviewQueueFocusGroup<T>[] = [],
): T[] {
  if (filter === "high") {
    return items.filter((item) => item.severity === "high");
  }
  if (filter === "focus") {
    return focusGroups[0]?.items ?? [];
  }
  if (SOURCE_LIST.includes(filter as ReviewQueueSource)) {
    return items.filter((item) => item.source === filter);
  }
  if (SURFACE_LIST.includes(filter as ReviewQueueSurfaceMode)) {
    return items.filter((item) => item.surfaceMode === filter);
  }
  return [...items];
}

export function resolveReviewQueueRecoveryCandidate<T extends SharedReviewQueueItemLike>(
  items: readonly T[],
  focusGroups: readonly SharedReviewQueueFocusGroup<T>[],
): SharedReviewQueueRecoveryCandidate<T> {
  if (!items.length) {
    return {
      mode: "none",
      itemCount: 0,
      highCount: 0,
      dueCount: 0,
      weaknessCount: 0,
      needsMorePracticeCount: 0,
      recentActionCount: 0,
      recoveryScore: 0,
    };
  }

  const topGroup = focusGroups[0];
  if (
    topGroup &&
    topGroup.items.length > 1 &&
    (topGroup.highCount > 0 ||
      topGroup.dueCount > 1 ||
      topGroup.needsMorePracticeCount > 0 ||
      topGroup.recentActionCount > 1)
  ) {
    return {
      mode: "focus_area_batch",
      item: topGroup.topItem,
      focusArea: topGroup.focusArea,
      itemCount: topGroup.items.length,
      highCount: topGroup.highCount,
      dueCount: topGroup.dueCount,
      weaknessCount: topGroup.weaknessCount,
      needsMorePracticeCount: topGroup.needsMorePracticeCount,
      recentActionCount: topGroup.recentActionCount,
      recoveryScore: topGroup.recoveryScore,
    };
  }

  const item = items[0];
  const signals = collectItemPrioritySignals(item, [], item.focusArea?.trim() || "Ungrouped");
  return {
    mode: "single_item",
    item,
    focusArea: item.focusArea?.trim() || item.concept.trim() || undefined,
    itemCount: 1,
    highCount: item.severity === "high" ? 1 : 0,
    dueCount: item.surfaceMode === "due" ? 1 : 0,
    weaknessCount: item.source === "weakness" ? 1 : 0,
    needsMorePracticeCount: signals.needsMorePracticeCount,
    recentActionCount: signals.recentActionCount,
    recoveryScore: signals.recoveryPressure - signals.completionPenalty,
  };
}
