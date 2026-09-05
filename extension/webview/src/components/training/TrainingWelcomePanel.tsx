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
import {
  SparklesIcon,
  TrophyIcon,
  TargetIcon,
  FireIcon,
  LightBulbIcon,
  ArrowRightIcon,
} from "../icons";

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
 * Get time-based greeting message
 */
function getTimeGreeting(hour: number, language: "zh-CN" | "en-US"): { greeting: string } {
  if (hour < 6) {
    return {
      greeting: language === "zh-CN" ? "夜间" : "Late night",
    };
  }
  if (hour < 9) {
    return {
      greeting: language === "zh-CN" ? "清晨" : "Early morning",
    };
  }
  if (hour < 12) {
    return {
      greeting: language === "zh-CN" ? "上午" : "Morning",
    };
  }
  if (hour < 14) {
    return {
      greeting: language === "zh-CN" ? "午间" : "Noon",
    };
  }
  if (hour < 18) {
    return {
      greeting: language === "zh-CN" ? "下午" : "Afternoon",
    };
  }
  if (hour < 21) {
    return {
      greeting: language === "zh-CN" ? "晚上" : "Evening",
    };
  }
  return {
    greeting: language === "zh-CN" ? "夜间" : "Night",
  };
}

/**
 * Get motivational message based on user's progress state
 */
function getMotivationalMessage(
  currentStreak: number,
  cardsMastered: number,
  todayProgress: number,
  cardsDueToday: number,
  language: "zh-CN" | "en-US"
): { message: string; type: "celebration" | "encouragement" | "reminder" | "challenge" } {
  // Celebration states
  if (currentStreak >= 7 && todayProgress >= 80) {
    return {
      message: language === "zh-CN"
        ? "连续 7 天练习。"
        : "7-day streak.",
      type: "celebration",
    };
  }
  if (currentStreak >= 30) {
    return {
      message: language === "zh-CN"
        ? "连续练习 1 个月。"
        : "One-month streak.",
      type: "celebration",
    };
  }
  if (cardsMastered >= 50) {
    return {
      message: language === "zh-CN"
        ? "已掌握 50+ 张卡片。"
        : "50+ cards mastered.",
      type: "celebration",
    };
  }

  // Encouragement states
  if (currentStreak >= 3) {
    return {
      message: language === "zh-CN"
        ? `连续 ${currentStreak} 天。`
        : `${currentStreak}-day streak.`,
      type: "encouragement",
    };
  }
  if (todayProgress >= 50) {
    return {
      message: language === "zh-CN"
        ? "今天进度过半。"
        : "Halfway today.",
      type: "encouragement",
    };
  }
  if (cardsDueToday === 0) {
    return {
      message: language === "zh-CN"
        ? "今天没有待复习卡片。"
        : "No cards due today.",
      type: "encouragement",
    };
  }

  // Reminder states
  if (cardsDueToday > 5) {
    return {
      message: language === "zh-CN"
        ? `${cardsDueToday} 张卡片待复习。`
        : `${cardsDueToday} cards waiting for review.`,
      type: "reminder",
    };
  }
  if (cardsDueToday > 0) {
    return {
      message: language === "zh-CN"
        ? `${cardsDueToday} 张卡片待复习。`
        : `${cardsDueToday} cards to review.`,
      type: "reminder",
    };
  }

  // Default challenge
  return {
    message: language === "zh-CN"
      ? "开始今天的训练。"
      : "Start today's training.",
    type: "challenge",
  };
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
      return language === "zh-CN"
        ? `${baseGreeting}，${learnerName}`
        : `${baseGreeting}, ${learnerName}`;
    }
    return baseGreeting;
  }, [timeGreeting, learnerName, language]);

  // Labels
  const streakLabel = language === "zh-CN" ? "连续练习" : "Streak";
  const masteredLabel = language === "zh-CN" ? "已掌握" : "Mastered";
  const timeLabel = language === "zh-CN" ? "本周练习" : "This week";
  const dueLabel = language === "zh-CN" ? "待复习" : "Due";
  const startLabel = language === "zh-CN" ? "开始" : "Start";
  const reviewLabel = language === "zh-CN" ? "复习" : "Review";
  const continueLabel = language === "zh-CN" ? "继续学习" : "Continue";
  const noCardsDueLabel = language === "zh-CN" ? "今日已完成" : "All done today";

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
              <span className="stat-unit">{language === "zh-CN" ? "天" : " days"}</span>
            </div>
          </div>
        </div>

        <div className="welcome-stat">
          <TrophyIcon size={18} />
          <div className="stat-info">
            <div className="stat-value">{cardsMastered}</div>
            <div className="stat-label">
              {masteredLabel}
              <span className="stat-unit">{language === "zh-CN" ? " 张" : " cards"}</span>
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
            {language === "zh-CN" ? "今日进度" : "Today's Progress"}
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
            {language === "zh-CN" ? "推荐下一步" : "Recommended Next"}
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
