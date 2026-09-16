/**
 * Acceptance progress feedback (batch 4).
 *
 * Turns the structured signal breakdown of `verify_practice_current_file`
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

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0);
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
 * Parse a `verify_practice_current_file` tool-result payload. Returns null
 * for results that are not practice verifications.
 */
export function parseAcceptanceFeedbackFromToolResult(
  result: unknown,
): AcceptanceFeedback | null {
  const record = asRecord(result);
  if (!record || record.tool !== "verify_practice_current_file") {
    return null;
  }
  const feedback = feedbackFromCriteria(
    Array.isArray(record.criteria) ? (record.criteria as CriteriaItemLike[]) : [],
    typeof record.next_step === "string" ? record.next_step : undefined,
  );
  if (feedback) {
    return feedback;
  }
  const matched = typeof record.matched_signal_count === "number" ? record.matched_signal_count : undefined;
  const total = typeof record.total_signal_count === "number" ? record.total_signal_count : undefined;
  if (matched !== undefined && total !== undefined && total > 0) {
    return { matched, total, matchedItems: [], missingItems: [] };
  }
  return null;
}

/**
 * Parse the "Acceptance progress: N/M …" + "Matched:/Missing:" detail lines
 * of a training-acceptance evaluation check.
 */
export function parseAcceptanceFeedbackFromCheckDetail(
  detail: string,
): AcceptanceFeedback | null {
  const text = String(detail ?? "");
  const progressMatch = text.match(/Acceptance progress:\s*(\d+)\/(\d+)\s+acceptance signals matched/);
  const matchedItems: string[] = [];
  const missingItems: string[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("Matched:")) {
      const item = line.slice("Matched:".length).split(" (")[0].trim();
      if (item) {
        matchedItems.push(item);
      }
    } else if (line.startsWith("Missing:")) {
      const item = line.slice("Missing:".length).split(" (")[0].trim();
      if (item) {
        missingItems.push(item);
      }
    }
  }
  if (progressMatch) {
    return {
      matched: Number(progressMatch[1]),
      total: Number(progressMatch[2]),
      matchedItems,
      missingItems,
    };
  }
  if (matchedItems.length === 0 && missingItems.length === 0) {
    return null;
  }
  return {
    matched: matchedItems.length,
    total: matchedItems.length + missingItems.length,
    matchedItems,
    missingItems,
  };
}
