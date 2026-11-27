/**
 * Acceptance progress feedback (batch 4).
 *
 * Turns the structured signal breakdown of `project_verify(action='verify_practice')`
 * results (and the training-acceptance check detail lines) into the
 * "matched N/M + which signals are missing + next minimal action" feedback
 * rendered in the training flow. Pure parsing only — the passed verdict
 * itself is never recomputed here.
 */

export interface AcceptanceFeedback {
  matched: number;
  total: number;
  matchedItems: string[];
  missingItems: string[];
  nextStep?: string;
}

type CriteriaItemLike = {
  text?: unknown;
  status?: unknown;
  matched_signals?: unknown;
  missing_signals?: unknown;
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function feedbackFromCriteria(
  criteria: CriteriaItemLike[],
  nextStep?: string,
): AcceptanceFeedback | null {
  if (!Array.isArray(criteria) || criteria.length === 0) {
    return null;
  }
  const matchedItems: string[] = [];
  const missingItems: string[] = [];
  for (const item of criteria) {
    const text = typeof item?.text === "string" ? item.text.trim() : "";
    if (!text) {
      continue;
    }
    if (item?.status === "matched") {
      matchedItems.push(text);
    } else {
      missingItems.push(text);
    }
  }
  if (matchedItems.length === 0 && missingItems.length === 0) {
    return null;
  }
  return {
    matched: matchedItems.length,
    total: matchedItems.length + missingItems.length,
    matchedItems,
    missingItems,
    ...(nextStep && nextStep.trim() ? { nextStep: nextStep.trim() } : {}),
  };
}

/**
 * Parse a `project_verify(action='verify_practice')` (or historical
 * `verify_practice_current_file`) tool-result payload. Returns null for
 * results that are not practice verifications.
 */
export function parseAcceptanceFeedbackFromToolResult(
  result: unknown,
  toolName?: unknown,
): AcceptanceFeedback | null {
  const record = asRecord(result);
  if (!record) {
    return null;
  }
  const declaredTool = typeof record.tool === "string" ? record.tool.trim() : "";
  const declaredAction = typeof record.action === "string" ? record.action.trim().toLowerCase() : "";
  const callerTool = typeof toolName === "string" ? toolName.trim() : "";
  const isPracticeVerification =
    (declaredTool === "project_verify" &&
      (declaredAction === "" || declaredAction === "verify_practice")) ||
    declaredTool === "verify_practice_current_file" ||
    declaredAction === "verify_practice" ||
    (callerTool === "project_verify" &&
      (declaredAction === "verify_practice" || Array.isArray(record.criteria)));
  if (!isPracticeVerification) {
    return null;
  }
  const feedback = feedbackFromCriteria(
    Array.isArray(record.criteria) ? (record.criteria as CriteriaItemLike[]) : [],
    typeof record.next_step === "string" ? record.next_step : undefined,
  );
  if (feedback) {
    return feedback;
  }
  const matched =
    typeof record.matched_signal_count === "number" ? record.matched_signal_count : undefined;
  const total =
    typeof record.total_signal_count === "number" ? record.total_signal_count : undefined;
  if (matched !== undefined && total !== undefined && total > 0) {
    return { matched, total, matchedItems: [], missingItems: [] };
  }
  return null;
}
