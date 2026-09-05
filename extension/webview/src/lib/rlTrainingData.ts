/**
 * Reinforcement Learning Training Cards Data
 * 基于强化学习典型算法的真实训练卡片数据
 */

export interface RLAlgorithm {
  id: string;
  name: string;
  nameEn: string;
  category: "tabular" | "function_approximation" | "model_based" | "multi_agent" | "meta_rl";
  difficulty: "beginner" | "intermediate" | "advanced";
  coreConcept: string;
  keyEquations: string[];
  algorithms: RLAlgorithmDetail[];
}

export interface RLAlgorithmDetail {
  id: string;
  name: string;
  nameZh: string;
  category: string;
  difficulty: "easy" | "medium" | "hard";
  description: string;
  whenToUse: string;
  pros: string[];
  cons: string[];
  flashCards: FlashCard[];
  practiceCards: PracticeCard[];
}

export interface FlashCard {
  id: string;
  type: "principle" | "formula" | "concept" | "anti_pattern";
  question: string;
  expectedAnswer: string;
  hintLadder: string[];
  commonMistakes: string[];
  masteryDelta: number;
}

export interface PracticeCard {
  id: string;
  title: string;
  focusArea: string;
  targetSkill: string;
  problemStatement: string;
  suggestedFiles: string[];
  deliverable: string;
  selfCheck: string[];
  gradingRubric: string;
  difficulty: "easy" | "medium" | "hard";
}

// ============== 强化学习算法全景图 ==============

export const rlAlgorithmsData: RLAlgorithmDetail[] = [
  // ========== Tabular RL ==========
  {
    id: "q-learning",
    name: "Q-Learning",
    nameZh: "Q 学习",
    category: "tabular_mc_based",
    difficulty: "easy",
    description: "一种离线策略TD学习算法，通过贝尔曼最优方程迭代更新动作价值函数，最终收敛到最优Q值。",
    whenToUse: "状态空间和动作空间都可枚举的小规模问题，需要找到最优策略。",
    pros: ["收敛到最优策略", "离线策略学习", "实现相对简单"],
    cons: ["状态空间大时维度灾难", "对函数逼近泛化能力弱"],
    flashCards: [
      {
        id: "q-qfunc",
        type: "formula",
        question: "Q-Learning的更新公式是什么？",
        expectedAnswer: "Q(s,a) ← Q(s,a) + α[r + γ·max_a' Q(s',a') - Q(s,a)]",
        hintLadder: [
          "从当前状态和动作出发",
          "考虑即时奖励和未来价值",
          "TD目标 = r + γ·max Q(s',a')"
        ],
        commonMistakes: [
          "忘记使用max操作",
          "混淆离线/在线策略"
        ],
        masteryDelta: 0.15
      },
      {
        id: "q-offpolicy",
        type: "concept",
        question: "为什么Q-Learning是离线策略算法？",
        expectedAnswer: "因为它用贪婪策略(选择最大Q值的动作)计算TD目标，但用ε-贪婪策略生成行为策略，两者是不同的策略。",
        hintLadder: [
          "行为策略和目标策略是否相同？",
          "TD目标用什么策略选动作？",
          "行为策略用什么策略探索？"
        ],
        commonMistakes: [
          "认为只有在线策略",
          "混淆ε-贪婪和贪婪的区别"
        ],
        masteryDelta: 0.12
      },
      {
        id: "q-converge",
        type: "principle",
        question: "Q-Learning收敛的三个必要条件是什么？",
        expectedAnswer: "1. 所有状态-动作对被无限次访问 2. 学习率满足 Robbins-Monro 条件 3. 步长足够小",
        hintLadder: [
          "从探索角度",
          "从数学角度",
          "从数值稳定性角度"
        ],
        commonMistakes: [
          "只记得探索条件",
          "忽略数学条件"
        ],
        masteryDelta: 0.10
      }
    ],
    practiceCards: [
      {
        id: "prac-q-frozenlake",
        title: "用Q-Learning解决FrozenLake",
        focusArea: "tabular_rl_implementation",
        targetSkill: "Q-Learning算法实现",
        problemStatement: "在8x8 FrozenLake环境中实现Q-Learning算法，要求：1) 实现Q表更新逻辑 2) 使用ε-贪婪策略探索 3) 可视化Q值收敛过程",
        suggestedFiles: ["frozen_lake.py", "q_agent.py"],
        deliverable: "可运行的Q-Learning实现 + 收敛曲线",
        selfCheck: [
          "Q表是否正确初始化",
          "ε衰减是否合理",
          "是否收敛到最优策略"
        ],
        gradingRubric: "功能正确 > 代码简洁 > 收敛速度",
        difficulty: "easy"
      }
    ]
  },
  {
    id: "sarsa",
    name: "SARSA",
    nameZh: "SARSA",
    category: "tabular_on_policy",
    difficulty: "easy",
    description: "一种在线策略TD学习算法，使用当前策略选择的动作来计算TD目标，更保守但更安全。",
    whenToUse: "需要安全探索的在线应用，或者环境交互成本较高的场景。",
    pros: ["在线策略，符合实际部署", "更安全的探索", "方差较低"],
    cons: ["收敛到的是当前策略最优，不是全局最优"],
    flashCards: [
      {
        id: "sarsa-update",
        type: "formula",
        question: "SARSA的更新公式是什么？",
        expectedAnswer: "Q(s,a) ← Q(s,a) + α[r + γ·Q(s',a') - Q(s,a)]，其中a'是当前策略在s'选择的动作",
        hintLadder: [
          "和Q-Learning的区别在于TD目标",
          "Q-Learning用max，SARSA用什么？",
          "a'是实际选择的下一步动作"
        ],
        commonMistakes: [
          "混淆SARSA和Q-Learning",
          "忘记a'是策略决定的"
        ],
        masteryDelta: 0.15
      },
      {
        id: "sarsa-vs-q",
        type: "concept",
        question: "SARSA和Q-Learning的核心区别是什么？",
        expectedAnswer: "SARSA是在线策略，用实际采取的动作计算TD目标；Q-Learning是离线策略，用最优动作计算TD目标。",
        hintLadder: [
          "看TD目标的计算",
          "看策略一致性",
          "看收敛结果"
        ],
        commonMistakes: [
          "只记公式不记本质",
          "混淆策略概念"
        ],
        masteryDelta: 0.12
      }
    ],
    practiceCards: [
      {
        id: "prac-sarsa-cliff",
        title: "对比SARSA和Q-Learning在Cliff Walking的表现",
        focusArea: "on_off_policy_comparison",
        targetSkill: "算法对比分析",
        problemStatement: "在Cliff Walking环境中分别实现SARSA和Q-Learning，对比：1) 学习曲线 2) 最终策略安全性 3) 收敛速度",
        suggestedFiles: ["cliff_walking.py", "sarsa_agent.py", "q_agent.py"],
        deliverable: "对比实验报告 + 策略可视化",
        selfCheck: [
          "两种算法的策略是否不同",
          "哪个算法更安全",
          "原因是什么"
        ],
        gradingRubric: "分析深度 > 代码正确 > 报告质量",
        difficulty: "easy"
      }
    ]
  },
  {
    id: "dqn",
    name: "Deep Q-Network",
    nameZh: "深度Q网络",
    category: "function_approximation",
    difficulty: "medium",
    description: "用深度神经网络近似Q函数，结合经验回放和目标网络稳定训练，是深度强化学习的里程碑。",
    whenToUse: "状态空间连续或大规模离散问题，如Atari游戏、机器人控制。",
    pros: ["处理高维状态空间", "端到端学习", "超越人类水平"],
    cons: ["过度估计问题", "训练不稳定", "超参数敏感"],
    flashCards: [
      {
        id: "dqn-loss",
        type: "formula",
        question: "DQN的损失函数是什么？",
        expectedAnswer: "L(θ) = E[(r + γ·max_a' Q(s',a';θ⁻) - Q(s,a;θ))²]",
        hintLadder: [
          "MSE形式",
          "目标网络的作用",
          "max操作在哪里"
        ],
        commonMistakes: [
          "忘记目标网络",
          "混淆θ和θ⁻"
        ],
        masteryDelta: 0.15
      },
      {
        id: "dqn-exp-replay",
        type: "concept",
        question: "经验回放(Experience Replay)的作用是什么？",
        expectedAnswer: "1) 打破数据时间相关性 2) 提高样本利用率 3) 使训练更稳定",
        hintLadder: [
          "从数据角度",
          "从相关性角度",
          "从利用率角度"
        ],
        commonMistakes: [
          "只记得打破相关性",
          "忽略利用率"
        ],
        masteryDelta: 0.12
      },
      {
        id: "dqn-target-net",
        type: "concept",
        question: "为什么DQN需要目标网络(Target Network)？",
        expectedAnswer: "目标网络提供稳定的TD目标，避免训练过程中目标不断变化导致的振荡和不收敛。",
        hintLadder: [
          "如果不使用目标网络会怎样？",
          "目标网络多久更新一次？",
          "目标网络是软更新还是硬更新？"
        ],
        commonMistakes: [
          "不理解为什么需要稳定目标",
          "混淆更新频率"
        ],
        masteryDelta: 0.12
      }
    ],
    practiceCards: [
      {
        id: "prac-dqn-cartpole",
        title: "用DQN解决CartPole平衡任务",
        focusArea: "dqn_implementation",
        targetSkill: "深度强化学习实现",
        problemStatement: "在CartPole-v1环境中实现DQN，要求：1) 实现经验回放 2) 实现目标网络 3) 达到平均奖励195以上",
        suggestedFiles: ["dqn_agent.py", "replay_buffer.py", "train.py"],
        deliverable: "可运行的DQN实现 + 训练曲线 + 模型权重",
        selfCheck: [
          "经验回放是否正确实现",
          "目标网络更新频率",
          "是否达到目标性能"
        ],
        gradingRubric: "性能达标 > 代码质量 > 实现完整性",
        difficulty: "medium"
      }
    ]
  },
  {
    id: "policy-gradient",
    name: "Policy Gradient",
    nameZh: "策略梯度",
    category: "policy_based",
    difficulty: "medium",
    description: "直接对策略函数求梯度，通过梯度上升优化策略参数，适合连续动作空间。",
    whenToUse: "连续动作空间、需要随机策略、或者策略形式比价值函数更简单的场景。",
    pros: ["处理连续动作", "收敛性更好", "策略直接可解释"],
    cons: ["方差高", "收敛慢", "容易陷入局部最优"],
    flashCards: [
      {
        id: "pg-loss",
        type: "formula",
        question: "REINFORCE算法的梯度公式是什么？",
        expectedAnswer: "∇J(θ) = E[∇θ log πθ(a|s) · Gt]，其中Gt是累积回报",
        hintLadder: [
          "策略梯度定理",
          "对数概率梯度",
          "回报作为基线"
        ],
        commonMistakes: [
          "忘记log",
          "混淆G和V"
        ],
        masteryDelta: 0.18
      },
      {
        id: "pg-baseline",
        type: "concept",
        question: "为什么策略梯度算法需要引入基线(baseline)？",
        expectedAnswer: "引入基线可以减少方差而不改变期望，它通过减去一个与动作无关的函数来实现。",
        hintLadder: [
          "方差的来源是什么",
          "基线会影响梯度期望吗",
          "常用的基线是什么"
        ],
        commonMistakes: [
          "认为基线会改变最优策略",
          "选择不合适的基线"
        ],
        masteryDelta: 0.12
      }
    ],
    practiceCards: [
      {
        id: "prac-pg-pendulum",
        title: "用策略梯度控制倒立摆",
        focusArea: "policy_gradient_implementation",
        targetSkill: "连续控制",
        problemStatement: "在Pendulum-v1环境中实现REINFORCE算法，控制倒立摆达到目标角度，要求：1) 实现策略网络 2) 实现回报计算 3) 添加baseline减少方差",
        suggestedFiles: ["policy_network.py", "reinforce.py", "utils.py"],
        deliverable: "可运行的控制策略 + 对比实验",
        selfCheck: [
          "梯度计算是否正确",
          "是否添加了baseline",
          "收敛是否稳定"
        ],
        gradingRubric: "功能正确 > 收敛稳定性 > 代码质量",
        difficulty: "medium"
      }
    ]
  },
  {
    id: "ppo",
    name: "Proximal Policy Optimization",
    nameZh: "近端策略优化",
    category: "advanced_policy",
    difficulty: "hard",
    description: "通过限制策略更新幅度来稳定训练，是目前最流行的强化学习算法之一。",
    whenToUse: "需要稳定训练的各种场景，特别是需要在线学习的应用。",
    pros: ["训练稳定", "超参数鲁棒", "效果好"],
    cons: ["计算开销大", "参数调节仍需经验"],
    flashCards: [
      {
        id: "ppo-clipped",
        type: "formula",
        question: "PPO的剪切目标函数是什么？",
        expectedAnswer: "L^CLIP(θ) = E[min(r_t(θ)·A_t, clip(r_t(θ),1-ε,1+ε)·A_t)]，其中r_t是新旧策略概率比",
        hintLadder: [
          "r_t是什么",
          "clip函数的作用",
          "min操作的意义"
        ],
        commonMistakes: [
          "混淆r_t的含义",
          "不理解clip的区间"
        ],
        masteryDelta: 0.20
      },
      {
        id: "ppo-why",
        type: "concept",
        question: "PPO为什么要限制策略更新幅度？",
        expectedAnswer: "大跨度策略更新会导致性能崩溃，限制更新幅度可以保证训练稳定性。",
        hintLadder: [
          "信任域方法的核心思想",
          "大更新的风险",
          "剪切的作用"
        ],
        commonMistakes: [
          "只知其然不知其所以然",
          "混淆PPO和TRPO"
        ],
        masteryDelta: 0.15
      }
    ],
    practiceCards: [
      {
        id: "prac-ppo-halfcheetah",
        title: "用PPO训练HalfCheetah行走",
        focusArea: "ppo_implementation",
        targetSkill: "高级策略优化",
        problemStatement: "在HalfCheetah-v5环境中实现PPO算法，要求：1) 实现GAE计算优势函数 2) 实现自适应KL散度约束 3) 达到稳定行走",
        suggestedFiles: ["ppo_agent.py", "gae.py", "networks.py"],
        deliverable: "可运行的PPO实现 + 行走动画",
        selfCheck: [
          "GAE计算是否正确",
          "是否实现了KL约束",
          "训练是否稳定"
        ],
        gradingRubric: "性能 > 稳定性 > 代码质量",
        difficulty: "hard"
      }
    ]
  },
  {
    id: "ddpg",
    name: "Deep Deterministic Policy Gradient",
    nameZh: "深度确定性策略梯度",
    category: "actor_critic",
    difficulty: "medium",
    description: "结合DQN的思想和策略梯度，用于连续动作空间的深度强化学习。",
    whenToUse: "连续动作空间的控制和机器人任务。",
    pros: ["处理连续动作", "样本效率高", "稳定"],
    cons: ["对超参数敏感", "需要仔细调优"],
    flashCards: [
      {
        id: "ddpg-actor",
        type: "formula",
        question: "DDPG的Actor更新公式是什么？",
        expectedAnswer: "∇θ^μ J ≈ E[∇_a Q(s,a|θ^Q)|_{a=μ(s)} · ∇_θ^μ μ(s|θ^μ)]",
        hintLadder: [
          "策略梯度形式",
          "Q函数对动作的梯度",
          "策略对参数的梯度"
        ],
        commonMistakes: [
          "混淆actor和critic的更新",
          "忘记链式法则"
        ],
        masteryDelta: 0.18
      },
      {
        id: "ddpg-exploration",
        type: "concept",
        question: "DDPG为什么使用确定性策略？如何在确定性策略下实现探索？",
        expectedAnswer: "确定性策略无法像随机策略那样自然探索，所以DDPG在动作上添加噪声来促进探索。",
        hintLadder: [
          "确定性策略的特点",
          "探索的必要性",
          "常用的噪声类型"
        ],
        commonMistakes: [
          "认为确定性策略不需要探索",
          "混淆探索方式"
        ],
        masteryDelta: 0.12
      }
    ],
    practiceCards: [
      {
        id: "prac-ddpg-lunarlander",
        title: "用DDPG控制LunarLander着陆",
        focusArea: "continuous_control",
        targetSkill: "Actor-Critic架构",
        problemStatement: "在LunarLander-v3环境中实现DDPG算法，要求：1) 实现Actor-Critic架构 2) 实现目标网络软更新 3) 成功着陆",
        suggestedFiles: ["ddpg_agent.py", "replay_buffer.py"],
        deliverable: "可运行的DDPG实现 + 训练曲线",
        selfCheck: [
          "Actor和Critic是否独立更新",
          "软更新系数是否合适",
          "是否成功着陆"
        ],
        gradingRubric: "功能正确 > 性能 > 代码质量",
        difficulty: "medium"
      }
    ]
  },
  {
    id: "a2c-a3c",
    name: "A2C/A3C",
    nameZh: "异步优势Actor-Critic",
    category: "actor_critic_distributed",
    difficulty: "medium",
    description: "通过异步并行训练加速策略学习，平衡样本效率和训练稳定性。",
    whenToUse: "需要加速训练、计算资源充足时。",
    pros: ["训练快", "样本效率好", "稳定"],
    cons: ["实现复杂", "需要多进程/多线程"],
    flashCards: [
      {
        id: "a2c-advantage",
        type: "formula",
        question: "A2C中优势函数A(s,a)是如何计算的？",
        expectedAnswer: "A(s,a) = Q(s,a) - V(s) ≈ r + γ·V(s') - V(s)",
        hintLadder: [
          "优势的定义",
          "用V函数近似Q",
          "TD形式"
        ],
        commonMistakes: [
          "混淆A和Q",
          "忘记基线"
        ],
        masteryDelta: 0.15
      },
      {
        id: "a2c-sync",
        type: "concept",
        question: "A2C和A3C的核心区别是什么？",
        expectedAnswer: "A3C是异步的，各worker独立更新；A2C是同步的，等待所有worker完成后再更新。",
        hintLadder: [
          "同步 vs 异步",
          "更新频率",
          "效率差异"
        ],
        commonMistakes: [
          "认为A2C和A3C完全相同",
          "忽略同步开销"
        ],
        masteryDelta: 0.10
      }
    ],
    practiceCards: [
      {
        id: "prac-a2c-pong",
        title: "用A2C玩Atari Pong",
        focusArea: "actor_critic",
        targetSkill: "并行训练",
        problemStatement: "在Pong-v5环境中实现A2C算法，要求：1) 实现多环境并行 2) 实现n步回报 3) 达到人类水平",
        suggestedFiles: ["a2c_agent.py", "env_wrapper.py"],
        deliverable: "可运行的A2C实现 + 游戏表现",
        selfCheck: [
          "是否正确计算优势",
          "并行环境是否同步",
          "是否达到目标性能"
        ],
        gradingRubric: "性能 > 实现正确性 > 代码质量",
        difficulty: "medium"
      }
    ]
  },
  {
    id: "td3",
    name: "Twin Delayed DDPG",
    nameZh: "双延迟DDPG",
    category: "actor_critic_advanced",
    difficulty: "hard",
    description: "通过双Q网络和延迟更新减少Q值过度估计，是DDPG的改进版本。",
    whenToUse: "需要更稳定训练的连续控制任务。",
    pros: ["减少过度估计", "训练更稳定", "性能更好"],
    cons: ["计算开销增加", "超参数更多"],
    flashCards: [
      {
        id: "td3-clipped",
        type: "formula",
        question: "TD3使用什么技巧来减少过度估计？",
        expectedAnswer: "使用两个Q网络取最小值：y = r + γ·min(Q1(s',a'), Q2(s',a'))",
        hintLadder: [
          "过度估计的原因",
          "双网络的作用",
          "min操作的意义"
        ],
        commonMistakes: [
          "认为只是简单的平均",
          "忽略延迟更新"
        ],
        masteryDelta: 0.18
      },
      {
        id: "td3-delay",
        type: "concept",
        question: "TD3的延迟更新策略是什么？为什么需要延迟更新？",
        expectedAnswer: "Actor每更新1次，Critic更新2次。避免Actor被过时的Q值误导。",
        hintLadder: [
          "Actor和Critic的耦合",
          "更新频率的影响",
          "延迟的好处"
        ],
        commonMistakes: [
          "不理解延迟的原因",
          "混淆更新频率比例"
        ],
        masteryDelta: 0.15
      }
    ],
    practiceCards: [
      {
        id: "prac-td3-ant",
        title: "用TD3训练Ant行走",
        focusArea: "advanced_actor_critic",
        targetSkill: "连续控制优化",
        problemStatement: "在Ant-v5环境中实现TD3算法，要求：1) 实现双Q网络 2) 实现延迟更新 3) 实现目标策略平滑",
        suggestedFiles: ["td3_agent.py", "networks.py"],
        deliverable: "可运行的TD3实现 + 行走策略",
        selfCheck: [
          "双Q网络是否正确使用",
          "更新频率是否正确",
          "训练是否稳定"
        ],
        gradingRubric: "稳定性 > 性能 > 代码质量",
        difficulty: "hard"
      }
    ]
  },
  {
    id: "sac",
    name: "Soft Actor-Critic",
    nameZh: "软Actor-Critic",
    category: "max_entropy",
    difficulty: "hard",
    description: "结合最大熵原理的Actor-Critic算法，在探索和 exploitation 之间取得更好的平衡。",
    whenToUse: "需要良好探索的复杂任务，稀疏奖励问题。",
    pros: ["自动探索调节", "稳定训练", "处理稀疏奖励"],
    cons: ["熵系数调节困难", "计算复杂度高"],
    flashCards: [
      {
        id: "sac-entropy",
        type: "formula",
        question: "SAC的目标函数是什么？",
        expectedAnswer: "J(π) = E[(r + γ·(V(s') + α·H(π(·|s')))) - Q(s,a)]，其中H是策略熵",
        hintLadder: [
          "最大熵RL的形式",
          "熵的系数α",
          "熵的作用"
        ],
        commonMistakes: [
          "忽略熵项",
          "不理解熵的物理意义"
        ],
        masteryDelta: 0.20
      },
      {
        id: "sac-auto-alpha",
        type: "concept",
        question: "SAC如何自动调节熵系数α？",
        expectedAnswer: "将熵系数作为要优化的变量，在目标函数中加入熵约束，使期望熵不低于某个阈值。",
        hintLadder: [
          "手动调节的困难",
          "自动调节的目标",
          "约束条件"
        ],
        commonMistakes: [
          "认为α是固定的",
          "不理解自动调节机制"
        ],
        masteryDelta: 0.15
      }
    ],
    practiceCards: [
      {
        id: "prac-sac-halfcheetah",
        title: "用SAC训练HalfCheetah行走",
        focusArea: "max_entropy_rl",
        targetSkill: "熵正则化RL",
        problemStatement: "在HalfCheetah-v5环境中实现SAC算法，要求：1) 实现熵正则化 2) 实现自动α调节 3) 实现双Q网络",
        suggestedFiles: ["sac_agent.py", "replay_buffer.py"],
        deliverable: "可运行的SAC实现 + 对比实验",
        selfCheck: [
          "熵项是否正确加入",
          "α是否自动调节",
          "探索是否充分"
        ],
        gradingRubric: "探索充分性 > 性能 > 代码质量",
        difficulty: "hard"
      }
    ]
  },
  {
    id: "mcts",
    name: "Monte Carlo Tree Search",
    nameZh: "蒙特卡洛树搜索",
    category: "model_based",
    difficulty: "medium",
    description: "通过蒙特卡洛模拟和树搜索的结合，在不确定环境下做出最优决策。",
    whenToUse: "完美或近似完美的环境模型，如棋类游戏、规划问题。",
    pros: ["可解释性强", "适合有模型场景", "不需要价值函数近似"],
    cons: ["计算量大", "需要环境模型", "不直接适合连续控制"],
    flashCards: [
      {
        id: "mcts-four-steps",
        type: "concept",
        question: "MCTS的四个步骤是什么？",
        expectedAnswer: "1. Selection: 从根节点选择最优子节点 2. Expansion: 添加新子节点 3. Simulation: 从新节点模拟到终止 4. Backpropagation: 回溯更新统计信息",
        hintLadder: [
          "树遍历阶段",
          "新节点生成",
          "结果回传"
        ],
        commonMistakes: [
          "混淆各步骤顺序",
          "遗漏某一步骤"
        ],
        masteryDelta: 0.15
      },
      {
        id: "mcts-ucb",
        type: "formula",
        question: "MCTS的UCB1公式是什么？",
        expectedAnswer: "UCB1 = Q(v) / N(v) + c · sqrt(ln(N(parent)) / N(v))，其中c是探索常数",
        hintLadder: [
          "利用项和探索项",
          "探索常数的作用",
          "为什么用对数"
        ],
        commonMistakes: [
          "混淆分子分母",
          "忘记开根号"
        ],
        masteryDelta: 0.12
      }
    ],
    practiceCards: [
      {
        id: "prac-mcts-gobang",
        title: "用MCTS实现五子棋AI",
        focusArea: "mcts_implementation",
        targetSkill: "树搜索算法",
        problemStatement: "实现一个五子棋AI，使用MCTS作为搜索算法，要求：1) 实现UCB1选择 2) 实现快速模拟 3) 实现并行搜索",
        suggestedFiles: ["mcts.py", "game.py", "uct.py"],
        deliverable: "可运行的五子棋AI + 对弈演示",
        selfCheck: [
          "UCB1计算是否正确",
          "模拟策略是否合理",
          "是否能战胜简单AI"
        ],
        gradingRubric: "AI水平 > 代码质量 > 性能",
        difficulty: "medium"
      }
    ]
  }
];

// ============== 强化学习核心概念卡片 ==============

export const rlCoreConcepts: FlashCard[] = [
  {
    id: "core-mdp",
    type: "concept",
    question: "马尔可夫决策过程(MDP)的五元组是什么？",
    expectedAnswer: "(S, A, P, R, γ)：状态空间、动作空间、转移概率、奖励函数、折扣因子",
    hintLadder: [
      "描述环境的元素",
      "描述决策的元素",
      "描述学习的元素"
    ],
    commonMistakes: [
      "遗漏某个元素",
      "混淆转移概率和奖励"
    ],
    masteryDelta: 0.10
  },
  {
    id: "core-bellman",
    type: "formula",
    question: "贝尔曼方程的核心思想是什么？",
    expectedAnswer: "当前时刻的价值等于即时奖励加上下一步价值的折扣：V(s) = E[r + γ·V(s')]",
    hintLadder: [
      "递归形式",
      "未来价值折现",
      "期望的意义"
    ],
    commonMistakes: [
      "忘记折扣因子",
      "混淆期望和确定性"
    ],
    masteryDelta: 0.15
  },
  {
    id: "core-on-off",
    type: "concept",
    question: "在线策略和离线策略的核心区别是什么？",
    expectedAnswer: "在线策略用当前策略生成的数据训练，离线策略可以用任意数据训练。",
    hintLadder: [
      "数据来源",
      "策略一致性",
      "例子对比"
    ],
    commonMistakes: [
      "认为在线一定更好",
      "混淆策略类型"
    ],
    masteryDelta: 0.12
  },
  {
    id: "core-exploration",
    type: "concept",
    question: "为什么强化学习需要探索？有哪些探索策略？",
    expectedAnswer: "为了发现更优策略，需要尝试未知动作。策略包括：ε-贪婪、softmax、UCB、熵正则化等。",
    hintLadder: [
      "探索的目的",
      "exploitation vs exploration",
      "常用方法"
    ],
    commonMistakes: [
      "只记一种方法",
      "不理解探索-利用权衡"
    ],
    masteryDelta: 0.10
  }
];

// ============== 学习路径 ==============

export const rlLearningPath = [
  {
    stage: 1,
    title: "基础概念",
    topics: ["MDP", "贝尔曼方程", "策略与价值函数", "在线/离线策略"],
    prerequisite: "概率论基础",
    estimatedHours: 8
  },
  {
    stage: 2,
    title: "表格型RL",
    topics: ["Q-Learning", "SARSA", "时序差分学习", "蒙特卡洛方法"],
    prerequisite: "基础概念",
    estimatedHours: 12
  },
  {
    stage: 3,
    title: "深度强化学习基础",
    topics: ["DQN", "经验回放", "目标网络", "策略梯度"],
    prerequisite: "深度学习 + 表格型RL",
    estimatedHours: 20
  },
  {
    stage: 4,
    title: "高级策略优化",
    topics: ["DDPG", "TD3", "SAC", "PPO"],
    prerequisite: "深度强化学习基础",
    estimatedHours: 24
  },
  {
    stage: 5,
    title: "高级主题",
    topics: ["蒙特卡洛树搜索", "多智能体RL", "元学习", "模型预测控制"],
    prerequisite: "高级策略优化",
    estimatedHours: 32
  }
];

export default {
  rlAlgorithmsData,
  rlCoreConcepts,
  rlLearningPath
};