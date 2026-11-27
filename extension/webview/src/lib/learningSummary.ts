import { normalizeHostText } from "./hostText";
import { DIMENSION_LABELS,STATE_LABELS } from "./i18n/segments/progressInlineText";
import { dimensionKeysFor } from "./progressDimensions";
import type { ComposerLanguage,TrainingSkillDimensionState,TrainingSkillProjection } from "./types";

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
    repeat_verified: (topic, count) => `「${topic}」已连续 ${count} 次独立验证通过。`,
    independent: (topic) => `已独立完成「${topic}」。`,
    assisted: (topic) => `已在辅助下完成「${topic}」，下一步建议尝试独立完成。`,
    needs_review: (topic) => `「${topic}」掌握尚不稳固，建议安排复习巩固。`,
  },
  "en-US": {
    repeat_verified: (topic, count) => `Independently verified "${topic}" across ${count} consecutive assessments.`,
    independent: (topic) => `Independently completed "${topic}".`,
    assisted: (topic) => `Completed "${topic}" with assistance; independent verification is recommended next.`,
    needs_review: (topic) => `Mastery of "${topic}" requires further consolidation; schedule a review.`,
  },
  "es-ES": {
    repeat_verified: (topic, count) => `"${topic}" verificado de forma independiente en ${count} evaluaciones consecutivas.`,
    independent: (topic) => `"${topic}" completado de forma independiente.`,
    assisted: (topic) => `"${topic}" completado con asistencia; se recomienda intentar la verificación independiente.`,
    needs_review: (topic) => `El dominio de "${topic}" aún requiere consolidación; se sugiere repasar.`,
  },
  "fr-FR": {
    repeat_verified: (topic, count) => `« ${topic} » validé de manière autonome lors de ${count} vérifications consécutives.`,
    independent: (topic) => `« ${topic} » réalisé de manière autonome.`,
    assisted: (topic) => `« ${topic} » réalisé avec assistance ; une validation autonome est recommandée ensuite.`,
    needs_review: (topic) => `La maîtrise de « ${topic} » reste à consolider ; une révision est recommandée.`,
  },
  "de-DE": {
    repeat_verified: (topic, count) => `„${topic}“ wurde ${count}-mal in Folge selbstständig nachgewiesen.`,
    independent: (topic) => `„${topic}“ wurde selbstständig abgeschlossen.`,
    assisted: (topic) => `„${topic}“ wurde mit Hilfestellung abgeschlossen; als Nächstes wird eine selbstständige Prüfung empfohlen.`,
    needs_review: (topic) => `Die Beherrschung von „${topic}“ ist noch nicht gefestigt; eine Wiederholung wird empfohlen.`,
  },
  "ja-JP": {
    repeat_verified: (topic, count) => `「${topic}」は ${count} 回連続で独力による検証に合格しました。`,
    independent: (topic) => `「${topic}」を独力で完了しました。`,
    assisted: (topic) => `補助のもと「${topic}」を完了しました。次は独力での検証を推奨します。`,
    needs_review: (topic) => `「${topic}」の定着が十分ではないため、復習による補強を推奨します。`,
  },
  "ko-KR": {
    repeat_verified: (topic, count) => `「${topic}」을(를) ${count}회 연속 독립 검증으로 통과했습니다.`,
    independent: (topic) => `「${topic}」을(를) 독립적으로 완료했습니다.`,
    assisted: (topic) => `보조를 받아 「${topic}」을(를) 완료했습니다. 다음에는 독립 수행을 권장합니다.`,
    needs_review: (topic) => `「${topic}」의 숙달이 아직 안정적이지 않아 복습을 통한 보강이 필요합니다.`,
  },
  "pt-BR": {
    repeat_verified: (topic, count) => `"${topic}" verificado de forma independente em ${count} avaliações consecutivas.`,
    independent: (topic) => `"${topic}" concluído de forma independente.`,
    assisted: (topic) => `"${topic}" concluído com assistência; recomenda-se tentar a verificação independente a seguir.`,
    needs_review: (topic) => `O domínio de "${topic}" ainda requer consolidação; recomenda-se revisar.`,
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
      return `${reviewText}掌握尚不稳固，建议优先复习巩固。`;
    }
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText}仍需辅助` : "",
        untried.length > 0 ? `${untriedText}尚未验证` : "",
      ]
        .filter(Boolean)
        .join("，");
      return `${strongText}已达独立完成标准；${rest}。`;
    }
    if (strong.length > 0) {
      return `${strongText}均已达到独立完成标准。`;
    }
    if (assisted.length > 0) {
      return `${assistedText}已在辅助下完成，下一步建议尝试独立验证。`;
    }
    return undefined;
  }

  if (language === "es-ES") {
    if (review.length > 0) return `${reviewText} requiere consolidación prioritaria.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText} con asistencia` : "",
        untried.length > 0 ? `${untriedText} sin verificar` : "",
      ].filter(Boolean).join(", ");
      return `${strongText} alcanzado de forma independiente; ${rest}.`;
    }
    if (strong.length > 0) return `${strongText} alcanzado de forma independiente.`;
    if (assisted.length > 0) return `${assistedText} completado con asistencia; se recomienda verificación independiente.`;
    return undefined;
  }

  if (language === "fr-FR") {
    if (review.length > 0) return `${reviewText} nécessite une consolidation prioritaire.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText} avec assistance` : "",
        untried.length > 0 ? `${untriedText} non vérifié` : "",
      ].filter(Boolean).join(", ");
      return `Autonomie acquise sur ${strongText} ; ${rest}.`;
    }
    if (strong.length > 0) return `Autonomie acquise sur ${strongText}.`;
    if (assisted.length > 0) return `${assistedText} réalisé avec assistance ; validation autonome recommandée.`;
    return undefined;
  }

  if (language === "de-DE") {
    if (review.length > 0) return `${reviewText} erfordert eine vorrangige Wiederholung.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText} mit Hilfestellung` : "",
        untried.length > 0 ? `${untriedText} nicht überprüft` : "",
      ].filter(Boolean).join(", ");
      return `Selbstständig erreicht in ${strongText}; ${rest}.`;
    }
    if (strong.length > 0) return `Selbstständig erreicht in ${strongText}.`;
    if (assisted.length > 0) return `${assistedText} mit Hilfestellung abgeschlossen; selbstständige Prüfung empfohlen.`;
    return undefined;
  }

  if (language === "ja-JP") {
    if (review.length > 0) return `${reviewText}の定着が不十分なため、優先的な復習を推奨します。`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText}は補助あり` : "",
        untried.length > 0 ? `${untriedText}は未検証` : "",
      ].filter(Boolean).join("、");
      return `${strongText}は独力達成水準に到達しており、${rest}です。`;
    }
    if (strong.length > 0) return `${strongText}はいずれも独力達成水準に到達しています。`;
    if (assisted.length > 0) return `${assistedText}は補助ありで完了済みです。次は独力での検証を推奨します。`;
    return undefined;
  }

  if (language === "ko-KR") {
    if (review.length > 0) return `${reviewText}의 숙달이 불충분하여 우선 복습이 필요합니다.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText}은(는) 보조 완료` : "",
        untried.length > 0 ? `${untriedText}은(는) 미검증` : "",
      ].filter(Boolean).join(", ");
      return `${strongText}은(는) 독립 수행 기준에 도달했으며, ${rest} 상태입니다.`;
    }
    if (strong.length > 0) return `${strongText} 모두 독립 수행 기준에 도달했습니다.`;
    if (assisted.length > 0) return `${assistedText}을(를) 보조하에 완료했습니다. 다음 단계로 독립 검증을 권장합니다.`;
    return undefined;
  }

  if (language === "pt-BR") {
    if (review.length > 0) return `${reviewText} requer consolidação prioritária.`;
    if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
      const rest = [
        assisted.length > 0 ? `${assistedText} com assistência` : "",
        untried.length > 0 ? `${untriedText} não verificado` : "",
      ].filter(Boolean).join(", ");
      return `Autonomia atingida em ${strongText}; ${rest}.`;
    }
    if (strong.length > 0) return `Autonomia atingida em ${strongText}.`;
    if (assisted.length > 0) return `${assistedText} concluído com assistência; recomenda-se verificação independente.`;
    return undefined;
  }

  if (review.length > 0) {
    return `${reviewText} requires prioritized review and consolidation.`;
  }
  if (strong.length > 0 && (assisted.length > 0 || untried.length > 0)) {
    const rest = [
      assisted.length > 0 ? `${assistedText} assisted` : "",
      untried.length > 0 ? `${untriedText} unverified` : "",
    ]
      .filter(Boolean)
      .join(", ");
    return `Independent proficiency verified in ${strongText}; ${rest}.`;
  }
  if (strong.length > 0) {
    return `Independent proficiency verified in ${strongText}.`;
  }
  if (assisted.length > 0) {
    return `${assistedText} completed with assistance; independent verification recommended next.`;
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

const CASUAL_GREETING_TOKENS = new Set([
  "你好",
  "您好",
  "你好呀",
  "你好啊",
  "你好哦",
  "你好吗",
  "嗨",
  "哈喽",
  "哈罗",
  "早",
  "早安",
  "早上好",
  "上午好",
  "中午好",
  "下午好",
  "晚上好",
  "晚安",
  "在吗",
  "在不在",
  "谢谢",
  "多谢",
  "感谢",
  "谢谢你",
  "好的",
  "好",
  "嗯",
  "嗯嗯",
  "收到",
  "明白",
  "了解",
  "测试",
  "试试",
  "hi",
  "hello",
  "hey",
  "yo",
  "sup",
  "hi there",
  "hello there",
  "hey there",
  "hi trainer",
  "hello trainer",
  "hey trainer",
  "你好 trainer",
  "你好教练",
  "good morning",
  "good afternoon",
  "good evening",
  "thanks",
  "thank you",
  "thx",
  "ok",
  "okay",
  "got it",
  "ping",
  "test",
  "你是谁",
  "你叫什么",
  "你能做什么",
  "你是干嘛的",
  "who are you",
  "what can you do",
  "こんにちは",
  "こんばんは",
  "ありがとう",
  "ありがとうございます",
  "안녕하세요",
  "감사합니다",
  "hola",
  "gracias",
  "bonjour",
  "salut",
  "merci",
  "hallo",
  "danke",
  "olá",
  "ola",
  "oi",
  "obrigado",
  "obrigada",
]);

const BOGUS_SMALLTALK_STEP_PATTERNS: readonly RegExp[] = [
  /^先把\s+(.+?)\s+压成一个很小的补丁目标(?:[，,]?\s*再继续写[。.]?)?$/u,
  /^先交付一个小而可复盘的\s+(.+?)\s+版本(?:[，,。.]|$)/u,
  /^先找到\s+(.+?)\s+的第一处切口(?:[，,。.]|$)/u,
  /^先用一句话重述\s+(.+?)\s+该表现成什么样[。.]?$/u,
  /^先说出\s+(.+?)\s+的第一个可见行为(?:[，,。.]|$)/u,
  /^围绕[「"](.+?)[」"]先做一个小动作/u,
];

function isCasualGreetingTarget(raw: string): boolean {
  const normalized = raw
    .trim()
    .toLocaleLowerCase()
    .replace(/[\s`~!@#$%^&*()\-_=+[\]{};:'",.<>/?\\|，。！？、；：“”‘’（）【】《》~～·]+/g, " ")
    .trim();
  return normalized.length > 0 && CASUAL_GREETING_TOKENS.has(normalized);
}

/**
 * Scrub legacy ImplementationCoach fallback steps that mistakenly wrapped a
 * casual greeting ("先把 你好 压成一个很小的补丁目标，再继续写。") from persisted
 * pre-1.5 sessions while preserving real technical goals.
 */
export function sanitizeBogusLearningStep(value?: string): string | undefined {
  const cleaned = " ".concat(String(value ?? "").trim()).trim().replace(/\s+/g, " ");
  if (!cleaned) {
    return undefined;
  }
  for (const pattern of BOGUS_SMALLTALK_STEP_PATTERNS) {
    const match = pattern.exec(cleaned);
    if (match && isCasualGreetingTarget(match[1])) {
      return undefined;
    }
  }
  return cleaned;
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
    goalTitle: sanitizeBogusLearningStep(input.planTitle),
    goalStep: sanitizeBogusLearningStep(input.currentStep),
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
