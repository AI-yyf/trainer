import type { TrainingSubmode } from "./models";

export type ActiveTrainingCardType = "practice" | "flash";

export type TrainingCardCreatedFrom =
  | "conversation"
  | "plan"
  | "resource"
  | "practice_feedback"
  | "dependency_mastery"
  | "review_due"
  | "recovery";

export type TrainingCardTrustState = "trusted" | "fresh" | "unknown" | "stale" | "untrusted";

export type TrainingCardStatus =
  | "candidate"
  | "active"
  | "needs_primer"
  | "answered"
  | "implemented"
  | "completed"
  | "reviewed"
  | "fed_back"
  | "archived"
  | "skipped"
  | "blocked";

export interface TrainingCardScoreFactors {
  planRelevance: number;
  blockingPower: number;
  evidenceGap: number;
  recencyNeed: number;
  resourceTrust: number;
  difficultyFit: number;
  projectFit: number;
  transferValue: number;
  recoveryPriority: number;
  repeatedWeaknessPriority: number;
}

export interface TrainingCardCandidate {
  id: string;
  type: ActiveTrainingCardType;
  title: string;
  status?: TrainingCardStatus;
  focusArea?: string;
  prompt?: string;
  createdFrom: TrainingCardCreatedFrom;
  sourceChain: string[];
  whyNow?: string;
  scenarioPack?: string;
  targetSkill?: string;
  difficulty?: "easy" | "medium" | "hard";
  planLinks?: string[];
  projectLinks?: string[];
  resourceLinks?: string[];
  dependencyLinks?: string[];
  expectedEvidence?: string[];
  expectedSymbols?: string[];
  feedbackTargets?: string[];
  scoreFactors: Partial<TrainingCardScoreFactors>;
  repeatedWeaknessKey?: string;
  repeatedWeaknessSummary?: string;
  nextAfterCompletion?: string;
  fallbackAction?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  returnWith?: string;
  blockers?: string[];
  trustState?: TrainingCardTrustState;
  trustAcknowledged?: boolean;
  requiresProjectContext?: boolean;
  projectContextReady?: boolean;
  coachOnly?: boolean;
  hasPrompt?: boolean;
  hasDeliverable?: boolean;
  hasVerification?: boolean;
  hasReferenceAnswer?: boolean;
  hasRubric?: boolean;
  hasHintLadder?: boolean;
  // §1.14 Practice card extended fields
  scenario?: string;
  problemStatement?: string;
  suggestedWorkspaceAction?: string;
  apiHints?: string[];
  constraints?: string[];
  deliverable?: string;
  selfCheck?: string[];
  expectedAnswerShape?: string;
  validationMethod?: string;
  gradingRubric?: string[];
  trainerReviewInput?: string;
  stuckRecovery?: string;
  reflectionPrompt?: string;
  // §1.15 Flash card extended fields
  knowledgeType?: string;
  question?: string;
  context?: string;
  answerMode?: string;
  options?: string[];
  expectedAnswer?: string;
  rubric?: string[];
  hintLadder?: string[];
  feedback?: Record<string, string>;
  commonMistakes?: string[];
  reviewSchedule?: string;
  masteryDelta?: number;
  createdAt?: string;
  updatedAt?: string;
}

export interface BlockedTrainingCardCandidate {
  cardId: string;
  type: ActiveTrainingCardType;
  title: string;
  reasons: string[];
}

export interface TrainingCardSelectionRecord {
  cardId: string;
  type: ActiveTrainingCardType;
  title: string;
  selectionScore: number;
  scoreFactors: TrainingCardScoreFactors;
  sourceChain: string[];
  repeatedWeaknessKey?: string;
  repeatedWeaknessSummary?: string;
  scenarioPack?: string;
  learnerDeliverables?: string[];
  verificationSteps?: string[];
  successSignal?: string;
  expectedSymbols?: string[];
  apiHints?: string[];
  nextAfterCompletion?: string;
  returnWith?: string;
}

export interface ActiveTrainingCardRouting {
  selectedCardId?: string;
  selectedCard?: TrainingCardSelectionRecord;
  selectionScore: number;
  scoreFactors: TrainingCardScoreFactors;
  whyThisCard: string;
  whyNotOthers: string[];
  blockedCandidates: BlockedTrainingCardCandidate[];
  fallbackAction: string;
  nextAfterCompletion: string;
  candidateCount: number;
  eligibleCount: number;
  authoritySource?: "server" | "frontend_fallback";
  routerVersion?: string;
  generatedAt?: string;
}

export interface TrainingCardRoutingInput {
  candidates: TrainingCardCandidate[];
  currentSubmode?: TrainingSubmode;
  pureConversationMode?: boolean;
  fallbackAction?: string;
  nextAfterCompletion?: string;
}

const ZERO_FACTORS: TrainingCardScoreFactors = {
  planRelevance: 0,
  blockingPower: 0,
  evidenceGap: 0,
  recencyNeed: 0,
  resourceTrust: 0,
  difficultyFit: 0,
  projectFit: 0,
  transferValue: 0,
  recoveryPriority: 0,
  repeatedWeaknessPriority: 0,
};

const FACTOR_WEIGHTS: TrainingCardScoreFactors = {
  planRelevance: 0.19,
  blockingPower: 0.17,
  evidenceGap: 0.17,
  recencyNeed: 0.12,
  resourceTrust: 0.08,
  difficultyFit: 0.1,
  projectFit: 0.08,
  transferValue: 0.04,
  recoveryPriority: 0.03,
  repeatedWeaknessPriority: 0.02,
};

const FACTOR_LABELS: Record<keyof TrainingCardScoreFactors, string> = {
  planRelevance: "plan relevance",
  blockingPower: "blocking power",
  evidenceGap: "evidence gap",
  recencyNeed: "review timing",
  resourceTrust: "resource trust",
  difficultyFit: "difficulty fit",
  projectFit: "project fit",
  transferValue: "transfer value",
  recoveryPriority: "recovery priority",
  repeatedWeaknessPriority: "cross-project repeated weakness",
};

function clampFactor(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(1, value));
}

function normalizeScoreFactors(value?: Partial<TrainingCardScoreFactors>): TrainingCardScoreFactors {
  return {
    planRelevance: clampFactor(value?.planRelevance),
    blockingPower: clampFactor(value?.blockingPower),
    evidenceGap: clampFactor(value?.evidenceGap),
    recencyNeed: clampFactor(value?.recencyNeed),
    resourceTrust: clampFactor(value?.resourceTrust),
    difficultyFit: clampFactor(value?.difficultyFit),
    projectFit: clampFactor(value?.projectFit),
    transferValue: clampFactor(value?.transferValue),
    recoveryPriority: clampFactor(value?.recoveryPriority),
    repeatedWeaknessPriority: clampFactor(value?.repeatedWeaknessPriority),
  };
}

function scoreCandidate(factors: TrainingCardScoreFactors): number {
  const weighted = (Object.keys(FACTOR_WEIGHTS) as Array<keyof TrainingCardScoreFactors>)
    .reduce((total, key) => total + factors[key] * FACTOR_WEIGHTS[key], 0);
  return Math.round(weighted * 1000) / 10;
}

function preferredTypeForSubmode(submode?: TrainingSubmode): ActiveTrainingCardType | undefined {
  if (submode === "flash") {
    return "flash";
  }
  if (submode === "practice" || submode === "review" || submode === "review_queue") {
    return "practice";
  }
  return undefined;
}

function compact(value?: string): string | undefined {
  const text = value?.replace(/\s+/g, " ").trim();
  return text || undefined;
}

function inferCandidateBlockers(candidate: TrainingCardCandidate): string[] {
  const blockers = [...(candidate.blockers ?? [])].map((item) => item.trim()).filter(Boolean);

  if ((candidate.trustState === "untrusted" || candidate.trustState === "stale") && !candidate.trustAcknowledged) {
    blockers.push("resource is not trusted or fresh enough");
  }

  if (candidate.coachOnly === false) {
    blockers.push("practice would cross the coach-only boundary");
  }

  if (candidate.requiresProjectContext && !candidate.projectContextReady) {
    blockers.push("project context is not ready");
  }

  if (candidate.hasPrompt === false || !compact(candidate.prompt ?? candidate.title)) {
    blockers.push("card prompt is missing");
  }

  if (candidate.type === "practice") {
    if (candidate.hasDeliverable === false) {
      blockers.push("practice deliverable is missing");
    }
    if (candidate.hasVerification === false) {
      blockers.push("practice verification method is missing");
    }
  }

  if (candidate.type === "flash") {
    if (candidate.hasReferenceAnswer === false) {
      blockers.push("flash reference answer is missing");
    }
    if (candidate.hasRubric === false) {
      blockers.push("flash scoring rubric is missing");
    }
    if (candidate.hasHintLadder === false) {
      blockers.push("flash hint ladder is missing");
    }
  }

  return Array.from(new Set(blockers));
}

function topFactorLabels(factors: TrainingCardScoreFactors, limit = 3): string[] {
  return (Object.keys(factors) as Array<keyof TrainingCardScoreFactors>)
    .sort((left, right) => factors[right] - factors[left])
    .slice(0, limit)
    .map((key) => FACTOR_LABELS[key]);
}

function whyLower(selected: TrainingCardSelectionRecord, other: TrainingCardSelectionRecord): string {
  const gap = Math.round((selected.selectionScore - other.selectionScore) * 10) / 10;
  const strongest = topFactorLabels(other.scoreFactors, 1)[0] ?? "score";
  return `${other.title} scored ${gap} point(s) lower; strongest signal was ${strongest}.`;
}

function emptyRouting(input: TrainingCardRoutingInput, blockedCandidates: BlockedTrainingCardCandidate[]): ActiveTrainingCardRouting {
  return {
    selectionScore: 0,
    scoreFactors: ZERO_FACTORS,
    whyThisCard: input.pureConversationMode
      ? "Training is paused because the user is in pure conversation mode."
      : "No eligible training card can be activated yet.",
    whyNotOthers: blockedCandidates.map((item) => `${item.title}: ${item.reasons[0] ?? "blocked"}`),
    blockedCandidates,
    fallbackAction: input.fallbackAction ?? "Stay in coach chat and clarify the next training card.",
    nextAfterCompletion: input.nextAfterCompletion ?? "Create an eligible practice or flash card before advancing mastery.",
    candidateCount: input.candidates.length,
    eligibleCount: 0,
    authoritySource: "frontend_fallback",
    routerVersion: "shared.active_card_router.v1",
  };
}

export function buildTrainingCardRouting(input: TrainingCardRoutingInput): ActiveTrainingCardRouting {
  const blockedCandidates = input.candidates
    .map((candidate) => ({
      candidate,
      reasons: inferCandidateBlockers(candidate),
    }))
    .filter((item) => item.reasons.length > 0)
    .map((item) => ({
      cardId: item.candidate.id,
      type: item.candidate.type,
      title: item.candidate.title,
      reasons: item.reasons,
    }));

  if (input.pureConversationMode) {
    return emptyRouting(input, blockedCandidates);
  }

  const preferredType = preferredTypeForSubmode(input.currentSubmode);
  const eligible = input.candidates
    .filter((candidate) => !blockedCandidates.some((item) => item.cardId === candidate.id))
    .map((candidate) => {
      const scoreFactors = normalizeScoreFactors(candidate.scoreFactors);
      const preferenceBoost = preferredType && candidate.type === preferredType ? 0.8 : 0;
      const selectionScore = Math.min(100, scoreCandidate(scoreFactors) + preferenceBoost);
      return {
        candidate,
        record: {
          cardId: candidate.id,
          type: candidate.type,
          title: candidate.title,
          selectionScore,
          scoreFactors,
          sourceChain: candidate.sourceChain.filter(Boolean),
          repeatedWeaknessKey: compact(candidate.repeatedWeaknessKey),
          repeatedWeaknessSummary: compact(candidate.repeatedWeaknessSummary),
          scenarioPack: compact(candidate.scenarioPack),
          learnerDeliverables: candidate.learnerDeliverables,
          verificationSteps: candidate.verificationSteps,
          successSignal: candidate.successSignal,
          expectedSymbols: candidate.expectedSymbols,
          apiHints: candidate.apiHints,
          nextAfterCompletion: compact(candidate.nextAfterCompletion),
          returnWith: candidate.returnWith,
        } satisfies TrainingCardSelectionRecord,
      };
    })
    .sort((left, right) => {
      if (right.record.selectionScore !== left.record.selectionScore) {
        return right.record.selectionScore - left.record.selectionScore;
      }
      if (right.record.scoreFactors.recoveryPriority !== left.record.scoreFactors.recoveryPriority) {
        return right.record.scoreFactors.recoveryPriority - left.record.scoreFactors.recoveryPriority;
      }
      return left.record.cardId.localeCompare(right.record.cardId);
    });

  const preferredEligible = preferredType
    ? eligible.filter((item) => item.candidate.type === preferredType)
    : [];
  const rankingPool = preferredEligible.length > 0 ? preferredEligible : eligible;
  const selected = rankingPool[0];
  if (!selected) {
    return emptyRouting(input, blockedCandidates);
  }

  const whyNotOthers = [
    ...rankingPool.slice(1, 4).map((item) => whyLower(selected.record, item.record)),
    ...(preferredEligible.length > 0
      ? eligible
          .filter((item) => item.candidate.type !== preferredType)
          .slice(0, 3)
          .map(
            (item) =>
              `${item.record.title} is eligible but deferred because the current deck is ${preferredType}.`,
          )
      : []),
    ...blockedCandidates.slice(0, 4).map((item) => `${item.title} was blocked: ${item.reasons[0] ?? "missing requirements"}.`),
  ];
  const factorLabels = topFactorLabels(selected.record.scoreFactors);
  const whyThisCard =
    compact(selected.candidate.whyNow) ??
    `${selected.record.title} is active because ${factorLabels.join(", ")} are the strongest signals.`;

  return {
    selectedCardId: selected.record.cardId,
    selectedCard: selected.record,
    selectionScore: selected.record.selectionScore,
    scoreFactors: selected.record.scoreFactors,
    whyThisCard,
    whyNotOthers,
    blockedCandidates,
    fallbackAction:
      selected.candidate.fallbackAction ??
      input.fallbackAction ??
      "If this card stalls, return to coach chat with the exact blocker and verification output.",
    nextAfterCompletion:
      selected.record.nextAfterCompletion ??
      input.nextAfterCompletion ??
      "Record the attempt, update evidence, then route the next practice or flash card.",
    candidateCount: input.candidates.length,
    eligibleCount: eligible.length,
    authoritySource: "frontend_fallback",
    routerVersion: "shared.active_card_router.v1",
  };
}

/**
 * §13.5 Card status machine: candidate -> active -> answered/implemented -> reviewed -> fed_back -> archived
 * Each transition must have a trigger source, must be explainable, and must be auditable.
 */
const VALID_CARD_TRANSITIONS: Record<TrainingCardStatus, TrainingCardStatus[]> = {
  candidate: ["active", "needs_primer", "skipped", "blocked"],
  active: ["needs_primer", "answered", "implemented", "completed", "skipped", "blocked"],
  needs_primer: ["active", "skipped", "blocked"],
  answered: ["reviewed"],
  implemented: ["reviewed", "completed"],
  completed: ["reviewed"],
  reviewed: ["fed_back"],
  fed_back: ["archived"],
  skipped: ["active"],
  blocked: ["active"],
  archived: [],
};

export function isValidCardTransition(
  from: TrainingCardStatus,
  to: TrainingCardStatus,
): boolean {
  return VALID_CARD_TRANSITIONS[from]?.includes(to) ?? false;
}

export function isTerminalCardStatus(status: TrainingCardStatus): boolean {
  return status === "archived";
}

export function nextValidCardStatuses(
  status: TrainingCardStatus,
): TrainingCardStatus[] {
  return VALID_CARD_TRANSITIONS[status] ?? [];
}
