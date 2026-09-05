export type ConversationCandidateStatus =
  | "created"
  | "surfaced"
  | "accepted"
  | "continued_in_chat"
  | "dismissed"
  | "deferred"
  | "blocked"
  | "expired"
  | "archived";

export interface ConversationCandidateActionGovernanceInput {
  status?: ConversationCandidateStatus;
}

export interface ConversationCoachVisibleStatusLike {
  selectedCardTitle?: string;
}

export interface ConversationCandidateRenderLike {
  title?: string;
}

export interface ConversationCandidateActionGovernance {
  isClosed: boolean;
  isRecoverable: boolean;
  shouldRenderOrdinaryActions: boolean;
  canAccept: boolean;
  canDefer: boolean;
  canDismiss: boolean;
  canBlock: boolean;
}

export const CLOSED_CONVERSATION_CANDIDATE_STATUSES: ReadonlySet<ConversationCandidateStatus> =
  new Set(["accepted", "continued_in_chat", "dismissed", "expired", "archived"]);

export const RECOVERABLE_CONVERSATION_CANDIDATE_STATUSES: ReadonlySet<ConversationCandidateStatus> =
  new Set(["deferred", "blocked"]);

export function resolveConversationCandidateActionGovernance(
  candidate: ConversationCandidateActionGovernanceInput,
): ConversationCandidateActionGovernance {
  const status = candidate.status;
  const isClosed = Boolean(status && CLOSED_CONVERSATION_CANDIDATE_STATUSES.has(status));
  const isRecoverable = Boolean(status && RECOVERABLE_CONVERSATION_CANDIDATE_STATUSES.has(status));

  if (isClosed) {
    return {
      isClosed: true,
      isRecoverable: false,
      shouldRenderOrdinaryActions: false,
      canAccept: false,
      canDefer: false,
      canDismiss: false,
      canBlock: false,
    };
  }

  return {
    isClosed: false,
    isRecoverable,
    shouldRenderOrdinaryActions: true,
    canAccept: true,
    canDefer: status !== "deferred",
    canDismiss: true,
    canBlock: status !== "blocked",
  };
}

export function shouldRenderConversationCandidateAlongsideStatus(
  candidate: ConversationCandidateRenderLike,
  status?: ConversationCoachVisibleStatusLike,
): boolean {
  const candidateTitle = candidate.title?.trim().toLowerCase();
  const selectedCardTitle = status?.selectedCardTitle?.trim().toLowerCase();
  if (!candidateTitle || !selectedCardTitle) {
    return true;
  }
  return candidateTitle !== selectedCardTitle;
}
