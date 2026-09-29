/**
 * Composer-level training card actions (§四十八).
 *
 * Lives in its own light module so App.tsx can use these pure helpers
 * statically without pinning the whole TrainingWorkbenchView into the first
 * bundle — the view itself is lazy (§十四).
 */
import type { ComposerLanguage } from "../../lib/types";
import type { TrainingCardStatus } from "../../../../../shared/src/trainingCardRouting";

export type TrainingCardGrade = "again" | "hard" | "good" | "easy";

export type TrainingComposerCardCommand =
  | { kind: "skip" }
  | { kind: "grade"; grade: TrainingCardGrade };

export type CardStatusTransition = (
  cardId: string,
  newStatus: TrainingCardStatus,
  reason?: string,
) => void;

type CardStatusTransitionSource =
  | CardStatusTransition
  | ((cardId: string, newStatus: string, reason?: string) => void)
  | undefined;

export function interpretTrainingComposerCardCommand(
  text: string,
): TrainingComposerCardCommand | undefined {
  const normalized = text.replace(/\s+/g, " ").trim().toLowerCase();
  if (!normalized) {
    return undefined;
  }
  if (/^(跳过(?:这张)?|先跳过|skip(?: this(?: card)?)?)$/u.test(normalized)) {
    return { kind: "skip" };
  }
  if (/^(再来一次|again)$/u.test(normalized)) {
    return { kind: "grade", grade: "again" };
  }
  if (/^(有点难|hard)$/u.test(normalized)) {
    return { kind: "grade", grade: "hard" };
  }
  if (/^(这张我会了|我会了|不错|good)$/u.test(normalized)) {
    return { kind: "grade", grade: "good" };
  }
  if (/^(太简单了|easy)$/u.test(normalized)) {
    return { kind: "grade", grade: "easy" };
  }
  return undefined;
}

type TrainingCardActionCopyKey =
  | "skipReason"
  | "gradeAgainReason"
  | "gradeHardReason"
  | "gradeGoodReason"
  | "gradeEasyReason";

/**
 * Status-transition reason copy keyed by zh-CN string keys (§十五 i18n
 * copy-record pattern). Kept in-file: the literals are persisted reasons.
 */
const trainingCardActionCopy: Record<ComposerLanguage, Record<TrainingCardActionCopyKey, string>> = {
  "zh-CN": {
    skipReason: "学员跳过",
    gradeAgainReason: "自评：再来一次",
    gradeHardReason: "自评：有点难",
    gradeGoodReason: "自评：不错",
    gradeEasyReason: "自评：太简单了",
  },
  "en-US": {
    skipReason: "Learner skipped",
    gradeAgainReason: "Self-grade: again",
    gradeHardReason: "Self-grade: hard",
    gradeGoodReason: "Self-grade: good",
    gradeEasyReason: "Self-grade: easy",
  },
  "es-ES": {
    skipReason: "Saltado por el estudiante",
    gradeAgainReason: "Autoevaluación: otra vez",
    gradeHardReason: "Autoevaluación: difícil",
    gradeGoodReason: "Autoevaluación: bien",
    gradeEasyReason: "Autoevaluación: muy fácil",
  },
  "fr-FR": {
    skipReason: "Passé par l'apprenant",
    gradeAgainReason: "Auto-évaluation : à revoir",
    gradeHardReason: "Auto-évaluation : difficile",
    gradeGoodReason: "Auto-évaluation : bien",
    gradeEasyReason: "Auto-évaluation : trop facile",
  },
  "de-DE": {
    skipReason: "Von Lernenden übersprungen",
    gradeAgainReason: "Selbsteinschätzung: nochmal",
    gradeHardReason: "Selbsteinschätzung: schwer",
    gradeGoodReason: "Selbsteinschätzung: gut",
    gradeEasyReason: "Selbsteinschätzung: zu leicht",
  },
  "ja-JP": {
    skipReason: "学習者がスキップ",
    gradeAgainReason: "自己評価：もう一度",
    gradeHardReason: "自己評価：難しい",
    gradeGoodReason: "自己評価：良い",
    gradeEasyReason: "自己評価：簡単すぎる",
  },
  "ko-KR": {
    skipReason: "학습자가 건너뜀",
    gradeAgainReason: "자가 평가: 다시",
    gradeHardReason: "자가 평가: 어려움",
    gradeGoodReason: "자가 평가: 좋음",
    gradeEasyReason: "자가 평가: 너무 쉬움",
  },
  "pt-BR": {
    skipReason: "Pulado pelo aprendiz",
    gradeAgainReason: "Autoavaliação: de novo",
    gradeHardReason: "Autoavaliação: difícil",
    gradeGoodReason: "Autoavaliação: bom",
    gradeEasyReason: "Autoavaliação: fácil demais",
  },
};

function trainingCardActionText(language: ComposerLanguage, key: TrainingCardActionCopyKey): string {
  return trainingCardActionCopy[language]?.[key] ?? trainingCardActionCopy["en-US"][key];
}

export function applyTrainingCardSkip(
  onCardStatusTransition: CardStatusTransitionSource,
  cardId: string | undefined,
  language: ComposerLanguage,
  leftoverStoredNote?: string,
): boolean {
  const normalizedCardId = cardId?.trim() || "";
  if (!normalizedCardId || !onCardStatusTransition || leftoverStoredNote) {
    return false;
  }
  onCardStatusTransition(
    normalizedCardId,
    "skipped",
    trainingCardActionText(language, "skipReason"),
  );
  return true;
}

export function applyTrainingCardGrade(
  onCardStatusTransition: CardStatusTransitionSource,
  cardId: string | undefined,
  language: ComposerLanguage,
  grade: TrainingCardGrade,
  leftoverStoredNote?: string,
): boolean {
  const normalizedCardId = cardId?.trim() || "";
  if (!normalizedCardId || !onCardStatusTransition || leftoverStoredNote) {
    return false;
  }
  const reason =
    grade === "again"
      ? trainingCardActionText(language, "gradeAgainReason")
      : grade === "hard"
        ? trainingCardActionText(language, "gradeHardReason")
        : grade === "good"
          ? trainingCardActionText(language, "gradeGoodReason")
          : trainingCardActionText(language, "gradeEasyReason");
  onCardStatusTransition(normalizedCardId, "reviewed", reason);
  return true;
}
