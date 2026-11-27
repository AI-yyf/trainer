export type PlanRuntimeResumeState = "interrupted" | "in_progress" | "waiting";

export function normalizePlanRuntimeResumeState(value: unknown): PlanRuntimeResumeState | undefined {
  const token = text(value).replace(/-/g, "_");
  if (token === "in_progress" || token === "waiting" || token === "interrupted") {
    return token;
  }
  return undefined;
}

export type RecoveryScope = {
  workspaceId: string;
  providerProfileId?: string;
  providerName?: string;
  baseUrl?: string;
  model?: string;
};

export type PlanRuntimeRecoveryRecord = {
  revision: number;
  workspaceId?: string;
  requestId?: string;
  planId?: string;
  currentStageId?: string;
  currentStep?: string;
  frozen: boolean;
  blockedReason?: string;
  whyNow?: string;
  verifyMethod: string[];
  nextAfterCurrent?: string;
  evidenceBinding?: string;
  resumeState?: PlanRuntimeResumeState;
  updatedAt?: string;
};

export type ProviderCapabilityRecoveryRecord = {
  revision: number;
  workspaceId?: string;
  providerProfileId?: string;
  providerName: string;
  baseUrl: string;
  model: string;
  protocol?: string;
  ok: boolean;
  checkedAt: string;
  toolsReady: boolean;
  toolProbeStatus: string;
  streamingReady: boolean;
  streamProbeStatus: string;
  visionReady: boolean;
  visionProbeStatus: string;
  thinkingReady: boolean;
  thinkingProbeStatus: string;
  capabilityEvidence: Array<{
    name: string;
    declared: boolean;
    observed: boolean | null;
    state: string;
  }>;
};

export type StreamingCheckpointPhase = "streaming" | "interrupted" | "completed" | "cancelled";

export type StreamingCheckpointRecord = {
  revision: number;
  workspaceId?: string;
  providerProfileId?: string;
  providerName?: string;
  baseUrl?: string;
  model?: string;
  requestId: string;
  checkpointId?: string;
  sessionId?: string;
  streamMessageId?: string;
  phase: StreamingCheckpointPhase;
  stopReason?: string;
  error?: string;
  updatedAt?: string;
};

const STREAMING_PHASES = new Set<StreamingCheckpointPhase>([
  "streaming",
  "interrupted",
  "completed",
  "cancelled",
]);

const SECRET_KEYS = new Set([
  "apikey",
  "api_key",
  "api-key",
  "secret",
  "token",
  "authorization",
  "password",
]);

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asRevision(value: unknown, fallback = 1): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}

function stripSecrets<T extends Record<string, unknown>>(value: T): T {
  const cleaned = { ...value };
  for (const key of Object.keys(cleaned)) {
    if (SECRET_KEYS.has(key.toLowerCase())) {
      delete cleaned[key];
    }
  }
  return cleaned;
}

export function normalizePlanRuntimeRecovery(value: unknown): PlanRuntimeRecoveryRecord | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const planId = text(record.planId ?? record.plan_id);
  const currentStageId = text(record.currentStageId ?? record.current_stage_id);
  const currentStep = text(record.currentStep ?? record.current_step);
  const blockedReason = text(record.blockedReason ?? record.blocked_reason);
  const workspaceId = text(record.workspaceId ?? record.workspace_id);
  const resumeState = normalizePlanRuntimeResumeState(record.resumeState ?? record.resume_state) ?? "interrupted";
  const recoveredWithoutStep =
    (resumeState === "in_progress" || resumeState === "waiting") && Boolean(workspaceId);
  if (!planId && !currentStageId && !currentStep && !blockedReason && !recoveredWithoutStep) {
    return undefined;
  }
  const verifyRaw = record.verifyMethod ?? record.verify_method;
  return {
    revision: asRevision(record.revision),
    workspaceId: workspaceId || undefined,
    requestId: text(record.requestId ?? record.request_id) || undefined,
    planId: planId || undefined,
    currentStageId: currentStageId || undefined,
    currentStep: currentStep || undefined,
    frozen: record.frozen === true,
    blockedReason: blockedReason || undefined,
    whyNow: text(record.whyNow ?? record.why_now) || undefined,
    verifyMethod: Array.isArray(verifyRaw)
      ? verifyRaw.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      : [],
    nextAfterCurrent: text(record.nextAfterCurrent ?? record.next_after_current) || undefined,
    evidenceBinding: text(record.evidenceBinding ?? record.evidence_binding) || undefined,
    resumeState,
    updatedAt: text(record.updatedAt ?? record.updated_at) || undefined,
  };
}

export function normalizeProviderCapabilityRecovery(
  value: unknown,
): ProviderCapabilityRecoveryRecord | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const cleaned = stripSecrets(record);
  const providerName = text(cleaned.providerName ?? cleaned.provider_name);
  const baseUrl = text(cleaned.baseUrl ?? cleaned.base_url);
  const model = text(cleaned.model);
  const checkedAt = text(cleaned.checkedAt ?? cleaned.checked_at);
  if (!providerName || !baseUrl || !model || !checkedAt) {
    return undefined;
  }
  const evidenceRaw = cleaned.capabilityEvidence ?? cleaned.capability_evidence;
  const capabilityEvidence = Array.isArray(evidenceRaw)
    ? evidenceRaw.flatMap((item) => {
        const entry = asRecord(item);
        const name = text(entry?.name);
        const state = text(entry?.state);
        if (!name || !state) {
          return [];
        }
        return [
          {
            name,
            declared: entry?.declared === true,
            observed: typeof entry?.observed === "boolean" ? entry.observed : null,
            state,
          },
        ];
      })
    : [];
  const liveOk = cleaned.ok === true;
  const verifiedReady = (readyKey: string, statusKey: string, evidenceName: string): boolean => {
    const evidence = capabilityEvidence.find((item) => item.name.toLowerCase() === evidenceName);
    return (
      liveOk &&
      cleaned[readyKey] === true &&
      text(cleaned[statusKey]) === "verified" &&
      evidence?.state === "verified" &&
      evidence.observed === true
    );
  };
  return {
    revision: asRevision(cleaned.revision),
    workspaceId: text(cleaned.workspaceId ?? cleaned.workspace_id) || undefined,
    providerProfileId: text(cleaned.providerProfileId ?? cleaned.provider_profile_id ?? cleaned.profileId ?? cleaned.profile_id) || undefined,
    providerName,
    baseUrl,
    model,
    protocol: text(cleaned.protocol) || undefined,
    ok: cleaned.ok === true,
    checkedAt,
    toolsReady: verifiedReady("toolsReady", "toolProbeStatus", "tools") || verifiedReady("tools_ready", "tool_probe_status", "tools"),
    toolProbeStatus: text(cleaned.toolProbeStatus ?? cleaned.tool_probe_status) || "unverified",
    streamingReady:
      verifiedReady("streamingReady", "streamProbeStatus", "streaming") ||
      verifiedReady("streaming_ready", "stream_probe_status", "streaming"),
    streamProbeStatus: text(cleaned.streamProbeStatus ?? cleaned.stream_probe_status) || "unverified",
    visionReady:
      verifiedReady("visionReady", "visionProbeStatus", "vision") ||
      verifiedReady("vision_ready", "vision_probe_status", "vision"),
    visionProbeStatus: text(cleaned.visionProbeStatus ?? cleaned.vision_probe_status) || "unverified",
    thinkingReady:
      verifiedReady("thinkingReady", "thinkingProbeStatus", "thinking") ||
      verifiedReady("thinking_ready", "thinking_probe_status", "thinking"),
    thinkingProbeStatus: text(cleaned.thinkingProbeStatus ?? cleaned.thinking_probe_status) || "unverified",
    capabilityEvidence,
  };
}

export function normalizeStreamingCheckpoint(value: unknown): StreamingCheckpointRecord | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const requestId = text(record.requestId ?? record.request_id ?? record.stream_id);
  const phaseRaw = text(record.phase).toLowerCase().replace(/-/g, "_");
  const phase = STREAMING_PHASES.has(phaseRaw as StreamingCheckpointPhase)
    ? (phaseRaw as StreamingCheckpointPhase)
    : undefined;
  if (!requestId || !phase) {
    return undefined;
  }
  return {
    revision: asRevision(record.revision),
    workspaceId: text(record.workspaceId ?? record.workspace_id) || undefined,
    providerProfileId:
      text(record.providerProfileId ?? record.provider_profile_id ?? record.profileId ?? record.profile_id) ||
      undefined,
    providerName: text(record.providerName ?? record.provider_name) || undefined,
    baseUrl: text(record.baseUrl ?? record.base_url) || undefined,
    model: text(record.model) || undefined,
    requestId,
    checkpointId: text(record.checkpointId ?? record.checkpoint_id) || undefined,
    sessionId: text(record.sessionId ?? record.session_id) || undefined,
    streamMessageId: text(record.streamMessageId ?? record.stream_message_id) || undefined,
    phase,
    stopReason: text(record.stopReason ?? record.stop_reason) || undefined,
    error: text(record.error) || undefined,
    updatedAt: text(record.updatedAt ?? record.updated_at) || undefined,
  };
}

export function recoverStreamingCheckpointAfterRestart(
  value: unknown,
): StreamingCheckpointRecord | undefined {
  const record = normalizeStreamingCheckpoint(value);
  if (!record) {
    return undefined;
  }
  if (record.phase !== "streaming") {
    return record;
  }
  return {
    ...record,
    phase: "interrupted",
    stopReason: record.stopReason || "interrupted",
    revision: record.revision + 1,
  };
}

function sameIdentity(left: string | undefined, right: string | undefined): boolean {
  const a = text(left);
  const b = text(right);
  return Boolean(a) && a.toLowerCase() === b.toLowerCase();
}

export function isCurrentForWorkspace(
  record: { workspaceId?: string } | undefined,
  workspaceId: string,
): boolean {
  const recordWorkspaceId = text(record?.workspaceId);
  const scopeWorkspaceId = text(workspaceId);
  return Boolean(recordWorkspaceId) && Boolean(scopeWorkspaceId) && recordWorkspaceId === scopeWorkspaceId;
}

export function isCurrentForProvider(
  record:
    | {
        workspaceId?: string;
        providerProfileId?: string;
        providerName?: string;
        baseUrl?: string;
        model?: string;
      }
    | undefined,
  scope: RecoveryScope,
): boolean {
  if (!isCurrentForWorkspace(record, scope.workspaceId)) {
    return false;
  }
  const recordProfileId = text(record?.providerProfileId);
  const scopeProfileId = text(scope.providerProfileId);
  if (scopeProfileId) {
    return Boolean(recordProfileId) && recordProfileId === scopeProfileId;
  }
  if (
    text(scope.providerName) ||
    text(scope.baseUrl) ||
    text(scope.model)
  ) {
    return (
      !recordProfileId &&
      sameIdentity(record?.providerName, scope.providerName) &&
      sameIdentity(record?.baseUrl, scope.baseUrl) &&
      sameIdentity(record?.model, scope.model)
    );
  }
  return true;
}

export function selectPlanRuntimeForScope(
  value: unknown,
  scope: Pick<RecoveryScope, "workspaceId">,
): PlanRuntimeRecoveryRecord | undefined {
  const record = normalizePlanRuntimeRecovery(value);
  return record && isCurrentForWorkspace(record, scope.workspaceId) ? record : undefined;
}

export type PlanRuntimeStatusFromRecovery = {
  currentStep?: string;
  currentStageId?: string;
  whyNow?: string;
  verifyMethod: string[];
  blockedReason?: string;
  nextAfterCurrent?: string;
  recovered: true;
  currentStage: null;
  resumeState?: PlanRuntimeResumeState;
  requestId?: string;
  revision?: number;
};

export function planRuntimeStatusFromRecovery(
  value: unknown,
  workspaceId: string,
): PlanRuntimeStatusFromRecovery | undefined {
  const record = selectPlanRuntimeForScope(value, { workspaceId });
  if (!record) {
    return undefined;
  }
  const hasPressure = Boolean(text(record.blockedReason) || text(record.currentStep));
  const recoveredWithoutStep =
    (record.resumeState === "in_progress" || record.resumeState === "waiting") &&
    Boolean(record.workspaceId);
  if (!hasPressure && !recoveredWithoutStep) {
    return undefined;
  }
  if (!record.currentStep) {
    return {
      currentStep: undefined,
      currentStageId: undefined,
      whyNow: undefined,
      verifyMethod: [],
      blockedReason: undefined,
      nextAfterCurrent: record.nextAfterCurrent,
      recovered: true,
      currentStage: null,
      resumeState: record.resumeState,
      requestId: record.requestId,
      revision: record.revision,
    };
  }
  return {
    currentStep: record.currentStep,
    currentStageId: record.currentStageId,
    whyNow: record.whyNow,
    verifyMethod: record.verifyMethod,
    blockedReason: record.blockedReason,
    nextAfterCurrent: record.nextAfterCurrent,
    recovered: true,
    currentStage: null,
    resumeState: record.resumeState,
    requestId: record.requestId,
    revision: record.revision,
  };
}

export type TrainingChromeRecord = {
  workspaceId?: string;
  selectedCardTitle?: string;
  cardTitle?: string;
  title?: string;
};

export function normalizeTrainingChrome(value: unknown): TrainingChromeRecord | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const workspaceId = text(record.workspaceId ?? record.workspace_id);
  const selectedCardTitle = text(
    record.selectedCardTitle ?? record.selected_card_title ?? record.cardTitle ?? record.card_title ?? record.title,
  );
  if (!workspaceId && !selectedCardTitle) {
    return undefined;
  }
  return {
    workspaceId: workspaceId || undefined,
    selectedCardTitle: selectedCardTitle || undefined,
    cardTitle: text(record.cardTitle ?? record.card_title) || undefined,
    title: text(record.title) || undefined,
  };
}

export function selectTrainingChromeForScope(
  value: unknown,
  scope: Pick<RecoveryScope, "workspaceId">,
): TrainingChromeRecord | undefined {
  const record = normalizeTrainingChrome(value);
  return record && isCurrentForWorkspace(record, scope.workspaceId) ? record : undefined;
}

export function trainingRecordMatchesWorkspace(
  value: unknown,
  workspaceId: string,
): boolean {
  const record = asRecord(value);
  if (!record) {
    return false;
  }
  const stamped = text(record.workspaceId ?? record.workspace_id);
  if (!stamped) {
    return true;
  }
  const scope = text(workspaceId);
  if (!scope) {
    return true;
  }
  return stamped === scope;
}

export function selectProviderCapabilityForScope(
  value: unknown,
  scope: RecoveryScope,
): ProviderCapabilityRecoveryRecord | undefined {
  const record = normalizeProviderCapabilityRecovery(value);
  return record && isCurrentForProvider(record, scope) ? record : undefined;
}

export function preferAuthoritativeProviderLastTest<T extends { ok?: boolean; checkedAt?: string }>(
  leftover: T | undefined,
  recovered: T | undefined,
): T | undefined {
  if (!leftover) {
    return recovered;
  }
  if (!recovered) {
    return leftover;
  }
  const leftoverMs = Date.parse(leftover.checkedAt ?? "");
  const recoveredMs = Date.parse(recovered.checkedAt ?? "");
  if (Number.isFinite(leftoverMs) && Number.isFinite(recoveredMs) && leftoverMs !== recoveredMs) {
    return leftoverMs > recoveredMs ? leftover : recovered;
  }
  if (leftover.ok !== true) {
    return leftover;
  }
  if (recovered.ok !== true) {
    return recovered;
  }
  return recovered;
}

export function selectStreamingCheckpointForScope(
  value: unknown,
  scope: RecoveryScope,
): StreamingCheckpointRecord | undefined {
  const recovered = recoverStreamingCheckpointAfterRestart(value);
  return recovered && isCurrentForProvider(recovered, scope) ? recovered : undefined;
}

export type FormalPlanIdentityRecord = {
  workspaceId?: string;
  id?: string;
  title?: string;
  summary?: string;
  currentStep?: string;
};

export function normalizeFormalPlanIdentity(value: unknown): FormalPlanIdentityRecord | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const workspaceId = text(record.workspaceId ?? record.workspace_id);
  const id = text(record.id ?? record.planId ?? record.plan_id);
  const title = text(record.title);
  const summary = text(record.summary ?? record.objective);
  const currentStep = text(record.currentStep ?? record.current_step);
  if (!workspaceId && !id && !title && !summary && !currentStep) {
    return undefined;
  }
  return {
    workspaceId: workspaceId || undefined,
    id: id || undefined,
    title: title || undefined,
    summary: summary || undefined,
    currentStep: currentStep || undefined,
  };
}

export function formalPlanIdentityIsLive(value: unknown): boolean {
  if (value == null) {
    return false;
  }
  const record = normalizeFormalPlanIdentity(value);
  if (!record) {
    return false;
  }
  const raw = asRecord(value);
  const stageCount = Array.isArray(raw?.stages)
    ? raw.stages.length
    : Array.isArray(raw?.phases)
      ? raw.phases.length
      : 0;
  return Boolean(record.id || record.title || record.summary || record.currentStep || stageCount);
}

export type NextStepHintIdentityRecord = {
  workspaceId?: string;
  title?: string;
  summary?: string;
  recommendedAction?: string;
};

export function normalizeNextStepHintIdentity(value: unknown): NextStepHintIdentityRecord | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const workspaceId = text(record.workspaceId ?? record.workspace_id);
  const title = text(record.title ?? record.label ?? record.nextStep ?? record.next_step);
  const summary = text(record.summary ?? record.detail);
  const recommendedAction = text(record.recommendedAction ?? record.recommended_action);
  if (!workspaceId && !title && !summary && !recommendedAction) {
    return undefined;
  }
  return {
    workspaceId: workspaceId || undefined,
    title: title || undefined,
    summary: summary || undefined,
    recommendedAction: recommendedAction || undefined,
  };
}

export function selectNextStepHintForScope(
  value: unknown,
  scope: Pick<RecoveryScope, "workspaceId">,
): NextStepHintIdentityRecord | undefined {
  const record = normalizeNextStepHintIdentity(value);
  return record && isCurrentForWorkspace(record, scope.workspaceId) ? record : undefined;
}

export type CoachingAdaptationIdentityRecord = {
  workspaceId?: string;
  summary?: string;
  evidence?: string[];
};

export function normalizeCoachingAdaptationIdentity(
  value: unknown,
): CoachingAdaptationIdentityRecord | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }
  const workspaceId = text(record.workspaceId ?? record.workspace_id);
  const summary = text(record.summary);
  const evidence = Array.isArray(record.evidence)
    ? record.evidence
        .map((item) => text(item))
        .filter((item): item is string => Boolean(item))
    : [];
  if (!workspaceId && !summary && evidence.length === 0) {
    return undefined;
  }
  return {
    workspaceId: workspaceId || undefined,
    summary: summary || undefined,
    evidence: evidence.length > 0 ? evidence : undefined,
  };
}

export function selectCoachingAdaptationForScope(
  value: unknown,
  scope: Pick<RecoveryScope, "workspaceId">,
): CoachingAdaptationIdentityRecord | undefined {
  const record = normalizeCoachingAdaptationIdentity(value);
  return record && isCurrentForWorkspace(record, scope.workspaceId) ? record : undefined;
}

export function selectResourcesForScope(
  value: unknown,
  scope: Pick<RecoveryScope, "workspaceId">,
): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Record<string, unknown> => {
    const record = asRecord(item);
    return Boolean(record) && trainingRecordMatchesWorkspace(record, scope.workspaceId);
  });
}
