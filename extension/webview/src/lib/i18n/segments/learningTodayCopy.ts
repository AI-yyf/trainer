import type { ComposerLanguage } from "../../types";

export type LearningTodayCopy = {
  eyebrow: string;
  due: string;
  remaining: string;
};

const copy: Record<ComposerLanguage, LearningTodayCopy> = {
  "zh-CN": { eyebrow: "今日学习", due: "待复习", remaining: "待推进" },
  "en-US": { eyebrow: "Today's learning", due: "Due", remaining: "Next" },
  "es-ES": { eyebrow: "Aprendizaje de hoy", due: "Pendientes", remaining: "Siguiente" },
  "fr-FR": { eyebrow: "Apprentissage du jour", due: "À revoir", remaining: "À venir" },
  "de-DE": { eyebrow: "Heutiges Lernen", due: "Fällig", remaining: "Als Nächstes" },
  "ja-JP": { eyebrow: "今日の学習", due: "復習待ち", remaining: "次へ" },
  "ko-KR": { eyebrow: "오늘의 학습", due: "복습 대기", remaining: "다음" },
  "pt-BR": { eyebrow: "Aprendizado de hoje", due: "Para revisar", remaining: "A seguir" },
};

export function resolveLearningTodayCopy(language: ComposerLanguage): LearningTodayCopy {
  return copy[language] ?? copy["en-US"];
}
