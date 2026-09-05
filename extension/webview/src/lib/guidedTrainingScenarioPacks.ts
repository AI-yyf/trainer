import guidedTrainingScenarioPacks from "../../../../server/app/training/guided_training_scenario_packs.json";
import type { ComposerLanguage } from "./types";

export type GuidedTrainingPreviewScenario =
  | "training-remote"
  | "training-debug"
  | "training-function"
  | "training-resource"
  | "training-dependency";

type PreviewLanguage = ComposerLanguage;

type LocalizedValue<T> = Partial<Record<PreviewLanguage, T>> & { "en-US": T };

type RawGuidedTrainingCard = {
  cardId: string;
  type: "practice" | "flash";
  title: LocalizedValue<string>;
  whyNow: LocalizedValue<string>;
  focusArea: LocalizedValue<string>;
  targetSkill: LocalizedValue<string>;
  scenario: LocalizedValue<string>;
  problemStatement: LocalizedValue<string>;
  suggestedWorkspaceAction: LocalizedValue<string>;
  apiHints?: string[];
  constraints: LocalizedValue<string[]>;
  deliverable?: LocalizedValue<string>;
  selfCheck?: LocalizedValue<string[]>;
  validationMethod: LocalizedValue<string>;
  learnerDeliverables: LocalizedValue<string[]>;
  verificationSteps: LocalizedValue<string[]>;
  successSignal: LocalizedValue<string>;
  expectedSymbols?: string[];
  filesToTouch?: string[];
  hintLadder: LocalizedValue<string[]>;
  commonMistakes: LocalizedValue<string[]>;
  stuckRecovery?: LocalizedValue<string>;
  reflectionPrompt: LocalizedValue<string>;
  returnWith: LocalizedValue<string>;
  knowledgeType?: LocalizedValue<string>;
  question?: LocalizedValue<string>;
  context?: LocalizedValue<string>;
  answerMode?: LocalizedValue<string>;
  expectedAnswer?: LocalizedValue<string>;
  feedback?: LocalizedValue<Record<string, string>>;
};

type RawGuidedTrainingPack = {
  id: string;
  previewScenario: GuidedTrainingPreviewScenario;
  sourceChain: LocalizedValue<string[]>;
  currentFocus: LocalizedValue<string>;
  coachSummary: LocalizedValue<string>;
  practiceGoal: LocalizedValue<string>;
  flashGoal: LocalizedValue<string>;
  practiceNextStep: LocalizedValue<string>;
  flashNextStep: LocalizedValue<string>;
  practice: RawGuidedTrainingCard;
  flash: RawGuidedTrainingCard;
};

export interface GuidedTrainingPreviewCard {
  cardId: string;
  type: "practice" | "flash";
  title: string;
  whyNow: string;
  focusArea: string;
  targetSkill: string;
  scenario: string;
  problemStatement: string;
  suggestedWorkspaceAction: string;
  apiHints: string[];
  constraints: string[];
  deliverable: string;
  selfCheck: string[];
  validationMethod: string;
  learnerDeliverables: string[];
  verificationSteps: string[];
  successSignal: string;
  expectedSymbols: string[];
  filesToTouch: string[];
  hintLadder: string[];
  commonMistakes: string[];
  stuckRecovery: string;
  reflectionPrompt: string;
  returnWith: string;
  nextAfterCompletion: string;
  knowledgeType?: string;
  question?: string;
  context?: string;
  answerMode?: string;
  expectedAnswer?: string;
  feedback?: Record<string, string>;
}

export interface GuidedTrainingPreviewScenarioData {
  id: string;
  previewScenario: GuidedTrainingPreviewScenario;
  sourceChain: string[];
  currentFocus: string;
  coachSummary: string;
  practiceGoal: string;
  flashGoal: string;
  practiceNextStep: string;
  flashNextStep: string;
  practiceCard: GuidedTrainingPreviewCard;
  flashCard: GuidedTrainingPreviewCard;
}

type PreviewFallbackCopy = {
  practiceTitle: string;
  flashTitle: string;
  whyNow: string;
  scenario: string;
  problem: string;
  action: string;
  deliverable: string;
  check: string;
  validation: string;
  success: string;
  stuck: string;
  reflect: string;
  returnWith: string;
  next: string;
  question: string;
  expected: string;
  hintA: string;
  hintB: string;
  mistake: string;
  learn: string;
  verify: string;
};

const previewFallbackCopy: Partial<Record<ComposerLanguage, PreviewFallbackCopy>> = {
  "es-ES": {
    practiceTitle: "Práctica: {focus}", flashTitle: "Tarjeta: {focus}",
    whyNow: "Consolida el siguiente paso antes de ampliar el tema.",
    scenario: "Trabaja una parte pequeña y verificable de {focus}.",
    problem: "Explica una regla, un ejemplo o un límite concreto de {focus}.",
    action: "Aprende primero y responde después con una evidencia concreta.",
    deliverable: "Una explicación breve y una evidencia concreta.",
    check: "¿Puedes señalar una evidencia concreta en lugar de una suposición?",
    validation: "Comprueba la respuesta con una fuente, ejemplo o resultado verificable.",
    success: "Puedes explicar {focus} y respaldarlo con una evidencia.",
    stuck: "Reduce la respuesta a una regla y una evidencia.",
    reflect: "¿Qué evidencia hizo clara esta idea?",
    returnWith: "Vuelve con tu respuesta, la comprobación y una breve reflexión.",
    next: "Regresa con el resultado verificado y elige el siguiente paso.",
    question: "¿Cuál es la explicación más pequeña y precisa de {focus}?",
    expected: "Una explicación concisa con un ejemplo o un límite.",
    hintA: "Empieza por la regla central.", hintB: "Añade un ejemplo o una condición límite.",
    mistake: "Dar una definición vaga sin evidencia ni límite.", learn: "Aprender", verify: "Verificar",
  },
  "fr-FR": {
    practiceTitle: "Exercice : {focus}", flashTitle: "Carte : {focus}",
    whyNow: "Consolide la prochaine étape avant d'élargir le sujet.",
    scenario: "Travaillez une partie petite et vérifiable de {focus}.",
    problem: "Expliquez une règle, un exemple ou une limite concrète de {focus}.",
    action: "Apprenez d'abord, puis répondez avec une preuve concrète.",
    deliverable: "Une courte explication et une preuve concrète.",
    check: "Pouvez-vous montrer une preuve concrète plutôt qu'une supposition ?",
    validation: "Vérifiez la réponse avec une source, un exemple ou un résultat contrôlable.",
    success: "Vous pouvez expliquer {focus} et le relier à une preuve.",
    stuck: "Réduisez la réponse à une règle et une preuve.",
    reflect: "Quelle preuve a rendu cette idée claire ?",
    returnWith: "Revenez avec votre réponse, la vérification et une brève réflexion.",
    next: "Revenez avec le résultat vérifié, puis choisissez la suite.",
    question: "Quelle est l'explication la plus petite et la plus exacte de {focus} ?",
    expected: "Une explication concise avec un exemple ou une limite.",
    hintA: "Commencez par la règle centrale.", hintB: "Ajoutez un exemple ou une condition limite.",
    mistake: "Donner une définition vague sans preuve ni limite.", learn: "Apprendre", verify: "Vérifier",
  },
  "de-DE": {
    practiceTitle: "Übung: {focus}", flashTitle: "Karte: {focus}",
    whyNow: "Festigt den nächsten Schritt, bevor das Thema erweitert wird.",
    scenario: "Bearbeite einen kleinen, prüfbaren Teil von {focus}.",
    problem: "Erkläre eine konkrete Regel, ein Beispiel oder eine Grenze von {focus}.",
    action: "Lerne zuerst und antworte dann mit einem konkreten Nachweis.",
    deliverable: "Eine kurze Erklärung und ein konkreter Nachweis.",
    check: "Kannst du einen konkreten Nachweis statt einer Vermutung zeigen?",
    validation: "Prüfe die Antwort an einer Quelle, einem Beispiel oder einem Ergebnis.",
    success: "Du kannst {focus} erklären und mit einem Nachweis belegen.",
    stuck: "Reduziere die Antwort auf eine Regel und einen Nachweis.",
    reflect: "Welcher Nachweis hat diese Idee klar gemacht?",
    returnWith: "Komm mit deiner Antwort, der Prüfung und einer kurzen Reflexion zurück.",
    next: "Komm mit dem verifizierten Ergebnis zurück und wähle den nächsten Schritt.",
    question: "Was ist die kleinste präzise Erklärung von {focus}?",
    expected: "Eine knappe Erklärung mit einem Beispiel oder einer Grenze.",
    hintA: "Beginne mit der zentralen Regel.", hintB: "Füge ein Beispiel oder eine Grenzbedingung hinzu.",
    mistake: "Eine vage Definition ohne Nachweis oder Grenze geben.", learn: "Lernen", verify: "Prüfen",
  },
  "ja-JP": {
    practiceTitle: "練習: {focus}", flashTitle: "カード: {focus}",
    whyNow: "テーマを広げる前に、次の一歩を確実にします。",
    scenario: "{focus} の小さく検証可能な部分に取り組みます。",
    problem: "{focus} の具体的な規則、例、または境界を説明してください。",
    action: "先に学び、次に具体的な根拠を含む回答をしてください。",
    deliverable: "短い説明と具体的な根拠。",
    check: "推測ではなく具体的な根拠を示せますか。",
    validation: "資料、例、または確認可能な結果と照らして検証します。",
    success: "{focus} を説明し、具体的な根拠に結び付けられます。",
    stuck: "回答を一つの規則と一つの根拠まで小さくしてください。",
    reflect: "どの根拠でこの考えが明確になりましたか。",
    returnWith: "回答、検証結果、短い振り返りを持って戻ってください。",
    next: "検証済みの結果を持って戻り、次の一歩を選びます。",
    question: "{focus} を最も小さく正確に説明すると何ですか。",
    expected: "一つの例または境界を含む簡潔な説明。",
    hintA: "中心となる規則から始めてください。", hintB: "例または境界条件を一つ加えてください。",
    mistake: "根拠や境界なしに曖昧な定義を述べること。", learn: "学ぶ", verify: "検証する",
  },
  "ko-KR": {
    practiceTitle: "연습: {focus}", flashTitle: "카드: {focus}",
    whyNow: "주제를 넓히기 전에 다음 단계를 확실히 합니다.",
    scenario: "{focus}의 작고 검증 가능한 한 부분을 다룹니다.",
    problem: "{focus}의 구체적인 규칙, 예시 또는 경계를 설명하세요.",
    action: "먼저 학습한 뒤 구체적인 근거를 포함해 답하세요.",
    deliverable: "짧은 설명과 구체적인 근거.",
    check: "추측 대신 구체적인 근거를 제시할 수 있나요?",
    validation: "자료, 예시 또는 확인 가능한 결과와 비교하여 검증하세요.",
    success: "{focus}를 설명하고 구체적인 근거와 연결할 수 있습니다.",
    stuck: "답을 하나의 규칙과 하나의 근거로 줄이세요.",
    reflect: "어떤 근거가 이 생각을 분명하게 만들었나요?",
    returnWith: "답변, 검증 결과, 짧은 성찰을 가지고 돌아오세요.",
    next: "검증한 결과를 가지고 돌아와 다음 단계를 선택하세요.",
    question: "{focus}에 대한 가장 작고 정확한 설명은 무엇인가요?",
    expected: "한 가지 예시 또는 경계를 포함한 간결한 설명.",
    hintA: "핵심 규칙부터 시작하세요.", hintB: "예시 또는 경계 조건을 하나 추가하세요.",
    mistake: "근거나 경계 없이 모호한 정의를 제시하는 것.", learn: "학습", verify: "검증",
  },
  "pt-BR": {
    practiceTitle: "Prática: {focus}", flashTitle: "Cartão: {focus}",
    whyNow: "Consolida o próximo passo antes de ampliar o tema.",
    scenario: "Trabalhe uma parte pequena e verificável de {focus}.",
    problem: "Explique uma regra, um exemplo ou um limite concreto de {focus}.",
    action: "Aprenda primeiro e responda depois com uma evidência concreta.",
    deliverable: "Uma explicação curta e uma evidência concreta.",
    check: "Você consegue mostrar uma evidência concreta em vez de uma suposição?",
    validation: "Confira a resposta com uma fonte, um exemplo ou um resultado verificável.",
    success: "Você consegue explicar {focus} e ligá-lo a uma evidência.",
    stuck: "Reduza a resposta a uma regra e uma evidência.",
    reflect: "Qual evidência tornou esta ideia clara?",
    returnWith: "Volte com sua resposta, a verificação e uma reflexão curta.",
    next: "Volte com o resultado verificado e escolha o próximo passo.",
    question: "Qual é a explicação mais pequena e precisa de {focus}?",
    expected: "Uma explicação concisa com um exemplo ou um limite.",
    hintA: "Comece pela regra central.", hintB: "Acrescente um exemplo ou uma condição limite.",
    mistake: "Dar uma definição vaga sem evidência ou limite.", learn: "Aprender", verify: "Verificar",
  },
};

const previewScenarioFocusCopy: Partial<
  Record<ComposerLanguage, Record<GuidedTrainingPreviewScenario, string>>
> = {
  "es-ES": {
    "training-remote": "espacio de trabajo remoto de VS Code",
    "training-debug": "flujo de depuración de VS Code",
    "training-function": "contrato de función",
    "training-resource": "de recurso a conocimiento fiable",
    "training-dependency": "dominio de dependencias y API",
  },
  "fr-FR": {
    "training-remote": "espace de travail distant VS Code",
    "training-debug": "boucle de débogage VS Code",
    "training-function": "contrat de fonction",
    "training-resource": "des ressources au savoir fiable",
    "training-dependency": "maîtrise des dépendances et des API",
  },
  "de-DE": {
    "training-remote": "VS Code-Remote-Arbeitsbereich",
    "training-debug": "VS Code-Debug-Schleife",
    "training-function": "Funktionsvertrag",
    "training-resource": "von Ressourcen zu verlässlichem Wissen",
    "training-dependency": "Abhängigkeiten und APIs sicher beherrschen",
  },
  "ja-JP": {
    "training-remote": "VS Code のリモートワークスペース",
    "training-debug": "VS Code のデバッグ手順",
    "training-function": "関数の契約",
    "training-resource": "資料を信頼できる知識にする",
    "training-dependency": "依存関係と API の理解",
  },
  "ko-KR": {
    "training-remote": "VS Code 원격 작업 영역",
    "training-debug": "VS Code 디버그 흐름",
    "training-function": "함수 계약",
    "training-resource": "자료를 신뢰할 수 있는 지식으로 만들기",
    "training-dependency": "의존성과 API 이해",
  },
  "pt-BR": {
    "training-remote": "espaço de trabalho remoto do VS Code",
    "training-debug": "fluxo de depuração do VS Code",
    "training-function": "contrato de função",
    "training-resource": "de recurso a conhecimento confiável",
    "training-dependency": "domínio de dependências e APIs",
  },
};

function pickLocalized<T>(value: LocalizedValue<T>, language: PreviewLanguage): T {
  return value[language] ?? value["en-US"];
}

function cloneStringArray(values: string[] | undefined): string[] {
  return Array.isArray(values) ? [...values] : [];
}

function normalizeCard(
  raw: RawGuidedTrainingCard,
  language: PreviewLanguage,
  nextAfterCompletion: string,
): GuidedTrainingPreviewCard {
  return {
    cardId: raw.cardId,
    type: raw.type,
    title: pickLocalized(raw.title, language),
    whyNow: pickLocalized(raw.whyNow, language),
    focusArea: pickLocalized(raw.focusArea, language),
    targetSkill: pickLocalized(raw.targetSkill, language),
    scenario: pickLocalized(raw.scenario, language),
    problemStatement: pickLocalized(raw.problemStatement, language),
    suggestedWorkspaceAction: pickLocalized(raw.suggestedWorkspaceAction, language),
    apiHints: cloneStringArray(raw.apiHints),
    constraints: cloneStringArray(pickLocalized(raw.constraints, language)),
    deliverable: raw.deliverable ? pickLocalized(raw.deliverable, language) : "",
    selfCheck: raw.selfCheck ? cloneStringArray(pickLocalized(raw.selfCheck, language)) : [],
    validationMethod: pickLocalized(raw.validationMethod, language),
    learnerDeliverables: cloneStringArray(pickLocalized(raw.learnerDeliverables, language)),
    verificationSteps: cloneStringArray(pickLocalized(raw.verificationSteps, language)),
    successSignal: pickLocalized(raw.successSignal, language),
    expectedSymbols: cloneStringArray(raw.expectedSymbols),
    filesToTouch: cloneStringArray(raw.filesToTouch),
    hintLadder: cloneStringArray(pickLocalized(raw.hintLadder, language)),
    commonMistakes: cloneStringArray(pickLocalized(raw.commonMistakes, language)),
    stuckRecovery: raw.stuckRecovery ? pickLocalized(raw.stuckRecovery, language) : "",
    reflectionPrompt: pickLocalized(raw.reflectionPrompt, language),
    returnWith: pickLocalized(raw.returnWith, language),
    nextAfterCompletion,
    knowledgeType: raw.knowledgeType ? pickLocalized(raw.knowledgeType, language) : undefined,
    question: raw.question ? pickLocalized(raw.question, language) : undefined,
    context: raw.context ? pickLocalized(raw.context, language) : undefined,
    answerMode: raw.answerMode ? pickLocalized(raw.answerMode, language) : undefined,
    expectedAnswer: raw.expectedAnswer ? pickLocalized(raw.expectedAnswer, language) : undefined,
    feedback: raw.feedback ? { ...pickLocalized(raw.feedback, language) } : undefined,
  };
}

function interpolatePreviewCopy(value: string, focus: string): string {
  return value.replace("{focus}", focus);
}

function previewScenarioFocus(
  scenario: GuidedTrainingPreviewScenario,
  language: PreviewLanguage,
): string {
  const localizedFocus = previewScenarioFocusCopy[language]?.[scenario];
  if (localizedFocus) {
    return localizedFocus;
  }
  if (scenario === "training-remote") {
    return "VS Code remote workspace";
  }
  if (scenario === "training-debug") {
    return "VS Code debug loop";
  }
  if (scenario === "training-resource") {
    return "resource to trusted knowledge";
  }
  if (scenario === "training-dependency") {
    return "dependency and API mastery";
  }
  return "function contract";
}

function buildLocalizedFallbackCard(
  raw: RawGuidedTrainingCard,
  copy: PreviewFallbackCopy,
  focus: string,
  nextAfterCompletion: string,
): GuidedTrainingPreviewCard {
  const localized = (key: keyof PreviewFallbackCopy) =>
    interpolatePreviewCopy(copy[key], focus);
  const isFlash = raw.type === "flash";

  return {
    cardId: raw.cardId,
    type: raw.type,
    title: localized(isFlash ? "flashTitle" : "practiceTitle"),
    whyNow: localized("whyNow"),
    focusArea: focus,
    targetSkill: focus,
    scenario: localized("scenario"),
    problemStatement: localized("problem"),
    suggestedWorkspaceAction: localized("action"),
    apiHints: [localized("hintA"), localized("hintB")],
    constraints: [localized("check")],
    deliverable: localized("deliverable"),
    selfCheck: [localized("check")],
    validationMethod: localized("validation"),
    learnerDeliverables: [localized("deliverable"), localized("success")],
    verificationSteps: [localized("validation"), localized("check")],
    successSignal: localized("success"),
    expectedSymbols: [],
    filesToTouch: [],
    hintLadder: [localized("hintA"), localized("hintB")],
    commonMistakes: [localized("mistake")],
    stuckRecovery: localized("stuck"),
    reflectionPrompt: localized("reflect"),
    returnWith: localized("returnWith"),
    nextAfterCompletion,
    knowledgeType: isFlash ? "concept" : undefined,
    question: isFlash ? localized("question") : undefined,
    context: isFlash ? localized("scenario") : undefined,
    answerMode: isFlash ? "text" : undefined,
    expectedAnswer: isFlash ? localized("expected") : undefined,
    feedback: isFlash
      ? { correct: localized("success"), incorrect: localized("stuck") }
      : undefined,
  };
}

function buildLocalizedFallbackScenario(
  raw: RawGuidedTrainingPack,
  copy: PreviewFallbackCopy,
  language: PreviewLanguage,
): GuidedTrainingPreviewScenarioData {
  const focus = previewScenarioFocus(raw.previewScenario, language);
  const localized = (key: keyof PreviewFallbackCopy) =>
    interpolatePreviewCopy(copy[key], focus);
  const practiceNextStep = localized("next");
  const flashNextStep = localized("next");

  return {
    id: raw.id,
    previewScenario: raw.previewScenario,
    sourceChain: [copy.learn, copy.verify],
    currentFocus: focus,
    coachSummary: localized("whyNow"),
    practiceGoal: localized("action"),
    flashGoal: localized("question"),
    practiceNextStep,
    flashNextStep,
    practiceCard: buildLocalizedFallbackCard(raw.practice, copy, focus, practiceNextStep),
    flashCard: buildLocalizedFallbackCard(raw.flash, copy, focus, flashNextStep),
  };
}

const rawPackList = ((guidedTrainingScenarioPacks as { packs?: RawGuidedTrainingPack[] }).packs ??
  []) as RawGuidedTrainingPack[];

const rawPackMap = new Map<GuidedTrainingPreviewScenario, RawGuidedTrainingPack>(
  rawPackList.map((pack) => [pack.previewScenario, pack]),
);

export const guidedTrainingPreviewScenarios: GuidedTrainingPreviewScenario[] = [
  "training-remote",
  "training-debug",
  "training-function",
  "training-resource",
  "training-dependency",
];

export function resolveGuidedTrainingPreviewScenarioData(
  scenario: GuidedTrainingPreviewScenario,
  language: PreviewLanguage,
): GuidedTrainingPreviewScenarioData | undefined {
  const raw = rawPackMap.get(scenario);
  if (!raw) {
    return undefined;
  }

  const fallbackCopy = previewFallbackCopy[language];
  if (fallbackCopy) {
    return buildLocalizedFallbackScenario(raw, fallbackCopy, language);
  }

  return {
    id: raw.id,
    previewScenario: raw.previewScenario,
    sourceChain: cloneStringArray(pickLocalized(raw.sourceChain, language)),
    currentFocus: pickLocalized(raw.currentFocus, language),
    coachSummary: pickLocalized(raw.coachSummary, language),
    practiceGoal: pickLocalized(raw.practiceGoal, language),
    flashGoal: pickLocalized(raw.flashGoal, language),
    practiceNextStep: pickLocalized(raw.practiceNextStep, language),
    flashNextStep: pickLocalized(raw.flashNextStep, language),
    practiceCard: normalizeCard(raw.practice, language, pickLocalized(raw.practiceNextStep, language)),
    flashCard: normalizeCard(raw.flash, language, pickLocalized(raw.flashNextStep, language)),
  };
}
