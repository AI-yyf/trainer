/**
 * RL Training Mock Data
 * 强化学习训练的完整 Mock 数据
 */

import type {
  BootstrapData,
  FlashcardAttempt,
  TrainingCardCandidateSnapshot,
  LearningPlan,
  PlanStage,
} from "./types";

// =============================================================================
// RL 学习计划
// =============================================================================

export const rlLearningPlan: LearningPlan = {
  id: "rl-mastery-plan",
  title: "强化学习算法完全掌握",
  frozen: false,
  cadence: "每天2小时，持续60天",
  summary: "通过系统的理论学习和密集的实战练习，全面掌握从基础概念到高级算法的强化学习知识体系。",
  stages: [
    {
      id: "stage-1-foundation",
      title: "第一阶段：强化学习基础",
      objective: "掌握MDP、贝尔曼方程、策略与价值函数等核心概念",
      status: "active",
    },
    {
      id: "stage-2-tabular",
      title: "第二阶段：表格型强化学习",
      objective: "精通Q-Learning、SARSA、蒙特卡洛方法等基础算法",
      status: "queued",
    },
    {
      id: "stage-3-deep-rl",
      title: "第三阶段：深度强化学习",
      objective: "掌握DQN及其变体，理解经验回放和目标网络",
      status: "queued",
    },
    {
      id: "stage-4-policy",
      title: "第四阶段：策略优化算法",
      objective: "精通Actor-Critic、DDPG、TD3、SAC等连续控制算法",
      status: "queued",
    },
    {
      id: "stage-5-advanced",
      title: "第五阶段：高级主题",
      objective: "掌握PPO、MCTS、多智能体RL、元学习等高级主题",
      status: "queued",
    },
  ],
  currentStageId: "stage-1-foundation",
  sessionId: "rl-session-001",
};

// =============================================================================
// RL 闪卡数据
// =============================================================================

export const rlFoundationFlashcards: Omit<FlashcardAttempt, "id" | "cardId" | "attemptedAt">[] = [
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "马尔可夫决策过程(MDP)的五元组是什么？",
    expectedAnswer: "(S, A, P, R, γ)：状态空间、动作空间、转移概率、奖励函数、折扣因子",
    hintLadder: [
      "MDP描述了智能体与环境交互的框架",
      "包含描述环境的元素（状态、动作、转移）",
      "包含描述决策的元素（奖励）和学习参数（折扣）",
    ],
    commonMistakes: ["遗漏转移概率P", "混淆奖励函数和价值函数"],
    mastery_delta: 0.10,
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "formula",
    question: "写出贝尔曼期望方程和贝尔曼最优方程",
    expectedAnswer:
      "期望方程: V^π(s) = Σ_a π(a|s) Σ_{s',r} p(s',r|s,a)[r + γV^π(s')]\n最优方程: V*(s) = max_a Σ_{s',r} p(s',r|s,a)[r + γV*(s')]",
    hintLadder: ["期望方程描述给定策略下的价值", "最优方程描述最优策略的价值", "关键区别：期望 vs 最大"],
    commonMistakes: ["混淆两个方程", "忘记折扣因子"],
    mastery_delta: 0.15,
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "Q-Learning的更新公式是什么？",
    expectedAnswer: "Q(s,a) ← Q(s,a) + α[r + γ·max_a' Q(s',a') - Q(s,a)]",
    hintLadder: ["从当前状态和动作出发", "考虑即时奖励和未来价值", "TD目标 = r + γ·max Q(s',a')"],
    commonMistakes: ["忘记使用max操作", "混淆离线/在线策略"],
    mastery_delta: 0.15,
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "为什么Q-Learning是离线策略算法？",
    expectedAnswer:
      "因为它用贪婪策略(选择最大Q值的动作)计算TD目标，但用ε-贪婪策略生成行为策略，两者是不同的策略。",
    hintLadder: ["行为策略和目标策略是否相同？", "TD目标用什么策略选动作？", "行为策略用什么策略探索？"],
    commonMistakes: ["认为只有在线策略", "混淆ε-贪婪和贪婪的区别"],
    mastery_delta: 0.12,
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "on-policy和off-policy的核心区别是什么？",
    expectedAnswer: "on-policy：用于生成数据的策略与正在学习的策略相同（如SARSA）。off-policy：两者不同（如Q-Learning使用ε-贪婪生成数据但学习贪婪策略）。",
    hintLadder: ["关键在于数据来源", "on-policy更保守但sample efficient低", "off-policy可以用历史数据"],
    commonMistakes: ["混淆策略类型", "认为off-policy一定更好"],
    mastery_delta: 0.12,
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "什么是探索-利用困境？有哪些解决方法？",
    expectedAnswer: "探索：尝试新动作获取信息；利用：使用已知最优动作最大化奖励。解决方法：ε-贪婪、softmax、UCB、熵正则化。",
    hintLadder: ["从定义出发", "考虑探索的必要性", "了解各种方法的特点"],
    commonMistakes: ["只记一种方法", "不理解何时需要更多探索"],
    mastery_delta: 0.10,
  },
];

// =============================================================================
// RL 练习卡片
// =============================================================================

export const rlPracticeCards: TrainingCardCandidateSnapshot[] = [
  {
    id: "prac-q-learning-frozenlake",
    card_type: "practice",
    title: "Q-Learning实现FrozenLake环境",
    focus_area: "tabular_rl_implementation",
    target_skill: "Q-Learning算法实现与调试",
    why_now: "Q-Learning是理解强化学习的第一步，是后续所有算法的基础",
    source_chain: ["MDP基础", "贝尔曼方程", "TD学习"],
    difficulty: "easy",
    problem_statement:
      "在FrozenLake-8x8环境中实现Q-Learning算法。\n\n要求：\n1. 正确初始化Q表\n2. 实现ε-贪婪探索策略，支持衰减\n3. 正确实现TD更新公式\n4. 训练10000个episodes，评估最终策略\n5. 可视化学习曲线",
    suggested_files: ["frozen_lake.py", "q_agent.py", "visualization.py"],
    api_hints: [
      "Q(s,a) ← Q(s,a) + α[r + γ·max_{a'}Q(s',a') - Q(s,a)]",
      "np.argmax(q_values) 获取最优动作",
      "ε衰减：epsilon = max(epsilon_min, epsilon * epsilon_decay)",
    ],
    deliverable: "完整可运行的Q-Learning实现 + 训练日志 + 收敛曲线",
    self_check: [
      "Q表更新是否正确使用了TD目标",
      "ε-贪婪是否正确实现",
      "最终成功率是否达到80%以上",
    ],
    validation_method: "运行评估脚本，验证10次平均成功率",
    grading_rubric: "正确性(40%) > 收敛效果(30%) > 代码质量(20%) > 文档(10%)",
    knowledge_type: "algorithm_implementation",
    created_at: new Date().toISOString(),
  },
  {
    id: "prac-sarsa-cliffwalking",
    card_type: "practice",
    title: "SARSA vs Q-Learning悬崖行走对比实验",
    focus_area: "on_off_policy_comparison",
    target_skill: "算法对比分析能力",
    why_now: "通过对比理解on-policy和off-policy的本质差异",
    source_chain: ["SARSA算法", "Q-Learning算法", "策略对比"],
    difficulty: "easy",
    problem_statement:
      "在CliffWalking环境中分别实现SARSA和Q-Learning，完成对比实验。\n\n要求：\n1. 两种算法都使用ε-贪婪探索\n2. 记录每个episode的累计奖励和步数\n3. 可视化两种算法的学习曲线\n4. 分析最终策略的差异",
    suggested_files: ["cliff_walking.py", "sarsa_agent.py", "q_agent.py", "comparison.py"],
    api_hints: [
      "SARSA：Q(s,a) ← Q(s,a) + α[r + γ·Q(s',a') - Q(s,a)]",
      "Q-Learning：Q(s,a) ← Q(s,a) + α[r + γ·max_{a'}Q(s',a') - Q(s,a)]",
    ],
    deliverable: "两个算法的实现 + 对比可视化 + 分析报告",
    self_check: ["理解为什么Q-Learning的最终路径更靠近悬崖", "理解这与on/off-policy的关系"],
    validation_method: "运行100次评估，比较两种策略的安全性",
    grading_rubric: "分析深度(40%) > 实现正确性(30%) > 可视化质量(20%) > 报告(10%)",
    knowledge_type: "comparative_analysis",
    created_at: new Date().toISOString(),
  },
  {
    id: "prac-dqn-cartpole",
    card_type: "practice",
    title: "DQN实现CartPole平衡任务",
    focus_area: "dqn_implementation",
    target_skill: "深度强化学习工程实践",
    why_now: "DQN是深度强化学习的里程碑，理解它是进入DRL世界的门槛",
    source_chain: ["Q-Learning", "经验回放", "目标网络", "深度神经网络"],
    difficulty: "medium",
    problem_statement:
      "在CartPole-v1环境中实现DQN算法。\n\n要求：\n1. 实现经验回放缓冲区\n2. 实现目标网络\n3. 实现ε-贪婪探索\n4. 达到平均奖励195+的目标",
    suggested_files: ["dqn_agent.py", "replay_buffer.py", "network.py", "train.py"],
    api_hints: [
      "损失函数: L = MSE(Q(s,a), r + γ·Q_target(s',a*))",
      "目标网络更新: θ_target ← τ·θ + (1-τ)·θ_target",
    ],
    deliverable: "完整DQN实现 + 训练好的模型权重 + 训练曲线",
    self_check: ["经验回放是否打破数据相关性", "目标网络是否稳定训练", "是否达到性能目标"],
    validation_method: "连续10次评估，平均奖励达到195+",
    grading_rubric: "性能达标(40%) > 实现完整性(30%) > 代码质量(20%) > 分析(10%)",
    knowledge_type: "deep_rl_implementation",
    created_at: new Date().toISOString(),
  },
  {
    id: "prac-ppo-lunarlander",
    card_type: "practice",
    title: "PPO实现LunarLander安全着陆",
    focus_area: "ppo_implementation",
    target_skill: "策略优化算法工程实践",
    why_now: "PPO是目前最流行的RL算法，理解它是工程应用的基础",
    source_chain: ["策略梯度", "TRPO", "剪切代理目标", "GAE"],
    difficulty: "hard",
    problem_statement:
      "在LunarLander-v2环境中实现PPO算法。\n\n要求：\n1. 实现剪切代理目标函数\n2. 实现GAE优势估计\n3. 使用Adam优化器\n4. 达到平均奖励200+的目标",
    suggested_files: ["ppo_agent.py", "gae.py", "networks.py", "train.py"],
    api_hints: [
      "PPO目标: L = min(r(θ)·A, clip(r(θ), 1-ε, 1+ε)·A)",
      "GAE: A_t = δ_t + (γλ)δ_{t+1} + ...",
    ],
    deliverable: "PPO实现 + 训练好的策略 + 超参数对比实验",
    self_check: ["理解剪切机制如何稳定训练", "理解GAE如何平衡偏差和方差"],
    validation_method: "评估100次，计算平均奖励",
    grading_rubric: "性能(40%) > 稳定性(30%) > 代码质量(20%) > 分析(10%)",
    knowledge_type: "policy_optimization",
    created_at: new Date().toISOString(),
  },
];

// =============================================================================
// RL Flash Deck
// =============================================================================

export const rlFlashDeck = {
  id: "flash-rl-foundation",
  title: "强化学习基础概念闪记",
  description: "MDP、贝尔曼方程、Q-Learning核心概念闪记卡",
  totalCards: 6,
  masteredCount: 0,
  dueCount: 6,
  remainingCount: 6,
  cards: rlFoundationFlashcards.map((card, index) => ({
    ...card,
    id: `flash-attempt-${index + 1}`,
    cardId: `flash-card-${index + 1}`,
    attemptedAt: new Date().toISOString(),
  })),
};

// =============================================================================
// 创建 RL 训练状态的 Bootstrap Data
// =============================================================================

export function createRLTrainingBootstrapData(): Partial<BootstrapData> {
  return {
    plan: rlLearningPlan,
    flashDeck: rlFlashDeck,
    memory: {
      currentFocus: "强化学习算法完全掌握",
      weakSpots: [],
      recentWins: [],
      reviewSummary: "刚开始RL学习旅程",
      reviewRhythm: "每2天复习一次",
      dueReviews: [],
      teachingObservations: [],
      lowestMasteryConcepts: [],
      activeThread: {
        scenario: "idea_implementation",
        focusArea: "reinforcement_learning",
        summary: "系统掌握强化学习所有典型算法",
        nextStep: "从Q-Learning开始",
        blocker: undefined,
        verifiedResult: undefined,
        updatedAt: new Date().toISOString(),
      },
      memoryEvidence: [],
      learningOutcomes: [],
      dependencyMastery: [],
      workspaceUnderstanding: {
        repoSummary: "强化学习算法学习与实践",
        entryPoints: [],
        featureLanes: ["表格型RL", "深度RL", "策略优化"],
        riskZones: [],
        trainingOpportunities: ["算法实现", "对比实验", "性能优化"],
        resourceBrief: "RL学习资源",
        updated_at: new Date().toISOString(),
      },
    },
    trainingCardCandidates: rlPracticeCards,
    workspaceTrainingState: {
      workspaceId: "rl-learning",
      latestTrainingSubmode: "practice",
      dueReviews: [],
      reviewQueueActions: [],
      trainingCardCandidates: rlPracticeCards,
    },
  };
}

// =============================================================================
// 默认的 RL 对话示例
// =============================================================================

export const rlExampleConversation = [
  {
    id: "rl-m1",
    role: "assistant" as const,
    author: "Coach",
    body: "你好！我是你的强化学习教练。告诉我你想达到什么目标，我来帮你制定学习计划。",
    timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
  },
  {
    id: "rl-m2",
    role: "user" as const,
    author: "你",
    body: "我想系统地掌握强化学习，从基础到能够独立实现各类算法",
    timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
  },
  {
    id: "rl-m3",
    role: "assistant" as const,
    author: "Coach",
    body: "明白了！系统掌握强化学习是一个很有价值的目标。\n\n首先让我了解一下你的背景：\n\n**你目前的强化学习水平如何？**\n\n1. 完全零基础，只了解基本概念\n2. 有一些了解，但没有实践经验\n3. 有实践经验，想系统化提升\n4. 已经是专家水平，想深入某个细分领域",
    timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
    coachAction: {
      id: "rl-action-1",
      kind: "idle" as const,
      status: "active" as const,
      label: "收集背景信息",
      detail: "了解用户当前水平",
      timestamp: new Date().toISOString(),
    },
  },
  {
    id: "rl-m4",
    role: "user" as const,
    author: "你",
    body: "有一些了解，大概知道Q-Learning和DQN是什么，但没有亲手实现过",
    timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
  },
  {
    id: "rl-m5",
    role: "assistant" as const,
    author: "Coach",
    body: "很好！有基础认知但不缺实践经验，正是最好的学习状态。\n\n**你每周能投入多少时间学习？**\n\n1. 1-3小时/周\n2. 4-6小时/周\n3. 7-10小时/周\n4. 10+小时/周",
    timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
  },
  {
    id: "rl-m6",
    role: "user" as const,
    author: "你",
    body: "每天大概1-2小时，也就是每周7-14小时",
    timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
  },
  {
    id: "rl-m7",
    role: "assistant" as const,
    author: "Coach",
    body: "根据你的情况，我为你制定了一个 **60天强化学习掌握计划**。\n\n📊 **学习路径概览**\n\n| 阶段 | 内容 | 时间 |\n|------|------|------|\n| 第一阶段 | MDP基础、贝尔曼方程 | 1周 |\n| 第二阶段 | Q-Learning、SARSA、MC方法 | 2周 |\n| 第三阶段 | DQN及其变体 | 2周 |\n| 第四阶段 | Actor-Critic、DDPG、SAC | 2周 |\n| 第五阶段 | PPO、MCTS、高级主题 | 2周 |\n\n预计总时长：约120小时。\n\n我们从第一张练习卡开始吗？",
    timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
    suggestedActions: [
      {
        id: "start-practice",
        label: "开始第一张练习卡",
        action: "task" as const,
        rationale: "Q-Learning实现FrozenLake是巩固理论的最佳实践",
        prompt: "开始Q-Learning练习",
      },
      {
        id: "preview-plan",
        label: "查看完整学习计划",
        action: "plan" as const,
        rationale: "了解整个学习路径",
        prompt: "显示完整学习计划",
      },
    ],
  },
];

export default {
  rlLearningPlan,
  rlFoundationFlashcards,
  rlPracticeCards,
  rlFlashDeck,
  createRLTrainingBootstrapData,
  rlExampleConversation,
};
