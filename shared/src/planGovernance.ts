export interface SharedPlanEvidenceItem {
  id: string;
  title?: string;
  summary?: string;
  rationale?: string;
  focusArea?: string;
  source?: "learning_signal" | "evaluation";
  reviewState?: "captured" | "queued" | "reviewed";
  reviewNote?: string;
  freshness?: "fresh" | "stale" | "unknown";
  staleReason?: string;
  diffSummary?: string;
  changedFields?: string[];
  outcome?: string;
  repetitionCount?: number;
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
  proposedPlanPatch?: Record<string, unknown>;
}

export type SharedPlanEvidenceFilterMode = "all" | "evaluation" | "learning_signal";
export type SharedPlanEvidenceDiffFilterMode = "all" | "with_diff" | "without_diff";
export type SharedPlanEvidenceReviewFilterMode = "all" | "captured" | "queued" | "reviewed";

export interface SharedPlanEvidenceFilterState {
  source: SharedPlanEvidenceFilterMode;
  reviewState: SharedPlanEvidenceReviewFilterMode;
  focusArea: string;
  query: string;
  diffMode: SharedPlanEvidenceDiffFilterMode;
}

export interface SharedPlanHistoryItem {
  id: string;
  title?: string;
  detail?: string;
  note?: string;
  diffSummary?: string;
  changedFields?: string[];
  action?: string;
  level?: "project" | "master";
  createdAt?: string;
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
}

export interface SharedPlanHistoryFilterState {
  level: "all" | "project" | "master";
  query: string;
  diffMode: SharedPlanEvidenceDiffFilterMode;
}

export interface SharedPlanHistoryCompareState<T extends SharedPlanHistoryItem = SharedPlanHistoryItem> {
  mode: "selected_single" | "compare_focus" | "selection_blocked" | "needs_candidate";
  candidateId?: string;
  candidate?: T;
  selectedCount: number;
}

export type SharedRestoreOrchestrationSource =
  | "formal_history"
  | "project_subplan_history"
  | "master_history";

export interface SharedRestoreOrchestrationExecutionPayload {
  action: "restore_formal_history" | "restore_project_subplan";
  entryId?: string;
  version?: number;
}

export interface SharedRestoreOrchestrationItem {
  id: string;
  source: SharedRestoreOrchestrationSource;
  sourceLabel: string;
  title: string;
  targetScopeLabel: string;
  mode: "mutating" | "compare_only";
  allowed: boolean;
  blockedReason?: string;
  changedFields: string[];
  diffSummary?: string;
  createdAt?: string;
  meta?: string;
  execution?: SharedRestoreOrchestrationExecutionPayload;
}

export interface SharedRestoreOrchestrationSummary {
  totalItems: number;
  allowedCount: number;
  blockedCount: number;
  compareOnlyCount: number;
  mutatingCount: number;
  selectedCount: number;
}

export type SharedGovernedPlanAction =
  | "preview_candidate"
  | "adopt_candidate"
  | "restore_formal_history"
  | "restore_project_subplan";

export type SharedGovernedPlanActionBlockReason =
  | "project_frozen"
  | "master_frozen"
  | "compare_only"
  | "needs_candidate"
  | "adoption_blocked";

export interface SharedGovernedPlanActionGuardInput {
  action: SharedGovernedPlanAction;
  projectPlanFrozen?: boolean;
  masterPlanFrozen?: boolean;
  targetLevel?: "project" | "master";
  hasCandidate?: boolean;
  adoptionReady?: boolean;
  adoptionReason?: string;
}

export interface SharedGovernedPlanActionGuardResult {
  allowed: boolean;
  reasonCode?: SharedGovernedPlanActionBlockReason;
  reason?: string;
}

export interface SharedPlanEvidenceCompositeCandidate extends SharedPlanEvidenceItem, SharedPlanChangeCarrier {
  candidateEvidenceIds: string[];
  candidateKind: "single" | "multi";
  proposedPlanPatch?: Record<string, unknown>;
  conflictFields?: string[];
}

export interface SharedPlanEvidenceAdoptionState {
  adoptable: boolean;
  mode:
    | "selected_single"
    | "selected_multi"
    | "compare_focus"
    | "conflict_blocked"
    | "stale_blocked"
    | "review_blocked"
    | "needs_candidate";
  candidateId?: string;
  candidateEvidenceIds: string[];
  candidate?: SharedPlanEvidenceCompositeCandidate;
  selectedCount: number;
  reason?: string;
}

export interface SharedPlanChangeCarrier {
  changedFields?: string[];
  beforeSnapshot?: Record<string, unknown>;
  afterSnapshot?: Record<string, unknown>;
}

export interface SharedPlanChangeAlignmentSummary {
  primaryFields: string[];
  compareFields: string[];
  overlapFields: string[];
  primaryOnlyFields: string[];
  compareOnlyFields: string[];
}

export interface SharedPlanHistoryMatch<
  T extends SharedPlanHistoryItem = SharedPlanHistoryItem,
> {
  historyId: string;
  historyTitle?: string;
  historyLevel?: "project" | "master";
  createdAt?: string;
  overlapFields: string[];
  primaryOnlyFields: string[];
  historyOnlyFields: string[];
  overlapCount: number;
  primaryOnlyCount: number;
  historyOnlyCount: number;
  matchKind: "exact" | "partial" | "disjoint";
  item: T;
}

export interface SharedRestoreOrchestrationInput<
  TFormal extends SharedPlanHistoryItem = SharedPlanHistoryItem,
  TSubplan extends SharedPlanHistoryItem = SharedPlanHistoryItem,
  TMaster extends SharedPlanHistoryItem = SharedPlanHistoryItem,
> {
  formalHistory: {
    selectedIds: ReadonlySet<string> | readonly string[];
    compareState: SharedPlanHistoryCompareState<TFormal>;
    items: readonly TFormal[];
    guard: SharedGovernedPlanActionGuardResult;
  };
  subplanHistory: {
    selectedIds: ReadonlySet<string> | readonly string[];
    compareState: SharedPlanHistoryCompareState<TSubplan>;
    items: readonly TSubplan[];
    guard: SharedGovernedPlanActionGuardResult;
  };
  masterHistory: {
    selectedIds: ReadonlySet<string> | readonly string[];
    compareState: SharedPlanHistoryCompareState<TMaster>;
    items: readonly TMaster[];
  };
}

function normalizePlanSnapshotValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function normalizePlanChangeFields(values: readonly string[] | undefined): string[] {
  return Array.from(
    new Set(
      (values ?? [])
        .map((value) => value.trim())
        .filter((value) => value.length > 0),
    ),
  ).sort((left, right) => left.localeCompare(right));
}

const PLAN_FIELD_ALIASES: Record<string, string[]> = {
  current_step: ["current_step", "currentStep"],
  why_now: ["why_now", "whyNow"],
  blocked_reason: ["blocked_reason", "blockedReason"],
  next_after_current: ["next_after_current", "nextAfterCurrent"],
  current_stage_id: ["current_stage_id", "currentStageId"],
  verify_method: ["verify_method", "verifyMethod"],
};

function readPlanSnapshotField(
  snapshot: Record<string, unknown> | undefined,
  field: string,
): unknown {
  if (!snapshot) {
    return undefined;
  }
  const aliases = PLAN_FIELD_ALIASES[field] ?? [field];
  for (const key of aliases) {
    if (Object.prototype.hasOwnProperty.call(snapshot, key)) {
      return snapshot[key];
    }
  }
  return snapshot[field];
}

function writePlanSnapshotField(
  snapshot: Record<string, unknown>,
  field: string,
  value: unknown,
): void {
  const aliases = PLAN_FIELD_ALIASES[field] ?? [field];
  const existingKey = aliases.find((key) => Object.prototype.hasOwnProperty.call(snapshot, key));
  snapshot[existingKey ?? aliases[0] ?? field] = value;
}

function materializePlanEvidenceCandidate<T extends SharedPlanEvidenceItem>(
  item: T,
): SharedPlanEvidenceCompositeCandidate {
  const afterSnapshot = item.afterSnapshot ?? item.proposedPlanPatch ?? {};
  return {
    ...item,
    candidateEvidenceIds: [item.id],
    candidateKind: "single",
    beforeSnapshot: item.beforeSnapshot,
    afterSnapshot,
    proposedPlanPatch: afterSnapshot,
    changedFields: resolvePlanChangeFields({
      changedFields: item.changedFields,
      beforeSnapshot: item.beforeSnapshot,
      afterSnapshot,
    }),
  };
}

export function composePlanEvidenceCandidate<T extends SharedPlanEvidenceItem>(
  items: readonly T[],
): SharedPlanEvidenceCompositeCandidate | undefined {
  if (!items.length) {
    return undefined;
  }
  if (items.length === 1) {
    return materializePlanEvidenceCandidate(items[0]);
  }

  const baseline =
    items.find(
      (item) => item.beforeSnapshot && Object.keys(item.beforeSnapshot).length > 0,
    )?.beforeSnapshot ?? {};
  const mergedSnapshot: Record<string, unknown> = { ...baseline };
  const changedFieldSet = new Set<string>();
  const conflictFieldSet = new Set<string>();
  const proposalByField = new Map<
    string,
    { normalizedValue: string; rawValue: unknown; evidenceIds: string[] }
  >();

  for (const item of items) {
    const afterSnapshot = item.afterSnapshot ?? item.proposedPlanPatch ?? {};
    const changedFields = resolvePlanChangeFields({
      changedFields: item.changedFields,
      beforeSnapshot: item.beforeSnapshot ?? baseline,
      afterSnapshot,
    });
    for (const field of changedFields) {
      changedFieldSet.add(field);
      const rawValue = readPlanSnapshotField(afterSnapshot, field);
      const normalizedValue = normalizePlanSnapshotValue(rawValue);
      const currentProposal = proposalByField.get(field);
      if (!currentProposal) {
        proposalByField.set(field, {
          normalizedValue,
          rawValue,
          evidenceIds: [item.id],
        });
        continue;
      }
      currentProposal.evidenceIds.push(item.id);
      if (currentProposal.normalizedValue !== normalizedValue) {
        conflictFieldSet.add(field);
      }
    }
  }

  for (const [field, proposal] of proposalByField.entries()) {
    if (conflictFieldSet.has(field)) {
      continue;
    }
    writePlanSnapshotField(mergedSnapshot, field, proposal.rawValue);
  }

  const focusAreas = Array.from(
    new Set(
      items
        .map((item) => item.focusArea?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  ).sort((left, right) => left.localeCompare(right));
  const titles = Array.from(
    new Set(
      items
        .map((item) => item.title?.trim() || item.summary?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  );
  const summaries = Array.from(
    new Set(
      items
        .map((item) => item.summary?.trim() || item.rationale?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  );
  const candidateEvidenceIds = items.map((item) => item.id);
  const changedFields = Array.from(changedFieldSet).sort((left, right) => left.localeCompare(right));
  const conflictFields = Array.from(conflictFieldSet).sort((left, right) => left.localeCompare(right));

  return {
    id: `composed:${candidateEvidenceIds.join("+")}`,
    title:
      titles[0] ??
      `Combined formal candidate (${candidateEvidenceIds.length} evidence items)`,
    summary:
      summaries[0] ??
      `Compose ${candidateEvidenceIds.length} reviewed evidence items into one governed formal-plan candidate.`,
    rationale:
      focusAreas.length > 0
        ? `Focus areas: ${focusAreas.join(", ")}`
        : `Grouped evidence candidate from ${candidateEvidenceIds.length} items.`,
    focusArea: focusAreas.join(" / "),
    source: items.every((item) => item.source === "evaluation")
      ? "evaluation"
      : "learning_signal",
    reviewState: "reviewed",
    freshness: conflictFields.length > 0 ? "unknown" : "fresh",
    diffSummary:
      conflictFields.length > 0
        ? `Selected evidence conflicts on ${conflictFields.join(", ")}.`
        : `Formal candidate would update ${changedFields.length} plan field${
            changedFields.length === 1 ? "" : "s"
          } from ${candidateEvidenceIds.length} evidence item${
            candidateEvidenceIds.length === 1 ? "" : "s"
          }.`,
    changedFields,
    beforeSnapshot: baseline,
    afterSnapshot: mergedSnapshot,
    proposedPlanPatch: mergedSnapshot,
    candidateEvidenceIds,
    candidateKind: "multi",
    conflictFields,
  };
}

export function resolvePlanChangeFields(item: SharedPlanChangeCarrier | undefined): string[] {
  const explicitFields = normalizePlanChangeFields(item?.changedFields);
  if (explicitFields.length > 0) {
    return explicitFields;
  }

  const beforeSnapshot = item?.beforeSnapshot ?? {};
  const afterSnapshot = item?.afterSnapshot ?? {};
  const candidateFields = Array.from(
    new Set([...Object.keys(beforeSnapshot), ...Object.keys(afterSnapshot)]),
  ).sort((left, right) => left.localeCompare(right));

  return candidateFields.filter(
    (field) =>
      normalizePlanSnapshotValue(beforeSnapshot[field]) !==
      normalizePlanSnapshotValue(afterSnapshot[field]),
  );
}

export function summarizePlanChangeAlignment(
  primary: SharedPlanChangeCarrier | undefined,
  compare: SharedPlanChangeCarrier | undefined,
): SharedPlanChangeAlignmentSummary {
  const primaryFields = resolvePlanChangeFields(primary);
  const compareFields = resolvePlanChangeFields(compare);
  const compareFieldSet = new Set(compareFields);
  const primaryFieldSet = new Set(primaryFields);

  return {
    primaryFields,
    compareFields,
    overlapFields: primaryFields.filter((field) => compareFieldSet.has(field)),
    primaryOnlyFields: primaryFields.filter((field) => !compareFieldSet.has(field)),
    compareOnlyFields: compareFields.filter((field) => !primaryFieldSet.has(field)),
  };
}

export function rankPlanHistoryMatches<T extends SharedPlanHistoryItem>(
  primary: SharedPlanChangeCarrier | undefined,
  items: readonly T[],
  limit = items.length,
): Array<SharedPlanHistoryMatch<T>> {
  const primaryFields = resolvePlanChangeFields(primary);
  if (!primaryFields.length || !items.length || limit <= 0) {
    return [];
  }

  const matchRank: Record<SharedPlanHistoryMatch["matchKind"], number> = {
    exact: 0,
    partial: 1,
    disjoint: 2,
  };

  return items
    .map((item) => {
      const alignment = summarizePlanChangeAlignment(primary, {
        changedFields: item.changedFields,
        beforeSnapshot: item.beforeSnapshot,
        afterSnapshot: item.afterSnapshot,
      });
      const matchKind: SharedPlanHistoryMatch["matchKind"] =
        alignment.overlapFields.length === 0
          ? "disjoint"
          : alignment.primaryOnlyFields.length === 0 &&
              alignment.compareOnlyFields.length === 0
            ? "exact"
            : "partial";

      return {
        historyId: item.id,
        historyTitle: item.title,
        historyLevel: item.level,
        createdAt: item.createdAt,
        overlapFields: alignment.overlapFields,
        primaryOnlyFields: alignment.primaryOnlyFields,
        historyOnlyFields: alignment.compareOnlyFields,
        overlapCount: alignment.overlapFields.length,
        primaryOnlyCount: alignment.primaryOnlyFields.length,
        historyOnlyCount: alignment.compareOnlyFields.length,
        matchKind,
        item,
      };
    })
    .sort((left, right) => {
      const rankDelta = matchRank[left.matchKind] - matchRank[right.matchKind];
      if (rankDelta !== 0) {
        return rankDelta;
      }
      if (right.overlapCount !== left.overlapCount) {
        return right.overlapCount - left.overlapCount;
      }
      if (left.primaryOnlyCount !== right.primaryOnlyCount) {
        return left.primaryOnlyCount - right.primaryOnlyCount;
      }
      if (left.historyOnlyCount !== right.historyOnlyCount) {
        return left.historyOnlyCount - right.historyOnlyCount;
      }
      const leftCreatedAt = left.createdAt ? Date.parse(left.createdAt) : Number.NaN;
      const rightCreatedAt = right.createdAt ? Date.parse(right.createdAt) : Number.NaN;
      const leftTime = Number.isFinite(leftCreatedAt) ? leftCreatedAt : 0;
      const rightTime = Number.isFinite(rightCreatedAt) ? rightCreatedAt : 0;
      return rightTime - leftTime;
    })
    .slice(0, limit);
}

export function normalizePlanEvidenceSearch(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

export function matchesPlanEvidenceQuery(
  item: SharedPlanEvidenceItem,
  normalizedQuery: string,
): boolean {
  if (!normalizedQuery) {
    return true;
  }
  const haystacks = [
    item.title,
    item.summary,
    item.rationale,
    item.focusArea,
    item.diffSummary,
    item.outcome,
    ...(item.changedFields ?? []),
  ];
  return haystacks.some((value) => (value ?? "").toLowerCase().includes(normalizedQuery));
}

export function hasPlanEvidenceDiff(item: SharedPlanEvidenceItem): boolean {
  return Boolean(item.diffSummary?.trim() || item.changedFields?.length);
}

export function resolvePlanEvidenceReviewState(
  item: SharedPlanEvidenceItem,
): "captured" | "queued" | "reviewed" {
  return item.reviewState ?? "queued";
}

export function matchesPlanHistoryQuery(
  item: SharedPlanHistoryItem,
  normalizedQuery: string,
): boolean {
  if (!normalizedQuery) {
    return true;
  }
  const haystacks = [
    item.title,
    item.detail,
    item.note,
    item.diffSummary,
    item.action,
    item.level,
    ...(item.changedFields ?? []),
  ];
  return haystacks.some((value) => (value ?? "").toLowerCase().includes(normalizedQuery));
}

export function hasPlanHistoryDiff(item: SharedPlanHistoryItem): boolean {
  return Boolean(item.diffSummary?.trim() || item.changedFields?.length);
}

export function filterPlanEvidenceItems<T extends SharedPlanEvidenceItem>(
  items: readonly T[],
  state: SharedPlanEvidenceFilterState,
): T[] {
  const normalizedFocusArea = normalizePlanEvidenceSearch(state.focusArea);
  const normalizedQuery = normalizePlanEvidenceSearch(state.query);
  return items.filter((item) => {
    if (state.source !== "all" && item.source !== state.source) {
      return false;
    }
    if (state.reviewState !== "all" && resolvePlanEvidenceReviewState(item) !== state.reviewState) {
      return false;
    }
    if (normalizedFocusArea && normalizedFocusArea !== "all") {
      const focus = normalizePlanEvidenceSearch(item.focusArea);
      if (!focus.includes(normalizedFocusArea)) {
        return false;
      }
    }
    if (state.diffMode === "with_diff" && !hasPlanEvidenceDiff(item)) {
      return false;
    }
    if (state.diffMode === "without_diff" && hasPlanEvidenceDiff(item)) {
      return false;
    }
    return matchesPlanEvidenceQuery(item, normalizedQuery);
  });
}

export function filterPlanHistoryItems<T extends SharedPlanHistoryItem>(
  items: readonly T[],
  state: SharedPlanHistoryFilterState,
): T[] {
  const normalizedQuery = normalizePlanEvidenceSearch(state.query);
  return items.filter((item) => {
    if (state.level !== "all" && item.level !== state.level) {
      return false;
    }
    if (state.diffMode === "with_diff" && !hasPlanHistoryDiff(item)) {
      return false;
    }
    if (state.diffMode === "without_diff" && hasPlanHistoryDiff(item)) {
      return false;
    }
    return matchesPlanHistoryQuery(item, normalizedQuery);
  });
}

export function summarizePlanEvidenceSelection<T extends SharedPlanEvidenceItem>(
  selectedIds: ReadonlySet<string>,
  items: readonly T[],
): {
  totalSelected: number;
  selectedWithDiff: number;
  selectedCaptured: number;
  selectedQueued: number;
  selectedReviewed: number;
  selectedStale: number;
  focusAreas: string[];
} {
  const selectedItems = items.filter((item) => selectedIds.has(item.id));
  const focusAreas = Array.from(
    new Set(
      selectedItems
        .map((item) => item.focusArea?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  ).sort((left, right) => left.localeCompare(right));
  return {
    totalSelected: selectedItems.length,
    selectedWithDiff: selectedItems.filter((item) => hasPlanEvidenceDiff(item)).length,
    selectedCaptured: selectedItems.filter((item) => resolvePlanEvidenceReviewState(item) === "captured")
      .length,
    selectedQueued: selectedItems.filter((item) => resolvePlanEvidenceReviewState(item) === "queued").length,
    selectedReviewed: selectedItems.filter((item) => resolvePlanEvidenceReviewState(item) === "reviewed")
      .length,
    selectedStale: selectedItems.filter((item) => item.freshness === "stale").length,
    focusAreas,
  };
}

export function resolvePlanEvidenceAdoptionState<T extends SharedPlanEvidenceItem>(
  items: readonly T[],
  selectedIds: ReadonlySet<string> | readonly string[],
  compareFocusId?: string,
): SharedPlanEvidenceAdoptionState {
  const itemMap = new Map(items.map((item) => [item.id, item]));
  const selectedIdList = Array.isArray(selectedIds) ? selectedIds : Array.from(selectedIds);
  const selectedItems = selectedIdList
    .map((id) => itemMap.get(id))
    .filter((item): item is T => Boolean(item));

  const staleReasonFor = (item: T | undefined): string =>
    item?.staleReason?.trim() ||
    "This evidence is stale because the formal plan changed after it was captured.";
  const reviewReasonFor = (item: T | undefined): string =>
    resolvePlanEvidenceReviewState(item ?? { id: "" }) === "captured"
      ? "This evidence was captured but has not been reviewed yet."
      : "This evidence is still queued for review before it can be adopted into the formal plan.";

  if (selectedItems.length === 1) {
    const candidate = materializePlanEvidenceCandidate(selectedItems[0]);
    if (selectedItems[0].freshness === "stale") {
      return {
        adoptable: false,
        mode: "stale_blocked",
        candidateId: candidate.id,
        candidateEvidenceIds: candidate.candidateEvidenceIds,
        candidate,
        selectedCount: 1,
        reason: staleReasonFor(selectedItems[0]),
      };
    }
    if (resolvePlanEvidenceReviewState(selectedItems[0]) !== "reviewed") {
      return {
        adoptable: false,
        mode: "review_blocked",
        candidateId: candidate.id,
        candidateEvidenceIds: candidate.candidateEvidenceIds,
        candidate,
        selectedCount: 1,
        reason: reviewReasonFor(selectedItems[0]),
      };
    }
    return {
      adoptable: true,
      mode: "selected_single",
      candidateId: candidate.id,
      candidateEvidenceIds: candidate.candidateEvidenceIds,
      candidate,
      selectedCount: 1,
    };
  }

  if (selectedItems.length > 1) {
    const staleItem = selectedItems.find((item) => item.freshness === "stale");
    const unreviewedItem = selectedItems.find(
      (item) => resolvePlanEvidenceReviewState(item) !== "reviewed",
    );
    const candidate = composePlanEvidenceCandidate(selectedItems);
    if (staleItem) {
      return {
        adoptable: false,
        mode: "stale_blocked",
        candidateId: candidate?.id,
        candidateEvidenceIds: candidate?.candidateEvidenceIds ?? selectedItems.map((item) => item.id),
        candidate,
        selectedCount: selectedItems.length,
        reason: staleReasonFor(staleItem),
      };
    }
    if (unreviewedItem) {
      return {
        adoptable: false,
        mode: "review_blocked",
        candidateId: candidate?.id,
        candidateEvidenceIds: candidate?.candidateEvidenceIds ?? selectedItems.map((item) => item.id),
        candidate,
        selectedCount: selectedItems.length,
        reason: reviewReasonFor(unreviewedItem),
      };
    }
    if (candidate?.conflictFields?.length) {
      return {
        adoptable: false,
        mode: "conflict_blocked",
        candidateId: candidate.id,
        candidateEvidenceIds: candidate.candidateEvidenceIds,
        candidate,
        selectedCount: selectedItems.length,
        reason: `Selected evidence conflicts on ${candidate.conflictFields.join(", ")}.`,
      };
    }
    return {
      adoptable: true,
      mode: "selected_multi",
      candidateId: candidate?.id,
      candidateEvidenceIds: candidate?.candidateEvidenceIds ?? selectedItems.map((item) => item.id),
      candidate,
      selectedCount: selectedItems.length,
    };
  }

  if (compareFocusId) {
    const candidate = itemMap.get(compareFocusId);
    if (candidate) {
      const materializedCandidate = materializePlanEvidenceCandidate(candidate);
      if (candidate.freshness === "stale") {
        return {
          adoptable: false,
          mode: "stale_blocked",
          candidateId: materializedCandidate.id,
          candidateEvidenceIds: materializedCandidate.candidateEvidenceIds,
          candidate: materializedCandidate,
          selectedCount: 0,
          reason: staleReasonFor(candidate),
        };
      }
      if (resolvePlanEvidenceReviewState(candidate) !== "reviewed") {
        return {
          adoptable: false,
          mode: "review_blocked",
          candidateId: materializedCandidate.id,
          candidateEvidenceIds: materializedCandidate.candidateEvidenceIds,
          candidate: materializedCandidate,
          selectedCount: 0,
          reason: reviewReasonFor(candidate),
        };
      }
      return {
        adoptable: true,
        mode: "compare_focus",
        candidateId: materializedCandidate.id,
        candidateEvidenceIds: materializedCandidate.candidateEvidenceIds,
        candidate: materializedCandidate,
        selectedCount: 0,
      };
    }
  }

  return {
    adoptable: false,
    mode: "needs_candidate",
    candidateEvidenceIds: [],
    selectedCount: 0,
  };
}

function normalizeSelectedIds(selectedIds: ReadonlySet<string> | readonly string[]): string[] {
  return Array.isArray(selectedIds) ? selectedIds : Array.from(selectedIds);
}

function buildRestoreHistoryItem(
  item: SharedPlanHistoryItem | undefined,
  fallbackId: string,
  source: SharedRestoreOrchestrationSource,
  sourceLabel: string,
  title: string,
  targetScopeLabel: string,
  mode: "mutating" | "compare_only",
  allowed: boolean,
  blockedReason?: string,
  execution?: SharedRestoreOrchestrationExecutionPayload,
): SharedRestoreOrchestrationItem {
  return {
    id: item?.id ?? fallbackId,
    source,
    sourceLabel,
    title,
    targetScopeLabel,
    mode,
    allowed,
    blockedReason,
    changedFields: resolvePlanChangeFields(item),
    diffSummary: item?.diffSummary,
    createdAt: item?.createdAt,
    meta: item?.action ?? item?.detail ?? item?.note,
    execution,
  };
}

export function resolveRestoreOrchestrationItems<
  TFormal extends SharedPlanHistoryItem = SharedPlanHistoryItem,
  TSubplan extends SharedPlanHistoryItem = SharedPlanHistoryItem,
  TMaster extends SharedPlanHistoryItem = SharedPlanHistoryItem,
>(
  input: SharedRestoreOrchestrationInput<TFormal, TSubplan, TMaster>,
): SharedRestoreOrchestrationItem[] {
  const items: SharedRestoreOrchestrationItem[] = [];
  const formalSelectedIds = normalizeSelectedIds(input.formalHistory.selectedIds);
  const subplanSelectedIds = normalizeSelectedIds(input.subplanHistory.selectedIds);
  const masterSelectedIds = normalizeSelectedIds(input.masterHistory.selectedIds);

  if (formalSelectedIds.length > 1) {
    items.push({
      id: "restore-formal-history-batch-preview",
      source: "formal_history",
      sourceLabel: "formal_history",
      title: `formal_history_batch:${formalSelectedIds.length}`,
      targetScopeLabel: "current_formal_project_plan",
      mode: "mutating",
      allowed: false,
      blockedReason: "Only one formal-history entry can restore at a time. Keep multiple selections as preview only.",
      changedFields: Array.from(
        new Set(
          input.formalHistory.items
            .filter((entry) => formalSelectedIds.includes(entry.id))
            .flatMap((entry) => resolvePlanChangeFields(entry)),
        ),
      ).sort((left, right) => left.localeCompare(right)),
    });
  }

  const formalCandidate = input.formalHistory.compareState.candidate;
  items.push(
    buildRestoreHistoryItem(
      formalCandidate,
      "restore-formal-history-focus",
      "formal_history",
      "formal_history",
      formalCandidate?.title ?? "formal_history_focus",
      "current_formal_project_plan",
      "mutating",
      Boolean(formalCandidate) &&
        input.formalHistory.guard.allowed &&
        formalCandidate?.level === "project",
      Boolean(formalCandidate) &&
      input.formalHistory.guard.allowed &&
      formalCandidate?.level === "project"
        ? undefined
        : input.formalHistory.guard.reason,
      formalCandidate && input.formalHistory.guard.allowed && formalCandidate.level === "project"
        ? {
            action: "restore_formal_history",
            entryId: formalCandidate.id,
          }
        : undefined,
    ),
  );

  if (subplanSelectedIds.length > 1) {
    items.push({
      id: "restore-subplan-history-batch-preview",
      source: "project_subplan_history",
      sourceLabel: "project_subplan_history",
      title: `project_subplan_history_batch:${subplanSelectedIds.length}`,
      targetScopeLabel: "current_project_training_lane",
      mode: "mutating",
      allowed: false,
      blockedReason: "Only one subplan-history version can restore at a time. Keep multiple selections as preview only.",
      changedFields: Array.from(
        new Set(
          input.subplanHistory.items
            .filter((entry) => subplanSelectedIds.includes(entry.id))
            .flatMap((entry) => resolvePlanChangeFields(entry)),
        ),
      ).sort((left, right) => left.localeCompare(right)),
    });
  }

  const subplanCandidate = input.subplanHistory.compareState.candidate;
  items.push(
    buildRestoreHistoryItem(
      subplanCandidate,
      "restore-subplan-history-focus",
      "project_subplan_history",
      "project_subplan_history",
      subplanCandidate?.title ?? "project_subplan_history_focus",
      "current_project_training_lane",
      "mutating",
      Boolean(subplanCandidate) && input.subplanHistory.guard.allowed,
      input.subplanHistory.guard.allowed ? undefined : input.subplanHistory.guard.reason,
      subplanCandidate && input.subplanHistory.guard.allowed
        ? {
            action: "restore_project_subplan",
            entryId: subplanCandidate.id,
            version: (subplanCandidate as { version?: number }).version,
          }
        : undefined,
    ),
  );

  if (masterSelectedIds.length > 1) {
    items.push({
      id: "restore-master-history-batch-preview",
      source: "master_history",
      sourceLabel: "master_history",
      title: `master_history_batch:${masterSelectedIds.length}`,
      targetScopeLabel: "cross_project_master_plan_comparison",
      mode: "compare_only",
      allowed: false,
      blockedReason: "Master history is compare-only. Multiple selections remain preview material and never become direct restore actions.",
      changedFields: Array.from(
        new Set(
          input.masterHistory.items
            .filter((entry) => masterSelectedIds.includes(entry.id))
            .flatMap((entry) => resolvePlanChangeFields(entry)),
        ),
      ).sort((left, right) => left.localeCompare(right)),
    });
  }

  const masterCandidate = input.masterHistory.compareState.candidate;
  items.push(
    buildRestoreHistoryItem(
      masterCandidate,
      "restore-master-history-focus",
      "master_history",
      "master_history",
      masterCandidate?.title ?? "master_history_focus",
      "cross_project_master_plan_comparison",
      "compare_only",
      false,
      "Master history is compare-only and must flow back through formal history, subplan history, or reviewed evidence before any restore can happen.",
      undefined,
    ),
  );

  return items.filter(
    (item, index, current) =>
      Boolean(item.title) &&
      current.findIndex((candidate) => candidate.id === item.id) === index,
  );
}

export function summarizeRestoreOrchestrationItems(
  items: readonly SharedRestoreOrchestrationItem[],
): SharedRestoreOrchestrationSummary {
  return {
    totalItems: items.length,
    allowedCount: items.filter((item) => item.allowed).length,
    blockedCount: items.filter((item) => !item.allowed).length,
    compareOnlyCount: items.filter((item) => item.mode === "compare_only").length,
    mutatingCount: items.filter((item) => item.mode === "mutating").length,
    selectedCount: items.filter((item) =>
      item.id.includes("-batch-preview") || item.id.includes("-focus"),
    ).length,
  };
}

export function summarizePlanHistorySelection<T extends SharedPlanHistoryItem>(
  selectedIds: ReadonlySet<string>,
  items: readonly T[],
): {
  totalSelected: number;
  selectedWithDiff: number;
  levels: Array<"project" | "master">;
  actions: string[];
} {
  const selectedItems = items.filter((item) => selectedIds.has(item.id));
  const levels = Array.from(
    new Set(
      selectedItems
        .map((item) => item.level)
        .filter((value): value is "project" | "master" => value === "project" || value === "master"),
    ),
  ).sort((left, right) => left.localeCompare(right)) as Array<"project" | "master">;
  const actions = Array.from(
    new Set(
      selectedItems
        .map((item) => item.action?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  ).sort((left, right) => left.localeCompare(right));
  return {
    totalSelected: selectedItems.length,
    selectedWithDiff: selectedItems.filter((item) => hasPlanHistoryDiff(item)).length,
    levels,
    actions,
  };
}

export function resolvePlanHistoryCompareState<T extends SharedPlanHistoryItem>(
  items: readonly T[],
  selectedIds: ReadonlySet<string> | readonly string[],
  compareFocusId?: string,
): SharedPlanHistoryCompareState<T> {
  const itemMap = new Map(items.map((item) => [item.id, item]));
  const selectedIdList = Array.isArray(selectedIds) ? selectedIds : Array.from(selectedIds);
  const selectedItems = selectedIdList
    .map((id) => itemMap.get(id))
    .filter((item): item is T => Boolean(item));

  if (selectedItems.length === 1) {
    return {
      mode: "selected_single",
      candidateId: selectedItems[0].id,
      candidate: selectedItems[0],
      selectedCount: 1,
    };
  }

  if (selectedItems.length > 1) {
    return {
      mode: "selection_blocked",
      selectedCount: selectedItems.length,
    };
  }

  if (compareFocusId) {
    const candidate = itemMap.get(compareFocusId);
    if (candidate) {
      return {
        mode: "compare_focus",
        candidateId: candidate.id,
        candidate,
        selectedCount: 0,
      };
    }
  }

  return {
    mode: "needs_candidate",
    selectedCount: 0,
  };
}

export function resolveGovernedPlanActionGuard(
  input: SharedGovernedPlanActionGuardInput,
): SharedGovernedPlanActionGuardResult {
  if (input.action === "preview_candidate" || input.action === "adopt_candidate") {
    if (input.projectPlanFrozen) {
      return {
        allowed: false,
        reasonCode: "project_frozen",
      };
    }
    if (input.masterPlanFrozen) {
      return {
        allowed: false,
        reasonCode: "master_frozen",
      };
    }
    if (!input.hasCandidate) {
      return {
        allowed: false,
        reasonCode: "needs_candidate",
      };
    }
    if (!input.adoptionReady) {
      return {
        allowed: false,
        reasonCode: "adoption_blocked",
        reason: input.adoptionReason?.trim() || undefined,
      };
    }
    return {
      allowed: true,
    };
  }

  if (input.action === "restore_formal_history") {
    if (input.targetLevel !== "project") {
      return {
        allowed: false,
        reasonCode: "compare_only",
      };
    }
    if (input.projectPlanFrozen) {
      return {
        allowed: false,
        reasonCode: "project_frozen",
      };
    }
    return {
      allowed: true,
    };
  }

  if (input.projectPlanFrozen) {
    return {
      allowed: false,
      reasonCode: "project_frozen",
    };
  }
  if (input.masterPlanFrozen) {
    return {
      allowed: false,
      reasonCode: "master_frozen",
    };
  }
  return {
    allowed: true,
  };
}
