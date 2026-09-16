/**
 * Shared motivation copy for learning-home surfaces.
 *
 * Extracted from TrainingWelcomePanel (batch 3) so the plan view's learning
 * overview and the training welcome panel render identical encouragement
 * from one source.
 */

export type MotivationLanguage = "zh-CN" | "en-US";

export type MotivationMessageType = "celebration" | "encouragement" | "reminder" | "challenge";

export interface MotivationalMessage {
  message: string;
  type: MotivationMessageType;
}

/**
 * Motivational message based on the learner's progress state. Falls through
 * to honest zero-state copy when streak/mastered data is not available.
 */
export function getMotivationalMessage(
  currentStreak: number,
  cardsMastered: number,
  todayProgress: number,
  cardsDueToday: number,
  language: MotivationLanguage,
): MotivationalMessage {
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
