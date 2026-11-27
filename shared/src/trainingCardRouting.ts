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
