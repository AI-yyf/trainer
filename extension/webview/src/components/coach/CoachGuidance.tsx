/**
 * Coach Guidance System - Contextual, humanized coaching feedback
 *
 * Provides compact status and next-step feedback for the current view.
 */

import type { ReactNode } from "react";

export interface CoachGuidanceConfig {
  language: "zh-CN" | "en-US";
  currentView: "coach" | "plan" | "training" | "resources" | "settings";
  hasProviderSetup: boolean;
  hasConversation: boolean;
  hasActivePlan: boolean;
  hasTrainingCards: boolean;
  hasResources: boolean;
  recentMistakes?: string[];
  recentWins?: string[];
  streak?: number;
  dueReviews?: number;
  masteredCards?: number;
  totalPracticeTime?: number; // in minutes
}

export interface GuidanceItem {
  id: string;
  icon?: ReactNode;
  title: string;
  description: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  dismissible: boolean;
  priority: number;
  tone?: "info" | "success" | "warning" | "encouragement";
}

/**
 * Motivational messages for different streaks and progress states
 */
const STREAK_MESSAGES = {
  "zh-CN": {
    none: "今天还没有练习",
    beginning: "练习已开始",
    building: "坚持训练，习惯正在养成",
    strong: "你已经建立了训练节奏！",
    excellent: "你的坚持正在产生效果",
    expert: "训练节奏很稳",
  },
  "en-US": {
    none: "No practice yet today",
    beginning: "Practice started",
    building: "Keep training, habits are forming",
    strong: "You've built a training rhythm!",
    excellent: "Your consistency is showing results",
    expert: "Training rhythm is steady",
  },
};

const REVIEW_MESSAGES = {
  "zh-CN": {
    none: "没有待复习的卡片，休息一下或者挑战新内容",
    few: "{n} 张卡片等待复习，保持记忆不丢失",
    some: "你有 {n} 张卡片需要复习，坚持就是胜利",
    many: "复习队列较长，逐一击破会更有成就感",
  },
  "en-US": {
    none: "No cards due for review. Take a break or challenge something new",
    few: "{n} card{s} waiting for review, keep that memory fresh",
    some: "You have {n} card{s} to review. Persistence wins",
    many: "Review queue is long. Conquer them one by one for a real sense of achievement",
  },
};

/**
 * Get streak-level message
 */
function getStreakMessage(language: "zh-CN" | "en-US", streak: number): string {
  const isZh = language === "zh-CN";
  if (streak === 0) {
    return isZh ? STREAK_MESSAGES["zh-CN"].none : STREAK_MESSAGES["en-US"].none;
  }
  if (streak <= 3) {
    return isZh ? STREAK_MESSAGES["zh-CN"].beginning : STREAK_MESSAGES["en-US"].beginning;
  }
  if (streak <= 7) {
    return isZh ? STREAK_MESSAGES["zh-CN"].building : STREAK_MESSAGES["en-US"].building;
  }
  if (streak <= 14) {
    return isZh ? STREAK_MESSAGES["zh-CN"].strong : STREAK_MESSAGES["en-US"].strong;
  }
  if (streak <= 30) {
    return isZh ? STREAK_MESSAGES["zh-CN"].excellent : STREAK_MESSAGES["en-US"].excellent;
  }
  return isZh ? STREAK_MESSAGES["zh-CN"].expert : STREAK_MESSAGES["en-US"].expert;
}

/**
 * Get review queue message
 */
function getReviewMessage(language: "zh-CN" | "en-US", dueCount: number): string {
  const isZh = language === "zh-CN";
  const msg = isZh ? REVIEW_MESSAGES["zh-CN"] : REVIEW_MESSAGES["en-US"];
  const plural = dueCount !== 1 ? (isZh ? "s" : "s") : "";

  if (dueCount === 0) {
    return msg.none;
  }
  if (dueCount <= 3) {
    return msg.few.replace("{n}", String(dueCount)).replace("{s}", plural);
  }
  if (dueCount <= 10) {
    return msg.some.replace("{n}", String(dueCount)).replace("{s}", plural);
  }
  return msg.many;
}

/**
 * Time-based greeting that feels natural
 */
function getTimeBasedGreeting(language: "zh-CN" | "en-US", hour?: number): string {
  const isZh = language === "zh-CN";
  const h = hour ?? new Date().getHours();

  if (h < 5) {
    return isZh ? "夜间" : "Late night";
  }
  if (h < 9) {
    return isZh ? "清晨" : "Early morning";
  }
  if (h < 12) {
    return isZh ? "上午" : "Morning";
  }
  if (h < 14) {
    return isZh ? "午间" : "Noon";
  }
  if (h < 18) {
    return isZh ? "下午" : "Afternoon";
  }
  if (h < 21) {
    return isZh ? "晚上" : "Evening";
  }
  return isZh ? "夜间" : "Late night";
}

/**
 * Get contextual guidance based on current state
 */
export function getContextualGuidance(config: CoachGuidanceConfig): GuidanceItem[] {
  const {
    language,
    currentView,
    hasProviderSetup,
    hasConversation,
    hasActivePlan,
    hasTrainingCards,
    hasResources,
    recentMistakes = [],
    recentWins = [],
    streak = 0,
    dueReviews = 0,
    masteredCards = 0,
    totalPracticeTime = 0,
  } = config;

  const isZh = language === "zh-CN";
  const guidance: GuidanceItem[] = [];

  // Time-based greeting (low priority, always available)
  guidance.push({
    id: "time-greeting",
    title: getTimeBasedGreeting(language),
    description: getStreakMessage(language, streak),
    priority: 100,
    dismissible: true,
    tone: "encouragement",
  });

  // Welcome guidance for new users
  if (!hasProviderSetup) {
    guidance.push({
      id: "setup-provider",
      title: isZh ? "第一步：连接模型" : "Step 1: Connect a model",
      description: isZh
        ? "填写 provider、模型和 API key。"
        : "Set provider, model, and API key.",
      priority: 1,
      dismissible: false,
      tone: "info",
    });
    return guidance;
  }

  // Welcome back for returning users
  if (hasConversation && !hasActivePlan) {
    guidance.push({
      id: "create-plan",
      title: isZh ? "创建一个训练计划" : "Create a training plan",
      description: isZh
        ? "告诉我目标或当前项目。"
        : "Share a goal or current project.",
      priority: 2,
      dismissible: true,
      tone: "info",
    });
  }

  // Plan-based guidance
  if (hasActivePlan) {
    if (!hasTrainingCards) {
      guidance.push({
        id: "generate-training",
      title: isZh ? "生成训练卡片" : "Generate training cards",
      description: isZh
          ? "问一个具体问题开始。"
          : "Ask one specific question to begin.",
        priority: 3,
        dismissible: true,
        tone: "info",
      });
    }

    // Encourage practice based on due reviews
    if (dueReviews > 0) {
      guidance.push({
        id: "review-due",
        title: isZh ? "复习提醒" : "Review reminder",
        description: getReviewMessage(language, dueReviews),
        priority: 4,
        dismissible: true,
        tone: "warning",
      });
    } else if (hasTrainingCards) {
      guidance.push({
        id: "practice-ready",
        title: isZh ? "可以继续练习" : "Ready to practice",
        description: isZh
          ? "今天的复习已完成。"
          : "Today's reviews are complete.",
        priority: 5,
        dismissible: true,
        tone: "success",
      });
    }
  }

  // Resources guidance
  if (currentView === "resources" && !hasResources) {
    guidance.push({
      id: "add-resources",
      title: isZh ? "添加学习资料" : "Add learning materials",
      description: isZh
        ? "导入代码、文档或网页。"
        : "Import code, docs, or web pages.",
      priority: 6,
      dismissible: true,
      tone: "info",
    });
  }

  // Win celebration
  if (recentWins.length > 0) {
    const latestWin = recentWins[recentWins.length - 1];
    guidance.push({
      id: "celebrate-win",
      title: isZh ? "已完成" : "Completed",
      description: latestWin,
      priority: 50,
      dismissible: true,
      tone: "success",
    });
  }

  // Growth mindset for mistakes
  if (recentMistakes.length > 0) {
    const latestMistake = recentMistakes[recentMistakes.length - 1];
    guidance.push({
      id: "growth-mindset",
      title: isZh ? "待复盘" : "Needs review",
      description: latestMistake,
      priority: 51,
      dismissible: true,
      tone: "encouragement",
    });
  }

  // Mastery progress (for users with stats)
  if (masteredCards > 0) {
    guidance.push({
      id: "mastery-progress",
      title: isZh ? "技能成长" : "Skill growth",
      description: isZh
        ? `已掌握 ${masteredCards} 个概念。`
        : `${masteredCards} concept${masteredCards > 1 ? "s" : ""} mastered.`,
      priority: 60,
      dismissible: true,
      tone: "success",
    });
  }

  // Practice time encouragement
  if (totalPracticeTime > 30) {
    const hours = Math.floor(totalPracticeTime / 60);
    const minutes = totalPracticeTime % 60;
    const timeStr = hours > 0
      ? (isZh ? `${hours} 小时 ${minutes} 分钟` : `${hours}h ${minutes}m`)
      : (isZh ? `${minutes} 分钟` : `${minutes} minutes`);

    guidance.push({
      id: "practice-time",
      title: isZh ? "专注时间" : "Focus time",
      description: isZh
        ? `你已经投入 ${timeStr} 的专注练习。持续的投入会带来质的飞跃。`
        : `You've invested ${timeStr} of focused practice. Consistent investment leads to breakthroughs.`,
      priority: 70,
      dismissible: true,
      tone: "encouragement",
    });
  }

  // Sort by priority
  return guidance.sort((a, b) => a.priority - b.priority);
}

/**
 * Get guidance tone color class
 */
export function getGuidanceToneClass(tone?: GuidanceItem["tone"]): string {
  switch (tone) {
    case "success":
      return "guidance-item--success";
    case "warning":
      return "guidance-item--warning";
    case "encouragement":
      return "guidance-item--encouragement";
    default:
      return "guidance-item--info";
  }
}

/**
 * Keyboard shortcut item for display
 */
export interface KeyboardShortcutItem {
  key: string;
  description: string;
}

/**
 * Get keyboard shortcuts for the current view
 */
export function getKeyboardShortcuts(view: CoachGuidanceConfig["currentView"]): KeyboardShortcutItem[] {
  const shortcuts: Record<string, KeyboardShortcutItem[]> = {
    coach: [
      { key: "Enter", description: "发送消息" },
      { key: "Shift+Enter", description: "换行" },
      { key: "/", description: "斜杠命令" },
      { key: "Ctrl+L", description: "清除对话" },
    ],
    plan: [
      { key: "Enter", description: "确认编辑" },
      { key: "Esc", description: "取消编辑" },
    ],
    training: [
      { key: "1-4", description: "评级卡片" },
      { key: "Space", description: "显示答案" },
      { key: "→", description: "下一张卡片" },
    ],
    resources: [
      { key: "Enter", description: "打开预览" },
      { key: "Delete", description: "删除资源" },
      { key: "Ctrl+I", description: "导入资源" },
    ],
    settings: [
      { key: "Ctrl+S", description: "保存设置" },
      { key: "Tab", description: "切换字段" },
    ],
  };
  return shortcuts[view] || [];
}

/**
 * Get motivational message based on current state
 */
export function getMotivationalMessage(
  streak: number,
  masteredCards: number,
  language: "zh-CN" | "en-US"
): string {
  const isZh = language === "zh-CN";

  if (streak >= 30) {
    return isZh
      ? "已连续练习 30 天。"
      : "30-day streak.";
  }
  if (streak >= 7) {
    return isZh
      ? "已连续练习一周。"
      : "One-week streak.";
  }
  if (masteredCards >= 50) {
    return isZh
      ? "已掌握 50+ 个概念。"
      : "50+ concepts mastered.";
  }
  if (masteredCards >= 10) {
    return isZh
      ? "已掌握 10+ 个概念。"
      : "10+ concepts mastered.";
  }
  return isZh
    ? "暂无练习记录。"
    : "No practice yet.";
}

/**
 * Get encouragement message based on performance
 */
export function getEncouragementMessage(
  lastRating: number,
  language: "zh-CN" | "en-US"
): string {
  const isZh = language === "zh-CN";

  if (lastRating === 1) {
    return isZh ? "再试一次。" : "Try again.";
  }
  if (lastRating === 2) {
    return isZh ? "再做一遍。" : "Try one more pass.";
  }
  if (lastRating === 3) {
    return isZh ? "已通过。" : "Passed.";
  }
  if (lastRating === 4) {
    return isZh ? "已掌握这个概念。" : "Concept mastered.";
  }
  return isZh ? "继续当前练习。" : "Continue the current practice.";
}

/**
 * Format relative time in a human-friendly way
 */
export function formatRelativeTime(
  minutes: number,
  language: "zh-CN" | "en-US"
): string {
  const isZh = language === "zh-CN";

  if (minutes < 1) {
    return isZh ? "刚刚" : "Just now";
  }
  if (minutes < 60) {
    return isZh ? `${minutes} 分钟前` : `${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return isZh ? `${hours} 小时前` : `${hours}h ago`;
  }
  const days = Math.floor(hours / 24);
  if (days < 7) {
    return isZh ? `${days} 天前` : `${days}d ago`;
  }
  const weeks = Math.floor(days / 7);
  if (weeks < 4) {
    return isZh ? `${weeks} 周前` : `${weeks}w ago`;
  }
  const months = Math.floor(days / 30);
  return isZh ? `${months} 个月前` : `${months}mo ago`;
}
