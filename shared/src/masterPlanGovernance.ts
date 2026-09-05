import type { SharedProjectLaneItem } from "./projectLaneGovernance";

export interface SharedMasterPlanRollup {
  activeWorkspaceCount?: number;
  blockedWorkspaceCount?: number;
  completedWorkspaceCount?: number;
  averageProgressRatio?: number;
  pendingEvidenceCount?: number;
  focusAreas?: string[];
  riskAreas?: string[];
  strongestCapabilities?: string[];
  capabilityGaps?: string[];
  repeatedWeaknessCount?: number;
  repeatedWeaknessWorkspaceCount?: number;
  repeatedWeaknessSeverity?: number;
  repeatedWeaknesses?: string[];
  repeatedWeaknessSignals?: string[];
  transferStage?: "nascent" | "emerging" | "stable" | "portable";
  transferSummary?: string;
  transferEvidenceCount?: number;
  transferWorkspacePairCount?: number;
  transferDependencyCount?: number;
  transferSourceWorkspaceCount?: number;
  transferTargetWorkspaceCount?: number;
  transferEvidenceSignals?: string[];
  evaluationSummary?: string;
  elasticityScore?: number;
  elasticityStage?: "fragile" | "forming" | "resilient" | "adaptive";
  elasticitySummary?: string;
  migrationEvidence?: string[];
  migrationBlockers?: string[];
  recommendedWorkspaceId?: string;
  recommendedWorkspaceLabel?: string;
  recommendedFocusArea?: string;
  recommendedReason?: string;
  updatedAt?: string;
}

export interface SharedMasterPlanRollupSummary {
  health: "attention" | "steady" | "strong";
  activeWorkspaceCount: number;
  blockedWorkspaceCount: number;
  completedWorkspaceCount: number;
  averageProgressRatio?: number;
  pendingEvidenceCount: number;
  focusAreas: string[];
  riskAreas: string[];
  strongestCapabilities: string[];
  capabilityGaps: string[];
  repeatedWeaknessCount: number;
  repeatedWeaknessWorkspaceCount: number;
  repeatedWeaknessSeverity: number;
  repeatedWeaknesses: string[];
  repeatedWeaknessSignals: string[];
  transferStage?: "nascent" | "emerging" | "stable" | "portable";
  transferSummary?: string;
  transferEvidenceCount: number;
  transferWorkspacePairCount: number;
  transferDependencyCount: number;
  transferSourceWorkspaceCount: number;
  transferTargetWorkspaceCount: number;
  transferEvidenceSignals: string[];
  evaluationSummary?: string;
  elasticityScore?: number;
  elasticityStage?: "fragile" | "forming" | "resilient" | "adaptive";
  elasticitySummary?: string;
  migrationEvidence: string[];
  migrationBlockers: string[];
  recommendedWorkspaceId?: string;
  recommendedWorkspaceLabel?: string;
  recommendedFocusArea?: string;
  recommendedReason?: string;
  updatedAt?: string;
}

export type SharedMasterPlanAuditSource =
  | "formal_history"
  | "project_subplan_history"
  | "project_lane";

export interface SharedMasterPlanAuditItem {
  id: string;
  source: SharedMasterPlanAuditSource;
  workspaceId?: string;
  title?: string;
  action?: string;
  level?: "project" | "master";
  status?: "active" | "blocked" | "completed" | "idle";
  progressRatio?: number;
  pendingEvidenceCount?: number;
  diffSummary?: string;
  changedFields?: string[];
  focusAreas?: string[];
  linkedLongTermGoals?: string[];
  capabilityContributions?: string[];
  transferSignal?: "nascent" | "emerging" | "stable" | "portable";
  compareActive?: boolean;
}

export interface SharedMasterPlanAuditSummary {
  totalItems: number;
  formalHistoryCount: number;
  subplanHistoryCount: number;
  laneCount: number;
  workspaceCount: number;
  pendingEvidenceCount: number;
  diffItemCount: number;
  compareFocusCount: number;
  blockedLaneCount: number;
  activeLaneCount: number;
  levels: Array<"project" | "master">;
  statuses: Array<"active" | "blocked" | "completed" | "idle">;
  focusAreas: string[];
  linkedLongTermGoals: string[];
  capabilityContributions: string[];
  transferSignals: Array<"nascent" | "emerging" | "stable" | "portable">;
}

export type SharedMasterPlanAuditDiffFilterMode = "all" | "with_diff" | "without_diff";
export type SharedMasterPlanAuditStatusFilterMode =
  | "all"
  | "active"
  | "blocked"
  | "completed"
  | "idle";

export interface SharedMasterPlanAuditFilterState {
  source: "all" | SharedMasterPlanAuditSource;
  status: SharedMasterPlanAuditStatusFilterMode;
  query: string;
  diffMode: SharedMasterPlanAuditDiffFilterMode;
}

export interface SharedMasterPlanAuditSelectionSummary {
  totalSelected: number;
  selectedWithDiff: number;
  workspaceCount: number;
  pendingEvidenceCount: number;
  sources: SharedMasterPlanAuditSource[];
  statuses: Array<"active" | "blocked" | "completed" | "idle">;
  focusAreas: string[];
  linkedLongTermGoals: string[];
  capabilityContributions: string[];
  transferSignals: Array<"nascent" | "emerging" | "stable" | "portable">;
}

export interface SharedMasterPlanAuditCompareState<
  T extends SharedMasterPlanAuditItem = SharedMasterPlanAuditItem,
> {
  mode: "selected_single" | "compare_focus" | "selection_blocked" | "needs_candidate";
  candidateId?: string;
  candidate?: T;
  selectedCount: number;
}

function normalizeOrderedUnique(values: readonly string[] | undefined): string[] {
  return Array.from(
    new Set(
      (values ?? [])
        .map((value) => value.trim())
        .filter((value) => value.length > 0),
    ),
  ).sort((left, right) => left.localeCompare(right));
}

function normalizeNonNegativeCount(value: number | undefined): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
}

function hasAuditDiff(item: SharedMasterPlanAuditItem): boolean {
  return Boolean(item.diffSummary?.trim() || item.changedFields?.length);
}

export function normalizeMasterPlanAuditSearch(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function matchesMasterPlanAuditQuery(
  item: SharedMasterPlanAuditItem,
  normalizedQuery: string,
): boolean {
  if (!normalizedQuery) {
    return true;
  }
  const haystacks = [
    item.id,
    item.source,
    item.workspaceId,
    item.title,
    item.action,
    item.level,
    item.status,
    item.transferSignal,
    item.diffSummary,
    ...(item.changedFields ?? []),
    ...(item.focusAreas ?? []),
    ...(item.linkedLongTermGoals ?? []),
    ...(item.capabilityContributions ?? []),
  ];
  return haystacks.some((value) => (value ?? "").toLowerCase().includes(normalizedQuery));
}

export function summarizeMasterPlanRollup(
  rollup: SharedMasterPlanRollup | undefined,
): SharedMasterPlanRollupSummary {
  const activeWorkspaceCount = rollup?.activeWorkspaceCount ?? 0;
  const blockedWorkspaceCount = rollup?.blockedWorkspaceCount ?? 0;
  const completedWorkspaceCount = rollup?.completedWorkspaceCount ?? 0;
  const pendingEvidenceCount = rollup?.pendingEvidenceCount ?? 0;
  const averageProgressRatio =
    typeof rollup?.averageProgressRatio === "number" && !Number.isNaN(rollup.averageProgressRatio)
      ? rollup.averageProgressRatio
      : undefined;
  const focusAreas = normalizeOrderedUnique(rollup?.focusAreas);
  const riskAreas = normalizeOrderedUnique(rollup?.riskAreas);
  const strongestCapabilities = normalizeOrderedUnique(rollup?.strongestCapabilities);
  const capabilityGaps = normalizeOrderedUnique(rollup?.capabilityGaps);
  const repeatedWeaknessCount = normalizeNonNegativeCount(rollup?.repeatedWeaknessCount);
  const repeatedWeaknessWorkspaceCount = normalizeNonNegativeCount(
    rollup?.repeatedWeaknessWorkspaceCount,
  );
  const repeatedWeaknessSeverity = normalizeNonNegativeCount(rollup?.repeatedWeaknessSeverity);
  const repeatedWeaknesses = normalizeOrderedUnique(rollup?.repeatedWeaknesses);
  const repeatedWeaknessSignals = normalizeOrderedUnique(rollup?.repeatedWeaknessSignals);
  const transferEvidenceCount = normalizeNonNegativeCount(rollup?.transferEvidenceCount);
  const transferWorkspacePairCount = normalizeNonNegativeCount(rollup?.transferWorkspacePairCount);
  const transferDependencyCount = normalizeNonNegativeCount(rollup?.transferDependencyCount);
  const transferSourceWorkspaceCount = normalizeNonNegativeCount(rollup?.transferSourceWorkspaceCount);
  const transferTargetWorkspaceCount = normalizeNonNegativeCount(rollup?.transferTargetWorkspaceCount);
  const transferEvidenceSignals = normalizeOrderedUnique(rollup?.transferEvidenceSignals);
  const migrationEvidence = normalizeOrderedUnique(rollup?.migrationEvidence);
  const migrationBlockers = normalizeOrderedUnique(rollup?.migrationBlockers);
  const elasticityScore =
    typeof rollup?.elasticityScore === "number" && !Number.isNaN(rollup.elasticityScore)
      ? Math.max(0, Math.min(1, rollup.elasticityScore))
      : undefined;

  const health: SharedMasterPlanRollupSummary["health"] =
    blockedWorkspaceCount > 0 ||
    pendingEvidenceCount > 2 ||
    riskAreas.length > 0 ||
    capabilityGaps.length > 0 ||
    repeatedWeaknessCount > 0 ||
    migrationBlockers.length > 0 ||
    rollup?.elasticityStage === "fragile" ||
    (averageProgressRatio !== undefined && averageProgressRatio < 0.4)
      ? "attention"
      : averageProgressRatio !== undefined &&
          averageProgressRatio >= 0.75 &&
          (elasticityScore === undefined || elasticityScore >= 0.72) &&
          blockedWorkspaceCount === 0 &&
          riskAreas.length === 0 &&
          capabilityGaps.length === 0 &&
          repeatedWeaknessCount === 0 &&
          migrationBlockers.length === 0 &&
          activeWorkspaceCount + completedWorkspaceCount > 0
        ? "strong"
        : "steady";

  return {
    health,
    activeWorkspaceCount,
    blockedWorkspaceCount,
    completedWorkspaceCount,
    averageProgressRatio,
    pendingEvidenceCount,
    focusAreas,
    riskAreas,
    strongestCapabilities,
    capabilityGaps,
    repeatedWeaknessCount,
    repeatedWeaknessWorkspaceCount,
    repeatedWeaknessSeverity,
    repeatedWeaknesses,
    repeatedWeaknessSignals,
    transferStage: rollup?.transferStage,
    transferSummary: rollup?.transferSummary?.trim() || undefined,
    transferEvidenceCount,
    transferWorkspacePairCount,
    transferDependencyCount,
    transferSourceWorkspaceCount,
    transferTargetWorkspaceCount,
    transferEvidenceSignals,
    evaluationSummary: rollup?.evaluationSummary?.trim() || undefined,
    elasticityScore,
    elasticityStage: rollup?.elasticityStage,
    elasticitySummary: rollup?.elasticitySummary?.trim() || undefined,
    migrationEvidence,
    migrationBlockers,
    recommendedWorkspaceId: rollup?.recommendedWorkspaceId?.trim() || undefined,
    recommendedWorkspaceLabel: rollup?.recommendedWorkspaceLabel?.trim() || undefined,
    recommendedFocusArea: rollup?.recommendedFocusArea?.trim() || undefined,
    recommendedReason: rollup?.recommendedReason?.trim() || undefined,
    updatedAt: rollup?.updatedAt,
  };
}

export function resolveRecommendedProjectLane<T extends SharedProjectLaneItem>(
  items: readonly T[],
  rollup: SharedMasterPlanRollup | undefined,
): T | undefined {
  const recommendedWorkspaceId = rollup?.recommendedWorkspaceId?.trim();
  if (!recommendedWorkspaceId) {
    return undefined;
  }
  return items.find((item) => item.workspaceId === recommendedWorkspaceId);
}

export function summarizeMasterPlanAuditItems(
  items: readonly SharedMasterPlanAuditItem[],
): SharedMasterPlanAuditSummary {
  const workspaceCount = new Set(
    items
      .map((item) => item.workspaceId?.trim())
      .filter((value): value is string => Boolean(value)),
  ).size;
  const levels = Array.from(
    new Set(
      items
        .map((item) => item.level)
        .filter((value): value is "project" | "master" => value === "project" || value === "master"),
    ),
  ).sort((left, right) => left.localeCompare(right)) as Array<"project" | "master">;
  const statuses = Array.from(
    new Set(
      items
        .map((item) => item.status)
        .filter(
          (
            value,
          ): value is "active" | "blocked" | "completed" | "idle" =>
            value === "active" || value === "blocked" || value === "completed" || value === "idle",
        ),
    ),
  ).sort((left, right) => left.localeCompare(right)) as Array<
    "active" | "blocked" | "completed" | "idle"
  >;
  const focusAreas = normalizeOrderedUnique(
    items.flatMap((item) => item.focusAreas ?? []),
  );
  const linkedLongTermGoals = normalizeOrderedUnique(
    items.flatMap((item) => item.linkedLongTermGoals ?? []),
  );
  const capabilityContributions = normalizeOrderedUnique(
    items.flatMap((item) => item.capabilityContributions ?? []),
  );
  const transferSignals = Array.from(
    new Set(
      items
        .map((item) => item.transferSignal)
        .filter(
          (
            value,
          ): value is "nascent" | "emerging" | "stable" | "portable" =>
            value === "nascent" ||
            value === "emerging" ||
            value === "stable" ||
            value === "portable",
        ),
    ),
  ).sort((left, right) => left.localeCompare(right)) as Array<
    "nascent" | "emerging" | "stable" | "portable"
  >;

  return {
    totalItems: items.length,
    formalHistoryCount: items.filter((item) => item.source === "formal_history").length,
    subplanHistoryCount: items.filter((item) => item.source === "project_subplan_history").length,
    laneCount: items.filter((item) => item.source === "project_lane").length,
    workspaceCount,
    pendingEvidenceCount: items.reduce((sum, item) => sum + (item.pendingEvidenceCount ?? 0), 0),
    diffItemCount: items.filter((item) => hasAuditDiff(item)).length,
    compareFocusCount: items.filter((item) => item.compareActive).length,
    blockedLaneCount: items.filter(
      (item) => item.source === "project_lane" && item.status === "blocked",
    ).length,
    activeLaneCount: items.filter(
      (item) => item.source === "project_lane" && item.status === "active",
    ).length,
    levels,
    statuses,
    focusAreas,
    linkedLongTermGoals,
    capabilityContributions,
    transferSignals,
  };
}

export function filterMasterPlanAuditItems<T extends SharedMasterPlanAuditItem>(
  items: readonly T[],
  state: SharedMasterPlanAuditFilterState,
): T[] {
  const normalizedQuery = normalizeMasterPlanAuditSearch(state.query);
  return items.filter((item) => {
    if (state.source !== "all" && item.source !== state.source) {
      return false;
    }
    if (state.status !== "all" && item.status !== state.status) {
      return false;
    }
    if (state.diffMode === "with_diff" && !hasAuditDiff(item)) {
      return false;
    }
    if (state.diffMode === "without_diff" && hasAuditDiff(item)) {
      return false;
    }
    return matchesMasterPlanAuditQuery(item, normalizedQuery);
  });
}

export function summarizeMasterPlanAuditSelection<T extends SharedMasterPlanAuditItem>(
  selectedIds: ReadonlySet<string>,
  items: readonly T[],
): SharedMasterPlanAuditSelectionSummary {
  const selectedItems = items.filter((item) => selectedIds.has(item.id));
  const workspaceCount = new Set(
    selectedItems
      .map((item) => item.workspaceId?.trim())
      .filter((value): value is string => Boolean(value)),
  ).size;
  const sources = Array.from(
    new Set(selectedItems.map((item) => item.source)),
  ).sort((left, right) => left.localeCompare(right)) as SharedMasterPlanAuditSource[];
  const statuses = Array.from(
    new Set(
      selectedItems
        .map((item) => item.status)
        .filter(
          (
            value,
          ): value is "active" | "blocked" | "completed" | "idle" =>
            value === "active" || value === "blocked" || value === "completed" || value === "idle",
        ),
    ),
  ).sort((left, right) => left.localeCompare(right)) as Array<
    "active" | "blocked" | "completed" | "idle"
  >;
  const focusAreas = normalizeOrderedUnique(
    selectedItems.flatMap((item) => item.focusAreas ?? []),
  );
  const linkedLongTermGoals = normalizeOrderedUnique(
    selectedItems.flatMap((item) => item.linkedLongTermGoals ?? []),
  );
  const capabilityContributions = normalizeOrderedUnique(
    selectedItems.flatMap((item) => item.capabilityContributions ?? []),
  );
  const transferSignals = Array.from(
    new Set(
      selectedItems
        .map((item) => item.transferSignal)
        .filter(
          (
            value,
          ): value is "nascent" | "emerging" | "stable" | "portable" =>
            value === "nascent" ||
            value === "emerging" ||
            value === "stable" ||
            value === "portable",
        ),
    ),
  ).sort((left, right) => left.localeCompare(right)) as Array<
    "nascent" | "emerging" | "stable" | "portable"
  >;
  return {
    totalSelected: selectedItems.length,
    selectedWithDiff: selectedItems.filter((item) => hasAuditDiff(item)).length,
    workspaceCount,
    pendingEvidenceCount: selectedItems.reduce(
      (sum, item) => sum + (item.pendingEvidenceCount ?? 0),
      0,
    ),
    sources,
    statuses,
    focusAreas,
    linkedLongTermGoals,
    capabilityContributions,
    transferSignals,
  };
}

export function resolveMasterPlanAuditCompareState<T extends SharedMasterPlanAuditItem>(
  items: readonly T[],
  selectedIds: ReadonlySet<string> | readonly string[],
  compareFocusId?: string,
): SharedMasterPlanAuditCompareState<T> {
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
