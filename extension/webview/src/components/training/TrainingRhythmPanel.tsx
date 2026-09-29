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
import {
  timeOfDayPeriodPrefix,
  trainingDurationCopy,
} from "./trainingPanelCopy";
import type { ComposerLanguage } from "../../lib/types";

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

type TrainingRhythmTextKey =
  | "titleLabel"
  | "todayLabel"
  | "streakLabel"
  | "goalLabel"
  | "cardsLabel"
  | "viewScheduleLabel"
  | "noSlotsLabel"
  | "goodDayLabel"
  | "missedDayLabel"
  | "weekLabel"
  | "newCardLabel"
  | "learningCardLabel"
  | "reviewCardLabel";

/** §十五: rhythm-panel labels in eight languages (no zh/en binary). */
const trainingRhythmTextCopy: Record<ComposerLanguage, Record<TrainingRhythmTextKey, string>> = {
  "zh-CN": {
    titleLabel: "复习节奏",
    todayLabel: "今日安排",
    streakLabel: "连续",
    goalLabel: "目标",
    cardsLabel: "张卡片",
    viewScheduleLabel: "完整日程",
    noSlotsLabel: "今天没有待复习的内容",
    goodDayLabel: "今日可练",
    missedDayLabel: "有待复习",
    weekLabel: "本周",
    newCardLabel: "新卡片",
    learningCardLabel: "学习中",
    reviewCardLabel: "复习",
  },
  "en-US": {
    titleLabel: "Review Rhythm",
    todayLabel: "Today's Schedule",
    streakLabel: "Streak",
    goalLabel: "Goal",
    cardsLabel: "cards",
    viewScheduleLabel: "Full schedule",
    noSlotsLabel: "No reviews scheduled today",
    goodDayLabel: "Ready today",
    missedDayLabel: "Review overdue",
    weekLabel: "This week",
    newCardLabel: "New",
    learningCardLabel: "Learning",
    reviewCardLabel: "Review",
  },
  "es-ES": {
    titleLabel: "Ritmo de repaso",
    todayLabel: "Agenda de hoy",
    streakLabel: "Racha",
    goalLabel: "Meta",
    cardsLabel: "tarjetas",
    viewScheduleLabel: "Agenda completa",
    noSlotsLabel: "Hoy no hay repasos programados",
    goodDayLabel: "Listo para hoy",
    missedDayLabel: "Repasos pendientes",
    weekLabel: "Esta semana",
    newCardLabel: "Nueva",
    learningCardLabel: "Aprendiendo",
    reviewCardLabel: "Repaso",
  },
  "fr-FR": {
    titleLabel: "Rythme de révision",
    todayLabel: "Programme du jour",
    streakLabel: "Série",
    goalLabel: "Objectif",
    cardsLabel: "cartes",
    viewScheduleLabel: "Programme complet",
    noSlotsLabel: "Aucune révision programmée aujourd'hui",
    goodDayLabel: "Prêt aujourd'hui",
    missedDayLabel: "Révisions en retard",
    weekLabel: "Cette semaine",
    newCardLabel: "Nouvelle",
    learningCardLabel: "En apprentissage",
    reviewCardLabel: "Révision",
  },
  "de-DE": {
    titleLabel: "Wiederholungsrhythmus",
    todayLabel: "Heutiger Plan",
    streakLabel: "Serie",
    goalLabel: "Ziel",
    cardsLabel: "Karten",
    viewScheduleLabel: "Gesamter Plan",
    noSlotsLabel: "Heute sind keine Wiederholungen geplant",
    goodDayLabel: "Heute bereit",
    missedDayLabel: "Wiederholungen überfällig",
    weekLabel: "Diese Woche",
    newCardLabel: "Neu",
    learningCardLabel: "Lernen",
    reviewCardLabel: "Wiederholung",
  },
  "ja-JP": {
    titleLabel: "復習リズム",
    todayLabel: "今日の予定",
    streakLabel: "連続",
    goalLabel: "目標",
    cardsLabel: "枚のカード",
    viewScheduleLabel: "全スケジュール",
    noSlotsLabel: "今日は復習予定がありません",
    goodDayLabel: "今日は練習可能",
    missedDayLabel: "復習が残っています",
    weekLabel: "今週",
    newCardLabel: "新規",
    learningCardLabel: "学習中",
    reviewCardLabel: "復習",
  },
  "ko-KR": {
    titleLabel: "복습 리듬",
    todayLabel: "오늘 일정",
    streakLabel: "연속",
    goalLabel: "목표",
    cardsLabel: "장의 카드",
    viewScheduleLabel: "전체 일정",
    noSlotsLabel: "오늘 예정된 복습이 없습니다",
    goodDayLabel: "오늘 연습 가능",
    missedDayLabel: "복습이 밀렸습니다",
    weekLabel: "이번 주",
    newCardLabel: "새 카드",
    learningCardLabel: "학습 중",
    reviewCardLabel: "복습",
  },
  "pt-BR": {
    titleLabel: "Ritmo de revisão",
    todayLabel: "Programação de hoje",
    streakLabel: "Sequência",
    goalLabel: "Meta",
    cardsLabel: "cartões",
    viewScheduleLabel: "Programação completa",
    noSlotsLabel: "Sem revisões programadas hoje",
    goodDayLabel: "Pronto hoje",
    missedDayLabel: "Revisões pendentes",
    weekLabel: "Esta semana",
    newCardLabel: "Nova",
    learningCardLabel: "Aprendendo",
    reviewCardLabel: "Revisão",
  },
};

function trainingRhythmText(language: ComposerLanguage, key: TrainingRhythmTextKey): string {
  return trainingRhythmTextCopy[language]?.[key] ?? trainingRhythmTextCopy["en-US"][key];
}

/**
 * Get time period label (hour bucketing stays here; the period prefix copy
 * lives in the shared eight-language record).
 */
function getTimePeriodLabel(
  slot: ReviewSlot,
  language: ComposerLanguage
): string {
  const hour = slot.dueAt.getHours();
  const minute = slot.dueAt.getMinutes();
  const timeStr = `${hour}:${minute.toString().padStart(2, "0")}`;
  return `${timeOfDayPeriodPrefix(hour, language)} ${timeStr}`;
}

/**
 * Get card type label
 */
function getCardTypeInfo(
  type: ReviewSlot["type"],
  language: ComposerLanguage
): { label: string } {
  const info: Record<ReviewSlot["type"], { label: string }> = {
    new: {
      label: trainingRhythmText(language, "newCardLabel"),
    },
    learning: {
      label: trainingRhythmText(language, "learningCardLabel"),
    },
    review: {
      label: trainingRhythmText(language, "reviewCardLabel"),
    },
  };
  return info[type];
}

function formatTime(minutes: number, language: ComposerLanguage): string {
  const duration = trainingDurationCopy(language);
  if (minutes < 1) {
    return duration.underMinute;
  }
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
  const titleLabel = trainingRhythmText(language, "titleLabel");
  const todayLabel = trainingRhythmText(language, "todayLabel");
  const streakLabel = trainingRhythmText(language, "streakLabel");
  const goalLabel = trainingRhythmText(language, "goalLabel");
  const cardsLabel = trainingRhythmText(language, "cardsLabel");
  const viewScheduleLabel = trainingRhythmText(language, "viewScheduleLabel");
  const noSlotsLabel = trainingRhythmText(language, "noSlotsLabel");
  const goodDayLabel = trainingRhythmText(language, "goodDayLabel");
  const missedDayLabel = trainingRhythmText(language, "missedDayLabel");

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
          <div className="week-label">{trainingRhythmText(language, "weekLabel")}</div>
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
