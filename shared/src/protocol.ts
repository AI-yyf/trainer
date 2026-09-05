import type {
  AffectState,
  CoachingState,
  CoachingScenario,
  EvaluationReport,
  GlobalPlan,
  GlobalPlanProjectLink,
  ImplementationGuide,
  LearnerSignal,
  LearnerState,
  LearningPlan,
  MemorySnapshot,
  PlanRuntimeStatus,
  PrincipleNote,
  ProviderConfig,
  ProjectAdaptationGuide,
  ProjectIdea,
  ProjectSourceSuggestion,
  ResourceRecord,
  TaskSpec,
  TeachingDecision,
  ToneDecision,
  UserProfile,
} from "./models";
import type { ComposerLanguage } from "./types";
import {
  normalizeOperationReliabilityOutcome,
  normalizeOperationReliabilityPhase,
  operationReliabilityLooksSuccessful,
} from "./operationReliabilityGovernance";

export type WorkbenchPanel = "coach" | "plan" | "settings";

export type CoachActionType =
  | "plan"
  | "next_task"
  | "review"
  | "hint"
  | "retry_review"
  | "task";

export type CoachArtifactKind =
  | "task"
  | "plan"
  | "evaluation"
  | "note"
  | "idea_implementation"
  | "project_idea"
  | "project_adaptation"
  | "project_source"
  | "principle"
  | "review"
  | "plan_update"
  | "next_step";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
};

export type NextStepHintSource =
  | "agent_loop"
  | "coach_turn"
  | "active_thread"
  | "coaching_state"
  | "plan"
  | "implementation_guide"
  | "evaluation"
  | "task"
  | "review";

export type NextStepHintContinueIn = "coach" | "plan" | "training";

export type NextStepHint = {
  title: string;
  summary?: string;
  recommendedAction?: CoachActionType;
  focusArea?: string;
  prompt?: string;
  resumeThread?: string;
  source?: NextStepHintSource;
  continueIn?: NextStepHintContinueIn;
  verification?: string[];
};

export type AgentCheckpointSummary = {
  checkpointId: string;
  sessionId: string;
  createdAt?: string;
  nextStep?: string;
};

export type AgentMeta = {
  agentic?: boolean;
  summary?: string;
  nextStep?: string;
  stopReason?: string;
  decision?: string;
  blocker?: string;
  teachingNote?: string;
  confidence?: string;
  evidence?: string[];
  resumeThread?: string;
  fellBack?: boolean;
  toolEvents?: Array<Record<string, unknown>>;
  steps?: Array<Record<string, unknown>>;
  attachmentsPresent?: boolean;
  imageAttachmentCount?: number;
  attachmentsDeliveredToModel?: boolean;
  attachmentsDeliveryPath?: string;
  attachmentsDeliveryReason?: string;
  coachVisibleStatus?: CoachVisibleStatusPart;
  nextStepHint?: NextStepHint;
  checkpointId?: string;
  recoveryAvailable?: boolean;
};

/**
 * Research compatibility surface
 *
 * These protocol types remain exported for legacy/internal research flows.
 * They are intentionally grouped away from the primary coach-first protocol
 * so the main reading path stays centered on coach / plan / task traffic.
 */

export type ScheduleCadence = "daily" | "weekly" | "biweekly" | "monthly";

export type AgentRole = "researcher" | "editor" | "critic" | "synthesizer";

export type ThemeStatus = "planning" | "active" | "paused" | "completed";

export type ThreadDepth = "shallow" | "medium" | "deep";

export type ArtifactKind = "note" | "draft" | "summary" | "report" | "outline" | "bibliography";

export type ApprovalStatus = "pending" | "approved" | "rejected";

/**
 * Kept for compatibility with older research scheduling payloads.
 */
export type ResearchCheckpoint = {
  id: string;
  label: string;
  due_date: string;
  completed: boolean;
};

export type ResearchSchedule = {
  start_date: string | null;
  end_date: string | null;
  cadence: ScheduleCadence | null;
  checkpoints: ResearchCheckpoint[];
};

export type ResearchThread = {
  id: string;
  angle: string;
  depth: ThreadDepth;
  status: string;
  findings_count: number;
};

export type ResearchTheme = {
  id: string;
  title: string;
  description: string;
  duration_weeks: number;
  status: ThemeStatus;
  schedule: ResearchSchedule;
  threads: ResearchThread[];
  artifacts_count: number;
  created_at: string;
  updated_at: string;
};

export type ThinkingEntry = {
  id: string;
  role: AgentRole;
  question: string;
  conclusion: string;
  created_at: string;
};

export type AgentState = {
  current_role: AgentRole;
  thinking_log: ThinkingEntry[];
  pending_questions: string[];
  self_review_count: number;
  current_iteration: number;
  max_review_rounds: number;
};

export type ResearchApproval = {
  id: string;
  title: string;
  description: string;
  created_at: string;
  agent_context: Record<string, unknown>;
};

/**
 * Compatibility-only gate shape for the older research workbench flow.
 */
export type WorkbenchGate = {
  messages: ChatMessage[];
  pending_approvals: string[];
  notifications: string[];
};

export type ResearchProject = {
  id: string;
  title: string;
  description: string;
  themes: ResearchTheme[];
  agent_state: AgentState;
  gate: WorkbenchGate;
  active_themes_count: number;
  created_at: string;
  updated_at: string;
};

export type ResearchScheduleStatus = {
  theme_id: string;
  theme_title: string;
  status: ThemeStatus;
  duration_weeks: number;
  progress_percentage: number;
  time_elapsed_percentage: number;
  next_checkpoint: ResearchCheckpoint | null;
  overdue_checkpoints: ResearchCheckpoint[];
  threads_count: number;
  artifacts_count: number;
};

// End research compatibility surface

export type WorkbenchSuggestedAction = {
  id: string;
  label: string;
  action: string;
  rationale?: string;
  prompt?: string;
  focusArea?: string;
};

export type WorkbenchSnapshot = {
  sidecarStatus: "unknown" | "starting" | "ready" | "error";
  activePanel: WorkbenchPanel;
  messages: ChatMessage[];
  profile?: UserProfile;
  plan?: LearningPlan;
  globalPlan?: GlobalPlan;
  projectPlanLink?: GlobalPlanProjectLink;
  currentTask?: TaskSpec;
  evaluation?: EvaluationReport;
  memory: MemorySnapshot;
  provider?: ProviderConfig;
  coachingState?: CoachingState;
  learnerState?: LearnerState;
  affectState?: AffectState;
  teachingDecision?: TeachingDecision;
  toneDecision?: ToneDecision;
  implementationGuide?: ImplementationGuide;
  projectIdeas?: ProjectIdea[];
  projectAdaptationGuide?: ProjectAdaptationGuide;
  projectSources?: ProjectSourceSuggestion[];
  principleNotes?: PrincipleNote;
  reviewQueueSummary: string;
  nextReviewDue?: string;
  planRuntimeStatus?: PlanRuntimeStatus;
  suggestedActions?: WorkbenchSuggestedAction[];
};

export type ViewNodeKind =
  | "plan"
  | "memory"
  | "resource"
  | "weakness"
  | "review"
  | "session";

export type TreeNode = {
  id: string;
  kind: ViewNodeKind;
  label: string;
  description?: string;
  collapsible?: boolean;
  children?: TreeNode[];
  command?: string;
};

export type SessionStartRequest = {
  profile?: Partial<UserProfile>;
  workspaceId: string;
  workspaceName: string;
  workspacePath?: string;
};

export type SessionMessageRequest = {
  sessionId?: string;
  message: string;
  formalPlanMutation?: boolean;
  activeView?: "coach" | "plan" | "resources" | "training" | "settings";
  resourceIds?: string[];
  currentFile?: {
    path: string;
    languageId: string;
    content: string;
    contentExcerpt?: string;
    contentLineSpan?: string;
    contentStrategy?: string;
    selectionText?: string;
    selectionRange?: string;
    diagnostics?: string[];
    recentFiles?: string[];
    recentEditedFiles?: string[];
    relatedFiles?: Array<Record<string, string>>;
  };
  responseLanguage?: string;
  answerMode?: "auto" | "coach-first" | "guided" | "balanced" | "direct";
  coachDefaults?: {
    memoryScope?: "project" | "personal" | "session";
    workingSetMode?: "focused" | "balanced" | "broad";
    reviewCadence?: "light" | "steady" | "active";
    reviewReminderMode?: "due" | "ahead" | "digest";
    workspaceMemoryToggles?: {
      decisions?: boolean;
      patterns?: boolean;
      resources?: boolean;
    };
  };
};

export type SessionMessageResponse = {
  sessionId: string;
  reply: ChatMessage;
  snapshot: WorkbenchSnapshot;
  agentMeta?: AgentMeta;
  agent?: AgentMeta;
  coachTurn?: {
    scenario: CoachArtifactKind | CoachingScenario;
    learner_signal?: LearnerSignal;
    summary: string;
    next_step: string;
    encouragement?: string;
    teaching_mode?: "coach" | "practice" | "review" | "principle" | "plan";
    emotional_tone?: "steady" | "supportive" | "challenging";
    review_rhythm?: string;
    teaching_observation?: string;
    intervention_strategy?: string;
    teaching_goal?: string;
    resume_thread?: string;
    support_strategy?: string;
    decision_reason?: string;
    tone?: "steady" | "encouraging" | "concise_rescue" | "reflective";
    verbosity_bias?: "short" | "medium" | "expanded";
    active_stage?: string;
    active_task?: string;
    due_review_count?: number;
    review_queue_summary?: string;
    failing_checks?: string[];
    artifact_kinds?: CoachArtifactKind[];
    suggested_action_types?: CoachActionType[];
    background_mode?: "embedded";
  };
  learnerState?: LearnerState;
  affectState?: AffectState;
  teachingDecision?: TeachingDecision;
  toneDecision?: ToneDecision;
  suggestedActions: Array<{
    id: string;
    label: string;
    action: CoachActionType;
    rationale?: string;
    artifactKind?: CoachArtifactKind;
    prompt?: string;
    focusArea?: string;
  }>;
  artifacts?: Array<{
    kind: CoachArtifactKind;
    title: string;
    summary?: string;
    content?: string;
    bullets?: string[];
    teaser?: string;
    recommendedAction?: CoachActionType;
    rationale?: string;
    focusArea?: string;
    verification?: string[];
    metadata?: Record<string, unknown>;
  }>;
  pedagogy?: {
    implementationGuide?: ImplementationGuide;
    projectIdeas?: ProjectIdea[];
    projectAdaptationGuide?: ProjectAdaptationGuide;
    principleNotes?: PrincipleNote;
  };
};

export type PlanGenerateRequest = {
  profile: UserProfile;
  goals: string[];
  constraints: string[];
  resourceIds?: string[];
};

export type PlanUpdateRequest = {
  planId: string;
  instructions: string;
  freeze?: boolean;
};

export type TaskSpecifyRequest = {
  sessionId?: string;
  naturalLanguageGoal: string;
};

export type TaskNextRequest = {
  sessionId?: string;
  focusArea?: string;
};

export type EvaluateCurrentFileRequest = {
  sessionId?: string;
  taskSpecId?: string;
  filePath: string;
  languageId: string;
  content: string;
};

export type ProviderTestRequest = {
  provider: ProviderConfig;
  apiKey?: string;
  probeMessage?: string;
  responseLanguage?: string;
};

// =============================================================================
// Typed message parts
// =============================================================================

export const trainerMessagePartTypes = [
  "markdown",
  "code",
  "diff",
  "math",
  "mermaid",
  "table",
  "citation",
  "tool_call",
  "tool_result",
  "reasoning",
  "coach_visible_status",
  "training_card",
  "plan_update",
  "test_result",
  "file_preview",
  "checklist",
  "alert",
] as const;

export type TrainerMessagePartType = (typeof trainerMessagePartTypes)[number];

export type MarkdownPart = {
  type: "markdown";
  content: string;
};

export type CodePart = {
  type: "code";
  code: string;
  language?: string;
  path?: string;
};

export type DiffPart = {
  type: "diff";
  patch: string;
  language?: string;
};

export type MathPart = {
  type: "math";
  tex: string;
  display?: boolean;
};

export type MermaidPart = {
  type: "mermaid";
  source: string;
};

export type TablePart = {
  type: "table";
  columns: string[];
  rows: Array<Array<string | number | boolean | null>>;
};

export type CitationPart = {
  type: "citation";
  resourceId: string;
  chunkId?: string;
  label: string;
  title?: string;
  source?: string;
  trustScore?: number;
};

export type ToolCallPart = {
  type: "tool_call";
  id: string;
  name: string;
  status: "pending" | "called" | "completed" | "failed" | "cancelled";
  args: Record<string, unknown>;
  step?: number;
};

export type ToolResultPart = {
  type: "tool_result";
  callId: string;
  name?: string;
  result?: unknown;
  error?: string;
  step?: number;
  displayKind?: "practice_verification";
  status?: string;
  summary?: string;
  detail?: string;
  nextStep?: string;
  passed?: boolean;
  path?: string;
};

export type TrainerToolActivity = {
  id: string;
  name: string;
  status: "running" | "succeeded" | "failed";
  args?: Record<string, unknown>;
  result?: unknown;
  step?: number;
};

export type TrainerToolActivityUpdate = {
  id: string;
  name?: string;
  status: TrainerToolActivity["status"];
  args?: Record<string, unknown>;
  result?: unknown;
  step?: number;
};

export type TrainerStreamingState = {
  isStreaming: boolean;
  streamedContent: string;
  streamMessageId?: string;
  streamError?: string;
  agentActivity: TrainerToolActivity[];
  agentStep?: number;
  completionSummary?: string;
  completionNextStep?: string;
  completionStopReason?: string;
  toolCount?: number;
  agentic?: boolean;
  reliabilityPhase?:
    | "intent"
    | "pending"
    | "executing"
    | "succeeded"
    | "failed"
    | "acked"
    | "cancelled";
  reliabilityOutcome?: "success" | "failure" | "cancelled" | "timeout" | "";
};

export type TrainerOperationMessage = {
  tone: "info" | "success" | "error";
  message: string;
};

export type ReasoningPart = {
  type: "reasoning";
  summary: string;
  detail?: string;
  redacted?: boolean;
  sourceChain?: string[];
  hintLadder?: string[];
  verificationSteps?: string[];
};

export type CoachVisibleStatusPart = {
  type: "coach_visible_status";
  status: "working" | "done" | "blocked" | "degraded";
  summary: string;
  detail?: string;
  nextStep?: string;
  resumeThread?: string;
  stopReason?: string;
  source?: "agent_loop" | "coach" | "system";
  toolNames?: string[];
  stepCount?: number;
  displayKind?: "practice_verification";
  decision?: string;
  blocker?: string;
  teachingNote?: string;
  confidence?: string;
  evidence?: string[];
};

export type TrainingCardPart = {
  type: "training_card";
  cardId: string;
  cardType?: "practice" | "flash";
  title?: string;
  focusArea?: string;
  scenarioPack?: string;
  targetSkill?: string;
  difficulty?: "easy" | "medium" | "hard";
  status?: string;
  whyNow?: string;
  problemStatement?: string;
  deliverable?: string;
  validationMethod?: string;
  successSignal?: string;
  fallbackAction?: string;
  nextAfterCompletion?: string;
  dueAt?: string;
  intervalDays?: number;
  masteryScore?: number;
  stability?: number;
  fsrsDifficulty?: number;
  retrievability?: number;
  fsrsState?: string;
  reviewSource?: string;
  hintLadder?: string[];
  verificationSteps?: string[];
  sourceChain?: string[];
};

export type PlanUpdatePart = {
  type: "plan_update";
  planId: string;
  changes: unknown[];
};

export type TestResultPart = {
  type: "test_result";
  command: string;
  status: "pass" | "fail" | "unknown";
  outputRef?: string;
  detail?: string;
};

export type FilePreviewPart = {
  type: "file_preview";
  resourceId: string;
  path: string;
  title?: string;
  content?: string;
  html?: string;
  assetUri?: string;
  previewTier?: "rich" | "converted" | "metadata";
  previewKind?: string;
  canNativeOpen?: boolean;
  structuredData?: Record<string, unknown>;
  truncated?: boolean;
};

export type ChecklistPart = {
  type: "checklist";
  items: Array<{ label: string; done: boolean }>;
};

export type AlertPart = {
  type: "alert";
  level: "info" | "warn" | "error";
  title: string;
  detail?: string;
};

export type TrainerMessagePart =
  | MarkdownPart
  | CodePart
  | DiffPart
  | MathPart
  | MermaidPart
  | TablePart
  | CitationPart
  | ToolCallPart
  | ToolResultPart
  | ReasoningPart
  | CoachVisibleStatusPart
  | TrainingCardPart
  | PlanUpdatePart
  | TestResultPart
  | FilePreviewPart
  | ChecklistPart
  | AlertPart;

export function normalizeTrainerMessageParts(value: unknown): TrainerMessagePart[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const normalized = value
    .map((item) => normalizeTrainerMessagePart(item))
    .filter((item): item is TrainerMessagePart => Boolean(item));
  return normalized.length > 0 ? normalized : undefined;
}

export function findCoachVisibleStatusPart(
  parts: TrainerMessagePart[] | undefined,
): CoachVisibleStatusPart | undefined {
  if (!Array.isArray(parts) || parts.length === 0) {
    return undefined;
  }
  return parts.find(
    (part): part is CoachVisibleStatusPart => part.type === "coach_visible_status",
  );
}

export function deriveTrainerToolActivity(
  parts: TrainerMessagePart[] | undefined,
): TrainerToolActivity[] {
  if (!Array.isArray(parts) || parts.length === 0) {
    return [];
  }

  let activities: TrainerToolActivity[] = [];

  for (const part of parts) {
    if (part.type === "tool_call") {
      activities = upsertTrainerToolActivity(activities, {
        id: part.id,
        name: part.name,
        status: mapToolCallPartStatus(part.status),
        args: part.args,
        step: part.step,
      });
      continue;
    }

    if (part.type === "tool_result") {
      activities = upsertTrainerToolActivity(activities, {
        id: part.callId,
        name: part.name,
        status: part.error ? "failed" : "succeeded",
        result: part.result,
        step: part.step,
      });
    }
  }

  return activities;
}

export function upsertTrainerToolActivity(
  activities: TrainerToolActivity[] | undefined,
  update: TrainerToolActivityUpdate,
): TrainerToolActivity[] {
  const list = Array.isArray(activities) ? [...activities] : [];
  const existingIndex = list.findIndex((item) => item.id === update.id);
  const current = existingIndex >= 0 ? list[existingIndex] : undefined;
  const next: TrainerToolActivity = {
    id: update.id,
    name: update.name ?? current?.name ?? humanizeToolIdentifier(update.id),
    status: update.status ?? current?.status ?? "running",
  };
  const nextArgs =
    Object.prototype.hasOwnProperty.call(update, "args") ? update.args : current?.args;
  const nextResult =
    Object.prototype.hasOwnProperty.call(update, "result") ? update.result : current?.result;
  const nextStep =
    Object.prototype.hasOwnProperty.call(update, "step")
      ? update.step ?? current?.step
      : current?.step;

  if (nextArgs !== undefined) {
    next.args = nextArgs;
  }
  if (nextResult !== undefined) {
    next.result = nextResult;
  }
  if (nextStep !== undefined) {
    next.step = nextStep;
  }

  if (existingIndex >= 0) {
    list[existingIndex] = next;
    return list;
  }

  list.push(next);
  return list;
}

export function createEmptyTrainerStreamingState(): TrainerStreamingState {
  return {
    isStreaming: false,
    streamedContent: "",
    streamError: undefined,
    streamMessageId: undefined,
    agentActivity: [],
    agentStep: undefined,
    completionSummary: undefined,
    completionNextStep: undefined,
    completionStopReason: undefined,
    toolCount: undefined,
    agentic: undefined,
    reliabilityPhase: undefined,
    reliabilityOutcome: undefined,
  };
}

export function normalizeTrainerStreamingState(value: unknown): TrainerStreamingState {
  const fallback = createEmptyTrainerStreamingState();
  const record = asObjectRecord(value);
  if (!record) {
    return fallback;
  }

  const rawActivities = Array.isArray(record.agentActivity)
    ? record.agentActivity
    : Array.isArray(record.agent_activity)
      ? record.agent_activity
      : [];
  const agentActivity = rawActivities.reduce<TrainerToolActivity[]>((items, item) => {
    const row = asObjectRecord(item);
    const id = asString(row?.id);
    const status = normalizeTrainerToolActivityStatus(asString(row?.status));
    if (!id || !status) {
      return items;
    }
    return upsertTrainerToolActivity(items, {
      id,
      name: asString(row?.name),
      status,
      args: asObjectRecord(row?.args) ?? asObjectRecord(row?.arguments),
      result: row?.result,
      step: asNumber(row?.step),
    });
  }, []);
  const toolCount =
    asNumber(record.toolCount) ??
    asNumber(record.tool_count) ??
    (agentActivity.length > 0 ? agentActivity.length : undefined);

  return {
    isStreaming:
      asBoolean(record.isStreaming) ?? asBoolean(record.is_streaming) ?? fallback.isStreaming,
    streamedContent:
      asString(record.streamedContent) ??
      asString(record.streamed_content) ??
      fallback.streamedContent,
    streamMessageId:
      asString(record.streamMessageId) ?? asString(record.stream_message_id),
    streamError: asString(record.streamError) ?? asString(record.stream_error),
    agentActivity,
    agentStep: asNumber(record.agentStep) ?? asNumber(record.agent_step),
    completionSummary:
      asString(record.completionSummary) ?? asString(record.completion_summary),
    completionNextStep:
      asString(record.completionNextStep) ?? asString(record.completion_next_step),
    completionStopReason:
      asString(record.completionStopReason) ?? asString(record.completion_stop_reason),
    toolCount,
    agentic: asBoolean(record.agentic),
    reliabilityPhase: normalizeOperationReliabilityPhase(
      asString(record.reliabilityPhase) ?? asString(record.reliability_phase),
    ),
    reliabilityOutcome: normalizeOperationReliabilityOutcome(
      asString(record.reliabilityOutcome) ?? asString(record.reliability_outcome),
    ),
  };
}

function localizeTrainerStreamingCopy(
  language: ComposerLanguage,
  english: string,
  chinese: string,
): string {
  return language === "zh-CN" ? chinese : english;
}

export function describeTrainerStopReason(
  stopReason: string | undefined,
  language: ComposerLanguage,
): string | undefined {
  const normalized = stopReason?.trim();
  if (!normalized || normalized === "completed" || normalized === "stop") {
    return undefined;
  }

  const labels: Record<string, { en: string; zh: string }> = {
    cancelled: { en: "Cancelled", zh: "已取消" },
    coach_finalize: { en: "Coach wrapped up", zh: "教练收束" },
    no_progress: { en: "No new evidence", zh: "没有新证据" },
    timeout: { en: "Took too long", zh: "超时" },
    provider_error: { en: "Model error", zh: "模型错误" },
    invalid_key_or_permission: { en: "API key blocked", zh: "API key 被拒绝" },
    model_unsupported: { en: "Model unsupported", zh: "模型不可用" },
    model_not_found: { en: "Model unavailable", zh: "模型无通道" },
    malformed_response: { en: "Protocol mismatch", zh: "protocol 不匹配" },
    rate_limit: { en: "Rate limited", zh: "rate limit" },
    network: { en: "Network issue", zh: "网络问题" },
    language_corruption: { en: "Input corrupted", zh: "\u8f93\u5165\u5df2\u635f\u574f" },
    language_corruption_recovered: { en: "Recovered locally", zh: "已本地接住" },
    agent_error: { en: "Execution error", zh: "执行错误" },
    max_steps: { en: "Step cap reached", zh: "步数上限" },
    local_guided_training: {
      en: "Local guided training (no model call)",
      zh: "本地引导训练（未调用模型）",
    },
  };

  const repairedZhLabels: Partial<Record<keyof typeof labels, string>> = {
    coach_finalize: "教练收束",
    no_progress: "没有新证据",
    timeout: "超时",
    provider_error: "模型错误",
    invalid_key_or_permission: "API key 被拦截",
    model_unsupported: "模型不可用",
    model_not_found: "模型无通道",
    malformed_response: "protocol 不匹配",
    network: "网络问题",
    language_corruption_recovered: "已在本地接住",
    agent_error: "执行错误",
    max_steps: "步数上限",
    local_guided_training: "本地引导训练（未调用模型）",
  };
  for (const [key, value] of Object.entries(repairedZhLabels)) {
    if (value) {
      labels[key as keyof typeof labels].zh = value;
    }
  }

  const entry = labels[normalized.split(":", 1)[0].trim()] ?? labels[normalized];
  if (entry) {
    return language === "zh-CN" ? entry.zh : entry.en;
  }

  const humanized = normalized.replace(/[_-]+/g, " ").trim();
  return humanized.length > 0 ? humanized : undefined;
}

function normalizeTrainerStreamingNoticeText(value: unknown): string | undefined {
  const normalized = asString(value)?.trim();
  return normalized && normalized.length > 0 ? normalized : undefined;
}

function hasRecoverableTrainerStreamingCompletion(state: TrainerStreamingState): boolean {
  if (state.isStreaming || normalizeTrainerStreamingNoticeText(state.streamError)) {
    return false;
  }
  if (
    normalizeTrainerStreamingNoticeText(state.completionSummary) ||
    normalizeTrainerStreamingNoticeText(state.completionNextStep) ||
    normalizeTrainerStreamingNoticeText(state.completionStopReason)
  ) {
    return true;
  }
  if (typeof state.toolCount === "number" || state.agentic !== undefined) {
    return true;
  }
  if (state.agentActivity.length > 0) {
    return true;
  }
  return Boolean(
    state.streamMessageId && normalizeTrainerStreamingNoticeText(state.streamedContent),
  );
}

export function buildTrainerStreamingCompletionMessage(
  language: ComposerLanguage,
  payload: {
    tokens?: number;
    agentic?: boolean;
    summary?: string;
    nextStep?: string;
    toolCount?: number;
  },
): string {
  const summary = normalizeTrainerStreamingNoticeText(payload.summary);
  const nextStep = normalizeTrainerStreamingNoticeText(payload.nextStep);
  if (summary && nextStep) {
    return localizeTrainerStreamingCopy(
      language,
      `${summary} Next: ${nextStep}`,
      `本轮教练收口：${summary} 下一步：${nextStep}`,
    );
  }
  if (summary) {
    return localizeTrainerStreamingCopy(
      language,
      `Coach loop closed: ${summary}`,
      `本轮教练收口：${summary}`,
    );
  }
  if (nextStep) {
    return localizeTrainerStreamingCopy(language, `Next step: ${nextStep}`, `下一步：${nextStep}`);
  }

  const toolCount = typeof payload.toolCount === "number" ? payload.toolCount : undefined;
  if ((toolCount ?? 0) > 0) {
    return localizeTrainerStreamingCopy(
      language,
      `Coach loop completed after ${toolCount} tool step${toolCount === 1 ? "" : "s"}.`,
      `教练回合已完成，共执行 ${toolCount} 个工具步骤。`,
    );
  }
  if (payload.agentic) {
    return localizeTrainerStreamingCopy(language, "Coach loop completed.", "教练回合已完成。");
  }
  if (typeof payload.tokens === "number") {
    return localizeTrainerStreamingCopy(
      language,
      `Stream completed (${payload.tokens} tokens)`,
      `流式回复已完成（${payload.tokens} tokens）。`,
    );
  }
  return localizeTrainerStreamingCopy(language, "Coach reply completed.", "本轮教练回复已完成。");
}

export function buildTrainerStreamingErrorMessage(
  language: ComposerLanguage,
  error: string,
  category?: string,
): string {
  const normalizedError = error.trim();
  const normalizedCategory = category?.trim().toLowerCase();
  const invalidProviderError =
    category === "invalid_key_or_permission" ||
    /401|403|invalid[_\s-]?api[_\s-]?key|incorrect api key|invalid_key_or_permission|unauthorized|forbidden/i.test(
      normalizedError,
    );
  if (invalidProviderError) {
    return localizeTrainerStreamingCopy(
      language,
      "The current API key is invalid or does not have access to this model. Open Settings and update the provider connection.",
      "当前 API key 无效，或没有访问这个模型的权限。请打开设置并更新 provider 连接。",
    );
  }

  const unsupportedModelError =
    category === "model_unsupported" ||
    /model_unsupported|unsupported model|model_not_found|does not exist.*model/i.test(
      normalizedError,
    );
  if (unsupportedModelError) {
    return localizeTrainerStreamingCopy(
      language,
      "The current model is not accepted by this provider. Open Settings and choose a supported model.",
      "当前模型不被这个 provider 接受。请打开设置并选择可用模型。",
    );
  }

  if (
    normalizedCategory === "rate_limit" ||
    /rate[_\s-]?limit|too many requests/i.test(normalizedError)
  ) {
    return localizeTrainerStreamingCopy(
      language,
      "The model is busy right now. Wait a moment, then try again.",
      "模型现在比较忙。等一会儿再试一次。",
    );
  }

  if (
    normalizedCategory === "timeout" ||
    /timed out|timeout|deadline exceeded/i.test(normalizedError)
  ) {
    return localizeTrainerStreamingCopy(
      language,
      "This reply took too long to finish. Try again in a moment.",
      "这次回复花的时间太久了。等一会儿再试一次。",
    );
  }

  if (
    normalizedCategory === "network" ||
    /network|fetch failed|econn|connection refused|dns/i.test(normalizedError)
  ) {
    return localizeTrainerStreamingCopy(
      language,
      "Trainer could not reach the model. Check the connection and try again.",
      "Trainer 暂时连不上模型。检查连接后再试一次。",
    );
  }

  return localizeTrainerStreamingCopy(
    language,
    "Trainer could not finish this reply. Try again in a moment.",
    "Trainer 这次没有完成回复。等一会儿再试一次。",
  );
}

export function deriveTrainerStreamingOperationMessage(
  language: ComposerLanguage,
  value: unknown,
  options?: {
    completionTokens?: number;
    errorCategory?: string;
  },
): TrainerOperationMessage | undefined {
  const state = normalizeTrainerStreamingState(value);
  const streamError = normalizeTrainerStreamingNoticeText(state.streamError);
  if (streamError) {
    return {
      tone: "error",
      message: buildTrainerStreamingErrorMessage(language, streamError, options?.errorCategory),
    };
  }
  if (state.isStreaming) {
    return undefined;
  }
  if (state.completionStopReason?.trim().toLowerCase() === "cancelled") {
    return {
      tone: "info",
      message: localizeTrainerStreamingCopy(
        language,
        "This reply was cancelled. The generated content is still here.",
        "已取消本轮回复，已保留已生成内容。",
      ),
    };
  }
  if (!hasRecoverableTrainerStreamingCompletion(state)) {
    return undefined;
  }
  const stopReason = describeTrainerStopReason(state.completionStopReason, language);
  const message = buildTrainerStreamingCompletionMessage(language, {
    tokens: options?.completionTokens,
    agentic: state.agentic,
    summary: state.completionSummary,
    nextStep: state.completionNextStep,
    toolCount: state.toolCount,
  });
  const hasReliability =
    state.reliabilityPhase !== undefined || state.reliabilityOutcome !== undefined;
  if (hasReliability) {
    const looksSuccessful = operationReliabilityLooksSuccessful({
      phase: state.reliabilityPhase,
      outcome: state.reliabilityOutcome,
      stopReason: state.completionStopReason,
    });
    if (
      state.reliabilityOutcome === "failure" ||
      state.reliabilityPhase === "failed" ||
      !looksSuccessful
    ) {
      return {
        tone: "error",
        message: stopReason ? `${message} (${stopReason})` : message,
      };
    }
  }
  return {
    tone: "success",
    message: stopReason ? `${message} (${stopReason})` : message,
  };
}

export function normalizeNextStepHint(value: unknown): NextStepHint | undefined {
  const record = asObjectRecord(value);
  if (!record) {
    return undefined;
  }
  const title =
    asString(record.title) ??
    asString(record.label) ??
    asString(record.nextStep) ??
    asString(record.next_step);
  if (!title) {
    return undefined;
  }
  return {
    title,
    summary: asString(record.summary) ?? asString(record.detail),
    recommendedAction: normalizeCoachActionType(
      asString(record.recommendedAction) ?? asString(record.recommended_action),
    ),
    focusArea: asString(record.focusArea) ?? asString(record.focus_area),
    prompt: asString(record.prompt),
    resumeThread: asString(record.resumeThread) ?? asString(record.resume_thread),
    source: normalizeNextStepHintSource(asString(record.source)),
    continueIn: normalizeNextStepHintContinueIn(
      asString(record.continueIn) ?? asString(record.continue_in),
    ),
    verification: asStringArray(record.verification),
  };
}

function normalizeTrainerMessagePart(value: unknown): TrainerMessagePart | undefined {
  const record = asObjectRecord(value);
  if (!record) {
    return undefined;
  }
  const rawType = asString(record.type);
  const type = normalizePartType(rawType);
  if (!type) {
    return undefined;
  }

  switch (type) {
    case "markdown": {
      const content = asString(record.content);
      return content ? { type, content } : undefined;
    }
    case "code": {
      const code = asString(record.code) ?? asString(record.content);
      return code
        ? {
            type,
            code,
            language: asString(record.language),
            path: asString(record.path),
          }
        : undefined;
    }
    case "diff": {
      const patch = asString(record.patch) ?? asString(record.diff);
      return patch
        ? {
            type,
            patch,
            language: asString(record.language),
          }
        : undefined;
    }
    case "math": {
      const tex = asString(record.tex) ?? asString(record.content);
      return tex
        ? {
            type,
            tex,
            display: asBoolean(record.display),
          }
        : undefined;
    }
    case "mermaid": {
      const source = asString(record.source) ?? asString(record.content);
      return source ? { type, source } : undefined;
    }
    case "table": {
      const columns = asStringArray(record.columns) ?? [];
      const rows = Array.isArray(record.rows)
        ? record.rows.map((row) =>
            Array.isArray(row)
              ? row.map((cell) =>
                  typeof cell === "string" ||
                  typeof cell === "number" ||
                  typeof cell === "boolean" ||
                  cell === null
                    ? cell
                    : JSON.stringify(cell),
                )
              : [],
          )
        : [];
      return columns.length > 0 || rows.length > 0 ? { type, columns, rows } : undefined;
    }
    case "citation": {
      const resourceId = asString(record.resourceId) ?? asString(record.resource_id);
      const label = asString(record.label) ?? asString(record.title) ?? asString(record.source);
      return resourceId && label
        ? {
            type,
            resourceId,
            chunkId: asString(record.chunkId) ?? asString(record.chunk_id),
            label,
            title: asString(record.title),
            source: asString(record.source),
            trustScore: asNumber(record.trustScore) ?? asNumber(record.trust_score),
          }
        : undefined;
    }
    case "tool_call": {
      const id = asString(record.id) ?? asString(record.callId) ?? asString(record.call_id);
      const name = asString(record.name);
      return id && name
        ? {
            type,
            id,
            name,
            status: normalizeToolCallStatus(
              asString(record.status) ?? asString(record.state),
            ),
            args:
              asObjectRecord(record.args) ??
              asObjectRecord(record.arguments) ??
              asObjectRecord(record.parameters) ??
              {},
            step: asNumber(record.step),
          }
        : undefined;
    }
    case "tool_result": {
      const callId = asString(record.callId) ?? asString(record.call_id) ?? asString(record.id);
      const output = record.result ?? record.output;
      const error =
        asString(record.error) ??
        (asObjectRecord(output) && asString(asObjectRecord(output)?.error));
      return callId
        ? {
            type,
            callId,
            name:
              asString(record.name) ??
              asString(record.toolName) ??
              asString(record.tool_name),
            result: output,
            error,
            step: asNumber(record.step),
          }
        : undefined;
    }
    case "reasoning": {
      const summary = asString(record.summary) ?? asString(record.content);
      return summary
        ? {
            type,
            summary,
            detail: asString(record.detail),
            redacted: asBoolean(record.redacted),
            sourceChain: asStringArray(record.sourceChain) ?? asStringArray(record.source_chain),
            hintLadder: asStringArray(record.hintLadder) ?? asStringArray(record.hint_ladder),
            verificationSteps:
              asStringArray(record.verificationSteps) ?? asStringArray(record.verification_steps),
          }
        : undefined;
    }
    case "coach_visible_status": {
      const summary = asString(record.summary) ?? asString(record.content);
      return summary
        ? {
            type,
            status: normalizeCoachVisibleStatus(
              asString(record.status) ?? asString(record.state),
            ),
            summary,
            detail: asString(record.detail),
            nextStep: asString(record.nextStep) ?? asString(record.next_step),
            resumeThread:
              asString(record.resumeThread) ?? asString(record.resume_thread),
            stopReason: asString(record.stopReason) ?? asString(record.stop_reason),
            source: normalizeCoachVisibleStatusSource(asString(record.source)),
            toolNames: asStringArray(record.toolNames) ?? asStringArray(record.tool_names),
            stepCount: asNumber(record.stepCount) ?? asNumber(record.step_count),
            displayKind:
              asString(record.displayKind) === "practice_verification" ||
              asString(record.display_kind) === "practice_verification"
                ? "practice_verification"
                : undefined,
            decision: asString(record.decision) ?? undefined,
            blocker: asString(record.blocker) ?? undefined,
            teachingNote:
              asString(record.teachingNote) ?? asString(record.teaching_note) ?? undefined,
            confidence: asString(record.confidence) ?? undefined,
            evidence: asStringArray(record.evidence) ?? undefined,
          }
        : undefined;
    }
    case "training_card": {
      const cardId = asString(record.cardId) ?? asString(record.card_id);
      return cardId
        ? {
            type,
            cardId,
            cardType: normalizeTrainingCardType(
              asString(record.cardType) ?? asString(record.card_type),
            ),
            title: asString(record.title),
            focusArea: asString(record.focusArea) ?? asString(record.focus_area),
            scenarioPack: asString(record.scenarioPack) ?? asString(record.scenario_pack),
            targetSkill: asString(record.targetSkill) ?? asString(record.target_skill),
            difficulty: normalizeTrainingDifficulty(asString(record.difficulty)),
            status: asString(record.status),
            whyNow: asString(record.whyNow) ?? asString(record.why_now),
            problemStatement:
              asString(record.problemStatement) ?? asString(record.problem_statement),
            deliverable: asString(record.deliverable),
            validationMethod:
              asString(record.validationMethod) ?? asString(record.validation_method),
            successSignal: asString(record.successSignal) ?? asString(record.success_signal),
            fallbackAction:
              asString(record.fallbackAction) ?? asString(record.fallback_action),
            nextAfterCompletion:
              asString(record.nextAfterCompletion) ?? asString(record.next_after_completion),
            dueAt: asString(record.dueAt) ?? asString(record.due_at),
            intervalDays: asNumber(record.intervalDays) ?? asNumber(record.interval_days),
            masteryScore: asNumber(record.masteryScore) ?? asNumber(record.mastery_score),
            stability: asNumber(record.stability),
            fsrsDifficulty:
              asNumber(record.fsrsDifficulty) ?? asNumber(record.fsrs_difficulty),
            retrievability: asNumber(record.retrievability),
            fsrsState: asString(record.fsrsState) ?? asString(record.fsrs_state),
            reviewSource: asString(record.reviewSource) ?? asString(record.review_source),
            hintLadder: asStringArray(record.hintLadder) ?? asStringArray(record.hint_ladder),
            verificationSteps:
              asStringArray(record.verificationSteps) ?? asStringArray(record.verification_steps),
            sourceChain: asStringArray(record.sourceChain) ?? asStringArray(record.source_chain),
          }
        : undefined;
    }
    case "plan_update": {
      const planId = asString(record.planId) ?? asString(record.plan_id);
      const changes = Array.isArray(record.changes)
        ? record.changes
        : record.change !== undefined
          ? [record.change]
          : [];
      return planId ? { type, planId, changes } : undefined;
    }
    case "test_result": {
      const command = asString(record.command);
      return command
        ? {
            type,
            command,
            status: normalizeTestStatus(asString(record.status)),
            outputRef: asString(record.outputRef) ?? asString(record.output_ref),
            detail: asString(record.detail),
          }
        : undefined;
    }
    case "file_preview": {
      const resourceId = asString(record.resourceId) ?? asString(record.resource_id);
      const filePath = asString(record.path);
      return resourceId && filePath
        ? {
            type,
            resourceId,
            path: filePath,
            title: asString(record.title),
            content: asString(record.content),
            html: asString(record.html),
            assetUri: asString(record.assetUri) ?? asString(record.asset_uri),
            previewTier: normalizePreviewTier(
              asString(record.previewTier) ?? asString(record.preview_tier),
            ),
            previewKind: asString(record.previewKind) ?? asString(record.preview_kind),
            canNativeOpen:
              asBoolean(record.canNativeOpen) ?? asBoolean(record.can_native_open),
            structuredData:
              asObjectRecord(record.structuredData) ?? asObjectRecord(record.structured_data),
            truncated: asBoolean(record.truncated),
          }
        : undefined;
    }
    case "checklist": {
      const rawItems = Array.isArray(record.items)
        ? record.items
        : Array.isArray(record.checklist)
          ? record.checklist
          : [];
      const items = rawItems
        .map((item) => {
          if (typeof item === "string") {
            return { label: item, done: false };
          }
          const row = asObjectRecord(item);
          const label = asString(row?.label) ?? asString(row?.text);
          if (!label) {
            return undefined;
          }
          return {
            label,
            done: asBoolean(row?.done) ?? false,
          };
        })
        .filter((item): item is { label: string; done: boolean } => Boolean(item));
      return items.length > 0 ? { type, items } : undefined;
    }
    case "alert": {
      const title = asString(record.title);
      return title
        ? {
            type,
            level: normalizeAlertLevel(asString(record.level) ?? asString(record.severity)),
            title,
            detail: asString(record.detail),
          }
        : undefined;
    }
    default:
      return undefined;
  }
}

function normalizePartType(value: string | undefined): TrainerMessagePartType | undefined {
  const normalized = value?.trim();
  if (!normalized) {
    return undefined;
  }
  const aliases: Record<string, TrainerMessagePartType> = {
    markdown: "markdown",
    code: "code",
    diff: "diff",
    math: "math",
    mermaid: "mermaid",
    table: "table",
    citation: "citation",
    tool_call: "tool_call",
    toolcall: "tool_call",
    toolCall: "tool_call",
    tool_result: "tool_result",
    toolresult: "tool_result",
    toolResults: "tool_result",
    reasoning: "reasoning",
    reasoningSummary: "reasoning",
    coach_visible_status: "coach_visible_status",
    coachVisibleStatus: "coach_visible_status",
    training_card: "training_card",
    trainingCard: "training_card",
    plan_update: "plan_update",
    planUpdate: "plan_update",
    test_result: "test_result",
    testResult: "test_result",
    file_preview: "file_preview",
    filePreview: "file_preview",
    checklist: "checklist",
    checkList: "checklist",
    alert: "alert",
  };
  return aliases[normalized];
}

function normalizeToolCallStatus(
  value: string | undefined,
): ToolCallPart["status"] {
  if (
    value === "pending" ||
    value === "completed" ||
    value === "failed" ||
    value === "cancelled"
  ) {
    return value;
  }
  return value === "called" ? value : "called";
}

function mapToolCallPartStatus(
  value: ToolCallPart["status"],
): TrainerToolActivity["status"] {
  if (value === "completed") {
    return "succeeded";
  }
  if (value === "failed" || value === "cancelled") {
    return "failed";
  }
  return "running";
}

function normalizeTrainerToolActivityStatus(
  value: string | undefined,
): TrainerToolActivity["status"] | undefined {
  if (value === "running" || value === "succeeded" || value === "failed") {
    return value;
  }
  return undefined;
}

function normalizeCoachVisibleStatus(
  value: string | undefined,
): CoachVisibleStatusPart["status"] {
  if (
    value === "working" ||
    value === "blocked" ||
    value === "degraded"
  ) {
    return value;
  }
  return value === "done" ? value : "done";
}

function normalizeCoachVisibleStatusSource(
  value: string | undefined,
): CoachVisibleStatusPart["source"] {
  if (value === "coach" || value === "system") {
    return value;
  }
  return value === "agent_loop" ? value : undefined;
}

function normalizeCoachActionType(value: string | undefined): CoachActionType | undefined {
  if (
    value === "plan" ||
    value === "next_task" ||
    value === "review" ||
    value === "hint" ||
    value === "retry_review" ||
    value === "task"
  ) {
    return value;
  }
  return undefined;
}

function normalizeNextStepHintSource(
  value: string | undefined,
): NextStepHint["source"] {
  if (
    value === "agent_loop" ||
    value === "coach_turn" ||
    value === "active_thread" ||
    value === "coaching_state" ||
    value === "plan" ||
    value === "implementation_guide" ||
    value === "evaluation" ||
    value === "task" ||
    value === "review"
  ) {
    return value;
  }
  return undefined;
}

function normalizeNextStepHintContinueIn(
  value: string | undefined,
): NextStepHint["continueIn"] {
  if (value === "coach" || value === "plan" || value === "training") {
    return value;
  }
  return undefined;
}

function normalizeTrainingCardType(
  value: string | undefined,
): TrainingCardPart["cardType"] {
  if (value === "flash") {
    return "flash";
  }
  return value === "practice" ? value : undefined;
}

function normalizeTrainingDifficulty(
  value: string | undefined,
): TrainingCardPart["difficulty"] {
  if (value === "easy" || value === "hard") {
    return value;
  }
  return value === "medium" ? value : undefined;
}

function normalizeTestStatus(value: string | undefined): TestResultPart["status"] {
  if (value === "pass" || value === "fail") {
    return value;
  }
  return "unknown";
}

function normalizePreviewTier(
  value: string | undefined,
): FilePreviewPart["previewTier"] {
  if (value === "rich" || value === "converted") {
    return value;
  }
  return value === "metadata" ? value : undefined;
}

function normalizeAlertLevel(value: string | undefined): AlertPart["level"] {
  if (value === "warn" || value === "error") {
    return value;
  }
  return "info";
}

function humanizeToolIdentifier(value: string): string {
  const normalized = value.replace(/[_-]+/g, " ").trim();
  return normalized.length > 0 ? normalized : "tool";
}

function asObjectRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function asStringArray(value: unknown): string[] | undefined {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : undefined;
}
