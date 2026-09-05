/**
 * TrainingMotivationPanel Component
 *
 * Displays compact training metrics and the next review entry point.
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §6.6
 */

import React from "react";
import { SparklesIcon, TrophyIcon, TargetIcon, FireIcon } from "../icons";

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

/**
 * Get time-based greeting based on current hour
 */
function getTimeBasedGreeting(hour: number, language: "zh-CN" | "en-US"): string {
  if (hour < 6) {
    return language === "zh-CN" ? "夜间" : "Late night";
  }
  if (hour < 9) {
    return language === "zh-CN" ? "清晨" : "Early morning";
  }
  if (hour < 12) {
    return language === "zh-CN" ? "上午" : "Morning";
  }
  if (hour < 14) {
    return language === "zh-CN" ? "午间" : "Noon";
  }
  if (hour < 18) {
    return language === "zh-CN" ? "下午" : "Afternoon";
  }
  if (hour < 21) {
    return language === "zh-CN" ? "晚上" : "Evening";
  }
  return language === "zh-CN" ? "夜间" : "Night";
}

function formatTime(minutes: number, language: "zh-CN" | "en-US"): string {
  if (minutes < 60) {
    return language === "zh-CN" ? `${minutes} 分钟` : `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (mins === 0) {
    return language === "zh-CN" ? `${hours} 小时` : `${hours} hr`;
  }
  return language === "zh-CN" ? `${hours}h ${mins}m` : `${hours}hr ${mins}min`;
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

  const streakLabel = language === "zh-CN" ? "连续练习" : "Streak";
  const masteredLabel = language === "zh-CN" ? "已掌握" : "Mastered";
  const timeLabel = language === "zh-CN" ? "练习时长" : "Practice time";
  const progressLabel = language === "zh-CN" ? "今日进度" : "Today's progress";
  const nextReviewLabel = language === "zh-CN" ? "下次复习" : "Next review";
  const startLabel = language === "zh-CN" ? "开始" : "Start";

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
                {language === "zh-CN" ? "天" : " days"}
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
                {language === "zh-CN" ? " 张" : " cards"}
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
