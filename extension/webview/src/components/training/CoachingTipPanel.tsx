/**
 * CoachingTipPanel Component
 *
 * Displays contextual coaching tips based on:
 * - Current learning context
 * - Recent mistakes or patterns
 * - User's learning style
 * - Time of day and practice patterns
 *
 * Tips are designed to be actionable, not generic motivational quotes.
 *
 * Reference: docs/open-source-fit-and-provider-strategy.md §6.6 (teaching interaction)
 */

import React, { useMemo } from "react";
import { LightBulbIcon, ArrowRightIcon } from "../icons";

export interface CoachingTip {
  id: string;
  title: string;
  content: string;
  category: "technique" | "mindset" | "habit" | "pattern" | "strategy";
  actionLabel?: string;
  actionHint?: string;
  relevanceScore?: number;
}

export interface CoachingTipPanelProps {
  /** Current language */
  language: "zh-CN" | "en-US";
  /** Current tip to display */
  tip?: CoachingTip;
  /** Available tips for this context */
  availableTips?: CoachingTip[];
  /** Current streak to personalize tips */
  currentStreak?: number;
  /** Recent performance pattern */
  recentPattern?: {
    successRate: number;
    averageTime: number;
    streakGrowth: number;
  };
  /** Callback when user dismisses tip */
  onDismissTip?: (tipId: string) => void;
  /** Callback when user wants next tip */
  onNextTip?: () => void;
  /** Callback when user clicks action */
  onTipAction?: (tipId: string) => void;
}

/**
 * Get contextual tip based on learning patterns
 */
function selectBestTip(
  availableTips: CoachingTip[] | undefined,
  recentPattern: { successRate: number; averageTime: number; streakGrowth: number } | undefined,
  language: "zh-CN" | "en-US"
): CoachingTip | undefined {
  if (!availableTips || availableTips.length === 0) {
    return undefined;
  }

  // Score and sort tips by relevance
  const scoredTips = availableTips.map((tip) => {
    let score = tip.relevanceScore ?? 50;

    // Boost technique tips for low success rate
    if (recentPattern && recentPattern.successRate < 0.6 && tip.category === "technique") {
      score += 30;
    }

    // Boost mindset tips for declining streak
    if (recentPattern && recentPattern.streakGrowth < 0 && tip.category === "mindset") {
      score += 25;
    }

    // Boost habit tips for new learners
    if (recentPattern && recentPattern.streakGrowth < 7 && tip.category === "habit") {
      score += 20;
    }

    // Boost strategy tips for consistent performers
    if (recentPattern && recentPattern.successRate > 0.8 && tip.category === "strategy") {
      score += 15;
    }

    return { tip, score };
  });

  scoredTips.sort((a, b) => b.score - a.score);
  return scoredTips[0].tip;
}

/**
 * Get category color and label
 */
function getCategoryStyle(
  category: CoachingTip["category"],
  language: "zh-CN" | "en-US"
): { label: string; icon: string } {
  const styles: Record<CoachingTip["category"], { label: string; icon: string }> = {
    technique: {
      label: language === "zh-CN" ? "技巧" : "Technique",
      icon: "T",
    },
    mindset: {
      label: language === "zh-CN" ? "心态" : "Mindset",
      icon: "M",
    },
    habit: {
      label: language === "zh-CN" ? "习惯" : "Habit",
      icon: "H",
    },
    pattern: {
      label: language === "zh-CN" ? "模式" : "Pattern",
      icon: "P",
    },
    strategy: {
      label: language === "zh-CN" ? "策略" : "Strategy",
      icon: "S",
    },
  };
  return styles[category];
}

export const CoachingTipPanel: React.FC<CoachingTipPanelProps> = ({
  language,
  tip,
  availableTips,
  currentStreak = 0,
  recentPattern,
  onDismissTip,
  onNextTip,
  onTipAction,
}) => {
  const selectedTip = useMemo(
    () => tip ?? selectBestTip(availableTips, recentPattern, language),
    [tip, availableTips, recentPattern, language]
  );

  const categoryStyle = selectedTip
    ? getCategoryStyle(selectedTip.category, language)
    : null;

  const dismissLabel = language === "zh-CN" ? "收起" : "Dismiss";
  const nextLabel = language === "zh-CN" ? "下一条" : "Next";

  if (!selectedTip) {
    return null;
  }

  return (
    <div className="coaching-tip-panel">
      {/* Header with category */}
      <div className="tip-header">
        <div className={`tip-category tip-category--${selectedTip.category}`}>
          <span className="category-icon">{categoryStyle?.icon}</span>
          <span className="category-label">{categoryStyle?.label}</span>
        </div>
        {availableTips && availableTips.length > 1 && onNextTip && (
          <button
            className="tip-nav-button"
            onClick={onNextTip}
            type="button"
            aria-label={nextLabel}
          >
            <ArrowRightIcon size={14} />
          </button>
        )}
      </div>

      {/* Tip content */}
      <div className="tip-content">
        <div className="tip-icon">
          <LightBulbIcon size={20} />
        </div>
        <div className="tip-text">
          <div className="tip-title">{selectedTip.title}</div>
          <div className="tip-body">{selectedTip.content}</div>
        </div>
      </div>

      {/* Action area */}
      {(selectedTip.actionLabel || onDismissTip) && (
        <div className="tip-actions">
          {selectedTip.actionLabel && onTipAction && (
            <button
              className="tip-action-button"
              onClick={() => onTipAction(selectedTip.id)}
              type="button"
            >
              <span>{selectedTip.actionLabel}</span>
              {selectedTip.actionHint && (
                <span className="action-hint">{selectedTip.actionHint}</span>
              )}
            </button>
          )}
          {onDismissTip && (
            <button
              className="tip-dismiss-button"
              onClick={() => onDismissTip(selectedTip.id)}
              type="button"
            >
              {dismissLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
};
