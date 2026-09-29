/**
 * Coach Guidance System - Contextual, humanized coaching feedback
 *
 * Provides compact status and next-step feedback for the current view.
 */

import type { ReactNode } from "react";
import type { ComposerLanguage } from "../../lib/types";
import { coachGuidanceCopy } from "./coachGuidanceCopy";

export interface CoachGuidanceConfig {
  language: ComposerLanguage;
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
 * Get streak-level message
 */
function getStreakMessage(language: ComposerLanguage, streak: number): string {
  if (streak === 0) {
    return coachGuidanceCopy(language, "今天还没有练习");
  }
  if (streak <= 3) {
    return coachGuidanceCopy(language, "练习已开始");
  }
  if (streak <= 7) {
    return coachGuidanceCopy(language, "坚持训练，习惯正在养成");
  }
  if (streak <= 14) {
    return coachGuidanceCopy(language, "你已经建立了训练节奏！");
  }
  if (streak <= 30) {
    return coachGuidanceCopy(language, "你的坚持正在产生效果");
  }
  return coachGuidanceCopy(language, "训练节奏很稳");
}

/**
 * Get review queue message
 */
function getReviewMessage(language: ComposerLanguage, dueCount: number): string {
  const plural = dueCount !== 1 ? "s" : "";

  if (dueCount === 0) {
    return coachGuidanceCopy(language, "没有待复习的卡片，休息一下或者挑战新内容");
  }
  if (dueCount <= 3) {
    return coachGuidanceCopy(language, "{n} 张卡片等待复习，保持记忆不丢失")
      .replace("{n}", String(dueCount))
      .replace("{s}", plural);
  }
  if (dueCount <= 10) {
    return coachGuidanceCopy(language, "你有 {n} 张卡片需要复习，坚持就是胜利")
      .replace("{n}", String(dueCount))
      .replace("{s}", plural);
  }
  return coachGuidanceCopy(language, "复习队列较长，逐一击破会更有成就感");
}

/**
 * Time-based greeting that feels natural
 */
function getTimeBasedGreeting(language: ComposerLanguage, hour?: number): string {
  const h = hour ?? new Date().getHours();

  if (h < 5) {
    return coachGuidanceCopy(language, "夜间");
  }
  if (h < 9) {
    return coachGuidanceCopy(language, "清晨");
  }
  if (h < 12) {
    return coachGuidanceCopy(language, "上午");
  }
  if (h < 14) {
    return coachGuidanceCopy(language, "午间");
  }
  if (h < 18) {
    return coachGuidanceCopy(language, "下午");
  }
  if (h < 21) {
    return coachGuidanceCopy(language, "晚上");
  }
  return coachGuidanceCopy(language, "夜间");
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
      title: coachGuidanceCopy(language, "第一步：连接模型"),
      description: coachGuidanceCopy(language, "填写 provider、模型和 API key。"),
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
      title: coachGuidanceCopy(language, "创建一个训练计划"),
      description: coachGuidanceCopy(language, "告诉我目标或当前项目。"),
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
      title: coachGuidanceCopy(language, "生成训练卡片"),
      description: coachGuidanceCopy(language, "问一个具体问题开始。"),
        priority: 3,
        dismissible: true,
        tone: "info",
      });
    }

    // Encourage practice based on due reviews
    if (dueReviews > 0) {
      guidance.push({
        id: "review-due",
        title: coachGuidanceCopy(language, "复习提醒"),
        description: getReviewMessage(language, dueReviews),
        priority: 4,
        dismissible: true,
        tone: "warning",
      });
    } else if (hasTrainingCards) {
      guidance.push({
        id: "practice-ready",
        title: coachGuidanceCopy(language, "可以继续练习"),
        description: coachGuidanceCopy(language, "今天的复习已完成。"),
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
      title: coachGuidanceCopy(language, "添加学习资料"),
      description: coachGuidanceCopy(language, "导入代码、文档或网页。"),
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
      title: coachGuidanceCopy(language, "已完成"),
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
      title: coachGuidanceCopy(language, "待复盘"),
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
      title: coachGuidanceCopy(language, "技能成长"),
      description: coachGuidanceCopy(language, "已掌握 {n} 个概念。")
        .replace("{n}", String(masteredCards))
        .replace("{s}", masteredCards > 1 ? "s" : ""),
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
      ? coachGuidanceCopy(language, "{h} 小时 {m} 分钟")
          .replace("{h}", String(hours))
          .replace("{m}", String(minutes))
      : coachGuidanceCopy(language, "{m} 分钟").replace("{m}", String(minutes));

    guidance.push({
      id: "practice-time",
      title: coachGuidanceCopy(language, "专注时间"),
      description: coachGuidanceCopy(
        language,
        "你已经投入 {t} 的专注练习。持续的投入会带来质的飞跃。",
      ).replace("{t}", timeStr),
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
  language: ComposerLanguage
): string {
  if (streak >= 30) {
    return coachGuidanceCopy(language, "已连续练习 30 天。");
  }
  if (streak >= 7) {
    return coachGuidanceCopy(language, "已连续练习一周。");
  }
  if (masteredCards >= 50) {
    return coachGuidanceCopy(language, "已掌握 50+ 个概念。");
  }
  if (masteredCards >= 10) {
    return coachGuidanceCopy(language, "已掌握 10+ 个概念。");
  }
  return coachGuidanceCopy(language, "暂无练习记录。");
}

/**
 * Get encouragement message based on performance
 */
export function getEncouragementMessage(
  lastRating: number,
  language: ComposerLanguage
): string {
  if (lastRating === 1) {
    return coachGuidanceCopy(language, "再试一次。");
  }
  if (lastRating === 2) {
    return coachGuidanceCopy(language, "再做一遍。");
  }
  if (lastRating === 3) {
    return coachGuidanceCopy(language, "已通过。");
  }
  if (lastRating === 4) {
    return coachGuidanceCopy(language, "已掌握这个概念。");
  }
  return coachGuidanceCopy(language, "继续当前练习。");
}

/**
 * Format relative time in a human-friendly way
 */
export function formatRelativeTime(
  minutes: number,
  language: ComposerLanguage
): string {
  if (minutes < 1) {
    return coachGuidanceCopy(language, "刚刚");
  }
  if (minutes < 60) {
    return coachGuidanceCopy(language, "{m} 分钟前").replace("{m}", String(minutes));
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return coachGuidanceCopy(language, "{h} 小时前").replace("{h}", String(hours));
  }
  const days = Math.floor(hours / 24);
  if (days < 7) {
    return coachGuidanceCopy(language, "{d} 天前").replace("{d}", String(days));
  }
  const weeks = Math.floor(days / 7);
  if (weeks < 4) {
    return coachGuidanceCopy(language, "{w} 周前").replace("{w}", String(weeks));
  }
  const months = Math.floor(days / 30);
  return coachGuidanceCopy(language, "{mo} 个月前").replace("{mo}", String(months));
}
