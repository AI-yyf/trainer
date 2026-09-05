export interface SharedPlanEvidenceItem {
  id: string;
  title?: string;
  summary?: string;
  rationale?: string;
  focusArea?: string;
  source?: "learning_signal" | "evaluation";
  diffSummary?: string;
  changedFields?: string[];
  outcome?: string;
  repetitionCount?: number;
}
export type SharedPlanEvidenceFilterMode = "all" | "evaluation" | "learning_signal";
export type SharedPlanEvidenceDiffFilterMode = "all" | "with_diff" | "without_diff";
export interface SharedPlanEvidenceFilterState {
  source: SharedPlanEvidenceFilterMode;
  focusArea: string;
  query: string;
  diffMode: SharedPlanEvidenceDiffFilterMode;
}
export declare function normalizePlanEvidenceSearch(value: string | undefined): string;
export declare function matchesPlanEvidenceQuery(
  item: SharedPlanEvidenceItem,
  normalizedQuery: string,
): boolean;
export declare function hasPlanEvidenceDiff(item: SharedPlanEvidenceItem): boolean;
export declare function filterPlanEvidenceItems<T extends SharedPlanEvidenceItem>(
  items: readonly T[],
  state: SharedPlanEvidenceFilterState,
): T[];
export declare function summarizePlanEvidenceSelection<T extends SharedPlanEvidenceItem>(
  selectedIds: ReadonlySet<string>,
  items: readonly T[],
): {
  totalSelected: number;
  selectedWithDiff: number;
  focusAreas: string[];
};
