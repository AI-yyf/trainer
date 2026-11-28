import { trainerCommands } from "../../../../shared/src/commands";
import { resolveCopy } from "./i18n/copy";
import type {
  ActiveWorkbenchView,
  BootstrapData,
  ComposerLanguage,
  LearningPlan,
  PlanRuntimeStatus,
  PlanStage,
  ResourceRecord,
  TaskSpec,
  TrainerWorkspaceAdmission,
  WebviewAction,
} from "./types";

export type BrowserPreviewBootstrap = BootstrapData & {
  hasFormalPlan?: boolean;
  activeView?: ActiveWorkbenchView;
};

export type BrowserPreviewPatch = Partial<BootstrapData> & {
  hasFormalPlan?: boolean;
};

export type BrowserPreviewActionResult = {
  patch?: BrowserPreviewPatch;
  tone: "info" | "success" | "error";
  message: string;
};

type PreviewActionCopy = {
  planTitle: (goal: string) => string;
  planSummary: string;
  firstStage: string;
  firstObjective: (goal: string) => string;
  secondStage: string;
  secondObjective: (goal: string) => string;
  thirdStage: string;
  thirdObjective: (goal: string) => string;
  verification: string;
  nextAfterCurrent: string;
  generateSucceeded: string;
  planFrozen: string;
  planResumed: string;
  missingPlan: string;
  taskReady: (stage: string) => string;
  resourceOpened: (title: string) => string;
  resourcesRefreshed: (count: number) => string;
  trainingCardReady: string;
  unsupported: string;
  evaluateCurrentFileMissing: string;
  fallbackGoal: string;
  continueInCoach: string;
  localPreviewTaskConstraint: string;
};

const EN_PREVIEW_ACTION_COPY: PreviewActionCopy = {
  planTitle: (goal) => `Learning path for "${goal}"`,
  planSummary: "Start with one finishable outcome, then practice, verify, and reflect.",
  firstStage: "Define a first-week outcome",
  firstObjective: (goal) => `Write one visible outcome you can finish this week for "${goal}".`,
  secondStage: "Complete one small practice",
  secondObjective: (goal) => `Use a short practice to move "${goal}" into a state you can show.`,
  thirdStage: "Verify and reflect",
  thirdObjective: (goal) => `Verify the result for "${goal}" and record what to adjust next time.`,
  verification: "You can name the first-week outcome, how to verify it, and your available time.",
  nextAfterCurrent: "Return to Coach with the result, then shape the next step.",
  generateSucceeded: "A local preview plan was created from your current goal.",
  planFrozen: "The preview plan is frozen; normal conversation will not rewrite it.",
  planResumed: "The preview plan is editable again.",
  missingPlan: "Create a plan from your goal first.",
  taskReady: (stage) => `The current task is ready: "${stage}".`,
  resourceOpened: (title) => `Located "${title}" in the preview. Use VS Code to open the full resource.`,
  resourcesRefreshed: (count) => `Refreshed local preview status for ${count} resource${count === 1 ? "" : "s"}. Run real file indexing in VS Code.`,
  trainingCardReady: "A local demo training card is ready. It does not change the real workspace.",
  unsupported: "This browser preview action does not change real data. Continue in the VS Code sidebar.",
  evaluateCurrentFileMissing:
    "The browser preview has no current IDE file. Open the file in VS Code, then use Verify current file there.",
  fallbackGoal: "your current learning goal",
  continueInCoach: "Continue in Coach",
  localPreviewTaskConstraint: "This is a local browser-preview task and does not change a real workspace.",
};

const ZH_PREVIEW_ACTION_COPY: PreviewActionCopy = {
  planTitle: (goal) => `\u56f4\u7ed5\u201c${goal}\u201d\u7684\u5b66\u4e60\u8def\u5f84`,
  planSummary: "\u6559\u7ec3\u521a\u521a\u5148\u5b8c\u6210\u4e00\u4e2a\u53ef\u4ea4\u4ed8\u7ed3\u679c\uff0c\u518d\u7ec3\u4e60\u3001\u9a8c\u8bc1\u548c\u590d\u76d8\u3002",
  firstStage: "\u5b9a\u4e49\u7b2c\u4e00\u5468\u7ed3\u679c",
  firstObjective: (goal) => `\u4e3a\u201c${goal}\u201d\u5199\u4e0b\u672c\u5468\u80fd\u5b8c\u6210\u7684\u4e00\u4e2a\u53ef\u89c1\u7ed3\u679c\u3002`,
  secondStage: "\u5b8c\u6210\u4e00\u6b21\u5c0f\u7ec3\u4e60",
  secondObjective: (goal) => `\u7528\u4e00\u6b21\u77ed\u7ec3\u4e60\u628a\u201c${goal}\u201d\u63a8\u8fdb\u5230\u53ef\u5c55\u793a\u72b6\u6001\u3002`,
  thirdStage: "\u9a8c\u8bc1\u5e76\u590d\u76d8",
  thirdObjective: (goal) => `\u9a8c\u8bc1\u201c${goal}\u201d\u7684\u7ed3\u679c\uff0c\u5e76\u8bb0\u5f55\u4e0b\u6b21\u8981\u8c03\u6574\u7684\u5730\u65b9\u3002`,
  verification: "\u4f60\u80fd\u8bf4\u6e05\u7b2c\u4e00\u5468\u7ed3\u679c\u3001\u9a8c\u8bc1\u65b9\u5f0f\u548c\u53ef\u7528\u65f6\u95f4\u3002",
  nextAfterCurrent: "\u5e26\u7740\u7ed3\u679c\u56de\u5230 Coach\uff0c\u518d\u786e\u5b9a\u4e0b\u4e00\u6b65\u3002",
  generateSucceeded: "\u5df2\u6839\u636e\u5f53\u524d\u76ee\u6807\u521b\u5efa\u672c\u5730\u9884\u89c8\u8ba1\u5212\u3002",
  planFrozen: "\u9884\u89c8\u8ba1\u5212\u5df2\u51bb\u7ed3\uff1b\u666e\u901a\u5bf9\u8bdd\u4e0d\u4f1a\u6539\u5199\u5b83\u3002",
  planResumed: "\u9884\u89c8\u8ba1\u5212\u5df2\u6062\u590d\u53ef\u7f16\u8f91\u3002",
  missingPlan: "\u8bf7\u5148\u6839\u636e\u76ee\u6807\u521b\u5efa\u8ba1\u5212\u3002",
  taskReady: (stage) => `\u5f53\u524d\u4efb\u52a1\u5df2\u51c6\u5907\u597d\uff1a\u201c${stage}\u201d\u3002`,
  resourceOpened: (title) => `\u5df2\u5728\u9884\u89c8\u4e2d\u5b9a\u4f4d\u201c${title}\u201d\u3002\u5b8c\u6574\u8d44\u6e90\u8bf7\u5728 VS Code \u4e2d\u6253\u5f00\u3002`,
  resourcesRefreshed: (count) => `\u5df2\u5237\u65b0 ${count} \u4e2a\u8d44\u6599\u7684\u672c\u5730\u9884\u89c8\u72b6\u6001\u3002\u771f\u5b9e\u6587\u4ef6\u7d22\u5f15\u8bf7\u5728 VS Code \u4e2d\u6267\u884c\u3002`,
  trainingCardReady: "\u672c\u5730\u9884\u89c8\u8bad\u7ec3\u5361\u5df2\u51c6\u5907\u597d\uff0c\u4e0d\u4f1a\u4fee\u6539\u771f\u5b9e\u5de5\u4f5c\u533a\u3002",
  unsupported: "\u6b64\u6d4f\u89c8\u5668\u9884\u89c8\u64cd\u4f5c\u4e0d\u4f1a\u4fee\u6539\u771f\u5b9e\u6570\u636e\u3002\u8bf7\u56de\u5230 VS Code \u4fa7\u680f\u7ee7\u7eed\u3002",
  evaluateCurrentFileMissing:
    "\u6d4f\u89c8\u5668\u9884\u89c8\u4e2d\u6ca1\u6709\u5f53\u524d IDE \u6587\u4ef6\u3002\u8bf7\u5148\u5728 VS Code \u4e2d\u6253\u5f00\u8be5\u6587\u4ef6\uff0c\u518d\u5728\u90a3\u91cc\u4f7f\u7528\u201c\u9a8c\u8bc1\u5f53\u524d\u6587\u4ef6\u201d\u3002",
  fallbackGoal: "\u5f53\u524d\u5b66\u4e60\u76ee\u6807",
  continueInCoach: "\u56de\u5230 Coach",
  localPreviewTaskConstraint: "\u6d4f\u89c8\u5668\u9884\u89c8\u53ea\u66f4\u65b0\u6f14\u793a\u72b6\u6001\uff1b\u771f\u5b9e\u6587\u4ef6\u548c\u5de5\u4f5c\u533a\u64cd\u4f5c\u8bf7\u5728 VS Code \u4e2d\u5b8c\u6210\u3002",
};

const PREVIEW_ACTION_COPY: Record<ComposerLanguage, PreviewActionCopy> = {
  "zh-CN": ZH_PREVIEW_ACTION_COPY,
  "en-US": EN_PREVIEW_ACTION_COPY,
  "es-ES": EN_PREVIEW_ACTION_COPY,
  "fr-FR": EN_PREVIEW_ACTION_COPY,
  "de-DE": EN_PREVIEW_ACTION_COPY,
  "ja-JP": EN_PREVIEW_ACTION_COPY,
  "ko-KR": EN_PREVIEW_ACTION_COPY,
  "pt-BR": EN_PREVIEW_ACTION_COPY,
};

function copyFor(language: ComposerLanguage): PreviewActionCopy {
  return PREVIEW_ACTION_COPY[language] ?? PREVIEW_ACTION_COPY["en-US"];
}

/** §十五: flash-card fixture copy in eight languages (no zh/en binary). */
const BROWSER_PREVIEW_FLASH_TEXT: Record<string, Record<ComposerLanguage, string>> = {
  "每周练习 3 次": {
    "zh-CN": "每周练习 3 次",
    "en-US": "3 times per week",
    "es-ES": "3 veces por semana",
    "fr-FR": "3 fois par semaine",
    "de-DE": "3-mal pro Woche",
    "ja-JP": "週 3 回練習する",
    "ko-KR": "주 3회 연습",
    "pt-BR": "3 vezes por semana",
  },
  "回顾当前学习目标的一条关键规则": {
    "zh-CN": "回顾当前学习目标的一条关键规则",
    "en-US": "Recall one key rule for the current learning goal",
    "es-ES": "Recuerda una regla clave del objetivo de aprendizaje actual",
    "fr-FR": "Rappelez une règle clé de l’objectif d’apprentissage actuel",
    "de-DE": "Erinnere dich an eine Kernregel des aktuellen Lernziels",
    "ja-JP": "現在の学習目標の重要なルールを 1 つ思い出す",
    "ko-KR": "현재 학습 목표의 핵심 규칙 하나 떠올리기",
    "pt-BR": "Lembre uma regra chave do objetivo de aprendizagem atual",
  },
  "用自己的话解释“{goal}”中的一条关键规则，并给出一个小例子。": {
    "zh-CN": "用自己的话解释“{goal}”中的一条关键规则，并给出一个小例子。",
    "en-US": "Explain one key rule for \"{goal}\" in your own words and give one small example.",
    "es-ES": "Explica con tus palabras una regla clave de \"{goal}\" y da un ejemplo pequeño.",
    "fr-FR": "Expliquez avec vos mots une règle clé de « {goal} » et donnez un petit exemple.",
    "de-DE": "Erkläre eine Kernregel von \"{goal}\" in deinen Worten und gib ein kleines Beispiel.",
    "ja-JP": "「{goal}」の重要なルールを 1 つ自分の言葉で説明し、小さな例を 1 つ挙げてください。",
    "ko-KR": "\"{goal}\" 의 핵심 규칙 하나를 자신의 말로 설명하고 작은 예시를 하나 들어 주세요.",
    "pt-BR": "Explique com suas palavras uma regra chave de \"{goal}\" e dê um pequeno exemplo.",
  },
  "这是本地浏览器预览训练卡，不会修改真实工作区。": {
    "zh-CN": "这是本地浏览器预览训练卡，不会修改真实工作区。",
    "en-US": "This is a local browser-preview training card and does not change a real workspace.",
    "es-ES": "Esta es una tarjeta de entrenamiento local de la vista previa del navegador y no cambia un workspace real.",
    "fr-FR": "Il s’agit d’une carte d’entraînement locale de l’aperçu navigateur ; elle ne modifie pas un workspace réel.",
    "de-DE": "Dies ist eine lokale Browser-Vorschau-Trainingskarte und ändert keinen echten Workspace.",
    "ja-JP": "これはブラウザプレビューのローカル訓練カードであり、実際のワークスペースは変更しません。",
    "ko-KR": "이것은 브라우저 미리보기의 로컬 훈련 카드이며 실제 워크스페이스를 변경하지 않습니다.",
    "pt-BR": "Este é um cartão de treino local de pré-visualização no navegador e não altera um workspace real.",
  },
  "先完成这一张卡，再扩展练习。": {
    "zh-CN": "先完成这一张卡，再扩展练习。",
    "en-US": "Finish this one card before expanding the practice.",
    "es-ES": "Termina esta tarjeta antes de ampliar la práctica.",
    "fr-FR": "Terminez cette carte avant d’élargir la pratique.",
    "de-DE": "Schließe diese Karte ab, bevor du die Übung ausbaust.",
    "ja-JP": "まずこの 1 枚を完成させてから、練習を広げましょう。",
    "ko-KR": "이 카드 한 장을 먼저 끝낸 뒤 연습을 넓히세요.",
    "pt-BR": "Termine este cartão antes de ampliar a prática.",
  },
  "先把这张卡做成一个可验证的结果，再继续。": {
    "zh-CN": "先把这张卡做成一个可验证的结果，再继续。",
    "en-US": "Make this card concrete first, then continue.",
    "es-ES": "Haz concreta esta tarjeta primero y luego continúa.",
    "fr-FR": "Rendez d’abord cette carte concrète, puis continuez.",
    "de-DE": "Mache diese Karte zuerst konkret, dann fahre fort.",
    "ja-JP": "まずこのカードを検証できる結果にしましょう。そのあと続けます。",
    "ko-KR": "먼저 이 카드를 검증 가능한 결과로 만든 뒤 계속하세요.",
    "pt-BR": "Torne este cartão concreto primeiro e depois continue.",
  },
};

function browserPreviewFlashCopy(language: ComposerLanguage, key: string): string {
  return (
    BROWSER_PREVIEW_FLASH_TEXT[key]?.[language] ??
    BROWSER_PREVIEW_FLASH_TEXT[key]?.["en-US"] ??
    key
  );
}

export type BrowserPreviewCoachCopy = Pick<
  PreviewActionCopy,
  | "planSummary"
  | "generateSucceeded"
  | "missingPlan"
  | "taskReady"
  | "verification"
  | "nextAfterCurrent"
  | "continueInCoach"
  | "fallbackGoal"
>;

export function browserPreviewCoachCopy(language: ComposerLanguage): BrowserPreviewCoachCopy {
  return copyFor(language);
}

function cleanText(value: string | undefined): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized || undefined;
}

export function resolveBrowserPreviewGoal(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
): string {
  const profileGoals = Array.isArray(bootstrap.profile?.goals) ? bootstrap.profile.goals : [];
  const candidates = [
    bootstrap.coachFocus?.currentFocus,
    bootstrap.memory?.activeThread?.focusArea,
    profileGoals.find((goal) => cleanText(goal)),
  ];
  for (const candidate of candidates) {
    const goal = cleanText(candidate);
    if (goal) {
      return goal;
    }
  }
  return copyFor(language).fallbackGoal;
}

export function buildGoalAwarePreviewPlan(
  goal: string,
  language: ComposerLanguage,
): LearningPlan {
  const copy = copyFor(language);
  const stages: PlanStage[] = [
    {
      id: "browser-preview-plan-first-outcome",
      title: copy.firstStage,
      objective: copy.firstObjective(goal),
      status: "active",
    },
    {
      id: "browser-preview-plan-small-practice",
      title: copy.secondStage,
      objective: copy.secondObjective(goal),
      status: "queued",
    },
    {
      id: "browser-preview-plan-verify-reflect",
      title: copy.thirdStage,
      objective: copy.thirdObjective(goal),
      status: "queued",
    },
  ];
  return {
    id: "browser-preview-goal-plan",
    title: copy.planTitle(goal),
    frozen: false,
    cadence: browserPreviewFlashCopy(language, "每周练习 3 次"),
    summary: copy.planSummary,
    stages,
    currentStageId: stages[0].id,
    currentStep: stages[0].objective,
    whyNow: copy.planSummary,
    verifyMethod: [copy.verification],
    nextAfterCurrent: copy.nextAfterCurrent,
  };
}

function buildPreviewPlanRuntime(
  goal: string,
  plan: LearningPlan,
): PlanRuntimeStatus {
  const currentStage = plan.stages.find((stage) => stage.id === plan.currentStageId) ?? plan.stages[0];
  return {
    currentStage: currentStage
      ? {
          id: currentStage.id,
          title: currentStage.title,
          goal: currentStage.objective,
          status: currentStage.status,
        }
      : undefined,
    currentMainThread: {
      scenario: "onboarding",
      focusArea: goal,
      summary: plan.summary,
      nextStep: currentStage?.objective,
      currentStep: plan.currentStep,
      whyNow: plan.whyNow,
      verifyMethod: plan.verifyMethod,
      nextAfterCurrent: plan.nextAfterCurrent,
    },
    reviewPoints: [],
    currentStep: plan.currentStep,
    whyNow: plan.whyNow,
    verifyMethod: plan.verifyMethod,
    nextAfterCurrent: plan.nextAfterCurrent,
    nextTrainingAction: currentStage?.objective,
  };
}

function buildPreviewTask(plan: LearningPlan, language: ComposerLanguage): TaskSpec {
  const currentStage =
    plan.stages.find((stage) => stage.id === plan.currentStageId) ??
    plan.stages.find((stage) => stage.status === "active") ??
    plan.stages[0];
  const copy = copyFor(language);
  return {
    id: `browser-preview-task-${currentStage?.id ?? "current"}`,
    title: currentStage?.title ?? copy.firstStage,
    description: currentStage?.objective ?? plan.currentStep ?? copy.planSummary,
    constraints: [copy.localPreviewTaskConstraint],
    acceptanceCriteria: plan.verifyMethod?.length ? [...plan.verifyMethod] : [copy.verification],
    nextActionLabel: copy.continueInCoach,
  };
}

function commandIdForAction(action: WebviewAction): string | undefined {
  if (action.type === "command/execute") {
    return action.payload.commandId;
  }
  if (action.type === "plan/generate") {
    return trainerCommands.generatePlan;
  }
  if (action.type === "plan/freeze") {
    return trainerCommands.updatePlan;
  }
  if (action.type === "task/next") {
    return trainerCommands.nextTask;
  }
  if (action.type === "resource/open") {
    return trainerCommands.openResource;
  }
  return undefined;
}

function hasFormalPreviewPlan(bootstrap: BrowserPreviewBootstrap): boolean {
  if (typeof bootstrap.hasFormalPlan === "boolean") {
    return bootstrap.hasFormalPlan;
  }
  return Boolean(
    cleanText(bootstrap.plan?.id) &&
      Array.isArray(bootstrap.plan?.stages) &&
      bootstrap.plan.stages.length > 0,
  );
}

export function buildGoalAwarePreviewPlanPatch(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
  explicitGoal?: string,
): BrowserPreviewPatch {
  const goal = cleanText(explicitGoal) ?? resolveBrowserPreviewGoal(bootstrap, language);
  const plan = buildGoalAwarePreviewPlan(goal, language);
  const profile = bootstrap.profile;
  const existingGoals = Array.isArray(profile?.goals) ? profile.goals : [];
  return {
    plan,
    hasFormalPlan: true,
    profile: {
      learnerName: profile?.learnerName ?? "",
      goals: [goal, ...existingGoals.filter((item) => cleanText(item) && item !== goal)],
      weeklyHours: profile?.weeklyHours ?? 3,
      preferredStyle: profile?.preferredStyle ?? "guided",
      answerPolicy: profile?.answerPolicy ?? "auto",
      focusAreas: profile?.focusAreas ?? [],
      targetProject: profile?.targetProject,
      preferredRhythm: profile?.preferredRhythm,
      preferredLearningMode: profile?.preferredLearningMode,
      onboardingRequest: profile?.onboardingRequest,
      projectContext: profile?.projectContext,
    },
    task: buildPreviewTask(plan, language),
    planRuntimeStatus: buildPreviewPlanRuntime(goal, plan),
  };
}

function updatePlanFreezePatch(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
  frozen: boolean,
): BrowserPreviewPatch | undefined {
  if (!hasFormalPreviewPlan(bootstrap)) {
    return undefined;
  }
  const goal = resolveBrowserPreviewGoal(bootstrap, language);
  const plan = { ...bootstrap.plan, frozen };
  return {
    plan,
    hasFormalPlan: true,
    planRuntimeStatus: buildPreviewPlanRuntime(goal, plan),
  };
}

function refreshResourcesPatch(bootstrap: BrowserPreviewBootstrap): BrowserPreviewPatch {
  const now = new Date().toISOString();
  const resources = (bootstrap.resources ?? []).map((resource) => ({
    ...resource,
    status: "ready" as const,
    indexState: "indexed",
    freshness: "fresh" as const,
    updatedAt: now,
  }));
  return {
    resources,
    memory: {
      ...bootstrap.memory,
      sandboxState: bootstrap.memory?.sandboxState
        ? {
            ...bootstrap.memory.sandboxState,
            lastUpdatedAt: now,
          }
        : bootstrap.memory?.sandboxState,
    },
  };
}

function requestedPreviewTrainingCardType(action: WebviewAction): "practice" | "flash" {
  if (action.type !== "command/execute" || !action.payload.payload || typeof action.payload.payload !== "object") {
    return "practice";
  }
  const payload = action.payload.payload;
  const requestedCardType = "cardType" in payload ? payload.cardType : undefined;
  const requestedSubmode = "submode" in payload ? payload.submode : undefined;
  return requestedCardType === "flash" || requestedSubmode === "flash" ? "flash" : "practice";
}

function buildPreviewTrainingCardPatch(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
  cardType: "practice" | "flash",
): BrowserPreviewPatch | undefined {
  const copy = copyFor(language);
  const goal = resolveBrowserPreviewGoal(bootstrap, language);
  const isFlash = cardType === "flash";
  const flashTitle = browserPreviewFlashCopy(language, "回顾当前学习目标的一条关键规则");
  const title = isFlash ? flashTitle : copy.secondStage;
  const taskDescription = isFlash
    ? browserPreviewFlashCopy(
        language,
        "用自己的话解释“{goal}”中的一条关键规则，并给出一个小例子。",
      ).replace("{goal}", goal)
    : copy.secondObjective(goal);
  const cardId = `browser-preview-${isFlash ? "flash" : "practice"}-card`;
  const card = {
    cardId,
    type: cardType,
    title,
    whyNow: copy.planSummary,
    learningFamily: isFlash ? "theory" as const : "code" as const,
    focusArea: goal,
    targetSkill: goal,
    scenario: taskDescription,
    problemStatement: taskDescription,
    suggestedWorkspaceAction: taskDescription,
    constraints: [
      browserPreviewFlashCopy(language, "这是本地浏览器预览训练卡，不会修改真实工作区。"),
    ],
    deliverable: taskDescription,
    selfCheck: [copy.verification],
    validationMethod: copy.verification,
    learnerDeliverables: [taskDescription],
    verificationSteps: [copy.verification],
    successSignal: copy.taskReady(title),
    expectedSymbols: [],
    filesToTouch: [],
    hintLadder: [copy.firstObjective(goal), taskDescription],
    commonMistakes: [copy.planSummary],
    stuckRecovery: copy.firstObjective(goal),
    reflectionPrompt: copy.nextAfterCurrent,
    returnWith: copy.nextAfterCurrent,
    nextAfterCompletion: copy.nextAfterCurrent,
  };
  const nextCard = {
    ...card,
    cardId: `browser-preview-${isFlash ? "practice" : "flash"}-next-card`,
    type: isFlash ? "practice" as const : "flash" as const,
    title: isFlash ? copy.secondStage : flashTitle,
  };
  const candidateType = cardType === "flash" ? "flash_candidate" : "practice_candidate";
  const nextCandidateType = nextCard.type === "flash" ? "flash_candidate" : "practice_candidate";
  const now = new Date().toISOString();

  return {
    task: {
      ...bootstrap.task,
      id: `browser-preview-training-${cardId}`,
      title: card.title,
      description: taskDescription,
      constraints: card.constraints,
      acceptanceCriteria: card.learnerDeliverables,
      nextActionLabel: copy.nextAfterCurrent,
    },
    memory: {
      ...bootstrap.memory,
      currentFocus: card.focusArea,
      reviewSummary: copy.planSummary,
    },
    coachingState: {
      ...bootstrap.coachingState,
      scenario: "task",
      answerMode: "guided",
      learnerSignal: "curious",
      summary: copy.taskReady(card.title),
      nextStep: card.suggestedWorkspaceAction || taskDescription,
      encouragement: browserPreviewFlashCopy(language, "先完成这一张卡，再扩展练习。"),
      updatedAt: now,
    },
    coachTurn: {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "curious",
      summary: copy.taskReady(card.title),
      nextStep: card.suggestedWorkspaceAction || taskDescription,
      encouragement: browserPreviewFlashCopy(language, "先把这张卡做成一个可验证的结果，再继续。"),
      activeTask: card.title,
      artifactKinds: ["task"],
      suggestedActionTypes: ["task"],
      backgroundMode: "embedded",
    },
    workspaceTrainingState: {
      ...bootstrap.workspaceTrainingState,
      workspaceId: "trainer-preview",
      selectedCardId: card.cardId,
      selectedCardType: card.type,
      selectedCardTitle: card.title,
      selectedCardStatus: "active",
      latestTrainingSubmode: cardType === "flash" ? "flash" : "practice",
      latestLearningFocusArea: card.focusArea,
      trainingCardCandidates: [card],
      activeTrainingCardRouting: {
        selectedCardId: card.cardId,
        selectedCard: card,
        whyThisCard: card.whyNow,
        fallbackAction: card.stuckRecovery,
        nextAfterCompletion: card.nextAfterCompletion,
        candidateCount: 1,
        eligibleCount: 1,
      },
      latestTrainingHandoff: {
        handoffId: `browser-preview-${card.cardId}-handoff`,
        candidateId: cardId,
        candidateType,
        targetKind: "training_card",
        targetId: cardId,
        continueIn: "training",
        acceptedInto: "training",
        handoffStatus: "accepted",
        handoffSummary: card.whyNow,
        cardType: card.type,
        cardTitle: card.title,
        learnerDeliverables: card.learnerDeliverables,
        verificationSteps: card.verificationSteps,
        successSignal: card.successSignal,
        returnWith: card.returnWith,
        nextAfterCompletion: card.nextAfterCompletion,
        judgedAt: now,
        sourceChain: ["browser-preview"],
      },
      latestTrainingNextHop: {
        candidateId: nextCard.cardId,
        candidateType: nextCandidateType,
        title: nextCard.title,
        summary: nextCard.problemStatement || nextCard.deliverable,
        whyNow: nextCard.whyNow,
        continueIn: "training",
        targetKind: "training_card",
        targetId: nextCard.cardId,
        acceptedInto: "training",
        status: "surfaced",
        cardType: nextCard.type,
        cardTitle: nextCard.title,
        returnSummary: nextCard.returnWith,
        judgedAt: now,
        sourceChain: ["browser-preview"],
      },
    },
  };
}

type PreviewTrainingCardContext = {
  cardId: string;
  cardTitle: string;
  cardType: "practice" | "flash";
  focusArea: string;
  handoffId: string;
  returnWith: string;
  nextAfterCompletion: string;
  sourceChain: string[];
};

type PreviewTrainingActionOptions = {
  eventType: string;
  summary: string;
  detail: string;
  selectedCardStatus: string;
  nextStep: string;
  coachScenario: "task" | "review";
  learnerSignal?: "steady" | "blocked" | "uncertain" | "curious";
  verifiedResult?: string;
  followup?: string;
  blocker?: string;
  partialProgress?: string;
  returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
  handoffStatus?: string;
  nextHopStatus?:
    | "created"
    | "surfaced"
    | "accepted"
    | "continued_in_chat"
    | "verification_required"
    | "reflection_required"
    | "return_required"
    | "dismissed"
    | "deferred"
    | "blocked"
    | "expired"
    | "archived";
  nextHopSummary?: string;
  nextHopWhyNow?: string;
  evidenceItem?: {
    id: string;
    summary: string;
    source: string;
    concepts: string[];
    outcome: string;
    confidence: number;
    timestamp: string;
    sourceCardId?: string;
    targetPlanStageId?: string;
  };
};

function resolvePreviewTrainingCardContext(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
): PreviewTrainingCardContext {
  const copy = resolveCopy(language);
  const trainingState = bootstrap.workspaceTrainingState ?? {};
  const candidate =
    trainingState.trainingCardCandidates?.find((item) => item.cardId === trainingState.selectedCardId) ??
    trainingState.activeTrainingCardRouting?.selectedCard ??
    trainingState.trainingCardCandidates?.[0];
  const goal = resolveBrowserPreviewGoal(bootstrap, language);
  const fallbackId = `browser-preview-${goal.replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "") || "training"}-card`;
  const cardId = trainingState.selectedCardId?.trim() || candidate?.cardId?.trim() || fallbackId;
  const cardTitle =
    trainingState.selectedCardTitle?.trim() ||
    candidate?.title?.trim() ||
    trainingState.latestTrainingHandoff?.cardTitle?.trim() ||
    copy.trainingOpenCurrentCard;
  const cardType = trainingState.selectedCardType ?? candidate?.type ?? "practice";
  const focusArea =
    trainingState.latestLearningFocusArea?.trim() ||
    candidate?.focusArea?.trim() ||
    goal;
  const handoffId =
    trainingState.latestTrainingHandoff?.handoffId?.trim() || `browser-preview-${cardId}-handoff`;
  const returnWith =
    trainingState.latestTrainingHandoff?.returnWith?.trim() || copy.trainingReturnToCoach;
  const nextAfterCompletion =
    trainingState.latestTrainingHandoff?.nextAfterCompletion?.trim() || copy.trainingReturnToCoach;
  const sourceChain = trainingState.latestTrainingHandoff?.sourceChain?.length
    ? [...trainingState.latestTrainingHandoff.sourceChain]
    : ["browser-preview"];

  return {
    cardId,
    cardTitle,
    cardType,
    focusArea,
    handoffId,
    returnWith,
    nextAfterCompletion,
    sourceChain,
  };
}

function buildPreviewEvidenceQueuePatch(
  bootstrap: BrowserPreviewBootstrap,
  evidenceItem: PreviewTrainingActionOptions["evidenceItem"],
): BrowserPreviewPatch {
  if (!evidenceItem) {
    return {};
  }
  const queue = bootstrap.memory?.evidenceQueue ?? {
    pending: [],
    deferred: [],
    adopted: [],
    rejected: [],
    totalCount: 0,
  };
  const pending = [
    {
      ...evidenceItem,
      sourceCardId: evidenceItem.sourceCardId,
      targetPlanStageId: evidenceItem.targetPlanStageId,
    },
    ...(queue.pending ?? []),
  ];
  return {
    memory: {
      ...bootstrap.memory,
      evidenceQueue: {
        pending,
        deferred: queue.deferred ?? [],
        adopted: queue.adopted ?? [],
        rejected: queue.rejected ?? [],
        totalCount:
          pending.length +
          (queue.deferred?.length ?? 0) +
          (queue.adopted?.length ?? 0) +
          (queue.rejected?.length ?? 0),
      },
    },
  };
}

function buildPreviewTrainingActionPatch(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
  options: PreviewTrainingActionOptions,
): BrowserPreviewPatch {
  const uiCopy = resolveCopy(language);
  const card = resolvePreviewTrainingCardContext(bootstrap, language);
  const now = new Date().toISOString();
  const summary = `Browser-preview simulation: ${options.summary}`;
  const detail = `${options.detail} This only updates the local browser-preview fixture.`;
  const followup = options.followup ?? uiCopy.trainingReturnToCoach;
  const ledgerEntry = {
    eventId: `browser-preview-${options.eventType}-${now}`,
    eventType: options.eventType,
    selectedCardId: card.cardId,
    selectedCardType: card.cardType,
    selectedCardTitle: card.cardTitle,
    learnerDeliverables: bootstrap.workspaceTrainingState?.latestTrainingHandoff?.learnerDeliverables,
    verificationSteps: bootstrap.workspaceTrainingState?.latestTrainingHandoff?.verificationSteps,
    successSignal: bootstrap.workspaceTrainingState?.latestTrainingHandoff?.successSignal,
    returnWith: card.returnWith,
    nextAfterCompletion: card.nextAfterCompletion,
    fallbackAction: bootstrap.workspaceTrainingState?.latestTrainingHandoff?.fallbackAction,
    returnMode: options.returnMode,
    returnSummary: options.followup ?? followup,
    statusSummary: summary,
    statusDetail: detail,
    candidateTargetKind: "training_card",
    candidateTargetId: card.cardId,
    candidateAcceptedInto: "training",
    candidateType: "card_invocation" as const,
    candidateTitle: card.cardTitle,
    judgedAt: now,
    createdAt: now,
    sourceChain: ["browser-preview"],
  };

  return {
    ...buildPreviewEvidenceQueuePatch(bootstrap, options.evidenceItem),
    workspaceTrainingState: {
      ...bootstrap.workspaceTrainingState,
      workspaceId: "trainer-preview",
      latestTrainingHandoff: {
        ...bootstrap.workspaceTrainingState?.latestTrainingHandoff,
        handoffId: card.handoffId,
        candidateId: card.cardId,
        candidateType: "card_invocation",
        targetKind: "training_card",
        targetId: card.cardId,
        continueIn: "training",
        acceptedInto: "training",
        handoffStatus: options.handoffStatus ?? options.selectedCardStatus,
        handoffSummary: summary,
        cardType: card.cardType,
        cardTitle: card.cardTitle,
        returnWith: card.returnWith,
        nextAfterCompletion: card.nextAfterCompletion,
        returnMode: options.returnMode,
        returnSummary: options.followup ?? followup,
        judgedAt: now,
        sourceChain: card.sourceChain,
      },
      latestTrainingNextHop: {
        ...bootstrap.workspaceTrainingState?.latestTrainingNextHop,
        candidateId: card.cardId,
        candidateType:
          options.evidenceItem !== undefined
            ? "evidence_candidate"
            : card.cardType === "flash"
              ? "flash_candidate"
              : "practice_candidate",
        title: card.cardTitle,
        summary: options.nextHopSummary ?? detail,
        whyNow: options.nextHopWhyNow ?? summary,
        continueIn: "training",
        targetKind: "training_card",
        targetId: card.cardId,
        acceptedInto: "training",
        status: options.nextHopStatus ?? "accepted",
        cardType: card.cardType,
        cardTitle: card.cardTitle,
        returnMode: options.returnMode,
        returnSummary: options.followup ?? followup,
        judgedAt: now,
        sourceChain: ["browser-preview"],
      },
      latestTrainingSubmode: card.cardType === "flash" ? "flash" : "practice",
      latestLearningFocusArea: card.focusArea,
      latestLearningFollowup: followup,
      latestLearningVerifiedResult: options.verifiedResult ?? bootstrap.workspaceTrainingState?.latestLearningVerifiedResult,
      latestLearningBlocker: options.blocker ?? bootstrap.workspaceTrainingState?.latestLearningBlocker,
      latestLearningPartialProgress:
        options.partialProgress ?? bootstrap.workspaceTrainingState?.latestLearningPartialProgress,
      selectedCardId: card.cardId,
      selectedCardType: card.cardType,
      selectedCardTitle: card.cardTitle,
      selectedCardStatus: options.selectedCardStatus,
      trainingEventLedger: [...(bootstrap.workspaceTrainingState?.trainingEventLedger ?? []), ledgerEntry],
    },
    coachingState: {
      ...bootstrap.coachingState,
      scenario: options.coachScenario,
      answerMode: "guided",
      learnerSignal: options.learnerSignal ?? "curious",
      summary,
      nextStep: options.nextStep,
      encouragement: detail,
      updatedAt: now,
    },
    coachTurn: {
      ...bootstrap.coachTurn,
      scenario: options.coachScenario,
      learnerSignal: options.learnerSignal ?? "curious",
      summary,
      nextStep: options.nextStep,
      encouragement: detail,
      activeTask: card.cardTitle,
      artifactKinds: options.evidenceItem ? ["review"] : ["task"],
      suggestedActionTypes: options.evidenceItem ? ["review"] : ["task"],
      backgroundMode: "embedded",
    },
  };
}

function resourceForAction(
  bootstrap: BrowserPreviewBootstrap,
  action: WebviewAction,
): ResourceRecord | undefined {
  const resourceId =
    action.type === "resource/open"
      ? action.payload.resourceId
      : action.type === "command/execute" &&
          action.payload.commandId === trainerCommands.openResource &&
          action.payload.payload &&
          typeof action.payload.payload === "object" &&
          "resourceId" in action.payload.payload &&
          typeof action.payload.payload.resourceId === "string"
        ? action.payload.payload.resourceId
        : undefined;
  return resourceId ? bootstrap.resources?.find((resource) => resource.id === resourceId) : undefined;
}

type PreviewWorkspaceAdmissionStatus = "project-found" | "managed" | "browse" | "ignored";
type PreviewWorkspaceAdmissionState = PreviewWorkspaceAdmissionStatus | "root-missing";

const PREVIEW_WORKSPACE_MUTATION_COMMAND_IDS = new Set<string>([
  trainerCommands.generatePlan,
  trainerCommands.updatePlan,
  trainerCommands.nextTask,
  trainerCommands.indexResources,
  trainerCommands.trainingGenerateCard,
]);

function workspaceAdmissionDeletePatch(bootstrap: BrowserPreviewBootstrap): BrowserPreviewPatch {
  const workspace = bootstrap.memory.workspace ?? {};
  const admission = (workspace.trainerWorkspace ?? {}) as Partial<TrainerWorkspaceAdmission>;
  return {
    plan: {
      id: "",
      title: "",
      frozen: false,
      cadence: "",
      summary: "",
      stages: [],
    },
    task: {
      id: "",
      title: "",
      description: "",
      constraints: [],
      acceptanceCriteria: [],
      nextActionLabel: "",
    },
    workspaceTrainingState: {
      ...(bootstrap.workspaceTrainingState ?? {}),
      workspaceId: undefined,
      selectedCardId: undefined,
      selectedCardTitle: undefined,
    },
    memory: {
      ...bootstrap.memory,
      workspace: {
        ...workspace,
        workspaceId: undefined,
        projectContext: undefined,
        trainerWorkspace: {
          status: "project-found",
          rootPath: admission.rootPath,
          projectName: admission.projectName,
          projectPath: admission.projectPath,
        },
      },
    },
    hasFormalPlan: false,
  };
}

function workspaceAdmissionPatch(
  bootstrap: BrowserPreviewBootstrap,
  status: PreviewWorkspaceAdmissionStatus,
  copy: ReturnType<typeof resolveCopy>,
): BrowserPreviewPatch {
  const workspace = bootstrap.memory.workspace ?? {};
  const admission = (workspace.trainerWorkspace ?? {}) as Partial<TrainerWorkspaceAdmission>;
  const nextStep = previewWorkspaceAdmissionDetail(status, copy);
  const workspaceUnderstanding = bootstrap.memory.workspaceUnderstanding;

  return {
    memory: {
      ...bootstrap.memory,
      workspace: {
        ...workspace,
        trainerWorkspace: {
          ...admission,
          status,
          rootPath: admission.rootPath ?? "D:\\TrainerWorkspace",
          projectId: admission.projectId ?? "browser-preview-project",
          projectName: admission.projectName ?? "Preview project",
          projectPath: admission.projectPath ?? "D:\\TrainerWorkspace\\Projects\\browser-preview-project",
          updatedAt: "2026-07-18T00:00:00.000Z",
        },
      },
      ...(workspaceUnderstanding?.firstLookSummary
        ? {
            workspaceUnderstanding: {
              ...workspaceUnderstanding,
              firstLookSummary: {
                ...workspaceUnderstanding.firstLookSummary,
                recommendedNextStep: nextStep,
              },
            },
          }
        : {}),
    },
    ...(bootstrap.coachingState
      ? {
          coachingState: {
            ...bootstrap.coachingState,
            nextStep,
          },
        }
      : {}),
  };
}

function previewWorkspaceAdmissionStatus(
  bootstrap: BrowserPreviewBootstrap,
): PreviewWorkspaceAdmissionState | undefined {
  const status = bootstrap.memory?.workspace?.trainerWorkspace?.status;
  return status === "root-missing" ||
    status === "project-found" ||
    status === "managed" ||
    status === "browse" ||
    status === "ignored"
    ? status
    : undefined;
}

function previewWorkspaceAdmissionDetail(
  status: PreviewWorkspaceAdmissionState,
  copy: ReturnType<typeof resolveCopy>,
): string {
  switch (status) {
    case "root-missing":
      return copy.workspaceAdmissionRootMissingDetail;
    case "project-found":
      return copy.workspaceAdmissionProjectFoundDetail;
    case "managed":
      return copy.workspaceAdmissionManagedDetail;
    case "browse":
      return copy.workspaceAdmissionBrowseDetail;
    case "ignored":
      return copy.workspaceAdmissionIgnoredDetail;
  }
}

function previewWorkspaceAdmissionBlockedResult(
  status: PreviewWorkspaceAdmissionState | undefined,
  copy: ReturnType<typeof resolveCopy>,
): BrowserPreviewActionResult {
  return {
    tone: "info",
    message: previewWorkspaceAdmissionDetail(status ?? "root-missing", copy),
  };
}

function previewWorkspaceAdmissionTransition(
  commandId: string | undefined,
  bootstrap: BrowserPreviewBootstrap,
  copy: ReturnType<typeof resolveCopy>,
): BrowserPreviewActionResult | undefined {
  if (
    commandId !== trainerCommands.chooseTrainerWorkspaceRoot &&
    commandId !== trainerCommands.adoptWorkspaceProject &&
    commandId !== trainerCommands.browseWorkspaceProject &&
    commandId !== trainerCommands.ignoreWorkspaceProject &&
    commandId !== trainerCommands.deleteWorkspaceProject
  ) {
    return undefined;
  }

  const status = previewWorkspaceAdmissionStatus(bootstrap);
  if (commandId === trainerCommands.chooseTrainerWorkspaceRoot) {
    return status === undefined || status === "root-missing"
      ? {
          patch: workspaceAdmissionPatch(bootstrap, "project-found", copy),
          tone: "success",
          message: copy.workspaceAdmissionProjectFoundDetail,
        }
      : previewWorkspaceAdmissionBlockedResult(status, copy);
  }

  if (commandId === trainerCommands.deleteWorkspaceProject) {
    return status === "managed"
      ? {
          patch: workspaceAdmissionDeletePatch(bootstrap),
          tone: "success",
          message: copy.workspaceAdmissionProjectFoundDetail,
        }
      : previewWorkspaceAdmissionBlockedResult(status, copy);
  }

  if (status === "project-found" || status === "browse" || status === "ignored") {
    const targetStatus =
      commandId === trainerCommands.adoptWorkspaceProject
        ? "managed"
        : commandId === trainerCommands.browseWorkspaceProject
          ? "browse"
          : "ignored";
    if (targetStatus !== status) {
      return {
        patch: workspaceAdmissionPatch(bootstrap, targetStatus, copy),
        tone: "success",
        message: previewWorkspaceAdmissionDetail(targetStatus, copy),
      };
    }
  }

  return previewWorkspaceAdmissionBlockedResult(status, copy);
}

function previewWorkspaceMutationGate(
  commandId: string | undefined,
  bootstrap: BrowserPreviewBootstrap,
  copy: ReturnType<typeof resolveCopy>,
): BrowserPreviewActionResult | undefined {
  if (!commandId || !PREVIEW_WORKSPACE_MUTATION_COMMAND_IDS.has(commandId)) {
    return undefined;
  }

  const status = previewWorkspaceAdmissionStatus(bootstrap);
  return status && status !== "managed"
    ? previewWorkspaceAdmissionBlockedResult(status, copy)
    : undefined;
}

export function runBrowserPreviewAction(
  action: WebviewAction,
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
): BrowserPreviewActionResult {
  const copy = copyFor(language);
  const uiCopy = resolveCopy(language);
  const workspaceCopy = resolveCopy(language);
  const commandId = commandIdForAction(action);

  const workspaceTransition = previewWorkspaceAdmissionTransition(
    commandId,
    bootstrap,
    workspaceCopy,
  );
  if (workspaceTransition) {
    return workspaceTransition;
  }

  // The host owns window trust in VS Code; the preview owns it here. Without
  // this emulation the preview could never confirm trust, and every
  // trust-gated surface (training cards, attestation) stayed dead forever.
  if (commandId === trainerCommands.trustWorkspaceWindow) {
    return {
      patch: {
        memory: {
          ...bootstrap.memory,
          workspace: {
            ...(bootstrap.memory?.workspace ?? {}),
            windowTrusted: true,
          },
        },
      },
      tone: "success",
      message: workspaceCopy.workspaceRootReady,
    };
  }

  const workspaceMutationBlock = previewWorkspaceMutationGate(commandId, bootstrap, workspaceCopy);
  if (workspaceMutationBlock) {
    return workspaceMutationBlock;
  }

  if (commandId === trainerCommands.generatePlan) {
    if (hasFormalPreviewPlan(bootstrap) && bootstrap.plan.frozen) {
      return { tone: "error", message: copy.planFrozen };
    }
    return {
      patch: buildGoalAwarePreviewPlanPatch(bootstrap, language),
      tone: "success",
      message: copy.generateSucceeded,
    };
  }

  if (commandId === trainerCommands.updatePlan) {
    const frozen =
      action.type === "plan/freeze"
        ? action.payload.frozen
        : action.type === "command/execute" &&
            action.payload.payload &&
            typeof action.payload.payload === "object" &&
            "frozen" in action.payload.payload
          ? Boolean(action.payload.payload.frozen)
          : true;
    const patch = updatePlanFreezePatch(bootstrap, language, frozen);
    if (!patch) {
      return { tone: "error", message: copy.missingPlan };
    }
    return {
      patch,
      tone: "success",
      message: frozen ? copy.planFrozen : copy.planResumed,
    };
  }

  if (commandId === trainerCommands.nextTask) {
    if (!hasFormalPreviewPlan(bootstrap)) {
      return { tone: "error", message: copy.missingPlan };
    }
    const task = buildPreviewTask(bootstrap.plan, language);
    return {
      patch: { task },
      tone: "success",
      message: copy.taskReady(task.title),
    };
  }

  if (commandId === trainerCommands.openResource) {
    const resource = resourceForAction(bootstrap, action);
    if (!resource) {
      return { tone: "error", message: copy.unsupported };
    }
    return {
      patch: {
        memory: {
          ...bootstrap.memory,
          selectedResourceDetail: resource,
        },
      },
      tone: "info",
      message: copy.resourceOpened(resource.title),
    };
  }

  if (commandId === trainerCommands.indexResources) {
    return {
      patch: refreshResourcesPatch(bootstrap),
      tone: "success",
      message: copy.resourcesRefreshed(bootstrap.resources?.length ?? 0),
    };
  }

  if (commandId === trainerCommands.trainingGenerateCard) {
    const patch = buildPreviewTrainingCardPatch(
      bootstrap,
      language,
      requestedPreviewTrainingCardType(action),
    );
    if (!patch) {
      return { tone: "error", message: copy.unsupported };
    }
    return {
      patch,
      tone: "success",
      message: copy.trainingCardReady,
    };
  }

  if (commandId === trainerCommands.evaluateCurrentFile) {
    return {
      tone: "error",
      message: copy.evaluateCurrentFileMissing,
    };
  }

  // Candidate governance (importance, priority, merge, library) is a decision
  // the learner makes on the card. The browser preview records it locally so
  // the card stays usable without a live sidecar.
  if (
    commandId === trainerCommands.trainingCardMarkImportant ||
    commandId === trainerCommands.trainingCardSetPriority ||
    commandId === trainerCommands.trainingCardMerge ||
    commandId === trainerCommands.trainingCardLibrary
  ) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as {
            cardId?: string;
            important?: boolean;
            priority?: number;
            keepCardId?: string;
            duplicateCardIds?: string[];
          })
        : undefined;
    const summary =
      commandId === trainerCommands.trainingCardMarkImportant
        ? `Mark the candidate card ${payload?.important ? "important" : "not important"}.`
        : commandId === trainerCommands.trainingCardSetPriority
          ? `Set the candidate card priority to ${payload?.priority ?? 0}.`
          : commandId === trainerCommands.trainingCardMerge
            ? "Merge the duplicate candidate cards."
            : "Review the candidate card library.";
    // The learner's decision applies to the local candidate list, so the card
    // keeps its siblings and the next decision stays available.
    const candidates = (bootstrap.workspaceTrainingState?.trainingCardCandidates ?? []).map((candidate) => {
      if (candidate.cardId === payload?.cardId) {
        return commandId === trainerCommands.trainingCardMarkImportant
          ? { ...candidate, important: payload?.important }
          : commandId === trainerCommands.trainingCardSetPriority
            ? { ...candidate, cardPriority: payload?.priority }
            : candidate;
      }
      if (commandId === trainerCommands.trainingCardMerge
        && (payload?.duplicateCardIds ?? []).includes(candidate.cardId)) {
        return { ...candidate, mergedInto: payload?.keepCardId };
      }
      return candidate;
    });
    return {
      patch: {
        ...buildPreviewTrainingActionPatch(bootstrap, language, {
          eventType: "training_candidate_governance",
          summary,
          detail: "The browser preview only updates its local training state.",
          selectedCardStatus: "candidate",
          nextStep: uiCopy.trainingRecordStep,
          coachScenario: "task",
          learnerSignal: "curious",
          followup: uiCopy.trainingRecordStep,
          handoffStatus: "in_progress",
          nextHopStatus: "accepted",
          nextHopSummary: "The local candidate card decision was recorded in the preview.",
        }),
        workspaceTrainingState: {
          ...bootstrap.workspaceTrainingState,
          trainingCardCandidates: candidates,
          // The decision applies to the card the learner is looking at, not to
          // whatever card the preview fixture happens to carry.
          ...(payload?.cardId || payload?.keepCardId
            ? {
                selectedCardId: payload.cardId ?? payload.keepCardId,
                selectedCardStatus: "candidate",
              }
            : {}),
        },
      },
      tone: "success",
      message: "Browser-preview simulation: the candidate decision was recorded locally without touching a real workspace.",
    };
  }

  if (commandId === trainerCommands.trainingCardStatusTransition) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as { cardId?: string; newStatus?: string; reason?: string })
        : undefined;
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_card_status_transition",
        summary: `Move the training card to ${payload?.newStatus ?? "the next local status"}.`,
        detail: payload?.reason
          ? `Reason: ${payload.reason}.`
          : "The browser preview only updates its local training state.",
        selectedCardStatus: payload?.newStatus?.trim() || "in_progress",
        nextStep: uiCopy.trainingRecordStep,
        coachScenario: "task",
        learnerSignal: "curious",
        followup: uiCopy.trainingRecordStep,
        handoffStatus: payload?.newStatus?.trim() || "in_progress",
        nextHopStatus: "accepted",
        nextHopSummary: "The local card moved forward in the preview training flow.",
      }),
      tone: "success",
      message: "Browser-preview simulation: card status updated locally without touching a real workspace.",
    };
  }

  if (commandId === trainerCommands.trainingFlashcardAnswer) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as { cardId?: string; learnerAnswer?: string; answer?: string })
        : undefined;
    const answer = payload?.learnerAnswer?.trim() || payload?.answer?.trim() || "";
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_flashcard_answer",
        summary: "Record the flashcard answer in the local preview.",
        detail: "The browser preview did not call a real provider or update a real workspace.",
        selectedCardStatus: "answered",
        nextStep: uiCopy.trainingReturnToCoach,
        coachScenario: "task",
        learnerSignal: "curious",
        followup: uiCopy.trainingReturnToCoach,
        partialProgress: answer ? `Flashcard answer captured locally: ${answer}` : "Flashcard answer captured locally.",
        handoffStatus: "answered",
        nextHopStatus: "accepted",
        nextHopSummary: "The local flashcard answer is ready to return to Coach.",
      }),
      tone: "success",
      message: "Browser-preview simulation: flashcard answer recorded locally.",
    };
  }

  if (commandId === trainerCommands.trainingPracticeReturn) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as {
            cardId?: string;
            passed?: boolean;
            summary?: string;
            nextStep?: string;
            focusArea?: string;
          })
        : undefined;
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_practice_return",
        summary: "Return the verified practice result from the local preview.",
        detail: payload?.summary?.trim()
          ? `Practice return summary: ${payload.summary.trim()}`
          : "The browser preview only records the local return signal.",
        selectedCardStatus: payload?.passed ? "returned" : "verification_required",
        nextStep: uiCopy.trainingReturnToCoach,
        coachScenario: "review",
        learnerSignal: "curious",
        verifiedResult:
          payload?.passed === true
            ? payload?.summary?.trim() || "Browser-preview practice result verified locally."
            : undefined,
        followup: uiCopy.trainingReturnToCoach,
        returnMode: payload?.passed === true ? "result" : "verification_required",
        handoffStatus: payload?.passed === true ? "returned" : "verification_required",
        nextHopStatus: payload?.passed === true ? "accepted" : "verification_required",
        nextHopSummary: payload?.nextStep?.trim() || "Return the practice result to Coach.",
      }),
      tone: "success",
      message: "Browser-preview simulation: practice return recorded locally.",
    };
  }

  if (commandId === trainerCommands.trainingReflect) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as { cardId?: string; handoffId?: string; reflection?: string })
        : undefined;
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_reflect",
        summary: "Record the reflection step in the local preview.",
        detail: payload?.reflection?.trim()
          ? `Reflection captured locally: ${payload.reflection.trim()}`
          : "The browser preview only records a local reflection step.",
        selectedCardStatus: "reflected",
        nextStep: uiCopy.trainingReturnToCoach,
        coachScenario: "review",
        learnerSignal: "curious",
        followup: uiCopy.trainingReturnToCoach,
        partialProgress: payload?.reflection?.trim() || "Reflection captured locally.",
        returnMode: "return_required",
        handoffStatus: "ready_to_return",
        nextHopStatus: "return_required",
        nextHopSummary: "The local reflection step is ready to complete the return to Coach.",
      }),
      tone: "success",
      message: "Browser-preview simulation: reflection recorded locally.",
    };
  }

  if (commandId === trainerCommands.trainingReturn) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as { cardId?: string; handoffId?: string })
        : undefined;
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_return",
        summary: "Return the local training handoff to Coach.",
        detail: "The browser preview did not hand anything back to a real workspace.",
        selectedCardStatus: "returned",
        nextStep: uiCopy.trainingReturnToCoach,
        coachScenario: "review",
        learnerSignal: "curious",
        followup: uiCopy.trainingReturnToCoach,
        returnMode: "result",
        handoffStatus: "returned",
        nextHopStatus: "continued_in_chat",
        nextHopSummary: payload?.handoffId?.trim()
          ? `Local return completed for ${payload.handoffId.trim()}.`
          : "The local return completed in the preview fixture.",
      }),
      tone: "success",
      message: "Browser-preview simulation: return completed locally.",
    };
  }

  if (commandId === trainerCommands.evidenceEnqueue) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as {
            waitingComposer?: boolean;
            source?: string;
            summary?: string;
            concepts?: string[];
            outcome?: string;
            sourceCardId?: string;
            targetPlanStageId?: string;
            confidence?: number;
          })
        : undefined;
    const waitingComposer = payload?.waitingComposer === true;
    const submitted = payload?.summary?.trim() ?? "";
    if (waitingComposer && !submitted) {
      return { tone: "info", message: copy.unsupported };
    }
    const now = new Date().toISOString();
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "evidence_enqueue",
        summary: "Queue evidence in the local browser preview.",
        detail:
          "The browser preview only updates a local evidence queue and does not create real evidence records.",
        selectedCardStatus: "evidence_queued",
        nextStep: uiCopy.trainingRecordStep,
        coachScenario: "review",
        learnerSignal: "curious",
        followup: uiCopy.trainingRecordStep,
        returnMode: "result",
        handoffStatus: "evidence_queued",
        nextHopStatus: "accepted",
        nextHopSummary: "The local evidence queue advanced in the preview fixture.",
        evidenceItem: {
          id: `browser-preview-evidence-${now}`,
          summary: waitingComposer
            ? submitted
            : payload?.summary?.trim() || "Browser-preview evidence queued locally.",
          source: waitingComposer
            ? "plan_runtime_verify"
            : payload?.source?.trim() || "browser_preview_simulation",
          concepts: Array.isArray(payload?.concepts) ? payload.concepts : [],
          outcome: waitingComposer ? "partial" : payload?.outcome?.trim() || "pass",
          confidence: waitingComposer
            ? 0
            : typeof payload?.confidence === "number"
              ? payload.confidence
              : 0.75,
          timestamp: now,
          sourceCardId: payload?.sourceCardId?.trim(),
          targetPlanStageId: payload?.targetPlanStageId?.trim(),
        },
      }),
      tone: "success",
      message: "Browser-preview simulation: evidence queued locally without creating a real evidence record.",
    };
  }

  return { tone: "info", message: copy.unsupported };
}
