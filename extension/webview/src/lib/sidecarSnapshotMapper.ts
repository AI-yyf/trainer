import { trainerCommandCatalog } from "../../../../shared/src/commands";
import { createEmptyTrainerStreamingState } from "../../../../shared/src/protocol";
import {
  normalizeProviderProtocol,
  providerProtocolFamily,
} from "../../../../shared/src/providerProtocols";

import { createNeutralBootstrapData } from "./neutralBootstrap";
import type {
  ActiveThreadView,
  BootstrapData,
  CapabilityFlags,
  CoachAnswerMode,
  CoachingState,
  ComposerLanguage,
  ConversationMessage,
  PlanStage,
  ProviderConfigView,
  ResourceRecord,
  ReviewQueueItem,
  WorkspaceTrainingState,
} from "./types";

export interface BrowserTabLiveSummary {
  url: string;
  title: string;
  selection?: string;
}

export interface RedactedWorkspaceProviderSummary {
  configured?: boolean;
  name?: string;
  model?: string;
  protocol?: string;
  api_key_configured?: boolean;
  apiKeyConfigured?: boolean;
  capabilities?: Record<string, unknown>;
}

export interface MapSidecarSnapshotOptions {
  workspaceId: string;
  workspaceName: string;
  paired: boolean;
  needsPairing?: boolean;
  activeTab?: BrowserTabLiveSummary | null;
  workspaceProvider?: RedactedWorkspaceProviderSummary | null;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function asStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean);
}

function toAnswerPolicy(value: string | undefined): CoachAnswerMode {
  if (value === "coach-first" || value === "balanced" || value === "direct" || value === "auto") {
    return value;
  }
  return "auto";
}

function mapCapabilities(raw: Record<string, unknown> | undefined, configured: boolean): CapabilityFlags {
  return {
    chat: asBoolean(raw?.chat) ?? configured,
    responses: asBoolean(raw?.responses) ?? false,
    vision: asBoolean(raw?.vision) ?? false,
    embeddings: asBoolean(raw?.embeddings) ?? false,
    tools: asBoolean(raw?.tools) ?? false,
    jsonSchema: asBoolean(raw?.jsonSchema ?? raw?.json_schema) ?? false,
    structuredOutput: asBoolean(raw?.structuredOutput ?? raw?.structured_output) ?? false,
    streaming: asBoolean(raw?.streaming) ?? configured,
    ...(typeof raw?.thinking === "boolean" ? { thinking: raw.thinking } : {}),
  };
}

function formatTabDisplayLabel(tab: BrowserTabLiveSummary | null | undefined): string | undefined {
  if (!tab?.url) {
    return undefined;
  }
  const cleanTitle = tab.title?.trim();
  try {
    const parsed = new URL(tab.url);
    return cleanTitle ? `${cleanTitle} (${parsed.hostname})` : parsed.href;
  } catch {
    return cleanTitle || tab.url;
  }
}

function mapConversationMessage(raw: unknown, index: number): ConversationMessage {
  const record = asRecord(raw);
  const roleRaw = asString(record?.role);
  const role: ConversationMessage["role"] =
    roleRaw === "user" || roleRaw === "system" ? roleRaw : "assistant";
  const body =
    (typeof record?.body === "string" ? record.body : undefined) ??
    (typeof record?.content === "string" ? record.content : undefined) ??
    "";
  return {
    id:
      asString(record?.id) ??
      asString(record?.message_id) ??
      `msg-${index + 1}`,
    role,
    author:
      asString(record?.author) ??
      (role === "user" ? "You" : role === "system" ? "System" : "Trainer"),
    body,
    timestamp:
      asString(record?.timestamp) ??
      asString(record?.created_at) ??
      "",
    sourceResourceIds:
      asStringArray(record?.sourceResourceIds ?? record?.source_resource_ids),
    contextNote: asString(record?.contextNote ?? record?.context_note),
    sourceNote: asString(record?.sourceNote ?? record?.source_note),
  };
}

function mapResourceRecord(raw: unknown, index: number): ResourceRecord {
  const record = asRecord(raw);
  const kindRaw = asString(record?.kind ?? record?.resource_kind) ?? "url";
  const allowedKinds = new Set([
    "pdf",
    "epub",
    "docx",
    "pptx",
    "html",
    "image",
    "markdown",
    "text",
    "code",
    "url",
    "video",
  ]);
  const kind = (allowedKinds.has(kindRaw) ? kindRaw : "url") as ResourceRecord["kind"];
  const statusRaw = asString(record?.status);
  const status: ResourceRecord["status"] =
    statusRaw === "indexing" || statusRaw === "attention" ? statusRaw : "ready";

  return {
    id: asString(record?.id ?? record?.resource_id) ?? `resource-${index + 1}`,
    title: asString(record?.title ?? record?.name) ?? "Resource",
    kind,
    status,
    summary: asString(record?.summary ?? record?.excerpt) ?? "",
    source: asString(record?.source ?? record?.url),
    canonicalSource: asString(record?.canonicalSource ?? record?.canonical_source),
    collectionPath: asString(record?.collectionPath ?? record?.collection_path),
    tags: asStringArray(record?.tags),
    trustState: asString(record?.trustState ?? record?.trust_state),
    indexState: asString(record?.indexState ?? record?.index_state),
    updatedAt: asString(record?.updatedAt ?? record?.updated_at),
  };
}

function mapDueReviews(raw: unknown): ReviewQueueItem[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const items: ReviewQueueItem[] = [];
  for (const entry of raw) {
    const record = asRecord(entry);
    const concept = asString(record?.concept);
    if (!concept) {
      continue;
    }
    const sourceRaw = asString(record?.source);
    const source: ReviewQueueItem["source"] =
      sourceRaw === "mastery" || sourceRaw === "reflection" || sourceRaw === "plan"
        ? sourceRaw
        : "weakness";
    const severityRaw = asString(record?.severity);
    const severity: ReviewQueueItem["severity"] =
      severityRaw === "low" || severityRaw === "high" ? severityRaw : "medium";
    items.push({
      concept,
      reason: asString(record?.reason) ?? "",
      dueAt: asString(record?.dueAt ?? record?.due_at),
      source,
      severity,
      focusArea: asString(record?.focusArea ?? record?.focus_area),
      intervalDays: asNumber(record?.intervalDays ?? record?.interval_days),
      masteryScore: asNumber(record?.masteryScore ?? record?.mastery_score),
    });
  }
  return items;
}

/**
 * Maps a real Sidecar `/browser/chat/bootstrap` (or SSE inline `snapshot`)
 * response into the canonical `BootstrapData` consumed by `extension/webview`.
 */
export function mapSidecarSnapshotToBootstrapData(
  snapshot: unknown,
  options: MapSidecarSnapshotOptions,
): BootstrapData {
  const baseline = createNeutralBootstrapData(options.paired ? "connected" : "offline");
  const record = asRecord(snapshot);
  const memory = asRecord(record?.memory);
  const profile = asRecord(record?.profile);
  const plan = asRecord(record?.plan);
  const currentTask = asRecord(record?.current_task ?? record?.task);
  const evaluation = asRecord(record?.evaluation);
  const snapshotProvider = asRecord(record?.workspace_provider ?? record?.provider);
  const providerSummary = options.workspaceProvider ?? (snapshotProvider as RedactedWorkspaceProviderSummary | undefined);

  const workspaceId =
    asString(record?.workspace_id ?? record?.workspaceId) ??
    options.workspaceId ??
    "browser-workspace";
  const workspaceName =
    options.workspaceName ||
    asString(record?.workspace_name ?? record?.workspaceName) ||
    workspaceId;

  const providerConfigured = Boolean(
    options.paired &&
      (providerSummary?.configured === true ||
        Boolean(asString(providerSummary?.model))),
  );
  const protocol = normalizeProviderProtocol(
    asString(providerSummary?.protocol) ?? "openai_chat_completions_compatible",
  );
  const capabilities = mapCapabilities(
    asRecord(providerSummary?.capabilities),
    providerConfigured,
  );
  const modelName = asString(providerSummary?.model) ?? "";
  const providerName =
    asString(providerSummary?.name) ?? (providerConfigured ? "Trainer Host" : "");
  const checkedAt = new Date().toISOString();

  const providerConfig: ProviderConfigView = {
    configured: providerConfigured,
    name: providerName,
    baseUrl: providerConfigured ? "loopback://trainer-sidecar" : "",
    model: modelName,
    apiKeyConfigured:
      providerConfigured &&
      (providerSummary?.api_key_configured ?? providerSummary?.apiKeyConfigured ?? true),
    capabilities,
    availableModels: modelName ? [modelName] : [],
    resolvedModel: modelName || undefined,
    modelListStatus: providerConfigured ? "ready" : "idle",
    protocol,
    protocolFamily: providerProtocolFamily(protocol),
    credentialMode: "ui_proxy",
    ...(providerConfigured
      ? {
          lastTestResult: {
            ok: true,
            status: "connected",
            detail: "Paired with local Trainer workspace",
            checkedAt,
            workspaceId,
            providerName,
            baseUrl: "loopback://trainer-sidecar",
            model: modelName,
            protocol,
            protocolFamily: providerProtocolFamily(protocol),
            toolsReady: capabilities.tools,
            toolProbeStatus: capabilities.tools ? "verified" : "unverified",
            streamingReady: capabilities.streaming,
            streamProbeStatus: capabilities.streaming ? "verified" : "unverified",
            capabilityEvidence: [
              {
                name: "tools",
                declared: capabilities.tools,
                observed: capabilities.tools ? true : null,
                state: capabilities.tools ? "verified" : "unverified",
              },
            ],
          },
        }
      : {}),
  };

  const planStagesRaw = Array.isArray(plan?.stages) ? plan.stages : [];
  const mappedStages: PlanStage[] = planStagesRaw.map((stageItem, idx) => {
    const stage = asRecord(stageItem);
    const statusRaw = asString(stage?.status);
    const resourceIds = asStringArray(stage?.resources ?? stage?.resourceIds);
    return {
      id: asString(stage?.id) ?? `stage-${idx + 1}`,
      title: asString(stage?.title) ?? `Stage ${idx + 1}`,
      objective: asString(stage?.goal ?? stage?.objective) ?? "",
      status:
        statusRaw === "active"
          ? "active"
          : statusRaw === "completed" || statusRaw === "done"
            ? "done"
            : "queued",
      ...(resourceIds?.length ? { resourceIds } : {}),
    };
  });

  const rawMessages = Array.isArray(record?.messages)
    ? record.messages
    : Array.isArray(record?.conversation)
      ? record.conversation
      : [];
  const rawResources = Array.isArray(memory?.resources)
    ? memory.resources
    : Array.isArray(record?.resources)
      ? record.resources
      : [];

  const memoryWorkspaceRaw = asRecord(memory?.workspace);
  const responseLanguage = asString(
    memoryWorkspaceRaw?.response_language ?? memoryWorkspaceRaw?.responseLanguage,
  ) as ComposerLanguage | undefined;

  const activeThreadRaw = asRecord(memory?.active_thread ?? memory?.activeThread);
  const activeThread: ActiveThreadView | undefined = activeThreadRaw
    ? {
        scenario: asString(activeThreadRaw.scenario),
        focusArea: asString(activeThreadRaw.focus_area ?? activeThreadRaw.focusArea),
        summary: asString(activeThreadRaw.summary),
        nextStep: asString(activeThreadRaw.next_step ?? activeThreadRaw.nextStep),
        blocker: asString(activeThreadRaw.blocker),
      }
    : undefined;

  const trainingRaw = asRecord(
    record?.workspace_training_state ??
      record?.workspaceTrainingState ??
      memory?.training_state ??
      memory?.workspaceTrainingState,
  );
  const workspaceTrainingState: WorkspaceTrainingState | undefined = trainingRaw
    ? ({
        ...(trainingRaw as unknown as WorkspaceTrainingState),
        workspaceId,
      })
    : { workspaceId };

  const sandboxRoot = `sandbox:/${workspaceId}`;
  const activeTabLabel = formatTabDisplayLabel(options.activeTab);

  return {
    ...baseline,
    sessionHistoryRestored: rawMessages.length > 0,
    workspaceName,
    sessionLabel: asString(record?.session_id ?? record?.sessionId) ?? "",
    connection: {
      state: options.paired ? "connected" : "offline",
      provider: {
        name: providerName,
        model: modelName,
        capabilities,
        protocol,
        protocolFamily: providerProtocolFamily(protocol),
      },
    },
    providerConfig,
    liveContext: {
      activeFile: activeTabLabel,
      activeLanguageId: options.activeTab?.url ? "markdown" : undefined,
      selectionRange: options.activeTab?.selection
        ? `${options.activeTab.selection.length} chars`
        : undefined,
      selectionPreview: options.activeTab?.selection || undefined,
      diagnosticsSummary: "",
      recentFiles: options.activeTab?.url ? [options.activeTab.url] : [],
      recentEditedFiles: [],
      relatedFiles: [],
    },
    profile: {
      learnerName:
        asString(memoryWorkspaceRaw?.learner_name ?? memoryWorkspaceRaw?.learnerName) ?? "",
      goals: asStringArray(profile?.long_term_goals ?? profile?.goals) ?? [],
      weeklyHours: asNumber(profile?.weekly_hours ?? profile?.weeklyHours) ?? 4,
      preferredStyle: asString(profile?.teaching_style ?? profile?.preferredStyle) ?? "auto",
      answerPolicy: toAnswerPolicy(
        asString(profile?.answer_policy ?? profile?.answerPolicy),
      ),
      focusAreas: asStringArray(profile?.preferred_libraries ?? profile?.focusAreas) ?? [],
      targetProject:
        asString(profile?.target_project ?? memoryWorkspaceRaw?.project_context) ?? undefined,
      preferredRhythm:
        asString(memoryWorkspaceRaw?.preferred_rhythm ?? memoryWorkspaceRaw?.preferredRhythm) ??
        undefined,
      preferredLearningMode:
        asString(
          memoryWorkspaceRaw?.preferred_learning_mode ??
            memoryWorkspaceRaw?.preferredLearningMode,
        ) ?? undefined,
      onboardingRequest:
        asString(
          memoryWorkspaceRaw?.onboarding_request ?? memoryWorkspaceRaw?.onboardingRequest,
        ) ?? undefined,
      projectContext:
        asString(memoryWorkspaceRaw?.project_context ?? memoryWorkspaceRaw?.projectContext) ??
        undefined,
    },
    plan: {
      id: asString(plan?.id ?? plan?.plan_id) ?? "",
      title: asString(plan?.title) ?? "",
      frozen: asBoolean(plan?.frozen) ?? false,
      cadence: asString(plan?.cadence) ?? "",
      summary: asString(plan?.summary) ?? "",
      currentStageId: asString(plan?.current_stage_id ?? plan?.currentStageId),
      currentStep: asString(plan?.current_step ?? plan?.currentStep),
      whyNow: asString(plan?.why_now ?? plan?.whyNow),
      verifyMethod: asStringArray(plan?.verify_method ?? plan?.verifyMethod),
      blockedReason: asString(plan?.blocked_reason ?? plan?.blockedReason),
      nextAfterCurrent: asString(plan?.next_after_current ?? plan?.nextAfterCurrent),
      revision: asNumber(plan?._plan_revision ?? plan?.revision),
      stages: mappedStages,
    },
    task: {
      id: asString(currentTask?.id) ?? "",
      title: asString(currentTask?.title) ?? "",
      description:
        asString(currentTask?.natural_language_goal ?? currentTask?.description) ?? "",
      constraints: asStringArray(currentTask?.constraints) ?? [],
      acceptanceCriteria:
        asStringArray(
          currentTask?.verification_strategy ?? currentTask?.acceptanceCriteria,
        ) ?? [],
      nextActionLabel: "Continue",
    },
    evaluation: {
      headline: asString(evaluation?.summary ?? evaluation?.headline) ?? "",
      summary: asString(evaluation?.summary) ?? "",
      passRate: asNumber(evaluation?.pass_rate ?? evaluation?.passRate) ?? 0,
      updatedAt: asString(evaluation?.updated_at ?? evaluation?.updatedAt) ?? "",
      checks: [],
      nextStep: asString(evaluation?.next_step ?? evaluation?.nextStep) ?? "",
    },
    memory: {
      currentFocus:
        asString(memory?.current_focus ?? memory?.recent_summary) ?? "",
      weakSpots: asStringArray(memory?.weaknesses ?? memory?.weakSpots) ?? [],
      recentWins: asStringArray(memory?.recent_wins ?? memory?.recentWins) ?? [],
      reviewSummary: asString(memory?.review_rhythm ?? memory?.reviewSummary) ?? "",
      reviewRhythm: asString(memory?.review_rhythm ?? memory?.reviewRhythm) ?? "",
      dueReviews: mapDueReviews(memory?.due_reviews ?? memory?.dueReviews),
      teachingObservations:
        asStringArray(memory?.teaching_observations ?? memory?.teachingObservations) ?? [],
      dueReviewCount: asNumber(memory?.due_review_count ?? memory?.dueReviewCount) ?? 0,
      activeThread,
      memoryEvidence:
        asStringArray(memory?.memory_evidence ?? memory?.memoryEvidence) ?? [],
      sandboxState: {
        ready: options.paired,
        rootPath: sandboxRoot,
        sandboxRootPath: sandboxRoot,
        activeWorkspaceRoot: sandboxRoot,
        authority: {
          authoritySource: "browser_sidepanel",
          authorityMode: "trainer_sandbox",
          authorityScope: "trainer_sandbox",
          resourceWriteAllowed: options.paired,
          resourceWriteEvidence: {
            operation: "write",
            scope: "trainer_sandbox",
            targetRoot: sandboxRoot,
            allowed: options.paired,
            reason: options.paired ? "paired_browser_sidepanel" : "unpaired_browser_sidepanel",
          },
          permissionLevel: "workspace",
          allowedOperations: options.paired ? ["read", "write"] : ["read"],
          nextSafeAction: "continue",
        },
      },
      workspace: {
        workspaceId,
        windowTrusted: true,
        ...(responseLanguage ? { responseLanguage } : {}),
        trainerWorkspace: {
          status: "managed",
          projectId: workspaceId,
          projectName: workspaceName,
        },
      },
    },
    workspaceTrainingState,
    coachingState: asRecord(record?.coaching_state) as CoachingState | undefined,
    reviewQueueSummary: asString(record?.review_queue_summary) ?? "",
    nextReviewDue: asString(record?.next_review_due),
    streamingState: createEmptyTrainerStreamingState(),
    resources: rawResources.map((item, idx) => mapResourceRecord(item, idx)),
    conversation: rawMessages.map((item, idx) => mapConversationMessage(item, idx)),
    suggestedActions: [],
    commands: trainerCommandCatalog.map((command) => ({ ...command })),
  };
}
