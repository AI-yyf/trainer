import { DIMENSION_LABELS, STATE_LABELS } from "./i18n/segments/progressInlineText";
import { dimensionKeysFor } from "./progressDimensions";
import type { ComposerLanguage, TrainingSkillProjection } from "./types";

export interface LearningProgressRow {
  label: string;
  /** The localized band text (independent / assisted / emerging / not verified). */
  state: string;
  /** The raw band key, so a surface can draw its own band scale. */
  stateKey: string;
  /**
   * The band position on a 0..4 scale. This is a band, never a fake
   * percentage: it says how far the capability has come, not a score.
   */
  level: number;
  evidenceCount: number;
}

/** Capability bands, from "not verified" to "independent". */
const BAND_LEVELS: Record<string, number> = {
  not_verified: 0,
  emerging: 1,
  assisted: 2,
  independent: 3,
};

/** The band position used by the growth heatmap (0 = nothing yet, 3 = independent). */
export function capabilityLevel(stateKey: string): number {
  return BAND_LEVELS[stateKey] ?? 0;
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
