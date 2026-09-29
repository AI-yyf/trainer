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
// §十五: coach engine copy in eight languages (no zh/en binary).
// The zh-CN source string is the record key; {domain} / {question} / {reason} /
// {weeks} are positional slots filled by the caller with .replace().
// =============================================================================

const COACH_ENGINE_TEXT: Record<string, Record<ComposerLanguage, string>> = {
  "我是你的学习教练。告诉我你想学什么，或者你现在在哪方面想提升？": {
    "zh-CN": "我是你的学习教练。告诉我你想学什么，或者你现在在哪方面想提升？",
    "en-US": "I'm your learning coach. Tell me what you want to learn, or where you'd like to improve.",
    "es-ES": "Soy tu coach de aprendizaje. Dime qué quieres aprender o en qué área quieres mejorar.",
    "fr-FR": "Je suis votre coach d’apprentissage. Dites-moi ce que vous voulez apprendre ou où vous souhaitez progresser.",
    "de-DE": "Ich bin dein Lerncoach. Sag mir, was du lernen willst oder wo du dich verbessern möchtest.",
    "ja-JP": "私はあなたの学習コーチです。何を学びたいか、どの分野を伸ばしたいか教えてください。",
    "ko-KR": "저는 학습 코치입니다. 무엇을 배우고 싶은지, 어느 부분을 향상시키고 싶은지 알려주세요.",
    "pt-BR": "Sou o seu coach de aprendizagem. Diga-me o que você quer aprender ou onde quer melhorar.",
  },
  "明白了，你想学习{domain}。{question}\n\n{reason}": {
    "zh-CN": "明白了，你想学习{domain}。{question}\n\n{reason}",
    "en-US": "Got it, you want to learn {domain}. {question}\n\n{reason}",
    "es-ES": "Entendido, quieres aprender {domain}. {question}\n\n{reason}",
    "fr-FR": "Bien compris, vous voulez apprendre {domain}. {question}\n\n{reason}",
    "de-DE": "Verstanden, du möchtest {domain} lernen. {question}\n\n{reason}",
    "ja-JP": "わかりました。{domain} を学びたいのですね。{question}\n\n{reason}",
    "ko-KR": "알겠습니다. {domain}을(를) 배우고 싶으시군요. {question}\n\n{reason}",
    "pt-BR": "Entendido, você quer aprender {domain}. {question}\n\n{reason}",
  },
  "这个领域": {
    "zh-CN": "这个领域",
    "en-US": "this topic",
    "es-ES": "este tema",
    "fr-FR": "ce sujet",
    "de-DE": "dieses Thema",
    "ja-JP": "この分野",
    "ko-KR": "이 주제",
    "pt-BR": "este tópico",
  },
  "根据你的情况，我会帮你制定一个适合你的学习计划。预计需要{weeks}周时间。": {
    "zh-CN": "根据你的情况，我会帮你制定一个适合你的学习计划。预计需要{weeks}周时间。",
    "en-US": "Based on your situation, I'll create a learning plan for you. Estimated time: {weeks} weeks.",
    "es-ES": "Según tu situación, crearé un plan de aprendizaje adecuado para ti. Tiempo estimado: {weeks} semanas.",
    "fr-FR": "D’après votre situation, je vais élaborer un plan d’apprentissage adapté. Durée estimée : {weeks} semaines.",
    "de-DE": "Basierend auf deiner Situation erstelle ich einen passenden Lernplan für dich. Geschätzte Zeit: {weeks} Wochen.",
    "ja-JP": "あなたの状況に合わせて学習プランを作成します。予想所要期間：{weeks} 週間。",
    "ko-KR": "상황에 맞는 학습 계획을 만들어 드리겠습니다. 예상 기간: {weeks}주.",
    "pt-BR": "Com base na sua situação, criarei um plano de aprendizagem adequado para você. Tempo estimado: {weeks} semanas.",
  },
  "我们开始制定具体的学习计划吗？": {
    "zh-CN": "我们开始制定具体的学习计划吗？",
    "en-US": "Shall we start creating your learning plan?",
    "es-ES": "¿Empezamos a crear tu plan de aprendizaje?",
    "fr-FR": "Commençons à élaborer votre plan d’apprentissage ?",
    "de-DE": "Sollen wir mit der Erstellung deines Lernplans beginnen?",
    "ja-JP": "具体的な学習プランの作成を始めましょうか？",
    "ko-KR": "구체적인 학습 계획 만들기를 시작할까요?",
    "pt-BR": "Vamos começar a criar seu plano de aprendizagem?",
  },
  "好的，让我为你生成学习计划...": {
    "zh-CN": "好的，让我为你生成学习计划...",
    "en-US": "Alright, let me create your learning plan...",
    "es-ES": "De acuerdo, déjame crear tu plan de aprendizaje...",
    "fr-FR": "Très bien, laissez-moi créer votre plan d’apprentissage...",
    "de-DE": "In Ordnung, ich erstelle deinen Lernplan...",
    "ja-JP": "わかりました。学習プランを作成します...",
    "ko-KR": "좋아요, 학습 계획을 만들어 드릴게요...",
    "pt-BR": "Certo, deixe-me criar seu plano de aprendizagem...",
  },
  "我需要更多信息来帮你制定学习计划。请告诉我你想学什么？": {
    "zh-CN": "我需要更多信息来帮你制定学习计划。请告诉我你想学什么？",
    "en-US": "I need more information to help you create a learning plan. What would you like to learn?",
    "es-ES": "Necesito más información para ayudarte a crear un plan de aprendizaje. ¿Qué te gustaría aprender?",
    "fr-FR": "J’ai besoin de plus d’informations pour vous aider à créer un plan d’apprentissage. Que souhaitez-vous apprendre ?",
    "de-DE": "Ich brauche mehr Informationen, um dir bei einem Lernplan zu helfen. Was möchtest du lernen?",
    "ja-JP": "学習プランを作るにはもっと情報が必要です。何を学びたいですか？",
    "ko-KR": "학습 계획을 세우려면 정보가 더 필요합니다. 무엇을 배우고 싶으신가요?",
    "pt-BR": "Preciso de mais informações para ajudar você a criar um plano de aprendizagem. O que você gostaria de aprender?",
  },
  "正在了解你的学习目标": {
    "zh-CN": "正在了解你的学习目标",
    "en-US": "Understanding your learning goals",
    "es-ES": "Entendiendo tus objetivos de aprendizaje",
    "fr-FR": "Compréhension de vos objectifs d’apprentissage",
    "de-DE": "Lernziele werden erfasst",
    "ja-JP": "学習目標を把握しています",
    "ko-KR": "학습 목표 파악 중",
    "pt-BR": "Entendendo seus objetivos de aprendizagem",
  },
  "正在分析你的情况": {
    "zh-CN": "正在分析你的情况",
    "en-US": "Analyzing your situation",
    "es-ES": "Analizando tu situación",
    "fr-FR": "Analyse de votre situation",
    "de-DE": "Deine Situation wird analysiert",
    "ja-JP": "あなたの状況を分析しています",
    "ko-KR": "상황 분석 중",
    "pt-BR": "Analisando sua situação",
  },
  "正在生成学习计划": {
    "zh-CN": "正在生成学习计划",
    "en-US": "Creating your learning plan",
    "es-ES": "Creando tu plan de aprendizaje",
    "fr-FR": "Création de votre plan d’apprentissage",
    "de-DE": "Lernplan wird erstellt",
    "ja-JP": "学習プランを作成しています",
    "ko-KR": "학습 계획 생성 중",
    "pt-BR": "Criando seu plano de aprendizagem",
  },
  "正在执行学习计划": {
    "zh-CN": "正在执行学习计划",
    "en-US": "Executing learning plan",
    "es-ES": "Ejecutando el plan de aprendizaje",
    "fr-FR": "Exécution du plan d’apprentissage",
    "de-DE": "Lernplan wird ausgeführt",
    "ja-JP": "学習プランを実行しています",
    "ko-KR": "학습 계획 실행 중",
    "pt-BR": "Executando o plano de aprendizagem",
  },
  "正在调整计划": {
    "zh-CN": "正在调整计划",
    "en-US": "Adapting plan",
    "es-ES": "Adaptando el plan",
    "fr-FR": "Adaptation du plan",
    "de-DE": "Plan wird angepasst",
    "ja-JP": "プランを調整しています",
    "ko-KR": "계획 조정 중",
    "pt-BR": "Adaptando o plano",
  },
  "已完成当前阶段": {
    "zh-CN": "已完成当前阶段",
    "en-US": "Current stage completed",
    "es-ES": "Etapa actual completada",
    "fr-FR": "Étape actuelle terminée",
    "de-DE": "Aktuelle Phase abgeschlossen",
    "ja-JP": "現在のステージが完了しました",
    "ko-KR": "현재 단계 완료",
    "pt-BR": "Etapa atual concluída",
  },
  "准备中": {
    "zh-CN": "准备中",
    "en-US": "Preparing",
    "es-ES": "Preparando",
    "fr-FR": "Préparation",
    "de-DE": "Wird vorbereitet",
    "ja-JP": "準備中",
    "ko-KR": "준비 중",
    "pt-BR": "Preparando",
  },
};

function coachEngineCopy(language: ComposerLanguage, key: string): string {
  return COACH_ENGINE_TEXT[key]?.[language] ?? COACH_ENGINE_TEXT[key]?.["en-US"] ?? key;
}

/**
 * §十五: plan-confirmation keyword detection per composer language. The zh and
 * en lists keep the original single-token behavior; the other locales add
 * their own confirmations on top of the shared English token.
 */
const PLAN_CONFIRM_KEYWORDS: Record<ComposerLanguage, string[]> = {
  "zh-CN": ["开始"],
  "en-US": ["start"],
  "es-ES": ["start", "empezar", "comenzar"],
  "fr-FR": ["start", "commencer", "démarrer"],
  "de-DE": ["start", "starten", "beginnen"],
  "ja-JP": ["start", "開始", "はじめる"],
  "ko-KR": ["start", "시작"],
  "pt-BR": ["start", "começar", "iniciar"],
};

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

  // Phase 1: 收集用户信息
  if (state.phase === "intake") {
    // 首次对话，提取学习意图
    const { intent, goal } = extractLearningIntent(userMessage, language);

    if (intent === "general") {
      return {
        message: coachEngineCopy(
          language,
          "我是你的学习教练。告诉我你想学什么，或者你现在在哪方面想提升？",
        ),
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
        message: coachEngineCopy(language, "明白了，你想学习{domain}。{question}\n\n{reason}")
          .replace("{domain}", goal?.domain || coachEngineCopy(language, "这个领域"))
          .replace("{question}", questionText)
          .replace("{reason}", question.reason),
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
      coachJudgment: coachEngineCopy(
        language,
        "根据你的情况，我会帮你制定一个适合你的学习计划。预计需要{weeks}周时间。",
      ).replace("{weeks}", String(weeks)),
      clarifyingQuestions: [],
    };

    state.diagnosis = diagnosis;
    state.learnerProfile = {
      relatedExperience: [levelMap[levelIndex]],
      timeAvailability: hoursMap[hoursIndex],
    };

    return {
      message:
        diagnosis.coachJudgment +
        "\n\n" +
        coachEngineCopy(language, "我们开始制定具体的学习计划吗？"),
      action: { type: "present_diagnosis", diagnosis },
      data: { diagnosis },
      newState: state,
    };
  }

  // Phase 3: 生成计划（当用户确认时）
  const confirmKeywords = PLAN_CONFIRM_KEYWORDS[language] ?? PLAN_CONFIRM_KEYWORDS["en-US"];
  if (state.phase === "diagnosis" && confirmKeywords.some((keyword) => userMessage.includes(keyword))) {
    state.phase = "planning";
    return {
      message: coachEngineCopy(language, "好的，让我为你生成学习计划..."),
      newState: state,
    };
  }

  // 默认回复
  return {
    message: coachEngineCopy(
      language,
      "我需要更多信息来帮你制定学习计划。请告诉我你想学什么？",
    ),
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
  switch (state.phase) {
    case "intake":
      return coachEngineCopy(language, "正在了解你的学习目标");
    case "diagnosis":
      return coachEngineCopy(language, "正在分析你的情况");
    case "planning":
      return coachEngineCopy(language, "正在生成学习计划");
    case "executing":
      return coachEngineCopy(language, "正在执行学习计划");
    case "adapting":
      return coachEngineCopy(language, "正在调整计划");
    case "completed":
      return coachEngineCopy(language, "已完成当前阶段");
    default:
      return coachEngineCopy(language, "准备中");
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
