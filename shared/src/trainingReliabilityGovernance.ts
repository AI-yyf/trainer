export type TrainingReliabilityPhase =
  | "intent"
  | "pending"
  | "executing"
  | "succeeded"
  | "failed"
  | "acked"
  | "cancelled";

export type TrainingReliabilityOutcome = "success" | "failure" | "cancelled" | "timeout" | "";

export interface TrainingReliabilityRecord {
  requestId: string;
  idempotencyKey: string;
  commandId: string;
  cardId?: string;
  handoffId?: string;
  phase: TrainingReliabilityPhase;
  revision: number;
  snapshotRevision?: number;
  createdAt?: string;
  updatedAt?: string;
  ackedAt?: string;
  timeoutAt?: string;
  cancelRequested?: boolean;
  outcome?: TrainingReliabilityOutcome;
  error?: string;
  recoverable?: boolean;
  recoveryAction?: string;
  learningPhase?: string;
}

export interface TrainingReliabilityCopy {
  what: string;
  why: string;
  next: string;
}

const RELIABILITY_PHASES = new Set<TrainingReliabilityPhase>([
  "intent",
  "pending",
  "executing",
  "succeeded",
  "failed",
  "acked",
  "cancelled",
]);

const ALLOWED_TRANSITIONS: Record<TrainingReliabilityPhase, ReadonlySet<TrainingReliabilityPhase>> = {
  intent: new Set(["pending", "cancelled"]),
  pending: new Set(["executing", "cancelled", "failed"]),
  executing: new Set(["succeeded", "failed", "cancelled"]),
  succeeded: new Set(["acked"]),
  failed: new Set(["pending"]),
  cancelled: new Set(["pending"]),
  acked: new Set(["pending"]),
};

const IN_FLIGHT_PHASES = new Set<TrainingReliabilityPhase>(["intent", "pending", "executing"]);
const TERMINAL_SUCCESS_PHASES = new Set<TrainingReliabilityPhase>(["succeeded", "acked"]);
const RECOVERABLE_PHASES = new Set<TrainingReliabilityPhase>(["failed", "cancelled"]);

export const TRAINING_RELIABILITY_DEFAULT_TIMEOUT_MS = 30_000;

export function normalizeTrainingReliabilityPhase(
  value: string | undefined,
): TrainingReliabilityPhase | undefined {
  const normalized = value?.trim().toLowerCase().replace(/-/g, "_");
  if (normalized && RELIABILITY_PHASES.has(normalized as TrainingReliabilityPhase)) {
    return normalized as TrainingReliabilityPhase;
  }
  return undefined;
}

export function canTransitionTrainingReliability(
  from: TrainingReliabilityPhase,
  to: TrainingReliabilityPhase,
): boolean {
  return ALLOWED_TRANSITIONS[from].has(to);
}

export function isTrainingReliabilityInFlight(phase: TrainingReliabilityPhase | undefined): boolean {
  return phase !== undefined && IN_FLIGHT_PHASES.has(phase);
}

export function isTrainingReliabilityAuthoritativeSuccess(
  phase: TrainingReliabilityPhase | undefined,
): boolean {
  return phase !== undefined && TERMINAL_SUCCESS_PHASES.has(phase);
}

export function isTrainingReliabilityRecoverable(record: TrainingReliabilityRecord | undefined): boolean {
  if (!record) {
    return false;
  }
  return record.recoverable === true && RECOVERABLE_PHASES.has(record.phase);
}

export function isTrainingReliabilityExpired(
  record: Pick<TrainingReliabilityRecord, "phase" | "timeoutAt">,
  nowMs: number = Date.now(),
): boolean {
  if (!isTrainingReliabilityInFlight(record.phase) || !record.timeoutAt) {
    return false;
  }
  const timeoutMs = Date.parse(record.timeoutAt);
  return Number.isFinite(timeoutMs) && nowMs >= timeoutMs;
}

export function sameTrainingReliabilityIdentity(
  record: Pick<TrainingReliabilityRecord, "requestId" | "idempotencyKey">,
  requestId: string,
  idempotencyKey: string,
): boolean {
  const normalizedRequestId = requestId.trim();
  const normalizedKey = idempotencyKey.trim() || normalizedRequestId;
  if (normalizedRequestId && record.requestId === normalizedRequestId) {
    return true;
  }
  return Boolean(normalizedKey && record.idempotencyKey === normalizedKey);
}

export function shouldReplayTrainingReliability(
  record: TrainingReliabilityRecord | undefined,
  requestId: string,
  idempotencyKey: string,
): boolean {
  if (!record || !sameTrainingReliabilityIdentity(record, requestId, idempotencyKey)) {
    return false;
  }
  return isTrainingReliabilityAuthoritativeSuccess(record.phase);
}

export function shouldCoalesceTrainingReliability(
  record: TrainingReliabilityRecord | undefined,
  requestId: string,
  commandId: string,
  cardId: string,
  nowMs: number = Date.now(),
): boolean {
  if (!record || !isTrainingReliabilityInFlight(record.phase) || isTrainingReliabilityExpired(record, nowMs)) {
    return false;
  }
  if (sameTrainingReliabilityIdentity(record, requestId, requestId)) {
    return true;
  }
  return record.commandId === commandId && (record.cardId ?? "") === cardId;
}

export function describeTrainingReliability(input: {
  record?: TrainingReliabilityRecord;
  localInFlight?: boolean;
  language?: string;
}): TrainingReliabilityCopy | undefined {
  const isZh = input.language === "zh-CN";
  const phase = input.record?.phase;
  if (phase && isTrainingReliabilityInFlight(phase)) {
    return {
      what: isZh ? "正在保存这次训练步骤" : "Saving this training step",
      why: isZh
        ? "要等 sidecar 写入快照后，才算当前状态。"
        : "This is not current until the sidecar writes the snapshot.",
      next: isZh ? "先等确认，不要重复提交。" : "Wait for acknowledgement. Do not submit again yet.",
    };
  }
  if (phase === "failed") {
    const timedOut = input.record?.outcome === "timeout";
    return {
      what: timedOut
        ? isZh
          ? "保存超时"
          : "Save timed out"
        : isZh
          ? "保存失败"
          : "Save failed",
      why: isZh
        ? "这次步骤还没有被权威快照确认。"
        : "The authoritative snapshot has not accepted this step.",
      next: isZh ? "再提交一次以恢复。" : "Submit again to recover.",
    };
  }
  if (phase === "cancelled") {
    return {
      what: isZh ? "保存已取消" : "Save cancelled",
      why: isZh ? "这次请求在确认前被取消。" : "This request was cancelled before acknowledgement.",
      next: isZh ? "需要的话再提交一次。" : "Submit again if you still want this step.",
    };
  }
  if (input.localInFlight && !phase) {
    return {
      what: isZh ? "正在等待 sidecar 确认" : "Waiting for sidecar acknowledgement",
      why: isZh
        ? "本地“保存中”还不是当前真相。"
        : "A local pending flag is not current truth.",
      next: isZh ? "等快照回来，或超时后重试。" : "Wait for the snapshot, or retry after timeout.",
    };
  }
  return undefined;
}
