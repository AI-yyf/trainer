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
import {
  manualPracticeFallbackCopy,
  manualPracticeSubtypeCopy,
  trainingCardOnlyCopy,
  trainingCardOnlySurfaceCopy,
  trainingSurfaceLabels,
  trainingVerificationReturnCopy,
  trainingWorkbenchTextCopy,
  type ManualPracticeSubtypeCopyKey,
  type ManualPracticeVerificationCopy,
  type TrainingCardOnlyCopyKey,
  type TrainingCardOnlySurfaceCopyKey,
  type TrainingSurfaceLabelKey,
  type TrainingVerificationReturnCopyKey,
  type TrainingWorkbenchTextKey,
} from "../../lib/i18n/segments/trainingInlineText";

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
} from "../../lib/i18n/segments/trainingCardActions";
import {
  applyTrainingCardGrade as applyTrainingCardGradeImpl,
  applyTrainingCardSkip as applyTrainingCardSkipImpl,
  interpretTrainingComposerCardCommand as interpretTrainingComposerCardCommandImpl,
} from "../../lib/i18n/segments/trainingCardActions";

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

function trainingSurfaceLabel(language: ComposerLanguage, key: TrainingSurfaceLabelKey): string {
  return trainingSurfaceLabels[language]?.[key] ?? trainingSurfaceLabels["en-US"][key];
}

function trainingCardOnlySurfaceText(
  language: ComposerLanguage,
  key: TrainingCardOnlySurfaceCopyKey,
): string {
  return trainingCardOnlySurfaceCopy[language]?.[key] ?? trainingCardOnlySurfaceCopy["en-US"][key];
}

function trainingCardOnlyText(language: ComposerLanguage, key: TrainingCardOnlyCopyKey): string {
  return trainingCardOnlyCopy[language]?.[key] ?? trainingCardOnlyCopy["en-US"][key];
}

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
  // Card facts that previously reached the view but never rendered (dead
  // props): the self-check list, common mistakes, and the stuck-recovery
  // path are part of the card's guidance contract, so they stay in the task
  // details disclosure instead of being dropped.
  const resolvedSelfCheck = uniqueTrainingCardItems(selfCheck);
  const resolvedCommonMistakes = uniqueTrainingCardItems(commonMistakes);
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
        {resolvedSelfCheck.length > 0 ? (
          <div data-training-card-fact="self-check">
            <span className="template-metadata">{trainingWorkbenchText(language, "selfCheckLabel")}</span>
            <ul className="training-card-list" data-training-self-check="true">
              {resolvedSelfCheck.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {resolvedCommonMistakes.length > 0 ? (
          <div data-training-card-fact="common-mistakes">
            <span className="template-metadata">{trainingWorkbenchText(language, "commonMistakesLabel")}</span>
            <ul className="training-card-list" data-training-common-mistakes="true">
              {resolvedCommonMistakes.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {resolvedFallbackAction ? (
          <div data-training-card-fact="recovery">
            <span className="template-metadata">{trainingWorkbenchText(language, "stuckRecoveryLabel")}</span>
            <MessageRichContent body={resolvedFallbackAction} language={language} />
          </div>
        ) : null}
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
