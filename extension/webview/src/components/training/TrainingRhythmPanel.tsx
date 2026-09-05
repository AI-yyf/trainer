/**
 * TrainingRhythmPanel Component
 *
 * Visualizes the spaced repetition schedule to help learners:
 * - See upcoming review times
 * - Understand the learning rhythm
 * - Plan their practice sessions
 *
 * Based on FSRS principles but presented in a humanized way.
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §6.6, §6.8 (FSRS integration)
 */

import React, { useMemo } from "react";

export interface ReviewSlot {
  /** When this review is due */
  dueAt: Date;
  /** Number of cards due */
  cardCount: number;
  /** Type of cards in this slot */
  type: "new" | "learning" | "review";
  /** Estimated time in minutes */
  estimatedMinutes: number;
}

export interface TrainingRhythmPanelProps {
  /** Current language */
  language: "zh-CN" | "en-US";
  /** Today's review schedule */
  todaySlots?: ReviewSlot[];
  /** This week's schedule */
  weekSlots?: ReviewSlot[];
  /** Current streak */
  currentStreak: number;
  /** Optimal daily goal for reviews */
  dailyGoal?: number;
  /** Whether this is a "good day" to train */
  isGoodDay?: boolean;
  /** Callback when user clicks to view schedule */
  onViewSchedule?: () => void;
  /** Callback when user clicks on a specific slot */
  onSlotClick?: (slot: ReviewSlot) => void;
}

/**
 * Get time period label
 */
function getTimePeriodLabel(
  slot: ReviewSlot,
  language: "zh-CN" | "en-US"
): string {
  const hour = slot.dueAt.getHours();
  const minute = slot.dueAt.getMinutes();
  const timeStr = `${hour}:${minute.toString().padStart(2, "0")}`;

  if (language === "zh-CN") {
    if (hour < 6) return `凌晨 ${timeStr}`;
    if (hour < 9) return `早晨 ${timeStr}`;
    if (hour < 12) return `上午 ${timeStr}`;
    if (hour < 14) return `中午 ${timeStr}`;
    if (hour < 18) return `下午 ${timeStr}`;
    if (hour < 21) return `傍晚 ${timeStr}`;
    return `晚上 ${timeStr}`;
  }

  if (hour < 6) return `Late night ${timeStr}`;
  if (hour < 9) return `Morning ${timeStr}`;
  if (hour < 12) return `Late morning ${timeStr}`;
  if (hour < 14) return `Noon ${timeStr}`;
  if (hour < 18) return `Afternoon ${timeStr}`;
  if (hour < 21) return `Evening ${timeStr}`;
  return `Night ${timeStr}`;
}

/**
 * Get card type label
 */
function getCardTypeInfo(
  type: ReviewSlot["type"],
  language: "zh-CN" | "en-US"
): { label: string } {
  const info: Record<ReviewSlot["type"], { label: string }> = {
    new: {
      label: language === "zh-CN" ? "新卡片" : "New",
    },
    learning: {
      label: language === "zh-CN" ? "学习中" : "Learning",
    },
    review: {
      label: language === "zh-CN" ? "复习" : "Review",
    },
  };
  return info[type];
}

function formatTime(minutes: number, language: "zh-CN" | "en-US"): string {
  if (minutes < 1) {
    return language === "zh-CN" ? "<1 分钟" : "<1 min";
  }
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

export const TrainingRhythmPanel: React.FC<TrainingRhythmPanelProps> = ({
  language,
  todaySlots = [],
  weekSlots = [],
  currentStreak,
  dailyGoal = 20,
  isGoodDay = true,
  onViewSchedule,
  onSlotClick,
}) => {
  // Calculate today's stats
  const todayStats = useMemo(() => {
    const totalCards = todaySlots.reduce((sum, slot) => sum + slot.cardCount, 0);
    const totalTime = todaySlots.reduce((sum, slot) => sum + slot.estimatedMinutes, 0);
    return { totalCards, totalTime };
  }, [todaySlots]);

  // Sort slots by time
  const sortedTodaySlots = useMemo(
    () => [...todaySlots].sort((a, b) => a.dueAt.getTime() - b.dueAt.getTime()),
    [todaySlots]
  );

  // Labels
  const titleLabel = language === "zh-CN" ? "复习节奏" : "Review Rhythm";
  const todayLabel = language === "zh-CN" ? "今日安排" : "Today's Schedule";
  const streakLabel = language === "zh-CN" ? "连续" : "Streak";
  const goalLabel = language === "zh-CN" ? "目标" : "Goal";
  const cardsLabel = language === "zh-CN" ? "张卡片" : "cards";
  const viewScheduleLabel = language === "zh-CN" ? "完整日程" : "Full schedule";
  const noSlotsLabel = language === "zh-CN" ? "今天没有待复习的内容" : "No reviews scheduled today";
  const goodDayLabel = language === "zh-CN" ? "今日可练" : "Ready today";
  const missedDayLabel = language === "zh-CN" ? "有待复习" : "Review overdue";

  // Determine if user is on track
  const progressPercent = Math.min(100, (todayStats.totalCards / dailyGoal) * 100);
  const isOnTrack = progressPercent >= 50;
  const isAhead = progressPercent >= 100;

  return (
    <div className="training-rhythm-panel">
      {/* Header */}
      <div className="rhythm-header">
        <div className="rhythm-title">{titleLabel}</div>
        <div className="rhythm-day-status">
          {isGoodDay ? (
            <span className="day-status day-status--good">{goodDayLabel}</span>
          ) : (
            <span className="day-status day-status--missed">{missedDayLabel}</span>
          )}
        </div>
      </div>

      {/* Quick stats row */}
      <div className="rhythm-stats-row">
        <div className="rhythm-stat">
          <span className="stat-value">{currentStreak}</span>
          <span className="stat-unit">{streakLabel}</span>
        </div>
        <div className="rhythm-stat">
          <span className="stat-value">{todayStats.totalCards}</span>
          <span className="stat-unit">{cardsLabel}</span>
        </div>
        <div className="rhythm-stat">
          <span className="stat-value">{formatTime(todayStats.totalTime, language)}</span>
          <span className="stat-unit">{goalLabel}</span>
        </div>
      </div>

      {/* Progress indicator */}
      <div className="rhythm-progress">
        <div className="progress-track">
          <div
            className={`progress-indicator ${
              isAhead ? "is-ahead" : isOnTrack ? "is-on-track" : "is-behind"
            }`}
            style={{ width: `${Math.min(100, progressPercent)}%` }}
          />
          {dailyGoal && (
            <div
              className="goal-marker"
              style={{ left: `${Math.min(100, (dailyGoal / Math.max(todayStats.totalCards, dailyGoal)) * 100)}%` }}
            />
          )}
        </div>
        <div className="progress-labels">
          <span className="progress-current">{todayStats.totalCards} / {dailyGoal}</span>
          <span className="progress-percent">{Math.round(progressPercent)}%</span>
        </div>
      </div>

      {/* Today's schedule */}
      <div className="rhythm-schedule">
        <div className="schedule-header">
          <span className="schedule-title">{todayLabel}</span>
          {onViewSchedule && (
            <button
              className="schedule-view-button"
              onClick={onViewSchedule}
              type="button"
            >
              {viewScheduleLabel}
            </button>
          )}
        </div>

        {sortedTodaySlots.length === 0 ? (
          <div className="schedule-empty">{noSlotsLabel}</div>
        ) : (
          <div className="schedule-slots">
            {sortedTodaySlots.map((slot, index) => {
              const typeInfo = getCardTypeInfo(slot.type, language);
              return (
                <button
                  key={index}
                  className="schedule-slot"
                  onClick={() => onSlotClick?.(slot)}
                  type="button"
                >
                  <div className={`slot-dot slot-dot--${slot.type}`} />
                  <div className="slot-time">{getTimePeriodLabel(slot, language)}</div>
                  <div className="slot-count">
                    {slot.cardCount}
                    <span className={`slot-type slot-type--${slot.type}`}>
                      {typeInfo.label}
                    </span>
                  </div>
                  <div className="slot-duration">
                    {formatTime(slot.estimatedMinutes, language)}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Week overview (condensed) */}
      {weekSlots.length > 0 && (
        <div className="rhythm-week">
          <div className="week-label">{language === "zh-CN" ? "本周" : "This week"}</div>
          <div className="week-dots">
            {weekSlots.slice(0, 7).map((slot, index) => {
              const intensity = Math.min(1, slot.cardCount / 30);
              return (
                <div
                  key={index}
                  className={`week-dot ${intensity > 0.7 ? "week-dot--heavy" : "week-dot--normal"}`}
                  style={{
                    opacity: 0.3 + intensity * 0.7,
                  }}
                  title={`${slot.dueAt.toLocaleDateString()}: ${slot.cardCount} ${cardsLabel}`}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
