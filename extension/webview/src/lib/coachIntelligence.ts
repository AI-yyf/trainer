/**
 * Coach Intelligence System - 教练智能核心
 *
 * 这个模块定义了 Trainer 作为"真正教练"所需的核心能力：
 * 1. 理解用户的学习目标
 * 2. 评估用户的当前水平
 * 3. 动态生成学习计划
 * 4. 实时生成训练卡片
 * 5. 调整教学策略
 *
 * 设计原则：
 * - 不预置固定内容，而是基于用户需求动态生成
 * - 教练能力由 AI + 结构化协议共同提供
 * - 支持多轮对话迭代优化计划
 */

import type {
  ComposerLanguage,
  LearningPlan,
  PlanStage,
  TrainingCardCandidateSnapshot,
  FlashcardAttempt,
} from "./types";

// =============================================================================
// 教练能力类型定义
// =============================================================================

/** 用户的学习目标描述 */
export interface LearningGoal {
  /** 用户用自然语言描述的目标 */
  rawDescription: string;
  /** 目标领域（如强化学习、编程、机器学习等） */
  domain: string;
  /** 目标细分（如强化学习 → Q-Learning, DQN, PPO等）*/
  subdomains: string[];
  /** 用户认为的难度偏好 */
  difficultyPreference: "beginner" | "intermediate" | "advanced" | "adaptive";
  /** 用户可投入的时间（小时/周） */
  weeklyHours: number;
  /** 用户当前水平（自评） */
  currentLevel: "none" | "basic" | "intermediate" | "advanced";
  /** 是否有特定的应用场景 */
  applicationContext?: string;
  /** 是否有已知的约束或偏好 */
  constraints?: string[];
}

/** 用户背景信息 */
export interface LearnerProfile {
  /** 教育背景 */
  education?: string;
  /** 相关经验 */
  relatedExperience?: string[];
  /** 学习偏好 */
  learningStyle?: "theory_first" | "practice_first" | "balanced";
  /** 时间可用性 */
  timeAvailability?: number; // hours per week
  /** 目标时间线 */
  targetTimeline?: string;
  /** 学习动机 */
  motivation?: string;
}

/** 教练生成的诊断结果 */
export interface CoachDiagnosis {
  /** 用户描述的目标解析 */
  goal: LearningGoal;
  /** 评估的用户水平 */
  assessedLevel: "beginner" | "intermediate" | "advanced";
  /** 推荐的学习路径 */
  recommendedPath: LearningPath;
  /** 需要先补的基础（如果有）*/
  prerequisites: string[];
  /** 教练的初始判断 */
  coachJudgment: string;
  /** 需要向用户确认的问题 */
  clarifyingQuestions: ClarifyingQuestion[];
}

/** 澄清性问题 */
export interface ClarifyingQuestion {
  id: string;
  question: string;
  options?: string[];
  isRequired: boolean;
  reason: string;
}

/** 学习路径 */
export interface LearningPath {
  id: string;
  name: string;
  description: string;
  estimatedHours: number;
  stages: LearningStage[];
  /** 推荐的学习顺序 */
  sequence: string[];
}

/** 学习阶段 */
export interface LearningStage {
  id: string;
  title: string;
  description: string;
  topics: string[];
  estimatedHours: number;
  difficulty: "easy" | "medium" | "hard";
  /** 推荐的练习/项目类型 */
  practiceTypes: string[];
  /** 验收标准 */
  acceptanceCriteria: string[];
  dependencies: string[];
}

/** 生成的学习计划 */
export interface GeneratedLearningPlan {
  /** 计划基本信息 */
  meta: {
    id: string;
    title: string;
    subtitle: string;
    createdAt: string;
    estimatedTotalHours: number;
    targetCompletionDate?: string;
  };
  /** 学习阶段 */
  stages: GeneratedStage[];
  /** 每周节奏建议 */
  weeklyRhythm: WeeklyRhythm;
  /** 教练策略 */
  coachingStrategy: CoachingStrategy;
}

/** 生成的阶段 */
export interface GeneratedStage {
  id: string;
  order: number;
  title: string;
  description: string;
  topics: string[];
  estimatedHours: number;
  difficulty: "easy" | "medium" | "hard";
  milestones: Milestone[];
  practiceCards: PracticeCardSpec[];
  flashCards: FlashCardSpec[];
  verificationMethod: VerificationMethod;
}

/** 里程碑 */
export interface Milestone {
  id: string;
  title: string;
  description: string;
  /** 完成标志 */
  completionSignal: string;
  /** 需要的练习数量 */
  requiredPracticeCount: number;
}

/** 练习卡片规格（用于 AI 生成） */
export interface PracticeCardSpec {
  id: string;
  type: "implementation" | "debug" | "optimization" | "transfer" | "analysis";
  title: string;
  focusArea: string;
  targetSkill: string;
  problemStatement: string;
  suggestedApproach: string;
  hints: string[];
  verificationCriteria: string[];
  estimatedTime: string;
  difficulty: "easy" | "medium" | "hard";
}

/** 闪卡规格（用于 AI 生成） */
export interface FlashCardSpec {
  id: string;
  type: "concept" | "formula" | "principle" | "anti_pattern" | "comparison";
  question: string;
  expectedAnswer: string;
  hintLadder: string[];
  commonMistakes: string[];
  masteryDelta: number;
}

/** 验证方法 */
export interface VerificationMethod {
  type: "project" | "quiz" | "teaching" | "peer_review" | "self_assessment";
  description: string;
  criteria: string[];
}

/** 每周节奏 */
export interface WeeklyRhythm {
  sessionsPerWeek: number;
  sessionDuration: number; // minutes
  recommendedActivities: {
    day: string;
    activity: "practice" | "review" | "new_concept" | "project";
    duration: number;
  }[];
  restDays: string[];
}

/** 教练策略 */
export interface CoachingStrategy {
  /** 教学风格 */
  teachingStyle: "guided" | "challenge" | "socratic" | "mixed";
  /** 反馈时机 */
  feedbackTiming: "immediate" | "delayed" | "milestone";
  /** 探索vs指导的平衡 */
  explorationRatio: number; // 0-1
  /** 复习策略 */
  reviewStrategy: "spaced" | "interleaved" | "blocked";
  /** 难度调整策略 */
  difficultyAdaptation: "stable" | "adaptive" | "probe_then_adapt";
}

/** 计划调整请求 */
export interface PlanAdjustmentRequest {
  /** 当前进度 */
  completedTopics: string[];
  /** 遇到的困难 */
  difficulties: string[];
  /** 用户的反馈 */
  userFeedback: string;
  /** 时间变化 */
  newTimeAvailability?: number;
  /** 目标变化 */
  newGoals?: string;
}

// =============================================================================
// 教练提示词模板
// =============================================================================

export const COACH_SYSTEM_PROMPT = `你是一个专业教练，专注于帮助用户达成学习目标。你的职责是：

1. **理解需求**：通过对话理解用户真正想学什么、当前水平如何、能投入多少时间
2. **生成计划**：基于用户情况，生成结构化的学习计划，包括阶段划分、练习安排、复习节奏
3. **动态调整**：根据用户的进展和反馈，实时调整计划
4. **生成内容**：为每个学习单元生成具体的练习卡片和闪卡
5. **激励学习**：保持用户的学习动力，帮助克服困难

你的特点：
- 先问清楚再行动：不要假设，理解用户真正的背景和目标
- 具体而非抽象：给出可操作的学习步骤，不是泛泛而谈
- 灵活调整：计划是活的，可以根据实际情况调整
- 人性化：理解学习中的挫折，鼓励用户继续前进

记住：你不是搜索引擎，不是知识库，而是一个陪伴用户学习的教练。`;

/** 生成学习计划时的系统提示 */
export const PLAN_GENERATION_PROMPT = `当用户描述了一个学习目标后，你需要：

1. **解析目标**：
   - 识别目标领域和细分方向
   - 评估用户的实际水平（通过提问）
   - 了解时间和资源约束

2. **设计学习路径**：
   - 确定必要的先修知识
   - 划分合理的学习阶段
   - 每阶段设置可验证的里程碑
   - 分配合理的时间

3. **生成具体内容**：
   - 为每个主题生成练习卡片
   - 生成概念闪卡
   - 设计验证方法

4. **考虑个人化**：
   - 根据用户时间安排学习节奏
   - 根据用户偏好调整教学风格
   - 预留调整空间

输出格式必须是结构化的 JSON，符合 GeneratedLearningPlan 类型定义。`;

/** 生成练习卡片时的提示 */
export const CARD_GENERATION_PROMPT = `为用户生成练习卡片时，确保：

1. **练习要有意义**：
   - 紧扣当前学习目标
   - 有清晰的验收标准
   - 难度适当

2. **提供渐进式提示**：
   - 从最少的提示开始
   - 逐步增加提示深度
   - 最后才给答案

3. **包含常见错误**：
   - 预测可能的犯错方式
   - 帮助用户识别错误

4. **确保可验证**：
   - 每张卡片有明确的完成标志
   - 提供自检方法

闪卡格式：
- 问题要具体，不要太泛
- 答案要简洁有力
- 提供回忆提示（hint ladder）

练习卡格式：
- 问题陈述清晰
- 有足够上下文让用户理解
- 提供验证方法`;

// =============================================================================
// 教练对话协议
// =============================================================================

/** 教练对话状态 */
export type CoachConversationPhase =
  | "intake"           // 收集用户信息
  | "diagnosis"        // 诊断和理解
  | "planning"         // 生成计划
  | "executing"        // 执行计划
  | "adapting"         // 调整计划
  | "completed";       // 完成某个阶段

/** 教练对话状态机 */
export interface CoachConversationState {
  phase: CoachConversationPhase;
  /** 用户描述的原始需求 */
  rawGoal?: string;
  /** 解析后的目标 */
  parsedGoal?: LearningGoal;
  /** 用户背景 */
  learnerProfile?: LearnerProfile;
  /** 诊断结果 */
  diagnosis?: CoachDiagnosis;
  /** 当前计划 */
  currentPlan?: GeneratedLearningPlan;
  /** 当前阶段 */
  currentStageIndex?: number;
  /** 当前练习卡片 */
  currentCard?: TrainingCardCandidateSnapshot | FlashcardAttempt;
  /** 收集到的澄清答案 */
  clarifyingAnswers: Record<string, string>;
}

/** 教练动作 */
export type CoachAction =
  | { type: "ask_background"; question: ClarifyingQuestion }
  | { type: "present_diagnosis"; diagnosis: CoachDiagnosis }
  | { type: "present_plan"; plan: GeneratedLearningPlan }
  | { type: "present_card"; card: TrainingCardCandidateSnapshot | FlashcardAttempt }
  | { type: "give_feedback"; feedback: string }
  | { type: "adjust_plan"; adjustment: PlanAdjustmentRequest }
  | { type: "celebrate_progress"; milestone: string }
  | { type: "offer_support"; support: string };

// =============================================================================
// 教练能力工厂
// =============================================================================

/** 创建默认的学习阶段模板 */
export function createDefaultLearningStages(domain: string): LearningStage[] {
  return [
    {
      id: `${domain}-stage-1`,
      title: "基础概念",
      description: "理解核心概念和基本原理",
      topics: [],
      estimatedHours: 4,
      difficulty: "easy",
      practiceTypes: ["recall", "explain"],
      acceptanceCriteria: ["能够用自己的话解释核心概念", "能识别相关概念"],
      dependencies: [],
    },
    {
      id: `${domain}-stage-2`,
      title: "核心方法",
      description: "掌握主要方法和工具",
      topics: [],
      estimatedHours: 8,
      difficulty: "medium",
      practiceTypes: ["implementation", "comparison"],
      acceptanceCriteria: ["能独立实现基本方法", "能对比不同方法的优缺点"],
      dependencies: ["stage-1"],
    },
    {
      id: `${domain}-stage-3`,
      title: "实践应用",
      description: "通过项目练习深化理解",
      topics: [],
      estimatedHours: 12,
      difficulty: "medium",
      practiceTypes: ["project", "transfer"],
      acceptanceCriteria: ["能完成一个小型项目", "能将知识迁移到类似问题"],
      dependencies: ["stage-2"],
    },
    {
      id: `${domain}-stage-4`,
      title: "高级主题",
      description: "深入高级特性和最佳实践",
      topics: [],
      estimatedHours: 8,
      difficulty: "hard",
      practiceTypes: ["optimization", "analysis"],
      acceptanceCriteria: ["能处理复杂场景", "能优化和改进现有方案"],
      dependencies: ["stage-3"],
    },
  ];
}

/** 根据目标领域生成澄清问题 */
export function generateClarifyingQuestions(goal: string, domain: string): ClarifyingQuestion[] {
  const questions: ClarifyingQuestion[] = [
    {
      id: "current_level",
      question: `你目前的${domain}水平如何？`,
      options: [
        "完全零基础，只了解基本概念",
        "有一些了解，但没有实践经验",
        "有实践经验，想系统化提升",
        "已经是专家水平，想深入某个细分领域",
      ],
      isRequired: true,
      reason: "了解你的起点有助于设计合适的学习路径。",
    },
    {
      id: "time_availability",
      question: "你每周能投入多少时间学习？",
      options: [
        "1-3小时/周（碎片化时间）",
        "4-6小时/周（每天1小时左右）",
        "7-10小时/周（每天1-2小时）",
        "10+小时/周（深度学习模式）",
      ],
      isRequired: true,
      reason: "时间投入决定了学习节奏和计划密度。",
    },
    {
      id: "learning_style",
      question: "你更喜欢哪种学习方式？",
      options: [
        "先打理论基础，再实践",
        "边做边学，从实践中理解理论",
        "理论实践交替进行",
      ],
      isRequired: false,
      reason: "学习偏好影响教学策略的选择。",
    },
  ];

  // 根据领域添加特定问题
  if (domain.includes("编程") || domain.includes("代码")) {
    questions.push({
      id: "language",
      question: "你主要使用哪种编程语言？",
      options: ["Python", "JavaScript/TypeScript", "Java", "Go", "Rust", "其他"],
      isRequired: false,
      reason: "了解你的工具偏好可以给出更具体的学习建议。",
    });
  }

  if (domain.includes("机器学习") || domain.includes("深度学习") || domain.includes("强化学习")) {
    questions.push({
      id: "math_background",
      question: "你的数学基础如何？",
      options: [
        "数学基础较弱，需要补充",
        "有本科数学基础（微积分、线代、概率）",
        "数学基础扎实，能理解推导过程",
      ],
      isRequired: false,
      reason: "数学是这些领域的基础，影响学习深度。",
    });
  }

  return questions;
}

/** 从目标字符串推断领域 */
export function inferDomain(goal: string): { domain: string; subdomains: string[] } {
  const lowerGoal = goal.toLowerCase();

  // 机器学习相关
  if (lowerGoal.includes("机器学习") || lowerGoal.includes("machine learning") || lowerGoal.includes("ml")) {
    const subdomains: string[] = [];
    if (lowerGoal.includes("深度学习") || lowerGoal.includes("deep learning") || lowerGoal.includes("dl")) {
      subdomains.push("深度学习");
    }
    if (lowerGoal.includes("强化学习") || lowerGoal.includes("reinforcement learning") || lowerGoal.includes("rl")) {
      subdomains.push("强化学习");
    }
    if (lowerGoal.includes("计算机视觉") || lowerGoal.includes("cv") || lowerGoal.includes("图像")) {
      subdomains.push("计算机视觉");
    }
    if (lowerGoal.includes("nlp") || lowerGoal.includes("自然语言") || lowerGoal.includes("文本")) {
      subdomains.push("自然语言处理");
    }
    return { domain: "机器学习", subdomains: subdomains.length > 0 ? subdomains : ["机器学习基础"] };
  }

  // 编程相关
  if (lowerGoal.includes("编程") || lowerGoal.includes("开发") || lowerGoal.includes("代码")) {
    const subdomains: string[] = [];
    if (lowerGoal.includes("前端")) subdomains.push("前端开发");
    if (lowerGoal.includes("后端")) subdomains.push("后端开发");
    if (lowerGoal.includes("全栈")) subdomains.push("全栈开发");
    if (lowerGoal.includes("移动")) subdomains.push("移动开发");
    if (lowerGoal.includes("web")) subdomains.push("Web开发");
    return { domain: "软件开发", subdomains: subdomains.length > 0 ? subdomains : ["编程基础"] };
  }

  // 默认返回通用领域
  return { domain: goal.split(" ")[0] || "通用技能", subdomains: [] };
}

/** 估算完成时间 */
export function estimateCompletionTime(
  domain: string,
  subdomains: string[],
  weeklyHours: number,
  level: string,
): number {
  // 基础时间（小时）
  const baseHours: Record<string, number> = {
    "机器学习": 60,
    "强化学习": 80,
    "深度学习": 50,
    "软件开发": 40,
    "前端开发": 30,
    "后端开发": 35,
    "通用技能": 20,
  };

  let hours = baseHours[domain] || baseHours["通用技能"];

  // 根据水平调整
  if (level === "beginner" || level === "none") hours *= 1.5;
  if (level === "advanced") hours *= 0.7;

  // 根据子领域调整
  hours += subdomains.length * 10;

  // 计算周数
  const weeks = Math.ceil(hours / weeklyHours);

  return weeks;
}

// =============================================================================
// 导出
// =============================================================================

export const coachIntelligence = {
  COACH_SYSTEM_PROMPT,
  PLAN_GENERATION_PROMPT,
  CARD_GENERATION_PROMPT,
  createDefaultLearningStages,
  generateClarifyingQuestions,
  inferDomain,
  estimateCompletionTime,
};

export default coachIntelligence;
