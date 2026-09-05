/**
 * RL Training Plan - 强化学习完整学习路径
 *
 * 本计划围绕"掌握强化学习所有典型算法"这一核心目标设计
 * 参考 Spaced Repetition 原理，确保长期记忆和深度理解
 */

import type { LearningPlan, PlanStage, FlashcardAttempt, TrainingCardCandidateSnapshot } from "../lib/types";

// =============================================================================
// 核心元数据
// =============================================================================

export const rlPlanMeta = {
  id: "rl-mastery-plan",
  title: "强化学习算法完全掌握",
  subtitle: "从基础概念到高级算法，构建完整的RL知识体系",
  estimatedTotalHours: 120,
  targetAudience: "希望深入掌握强化学习的AI工程师和研究人员",
  prerequisites: ["概率论基础", "微积分基础", "Python编程能力", "深度学习基础"],
  learningGoal: "能够独立实现、调试和优化各类RL算法，理解其数学原理和工程实践"
};

// =============================================================================
// 五阶段学习路径
// =============================================================================

export const rlLearningStages: PlanStage[] = [
  {
    id: "stage-1-foundation",
    title: "第一阶段：强化学习基础",
    objective: "掌握MDP、贝尔曼方程、策略与价值函数等核心概念",
    status: "active"
  },
  {
    id: "stage-2-tabular-rl",
    title: "第二阶段：表格型强化学习",
    objective: "精通Q-Learning、SARSA、蒙特卡洛方法等基础算法",
    status: "queued"
  },
  {
    id: "stage-3-deep-rl",
    title: "第三阶段：深度强化学习",
    objective: "掌握DQN及其变体，理解经验回放和目标网络",
    status: "queued"
  },
  {
    id: "stage-4-policy-optimization",
    title: "第四阶段：策略优化算法",
    objective: "精通Actor-Critic、DDPG、TD3、SAC等连续控制算法",
    status: "queued"
  },
  {
    id: "stage-5-advanced",
    title: "第五阶段：高级主题",
    objective: "掌握PPO、MCTS、多智能体RL、元学习等高级主题",
    status: "queued"
  }
];

// =============================================================================
// 第一阶段：基础概念闪卡
// =============================================================================

export const rlFoundationFlashcards: Omit<FlashcardAttempt, "id" | "cardId" | "attemptedAt">[] = [
  // MDP基础
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "马尔可夫决策过程(MDP)的五元组是什么？",
    expectedAnswer: "(S, A, P, R, γ)：状态空间S、动作空间A、转移概率P(s'|s,a)、奖励函数R(s,a)、折扣因子γ",
    hintLadder: [
      "MDP描述了智能体与环境交互的框架",
      "包含描述环境的元素（状态、动作、转移）",
      "包含描述决策的元素（奖励）和学习参数（折扣）"
    ],
    commonMistakes: [
      "遗漏转移概率P",
      "混淆奖励函数和价值函数",
      "不理解折扣因子的作用"
    ],
    mastery_delta: 0.10
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "formula",
    question: "写出贝尔曼期望方程和贝尔曼最优方程",
    expectedAnswer: "期望方程: V^π(s) = Σ_a π(a|s) Σ_{s',r} p(s',r|s,a)[r + γV^π(s')]\n最优方程: V*(s) = max_a Σ_{s',r} p(s',r|s,a)[r + γV*(s')]",
    hintLadder: [
      "期望方程描述给定策略下的价值",
      "最优方程描述最优策略的价值",
      "关键区别：期望 vs 最大"
    ],
    commonMistakes: [
      "混淆两个方程",
      "忘记折扣因子",
      "忘记对动作求期望或最大化"
    ],
    mastery_delta: 0.15
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "策略梯度方法与价值方法的核心区别是什么？",
    expectedAnswer: "价值方法学习状态或动作的价值函数，再间接得到策略；策略方法直接优化策略函数本身。",
    hintLadder: [
      "价值方法：学什么是最好的",
      "策略方法：直接学怎么做",
      "Actor-Critic结合两者优点"
    ],
    commonMistakes: [
      "认为两者可以完全互换",
      "不理解on/off-policy与策略/价值的关系"
    ],
    mastery_delta: 0.12
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "什么是折扣因子γ？为什么需要折扣因子？",
    expectedAnswer: "γ∈[0,1]表示未来奖励的重要性。γ=1时同等重视所有未来奖励；γ<1时更重视即时奖励，帮助算法收敛并处理无限 horizon。",
    hintLadder: [
      "从数学角度：保证无限求和收敛",
      "从心理学角度：模拟即时奖励偏好",
      "从实践角度：平衡探索与利用"
    ],
    commonMistakes: [
      "选择不当的折扣因子",
      "不理解γ对算法行为的影响"
    ],
    mastery_delta: 0.08
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "on-policy和off-policy的核心区别是什么？请举例说明",
    expectedAnswer: "on-policy：用于生成数据的策略与正在学习的策略相同（如SARSA）。off-policy：两者不同（如Q-Learning使用ε-贪婪生成数据但学习贪婪策略）。",
    hintLadder: [
      "关键在于数据来源",
      "on-policy更保守但sample efficient低",
      "off-policy可以用历史数据"
    ],
    commonMistakes: [
      "混淆策略类型",
      "认为off-policy一定更好"
    ],
    mastery_delta: 0.12
  },
  {
    status: "unanswered",
    answer: "",
    correct: false,
    knowledgeType: "concept",
    question: "什么是探索-利用困境(Exploration-Exploitation Tradeoff)？有哪些解决方法？",
    expectedAnswer: "探索：尝试新动作获取信息；利用：使用已知最优动作最大化奖励。解决方法：ε-贪婪、softmax/boltzmann、UCB、熵正则化。",
    hintLadder: [
      "从定义出发",
      "考虑探索的必要性",
      "了解各种方法的特点"
    ],
    commonMistakes: [
      "只记一种方法",
      "不理解何时需要更多探索"
    ],
    mastery_delta: 0.10
  }
];

// =============================================================================
// 第二阶段：表格型RL训练卡片
// =============================================================================

export const rlTabularRLPracticeCards: TrainingCardCandidateSnapshot[] = [
  {
    id: "prac-q-learning-frozenlake",
    card_type: "practice",
    title: "Q-Learning实现FrozenLake环境",
    focus_area: "tabular_rl_implementation",
    target_skill: "Q-Learning算法实现与调试",
    why_now: "Q-Learning是理解强化学习的第一步，是后续所有算法的基础",
    source_chain: ["MDP基础", "贝尔曼方程", "TD学习"],
    difficulty: "easy",
    problem_statement: "在FrozenLake-8x8环境中实现Q-Learning算法。\n\n要求：\n1. 正确初始化Q表（可用零初始化或随机初始化）\n2. 实现ε-贪婪探索策略，支持衰减\n3. 正确实现TD更新公式\n4. 训练10000个episodes，评估最终策略\n5. 可视化学习曲线",
    suggested_files: ["frozen_lake.py", "q_agent.py", "visualization.py"],
    api_hints: [
      "Q(s,a) ← Q(s,a) + α[r + γ·max_{a'}Q(s',a') - Q(s,a)]",
      "np.argmax(q_values) 获取最优动作",
      "ε衰减：epsilon = max(epsilon_min, epsilon * epsilon_decay)"
    ],
    deliverable: "完整可运行的Q-Learning实现 + 训练日志 + 收敛曲线",
    self_check: [
      "Q表更新是否正确使用了TD目标",
      "ε-贪婪是否正确实现",
      "最终成功率是否达到80%以上"
    ],
    validation_method: "运行评估脚本，验证10次平均成功率",
    grading_rubric: "正确性(40%) > 收敛效果(30%) > 代码质量(20%) > 文档(10%)",
    knowledge_type: "algorithm_implementation",
    created_at: new Date().toISOString()
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
    problem_statement: "在CliffWalking环境中分别实现SARSA和Q-Learning，完成对比实验。\n\n要求：\n1. 两种算法都使用ε-贪婪探索\n2. 记录每个episode的累计奖励和步数\n3. 可视化两种算法的学习曲线\n4. 分析最终策略的差异（为什么Q-Learning的策略更危险？）\n5. 撰写分析报告",
    suggested_files: ["cliff_walking.py", "sarsa_agent.py", "q_agent.py", "comparison.py"],
    api_hints: [
      "SARSA使用实际采取的下一步动作更新：Q(s,a) ← Q(s,a) + α[r + γ·Q(s',a') - Q(s,a)]",
      "Q-Learning使用最优动作更新：Q(s,a) ← Q(s,a) + α[r + γ·max_{a'}Q(s',a') - Q(s,a)]",
      "关键差异：SARSA考虑探索，Q-Learning直接学最优"
    ],
    deliverable: "两个算法的实现 + 对比可视化 + 分析报告",
    self_check: [
      "理解为什么Q-Learning的最终路径更靠近悬崖",
      "理解这与on/off-policy的关系"
    ],
    validation_method: "运行100次评估，比较两种策略的安全性",
    grading_rubric: "分析深度(40%) > 实现正确性(30%) > 可视化质量(20%) > 报告(10%)",
    knowledge_type: "comparative_analysis",
    created_at: new Date().toISOString()
  },
  {
    id: "prac-monte-carlo",
    card_type: "practice",
    title: "蒙特卡洛方法实现21点游戏",
    focus_area: "monte_carlo_methods",
    target_skill: "蒙特卡洛估计与控制",
    why_now: "蒙特卡洛方法是理解model-free RL的重要基础",
    source_chain: ["蒙特卡洛估计", "广义策略迭代", "ε-贪婪控制"],
    difficulty: "medium",
    problem_statement: "用蒙特卡洛方法实现21点游戏的AI策略。\n\n要求：\n1. 实现First-Visit MC和Every-Visit MC两种估计方法\n2. 使用ε-贪婪和GLIE（Greedy in the Limit with Infinite Exploration）\n3. 比较两种MC方法的学习曲线\n4. 展示学习到的策略（如庄家需要多少点停牌）",
    suggested_files: ["blackjack.py", "mc_control.py", "policy_visualization.py"],
    api_hints: [
      "MC估计：V(s) ≈ 平均(返回(s))",
      "GLIE：ε_t = 1/t 逐渐衰减到0",
      "策略评估 → 策略改进 循环"
    ],
    deliverable: "21点游戏环境 + MC控制实现 + 策略可视化",
    self_check: [
      "理解MC方法与TD方法的区别",
      "理解为什么MC需要完整的episode"
    ],
    validation_method: "评估学习策略的胜率",
    grading_rubric: "实现正确性(50%) > 理解深度(30%) > 可视化(20%)",
    knowledge_type: "algorithm_implementation",
    created_at: new Date().toISOString()
  }
];

// =============================================================================
// 第三阶段：深度强化学习训练卡片
// =============================================================================

export const rlDeepRLPracticeCards: TrainingCardCandidateSnapshot[] = [
  {
    id: "prac-dqn-cartpole",
    card_type: "practice",
    title: "DQN实现CartPole平衡任务",
    focus_area: "dqn_implementation",
    target_skill: "深度强化学习工程实践",
    why_now: "DQN是深度强化学习的里程碑，理解它是进入DRL世界的门槛",
    source_chain: ["Q-Learning", "经验回放", "目标网络", "深度神经网络"],
    difficulty: "medium",
    problem_statement: "在CartPole-v1环境中实现DQN算法。\n\n要求：\n1. 实现经验回放缓冲区（固定容量，支持采样）\n2. 实现目标网络（每N步硬更新或软更新）\n3. 实现ε-贪婪探索，支持衰减\n4. 达到连续100个episode平均奖励195+的目标\n5. 绘制训练曲线和目标Q值变化图",
    suggested_files: ["dqn_agent.py", "replay_buffer.py", "network.py", "train.py"],
    api_hints: [
      "损失函数: L = MSE(Q(s,a), r + γ·Q_target(s',a*))",
      "目标网络更新: θ_target ← τ·θ + (1-τ)·θ_target",
      "经验存储: (s, a, r, s', done)"
    ],
    deliverable: "完整DQN实现 + 训练好的模型权重 + 训练曲线",
    self_check: [
      "经验回放是否打破数据相关性",
      "目标网络是否稳定训练",
      "是否达到性能目标"
    ],
    validation_method: "连续10次评估，平均奖励达到195+",
    grading_rubric: "性能达标(40%) > 实现完整性(30%) > 代码质量(20%) > 分析(10%)",
    knowledge_type: "deep_rl_implementation",
    created_at: new Date().toISOString()
  },
  {
    id: "prac-dqn-atarigames",
    card_type: "practice",
    title: "DQN玩Atari Breakout游戏",
    focus_area: "dqn_highdimensional",
    target_skill: "处理高维观测空间",
    why_now: "Atari游戏是检验DRL算法的标准基准",
    source_chain: ["DQN", "图像预处理", "卷积神经网络"],
    difficulty: "hard",
    problem_statement: "用DQN在Atari Breakout游戏中达到人类水平。\n\n要求：\n1. 实现图像预处理（灰度化、下采样、帧堆叠）\n2. 使用卷积神经网络作为Q函数逼近器\n3. 实现自适应ε-贪婪（后期减少探索）\n4. 达到专业人类水平（400+分）的目标\n5. 可视化学习过程中的策略变化",
    suggested_files: ["dqn.py", "atari_wrapper.py", "cnn.py", "train.py"],
    api_hints: [
      "图像预处理：84x84灰度图，4帧堆叠",
      "目标网络更新频率：10000步",
      "优先经验回放(可选)：基于TD误差优先级采样"
    ],
    deliverable: "DQN实现 + 预训练模型 + 游戏录像",
    self_check: [
      "网络架构是否适合图像输入",
      "探索策略是否合理"
    ],
    validation_method: "评估30分钟游戏表现",
    grading_rubric: "性能(50%) > 实现正确性(30%) > 代码质量(20%)",
    knowledge_type: "advanced_deep_rl",
    created_at: new Date().toISOString()
  }
];

// =============================================================================
// 第四阶段：策略优化算法训练卡片
// =============================================================================

export const rlPolicyOptimizationCards: TrainingCardCandidateSnapshot[] = [
  {
    id: "prac-ppo-lunarlander",
    card_type: "practice",
    title: "PPO实现LunarLander安全着陆",
    focus_area: "ppo_implementation",
    target_skill: "策略优化算法工程实践",
    why_now: "PPO是目前最流行的RL算法，理解它是工程应用的基础",
    source_chain: ["策略梯度", "TRPO", "剪切代理目标", "GAE"],
    difficulty: "hard",
    problem_statement: "在LunarLander-v2环境中实现PPO算法。\n\n要求：\n1. 实现剪切代理目标函数（PPO-Clip）\n2. 实现GAE(λ)优势估计\n3. 使用Adam优化器，支持学习率调度\n4. 达到连续100次平均奖励200+的目标\n5. 对比不同超参数（ε、λ、γ）的影响",
    suggested_files: ["ppo_agent.py", "gae.py", "networks.py", "train.py"],
    api_hints: [
      "PPO目标: L = min(r(θ)·A, clip(r(θ), 1-ε, 1+ε)·A)",
      "r(θ) = π_θ(a|s) / π_θ_old(a|s)",
      "GAE: A_t = δ_t + (γλ)δ_{t+1} + ... + (γλ)^{T-t}δ_T"
    ],
    deliverable: "PPO实现 + 训练好的策略 + 超参数对比实验",
    self_check: [
      "理解剪切机制如何稳定训练",
      "理解GAE如何平衡偏差和方差"
    ],
    validation_method: "评估100次，计算平均奖励",
    grading_rubric: "性能(40%) > 稳定性(30%) > 代码质量(20%) > 分析(10%)",
    knowledge_type: "policy_optimization",
    created_at: new Date().toISOString()
  },
  {
    id: "prac-sac-ant",
    card_type: "practice",
    title: "SAC实现Ant四足行走",
    focus_area: "max_entropy_rl",
    target_skill: "最大熵RL与自动熵调节",
    why_now: "SAC在连续控制任务中表现优异，是机器人控制的首选算法",
    source_chain: ["Actor-Critic", "最大熵RL", "软策略迭代"],
    difficulty: "hard",
    problem_statement: "在Ant-v5环境中实现SAC算法。\n\n要求：\n1. 实现双Q网络和熵正则化\n2. 实现自动熵调节（调整α使熵达到目标值）\n3. 使用平滑策略（squashing functions）\n4. 达到平均奖励3000+的目标\n5. 可视化训练过程中的策略演化",
    suggested_files: ["sac_agent.py", "replay_buffer.py", "networks.py"],
    api_hints: [
      "SAC目标：max_π E[(r + γ·(V(s') + α·H(π)))]",
      "自动α：优化 log(α) 目标熵",
      "双Q取min减少过度估计"
    ],
    deliverable: "SAC实现 + 训练好的策略 + 行走动画",
    self_check: [
      "理解熵正则化如何促进探索",
      "理解自动熵调节的优势"
    ],
    validation_method: "评估50次，计算平均奖励",
    grading_rubric: "性能(40%) > 探索充分性(30%) > 代码质量(20%) > 分析(10%)",
    knowledge_type: "max_entropy_rl",
    created_at: new Date().toISOString()
  }
];

// =============================================================================
// 第五阶段：高级主题训练卡片
// =============================================================================

export const rlAdvancedTopicCards: TrainingCardCandidateSnapshot[] = [
  {
    id: "prac-mcts-gobang",
    card_type: "practice",
    title: "MCTS实现五子棋AI",
    focus_area: "mcts_implementation",
    target_skill: "树搜索与蒙特卡洛模拟",
    why_now: "MCTS是AlphaGo的核心技术，理解它对于博弈类AI至关重要",
    source_chain: ["蒙特卡洛模拟", "UCT", "树搜索"],
    difficulty: "medium",
    problem_statement: "实现一个五子棋AI，使用MCTS作为搜索算法。\n\n要求：\n1. 实现UCB1公式：UCB = Q/N + c√(ln(N_parent)/N)\n2. 实现Selection、Expansion、Simulation、Backpropagation四步\n3. 实现快速模拟策略\n4. AI能够战胜简单规则AI\n5. 可视化搜索树（可选）",
    suggested_files: ["mcts.py", "game.py", "uct.py", "policy.py"],
    api_hints: [
      "UCB探索常数c通常取√2",
      "Simulation使用快速随机策略",
      "每个节点存储(N, Q)统计量"
    ],
    deliverable: "五子棋游戏 + MCTS AI + 对弈演示",
    self_check: [
      "UCB公式是否正确",
      "是否正确更新统计量"
    ],
    validation_method: "与随机AI和规则AI对弈",
    grading_rubric: "AI水平(50%) > 实现正确性(30%) > 代码质量(20%)",
    knowledge_type: "tree_search",
    created_at: new Date().toISOString()
  },
  {
    id: "prac-imagination-augmented",
    card_type: "practice",
    title: "I2A想象力增强智能体",
    focus_area: "model_based_rl",
    target_skill: "基于模型的RL与想象力模块",
    why_now: "I2A展示了如何结合模型预测和模型无关RL的优势",
    source_chain: ["基于模型的RL", "世界模型", "想象力rollout"],
    difficulty: "hard",
    problem_statement: "在迷宫环境中实现I2A（ Imagination-Augmented Agent）算法。\n\n要求：\n1. 实现环境模型（观察预测、奖励预测）\n2. 实现想象力模块（生成模拟rollout）\n3. 结合真实经验和小样本想象力rollout\n4. 对比I2A与纯模型无关方法（如A2C）的性能",
    suggested_files: ["i2a_agent.py", "env_model.py", "imagination.py"],
    api_hints: [
      "环境模型: p(o_{t+1}|h_t, a_t), p(r_t|h_t, a_t)",
      "想象力模块: 从当前隐状态预测未来",
      "组合真实和想象的特征"
    ],
    deliverable: "I2A实现 + 迷宫环境 + 对比实验",
    self_check: [
      "理解基于模型vs模型无关的权衡",
      "理解想象力的作用"
    ],
    validation_method: "样本效率对比",
    grading_rubric: "理解深度(40%) > 实现正确性(30%) > 对比分析(30%)",
    knowledge_type: "model_based_rl",
    created_at: new Date().toISOString()
  }
];

// =============================================================================
// 算法对比总览
// =============================================================================

export const rlAlgorithmComparison = {
  overview: {
    tabular: {
      algorithms: ["Q-Learning", "SARSA", "Monte Carlo", "TD(λ)"],
      pros: ["收敛性保证", "易于理解", "无需函数逼近"],
      cons: ["维度灾难", "无法处理连续状态"],
      bestFor: "状态空间小且离散的问题"
    },
    valueApproximation: {
      algorithms: ["DQN", "Double DQN", "Prioritized DQN", "Dueling DQN"],
      pros: ["可处理高维状态", "端到端学习"],
      cons: ["训练不稳定", "过度估计问题"],
      bestFor: "Atari游戏、视觉输入"
    },
    policyGradient: {
      algorithms: ["REINFORCE", "Actor-Critic", "A2C/A3C"],
      pros: ["处理连续动作", "收敛性更好"],
      cons: ["方差高", "采样效率低"],
      bestFor: "连续控制任务"
    },
    advancedPolicyOptimization: {
      algorithms: ["DDPG", "TD3", "SAC", "PPO", "TRPO"],
      pros: ["稳定高效", "超参数鲁棒"],
      cons: ["实现复杂", "计算开销大"],
      bestFor: "机器人控制、复杂连续任务"
    },
    modelBased: {
      algorithms: ["MCTS", "World Models", "Dreamer", "I2A"],
      pros: ["样本效率高", "可解释性强"],
      cons: ["模型误差累积", "训练难度大"],
      bestFor: "棋类游戏、规划任务"
    }
  }
};

// =============================================================================
// 完整的RL学习计划
// =============================================================================

export const rlMasteryPlan: LearningPlan = {
  id: "rl-mastery-plan",
  title: "强化学习算法完全掌握",
  frozen: false,
  cadence: "每天2小时，持续60天",
  summary: "通过系统的理论学习和密集的实战练习，全面掌握从基础概念到高级算法的强化学习知识体系。",
  stages: rlLearningStages,
  currentStageId: "stage-1-foundation",
  sessionId: "rl-session-001",
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString()
};

// =============================================================================
// 导出所有训练数据
// =============================================================================

export const rlTrainingData = {
  meta: rlPlanMeta,
  plan: rlMasteryPlan,
  foundationFlashcards: rlFoundationFlashcards,
  tabularRLCards: rlTabularRLPracticeCards,
  deepRLCards: rlDeepRLPracticeCards,
  policyOptimizationCards: rlPolicyOptimizationCards,
  advancedTopicCards: rlAdvancedTopicCards,
  algorithmComparison: rlAlgorithmComparison
};

export default rlTrainingData;
