import { FocusedPractice } from "../../templates/FocusedPractice";
import { NextAction } from "../../templates/NextAction";
import { VerificationResult } from "../../templates/VerificationResult";
import { templateCopy } from "../../templates/templateCopy";
import { useEffect, useRef, useState, useMemo, type ReactNode } from "react";

import {
  deriveTrainingExecutionState,
  type TrainingExecutionState,
} from "../../../../../shared/src/trainingExecutionGovernance";
import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";
import {
  describeTrainingReliability,
  type TrainingReliabilityRecord,
} from "../../../../../shared/src/trainingReliabilityGovernance";
import type { TrainingReliability, TrainingSkillProjection } from "../../lib/types";
import { RemoteVerificationPanel } from "./RemoteVerificationPanel";
import { remoteVerifyCopy } from "./remoteVerificationCopy";
import { MessageRichContent } from "../coach/MessageRichContent";
import { resolveCopy as resolveWorkbenchCopy } from "../../lib/i18n/copy";
import type { ComposerLanguage, TrainingCardType } from "../../lib/types";
import { useWorkbenchState } from "../../app/useWorkbenchState";
import type { TrainingCardStatus } from "../../../../../shared/src/trainingCardRouting";
import { groupReviewQueueByFocusArea } from "../../../../../shared/src/reviewQueueGovernance";

export type TrainingReviewAction = "accept" | "snooze" | "reset" | "skip" | "done";


export interface TrainingReviewItem {
  id: string;
  title: string;
  concept: string;
  focusArea: string;
  taskHint: string;
  due?: string;
  fsrs?: {
    intervalDays?: number;
    masteryScore?: number;
  };
  detail?: string;
  meta?: string;
}

export interface TrainingSummaryCard {
  title: string;
  detail?: string;
  meta?: string;
}

export type FlashVerificationMode = "choice" | "fill" | "short";

export interface FlashAnswerPayload {
  cardId?: string;
  theoryDrillId?: string;
  questionId?: string;
  mode: FlashVerificationMode;
  answer: string;
  selectedOptionIndex?: number;
  title: string;
  prompt?: string;
}

export interface TrainingWorkbenchViewProps {
  response?: ReactNode;
  onBackToLearning?: () => void;
  language: ComposerLanguage;
  cardType?: TrainingCardType;
  trainingSubmode?: string;
  cardOnly?: boolean;
  cardId?: string;
  selectedCardStatus?: string;
  /** Fail-closed: skip/grade must use hooked persistence path, not a bare command. */
  onCardStatusTransition?: (cardId: string, newStatus: TrainingCardStatus, reason?: string) => void;
  title: string;
  currentStep: string;
  learningFamily?: "code" | "theory";
  learningSubtype?: string;
  whyThisCard?: string;
  targetSkill?: string;
  problemStatement?: string;
  suggestedWorkspaceAction?: string;
  scenario?: string;
  whyNow?: string;
  sourceSummary?: string;
  sourceDetail?: string;
  apiHints?: string[];
  constraints?: string[];
  selfCheck?: string[];
  deliverable?: string;
  deliverables?: string[];
  validationMethod?: string;
  verificationMethod?: string;
  verifyItems: string[];
  successSignal?: string;
  returnWith?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  filesToTouch?: string[];
  hintLadder?: string[];
  commonMistakes?: string[];
  stuckRecovery?: string;
  reflectionPrompt?: string;
  restoredFocus?: TrainingSummaryCard;
  outcome?: TrainingSummaryCard;
  nextHop?: TrainingSummaryCard;
  coachSummary?: string;
  currentFocus?: string;
  scenarioPackLabel?: string;
  latestTrainingHandoffStatus?: string;
  latestTrainingLearningPhase?: string;
  latestTrainingReliability?: TrainingReliability;
  reliabilityInFlight?: boolean;
  latestTrainingNextHopStatus?: string;
  latestTrainingNextHopReason?: string;
  latestTrainingBlockedBy?: string;
  latestVerifiedResult?: string;
  latestLearningBlocker?: string;
  verificationNotice?: string;
  latestLearningFollowup?: string;
  /** Phase-D: evidence-derived skill states for the active attempt. */
  skillProjection?: TrainingSkillProjection;
  reviewItems?: TrainingReviewItem[];
  reviewQueueOpenRequest?: boolean;
  reviewSummary?: string;
  onReviewQueueAction?: (payload: {
    concept: string;
    action: TrainingReviewAction;
    focusArea: string;
    taskHint: string;
  }) => void;
  recentWins?: string[];
  weakSpots?: string[];
  primaryAction?: ReactNode;
  /** Card-owned verification affordance (preview/workspace verify flow). */
  onVerifyCurrentFile?: () => void;
  /** §八: remote identity + streaming verification panel state. */
  remoteVerification?: {
    running: boolean;
    output: string;
    summary?: string;
    finishedState?: "completed" | "cancelled" | "timed_out" | "spawn_failed" | "connection_lost";
    passed?: boolean;
  };
  remoteName?: string;
  onStopRemoteVerification?: () => void;
  /** §五: record honest assistance usage when the learner reveals a hint. */
  onHintReveal?: (hintLevel: number) => void;
  leftoverNote?: string;
  actions?: ReactNode;
  emptyState?: ReactNode;
  onPreviousCard?: () => void;
  onNextCard?: () => void;
  onRefreshDeck?: () => void;
  flashPrompt?: string;
  expectedSymbols?: string[];
}

/** Governance failures that mean "you acted on a card that does not own the live handoff". */
const CARD_HANDOFF_MISMATCH_PATTERN =
  /handoff belongs to a different card|leftover-not-live/i;

export interface TrainingCardMismatchRecovery {
  /** The card that owns the live handoff; activating it is the governed recovery move. */
  cardId: string;
}

export function resolveTrainingCardMismatchRecovery(input: {
  operationMessage?: { tone: "info" | "success" | "error"; message: string };
  handoffOwnerCardId?: string;
  selectedCardId?: string;
}): TrainingCardMismatchRecovery | undefined {
  if (input.operationMessage?.tone !== "error") {
    return undefined;
  }
  if (!CARD_HANDOFF_MISMATCH_PATTERN.test(input.operationMessage.message ?? "")) {
    return undefined;
  }
  const cardId =
    input.handoffOwnerCardId?.trim() || input.selectedCardId?.trim() || "";
  return cardId ? { cardId } : undefined;
}




export {
  applyTrainingCardGrade,
  applyTrainingCardSkip,
  interpretTrainingComposerCardCommand,
  type TrainingCardGrade,
  type TrainingComposerCardCommand,
} from "./trainingCardActions";
import {
  applyTrainingCardGrade as applyTrainingCardGradeImpl,
  applyTrainingCardSkip as applyTrainingCardSkipImpl,
  interpretTrainingComposerCardCommand as interpretTrainingComposerCardCommandImpl,
} from "./trainingCardActions";

function normalizeCardText(value: string | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

function isCurrentCardActionLabel(value: string): boolean {
  return /(?:submit\s+flash\s+answer|\u63d0\u4ea4\u95ea\u8bb0\u7b54\u6848|verify\s+current\s+file|\u8bfb\u53d6\u5f53\u524d\u6587\u4ef6\u9a8c\u8bc1)/iu.test(value);
}

function compactCardText(value: string | undefined, limit: number): string {
  const normalized = (value ?? "").replace(/\s+/g, " ").trim();
  if (!normalized || normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}\u2026`;
}

function compactArtifactText(value: string, limit: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "";
  }
  if (/[\\/]/.test(normalized)) {
    const segments = normalized.split(/[\\/]+/).filter(Boolean);
    const tail = segments.length > 3 ? segments.slice(-3).join("/") : segments.join("/");
    return compactCardText(tail, limit);
  }
  return compactCardText(normalized, limit);
}

function compactArtifactList(values: Array<string | undefined>, limit: number, maxItems: number): string[] {
  const seen = new Set<string>();
  const compacted: string[] = [];
  for (const value of values) {
    const label = compactArtifactText(value ?? "", limit);
    if (!label || seen.has(label)) {
      continue;
    }
    seen.add(label);
    compacted.push(label);
    if (compacted.length >= maxItems) {
      break;
    }
  }
  return compacted;
}

function stripTrainingCardTitlePrefix(value: string): string {
  const normalized = value.trim();
  return normalized.replace(/^(?:练习|闪记|Practice|Flash)\s*[:：]\s*/iu, "").trim() || normalized;
}

type TrainingVerificationReturnKind =
  | "waiting"
  | "verified"
  | "pending-plan-confirmation"
  | "needs-review"
  | "blocked";

interface TrainingVerificationReturnState {
  kind: TrainingVerificationReturnKind;
  eyebrow: string;
  title: string;
  detail: string;
  next: string;
}

function firstText(...values: Array<string | undefined>): string | undefined {
  return values.find((value) => Boolean(value?.trim()))?.trim();
}

function uniqueTrainingCardItems(values: Array<string | undefined>): string[] {
  const seen = new Set<string>();
  const items: string[] = [];

  for (const value of values) {
    const item = value?.trim();
    const key = normalizeCardText(item);
    if (!item || !key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    items.push(item);
  }

  return items;
}

type PracticeVerificationMode = "file" | "manual";

type ManualPracticeVerificationCopy = {
  tryNote: string;
  verifyNote: string;
  shortcut: string;
  composerHint: string;
  fallbackHint: string;
};

const manualPracticeFallbackCopy: Record<ComposerLanguage, ManualPracticeVerificationCopy> = {
  "zh-CN": {
    tryNote: "\u5148\u5199\u51fa\u4e00\u6761\u6700\u5c0f\u89e3\u91ca\u3001\u4f8b\u5b50\u6216\u7ed3\u679c\u3002",
    verifyNote: "\u6307\u51fa\u7528\u6765\u8bc1\u660e\u8fd9\u5f20\u5361\u7684\u5177\u4f53\u4f8b\u5b50\u3001\u7247\u6bb5\u6216\u89e3\u91ca\u3002",
    shortcut: "\u68c0\u67e5\u8bc1\u636e\u548c\u89e3\u91ca",
    composerHint: "\u7528\u4e0b\u65b9\u8f93\u5165\u6846\u8bb0\u5f55\u5df2\u9a8c\u8bc1\u7684\u7ed3\u679c\u6216\u5f53\u524d\u5361\u70b9\u3002",
    fallbackHint: "\u5361\u4f4f\u65f6\uff0c\u5148\u628a\u8303\u56f4\u7f29\u56de\u4e00\u4e2a\u5c0f\u4f8b\u5b50\u3002",
  },
  "en-US": {
    tryNote: "Land one small explanation, example, or result first.",
    verifyNote: "Point to the exact example, excerpt, or explanation that proves this card.",
    shortcut: "Check evidence and explanation",
    composerHint: "Use the composer below to record the verified result or the current blocker.",
    fallbackHint: "If blocked, shrink the scope back to one minimum example.",
  },
  "es-ES": {
    tryNote: "Empieza con una explicaci\u00f3n, un ejemplo o un resultado peque\u00f1o.",
    verifyNote: "Se\u00f1ala el ejemplo, fragmento o explicaci\u00f3n exactos que prueban esta tarjeta.",
    shortcut: "Comprueba la evidencia y la explicaci\u00f3n",
    composerHint: "Usa el campo de abajo para registrar el resultado verificado o el bloqueo actual.",
    fallbackHint: "Si te bloqueas, reduce el alcance a un ejemplo peque\u00f1o.",
  },
  "fr-FR": {
    tryNote: "Commencez par une petite explication, un exemple ou un r\u00e9sultat.",
    verifyNote: "Indiquez l'exemple, l'extrait ou l'explication pr\u00e9cis qui prouve cette carte.",
    shortcut: "V\u00e9rifier la preuve et l'explication",
    composerHint: "Utilisez le champ ci-dessous pour noter le r\u00e9sultat v\u00e9rifi\u00e9 ou le blocage actuel.",
    fallbackHint: "En cas de blocage, r\u00e9duisez le p\u00e9rim\u00e8tre \u00e0 un petit exemple.",
  },
  "de-DE": {
    tryNote: "Beginne mit einer kleinen Erkl\u00e4rung, einem Beispiel oder einem Ergebnis.",
    verifyNote: "Nenne das genaue Beispiel, den Ausschnitt oder die Erkl\u00e4rung, die diese Karte belegt.",
    shortcut: "Beleg und Erkl\u00e4rung pr\u00fcfen",
    composerHint: "Halte im Eingabefeld unten das verifizierte Ergebnis oder den aktuellen Blocker fest.",
    fallbackHint: "Wenn du feststeckst, beschr\u00e4nke den Umfang auf ein kleines Beispiel.",
  },
  "ja-JP": {
    tryNote: "\u5c0f\u3055\u306a\u8aac\u660e\u3001\u4f8b\u3001\u7d50\u679c\u3092\u4e00\u3064\u66f8\u304f\u3068\u3053\u308d\u304b\u3089\u59cb\u3081\u307e\u3059\u3002",
    verifyNote: "\u3053\u306e\u30ab\u30fc\u30c9\u3092\u88cf\u4ed8\u3051\u308b\u5177\u4f53\u7684\u306a\u4f8b\u3001\u629c\u7c8b\u3001\u8aac\u660e\u3092\u793a\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    shortcut: "\u8a3c\u62e0\u3068\u8aac\u660e\u3092\u78ba\u8a8d",
    composerHint: "\u4e0b\u306e\u5165\u529b\u6b04\u306b\u3001\u78ba\u8a8d\u3067\u304d\u305f\u7d50\u679c\u307e\u305f\u306f\u73fe\u5728\u306e\u8a70\u307e\u308a\u3092\u8a18\u9332\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    fallbackHint: "\u8a70\u307e\u3063\u305f\u3089\u3001\u7bc4\u56f2\u3092\u5c0f\u3055\u306a\u4f8b\u4e00\u3064\u307e\u3067\u7d5e\u308a\u8fbc\u3093\u3067\u304f\u3060\u3055\u3044\u3002",
  },
  "ko-KR": {
    tryNote: "\uc9e7\uc740 \uc124\uba85, \uc608\uc2dc \ub610\ub294 \uacb0\uacfc \ud558\ub098\ubd80\ud130 \uc2dc\uc791\ud558\uc138\uc694.",
    verifyNote: "\uc774 \uce74\ub4dc\ub97c \uc99d\uba85\ud558\ub294 \uad6c\uccb4\uc801\uc778 \uc608\uc2dc, \ubc1c\ucdcc \ub610\ub294 \uc124\uba85\uc744 \uc9c0\ubaa9\ud558\uc138\uc694.",
    shortcut: "\uc99d\uac70\uc640 \uc124\uba85 \ud655\uc778",
    composerHint: "\uc544\ub798 \uc785\ub825\ucc3d\uc5d0 \ud655\uc778\ud55c \uacb0\uacfc\ub098 \ud604\uc7ac \ub9c9\ud78c \uc9c0\uc810\uc744 \uae30\ub85d\ud558\uc138\uc694.",
    fallbackHint: "\ub9c9\ud788\uba74 \ubc94\uc704\ub97c \uc791\uc740 \uc608\uc2dc \ud558\ub098\ub85c \uc904\uc774\uc138\uc694.",
  },
  "pt-BR": {
    tryNote: "Comece com uma explica\u00e7\u00e3o, um exemplo ou um resultado pequeno.",
    verifyNote: "Aponte o exemplo, trecho ou explica\u00e7\u00e3o exatos que comprovam este cart\u00e3o.",
    shortcut: "Verificar evid\u00eancia e explica\u00e7\u00e3o",
    composerHint: "Use o campo abaixo para registrar o resultado verificado ou o bloqueio atual.",
    fallbackHint: "Se travar, reduza o escopo a um exemplo pequeno.",
  },
};

/** §十五: per-subtype manual-practice copy in eight languages (no zh/en binary). */
type ManualPracticeSubtypeCopyKey = "derivation" | "writing" | "memorization" | "reading" | "default";

const manualPracticeSubtypeCopy: Record<
  ManualPracticeSubtypeCopyKey,
  Record<ComposerLanguage, ManualPracticeVerificationCopy>
> = {
  derivation: {
    "zh-CN": {
      tryNote: "先写出一个最小可检查的推导步骤。",
      verifyNote: "逐行检查关键步骤，或把结果代回去确认它成立。",
      shortcut: "检查关键步骤",
      composerHint: "用下方输入框写出这一步怎么成立，或指出卡住的具体行。",
      fallbackHint: "卡住时先退回到第一条你能证明的步骤。",
    },
    "en-US": {
      tryNote: "Land one small derivation step you can inspect.",
      verifyNote: "Check the key step line by line, or substitute it back to confirm it holds.",
      shortcut: "Check the key step",
      composerHint: "Use the composer below to explain why the step holds, or name the exact line that is blocked.",
      fallbackHint: "If blocked, return to the first step you can prove.",
    },
    "es-ES": {
      tryNote: "Aterriza un paso de derivación pequeño que puedas inspeccionar.",
      verifyNote: "Comprueba el paso clave línea por línea, o sustituye el resultado para confirmar que se sostiene.",
      shortcut: "Comprueba el paso clave",
      composerHint: "Usa el campo de abajo para explicar por qué se sostiene el paso o señala la línea exacta bloqueada.",
      fallbackHint: "Si te bloqueas, vuelve al primer paso que puedas demostrar.",
    },
    "fr-FR": {
      tryNote: "Posez une petite étape de dérivation que vous pouvez inspecter.",
      verifyNote: "Vérifiez l'étape clé ligne par ligne, ou réinjectez le résultat pour confirmer qu'il tient.",
      shortcut: "Vérifier l'étape clé",
      composerHint: "Utilisez le champ ci-dessous pour expliquer pourquoi l'étape tient, ou nommez la ligne exacte bloquée.",
      fallbackHint: "En cas de blocage, revenez à la première étape que vous pouvez prouver.",
    },
    "de-DE": {
      tryNote: "Landiere einen kleinen, überprüfbaren Herleitungsschritt.",
      verifyNote: "Prüfe den Schlüsselschritt Zeile für Zeile oder setze das Ergebnis ein, um zu bestätigen, dass es hält.",
      shortcut: "Schlüsselschritt prüfen",
      composerHint: "Erkläre im Eingabefeld unten, warum der Schritt hält, oder nenne die genaue Zeile, an der es hakt.",
      fallbackHint: "Wenn du feststeckst, kehre zum ersten Schritt zurück, den du beweisen kannst.",
    },
    "ja-JP": {
      tryNote: "検証できる小さな導出ステップを一つ書きましょう。",
      verifyNote: "重要なステップを一行ずつ確認するか、結果を代入して成り立つか確かめましょう。",
      shortcut: "重要ステップを確認",
      composerHint: "下の入力欄で、このステップがなぜ成り立つかを説明するか、詰まっている行を具体的に示しましょう。",
      fallbackHint: "詰まったら、証明できる最初のステップに戻りましょう。",
    },
    "ko-KR": {
      tryNote: "확인할 수 있는 작은 유도 단계를 하나 쓰세요.",
      verifyNote: "핵심 단계를 한 줄씩 확인하거나 결과를 다시 대입해 성립하는지 확인하세요.",
      shortcut: "핵심 단계 확인",
      composerHint: "아래 입력창에 이 단계가 왜 성립하는지 설명하거나 막힌 정확한 줄을 짚으세요.",
      fallbackHint: "막히면 증명할 수 있는 첫 단계로 돌아가세요.",
    },
    "pt-BR": {
      tryNote: "Entregue um passo de derivação pequeno que você possa inspecionar.",
      verifyNote: "Confira o passo-chave linha por linha, ou substitua o resultado de volta para confirmar que vale.",
      shortcut: "Confira o passo-chave",
      composerHint: "Use o campo abaixo para explicar por que o passo vale, ou aponte a linha exata que está travando.",
      fallbackHint: "Se travar, volte ao primeiro passo que você consegue provar.",
    },
  },
  writing: {
    "zh-CN": {
      tryNote: "先写出一个最小的改写、对比或解释。",
      verifyNote: "对照原句和你的判断，说明为什么这个表达更合适。",
      shortcut: "检查句子和判断",
      composerHint: "用下方输入框写出你的语言选择，或指出目前还说不清的地方。",
      fallbackHint: "卡住时把范围缩回一个句子或一个对比。",
    },
    "en-US": {
      tryNote: "Land one short rewrite, comparison, or explanation.",
      verifyNote: "Compare the exact phrase against your judgment and explain why it fits better.",
      shortcut: "Check the sentence and judgment",
      composerHint: "Use the composer below to state the language choice, or name what is still unclear.",
      fallbackHint: "If blocked, shrink the scope back to one sentence or one contrast.",
    },
    "es-ES": {
      tryNote: "Aterriza una reescritura, comparación o explicación breve.",
      verifyNote: "Compara la frase exacta con tu criterio y explica por qué encaja mejor.",
      shortcut: "Comprueba la frase y el criterio",
      composerHint: "Usa el campo de abajo para indicar tu elección de lenguaje o señalar qué aún no tienes claro.",
      fallbackHint: "Si te bloqueas, reduce el alcance a una frase o una comparación.",
    },
    "fr-FR": {
      tryNote: "Posez une reformulation, une comparaison ou une explication courte.",
      verifyNote: "Comparez la formule exacte à votre jugement et expliquez pourquoi elle convient mieux.",
      shortcut: "Vérifier la phrase et le jugement",
      composerHint: "Utilisez le champ ci-dessous pour donner votre choix de formulation ou nommer ce qui reste flou.",
      fallbackHint: "En cas de blocage, ramenez le périmètre à une phrase ou une comparaison.",
    },
    "de-DE": {
      tryNote: "Liefere eine kurze Umformulierung, einen Vergleich oder eine Erklärung.",
      verifyNote: "Gleiche die genaue Formulierung mit deinem Urteil ab und erkläre, warum sie besser passt.",
      shortcut: "Satz und Urteil prüfen",
      composerHint: "Trage im Eingabefeld unten deine Sprachwahl nach oder benenne, was noch unklar ist.",
      fallbackHint: "Wenn du feststeckst, verenge den Umfang auf einen Satz oder einen Kontrast.",
    },
    "ja-JP": {
      tryNote: "短い書き直し・比較・説明を一つ書きましょう。",
      verifyNote: "元の文と自分の判断を突き合わせて、なぜその表現がより適切か説明しましょう。",
      shortcut: "文と判断を確認",
      composerHint: "下の入力欄に言葉の選択を書くか、まだはっきり言えない部分を示しましょう。",
      fallbackHint: "詰まったら、範囲を一つの文か一つの対比まで絞りましょう。",
    },
    "ko-KR": {
      tryNote: "짧은 고쳐 쓰기, 비교 또는 설명을 하나 쓰세요.",
      verifyNote: "원래 문장과 판단을 견주어 그 표현이 왜 더 적합한지 설명하세요.",
      shortcut: "문장과 판단 확인",
      composerHint: "아래 입력창에 표현 선택을 적거나 아직 명확하지 않은 부분을 짚으세요.",
      fallbackHint: "막히면 범위를 한 문장이나 한 비교로 줄이세요.",
    },
    "pt-BR": {
      tryNote: "Entregue uma reescrita, comparação ou explicação curta.",
      verifyNote: "Compare a frase exata com o seu julgamento e explique por que ela fica melhor.",
      shortcut: "Confira a frase e o julgamento",
      composerHint: "Use o campo abaixo para registrar sua escolha de linguagem ou apontar o que ainda não está claro.",
      fallbackHint: "Se travar, reduza o escopo a uma frase ou um contraste.",
    },
  },
  memorization: {
    "zh-CN": {
      tryNote: "先完成一轮最小闭卷回忆。",
      verifyNote: "先回忆，再打开资料核对，标出真正漏掉的点。",
      shortcut: "回忆后核对",
      composerHint: "用下方输入框记录你记住了什么、漏掉了什么，或哪一组还会混淆。",
      fallbackHint: "卡住时把这组内容缩回两个点和一个对比。",
    },
    "en-US": {
      tryNote: "Complete one tiny closed-book recall first.",
      verifyNote: "Recall first, then reopen the source and mark the real gap.",
      shortcut: "Recall, then check",
      composerHint: "Use the composer below to record what you recalled, missed, or still confuse.",
      fallbackHint: "If blocked, shrink the cluster back to two points and one contrast.",
    },
    "es-ES": {
      tryNote: "Completa primero un recuerdo breve sin consultar nada.",
      verifyNote: "Recuerda primero, reabre la fuente y marca lo que de verdad faltó.",
      shortcut: "Recordar y comprobar",
      composerHint: "Usa el campo de abajo para registrar qué recordaste, qué faltó o qué grupo aún confundes.",
      fallbackHint: "Si te bloqueas, reduce el grupo a dos puntos y una comparación.",
    },
    "fr-FR": {
      tryNote: "Faites d'abord un petit rappel de mémoire, sans support.",
      verifyNote: "Rappelez d'abord, rouvrez la source et marquez ce qui manque vraiment.",
      shortcut: "Rappel, puis vérification",
      composerHint: "Utilisez le champ ci-dessous pour noter ce que vous avez rappelé, manqué ou confondu.",
      fallbackHint: "En cas de blocage, ramenez le groupe à deux points et une comparaison.",
    },
    "de-DE": {
      tryNote: "Mache zuerst eine kleine Abfrage ohne Unterlagen.",
      verifyNote: "Erinnere zuerst, öffne dann die Quelle und markiere die echte Lücke.",
      shortcut: "Erst erinnern, dann prüfen",
      composerHint: "Halte im Eingabefeld unten fest, was du erinnert hast, was fehlte und was du noch verwechselst.",
      fallbackHint: "Wenn du feststeckst, schrumpfe den Haufen auf zwei Punkte und einen Kontrast.",
    },
    "ja-JP": {
      tryNote: "まず小さなクローズドブックの想起を一回やりましょう。",
      verifyNote: "先に思い出してから資料を開いて照合し、本当に抜けている点を印をつけましょう。",
      shortcut: "想起してから照合",
      composerHint: "下の入力欄に、覚えていたこと・抜けていたこと・まだ混同するグループを記録しましょう。",
      fallbackHint: "詰まったら、このグループを2つのポイントと1つの対比まで縮めましょう。",
    },
    "ko-KR": {
      tryNote: "먼저 아주 작은 책 없이 회상을 한 번 해보세요.",
      verifyNote: "먼저 회상한 뒤 자료를 다시 열어 진짜 빠진 부분을 표시하세요.",
      shortcut: "회상 후 확인",
      composerHint: "아래 입력창에 기억한 것, 놓친 것, 아직 헷갈리는 묶음을 기록하세요.",
      fallbackHint: "막히면 묶음을 두 포인트와 하나의 대비로 줄이세요.",
    },
    "pt-BR": {
      tryNote: "Complete primeiro uma lembrança pequena de cabeça.",
      verifyNote: "Lembre primeiro, reabra a fonte e marque o que realmente faltou.",
      shortcut: "Lembrar e conferir",
      composerHint: "Use o campo abaixo para registrar o que lembrou, o que faltou ou o que ainda confunde.",
      fallbackHint: "Se travar, reduza o grupo a dois pontos e um contraste.",
    },
  },
  reading: {
    "zh-CN": {
      tryNote: "先写下一条窄判断和一条支撑它的证据。",
      verifyNote: "指出具体片段，并解释它为什么真的支撑这个判断。",
      shortcut: "检查片段和判断",
      composerHint: "用下方输入框写出你的判断和证据，或指出目前最不够扎实的那一处。",
      fallbackHint: "卡住时只保留一个句子、一个意象或一个场景。",
    },
    "en-US": {
      tryNote: "Write one narrow claim and one piece of evidence first.",
      verifyNote: "Point to the exact excerpt and explain why it really supports the claim.",
      shortcut: "Check the excerpt and claim",
      composerHint: "Use the composer below to write the claim and evidence, or name the weakest point.",
      fallbackHint: "If blocked, shrink the scope to one sentence, image, or scene.",
    },
    "es-ES": {
      tryNote: "Escribe primero una afirmación estrecha y una evidencia que la respalde.",
      verifyNote: "Señala el fragmento exacto y explica por qué de verdad respalda la afirmación.",
      shortcut: "Comprueba el fragmento y la afirmación",
      composerHint: "Usa el campo de abajo para escribir la afirmación y la evidencia, o señala el punto más débil.",
      fallbackHint: "Si te bloqueas, quédate con una sola frase, una imagen o una escena.",
    },
    "fr-FR": {
      tryNote: "Écrivez d'abord un jugement étroit et une preuve qui l'appuie.",
      verifyNote: "Désignez l'extrait exact et expliquez pourquoi il soutient vraiment le jugement.",
      shortcut: "Vérifier l'extrait et le jugement",
      composerHint: "Utilisez le champ ci-dessous pour écrire le jugement et la preuve, ou nommez le point le plus fragile.",
      fallbackHint: "En cas de blocage, gardez une seule phrase, une image ou une scène.",
    },
    "de-DE": {
      tryNote: "Schreibe zuerst eine schmale Behauptung und einen Beleg dazu.",
      verifyNote: "Zeige die genaue Stelle und erkläre, warum sie die Behauptung wirklich stützt.",
      shortcut: "Ausschnitt und Behauptung prüfen",
      composerHint: "Schreibe im Eingabefeld unten Behauptung und Beleg, oder benenne den wackeligsten Punkt.",
      fallbackHint: "Wenn du feststeckst, behalte nur einen Satz, ein Bild oder eine Szene.",
    },
    "ja-JP": {
      tryNote: "まず狭い主張と、それを支える根拠を一つ書きましょう。",
      verifyNote: "具体的な一節を示し、なぜそれが主張を本当に支えるのか説明しましょう。",
      shortcut: "一節と主張を確認",
      composerHint: "下の入力欄に主張と根拠を書くか、今一番頼りない部分を指しましょう。",
      fallbackHint: "詰まったら、一つの文・イメージ・場面だけを残しましょう。",
    },
    "ko-KR": {
      tryNote: "먼저 좁은 주장 하나와 이를 뒷받침하는 근거 하나를 쓰세요.",
      verifyNote: "정확한 구절을 짚고, 왜 그것이 주장을 정말 뒷받침하는지 설명하세요.",
      shortcut: "구절과 주장 확인",
      composerHint: "아래 입력창에 주장과 근거를 적거나 가장 아직 못박은 부분을 짚으세요.",
      fallbackHint: "막히면 한 문장, 한 이미지, 한 장면만 남기세요.",
    },
    "pt-BR": {
      tryNote: "Escreva primeiro uma afirmação estreita e uma evidência que a sustente.",
      verifyNote: "Aponte o trecho exato e explique por que ele realmente sustenta a afirmação.",
      shortcut: "Confira o trecho e a afirmação",
      composerHint: "Use o campo abaixo para escrever a afirmação e a evidência, ou aponte o ponto mais frágil.",
      fallbackHint: "Se travar, guarde apenas uma frase, uma imagem ou uma cena.",
    },
  },
  default: {
    "zh-CN": {
      tryNote: "先落下一条最小解释、例子或结果。",
      verifyNote: "指出你用来证明这张卡的那个例子、片段或解释。",
      shortcut: "检查证据和解释",
      composerHint: "用下方输入框记录你已验证的结果，或指出当前 blocker。",
      fallbackHint: "卡住时先把范围缩回一个最小例子。",
    },
    "en-US": {
      tryNote: "Land one small explanation, example, or result first.",
      verifyNote: "Point to the exact example, excerpt, or explanation that proves this card.",
      shortcut: "Check evidence and explanation",
      composerHint: "Use the composer below to record the verified result or the current blocker.",
      fallbackHint: "If blocked, shrink the scope back to one minimum example.",
    },
    // Other locales share the generic fallback copy on the untyped default lane.
    "es-ES": manualPracticeFallbackCopy["es-ES"],
    "fr-FR": manualPracticeFallbackCopy["fr-FR"],
    "de-DE": manualPracticeFallbackCopy["de-DE"],
    "ja-JP": manualPracticeFallbackCopy["ja-JP"],
    "ko-KR": manualPracticeFallbackCopy["ko-KR"],
    "pt-BR": manualPracticeFallbackCopy["pt-BR"],
  },
};

function resolvePracticeVerificationMode(input: {
  isFlashCard: boolean;
  learningFamily?: "code" | "theory";
  filesToTouch: string[];
  apiHints: string[];
  expectedSymbols: string[];
}): PracticeVerificationMode {
  if (input.isFlashCard) {
    return "manual";
  }
  if (input.learningFamily === "code") {
    return "file";
  }
  if (input.learningFamily === "theory") {
    return "manual";
  }
  return input.filesToTouch.length > 0 || input.apiHints.length > 0 || input.expectedSymbols.length > 0
    ? "file"
    : "manual";
}

function resolveManualPracticeVerificationCopy(
  language: ComposerLanguage,
  subtype: string | undefined,
): ManualPracticeVerificationCopy {
  const normalizedSubtype = (subtype ?? "").trim().toLowerCase();
  if (normalizedSubtype === "derivation") {
    return manualPracticeSubtypeCopy.derivation[language] ?? manualPracticeSubtypeCopy.derivation["en-US"];
  }
  if (normalizedSubtype === "writing") {
    return manualPracticeSubtypeCopy.writing[language] ?? manualPracticeSubtypeCopy.writing["en-US"];
  }
  if (normalizedSubtype === "memorization") {
    return (
      manualPracticeSubtypeCopy.memorization[language] ?? manualPracticeSubtypeCopy.memorization["en-US"]
    );
  }
  if (normalizedSubtype === "reading") {
    return manualPracticeSubtypeCopy.reading[language] ?? manualPracticeSubtypeCopy.reading["en-US"];
  }
  if (language !== "zh-CN" && language !== "en-US") {
    return manualPracticeFallbackCopy[language] ?? manualPracticeFallbackCopy["en-US"];
  }
  return manualPracticeSubtypeCopy.default[language] ?? manualPracticeSubtypeCopy.default["en-US"];
}

type TrainingLoopStepKey = "learn" | "try" | "verify" | "reflect" | "return";
type TrainingLoopStepState = "done" | "active" | "upcoming";

interface TrainingLoopStep {
  key: TrainingLoopStepKey;
  label: string;
  state: TrainingLoopStepState;
}

function trainingLoopStepLabel(step: TrainingLoopStepKey, language: ComposerLanguage): string {
  const labels: Record<ComposerLanguage, Record<TrainingLoopStepKey, string>> = {
    "zh-CN": { learn: "\u5b66\u4e60", try: "\u52a8\u624b", verify: "\u9a8c\u8bc1", reflect: "\u590d\u76d8", return: "\u56de\u6d41" },
    "en-US": { learn: "Learn", try: "Try", verify: "Verify", reflect: "Reflect", return: "Return" },
    "es-ES": { learn: "Aprender", try: "Intentar", verify: "Verificar", reflect: "Reflexionar", return: "Volver" },
    "fr-FR": { learn: "Apprendre", try: "Essayer", verify: "Verifier", reflect: "Reflechir", return: "Retour" },
    "de-DE": { learn: "Lernen", try: "Probieren", verify: "Prüfen", reflect: "Reflektieren", return: "Zurück" },
    "ja-JP": { learn: "\u5b66\u3076", try: "\u8a66\u3059", verify: "\u691c\u8a3c", reflect: "\u632f\u308a\u8fd4\u308b", return: "\u623b\u308b" },
    "ko-KR": { learn: "\ud559\uc2b5", try: "\uc2dc\ub3c4", verify: "\uac80\uc99d", reflect: "\ud68c\uace0", return: "\ub3cc\uc544\uac00\uae30" },
    "pt-BR": { learn: "Aprender", try: "Tentar", verify: "Verificar", reflect: "Refletir", return: "Retornar" },
  };
  return labels[language]?.[step] ?? labels["en-US"][step];
}

type TrainingSurfaceLabelKey =
  | "currentCard"
  | "flash"
  | "practice"
  | "primer"
  | "review"
  | "scenario"
  | "transfer"
  | "theory"
  | "code"
  | "requirements"
  | "currentTrainingCard"
  | "trainingLoop"
  | "codeSymbols"
  | "checks"
  | "startStep"
  | "verifyCurrentFile"
  | "verifyStepTitle";

const trainingSurfaceLabels: Record<
  ComposerLanguage,
  Record<TrainingSurfaceLabelKey, string>
> = {
  "zh-CN": {
    currentCard: "当前卡片", flash: "闪记", practice: "实战", primer: "学习", review: "复盘",
    scenario: "场景", transfer: "迁移", theory: "理论", code: "代码", requirements: "具体要求",
    currentTrainingCard: "当前训练卡片", trainingLoop: "学习循环", codeSymbols: "将检查的代码符号", checks: "检查", startStep: "开始这一步", verifyCurrentFile: "验证当前文件", verifyStepTitle: "做完这一步，验证一下结果",
  },
  "en-US": {
    currentCard: "Current card", flash: "Flash", practice: "Practice", primer: "Primer", review: "Review",
    scenario: "Scenario", transfer: "Transfer", theory: "Theory", code: "Code", requirements: "Requirements",
    currentTrainingCard: "Current training card", trainingLoop: "Training loop", codeSymbols: "Code symbols to check", checks: "Checks", startStep: "Start this step", verifyCurrentFile: "Verify current file", verifyStepTitle: "Done with the step? Verify the result",
  },
  "es-ES": {
    currentCard: "Tarjeta actual", flash: "Tarjeta", practice: "Práctica", primer: "Base", review: "Repaso",
    scenario: "Escenario", transfer: "Transferencia", theory: "Teoría", code: "Código", requirements: "Requisitos",
    currentTrainingCard: "Tarjeta de entrenamiento actual", trainingLoop: "Ciclo de aprendizaje", codeSymbols: "Símbolos de código a comprobar", checks: "Comprobaciones", startStep: "Comenzar este paso", verifyCurrentFile: "Verificar archivo actual", verifyStepTitle: "¿Terminaste el paso? Comprueba el resultado",
  },
  "fr-FR": {
    currentCard: "Carte actuelle", flash: "Carte", practice: "Exercice", primer: "Base", review: "Révision",
    scenario: "Scénario", transfer: "Transfert", theory: "Théorie", code: "Code", requirements: "Exigences",
    currentTrainingCard: "Carte d'entraînement actuelle", trainingLoop: "Boucle d'apprentissage", codeSymbols: "Symboles de code à vérifier", checks: "Vérifications", startStep: "Commencer cette étape", verifyCurrentFile: "Vérifier le fichier actuel", verifyStepTitle: "Étape terminée ? Vérifiez le résultat",
  },
  "de-DE": {
    currentCard: "Aktuelle Karte", flash: "Karte", practice: "Übung", primer: "Grundlage", review: "Wiederholung",
    scenario: "Szenario", transfer: "Transfer", theory: "Theorie", code: "Code", requirements: "Anforderungen",
    currentTrainingCard: "Aktuelle Trainingskarte", trainingLoop: "Lernzyklus", codeSymbols: "Zu prüfende Codesymbole", checks: "Prüfungen", startStep: "Diesen Schritt starten", verifyCurrentFile: "Aktuelle Datei prüfen", verifyStepTitle: "Schritt geschafft? Prüfe das Ergebnis",
  },
  "ja-JP": {
    currentCard: "現在のカード", flash: "カード", practice: "練習", primer: "導入", review: "復習",
    scenario: "場面", transfer: "転移", theory: "理論", code: "コード", requirements: "要件",
    currentTrainingCard: "現在のトレーニングカード", trainingLoop: "学習サイクル", codeSymbols: "確認するコードシンボル", checks: "確認", startStep: "このステップを開始", verifyCurrentFile: "現在のファイルを検証", verifyStepTitle: "このステップができたら、結果を検証しましょう",
  },
  "ko-KR": {
    currentCard: "현재 카드", flash: "카드", practice: "연습", primer: "기초", review: "복습",
    scenario: "시나리오", transfer: "전이", theory: "이론", code: "코드", requirements: "요구 사항",
    currentTrainingCard: "현재 훈련 카드", trainingLoop: "학습 순환", codeSymbols: "확인할 코드 기호", checks: "확인", startStep: "이 단계 시작", verifyCurrentFile: "현재 파일 검증", verifyStepTitle: "이 단계를 마쳤다면 결과를 검증해 보세요",
  },
  "pt-BR": {
    currentCard: "Cartão atual", flash: "Cartão", practice: "Prática", primer: "Base", review: "Revisão",
    scenario: "Cenário", transfer: "Transferência", theory: "Teoria", code: "Código", requirements: "Requisitos",
    currentTrainingCard: "Cartão de treinamento atual", trainingLoop: "Ciclo de aprendizagem", codeSymbols: "Símbolos de código para verificar", checks: "Verificações", startStep: "Iniciar esta etapa", verifyCurrentFile: "Verificar arquivo atual", verifyStepTitle: "Terminou a etapa? Verifique o resultado",
  },
};

function trainingSurfaceLabel(language: ComposerLanguage, key: TrainingSurfaceLabelKey): string {
  return trainingSurfaceLabels[language]?.[key] ?? trainingSurfaceLabels["en-US"][key];
}

type TrainingCardOnlySurfaceCopyKey =
  | "flashAnswerMethod"
  | "currentFileDiagnostics"
  | "smallestDeliverable"
  | "returnResultOrBlocker"
  | "afterThis";

const trainingCardOnlySurfaceCopy: Record<
  ComposerLanguage,
  Record<TrainingCardOnlySurfaceCopyKey, string>
> = {
  "zh-CN": {
    flashAnswerMethod: "\u9009\u62e9 / \u586b\u7a7a / \u7b80\u7b54",
    currentFileDiagnostics: "\u5f53\u524d IDE \u6587\u4ef6\u548c\u8bca\u65ad",
    smallestDeliverable: "\u6700\u5c0f\u53ef\u4ea4\u4ed8\u7ed3\u679c",
    returnResultOrBlocker: "\u5e26\u56de\u7ed3\u679c\u6216\u5361\u70b9\u3002",
    afterThis: "\u5b8c\u6210\u540e",
  },
  "en-US": {
    flashAnswerMethod: "Choice / fill / short answer",
    currentFileDiagnostics: "Current IDE file + diagnostics",
    smallestDeliverable: "Smallest deliverable",
    returnResultOrBlocker: "Return result or blocker.",
    afterThis: "After this",
  },
  "es-ES": {
    flashAnswerMethod: "Opci\u00f3n / completar / respuesta corta",
    currentFileDiagnostics: "Archivo actual del IDE y diagn\u00f3sticos",
    smallestDeliverable: "Resultado entregable m\u00ednimo",
    returnResultOrBlocker: "Lleva de vuelta el resultado o el bloqueo.",
    afterThis: "Despu\u00e9s de esto",
  },
  "fr-FR": {
    flashAnswerMethod: "Choix / texte \u00e0 trous / r\u00e9ponse courte",
    currentFileDiagnostics: "Fichier IDE actuel et diagnostics",
    smallestDeliverable: "Plus petit r\u00e9sultat livrable",
    returnResultOrBlocker: "Rapportez le r\u00e9sultat ou le blocage.",
    afterThis: "Apr\u00e8s cela",
  },
  "de-DE": {
    flashAnswerMethod: "Auswahl / L\u00fcckentext / Kurzantwort",
    currentFileDiagnostics: "Aktuelle IDE-Datei und Diagnosen",
    smallestDeliverable: "Kleinstes lieferbares Ergebnis",
    returnResultOrBlocker: "Bringe Ergebnis oder Blocker zur\u00fcck.",
    afterThis: "Danach",
  },
  "ja-JP": {
    flashAnswerMethod: "\u9078\u629e / \u7a74\u57cb\u3081 / \u77ed\u7b54",
    currentFileDiagnostics: "\u73fe\u5728\u306e IDE \u30d5\u30a1\u30a4\u30eb\u3068\u8a3a\u65ad",
    smallestDeliverable: "\u6700\u5c0f\u306e\u6210\u679c\u7269",
    returnResultOrBlocker: "\u7d50\u679c\u307e\u305f\u306f\u8a70\u307e\u308a\u3092\u6301\u3061\u5e30\u308b\u3002",
    afterThis: "\u3053\u306e\u5f8c",
  },
  "ko-KR": {
    flashAnswerMethod: "\uc120\ud0dd / \ube48\uce78 \ucc44\uc6b0\uae30 / \uc9e7\uc740 \ub2f5",
    currentFileDiagnostics: "\ud604\uc7ac IDE \ud30c\uc77c\uacfc \uc9c4\ub2e8",
    smallestDeliverable: "\ucd5c\uc18c \uc81c\ucd9c\ubb3c",
    returnResultOrBlocker: "\uacb0\uacfc \ub610\ub294 \ub9c9\ud78c \uc9c0\uc810\uc744 \uac00\uc838\uc624\uc138\uc694.",
    afterThis: "\uc644\ub8cc \ud6c4",
  },
  "pt-BR": {
    flashAnswerMethod: "Escolha / lacuna / resposta curta",
    currentFileDiagnostics: "Arquivo atual do IDE e diagn\u00f3sticos",
    smallestDeliverable: "Menor resultado entreg\u00e1vel",
    returnResultOrBlocker: "Leve o resultado ou o bloqueio de volta.",
    afterThis: "Depois disso",
  },
};

function trainingCardOnlySurfaceText(
  language: ComposerLanguage,
  key: TrainingCardOnlySurfaceCopyKey,
): string {
  return trainingCardOnlySurfaceCopy[language]?.[key] ?? trainingCardOnlySurfaceCopy["en-US"][key];
}

type TrainingCardOnlyCopyKey = "learnFirst" | "whyNow";

const trainingCardOnlyCopy: Record<ComposerLanguage, Record<TrainingCardOnlyCopyKey, string>> = {
  "zh-CN": {
    learnFirst: "\u5148\u7406\u89e3\u8fd9\u5f20\u5361\u7684\u5bf9\u8c61\u548c\u8fb9\u754c\uff0c\u518d\u5f00\u59cb\u6700\u5c0f\u7684\u4e00\u6b65\u3002",
    whyNow: "\u8fd9\u662f\u5f53\u524d\u4e3b\u7ebf\u7684\u4e0b\u4e00\u6b65\u3002",
  },
  "en-US": {
    learnFirst: "Understand the object and boundary before the smallest move.",
    whyNow: "This is the next step in the current thread.",
  },
  "es-ES": {
    learnFirst: "Entiende el objeto y el l\u00edmite antes del paso m\u00e1s peque\u00f1o.",
    whyNow: "Este es el siguiente paso del hilo actual.",
  },
  "fr-FR": {
    learnFirst: "Comprenez l'objet et la limite avant le plus petit geste.",
    whyNow: "C'est la prochaine \u00e9tape du fil actuel.",
  },
  "de-DE": {
    learnFirst: "Verstehe Objekt und Grenze vor dem kleinsten Schritt.",
    whyNow: "Dies ist der n\u00e4chste Schritt im aktuellen Arbeitsfaden.",
  },
  "ja-JP": {
    learnFirst: "\u5bfe\u8c61\u3068\u5883\u754c\u3092\u7406\u89e3\u3057\u3066\u304b\u3089\u3001\u6700\u5c0f\u306e\u4e00\u6b69\u3092\u59cb\u3081\u307e\u3059\u3002",
    whyNow: "\u3053\u308c\u306f\u73fe\u5728\u306e\u5b66\u7fd2\u306e\u6d41\u308c\u306e\u6b21\u306e\u4e00\u6b69\u3067\u3059\u3002",
  },
  "ko-KR": {
    learnFirst: "\uac1d\uccb4\uc640 \uacbd\uacc4\ub97c \uc774\ud574\ud55c \ub4a4 \uac00\uc7a5 \uc791\uc740 \ub2e8\uacc4\ub97c \uc2dc\uc791\ud558\uc138\uc694.",
    whyNow: "\uc774\uac83\uc740 \ud604\uc7ac \ud559\uc2b5 \ud750\ub984\uc758 \ub2e4\uc74c \ub2e8\uacc4\uc785\ub2c8\ub2e4.",
  },
  "pt-BR": {
    learnFirst: "Entenda o objeto e o limite antes do menor passo.",
    whyNow: "Este \u00e9 o pr\u00f3ximo passo do fluxo atual.",
  },
};

function trainingCardOnlyText(language: ComposerLanguage, key: TrainingCardOnlyCopyKey): string {
  return trainingCardOnlyCopy[language]?.[key] ?? trainingCardOnlyCopy["en-US"][key];
}

/** §十五: workbench-surface copy in eight languages (no zh/en binary). */
type TrainingWorkbenchTextKey =
  | "ungrouped"
  | "startHere"
  | "currentScenario"
  | "scenarioPack"
  | "readSliceFirst"
  | "startIn"
  | "apiHint"
  | "apiHintsLabel"
  | "boundary"
  | "ifStuck"
  | "guidanceFallback"
  | "answerNow"
  | "flashCheck"
  | "verifyNow"
  | "practiceVerificationLabel"
  | "verifyFileNoteCardOnly"
  | "verifyFileNote"
  | "studyFirstLabel"
  | "primerLabel"
  | "flashComposerHint"
  | "fileComposerHint"
  | "saveStatus"
  | "flashDeckNext"
  | "flashDeckPractice"
  | "adjustReturnLabel"
  | "adjustReflectLabel"
  | "adjustCarryTitle"
  | "adjustEvidenceTitle"
  | "adjustNarrowTitle"
  | "adjustTightenTitle"
  | "adjustDetailFallback"
  | "adjustReturnNext"
  | "adjustEvidenceNext"
  | "adjustRetestNext"
  | "flashVerificationAria"
  | "choiceFillShort"
  | "readCurrentIdeFile"
  | "mismatchRecoveryReason"
  | "currentTrainingRoute"
  | "studyCuesFirst"
  | "primerCues"
  | "hintsGuardrails"
  | "hintsGuardrailsBody"
  | "verifyLikeThis"
  | "bringBackAfterCompletion"
  | "filesToTouchLabel"
  | "hintLadderLabel"
  | "commonMistakesLabel"
  | "stuckRecoveryLabel"
  | "sourceAndReason"
  | "fullAcceptance"
  | "deliverablesLabel"
  | "acceptanceMethod"
  | "landSmallResultFirst"
  | "returnPath"
  | "followUpReview"
  | "fsrsInterval"
  | "fsrsMastery"
  | "reviewDayUnit"
  | "reviewActions"
  | "reviewAccept"
  | "reviewSnooze"
  | "moreLabel"
  | "reviewReset"
  | "reviewSkip"
  | "reviewDone"
  | "recentWins"
  | "watchOuts"
  | "hintProgressPrefix"
  | "taskDetails"
  | "returnCompleteEyebrow"
  | "returnCompleteTitle"
  | "mismatchCardHint"
  | "mismatchSwitchLabel";

const trainingWorkbenchTextCopy: Record<
  ComposerLanguage,
  Record<TrainingWorkbenchTextKey, string>
> = {
  "zh-CN": {
    ungrouped: "未分组",
    startHere: "先做这一步",
    currentScenario: "当前场景",
    scenarioPack: "场景包",
    readSliceFirst: "先把当前切片读清楚，再进入下面的验证。",
    startIn: "先看",
    apiHint: "API 提示",
    apiHintsLabel: "API 提示",
    boundary: "边界",
    ifStuck: "卡住时",
    guidanceFallback: "展开查看提示、边界和卡住时的恢复路径。",
    answerNow: "现在作答",
    flashCheck: "闪记检查",
    verifyNow: "现在验证",
    practiceVerificationLabel: "实战验证",
    verifyFileNoteCardOnly: "再读取当前文件，按下面的检查项确认它是否成立。",
    verifyFileNote: "从当前文件和诊断判断是否通过。",
    studyFirstLabel: "先看",
    primerLabel: "前置",
    flashComposerHint: "用下方输入框作答，选择列表会出现在输入框上方。",
    fileComposerHint: "先动手，再用下方输入框记录结果或 blocker。真正通过要靠输入框区域里的 Verify current file。",
    saveStatus: "保存状态",
    flashDeckNext: "换一张闪卡",
    flashDeckPractice: "用闪卡练习",
    adjustReturnLabel: "回流",
    adjustReflectLabel: "复盘",
    adjustCarryTitle: "把这次结果带回下一步",
    adjustEvidenceTitle: "先复盘这条证据说明了什么",
    adjustNarrowTitle: "收窄修复，然后再验",
    adjustTightenTitle: "收紧下一步",
    adjustDetailFallback: "先记下这轮学到的边界，再继续往下走。",
    adjustReturnNext: "先记下这条边界，再继续。",
    adjustEvidenceNext: "先在输入框里说清这条证据，再回流。",
    adjustRetestNext: "先做最小改动，然后再验一次。",
    flashVerificationAria: "闪记验证",
    choiceFillShort: "选择 / 填空 / 简答",
    readCurrentIdeFile: "读取 IDE 当前文件",
    mismatchRecoveryReason: "切换到与当前进度一致的卡片",
    currentTrainingRoute: "当前训练路线",
    studyCuesFirst: "先看这些线索",
    primerCues: "前置线索",
    hintsGuardrails: "提示与边界",
    hintsGuardrailsBody: "提示和边界",
    verifyLikeThis: "这样验证",
    bringBackAfterCompletion: "完成后带回",
    filesToTouchLabel: "优先文件",
    hintLadderLabel: "提示阶梯",
    commonMistakesLabel: "常见错误",
    stuckRecoveryLabel: "卡住时怎么恢复",
    sourceAndReason: "来源与原因",
    fullAcceptance: "完整验收",
    deliverablesLabel: "交付物",
    acceptanceMethod: "验收方式",
    landSmallResultFirst: "先拿到一个最小可验证结果，再决定要不要扩展范围。",
    returnPath: "回流去向",
    followUpReview: "后续和回看",
    fsrsInterval: "间隔",
    fsrsMastery: "掌握度",
    reviewDayUnit: "天",
    reviewActions: "复习操作",
    reviewAccept: "开始复习",
    reviewSnooze: "稍后",
    moreLabel: "更多",
    reviewReset: "重置",
    reviewSkip: "跳过",
    reviewDone: "完成",
    recentWins: "最近进步",
    watchOuts: "需要留意",
    hintProgressPrefix: "提示",
    taskDetails: "任务详情",
    returnCompleteEyebrow: "已完成",
    returnCompleteTitle: "结果已带给教练",
    mismatchCardHint: "这张卡与当前进度不一致。",
    mismatchSwitchLabel: "切换到当前卡",
  },
  "en-US": {
    ungrouped: "Ungrouped",
    startHere: "Start here",
    currentScenario: "Current scenario",
    scenarioPack: "Scenario pack",
    readSliceFirst: "Read this slice first, then move into verification.",
    startIn: "Start in",
    apiHint: "API hint",
    apiHintsLabel: "API hints",
    boundary: "Boundary",
    ifStuck: "If stuck",
    guidanceFallback: "Open for hints, boundaries, and recovery.",
    answerNow: "Answer now",
    flashCheck: "Flash check",
    verifyNow: "Verify",
    practiceVerificationLabel: "Practice verification",
    verifyFileNoteCardOnly: "Then read the current file and confirm the checks below.",
    verifyFileNote: "Pass/fail comes from the current file and diagnostics.",
    studyFirstLabel: "Study first",
    primerLabel: "Primer",
    flashComposerHint: "Answer in the composer below. The choice list appears above the input.",
    fileComposerHint: "Try the task first, then use the composer below to record the result or blocker. Real pass/fail still comes from Verify current file.",
    saveStatus: "Save status",
    flashDeckNext: "Next flashcard",
    flashDeckPractice: "Practice with flashcards",
    adjustReturnLabel: "Return",
    adjustReflectLabel: "Reflect",
    adjustCarryTitle: "Carry this result forward",
    adjustEvidenceTitle: "Reflect on what this evidence proves",
    adjustNarrowTitle: "Narrow the fix and test again",
    adjustTightenTitle: "Tighten the next move",
    adjustDetailFallback: "Write down the boundary you learned this round before moving on.",
    adjustReturnNext: "Capture the boundary, then continue.",
    adjustEvidenceNext: "State the evidence in the composer, then return.",
    adjustRetestNext: "Make the smallest change, then retest.",
    flashVerificationAria: "Flash verification",
    choiceFillShort: "Choice / fill / short",
    readCurrentIdeFile: "Read current IDE file",
    mismatchRecoveryReason: "Switch to the card that matches your current progress",
    currentTrainingRoute: "Current training route",
    studyCuesFirst: "Study cues first",
    primerCues: "Primer cues",
    hintsGuardrails: "Hints and guardrails",
    hintsGuardrailsBody: "Hints and guardrails",
    verifyLikeThis: "Verify like this",
    bringBackAfterCompletion: "Bring back after completion",
    filesToTouchLabel: "Files to touch",
    hintLadderLabel: "Hint ladder",
    commonMistakesLabel: "Common mistakes",
    stuckRecoveryLabel: "If you get stuck",
    sourceAndReason: "Source and reason",
    fullAcceptance: "Full acceptance",
    deliverablesLabel: "Deliverables",
    acceptanceMethod: "Acceptance method",
    landSmallResultFirst: "Land one small result first.",
    returnPath: "Return path",
    followUpReview: "Follow-up and review",
    fsrsInterval: "Interval",
    fsrsMastery: "Mastery",
    reviewDayUnit: "days",
    reviewActions: "Review actions",
    reviewAccept: "Start review",
    reviewSnooze: "Later",
    moreLabel: "More",
    reviewReset: "Reset",
    reviewSkip: "Skip",
    reviewDone: "Done",
    recentWins: "Recent wins",
    watchOuts: "Watch-outs",
    hintProgressPrefix: "Hint",
    taskDetails: "Task details",
    returnCompleteEyebrow: "Done",
    returnCompleteTitle: "Your result is with the coach",
    mismatchCardHint: "This card does not match your current progress.",
    mismatchSwitchLabel: "Switch to the current card",
  },
  "es-ES": {
    ungrouped: "Sin agrupar",
    startHere: "Empieza aquí",
    currentScenario: "Escenario actual",
    scenarioPack: "Paquete de escenario",
    readSliceFirst: "Lee primero este fragmento y pasa a la verificación de abajo.",
    startIn: "Empieza en",
    apiHint: "Pista de API",
    apiHintsLabel: "Pistas de API",
    boundary: "Límite",
    ifStuck: "Si te bloqueas",
    guidanceFallback: "Ábrela para ver pistas, límites y la ruta de recuperación.",
    answerNow: "Responder ahora",
    flashCheck: "Comprobación flash",
    verifyNow: "Verificar",
    practiceVerificationLabel: "Verificación de práctica",
    verifyFileNoteCardOnly: "Luego lee el archivo actual y confirma con las comprobaciones de abajo si se cumple.",
    verifyFileNote: "Aprobar o no depende del archivo actual y sus diagnósticos.",
    studyFirstLabel: "Estudia primero",
    primerLabel: "Base",
    flashComposerHint: "Responde en el campo de abajo. La lista de opciones aparece sobre el campo.",
    fileComposerHint: "Inténtalo primero y usa el campo de abajo para registrar el resultado o el bloqueo. La aprobación real sigue viniendo de Verify current file.",
    saveStatus: "Estado del guardado",
    flashDeckNext: "Otra tarjeta flash",
    flashDeckPractice: "Practicar con tarjetas flash",
    adjustReturnLabel: "Volver",
    adjustReflectLabel: "Reflexionar",
    adjustCarryTitle: "Lleva este resultado al siguiente paso",
    adjustEvidenceTitle: "Repasa qué demuestra esta evidencia",
    adjustNarrowTitle: "Reduce el arreglo y verifica otra vez",
    adjustTightenTitle: "Ajusta el siguiente movimiento",
    adjustDetailFallback: "Anota el límite que aprendiste en esta ronda antes de seguir avanzando.",
    adjustReturnNext: "Registra el límite y continúa.",
    adjustEvidenceNext: "Explica esta evidencia en el campo y vuelve al flujo.",
    adjustRetestNext: "Haz el cambio más pequeño y vuelve a probar.",
    flashVerificationAria: "Verificación flash",
    choiceFillShort: "Opción / completar / corta",
    readCurrentIdeFile: "Leer el archivo actual del IDE",
    mismatchRecoveryReason: "Cambiar a la tarjeta que coincide con tu progreso actual",
    currentTrainingRoute: "Ruta de entrenamiento actual",
    studyCuesFirst: "Primero mira estas pistas",
    primerCues: "Pistas previas",
    hintsGuardrails: "Pistas y límites",
    hintsGuardrailsBody: "Pistas y límites",
    verifyLikeThis: "Verifica así",
    bringBackAfterCompletion: "Traer de vuelta al terminar",
    filesToTouchLabel: "Archivos prioritarios",
    hintLadderLabel: "Escalera de pistas",
    commonMistakesLabel: "Errores comunes",
    stuckRecoveryLabel: "Cómo recuperarte si te bloqueas",
    sourceAndReason: "Fuente y motivo",
    fullAcceptance: "Aceptación completa",
    deliverablesLabel: "Entregables",
    acceptanceMethod: "Método de aceptación",
    landSmallResultFirst: "Consigue primero un resultado pequeño y verificable antes de decidir si amplías el alcance.",
    returnPath: "Ruta de retorno",
    followUpReview: "Seguimiento y repaso",
    fsrsInterval: "Intervalo",
    fsrsMastery: "Dominio",
    reviewDayUnit: "días",
    reviewActions: "Acciones de repaso",
    reviewAccept: "Comenzar repaso",
    reviewSnooze: "Más tarde",
    moreLabel: "Más",
    reviewReset: "Reiniciar",
    reviewSkip: "Saltar",
    reviewDone: "Hecho",
    recentWins: "Progresos recientes",
    watchOuts: "Puntos a vigilar",
    hintProgressPrefix: "Pista",
    taskDetails: "Detalles de la tarea",
    returnCompleteEyebrow: "Completado",
    returnCompleteTitle: "Tu resultado ya está con el coach",
    mismatchCardHint: "Esta tarjeta no coincide con tu progreso actual.",
    mismatchSwitchLabel: "Cambiar a la tarjeta actual",
  },
  "fr-FR": {
    ungrouped: "Non groupé",
    startHere: "Commencez ici",
    currentScenario: "Scénario actuel",
    scenarioPack: "Pack de scénario",
    readSliceFirst: "Lisez d'abord ce fragment, puis passez à la vérification ci-dessous.",
    startIn: "Commencer par",
    apiHint: "Indice API",
    apiHintsLabel: "Indices API",
    boundary: "Limite",
    ifStuck: "En cas de blocage",
    guidanceFallback: "Ouvrez pour les indices, les limites et la récupération en cas de blocage.",
    answerNow: "Répondre maintenant",
    flashCheck: "Vérification carte",
    verifyNow: "Vérifier",
    practiceVerificationLabel: "Vérification d'exercice",
    verifyFileNoteCardOnly: "Lisez ensuite le fichier actuel et confirmez avec les vérifications ci-dessous s'il est valide.",
    verifyFileNote: "La réussite se juge sur le fichier actuel et ses diagnostics.",
    studyFirstLabel: "Étudier d'abord",
    primerLabel: "Base",
    flashComposerHint: "Répondez dans le champ ci-dessous. La liste de choix apparaît au-dessus du champ.",
    fileComposerHint: "Essayez d'abord, puis notez le résultat ou le blocage dans le champ ci-dessous. La réussite réelle passe toujours par Verify current file.",
    saveStatus: "État de l'enregistrement",
    flashDeckNext: "Autre carte flash",
    flashDeckPractice: "S'entraîner avec des cartes flash",
    adjustReturnLabel: "Retour",
    adjustReflectLabel: "Réviser",
    adjustCarryTitle: "Reportez ce résultat à l'étape suivante",
    adjustEvidenceTitle: "Révisez ce que prouve cette preuve",
    adjustNarrowTitle: "Réduisez la correction et retestez",
    adjustTightenTitle: "Resserrez le prochain geste",
    adjustDetailFallback: "Notez la limite apprise à cette passe avant de continuer.",
    adjustReturnNext: "Notez cette limite, puis continuez.",
    adjustEvidenceNext: "Énoncez cette preuve dans le champ, puis revenez au flux.",
    adjustRetestNext: "Faites le plus petit changement, puis retestez.",
    flashVerificationAria: "Vérification carte flash",
    choiceFillShort: "Choix / trous / courte",
    readCurrentIdeFile: "Lire le fichier actuel de l'IDE",
    mismatchRecoveryReason: "Passer à la carte qui correspond à votre progression actuelle",
    currentTrainingRoute: "Parcours d'entraînement actuel",
    studyCuesFirst: "Commencez par ces indices",
    primerCues: "Indices de base",
    hintsGuardrails: "Indices et limites",
    hintsGuardrailsBody: "Indices et limites",
    verifyLikeThis: "Vérifiez ainsi",
    bringBackAfterCompletion: "À rapporter après l'achèvement",
    filesToTouchLabel: "Fichiers prioritaires",
    hintLadderLabel: "Échelle d'indices",
    commonMistakesLabel: "Erreurs fréquentes",
    stuckRecoveryLabel: "Comment vous débloquer",
    sourceAndReason: "Source et raison",
    fullAcceptance: "Acceptation complète",
    deliverablesLabel: "Livrables",
    acceptanceMethod: "Méthode d'acceptation",
    landSmallResultFirst: "Obtenez d'abord un petit résultat vérifiable avant de décider d'élargir le périmètre.",
    returnPath: "Chemin de retour",
    followUpReview: "Suivi et révision",
    fsrsInterval: "Intervalle",
    fsrsMastery: "Maîtrise",
    reviewDayUnit: "jours",
    reviewActions: "Actions de révision",
    reviewAccept: "Commencer la révision",
    reviewSnooze: "Plus tard",
    moreLabel: "Plus",
    reviewReset: "Réinitialiser",
    reviewSkip: "Passer",
    reviewDone: "Terminé",
    recentWins: "Progrès récents",
    watchOuts: "Points de vigilance",
    hintProgressPrefix: "Indice",
    taskDetails: "Détails de la tâche",
    returnCompleteEyebrow: "Terminé",
    returnCompleteTitle: "Votre résultat est chez le coach",
    mismatchCardHint: "Cette carte ne correspond pas à votre progression actuelle.",
    mismatchSwitchLabel: "Aller à la carte actuelle",
  },
  "de-DE": {
    ungrouped: "Ungruppiert",
    startHere: "Hier starten",
    currentScenario: "Aktuelles Szenario",
    scenarioPack: "Szenariopaket",
    readSliceFirst: "Lies zuerst diesen Ausschnitt und gehe dann zur untenstehenden Prüfung über.",
    startIn: "Einstieg in",
    apiHint: "API-Hinweis",
    apiHintsLabel: "API-Hinweise",
    boundary: "Grenze",
    ifStuck: "Wenn du feststeckst",
    guidanceFallback: "Aufklappen für Hinweise, Grenzen und den Wiederherstellungsweg.",
    answerNow: "Jetzt antworten",
    flashCheck: "Karten-Check",
    verifyNow: "Prüfen",
    practiceVerificationLabel: "Übungsprüfung",
    verifyFileNoteCardOnly: "Lies danach die aktuelle Datei und bestätige mit den untenstehenden Prüfungen, ob sie hält.",
    verifyFileNote: "Bestanden oder nicht entscheidet die aktuelle Datei samt Diagnosen.",
    studyFirstLabel: "Zuerst lernen",
    primerLabel: "Grundlage",
    flashComposerHint: "Antworte im Eingabefeld unten. Die Auswahlliste erscheint über dem Eingabefeld.",
    fileComposerHint: "Probiere die Aufgabe zuerst und nutze das Eingabefeld unten für Ergebnis oder Blocker. Echtes Bestehen läuft weiterhin über Verify current file.",
    saveStatus: "Speicherstatus",
    flashDeckNext: "Nächste Lernkarte",
    flashDeckPractice: "Mit Lernkarten üben",
    adjustReturnLabel: "Zurück",
    adjustReflectLabel: "Reflektieren",
    adjustCarryTitle: "Trage dieses Ergebnis in den nächsten Schritt",
    adjustEvidenceTitle: "Reflektiere, was dieser Beleg beweist",
    adjustNarrowTitle: "Verenge die Korrektur und prüfe erneut",
    adjustTightenTitle: "Schärfe den nächsten Schritt",
    adjustDetailFallback: "Notiere die in dieser Runde gelernte Grenze, bevor du weitergehst.",
    adjustReturnNext: "Halte diese Grenze fest und mache weiter.",
    adjustEvidenceNext: "Benenne diesen Beleg im Eingabefeld und kehre zurück.",
    adjustRetestNext: "Mache die kleinste Änderung und teste erneut.",
    flashVerificationAria: "Karten-Verifizierung",
    choiceFillShort: "Auswahl / Lücke / kurz",
    readCurrentIdeFile: "Aktuelle IDE-Datei lesen",
    mismatchRecoveryReason: "Zur Karte wechseln, die zu deinem aktuellen Fortschritt passt",
    currentTrainingRoute: "Aktuelle Trainingsroute",
    studyCuesFirst: "Zuerst diese Hinweise ansehen",
    primerCues: "Grundlagen-Hinweise",
    hintsGuardrails: "Hinweise und Grenzen",
    hintsGuardrailsBody: "Hinweise und Grenzen",
    verifyLikeThis: "So prüfst du",
    bringBackAfterCompletion: "Nach Abschluss zurückbringen",
    filesToTouchLabel: "Vorrangige Dateien",
    hintLadderLabel: "Hinweisleiter",
    commonMistakesLabel: "Häufige Fehler",
    stuckRecoveryLabel: "Wenn du feststeckst",
    sourceAndReason: "Quelle und Grund",
    fullAcceptance: "Vollständige Abnahme",
    deliverablesLabel: "Lieferergebnisse",
    acceptanceMethod: "Abnahmeverfahren",
    landSmallResultFirst: "Erreiche zuerst ein kleines, prüfbares Ergebnis, bevor du den Umfang erweiterst.",
    returnPath: "Rückweg",
    followUpReview: "Anschluss und Wiederholung",
    fsrsInterval: "Abstand",
    fsrsMastery: "Beherrschung",
    reviewDayUnit: "Tage",
    reviewActions: "Wiederholungsaktionen",
    reviewAccept: "Wiederholung starten",
    reviewSnooze: "Später",
    moreLabel: "Mehr",
    reviewReset: "Zurücksetzen",
    reviewSkip: "Überspringen",
    reviewDone: "Fertig",
    recentWins: "Neue Fortschritte",
    watchOuts: "Beobachtungspunkte",
    hintProgressPrefix: "Hinweis",
    taskDetails: "Aufgabendetails",
    returnCompleteEyebrow: "Abgeschlossen",
    returnCompleteTitle: "Dein Ergebnis ist beim Coach",
    mismatchCardHint: "Diese Karte passt nicht zu deinem aktuellen Fortschritt.",
    mismatchSwitchLabel: "Zur aktuellen Karte wechseln",
  },
  "ja-JP": {
    ungrouped: "未グループ",
    startHere: "まずこのステップ",
    currentScenario: "現在のシナリオ",
    scenarioPack: "シナリオパック",
    readSliceFirst: "まずこの断片を読み込み、下の検証に進みましょう。",
    startIn: "まずは",
    apiHint: "API ヒント",
    apiHintsLabel: "API ヒント",
    boundary: "境界",
    ifStuck: "詰まったとき",
    guidanceFallback: "開くとヒント・境界・詰まったときの復旧手順を確認できます。",
    answerNow: "今すぐ回答",
    flashCheck: "フラッシュ確認",
    verifyNow: "検証",
    practiceVerificationLabel: "実践検証",
    verifyFileNoteCardOnly: "その後、現在のファイルを読み、下の確認項目で成立するか確かめましょう。",
    verifyFileNote: "合格かどうかは現在のファイルと診断で判断します。",
    studyFirstLabel: "先に学ぶ",
    primerLabel: "導入",
    flashComposerHint: "下の入力欄で回答しましょう。選択肢のリストは入力欄の上に表示されます。",
    fileComposerHint: "まず取り組んでから、下の入力欄に結果またはブロッカーを記録しましょう。本当の合格は Verify current file で判定されます。",
    saveStatus: "保存状態",
    flashDeckNext: "次のフラッシュカード",
    flashDeckPractice: "フラッシュカードで練習",
    adjustReturnLabel: "戻す",
    adjustReflectLabel: "振り返る",
    adjustCarryTitle: "この結果を次のステップへ持ち込む",
    adjustEvidenceTitle: "この根拠が何を示すか振り返る",
    adjustNarrowTitle: "修正を絞って、もう一度検証",
    adjustTightenTitle: "次の一手を絞る",
    adjustDetailFallback: "先に、このラウンドで学んだ境界を書き留めてから進みましょう。",
    adjustReturnNext: "この境界を書き留めてから続けましょう。",
    adjustEvidenceNext: "入力欄でこの根拠を説明してから、流れに戻りましょう。",
    adjustRetestNext: "最小の変更をしてから、もう一度試しましょう。",
    flashVerificationAria: "フラッシュ検証",
    choiceFillShort: "選択 / 穴埋め / 短答",
    readCurrentIdeFile: "現在の IDE ファイルを読む",
    mismatchRecoveryReason: "現在の進捗に合うカードに切り替える",
    currentTrainingRoute: "現在のトレーニング経路",
    studyCuesFirst: "まずこの手がかりを見る",
    primerCues: "導入の手がかり",
    hintsGuardrails: "ヒントと境界",
    hintsGuardrailsBody: "ヒントと境界",
    verifyLikeThis: "このように検証",
    bringBackAfterCompletion: "完了後に持ち帰るもの",
    filesToTouchLabel: "優先ファイル",
    hintLadderLabel: "ヒントラダー",
    commonMistakesLabel: "よくある間違い",
    stuckRecoveryLabel: "詰まったときの復旧",
    sourceAndReason: "出典と理由",
    fullAcceptance: "完全な受け入れ基準",
    deliverablesLabel: "成果物",
    acceptanceMethod: "受け入れ方法",
    landSmallResultFirst: "まず小さく検証できる結果を形にしてから、範囲を広げるか判断しましょう。",
    returnPath: "戻り先",
    followUpReview: "フォローアップと復習",
    fsrsInterval: "間隔",
    fsrsMastery: "習熟度",
    reviewDayUnit: "日",
    reviewActions: "復習アクション",
    reviewAccept: "復習を開始",
    reviewSnooze: "後で",
    moreLabel: "もっと見る",
    reviewReset: "リセット",
    reviewSkip: "スキップ",
    reviewDone: "完了",
    recentWins: "最近の進歩",
    watchOuts: "注意ポイント",
    hintProgressPrefix: "ヒント",
    taskDetails: "タスクの詳細",
    returnCompleteEyebrow: "完了",
    returnCompleteTitle: "結果をコーチに渡しました",
    mismatchCardHint: "このカードは現在の進捗と一致していません。",
    mismatchSwitchLabel: "現在のカードに切り替え",
  },
  "ko-KR": {
    ungrouped: "그룹 없음",
    startHere: "이 단계부터",
    currentScenario: "현재 시나리오",
    scenarioPack: "시나리오 팩",
    readSliceFirst: "먼저 이 조각을 읽고 아래 검증으로 넘어가세요.",
    startIn: "먼저",
    apiHint: "API 힌트",
    apiHintsLabel: "API 힌트",
    boundary: "경계",
    ifStuck: "막혔을 때",
    guidanceFallback: "펼치면 힌트, 경계, 막혔을 때의 복구 경로를 볼 수 있습니다.",
    answerNow: "지금 답하기",
    flashCheck: "플래시 확인",
    verifyNow: "검증",
    practiceVerificationLabel: "실전 검증",
    verifyFileNoteCardOnly: "이후 현재 파일을 읽고 아래 확인 항목으로 성립하는지 확인하세요.",
    verifyFileNote: "통과 여부는 현재 파일과 진단으로 판단합니다.",
    studyFirstLabel: "먼저 학습",
    primerLabel: "기초",
    flashComposerHint: "아래 입력창에서 답하세요. 선택 목록은 입력창 위에 나타납니다.",
    fileComposerHint: "먼저 시도한 뒤 아래 입력창에 결과나 막힌 지점을 기록하세요. 실제 통과는 Verify current file로 판정됩니다.",
    saveStatus: "저장 상태",
    flashDeckNext: "다음 플래시카드",
    flashDeckPractice: "플래시카드로 연습",
    adjustReturnLabel: "돌아가기",
    adjustReflectLabel: "회고",
    adjustCarryTitle: "이 결과를 다음 단계로 가져가기",
    adjustEvidenceTitle: "이 근거가 무엇을 증명하는지 복기하기",
    adjustNarrowTitle: "수정을 좁히고 다시 검증",
    adjustTightenTitle: "다음 수를 다듬기",
    adjustDetailFallback: "먼저 이 라운드에서 배운 경계를 적어 둔 뒤 계속 진행하세요.",
    adjustReturnNext: "이 경계를 적어 둔 뒤 계속하세요.",
    adjustEvidenceNext: "입력창에서 이 근거를 설명한 뒤 흐름으로 돌아가세요.",
    adjustRetestNext: "가장 작은 변경을 한 뒤 다시 시험하세요.",
    flashVerificationAria: "플래시 검증",
    choiceFillShort: "선택 / 빈칸 / 단답",
    readCurrentIdeFile: "현재 IDE 파일 읽기",
    mismatchRecoveryReason: "현재 진행과 일치하는 카드로 전환",
    currentTrainingRoute: "현재 훈련 경로",
    studyCuesFirst: "먼저 이 단서 보기",
    primerCues: "기초 단서",
    hintsGuardrails: "힌트와 경계",
    hintsGuardrailsBody: "힌트와 경계",
    verifyLikeThis: "이렇게 검증",
    bringBackAfterCompletion: "완료 후 가져올 것",
    filesToTouchLabel: "우선 파일",
    hintLadderLabel: "힌트 사다리",
    commonMistakesLabel: "흔한 실수",
    stuckRecoveryLabel: "막혔을 때 복구",
    sourceAndReason: "출처와 이유",
    fullAcceptance: "전체 인수 조건",
    deliverablesLabel: "산출물",
    acceptanceMethod: "인수 방법",
    landSmallResultFirst: "범위를 넓힐지 정하기 전에 작고 검증 가능한 결과를 먼저 만드세요.",
    returnPath: "돌아가는 경로",
    followUpReview: "후속 조치와 복습",
    fsrsInterval: "간격",
    fsrsMastery: "숙달도",
    reviewDayUnit: "일",
    reviewActions: "복습 작업",
    reviewAccept: "복습 시작",
    reviewSnooze: "나중에",
    moreLabel: "더보기",
    reviewReset: "초기화",
    reviewSkip: "건너뛰기",
    reviewDone: "완료",
    recentWins: "최근 진전",
    watchOuts: "주의 포인트",
    hintProgressPrefix: "힌트",
    taskDetails: "과제 세부 정보",
    returnCompleteEyebrow: "완료",
    returnCompleteTitle: "결과를 코치에게 전달했습니다",
    mismatchCardHint: "이 카드는 현재 진행과 일치하지 않습니다.",
    mismatchSwitchLabel: "현재 카드로 전환",
  },
  "pt-BR": {
    ungrouped: "Sem grupo",
    startHere: "Comece por aqui",
    currentScenario: "Cenário atual",
    scenarioPack: "Pacote de cenário",
    readSliceFirst: "Leia primeiro esta fatia e siga para a verificação abaixo.",
    startIn: "Comece em",
    apiHint: "Dica de API",
    apiHintsLabel: "Dicas de API",
    boundary: "Limite",
    ifStuck: "Se travar",
    guidanceFallback: "Abra para ver dicas, limites e o caminho de recuperação.",
    answerNow: "Responder agora",
    flashCheck: "Verificação flash",
    verifyNow: "Verificar",
    practiceVerificationLabel: "Verificação de prática",
    verifyFileNoteCardOnly: "Depois leia o arquivo atual e confirme com as verificações abaixo se ele vale.",
    verifyFileNote: "Aprovar ou não depende do arquivo atual e dos diagnósticos.",
    studyFirstLabel: "Estude primeiro",
    primerLabel: "Base",
    flashComposerHint: "Responda no campo abaixo. A lista de opções aparece acima do campo.",
    fileComposerHint: "Tente primeiro e use o campo abaixo para registrar o resultado ou o bloqueio. A aprovação real continua vindo de Verify current file.",
    saveStatus: "Estado do salvamento",
    flashDeckNext: "Próximo cartão flash",
    flashDeckPractice: "Praticar com cartões flash",
    adjustReturnLabel: "Retornar",
    adjustReflectLabel: "Refletir",
    adjustCarryTitle: "Leve este resultado para o próximo passo",
    adjustEvidenceTitle: "Reveja o que esta evidência prova",
    adjustNarrowTitle: "Estreite a correção e teste de novo",
    adjustTightenTitle: "Ajuste o próximo passo",
    adjustDetailFallback: "Anote o limite que você aprendeu nesta rodada antes de seguir em frente.",
    adjustReturnNext: "Registre este limite e continue.",
    adjustEvidenceNext: "Explique esta evidência no campo e retorne ao fluxo.",
    adjustRetestNext: "Faça a menor mudança e teste de novo.",
    flashVerificationAria: "Verificação de cartão flash",
    choiceFillShort: "Escolha / lacuna / curta",
    readCurrentIdeFile: "Ler o arquivo atual do IDE",
    mismatchRecoveryReason: "Trocar para o cartão que corresponde ao seu progresso atual",
    currentTrainingRoute: "Rota de treinamento atual",
    studyCuesFirst: "Veja primeiro estas pistas",
    primerCues: "Pistas da base",
    hintsGuardrails: "Dicas e limites",
    hintsGuardrailsBody: "Dicas e limites",
    verifyLikeThis: "Verifique assim",
    bringBackAfterCompletion: "Trazer de volta ao concluir",
    filesToTouchLabel: "Arquivos prioritários",
    hintLadderLabel: "Escada de dicas",
    commonMistakesLabel: "Erros comuns",
    stuckRecoveryLabel: "Se você travar",
    sourceAndReason: "Fonte e motivo",
    fullAcceptance: "Aceitação completa",
    deliverablesLabel: "Entregáveis",
    acceptanceMethod: "Método de aceitação",
    landSmallResultFirst: "Consiga primeiro um resultado pequeno e verificável antes de decidir ampliar o escopo.",
    returnPath: "Caminho de retorno",
    followUpReview: "Acompanhamento e revisão",
    fsrsInterval: "Intervalo",
    fsrsMastery: "Domínio",
    reviewDayUnit: "dias",
    reviewActions: "Ações de revisão",
    reviewAccept: "Iniciar revisão",
    reviewSnooze: "Mais tarde",
    moreLabel: "Mais",
    reviewReset: "Redefinir",
    reviewSkip: "Pular",
    reviewDone: "Concluído",
    recentWins: "Progressos recentes",
    watchOuts: "Pontos de atenção",
    hintProgressPrefix: "Dica",
    taskDetails: "Detalhes da tarefa",
    returnCompleteEyebrow: "Concluído",
    returnCompleteTitle: "Seu resultado está com o coach",
    mismatchCardHint: "Este cartão não corresponde ao seu progresso atual.",
    mismatchSwitchLabel: "Trocar para o cartão atual",
  },
};

function trainingWorkbenchText(language: ComposerLanguage, key: TrainingWorkbenchTextKey): string {
  return trainingWorkbenchTextCopy[language]?.[key] ?? trainingWorkbenchTextCopy["en-US"][key];
}

function buildTrainingLoopSteps(input: {
  language: ComposerLanguage;
  composerPhase: TrainingExecutionState["composerPhase"];
}): TrainingLoopStep[] {
  const order: TrainingLoopStepKey[] = ["learn", "try", "verify", "reflect", "return"];
  // The shared lifecycle owns pass/reflect/return progression; the card only mirrors it.
  const activeStep: TrainingLoopStepKey =
    input.composerPhase === "answer" ? "try" : input.composerPhase;
  const activeIndex = order.indexOf(activeStep);

  return order.map((step, index) => ({
    key: step,
    label: trainingLoopStepLabel(step, input.language),
    state: index < activeIndex ? "done" : index === activeIndex ? "active" : "upcoming",
  }));
}

/** §十五: verification-return state copy in eight languages (no zh/en binary). */
type TrainingVerificationReturnCopyKey =
  | "primerRetryEyebrow"
  | "primerRetryTitle"
  | "primerRetryDetail"
  | "primerRetryNext"
  | "primerStudyEyebrow"
  | "primerStudyTitle"
  | "primerStudyDetail"
  | "primerStudyNext"
  | "skippedEyebrow"
  | "skippedTitle"
  | "skippedDetail"
  | "skippedNext"
  | "flashBlockedEyebrow"
  | "flashBlockedTitle"
  | "flashBlockedDetailFallback"
  | "flashBlockedNext"
  | "flashVerifiedEyebrow"
  | "flashVerifiedTitle"
  | "flashVerifiedDetailFallback"
  | "flashVerifiedNext"
  | "flashAnsweredEyebrow"
  | "flashAnsweredTitle"
  | "flashAnsweredDetailFallback"
  | "flashAnsweredNext"
  | "flashEvidenceMissingEyebrow"
  | "flashEvidenceMissingTitle"
  | "flashEvidenceMissingDetailFallback"
  | "flashEvidenceMissingNext"
  | "flashWaitingEyebrow"
  | "flashWaitingTitle"
  | "flashWaitingDetail"
  | "flashWaitingNext"
  | "practiceBlockedEyebrow"
  | "practiceBlockedTitleManual"
  | "practiceBlockedTitleFile"
  | "practiceBlockedDetailManual"
  | "practiceBlockedDetailFile"
  | "practiceBlockedNextManualFallback"
  | "practiceBlockedNextFile"
  | "pendingPlanEyebrow"
  | "pendingPlanTitle"
  | "pendingPlanDetailFallback"
  | "pendingPlanNext"
  | "practiceVerifiedEyebrow"
  | "practiceVerifiedTitleManual"
  | "practiceVerifiedTitleFile"
  | "practiceVerifiedDetailManual"
  | "practiceVerifiedDetailFile"
  | "practiceVerifiedNextManual"
  | "practiceVerifiedNextFile"
  | "practiceEvidenceMissingEyebrow"
  | "practiceEvidenceMissingTitle"
  | "practiceEvidenceMissingDetailFallback"
  | "practiceEvidenceMissingNext"
  | "waitingEyebrow"
  | "waitingTitle"
  | "waitingDetailFile"
  | "waitingNextManual"
  | "waitingNextFile";

const trainingVerificationReturnCopy: Record<
  ComposerLanguage,
  Record<TrainingVerificationReturnCopyKey, string>
> = {
  "zh-CN": {
    primerRetryEyebrow: "需要再答",
    primerRetryTitle: "先巩固这条规则，再答一次",
    primerRetryDetail: "刚才的答案还没稳住；这张卡保持在当前训练里，不会算作完成。",
    primerRetryNext: "看提示或巩固材料，再答同一张卡。",
    primerStudyEyebrow: "先学",
    primerStudyTitle: "先建立最小理解",
    primerStudyDetail: "这张卡还不适合直接动手，先看 primer 再回来。",
    primerStudyNext: "先读完 primer，再回到同一张卡。",
    skippedEyebrow: "已跳过",
    skippedTitle: "先收紧入口，再回来",
    skippedDetail: "这张卡暂时跳过了，现在先把入口改成更小的切片。",
    skippedNext: "先选一个更小的入口，再回到当前主线。",
    flashBlockedEyebrow: "未稳住",
    flashBlockedTitle: "先收紧这条规则",
    flashBlockedDetailFallback: "这个答案还没稳定到可以带回主线。",
    flashBlockedNext: "先补上缺的证据，再简述一次。",
    flashVerifiedEyebrow: "已作答",
    flashVerifiedTitle: "先复盘这条已验证规则",
    flashVerifiedDetailFallback: "这张闪记卡已经完成。",
    flashVerifiedNext: "先用一句话说清它为什么成立，再回流。",
    flashAnsweredEyebrow: "已作答",
    flashAnsweredTitle: "把答案压成一条规则",
    flashAnsweredDetailFallback: "现在用一句话说出这张卡真正想让你记住的规则。",
    flashAnsweredNext: "复盘一次，再把规则带回主线。",
    flashEvidenceMissingEyebrow: "缺少证据",
    flashEvidenceMissingTitle: "先补上这次答案的依据",
    flashEvidenceMissingDetailFallback: "还没有可追溯的答案依据。",
    flashEvidenceMissingNext: "在输入框记下规则和依据，再复盘。",
    flashWaitingEyebrow: "闪记",
    flashWaitingTitle: "选择 /填空 /简答",
    flashWaitingDetail: "不读 IDE 文件。",
    flashWaitingNext: "提交答案。",
    practiceBlockedEyebrow: "未通过",
    practiceBlockedTitleManual: "先收紧这一轮验证",
    practiceBlockedTitleFile: "先修当前文件",
    practiceBlockedDetailManual: "还需要一条更稳的解释、例子，或证据。",
    practiceBlockedDetailFile: "还没达到通过条件。",
    practiceBlockedNextManualFallback: "先缩回到一个更小的可证明步骤。",
    practiceBlockedNextFile: "修完再验。",
    pendingPlanEyebrow: "已验证，待计划确认",
    pendingPlanTitle: "这次证据已验证，但还不是正式计划完成",
    pendingPlanDetailFallback: "IDE 或闪记验证已通过，等待 Coach 确认是否更新正式计划。",
    pendingPlanNext: "先复盘，再把证据带回 Coach 确认计划下一步。",
    practiceVerifiedEyebrow: "已通过",
    practiceVerifiedTitleManual: "先复盘这张已验证练习卡",
    practiceVerifiedTitleFile: "先复盘这次实战证据",
    practiceVerifiedDetailManual: "这一轮解释或例子已经足够稳。",
    practiceVerifiedDetailFile: "当前文件已通过。",
    practiceVerifiedNextManual: "先说清楚你用的证据或关键步，再回流。",
    practiceVerifiedNextFile: "先说清楚是哪条证据让它通过，再回流。",
    practiceEvidenceMissingEyebrow: "缺少证据",
    practiceEvidenceMissingTitle: "先补上这次练习的依据",
    practiceEvidenceMissingDetailFallback: "实现不等于通过，还需要一条可追溯的验证结果。",
    practiceEvidenceMissingNext: "在输入框记录验证结果或 blocker，再复盘。",
    waitingEyebrow: "待验",
    waitingTitle: "先落地一个最小可交付结果",
    waitingDetailFile: "实战卡要读当前 IDE 文件。",
    waitingNextManual: "在下方输入框记录结果或 blocker。",
    waitingNextFile: "写完后验证。",
  },
  "en-US": {
    primerRetryEyebrow: "Retry needed",
    primerRetryTitle: "Reinforce the rule, then answer again",
    primerRetryDetail: "The last answer was not stable yet; this card stays active and is not counted as complete.",
    primerRetryNext: "Review the hint or primer, then answer the same card again.",
    primerStudyEyebrow: "Study first",
    primerStudyTitle: "Build the smallest understanding first",
    primerStudyDetail: "This card is not ready for direct execution yet; open the primer first.",
    primerStudyNext: "Finish the primer, then return to the same card.",
    skippedEyebrow: "Skipped",
    skippedTitle: "Narrow the entry, then return",
    skippedDetail: "This card was skipped for now, so the next step is to reopen it with a smaller slice.",
    skippedNext: "Choose a smaller entry point, then return to the current thread.",
    flashBlockedEyebrow: "Needs review",
    flashBlockedTitle: "Tighten the rule first",
    flashBlockedDetailFallback: "This answer is not stable enough to carry back yet.",
    flashBlockedNext: "Add the missing proof, then restate it once.",
    flashVerifiedEyebrow: "Answer checked",
    flashVerifiedTitle: "Reflect on this verified rule",
    flashVerifiedDetailFallback: "This flash card is completed.",
    flashVerifiedNext: "State why it holds in one sentence, then return.",
    flashAnsweredEyebrow: "Answered",
    flashAnsweredTitle: "Compress the answer into one rule",
    flashAnsweredDetailFallback: "Now say the one rule this card wants you to retain.",
    flashAnsweredNext: "Reflect once, then bring the rule back.",
    flashEvidenceMissingEyebrow: "Evidence missing",
    flashEvidenceMissingTitle: "Add the evidence for this answer",
    flashEvidenceMissingDetailFallback: "There is no traceable evidence for this answer yet.",
    flashEvidenceMissingNext: "Record the rule and its evidence in the composer, then reflect.",
    flashWaitingEyebrow: "Flash",
    flashWaitingTitle: "Choice / fill / short answer",
    flashWaitingDetail: "No IDE file read.",
    flashWaitingNext: "Submit an answer.",
    practiceBlockedEyebrow: "Needs work",
    practiceBlockedTitleManual: "Tighten this verification round first",
    practiceBlockedTitleFile: "Fix the current file first",
    practiceBlockedDetailManual: "This still needs one tighter explanation, example, or proof.",
    practiceBlockedDetailFile: "Pass condition not met yet.",
    practiceBlockedNextManualFallback: "Return to one smaller step you can prove.",
    practiceBlockedNextFile: "Fix it, then verify again.",
    pendingPlanEyebrow: "Verified, plan confirmation pending",
    pendingPlanTitle: "Evidence is verified; the formal plan is not complete",
    pendingPlanDetailFallback: "The IDE or flash evidence passed; Coach must confirm any formal plan change.",
    pendingPlanNext: "Reflect, then bring the evidence to Coach to confirm the next plan step.",
    practiceVerifiedEyebrow: "Verified",
    practiceVerifiedTitleManual: "Reflect on this verified practice card",
    practiceVerifiedTitleFile: "Reflect on this verified evidence",
    practiceVerifiedDetailManual: "This explanation or example is grounded enough to continue.",
    practiceVerifiedDetailFile: "Current file passed.",
    practiceVerifiedNextManual: "Name the proof or key step you used, then return.",
    practiceVerifiedNextFile: "Name the proof that made it pass, then return.",
    practiceEvidenceMissingEyebrow: "Evidence missing",
    practiceEvidenceMissingTitle: "Add the evidence for this practice",
    practiceEvidenceMissingDetailFallback: "Implementation is not a pass; a traceable verification result is still needed.",
    practiceEvidenceMissingNext: "Record the verification result or blocker in the composer, then reflect.",
    waitingEyebrow: "Waiting",
    waitingTitle: "Land the smallest deliverable first",
    waitingDetailFile: "Practice cards read the current IDE file.",
    waitingNextManual: "Record the result or blocker in the composer below.",
    waitingNextFile: "Verify after editing.",
  },
  "es-ES": {
    primerRetryEyebrow: "Reintento necesario",
    primerRetryTitle: "Refuerza la regla y responde de nuevo",
    primerRetryDetail: "La última respuesta aún no se consolidó; esta tarjeta sigue activa en el entrenamiento y no cuenta como completada.",
    primerRetryNext: "Repasa la pista o el material de refuerzo y vuelve a responder la misma tarjeta.",
    primerStudyEyebrow: "Estudia primero",
    primerStudyTitle: "Construye primero la comprensión mínima",
    primerStudyDetail: "Esta tarjeta aún no está lista para ejecutarse directamente; abre primero la base.",
    primerStudyNext: "Termina la base y vuelve a la misma tarjeta.",
    skippedEyebrow: "Omitida",
    skippedTitle: "Reduce la entrada y vuelve",
    skippedDetail: "Esta tarjeta se omitió por ahora; el siguiente paso es reabrirla con un fragmento más pequeño.",
    skippedNext: "Elige un punto de entrada más pequeño y vuelve al hilo actual.",
    flashBlockedEyebrow: "Requiere revisión",
    flashBlockedTitle: "Afina primero la regla",
    flashBlockedDetailFallback: "Esta respuesta aún no es lo bastante estable para llevarla de vuelta.",
    flashBlockedNext: "Añade la prueba que falta y reformúlala una vez.",
    flashVerifiedEyebrow: "Respuesta comprobada",
    flashVerifiedTitle: "Repasa esta regla verificada",
    flashVerifiedDetailFallback: "Esta tarjeta flash está completada.",
    flashVerifiedNext: "Explica en una frase por qué se sostiene y vuelve al flujo.",
    flashAnsweredEyebrow: "Respondida",
    flashAnsweredTitle: "Condensa la respuesta en una regla",
    flashAnsweredDetailFallback: "Ahora di en una frase la regla que esta tarjeta quiere que retengas.",
    flashAnsweredNext: "Repasa una vez y lleva la regla de vuelta al hilo.",
    flashEvidenceMissingEyebrow: "Falta evidencia",
    flashEvidenceMissingTitle: "Añade la evidencia de esta respuesta",
    flashEvidenceMissingDetailFallback: "Todavía no hay evidencia rastreable de esta respuesta.",
    flashEvidenceMissingNext: "Anota la regla y su evidencia en el campo y repasa.",
    flashWaitingEyebrow: "Tarjeta",
    flashWaitingTitle: "Opción / completar / respuesta corta",
    flashWaitingDetail: "No lee archivos del IDE.",
    flashWaitingNext: "Envía una respuesta.",
    practiceBlockedEyebrow: "Necesita trabajo",
    practiceBlockedTitleManual: "Afina primero esta ronda de verificación",
    practiceBlockedTitleFile: "Corrige primero el archivo actual",
    practiceBlockedDetailManual: "Todavía hace falta una explicación, un ejemplo o una prueba más sólidos.",
    practiceBlockedDetailFile: "Aún no se cumple la condición de paso.",
    practiceBlockedNextManualFallback: "Vuelve a un paso más pequeño que puedas demostrar.",
    practiceBlockedNextFile: "Corrige y verifica de nuevo.",
    pendingPlanEyebrow: "Verificada, pendiente de confirmar el plan",
    pendingPlanTitle: "La evidencia está verificada, pero el plan formal no está completo",
    pendingPlanDetailFallback: "La verificación del IDE o de la tarjeta pasó; Coach debe confirmar cualquier cambio del plan formal.",
    pendingPlanNext: "Repasa y lleva la evidencia a Coach para confirmar el siguiente paso del plan.",
    practiceVerifiedEyebrow: "Verificada",
    practiceVerifiedTitleManual: "Repasa esta tarjeta de práctica verificada",
    practiceVerifiedTitleFile: "Repasa esta evidencia de práctica verificada",
    practiceVerifiedDetailManual: "Esta explicación o ejemplo ya es lo bastante sólido para continuar.",
    practiceVerifiedDetailFile: "El archivo actual pasó.",
    practiceVerifiedNextManual: "Nombra la prueba o el paso clave que usaste y vuelve al flujo.",
    practiceVerifiedNextFile: "Nombra la prueba que hizo que pasara y vuelve al flujo.",
    practiceEvidenceMissingEyebrow: "Falta evidencia",
    practiceEvidenceMissingTitle: "Añade la evidencia de esta práctica",
    practiceEvidenceMissingDetailFallback: "Implementar no es aprobar; aún hace falta un resultado de verificación rastreable.",
    practiceEvidenceMissingNext: "Registra el resultado de verificación o el bloqueo en el campo y repasa.",
    waitingEyebrow: "En espera",
    waitingTitle: "Aterriza primero el resultado entregable más pequeño",
    waitingDetailFile: "Las tarjetas de práctica leen el archivo actual del IDE.",
    waitingNextManual: "Registra el resultado o el bloqueo en el campo de abajo.",
    waitingNextFile: "Verifica después de editar.",
  },
  "fr-FR": {
    primerRetryEyebrow: "Nouvelle réponse requise",
    primerRetryTitle: "Renforcez la règle, puis répondez à nouveau",
    primerRetryDetail: "La dernière réponse n'était pas encore solide ; cette carte reste active dans l'entraînement et ne compte pas comme terminée.",
    primerRetryNext: "Relisez l'indice ou le support de renforcement, puis répondez à nouveau à la même carte.",
    primerStudyEyebrow: "Étudier d'abord",
    primerStudyTitle: "Construisez d'abord la compréhension minimale",
    primerStudyDetail: "Cette carte n'est pas encore prête pour une exécution directe ; ouvrez d'abord la base.",
    primerStudyNext: "Terminez la base, puis revenez à la même carte.",
    skippedEyebrow: "Passée",
    skippedTitle: "Resserrez l'entrée, puis revenez",
    skippedDetail: "Cette carte a été passée pour l'instant ; l'étape suivante est de la rouvrir avec un fragment plus petit.",
    skippedNext: "Choisissez un point d'entrée plus petit, puis revenez au fil actuel.",
    flashBlockedEyebrow: "À revoir",
    flashBlockedTitle: "Resserrez d'abord la règle",
    flashBlockedDetailFallback: "Cette réponse n'est pas encore assez stable pour être rapportée.",
    flashBlockedNext: "Ajoutez la preuve manquante, puis reformulez-la une fois.",
    flashVerifiedEyebrow: "Réponse vérifiée",
    flashVerifiedTitle: "Révisez cette règle vérifiée",
    flashVerifiedDetailFallback: "Cette carte flash est terminée.",
    flashVerifiedNext: "Dites en une phrase pourquoi elle tient, puis revenez au flux.",
    flashAnsweredEyebrow: "Répondue",
    flashAnsweredTitle: "Condensez la réponse en une règle",
    flashAnsweredDetailFallback: "Dites maintenant en une phrase la règle que cette carte veut vous faire retenir.",
    flashAnsweredNext: "Révisez une fois, puis rapportez la règle au fil.",
    flashEvidenceMissingEyebrow: "Preuve manquante",
    flashEvidenceMissingTitle: "Ajoutez la preuve de cette réponse",
    flashEvidenceMissingDetailFallback: "Il n'y a pas encore de preuve traçable pour cette réponse.",
    flashEvidenceMissingNext: "Notez la règle et sa preuve dans le champ, puis révisez.",
    flashWaitingEyebrow: "Carte",
    flashWaitingTitle: "Choix / texte à trous / réponse courte",
    flashWaitingDetail: "Ne lit aucun fichier de l'IDE.",
    flashWaitingNext: "Soumettez une réponse.",
    practiceBlockedEyebrow: "À retravailler",
    practiceBlockedTitleManual: "Resserrez d'abord cette passe de vérification",
    practiceBlockedTitleFile: "Corrigez d'abord le fichier actuel",
    practiceBlockedDetailManual: "Il manque encore une explication, un exemple ou une preuve plus solide.",
    practiceBlockedDetailFile: "La condition de passage n'est pas encore remplie.",
    practiceBlockedNextManualFallback: "Revenez à une étape plus petite que vous pouvez prouver.",
    practiceBlockedNextFile: "Corrigez, puis vérifiez à nouveau.",
    pendingPlanEyebrow: "Vérifiée, confirmation du plan en attente",
    pendingPlanTitle: "La preuve est vérifiée, mais le plan formel n'est pas terminé",
    pendingPlanDetailFallback: "La vérification IDE ou carte est passée ; Coach doit confirmer toute modification du plan formel.",
    pendingPlanNext: "Révisez, puis apportez la preuve à Coach pour confirmer la prochaine étape du plan.",
    practiceVerifiedEyebrow: "Vérifiée",
    practiceVerifiedTitleManual: "Révisez cette carte d'exercice vérifiée",
    practiceVerifiedTitleFile: "Révisez cette preuve de pratique vérifiée",
    practiceVerifiedDetailManual: "Cette explication ou cet exemple est désormais assez solide pour continuer.",
    practiceVerifiedDetailFile: "Le fichier actuel est passé.",
    practiceVerifiedNextManual: "Nommez la preuve ou l'étape clé utilisée, puis revenez au flux.",
    practiceVerifiedNextFile: "Nommez la preuve qui l'a fait passer, puis revenez au flux.",
    practiceEvidenceMissingEyebrow: "Preuve manquante",
    practiceEvidenceMissingTitle: "Ajoutez la preuve de cet exercice",
    practiceEvidenceMissingDetailFallback: "Implémenter n'est pas réussir ; il faut encore un résultat de vérification traçable.",
    practiceEvidenceMissingNext: "Notez le résultat de vérification ou le blocage dans le champ, puis révisez.",
    waitingEyebrow: "En attente",
    waitingTitle: "Posez d'abord le plus petit livrable possible",
    waitingDetailFile: "Les cartes de pratique lisent le fichier actuel de l'IDE.",
    waitingNextManual: "Notez le résultat ou le blocage dans le champ ci-dessous.",
    waitingNextFile: "Vérifiez après modification.",
  },
  "de-DE": {
    primerRetryEyebrow: "Erneut Antworten nötig",
    primerRetryTitle: "Festige die Regel zuerst und antworte dann erneut",
    primerRetryDetail: "Die letzte Antwort war noch nicht stabil; diese Karte bleibt im aktuellen Training aktiv und gilt nicht als abgeschlossen.",
    primerRetryNext: "Sieh dir den Hinweis oder das Festigungsmaterial an und beantworte dieselbe Karte erneut.",
    primerStudyEyebrow: "Zuerst lernen",
    primerStudyTitle: "Baue zuerst das kleinste Verständnis auf",
    primerStudyDetail: "Diese Karte ist noch nicht für die direkte Ausführung bereit; öffne zuerst die Grundlage.",
    primerStudyNext: "Schließe die Grundlage ab und kehre zur selben Karte zurück.",
    skippedEyebrow: "Übersprungen",
    skippedTitle: "Verkleinere den Einstieg und kehre zurück",
    skippedDetail: "Diese Karte wurde vorerst übersprungen; öffne sie als Nächstes mit einem kleineren Ausschnitt wieder.",
    skippedNext: "Wähle einen kleineren Einstieg und kehre zum aktuellen Arbeitsfaden zurück.",
    flashBlockedEyebrow: "Überprüfung nötig",
    flashBlockedTitle: "Schärfe zuerst die Regel",
    flashBlockedDetailFallback: "Diese Antwort ist noch nicht stabil genug, um sie zurückzubringen.",
    flashBlockedNext: "Ergänze den fehlenden Beleg und formuliere ihn einmal aus.",
    flashVerifiedEyebrow: "Antwort geprüft",
    flashVerifiedTitle: "Reflektiere diese geprüfte Regel",
    flashVerifiedDetailFallback: "Diese Lernkarte ist abgeschlossen.",
    flashVerifiedNext: "Sage in einem Satz, warum sie gilt, und kehre zurück.",
    flashAnsweredEyebrow: "Beantwortet",
    flashAnsweredTitle: "Verdichte die Antwort zu einer Regel",
    flashAnsweredDetailFallback: "Nenne jetzt in einem Satz die Regel, die diese Karte dir wirklich einprägen will.",
    flashAnsweredNext: "Reflektiere einmal und bringe die Regel zurück zum Faden.",
    flashEvidenceMissingEyebrow: "Beleg fehlt",
    flashEvidenceMissingTitle: "Ergänze den Beleg für diese Antwort",
    flashEvidenceMissingDetailFallback: "Es gibt noch keinen nachvollziehbaren Beleg für diese Antwort.",
    flashEvidenceMissingNext: "Notiere Regel und Beleg im Eingabefeld und reflektiere.",
    flashWaitingEyebrow: "Karte",
    flashWaitingTitle: "Auswahl / Lückentext / Kurzantwort",
    flashWaitingDetail: "Liest keine IDE-Dateien.",
    flashWaitingNext: "Sende eine Antwort ab.",
    practiceBlockedEyebrow: "Nachbesserung nötig",
    practiceBlockedTitleManual: "Schärfe zuerst diese Prüfrunde",
    practiceBlockedTitleFile: "Korrigiere zuerst die aktuelle Datei",
    practiceBlockedDetailManual: "Es fehlt noch eine belastbarere Erklärung, ein Beispiel oder ein Beleg.",
    practiceBlockedDetailFile: "Die Bestehensbedingung ist noch nicht erfüllt.",
    practiceBlockedNextManualFallback: "Kehre zu einem kleineren, beweisbaren Schritt zurück.",
    practiceBlockedNextFile: "Erst korrigieren, dann erneut prüfen.",
    pendingPlanEyebrow: "Verifiziert, Planbestätigung ausstehend",
    pendingPlanTitle: "Dieser Beleg ist verifiziert, aber der formale Plan ist nicht fertig",
    pendingPlanDetailFallback: "Die IDE- oder Karten-Verifizierung ist bestanden; Coach muss jede formale Planänderung bestätigen.",
    pendingPlanNext: "Reflektiere und bringe den Beleg zu Coach, um den nächsten Planschritt zu bestätigen.",
    practiceVerifiedEyebrow: "Verifiziert",
    practiceVerifiedTitleManual: "Reflektiere diese verifizierte Übungskarte",
    practiceVerifiedTitleFile: "Reflektiere diesen verifizierten Praxisbeleg",
    practiceVerifiedDetailManual: "Diese Erklärung oder dieses Beispiel ist jetzt stabil genug, um weiterzumachen.",
    practiceVerifiedDetailFile: "Die aktuelle Datei ist bestanden.",
    practiceVerifiedNextManual: "Nenne den Beleg oder Schlüsselschritt, den du verwendet hast, und kehre zurück.",
    practiceVerifiedNextFile: "Nenne den Beleg, der zum Bestehen geführt hat, und kehre zurück.",
    practiceEvidenceMissingEyebrow: "Beleg fehlt",
    practiceEvidenceMissingTitle: "Ergänze den Beleg für diese Übung",
    practiceEvidenceMissingDetailFallback: "Umsetzen ist nicht Bestehen; es fehlt noch ein nachvollziehbares Verifizierungsergebnis.",
    practiceEvidenceMissingNext: "Halte das Verifizierungsergebnis oder den Blocker im Eingabefeld fest und reflektiere.",
    waitingEyebrow: "Ausstehend",
    waitingTitle: "Liefere zuerst das kleinste lieferbare Ergebnis",
    waitingDetailFile: "Übungskarten lesen die aktuelle IDE-Datei.",
    waitingNextManual: "Halte das Ergebnis oder den Blocker im Feld unten fest.",
    waitingNextFile: "Nach dem Bearbeiten prüfen.",
  },
  "ja-JP": {
    primerRetryEyebrow: "再回答が必要",
    primerRetryTitle: "このルールを先に強化してから、もう一度答えましょう",
    primerRetryDetail: "直前の回答はまだ安定していません。このカードは現在のトレーニングに残り、完了として数えられません。",
    primerRetryNext: "ヒントや強化素材を見て、同じカードにもう一度答えましょう。",
    primerStudyEyebrow: "先に学ぶ",
    primerStudyTitle: "まず最小の理解を作る",
    primerStudyDetail: "このカードはまだ直接取り組む段階ではありません。まず導入を読みましょう。",
    primerStudyNext: "導入を読み終えてから、同じカードに戻りましょう。",
    skippedEyebrow: "スキップ済み",
    skippedTitle: "入り口を絞ってから戻る",
    skippedDetail: "このカードはいったんスキップされました。次はもっと小さな断片で開き直しましょう。",
    skippedNext: "もっと小さい入り口を選んでから、現在のスレッドに戻りましょう。",
    flashBlockedEyebrow: "要見直し",
    flashBlockedTitle: "まずこのルールを締めましょう",
    flashBlockedDetailFallback: "この回答はまだ十分に安定しておらず、持ち帰る段階ではありません。",
    flashBlockedNext: "欠けている根拠を補い、一度言い換えましょう。",
    flashVerifiedEyebrow: "回答済み",
    flashVerifiedTitle: "この検証済みルールを振り返る",
    flashVerifiedDetailFallback: "このフラッシュカードは完了しました。",
    flashVerifiedNext: "なぜ成り立つのかを一文で説明してから、学習の流れに戻りましょう。",
    flashAnsweredEyebrow: "回答済み",
    flashAnsweredTitle: "答えを一つのルールに圧縮する",
    flashAnsweredDetailFallback: "このカードが本当に覚えさせたいルールを、今一文で言いましょう。",
    flashAnsweredNext: "一度振り返ってから、ルールを本筋に持ち帰りましょう。",
    flashEvidenceMissingEyebrow: "根拠が不足",
    flashEvidenceMissingTitle: "この回答の根拠を補いましょう",
    flashEvidenceMissingDetailFallback: "この回答にはまだ追跡可能な根拠がありません。",
    flashEvidenceMissingNext: "入力欄にルールと根拠を記録してから、振り返りましょう。",
    flashWaitingEyebrow: "カード",
    flashWaitingTitle: "選択 / 穴埋め / 短答",
    flashWaitingDetail: "IDE のファイルは読みません。",
    flashWaitingNext: "答えを送信しましょう。",
    practiceBlockedEyebrow: "要修正",
    practiceBlockedTitleManual: "まずこの検証ラウンドを締めましょう",
    practiceBlockedTitleFile: "まず現在のファイルを修正しましょう",
    practiceBlockedDetailManual: "もっと安定した説明・例・根拠がまだ必要です。",
    practiceBlockedDetailFile: "合格条件にまだ達していません。",
    practiceBlockedNextManualFallback: "証明できるもっと小さなステップに縮めましょう。",
    practiceBlockedNextFile: "修正してから、もう一度検証しましょう。",
    pendingPlanEyebrow: "検証済み、計画確認待ち",
    pendingPlanTitle: "この根拠は検証済みですが、正式な計画はまだ完了していません",
    pendingPlanDetailFallback: "IDE またはフラッシュカードの検証は合格しました。正式な計画を更新するかどうかは Coach の確認待ちです。",
    pendingPlanNext: "振り返ってから、根拠を Coach に持ち帰り、計画の次のステップを確認しましょう。",
    practiceVerifiedEyebrow: "合格",
    practiceVerifiedTitleManual: "この検証済み練習カードを振り返る",
    practiceVerifiedTitleFile: "この検証済みの実践根拠を振り返る",
    practiceVerifiedDetailManual: "この説明または例は、続行できる十分な安定さになりました。",
    practiceVerifiedDetailFile: "現在のファイルは合格しました。",
    practiceVerifiedNextManual: "使った根拠や重要なステップを言ってから、流れに戻りましょう。",
    practiceVerifiedNextFile: "合格につながった根拠を言ってから、流れに戻りましょう。",
    practiceEvidenceMissingEyebrow: "根拠が不足",
    practiceEvidenceMissingTitle: "この練習の根拠を補いましょう",
    practiceEvidenceMissingDetailFallback: "実装は合格ではありません。追跡可能な検証結果がまだ必要です。",
    practiceEvidenceMissingNext: "入力欄に検証結果またはブロッカーを記録してから、振り返りましょう。",
    waitingEyebrow: "検証待ち",
    waitingTitle: "まず最小の成果物を形にしましょう",
    waitingDetailFile: "実践カードは現在の IDE ファイルを読みます。",
    waitingNextManual: "下の入力欄に結果またはブロッカーを記録しましょう。",
    waitingNextFile: "書き終えたら検証しましょう。",
  },
  "ko-KR": {
    primerRetryEyebrow: "다시 응답 필요",
    primerRetryTitle: "규칙을 먼저 다지고 다시 답하세요",
    primerRetryDetail: "방금 답은 아직 안정되지 않았습니다. 이 카드는 현재 훈련에 유지되며 완료로 계산되지 않습니다.",
    primerRetryNext: "힌트나 보강 자료를 본 뒤 같은 카드에 다시 답하세요.",
    primerStudyEyebrow: "먼저 학습",
    primerStudyTitle: "가장 작은 이해부터 만들기",
    primerStudyDetail: "이 카드는 아직 바로 실행하기엔 이르니, 먼저 기초 자료를 보세요.",
    primerStudyNext: "기초 자료를 끝낸 뒤 같은 카드로 돌아오세요.",
    skippedEyebrow: "건너뜀",
    skippedTitle: "진입을 좁힌 뒤 돌아오기",
    skippedDetail: "이 카드는 일단 건너뛰었습니다. 이제 더 작은 조각으로 다시 여는 것이 다음 단계입니다.",
    skippedNext: "더 작은 진입점을 고른 뒤 현재 흐름으로 돌아오세요.",
    flashBlockedEyebrow: "검토 필요",
    flashBlockedTitle: "먼저 이 규칙을 다듬으세요",
    flashBlockedDetailFallback: "이 답은 아직 메인 흐름으로 가져가기에 충분히 안정적이지 않습니다.",
    flashBlockedNext: "빠진 근거를 보충하고 한 번 다시 요약하세요.",
    flashVerifiedEyebrow: "답안 확인됨",
    flashVerifiedTitle: "검증된 이 규칙을 복기하세요",
    flashVerifiedDetailFallback: "이 플래시 카드는 완료되었습니다.",
    flashVerifiedNext: "왜 성립하는지 한 문장으로 말한 뒤 흐름으로 돌아가세요.",
    flashAnsweredEyebrow: "응답함",
    flashAnsweredTitle: "답을 한 규칙으로 압축하기",
    flashAnsweredDetailFallback: "이 카드가 정말 기억하길 원하는 규칙을 지금 한 문장으로 말해 보세요.",
    flashAnsweredNext: "한 번 복기한 뒤 규칙을 본 흐름으로 가져오세요.",
    flashEvidenceMissingEyebrow: "근거 없음",
    flashEvidenceMissingTitle: "이 답의 근거를 보충하세요",
    flashEvidenceMissingDetailFallback: "이 답에는 아직 추적 가능한 근거가 없습니다.",
    flashEvidenceMissingNext: "입력창에 규칙과 근거를 적은 뒤 복기하세요.",
    flashWaitingEyebrow: "카드",
    flashWaitingTitle: "선택 / 빈칸 / 단답",
    flashWaitingDetail: "IDE 파일을 읽지 않습니다.",
    flashWaitingNext: "답을 제출하세요.",
    practiceBlockedEyebrow: "보완 필요",
    practiceBlockedTitleManual: "먼저 이 검증 라운드를 다듬으세요",
    practiceBlockedTitleFile: "먼저 현재 파일을 수정하세요",
    practiceBlockedDetailManual: "더 안정적인 설명, 예시 또는 근거가 아직 필요합니다.",
    practiceBlockedDetailFile: "통과 조건을 아직 충족하지 못했습니다.",
    practiceBlockedNextManualFallback: "증명할 수 있는 더 작은 단계로 줄이세요.",
    practiceBlockedNextFile: "고친 뒤 다시 검증하세요.",
    pendingPlanEyebrow: "검증됨, 계획 확인 대기",
    pendingPlanTitle: "이 근거는 검증되었지만 공식 계획은 아직 완료되지 않았습니다",
    pendingPlanDetailFallback: "IDE 또는 플래시 검증은 통과했습니다. 공식 계획 변경 여부는 Coach의 확인을 기다리는 중입니다.",
    pendingPlanNext: "복기한 뒤 근거를 Coach에게 가져가 계획의 다음 단계를 확인하세요.",
    practiceVerifiedEyebrow: "통과",
    practiceVerifiedTitleManual: "검증된 이 연습 카드를 복기하세요",
    practiceVerifiedTitleFile: "검증된 이 실전 근거를 복기하세요",
    practiceVerifiedDetailManual: "이 설명이나 예시는 이제 계속하기에 충분히 안정적입니다.",
    practiceVerifiedDetailFile: "현재 파일이 통과했습니다.",
    practiceVerifiedNextManual: "사용한 근거나 핵심 단계를 말한 뒤 흐름으로 돌아가세요.",
    practiceVerifiedNextFile: "통과시킨 근거를 말한 뒤 흐름으로 돌아가세요.",
    practiceEvidenceMissingEyebrow: "근거 없음",
    practiceEvidenceMissingTitle: "이 연습의 근거를 보충하세요",
    practiceEvidenceMissingDetailFallback: "구현은 통과가 아닙니다. 추적 가능한 검증 결과가 아직 필요합니다.",
    practiceEvidenceMissingNext: "입력창에 검증 결과나 막힌 지점을 기록한 뒤 복기하세요.",
    waitingEyebrow: "검증 대기",
    waitingTitle: "가장 작은 인도 가능한 결과부터 만들기",
    waitingDetailFile: "실전 카드는 현재 IDE 파일을 읽습니다.",
    waitingNextManual: "아래 입력창에 결과나 막힌 지점을 기록하세요.",
    waitingNextFile: "작성한 뒤 검증하세요.",
  },
  "pt-BR": {
    primerRetryEyebrow: "Nova resposta necessária",
    primerRetryTitle: "Reforce a regra e responda novamente",
    primerRetryDetail: "A última resposta ainda não ficou estável; este cartão permanece ativo no treinamento e não conta como concluído.",
    primerRetryNext: "Revise a dica ou o material de reforço e responda o mesmo cartão de novo.",
    primerStudyEyebrow: "Estude primeiro",
    primerStudyTitle: "Construa primeiro o entendimento mínimo",
    primerStudyDetail: "Este cartão ainda não está pronto para execução direta; abra primeiro a base.",
    primerStudyNext: "Termine a base e volte ao mesmo cartão.",
    skippedEyebrow: "Pulado",
    skippedTitle: "Estreite a entrada e volte",
    skippedDetail: "Este cartão foi pulado por enquanto; o próximo passo é reabri-lo com uma fatia menor.",
    skippedNext: "Escolha uma entrada menor e volte ao fluxo atual.",
    flashBlockedEyebrow: "Precisa de revisão",
    flashBlockedTitle: "Afine primeiro a regra",
    flashBlockedDetailFallback: "Esta resposta ainda não está estável o bastante para voltar.",
    flashBlockedNext: "Adicione a prova que falta e reformule uma vez.",
    flashVerifiedEyebrow: "Resposta verificada",
    flashVerifiedTitle: "Reveja esta regra verificada",
    flashVerifiedDetailFallback: "Este cartão flash foi concluído.",
    flashVerifiedNext: "Diga em uma frase por que ela vale e retorne ao fluxo.",
    flashAnsweredEyebrow: "Respondida",
    flashAnsweredTitle: "Comprima a resposta em uma regra",
    flashAnsweredDetailFallback: "Agora diga em uma frase a regra que este cartão quer que você retenha.",
    flashAnsweredNext: "Reveja uma vez e leve a regra de volta ao fluxo.",
    flashEvidenceMissingEyebrow: "Evidência ausente",
    flashEvidenceMissingTitle: "Adicione a evidência desta resposta",
    flashEvidenceMissingDetailFallback: "Ainda não há evidência rastreável para esta resposta.",
    flashEvidenceMissingNext: "Registre a regra e a evidência no campo e reveja.",
    flashWaitingEyebrow: "Cartão",
    flashWaitingTitle: "Escolha / lacuna / resposta curta",
    flashWaitingDetail: "Não lê arquivos do IDE.",
    flashWaitingNext: "Envie uma resposta.",
    practiceBlockedEyebrow: "Precisa de ajuste",
    practiceBlockedTitleManual: "Afine primeiro esta rodada de verificação",
    practiceBlockedTitleFile: "Corrija primeiro o arquivo atual",
    practiceBlockedDetailManual: "Ainda falta uma explicação, um exemplo ou uma prova mais sólidos.",
    practiceBlockedDetailFile: "A condição de aprovação ainda não foi atingida.",
    practiceBlockedNextManualFallback: "Volte a um passo menor que você consiga provar.",
    practiceBlockedNextFile: "Corrija e verifique de novo.",
    pendingPlanEyebrow: "Verificada, confirmação do plano pendente",
    pendingPlanTitle: "A evidência está verificada, mas o plano formal não está concluído",
    pendingPlanDetailFallback: "A verificação do IDE ou do cartão passou; o Coach deve confirmar qualquer mudança no plano formal.",
    pendingPlanNext: "Reveja e leve a evidência ao Coach para confirmar o próximo passo do plano.",
    practiceVerifiedEyebrow: "Verificada",
    practiceVerifiedTitleManual: "Reveja este cartão de prática verificado",
    practiceVerifiedTitleFile: "Reveja esta evidência de prática verificada",
    practiceVerifiedDetailManual: "Esta explicação ou exemplo já está sólido o bastante para continuar.",
    practiceVerifiedDetailFile: "O arquivo atual passou.",
    practiceVerifiedNextManual: "Nomeie a prova ou o passo-chave que usou e retorne ao fluxo.",
    practiceVerifiedNextFile: "Nomeie a prova que fez passar e retorne ao fluxo.",
    practiceEvidenceMissingEyebrow: "Evidência ausente",
    practiceEvidenceMissingTitle: "Adicione a evidência desta prática",
    practiceEvidenceMissingDetailFallback: "Implementar não é aprovar; ainda é preciso um resultado de verificação rastreável.",
    practiceEvidenceMissingNext: "Registre o resultado da verificação ou o bloqueio no campo e reveja.",
    waitingEyebrow: "Aguardando",
    waitingTitle: "Entregue primeiro o menor resultado possível",
    waitingDetailFile: "Cartões de prática leem o arquivo atual do IDE.",
    waitingNextManual: "Registre o resultado ou o bloqueio no campo abaixo.",
    waitingNextFile: "Verifique após editar.",
  },
};

function trainingVerificationReturnText(
  language: ComposerLanguage,
  key: TrainingVerificationReturnCopyKey,
): string {
  return trainingVerificationReturnCopy[language]?.[key] ?? trainingVerificationReturnCopy["en-US"][key];
}

function resolveVerificationReturnState(input: {
  language: ComposerLanguage;
  isFlashCard: boolean;
  practiceVerificationMode: PracticeVerificationMode;
  learningSubtype?: string;
  trainingExecutionState: TrainingExecutionState;
  latestTrainingNextHopReason?: string;
  latestTrainingBlockedBy?: string;
  latestVerifiedResult?: string;
  latestLearningBlocker?: string;
  latestLearningFollowup?: string;
}): TrainingVerificationReturnState {
  const manualPracticeCopy =
    !input.isFlashCard && input.practiceVerificationMode === "manual"
      ? resolveManualPracticeVerificationCopy(input.language, input.learningSubtype)
      : undefined;
  const trainingExecutionState = input.trainingExecutionState;
  const selectedStatus = trainingExecutionState.selectedStatus;
  const nextHopStatus = trainingExecutionState.nextHopStatus;
  const blocker = firstText(
    input.latestLearningBlocker,
    input.latestTrainingBlockedBy,
    nextHopStatus === "blocked" ? input.latestTrainingNextHopReason : undefined,
  );
  const blockedLike = trainingExecutionState.blocked;
  const needsPrimerLike = trainingExecutionState.needsPrimer;
  const skippedLike = trainingExecutionState.skipped;
  const verifiedLike = trainingExecutionState.verified;
  const pendingPlanConfirmationLike = trainingExecutionState.pendingPlanConfirmation;
  const flashAnsweredLike = trainingExecutionState.flashAnswered;
  const evidenceMissingLike = trainingExecutionState.verification.status === "evidence_missing";
  const copy = (key: TrainingVerificationReturnCopyKey) =>
    trainingVerificationReturnText(input.language, key);

  if (needsPrimerLike) {
    const flashRetry = input.isFlashCard;
    return {
      kind: "waiting",
      eyebrow: flashRetry ? copy("primerRetryEyebrow") : copy("primerStudyEyebrow"),
      title: flashRetry ? copy("primerRetryTitle") : copy("primerStudyTitle"),
      detail:
        firstText(
          input.latestLearningFollowup,
          flashRetry ? copy("primerRetryDetail") : copy("primerStudyDetail"),
        ) ?? "",
      next: flashRetry ? copy("primerRetryNext") : copy("primerStudyNext"),
    };
  }

  if (skippedLike) {
    return {
      kind: "needs-review",
      eyebrow: copy("skippedEyebrow"),
      title: copy("skippedTitle"),
      detail: firstText(input.latestLearningFollowup, copy("skippedDetail")) ?? "",
      next: copy("skippedNext"),
    };
  }

  if (input.isFlashCard) {
    if (blockedLike) {
      return {
        kind: selectedStatus === "blocked" ? "blocked" : "needs-review",
        eyebrow: copy("flashBlockedEyebrow"),
        title: copy("flashBlockedTitle"),
        detail: blocker || copy("flashBlockedDetailFallback"),
        next: copy("flashBlockedNext"),
      };
    }

    if (verifiedLike) {
      return {
        kind: "verified",
        eyebrow: copy("flashVerifiedEyebrow"),
        title: copy("flashVerifiedTitle"),
        detail: input.latestVerifiedResult?.trim() || copy("flashVerifiedDetailFallback"),
        next: copy("flashVerifiedNext"),
      };
    }

    if (flashAnsweredLike) {
      return {
        kind: "needs-review",
        eyebrow: copy("flashAnsweredEyebrow"),
        title: copy("flashAnsweredTitle"),
        detail: firstText(input.latestLearningFollowup, copy("flashAnsweredDetailFallback")) ?? "",
        next: copy("flashAnsweredNext"),
      };
    }

    if (evidenceMissingLike) {
      return {
        kind: "needs-review",
        eyebrow: copy("flashEvidenceMissingEyebrow"),
        title: copy("flashEvidenceMissingTitle"),
        detail: firstText(input.latestLearningFollowup, copy("flashEvidenceMissingDetailFallback")) ?? "",
        next: copy("flashEvidenceMissingNext"),
      };
    }

    return {
      kind: "waiting",
      eyebrow: copy("flashWaitingEyebrow"),
      title: copy("flashWaitingTitle"),
      detail: copy("flashWaitingDetail"),
      next: copy("flashWaitingNext"),
    };
  }

  if (blockedLike) {
    return {
      kind: selectedStatus === "blocked" ? "blocked" : "needs-review",
      eyebrow: copy("practiceBlockedEyebrow"),
      title:
        input.practiceVerificationMode === "manual"
          ? copy("practiceBlockedTitleManual")
          : copy("practiceBlockedTitleFile"),
      detail:
        blocker ||
        (input.practiceVerificationMode === "manual"
          ? copy("practiceBlockedDetailManual")
          : copy("practiceBlockedDetailFile")),
      next:
        input.practiceVerificationMode === "manual"
          ? manualPracticeCopy?.fallbackHint ?? copy("practiceBlockedNextManualFallback")
          : copy("practiceBlockedNextFile"),
    };
  }

  if (pendingPlanConfirmationLike) {
    return {
      kind: "pending-plan-confirmation",
      eyebrow: copy("pendingPlanEyebrow"),
      title: copy("pendingPlanTitle"),
      detail: input.latestVerifiedResult?.trim() || copy("pendingPlanDetailFallback"),
      next: copy("pendingPlanNext"),
    };
  }

  if (verifiedLike) {
    return {
      kind: "verified",
      eyebrow: copy("practiceVerifiedEyebrow"),
      title:
        input.practiceVerificationMode === "manual"
          ? copy("practiceVerifiedTitleManual")
          : copy("practiceVerifiedTitleFile"),
      detail:
        input.latestVerifiedResult?.trim() ||
        (input.practiceVerificationMode === "manual"
          ? copy("practiceVerifiedDetailManual")
          : copy("practiceVerifiedDetailFile")),
      next:
        input.practiceVerificationMode === "manual"
          ? copy("practiceVerifiedNextManual")
          : copy("practiceVerifiedNextFile"),
    };
  }

  if (evidenceMissingLike) {
    return {
      kind: "needs-review",
      eyebrow: copy("practiceEvidenceMissingEyebrow"),
      title: copy("practiceEvidenceMissingTitle"),
      detail:
        firstText(
          input.latestLearningFollowup,
          copy("practiceEvidenceMissingDetailFallback"),
        ) ?? "",
      next: copy("practiceEvidenceMissingNext"),
    };
  }

  return {
    kind: "waiting",
    eyebrow: copy("waitingEyebrow"),
    title: copy("waitingTitle"),
    detail:
      firstText(
        input.latestLearningFollowup,
        input.practiceVerificationMode === "manual"
          ? manualPracticeCopy?.verifyNote
          : copy("waitingDetailFile"),
      ) ?? "",
    next:
      input.practiceVerificationMode === "manual"
        ? copy("waitingNextManual")
        : copy("waitingNextFile"),
  };
}

export function TrainingWorkbenchView({
  response,
  onBackToLearning,
  language,
  cardType = "practice",
  trainingSubmode,
  cardOnly = false,
  cardId,
  selectedCardStatus,
  onCardStatusTransition,
  title,
  currentStep,
  learningFamily,
  learningSubtype,
  whyThisCard,
  targetSkill,
  problemStatement,
  suggestedWorkspaceAction,
  scenario,
  whyNow,
  sourceSummary,
  sourceDetail,
  apiHints = [],
  constraints = [],
  selfCheck = [],
  deliverable,
  deliverables = [],
  validationMethod,
  verificationMethod,
  verifyItems,
  successSignal,
  returnWith,
  nextAfterCompletion,
  fallbackAction,
  filesToTouch = [],
  hintLadder = [],
  commonMistakes = [],
  stuckRecovery,
  reflectionPrompt,
  restoredFocus,
  outcome,
  nextHop,
  coachSummary,
  currentFocus,
  scenarioPackLabel,
  latestTrainingHandoffStatus,
  latestTrainingLearningPhase,
  latestTrainingReliability,
  reliabilityInFlight = false,
  latestTrainingNextHopStatus,
  latestTrainingNextHopReason,
  latestTrainingBlockedBy,
  latestVerifiedResult,
  latestLearningBlocker,
  verificationNotice,
  latestLearningFollowup,
  skillProjection,
  reviewItems = [],
  reviewQueueOpenRequest = false,
  reviewSummary,
  onReviewQueueAction,
  recentWins = [],
  weakSpots = [],
  primaryAction,
  onVerifyCurrentFile,
  remoteVerification,
  remoteName,
  onStopRemoteVerification,
  onHintReveal,
  leftoverNote,
  actions,
  emptyState,
  onPreviousCard,
  onNextCard,
  onRefreshDeck,
  flashPrompt,
  expectedSymbols = [],
}: TrainingWorkbenchViewProps) {
  const leftoverStoredNote = leftoverNote?.trim() || "";
  // Batch 6: default to focus-area groups so the review queue reads as a few
  // coherent topics instead of a flat list of one-off decisions.
  const reviewFocusGroups = useMemo(
    () =>
      groupReviewQueueByFocusArea(
        reviewItems.map((item) => ({
          ...item,
          reason: item.detail ?? item.meta ?? item.title,
        })),
        [],
        trainingWorkbenchText(language, "ungrouped"),
      ),
    [reviewItems, language],
  );
  const cappedReviewGroups = useMemo(() => {
    let budget = 4;
    const groups: Array<{ focusArea: string; items: TrainingReviewItem[] }> = [];
    for (const group of reviewFocusGroups) {
      if (budget <= 0) {
        break;
      }
      const items = group.items.slice(0, budget);
      budget -= items.length;
      groups.push({ focusArea: group.focusArea, items });
    }
    return groups;
  }, [reviewFocusGroups]);
  const t = resolveWorkbenchCopy(language);
  const operationMessage = useWorkbenchState((state) => state.operationMessage);
  const cardGenerationPending = useWorkbenchState((state) => state.streaming.isStreaming);
  const handoffOwnerCardId = useWorkbenchState(
    (state) => state.data.workspaceTrainingState?.latestTrainingHandoff?.candidateId,
  );
  const mismatchRecovery = resolveTrainingCardMismatchRecovery({
    operationMessage,
    handoffOwnerCardId,
    selectedCardId: cardId,
  });
  // Focus mode: the card may live mounted in a background view, so the
  // per-card scroll jump only runs while training is the active view and
  // per-surface scroll restoration stays in charge everywhere else.
  const activeWorkbenchView = useWorkbenchState((state) => state.layout.activeView);
  const isFlashCard = cardType === "flash";
  const currentCardRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!reviewQueueOpenRequest && cardId && activeWorkbenchView === "training") {
      currentCardRef.current?.scrollIntoView({ block: "start" });
    }
  }, [cardId, reviewQueueOpenRequest, activeWorkbenchView]);
  const reviewQueueRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (reviewQueueOpenRequest && reviewItems.length > 0) {
      reviewQueueRef.current?.scrollIntoView({ block: "start" });
    }
  }, [reviewQueueOpenRequest, reviewItems.length]);
  const trainingExecutionState = deriveTrainingExecutionState({
    cardType: isFlashCard ? "flash" : "practice",
    trainingSubmode,
    selectedCardStatus,
    latestTrainingHandoffStatus,
    latestTrainingNextHopStatus,
    latestTrainingBlockedBy,
    latestVerifiedResult,
    latestLearningBlocker,
    learningPhase: latestTrainingLearningPhase,
  });
  const reliabilityRecord: TrainingReliabilityRecord | undefined =
    latestTrainingReliability?.requestId && latestTrainingReliability.phase
    ? {
        requestId: latestTrainingReliability.requestId,
        idempotencyKey: latestTrainingReliability.idempotencyKey ?? latestTrainingReliability.requestId,
        commandId: latestTrainingReliability.commandId ?? "",
        cardId: latestTrainingReliability.cardId,
        handoffId: latestTrainingReliability.handoffId,
        phase: latestTrainingReliability.phase,
        revision: latestTrainingReliability.revision ?? 1,
        snapshotRevision: latestTrainingReliability.snapshotRevision,
        createdAt: latestTrainingReliability.createdAt,
        updatedAt: latestTrainingReliability.updatedAt,
        ackedAt: latestTrainingReliability.ackedAt,
        timeoutAt: latestTrainingReliability.timeoutAt,
        cancelRequested: latestTrainingReliability.cancelRequested,
        outcome: latestTrainingReliability.outcome,
        error: latestTrainingReliability.error
          ? sanitizeErrorSurfaceText(latestTrainingReliability.error, language)
          : undefined,
        recoverable: latestTrainingReliability.recoverable,
        recoveryAction: latestTrainingReliability.recoveryAction,
        learningPhase: latestTrainingReliability.learningPhase,
      }
    : undefined;
  const reliabilityCopy = describeTrainingReliability({
    record: reliabilityRecord,
    localInFlight: reliabilityInFlight,
    language,
  });
  const needsPrimerState = trainingExecutionState.needsPrimer;
  const displayTitle = stripTrainingCardTitlePrefix(title);
  const visibleExpectedSymbols = expectedSymbols.map((symbol) => symbol.trim()).filter(Boolean).slice(0, 4);
  // r1-g1-5: scenario packs can ship unfilled placeholders ("<current failing
  // file>"). The renderer never shows them raw — an entry with no resolvable
  // value is dropped, and a files line with no entries left is omitted whole.
  const resolvedFilesToTouch = filesToTouch
    .map((file) => file.trim())
    .filter((file) => file.length > 0 && !/^<[^>]*>$/.test(file) && !file.includes("<current failing file>"));
  const practiceVerificationMode = resolvePracticeVerificationMode({
    isFlashCard,
    learningFamily,
    filesToTouch: resolvedFilesToTouch,
    apiHints,
    expectedSymbols: visibleExpectedSymbols,
  });
  const manualPracticeCopy = resolveManualPracticeVerificationCopy(language, learningSubtype);
  const flashPromptText = flashPrompt?.trim() || currentStep.trim() || title;
  const resolvedWhyNow = firstText(whyThisCard?.trim(), whyNow?.trim());
  const resolvedProblemStatement = firstText(
    cardOnly && !isFlashCard ? suggestedWorkspaceAction?.trim() : undefined,
    problemStatement?.trim(),
    isFlashCard ? flashPromptText : undefined,
    currentStep.trim(),
    suggestedWorkspaceAction?.trim(),
    title,
  ) ?? title;
  const resolvedReturnWith = firstText(returnWith?.trim());
  const resolvedNextAfterCompletion = firstText(nextAfterCompletion?.trim());
  const resolvedFallbackAction = firstText(fallbackAction?.trim(), stuckRecovery?.trim());
  const resolvedSuccessSignal = firstText(successSignal?.trim());
  const resolvedDeliverables = uniqueTrainingCardItems([deliverable, ...deliverables]);
  const resolvedVerifyItems = uniqueTrainingCardItems([
    validationMethod,
    verificationMethod,
    ...verifyItems,
  ]);
  const resolvedTargetSkill = firstText(targetSkill?.trim());
  const visibleNextAfterCompletion =
    resolvedNextAfterCompletion &&
    normalizeCardText(resolvedNextAfterCompletion) !== normalizeCardText(resolvedReturnWith) &&
    !isCurrentCardActionLabel(resolvedNextAfterCompletion)
      ? resolvedNextAfterCompletion
      : undefined;
  const hasPrimaryLoop =
    currentStep.trim().length > 0 ||
    resolvedDeliverables.length > 0 ||
    Boolean(resolvedWhyNow?.trim()) ||
    Boolean(outcome) ||
    Boolean(nextHop);
  const normalizedSuggestedWorkspaceAction = normalizeCardText(suggestedWorkspaceAction);
  const normalizedStep = normalizeCardText(currentStep);
  const suggestedWorkspaceActionPreview = suggestedWorkspaceAction?.trim()
    ? compactCardText(suggestedWorkspaceAction, 160)
    : undefined;
  const scenarioPreview = scenario?.trim() ? compactCardText(scenario, 140) : undefined;
  const shouldShowNextMove =
    Boolean(suggestedWorkspaceActionPreview) &&
    normalizedSuggestedWorkspaceAction.length > 0 &&
    normalizedSuggestedWorkspaceAction !== normalizedStep;
  const nextMovePrimary = shouldShowNextMove ? suggestedWorkspaceActionPreview : scenarioPreview;
  const nextMoveSecondary = shouldShowNextMove ? scenarioPreview : undefined;
  const nextMoveLabel = shouldShowNextMove
    ? trainingWorkbenchText(language, "startHere")
    : trainingWorkbenchText(language, "currentScenario");
  const whyNowPreview = resolvedWhyNow ? compactCardText(resolvedWhyNow, cardOnly ? 88 : 120) : undefined;
  const learnFirstDetailBase =
    firstText(
      whyNowPreview,
      shouldShowNextMove && nextMovePrimary ? `${nextMoveLabel}: ${nextMovePrimary}` : undefined,
      nextMoveSecondary
        ? `${trainingSurfaceLabel(language, "scenario")}: ${nextMoveSecondary}`
        : undefined,
      scenarioPackLabel
        ? `${trainingWorkbenchText(language, "scenarioPack")}: ${scenarioPackLabel}`
        : undefined,
    ) ?? trainingWorkbenchText(language, "readSliceFirst");
  const learnFirstDetail = cardOnly
    ? (firstText(sourceSummary?.trim(), sourceDetail?.trim()) ??
      trainingCardOnlyText(language, "learnFirst"))
    : learnFirstDetailBase;
  const hasLearnFirstBlock = Boolean(learnFirstDetail || resolvedTargetSkill);
  const verificationReturn = resolveVerificationReturnState({
    language,
    isFlashCard,
    practiceVerificationMode,
    learningSubtype,
    trainingExecutionState,
    latestTrainingNextHopReason,
    latestTrainingBlockedBy,
    latestVerifiedResult,
    latestLearningBlocker,
    latestLearningFollowup,
  });
  const learnPhaseActive =
    (needsPrimerState || isFlashCard) && hasLearnFirstBlock && verificationReturn.kind === "waiting";
  const defaultReturnPath = trainingCardOnlySurfaceText(language, "returnResultOrBlocker");
  const trainingLoopSteps = buildTrainingLoopSteps({
    language,
    composerPhase: trainingExecutionState.composerPhase,
  });
  const activeLoopStep =
    trainingLoopSteps.find((step) => step.state === "active") ??
    trainingLoopSteps[0] ?? {
      key: "learn" as const,
      label: trainingSurfaceLabel(language, "currentCard"),
      state: "upcoming" as const,
    };
  const practiceSectionNote =
    practiceVerificationMode === "file"
      ? cardOnly
        ? trainingWorkbenchText(language, "verifyFileNoteCardOnly")
        : trainingWorkbenchText(language, "verifyFileNote")
      : manualPracticeCopy.verifyNote;
  const cardOnlyTask = resolvedProblemStatement;
  const cardOnlyDeliverable = resolvedDeliverables.length > 1
    ? resolvedDeliverables.map(item => `- ${item.replace(/\n/g, "\n  ")}`).join("\n")
    : firstText(resolvedDeliverables[0]?.trim(), resolvedSuccessSignal, cardOnlyTask) ?? cardOnlyTask;
  // r2-g1-1: multi-item deliverables render as real list items (one row per
  // item) instead of the " - " joined run-on paragraph.
  const deliverablesListNode = resolvedDeliverables.length > 1 ? (
    <ul className="training-card-list" data-training-deliverables="true">
      {resolvedDeliverables.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  ) : null;
  const cardOnlyVerification = resolvedVerifyItems.length > 1
    ? resolvedVerifyItems.map(item => `- ${item.replace(/\n/g, "\n  ")}`).join("\n")
    : firstText(
        resolvedVerifyItems[0],
        resolvedSuccessSignal,
        isFlashCard
          ? trainingCardOnlySurfaceText(language, "flashAnswerMethod")
          : practiceVerificationMode === "file"
            ? trainingCardOnlySurfaceText(language, "currentFileDiagnostics")
            : practiceSectionNote,
      );
  const cardOnlyWhyNowSummary = compactCardText(firstText(resolvedWhyNow), 120);
  // A card often derives several of these fields from one source, so the same
  // sentence can surface twice ("当前训练动作" == "交付物"). Seed the seen set
  // with the title/task so the task-details disclosure never restates them.
  const cardOnlySeenValues = new Set([displayTitle, cardOnlyTask].filter(Boolean).map(normalizeCardText));
  const cardOnlyBlockerDistinct =
    latestLearningBlocker &&
    !cardOnlySeenValues.has(normalizeCardText(latestLearningBlocker)) &&
    normalizeCardText(latestLearningBlocker) !== normalizeCardText(displayTitle)
      ? latestLearningBlocker
      : null;
  // Return Contract: once the handoff acks "continued in chat", the card's job
  // is done — show the terminal state instead of a phase action (TASK 4).
  const returnContinuedInChat = latestTrainingNextHopStatus?.trim() === "continued_in_chat";
  const nextCardButton = onNextCard ? (
    <button
      type="button"
      className="template-back"
      data-training-next-card="true"
      disabled={cardGenerationPending}
      onClick={() => onNextCard()}
    >
      {t.nextCard}
    </button>
  ) : null;

  // One collapsed disclosure per card (TASK 2): source, reason, deliverable,
  // verify and return facts as plain text — no nested composer, no competing
  // disclosures. Hidden while the learn phase owns the card face.
  const cardTaskDetails = learnPhaseActive ? undefined : (
    <details className="template-disclosure" data-training-card-details="true">
      <summary>{trainingWorkbenchText(language, "taskDetails")}</summary>
      <div>
        {currentFocus?.trim() ? <p className="template-metadata" data-training-card-fact="focus">{currentFocus}</p> : null}
        {resolvedWhyNow ? <div data-training-card-fact="why-now" title={cardOnlyWhyNowSummary}><MessageRichContent body={resolvedWhyNow} language={language} /></div> : null}
        {sourceDetail ? <MessageRichContent body={sourceDetail} language={language} /> : null}
        {currentStep && normalizeCardText(currentStep) !== normalizeCardText(cardOnlyTask) ? <MessageRichContent body={currentStep} language={language} /> : null}
        <div data-training-card-fact="deliverable">{deliverablesListNode ?? <MessageRichContent body={cardOnlyDeliverable ?? ""} language={language} />}</div>
        <div data-training-card-fact="verify"><span className="template-metadata">{trainingWorkbenchText(language, "verifyNow")}</span><MessageRichContent body={cardOnlyVerification ?? ""} language={language} /></div>
        <div data-training-card-fact="return"><MessageRichContent body={resolvedReturnWith || defaultReturnPath} language={language} /></div>
        {visibleNextAfterCompletion ? (
          <div data-training-card-fact="after-this">
            <span className="template-metadata">{trainingCardOnlySurfaceText(language, "afterThis")}</span>
            <MessageRichContent body={visibleNextAfterCompletion} language={language} />
          </div>
        ) : null}
      </div>
    </details>
  );

  return (
    <section
      className={`workbench-pane training-pane training-pane--single-card${cardOnly ? " training-pane--card-only" : ""}`}
      data-training-card-id={cardId}
      data-training-leftover-not-live={leftoverStoredNote ? "true" : undefined}
    >
      {mismatchRecovery && onCardStatusTransition ? (
        <div className="training-card-recovery" role="alert" data-training-card-recovery="true">
          <p>{trainingWorkbenchText(language, "mismatchCardHint")}</p>
          <button
            type="button"
            className="button button--micro"
            data-training-card-recovery-switch="true"
            onClick={() =>
              onCardStatusTransition(
                mismatchRecovery.cardId,
                "active",
                trainingWorkbenchText(language, "mismatchRecoveryReason"),
              )
            }
          >
            {trainingWorkbenchText(language, "mismatchSwitchLabel")}
          </button>
        </div>
      ) : null}
      {leftoverStoredNote ? (
        <>
          <p
            className="coach-plan-view__leftover-note"
            data-training-leftover-note="true"
            role="status"
            aria-live="polite"
          >
            {leftoverStoredNote}
          </p>
          {primaryAction ? (
            <div
              className="training-current__actions training-current__actions--primary"
              role="group"
              aria-label={t.openCoach}
            >
              {primaryAction}
            </div>
          ) : null}
        </>
      ) : !hasPrimaryLoop && emptyState ? (
        <>
          {emptyState}
          {actions ? (
            <div
              className="training-current__actions"
              role="group"
              aria-label={t.openCoach}
            >
              {actions}
            </div>
          ) : null}
        </>
      ) : (
        <>
          <section ref={currentCardRef} className="training-current training-current--primary training-current--single-card">
            {cardOnly ? (
              <FocusedPractice
                parent={t.plan}
                label={trainingSurfaceLabel(language, "currentTrainingCard")}
                title={displayTitle}
                phase={trainingExecutionState.composerPhase === "answer" ? "try" : trainingExecutionState.composerPhase}
                phaseLabel={activeLoopStep.label}
                onBack={onBackToLearning}
                details={cardTaskDetails}
              >
                {verificationNotice ? <VerificationResult language={language} verdict="unknown" summary={verificationNotice} /> : null}
                {returnContinuedInChat ? (
                  <section
                    className="training-verification-return is-verified"
                    role="status"
                    aria-live="polite"
                    data-training-return-complete="true"
                  >
                    <span className="training-verification-return__rail" aria-hidden="true" />
                    <div className="training-verification-return__copy">
                      <span className="training-verification-return__eyebrow">{trainingWorkbenchText(language, "returnCompleteEyebrow")}</span>
                      <strong>{trainingWorkbenchText(language, "returnCompleteTitle")}</strong>
                      {latestVerifiedResult?.trim() ? <p>{latestVerifiedResult}</p> : null}
                      {actions ? <div className="training-verification-return__actions">{actions}</div> : null}
                      {nextCardButton}
                    </div>
                  </section>
                ) : trainingExecutionState.composerPhase === "learn" ? <>
                  <MessageRichContent body={learnFirstDetail ?? cardOnlyTask ?? ""} language={language} />
                  <NextAction label={templateCopy[language].nextAction} title={cardOnlyTask || displayTitle} action={{ label: trainingSurfaceLabel(language, "startStep"), disabled: !onCardStatusTransition || !cardId || reliabilityInFlight, onClick: () => { if (cardId) onCardStatusTransition?.(cardId, "active", "start_step"); } }} />
                </> : trainingExecutionState.composerPhase === "try" || trainingExecutionState.composerPhase === "answer" ? <>
                  <MessageRichContent body={isFlashCard ? flashPrompt || cardOnlyTask : cardOnlyTask} language={language} />
                  {resolvedFilesToTouch.length ? (
                    <p className="template-metadata training-card-files" data-training-files="true">
                      {resolvedFilesToTouch.map((file) => (
                        <span key={file} className="training-card-files__item">{file}</span>
                      ))}
                    </p>
                  ) : null}
                  {cardOnlyBlockerDistinct ? <VerificationResult language={language} verdict={trainingExecutionState.blocked ? "failed" : "unknown"} summary={cardOnlyBlockerDistinct} /> : null}
                  {selectedCardStatus === "candidate" || !selectedCardStatus ? (
                    <NextAction label={templateCopy[language].nextAction} title={cardOnlyTask || displayTitle} action={{ label: trainingSurfaceLabel(language, "startStep"), disabled: !onCardStatusTransition || !cardId || reliabilityInFlight, onClick: () => { if (cardId) onCardStatusTransition?.(cardId, "active", "start_step"); } }} />
                  ) : !isFlashCard && practiceVerificationMode === "file" ? (
                    <NextAction label={templateCopy[language].nextAction} title={trainingSurfaceLabel(language, "verifyStepTitle")} detail={deliverablesListNode ? <><span className="template-metadata">{templateCopy[language].complete}: </span>{deliverablesListNode}</> : `${templateCopy[language].complete}: ${cardOnlyDeliverable}`} action={{ label: remoteName ? remoteVerifyCopy(language).verifyOn(remoteName) : trainingSurfaceLabel(language, "verifyCurrentFile"), disabled: !onVerifyCurrentFile || Boolean(remoteVerification?.running) || reliabilityInFlight, onClick: () => onVerifyCurrentFile?.() }} />
                  ) : response}
                  {hintLadder.length && cardType === "practice" ? <HintLadderReveal hints={hintLadder} onReveal={onHintReveal} language={language} /> : null}
                </> : trainingExecutionState.composerPhase === "verify" ? <>
                  {trainingExecutionState.verified || trainingExecutionState.blocked ? (
                    <VerificationResult language={language} verdict={trainingExecutionState.verified ? "passed" : "failed"} summary={latestVerifiedResult || latestLearningBlocker} />
                  ) : <MessageRichContent body={cardOnlyVerification || practiceSectionNote} language={language} />}
                  {onVerifyCurrentFile ? <NextAction label={templateCopy[language].nextAction} title={trainingSurfaceLabel(language, "verifyStepTitle")} action={{ label: trainingSurfaceLabel(language, "verifyCurrentFile"), disabled: Boolean(remoteVerification?.running) || reliabilityInFlight, onClick: onVerifyCurrentFile }} /> : response}
                </> : trainingExecutionState.composerPhase === "reflect" ? response : <>
                  <MessageRichContent body={latestVerifiedResult || latestLearningBlocker || resolvedReturnWith || defaultReturnPath} language={language} />
                  {actions}
                  {nextCardButton}
                </>}
                {remoteVerification && (remoteVerification.running || remoteVerification.summary) ? <RemoteVerificationPanel verification={remoteVerification} remoteName={remoteName} language={language} onStop={onStopRemoteVerification} /> : null}
              </FocusedPractice>
            ) : null}
          </section>

          {reviewQueueOpenRequest && (reviewItems.length > 0 || reviewSummary?.trim()) ? (
            <details ref={reviewQueueRef} className="training-details" data-training-review-queue="true" open={reviewQueueOpenRequest}>
              <summary>{trainingWorkbenchText(language, "followUpReview")}</summary>

              {reviewSummary && reviewItems.length === 0 ? <p className="training-details__summary">{reviewSummary}</p> : null}

              {cappedReviewGroups.length > 0 ? (
                <div className="training-review-stack">
                  {cappedReviewGroups.map((group) => (
                    <section className="training-review-group" key={group.focusArea}>
                      <h4 className="training-review-group__head">
                        <span>{group.focusArea}</span>
                        <span className="training-review-group__count">{group.items.length}</span>
                      </h4>
                      {group.items.map((item) => (
                        <article className="training-review-row" key={item.id}>
                          <h4>{item.title}</h4>
                          {item.detail ? <p>{item.detail}</p> : null}
                          {item.meta ? <p className="muted">{item.meta}</p> : null}
                          {item.fsrs ? (
                            <p className="training-review-row__memory muted">
                              {item.fsrs.intervalDays !== undefined
                                ? `${trainingWorkbenchText(language, "fsrsInterval")} ${item.fsrs.intervalDays} ${trainingWorkbenchText(language, "reviewDayUnit")}`
                                : null}
                              {item.fsrs.intervalDays !== undefined && item.fsrs.masteryScore !== undefined ? " · " : null}
                              {item.fsrs.masteryScore !== undefined
                                ? `${trainingWorkbenchText(language, "fsrsMastery")} ${item.fsrs.masteryScore}`
                                : null}
                            </p>
                          ) : null}
                          <details className="training-review-row__actions-details">
                            <summary>{trainingWorkbenchText(language, "reviewActions")}</summary>
                            <div
                              className="training-review-row__actions"
                              aria-label={trainingWorkbenchText(language, "reviewActions")}
                            >
                              {(["accept", "snooze"] as const).map((action) => (
                                <button
                                  className="button button--ghost"
                                  key={action}
                                  type="button"
                                  onClick={() => onReviewQueueAction?.({
                                    concept: item.concept,
                                    action,
                                    focusArea: item.focusArea,
                                    taskHint: item.taskHint,
                                  })}
                                >
                                  {trainingWorkbenchText(
                                    language,
                                    action === "accept" ? "reviewAccept" : "reviewSnooze",
                                  )}
                                </button>
                              ))}
                              <details className="training-review-row__more">
                                <summary>{trainingWorkbenchText(language, "moreLabel")}</summary>
                                <div className="training-review-row__more-actions">
                                  {(["reset", "skip", "done"] as const).map((action) => (
                                    <button
                                      className="button button--ghost"
                                      key={action}
                                      type="button"
                                      onClick={() => onReviewQueueAction?.({
                                        concept: item.concept,
                                        action,
                                        focusArea: item.focusArea,
                                        taskHint: item.taskHint,
                                      })}
                                    >
                                      {trainingWorkbenchText(
                                        language,
                                        action === "reset"
                                          ? "reviewReset"
                                          : action === "skip"
                                            ? "reviewSkip"
                                            : "reviewDone",
                                      )}
                                    </button>
                                  ))}
                                </div>
                              </details>
                            </div>
                          </details>
                        </article>
                      ))}
                    </section>
                  ))}
                </div>
              ) : null}
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}


function HintLadderReveal({
  hints,
  onReveal,
  language,
}: {
  hints: string[];
  onReveal?: (hintLevel: number) => void;
  language: ComposerLanguage;
}) {
  const [revealed, setRevealed] = useState(0);
  const total = hints.length;
  const allRevealed = revealed >= total;
  return (
    <div
      className="training-hint-reveal"
      role="group"
      aria-label={trainingWorkbenchText(language, "hintLadderLabel")}
    >
      {revealed > 0 ? (
        <ul className="training-hint-reveal__list">
          {hints.slice(0, revealed).map((hint, index) => (
            <li key={hint}>
              <span className="training-hint-reveal__index">{index + 1}</span>
              {hint}
            </li>
          ))}
        </ul>
      ) : null}
      {!allRevealed ? (
        <button
          type="button"
          className="toolbar-button training-hint-reveal__button"
          onClick={() => {
            const next = Math.min(revealed + 1, total);
            setRevealed(next);
            onReveal?.(next);
          }}
        >
          {`${trainingWorkbenchText(language, "hintProgressPrefix")} ${revealed + 1}/${total}`}
        </button>
      ) : null}
    </div>
  );
}
