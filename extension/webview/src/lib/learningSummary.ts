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

const TOPIC_SENTENCE_TEMPLATES: Record<
  ComposerLanguage,
  Record<Exclude<CapabilityState, "not_verified">, (topic: string, count: number) => string>
> = {
  "zh-CN": {
    repeat_verified: (topic, count) => `「${topic}」已连续 ${count} 次独立通过。`,
    independent: (topic) => `已能独立完成「${topic}」。`,
    assisted: (topic) => `在提示下完成了「${topic}」，下次试试独立做。`,
    needs_review: (topic) => `「${topic}」还不算稳，建议再回顾一次。`,
  },
  "en-US": {
    repeat_verified: (topic, count) => `Independently verified "${topic}" ${count} times in a row.`,
    independent: (topic) => `Independently completed "${topic}".`,
    assisted: (topic) => `Completed "${topic}" with hints — try it solo next.`,
    needs_review: (topic) => `"${topic}" isn't solid yet — review it once more.`,
  },
  "es-ES": {
    repeat_verified: (topic, count) => `Verificaste "${topic}" sin ayuda ${count} veces seguidas.`,
    independent: (topic) => `Completaste "${topic}" sin ayuda.`,
    assisted: (topic) => `Completaste "${topic}" con pistas; intenta hacerlo solo la próxima vez.`,
    needs_review: (topic) => `"${topic}" aún no está firme; conviene repasarlo.`,
  },
  "fr-FR": {
    repeat_verified: (topic, count) => `Vous avez réussi « ${topic} » sans aide ${count} fois de suite.`,
    independent: (topic) => `Vous avez réussi « ${topic} » en autonomie.`,
    assisted: (topic) => `Vous avez terminé « ${topic} » avec des indices ; essayez sans aide la prochaine fois.`,
    needs_review: (topic) => `« ${topic} » reste fragile ; à revoir une fois.`,
  },
  "de-DE": {
    repeat_verified: (topic, count) => `Du hast „${topic}“ ${count}-mal in Folge selbstständig geschafft.`,
    independent: (topic) => `Du hast „${topic}“ selbstständig abgeschlossen.`,
    assisted: (topic) => `Du hast „${topic}“ mit Hinweisen geschafft – probier es als Nächstes allein.`,
    needs_review: (topic) => `„${topic}“ sitzt noch nicht fest – bitte noch einmal wiederholen.`,
  },
  "ja-JP": {
    repeat_verified: (topic, count) => `「${topic}」を ${count} 回連続で自力達成しました。`,
    independent: (topic) => `「${topic}」を独力で達成しました。`,
    assisted: (topic) => `ヒント付きで「${topic}」を終えました。次は自力で試してみましょう。`,
    needs_review: (topic) => `「${topic}」はまだ定着途中なので、もう一度見直しましょう。`,
  },
  "ko-KR": {
    repeat_verified: (topic, count) => `「${topic}」을(를) ${count}회 연속 혼자서 통과했습니다.`,
    independent: (topic) => `「${topic}」을(를) 혼자서 해결했습니다.`,
    assisted: (topic) => `힌트로 「${topic}」을(를) 마쳤습니다. 다음엔 혼자 시도해 보세요.`,
    needs_review: (topic) => `「${topic}」은(는) 아직 단단하지 않으니 한 번 더 복습하세요.`,
  },
  "pt-BR": {
    repeat_verified: (topic, count) => `Você validou "${topic}" sem ajuda ${count} vezes seguidas.`,
    independent: (topic) => `Você concluiu "${topic}" sem ajuda.`,
    assisted: (topic) => `Você concluiu "${topic}" com dicas; tente sem ajuda na próxima.`,
    needs_review: (topic) => `"${topic}" ainda não está sólido — vale revisar mais uma vez.`,
  },
};

function joinDimensionLabels(language: ComposerLanguage, labels: string[]): string {
  const separator = language === "zh-CN" || language === "ja-JP" ? "、" : ", ";
  return labels.join(separator);
}

function summarizeDimensionsOverview(
  language: ComposerLanguage,
  projection: TrainingSkillProjection,
): string | undefined {
  const strong: string[] = [];
  const assisted: string[] = [];
  const review: string[] = [];
  const untried: string[] = [];

  for (const key of dimensionKeysFor(projection)) {
    const dim = projection.dimensions?.[key];
    const label = DIMENSION_LABELS[language][key];
    const state = dim && isCapabilityState(dim.state) ? dim.state : "not_verified";
    if (state === "repeat_verified" || state === "independent") {
      strong.push(label);
    } else if (state === "assisted") {
      assisted.push(label);
    } else if (state === "needs_review") {
      review.push(label);
    } else {
      untried.push(label);
    }
  }

  const strongText = joinDimensionLabels(language, strong);
  const assistedText = joinDimensionLabels(language, assisted);
  const reviewText = joinDimensionLabels(language, review);
  const untriedText = joinDimensionLabels(language, untried);

  if (language === "zh-CN") {
    if (review.length > 0) {
      return `${reviewText}还不算稳，建议先回顾一次。`;
    }
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText}还需提示` : "",
        untried.length > 0 ? `${untriedText}尚未实测` : "",
      ]
        .filter(Boolean)
        .join("，");
      return `${strongText}已能独立把关；${rest}。`;
    }
    if (strong.length > 0) {
      return `${strongText}均已能独立完成。`;
    }
    if (assisted.length > 0) {
      return `${assistedText}已在提示下练过，下一步试试独立完成。`;
    }
    return undefined;
  }

  if (language === "es-ES") {
    if (review.length > 0) return `${reviewText} necesita un repaso.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText} con pistas` : "",
        untried.length > 0 ? `${untriedText} sin practicar` : "",
      ].filter(Boolean).join(", ");
      return `Completaste ${strongText} sin ayuda; ${rest}.`;
    }
    if (strong.length > 0) return `Completaste ${strongText} sin ayuda.`;
    if (assisted.length > 0) return `Practicaste ${assistedText} con pistas; inténtalo solo luego.`;
    return undefined;
  }

  if (language === "fr-FR") {
    if (review.length > 0) return `${reviewText} demande une révision.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText} avec indices` : "",
        untried.length > 0 ? `${untriedText} pas encore pratiqué` : "",
      ].filter(Boolean).join(", ");
      return `Autonomie acquise sur ${strongText} ; ${rest}.`;
    }
    if (strong.length > 0) return `Autonomie acquise sur ${strongText}.`;
    if (assisted.length > 0) return `Pratiqué ${assistedText} avec indices ; essayez sans aide ensuite.`;
    return undefined;
  }

  if (language === "de-DE") {
    if (review.length > 0) return `${reviewText} braucht noch eine Wiederholung.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText} noch mit Hinweisen` : "",
        untried.length > 0 ? `${untriedText} noch ungeübt` : "",
      ].filter(Boolean).join(", ");
      return `Selbstständig bei ${strongText}; ${rest}.`;
    }
    if (strong.length > 0) return `Selbstständig bei ${strongText}.`;
    if (assisted.length > 0) return `Mit Hinweisen geübt: ${assistedText} — als Nächstes allein testen.`;
    return undefined;
  }

  if (language === "ja-JP") {
    if (review.length > 0) return `${reviewText}はまだ定着途中なので、もう一度見直しましょう。`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText}はヒントあり` : "",
        untried.length > 0 ? `${untriedText}は未練習` : "",
      ].filter(Boolean).join("、");
      return `${strongText}は独力で到達、${rest}です。`;
    }
    if (strong.length > 0) return `${strongText}はいずれも独力で完了済みです。`;
    if (assisted.length > 0) return `${assistedText}はヒント付きで完了済みです。次は自力で試してみましょう。`;
    return undefined;
  }

  if (language === "ko-KR") {
    if (review.length > 0) return `${reviewText}은(는) 한 번 더 복습이 필요합니다.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText}은(는) 힌트 사용` : "",
        untried.length > 0 ? `${untriedText}은(는) 미연습` : "",
      ].filter(Boolean).join(", ");
      return `${strongText}은(는) 혼자 해결할 수 있고, ${rest} 상태입니다.`;
    }
    if (strong.length > 0) return `${strongText} 모두 혼자서 완료했습니다.`;
    if (assisted.length > 0) return `힌트로 ${assistedText}을(를) 마쳤습니다. 다음엔 혼자 시도해 보세요.`;
    return undefined;
  }

  if (language === "pt-BR") {
    if (review.length > 0) return `${reviewText} precisa de mais uma revisão.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText} com dicas` : "",
        untried.length > 0 ? `${untriedText} sem prática` : "",
      ].filter(Boolean).join(", ");
      return `Concluiu ${strongText} sem ajuda; ${rest}.`;
    }
    if (strong.length > 0) return `Concluiu ${strongText} sem ajuda.`;
    if (assisted.length > 0) return `Praticou ${assistedText} com dicas; tente sem ajuda depois.`;
    return undefined;
  }

  if (review.length > 0) {
    return `${reviewText} needs another review pass.`;
  }
  if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
    const rest = [
      assisted.length > 0 ? `${assistedText} with hints` : "",
      untried.length > 0 ? `${untriedText} not practiced yet` : "",
    ]
      .filter(Boolean)
      .join(", ");
    return `Independently completed ${strongText}; ${rest}.`;
  }
  if (strong.length > 0) {
    return `Independently completed ${strongText}.`;
  }
  if (assisted.length > 0) {
    return `Practiced ${assistedText} with hints — try independently next.`;
  }
  return undefined;
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
  const detailText =
    normalizeHostText(best.latestEvidence?.cardTitle) ??
    normalizeHostText(best.latestEvidence?.scenario);
  const evidenceId = normalizeHostText(best.latestEvidence?.evidenceId);
  if (detailText) {
    const formatter = (TOPIC_SENTENCE_TEMPLATES[language] ?? TOPIC_SENTENCE_TEMPLATES["en-US"])[
      best.stateKey
    ];
    return {
      sentence: formatter(detailText, best.verifiedCount),
      dimensionKey: best.key,
      stateKey: best.stateKey,
      verifiedCount: best.verifiedCount,
      evidenceId,
    };
  }

  const overview = summarizeDimensionsOverview(language, projection);
  if (!overview) {
    return undefined;
  }
  return {
    sentence: overview,
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
