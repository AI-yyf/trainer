import { useEffect, useMemo, useState } from "react";

import {
  buildTransferEvidenceDraft,
  type TransferEvidenceDraft,
  type TransferWorkspaceOption,
} from "../../../../../shared/src/transferEvidenceGovernance";
import {
  summarizeTrainingNextHopCopy,
  summarizeWaitingCoachJudgment,
} from "../../../../../shared/src/coachLanguage";
import {
  compactTrainingCardText,
  summarizeTrainingCardLead,
  summarizeTrainingScenarioPack,
  type NarrowSidebarCopyLanguage,
} from "../../../../../shared/src/trainingCardCopy";
import {
  resolveTrainingHandoff,
  resolveTrainingNextHop,
  type TrainingEventLedgerEntrySummary,
} from "../../../../../shared/src/trainingHandoffGovernance";
import { summarizeReviewQueueTruth } from "../../../../../shared/src/reviewQueueGovernance";
import { buildTrainingRestoreOrchestrationSteps } from "../../../../../shared/src/trainingRecoveryGovernance";
import { ActionButton } from "../common";
import { BooksIcon } from "../icons";
import { DiagnosticsIcon, LightningIcon } from "../icons";
import { CoachFlashView } from "../flash";
import type { FlashPracticeBridge } from "../flash/CoachFlashView";
import { CoachPracticeView } from "../practice";
import { StatusPill } from "../StatusPill";
import { WorkspaceAuthoritySummary } from "../coach/parts/WorkspaceAuthoritySummary";
import type {
  PracticeCoachBridge,
  PracticeFileVerificationRequest,
} from "../practice/CoachPracticeView";
import type { TrainingReturnPayload } from "../../../../../shared/src/trainingReturn";
import type { TrainingCardStatus } from "../../../../../shared/src/trainingCardRouting";
import { isValidCardTransition } from "../../../../../shared/src/trainingCardRouting";
import { preferRecoveredTrainingFocusChrome } from "../../../../../shared/src/planOrientationGovernance";
import type {
  ComposerLanguage,
  DebugVisibleTrainingFacts,
  DependencyMastery,
  DependencySkillMap,
  DependencySkillMapHistoryEntry,
  EvidencePack,
  FlashcardAttempt,
  FlashcardDeck,
  FlashcardRecoveryMode,
  ImplementationGuide,
  LearningOutcome,
  MemoryLayerView,
  ReviewArtifact,
  ReviewArtifactHistoryEntry,
  ReviewQueueAction,
  ReviewQueueItem,
  ScenarioLab,
  ScenarioLabHistoryEntry,
  TaskSpec,
  TeachingDecision,
  TheoryDrillHistoryEntry,
  TheoryDrillSnapshot,
  TrainingEventLedgerEntry,
  TrainingNextHopSummary,
  TrainingSubmode,
  WorkspaceAuthority,
  WorkspaceUnderstanding,
} from "../../lib/types";
import { useTranslation } from "../../lib/i18n/useTranslation";

type TrainingSurfaceMode = "project" | "flash";
type TrainingConversationCandidateType =
  | "project_context_candidate"
  | "resource_import_candidate"
  | "evidence_candidate"
  | "flash_candidate"
  | "practice_candidate"
  | "coach_visible_status"
  | "micro_drill_prompt"
  | "card_invocation";
type TrainingLedgerContinueIn = "chat" | "training" | "plan" | "resources" | "none";
type TrainingLedgerProjectScope =
  | "global"
  | "current_project"
  | "project_subplan"
  | "sandbox"
  | "unknown";

type WorkspaceTrainingState = {
  workspaceId?: string;
  latestConversationHandoff?: {
    candidateId?: string;
    candidateType?: TrainingConversationCandidateType;
    targetKind?: string;
    targetId?: string;
    continueIn?: "chat" | "training" | "plan" | "resources" | "none";
    acceptedInto?: string;
    handoffStatus?: string;
    handoffSummary?: string;
    blockedBy?: string;
    coachOnly?: boolean;
    cardType?: "practice" | "flash";
    cardTitle?: string;
    learnerDeliverables?: string[];
    verificationSteps?: string[];
    successSignal?: string;
    returnWith?: string;
    nextAfterCompletion?: string;
    fallbackAction?: string;
  };
  latestConversationCandidateId?: string;
  latestConversationCandidateType?: TrainingConversationCandidateType;
  latestTrainingHandoff?: {
    candidateId?: string;
    candidateType?: TrainingConversationCandidateType;
    targetKind?: string;
    targetId?: string;
    continueIn?: "chat" | "training" | "plan" | "resources" | "none";
    acceptedInto?: string;
    handoffStatus?: string;
    handoffSummary?: string;
    blockedBy?: string;
    coachOnly?: boolean;
    cardType?: "practice" | "flash";
    cardTitle?: string;
    scenarioPack?: string;
    learnerDeliverables?: string[];
    verificationSteps?: string[];
    successSignal?: string;
    returnWith?: string;
    nextAfterCompletion?: string;
    fallbackAction?: string;
    returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
    returnSummary?: string;
    fedBackAt?: string;
    waitingCoachJudgment?: boolean;
    sourceChain?: string[];
  };
  latestTrainingNextHop?: {
    candidateId?: string;
    candidateType?: "evidence_candidate" | "flash_candidate" | "practice_candidate";
    title?: string;
    summary?: string;
    whyNow?: string;
    projectScope?: "global" | "current_project" | "project_subplan" | "sandbox" | "unknown";
    continueIn?: "chat" | "training" | "plan";
    targetKind?: string;
    targetId?: string;
    acceptedInto?: string;
    status?:
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
    statusReason?: string;
    blockedBy?: string;
    handoffStatus?: string;
    handoffSummary?: string;
    coachOnly?: boolean;
    cardType?: "practice" | "flash";
    cardTitle?: string;
    scenarioPack?: string;
    returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
    returnSummary?: string;
    judgedAt?: string;
    reviewArtifactId?: string;
    reviewArtifactStatus?: string;
    reviewRecoveryMode?: string;
    planEvidenceId?: string;
    nextAfterCompletion?: string;
    fallbackAction?: string;
    sourceChain?: string[];
    /** Humanized training metrics */
    streakDays?: number;
    cardsMastered?: number;
    practiceMinutes?: number;
    todayProgress?: number;
    nextReviewAt?: string;
  };
  latestTrainingSubmode?: TrainingSubmode;
  latestFlashcardBridge?: string;
  latestFlashcardRecoveryMode?: FlashcardRecoveryMode;
  latestLearningFollowup?: string;
  latestLearningFocusArea?: string;
  latestLearningScenario?: string;
  latestLearningVerifiedResult?: string;
  latestTransferEvidenceId?: string;
  latestTransferSourceWorkspaceId?: string;
  latestTransferTargetWorkspaceId?: string;
  latestTransferVerifiedResult?: string;
  latestTransferBlockedReason?: string;
  latestLearningBlocker?: string;
  latestLearningAbandonReason?: string;
  latestLearningPartialProgress?: string;
  selectedCardId?: string;
  selectedCardType?: "practice" | "flash";
  selectedCardTitle?: string;
  selectedCardStatus?: TrainingCardStatus;
  theoryDrill?: TheoryDrillSnapshot;
  theoryDrillHistory?: TheoryDrillHistoryEntry[];
  scenarioLab?: ScenarioLab;
  reviewArtifact?: ReviewArtifact;
  dependencySkillMaps?: DependencySkillMap[];
  dependencySkillMapHistory?: DependencySkillMapHistoryEntry[];
  dueReviews?: ReviewQueueItem[];
  reviewQueueActions?: ReviewQueueAction[];
  scenarioLabHistory?: ScenarioLabHistoryEntry[];
  reviewArtifactHistory?: ReviewArtifactHistoryEntry[];
  trainingCardCandidates?: unknown[];
  activeTrainingCardRouting?: unknown;
  trainingEventLedger?: TrainingEventLedgerEntry[];
};

export interface CoachTrainingViewProps {
  language: ComposerLanguage;
  task?: TaskSpec;
  isLoading?: boolean;
  workspaceUnderstanding?: WorkspaceUnderstanding;
  evidencePack?: EvidencePack;
  teachingDecision?: TeachingDecision;
  recoveredRuntime?: boolean;
  runtimeCurrentStep?: string;
  implementationGuide?: ImplementationGuide;
  dependencyMastery: DependencyMastery[];
  learningOutcomes: LearningOutcome[];
  memoryLayers?: MemoryLayerView[];
  workspaceAuthority?: WorkspaceAuthority;
  reviewSummary?: string;
  practiceBusy?: boolean;
  flashBusy?: boolean;
  transferWorkspaceOptions?: TransferWorkspaceOption[];
  flashDeck?: FlashcardDeck;
  recentFlashAttempts: FlashcardAttempt[];
  flashPracticeBridge?: FlashPracticeBridge;
  workspaceTrainingState?: WorkspaceTrainingState;
  initialTrainingSubmode?: TrainingSubmode;
  onTrainingSubmodeChange?: (submode: TrainingSubmode) => void;
  onRefreshTask: (focusArea?: string) => void;
  onQuickStartTraining?: (mode: "flash" | "practice" | "review") => void;
  onOpenCoachFromPractice?: (bridge: PracticeCoachBridge) => void;
  onRefreshDeck: () => void;
  onSubmitFlashAnswer: (payload: {
    cardId: string;
    learnerAnswer?: string;
    selectedOptionIndex?: number;
    selectedOptionIndices?: number[];
    fillBlankAnswers?: Record<number, string>;
    sortOrder?: number[];
  }) => void;
  onSubmitTheoryDrillAnswer: (payload: {
    theoryDrillId: string;
    questionId: string;
    learnerAnswer?: string;
    selectedOptionIndex?: number;
  }) => void;
  onTheoryDrillAction?: (payload: {
    theoryDrillId: string;
    action: "archive" | "reopen" | "restore_history";
    note?: string;
    historyEntryId?: string;
    historyVersion?: number;
  }) => void;
  onOpenCoachFromFlash?: () => void;
  onOpenCoachBridgeFromFlash?: (bridge: PracticeCoachBridge) => void;
  onOpenPracticeFromFlash?: (bridge: FlashPracticeBridge) => void;
  onCreateFlashcard?: (payload: {
    question: string;
    answerMode: "text" | "single_choice" | "multiple_choice" | "fill_blank" | "sorting" | "true_false";
    options?: string[];
    expectedAnswer?: string;
    correctOptionIndex?: number;
    correctOptionIndices?: number[];
    correctSortOrder?: number[];
    fillBlankAnswers?: Record<number, string>;
    hintLadder?: string[];
    context?: string;
  }) => void;
  onOpenResources?: () => void;
  onOpenReviewCoach?: (focusArea?: string) => void;
  onReviewQueueAction?: (payload: {
    concept: string;
    action: "accept" | "snooze" | "done" | "skip" | "reset";
    scope?: "single" | "all_due" | "focus_area";
    batchLimit?: number;
    focusArea?: string;
    taskHint?: string;
    note?: string;
  }) => void;
  onScenarioLabAction?: (payload: {
    scenarioLabId: string;
    action: "start" | "complete" | "archive" | "reopen" | "review" | "restore_history";
    note?: string;
    reviewOutcome?: string;
    historyEntryId?: string;
    historyVersion?: number;
  }) => void;
  onReviewArtifactAction?: (payload: {
    reviewArtifactId: string;
    action: "updated" | "reviewed" | "resolved" | "reopened" | "archived" | "restore_history";
    note?: string;
    historyEntryId?: string;
    historyVersion?: number;
    editPatch?: Record<string, unknown>;
  }) => void;
  onDependencySkillMapAction?: (payload: {
    dependencyKey: string;
    action:
      | "restore_history"
      | "send_to_flashcards"
      | "start_scenario_lab"
      | "request_verification"
      | "reset_basics";
    note?: string;
    historyEntryId?: string;
    historyVersion?: number;
    focusItemKey?: string;
    relatedApi?: string;
    scenario?: string;
  }) => void;
  onTrainingRestoreOrchestration?: (payload: {
    runId: string;
    note?: string;
    dryRun?: boolean;
    steps: ReturnType<typeof buildTrainingRestoreOrchestrationSteps>;
  }) => void;
  onCardStatusTransition?: (cardId: string, newStatus: TrainingCardStatus, reason?: string) => void;
  onVerifyCurrentFile?: (request: PracticeFileVerificationRequest) => void;
  debugRestoreTarget?: "theory_drill" | "scenario_lab" | "review_artifact" | "next_hop";
  debugTheoryDrillId?: string;
  debugScenarioLabId?: string;
  debugReviewArtifactId?: string;
  debugRestoredNextHop?: WorkspaceTrainingState["latestTrainingNextHop"];
  onDebugVisibleFacts?: (facts: DebugVisibleTrainingFacts) => void;
}

function normalizeText(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized ? normalized : undefined;
}

function areTransferDraftsEqual(
  left?: TransferEvidenceDraft,
  right?: TransferEvidenceDraft,
): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right) {
    return false;
  }
  return (
    left.dependencyKey === right.dependencyKey &&
    left.sourceWorkspaceId === right.sourceWorkspaceId &&
    left.targetWorkspaceId === right.targetWorkspaceId &&
    left.sourceContext === right.sourceContext &&
    left.targetContext === right.targetContext &&
    left.verifiedResult === right.verifiedResult &&
    left.evidenceSummary === right.evidenceSummary &&
    left.focusItemKey === right.focusItemKey &&
    left.relatedApi === right.relatedApi &&
    left.scenario === right.scenario
  );
}

function normalizeMode(value?: TrainingSubmode): TrainingSurfaceMode {
  return value === "flash" ? "flash" : "project";
}

/**
 * §十五: coach training copy in eight languages (no zh/en binary).
 * The zh-CN string is the record key; every other supported locale maps it to
 * a genuine translation. zh-CN and en-US output stays byte-identical to the
 * pre-migration strings passed at the call sites.
 */
type CoachTrainingLocale = Exclude<ComposerLanguage, "zh-CN">;

const coachTrainingTextCopy: Record<string, Record<CoachTrainingLocale, string>> = {
  "正在准备训练内容...": {
    "en-US": "Preparing training content...",
    "es-ES": "Preparando el contenido de entrenamiento...",
    "fr-FR": "Préparation du contenu d'entraînement...",
    "de-DE": "Trainingsinhalte werden vorbereitet...",
    "ja-JP": "トレーニング内容を準備中...",
    "ko-KR": "트레이닝 콘텐츠를 준비하는 중...",
    "pt-BR": "Preparando o conteúdo de treinamento...",
  },
  "没有当前训练任务": {
    "en-US": "No active training task",
    "es-ES": "No hay ninguna tarea de entrenamiento activa",
    "fr-FR": "Aucune tâche d'entraînement active",
    "de-DE": "Keine aktive Trainingsaufgabe",
    "ja-JP": "現在のトレーニングタスクはありません",
    "ko-KR": "활성 트레이닝 작업이 없습니다",
    "pt-BR": "Nenhuma tarefa de treinamento ativa",
  },
  "从计划开始，或生成训练卡。": {
    "en-US": "Start from the plan or generate a card.",
    "es-ES": "Empieza desde el plan o genera una tarjeta.",
    "fr-FR": "Commencez par le plan ou générez une carte.",
    "de-DE": "Starte mit dem Plan oder erzeuge eine Karte.",
    "ja-JP": "プランから始めるか、トレーニングカードを生成してください。",
    "ko-KR": "계획에서 시작하거나 훈련 카드를 생성하세요.",
    "pt-BR": "Comece pelo plano ou gere um cartão.",
  },
  "开始训练": {
    "en-US": "Start training",
    "es-ES": "Empezar entrenamiento",
    "fr-FR": "Commencer l'entraînement",
    "de-DE": "Training starten",
    "ja-JP": "トレーニングを開始",
    "ko-KR": "트레이닝 시작",
    "pt-BR": "Iniciar treinamento",
  },
  "训练进度": {
    "en-US": "Training progress",
    "es-ES": "Progreso de entrenamiento",
    "fr-FR": "Progression de l'entraînement",
    "de-DE": "Trainingsfortschritt",
    "ja-JP": "トレーニング進捗",
    "ko-KR": "트레이닝 진행률",
    "pt-BR": "Progresso do treinamento",
  },
  "先学习": {
    "en-US": "Learn first",
    "es-ES": "Aprende primero",
    "fr-FR": "Apprendre d'abord",
    "de-DE": "Zuerst lernen",
    "ja-JP": "まず学習",
    "ko-KR": "먼저 학습",
    "pt-BR": "Aprenda primeiro",
  },
  "场景包": {
    "en-US": "Scenario pack",
    "es-ES": "Paquete de escenarios",
    "fr-FR": "Pack de scénarios",
    "de-DE": "Szenariopaket",
    "ja-JP": "シナリオパック",
    "ko-KR": "시나리오 팩",
    "pt-BR": "Pacote de cenários",
  },
  "先读完这组场景的学习摘要，再进入下面的测试。": {
    "en-US": "Read the learning summary for this scenario family before you use the test below.",
    "es-ES": "Lee el resumen de aprendizaje de esta familia de escenarios antes de usar la prueba de abajo.",
    "fr-FR": "Lisez le résumé d'apprentissage de cette famille de scénarios avant d'utiliser le test ci-dessous.",
    "de-DE": "Lies die Lernzusammenfassung dieser Szenarienfamilie, bevor du den folgenden Test nutzt.",
    "ja-JP": "以下のテストを使う前に、このシナリオ群の学習要約を読んでください。",
    "ko-KR": "아래 테스트를 사용하기 전에 이 시나리오 군의 학습 요약을 먼저 읽어주세요.",
    "pt-BR": "Leia o resumo de aprendizado desta família de cenários antes de usar o teste abaixo.",
  },
  "对话到训练的交接": {
    "en-US": "Chat-to-training handoff",
    "es-ES": "Traspaso del chat al entrenamiento",
    "fr-FR": "Passage du coaching à l'entraînement",
    "de-DE": "Übergabe vom Chat zum Training",
    "ja-JP": "チャットからトレーニングへの引き継ぎ",
    "ko-KR": "대화에서 트레이닝으로 인계",
    "pt-BR": "Transição do bate-papo para o treinamento",
  },
  "来源": {
    "en-US": "Origin",
    "es-ES": "Origen",
    "fr-FR": "Origine",
    "de-DE": "Quelle",
    "ja-JP": "提供元",
    "ko-KR": "출처",
    "pt-BR": "Origem",
  },
  "对话交接": {
    "en-US": "Conversation handoff",
    "es-ES": "Traspaso de la conversación",
    "fr-FR": "Passage de la conversation",
    "de-DE": "Gesprächsübergabe",
    "ja-JP": "会話の引き継ぎ",
    "ko-KR": "대화 인계",
    "pt-BR": "Transição da conversa",
  },
  "工作区": {
    "en-US": "Workspace",
    "es-ES": "Espacio de trabajo",
    "fr-FR": "Espace de travail",
    "de-DE": "Workspace",
    "ja-JP": "ワークスペース",
    "ko-KR": "작업 공간",
    "pt-BR": "Espaço de trabalho",
  },
  "类型": {
    "en-US": "Type",
    "es-ES": "Tipo",
    "fr-FR": "Type",
    "de-DE": "Typ",
    "ja-JP": "種類",
    "ko-KR": "유형",
    "pt-BR": "Tipo",
  },
  "路由": {
    "en-US": "Routing",
    "es-ES": "Enrutamiento",
    "fr-FR": "Routage",
    "de-DE": "Routing",
    "ja-JP": "ルーティング",
    "ko-KR": "라우팅",
    "pt-BR": "Roteamento",
  },
  "候选": {
    "en-US": "Candidates",
    "es-ES": "Candidatas",
    "fr-FR": "Candidats",
    "de-DE": "Kandidaten",
    "ja-JP": "候補",
    "ko-KR": "후보",
    "pt-BR": "Candidatos",
  },
  "可用": {
    "en-US": "Eligible",
    "es-ES": "Elegibles",
    "fr-FR": "Éligibles",
    "de-DE": "Geeignete",
    "ja-JP": "利用可能",
    "ko-KR": "적격",
    "pt-BR": "Elegíveis",
  },
  "边界": {
    "en-US": "Boundary",
    "es-ES": "Límite",
    "fr-FR": "Limite",
    "de-DE": "Grenze",
    "ja-JP": "境界",
    "ko-KR": "경계",
    "pt-BR": "Limite",
  },
  "coach-only": {
    "en-US": "coach-only",
    "es-ES": "coach-only",
    "fr-FR": "coach-only",
    "de-DE": "coach-only",
    "ja-JP": "coach-only",
    "ko-KR": "coach-only",
    "pt-BR": "coach-only",
  },
  "引导式": {
    "en-US": "guided",
    "es-ES": "guiado",
    "fr-FR": "guidé",
    "de-DE": "geführt",
    "ja-JP": "ガイド付き",
    "ko-KR": "가이드형",
    "pt-BR": "guiado",
  },
  "默认只保留来源和边界摘要。交付物与验证保持可展开，让单卡主线仍然是第一优先。": {
    "en-US": "By default this keeps only source and boundary summary. Deliverables and verification stay expandable so the single-card lane remains primary.",
    "es-ES": "Por defecto se conservan solo el resumen de origen y de límite. Los entregables y la verificación siguen siendo ampliables para que la vía de una sola tarjeta siga siendo la prioridad.",
    "fr-FR": "Par défaut, seuls le résumé de l'origine et de la limite sont conservés. Les livrables et la vérification restent dépliables pour que la voie à carte unique reste prioritaire.",
    "de-DE": "Standardmäßig werden nur Quell- und Grenzzusammenfassung behalten. Lieferobjekte und Verifizierung bleiben ausklappbar, damit die Ein-Karten-Spur priorisiert bleibt.",
    "ja-JP": "デフォルトでは提供元と境界の要約のみを表示します。成果物と検証は展開可能なまま、単一カードの主流を最優先に保ちます。",
    "ko-KR": "기본적으로 출처와 경계 요약만 유지합니다. 산출물과 검증은 펼쳐볼 수 있도록 남겨 단일 카드 흐름이 최우선으로 유지됩니다.",
    "pt-BR": "Por padrão, mantém apenas o resumo de origem e limite. Entregas e verificação continuam expansíveis para que a trilha de cartão único siga prioridade.",
  },
  "查看卡片契约和验证": {
    "en-US": "Show the card contract and verification",
    "es-ES": "Mostrar el contrato de la tarjeta y la verificación",
    "fr-FR": "Afficher le contrat de la carte et la vérification",
    "de-DE": "Kartenkontrakt und Verifizierung anzeigen",
    "ja-JP": "カードの契約と検証を表示",
    "ko-KR": "카드 계약과 검증 보기",
    "pt-BR": "Mostrar o contrato do cartão e a verificação",
  },
  "你交付": {
    "en-US": "You deliver",
    "es-ES": "Entregas",
    "fr-FR": "Vous livrez",
    "de-DE": "Du lieferst",
    "ja-JP": "あなたの成果物",
    "ko-KR": "제출할 것",
    "pt-BR": "Você entrega",
  },
  "这样验证": {
    "en-US": "Verify like this",
    "es-ES": "Verifica así",
    "fr-FR": "Vérifiez ainsi",
    "de-DE": "So verifizierst du",
    "ja-JP": "このように検証",
    "ko-KR": "이렇게 검증",
    "pt-BR": "Verifique assim",
  },
  "带回": {
    "en-US": "Bring back",
    "es-ES": "Trae de vuelta",
    "fr-FR": "Rapporte",
    "de-DE": "Bringe zurück",
    "ja-JP": "持ち帰り",
    "ko-KR": "가져오기",
    "pt-BR": "Traga de volta",
  },
  "把这张卡的结果和验证输出带回来，再让教练判断是复习、升级，还是写入计划证据。": {
    "en-US": "Bring back the result of this card plus the verification output, then let the coach decide whether to review, level up, or feed it back into plan evidence.",
    "es-ES": "Trae de vuelta el resultado de esta tarjeta junto con la salida de verificación, y deja que el coach decida si repasar, subir de nivel o incorporarlo como evidencia del plan.",
    "fr-FR": "Rapporte le résultat de cette carte avec la sortie de vérification, puis laisse le coach décider s'il faut réviser, monter en niveau ou l'intégrer comme preuve dans le plan.",
    "de-DE": "Bringe das Ergebnis dieser Karte zusammen mit der Verifizierungsausgabe zurück und lasse den Coach entscheiden, ob wiederholt, aufgestiegen oder als Plan-Nachweis verbucht wird.",
    "ja-JP": "このカードの結果と検証出力を持ち帰り、復習するか、レベルを上げるか、プランの証拠に書き込むかをコーチに判断させましょう。",
    "ko-KR": "이 카드의 결과와 검증 출력을 가져와 복습할지, 수준을 올릴지, 계획 증거로 기록할지 코치가 판단하도록 하세요.",
    "pt-BR": "Traga de volta o resultado deste cartão junto com a saída de verificação e deixe o coach decidir entre revisar, subir de nível ou registrar como evidência do plano.",
  },
  "训练已暂停": {
    "en-US": "Training paused",
    "es-ES": "Entrenamiento en pausa",
    "fr-FR": "Entraînement en pause",
    "de-DE": "Training pausiert",
    "ja-JP": "トレーニングは一時停止中",
    "ko-KR": "트레이닝 일시 중지",
    "pt-BR": "Treinamento pausado",
  },
  "Trainer 不会继续从过期资料路由训练卡，也不会假装这张卡仍然安全可继续。": {
    "en-US": "Trainer will not keep routing cards from stale material or pretend this card is still safe to continue.",
    "es-ES": "Trainer no seguirá enrutando tarjetas desde material obsoleto ni fingirá que esta tarjeta sigue siendo segura para continuar.",
    "fr-FR": "Trainer ne continuera pas de router des cartes depuis un matériau obsolète ni ne fera semblant que cette carte reste sûre à poursuivre.",
    "de-DE": "Trainer routet keine Karten mehr aus veraltetem Material und tut nicht so, als wäre diese Karte noch sicher fortsetzbar.",
    "ja-JP": "Trainer は古い資料からカードをルーティングし続けず、このカードがまだ安全に続けられるふりもしません。",
    "ko-KR": "Trainer는 오래된 자료에서 카드를 계속 라우팅하지 않으며 이 카드가 여전히 안전하게 계속된다고 가장하지 않습니다.",
    "pt-BR": "O Trainer não continuará roteando cartões de material desatualizado nem fingirá que este cartão ainda é seguro para continuar.",
  },
  "打开资料": {
    "en-US": "Open Resources",
    "es-ES": "Abrir recursos",
    "fr-FR": "Ouvrir les ressources",
    "de-DE": "Ressourcen öffnen",
    "ja-JP": "資料を開く",
    "ko-KR": "자료 열기",
    "pt-BR": "Abrir recursos",
  },
  "先用资料页修正来源，再强制继续": {
    "en-US": "Use resources as support before forcing the route",
    "es-ES": "Corrige la fuente en recursos antes de forzar la ruta",
    "fr-FR": "Corrige la source dans les ressources avant de forcer la route",
    "de-DE": "Korrigiere die Quelle in den Ressourcen, bevor du die Route erzwingst",
    "ja-JP": "ルートを強制する前に資料ページでソースを修正する",
    "ko-KR": "경로를 강제하기 전에 자료 페이지에서 소스를 수정",
    "pt-BR": "Corrija a fonte nos recursos antes de forçar a rota",
  },
  "刷新训练路由": {
    "en-US": "Refresh training route",
    "es-ES": "Actualizar la ruta de entrenamiento",
    "fr-FR": "Actualiser la route d'entraînement",
    "de-DE": "Trainingsroute aktualisieren",
    "ja-JP": "トレーニングルートを更新",
    "ko-KR": "트레이닝 경로 새로 고침",
    "pt-BR": "Atualizar a rota de treinamento",
  },
  "重新收紧这张卡的下一步": {
    "en-US": "Tighten the next step for this card again",
    "es-ES": "Vuelve a ajustar el siguiente paso de esta tarjeta",
    "fr-FR": "Resserre à nouveau l'étape suivante de cette carte",
    "de-DE": "Ziehe den nächsten Schritt dieser Karte erneut zusammen",
    "ja-JP": "このカードの次のステップを再度引き締める",
    "ko-KR": "이 카드의 다음 단계를 다시 조이기",
    "pt-BR": "Restrinja novamente o próximo passo deste cartão",
  },
  "同轮还有候选卡被阻塞：": {
    "en-US": "Some same-turn candidates were blocked: ",
    "es-ES": "Algunas candidatas del mismo turno fueron bloqueadas: ",
    "fr-FR": "Certaines candidates du même tour ont été bloquées : ",
    "de-DE": "Einige Kandidaten desselben Zuges wurden blockiert: ",
    "ja-JP": "同じターンの候補カードの一部がブロックされました: ",
    "ko-KR": "같은 턴의 일부 후보 카드가 차단되었습니다: ",
    "pt-BR": "Alguns candidatos do mesmo turno foram bloqueados: ",
  },
  "迁移评估 ->": {
    "en-US": "Transfer assessment ->",
    "es-ES": "Evaluación de transferencia ->",
    "fr-FR": "Évaluation de transfert ->",
    "de-DE": "Transferbewertung ->",
    "ja-JP": "転移評価 ->",
    "ko-KR": "전이 평가 ->",
    "pt-BR": "Avaliação de transferência ->",
  },
  "依赖/API 掌握度": {
    "en-US": "Dependency/API mastery",
    "es-ES": "Dominio de dependencias/API",
    "fr-FR": "Maîtrise des dépendances/API",
    "de-DE": "Abhängigkeits-/API-Beherrschung",
    "ja-JP": "依存関係/API の習得度",
    "ko-KR": "의존성/API 숙련도",
    "pt-BR": "Domínio de dependências/API",
  },
  "等待训练证据": {
    "en-US": "Waiting for training evidence",
    "es-ES": "Esperando evidencia de entrenamiento",
    "fr-FR": "En attente de preuves d'entraînement",
    "de-DE": "Warte auf Trainingsnachweise",
    "ja-JP": "トレーニングの証拠を待機中",
    "ko-KR": "트레이닝 증거 대기 중",
    "pt-BR": "Aguardando evidência de treinamento",
  },
  "只使用当前卡片关联的证据": {
    "en-US": "Only evidence tied to the current card",
    "es-ES": "Solo evidencia vinculada a la tarjeta actual",
    "fr-FR": "Uniquement les preuves liées à la carte actuelle",
    "de-DE": "Nur Nachweise, die zur aktuellen Karte gehören",
    "ja-JP": "現在のカードに関連する証拠のみ",
    "ko-KR": "현재 카드에 연결된 증거만",
    "pt-BR": "Apenas evidência vinculada ao cartão atual",
  },
  "当前卡片产出证据后再展开": {
    "en-US": "Expand after the current card produces evidence",
    "es-ES": "Despliega cuando la tarjeta actual produzca evidencia",
    "fr-FR": "Déplie une fois que la carte actuelle produit des preuves",
    "de-DE": "Klapp auf, sobald die aktuelle Karte Nachweise liefert",
    "ja-JP": "現在のカードが証拠を出したら展開",
    "ko-KR": "현재 카드가 증거를 내면 펼치기",
    "pt-BR": "Expanda depois que o cartão atual produzir evidência",
  },
  "当前阶段": {
    "en-US": "Current stage",
    "es-ES": "Etapa actual",
    "fr-FR": "Étape actuelle",
    "de-DE": "Aktuelle Phase",
    "ja-JP": "現在のステージ",
    "ko-KR": "현재 단계",
    "pt-BR": "Etapa atual",
  },
  "理解、回忆、练习、应用、迁移是不同证据层。完成次数本身不等于掌握。": {
    "en-US": "Understanding, recall, practice, application, and transfer are evidence layers. Completion count is not mastery.",
    "es-ES": "Comprender, recordar, practicar, aplicar y transferir son capas de evidencia distintas. El número de finalizaciones no es dominio por sí solo.",
    "fr-FR": "Comprendre, se rappeler, pratiquer, appliquer et transférer sont des couches de preuve distinctes. Le nombre d'achèvements ne vaut pas maîtrise à lui seul.",
    "de-DE": "Verstehen, Abrufen, Üben, Anwenden und Transferieren sind eigene Nachweisebenen. Die Anzahl der Abschlüsse ist für sich keine Beherrschung.",
    "ja-JP": "理解・想起・練習・応用・転移はそれぞれ異なる証拠の層です。完了回数そのものは習得を意味しません。",
    "ko-KR": "이해·회상·연습·적용·전이는 서로 다른 증거 층입니다. 완료 횟수 자체가 숙련을 의미하지는 않습니다.",
    "pt-BR": "Compreender, recordar, praticar, aplicar e transferir são camadas de evidência distintas. O número de conclusões não é, por si só, domínio.",
  },
  "下一步": {
    "en-US": "Next step",
    "es-ES": "Siguiente paso",
    "fr-FR": "Prochaine étape",
    "de-DE": "Nächster Schritt",
    "ja-JP": "次のステップ",
    "ko-KR": "다음 단계",
    "pt-BR": "Próximo passo",
  },
  "继续当前卡片": {
    "en-US": "Continue the current card",
    "es-ES": "Continúa la tarjeta actual",
    "fr-FR": "Continue la carte actuelle",
    "de-DE": "Fahre mit der aktuellen Karte fort",
    "ja-JP": "現在のカードを続行",
    "ko-KR": "현재 카드 계속",
    "pt-BR": "Continue o cartão atual",
  },
  "先完成一个由学习者自己掌握的切片，再记录证据。": {
    "en-US": "Finish a learner-owned slice before recording evidence.",
    "es-ES": "Termina un fragmento dominado por el propio aprendiz antes de registrar evidencia.",
    "fr-FR": "Termine une tranche maîtrisée par l'apprenant lui-même avant d'enregistrer des preuves.",
    "de-DE": "Schließe einen Abschnitt ab, den du selbst beherrschst, bevor du Nachweise aufzeichnest.",
    "ja-JP": "学習者自身が習得したスライスを完了してから、証拠を記録してください。",
    "ko-KR": "학습자 자신이 습득한 슬라이스를 먼저 완료한 뒤 증거를 기록하세요.",
    "pt-BR": "Conclua uma fatia dominada pelo próprio aprendiz antes de registrar evidência.",
  },
  "迁移说明（待验证）": {
    "en-US": "Transfer note (waiting for verification)",
    "es-ES": "Nota de transferencia (pendiente de verificación)",
    "fr-FR": "Note de transfert (en attente de vérification)",
    "de-DE": "Transfernotiz (wartet auf Verifizierung)",
    "ja-JP": "転移メモ（検証待ち）",
    "ko-KR": "전이 노트(검증 대기 중)",
    "pt-BR": "Nota de transferência (aguardando verificação)",
  },
  "可提交说明": {
    "en-US": "Ready to submit note",
    "es-ES": "Nota lista para enviar",
    "fr-FR": "Note prête à envoyer",
    "de-DE": "Notiz sendebereit",
    "ja-JP": "メモ送信可能",
    "ko-KR": "노트 제출 가능",
    "pt-BR": "Nota pronta para enviar",
  },
  "需要补充": {
    "en-US": "Needs details",
    "es-ES": "Faltan detalles",
    "fr-FR": "Détails manquants",
    "de-DE": "Ergänzungen nötig",
    "ja-JP": "補足が必要",
    "ko-KR": "보충 필요",
    "pt-BR": "Faltam detalhes",
  },
  "填写说明不会直接改变掌握记录，提交后由 Trainer 验证。": {
    "en-US": "A note does not change mastery by itself. Trainer verifies it after submission.",
    "es-ES": "Rellenar la nota no cambia el registro de dominio por sí solo; Trainer la verifica después de enviarla.",
    "fr-FR": "Remplir la note ne change pas en soi le relevé de maîtrise ; Trainer la vérifie après soumission.",
    "de-DE": "Das Ausfüllen der Notiz ändert den Mastery-Eintrag nicht direkt; Trainer verifiziert sie nach dem Absenden.",
    "ja-JP": "メモを記入しても習得記録は直接変わらず、送信後に Trainer が検証します。",
    "ko-KR": "노트를 작성한다고 숙련 기록이 바로 바뀌지 않으며, 제출 후 Trainer가 검증합니다.",
    "pt-BR": "Preencher a nota não altera por si o registro de domínio; o Trainer a verifica após o envio.",
  },
  "源工作区": {
    "en-US": "Source workspace",
    "es-ES": "Espacio de trabajo de origen",
    "fr-FR": "Espace de travail source",
    "de-DE": "Quell-Workspace",
    "ja-JP": "ソースワークスペース",
    "ko-KR": "소스 작업 공간",
    "pt-BR": "Espaço de trabalho de origem",
  },
  "目标工作区": {
    "en-US": "Target workspace",
    "es-ES": "Espacio de trabajo de destino",
    "fr-FR": "Espace de travail cible",
    "de-DE": "Ziel-Workspace",
    "ja-JP": "ターゲットワークスペース",
    "ko-KR": "대상 작업 공간",
    "pt-BR": "Espaço de trabalho de destino",
  },
  "选择目标工作区": {
    "en-US": "Choose target workspace",
    "es-ES": "Elige el espacio de trabajo de destino",
    "fr-FR": "Choisis l'espace de travail cible",
    "de-DE": "Ziel-Workspace wählen",
    "ja-JP": "ターゲットワークスペースを選択",
    "ko-KR": "대상 작업 공간 선택",
    "pt-BR": "Escolha o espaço de trabalho de destino",
  },
  "（推荐）": {
    "en-US": " (Recommended)",
    "es-ES": " (recomendado)",
    "fr-FR": " (recommandé)",
    "de-DE": " (empfohlen)",
    "ja-JP": "（推奨）",
    "ko-KR": "(추천)",
    "pt-BR": " (recomendado)",
  },
  "迁移说明": {
    "en-US": "Transfer note",
    "es-ES": "Nota de transferencia",
    "fr-FR": "Note de transfert",
    "de-DE": "Transfernotiz",
    "ja-JP": "転移メモ",
    "ko-KR": "전이 노트",
    "pt-BR": "Nota de transferência",
  },
  "补充说明": {
    "en-US": "Evidence note",
    "es-ES": "Nota de evidencia",
    "fr-FR": "Note de preuve",
    "de-DE": "Nachweisnotiz",
    "ja-JP": "証拠メモ",
    "ko-KR": "증거 노트",
    "pt-BR": "Nota de evidência",
  },
  "更多动作": {
    "en-US": "More actions",
    "es-ES": "Más acciones",
    "fr-FR": "Plus d'actions",
    "de-DE": "Weitere Aktionen",
    "ja-JP": "その他のアクション",
    "ko-KR": "더 많은 작업",
    "pt-BR": "Mais ações",
  },
  "把当前薄弱点送回闪卡巩固。": {
    "en-US": "Push the current weak spot back into flashcards.",
    "es-ES": "Devuelve el punto débil actual a las tarjetas flash para reforzarlo.",
    "fr-FR": "Renvoie le point faible actuel dans les flashcards pour le consolider.",
    "de-DE": "Schiebe die aktuelle Schwachstelle zurück in die Flashcards, um sie zu festigen.",
    "ja-JP": "現在の弱点をフラッシュカードに戻して定着させましょう。",
    "ko-KR": "현재 약점을 플래시카드로 돌려보내 보강하세요.",
    "pt-BR": "Devolva o ponto fraco atual aos cartões flash para consolidá-lo.",
  },
  "送去闪卡": {
    "en-US": "Send to flashcards",
    "es-ES": "Enviar a tarjetas flash",
    "fr-FR": "Envoyer vers les flashcards",
    "de-DE": "Zu Flashcards senden",
    "ja-JP": "フラッシュカードへ送る",
    "ko-KR": "플래시카드로 보내기",
    "pt-BR": "Enviar para cartões flash",
  },
  "先用一个最小场景把它稳定下来。": {
    "en-US": "Stabilize this with a minimum scenario first.",
    "es-ES": "Estabilízalo primero con un escenario mínimo.",
    "fr-FR": "Stabilise-le d'abord avec un scénario minimal.",
    "de-DE": "Stabilisiere es zuerst mit einem minimalen Szenario.",
    "ja-JP": "まず最小のシナリオで安定させましょう。",
    "ko-KR": "먼저 최소 시나리오로 안정화하세요.",
    "pt-BR": "Estabilize isso primeiro com um cenário mínimo.",
  },
  "场景实验": {
    "en-US": "Scenario lab",
    "es-ES": "Laboratorio de escenarios",
    "fr-FR": "Laboratoire de scénarios",
    "de-DE": "Szenariolabor",
    "ja-JP": "シナリオ実験",
    "ko-KR": "시나리오 실험",
    "pt-BR": "Laboratório de cenários",
  },
  "完成后显示掌握证据和下一步。": {
    "en-US": "Completion shows mastery evidence and the next step.",
    "es-ES": "Al completar se muestran la evidencia de dominio y el siguiente paso.",
    "fr-FR": "Une fois terminé, affiche les preuves de maîtrise et l'étape suivante.",
    "de-DE": "Nach dem Abschluss werden Mastery-Nachweise und der nächste Schritt angezeigt.",
    "ja-JP": "完了すると習得の証拠と次のステップが表示されます。",
    "ko-KR": "완료하면 숙련 증거와 다음 단계가 표시됩니다.",
    "pt-BR": "Ao concluir, mostra a evidência de domínio e o próximo passo.",
  },
  "等待训练路由确认当前卡片": {
    "en-US": "Waiting for the training router to confirm the card",
    "es-ES": "Esperando a que el router de entrenamiento confirme la tarjeta",
    "fr-FR": "En attente de la confirmation de la carte par le routeur d'entraînement",
    "de-DE": "Warte darauf, dass der Trainingsrouter die Karte bestätigt",
    "ja-JP": "トレーニングルーターがカードを確認するのを待機中",
    "ko-KR": "트레이닝 라우터가 카드를 확인하기를 기다리는 중",
    "pt-BR": "Aguardando o roteador de treinamento confirmar o cartão",
  },
  "这张训练卡被资料风险暂停。继续前先刷新来源资料。": {
    "en-US": "This training card is paused by resource risk. Refresh the source material before continuing.",
    "es-ES": "Esta tarjeta de entrenamiento está en pausa por riesgo de recursos. Actualiza el material de origen antes de continuar.",
    "fr-FR": "Cette carte d'entraînement est en pause à cause d'un risque de ressources. Actualise le matériau source avant de continuer.",
    "de-DE": "Diese Trainingskarte ist wegen Ressourcenrisiko pausiert. Aktualisiere das Quellmaterial, bevor du fortfährst.",
    "ja-JP": "このトレーニングカードは資料リスクのため一時停止中です。続ける前にソース資料を更新してください。",
    "ko-KR": "이 훈련 카드는 자료 위험으로 일시 중지되었습니다. 계속하기 전에 소스 자료를 새로 고치세요.",
    "pt-BR": "Este cartão de treinamento está pausado por risco de recursos. Atualize o material de origem antes de continuar.",
  },
  "恢复的下一步已经成为前景，旧的理论、场景和复习对象不再抢占当前卡片。": {
    "en-US": "The restored next hop is now the foreground, so legacy theory, scenario, and review objects no longer take over the lane.",
    "es-ES": "El siguiente paso restaurado es ahora el primer plano, así que los objetos heredados de teoría, escenario y repaso ya no ocupan la vía.",
    "fr-FR": "L'étape suivante restaurée est désormais au premier plan, donc les objets hérités de théorie, de scénario et de révision ne prennent plus la voie.",
    "de-DE": "Der wiederhergestellte nächste Schritt ist jetzt im Vordergrund, daher übernehmen alte Theorie-, Szenario- und Wiederholungsobjekte die Spur nicht mehr.",
    "ja-JP": "復元された次のステップが前面になり、旧来の理論・シナリオ・復習オブジェクトは現在のカードを奪いません。",
    "ko-KR": "복원된 다음 단계가 이제 전면에 있으므로 기존 이론·시나리오·복습 객체가 더 이상 현재 카드를 빼앗지 않습니다.",
    "pt-BR": "O próximo passo restaurado agora está em primeiro plano, então objetos legados de teoria, cenário e revisão não tomam mais a trilha.",
  },
  "这张卡来自对话交接，训练页现在只聚焦这一张当前卡。": {
    "en-US": "This card came from conversation, and training now stays focused on this single current card.",
    "es-ES": "Esta tarjeta viene de la conversación, y el entrenamiento ahora se centra solo en esta tarjeta actual.",
    "fr-FR": "Cette carte vient de la conversation, et l'entraînement se concentre désormais sur cette seule carte actuelle.",
    "de-DE": "Diese Karte stammt aus dem Gespräch, und das Training fokussiert jetzt nur auf diese eine aktuelle Karte.",
    "ja-JP": "このカードは会話の引き継ぎから来ており、トレーニングは今この現在のカード 1 枚に集中します。",
    "ko-KR": "이 카드는 대화 인계에서 왔으며 트레이닝은 이제 이 현재 카드 한 장에만 집중합니다.",
    "pt-BR": "Este cartão veio da conversa e o treinamento agora se concentra apenas neste cartão atual.",
  },
  "闪卡": {
    "en-US": "Flash card",
    "es-ES": "Tarjeta flash",
    "fr-FR": "Flashcard",
    "de-DE": "Flashcard",
    "ja-JP": "フラッシュカード",
    "ko-KR": "플래시 카드",
    "pt-BR": "Cartão flash",
  },
  "练习卡": {
    "en-US": "Practice card",
    "es-ES": "Tarjeta de práctica",
    "fr-FR": "Carte de pratique",
    "de-DE": "Übungskarte",
    "ja-JP": "練習カード",
    "ko-KR": "연습 카드",
    "pt-BR": "Cartão de prática",
  },
  "关联资料已经过期或可信度不足。继续训练卡前，先在资料页刷新。": {
    "en-US": "A linked resource is stale or not trusted enough. Refresh it in Resources before continuing this training card.",
    "es-ES": "Un recurso vinculado está obsoleto o no es lo bastante confiable. Actualízalo en Recursos antes de continuar con esta tarjeta.",
    "fr-FR": "Une ressource liée est obsolète ou pas assez fiable. Actualise-la dans Ressources avant de continuer cette carte d'entraînement.",
    "de-DE": "Eine verknüpfte Ressource ist veraltet oder nicht vertrauenswürdig genug. Aktualisiere sie in den Ressourcen, bevor du diese Trainingskarte fortsetzt.",
    "ja-JP": "リンクされた資料が古いか、信頼性が十分ではありません。このトレーニングカードを続ける前に、資料ページで更新してください。",
    "ko-KR": "연결된 자료가 오래되었거나 신뢰도가 부족합니다. 이 훈련 카드를 계속하기 전에 자료 페이지에서 새로 고치세요.",
    "pt-BR": "Um recurso vinculado está desatualizado ou não é confiável o suficiente. Atualize-o em Recursos antes de continuar este cartão de treinamento.",
  },
  "下一步已经成形": {
    "en-US": "Next hop materialized",
    "es-ES": "El siguiente paso ya está definido",
    "fr-FR": "L'étape suivante est déjà définie",
    "de-DE": "Der nächste Schritt steht bereits",
    "ja-JP": "次のステップが固まりました",
    "ko-KR": "다음 단계가 구체화되었습니다",
    "pt-BR": "O próximo passo já está definido",
  },
  "回到计划继续": {
    "en-US": "Continue in plan",
    "es-ES": "Continúa en el plan",
    "fr-FR": "Continue dans le plan",
    "de-DE": "Im Plan weitermachen",
    "ja-JP": "プランで続行",
    "ko-KR": "계획에서 계속",
    "pt-BR": "Continue no plano",
  },
  "回到对话继续": {
    "en-US": "Return to coach",
    "es-ES": "Vuelve al coach",
    "fr-FR": "Revient au coach",
    "de-DE": "Zurück zum Coach",
    "ja-JP": "コーチに戻る",
    "ko-KR": "코치로 돌아가기",
    "pt-BR": "Volte ao coach",
  },
  "继续训练": {
    "en-US": "Continue training",
    "es-ES": "Continúa el entrenamiento",
    "fr-FR": "Poursuis l'entraînement",
    "de-DE": "Training fortsetzen",
    "ja-JP": "トレーニングを続行",
    "ko-KR": "트레이닝 계속",
    "pt-BR": "Continue o treinamento",
  },
  "恢复的下一步必须留在前景，不再回退到旧链路。": {
    "en-US": "The restored next hop must stay in the foreground; do not fall back to the old chain.",
    "es-ES": "El siguiente paso restaurado debe permanecer en primer plano; no retrocedas a la cadena antigua.",
    "fr-FR": "L'étape suivante restaurée doit rester au premier plan ; ne retombe pas sur l'ancienne chaîne.",
    "de-DE": "Der wiederhergestellte nächste Schritt muss im Vordergrund bleiben; falle nicht auf die alte Kette zurück.",
    "ja-JP": "復元された次のステップは前面に残す必要があり、古いチェーンにフォールバックしてはいけません。",
    "ko-KR": "복원된 다음 단계는 전면에 남아 있어야 하며 이전 체인으로 폴백하지 않습니다.",
    "pt-BR": "O próximo passo restaurado deve permanecer em primeiro plano; não volte à cadeia antiga.",
  },
  "训练视图需要直接展示并解释当前下一步。": {
    "en-US": "The training view should directly show and explain the current next hop.",
    "es-ES": "La vista de entrenamiento debe mostrar y explicar directamente el siguiente paso actual.",
    "fr-FR": "La vue d'entraînement doit montrer et expliquer directement l'étape suivante actuelle.",
    "de-DE": "Die Trainingsansicht muss den aktuellen nächsten Schritt direkt zeigen und erklären.",
    "ja-JP": "トレーニングビューは現在の次のステップを直接表示して説明する必要があります。",
    "ko-KR": "트레이닝 뷰는 현재 다음 단계를 직접 보여주고 설명해야 합니다.",
    "pt-BR": "A visão de treinamento deve mostrar e explicar diretamente o próximo passo atual.",
  },
  "已记录为待验证。请回到当前练习并使用“验证当前文件”。": {
    "en-US": "Recorded as waiting for verification. Return to the current practice and use Verify current file.",
    "es-ES": "Registrado como pendiente de verificación. Vuelve a la práctica actual y usa Verificar archivo actual.",
    "fr-FR": "Enregistré comme en attente de vérification. Retourne à la pratique actuelle et utilise Vérifier le fichier actuel.",
    "de-DE": "Als wartend auf Verifizierung erfasst. Kehre zur aktuellen Übung zurück und nutze Aktuelle Datei verifizieren.",
    "ja-JP": "検証待ちとして記録しました。現在の練習に戻り、「現在のファイルを検証」を使ってください。",
    "ko-KR": "검증 대기로 기록되었습니다. 현재 연습으로 돌아가 현재 파일 검증을 사용하세요.",
    "pt-BR": "Registrado como aguardando verificação. Volte à prática atual e use Verificar arquivo atual.",
  },
  "回到教练": {
    "en-US": "Return to coach",
    "es-ES": "Volver al coach",
    "fr-FR": "Revenir au coach",
    "de-DE": "Zurück zum Coach",
    "ja-JP": "コーチに戻る",
    "ko-KR": "코치로 돌아가기",
    "pt-BR": "Voltar ao coach",
  },
  "当前工作区": {
    "en-US": "Current workspace",
    "es-ES": "Espacio de trabajo actual",
    "fr-FR": "Espace de travail actuel",
    "de-DE": "Aktueller Workspace",
    "ja-JP": "現在のワークスペース",
    "ko-KR": "현재 작업 공간",
    "pt-BR": "Espaço de trabalho atual",
  },
  "让教练判断它是通过、部分通过、降级、计划证据，还是需要回到闪卡巩固。": {
    "en-US": "Let the coach judge whether this was a pass, partial pass, downgrade, plan evidence, or flash reinforcement.",
    "es-ES": "Deja que el coach juzgue si fue un aprobado, un aprobado parcial, una degradación, evidencia para el plan o un refuerzo con flashcards.",
    "fr-FR": "Laisse le coach juger si c'était une réussite, une réussite partielle, une rétrogradation, une preuve pour le plan ou un renforcement par flashcards.",
    "de-DE": "Lass den Coach entscheiden, ob dies ein Bestehen, Teilbestehen, eine Herabstufung, ein Plan-Nachweis oder eine Flash-Auffrischung war.",
    "ja-JP": "合格か部分合格か、降格か、プランの証拠か、それともフラッシュカードでの復習が必要かをコーチに判断させましょう。",
    "ko-KR": "통과인지 부분 통과인지, 강등인지, 계획 증거인지, 아니면 플래시카드 보강이 필요한지 코치가 판단하게 하세요.",
    "pt-BR": "Deixe o coach julgar se foi aprovação, aprovação parcial, rebaixamento, evidência para o plano ou reforço com flashcards.",
  },
};

/** Parameterized copy: "{0}" is replaced with the single interpolated value. */
const coachTrainingTemplateTextCopy: Record<
  string,
  Record<CoachTrainingLocale, (value: string) => string>
> = {
  "验证结果：{0}": {
    "en-US": (value) => `Verification result: ${value}`,
    "es-ES": (value) => `Resultado de la verificación: ${value}`,
    "fr-FR": (value) => `Résultat de la vérification : ${value}`,
    "de-DE": (value) => `Verifizierungsergebnis: ${value}`,
    "ja-JP": (value) => `検証結果：${value}`,
    "ko-KR": (value) => `검증 결과: ${value}`,
    "pt-BR": (value) => `Resultado da verificação: ${value}`,
  },
  "当前卡点：{0}": {
    "en-US": (value) => `Current blocker: ${value}`,
    "es-ES": (value) => `Bloqueo actual: ${value}`,
    "fr-FR": (value) => `Bloquage actuel : ${value}`,
    "de-DE": (value) => `Aktuelle Blockade: ${value}`,
    "ja-JP": (value) => `現在のブロッカー：${value}`,
    "ko-KR": (value) => `현재 블로커: ${value}`,
    "pt-BR": (value) => `Bloqueio atual: ${value}`,
  },
  "带回：{0}": {
    "en-US": (value) => `Bring back: ${value}`,
    "es-ES": (value) => `Traer de vuelta: ${value}`,
    "fr-FR": (value) => `À rapporter : ${value}`,
    "de-DE": (value) => `Zurückbringen: ${value}`,
    "ja-JP": (value) => `持ち帰り：${value}`,
    "ko-KR": (value) => `가져가기: ${value}`,
    "pt-BR": (value) => `Trazer de volta: ${value}`,
  },
  "通过信号：{0}": {
    "en-US": (value) => `Pass signal: ${value}`,
    "es-ES": (value) => `Señal de aprobado: ${value}`,
    "fr-FR": (value) => `Signal de réussite : ${value}`,
    "de-DE": (value) => `Bestehenssignal: ${value}`,
    "ja-JP": (value) => `合格シグナル：${value}`,
    "ko-KR": (value) => `통과 신호: ${value}`,
    "pt-BR": (value) => `Sinal de aprovação: ${value}`,
  },
  "把「{0}」带回教练判断": {
    "en-US": (value) => `Bring "${value}" back to coach`,
    "es-ES": (value) => `Trae «${value}» al coach para que juzgue`,
    "fr-FR": (value) => `Rapporte « ${value} » au coach pour jugement`,
    "de-DE": (value) => `Bring "${value}" zur Coach-Bewertung zurück`,
    "ja-JP": (value) => `「${value}」をコーチの判断に持ち帰る`,
    "ko-KR": (value) => `「${value}」을(를) 코치 판단으로 가져가기`,
    "pt-BR": (value) => `Traga "${value}" de volta ao coach para julgamento`,
  },
  "继续围绕「{0}」教我，保持 coach-only，不替我改代码。先判断这张卡的结果，再决定下一步。": {
    "en-US": (value) => `Keep coaching me on "${value}" and stay coach-only. Do not edit code for me. Judge the result of this card first, then choose the next step.`,
    "es-ES": (value) => `Sigue enseñándome sobre "${value}" y quédate en modo coach. No edites código por mí. Juzga primero el resultado de esta tarjeta y después elige el siguiente paso.`,
    "fr-FR": (value) => `Continue à me coacher sur "${value}" et reste en mode coach. N'édite pas le code pour moi. Juge d'abord le résultat de cette carte, puis choisis l'étape suivante.`,
    "de-DE": (value) => `Coache mich weiter zu "${value}" und bleib coach-only. Ändere keinen Code für mich. Bewerte zuerst das Ergebnis dieser Karte und wähle dann den nächsten Schritt.`,
    "ja-JP": (value) => `「${value}」についてコーチングを続け、coach-only を保ってください。コードの編集はしないでください。まずこのカードの結果を判断してから、次のステップを決めます。`,
    "ko-KR": (value) => `"${value}"에 대한 코칭을 계속하고 coach-only를 유지하세요. 코드를 대신 수정하지 마세요. 이 카드의 결과를 먼저 판단한 뒤 다음 단계를 정하세요.`,
    "pt-BR": (value) => `Continue me orientando sobre "${value}" e permaneça em modo coach. Não edite código por mim. Julgue primeiro o resultado deste cartão e depois escolha o próximo passo.`,
  },
  "已提交迁移说明，等待 Trainer 验证：{0}": {
    "en-US": (value) => `Transfer note submitted for Trainer verification: ${value}`,
    "es-ES": (value) => `Nota de transferencia enviada para verificación de Trainer: ${value}`,
    "fr-FR": (value) => `Note de transfert envoyée pour vérification par Trainer : ${value}`,
    "de-DE": (value) => `Transfernotiz zur Trainer-Verifizierung eingereicht: ${value}`,
    "ja-JP": (value) => `転移メモを送信し、Trainer の検証待ち：${value}`,
    "ko-KR": (value) => `전이 노트가 제출되어 Trainer 검증 대기 중: ${value}`,
    "pt-BR": (value) => `Nota de transferência enviada para verificação do Trainer: ${value}`,
  },
};

/** Progress-line copy with two interpolated numbers (current card / total). */
const trainingProgressLineCopy: Record<ComposerLanguage, (display: number, total: number) => string> = {
  "zh-CN": (display, total) => `第 ${display} / ${total} 张`,
  "en-US": (display, total) => `Card ${display} of ${total}`,
  "es-ES": (display, total) => `Tarjeta ${display} de ${total}`,
  "fr-FR": (display, total) => `Carte ${display} sur ${total}`,
  "de-DE": (display, total) => `Karte ${display} von ${total}`,
  "ja-JP": (display, total) => `${display} / ${total} 枚目`,
  "ko-KR": (display, total) => `카드 ${display} / ${total}`,
  "pt-BR": (display, total) => `Cartão ${display} de ${total}`,
};

function text(language: ComposerLanguage, zh: string, en: string): string {
  if (language === "zh-CN") {
    return zh;
  }
  return coachTrainingTextCopy[zh]?.[language] ?? en;
}

function textFilled(
  language: ComposerLanguage,
  zhTemplate: string,
  enTemplate: string,
  value: string,
): string {
  if (language === "zh-CN") {
    return zhTemplate.replace("{0}", value);
  }
  return coachTrainingTemplateTextCopy[zhTemplate]?.[language]?.(value) ?? enTemplate.replace("{0}", value);
}

type NextHopStatusKey =
  | "created" | "surfaced" | "accepted" | "continued_in_chat" | "verification_required"
  | "reflection_required" | "return_required" | "dismissed" | "deferred" | "blocked"
  | "expired" | "archived";

/** §十五: next-hop status labels in eight languages (no zh/en binary). */
const nextHopStatusLabelCopy: Record<ComposerLanguage, Record<NextHopStatusKey, string>> = {
  "zh-CN": {
    created: "已创建",
    surfaced: "已浮现",
    accepted: "已接受",
    continued_in_chat: "已回到对话",
    verification_required: "还需验证",
    reflection_required: "先复盘一下",
    return_required: "带回教练",
    dismissed: "已忽略",
    deferred: "已延后",
    blocked: "已阻塞",
    expired: "已过期",
    archived: "已归档",
  },
  "en-US": {
    created: "Created",
    surfaced: "Surfaced",
    accepted: "Accepted",
    continued_in_chat: "Back in coach",
    verification_required: "Needs a check",
    reflection_required: "Reflect first",
    return_required: "Return to coach",
    dismissed: "Dismissed",
    deferred: "Deferred",
    blocked: "Blocked",
    expired: "Expired",
    archived: "Archived",
  },
  "es-ES": {
    created: "Creado",
    surfaced: "Mostrado",
    accepted: "Aceptado",
    continued_in_chat: "De vuelta en el coach",
    verification_required: "Necesita una verificación",
    reflection_required: "Reflexiona primero",
    return_required: "Retorno al coach",
    dismissed: "Descartado",
    deferred: "Aplazado",
    blocked: "Bloqueado",
    expired: "Caducado",
    archived: "Archivado",
  },
  "fr-FR": {
    created: "Créé",
    surfaced: "Affiché",
    accepted: "Accepté",
    continued_in_chat: "De retour dans le coach",
    verification_required: "Nécessite une vérification",
    reflection_required: "Réfléchis d'abord",
    return_required: "Retour au coach",
    dismissed: "Ignoré",
    deferred: "Reporté",
    blocked: "Bloqué",
    expired: "Expiré",
    archived: "Archivé",
  },
  "de-DE": {
    created: "Erstellt",
    surfaced: "Eingeblendet",
    accepted: "Akzeptiert",
    continued_in_chat: "Zurück im Coach",
    verification_required: "Braucht eine Prüfung",
    reflection_required: "Zuerst reflektieren",
    return_required: "Rückkehr zum Coach",
    dismissed: "Verworfen",
    deferred: "Aufgeschoben",
    blocked: "Blockiert",
    expired: "Abgelaufen",
    archived: "Archiviert",
  },
  "ja-JP": {
    created: "作成済み",
    surfaced: "表示済み",
    accepted: "受け入れ済み",
    continued_in_chat: "コーチに戻りました",
    verification_required: "検証が必要です",
    reflection_required: "まず振り返りを",
    return_required: "コーチへ持ち帰り",
    dismissed: "却下済み",
    deferred: "延期済み",
    blocked: "ブロック中",
    expired: "期限切れ",
    archived: "アーカイブ済み",
  },
  "ko-KR": {
    created: "생성됨",
    surfaced: "표시됨",
    accepted: "수락됨",
    continued_in_chat: "코치로 복귀",
    verification_required: "검증이 필요합니다",
    reflection_required: "먼저 복기",
    return_required: "코치로 가져가기",
    dismissed: "무시됨",
    deferred: "연기됨",
    blocked: "차단됨",
    expired: "만료됨",
    archived: "보관됨",
  },
  "pt-BR": {
    created: "Criado",
    surfaced: "Exibido",
    accepted: "Aceito",
    continued_in_chat: "De volta ao coach",
    verification_required: "Precisa de uma verificação",
    reflection_required: "Reflita primeiro",
    return_required: "Retorno ao coach",
    dismissed: "Descartado",
    deferred: "Adiado",
    blocked: "Bloqueado",
    expired: "Expirado",
    archived: "Arquivado",
  },
};

function nextHopStatusLabel(
  language: ComposerLanguage,
  status?: "created" | "surfaced" | "accepted" | "continued_in_chat" | "verification_required" | "reflection_required" | "return_required" | "dismissed" | "deferred" | "blocked" | "expired" | "archived",
): string | undefined {
  if (!status) {
    return undefined;
  }
  return nextHopStatusLabelCopy[language][status];
}

/** §十五: next-hop continue labels in eight languages (no zh/en binary). */
const nextHopContinueLabelCopy: Record<ComposerLanguage, Record<"chat" | "plan" | "training", string>> = {
  "zh-CN": {
    chat: "回到对话",
    plan: "继续计划",
    training: "继续训练",
  },
  "en-US": {
    chat: "Return to coach",
    plan: "Continue in plan",
    training: "Continue training",
  },
  "es-ES": {
    chat: "Volver al coach",
    plan: "Continúa en el plan",
    training: "Continúa el entrenamiento",
  },
  "fr-FR": {
    chat: "Revenir au coach",
    plan: "Continue dans le plan",
    training: "Poursuis l'entraînement",
  },
  "de-DE": {
    chat: "Zurück zum Coach",
    plan: "Im Plan weitermachen",
    training: "Training fortsetzen",
  },
  "ja-JP": {
    chat: "コーチに戻る",
    plan: "プランで続行",
    training: "トレーニングを続行",
  },
  "ko-KR": {
    chat: "코치로 돌아가기",
    plan: "계획에서 계속",
    training: "트레이닝 계속",
  },
  "pt-BR": {
    chat: "Voltar ao coach",
    plan: "Continue no plano",
    training: "Continue o treinamento",
  },
};

function nextHopContinueLabel(
  language: ComposerLanguage,
  continueIn?: "chat" | "training" | "plan",
): string | undefined {
  if (!continueIn) {
    return undefined;
  }
  if (continueIn === "chat") {
    return nextHopContinueLabelCopy[language].chat;
  }
  return continueIn === "plan"
    ? nextHopContinueLabelCopy[language].plan
    : nextHopContinueLabelCopy[language].training;
}

/** §十五: next-hop scope labels in eight languages (no zh/en binary). */
const nextHopScopeLabelCopy: Record<
  ComposerLanguage,
  Record<"global" | "current_project" | "project_subplan" | "sandbox" | "unknown", string>
> = {
  "zh-CN": {
    global: "全局",
    current_project: "当前项目",
    project_subplan: "项目子计划",
    sandbox: "沙箱",
    unknown: "未标注",
  },
  "en-US": {
    global: "Global",
    current_project: "Current project",
    project_subplan: "Project subplan",
    sandbox: "Sandbox",
    unknown: "Unknown",
  },
  "es-ES": {
    global: "Global",
    current_project: "Proyecto actual",
    project_subplan: "Subplan del proyecto",
    sandbox: "Sandbox",
    unknown: "Sin etiquetar",
  },
  "fr-FR": {
    global: "Global",
    current_project: "Projet actuel",
    project_subplan: "Sous-plan du projet",
    sandbox: "Bac à sable",
    unknown: "Non renseigné",
  },
  "de-DE": {
    global: "Global",
    current_project: "Aktuelles Projekt",
    project_subplan: "Projekt-Teilplan",
    sandbox: "Sandbox",
    unknown: "Nicht angegeben",
  },
  "ja-JP": {
    global: "グローバル",
    current_project: "現在のプロジェクト",
    project_subplan: "プロジェクトのサブプラン",
    sandbox: "サンドボックス",
    unknown: "未設定",
  },
  "ko-KR": {
    global: "전역",
    current_project: "현재 프로젝트",
    project_subplan: "프로젝트 하위 계획",
    sandbox: "샌드박스",
    unknown: "미지정",
  },
  "pt-BR": {
    global: "Global",
    current_project: "Projeto atual",
    project_subplan: "Subplano do projeto",
    sandbox: "Sandbox",
    unknown: "Não especificado",
  },
};

function nextHopScopeLabel(
  language: ComposerLanguage,
  scope?: "global" | "current_project" | "project_subplan" | "sandbox" | "unknown",
): string | undefined {
  if (!scope) {
    return undefined;
  }
  return nextHopScopeLabelCopy[language][scope];
}

function memoryLayerStatusTone(status: MemoryLayerView["status"]): "connected" | "pending" | "offline" {
  if (status === "active") {
    return "connected";
  }
  if (status === "quiet") {
    return "pending";
  }
  return "offline";
}

function memoryLayerStatusLabel(language: ComposerLanguage, status: MemoryLayerView["status"]): string {
  if (status === "active") {
    return "Active";
  }
  if (status === "quiet") {
    return "Quiet";
  }
  return "Empty";
}

function memoryLayerInjectionLabel(language: ComposerLanguage, canInjectTrainingCard: boolean): string {
  return canInjectTrainingCard
    ? "Can inject training card"
    : "Reference only";
}

function toTrainingLedgerContinueIn(value?: string): TrainingLedgerContinueIn | undefined {
  return value === "chat" ||
    value === "training" ||
    value === "plan" ||
    value === "resources" ||
    value === "none"
    ? value
    : undefined;
}

function toTrainingLedgerProjectScope(value?: string): TrainingLedgerProjectScope | undefined {
  return value === "global" ||
    value === "current_project" ||
    value === "project_subplan" ||
    value === "sandbox" ||
    value === "unknown"
    ? value
    : undefined;
}

function stageLabel(language: ComposerLanguage, stage?: DependencyMastery["masteryStage"]): string {
  const labels = {
    understood: "Understood",
    recalled: "Recalled",
    practiced: "Practiced",
    applied: "Applied",
    transferable: "Transferable",
  } as const;
  return stage ? labels[stage] : "Not established";
}

function nextActionForStage(stage?: DependencyMastery["masteryStage"]): "mark_practiced" | "mark_applied" | "mark_transferable" {
  if (stage === "practiced") {
    return "mark_applied";
  }
  if (stage === "applied" || stage === "transferable") {
    return "mark_transferable";
  }
  return "mark_practiced";
}

function summarizeLatestReviewQueueAction(
  language: ComposerLanguage,
  reviewQueueActions: ReviewQueueAction[] | undefined,
  trainingEventLedger: TrainingEventLedgerEntry[] | undefined,
): string | undefined {
  const latestLedgerEvent = [...(trainingEventLedger ?? [])]
    .filter((entry) => entry.eventType === "review_queue_action_recorded")
    .sort((left, right) => Date.parse(right.createdAt ?? right.timestamp) - Date.parse(left.createdAt ?? left.timestamp))[0];
  const latestAction = [...(reviewQueueActions ?? [])]
    .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt))[0];
  const concept =
    normalizeText(latestAction?.concept) ||
    normalizeText(latestAction?.focusArea) ||
    normalizeText(latestLedgerEvent?.attemptTargetTitle) ||
    normalizeText(latestLedgerEvent?.attemptTargetId);
  const action =
    normalizeText(latestAction?.action) ||
    normalizeText(latestLedgerEvent?.learnerAnswerPreview) ||
    normalizeText(latestLedgerEvent?.statusKind);
  const note =
    normalizeText(latestAction?.note) ||
    normalizeText(latestLedgerEvent?.feedback) ||
    normalizeText(latestAction?.taskHint);
  if (!concept || !action) {
    return undefined;
  }
  const actionLabel =
    action === "reset"
      ? "reset into a smaller review loop"
      : action === "accept"
        ? "pulled back into training"
        : action === "snooze"
          ? "deferred for later review"
          : action === "done"
            ? "marked complete for this round"
            : action === "skip"
              ? "skipped for now"
              : action;
  return note
    ? `Latest review move: ${concept}, ${actionLabel}. ${note}`
    : `Latest review move: ${concept}, ${actionLabel}.`;
}

/** §十五: dependency verification action labels in eight languages. */
const actionLabelCopy: Record<
  ComposerLanguage,
  Record<"mark_practiced" | "mark_applied" | "mark_transferable", string>
> = {
  "zh-CN": {
    mark_practiced: "验证这次练习",
    mark_applied: "验证这次应用",
    mark_transferable: "请求验证迁移证据",
  },
  "en-US": {
    mark_practiced: "Verify this practice",
    mark_applied: "Verify this application",
    mark_transferable: "Request transfer verification",
  },
  "es-ES": {
    mark_practiced: "Verifica esta práctica",
    mark_applied: "Verifica esta aplicación",
    mark_transferable: "Solicita la verificación de la transferencia",
  },
  "fr-FR": {
    mark_practiced: "Vérifie cette pratique",
    mark_applied: "Vérifie cette application",
    mark_transferable: "Demande la vérification du transfert",
  },
  "de-DE": {
    mark_practiced: "Verifiziere diese Übung",
    mark_applied: "Verifiziere diese Anwendung",
    mark_transferable: "Fordere die Transfer-Verifizierung an",
  },
  "ja-JP": {
    mark_practiced: "この練習を検証",
    mark_applied: "この応用を検証",
    mark_transferable: "転移の検証をリクエスト",
  },
  "ko-KR": {
    mark_practiced: "이 연습 검증",
    mark_applied: "이 적용 검증",
    mark_transferable: "전이 검증 요청",
  },
  "pt-BR": {
    mark_practiced: "Verifique esta prática",
    mark_applied: "Verifique esta aplicação",
    mark_transferable: "Solicite a verificação de transferência",
  },
};

function actionLabel(language: ComposerLanguage, action: "mark_practiced" | "mark_applied" | "mark_transferable"): string {
  return actionLabelCopy[language][action];
}

function formatReviewDate(value?: string): string | undefined {
  if (!value) {
    return undefined;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatReviewPercent(value?: number): string | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return undefined;
  }
  return `${Math.round(value * 100)}%`;
}

function firstDependency(
  maps: DependencySkillMap[] | undefined,
  mastery: DependencyMastery[],
): {
  dependencyKey: string;
  dependencyName: string;
  masteryStage?: DependencyMastery["masteryStage"];
  masteryScore: number;
  confidence: number;
  projectFirstCut?: string;
  suggestedScenarioLab?: string;
  prioritySummary?: string;
  relatedApi?: string;
  scenario?: string;
} | undefined {
  const map = maps?.[0];
  const record = map
    ? mastery.find((item) => item.dependencyKey === map.dependencyKey)
    : mastery[0];
  if (map) {
    const transferItem = (map.topReviewItems ?? []).find((item) => item.layer === "transfer");
    return {
      dependencyKey: map.dependencyKey,
      dependencyName: map.dependencyName ?? "",
      masteryStage: record?.masteryStage ?? map.masteryStage ?? "understood",
      masteryScore: record?.masteryScore ?? map.masteryScore ?? 0,
      confidence: record?.confidence ?? map.confidence ?? 0,
      projectFirstCut: map.projectFirstCut,
      suggestedScenarioLab: map.suggestedScenarioLab,
      prioritySummary: map.prioritySummary,
      relatedApi: transferItem?.relatedApi,
      scenario: transferItem?.scenario,
    };
  }
  if (!record) {
    return undefined;
  }
  return {
    dependencyKey: record.dependencyKey,
    dependencyName: record.dependencyName,
    masteryStage: record.masteryStage,
    masteryScore: record.masteryScore,
    confidence: record.confidence ?? 0,
    projectFirstCut: (record.currentUseCases ?? [])[0],
    prioritySummary: (record.weakestPoints ?? [])[0],
    relatedApi: (record.currentApis ?? [])[0],
    scenario: (record.practiceScenarios ?? [])[0],
  };
}

function buildCoachReturnBridge(input: {
  language: ComposerLanguage;
  task?: TaskSpec;
  selectedCardId?: string;
  selectedCardType?: "practice" | "flash";
  selectedCardTitle?: string;
  focusArea?: string;
  latestVerifiedResult?: string;
  latestReturnWith?: string;
  latestSuccessSignal?: string;
  latestLearningBlocker?: string;
  latestLearningPartialProgress?: string;
}): PracticeCoachBridge {
  const focus = normalizeText(input.focusArea) || input.task?.title || "";
  const cardId = normalizeText(input.selectedCardId) || input.task?.id || "";
  const cardType = input.selectedCardType || "practice";
  const cardTitle = normalizeText(input.selectedCardTitle) || input.task?.title || "";
  const summaryLines = [
    input.latestVerifiedResult
      ? textFilled(input.language, "验证结果：{0}", "Verification result: {0}", input.latestVerifiedResult)
      : undefined,
    input.latestLearningBlocker
      ? textFilled(input.language, "当前卡点：{0}", "Current blocker: {0}", input.latestLearningBlocker)
      : undefined,
    input.latestReturnWith
      ? textFilled(input.language, "带回：{0}", "Bring back: {0}", input.latestReturnWith)
      : undefined,
    input.latestSuccessSignal
      ? textFilled(input.language, "通过信号：{0}", "Pass signal: {0}", input.latestSuccessSignal)
      : undefined,
  ].filter((item): item is string => Boolean(item));

  const trainingReturn: TrainingReturnPayload | undefined = input.latestVerifiedResult
    ? {
        cardId,
        cardType,
        cardTitle,
        returnMode: "result",
        summary: input.latestVerifiedResult,
        verifiedResult: input.latestVerifiedResult,
        source: "training_bridge",
      }
    : input.latestLearningBlocker || input.latestLearningPartialProgress
      ? {
          cardId,
          cardType,
          cardTitle,
          returnMode: "blocker",
          summary: input.latestLearningPartialProgress || input.latestLearningBlocker || "",
          blocker: input.latestLearningBlocker || undefined,
          source: "training_bridge",
        }
      : undefined;

  return {
    title: textFilled(input.language, "把「{0}」带回教练判断", "Bring \"{0}\" back to coach", focus),
    prompt: textFilled(
      input.language,
      "继续围绕「{0}」教我，保持 coach-only，不替我改代码。先判断这张卡的结果，再决定下一步。",
      "Keep coaching me on \"{0}\" and stay coach-only. Do not edit code for me. Judge the result of this card first, then choose the next step.",
      focus,
    ),
    detail: text(
      input.language,
      "让教练判断它是通过、部分通过、降级、计划证据，还是需要回到闪卡巩固。",
      "Let the coach judge whether this was a pass, partial pass, downgrade, plan evidence, or flash reinforcement.",
    ),
    ctaLabel: text(input.language, "回到教练", "Return to coach"),
    summaryLines,
    trainingReturn,
  };
}

function compactWorkspaceRouteLabel(
  language: ComposerLanguage,
  workspaceId: string | undefined,
): string {
  const normalized = workspaceId?.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return text(language, "当前工作区", "Current workspace");
  }
  return normalized.length <= 36 ? normalized : `${normalized.slice(0, 33).trimEnd()}...`;
}

function isTrainingCardStatus(value: unknown): value is TrainingCardStatus {
  return (
    value === "candidate" ||
    value === "active" ||
    value === "needs_primer" ||
    value === "answered" ||
    value === "implemented" ||
    value === "completed" ||
    value === "reviewed" ||
    value === "fed_back" ||
    value === "archived" ||
    value === "skipped" ||
    value === "blocked"
  );
}

function pickVisibleFlashAttempt(deck?: FlashcardDeck): FlashcardAttempt | undefined {
  if (!deck || !Array.isArray(deck.cards) || deck.cards.length === 0) {
    return undefined;
  }
  const unanswered = deck.cards.find((candidate) => candidate.status === "unanswered" || !candidate.status);
  return unanswered ?? deck.cards[0];
}

export function CoachTrainingView({
  language,
  task,
  isLoading = false,
  workspaceUnderstanding,
  evidencePack,
  teachingDecision,
  recoveredRuntime,
  runtimeCurrentStep,
  implementationGuide,
  dependencyMastery,
  learningOutcomes,
  memoryLayers = [],
  workspaceAuthority,
  reviewSummary,
  practiceBusy = false,
  flashBusy = false,
  transferWorkspaceOptions = [],
  flashDeck,
  recentFlashAttempts,
  flashPracticeBridge,
  workspaceTrainingState,
  latestLearningBlocker,
  initialTrainingSubmode,
  onTrainingSubmodeChange,
  onRefreshTask,
  onQuickStartTraining,
  onOpenCoachFromPractice,
  onRefreshDeck,
  onSubmitFlashAnswer,
  onOpenCoachFromFlash,
  onOpenCoachBridgeFromFlash,
  onOpenPracticeFromFlash,
  onCreateFlashcard,
  onOpenResources,
  onDependencySkillMapAction,
  onCardStatusTransition,
  onVerifyCurrentFile,
  debugRestoreTarget,
  debugTheoryDrillId,
  debugScenarioLabId,
  debugReviewArtifactId,
  debugRestoredNextHop,
  onDebugVisibleFacts,
}: CoachTrainingViewProps) {
  const [mode, setMode] = useState<TrainingSurfaceMode>(normalizeMode(initialTrainingSubmode));
  const dependency = firstDependency(workspaceTrainingState?.dependencySkillMaps, dependencyMastery);
  const [transferDraft, setTransferDraft] = useState<TransferEvidenceDraft | undefined>(undefined);
  const [pendingCardStatusTransition, setPendingCardStatusTransition] = useState<{
    cardId: string;
    cardType: "practice" | "flash";
    sourceStatus: TrainingCardStatus;
    newStatus: TrainingCardStatus;
    requestedAt: number;
  } | null>(null);
  const cardStatusBusy = pendingCardStatusTransition !== null;
  const { ledgerSummary, routingSummary } = useMemo(
    () => {
      const nextRoutingSummary = workspaceTrainingState?.activeTrainingCardRouting as
        | {
            selectedCardId?: string;
            selectedCard?: { title?: string; type?: "practice" | "flash" };
            whyThisCard?: string;
            blockedCandidates?: Array<{
              cardId: string;
              type: "practice" | "flash";
              title: string;
              reasons: string[];
            }>;
            fallbackAction?: string;
            candidateCount?: number;
            eligibleCount?: number;
          }
        | undefined;
      const nextLedgerSummary = workspaceTrainingState?.trainingEventLedger?.map(
        (entry): TrainingEventLedgerEntrySummary => ({
        eventType: entry.eventType,
        candidateId: entry.candidateId,
        candidateStatus: entry.candidateStatus,
        candidateStatusReason: entry.candidateStatusReason,
        statusKind: entry.statusKind,
        statusSummary: entry.statusSummary,
        statusDetail: entry.statusDetail,
        candidateContinueIn:
          toTrainingLedgerContinueIn(entry.candidateContinueIn),
        candidateTargetKind: entry.candidateTargetKind,
        candidateTargetId: entry.candidateTargetId,
        candidateProjectScope: toTrainingLedgerProjectScope(entry.candidateProjectScope),
        candidateBlockedBy: entry.candidateBlockedBy,
        candidateAcceptedInto: entry.candidateAcceptedInto,
        candidateWhyNow: entry.candidateWhyNow,
        candidateTitle: entry.candidateTitle,
        candidateType:
          entry.candidateType === "project_context_candidate" ||
          entry.candidateType === "resource_import_candidate" ||
          entry.candidateType === "evidence_candidate" ||
          entry.candidateType === "flash_candidate" ||
          entry.candidateType === "practice_candidate" ||
          entry.candidateType === "coach_visible_status" ||
          entry.candidateType === "micro_drill_prompt" ||
          entry.candidateType === "card_invocation"
            ? (entry.candidateType as "project_context_candidate" | "resource_import_candidate" | "evidence_candidate" | "flash_candidate" | "practice_candidate" | "coach_visible_status" | "micro_drill_prompt" | "card_invocation")
            : undefined,
        selectedCardId: entry.selectedCardId,
        selectedCardType: (entry.selectedCardType === "practice" || entry.selectedCardType === "flash"
          ? entry.selectedCardType
          : undefined) as "practice" | "flash" | undefined,
        selectedCardTitle: entry.selectedCardTitle,
        cardCandidateId: entry.cardCandidateId,
        cardCandidateType: entry.cardCandidateType === "practice" ? "practice" : entry.cardCandidateType === "flash" ? "flash" : undefined,
        cardCandidateTitle: entry.cardCandidateTitle,
        whyThisCard: entry.whyThisCard,
        nextAfterCompletion: entry.nextAfterCompletion,
        fallbackAction: entry.fallbackAction,
        returnMode: entry.returnMode === "result" ? "result" : entry.returnMode === "blocker" ? "blocker" : undefined,
        returnSummary: entry.returnSummary,
        judgedAt: entry.judgedAt,
        sourceChain: entry.sourceChain,
        blockedCandidates: entry.blockedCandidates,
        createdAt: entry.createdAt,
      }));
      return { ledgerSummary: nextLedgerSummary, routingSummary: nextRoutingSummary };
    },
    [workspaceTrainingState?.activeTrainingCardRouting, workspaceTrainingState?.trainingEventLedger],
  );
  const resolvedHandoff = useMemo(
    () =>
      resolveTrainingHandoff({
        latestTrainingHandoff: workspaceTrainingState?.latestTrainingHandoff,
        latestConversationHandoff: workspaceTrainingState?.latestConversationHandoff,
        latestTrainingSubmode: workspaceTrainingState?.latestTrainingSubmode,
        selectedCardId: workspaceTrainingState?.selectedCardId,
        selectedCardType: workspaceTrainingState?.selectedCardType,
        selectedCardTitle: workspaceTrainingState?.selectedCardTitle,
        trainingCardCandidates: Array.isArray(workspaceTrainingState?.trainingCardCandidates)
          ? (workspaceTrainingState?.trainingCardCandidates as Array<{
              id: string;
              type: "practice" | "flash";
              title: string;
              whyNow?: string;
            }>)
          : undefined,
        activeTrainingCardRouting: routingSummary,
        trainingEventLedger: ledgerSummary,
      }),
    [
      ledgerSummary,
      routingSummary,
      workspaceTrainingState?.latestConversationHandoff,
      workspaceTrainingState?.latestTrainingHandoff,
      workspaceTrainingState?.latestTrainingSubmode,
      workspaceTrainingState?.selectedCardId,
      workspaceTrainingState?.selectedCardTitle,
      workspaceTrainingState?.selectedCardType,
      workspaceTrainingState?.trainingCardCandidates,
    ],
  );
  const resolvedNextHop = useMemo(
    () =>
      resolveTrainingNextHop({
        language,
        latestTrainingNextHop:
          debugRestoreTarget === "next_hop" && debugRestoredNextHop
            ? debugRestoredNextHop
            : workspaceTrainingState?.latestTrainingNextHop,
        trainingEventLedger: ledgerSummary,
      }),
    [debugRestoreTarget, debugRestoredNextHop, language, workspaceTrainingState?.latestTrainingNextHop, workspaceTrainingState?.trainingEventLedger],
  );
  const restoredNextHopSource =
    debugRestoreTarget === "next_hop"
      ? debugRestoredNextHop ?? workspaceTrainingState?.latestTrainingNextHop
      : undefined;
  const nextHopDisplay = useMemo(() => {
    if (!restoredNextHopSource) {
      return resolvedNextHop;
    }

    const displayCopy = summarizeTrainingNextHopCopy(language, {
      title: restoredNextHopSource.title || restoredNextHopSource.cardTitle || resolvedNextHop.title,
      summary:
        restoredNextHopSource.summary ||
        restoredNextHopSource.returnSummary ||
        restoredNextHopSource.handoffSummary ||
        resolvedNextHop.summary,
      nextAfterCompletion:
        restoredNextHopSource.nextAfterCompletion || resolvedNextHop.nextAfterCompletion,
      whyNow: restoredNextHopSource.whyNow || resolvedNextHop.whyNow,
      statusReason: restoredNextHopSource.statusReason || resolvedNextHop.statusReason,
      blockedBy: restoredNextHopSource.blockedBy || resolvedNextHop.blockedBy,
      handoffSummary: restoredNextHopSource.handoffSummary || resolvedNextHop.handoffSummary,
      fallbackAction: restoredNextHopSource.fallbackAction || resolvedNextHop.fallbackAction,
    });
    const hasStructuredTarget = Boolean(
      restoredNextHopSource.candidateType ||
        restoredNextHopSource.targetKind ||
        restoredNextHopSource.targetId ||
        restoredNextHopSource.continueIn ||
        restoredNextHopSource.status ||
        restoredNextHopSource.reviewArtifactId ||
        restoredNextHopSource.planEvidenceId,
    );
    return {
      ...resolvedNextHop,
      shouldRender: true,
      hasRenderableCopy: Boolean(
        displayCopy.title || displayCopy.summary || displayCopy.detail || restoredNextHopSource.cardTitle,
      ),
      hasStructuredTarget: resolvedNextHop.hasStructuredTarget || hasStructuredTarget,
      candidateId: restoredNextHopSource.candidateId || resolvedNextHop.candidateId,
      candidateType: restoredNextHopSource.candidateType || resolvedNextHop.candidateType,
      title: displayCopy.title || resolvedNextHop.title,
      summary: displayCopy.summary || resolvedNextHop.summary,
      whyNow: displayCopy.detail || resolvedNextHop.whyNow,
      projectScope: restoredNextHopSource.projectScope || resolvedNextHop.projectScope,
      continueIn: restoredNextHopSource.continueIn || resolvedNextHop.continueIn,
      targetKind: restoredNextHopSource.targetKind || resolvedNextHop.targetKind,
      targetId: restoredNextHopSource.targetId || resolvedNextHop.targetId,
      acceptedInto: restoredNextHopSource.acceptedInto || resolvedNextHop.acceptedInto,
      status: restoredNextHopSource.status || resolvedNextHop.status,
      statusReason: restoredNextHopSource.statusReason || resolvedNextHop.statusReason,
      blockedBy: restoredNextHopSource.blockedBy || resolvedNextHop.blockedBy,
      handoffStatus: restoredNextHopSource.handoffStatus || resolvedNextHop.handoffStatus,
      handoffSummary: restoredNextHopSource.handoffSummary || resolvedNextHop.handoffSummary,
      coachOnly: restoredNextHopSource.coachOnly ?? resolvedNextHop.coachOnly,
      cardType: restoredNextHopSource.cardType || resolvedNextHop.cardType,
      cardTitle: restoredNextHopSource.cardTitle || resolvedNextHop.cardTitle || displayCopy.title,
      returnMode: restoredNextHopSource.returnMode || resolvedNextHop.returnMode,
      returnSummary: restoredNextHopSource.returnSummary || resolvedNextHop.returnSummary,
      judgedAt: restoredNextHopSource.judgedAt || resolvedNextHop.judgedAt,
      reviewArtifactId: restoredNextHopSource.reviewArtifactId || resolvedNextHop.reviewArtifactId,
      reviewArtifactStatus:
        restoredNextHopSource.reviewArtifactStatus || resolvedNextHop.reviewArtifactStatus,
      reviewRecoveryMode: restoredNextHopSource.reviewRecoveryMode || resolvedNextHop.reviewRecoveryMode,
      planEvidenceId: restoredNextHopSource.planEvidenceId || resolvedNextHop.planEvidenceId,
      nextAfterCompletion:
        restoredNextHopSource.nextAfterCompletion || resolvedNextHop.nextAfterCompletion,
      fallbackAction: restoredNextHopSource.fallbackAction || resolvedNextHop.fallbackAction,
      sourceChain:
        restoredNextHopSource.sourceChain?.map((item) => item.trim()).filter(Boolean) ??
        resolvedNextHop.sourceChain,
      canContinue:
        resolvedNextHop.canContinue ||
        Boolean(
          restoredNextHopSource.continueIn &&
            restoredNextHopSource.status &&
            ["created", "surfaced", "deferred", "blocked"].includes(restoredNextHopSource.status),
        ),
    };
  }, [language, resolvedNextHop, restoredNextHopSource]);
  const isNextHopRestoreForeground = Boolean(restoredNextHopSource);

  useEffect(() => {
    setMode(normalizeMode(initialTrainingSubmode));
  }, [initialTrainingSubmode]);

  const liveTrainingFocusChrome = preferRecoveredTrainingFocusChrome({
    recovered: recoveredRuntime,
    runtimeCurrentStep,
    teachingDecisionFocusArea: teachingDecision?.focusArea,
    latestLearningFocusArea: workspaceTrainingState?.latestLearningFocusArea,
  });
  const focus = normalizeText(
    liveTrainingFocusChrome.latestLearningFocusArea ||
      liveTrainingFocusChrome.teachingDecisionFocusArea,
  );

  const latestTransfer = dependency
    ? dependencyMastery.find((item) => item.dependencyKey === dependency.dependencyKey)
    : undefined;

  const defaultTransferDraft = useMemo(
    () =>
      dependency
        ? buildTransferEvidenceDraft({
            currentWorkspaceId: workspaceTrainingState?.workspaceId,
            coachFocus: focus,
            returnTarget:
              workspaceTrainingState?.latestLearningVerifiedResult ||
              workspaceTrainingState?.latestLearningFollowup,
            dependency,
            workspaceOptions: transferWorkspaceOptions,
            latestTransfer: {
              sourceWorkspaceId:
                workspaceTrainingState?.latestTransferSourceWorkspaceId ||
                latestTransfer?.latestTransferSourceWorkspaceId,
              targetWorkspaceId:
                workspaceTrainingState?.latestTransferTargetWorkspaceId ||
                latestTransfer?.latestTransferTargetWorkspaceId,
              verifiedResult:
                workspaceTrainingState?.latestTransferVerifiedResult ||
                latestTransfer?.latestTransferVerifiedResult,
            },
            latestEvidence: latestTransfer?.transferEvidence?.[0],
            weakItem: {
              label: dependency.prioritySummary,
              relatedApi: dependency.relatedApi,
              scenario: dependency.scenario,
              nextAction: dependency.projectFirstCut,
            },
          })
        : undefined,
    [
      dependency,
      focus,
      latestTransfer,
      transferWorkspaceOptions,
      workspaceTrainingState?.latestLearningFollowup,
      workspaceTrainingState?.latestLearningVerifiedResult,
      workspaceTrainingState?.latestTransferSourceWorkspaceId,
      workspaceTrainingState?.latestTransferTargetWorkspaceId,
      workspaceTrainingState?.latestTransferVerifiedResult,
      workspaceTrainingState?.workspaceId,
    ],
  );

  useEffect(() => {
    if (!defaultTransferDraft) {
      setTransferDraft((current) => (current ? undefined : current));
      return;
    }
    setTransferDraft((current) => {
      if (!current || current.dependencyKey !== defaultTransferDraft.dependencyKey) {
        return defaultTransferDraft;
      }
      const currentTarget = normalizeText(current.targetWorkspaceId);
      const defaultTarget = normalizeText(defaultTransferDraft.targetWorkspaceId);
      const mergedDraft: TransferEvidenceDraft = {
        ...current,
        sourceWorkspaceId: normalizeText(current.sourceWorkspaceId) || defaultTransferDraft.sourceWorkspaceId,
        targetWorkspaceId:
          !currentTarget || currentTarget === normalizeText(current.sourceWorkspaceId)
            ? defaultTarget || current.targetWorkspaceId
            : current.targetWorkspaceId,
        sourceContext: normalizeText(current.sourceContext) || defaultTransferDraft.sourceContext,
        targetContext: normalizeText(current.targetContext) || defaultTransferDraft.targetContext,
        verifiedResult: normalizeText(current.verifiedResult) || defaultTransferDraft.verifiedResult,
        evidenceSummary: normalizeText(current.evidenceSummary) || defaultTransferDraft.evidenceSummary,
        focusItemKey: normalizeText(current.focusItemKey) || defaultTransferDraft.focusItemKey,
        relatedApi: normalizeText(current.relatedApi) || defaultTransferDraft.relatedApi,
        scenario: normalizeText(current.scenario) || defaultTransferDraft.scenario,
      };
      return areTransferDraftsEqual(current, mergedDraft) ? current : mergedDraft;
    });
  }, [defaultTransferDraft]);

  const transferReady = Boolean(
    normalizeText(transferDraft?.sourceWorkspaceId) &&
      normalizeText(transferDraft?.targetWorkspaceId) &&
      normalizeText(transferDraft?.verifiedResult) &&
      normalizeText(transferDraft?.sourceWorkspaceId) !== normalizeText(transferDraft?.targetWorkspaceId),
  );
  const stageAction = nextActionForStage(dependency?.masteryStage);
  const canSubmitStage = Boolean(onDependencySkillMapAction && dependency);
  const canSubmitTransfer = Boolean(canSubmitStage && transferDraft && transferReady);

  const trainingPausedByResourceRisk = resolvedHandoff.pausedByResourceRisk;
  const handoffContractVisible = Boolean(
    resolvedHandoff.learnerDeliverables.length ||
      resolvedHandoff.verificationSteps.length ||
      resolvedHandoff.successSignal ||
      resolvedHandoff.returnWith ||
      resolvedHandoff.nextAfterCompletion,
  );
  const routeWorkspaceLabel = compactWorkspaceRouteLabel(language, workspaceTrainingState?.workspaceId);
  const showTrainingRouteStrip = Boolean(
    !isNextHopRestoreForeground &&
      resolvedHandoff.shouldRender &&
      (trainingPausedByResourceRisk ||
        resolvedHandoff.selectedCardId ||
        resolvedHandoff.selectedCardTitle ||
        workspaceTrainingState?.selectedCardId ||
        workspaceTrainingState?.selectedCardTitle),
  );
  const primaryCardTitle =
    (isNextHopRestoreForeground
      ? nextHopDisplay.cardTitle || nextHopDisplay.title || nextHopDisplay.summary
      : resolvedHandoff.selectedCardTitle) ||
    workspaceTrainingState?.selectedCardTitle ||
    text(language, "等待训练路由确认当前卡片", "Waiting for the training router to confirm the card");
  const primaryCardReason = trainingPausedByResourceRisk
    ? text(
        language,
        "这张训练卡被资料风险暂停。继续前先刷新来源资料。",
        "This training card is paused by resource risk. Refresh the source material before continuing.",
      )
    : isNextHopRestoreForeground
      ? nextHopDisplay.whyNow ||
        nextHopDisplay.handoffSummary ||
        nextHopDisplay.summary ||
        text(
          language,
          "恢复的下一步已经成为前景，旧的理论、场景和复习对象不再抢占当前卡片。",
          "The restored next hop is now the foreground, so legacy theory, scenario, and review objects no longer take over the lane.",
        )
      : resolvedHandoff.whyThisCard ||
        resolvedHandoff.handoffSummary ||
        text(
          language,
          "这张卡来自对话交接，训练页现在只聚焦这一张当前卡。",
          "This card came from conversation, and training now stays focused on this single current card.",
        );
  const primaryCardTypeLabel =
    (isNextHopRestoreForeground ? nextHopDisplay.cardType : resolvedHandoff.selectedCardType) === "flash"
      ? text(language, "闪卡", "Flash card")
      : text(language, "练习卡", "Practice card");
  const resourceRiskReason =
    resolvedHandoff.resourceRiskReason ||
    resolvedHandoff.blockedReason ||
    text(
      language,
      "关联资料已经过期或可信度不足。继续训练卡前，先在资料页刷新。",
      "A linked resource is stale or not trusted enough. Refresh it in Resources before continuing this training card.",
    );
  const practiceCoachBridge = buildCoachReturnBridge({
    language,
    task,
    selectedCardId:
      (isNextHopRestoreForeground ? nextHopDisplay.targetId || nextHopDisplay.candidateId : resolvedHandoff.selectedCardId) ||
      workspaceTrainingState?.selectedCardId,
    selectedCardType:
      (isNextHopRestoreForeground ? nextHopDisplay.cardType : resolvedHandoff.selectedCardType) ||
      workspaceTrainingState?.selectedCardType,
    selectedCardTitle:
      (isNextHopRestoreForeground ? primaryCardTitle : resolvedHandoff.selectedCardTitle) ||
      workspaceTrainingState?.selectedCardTitle,
    focusArea: focus,
    latestVerifiedResult: workspaceTrainingState?.latestLearningVerifiedResult,
    latestReturnWith: resolvedHandoff.returnWith,
    latestSuccessSignal: resolvedHandoff.successSignal,
    latestLearningBlocker: workspaceTrainingState?.latestLearningBlocker,
    latestLearningPartialProgress: workspaceTrainingState?.latestLearningPartialProgress,
  });
  const nextHopCopy = summarizeTrainingNextHopCopy(language, {
    title:
      nextHopDisplay.title ||
      nextHopDisplay.summary ||
      nextHopDisplay.nextAfterCompletion,
    summary:
      nextHopDisplay.summary ||
      nextHopDisplay.returnSummary ||
      nextHopDisplay.handoffSummary ||
      nextHopDisplay.nextAfterCompletion,
    nextAfterCompletion:
      nextHopDisplay.nextAfterCompletion,
    whyNow: nextHopDisplay.whyNow,
    statusReason: nextHopDisplay.statusReason,
    blockedBy: nextHopDisplay.blockedBy,
    handoffSummary: nextHopDisplay.handoffSummary,
    fallbackAction: nextHopDisplay.fallbackAction,
  });
  const completionNextHopMeta = [
    nextHopStatusLabel(language, nextHopDisplay.status),
    nextHopContinueLabel(language, nextHopDisplay.continueIn),
    nextHopScopeLabel(language, nextHopDisplay.projectScope),
  ].filter((item): item is string => Boolean(item));
  const nextHopHasStructuredAuthority = Boolean(
    nextHopDisplay.hasStructuredTarget ||
      nextHopDisplay.candidateType ||
      nextHopDisplay.targetKind ||
      nextHopDisplay.targetId ||
      nextHopDisplay.continueIn ||
      nextHopDisplay.status ||
      nextHopDisplay.reviewArtifactId ||
      nextHopDisplay.planEvidenceId,
  );
  const nextHopShouldRender = Boolean(nextHopDisplay.shouldRender || nextHopHasStructuredAuthority);
  const completionNextHopDetail = normalizeText(
    nextHopShouldRender
      ? nextHopCopy.detail ||
          nextHopDisplay.handoffSummary ||
          nextHopDisplay.whyNow ||
          nextHopDisplay.statusReason ||
          nextHopDisplay.summary
      : undefined,
  );
  const completionNextHop = normalizeText(
    nextHopShouldRender
      ? nextHopCopy.title ||
          nextHopCopy.summary ||
          nextHopDisplay.title ||
      nextHopDisplay.summary ||
      nextHopDisplay.cardTitle
      : undefined,
  );
  const nextHopPrimaryTitle = normalizeText(
    completionNextHop ||
      nextHopDisplay.cardTitle ||
      nextHopDisplay.title ||
      nextHopDisplay.summary ||
      (nextHopShouldRender
        ? text(language, "下一步已经成形", "Next hop materialized")
        : undefined),
  );
  const coachJudgmentPending = false;
  const coachJudgmentSummary = normalizeText(
    summarizeWaitingCoachJudgment(language, {
      returnSummary: workspaceTrainingState?.latestTrainingHandoff?.returnSummary,
      handoffSummary: workspaceTrainingState?.latestTrainingHandoff?.handoffSummary,
    }).summary,
  );
  const latestReviewQueueActionSummary = useMemo(
    () =>
      summarizeLatestReviewQueueAction(
        language,
        workspaceTrainingState?.reviewQueueActions,
        workspaceTrainingState?.trainingEventLedger,
      ),
    [language, workspaceTrainingState?.reviewQueueActions, workspaceTrainingState?.trainingEventLedger],
  );
  const latestReviewQueueLedgerEvent = useMemo(
    () =>
      [...(workspaceTrainingState?.trainingEventLedger ?? [])]
        .filter((entry) => entry.eventType === "review_queue_action_recorded")
        .sort((left, right) => Date.parse(right.createdAt ?? right.timestamp) - Date.parse(left.createdAt ?? left.timestamp))[0],
    [workspaceTrainingState?.trainingEventLedger],
  );
  const singleCardImmersive = true;
  const routeStripCollapsedByDefault = true;
  const cardOnlyMode = true;
  const secondaryPanelsCollapsedByDefault = true;
  const [secondaryPanelsOpen, setSecondaryPanelsOpen] = useState(false);
  // chainExpanded stays collapsed by default; route + mastery panels live behind the
  // mastery toggle and the route details summary, so we no longer expose a setter.
  const chainExpanded = false;
  const [masteryPanelVisible, setMasteryPanelVisible] = useState(false);
  const visibleTheoryDrill =
    !isNextHopRestoreForeground &&
    workspaceTrainingState?.theoryDrill &&
    (!debugTheoryDrillId || workspaceTrainingState.theoryDrill.id === debugTheoryDrillId)
      ? workspaceTrainingState.theoryDrill
      : undefined;
  const visibleScenarioLab =
    !isNextHopRestoreForeground &&
    workspaceTrainingState?.scenarioLab &&
    (!debugScenarioLabId || workspaceTrainingState.scenarioLab.id === debugScenarioLabId)
      ? workspaceTrainingState.scenarioLab
      : undefined;
  const visibleReviewArtifact =
    !isNextHopRestoreForeground &&
    workspaceTrainingState?.reviewArtifact &&
    (!debugReviewArtifactId || workspaceTrainingState.reviewArtifact.id === debugReviewArtifactId)
      ? workspaceTrainingState.reviewArtifact
      : undefined;
  const visibleTheoryQuestion =
    visibleTheoryDrill && Array.isArray(visibleTheoryDrill.questions) && visibleTheoryDrill.questions.length > 0
      ? visibleTheoryDrill.questions[
          Math.max(
            0,
            Math.min(
              visibleTheoryDrill.currentQuestionIndex ?? 0,
              visibleTheoryDrill.questions.length - 1,
            ),
          )
        ]
      : undefined;
  const visibleActiveSubmode =
    debugRestoreTarget === "theory_drill"
      ? "flash"
      : debugRestoreTarget === "scenario_lab" ||
          debugRestoreTarget === "review_artifact" ||
          debugRestoreTarget === "next_hop" ||
          isNextHopRestoreForeground
        ? "practice"
        : workspaceTrainingState?.latestTrainingSubmode;
  const nextHopVisible = Boolean(
    nextHopShouldRender &&
      (nextHopPrimaryTitle ||
        completionNextHopDetail ||
        nextHopDisplay.handoffSummary ||
        nextHopDisplay.whyNow ||
        nextHopDisplay.status ||
        nextHopDisplay.targetId ||
        nextHopDisplay.candidateId ||
        nextHopDisplay.reviewArtifactId ||
        nextHopDisplay.planEvidenceId ||
        (debugRestoreTarget === "next_hop" &&
          (debugRestoredNextHop?.status ||
            nextHopDisplay.status ||
            debugRestoredNextHop?.targetId ||
            nextHopDisplay.targetId ||
            debugRestoredNextHop?.candidateId ||
            nextHopDisplay.candidateId))),
  );
  const visiblePracticeTask =
    isNextHopRestoreForeground && (completionNextHop || nextHopDisplay.cardTitle || nextHopDisplay.summary) && task
      ? {
          ...task,
          id: nextHopDisplay.targetId || nextHopDisplay.candidateId || task.id,
          title: nextHopDisplay.cardTitle || completionNextHop || task.title,
          description:
            nextHopDisplay.summary ||
            nextHopDisplay.handoffSummary ||
            nextHopDisplay.whyNow ||
            task.description,
          nextActionLabel:
            nextHopDisplay.continueIn === "plan"
              ? text(language, "回到计划继续", "Continue in plan")
              : nextHopDisplay.continueIn === "chat"
                ? text(language, "回到对话继续", "Return to coach")
                : text(language, "继续训练", "Continue training"),
          constraints:
            task.constraints.length > 0
              ? task.constraints
              : [
                  nextHopDisplay.whyNow ||
                    text(
                      language,
                      "恢复的下一步必须留在前景，不再回退到旧链路。",
                      "The restored next hop must stay in the foreground; do not fall back to the old chain.",
                    ),
                ].filter((item): item is string => Boolean(item)),
          acceptanceCriteria:
            (task.acceptanceCriteria ?? []).length > 0
              ? task.acceptanceCriteria
              : [
                  nextHopDisplay.nextAfterCompletion ||
                    nextHopDisplay.returnSummary ||
                    nextHopDisplay.handoffSummary ||
                    text(
                      language,
                      "训练视图需要直接展示并解释当前下一步。",
                      "The training view should directly show and explain the current next hop.",
                    ),
                ].filter((item): item is string => Boolean(item)),
        }
      : task;
  const reviewTruth = useMemo(
    () =>
      summarizeReviewQueueTruth(
        workspaceTrainingState?.dueReviews ?? [],
        latestReviewQueueActionSummary,
        language,
      ),
    [language, latestReviewQueueActionSummary, workspaceTrainingState?.dueReviews],
  );
  const effectiveReviewSummary = useMemo(() => {
    const uniqueLines: string[] = [];
    for (const candidate of [reviewSummary, reviewTruth?.headline, reviewTruth?.detail]) {
      const normalized = normalizeText(candidate);
      if (!normalized || uniqueLines.includes(normalized)) {
        continue;
      }
      uniqueLines.push(normalized);
    }
    return uniqueLines.length ? uniqueLines.join(" ") : undefined;
  }, [reviewSummary, reviewTruth?.detail, reviewTruth?.headline]);
  const visibleFlashCard = useMemo(() => pickVisibleFlashAttempt(flashDeck), [flashDeck]);
  const normalizedTrainingCardCandidates = useMemo(() => {
    if (!Array.isArray(workspaceTrainingState?.trainingCardCandidates)) {
      return [];
    }
    const normalizedCandidates: Array<{
      id: string;
      type?: "practice" | "flash";
      status?: TrainingCardStatus;
    }> = [];
    for (const entry of workspaceTrainingState.trainingCardCandidates) {
      if (!entry || typeof entry !== "object") {
        continue;
      }
      const candidate = entry as {
        id?: string;
        cardId?: string;
        type?: string;
        card_type?: string;
        status?: unknown;
      };
      const id = normalizeText(candidate.id ?? candidate.cardId);
      if (!id) {
        continue;
      }
      const type =
        candidate.type === "flash" || candidate.card_type === "flash"
          ? "flash"
          : candidate.type === "practice" || candidate.card_type === "practice"
            ? "practice"
            : undefined;
      const status = isTrainingCardStatus(candidate.status) ? candidate.status : undefined;
      normalizedCandidates.push({ id, type, status });
    }
    return normalizedCandidates;
  }, [workspaceTrainingState?.trainingCardCandidates]);

  const selectedCardMeta = useMemo(() => {
    if (
      !workspaceTrainingState?.selectedCardId ||
      !Array.isArray(workspaceTrainingState.trainingCardCandidates)
    ) {
      return undefined;
    }
    const normalizedSelectedId = normalizeText(workspaceTrainingState.selectedCardId);
    for (const entry of workspaceTrainingState.trainingCardCandidates) {
      if (!entry || typeof entry !== "object") continue;
      const candidate = entry as {
        id?: string;
        cardId?: string;
        focus_area?: string;
        focusArea?: string;
        target_skill?: string;
        targetSkill?: string;
        scenario_pack?: string;
        scenarioPack?: string;
        why_now?: string;
        whyNow?: string;
        source_chain?: string[];
        sourceChain?: string[];
        feedback_targets?: string[];
        feedbackTargets?: string[];
      };
      const id = normalizeText(candidate.id ?? candidate.cardId);
      if (id === normalizedSelectedId) {
        return {
          focusArea: candidate.focus_area ?? candidate.focusArea ?? "",
          targetSkill: candidate.target_skill ?? candidate.targetSkill ?? "",
          scenarioPack: candidate.scenario_pack ?? candidate.scenarioPack ?? "",
          whyNow: candidate.why_now ?? candidate.whyNow ?? "",
          sourceChain: Array.isArray(candidate.source_chain)
            ? candidate.source_chain
            : Array.isArray(candidate.sourceChain)
              ? candidate.sourceChain
              : undefined,
          feedbackTargets: Array.isArray(candidate.feedback_targets)
            ? candidate.feedback_targets
            : Array.isArray(candidate.feedbackTargets)
              ? candidate.feedbackTargets
              : undefined,
        };
      }
    }
    return undefined;
  }, [workspaceTrainingState?.selectedCardId, workspaceTrainingState?.trainingCardCandidates]);
  const scenarioPackLabel = useMemo(
    () =>
      summarizeTrainingScenarioPack(
        language,
        selectedCardMeta?.scenarioPack ??
          workspaceTrainingState?.latestTrainingHandoff?.scenarioPack ??
          workspaceTrainingState?.latestTrainingNextHop?.scenarioPack,
      ),
    [
      language,
      selectedCardMeta?.scenarioPack,
      workspaceTrainingState?.latestTrainingHandoff?.scenarioPack,
      workspaceTrainingState?.latestTrainingNextHop?.scenarioPack,
    ],
  );

  const selectedDueReview = useMemo(() => {
    const dueReviews = workspaceTrainingState?.dueReviews;
    if (!Array.isArray(dueReviews) || dueReviews.length === 0) {
      return undefined;
    }

    const selectedKeys = [
      selectedCardMeta?.focusArea,
      selectedCardMeta?.targetSkill,
      selectedCardMeta?.whyNow,
      selectedCardMeta?.sourceChain?.[0],
      workspaceTrainingState?.selectedCardTitle,
    ]
      .map((value) => normalizeText(value)?.toLowerCase())
      .filter((value): value is string => Boolean(value));

    if (selectedKeys.length === 0) {
      return undefined;
    }

    for (const review of dueReviews) {
      const reviewKeys = [review.focusArea, review.concept, review.taskHint]
        .map((value) => normalizeText(value)?.toLowerCase())
        .filter((value): value is string => Boolean(value));
      if (
        reviewKeys.some((key) => selectedKeys.includes(key)) ||
        selectedKeys.some((key) => reviewKeys.includes(key))
      ) {
        return review;
      }
    }

    return undefined;
  }, [
    selectedCardMeta?.sourceChain,
    selectedCardMeta?.focusArea,
    selectedCardMeta?.targetSkill,
    selectedCardMeta?.whyNow,
    workspaceTrainingState?.dueReviews,
    workspaceTrainingState?.selectedCardTitle,
  ]);

  const visibleMemoryLayers = useMemo(() => memoryLayers.slice(0, 4), [memoryLayers]);

  function resolveTrainingCardStatus(
    cardId: string | undefined,
    cardType: "practice" | "flash",
  ): TrainingCardStatus {
    const normalizedCardId = normalizeText(cardId);
    const selectedCardId = normalizeText(workspaceTrainingState?.selectedCardId);
    const selectedCardType = workspaceTrainingState?.selectedCardType;

    if (
      normalizedCardId &&
      selectedCardId === normalizedCardId &&
      (!selectedCardType || selectedCardType === cardType) &&
      workspaceTrainingState?.selectedCardStatus
    ) {
      return workspaceTrainingState.selectedCardStatus;
    }

    const candidateStatus = normalizedTrainingCardCandidates.find(
      (candidate) =>
        candidate.id === normalizedCardId &&
        (!candidate.type || candidate.type === cardType) &&
        candidate.status,
    )?.status;
    if (candidateStatus) {
      return candidateStatus;
    }

    if (cardType === "flash") {
      const flashStatus = visibleFlashCard?.status;
      return visibleFlashCard?.cardId === normalizedCardId &&
        flashStatus &&
        flashStatus !== "unanswered"
        ? "answered"
        : "active";
    }

    return "active";
  }

  const visibleCardType = mode === "flash" ? "flash" : "practice";
  const visibleCardId = normalizeText(
    mode === "flash" ? visibleFlashCard?.cardId : visiblePracticeTask?.id,
  );
  const visibleCardStatus = resolveTrainingCardStatus(visibleCardId, visibleCardType);
  useEffect(() => {
    if (!pendingCardStatusTransition) {
      return;
    }
    if (
      !visibleCardId ||
      visibleCardId !== pendingCardStatusTransition.cardId ||
      visibleCardType !== pendingCardStatusTransition.cardType
    ) {
      setPendingCardStatusTransition(null);
      return;
    }
    if (visibleCardStatus === pendingCardStatusTransition.newStatus) {
      setPendingCardStatusTransition(null);
      return;
    }
    if (
      visibleCardStatus !== pendingCardStatusTransition.sourceStatus &&
      visibleCardStatus !== pendingCardStatusTransition.newStatus
    ) {
      setPendingCardStatusTransition(null);
    }
  }, [pendingCardStatusTransition, visibleCardId, visibleCardStatus, visibleCardType]);

  useEffect(() => {
    if (!pendingCardStatusTransition) {
      return;
    }
    const timeoutId = window.setTimeout(() => {
      setPendingCardStatusTransition((current) =>
        current?.requestedAt === pendingCardStatusTransition.requestedAt ? null : current,
      );
    }, 4000);
    return () => window.clearTimeout(timeoutId);
  }, [pendingCardStatusTransition]);

  useEffect(() => {
    onDebugVisibleFacts?.({
      surfaceMode: mode,
      activeSubmode: visibleActiveSubmode,
      visibleCaption:
        (coachJudgmentPending ? coachJudgmentSummary : latestReviewQueueActionSummary) ?? undefined,
      latestReviewQueueActionSummary,
      coachJudgmentPending,
      coachJudgmentSummary,
      selectedCardTitle:
        workspaceTrainingState?.selectedCardTitle ??
        resolvedHandoff.selectedCardTitle ??
        primaryCardTitle,
      routeWorkspaceLabel,
      theoryDrillVisible: Boolean(visibleTheoryDrill),
      theoryDrillId: visibleTheoryDrill?.id,
      theoryDrillTitle: visibleTheoryDrill?.title,
      theoryDrillStatus: visibleTheoryDrill?.status,
      theoryQuestionPrompt: visibleTheoryQuestion?.prompt,
      theoryQuestionKnowledgeType: visibleTheoryQuestion?.knowledgeType,
      scenarioLabVisible: Boolean(visibleScenarioLab),
      scenarioLabId: visibleScenarioLab?.id,
      scenarioLabTitle: visibleScenarioLab?.title,
      scenarioLabStatus: visibleScenarioLab?.status,
      scenarioLabScenario: visibleScenarioLab?.scenario,
      reviewArtifactVisible: Boolean(visibleReviewArtifact),
      reviewArtifactId: visibleReviewArtifact?.id,
      reviewArtifactStatus: visibleReviewArtifact?.status,
      reviewArtifactSummary:
        visibleReviewArtifact?.summary ?? visibleReviewArtifact?.verifiedResult ?? visibleReviewArtifact?.blocker,
      nextHopVisible,
      nextHopTitle: nextHopVisible ? nextHopPrimaryTitle : undefined,
      nextHopStatus: nextHopDisplay.status ?? debugRestoredNextHop?.status,
      nextHopContinueIn: nextHopDisplay.continueIn ?? debugRestoredNextHop?.continueIn,
      nextHopCardTitle: nextHopDisplay.cardTitle ?? debugRestoredNextHop?.cardTitle,
      nextHopCandidateType: nextHopDisplay.candidateType ?? debugRestoredNextHop?.candidateType,
      nextHopTargetKind: nextHopDisplay.targetKind ?? debugRestoredNextHop?.targetKind,
      nextHopTargetId: nextHopDisplay.targetId ?? debugRestoredNextHop?.targetId,
      nextHopReviewArtifactId:
        nextHopDisplay.reviewArtifactId ?? debugRestoredNextHop?.reviewArtifactId,
      nextHopPlanEvidenceId: nextHopDisplay.planEvidenceId ?? debugRestoredNextHop?.planEvidenceId,
      latestReviewQueueEventType: latestReviewQueueLedgerEvent?.eventType,
      latestReviewQueueAttemptKind: latestReviewQueueLedgerEvent?.attemptKind,
      latestReviewQueueAuthoritySource: latestReviewQueueLedgerEvent?.authoritySource,
      latestReviewQueueCurrentSubmode: latestReviewQueueLedgerEvent?.currentSubmode,
      singleCardImmersive,
      routeStripCollapsedByDefault,
      cardOnlyMode,
      secondaryPanelsCollapsedByDefault,
      secondaryPanelsOpen,
    });
  }, [
    cardOnlyMode,
    coachJudgmentPending,
    coachJudgmentSummary,
    latestReviewQueueActionSummary,
    latestReviewQueueLedgerEvent,
    mode,
    onDebugVisibleFacts,
    primaryCardTitle,
    routeStripCollapsedByDefault,
    resolvedHandoff.selectedCardTitle,
    nextHopDisplay.candidateType,
    nextHopDisplay.cardTitle,
    nextHopDisplay.continueIn,
    nextHopDisplay.fallbackAction,
    nextHopDisplay.handoffSummary,
    nextHopDisplay.hasRenderableCopy,
    nextHopDisplay.hasStructuredTarget,
    nextHopDisplay.planEvidenceId,
    nextHopDisplay.reviewArtifactId,
    nextHopDisplay.summary,
    nextHopDisplay.status,
    nextHopDisplay.title,
    nextHopDisplay.targetId,
    nextHopDisplay.targetKind,
    nextHopDisplay.whyNow,
    nextHopHasStructuredAuthority,
    nextHopPrimaryTitle,
    nextHopShouldRender,
    debugRestoredNextHop,
    routeWorkspaceLabel,
    secondaryPanelsCollapsedByDefault,
    secondaryPanelsOpen,
    singleCardImmersive,
    visibleReviewArtifact,
    visibleScenarioLab,
    visibleTheoryDrill,
    visibleTheoryQuestion,
    visibleActiveSubmode,
    workspaceTrainingState?.selectedCardTitle,
    nextHopVisible,
  ]);

  function setModeAndNotify(next: TrainingSurfaceMode): void {
    setMode(next);
    onTrainingSubmodeChange?.(next === "flash" ? "flash" : "practice");
  }

  function submitDependencyAction(): void {
    if (!onDependencySkillMapAction || !dependency) {
      return;
    }
    if (stageAction !== "mark_transferable") {
      if (onVerifyCurrentFile && visibleCardId && visibleCardType === "practice") {
        onVerifyCurrentFile({
          cardId: visibleCardId,
          cardTitle: primaryCardTitle,
          acceptanceCriteria: resolvedHandoff.verificationSteps,
          learnerDeliverables: resolvedHandoff.learnerDeliverables,
        });
        return;
      }
      onDependencySkillMapAction({
        dependencyKey: dependency.dependencyKey,
        action: "request_verification",
        note: text(
          language,
          "已记录为待验证。请回到当前练习并使用“验证当前文件”。",
          "Recorded as waiting for verification. Return to the current practice and use Verify current file.",
        ),
      });
      return;
    }
    if (!transferDraft || !transferReady) {
      return;
    }
    onDependencySkillMapAction({
      dependencyKey: dependency.dependencyKey,
      action: "request_verification",
      note: textFilled(
        language,
        "已提交迁移说明，等待 Trainer 验证：{0}",
        "Transfer note submitted for Trainer verification: {0}",
        transferDraft.evidenceSummary,
      ),
      relatedApi: transferDraft.relatedApi,
      scenario: transferDraft.scenario,
      focusItemKey: transferDraft.focusItemKey,
    });
  }

  function handleCardStatusTransition(cardId: string, newStatus: TrainingCardStatus, reason?: string): void {
    if (!onCardStatusTransition) {
      return;
    }
    const normalizedCardId = normalizeText(cardId);
    if (!normalizedCardId) {
      return;
    }
    const currentCardType = mode === "flash" ? "flash" : "practice";
    if (visibleCardId && visibleCardId !== normalizedCardId) {
      return;
    }
    const currentStatus = resolveTrainingCardStatus(normalizedCardId, currentCardType);
    if (!isValidCardTransition(currentStatus, newStatus)) {
      return;
    }
    setPendingCardStatusTransition({
      cardId: normalizedCardId,
      cardType: currentCardType,
      sourceStatus: currentStatus,
      newStatus,
      requestedAt: Date.now(),
    });
    try {
      onCardStatusTransition(normalizedCardId, newStatus, reason);
    } catch (error) {
      setPendingCardStatusTransition(null);
      throw error;
    }
  }

  // Loading state - when connection is starting and no task yet
  if (isLoading && !task) {
    return (
      <section className="section-block training-state training-state--loading" aria-busy="true">
        <div className="training-skeleton-lines" aria-hidden="true">
          <span className="skeleton training-skeleton-line" />
          <span className="skeleton training-skeleton-line" />
          <span className="skeleton training-skeleton-line training-skeleton-line--short" />
        </div>
        <p className="training-state__text">
          {text(language, "正在准备训练内容...", "Preparing training content...")}
        </p>
      </section>
    );
  }

  // Empty state - when connection is ready but no task
  if (!task) {
    return (
      <section className="section-block training-state training-state--empty">
        <span className="training-state__icon" aria-hidden="true"><BooksIcon size={32} /></span>
        <strong className="training-state__title">
          {text(language, "没有当前训练任务", "No active training task")}
        </strong>
        <p className="training-state__text">
          {text(language, "从计划开始，或生成训练卡。", "Start from the plan or generate a card.")}
        </p>
        <div className="training-state__suggestions">
          <button
            className="training-state__suggestion-btn training-state__suggestion-btn--primary"
            onClick={() => onQuickStartTraining?.("flash")}
            type="button"
          >
            <BooksIcon size={14} />
            {text(language, "开始训练", "Start training")}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="training-view training-view--minimal practice-view practice-view--compact">
      {/* Compact progress line - one row, no dots */}
      {normalizedTrainingCardCandidates.length > 1 && !trainingPausedByResourceRisk ? (
        <div className="training-progress-line" role="status" aria-label={text(language, "训练进度", "Training progress")}>
          {(() => {
            const currentIdx = normalizedTrainingCardCandidates.findIndex(
              (c) => c.id === workspaceTrainingState?.selectedCardId,
            );
            const display = currentIdx >= 0 ? currentIdx + 1 : 1;
            const total = normalizedTrainingCardCandidates.length;
            return trainingProgressLineCopy[language](display, total);
          })()}
        </div>
      ) : null}

      {/* Current chain strip removed: title and chain context now live inside the card. */}

      {scenarioPackLabel ? (
        <div className="training-next-move">
          <span className="training-next-move__label">
            {text(language, "先学习", "Learn first")}
          </span>
          <strong>
            {text(language, "场景包", "Scenario pack")} · {scenarioPackLabel}
          </strong>
          <p>
            {text(
              language,
              "先读完这组场景的学习摘要，再进入下面的测试。",
              "Read the learning summary for this scenario family before you use the test below.",
            )}
          </p>
        </div>
      ) : null}

      {/* Main training content */}
      {trainingPausedByResourceRisk ? null : mode === "flash" ? (
        <CoachFlashView
          language={language}
          deck={flashDeck}
          dependencyMastery={dependencyMastery}
          recentAttempts={recentFlashAttempts}
          busy={flashBusy}
          practiceBridge={flashPracticeBridge}
           cardStatus={visibleCardStatus}
           onCardStatusTransition={handleCardStatusTransition}
           onVerifyCurrentFile={onVerifyCurrentFile}
           cardStatusBusy={cardStatusBusy}
          onRefreshDeck={onRefreshDeck}
          onSubmitAnswer={onSubmitFlashAnswer}
          onOpenCoach={() => {
            onOpenCoachBridgeFromFlash?.(practiceCoachBridge);
            onOpenCoachFromFlash?.();
          }}
          onOpenPractice={onOpenPracticeFromFlash}
          onCreateFlashcard={onCreateFlashcard}
          compact
          cardOnly
          sourceChain={selectedCardMeta?.sourceChain ?? workspaceTrainingState?.latestTrainingNextHop?.sourceChain ?? workspaceTrainingState?.latestTrainingHandoff?.sourceChain}
          whyNow={selectedCardMeta?.whyNow ?? workspaceTrainingState?.latestTrainingNextHop?.whyNow}
          targetSkill={selectedCardMeta?.targetSkill || undefined}
          feedbackTargets={selectedCardMeta?.feedbackTargets}
          scenarioPackLabel={scenarioPackLabel}
        />
      ) : (
        <CoachPracticeView
          language={language}
            task={
              isNextHopRestoreForeground && (completionNextHop || nextHopDisplay.cardTitle || nextHopDisplay.summary)
                ? {
                    ...task,
                    id: nextHopDisplay.targetId || nextHopDisplay.candidateId || task.id,
                    title: nextHopDisplay.cardTitle || completionNextHop || task.title,
                    description:
                      nextHopDisplay.summary ||
                      nextHopDisplay.handoffSummary ||
                      nextHopDisplay.whyNow ||
                      task.description,
                    nextActionLabel:
                      nextHopDisplay.continueIn === "plan"
                        ? text(language, "回到计划继续", "Continue in plan")
                        : nextHopDisplay.continueIn === "chat"
                          ? text(language, "回到对话继续", "Return to coach")
                          : text(language, "继续训练", "Continue training"),
                    constraints:
                      task.constraints.length > 0
                        ? task.constraints
                        : [
                            nextHopDisplay.whyNow ||
                      text(language, "恢复的下一步必须留在前景，不再回退到旧链路。", "The restored next hop must stay in the foreground; do not fall back to the old chain."),
                          ].filter((item): item is string => Boolean(item)),
                    acceptanceCriteria:
                      (task.acceptanceCriteria ?? []).length > 0
                        ? task.acceptanceCriteria
                        : [
                            nextHopDisplay.nextAfterCompletion ||
                              nextHopDisplay.returnSummary ||
                              nextHopDisplay.handoffSummary ||
                      text(language, "训练视图需要直接展示并解释当前下一步。", "The training view should directly show and explain the current next hop."),
                          ].filter((item): item is string => Boolean(item)),
                  }
                : task
            }
          workspaceUnderstanding={workspaceUnderstanding}
          evidencePack={evidencePack}
          teachingDecision={teachingDecision}
          recoveredRuntime={recoveredRuntime}
          runtimeCurrentStep={runtimeCurrentStep}
          implementationGuide={implementationGuide}
          dependencyMastery={dependencyMastery}
          learningOutcomes={learningOutcomes}
          reviewSummary={effectiveReviewSummary}
          reviewMeta={reviewTruth?.meta}
          latestReviewActionSummary={reviewTruth?.latestAction}
          latestVerifiedResult={workspaceTrainingState?.latestLearningVerifiedResult}
          latestLearningBlocker={latestLearningBlocker || workspaceTrainingState?.latestLearningBlocker}
          latestLearningFollowup={workspaceTrainingState?.latestLearningFollowup}
          latestReturnWith={resolvedHandoff.returnWith}
          latestSuccessSignal={resolvedHandoff.successSignal}
          latestNextHop={completionNextHop}
          latestNextHopMeta={completionNextHopMeta}
          latestNextHopDetail={completionNextHopDetail}
          latestLearnerDeliverables={resolvedHandoff.learnerDeliverables}
          latestVerificationSteps={resolvedHandoff.verificationSteps}
          reviewArtifact={
            workspaceTrainingState?.reviewArtifact
              ? {
                  summary: workspaceTrainingState.reviewArtifact.summary,
                  verifiedResult: workspaceTrainingState.reviewArtifact.verifiedResult,
                  blocker: workspaceTrainingState.reviewArtifact.blocker,
                  abandonReason: workspaceTrainingState.reviewArtifact.abandonReason,
                  partialProgress: workspaceTrainingState.reviewArtifact.partialProgress,
                  rootCause: workspaceTrainingState.reviewArtifact.rootCause,
                  nextSelfImplementationRule:
                    workspaceTrainingState.reviewArtifact.nextSelfImplementationRule,
                  recommendedActions: workspaceTrainingState.reviewArtifact.recommendedActions,
                  status: workspaceTrainingState.reviewArtifact.status,
                }
              : undefined
          }
          cardStatus={visibleCardStatus}
          onCardStatusTransition={handleCardStatusTransition}
          cardStatusBusy={cardStatusBusy}
          onRefreshTask={onRefreshTask}
          onOpenCoach={onOpenCoachFromPractice}
          onOpenFlash={() => setModeAndNotify("flash")}
          busy={practiceBusy}
          compact
          cardOnly
          cardSourceChain={selectedCardMeta?.sourceChain ?? (Array.isArray(task?.metadata?.sourceChain) ? (task.metadata.sourceChain as string[]) : undefined)}
          cardWhyNow={selectedCardMeta?.whyNow ?? primaryCardReason}
          cardTargetSkill={selectedCardMeta?.targetSkill || undefined}
          cardFeedbackTargets={selectedCardMeta?.feedbackTargets}
          scenarioPackLabel={scenarioPackLabel}
        />
      )}

      {/* Post-card next-hop button removed; the back-end automatically advances after each card. */}

      {resolvedHandoff.shouldRender && showTrainingRouteStrip && chainExpanded ? (
        <details
          className="training-active-card-route training-active-card-route--collapsed"
          aria-label={text(language, "对话到训练的交接", "Chat-to-training handoff")}
        >
          <summary className="training-active-card-route__pill">
            <span className="training-active-card-route__pill-label">{text(language, "来源", "Origin")}</span>
            <span className="training-active-card-route__pill-title">{primaryCardTitle}</span>
          </summary>
          <div className="training-active-card-route__header">
            <div>
              <span className="eyebrow">{text(language, "对话交接", "Conversation handoff")}</span>
              <strong>{primaryCardTitle}</strong>
            </div>
            <p>{primaryCardReason}</p>
          </div>
          <div className="training-active-card-route__factors">
            <div className="training-active-card-route__factor">
              <span>{text(language, "工作区", "Workspace")}</span>
              <strong>{routeWorkspaceLabel}</strong>
            </div>
            <div className="training-active-card-route__factor">
              <span>{text(language, "类型", "Type")}</span>
              <strong>{primaryCardTypeLabel}</strong>
            </div>
            <div className="training-active-card-route__factor">
              <span>{text(language, "路由", "Routing")}</span>
              <strong>
                {text(language, "候选", "Candidates")} {resolvedHandoff.candidateCount} /{" "}
                {text(language, "可用", "Eligible")} {resolvedHandoff.eligibleCount}
              </strong>
            </div>
            <div className="training-active-card-route__factor">
              <span>{text(language, "边界", "Boundary")}</span>
              <strong>
                {resolvedHandoff.coachOnly
                  ? text(language, "coach-only", "coach-only")
                  : text(language, "引导式", "guided")}
              </strong>
            </div>
          </div>
          <p className="training-active-card-route__compact-note">
            {text(
              language,
              "默认只保留来源和边界摘要。交付物与验证保持可展开，让单卡主线仍然是第一优先。",
              "By default this keeps only source and boundary summary. Deliverables and verification stay expandable so the single-card lane remains primary.",
            )}
          </p>
          {handoffContractVisible ? (
            <details className="training-active-card-route__details">
              <summary>{text(language, "查看卡片契约和验证", "Show the card contract and verification")}</summary>
              <div className="training-active-card-route__details-body">
                <div className="training-active-card-route__contract">
                  {resolvedHandoff.learnerDeliverables.length ? (
                    <article className="training-active-card-route__contract-card">
                      <span className="eyebrow">{text(language, "你交付", "You deliver")}</span>
                      <ul>
                        {resolvedHandoff.learnerDeliverables.slice(0, 3).map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </article>
                  ) : null}
                  {resolvedHandoff.verificationSteps.length ? (
                    <article className="training-active-card-route__contract-card">
                      <span className="eyebrow">{text(language, "这样验证", "Verify like this")}</span>
                      <ul>
                        {resolvedHandoff.verificationSteps.slice(0, 3).map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </article>
                  ) : null}
                  <article className="training-active-card-route__contract-card">
                    <span className="eyebrow">{text(language, "带回", "Bring back")}</span>
                    <p>
                      {resolvedHandoff.returnWith ||
                        resolvedHandoff.nextAfterCompletion ||
                        resolvedHandoff.successSignal ||
                        text(
                          language,
                          "把这张卡的结果和验证输出带回来，再让教练判断是复习、升级，还是写入计划证据。",
                          "Bring back the result of this card plus the verification output, then let the coach decide whether to review, level up, or feed it back into plan evidence.",
                        )}
                    </p>
                  </article>
                </div>
              </div>
            </details>
          ) : null}
          {trainingPausedByResourceRisk ? (
            <div className="training-resource-risk-gate" role="status" aria-live="polite">
              <strong>{text(language, "训练已暂停", "Training paused")}</strong>
              <p>{resourceRiskReason}</p>
              <p>
                {text(
                  language,
                  "Trainer 不会继续从过期资料路由训练卡，也不会假装这张卡仍然安全可继续。",
                  "Trainer will not keep routing cards from stale material or pretend this card is still safe to continue.",
                )}
              </p>
              <div className="training-command-center__actions">
                <ActionButton
                  fullWidth={false}
                  tone="accent"
                  icon={<BooksIcon size={14} />}
                  label={text(language, "打开资料", "Open Resources")}
                  detail={text(
                    language,
                    "先用资料页修正来源，再强制继续",
                    "Use resources as support before forcing the route",
                  )}
                  type="button"
                  disabled={!onOpenResources}
                  onClick={() => onOpenResources?.()}
                />
                <ActionButton
                  fullWidth={false}
                  tone="ghost"
                  icon={<LightningIcon size={14} />}
                  label={text(language, "刷新训练路由", "Refresh training route")}
                  detail={text(
                    language,
                    "重新收紧这张卡的下一步",
                    "Tighten the next step for this card again",
                  )}
                  type="button"
                  onClick={() => onRefreshTask(focus)}
                />
              </div>
            </div>
          ) : null}
          {resolvedHandoff.blockedCandidate ? (
            <p className="practice-card__note">
              {text(language, "同轮还有候选卡被阻塞：", "Some same-turn candidates were blocked: ")}
              {resolvedHandoff.blockedCandidate.title}
              {resolvedHandoff.blockedReason ? ` | ${resolvedHandoff.blockedReason}` : ""}
            </p>
          ) : null}
        </details>
      ) : null}

      {!masteryPanelVisible && dependency ? (
        <div className="training-mastery-toggle-wrap">
          <button
            className="button button--ghost button--micro"
            type="button"
            onClick={() => setMasteryPanelVisible(true)}
          >
            {text(language, "迁移评估 ->", "Transfer assessment ->")}
          </button>
        </div>
      ) : null}

      {masteryPanelVisible && (
        <details
          className="section-block training-status-card training-status-card--secondary training-status-card--collapsible training-mastery-evidence"
          open={secondaryPanelsOpen}
          onToggle={(event) => {
            setSecondaryPanelsOpen((event.currentTarget as HTMLDetailsElement).open);
          }}
        >
        <summary>
          <span className="eyebrow">{text(language, "依赖/API 掌握度", "Dependency/API mastery")}</span>
          <strong>
            {dependency
              ? `${dependency.dependencyName} 路 ${stageLabel(language, dependency.masteryStage)}`
              : text(language, "等待训练证据", "Waiting for training evidence")}
          </strong>
          <span className="training-mastery-evidence__summary">
            {dependency
              ? compactTrainingCardText(
                  language,
                  dependency.projectFirstCut ||
                    dependency.prioritySummary ||
                  text(language, "只使用当前卡片关联的证据", "Only evidence tied to the current card"),
                  { maxLength: 58 },
                ) ||
                text(language, "只使用当前卡片关联的证据", "Only evidence tied to the current card")
              : text(language, "当前卡片产出证据后再展开", "Expand after the current card produces evidence")}
          </span>
        </summary>
        <div className="training-collapsible__content">
          {dependency ? (
            <>
              <div className="training-command-center__grid">
                <article className="training-command-center__card">
                  <span className="eyebrow">{text(language, "当前阶段", "Current stage")}</span>
                  <strong>{stageLabel(language, dependency.masteryStage)}</strong>
                  <p className="training-command-center__detail">
                    {text(
                      language,
                      "理解、回忆、练习、应用、迁移是不同证据层。完成次数本身不等于掌握。",
                      "Understanding, recall, practice, application, and transfer are evidence layers. Completion count is not mastery.",
                    )}
                  </p>
                </article>
                <article className="training-command-center__card">
                  <span className="eyebrow">{text(language, "下一步", "Next step")}</span>
                  <strong>{dependency.projectFirstCut || dependency.prioritySummary || text(language, "继续当前卡片", "Continue the current card")}</strong>
                  <p className="training-command-center__detail">
                    {dependency.relatedApi || dependency.scenario || text(language, "先完成一个由学习者自己掌握的切片，再记录证据。", "Finish a learner-owned slice before recording evidence.")}
                  </p>
                </article>
              </div>
              {stageAction === "mark_transferable" && transferDraft ? (
                <div className="training-transfer-evidence">
                  <div className="training-transfer-evidence__header">
                    <strong>{text(language, "迁移说明（待验证）", "Transfer note (waiting for verification)")}</strong>
                    <span className="practice-chip">{transferReady ? text(language, "可提交说明", "Ready to submit note") : text(language, "需要补充", "Needs details")}</span>
                  </div>
                  {workspaceTrainingState?.latestTransferBlockedReason ? (
                    <p className="practice-card__note">{workspaceTrainingState.latestTransferBlockedReason}</p>
                  ) : null}
                  <p className="practice-card__note">
                    {text(
                      language,
                      "填写说明不会直接改变掌握记录，提交后由 Trainer 验证。",
                      "A note does not change mastery by itself. Trainer verifies it after submission.",
                    )}
                  </p>
                  <div className="training-transfer-evidence__fields">
                    <label className="training-transfer-evidence__field">
                      <span>{text(language, "源工作区", "Source workspace")}</span>
                      <input type="text" value={transferDraft.sourceWorkspaceId} readOnly />
                    </label>
                    <label className="training-transfer-evidence__field">
                      <span>{text(language, "目标工作区", "Target workspace")}</span>
                      <select
                        value={transferDraft.targetWorkspaceId}
                        onChange={(event) =>
                          setTransferDraft((current) =>
                            current ? { ...current, targetWorkspaceId: event.target.value } : current,
                          )
                        }
                      >
                        <option value="">{text(language, "选择目标工作区", "Choose target workspace")}</option>
                        {transferWorkspaceOptions.map((option) => (
                          <option key={option.workspaceId} value={option.workspaceId}>
                            {option.label}
                            {option.recommended ? text(language, "（推荐）", " (Recommended)") : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="training-transfer-evidence__field">
                      <span>{text(language, "迁移说明", "Transfer note")}</span>
                      <textarea
                        rows={3}
                        value={transferDraft.verifiedResult}
                        onChange={(event) =>
                          setTransferDraft((current) =>
                            current ? { ...current, verifiedResult: event.target.value } : current,
                          )
                        }
                      />
                    </label>
                    <label className="training-transfer-evidence__field">
                      <span>{text(language, "补充说明", "Evidence note")}</span>
                      <textarea
                        rows={2}
                        value={transferDraft.evidenceSummary}
                        onChange={(event) =>
                          setTransferDraft((current) =>
                            current ? { ...current, evidenceSummary: event.target.value } : current,
                          )
                        }
                      />
                    </label>
                  </div>
                </div>
              ) : null}
              <div className="training-command-center__actions">
                <button
                  className="button"
                  type="button"
                  disabled={stageAction === "mark_transferable" ? !canSubmitTransfer : !canSubmitStage}
                  onClick={submitDependencyAction}
                >
                  {actionLabel(language, stageAction)}
                </button>
                <details className="training-mastery-evidence__more">
                  <summary>{text(language, "更多动作", "More actions")}</summary>
                  <div className="training-command-center__actions training-command-center__actions--secondary">
                    <button
                      className="button button--ghost"
                      type="button"
                      disabled={!onDependencySkillMapAction}
                      onClick={() =>
                        onDependencySkillMapAction?.({
                          dependencyKey: dependency.dependencyKey,
                          action: "send_to_flashcards",
                          note: text(language, "把当前薄弱点送回闪卡巩固。", "Push the current weak spot back into flashcards."),
                        })
                      }
                    >
                      {text(language, "送去闪卡", "Send to flashcards")}
                    </button>
                    <button
                      className="button button--ghost"
                      type="button"
                      disabled={!onDependencySkillMapAction}
                      onClick={() =>
                        onDependencySkillMapAction?.({
                          dependencyKey: dependency.dependencyKey,
                          action: "start_scenario_lab",
                          note: text(language, "先用一个最小场景把它稳定下来。", "Stabilize this with a minimum scenario first."),
                        })
                      }
                    >
                      {text(language, "场景实验", "Scenario lab")}
                    </button>
                  </div>
                </details>
              </div>
            </>
          ) : (
            <p className="practice-card__note">
              {text(
                language,
                "完成后显示掌握证据和下一步。",
                "Completion shows mastery evidence and the next step.",
              )}
            </p>
          )}
        </div>
      </details>
      )}
    </section>
  );
}
