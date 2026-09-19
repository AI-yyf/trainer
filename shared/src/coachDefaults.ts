import type { TrainerCustomSkill } from "./skillCatalog";

/**
 * Structural view of the workspace coach defaults the save-dedup and
 * saved-indicator comparisons need. The webview's concrete `CoachDefaults`
 * narrows the scalars to literal unions and keeps `workspaceMemoryToggles`
 * fully required; server snapshots may carry only a subset.
 */
export interface CoachDefaultsSnapshot {
  memoryScope?: string;
  workingSetMode?: string;
  reviewCadence?: string;
  reviewReminderMode?: string;
  workspaceMemoryToggles?: {
    decisions?: boolean;
    patterns?: boolean;
    resources?: boolean;
  };
  customSkills?: TrainerCustomSkill[];
}

/**
 * Neutral coach defaults — identical to the server's `CoachDefaults` model
 * defaults. A snapshot that lacks a field knows nothing beyond this value, so
 * a payload carrying the neutral value writes nothing new, while a payload
 * carrying any other value must be sent.
 */
export const NEUTRAL_COACH_DEFAULTS = {
  memoryScope: "project",
  workingSetMode: "balanced",
  reviewCadence: "steady",
  reviewReminderMode: "due",
  workspaceMemoryToggles: {
    decisions: true,
    patterns: true,
    resources: true,
  },
} as const;

export function sameCustomSkills(
  left: TrainerCustomSkill[] | undefined,
  right: TrainerCustomSkill[] | undefined,
): boolean {
  return JSON.stringify(left ?? []) === JSON.stringify(right ?? []);
}

function effectiveCoachDefaults(value: CoachDefaultsSnapshot) {
  return {
    memoryScope: value.memoryScope ?? NEUTRAL_COACH_DEFAULTS.memoryScope,
    workingSetMode: value.workingSetMode ?? NEUTRAL_COACH_DEFAULTS.workingSetMode,
    reviewCadence: value.reviewCadence ?? NEUTRAL_COACH_DEFAULTS.reviewCadence,
    reviewReminderMode: value.reviewReminderMode ?? NEUTRAL_COACH_DEFAULTS.reviewReminderMode,
    decisions: value.workspaceMemoryToggles?.decisions ?? NEUTRAL_COACH_DEFAULTS.workspaceMemoryToggles.decisions,
    patterns: value.workspaceMemoryToggles?.patterns ?? NEUTRAL_COACH_DEFAULTS.workspaceMemoryToggles.patterns,
    resources: value.workspaceMemoryToggles?.resources ?? NEUTRAL_COACH_DEFAULTS.workspaceMemoryToggles.resources,
    customSkills: value.customSkills ?? [],
  };
}

/**
 * Effective equality of two coach-defaults states. Fields missing from either
 * side compare equal to their neutral default, matching how the server
 * materializes absent values.
 */
export function sameCoachDefaults(
  left: CoachDefaultsSnapshot,
  right: CoachDefaultsSnapshot,
): boolean {
  const a = effectiveCoachDefaults(left);
  const b = effectiveCoachDefaults(right);
  return (
    a.memoryScope === b.memoryScope &&
    a.workingSetMode === b.workingSetMode &&
    a.reviewCadence === b.reviewCadence &&
    a.reviewReminderMode === b.reviewReminderMode &&
    a.decisions === b.decisions &&
    a.patterns === b.patterns &&
    a.resources === b.resources &&
    sameCustomSkills(a.customSkills, b.customSkills)
  );
}

/**
 * True when the saved server snapshot already covers every effective value in
 * the pending payload. A field missing from the snapshot counts as covered
 * only when the payload carries its neutral default — otherwise the payload
 * holds information the server lacks and the save must proceed (e.g. the
 * first custom skill on a workspace whose snapshot predates the field).
 */
export function matchesSavedCoachDefaults(
  next: CoachDefaultsSnapshot,
  saved: CoachDefaultsSnapshot | undefined,
): boolean {
  if (!saved) {
    return false;
  }
  return sameCoachDefaults(next, saved);
}
