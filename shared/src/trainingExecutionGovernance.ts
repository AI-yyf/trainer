export type TrainingComposerPhase = "learn" | "answer" | "try" | "verify" | "reflect" | "return";

export type TrainingLearningPhase = "learn" | "try" | "verify" | "reflect" | "return";

export type TrainingReflectReason =
  | "blocked"
  | "skipped"
  | "flash_answered"
  | "reviewed"
  | "verification_passed";

export type TrainingVerificationReason =
  | "practice_completed"
  | "flash_answered"
  | "evidence_recorded";

export type TrainingVerificationStatus =
  | "not_started"
  | "awaiting_evidence"
  | "passed"
  | "failed"
  | "evidence_missing";

export type TrainingVerificationSource =
  | "none"
  | "card_status"
  | "flash_answer"
  | "verified_result"
  | "handoff"
  | "next_hop"
  | "blocker";

export interface TrainingVerificationLifecycle {
  status: TrainingVerificationStatus;
  source: TrainingVerificationSource;
  /** True when training evidence has been recorded, including a failed result. */
  evidenceRecorded: boolean;
}

export interface DeriveTrainingExecutionStateInput {
  cardType: "practice" | "flash";
  trainingSubmode?: string;
  selectedCardStatus?: string;
  latestTrainingHandoffStatus?: string;
  latestTrainingNextHopStatus?: string;
  latestTrainingBlockedBy?: string;
  latestVerifiedResult?: string;
  latestLearningBlocker?: string;
  /** Persisted Learn→Try→Verify→Reflect→Return phase from card/handoff. */
  learningPhase?: string;
}

export interface TrainingExecutionState {
  selectedStatus: string;
  handoffStatus: string;
  nextHopStatus: string;
  needsPrimer: boolean;
  verification: TrainingVerificationLifecycle;
  verified: boolean;
  verificationPending: boolean;
  /** True when verified training evidence still awaits formal Plan adoption confirmation. */
  pendingPlanConfirmation: boolean;
  verificationReason?: TrainingVerificationReason;
  blocked: boolean;
  skipped: boolean;
  flashAnswered: boolean;
  reflectReason?: TrainingReflectReason;
  composerPhase: TrainingComposerPhase;
}

export function normalizeTrainingStatus(value: string | undefined): string {
  return value?.trim().toLowerCase().replace(/-/g, "_") ?? "";
}

export function normalizeTrainingSubmode(value: string | undefined): string {
  return value?.trim().toLowerCase().replace(/_/g, "-") ?? "";
}

export function normalizeTrainingLearningPhase(
  value: string | undefined,
): TrainingLearningPhase | undefined {
  const normalized = value?.trim().toLowerCase().replace(/-/g, "_");
  if (
    normalized === "learn" ||
    normalized === "try" ||
    normalized === "verify" ||
    normalized === "reflect" ||
    normalized === "return"
  ) {
    return normalized;
  }
  return undefined;
}

export function isTrainingPrimerLike(input: {
  trainingSubmode?: string;
  selectedCardStatus?: string;
  latestTrainingHandoffStatus?: string;
}): boolean {
  const normalizedSubmode = normalizeTrainingSubmode(input.trainingSubmode);
  const selectedStatus = normalizeTrainingStatus(input.selectedCardStatus);
  const handoffStatus = normalizeTrainingStatus(input.latestTrainingHandoffStatus);
  return (
    normalizedSubmode === "learn-primer" ||
    selectedStatus === "needs_primer" ||
    handoffStatus === "needs_primer"
  );
}

function hasTrainingText(value: string | undefined): boolean {
  return Boolean(value?.trim());
}

export function deriveTrainingVerificationLifecycle(
  input: DeriveTrainingExecutionStateInput,
): TrainingVerificationLifecycle {
  const selectedStatus = normalizeTrainingStatus(input.selectedCardStatus);
  const handoffStatus = normalizeTrainingStatus(input.latestTrainingHandoffStatus);
  const nextHopStatus = normalizeTrainingStatus(input.latestTrainingNextHopStatus);
  const hasLatestBlocker =
    hasTrainingText(input.latestLearningBlocker) || hasTrainingText(input.latestTrainingBlockedBy);
  const hasFailedVerification =
    hasLatestBlocker ||
    selectedStatus === "blocked" ||
    handoffStatus === "needs_revision" ||
    handoffStatus === "blocked" ||
    nextHopStatus === "blocked";

  if (handoffStatus === "unverified" || nextHopStatus === "evidence_unverified") {
    return { status: "evidence_missing", source: "handoff", evidenceRecorded: false };
  }

  if (hasFailedVerification) {
    return {
      status: "failed",
      source: hasLatestBlocker
        ? "blocker"
        : selectedStatus === "blocked"
          ? "card_status"
          : handoffStatus === "needs_revision" || handoffStatus === "blocked"
            ? "handoff"
            : "next_hop",
      evidenceRecorded: true,
    };
  }

  const trustedHandoffProgress =
    handoffStatus === "needs_reflection" ||
    handoffStatus === "ready_to_return" ||
    nextHopStatus === "reflection_required" ||
    nextHopStatus === "return_required";
  if (trustedHandoffProgress) {
    return { status: "passed", source: "handoff", evidenceRecorded: true };
  }

  const verificationRequired =
    handoffStatus === "needs_verification" || nextHopStatus === "verification_required";
  if (verificationRequired) {
    return {
      status: "awaiting_evidence",
      source: nextHopStatus === "verification_required" ? "next_hop" : "handoff",
      evidenceRecorded: false,
    };
  }

  const returned =
    selectedStatus === "fed_back" ||
    selectedStatus === "archived" ||
    handoffStatus === "resolved" ||
    handoffStatus === "fed_back" ||
    nextHopStatus === "continued_in_chat";
  const currentCardIsBeforeVerification =
    selectedStatus === "candidate" ||
    selectedStatus === "active" ||
    selectedStatus === "needs_primer";

  // A current pre-verification card must not inherit an unscoped older result.
  if (!returned && currentCardIsBeforeVerification) {
    return { status: "not_started", source: "none", evidenceRecorded: false };
  }

  if (hasTrainingText(input.latestVerifiedResult)) {
    return { status: "passed", source: "verified_result", evidenceRecorded: true };
  }

  if (handoffStatus === "verified" || handoffStatus === "resolved") {
    return { status: "passed", source: "handoff", evidenceRecorded: true };
  }

  if (nextHopStatus === "continued_in_chat") {
    return { status: "passed", source: "next_hop", evidenceRecorded: true };
  }

  const awaitingEvidence =
    selectedStatus === "implemented" ||
    selectedStatus === "completed" ||
    (input.cardType === "flash" && selectedStatus === "answered");
  if (awaitingEvidence) {
    return {
      status: "awaiting_evidence",
      source:
        input.cardType === "flash" && selectedStatus === "answered"
          ? "flash_answer"
          : "card_status",
      evidenceRecorded: false,
    };
  }

  if (
    selectedStatus === "reviewed" ||
    returned ||
    handoffStatus === "fed_back" ||
    nextHopStatus === "archived"
  ) {
    return {
      status: "evidence_missing",
      source:
        selectedStatus === "reviewed" || selectedStatus === "fed_back" || selectedStatus === "archived"
          ? "card_status"
          : handoffStatus === "fed_back"
            ? "handoff"
            : "next_hop",
      evidenceRecorded: false,
    };
  }

  return { status: "not_started", source: "none", evidenceRecorded: false };
}

export function deriveTrainingExecutionState(
  input: DeriveTrainingExecutionStateInput,
): TrainingExecutionState {
  const selectedStatus = normalizeTrainingStatus(input.selectedCardStatus);
  const handoffStatus = normalizeTrainingStatus(input.latestTrainingHandoffStatus);
  const nextHopStatus = normalizeTrainingStatus(input.latestTrainingNextHopStatus);
  const needsPrimer = isTrainingPrimerLike({
    trainingSubmode: input.trainingSubmode,
    selectedCardStatus: input.selectedCardStatus,
    latestTrainingHandoffStatus: input.latestTrainingHandoffStatus,
  });
  const verification = deriveTrainingVerificationLifecycle(input);
  const blocked = verification.status === "failed";
  const skipped = selectedStatus === "skipped" || handoffStatus === "skipped";
  const verified = verification.status === "passed";
  const returned =
    selectedStatus === "fed_back" ||
    selectedStatus === "archived" ||
    handoffStatus === "resolved" ||
    handoffStatus === "fed_back" ||
    nextHopStatus === "continued_in_chat";
  const reflectionRequired =
    !returned &&
    (handoffStatus === "needs_reflection" || nextHopStatus === "reflection_required");
  const returnRequired =
    !returned &&
    (handoffStatus === "ready_to_return" ||
      handoffStatus === "unverified" ||
      nextHopStatus === "return_required" ||
      nextHopStatus === "evidence_unverified");
  const flashRetryRequired =
    input.cardType === "flash" && selectedStatus === "needs_primer" && !returned;
  const flashAnswered =
    input.cardType === "flash" && selectedStatus === "answered" && !blocked && !returned;
  const reflectReason = returned
    ? undefined
    : returnRequired
      ? undefined
      : reflectionRequired
        ? "verification_passed"
    : skipped
      ? "skipped"
      : blocked
        ? "blocked"
        : selectedStatus === "reviewed"
          ? "reviewed"
          : verification.status === "passed"
            ? "verification_passed"
          : undefined;
  const verificationReason =
    verification.status === "passed"
      ? "evidence_recorded"
      : verification.status === "awaiting_evidence"
        ? verification.source === "flash_answer"
          ? "flash_answered"
          : "practice_completed"
        : undefined;
  const verificationPending = verification.status === "awaiting_evidence";
  // Training evidence can be verified before Coach explicitly confirms how it changes the formal plan.
  const pendingPlanConfirmation = verified && !returned;

  let composerPhase: TrainingComposerPhase;
  if (returned) {
    composerPhase = "return";
  } else if (returnRequired) {
    composerPhase = "return";
  } else if (reflectionRequired) {
    composerPhase = "reflect";
  } else if (reflectReason) {
    composerPhase = "reflect";
  } else if (flashRetryRequired || (input.cardType === "practice" && needsPrimer)) {
    composerPhase = "learn";
  } else if (verificationPending) {
    composerPhase = "verify";
  } else if (input.cardType === "flash") {
    composerPhase = "answer";
  } else {
    composerPhase = "try";
  }

  const persistedPhase = normalizeTrainingLearningPhase(input.learningPhase);
  if (persistedPhase) {
    composerPhase =
      persistedPhase === "try" && input.cardType === "flash" && !flashAnswered && !verified && !blocked
        ? "answer"
        : persistedPhase;
  }

  return {
    selectedStatus,
    handoffStatus,
    nextHopStatus,
    needsPrimer,
    verification,
    verified,
    verificationPending,
    pendingPlanConfirmation,
    verificationReason,
    blocked,
    skipped,
    flashAnswered,
    reflectReason,
    composerPhase,
  };
}
