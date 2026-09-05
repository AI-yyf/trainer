import type { ReviewArtifactHistoryEntry, ReviewArtifactSnapshot } from "./models";

export type ReviewArtifactGovernanceAction =
  | "reviewed"
  | "resolved"
  | "reopened"
  | "archived"
  | "restore_history";

export interface ReviewArtifactGovernanceGap {
  key:
    | "summary"
    | "root_cause"
    | "guardrail"
    | "next_self_implementation_rule"
    | "recommended_actions"
    | "verified_result";
  label: string;
  severity: "high" | "medium";
  reason: string;
}

export interface ReviewArtifactGovernanceSummary {
  canReview: boolean;
  canResolve: boolean;
  canReopen: boolean;
  canArchive: boolean;
  missingCount: number;
  readiness: "fragile" | "workable" | "strong";
  missingFields: ReviewArtifactGovernanceGap[];
  recommendedAction: Exclude<ReviewArtifactGovernanceAction, "restore_history">;
}

function hasText(value?: string): boolean {
  return Boolean(value?.trim());
}

export function summarizeReviewArtifactGovernance(
  artifact?: ReviewArtifactSnapshot | null,
): ReviewArtifactGovernanceSummary {
  if (!artifact) {
    return {
      canReview: false,
      canResolve: false,
      canReopen: false,
      canArchive: false,
      missingCount: 6,
      readiness: "fragile",
      missingFields: [
        {
          key: "summary",
          label: "Summary",
          severity: "high",
          reason: "No governed review artifact exists yet.",
        },
      ],
      recommendedAction: "reviewed",
    };
  }

  const missingFields: ReviewArtifactGovernanceGap[] = [];
  if (!hasText(artifact.summary)) {
    missingFields.push({
      key: "summary",
      label: "Summary",
      severity: "high",
      reason: "The loop outcome is not stated clearly yet.",
    });
  }
  if (!hasText(artifact.rootCause)) {
    missingFields.push({
      key: "root_cause",
      label: "Root cause",
      severity: "high",
      reason: "The underlying reason for the stall or win is still implicit.",
    });
  }
  if (!hasText(artifact.guardrail)) {
    missingFields.push({
      key: "guardrail",
      label: "Guardrail",
      severity: "medium",
      reason: "The next attempt still lacks an explicit boundary to protect.",
    });
  }
  if (!hasText(artifact.nextSelfImplementationRule)) {
    missingFields.push({
      key: "next_self_implementation_rule",
      label: "Next self-implementation rule",
      severity: "high",
      reason: "The learner still has no explicit rule for the next self-owned slice.",
    });
  }
  if (!artifact.recommendedActions?.length) {
    missingFields.push({
      key: "recommended_actions",
      label: "Recovery actions",
      severity: "medium",
      reason: "The review still does not tell the learner what to do next.",
    });
  }
  if (artifact.status === "resolved" && !hasText(artifact.verifiedResult)) {
    missingFields.push({
      key: "verified_result",
      label: "Verified result",
      severity: "high",
      reason: "A resolved artifact still needs a concrete verified result.",
    });
  }

  const readiness =
    missingFields.length >= 4 ? "fragile" : missingFields.length >= 2 ? "workable" : "strong";
  const canReview = artifact.status !== "archived";
  const canResolve =
    artifact.status === "active" &&
    hasText(artifact.summary) &&
    hasText(artifact.rootCause) &&
    hasText(artifact.guardrail) &&
    hasText(artifact.nextSelfImplementationRule);
  const canReopen = artifact.status !== "active";
  const canArchive = artifact.status !== "archived";

  let recommendedAction: Exclude<ReviewArtifactGovernanceAction, "restore_history"> = "reviewed";
  if (artifact.status === "resolved") {
    recommendedAction = canArchive ? "archived" : "reviewed";
  } else if (artifact.status === "archived") {
    recommendedAction = "reopened";
  } else if (canResolve) {
    recommendedAction = "resolved";
  }

  return {
    canReview,
    canResolve,
    canReopen,
    canArchive,
    missingCount: missingFields.length,
    readiness,
    missingFields,
    recommendedAction,
  };
}

export function resolveReviewArtifactHistoryAction(
  action: string | undefined,
): ReviewArtifactHistoryEntry["action"] {
  if (
    action === "created" ||
    action === "updated" ||
    action === "reviewed" ||
    action === "resolved" ||
    action === "reopened" ||
    action === "archived" ||
    action === "restore_history"
  ) {
    return action;
  }
  return "updated";
}
