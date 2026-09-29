/**
 * TrainingWelcomePanel Component
 *
 * A compact training status panel based on:
 * - Time of day
 * - Current streak status
 * - Recent training activity
 * - Personal learning context
 *
 * This panel keeps the next training action visible.
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §6.6 (humanized UX)
 */

import React, { useMemo } from "react";
import { getMotivationalMessage } from "../../../../../shared/src/motivation";
import {
  SparklesIcon,
  TrophyIcon,
  TargetIcon,
  FireIcon,
  LightBulbIcon,
  ArrowRightIcon,
} from "../icons";
import {
  timeOfDayGreeting,
  trainingDurationCopy,
} from "./trainingPanelCopy";
import type { ComposerLanguage } from "../../lib/types";

type TrainingWelcomeTextKey =
  | "streakLabel"
  | "masteredLabel"
  | "weekLabel"
  | "dueLabel"
  | "startLabel"
  | "reviewLabel"
  | "continueLabel"
  | "allDoneLabel"
  | "dayUnit"
  | "cardUnit"
  | "todayProgress"
  | "recommendedNext"
  | "nameSeparator";

/** §十五: welcome-panel labels in eight languages (no zh/en binary). */
const trainingWelcomeTextCopy: Record<ComposerLanguage, Record<TrainingWelcomeTextKey, string>> = {
  "zh-CN": {
    streakLabel: "连续练习",
    masteredLabel: "已掌握",
    weekLabel: "本周练习",
    dueLabel: "待复习",
    startLabel: "开始",
    reviewLabel: "复习",
    continueLabel: "继续学习",
    allDoneLabel: "今日已完成",
    dayUnit: "天",
    cardUnit: " 张",
    todayProgress: "今日进度",
    recommendedNext: "推荐下一步",
    nameSeparator: "，",
  },
  "en-US": {
    streakLabel: "Streak",
    masteredLabel: "Mastered",
    weekLabel: "This week",
    dueLabel: "Due",
    startLabel: "Start",
    reviewLabel: "Review",
    continueLabel: "Continue",
    allDoneLabel: "All done today",
    dayUnit: " days",
    cardUnit: " cards",
    todayProgress: "Today's Progress",
    recommendedNext: "Recommended Next",
    nameSeparator: ", ",
  },
  "es-ES": {
    streakLabel: "Racha",
    masteredLabel: "Dominado",
    weekLabel: "Esta semana",
    dueLabel: "Pendiente",
    startLabel: "Empezar",
    reviewLabel: "Repasar",
    continueLabel: "Continuar",
    allDoneLabel: "Todo listo hoy",
    dayUnit: " días",
    cardUnit: " tarjetas",
    todayProgress: "Progreso de hoy",
    recommendedNext: "Siguiente recomendado",
    nameSeparator: ", ",
  },
  "fr-FR": {
    streakLabel: "Série",
    masteredLabel: "Maîtrisé",
    weekLabel: "Cette semaine",
    dueLabel: "À revoir",
    startLabel: "Démarrer",
    reviewLabel: "Réviser",
    continueLabel: "Continuer",
    allDoneLabel: "Tout est fait aujourd'hui",
    dayUnit: " jours",
    cardUnit: " cartes",
    todayProgress: "Progrès du jour",
    recommendedNext: "Prochaine étape recommandée",
    nameSeparator: ", ",
  },
  "de-DE": {
    streakLabel: "Serie",
    masteredLabel: "Gemeistert",
    weekLabel: "Diese Woche",
    dueLabel: "Fällig",
    startLabel: "Start",
    reviewLabel: "Wiederholen",
    continueLabel: "Fortsetzen",
    allDoneLabel: "Heute alles erledigt",
    dayUnit: " Tage",
    cardUnit: " Karten",
    todayProgress: "Fortschritt heute",
    recommendedNext: "Empfohlener nächster Schritt",
    nameSeparator: ", ",
  },
  "ja-JP": {
    streakLabel: "連続練習",
    masteredLabel: "習得済み",
    weekLabel: "今週の練習",
    dueLabel: "復習予定",
    startLabel: "開始",
    reviewLabel: "復習",
    continueLabel: "続ける",
    allDoneLabel: "今日は完了",
    dayUnit: "日",
    cardUnit: " 枚",
    todayProgress: "今日の進捗",
    recommendedNext: "おすすめの次のステップ",
    nameSeparator: "、",
  },
  "ko-KR": {
    streakLabel: "연속 연습",
    masteredLabel: "습득 완료",
    weekLabel: "이번 주 연습",
    dueLabel: "복습 예정",
    startLabel: "시작",
    reviewLabel: "복습",
    continueLabel: "계속",
    allDoneLabel: "오늘 완료",
    dayUnit: "일",
    cardUnit: "장",
    todayProgress: "오늘의 진행률",
    recommendedNext: "추천 다음 단계",
    nameSeparator: ", ",
  },
  "pt-BR": {
    streakLabel: "Sequência",
    masteredLabel: "Dominado",
    weekLabel: "Esta semana",
    dueLabel: "Pendente",
    startLabel: "Iniciar",
    reviewLabel: "Revisar",
    continueLabel: "Continuar",
    allDoneLabel: "Tudo pronto hoje",
    dayUnit: " dias",
    cardUnit: " cartões",
    todayProgress: "Progresso de hoje",
    recommendedNext: "Próximo passo recomendado",
    nameSeparator: ", ",
  },
};

function trainingWelcomeText(language: ComposerLanguage, key: TrainingWelcomeTextKey): string {
  return trainingWelcomeTextCopy[language]?.[key] ?? trainingWelcomeTextCopy["en-US"][key];
}

export interface TrainingWelcomePanelProps {
  /** Current language */
  language: "zh-CN" | "en-US";
  /** User's name (optional, for personalization) */
  learnerName?: string;
  /** Current streak in days */
  currentStreak: number;
  /** Total cards mastered */
  cardsMastered: number;
  /** Practice time this week in minutes */
  weeklyPracticeMinutes: number;
  /** Today's progress (0-100) */
  todayProgress: number;
  /** Number of cards due for review */
  cardsDueToday: number;
  /** Next recommended action */
  nextAction?: {
    label: string;
    description: string;
    type: "review" | "practice" | "new_card" | "continue";
  };
  /** Callback when user clicks to start training */
  onStartTraining?: () => void;
  /** Callback when user clicks to review cards */
  onReviewCards?: () => void;
  /** Callback when user clicks to continue learning */
  onContinueLearning?: () => void;
}

/**
 * Get time-based greeting message (hour bucketing stays here; copy lives in
 * the eight-language record).
 */
function getTimeGreeting(hour: number, language: ComposerLanguage): { greeting: string } {
  return { greeting: timeOfDayGreeting(hour, language) };
}

function formatTime(minutes: number, language: ComposerLanguage): string {
  const duration = trainingDurationCopy(language);
  if (minutes < 60) {
    return duration.minutes(minutes);
  }
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (mins === 0) {
    return duration.hours(hours);
  }
  return duration.mixed(hours, mins);
}

export const TrainingWelcomePanel: React.FC<TrainingWelcomePanelProps> = ({
  language,
  learnerName,
  currentStreak,
  cardsMastered,
  weeklyPracticeMinutes,
  todayProgress,
  cardsDueToday,
  nextAction,
  onStartTraining,
  onReviewCards,
  onContinueLearning,
}) => {
  const currentHour = new Date().getHours();
  const timeGreeting = getTimeGreeting(currentHour, language);
  const motivation = getMotivationalMessage(
    currentStreak,
    cardsMastered,
    todayProgress,
    cardsDueToday,
    language,
  );

  const personalizedGreeting = useMemo(() => {
    const baseGreeting = timeGreeting.greeting;
    if (learnerName) {
      return `${baseGreeting}${trainingWelcomeText(language, "nameSeparator")}${learnerName}`;
    }
    return baseGreeting;
  }, [timeGreeting, learnerName, language]);

  // Labels
  const streakLabel = trainingWelcomeText(language, "streakLabel");
  const masteredLabel = trainingWelcomeText(language, "masteredLabel");
  const timeLabel = trainingWelcomeText(language, "weekLabel");
  const dueLabel = trainingWelcomeText(language, "dueLabel");
  const startLabel = trainingWelcomeText(language, "startLabel");
  const reviewLabel = trainingWelcomeText(language, "reviewLabel");
  const continueLabel = trainingWelcomeText(language, "continueLabel");
  const noCardsDueLabel = trainingWelcomeText(language, "allDoneLabel");

  return (
    <div className="training-welcome-panel">
      <div className="welcome-header">
        <div className="welcome-text">
          <div className="welcome-greeting">{personalizedGreeting}</div>
          <div className={`welcome-motivation motivation--${motivation.type}`}>
            {motivation.message}
          </div>
        </div>
      </div>

      {/* Quick stats */}
      <div className="welcome-stats">
        <div className="welcome-stat">
          <FireIcon size={18} />
          <div className="stat-info">
            <div className="stat-value">{currentStreak}</div>
            <div className="stat-label">
              {streakLabel}
              <span className="stat-unit">{trainingWelcomeText(language, "dayUnit")}</span>
            </div>
          </div>
        </div>

        <div className="welcome-stat">
          <TrophyIcon size={18} />
          <div className="stat-info">
            <div className="stat-value">{cardsMastered}</div>
            <div className="stat-label">
              {masteredLabel}
              <span className="stat-unit">{trainingWelcomeText(language, "cardUnit")}</span>
            </div>
          </div>
        </div>

        <div className="welcome-stat">
          <TargetIcon size={18} />
          <div className="stat-info">
            <div className="stat-value">{formatTime(weeklyPracticeMinutes, language)}</div>
            <div className="stat-label">{timeLabel}</div>
          </div>
        </div>

        <div className="welcome-stat">
          <LightBulbIcon size={18} />
          <div className="stat-info">
            <div className="stat-value">{cardsDueToday}</div>
            <div className="stat-label">{dueLabel}</div>
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="welcome-progress">
        <div className="progress-label-row">
          <span className="progress-label">
            {trainingWelcomeText(language, "todayProgress")}
          </span>
          <span className="progress-value">{todayProgress}%</span>
        </div>
        <div className="progress-bar-track">
          <div
            className="progress-bar-fill"
            style={{ width: `${todayProgress}%` }}
          />
        </div>
      </div>

      {/* Action buttons */}
      <div className="welcome-actions">
        {cardsDueToday > 0 && onReviewCards && (
          <button
            className="welcome-action welcome-action--primary"
            onClick={onReviewCards}
            type="button"
          >
            <SparklesIcon size={16} />
            <span>
              {reviewLabel}
              <span className="action-badge">{cardsDueToday}</span>
            </span>
          </button>
        )}

        {cardsDueToday === 0 && onContinueLearning && (
          <button
            className="welcome-action welcome-action--secondary"
            onClick={onContinueLearning}
            type="button"
          >
            <LightBulbIcon size={16} />
            <span>{noCardsDueLabel}</span>
          </button>
        )}

        {onStartTraining && (
          <button
            className="welcome-action welcome-action--default"
            onClick={onStartTraining}
            type="button"
          >
            <ArrowRightIcon size={16} />
            <span>{startLabel}</span>
          </button>
        )}
      </div>

      {/* Next action hint */}
      {nextAction && (
        <div className="welcome-next-action">
          <div className="next-action-label">
            {trainingWelcomeText(language, "recommendedNext")}
          </div>
          <div className="next-action-content">
            <div className="next-action-title">{nextAction.label}</div>
            <div className="next-action-desc">{nextAction.description}</div>
          </div>
        </div>
      )}
    </div>
  );
};
