import type { ComposerLanguage } from "../../lib/types";
import { LearningNavIcon } from "../icons";

const COPY: Record<ComposerLanguage, { learning: string; due: string; open: string }> = {
  "zh-CN": { learning: "学习", due: "{n} 张待复习", open: "打开学习" },
  "en-US": { learning: "Learning", due: "{n} due", open: "Open learning" },
  "es-ES": { learning: "Aprendizaje", due: "{n} pendientes", open: "Abrir aprendizaje" },
  "fr-FR": { learning: "Apprentissage", due: "{n} à revoir", open: "Ouvrir l'apprentissage" },
  "de-DE": { learning: "Lernen", due: "{n} fällig", open: "Lernen öffnen" },
  "ja-JP": { learning: "学習", due: "{n} 件", open: "学習を開く" },
  "ko-KR": { learning: "학습", due: "{n}개", open: "학습 열기" },
  "pt-BR": { learning: "Aprendizado", due: "{n} pendentes", open: "Abrir aprendizado" },
};

export interface LearningStripProps {
  language: ComposerLanguage;
  goalTitle?: string;
  currentStep?: string;
  /** A one-off active goal (Goal mode) is learning state too. */
  goalText?: string;
  dueCount: number;
  onOpen: () => void;
}

/**
 * One quiet line of learning state above the conversation. It is a state
 * readout, not a card: no accent button, no second primary action. The drawer
 * owns management.
 *
 * The line answers the acceptance contract explicitly — current goal, current
 * step, due count — instead of collapsing goal and step into one field: a
 * learner reading "当前目标 · 当前步骤 · 待复习数" must see all three.
 */
export function LearningStrip({ language, goalTitle, currentStep, goalText, dueCount, onOpen }: LearningStripProps) {
  const copy = COPY[language];
  const goal = goalTitle?.trim() || goalText?.trim();
  const step = currentStep?.trim();
  if (!goal && !step && dueCount <= 0) {
    return null;
  }
  const items = [
    goal ? { key: "goal", value: goal } : undefined,
    step ? { key: "step", value: step } : undefined,
    dueCount > 0 ? { key: "due", value: copy.due.replace("{n}", String(dueCount)) } : undefined,
  ].filter((item): item is { key: string; value: string } => Boolean(item));
  return (
    <button
      type="button"
      className="learning-strip"
      data-learning-strip="true"
      aria-label={copy.open}
      title={items.map((item) => item.value).join(" · ")}
      onClick={onOpen}
    >
      <span className="learning-strip__icon" aria-hidden="true"><LearningNavIcon size={14} /></span>
      <span className="learning-strip__label">{copy.learning}</span>
      {items.map((item, index) => (
        <span key={item.key} className="learning-strip__item" data-learning-strip-item={item.key}>
          {index > 0 ? <span className="learning-strip__separator" aria-hidden="true">·</span> : null}
          <span className={item.key === "due" ? "learning-strip__due" : "learning-strip__title"}>
            {item.value}
          </span>
        </span>
      ))}
      <span className="learning-strip__chevron" aria-hidden="true">›</span>
    </button>
  );
}
