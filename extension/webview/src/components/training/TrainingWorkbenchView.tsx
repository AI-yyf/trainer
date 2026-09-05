import type { ReactNode } from "react";

import {
  deriveTrainingExecutionState,
  type TrainingExecutionState,
} from "../../../../../shared/src/trainingExecutionGovernance";
import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";
import {
  describeTrainingReliability,
  type TrainingReliabilityRecord,
} from "../../../../../shared/src/trainingReliabilityGovernance";
import type { TrainingReliability } from "../../lib/types";
import { CheckMarkIcon, ChevronRightIcon, SparklesIcon, TargetIcon } from "../icons";
import { CollapseSection } from "../common/CollapseSection";
import { resolveCopy as resolveWorkbenchCopy } from "../../lib/i18n/copy";
import type { ComposerLanguage, TrainingCardType } from "../../lib/types";
import { useWorkbenchState } from "../../app/useWorkbenchState";
import type { TrainingCardStatus } from "../../../../../shared/src/trainingCardRouting";

export type TrainingReviewAction = "accept" | "snooze" | "reset" | "skip" | "done";
export type TrainingCardGrade = "again" | "hard" | "good" | "easy";

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
  latestLearningFollowup?: string;
  reviewItems?: TrainingReviewItem[];
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
  leftoverNote?: string;
  actions?: ReactNode;
  emptyState?: ReactNode;
  onPreviousCard?: () => void;
  onNextCard?: () => void;
  onRefreshDeck?: () => void;
  flashPrompt?: string;
  expectedSymbols?: string[];
}

function SectionHeading({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <span className="training-current__section-head">
      <span className="training-current__section-icon" aria-hidden="true">
        {icon}
      </span>
      <span className="training-current__section-label">{label}</span>
    </span>
  );
}

function TrainingCarryoverRow({ card }: { card: TrainingSummaryCard }) {
  return (
    <article className="training-carryover-row">
      <h4>{card.title}</h4>
      {card.detail ? <p>{card.detail}</p> : null}
      {card.meta ? <p className="training-loop-card__meta">{card.meta}</p> : null}
    </article>
  );
}

export type TrainingComposerCardCommand =
  | { kind: "skip" }
  | { kind: "grade"; grade: TrainingCardGrade };

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

export function interpretTrainingComposerCardCommand(
  text: string,
): TrainingComposerCardCommand | undefined {
  const normalized = text.replace(/\s+/g, " ").trim().toLowerCase();
  if (!normalized) {
    return undefined;
  }
  if (/^(跳过(?:这张)?|先跳过|skip(?: this(?: card)?)?)$/u.test(normalized)) {
    return { kind: "skip" };
  }
  if (/^(再来一次|again)$/u.test(normalized)) {
    return { kind: "grade", grade: "again" };
  }
  if (/^(有点难|hard)$/u.test(normalized)) {
    return { kind: "grade", grade: "hard" };
  }
  if (/^(这张我会了|我会了|不错|good)$/u.test(normalized)) {
    return { kind: "grade", grade: "good" };
  }
  if (/^(太简单了|easy)$/u.test(normalized)) {
    return { kind: "grade", grade: "easy" };
  }
  return undefined;
}

export function applyTrainingCardSkip(
  onCardStatusTransition: TrainingWorkbenchViewProps["onCardStatusTransition"],
  cardId: string | undefined,
  language: ComposerLanguage,
  leftoverStoredNote?: string,
): boolean {
  const normalizedCardId = cardId?.trim() || "";
  if (!normalizedCardId || !onCardStatusTransition || leftoverStoredNote) {
    return false;
  }
  onCardStatusTransition(
    normalizedCardId,
    "skipped",
    language === "zh-CN" ? "学员跳过" : "Learner skipped",
  );
  return true;
}

export function applyTrainingCardGrade(
  onCardStatusTransition: TrainingWorkbenchViewProps["onCardStatusTransition"],
  cardId: string | undefined,
  language: ComposerLanguage,
  grade: TrainingCardGrade,
  leftoverStoredNote?: string,
): boolean {
  const normalizedCardId = cardId?.trim() || "";
  if (!normalizedCardId || !onCardStatusTransition || leftoverStoredNote) {
    return false;
  }
  const reason =
    grade === "again"
      ? language === "zh-CN"
        ? "自评：再来一次"
        : "Self-grade: again"
      : grade === "hard"
        ? language === "zh-CN"
          ? "自评：有点难"
          : "Self-grade: hard"
        : grade === "good"
          ? language === "zh-CN"
            ? "自评：不错"
            : "Self-grade: good"
          : language === "zh-CN"
            ? "自评：太简单了"
            : "Self-grade: easy";
  onCardStatusTransition(normalizedCardId, "reviewed", reason);
  return true;
}

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
  const isZh = language === "zh-CN";
  if (language !== "zh-CN" && language !== "en-US") {
    return manualPracticeFallbackCopy[language] ?? manualPracticeFallbackCopy["en-US"];
  }
  if (normalizedSubtype === "derivation") {
    return {
      tryNote: isZh ? "先写出一个最小可检查的推导步骤。" : "Land one small derivation step you can inspect.",
      verifyNote: isZh ? "逐行检查关键步骤，或把结果代回去确认它成立。" : "Check the key step line by line, or substitute it back to confirm it holds.",
      shortcut: isZh ? "检查关键步骤" : "Check the key step",
      composerHint: isZh ? "用下方输入框写出这一步怎么成立，或指出卡住的具体行。" : "Use the composer below to explain why the step holds, or name the exact line that is blocked.",
      fallbackHint: isZh ? "卡住时先退回到第一条你能证明的步骤。" : "If blocked, return to the first step you can prove.",
    };
  }
  if (normalizedSubtype === "writing") {
    return {
      tryNote: isZh ? "先写出一个最小的改写、对比或解释。" : "Land one short rewrite, comparison, or explanation.",
      verifyNote: isZh ? "对照原句和你的判断，说明为什么这个表达更合适。" : "Compare the exact phrase against your judgment and explain why it fits better.",
      shortcut: isZh ? "检查句子和判断" : "Check the sentence and judgment",
      composerHint: isZh ? "用下方输入框写出你的语言选择，或指出目前还说不清的地方。" : "Use the composer below to state the language choice, or name what is still unclear.",
      fallbackHint: isZh ? "卡住时把范围缩回一个句子或一个对比。" : "If blocked, shrink the scope back to one sentence or one contrast.",
    };
  }
  if (normalizedSubtype === "memorization") {
    return {
      tryNote: isZh ? "先完成一轮最小闭卷回忆。" : "Complete one tiny closed-book recall first.",
      verifyNote: isZh ? "先回忆，再打开资料核对，标出真正漏掉的点。" : "Recall first, then reopen the source and mark the real gap.",
      shortcut: isZh ? "回忆后核对" : "Recall, then check",
      composerHint: isZh ? "用下方输入框记录你记住了什么、漏掉了什么，或哪一组还会混淆。" : "Use the composer below to record what you recalled, missed, or still confuse.",
      fallbackHint: isZh ? "卡住时把这组内容缩回两个点和一个对比。" : "If blocked, shrink the cluster back to two points and one contrast.",
    };
  }
  if (normalizedSubtype === "reading") {
    return {
      tryNote: isZh ? "先写下一条窄判断和一条支撑它的证据。" : "Write one narrow claim and one piece of evidence first.",
      verifyNote: isZh ? "指出具体片段，并解释它为什么真的支撑这个判断。" : "Point to the exact excerpt and explain why it really supports the claim.",
      shortcut: isZh ? "检查片段和判断" : "Check the excerpt and claim",
      composerHint: isZh ? "用下方输入框写出你的判断和证据，或指出目前最不够扎实的那一处。" : "Use the composer below to write the claim and evidence, or name the weakest point.",
      fallbackHint: isZh ? "卡住时只保留一个句子、一个意象或一个场景。" : "If blocked, shrink the scope to one sentence, image, or scene.",
    };
  }
  return {
    tryNote: isZh ? "先落下一条最小解释、例子或结果。" : "Land one small explanation, example, or result first.",
    verifyNote: isZh ? "指出你用来证明这张卡的那个例子、片段或解释。" : "Point to the exact example, excerpt, or explanation that proves this card.",
    shortcut: isZh ? "检查证据和解释" : "Check evidence and explanation",
    composerHint: isZh ? "用下方输入框记录你已验证的结果，或指出当前 blocker。" : "Use the composer below to record the verified result or the current blocker.",
    fallbackHint: isZh ? "卡住时先把范围缩回一个最小例子。" : "If blocked, shrink the scope back to one minimum example.",
  };
}

type TrainingLoopStepKey = "learn" | "try" | "verify" | "reflect" | "return";
type TrainingLoopStepState = "done" | "active" | "upcoming";

interface TrainingLoopStep {
  key: TrainingLoopStepKey;
  label: string;
  state: TrainingLoopStepState;
}

interface TrainingCardOnlySection {
  key: "current" | "why-now" | "deliverable" | "verify" | "return" | "reliability";
  label: string;
  title?: string;
  detail?: string;
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
  | "checks";

const trainingSurfaceLabels: Record<
  ComposerLanguage,
  Record<TrainingSurfaceLabelKey, string>
> = {
  "zh-CN": {
    currentCard: "当前卡片", flash: "闪记", practice: "实战", primer: "学习", review: "复盘",
    scenario: "场景", transfer: "迁移", theory: "理论", code: "代码", requirements: "具体要求",
    currentTrainingCard: "当前训练卡片", trainingLoop: "学习循环", codeSymbols: "将检查的代码符号", checks: "检查",
  },
  "en-US": {
    currentCard: "Current card", flash: "Flash", practice: "Practice", primer: "Primer", review: "Review",
    scenario: "Scenario", transfer: "Transfer", theory: "Theory", code: "Code", requirements: "Requirements",
    currentTrainingCard: "Current training card", trainingLoop: "Training loop", codeSymbols: "Code symbols to check", checks: "Checks",
  },
  "es-ES": {
    currentCard: "Tarjeta actual", flash: "Tarjeta", practice: "Práctica", primer: "Base", review: "Repaso",
    scenario: "Escenario", transfer: "Transferencia", theory: "Teoría", code: "Código", requirements: "Requisitos",
    currentTrainingCard: "Tarjeta de entrenamiento actual", trainingLoop: "Ciclo de aprendizaje", codeSymbols: "Símbolos de código a comprobar", checks: "Comprobaciones",
  },
  "fr-FR": {
    currentCard: "Carte actuelle", flash: "Carte", practice: "Exercice", primer: "Base", review: "Révision",
    scenario: "Scénario", transfer: "Transfert", theory: "Théorie", code: "Code", requirements: "Exigences",
    currentTrainingCard: "Carte d'entraînement actuelle", trainingLoop: "Boucle d'apprentissage", codeSymbols: "Symboles de code à vérifier", checks: "Vérifications",
  },
  "de-DE": {
    currentCard: "Aktuelle Karte", flash: "Karte", practice: "Übung", primer: "Grundlage", review: "Wiederholung",
    scenario: "Szenario", transfer: "Transfer", theory: "Theorie", code: "Code", requirements: "Anforderungen",
    currentTrainingCard: "Aktuelle Trainingskarte", trainingLoop: "Lernzyklus", codeSymbols: "Zu prüfende Codesymbole", checks: "Prüfungen",
  },
  "ja-JP": {
    currentCard: "現在のカード", flash: "カード", practice: "練習", primer: "導入", review: "復習",
    scenario: "場面", transfer: "転移", theory: "理論", code: "コード", requirements: "要件",
    currentTrainingCard: "現在のトレーニングカード", trainingLoop: "学習サイクル", codeSymbols: "確認するコードシンボル", checks: "確認",
  },
  "ko-KR": {
    currentCard: "현재 카드", flash: "카드", practice: "연습", primer: "기초", review: "복습",
    scenario: "시나리오", transfer: "전이", theory: "이론", code: "코드", requirements: "요구 사항",
    currentTrainingCard: "현재 훈련 카드", trainingLoop: "학습 순환", codeSymbols: "확인할 코드 기호", checks: "확인",
  },
  "pt-BR": {
    currentCard: "Cartão atual", flash: "Cartão", practice: "Prática", primer: "Base", review: "Revisão",
    scenario: "Cenário", transfer: "Transferência", theory: "Teoria", code: "Código", requirements: "Requisitos",
    currentTrainingCard: "Cartão de treinamento atual", trainingLoop: "Ciclo de aprendizagem", codeSymbols: "Símbolos de código para verificar", checks: "Verificações",
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
  const isZh = input.language === "zh-CN";
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

  if (needsPrimerLike) {
    const flashRetry = input.isFlashCard;
    return {
      kind: "waiting",
      eyebrow: flashRetry ? (isZh ? "\u9700\u8981\u518d\u7b54" : "Retry needed") : isZh ? "\u5148\u5b66" : "Study first",
      title: flashRetry ? (isZh ? "\u5148\u5de9\u56fa\u8fd9\u6761\u89c4\u5219\uff0c\u518d\u7b54\u4e00\u6b21" : "Reinforce the rule, then answer again") : isZh ? "\u5148\u5efa\u7acb\u6700\u5c0f\u7406\u89e3" : "Build the smallest understanding first",
      detail:
        firstText(
          input.latestLearningFollowup,
          flashRetry
            ? isZh
              ? "\u521a\u624d\u7684\u7b54\u6848\u8fd8\u6ca1\u7a33\u4f4f\uff1b\u8fd9\u5f20\u5361\u4fdd\u6301\u5728\u5f53\u524d\u8bad\u7ec3\u91cc\uff0c\u4e0d\u4f1a\u7b97\u4f5c\u5b8c\u6210\u3002"
              : "The last answer was not stable yet; this card stays active and is not counted as complete."
            : isZh
              ? "\u8fd9\u5f20\u5361\u8fd8\u4e0d\u9002\u5408\u76f4\u63a5\u52a8\u624b\uff0c\u5148\u770b primer \u518d\u56de\u6765\u3002"
              : "This card is not ready for direct execution yet; open the primer first.",
        ) ?? "",
      next: flashRetry ? (isZh ? "\u770b\u63d0\u793a\u6216\u5de9\u56fa\u6750\u6599\uff0c\u518d\u7b54\u540c\u4e00\u5f20\u5361\u3002" : "Review the hint or primer, then answer the same card again.") : isZh ? "\u5148\u8bfb\u5b8c primer\uff0c\u518d\u56de\u5230\u540c\u4e00\u5f20\u5361\u3002" : "Finish the primer, then return to the same card.",
    };
  }

  if (skippedLike) {
    return {
      kind: "needs-review",
      eyebrow: isZh ? "\u5df2\u8df3\u8fc7" : "Skipped",
      title: isZh ? "\u5148\u6536\u7d27\u5165\u53e3\uff0c\u518d\u56de\u6765" : "Narrow the entry, then return",
      detail:
        firstText(
          input.latestLearningFollowup,
          isZh
            ? "\u8fd9\u5f20\u5361\u6682\u65f6\u8df3\u8fc7\u4e86\uff0c\u73b0\u5728\u5148\u628a\u5165\u53e3\u6539\u6210\u66f4\u5c0f\u7684\u5207\u7247\u3002"
            : "This card was skipped for now, so the next step is to reopen it with a smaller slice.",
        ) ?? "",
      next: isZh ? "\u5148\u9009\u4e00\u4e2a\u66f4\u5c0f\u7684\u5165\u53e3\uff0c\u518d\u56de\u5230\u5f53\u524d\u4e3b\u7ebf\u3002" : "Choose a smaller entry point, then return to the current thread.",
    };
  }

  if (input.isFlashCard) {
    if (blockedLike) {
      return {
        kind: selectedStatus === "blocked" ? "blocked" : "needs-review",
        eyebrow: isZh ? "\u672a\u7a33\u4f4f" : "Needs review",
        title: isZh ? "\u5148\u6536\u7d27\u8fd9\u6761\u89c4\u5219" : "Tighten the rule first",
        detail:
          blocker ||
          (isZh
            ? "\u8fd9\u4e2a\u7b54\u6848\u8fd8\u6ca1\u7a33\u5b9a\u5230\u53ef\u4ee5\u5e26\u56de\u4e3b\u7ebf\u3002"
            : "This answer is not stable enough to carry back yet."),
        next: isZh ? "\u5148\u8865\u4e0a\u7f3a\u7684\u8bc1\u636e\uff0c\u518d\u7b80\u8ff0\u4e00\u6b21\u3002" : "Add the missing proof, then restate it once.",
      };
    }

    if (verifiedLike) {
      return {
        kind: "verified",
        eyebrow: isZh ? "\u5df2\u4f5c\u7b54" : "Answer checked",
        title: isZh ? "\u5148\u590d\u76d8\u8fd9\u6761\u5df2\u9a8c\u8bc1\u89c4\u5219" : "Reflect on this verified rule",
        detail:
          input.latestVerifiedResult?.trim() ||
          (isZh ? "\u8fd9\u5f20\u95ea\u8bb0\u5361\u5df2\u7ecf\u5b8c\u6210\u3002" : "This flash card is completed."),
        next: isZh ? "\u5148\u7528\u4e00\u53e5\u8bdd\u8bf4\u6e05\u5b83\u4e3a\u4ec0\u4e48\u6210\u7acb\uff0c\u518d\u56de\u6d41\u3002" : "State why it holds in one sentence, then return.",
      };
    }

    if (flashAnsweredLike) {
      return {
        kind: "needs-review",
        eyebrow: isZh ? "\u5df2\u4f5c\u7b54" : "Answered",
        title: isZh ? "\u628a\u7b54\u6848\u538b\u6210\u4e00\u6761\u89c4\u5219" : "Compress the answer into one rule",
        detail:
          firstText(
            input.latestLearningFollowup,
            isZh ? "\u73b0\u5728\u7528\u4e00\u53e5\u8bdd\u8bf4\u51fa\u8fd9\u5f20\u5361\u771f\u6b63\u60f3\u8ba9\u4f60\u8bb0\u4f4f\u7684\u89c4\u5219\u3002" : "Now say the one rule this card wants you to retain.",
          ) ?? "",
        next: isZh ? "\u590d\u76d8\u4e00\u6b21\uff0c\u518d\u628a\u89c4\u5219\u5e26\u56de\u4e3b\u7ebf\u3002" : "Reflect once, then bring the rule back.",
      };
    }

    if (evidenceMissingLike) {
      return {
        kind: "needs-review",
        eyebrow: isZh ? "\u7f3a\u5c11\u8bc1\u636e" : "Evidence missing",
        title: isZh ? "\u5148\u8865\u4e0a\u8fd9\u6b21\u7b54\u6848\u7684\u4f9d\u636e" : "Add the evidence for this answer",
        detail:
          firstText(
            input.latestLearningFollowup,
            isZh ? "\u8fd8\u6ca1\u6709\u53ef\u8ffd\u6eaf\u7684\u7b54\u6848\u4f9d\u636e\u3002" : "There is no traceable evidence for this answer yet.",
          ) ?? "",
        next: isZh ? "\u5728\u8f93\u5165\u6846\u8bb0\u4e0b\u89c4\u5219\u548c\u4f9d\u636e\uff0c\u518d\u590d\u76d8\u3002" : "Record the rule and its evidence in the composer, then reflect.",
      };
    }

    return {
      kind: "waiting",
      eyebrow: isZh ? "\u95ea\u8bb0" : "Flash",
      title: isZh ? "\u9009\u62e9 /\u586b\u7a7a /\u7b80\u7b54" : "Choice / fill / short answer",
      detail: isZh ? "\u4e0d\u8bfb IDE \u6587\u4ef6\u3002" : "No IDE file read.",
      next: isZh ? "\u63d0\u4ea4\u7b54\u6848\u3002" : "Submit an answer.",
    };
  }

  if (blockedLike) {
    return {
      kind: selectedStatus === "blocked" ? "blocked" : "needs-review",
      eyebrow: isZh ? "\u672a\u901a\u8fc7" : "Needs work",
      title:
        input.practiceVerificationMode === "manual"
          ? isZh
            ? "\u5148\u6536\u7d27\u8fd9\u4e00\u8f6e\u9a8c\u8bc1"
            : "Tighten this verification round first"
          : isZh
            ? "\u5148\u4fee\u5f53\u524d\u6587\u4ef6"
            : "Fix the current file first",
      detail:
        blocker ||
        (input.practiceVerificationMode === "manual"
          ? isZh
            ? "\u8fd8\u9700\u8981\u4e00\u6761\u66f4\u7a33\u7684\u89e3\u91ca\u3001\u4f8b\u5b50\uff0c\u6216\u8bc1\u636e\u3002"
            : "This still needs one tighter explanation, example, or proof."
          : isZh
            ? "\u8fd8\u6ca1\u8fbe\u5230\u901a\u8fc7\u6761\u4ef6\u3002"
            : "Pass condition not met yet."),
      next:
        input.practiceVerificationMode === "manual"
          ? manualPracticeCopy?.fallbackHint ??
            (isZh ? "\u5148\u7f29\u56de\u5230\u4e00\u4e2a\u66f4\u5c0f\u7684\u53ef\u8bc1\u660e\u6b65\u9aa4\u3002" : "Return to one smaller step you can prove.")
          : isZh
            ? "\u4fee\u5b8c\u518d\u9a8c\u3002"
            : "Fix it, then verify again.",
    };
  }

  if (pendingPlanConfirmationLike) {
    return {
      kind: "pending-plan-confirmation",
      eyebrow: isZh ? "\u5df2\u9a8c\u8bc1\uff0c\u5f85\u8ba1\u5212\u786e\u8ba4" : "Verified, plan confirmation pending",
      title: isZh ? "\u8fd9\u6b21\u8bc1\u636e\u5df2\u9a8c\u8bc1\uff0c\u4f46\u8fd8\u4e0d\u662f\u6b63\u5f0f\u8ba1\u5212\u5b8c\u6210" : "Evidence is verified; the formal plan is not complete",
      detail:
        input.latestVerifiedResult?.trim() ||
        (isZh ? "IDE \u6216\u95ea\u8bb0\u9a8c\u8bc1\u5df2\u901a\u8fc7\uff0c\u7b49\u5f85 Coach \u786e\u8ba4\u662f\u5426\u66f4\u65b0\u6b63\u5f0f\u8ba1\u5212\u3002" : "The IDE or flash evidence passed; Coach must confirm any formal plan change."),
      next: isZh ? "先复盘，再把证据带回 Coach 确认计划下一步。" : "Reflect, then bring the evidence to Coach to confirm the next plan step.",
    };
  }

  if (verifiedLike) {
    return {
      kind: "verified",
      eyebrow: isZh ? "\u5df2\u901a\u8fc7" : "Verified",
      title:
        input.practiceVerificationMode === "manual"
          ? isZh
            ? "\u5148\u590d\u76d8\u8fd9\u5f20\u5df2\u9a8c\u8bc1\u7ec3\u4e60\u5361"
            : "Reflect on this verified practice card"
          : isZh
            ? "\u5148\u590d\u76d8\u8fd9\u6b21\u5b9e\u6218\u8bc1\u636e"
            : "Reflect on this verified evidence",
      detail:
        input.latestVerifiedResult?.trim() ||
        (input.practiceVerificationMode === "manual"
          ? isZh
            ? "\u8fd9\u4e00\u8f6e\u89e3\u91ca\u6216\u4f8b\u5b50\u5df2\u7ecf\u8db3\u591f\u7a33\u3002"
            : "This explanation or example is grounded enough to continue."
          : isZh
            ? "\u5f53\u524d\u6587\u4ef6\u5df2\u901a\u8fc7\u3002"
            : "Current file passed."),
      next:
        input.practiceVerificationMode === "manual"
          ? isZh
            ? "\u5148\u8bf4\u6e05\u695a\u4f60\u7528\u7684\u8bc1\u636e\u6216\u5173\u952e\u6b65\uff0c\u518d\u56de\u6d41\u3002"
            : "Name the proof or key step you used, then return."
          : isZh
            ? "\u5148\u8bf4\u6e05\u695a\u662f\u54ea\u6761\u8bc1\u636e\u8ba9\u5b83\u901a\u8fc7\uff0c\u518d\u56de\u6d41\u3002"
            : "Name the proof that made it pass, then return.",
    };
  }

  if (evidenceMissingLike) {
    return {
      kind: "needs-review",
      eyebrow: isZh ? "\u7f3a\u5c11\u8bc1\u636e" : "Evidence missing",
      title: isZh ? "\u5148\u8865\u4e0a\u8fd9\u6b21\u7ec3\u4e60\u7684\u4f9d\u636e" : "Add the evidence for this practice",
      detail:
        firstText(
          input.latestLearningFollowup,
          isZh ? "\u5b9e\u73b0\u4e0d\u7b49\u4e8e\u901a\u8fc7\uff0c\u8fd8\u9700\u8981\u4e00\u6761\u53ef\u8ffd\u6eaf\u7684\u9a8c\u8bc1\u7ed3\u679c\u3002" : "Implementation is not a pass; a traceable verification result is still needed.",
        ) ?? "",
      next: isZh ? "\u5728\u8f93\u5165\u6846\u8bb0\u5f55\u9a8c\u8bc1\u7ed3\u679c\u6216 blocker\uff0c\u518d\u590d\u76d8\u3002" : "Record the verification result or blocker in the composer, then reflect.",
    };
  }

  return {
    kind: "waiting",
    eyebrow: isZh ? "\u5f85\u9a8c" : "Waiting",
    title: isZh ? "\u5148\u843d\u5730\u4e00\u4e2a\u6700\u5c0f\u53ef\u4ea4\u4ed8\u7ed3\u679c" : "Land the smallest deliverable first",
    detail:
      firstText(
        input.latestLearningFollowup,
        input.practiceVerificationMode === "manual"
          ? manualPracticeCopy?.verifyNote
          : isZh
            ? "\u5b9e\u6218\u5361\u8981\u8bfb\u5f53\u524d IDE \u6587\u4ef6\u3002"
            : "Practice cards read the current IDE file.",
      ) ?? "",
    next:
      input.practiceVerificationMode === "manual"
        ? isZh
          ? "\u5728\u4e0b\u65b9\u8f93\u5165\u6846\u8bb0\u5f55\u7ed3\u679c\u6216 blocker\u3002"
          : "Record the result or blocker in the composer below."
        : isZh
          ? "\u5199\u5b8c\u540e\u9a8c\u8bc1\u3002"
          : "Verify after editing.",
  };
}

export function TrainingWorkbenchView({
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
  latestLearningFollowup,
  reviewItems = [],
  reviewSummary,
  onReviewQueueAction,
  recentWins = [],
  weakSpots = [],
  primaryAction,
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
  const isZh = language === "zh-CN";
  const t = resolveWorkbenchCopy(language);
  const operationMessage = useWorkbenchState((state) => state.operationMessage);
  const handoffOwnerCardId = useWorkbenchState(
    (state) => state.data.workspaceTrainingState?.latestTrainingHandoff?.candidateId,
  );
  const mismatchRecovery = resolveTrainingCardMismatchRecovery({
    operationMessage,
    handoffOwnerCardId,
    selectedCardId: cardId,
  });
  const isFlashCard = cardType === "flash";
  const normalizedTrainingSubmode = (trainingSubmode ?? "")
    .trim()
    .toLowerCase()
    .replace(/_/g, "-");
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
  const isReviewSubmode = normalizedTrainingSubmode === "review";
  const isScenarioSubmode = normalizedTrainingSubmode === "scenario";
  const isTransferSubmode = normalizedTrainingSubmode === "transfer";
  const displayTitle = stripTrainingCardTitlePrefix(title);
  const visibleExpectedSymbols = expectedSymbols.map((symbol) => symbol.trim()).filter(Boolean).slice(0, 4);
  const currentCardLabel = trainingSurfaceLabel(language, "currentCard");
  const cardTypeLabel = isFlashCard
    ? trainingSurfaceLabel(language, "flash")
    : trainingSurfaceLabel(language, "practice");
  const toplineLabel = cardOnly ? cardTypeLabel : currentCardLabel;
  const trainingTrackLabel =
    needsPrimerState
      ? trainingSurfaceLabel(language, "primer")
      : isReviewSubmode
        ? trainingSurfaceLabel(language, "review")
        : isScenarioSubmode
          ? trainingSurfaceLabel(language, "scenario")
          : isTransferSubmode
            ? trainingSurfaceLabel(language, "transfer")
            : isFlashCard
              ? trainingSurfaceLabel(language, "theory")
              : learningFamily === "theory"
                ? trainingSurfaceLabel(language, "theory")
                : filesToTouch.length > 0 || apiHints.length > 0 || visibleExpectedSymbols.length > 0
                ? trainingSurfaceLabel(language, "code")
                : trainingSurfaceLabel(language, "practice");
  const practiceVerificationMode = resolvePracticeVerificationMode({
    isFlashCard,
    learningFamily,
    filesToTouch,
    apiHints,
    expectedSymbols: visibleExpectedSymbols,
  });
  const manualPracticeCopy = resolveManualPracticeVerificationCopy(language, learningSubtype);
  const flashPromptText = flashPrompt?.trim() || currentStep.trim() || title;
  const resolvedWhyNow = firstText(whyThisCard?.trim(), whyNow?.trim());
  const resolvedProblemStatement = firstText(
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
  const normalizedCardTitle = normalizeCardText(title);
  const normalizedCardFocus = normalizeCardText(currentFocus);
  const headerContextItems = Array.from(
    new Set(
      [
        trainingTrackLabel,
        resolvedTargetSkill && normalizeCardText(resolvedTargetSkill) !== normalizedCardTitle
          ? resolvedTargetSkill
          : undefined,
        scenarioPackLabel?.trim()
          ? scenarioPackLabel
        : !cardOnly && currentFocus?.trim() && normalizedCardFocus !== normalizedCardTitle
            ? currentFocus
            : undefined,
      ].filter(Boolean) as string[],
    ),
  );
  const headerContext = headerContextItems.join(" \u00b7 ");
  const headerContextDetails = headerContextItems.slice(1);
  const showHeaderContext = Boolean(headerContext);
  const showTopline = true;
  const hasPrimaryLoop =
    currentStep.trim().length > 0 ||
    resolvedDeliverables.length > 0 ||
    Boolean(resolvedWhyNow?.trim()) ||
    Boolean(outcome) ||
    Boolean(nextHop);
  const carryoverCards = [restoredFocus, outcome, cardOnly ? undefined : nextHop].filter(
    (card): card is TrainingSummaryCard => Boolean(card),
  );
  const normalizedTitle = normalizeCardText(title);
  const normalizedStep = normalizeCardText(currentStep);
  const normalizedSuggestedWorkspaceAction = normalizeCardText(suggestedWorkspaceAction);
  const shouldShowStep = normalizedStep.length > 0 && normalizedStep !== normalizedTitle;
  const stepPreview = shouldShowStep ? compactCardText(currentStep, 180) : "";
  const isStepLong = currentStep.trim().length > stepPreview.length;
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
    ? isZh
      ? "\u5148\u505a\u8fd9\u4e00\u6b65"
      : "Start here"
    : isZh
      ? "\u5f53\u524d\u573a\u666f"
      : "Current scenario";
  const whyNowPreview = resolvedWhyNow ? compactCardText(resolvedWhyNow, cardOnly ? 88 : 120) : undefined;
  const formattedFilesToTouch = compactArtifactList(filesToTouch, 40, 4);
  const formattedApiHints = compactArtifactList(apiHints, 44, 4);
  const studyArtifacts = compactArtifactList([...filesToTouch, ...apiHints], 40, 2);
  const flashLearnCues = compactArtifactList(
    [hintLadder[0]?.trim(), ...studyArtifacts, constraints[0]?.trim()],
    46,
    2,
  );
  const learnFirstTitle = cardOnly
    ? firstText(nextMovePrimary, scenarioPackLabel?.trim())
    : firstText(
        shouldShowStep ? stepPreview : undefined,
        shouldShowStep ? currentStep.trim() : undefined,
      );
  const learnFirstDetailBase =
    firstText(
      whyNowPreview,
      shouldShowNextMove && nextMovePrimary ? `${nextMoveLabel}: ${nextMovePrimary}` : undefined,
      nextMoveSecondary ? `${isZh ? "\u573a\u666f" : "Scenario"}: ${nextMoveSecondary}` : undefined,
      scenarioPackLabel ? `${isZh ? "\u573a\u666f\u5305" : "Scenario pack"}: ${scenarioPackLabel}` : undefined,
    ) ??
    (isZh
      ? "\u5148\u628a\u5f53\u524d\u5207\u7247\u8bfb\u6e05\u695a\uff0c\u518d\u8fdb\u5165\u4e0b\u9762\u7684\u9a8c\u8bc1\u3002"
      : "Read this slice first, then move into verification.");
  const learnFirstDetail = cardOnly
    ? (firstText(sourceSummary?.trim(), sourceDetail?.trim()) ??
      trainingCardOnlyText(language, "learnFirst"))
    : learnFirstDetailBase;
  const learnFirstArtifacts = isFlashCard ? flashLearnCues : studyArtifacts;
  const showCardOnlyTryStep = cardOnly && !isFlashCard;
  const learnFirstArtifactsRepeatTryStep =
    showCardOnlyTryStep &&
    learnFirstArtifacts.length > 0 &&
    formattedFilesToTouch.length > 0 &&
    learnFirstArtifacts.every((item) =>
      formattedFilesToTouch.some((candidate) => candidate.trim().toLowerCase() === item.trim().toLowerCase()),
    );
  const visibleLearnFirstArtifacts = learnFirstArtifactsRepeatTryStep ? [] : learnFirstArtifacts;
  const hasLearnFirstBlock = Boolean(
    learnFirstTitle ||
      learnFirstDetail ||
      visibleLearnFirstArtifacts.length > 0,
  );
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
  const showSourceDetails =
    !learnPhaseActive &&
    !cardOnly &&
    Boolean(sourceDetail?.trim() || (shouldShowStep && isStepLong) || resolvedWhyNow?.trim());
  const routeWhyNowSummary = compactCardText(resolvedWhyNow, 96);
  const defaultReturnPath = trainingCardOnlySurfaceText(language, "returnResultOrBlocker");
  const routeDeliverableSummary =
    resolvedDeliverables.length > 0
      ? compactCardText(resolvedDeliverables[0], 90)
      : trainingCardOnlySurfaceText(language, "smallestDeliverable");
  const routeVerifySummary = resolvedVerifyItems[0]
    ? compactCardText(resolvedVerifyItems[0], 92)
    : isFlashCard
      ? trainingCardOnlySurfaceText(language, "flashAnswerMethod")
      : resolvedSuccessSignal
        ? compactCardText(resolvedSuccessSignal, 92)
      : practiceVerificationMode === "file"
        ? trainingCardOnlySurfaceText(language, "currentFileDiagnostics")
        : manualPracticeCopy.shortcut;
  const routeReturnSummary = compactCardText(resolvedReturnWith || defaultReturnPath, 96);
  const routeStripItems = [
    { key: "why-now", label: t.trainingWhyNow, value: routeWhyNowSummary },
    { key: "deliverable", label: t.trainingDeliverable, value: routeDeliverableSummary },
    { key: "verify", label: trainingLoopStepLabel("verify", language), value: routeVerifySummary },
    { key: "return", label: trainingLoopStepLabel("return", language), value: routeReturnSummary },
  ];
  const showRouteDetails =
    !learnPhaseActive &&
    !cardOnly &&
    (resolvedDeliverables.length > 1 ||
      resolvedVerifyItems.length > 0 ||
      Boolean(resolvedReturnWith) ||
      Boolean(visibleNextAfterCompletion) ||
      Boolean(actions));
  const hasGuidanceDetails =
    !cardOnly &&
    (filesToTouch.length > 0 ||
      apiHints.length > 0 ||
      constraints.length > 0 ||
      selfCheck.length > 0 ||
      hintLadder.length > 0 ||
      commonMistakes.length > 0 ||
      Boolean(stuckRecovery?.trim()) ||
      Boolean(reflectionPrompt?.trim()));
  const guidanceSummary =
    firstText(
      formattedFilesToTouch[0]
        ? `${isZh ? "\u5148\u770b" : "Start in"} ${formattedFilesToTouch[0]}`
        : undefined,
      formattedApiHints[0]
        ? `${isZh ? "API \u63d0\u793a" : "API hint"} ${formattedApiHints[0]}`
        : undefined,
      constraints[0]
        ? `${isZh ? "\u8fb9\u754c" : "Boundary"} ${compactCardText(constraints[0], 54)}`
        : undefined,
      hintLadder[0]
        ? `${isZh ? "\u5361\u4f4f\u65f6" : "If stuck"} ${compactCardText(hintLadder[0], 54)}`
        : undefined,
      stuckRecovery?.trim() ? compactCardText(stuckRecovery, 58) : undefined,
      practiceVerificationMode === "manual" ? compactCardText(manualPracticeCopy.fallbackHint, 58) : undefined,
    ) ??
    (isZh
      ? "\u5c55\u5f00\u67e5\u770b\u63d0\u793a\u3001\u8fb9\u754c\u548c\u5361\u4f4f\u65f6\u7684\u6062\u590d\u8def\u5f84\u3002"
      : "Open for hints, boundaries, and recovery.");
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
  const flashSectionLabel = cardOnly
    ? isZh
      ? "\u73b0\u5728\u4f5c\u7b54"
      : "Answer now"
    : isZh
      ? "\u95ea\u8bb0\u68c0\u67e5"
      : "Flash check";
  const resolvedFlashSectionLabel = isZh
    ? cardOnly
      ? "\u73b0\u5728\u4f5c\u7b54"
      : "\u95ea\u8bb0\u68c0\u67e5"
    : flashSectionLabel;
  const practiceSectionLabel = cardOnly
    ? isZh
      ? "\u73b0\u5728\u9a8c\u8bc1"
      : "Verify"
    : isZh
      ? "\u5b9e\u6218\u9a8c\u8bc1"
      : "Practice verification";
  const practiceSectionNote =
    practiceVerificationMode === "file"
      ? cardOnly
        ? isZh
          ? "\u518d\u8bfb\u53d6\u5f53\u524d\u6587\u4ef6\uff0c\u6309\u4e0b\u9762\u7684\u68c0\u67e5\u9879\u786e\u8ba4\u5b83\u662f\u5426\u6210\u7acb\u3002"
          : "Then read the current file and confirm the checks below."
        : isZh
          ? "\u4ece\u5f53\u524d\u6587\u4ef6\u548c\u8bca\u65ad\u5224\u65ad\u662f\u5426\u901a\u8fc7\u3002"
          : "Pass/fail comes from the current file and diagnostics."
      : manualPracticeCopy.verifyNote;
  const cardOnlyTask = resolvedProblemStatement;
  const cardOnlyDoneLine = firstText(routeVerifySummary, resolvedSuccessSignal);
  const cardOnlyDoneText =
    cardOnlyDoneLine &&
    normalizeCardText(cardOnlyDoneLine) !== normalizeCardText(displayTitle) &&
    normalizeCardText(cardOnlyDoneLine) !== normalizeCardText(cardOnlyTask)
      ? cardOnlyDoneLine
      : undefined;
  const cardOnlyDeliverable =
    firstText(resolvedDeliverables[0]?.trim(), resolvedSuccessSignal, cardOnlyTask) ?? cardOnlyTask;
  const cardOnlyWhyNowSummary = compactCardText(firstText(resolvedWhyNow), 120);
  const learnSectionLabel = learnPhaseActive
    ? (isZh ? "\u5148\u770b" : "Study first")
    : (isZh ? "\u524d\u7f6e" : "Primer");
  const visibleLearnFirstDetail =
    learnFirstDetail && !learnPhaseActive ? compactCardText(learnFirstDetail, 108) : learnFirstDetail;
  const showLearnFirstPanel = learnPhaseActive && hasLearnFirstBlock;
  const showLearnPrimerNote = !cardOnly && !learnPhaseActive && hasLearnFirstBlock;
  const composerVerificationHint = isFlashCard
    ? (isZh
        ? "\u7528\u4e0b\u65b9\u8f93\u5165\u6846\u4f5c\u7b54\uff0c\u9009\u62e9\u5217\u8868\u4f1a\u51fa\u73b0\u5728\u8f93\u5165\u6846\u4e0a\u65b9\u3002"
        : "Answer in the composer below. The choice list appears above the input.")
    : practiceVerificationMode === "file"
      ? (isZh
          ? "\u5148\u52a8\u624b\uff0c\u518d\u7528\u4e0b\u65b9\u8f93\u5165\u6846\u8bb0\u5f55\u7ed3\u679c\u6216 blocker\u3002\u771f\u6b63\u901a\u8fc7\u8981\u9760\u8f93\u5165\u6846\u533a\u57df\u91cc\u7684 Verify current file\u3002"
          : "Try the task first, then use the composer below to record the result or blocker. Real pass/fail still comes from Verify current file.")
      : manualPracticeCopy.composerHint;
  const cardOnlyBodySections: TrainingCardOnlySection[] = [
    ...(reliabilityCopy
      ? [
          {
            key: "reliability",
            label: isZh ? "保存状态" : "Save status",
            title: reliabilityCopy.what,
            detail: `${reliabilityCopy.why} ${reliabilityCopy.next}`,
          } satisfies TrainingCardOnlySection,
        ]
      : []),
    {
      key: "current",
      label: t.currentTask,
      title: cardOnlyTask,
    },
    {
      key: "why-now",
      label: t.trainingWhyNow,
      detail: cardOnlyWhyNowSummary,
    },
    {
      key: "deliverable",
      label: t.trainingDeliverable,
      title: cardOnlyDeliverable,
    },
    {
      key: "verify",
      label: trainingLoopStepLabel("verify", language),
      detail: routeVerifySummary,
    },
    {
      key: "return",
      label: trainingLoopStepLabel("return", language),
      detail: routeReturnSummary,
    },
  ];
  const flashDeckActionLabel = isFlashCard
    ? isZh
      ? "\u6362\u4e00\u5f20\u95ea\u5361"
      : "Next flashcard"
    : isZh
      ? "\u7528\u95ea\u5361\u7ec3\u4e60"
      : "Practice with flashcards";
  const hasAdjustmentOutcome =
    verificationReturn.kind !== "waiting" ||
    Boolean(latestVerifiedResult?.trim() || latestLearningBlocker?.trim());
  const isReadyToReturn = trainingExecutionState.composerPhase === "return";
  const adjustmentCopy = hasAdjustmentOutcome
    ? {
        label:
          isReadyToReturn
            ? isZh
              ? "\u56de\u6d41"
              : "Return"
            : isZh
              ? "\u590d\u76d8"
              : "Reflect",
        title:
          isReadyToReturn
            ? isZh
              ? "\u628a\u8fd9\u6b21\u7ed3\u679c\u5e26\u56de\u4e0b\u4e00\u6b65"
              : "Carry this result forward"
            : verificationReturn.kind === "verified"
              ? isZh
                ? "\u5148\u590d\u76d8\u8fd9\u6761\u8bc1\u636e\u8bf4\u660e\u4e86\u4ec0\u4e48"
                : "Reflect on what this evidence proves"
            : verificationReturn.kind === "blocked"
              ? isZh
                ? "\u6536\u7a84\u4fee\u590d\uff0c\u7136\u540e\u518d\u9a8c"
                : "Narrow the fix and test again"
              : isZh
                ? "\u6536\u7d27\u4e0b\u4e00\u6b65"
                : "Tighten the next move",
        detail:
          firstText(
            isReadyToReturn ? latestLearningFollowup : undefined,
            stuckRecovery,
            reflectionPrompt,
          ) ?? (isZh ? "\u5148\u8bb0\u4e0b\u8fd9\u8f6e\u5b66\u5230\u7684\u8fb9\u754c\uff0c\u518d\u7ee7\u7eed\u5f80\u4e0b\u8d70\u3002" : "Write down the boundary you learned this round before moving on."),
        next:
          isReadyToReturn
            ? isZh
              ? "\u5148\u8bb0\u4e0b\u8fd9\u6761\u8fb9\u754c\uff0c\u518d\u7ee7\u7eed\u3002"
              : "Capture the boundary, then continue."
            : verificationReturn.kind === "verified"
              ? isZh
                ? "\u5148\u5728\u8f93\u5165\u6846\u91cc\u8bf4\u6e05\u8fd9\u6761\u8bc1\u636e\uff0c\u518d\u56de\u6d41\u3002"
                : "State the evidence in the composer, then return."
            : isZh
              ? "\u5148\u505a\u6700\u5c0f\u6539\u52a8\uff0c\u7136\u540e\u518d\u9a8c\u4e00\u6b21\u3002"
              : "Make the smallest change, then retest.",
      }
    : undefined;
  const shouldElevateReturnAction = Boolean(actions) && isReadyToReturn;

  const flashProofSurface = (
    <section
      className="training-proof-card training-proof-card--flash"
      aria-label={isZh ? "\u95ea\u8bb0\u9a8c\u8bc1" : "Flash verification"}
    >
      <div className="training-proof-card__head">
        <SectionHeading icon={<CheckMarkIcon size={12} />} label={resolvedFlashSectionLabel} />
        {!cardOnly ? (
          <span className="training-proof-card__shortcut">
            {isZh ? "\u9009\u62e9 / \u586b\u7a7a / \u7b80\u7b54" : "Choice / fill / short"}
          </span>
        ) : null}
      </div>
      <p className="training-proof-card__note">{composerVerificationHint}</p>
      {verifyItems.length > 0 ? (
        <ul className="training-inline-list">
          {verifyItems.slice(0, 4).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : resolvedSuccessSignal ? (
        <ul className="training-inline-list">
          <li>{resolvedSuccessSignal}</li>
        </ul>
      ) : null}
    </section>
  );

  const practiceProofSurface = (
    <section
      className="training-proof-card training-proof-card--practice"
      aria-label={isZh ? "\u5b9e\u6218\u9a8c\u8bc1" : "Practice verification"}
    >
      <div className="training-proof-card__head">
        <SectionHeading icon={<CheckMarkIcon size={12} />} label={practiceSectionLabel} />
        {!cardOnly ? (
          <span className="training-proof-card__shortcut">
            {practiceVerificationMode === "file"
              ? isZh
                ? "\u8bfb\u53d6 IDE \u5f53\u524d\u6587\u4ef6"
                : "Read current IDE file"
              : manualPracticeCopy.shortcut}
          </span>
        ) : null}
      </div>
      {!cardOnly ? (
        <p className="training-proof-card__note">
          {practiceSectionNote}
        </p>
      ) : null}
      {practiceVerificationMode === "file" && visibleExpectedSymbols.length > 0 ? (
        <div className="training-proof-card__symbols" aria-label={trainingSurfaceLabel(language, "codeSymbols")}>
          <span>{trainingSurfaceLabel(language, "checks")}</span>
          {visibleExpectedSymbols.map((symbol) => (
            <code key={symbol}>{symbol}</code>
          ))}
        </div>
      ) : null}
      {verifyItems.length > 0 ? (
        <ul className="training-inline-list">
          {verifyItems.slice(0, 4).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : resolvedSuccessSignal ? (
        <ul className="training-inline-list">
          <li>{resolvedSuccessSignal}</li>
        </ul>
      ) : null}
      {!cardOnly ? (
        <p className="training-proof-card__note">{composerVerificationHint}</p>
      ) : null}
    </section>
  );

  return (
    <section
      className={`workbench-pane training-pane training-pane--single-card${cardOnly ? " training-pane--card-only" : ""}`}
      data-training-leftover-not-live={leftoverStoredNote ? "true" : undefined}
    >
      {mismatchRecovery && onCardStatusTransition ? (
        <div className="training-card-recovery" role="alert" data-training-card-recovery="true">
          <p>{t.trainingHandoffMismatchHint}</p>
          <button
            type="button"
            className="button button--micro"
            data-training-card-recovery-switch="true"
            onClick={() =>
              onCardStatusTransition(
                mismatchRecovery.cardId,
                "active",
                isZh ? "从交接错配中恢复：切换到交接所属卡片" : "Recover from handoff mismatch: activate the handoff-owner card",
              )
            }
          >
            {t.trainingSwitchToCard}
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
          <section className="training-current training-current--primary training-current--single-card">
            {cardOnly ? (
              <div
                className="training-current__card-stack training-current__card-stack--card-only"
                role="group"
                data-view-primary=""
                aria-label={trainingSurfaceLabel(language, "currentTrainingCard")}
              >
                <div className="training-current__card-shell">
                  <div className="training-current__card-face">
                    <div className="training-current__sentence" data-view-identity="true" data-view-why="">
                      <div className="training-current__lead training-current__lead--card-face training-current__lead--floating">
                        <h2 data-view-object="">{displayTitle}</h2>
                      </div>
                      {cardOnlyTask &&
                      normalizeCardText(cardOnlyTask) !== normalizeCardText(displayTitle) ? (
                        <p data-view-why="">{cardOnlyTask}</p>
                      ) : null}
                    </div>
                    {cardOnlyBodySections
                      .filter((section) => {
                        const title = section.title?.trim();
                        const detail = section.detail?.trim();
                        if (!title && !detail) {
                          return false;
                        }
                        if (
                          section.key === "current" &&
                          title &&
                          normalizeCardText(title) === normalizeCardText(displayTitle)
                        ) {
                          return false;
                        }
                        return true;
                      })
                      .map((section) => (
                        <article key={section.key} className="training-current__card-section" data-training-card-fact={section.key}>
                          <span className="training-current__card-label">{section.label}</span>
                          {section.title ? (
                            <p className="training-current__card-value">{section.title}</p>
                          ) : null}
                          {section.detail ? <p>{section.detail}</p> : null}
                        </article>
                      ))}
                    {cardOnlyDoneText ? (
                      <p className="training-current__done">{cardOnlyDoneText}</p>
                    ) : null}
                    {latestLearningBlocker ? (
                      <p className="training-current__verify-result" role="status">
                        {latestLearningBlocker}
                      </p>
                    ) : null}
                    {shouldElevateReturnAction ? (
                      <div
                        className="training-current__actions training-current__actions--primary"
                        role="group"
                        aria-label={t.openCoach}
                      >
                        {actions}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}
            {!cardOnly ? (
              <>
            {showTopline ? (
              <div className="training-current__topline">
                <span className="eyebrow training-current__tag">
                  {cardOnly ? currentCardLabel : toplineLabel}
                </span>
                {showHeaderContext ? (
                  <span
                    className="training-current__meta training-current__meta--context"
                    data-training-context-layout="optional-second-line"
                    data-training-context-count={headerContextItems.length}
                    data-training-learning-family={learningFamily ?? (isFlashCard ? "theory" : "practice")}
                    aria-label={headerContext}
                  >
                    <span className="training-current__learning-family">{trainingTrackLabel}</span>
                    {headerContextDetails.map((item) => (
                      <span key={item} className="training-current__context-item">
                        <span className="training-current__context-separator" aria-hidden="true">
                          {" \u00b7 "}
                        </span>
                        {item}
                      </span>
                    ))}
                  </span>
                ) : null}
              </div>
            ) : null}

            {!cardOnly ? (
              <div className="training-card-nav" aria-label={t.training}>
                <button
                  className="training-card-nav__button"
                  type="button"
                  disabled={!onPreviousCard}
                  onClick={onPreviousCard}
                  title={t.previousCard}
                >
                  <span className="training-card-nav__icon training-card-nav__icon--previous" aria-hidden="true">
                    <ChevronRightIcon size={13} />
                  </span>
                  <span>{t.previousCard}</span>
                </button>
                <span className="training-card-nav__counter">
                  {`${cardTypeLabel} · ${currentCardLabel}`}
                </span>
                <button
                  className="training-card-nav__button"
                  type="button"
                  disabled={!onNextCard}
                  onClick={onNextCard}
                  title={t.nextCard}
                >
                  <span>{t.nextCard}</span>
                  <span className="training-card-nav__icon" aria-hidden="true">
                    <ChevronRightIcon size={13} />
                  </span>
                </button>
              </div>
            ) : null}

            {!cardOnly ? (
              <div
                className="training-loop-rail"
                aria-label={trainingSurfaceLabel(language, "trainingLoop")}
                data-training-loop-layout="3-plus-2"
                data-training-loop-step-count={trainingLoopSteps.length}
              >
                {trainingLoopSteps.map((step) => (
                  <div
                    key={step.key}
                    className={`training-loop-step is-${step.state}`}
                    aria-current={step.state === "active" ? "step" : undefined}
                    title={step.label}
                    data-training-loop-step={step.key}
                    data-training-loop-state={step.state}
                    data-training-loop-label={step.label}
                  >
                    <span className="training-loop-step__dot" aria-hidden="true" />
                    <span className="training-loop-step__label" data-training-loop-step-label={step.label}>
                      {step.label}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}

            <div
              className="training-current__lead training-current__lead--card-face"
              data-training-core-section="current"
            >
              <span className="training-current__core-label">{currentCardLabel}</span>
              <h2>{title}</h2>
              {isFlashCard && shouldShowStep && !learnPhaseActive ? <p className="training-current__step">{stepPreview}</p> : null}
              {isFlashCard && whyNowPreview && !learnPhaseActive ? <p className="training-current__why">{whyNowPreview}</p> : null}
            </div>

            <div className="training-current__route-strip" aria-label={isZh ? "\u5f53\u524d\u8bad\u7ec3\u8def\u7ebf" : "Current training route"}>
              {routeStripItems.map((item) => (
                <div
                  key={item.key}
                  className="training-current__route-item"
                  data-training-core-section={item.key === "return" ? "next" : item.key}
                  title={item.value}
                >
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>

            {showLearnFirstPanel ? (
              <div className="training-next-move">
                <span className="training-next-move__label">{learnSectionLabel}</span>
                {learnFirstTitle ? <strong>{learnFirstTitle}</strong> : null}
                <p>{learnFirstDetail}</p>
                {visibleLearnFirstArtifacts.length > 0 ? (
                  <div className="training-code-list" aria-label={isZh ? "\u5148\u770b\u8fd9\u4e9b\u7ebf\u7d22" : "Study cues first"}>
                    {visibleLearnFirstArtifacts.map((item, index) => (
                      <code key={`${item}-${index}`}>{item}</code>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {showLearnPrimerNote ? (
              <div className="training-primer-note">
                <span className="training-primer-note__label">{learnSectionLabel}</span>
                {learnFirstTitle ? <strong>{learnFirstTitle}</strong> : null}
                {visibleLearnFirstDetail ? <p>{visibleLearnFirstDetail}</p> : null}
                {visibleLearnFirstArtifacts.length > 0 ? (
                  <div className="training-code-list" aria-label={isZh ? "\u524d\u7f6e\u7ebf\u7d22" : "Primer cues"}>
                    {visibleLearnFirstArtifacts.slice(0, 2).map((item, index) => (
                      <code key={`${item}-${index}`}>{item}</code>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {isFlashCard && !cardOnly && nextMovePrimary && !learnPhaseActive ? (
              <div className="training-next-move">
                <span className="training-next-move__label">{nextMoveLabel}</span>
                <strong>{nextMovePrimary}</strong>
                {nextMoveSecondary ? (
                  <p>
                    <span>{isZh ? "\u573a\u666f" : "Scenario"}</span>{" "}
                    {nextMoveSecondary}
                  </p>
                ) : null}
              </div>
            ) : null}

            {!cardOnly && verificationReturn.kind !== "waiting" ? (
              <div
                key={`${verificationReturn.kind}-${verificationReturn.title}`}
                className={`training-verification-return is-${verificationReturn.kind} score-pulse`}
                role="status"
                aria-live="polite"
              >
                <span className="training-verification-return__rail" aria-hidden="true" />
                <div className="training-verification-return__copy">
                  {!cardOnly ? (
                    <span className="training-verification-return__eyebrow">{verificationReturn.eyebrow}</span>
                  ) : null}
                  <strong>{verificationReturn.title}</strong>
                  <p>{verificationReturn.detail}</p>
                  {!cardOnly ? <span>{verificationReturn.next}</span> : null}
                  {shouldElevateReturnAction ? (
                    <div className="training-verification-return__actions">{actions}</div>
                  ) : null}
                </div>
              </div>
            ) : null}

            {!cardOnly ? (isFlashCard ? flashProofSurface : practiceProofSurface) : null}
              </>
            ) : null}

            {!learnPhaseActive && !cardOnly && adjustmentCopy ? (
              <div className="training-next-move training-next-move--adjust">
                <span className="training-next-move__label">{adjustmentCopy.label}</span>
                <strong>{adjustmentCopy.title}</strong>
                <p>{adjustmentCopy.detail}</p>
                <span>{adjustmentCopy.next}</span>
              </div>
            ) : null}

            {!learnPhaseActive && hasGuidanceDetails ? (
              <details
                className="training-guidance-details"
                open={verificationReturn.kind === "blocked" && Boolean(stuckRecovery?.trim())}
              >
                <summary>
                  <span>{isZh ? "\u63d0\u793a\u4e0e\u8fb9\u754c" : "Hints and guardrails"}</span>
                  <strong>{guidanceSummary}</strong>
                </summary>
                <div className="training-guidance-details__body">
                  {formattedFilesToTouch.length > 0 ? (
                    <details className="training-guidance-details__nested">
                      <summary>{isZh ? "\u8fd9\u6837\u9a8c\u8bc1" : "Verify like this"}</summary>
                      <section className="training-guidance-details__section">
                        <ul className="training-inline-list">
                          {verifyItems.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </section>
                    </details>
                  ) : null}
                  {resolvedReturnWith?.trim() ? (
                    <section className="training-card-route-details__section">
                      <h3>{isZh ? "\u5b8c\u6210\u540e\u5e26\u56de" : "Bring back after completion"}</h3>
                      <p>{resolvedReturnWith}</p>
                    </section>
                  ) : null}
                  {(filesToTouch.length > 0 ||
                    apiHints.length > 0 ||
                    constraints.length > 0 ||
                    selfCheck.length > 0 ||
                    hintLadder.length > 0 ||
                    commonMistakes.length > 0 ||
                    Boolean(stuckRecovery?.trim()) ||
                    Boolean(reflectionPrompt?.trim())) ? (
                    <section className="training-card-route-details__section">
                      <h3>{isZh ? "\u63d0\u793a\u548c\u8fb9\u754c" : "Hints and guardrails"}</h3>
                      {formattedFilesToTouch.length > 0 ? (
                        <div className="training-code-list" aria-label={isZh ? "\u4f18\u5148\u6587\u4ef6" : "Files to touch"}>
                          {formattedFilesToTouch.map((item, index) => (
                            <code key={`${item}-${index}`}>{item}</code>
                          ))}
                        </div>
                      ) : null}
                      {formattedApiHints.length > 0 ? (
                        <CollapseSection
                          level={2}
                          title={t.trainingCardDetailsApiHints}
                          persistenceKey={`card-${cardId ?? "current"}-api-hints`}
                        >
                          <div className="training-code-list" aria-label={isZh ? "API \u63d0\u793a" : "API hints"}>
                            {formattedApiHints.map((item, index) => (
                              <code key={`${item}-${index}`}>{item}</code>
                            ))}
                          </div>
                        </CollapseSection>
                      ) : null}
                      {constraints.length > 0 ? (
                        <ul className="training-inline-list">
                          {constraints.slice(0, 3).map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      ) : null}
                      {selfCheck.length > 0 ? (
                        <CollapseSection
                          level={2}
                          title={t.trainingCardDetailsSelfCheck}
                          persistenceKey={`card-${cardId ?? "current"}-self-check`}
                        >
                          <ul className="training-inline-list">
                            {selfCheck.slice(0, 3).map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </CollapseSection>
                      ) : null}
                      {hintLadder.length > 0 ? (
                        <details className="training-guidance-details__nested">
                          <summary>{isZh ? "提示阶梯" : "Hint ladder"}</summary>
                          <ul className="training-inline-list">
                            {hintLadder.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                      {commonMistakes.length > 0 ? (
                        <details className="training-guidance-details__nested">
                          <summary>{isZh ? "常见错误" : "Common mistakes"}</summary>
                          <ul className="training-inline-list">
                            {commonMistakes.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                      {stuckRecovery?.trim() || reflectionPrompt?.trim() ? (
                        <details className="training-guidance-details__nested">
                          <summary>{isZh ? "卡住时怎么恢复" : "If you get stuck"}</summary>
                          {stuckRecovery?.trim() ? <p>{stuckRecovery}</p> : null}
                          {reflectionPrompt?.trim() ? <p>{reflectionPrompt}</p> : null}
                        </details>
                      ) : null}
                    </section>
                  ) : null}
                </div>
              </details>
            ) : null}

            {showSourceDetails ? (
              <details className="training-source-details">
                <summary>{isZh ? "\u6765\u6e90\u4e0e\u539f\u56e0" : "Source and reason"}</summary>
                <div className="training-source-details__body">
                  {sourceDetail?.trim() ? <p>{sourceDetail}</p> : null}
                  {shouldShowStep && isStepLong ? <p>{currentStep}</p> : null}
                  {resolvedWhyNow ? <p>{resolvedWhyNow}</p> : null}
                </div>
              </details>
            ) : null}

            {showRouteDetails ? (
              <details className="training-card-route-details">
                <summary>{isZh ? "\u5b8c\u6574\u9a8c\u6536" : "Full acceptance"}</summary>
                <div className="training-card-route-details__body">
                  {resolvedDeliverables.length > 0 ? (
                    <section className="training-card-route-details__section">
                      <h3>{isZh ? "\u4ea4\u4ed8\u7269" : "Deliverables"}</h3>
                      <ul className="training-inline-list">
                        {resolvedDeliverables.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                  <CollapseSection
                    level={2}
                    title={t.trainingCardDetailsAcceptance}
                    persistenceKey={`card-${cardId ?? "current"}-acceptance`}
                  >
                    <section className="training-card-route-details__section">
                      <h3>{isZh ? "\u9a8c\u6536\u65b9\u5f0f" : "Acceptance method"}</h3>
                      {resolvedVerifyItems.length > 0 ? (
                        <ul className="training-inline-list">
                          {resolvedVerifyItems.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">
                          {isZh
                            ? "\u5148\u62ff\u5230\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u7ed3\u679c\uff0c\u518d\u51b3\u5b9a\u8981\u4e0d\u8981\u6269\u5c55\u8303\u56f4\u3002"
                            : "Land one small result first."}
                        </p>
                      )}
                    </section>
                  </CollapseSection>
                  <section className="training-card-route-details__section">
                    <h3>{isZh ? "\u56de\u6d41\u53bb\u5411" : "Return path"}</h3>
                    <p>{resolvedReturnWith || defaultReturnPath}</p>
                  </section>
                  {visibleNextAfterCompletion ? (
                    <section className="training-card-route-details__section">
                      <h3>{trainingCardOnlySurfaceText(language, "afterThis")}</h3>
                      <p>{visibleNextAfterCompletion}</p>
                    </section>
                  ) : null}
                </div>
              </details>
            ) : null}
          </section>

          {!cardOnly && (carryoverCards.length > 0 ||
            reviewItems.length > 0 ||
            reviewSummary ||
            recentWins.length > 0 ||
            weakSpots.length > 0) ? (
            <details className="training-details">
              <summary>{isZh ? "\u540e\u7eed\u548c\u56de\u770b" : "Follow-up and review"}</summary>

              {carryoverCards.length > 0 ? (
                <div className="training-carryover-stack">
                  {carryoverCards.map((card) => (
                    <TrainingCarryoverRow
                      key={`${card.title}:${card.meta ?? card.detail ?? ""}`}
                      card={card}
                    />
                  ))}
                </div>
              ) : null}

              {reviewSummary ? <p className="training-details__summary">{reviewSummary}</p> : null}

              {reviewItems.length > 0 ? (
                <div className="training-review-stack">
                  {reviewItems.slice(0, 4).map((item) => (
                    <article className="training-review-row" key={item.id}>
                      <h4>{item.title}</h4>
                      {item.detail ? <p>{item.detail}</p> : null}
                      {item.meta ? <p className="muted">{item.meta}</p> : null}
                      {item.fsrs ? (
                        <details className="training-review-row__fsrs">
                          <summary>FSRS</summary>
                          <p>
                            {item.fsrs.intervalDays !== undefined
                              ? `${isZh ? "间隔" : "Interval"}: ${item.fsrs.intervalDays}d`
                              : null}
                            {item.fsrs.masteryScore !== undefined
                              ? ` · ${isZh ? "掌握度" : "Mastery"}: ${item.fsrs.masteryScore}`
                              : null}
                          </p>
                        </details>
                      ) : null}
                      <details className="training-review-row__actions-details" open>
                        <summary>{isZh ? "复习操作" : "Review actions"}</summary>
                      <div className="training-review-row__actions" aria-label={isZh ? "复习操作" : "Review actions"}>
                        {(["accept", "snooze", "reset", "skip", "done"] as const).map((action) => (
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
                            {isZh
                              ? { accept: "接受", snooze: "稍后", reset: "重置", skip: "跳过", done: "完成" }[action]
                              : action[0].toUpperCase() + action.slice(1)}
                          </button>
                        ))}
                      </div>
                      </details>
                    </article>
                  ))}
                </div>
              ) : null}

              {recentWins.length > 0 || weakSpots.length > 0 ? (
                <div className="training-signal-grid">
                  {recentWins.length > 0 ? (
                    <section className="training-signal-card">
                      <h4>
                        <SectionHeading icon={<TargetIcon size={12} />} label={isZh ? "\u6700\u8fd1\u8fdb\u6b65" : "Recent wins"} />
                      </h4>
                      <ul className="training-inline-list">
                        {recentWins.slice(0, 3).map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                  {weakSpots.length > 0 ? (
                    <section className="training-signal-card">
                      <h4>
                        <SectionHeading icon={<SparklesIcon size={12} />} label={isZh ? "\u9700\u8981\u7559\u610f" : "Watch-outs"} />
                      </h4>
                      <ul className="training-inline-list">
                        {weakSpots.slice(0, 3).map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                </div>
              ) : null}
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}
