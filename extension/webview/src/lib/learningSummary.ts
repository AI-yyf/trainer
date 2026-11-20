import { DIMENSION_LABELS, STATE_LABELS } from "./i18n/segments/progressInlineText";
import { normalizeHostText } from "./hostText";
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

export interface LearningProgressAchievement {
  sentence: string;
  dimensionKey: string;
  stateKey: CapabilityState;
  verifiedCount: number;
  evidenceId?: string;
}

export interface LearningSummary {
  goalTitle?: string;
  goalStep?: string;
  goalStatus?: string;
  dueCount: number;
  dueCardTitle?: string;
  progressRows: LearningProgressRow[];
  evidenceCount: number;
  latestAchievement?: LearningProgressAchievement;
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

const PROGRESS_SENTENCE_TEMPLATES: Record<
  ComposerLanguage,
  Record<Exclude<CapabilityState, "not_verified">, (dim: string, count: number, detail: string) => string>
> = {
  "zh-CN": {
    repeat_verified: (dim, count, detail) => `你已连续 ${count} 次独立完成「${dim}」${detail}`,
    independent: (dim, _count, detail) => `你已独立完成「${dim}」${detail}`,
    assisted: (dim, _count, detail) => `你在提示下完成了「${dim}」${detail}`,
    needs_review: (dim, _count, detail) => `「${dim}」还需要一次回顾${detail}`,
  },
  "en-US": {
    repeat_verified: (dim, count, detail) => `You independently completed "${dim}" ${count} times in a row${detail}`,
    independent: (dim, _count, detail) => `You independently completed "${dim}"${detail}`,
    assisted: (dim, _count, detail) => `You completed "${dim}" with hints${detail}`,
    needs_review: (dim, _count, detail) => `"${dim}" needs one more review${detail}`,
  },
  "es-ES": {
    repeat_verified: (dim, count, detail) => `Completaste "${dim}" de forma independiente ${count} veces${detail}`,
    independent: (dim, _count, detail) => `Completaste "${dim}" de forma independiente${detail}`,
    assisted: (dim, _count, detail) => `Completaste "${dim}" con ayudas${detail}`,
    needs_review: (dim, _count, detail) => `"${dim}" necesita un repaso más${detail}`,
  },
  "fr-FR": {
    repeat_verified: (dim, count, detail) => `Vous avez réussi « ${dim} » en autonomie ${count} fois${detail}`,
    independent: (dim, _count, detail) => `Vous avez réussi « ${dim} » en autonomie${detail}`,
    assisted: (dim, _count, detail) => `Vous avez terminé « ${dim} » avec des indices${detail}`,
    needs_review: (dim, _count, detail) => `« ${dim} » demande encore une révision${detail}`,
  },
  "de-DE": {
    repeat_verified: (dim, count, detail) => `Du hast „${dim}“ ${count}-mal selbstständig gemeistert${detail}`,
    independent: (dim, _count, detail) => `Du hast „${dim}“ selbstständig abgeschlossen${detail}`,
    assisted: (dim, _count, detail) => `Du hast „${dim}“ mit Hinweisen abgeschlossen${detail}`,
    needs_review: (dim, _count, detail) => `„${dim}“ braucht noch eine Wiederholung${detail}`,
  },
  "ja-JP": {
    repeat_verified: (dim, count, detail) => `「${dim}」を ${count} 回連続で自力完了しました${detail}`,
    independent: (dim, _count, detail) => `「${dim}」を自力で完了しました${detail}`,
    assisted: (dim, _count, detail) => `ヒント付きで「${dim}」を完了しました${detail}`,
    needs_review: (dim, _count, detail) => `「${dim}」はもう一度復習が必要です${detail}`,
  },
  "ko-KR": {
    repeat_verified: (dim, count, detail) => `「${dim}」을(를) ${count}회 연속 혼자서 완료했습니다${detail}`,
    independent: (dim, _count, detail) => `「${dim}」을(를) 혼자서 완료했습니다${detail}`,
    assisted: (dim, _count, detail) => `도움을 받아 「${dim}」을(를) 완료했습니다${detail}`,
    needs_review: (dim, _count, detail) => `「${dim}」은(는) 한 번 더 복습이 필요합니다${detail}`,
  },
  "pt-BR": {
    repeat_verified: (dim, count, detail) => `Você concluiu "${dim}" de forma independente ${count} vezes${detail}`,
    independent: (dim, _count, detail) => `Você concluiu "${dim}" de forma independente${detail}`,
    assisted: (dim, _count, detail) => `Você concluiu "${dim}" com dicas${detail}`,
    needs_review: (dim, _count, detail) => `"${dim}" precisa de mais uma revisão${detail}`,
  },
};

function formatEvidenceDetail(language: ComposerLanguage, detail?: string): string {
  if (!detail) {
    return language === "zh-CN" || language === "ja-JP" ? "。" : ".";
  }
  return language === "zh-CN" || language === "ja-JP" ? `：${detail}` : `: ${detail}`;
}

function evidenceTimestampMs(row: Record<string, unknown> | undefined): number {
  if (!row) return 0;
  const raw = normalizeHostText(row.timestamp) ?? normalizeHostText(row.createdAt);
  if (!raw) return 0;
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Turn verified skill projection facts into one plain, learner-readable sentence.
 * Every claim traces back to concrete evidence — never a fake percent or score.
 */
export function deriveProgressSentence(
  language: ComposerLanguage,
  projection?: TrainingSkillProjection,
): LearningProgressAchievement | undefined {
  if (!projection?.dimensions) {
    return undefined;
  }
  const candidates = dimensionKeysFor(projection)
    .map((key) => {
      const dim = projection.dimensions?.[key];
      if (!dim) return undefined;
      const stateKey = isCapabilityState(dim.state) ? dim.state : "not_verified";
      const verifiedCount = typeof dim.verifiedCount === "number" ? dim.verifiedCount : 0;
      if (stateKey === "not_verified" && verifiedCount <= 0) {
        return undefined;
      }
      if (stateKey === "not_verified") {
        return undefined;
      }
      const latestEvidence = dim.evidence?.[0] as Record<string, unknown> | undefined;
      return {
        key,
        dim,
        stateKey,
        verifiedCount: Math.max(verifiedCount, stateKey === "repeat_verified" ? 2 : 1),
        latestEvidence,
        timestampMs: evidenceTimestampMs(latestEvidence),
        level: capabilityLevel(stateKey),
      };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item));

  if (candidates.length === 0) {
    return undefined;
  }

  candidates.sort((left, right) => {
    if (right.timestampMs !== left.timestampMs) {
      return right.timestampMs - left.timestampMs;
    }
    if (right.level !== left.level) {
      return right.level - left.level;
    }
    return right.verifiedCount - left.verifiedCount;
  });

  const best = candidates[0];
  const dimLabel = DIMENSION_LABELS[language][best.key];
  const detailText =
    normalizeHostText(best.latestEvidence?.cardTitle) ??
    normalizeHostText(best.latestEvidence?.scenario);
  const evidenceId = normalizeHostText(best.latestEvidence?.evidenceId);
  const formatter = (PROGRESS_SENTENCE_TEMPLATES[language] ?? PROGRESS_SENTENCE_TEMPLATES["en-US"])[
    best.stateKey
  ];
  return {
    sentence: formatter(dimLabel, best.verifiedCount, formatEvidenceDetail(language, detailText)),
    dimensionKey: best.key,
    stateKey: best.stateKey,
    verifiedCount: best.verifiedCount,
    evidenceId,
  };
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
    latestAchievement: deriveProgressSentence(language, projection),
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
