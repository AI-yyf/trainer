/**
 * TrainingMotivationPanel Component
 *
 * Displays compact training metrics and the next review entry point.
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §6.6
 */

import React from "react";
import { SparklesIcon, TrophyIcon, TargetIcon, FireIcon } from "../icons";
import {
  timeOfDayGreeting,
  trainingDurationCopy,
} from "./trainingPanelCopy";
import type { ComposerLanguage } from "../../lib/types";

export interface TrainingMotivationMetrics {
  /** Current streak - days of consistent practice */
  streak: number;
  /** Total cards mastered */
  cardsMastered: number;
  /** Practice time in minutes */
  practiceMinutes: number;
  /** Today's progress percentage (0-100) */
  todayProgress: number;
  /** Next review time */
  nextReviewTime: string;
  /** Encouraging message based on progress */
  encouragingMessage: string;
}

export interface TrainingMotivationPanelProps {
  /** Humanized metrics data */
  metrics: TrainingMotivationMetrics;
  /** Current language for localization */
  language: "zh-CN" | "en-US";
  /** Callback when user clicks to start training */
  onStartTraining?: () => void;
  /** Callback when user clicks streak info */
  onStreakClick?: () => void;
  /** Callback when user clicks progress */
  onProgressClick?: () => void;
}

type TrainingMotivationTextKey =
  | "streakLabel"
  | "masteredLabel"
  | "timeLabel"
  | "progressLabel"
  | "nextReviewLabel"
  | "startLabel"
  | "dayUnit"
  | "cardUnit";

/** §十五: motivation-panel labels in eight languages (no zh/en binary). */
const trainingMotivationTextCopy: Record<ComposerLanguage, Record<TrainingMotivationTextKey, string>> = {
  "zh-CN": {
    streakLabel: "连续练习",
    masteredLabel: "已掌握",
    timeLabel: "练习时长",
    progressLabel: "今日进度",
    nextReviewLabel: "下次复习",
    startLabel: "开始",
    dayUnit: "天",
    cardUnit: " 张",
  },
  "en-US": {
    streakLabel: "Streak",
    masteredLabel: "Mastered",
    timeLabel: "Practice time",
    progressLabel: "Today's progress",
    nextReviewLabel: "Next review",
    startLabel: "Start",
    dayUnit: " days",
    cardUnit: " cards",
  },
  "es-ES": {
    streakLabel: "Racha",
    masteredLabel: "Dominado",
    timeLabel: "Tiempo de práctica",
    progressLabel: "Progreso de hoy",
    nextReviewLabel: "Próxima revisión",
    startLabel: "Empezar",
    dayUnit: " días",
    cardUnit: " tarjetas",
  },
  "fr-FR": {
    streakLabel: "Série",
    masteredLabel: "Maîtrisé",
    timeLabel: "Temps de pratique",
    progressLabel: "Progrès du jour",
    nextReviewLabel: "Prochaine révision",
    startLabel: "Démarrer",
    dayUnit: " jours",
    cardUnit: " cartes",
  },
  "de-DE": {
    streakLabel: "Serie",
    masteredLabel: "Gemeistert",
    timeLabel: "Praxiszeit",
    progressLabel: "Fortschritt heute",
    nextReviewLabel: "Nächste Wiederholung",
    startLabel: "Start",
    dayUnit: " Tage",
    cardUnit: " Karten",
  },
  "ja-JP": {
    streakLabel: "連続練習",
    masteredLabel: "習得済み",
    timeLabel: "練習時間",
    progressLabel: "今日の進捗",
    nextReviewLabel: "次の復習",
    startLabel: "開始",
    dayUnit: "日",
    cardUnit: " 枚",
  },
  "ko-KR": {
    streakLabel: "연속 연습",
    masteredLabel: "습득 완료",
    timeLabel: "연습 시간",
    progressLabel: "오늘의 진행률",
    nextReviewLabel: "다음 복습",
    startLabel: "시작",
    dayUnit: "일",
    cardUnit: "장",
  },
  "pt-BR": {
    streakLabel: "Sequência",
    masteredLabel: "Dominado",
    timeLabel: "Tempo de prática",
    progressLabel: "Progresso de hoje",
    nextReviewLabel: "Próxima revisão",
    startLabel: "Iniciar",
    dayUnit: " dias",
    cardUnit: " cartões",
  },
};

function trainingMotivationText(language: ComposerLanguage, key: TrainingMotivationTextKey): string {
  return trainingMotivationTextCopy[language]?.[key] ?? trainingMotivationTextCopy["en-US"][key];
}

/**
 * Get time-based greeting based on current hour (hour bucketing stays here;
 * copy lives in the shared eight-language record).
 */
function getTimeBasedGreeting(hour: number, language: ComposerLanguage): string {
  return timeOfDayGreeting(hour, language);
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

export const TrainingMotivationPanel: React.FC<TrainingMotivationPanelProps> = ({
  metrics,
  language,
  onStartTraining,
  onStreakClick,
  onProgressClick,
}) => {
  const currentHour = new Date().getHours();
  const greeting = getTimeBasedGreeting(currentHour, language);

  const streakLabel = trainingMotivationText(language, "streakLabel");
  const masteredLabel = trainingMotivationText(language, "masteredLabel");
  const timeLabel = trainingMotivationText(language, "timeLabel");
  const progressLabel = trainingMotivationText(language, "progressLabel");
  const nextReviewLabel = trainingMotivationText(language, "nextReviewLabel");
  const startLabel = trainingMotivationText(language, "startLabel");

  const progressState = metrics.todayProgress >= 80
    ? "is-complete"
    : metrics.todayProgress >= 50
      ? "is-progress"
      : "is-start";

  return (
    <div className="training-motivation-panel">
      {/* Header with greeting */}
      <div className="motivation-header">
        <div className="motivation-greeting">
          <SparklesIcon size={16} />
          <span>{greeting}</span>
        </div>
        <div className="motivation-encouragement">
          {metrics.encouragingMessage}
        </div>
      </div>

      {/* Quick stats grid */}
      <div className="motivation-stats">
        {/* Streak stat */}
        <button
          className="motivation-stat motivation-stat--streak"
          onClick={onStreakClick}
          type="button"
          aria-label={streakLabel}
        >
          <div className="stat-icon">
            <FireIcon size={20} />
          </div>
          <div className="stat-content">
            <div className="stat-value">
              {metrics.streak}
              <span className="stat-unit">
                {trainingMotivationText(language, "dayUnit")}
              </span>
            </div>
            <div className="stat-label">{streakLabel}</div>
          </div>
        </button>

        {/* Mastered stat */}
        <div className="motivation-stat motivation-stat--mastered">
          <div className="stat-icon">
            <TrophyIcon size={20} />
          </div>
          <div className="stat-content">
            <div className="stat-value">
              {metrics.cardsMastered}
              <span className="stat-unit">
                {trainingMotivationText(language, "cardUnit")}
              </span>
            </div>
            <div className="stat-label">{masteredLabel}</div>
          </div>
        </div>

        {/* Time stat */}
        <div className="motivation-stat motivation-stat--time">
          <div className="stat-icon">
            <TargetIcon size={20} />
          </div>
          <div className="stat-content">
            <div className="stat-value">
              {formatTime(metrics.practiceMinutes, language)}
            </div>
            <div className="stat-label">{timeLabel}</div>
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <button
        className="motivation-progress"
        onClick={onProgressClick}
        type="button"
        aria-label={progressLabel}
      >
        <div className="progress-header">
          <span className="progress-label">{progressLabel}</span>
          <span className="progress-value">{metrics.todayProgress}%</span>
        </div>
        <div className="progress-bar">
          <div
            className={`progress-fill ${progressState}`}
            style={{
              width: `${metrics.todayProgress}%`,
            }}
          />
        </div>
      </button>

      {/* Next review time */}
      {metrics.nextReviewTime && (
        <div className="motivation-next-review">
          <span className="next-review-label">{nextReviewLabel}:</span>
          <span className="next-review-time">{metrics.nextReviewTime}</span>
        </div>
      )}

      {/* Start training button */}
      {onStartTraining && (
        <button
          className="motivation-start-button"
          onClick={onStartTraining}
          type="button"
        >
          <SparklesIcon size={16} />
          <span>{startLabel}</span>
        </button>
      )}
    </div>
  );
};
