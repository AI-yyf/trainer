/**
 * Coach Conversation Engine - 教练对话引擎
 *
 * 这个模块实现了教练的核心对话逻辑：
 * 1. 理解用户的学习意图
 * 2. 通过对话收集必要信息
 * 3. 触发学习计划生成
 * 4. 管理训练卡片生成
 * 5. 处理进度反馈
 */

import type {
  ComposerLanguage,
  ConversationMessage,
  CoachingState,
  CoachAnswerMode,
  TeachingStyle,
} from "./types";
import {
  CoachConversationPhase,
  type CoachConversationState,
  type CoachAction,
  type ClarifyingQuestion,
  type GeneratedLearningPlan,
  type CoachDiagnosis,
  type LearningGoal as LGoal,
  type LearnerProfile as LProfile,
  coachIntelligence,
  inferDomain,
  generateClarifyingQuestions,
  estimateCompletionTime,
  createDefaultLearningStages,
} from "./coachIntelligence";

// =============================================================================
// 对话状态管理
// =============================================================================

/** 初始教练对话状态 */
export function createInitialCoachState(): CoachConversationState {
  return {
    phase: "intake",
    clarifyingAnswers: {},
  };
}

/** 从用户消息中提取学习意图 */
export function extractLearningIntent(
  message: string,
  language: ComposerLanguage
): { intent: string; goal?: LGoal } {
  const lowerMessage = message.toLowerCase();

  // 检测学习相关的关键词
  const learningKeywords = [
    "学习", "learn", "掌握", "master", "学", "学会",
    "理解", "understand", "了解", "熟悉", "familiar",
    "成为", "become", "想成为", "want to be",
  ];

  const isLearningIntent = learningKeywords.some(keyword => lowerMessage.includes(keyword));

  if (!isLearningIntent) {
    return { intent: "general" };
  }

  // 尝试提取目标领域
  const domainPatterns = [
    { pattern: /强化学习|reinforcement learning|RL/gi, domain: "强化学习" },
    { pattern: /机器学习|machine learning|ML/gi, domain: "机器学习" },
    { pattern: /深度学习|deep learning|DL/gi, domain: "深度学习" },
    { pattern: /人工智能|AI|artificial intelligence/gi, domain: "人工智能" },
    { pattern: /编程|programming|开发|development/gi, domain: "编程开发" },
    { pattern: /前端|frontend|react|vue|angular/gi, domain: "前端开发" },
    { pattern: /后端|backend|node|python|java/gi, domain: "后端开发" },
    { pattern: /数据结构|算法|algorithm|data structure/gi, domain: "数据结构与算法" },
  ];

  let detectedDomain = "";
  for (const { pattern, domain } of domainPatterns) {
    if (pattern.test(message)) {
      detectedDomain = domain;
      break;
    }
  }

  if (detectedDomain) {
    const { subdomains } = inferDomain(message);
    return {
      intent: "learning_goal",
      goal: {
        rawDescription: message,
        domain: detectedDomain,
        subdomains,
        difficultyPreference: "adaptive",
        weeklyHours: 5, // 默认值
        currentLevel: "basic",
      },
    };
  }

  return { intent: "learning_goal", goal: undefined };
}

/** 生成下一个澄清问题 */
export function getNextClarifyingQuestion(
  state: CoachConversationState,
  language: ComposerLanguage
): ClarifyingQuestion | undefined {
  if (!state.rawGoal) return undefined;

  const goal = state.parsedGoal || inferDomain(state.rawGoal);
  const questions = generateClarifyingQuestions(state.rawGoal, goal.domain);

  // 找到下一个未回答的问题
  for (const q of questions) {
    if (state.clarifyingAnswers[q.id] === undefined && q.isRequired) {
      return q;
    }
  }

  return undefined;
}

/** 判断是否需要继续提问 */
export function needsMoreInformation(state: CoachConversationState): boolean {
  if (!state.rawGoal) return false;

  const goal = state.parsedGoal || inferDomain(state.rawGoal);
  const questions = generateClarifyingQuestions(state.rawGoal, goal.domain);

  // 检查是否有未回答的必要问题
  return questions.some(q => q.isRequired && state.clarifyingAnswers[q.id] === undefined);
}

/** 根据状态生成教练回复 */
export interface CoachResponse {
  message: string;
  action?: CoachAction;
  newState?: CoachConversationState;
  data?: {
    diagnosis?: CoachDiagnosis;
    plan?: GeneratedLearningPlan;
    card?: any;
  };
}

/** 生成教练对话回复 */
export function generateCoachResponse(
  userMessage: string,
  currentState: CoachConversationState,
  language: ComposerLanguage,
  teachingStyle: TeachingStyle,
  previousContext?: string
): CoachResponse {
  const state = { ...currentState };
  const isChinese = language === "zh-CN";

  // Phase 1: 收集用户信息
  if (state.phase === "intake") {
    // 首次对话，提取学习意图
    const { intent, goal } = extractLearningIntent(userMessage, language);

    if (intent === "general") {
      return {
        message: isChinese
          ? "我是你的学习教练。告诉我你想学什么，或者你现在在哪方面想提升？"
          : "I'm your learning coach. Tell me what you want to learn, or where you'd like to improve.",
        newState: state,
      };
    }

    // 设置了学习目标
    state.rawGoal = userMessage;
    if (goal) {
      state.parsedGoal = goal;
    }

    // 生成第一个澄清问题
    const question = getNextClarifyingQuestion(state, language);
    if (question) {
      const questionText = question.options
        ? `${question.question}\n\n${question.options.map((opt, i) => `${i + 1}. ${opt}`).join('\n')}`
        : question.question;

      return {
        message: isChinese
          ? `明白了，你想学习${goal?.domain || '这个领域'}。${questionText}\n\n${question.reason}`
          : `Got it, you want to learn ${goal?.domain || 'this topic'}. ${questionText}\n\n${question.reason}`,
        newState: state,
      };
    }
  }

  // 处理澄清问题的回答
  if (userMessage.match(/^[1-4]$/)) {
    const optionIndex = parseInt(userMessage) - 1;
    const nextQuestion = getNextClarifyingQuestion(state, language);

    // 这里需要根据问题ID设置答案
    // 简化处理：根据问题数量判断
    if (Object.keys(state.clarifyingAnswers).length === 0) {
      state.clarifyingAnswers.current_level = optionIndex.toString();
      const nextQ = getNextClarifyingQuestion(state, language);
      if (nextQ) {
        const questionText = nextQ.options
          ? `${nextQ.question}\n\n${nextQ.options.map((opt, i) => `${i + 1}. ${opt}`).join('\n')}`
          : nextQ.question;
        return {
          message: questionText,
          newState: state,
        };
      }
    }

    if (Object.keys(state.clarifyingAnswers).length === 1) {
      state.clarifyingAnswers.time_availability = optionIndex.toString();
      const nextQ = getNextClarifyingQuestion(state, language);
      if (nextQ) {
        const questionText = nextQ.options
          ? `${nextQ.question}\n\n${nextQ.options.map((opt, i) => `${i + 1}. ${opt}`).join('\n')}`
          : nextQ.question;
        return {
          message: questionText,
          newState: state,
        };
      }
    }
  }

  // Phase 2: 生成诊断
  if (Object.keys(state.clarifyingAnswers).length >= 2 && state.phase === "intake") {
    state.phase = "diagnosis";

    // 构建学习目标
    const levelMap = ["none", "basic", "intermediate", "advanced"];
    const hoursMap = [2, 5, 8, 15];
    const levelIndex = parseInt(state.clarifyingAnswers.current_level || "1");
    const hoursIndex = parseInt(state.clarifyingAnswers.time_availability || "1");

    const goal = state.parsedGoal || {
      rawDescription: state.rawGoal || "",
      domain: "通用",
      subdomains: [],
      difficultyPreference: "adaptive" as const,
      weeklyHours: hoursMap[hoursIndex],
      currentLevel: levelMap[levelIndex] as LGoal["currentLevel"],
    };

    // 估算完成时间
    const weeks = estimateCompletionTime(
      goal.domain,
      goal.subdomains,
      goal.weeklyHours,
      goal.currentLevel
    );

    const diagnosis: CoachDiagnosis = {
      goal,
      assessedLevel: levelMap[levelIndex] as CoachDiagnosis["assessedLevel"],
      recommendedPath: {
        id: `path-${goal.domain}-${Date.now()}`,
        name: `${goal.domain}学习路径`,
        description: `为你的${goal.domain}学习设计的路径`,
        estimatedHours: goal.weeklyHours * weeks,
        stages: createDefaultLearningStages(goal.domain),
        sequence: createDefaultLearningStages(goal.domain).map(s => s.id),
      },
      prerequisites: levelMap[levelIndex] === "none" ? ["基础知识准备"] : [],
      coachJudgment: isChinese
        ? `根据你的情况，我会帮你制定一个适合你的学习计划。预计需要${weeks}周时间。`
        : `Based on your situation, I'll create a learning plan for you. Estimated time: ${weeks} weeks.`,
      clarifyingQuestions: [],
    };

    state.diagnosis = diagnosis;
    state.learnerProfile = {
      relatedExperience: [levelMap[levelIndex]],
      timeAvailability: hoursMap[hoursIndex],
    };

    return {
      message: diagnosis.coachJudgment + "\n\n" + (isChinese
        ? "我们开始制定具体的学习计划吗？"
        : "Shall we start creating your learning plan?"),
      action: { type: "present_diagnosis", diagnosis },
      data: { diagnosis },
      newState: state,
    };
  }

  // Phase 3: 生成计划（当用户确认时）
  if (state.phase === "diagnosis" && userMessage.includes(isChinese ? "开始" : "start")) {
    state.phase = "planning";
    return {
      message: isChinese
        ? "好的，让我为你生成学习计划..."
        : "Alright, let me create your learning plan...",
      newState: state,
    };
  }

  // 默认回复
  return {
    message: isChinese
      ? "我需要更多信息来帮你制定学习计划。请告诉我你想学什么？"
      : "I need more information to help you create a learning plan. What would you like to learn?",
    newState: state,
  };
}

// =============================================================================
// 教练状态描述
// =============================================================================

/** 获取教练状态的人类可读描述 */
export function getCoachStateDescription(
  state: CoachConversationState,
  language: ComposerLanguage
): string {
  const isChinese = language === "zh-CN";

  switch (state.phase) {
    case "intake":
      return isChinese ? "正在了解你的学习目标" : "Understanding your learning goals";
    case "diagnosis":
      return isChinese ? "正在分析你的情况" : "Analyzing your situation";
    case "planning":
      return isChinese ? "正在生成学习计划" : "Creating your learning plan";
    case "executing":
      return isChinese ? "正在执行学习计划" : "Executing learning plan";
    case "adapting":
      return isChinese ? "正在调整计划" : "Adapting plan";
    case "completed":
      return isChinese ? "已完成当前阶段" : "Current stage completed";
    default:
      return isChinese ? "准备中" : "Preparing";
  }
}

// =============================================================================
// 导出
// =============================================================================

export const coachConversationEngine = {
  createInitialCoachState,
  extractLearningIntent,
  getNextClarifyingQuestion,
  needsMoreInformation,
  generateCoachResponse,
  getCoachStateDescription,
};

export default coachConversationEngine;
