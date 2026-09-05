import type { FlashcardRecoveryMode, TrainingSubmode } from "./models";

export interface SharedProjectLaneItem {
  workspaceId: string;
  workspaceLabel?: string;
  workspacePath?: string;
  resumeSessionId?: string;
  canResumeHere?: boolean;
  latestTrainingSubmode?: TrainingSubmode;
  latestFlashcardRecoveryMode?: FlashcardRecoveryMode;
  title?: string;
  currentStageTitle?: string;
  status?: "active" | "blocked" | "completed" | "idle";
  progressRatio?: number;
  completedStageCount?: number;
  totalStageCount?: number;
  pendingEvidenceCount?: number;
  topFocusArea?: string;
  latestSummary?: string;
  strongestSignals?: string[];
  riskSignals?: string[];
  linkedLongTermGoals?: string[];
  capabilityContributions?: string[];
  resumeReason?: string;
  transferSignal?: "nascent" | "emerging" | "stable" | "portable";
  updatedAt?: string;
}

export type SharedProjectLaneStatusFilterMode = "all" | "active" | "blocked" | "completed" | "idle";
export type SharedProjectLaneProgressFilterMode = "all" | "attention" | "steady" | "advanced";

export interface SharedProjectLaneFilterState {
  status: SharedProjectLaneStatusFilterMode;
  progress: SharedProjectLaneProgressFilterMode;
  query: string;
}

export interface SharedProjectLaneSummary {
  totalVisible: number;
  activeCount: number;
  blockedCount: number;
  resumableCount: number;
  pendingEvidenceCount: number;
  focusAreas: string[];
}

export interface SharedProjectLaneSelectionSummary {
  totalSelected: number;
  resumableCount: number;
  pendingEvidenceCount: number;
  statuses: Array<"active" | "blocked" | "completed" | "idle">;
  focusAreas: string[];
  transferSignals: Array<"nascent" | "emerging" | "stable" | "portable">;
}

export interface SharedProjectLaneCompareState<T extends SharedProjectLaneItem = SharedProjectLaneItem> {
  mode: "selected_single" | "compare_focus" | "selection_blocked" | "needs_candidate";
  candidateId?: string;
  candidate?: T;
  selectedCount: number;
}

export function normalizeProjectLaneSearch(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function isResumable(item: SharedProjectLaneItem, activeWorkspaceId?: string): boolean {
  return item.workspaceId === activeWorkspaceId
    ? Boolean(item.resumeSessionId || item.workspacePath)
    : Boolean(item.workspacePath);
}

function matchesProjectLaneQuery(item: SharedProjectLaneItem, normalizedQuery: string): boolean {
  if (!normalizedQuery) {
    return true;
  }
  const haystacks = [
    item.workspaceId,
    item.workspaceLabel,
    item.title,
    item.currentStageTitle,
    item.topFocusArea,
    item.latestSummary,
    item.resumeReason,
    item.transferSignal,
    ...(item.capabilityContributions ?? []),
    ...(item.linkedLongTermGoals ?? []),
    ...(item.strongestSignals ?? []),
    ...(item.riskSignals ?? []),
  ];
  return haystacks.some((value) => (value ?? "").toLowerCase().includes(normalizedQuery));
}

function matchesProjectLaneProgress(
  item: SharedProjectLaneItem,
  mode: SharedProjectLaneProgressFilterMode,
): boolean {
  if (mode === "all") {
    return true;
  }
  const progress = item.progressRatio ?? 0;
  const pending = item.pendingEvidenceCount ?? 0;
  const blocked = item.status === "blocked";
  if (mode === "attention") {
    return blocked || pending > 0 || progress < 0.4;
  }
  if (mode === "steady") {
    return progress >= 0.4 && progress < 0.75 && !blocked;
  }
  return progress >= 0.75 && !blocked;
}

export function filterProjectLaneItems<T extends SharedProjectLaneItem>(
  items: readonly T[],
  state: SharedProjectLaneFilterState,
): T[] {
  const normalizedQuery = normalizeProjectLaneSearch(state.query);
  return items.filter((item) => {
    if (state.status !== "all" && item.status !== state.status) {
      return false;
    }
    if (!matchesProjectLaneProgress(item, state.progress)) {
      return false;
    }
    return matchesProjectLaneQuery(item, normalizedQuery);
  });
}

export function summarizeProjectLaneItems<T extends SharedProjectLaneItem>(
  items: readonly T[],
  activeWorkspaceId?: string,
): SharedProjectLaneSummary {
  const focusAreas = Array.from(
    new Set(
      items
        .map((item) => item.topFocusArea?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  ).sort((left, right) => left.localeCompare(right));
  return {
    totalVisible: items.length,
    activeCount: items.filter((item) => item.status === "active").length,
    blockedCount: items.filter((item) => item.status === "blocked").length,
    resumableCount: items.filter((item) => isResumable(item, activeWorkspaceId)).length,
    pendingEvidenceCount: items.reduce((sum, item) => sum + (item.pendingEvidenceCount ?? 0), 0),
    focusAreas,
  };
}

export function summarizeProjectLaneSelection<T extends SharedProjectLaneItem>(
  selectedIds: ReadonlySet<string>,
  items: readonly T[],
  activeWorkspaceId?: string,
): SharedProjectLaneSelectionSummary {
  const selectedItems = items.filter((item) => selectedIds.has(item.workspaceId));
  const focusAreas = Array.from(
    new Set(
      selectedItems
        .map((item) => item.topFocusArea?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  ).sort((left, right) => left.localeCompare(right));
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
    resumableCount: selectedItems.filter((item) => isResumable(item, activeWorkspaceId)).length,
    pendingEvidenceCount: selectedItems.reduce((sum, item) => sum + (item.pendingEvidenceCount ?? 0), 0),
    statuses,
    focusAreas,
    transferSignals,
  };
}

export function resolveProjectLaneCompareState<T extends SharedProjectLaneItem>(
  items: readonly T[],
  selectedIds: ReadonlySet<string> | readonly string[],
  compareFocusId?: string,
): SharedProjectLaneCompareState<T> {
  const itemMap = new Map(items.map((item) => [item.workspaceId, item]));
  const selectedIdList = Array.isArray(selectedIds) ? selectedIds : Array.from(selectedIds);
  const selectedItems = selectedIdList
    .map((id) => itemMap.get(id))
    .filter((item): item is T => Boolean(item));

  if (selectedItems.length === 1) {
    return {
      mode: "selected_single",
      candidateId: selectedItems[0].workspaceId,
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
        candidateId: candidate.workspaceId,
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
