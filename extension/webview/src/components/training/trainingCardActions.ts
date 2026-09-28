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
    language === "zh-CN" ? "学员跳过" : "Learner skipped",
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
      ? language === "zh-CN"
        ? "自评：再来一次"
        : "Self-grade: again"
      : grade === "hard"
        ? language === "zh-CN"
          ? "自评：有点难"
          : "Self-grade: hard"
        : grade === "good"
          ? language === "zh-CN"
            ? "自评：不错"
            : "Self-grade: good"
          : language === "zh-CN"
            ? "自评：太简单了"
            : "Self-grade: easy";
  onCardStatusTransition(normalizedCardId, "reviewed", reason);
  return true;
}
