export type OperationReliabilityPhase =
  | "intent"
  | "pending"
  | "executing"
  | "succeeded"
  | "failed"
  | "acked"
  | "cancelled";

export type OperationReliabilityOutcome = "success" | "failure" | "cancelled" | "timeout" | "";

export interface OperationReliabilityRecord {
  phase: OperationReliabilityPhase;
  outcome?: OperationReliabilityOutcome;
  requestId?: string;
}

const RELIABILITY_PHASES = new Set<OperationReliabilityPhase>([
  "intent",
  "pending",
  "executing",
  "succeeded",
  "failed",
  "acked",
  "cancelled",
]);

const IN_FLIGHT_PHASES = new Set<OperationReliabilityPhase>(["intent", "pending", "executing"]);
const FAILURE_STOP_REASONS = new Set([
  "empty_response",
  "language_corruption",
  "truncated",
  "reasoning_only",
  "truncated_or_empty",
]);

export function normalizeOperationReliabilityPhase(
  value: string | undefined,
): OperationReliabilityPhase | undefined {
  const normalized = value?.trim().toLowerCase().replace(/-/g, "_");
  if (normalized && RELIABILITY_PHASES.has(normalized as OperationReliabilityPhase)) {
    return normalized as OperationReliabilityPhase;
  }
  return undefined;
}

export function normalizeOperationReliabilityOutcome(
  value: string | undefined,
): OperationReliabilityOutcome | undefined {
  const normalized = value?.trim().toLowerCase();
  if (
    normalized === "success" ||
    normalized === "failure" ||
    normalized === "cancelled" ||
    normalized === "timeout"
  ) {
    return normalized;
  }
  if (normalized === "") {
    return "";
  }
  return undefined;
}

export function isOperationReliabilityInFlight(
  phase: OperationReliabilityPhase | undefined,
): boolean {
  return phase !== undefined && IN_FLIGHT_PHASES.has(phase);
}

export function operationReliabilityLooksSuccessful(input: {
  phase?: OperationReliabilityPhase;
  outcome?: OperationReliabilityOutcome;
  stopReason?: string;
}): boolean {
  if (isOperationReliabilityInFlight(input.phase)) {
    return false;
  }
  const stopReason = input.stopReason?.trim().toLowerCase() ?? "";
  if (FAILURE_STOP_REASONS.has(stopReason)) {
    return false;
  }
  if (input.outcome === "failure" || input.outcome === "cancelled" || input.outcome === "timeout") {
    return false;
  }
  return input.phase === "acked" && input.outcome === "success";
}

export function mapStreamStatusToReliabilityPhase(
  phase: string | undefined,
): OperationReliabilityPhase | undefined {
  const normalized = phase?.trim().toLowerCase();
  if (normalized === "preparing_context" || normalized === "requesting_model") {
    return "executing";
  }
  return normalizeOperationReliabilityPhase(normalized);
}

export function readOperationReliability(value: unknown): OperationReliabilityRecord | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const nested =
    record.reliability && typeof record.reliability === "object" && !Array.isArray(record.reliability)
      ? (record.reliability as Record<string, unknown>)
      : record;
  const agentMeta =
    record.agent_meta && typeof record.agent_meta === "object" && !Array.isArray(record.agent_meta)
      ? (record.agent_meta as Record<string, unknown>)
      : record.agent && typeof record.agent === "object" && !Array.isArray(record.agent)
        ? (record.agent as Record<string, unknown>)
        : undefined;
  const agentReliability =
    agentMeta?.reliability &&
    typeof agentMeta.reliability === "object" &&
    !Array.isArray(agentMeta.reliability)
      ? (agentMeta.reliability as Record<string, unknown>)
      : undefined;
  const source = agentReliability ?? nested;
  const phase = normalizeOperationReliabilityPhase(
    typeof source.phase === "string" ? source.phase : undefined,
  );
  if (!phase) {
    return undefined;
  }
  return {
    phase,
    outcome: normalizeOperationReliabilityOutcome(
      typeof source.outcome === "string" ? source.outcome : undefined,
    ),
    requestId:
      typeof source.request_id === "string"
        ? source.request_id
        : typeof source.requestId === "string"
          ? source.requestId
          : undefined,
  };
}
