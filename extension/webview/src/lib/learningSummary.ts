import { DIMENSION_LABELS, STATE_LABELS } from "./i18n/segments/progressInlineText";
import { dimensionKeysFor } from "./progressDimensions";
import type { ComposerLanguage, TrainingSkillDimensionState, TrainingSkillProjection } from "./types";

export interface LearningProgressRow {
  label: string;
  /** The localized band text, from the server projection's state. */
  state: string;
  /** The raw band key, so a surface can draw its own band scale. */
  stateKey: string;
  /**
   * The band position on a 0..3 scale. This is a band, never a fake
   * percentage: it says how far the capability has come, not a score.
   */
  level: number;
  evidenceCount: number;
}

export type CapabilityState = TrainingSkillDimensionState["state"];

/**
 * Capability bands, one entry per state the server projection can emit
 * (`server/app/training/skill_projection.py::_state_from_evidence`). The
 * record is exhaustive over `CapabilityState`, so a new server state fails the
 * type check here instead of silently drawing as "nothing yet".
 *
 * - `assisted`: passed with help — one cell.
 * - `independent`: one independent success — two cells.
 * - `repeat_verified`: two or more independent successes (transfer also needs
 *   two distinct contexts) — the full column.
 * - `needs_review`: failed evidence and no independent success — no cells;
 *   its label says it needs review instead of claiming progress.
 */
const BAND_LEVELS: Record<CapabilityState, number> = {
  not_verified: 0,
  needs_review: 0,
  assisted: 1,
  independent: 2,
  repeat_verified: 3,
};

/** The highest band, drawn as a full heatmap column. */
export const MAX_CAPABILITY_LEVEL = 3;

function isCapabilityState(value: string): value is CapabilityState {
  return Object.prototype.hasOwnProperty.call(BAND_LEVELS, value);
}

/**
 * The band position used by the growth heatmap (0 = nothing yet,
 * 3 = repeatedly verified). An unknown key is host data we cannot vouch for,
 * so it draws as nothing rather than as progress.
 */
export function capabilityLevel(stateKey: string): number {
  return isCapabilityState(stateKey) ? BAND_LEVELS[stateKey] : 0;
}

export interface LearningSummary {
  goalTitle?: string;
  goalStep?: string;
  goalStatus?: string;
  dueCount: number;
  dueCardTitle?: string;
  progressRows: LearningProgressRow[];
  evidenceCount: number;
}

export interface LearningSummaryInput {
  language: ComposerLanguage;
  planTitle?: string;
  currentStep?: string;
  frozen?: boolean;
  dueCount: number;
  dueCardTitle?: string;
  projection?: TrainingSkillProjection;
}

/**
 * One projection for the strip, the drawer and the inline progress card.
 * Every value is derived from live runtime facts; nothing is invented when a
 * plan, card or projection is absent.
 */
export function deriveLearningSummary(input: LearningSummaryInput): LearningSummary {
  const { language, projection } = input;
  const rows = dimensionKeysFor(projection).map((key) => {
    const state = projection?.dimensions?.[key];
    const stateKey = state?.state ?? "not_verified";
    return {
      label: DIMENSION_LABELS[language][key],
      state: STATE_LABELS[language][stateKey],
      stateKey,
      level: capabilityLevel(stateKey),
      evidenceCount: state?.verifiedCount ?? 0,
    };
  });
  return {
    goalTitle: input.planTitle?.trim() || undefined,
    goalStep: input.currentStep?.trim() || undefined,
    goalStatus: input.frozen ? "frozen" : undefined,
    dueCount: input.dueCount,
    dueCardTitle: input.dueCardTitle?.trim() || undefined,
    progressRows: rows,
    evidenceCount: rows.reduce((total, row) => total + row.evidenceCount, 0),
  };
}

/**
 * True when two learner-facing facts name the same thing. The plan's current
 * step and the current practice card are frequently the same card, and the
 * drawer must not say it twice.
 */
export function isSameLearningFact(left?: string, right?: string): boolean {
  const normalize = (value?: string): string =>
    (value ?? "")
      .trim()
      .replace(/[。．.！!？?，,、;；:：\s]+$/u, "")
      .toLocaleLowerCase();
  const a = normalize(left);
  const b = normalize(right);
  return a.length > 0 && a === b;
}
