import { SUPPORTED_LANGUAGES } from "../../../../shared/src/types";
import { trainerCommands } from "../../../../shared/src/commands";
import {
  runBrowserPreviewAction,
  type BrowserPreviewBootstrap,
  type BrowserPreviewPatch,
} from "./browserPreviewActions";
import {
  attachBrowserPreviewStreamReader,
  browserPreviewProviderRequestOverride,
  cancelBrowserPreviewStream,
  ensureBrowserPreviewSidecar,
  fetchBrowserPreviewBootstrap,
  isBrowserPreviewFixtureMode,
  mapSandboxPreview,
  registerBrowserPreviewStream,
  releaseBrowserPreviewStream,
  searchBrowserPreviewResources,
  sendBrowserPreviewMessage,
  streamBrowserPreviewMessage,
} from "./browserSidecar";
import { mockBootstrapData } from "./mockData";
import {
  guidedTrainingPreviewScenarios,
  resolveGuidedTrainingPreviewScenarioData,
  type GuidedTrainingPreviewScenario,
} from "./guidedTrainingScenarioPacks";
import type {
  BootstrapData,
  ComposerLanguage,
  HostMessage,
  PersistedWorkbenchState,
  ResourceTrainingHandoffResult,
  SessionMessageRequest,
  WebviewAction,
} from "./types";
import { waitingComposerEnqueueFailureText } from "../../../../shared/src/errorSurfaceSanitizer";
import { stripProviderSnapshotSecrets } from "../../../../shared/src/hostLastTestGovernance";
import { sanitizeVisibleData, sanitizeVisibleText } from "./visibleText";

type BrowserPreviewState = PersistedWorkbenchState & {
  connectionState?: "connected" | "starting" | "offline";
  streamingMode?: "demo";
  vscodeTheme?: "light" | "dark";
  scenario?:
    | "stream"
    | "rich-content"
    | "blocked"
    | "recovery"
    | "ready"
    | "vision-ready"
    | "provider-failure"
    | "provider-failure-empty"
    | "provider-auth-failure"
    | "provider-auth-failure-empty"
    | "empty"
    | "plan-frozen"
    | "plan-blocked"
    | "done"
    | "resource-preview-loaded"
    | "workspace-admission"
    | GuidedTrainingPreviewScenario;
  trainingSubmode?: string;
  workspaceAdmission?:
    | "root-missing"
    | "project-found"
    | "managed"
    | "browse"
    | "ignored";
};

type PreviewProviderConfig = Partial<typeof mockBootstrapData.providerConfig>;

const PREVIEW_HOST_MESSAGE_EVENT = "trainer:host-message";
const PREVIEW_WEBVIEW_ACTION_EVENT = "trainer:webview-action";
const PREVIEW_WORKSPACE_ID_STORAGE_KEY = "trainer:webview:preview:workspace-id";
const TRAINING_PERSISTENCE_REQUEST_ID_KEY = "__trainerTrainingPersistenceId";
const RESOURCE_TRAINING_HANDOFF_REQUEST_ID_KEY = "__trainerResourceTrainingHandoffId";
const LIVE_TRAINING_COMMAND_IDS = new Set<string>([
  trainerCommands.trainingGenerateCard,
  trainerCommands.trainingCardStatusTransition,
  trainerCommands.trainingFlashcardAnswer,
  trainerCommands.trainingTheoryDrillAnswer,
  trainerCommands.trainingPracticeReturn,
  trainerCommands.trainingReflect,
  trainerCommands.trainingReturn,
  trainerCommands.evidenceEnqueue,
  trainerCommands.trainingReviewQueueAction,
  trainerCommands.trainingReviewArtifactAction,
  trainerCommands.trainingScenarioLabAction,
  trainerCommands.trainingDependencySkillMapAction,
]);
const LIVE_TRAINING_PERSISTENCE_COMMAND_IDS = new Set<string>([
  trainerCommands.trainingCardStatusTransition,
  trainerCommands.trainingFlashcardAnswer,
  trainerCommands.trainingTheoryDrillAnswer,
  trainerCommands.trainingPracticeReturn,
  trainerCommands.trainingReflect,
  trainerCommands.trainingReturn,
  trainerCommands.evidenceEnqueue,
  trainerCommands.trainingReviewArtifactAction,
]);
const LIVE_AGENT_HANDOFF_COMMAND_IDS = new Set<string>([
  trainerCommands.openResource,
]);

let livePreviewSessionId: string | undefined;
let livePreviewBootstrap: BootstrapData | undefined;

function isWebviewAction(value: unknown): value is WebviewAction {
  return Boolean(
    value &&
      typeof value === "object" &&
      "type" in value &&
      typeof value.type === "string" &&
      value.type !== "webview/ready" &&
      value.type !== "debug/visibleFacts" &&
      value.type !== "debug/error",
  );
}

function currentBrowserPreviewBootstrap(): BrowserPreviewBootstrap {
  const injected = window.__TRAINER_BOOTSTRAP__;
  if (injected && typeof injected === "object") {
    return injected as BrowserPreviewBootstrap;
  }
  return structuredClone(mockBootstrapData) as BrowserPreviewBootstrap;
}

function mergeBrowserPreviewPatch(
  bootstrap: BrowserPreviewBootstrap,
  patch: BrowserPreviewPatch,
): BrowserPreviewBootstrap {
  return {
    ...bootstrap,
    ...patch,
  };
}

function emitBrowserPreviewHostMessage(message: HostMessage): void {
  window.dispatchEvent(
    new CustomEvent(PREVIEW_HOST_MESSAGE_EVENT, {
      detail: message,
    }),
  );
}

function resolveBrowserPreviewWorkspaceId(): string {
  if (typeof window === "undefined") {
    return "trainer-web-preview";
  }

  const existing = window.sessionStorage.getItem(PREVIEW_WORKSPACE_ID_STORAGE_KEY)?.trim();
  if (existing) {
    return existing;
  }

  const nextId = `trainer-web-preview-${Math.random().toString(36).slice(2, 10)}`;
  window.sessionStorage.setItem(PREVIEW_WORKSPACE_ID_STORAGE_KEY, nextId);
  return nextId;
}

function browserPreviewActionPayload(action: WebviewAction): Record<string, unknown> | undefined {
  if (action.type !== "command/execute") {
    return undefined;
  }
  const payload = action.payload.payload;
  return payload && typeof payload === "object" ? (payload as Record<string, unknown>) : undefined;
}

function browserPreviewTrainingPersistenceRequest(
  action: WebviewAction,
): { requestId: string; commandId: string } | undefined {
  if (
    action.type !== "command/execute" ||
    !LIVE_TRAINING_PERSISTENCE_COMMAND_IDS.has(action.payload.commandId)
  ) {
    return undefined;
  }
  const requestId = browserPreviewString(
    browserPreviewActionPayload(action)?.[TRAINING_PERSISTENCE_REQUEST_ID_KEY],
  );
  return /^[a-z0-9-]{1,96}$/i.test(requestId)
    ? { requestId, commandId: action.payload.commandId }
    : undefined;
}

function browserPreviewReliabilityFields(
  payload: Record<string, unknown> | undefined,
): {
  request_id: string;
  idempotency_key: string;
  revision: number;
  timeout_ms: number;
  cancel: boolean;
} {
  const requestId =
    browserPreviewString(payload?.[TRAINING_PERSISTENCE_REQUEST_ID_KEY]) ||
    browserPreviewString(payload?.requestId) ||
    browserPreviewString(payload?.request_id);
  const idempotencyKey =
    browserPreviewString(payload?.idempotencyKey) ||
    browserPreviewString(payload?.idempotency_key) ||
    requestId;
  const revision =
    typeof payload?.revision === "number" && Number.isFinite(payload.revision) ? payload.revision : 0;
  const timeoutMs =
    typeof payload?.timeoutMs === "number" && Number.isFinite(payload.timeoutMs)
      ? payload.timeoutMs
      : typeof payload?.timeout_ms === "number" && Number.isFinite(payload.timeout_ms)
        ? payload.timeout_ms
        : 30_000;
  return {
    request_id: requestId,
    idempotency_key: idempotencyKey,
    revision,
    timeout_ms: timeoutMs,
    cancel: payload?.cancel === true,
  };
}

function emitBrowserPreviewTrainingPersistenceAck(
  persistence: { requestId: string; commandId: string } | undefined,
  ok: boolean,
  data?: unknown,
  message?: string,
): void {
  if (!persistence) {
    return;
  }
  emitBrowserPreviewHostMessage({
    type: "training/persistenceAck",
    payload: {
      ...persistence,
      ok,
      ...(data !== undefined ? { data } : {}),
      ...(!ok && message ? { message } : {}),
    },
  });
}

function browserPreviewResourceTrainingHandoffRequest(
  action: WebviewAction,
): { requestId: string; resourceId: string } | undefined {
  if (
    action.type !== "command/execute" ||
    action.payload.commandId !== trainerCommands.trainingGenerateCard
  ) {
    return undefined;
  }
  const payload = browserPreviewActionPayload(action);
  const requestId = browserPreviewString(payload?.[RESOURCE_TRAINING_HANDOFF_REQUEST_ID_KEY]);
  const resourceId = browserPreviewString(payload?.resourceId ?? payload?.resource_id);
  return requestId && resourceId && /^[a-z0-9-]{1,96}$/i.test(requestId)
    ? { requestId, resourceId }
    : undefined;
}

function resourceTrainingHandoffReason(
  detail: string,
  outcome: ResourceTrainingHandoffResult["outcome"],
): ResourceTrainingHandoffResult["reason"] | undefined {
  const normalized = detail.toLowerCase();
  if (normalized.includes("resource") && /(not found|missing|deleted)/.test(normalized)) {
    return "resource_missing";
  }
  if (/(provider|api key|connection|sidecar|service unavailable|\b503\b)/.test(normalized)) {
    return "connection";
  }
  if (/(index|fresh|trust|source|generated_card_blocked|\b409\b|conflict)/.test(normalized)) {
    return "resource_needs_refresh";
  }
  return outcome === "ready" || outcome === "not-current" ? undefined : "unavailable";
}

function emitBrowserPreviewResourceTrainingHandoff(result: ResourceTrainingHandoffResult): void {
  emitBrowserPreviewHostMessage({
    type: "training/resourceHandoff",
    payload: result,
  });
}

function browserPreviewResourceTrainingHandoffFailure(
  request: { requestId: string; resourceId: string },
  detail: string,
): ResourceTrainingHandoffResult {
  const failureReason = resourceTrainingHandoffReason(detail, "failed");
  const outcome =
    failureReason === "resource_missing" || failureReason === "resource_needs_refresh"
      ? "blocked"
      : "failed";
  return {
    ...request,
    outcome,
    ...(failureReason ? { reason: failureReason } : {}),
  };
}

async function readLiveTrainingResponseRecord(
  response: Response,
): Promise<Record<string, unknown> | undefined> {
  const payload = await response
    .clone()
    .json()
    .catch(() => undefined);
  return payload && typeof payload === "object" && !Array.isArray(payload)
    ? (payload as Record<string, unknown>)
    : undefined;
}

function browserPreviewResourceTrainingHandoffSuccess(
  request: { requestId: string; resourceId: string },
  response: Record<string, unknown> | undefined,
  snapshot: BootstrapData,
): ResourceTrainingHandoffResult {
  const card =
    response?.card && typeof response.card === "object" && !Array.isArray(response.card)
      ? (response.card as Record<string, unknown>)
      : undefined;
  const generatedCardId = browserPreviewString(card?.card_id ?? card?.cardId);
  const selectedCardId =
    browserPreviewString(snapshot.workspaceTrainingState?.selectedCardId) ||
    browserPreviewString(snapshot.workspaceTrainingState?.activeTrainingCardRouting?.selectedCardId);
  const success = response?.success === true;
  const outcome =
    success && generatedCardId && selectedCardId === generatedCardId
      ? "ready"
      : success && selectedCardId
        ? "not-current"
        : "blocked";
  const reason = resourceTrainingHandoffReason(browserPreviewString(response?.reason), outcome);
  return {
    ...request,
    outcome,
    ...(reason ? { reason } : {}),
    ...(generatedCardId ? { generatedCardId } : {}),
    ...(selectedCardId ? { selectedCardId } : {}),
  };
}

function browserPreviewString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function browserPreviewStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean)
    : [];
}

function mapLiveGlobalPlan(value: unknown): BootstrapData["globalPlan"] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const stages = Array.isArray(record.stages)
    ? record.stages
        .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
        .map((item, index) => ({
          id: browserPreviewString(item.id) || `global-stage-${index + 1}`,
          title: browserPreviewString(item.title) || `Stage ${index + 1}`,
          objective: browserPreviewString(item.goal ?? item.objective),
          status:
            item.status === "active"
              ? ("active" as const)
              : item.status === "completed" || item.status === "done"
                ? ("done" as const)
                : ("queued" as const),
        }))
    : [];
  return {
    id: browserPreviewString(record.id),
    title: browserPreviewString(record.title),
    summary: browserPreviewString(record.summary),
    goals: browserPreviewStringArray(record.goals),
    stages,
    frozen: browserPreviewBoolean(record.frozen),
    currentProjectPlanId: browserPreviewString(record.current_project_plan_id ?? record.currentProjectPlanId) || undefined,
    currentStageId: browserPreviewString(record.current_stage_id ?? record.currentStageId) || undefined,
    currentStep: browserPreviewString(record.current_step ?? record.currentStep) || undefined,
    whyNow: browserPreviewString(record.why_now ?? record.whyNow) || undefined,
    verifyMethod: browserPreviewStringArray(record.verify_method ?? record.verifyMethod),
  };
}

function mapLiveGlobalPlanLink(value: unknown): BootstrapData["projectPlanLink"] {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  return {
    globalPlanId: browserPreviewString(record.global_plan_id ?? record.globalPlanId),
    workspaceId: browserPreviewString(record.workspace_id ?? record.workspaceId),
    projectPlanId: browserPreviewString(record.project_plan_id ?? record.projectPlanId),
    linkedAt: browserPreviewString(record.linked_at ?? record.linkedAt),
    updatedAt: browserPreviewString(record.updated_at ?? record.updatedAt),
  };
}

function browserPreviewBoolean(value: unknown): boolean {
  return typeof value === "boolean" ? value : Boolean(value);
}

function handleBrowserPreviewStreamCancel(action: WebviewAction): boolean {
  if (action.type !== "session/cancelStreamMessage") {
    return false;
  }
  cancelBrowserPreviewStream(action.payload?.messageId);
  return true;
}

function previewTrainingSuccessMessage(
  commandId: string,
  language: ComposerLanguage,
  detail?: string,
): string {
  const suffix = detail ? ` ${detail}` : "";
  switch (commandId) {
    case trainerCommands.trainingGenerateCard:
      return previewText(
        language,
        `A real training card is ready.${suffix}`,
        `真实训练卡已准备好。${suffix}`,
      );
    case trainerCommands.trainingCardStatusTransition:
      return previewText(
        language,
        `The real training card status updated.${suffix}`,
        `真实训练卡状态已更新。${suffix}`,
      );
    case trainerCommands.trainingFlashcardAnswer:
      return previewText(
        language,
        `The real flashcard answer was recorded.${suffix}`,
        `真实闪卡答案已记录。${suffix}`,
      );
    case trainerCommands.trainingTheoryDrillAnswer:
      return previewText(
        language,
        `The real theory-drill answer was recorded.${suffix}`,
        `真实理论练习答案已记录。${suffix}`,
      );
    case trainerCommands.trainingPracticeReturn:
      return previewText(
        language,
        `The real practice return was recorded.${suffix}`,
        `真实练习返回已记录。${suffix}`,
      );
    case trainerCommands.trainingReflect:
      return previewText(
        language,
        `The real reflection was recorded.${suffix}`,
        `真实反思已记录。${suffix}`,
      );
    case trainerCommands.trainingReturn:
      return previewText(
        language,
        `The real training return completed.${suffix}`,
        `真实训练回流已完成。${suffix}`,
      );
    case trainerCommands.trainingReviewQueueAction:
      return previewText(
        language,
        `The real review queue action was applied.${suffix}`,
        `真实复习队列动作已应用。${suffix}`,
      );
    case trainerCommands.trainingReviewArtifactAction:
      return previewText(
        language,
        `The real review artifact action was applied.${suffix}`,
        `真实复习产物动作已应用。${suffix}`,
      );
    case trainerCommands.trainingScenarioLabAction:
      return previewText(
        language,
        `The real scenario-lab action was applied.${suffix}`,
        `真实场景实验动作已应用。${suffix}`,
      );
    case trainerCommands.trainingDependencySkillMapAction:
      return previewText(
        language,
        `The real dependency-skill-map action was applied.${suffix}`,
        `真实依赖技能图动作已应用。${suffix}`,
      );
    default:
      return previewText(
        language,
        `The training step was applied in the real sidecar.${suffix}`,
        `训练步骤已在真实侧车中应用。${suffix}`,
      );
  }
}

async function refreshLiveBrowserPreviewBootstrap(): Promise<BootstrapData> {
  const { sessionId, message } = await fetchBrowserPreviewBootstrap(livePreviewSessionId, true);
  livePreviewSessionId = sessionId;
  if (message.type === "bootstrap") {
    livePreviewBootstrap = message.payload;
  }
  emitBrowserPreviewHostMessage(message);
  return livePreviewBootstrap ?? currentBrowserPreviewBootstrap();
}

async function readLiveTrainingResponseDetail(response: Response): Promise<string | undefined> {
  const raw = await response.text().catch(() => "");
  const compactRaw = raw.replace(/\s+/g, " ").trim();
  if (!compactRaw) {
    return undefined;
  }

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return undefined;
    }
    const record = parsed as Record<string, unknown>;
    for (const key of ["detail", "message", "summary", "reason"]) {
      const value = record[key];
      if (typeof value === "string" && value.trim()) {
        return value.replace(/\s+/g, " ").trim().slice(0, 240);
      }
    }
    return undefined;
  } catch {
    return compactRaw.length <= 240 ? compactRaw : undefined;
  }
}

function livePreviewTrainingSuccessMessage(
  commandId: string,
  language: ComposerLanguage,
  detail?: string,
): string {
  const suffix = detail ? ` ${detail}` : "";
  const isChinese = language === "zh-CN";
  switch (commandId) {
    case trainerCommands.trainingGenerateCard:
      return isChinese
        ? `真实训练卡已准备好。${suffix}`
        : `A real training card is ready.${suffix}`;
    case trainerCommands.trainingCardStatusTransition:
      return isChinese
        ? `真实训练卡状态已更新。${suffix}`
        : `The real training card status updated.${suffix}`;
    case trainerCommands.trainingFlashcardAnswer:
      return isChinese
        ? `真实闪卡答案已记录。${suffix}`
        : `The real flashcard answer was recorded.${suffix}`;
    case trainerCommands.trainingTheoryDrillAnswer:
      return isChinese
        ? `真实理论练习答案已记录。${suffix}`
        : `The real theory-drill answer was recorded.${suffix}`;
    case trainerCommands.trainingPracticeReturn:
      return isChinese
        ? `真实练习返回已记录。${suffix}`
        : `The real practice return was recorded.${suffix}`;
    case trainerCommands.trainingReflect:
      return isChinese ? `真实反思已记录。${suffix}` : `The real reflection was recorded.${suffix}`;
    case trainerCommands.trainingReturn:
      return isChinese
        ? `真实训练回流已完成。${suffix}`
        : `The real training return completed.${suffix}`;
    case trainerCommands.trainingReviewQueueAction:
      return isChinese
        ? `真实复习队列动作已应用。${suffix}`
        : `The real review queue action was applied.${suffix}`;
    case trainerCommands.trainingReviewArtifactAction:
      return isChinese
        ? `真实复习产物动作已应用。${suffix}`
        : `The real review artifact action was applied.${suffix}`;
    case trainerCommands.trainingScenarioLabAction:
      return isChinese
        ? `真实场景实验动作已应用。${suffix}`
        : `The real scenario-lab action was applied.${suffix}`;
    case trainerCommands.trainingDependencySkillMapAction:
      return isChinese
        ? `真实依赖技能图动作已应用。${suffix}`
        : `The real dependency-skill-map action was applied.${suffix}`;
    default:
      return isChinese
        ? `训练步骤已在真实侧车中应用。${suffix}`
        : `The training step was applied in the real sidecar.${suffix}`;
  }
}

async function runBrowserPreviewLiveTrainingAction(
  action: WebviewAction,
  language: ComposerLanguage,
): Promise<boolean> {
  if (action.type !== "command/execute") {
    return false;
  }

  const commandId = action.payload.commandId;
  if (!LIVE_TRAINING_COMMAND_IDS.has(commandId)) {
    return false;
  }

  const payload = browserPreviewActionPayload(action);
  const persistence = browserPreviewTrainingPersistenceRequest(action);
  const resourceTrainingHandoff = browserPreviewResourceTrainingHandoffRequest(action);
  const workspaceId = resolveBrowserPreviewWorkspaceId();
  const requestHeaders = { "content-type": "application/json" };
  const sidecarBaseUrl = await ensureBrowserPreviewSidecar();
  let activeTrainingStream:
    | { messageId: string; controller: AbortController; cancellationNotified: boolean }
    | undefined;
  const emitTrainingStreamCancelled = () => {
    if (!activeTrainingStream || activeTrainingStream.cancellationNotified) {
      return;
    }
    activeTrainingStream.cancellationNotified = true;
    emitBrowserPreviewHostMessage({
      type: "stream/cancelled",
      payload: { messageId: activeTrainingStream.messageId },
    });
  };
  const requestFor = (path: string, body: Record<string, unknown>, signal?: AbortSignal) =>
    fetch(`${sidecarBaseUrl}${path}`, {
      method: "POST",
      headers: requestHeaders,
      body: JSON.stringify(body),
      signal,
    });

  try {
    let response: Response;
    switch (commandId) {
      case trainerCommands.trainingGenerateCard:
        {
          const requestedSubmode = browserPreviewString(payload?.submode);
          const requestedCardType = browserPreviewString(payload?.cardType);
          const resolvedCardType = requestedSubmode === "flash" ? "flash" : requestedCardType || "practice";
          activeTrainingStream = {
            messageId: `training-preview-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            controller: new AbortController(),
            cancellationNotified: false,
          };
          registerBrowserPreviewStream(activeTrainingStream.messageId, activeTrainingStream.controller, {
            sidecarBaseUrl,
            streamId: activeTrainingStream.messageId,
          });
          const providerOverride = browserPreviewProviderRequestOverride();
          response = await requestFor(
            "/training/generate-card/stream",
            {
              workspace_id: workspaceId,
              source: browserPreviewString(payload?.source) || "conversation_gap",
              card_type: resolvedCardType,
              submode: requestedSubmode,
              focus_area: browserPreviewString(payload?.focusArea),
              target_skill: browserPreviewString(payload?.targetSkill),
              context_hint: browserPreviewString(payload?.contextHint),
              plan_stage_id: browserPreviewString(payload?.planStageId),
              resource_id: browserPreviewString(payload?.resourceId),
              why_now: browserPreviewString(payload?.whyNow),
              response_language: language,
              stream_id: activeTrainingStream.messageId,
              ...(providerOverride
                ? {
                    provider: providerOverride.provider,
                    api_key: providerOverride.apiKey,
                  }
                : {}),
            },
            activeTrainingStream.controller.signal,
          );
          if (response.ok) {
            response = await consumeBrowserPreviewTrainingCardStream(
              response,
              activeTrainingStream.messageId,
              activeTrainingStream.controller.signal,
            );
          } else {
            // HTTP 502 (and peers): pending → failure before generic reject, never silent success.
            emitBrowserPreviewHostMessage({
              type: "stream/start",
              payload: { messageId: activeTrainingStream.messageId },
            });
            emitBrowserPreviewHostMessage({
              type: "stream/error",
              payload: {
                messageId: activeTrainingStream.messageId,
                error: previewText(
                  language,
                  "The training card could not be prepared. Check the connection and try again.",
                  "训练卡没有生成成功。检查连接后再试一次。",
                ),
                category: "provider_error",
                retryable: true,
                reliabilityPhase: "acked",
                reliabilityOutcome: "failure",
              },
            });
          }
          if (activeTrainingStream.controller.signal.aborted) {
            emitTrainingStreamCancelled();
            if (resourceTrainingHandoff) {
              emitBrowserPreviewResourceTrainingHandoff(
                browserPreviewResourceTrainingHandoffFailure(resourceTrainingHandoff, "Training card stream cancelled."),
              );
            }
            return true;
          }
          break;
        }
      case trainerCommands.trainingCardStatusTransition:
        response = await requestFor("/training/card-status", {
          workspace_id: workspaceId,
          card_id: browserPreviewString(payload?.cardId),
          new_status: browserPreviewString(payload?.newStatus) || "active",
          reason: browserPreviewString(payload?.reason),
          ...browserPreviewReliabilityFields(payload),
        });
        break;
      case trainerCommands.trainingFlashcardAnswer:
        response = await requestFor("/training/flashcard/answer", {
          workspace_id: workspaceId,
          card_id: browserPreviewString(payload?.cardId),
          learner_answer: browserPreviewString(payload?.learnerAnswer) || browserPreviewString(payload?.answer),
          selected_option_index:
            typeof payload?.selectedOptionIndex === "number" ? payload.selectedOptionIndex : undefined,
        });
        break;
      case trainerCommands.trainingTheoryDrillAnswer:
        response = await requestFor("/training/theory-drill/answer", {
          workspace_id: workspaceId,
          theory_drill_id: browserPreviewString(payload?.theoryDrillId),
          question_id: browserPreviewString(payload?.questionId),
          learner_answer: browserPreviewString(payload?.learnerAnswer) || browserPreviewString(payload?.answer),
          selected_option_index:
            typeof payload?.selectedOptionIndex === "number" ? payload.selectedOptionIndex : undefined,
        });
        break;
      case trainerCommands.trainingPracticeReturn:
        response = await requestFor("/training/practice-return", {
          workspace_id: workspaceId,
          card_id: browserPreviewString(payload?.cardId),
          passed: browserPreviewBoolean(payload?.passed),
          summary: browserPreviewString(payload?.summary),
          next_step: browserPreviewString(payload?.nextStep),
          focus_area: browserPreviewString(payload?.focusArea),
          failed_checks: Array.isArray(payload?.failedChecks) ? payload.failedChecks : [],
          missing_requirements: Array.isArray(payload?.missingRequirements) ? payload.missingRequirements : [],
          evidence_source: browserPreviewString(payload?.evidenceSource) || "learner_return",
          ...browserPreviewReliabilityFields(payload),
        });
        break;
      case trainerCommands.trainingReflect:
        response = await requestFor("/training/reflect", {
          workspace_id: workspaceId,
          card_id: browserPreviewString(payload?.cardId),
          handoff_id: browserPreviewString(payload?.handoffId),
          reflection: browserPreviewString(payload?.reflection),
          ...browserPreviewReliabilityFields(payload),
        });
        break;
      case trainerCommands.trainingReturn:
        response = await requestFor("/training/return", {
          workspace_id: workspaceId,
          card_id: browserPreviewString(payload?.cardId),
          handoff_id: browserPreviewString(payload?.handoffId),
          ...browserPreviewReliabilityFields(payload),
        });
        break;
      case trainerCommands.evidenceEnqueue:
        response = await requestFor(
          "/evidence/enqueue",
          payload?.waitingComposer === true
            ? {
                session_id: livePreviewSessionId,
                workspace_id: workspaceId,
                waiting_composer: true,
                summary: browserPreviewString(payload?.summary),
              }
            : {
                session_id: livePreviewSessionId,
                workspace_id: workspaceId,
                source: browserPreviewString(payload?.source) || "card_result",
                summary: browserPreviewString(payload?.summary),
                concepts: browserPreviewStringArray(payload?.concepts),
                outcome: browserPreviewString(payload?.outcome) || "pass",
                source_card_id: browserPreviewString(payload?.sourceCardId),
                target_plan_stage_id: browserPreviewString(payload?.targetPlanStageId),
                confidence:
                  typeof payload?.confidence === "number" && Number.isFinite(payload.confidence)
                    ? payload.confidence
                    : 0.75,
              },
        );
        break;
      case trainerCommands.trainingReviewQueueAction:
        response = await requestFor("/training/review-queue/action", {
          workspace_id: workspaceId,
          concept: browserPreviewString(payload?.concept),
          action: browserPreviewString(payload?.action),
          scope: browserPreviewString(payload?.scope) || "single",
          focus_area: browserPreviewString(payload?.focusArea),
          task_hint: browserPreviewString(payload?.taskHint),
          note: browserPreviewString(payload?.note),
          batch_limit:
            typeof payload?.batchLimit === "number" && Number.isFinite(payload.batchLimit)
              ? payload.batchLimit
              : 4,
        });
        break;
      case trainerCommands.trainingReviewArtifactAction:
        response = await requestFor("/training/review-artifact/action", {
          workspace_id: workspaceId,
          review_artifact_id: browserPreviewString(payload?.reviewArtifactId),
          action: browserPreviewString(payload?.action),
          note: browserPreviewString(payload?.note),
          edit_patch:
            payload?.editPatch && typeof payload.editPatch === "object" && !Array.isArray(payload.editPatch)
              ? payload.editPatch
              : {},
        });
        break;
      case trainerCommands.trainingScenarioLabAction:
        response = await requestFor("/training/scenario-lab/action", {
          workspace_id: workspaceId,
          scenario_lab_id: browserPreviewString(payload?.scenarioLabId),
          action: browserPreviewString(payload?.action),
          note: browserPreviewString(payload?.note),
          review_outcome: browserPreviewString(payload?.reviewOutcome),
        });
        break;
      case trainerCommands.trainingDependencySkillMapAction:
        response = await requestFor("/training/dependency-skill-map/action", {
          workspace_id: workspaceId,
          dependency_key: browserPreviewString(payload?.dependencyKey),
          action: browserPreviewString(payload?.action),
          note: browserPreviewString(payload?.note),
          focus_item_key: browserPreviewString(payload?.focusItemKey),
          related_api: browserPreviewString(payload?.relatedApi),
          scenario: browserPreviewString(payload?.scenario),
        });
        break;
      default:
        return false;
    }

    if (!response.ok) {
      if (activeTrainingStream?.controller.signal.aborted) {
        emitTrainingStreamCancelled();
        if (resourceTrainingHandoff) {
          emitBrowserPreviewResourceTrainingHandoff(
            browserPreviewResourceTrainingHandoffFailure(resourceTrainingHandoff, "Training card stream cancelled."),
          );
        }
        return true;
      }
      const detail = await response.text().catch(() => "");
      if (resourceTrainingHandoff) {
        emitBrowserPreviewResourceTrainingHandoff(
          browserPreviewResourceTrainingHandoffFailure(resourceTrainingHandoff, detail),
        );
        return true;
      }
      const enqueueFailure =
        commandId === trainerCommands.evidenceEnqueue
          ? waitingComposerEnqueueFailureText(
              detail || `Sidecar request failed (${response.status}).`,
              language,
            )
          : undefined;
      emitBrowserPreviewTrainingPersistenceAck(persistence, false, undefined, enqueueFailure);
      emitBrowserPreviewHostMessage({
        type: "operation/status",
        payload: {
          tone: "error",
          message:
            enqueueFailure ??
            previewText(
              language,
              `The real training sidecar rejected this action. ${detail}`.trim(),
              `真实训练侧车拒绝了这个动作。${detail}`.trim(),
            ),
        },
      });
      return true;
    }

    const resourceResponseRecord = resourceTrainingHandoff
      ? await readLiveTrainingResponseRecord(response)
      : undefined;
    const refreshedSnapshot = await refreshLiveBrowserPreviewBootstrap();
    if (resourceTrainingHandoff) {
      emitBrowserPreviewResourceTrainingHandoff(
        browserPreviewResourceTrainingHandoffSuccess(
          resourceTrainingHandoff,
          resourceResponseRecord,
          refreshedSnapshot,
        ),
      );
      return true;
    }
    const detail = await readLiveTrainingResponseDetail(response);
    const responseRecord = await readLiveTrainingResponseRecord(response);
    emitBrowserPreviewTrainingPersistenceAck(persistence, true, responseRecord);
    emitBrowserPreviewHostMessage({
      type: "operation/status",
      payload: {
        tone: "success",
        message: livePreviewTrainingSuccessMessage(
          commandId,
          language,
          detail ? detail.replace(/\s+/g, " ") : undefined,
        ),
      },
    });
    return true;
  } catch (error) {
    if (activeTrainingStream?.controller.signal.aborted) {
      emitTrainingStreamCancelled();
      if (resourceTrainingHandoff) {
        emitBrowserPreviewResourceTrainingHandoff(
          browserPreviewResourceTrainingHandoffFailure(resourceTrainingHandoff, "Training card stream cancelled."),
        );
      }
      return true;
    }
    const detail = error instanceof Error ? error.message : String(error);
    if (resourceTrainingHandoff) {
      emitBrowserPreviewResourceTrainingHandoff(
        browserPreviewResourceTrainingHandoffFailure(resourceTrainingHandoff, detail),
      );
      return true;
    }
    const enqueueFailure =
      commandId === trainerCommands.evidenceEnqueue
        ? waitingComposerEnqueueFailureText(detail || "Sidecar is not running.", language)
        : undefined;
    emitBrowserPreviewTrainingPersistenceAck(persistence, false, undefined, enqueueFailure);
    emitBrowserPreviewHostMessage({
      type: "operation/status",
      payload: {
        tone: "error",
        message:
          enqueueFailure ??
          previewText(
            language,
            `Unable to reach the real training sidecar. ${detail}`.trim(),
            `无法连接真实训练侧车。${detail}`.trim(),
          ),
      },
    });
    return true;
  } finally {
    if (activeTrainingStream) {
      releaseBrowserPreviewStream(activeTrainingStream.messageId);
    }
  }
}

function emitLivePreviewOperationStatus(
  action: WebviewAction,
  tone: "success" | "error" | "info",
  message: string,
): void {
  const payload = browserPreviewActionPayload(action);
  const isResourceIndex =
    action.type === "command/execute" && action.payload.commandId === trainerCommands.indexResources;
  const isResourceSearch =
    action.type === "command/execute" && action.payload.commandId === trainerCommands.searchResources;
  const operationId =
    browserPreviewString(payload?.__trainerResourceOperationId) ||
    (isResourceSearch ? browserPreviewString(payload?.requestId) : "");
  const operationKind = isResourceIndex ? "index" : isResourceSearch ? "search" : undefined;
  const operationMessage =
    operationKind && operationId
      ? `[[trainer-resource-operation:${operationKind}:${operationId}]] ${message}`
      : message;
  emitBrowserPreviewHostMessage({
    type: "operation/status",
    payload: { tone, message: operationMessage },
  });
}

function liveAgentHandoffPrompt(
  action: WebviewAction,
  language: ComposerLanguage,
  bootstrap: BrowserPreviewBootstrap,
): string | undefined {
  const isOpenResourceAction =
    action.type === "resource/open" ||
    (action.type === "command/execute" && action.payload.commandId === trainerCommands.openResource);
  if (isOpenResourceAction) {
    const resourceId =
      action.type === "resource/open"
        ? browserPreviewString(action.payload.resourceId)
        : browserPreviewString(browserPreviewActionPayload(action)?.resourceId);
    const resource = resourceId
      ? bootstrap.resources?.find((item) => item.id === resourceId)
      : undefined;
    const label = resource?.title || resourceId || (language === "zh-CN" ? "当前资料" : "the selected resource");
    return previewText(
      language,
      `请在资料视图中处理“${label}”：使用当前工作区和资料工具定位它，说明当前可见内容与下一步；不要声称已经在浏览器中打开本地文件。`,
      `Handle "${label}" from the Resources view using the current workspace and resource tools. Explain what can be located and the next step; do not claim that a local file was opened in the browser.`,
    );
  }

  if (action.type !== "command/execute") {
    return undefined;
  }
  if (!LIVE_AGENT_HANDOFF_COMMAND_IDS.has(action.payload.commandId)) {
    return undefined;
  }

  const commandLabel =
    action.payload.commandId === trainerCommands.createGlobalPlan
      ? language === "zh-CN"
        ? "创建全局计划"
        : "create a global plan"
      : action.payload.commandId === trainerCommands.linkCurrentProjectPlan
        ? language === "zh-CN"
          ? "关联当前项目计划"
          : "link the current project plan"
        : language === "zh-CN"
          ? "处理当前资料"
          : "handle the current resource";
  return previewText(
    language,
    `我在${action.payload.commandId === trainerCommands.openResource ? "资料" : "计划"}视图请求${commandLabel}。请使用真实 Agent 工具检查当前状态，说明可执行的下一步；不要伪造已经完成的写入。`,
    `I requested "${commandLabel}" from the ${action.payload.commandId === trainerCommands.openResource ? "Resources" : "Plan"} view. Use the real Agent tools to inspect the current state and explain the next executable step; do not claim a write completed unless it did.`,
  );
}

async function runBrowserPreviewLiveAgentHandoff(
  action: WebviewAction,
  language: ComposerLanguage,
): Promise<boolean> {
  const bootstrap = currentBrowserPreviewBootstrap();
  const prompt = liveAgentHandoffPrompt(action, language, bootstrap);
  if (!prompt) {
    return false;
  }

  await refreshLiveBrowserPreviewBootstrap();
  const sessionId = livePreviewSessionId;
  if (!sessionId) {
    throw new Error("Live preview session is not available.");
  }
  const resourceId =
    action.type === "resource/open"
      ? browserPreviewString(action.payload.resourceId)
      : action.type === "command/execute" && action.payload.commandId === trainerCommands.openResource
        ? browserPreviewString(browserPreviewActionPayload(action)?.resourceId)
        : undefined;
  let completed = false;
  let failed = false;
  const request: SessionMessageRequest = {
    text: prompt,
    intent: action.type === "resource/open" ? "coach" : "plan",
    activeView: action.type === "resource/open" ? "resources" : "plan",
    resourceIds: resourceId ? [resourceId] : undefined,
    responseLanguage: language,
    contextDetail: "full",
    includeCurrentFile: true,
    includeSelection: true,
    includeDiagnostics: true,
    includeRelatedFiles: true,
    useAgentLoop: true,
  };

  await streamBrowserPreviewMessage(request, sessionId, {
    onStart: (message) => emitBrowserPreviewHostMessage(message),
    onChunk: (message) => emitBrowserPreviewHostMessage(message),
    onComplete: (message, nextSessionId) => {
      livePreviewSessionId = nextSessionId;
      if (message.type === "stream/complete") {
        completed = true;
      }
      emitBrowserPreviewHostMessage(message);
    },
    onError: (message) => {
      failed = true;
      emitBrowserPreviewHostMessage(message);
    },
    onCancelled: (message) => {
      failed = true;
      emitBrowserPreviewHostMessage(message);
    },
  });

  if (failed) {
    emitLivePreviewOperationStatus(
      action,
      "error",
      previewText(
        language,
        "Agent 没有完成这次转交；请根据流中的错误恢复或重试。",
        "The Agent handoff did not complete; use the stream error to recover or retry.",
      ),
    );
  } else if (completed) {
    emitLivePreviewOperationStatus(
      action,
      "success",
      previewText(
        language,
        "Agent 已接管这个视图动作，并把结果带回当前会话。",
        "The Agent handled this view action and returned the result to the current session.",
      ),
    );
  }
  return true;
}

async function runBrowserPreviewLiveAction(
  action: WebviewAction,
  language: ComposerLanguage,
): Promise<void> {
  if (await runBrowserPreviewLiveTrainingAction(action, language)) {
    return;
  }

  const isPlanFreeze = action.type === "plan/freeze";
  const commandId = action.type === "command/execute" ? action.payload.commandId : undefined;
  const payload = browserPreviewActionPayload(action);
  const isPlanGenerate = commandId === trainerCommands.generatePlan;
  const isPlanUpdate = commandId === trainerCommands.updatePlan;
  const isGlobalPlanCreate = commandId === trainerCommands.createGlobalPlan;
  const isGlobalPlanLink = commandId === trainerCommands.linkCurrentProjectPlan;
  const isNextTask = commandId === trainerCommands.nextTask;
  const isTaskSpecify = commandId === trainerCommands.taskSpecify;
  const isResourceIndex =
    commandId === trainerCommands.indexResources;
  const isResourceSearch = commandId === trainerCommands.searchResources;
  const isResourceTrashRefresh = commandId === trainerCommands.refreshResourceTrash;
  const isResourceOpen = action.type === "resource/open";
  const isSandboxPreview = commandId === trainerCommands.previewSandbox;
  const isUnsupportedCommand = action.type === "command/execute";
  if (
    !isPlanFreeze &&
    !isPlanGenerate &&
    !isPlanUpdate &&
    !isGlobalPlanCreate &&
    !isGlobalPlanLink &&
    !isNextTask &&
    !isTaskSpecify &&
    !isResourceIndex &&
    !isResourceSearch &&
    !isResourceTrashRefresh &&
    !isResourceOpen &&
    !isSandboxPreview &&
    !isUnsupportedCommand
  ) {
    return;
  }

  try {
    const sidecarBaseUrl = await ensureBrowserPreviewSidecar();
    const workspaceId = resolveBrowserPreviewWorkspaceId();
    const requestHeaders = { "content-type": "application/json" };

    if (isPlanGenerate) {
      const snapshot = await refreshLiveBrowserPreviewBootstrap();
      const requestedGoals = browserPreviewStringArray(payload?.objectives ?? payload?.goals);
      const goals =
        requestedGoals.length > 0
          ? requestedGoals
          : [
              browserPreviewString(snapshot.profile?.goals?.[0]) ||
                browserPreviewString(snapshot.coachFocus?.currentFocus) ||
                "current learning goal",
            ];
      const constraints = browserPreviewStringArray(payload?.constraints);
      const resourceIds = [
        ...new Set([
          ...snapshot.resources.map((resource) => resource.id).filter(Boolean),
          ...browserPreviewStringArray(payload?.resourceIds),
        ]),
      ];
      const constraintContext =
        constraints.length > 0
          ? ` Respect these constraints: ${constraints.join("; ")}.`
          : " No additional constraints were supplied; surface missing constraints instead of inventing them.";
      const request: SessionMessageRequest = {
        text:
          `Generate a formal learning plan for ${goals.join("; ")}. ` +
          "Use every attached library material as evidence, ask for clarification when the goal or available time is ambiguous, and explain stages, why now, verification, and the next step." +
          constraintContext,
        goals,
        intent: "plan",
        activeView: "plan",
        formalPlanMutation: true,
        resourceIds,
        responseLanguage: language,
        contextDetail: "full",
        includeCurrentFile: true,
        includeSelection: true,
        includeDiagnostics: true,
        includeRelatedFiles: true,
        useAgentLoop: true,
      };
      let completed = false;
      let failed = false;
      let cancelled = false;
      await streamBrowserPreviewMessage(request, livePreviewSessionId ?? "", {
        onStart: (message) => emitBrowserPreviewHostMessage(message),
        onChunk: (message) => emitBrowserPreviewHostMessage(message),
        onComplete: (message, nextSessionId) => {
          livePreviewSessionId = nextSessionId;
          if (message.type === "stream/complete") {
            completed = true;
          }
          emitBrowserPreviewHostMessage(message);
        },
        onError: (message) => {
          failed = true;
          emitBrowserPreviewHostMessage(message);
        },
        onCancelled: (message) => {
          cancelled = true;
          emitBrowserPreviewHostMessage(message);
        },
      });

      if (failed) {
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            "正式计划生成未完成；请根据流中的错误恢复或重试。",
            "The formal plan generation did not complete; use the stream error to recover or retry.",
          ),
        );
        return;
      }
      if (cancelled) {
        emitLivePreviewOperationStatus(
          action,
          "info",
          previewText(
            language,
            "正式计划生成已取消，未把新计划当作已完成。",
            "The formal plan generation was cancelled; no new plan is reported as complete.",
          ),
        );
        return;
      }
      if (completed) {
        await refreshLiveBrowserPreviewBootstrap();
        emitLivePreviewOperationStatus(
          action,
          "success",
          previewText(language, "正式计划已通过真实流式请求完成。", "The formal plan completed through the real stream."),
        );
      }
      return;
    }

    if (isGlobalPlanCreate || isGlobalPlanLink) {
      const snapshot = await refreshLiveBrowserPreviewBootstrap();
      const response = await fetch(
        `${sidecarBaseUrl}${isGlobalPlanCreate ? "/plan/global" : "/plan/global/projects"}`,
        {
          method: isGlobalPlanCreate ? "POST" : "PUT",
          headers: requestHeaders,
          body: JSON.stringify(
            isGlobalPlanCreate
              ? {
                  session_id: livePreviewSessionId,
                  workspace_id: workspaceId,
                  title: browserPreviewString(payload?.title) || undefined,
                  summary: browserPreviewString(payload?.summary) || undefined,
                  goals:
                    browserPreviewStringArray(payload?.goals).length > 0
                      ? browserPreviewStringArray(payload?.goals)
                      : browserPreviewStringArray(snapshot.profile?.goals),
                  frozen: browserPreviewBoolean(payload?.frozen),
                }
              : {
                  session_id: livePreviewSessionId,
                  workspace_id: workspaceId,
                  project_plan_id:
                    browserPreviewString(payload?.projectPlanId) ||
                    browserPreviewString(snapshot.plan?.id) ||
                    undefined,
                },
          ),
        },
      );
      if (!response.ok) {
        const detail = (await response.text().catch(() => "")).replace(/\s+/g, " ").trim();
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            `全局计划操作被真实 Sidecar 拒绝。${detail ? ` ${detail}` : ""}`,
            `The global-plan operation was rejected by the real Sidecar.${detail ? ` ${detail}` : ""}`,
          ),
        );
        return;
      }
      const record = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      const patch: BrowserPreviewPatch = {
        globalPlan: mapLiveGlobalPlan(record.global_plan),
        projectPlanLink: mapLiveGlobalPlanLink(record.project_plan_link),
      };
      const nextBootstrap = mergeBrowserPreviewPatch(currentBrowserPreviewBootstrap(), patch);
      window.__TRAINER_BOOTSTRAP__ = nextBootstrap;
      emitBrowserPreviewHostMessage({ type: "state/patch", payload: patch });
      emitLivePreviewOperationStatus(
        action,
        "success",
        isGlobalPlanCreate
          ? previewText(language, "全局计划已由真实 Sidecar 创建。", "The global plan was created by the real Sidecar.")
          : previewText(language, "当前项目计划已由真实 Sidecar 关联。", "The current project plan was linked by the real Sidecar."),
      );
      return;
    }

    if (isPlanFreeze || isPlanUpdate) {
      const snapshot = await refreshLiveBrowserPreviewBootstrap();
      const planId = browserPreviewString(snapshot.plan?.id);
      if (!planId) {
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            "当前没有可冻结的正式计划。先在 Plan 中生成计划。",
            "There is no formal plan to freeze yet. Generate a plan in Plan first.",
          ),
        );
        return;
      }
      const frozen =
        isPlanFreeze
          ? action.payload.frozen
          : payload && "frozen" in payload
            ? browserPreviewBoolean(payload.frozen)
            : true;
      const response = await fetch(`${sidecarBaseUrl}/plan/update`, {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify({
          plan_id: planId,
          workspace_id: workspaceId,
          frozen,
          freeze: frozen,
          instructions: browserPreviewString(payload?.instructions),
          title: browserPreviewString(payload?.title) || undefined,
          weekly_cadence: browserPreviewString(payload?.weeklyCadence),
          response_language: language,
        }),
      });
      if (!response.ok) {
        const detail = (await response.text().catch(() => "")).replace(/\s+/g, " ").trim();
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            `计划更新被 Sidecar 拒绝。${detail ? ` ${detail}` : ""}`,
            `The Sidecar rejected the plan update.${detail ? ` ${detail}` : ""}`,
          ),
        );
        return;
      }
      await refreshLiveBrowserPreviewBootstrap();
      emitLivePreviewOperationStatus(
        action,
        "success",
        frozen
          ? previewText(language, "计划已冻结。", "The plan is now frozen.")
          : previewText(language, "计划已恢复为可调整状态。", "The plan is live again."),
      );
      return;
    }

    if (isNextTask || isTaskSpecify) {
      const snapshot = await refreshLiveBrowserPreviewBootstrap();
      const requestPath = isNextTask ? "/task/next" : "/task/specify";
      const naturalLanguageGoal =
        browserPreviewString(payload?.naturalLanguageGoal) ||
        browserPreviewString(payload?.goal) ||
        browserPreviewString(payload?.text) ||
        browserPreviewString(snapshot.profile?.goals?.[0]) ||
        browserPreviewString(snapshot.coachFocus?.currentFocus) ||
        "current learning goal";
      const response = await fetch(`${sidecarBaseUrl}${requestPath}`, {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify(
          isNextTask
            ? {
                session_id: livePreviewSessionId,
                workspace_id: workspaceId,
                focus_area:
                  browserPreviewString(payload?.focusArea) ||
                  browserPreviewString(snapshot.planRuntimeStatus?.currentMainThread?.focusArea),
                response_language: language,
              }
            : {
                session_id: livePreviewSessionId,
                workspace_id: workspaceId,
                natural_language_goal: naturalLanguageGoal,
              },
        ),
      });
      if (!response.ok) {
        const detail = (await response.text().catch(() => "")).replace(/\s+/g, " ").trim();
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            `任务请求被真实 Sidecar 拒绝。${detail ? ` ${detail}` : ""}`,
            `The task request was rejected by the real Sidecar.${detail ? ` ${detail}` : ""}`,
          ),
        );
        return;
      }
      await refreshLiveBrowserPreviewBootstrap();
      emitLivePreviewOperationStatus(
        action,
        "success",
        isNextTask
          ? previewText(language, "下一项任务已由真实 Sidecar 准备好。", "The next task was prepared by the real Sidecar.")
          : previewText(language, "任务规格已由真实 Sidecar 整理好。", "The task specification was prepared by the real Sidecar."),
      );
      return;
    }

    if (isResourceIndex) {
      const snapshot = await refreshLiveBrowserPreviewBootstrap();
      const resources = Array.isArray(snapshot.resources) ? snapshot.resources : [];
      const candidates = resources.filter(
        (resource) => resource.status !== "ready" || resource.freshness === "stale",
      );
      let indexedCount = 0;
      let failedCount = 0;
      for (const resource of candidates) {
        const response = await fetch(`${sidecarBaseUrl}/resource/index`, {
          method: "POST",
          headers: requestHeaders,
          body: JSON.stringify({
            session_id: livePreviewSessionId,
            workspace_id: workspaceId,
            resource_id: resource.id,
            enable_network: resource.kind === "url",
          }),
        });
        if (response.ok) {
          const indexed = await response.json().catch(() => undefined);
          if (isCompletedLivePreviewResourceIndex(indexed)) {
            indexedCount += 1;
          } else {
            failedCount += 1;
          }
        } else {
          failedCount += 1;
        }
      }
      await refreshLiveBrowserPreviewBootstrap();
      const message =
        failedCount > 0
          ? previewText(
              language,
              `已索引 ${indexedCount} 项，${failedCount} 项失败，请检查资源状态。`,
              `Indexed ${indexedCount}; ${failedCount} resource${failedCount === 1 ? "" : "s"} failed. Check their status.`,
            )
          : previewText(
              language,
              candidates.length === 0 ? "没有需要刷新的资源。" : `已完成 ${indexedCount} 项资源索引。`,
              candidates.length === 0 ? "No resources need indexing." : `Indexed ${indexedCount} resource${indexedCount === 1 ? "" : "s"}.`,
            );
      emitLivePreviewOperationStatus(action, failedCount > 0 ? "error" : "success", message);
      return;
    }

    if (isResourceSearch) {
      const query = browserPreviewString(payload?.query);
      if (!query) {
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(language, "请输入要搜索的资料内容。", "Enter a resource search query first."),
        );
        return;
      }
      const requestId =
        browserPreviewString(payload?.requestId) ||
        browserPreviewString(payload?.__trainerResourceOperationId) ||
        `resource-search-${Date.now().toString(36)}`;
      const result = await searchBrowserPreviewResources(
        {
          query,
          requestId,
          mode: "lexical",
        },
        livePreviewSessionId,
      );
      livePreviewSessionId = result.sessionId;
      emitBrowserPreviewHostMessage(result.message);
      emitLivePreviewOperationStatus(
        action,
        "success",
        previewText(language, `已完成资料搜索：“${query}”。`, `Resource search completed for "${query}".`),
      );
      return;
    }

    if (isResourceTrashRefresh) {
      const response = await fetch(
        `${sidecarBaseUrl}/resource/trash?session_id=${encodeURIComponent(
          livePreviewSessionId ?? "",
        )}&workspace_id=${encodeURIComponent(workspaceId)}`,
        { headers: requestHeaders },
      );
      if (!response.ok) {
        const detail = (await response.text().catch(() => "")).replace(/\s+/g, " ").trim();
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            `资料 Trash 刷新被真实 Sidecar 拒绝。${detail ? ` ${detail}` : ""}`,
            `Refreshing resource Trash was rejected by the real Sidecar.${detail ? ` ${detail}` : ""}`,
          ),
        );
        return;
      }
      const record = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      const rawItems = Array.isArray(record.items) ? record.items : [];
      const deletedResources = rawItems
        .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
        .map((item) => ({
          resourceId: browserPreviewString(item.resource_id ?? item.resourceId),
          title: browserPreviewString(item.title) || "Deleted resource",
          deletedAt: browserPreviewString(item.deleted_at ?? item.deletedAt) || undefined,
          collectionPath:
            browserPreviewString(item.collection_path ?? item.collectionPath) || undefined,
          recoverable: item.recoverable !== false,
        }))
        .filter((item) => item.resourceId);
      const patch: BrowserPreviewPatch = { deletedResources };
      const bootstrap = currentBrowserPreviewBootstrap();
      window.__TRAINER_BOOTSTRAP__ = mergeBrowserPreviewPatch(bootstrap, patch);
      emitBrowserPreviewHostMessage({ type: "state/patch", payload: patch });
      emitLivePreviewOperationStatus(
        action,
        "success",
        previewText(
          language,
          `已从真实 Sidecar 刷新 ${deletedResources.length} 条可恢复资料。`,
          `Loaded ${deletedResources.length} recoverable resource${deletedResources.length === 1 ? "" : "s"} from the real Sidecar.`,
        ),
      );
      return;
    }

    if (isSandboxPreview) {
      // Mirror previewResourceCommand: resolve the resource's governed sandbox copy,
      // then ask the real sidecar for the preview and patch it into the bootstrap so
      // the resources detail pane re-renders with the content.
      // NB: resolve against the live bootstrap (not window.__TRAINER_BOOTSTRAP__,
      // which is unset in live mode and would fall back to mock data).
      const resourceId = browserPreviewString(payload?.resourceId);
      const explicitPath = browserPreviewString(payload?.path);
      const resolvePreviewPath = (snapshot: BootstrapData | BrowserPreviewBootstrap): string => {
        const resource = resourceId
          ? snapshot.resources?.find((item) => item.id === resourceId)
          : undefined;
        return (
          resource?.sandboxPath?.trim() ||
          (explicitPath && !/^https?:\/\//i.test(explicitPath) ? explicitPath : "")
        );
      };
      let snapshot = livePreviewBootstrap ?? currentBrowserPreviewBootstrap();
      let previewPath = resolvePreviewPath(snapshot);
      if (!previewPath && resourceId) {
        // The cached live bootstrap is stale: uploads/searches patch the Zustand
        // store directly and never reach this module-level snapshot. Refresh from
        // the real sidecar once so newly uploaded resources resolve here.
        try {
          snapshot = await refreshLiveBrowserPreviewBootstrap();
          previewPath = resolvePreviewPath(snapshot);
        } catch {
          // Fall through to the governed-copy error below.
        }
      }
      if (!previewPath) {
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            "这份资料没有可预览的沙箱副本。",
            "This resource has no governed sandbox copy to preview.",
          ),
        );
        return;
      }
      const response = await fetch(`${sidecarBaseUrl}/sandbox/preview`, {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify({ workspace_id: workspaceId, path: previewPath }),
      });
      if (!response.ok) {
        const detail = (await response.text().catch(() => "")).replace(/\s+/g, " ").trim();
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            `资料预览被真实 Sidecar 拒绝。${detail ? ` ${detail}` : ""}`,
            `The resource preview was rejected by the real Sidecar.${detail ? ` ${detail}` : ""}`,
          ),
        );
        return;
      }
      const record = await response.json().catch(() => undefined);
      const sandboxPreview = mapSandboxPreview(record);
      if (!sandboxPreview) {
        emitLivePreviewOperationStatus(
          action,
          "error",
          previewText(
            language,
            "真实 Sidecar 没有返回可渲染的预览内容。",
            "The real Sidecar did not return renderable preview content.",
          ),
        );
        return;
      }
      const bootstrap = livePreviewBootstrap ?? currentBrowserPreviewBootstrap();
      const patch: BrowserPreviewPatch = {
        memory: { ...bootstrap.memory, sandboxPreview } as BootstrapData["memory"],
      };
      livePreviewBootstrap = mergeBrowserPreviewPatch(bootstrap, patch);
      window.__TRAINER_BOOTSTRAP__ = livePreviewBootstrap;
      emitBrowserPreviewHostMessage({ type: "state/patch", payload: patch });
      emitLivePreviewOperationStatus(
        action,
        "success",
        previewText(language, "资料预览已从真实 Sidecar 载入。", "Resource preview loaded from the real Sidecar."),
      );
      return;
    }

    if (isResourceOpen) {
      if (await runBrowserPreviewLiveAgentHandoff(action, language)) {
        return;
      }
      emitLivePreviewOperationStatus(
        action,
        "error",
        previewText(
          language,
          "浏览器 live 预览不能打开本地资源路径；请使用资源对话或下载入口。",
          "Live browser preview cannot open a local resource path. Use the resource conversation or download action.",
        ),
      );
      return;
    }

    if (isUnsupportedCommand && (await runBrowserPreviewLiveAgentHandoff(action, language))) {
      return;
    }

    emitLivePreviewOperationStatus(
      action,
      "error",
      previewText(
        language,
        "这个操作在 live 预览中没有真实 Sidecar 路由，因此没有执行。",
        "This action has no real Sidecar route in live preview, so it was not executed.",
      ),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    emitLivePreviewOperationStatus(
      action,
      "error",
      previewText(
        language,
        `无法连接真实 Sidecar。${detail ? ` ${detail}` : ""}`,
        `Unable to reach the real Sidecar.${detail ? ` ${detail}` : ""}`,
      ),
    );
  }
}

async function consumeBrowserPreviewTrainingCardStream(
  response: Response,
  messageId: string,
  signal: AbortSignal,
): Promise<Response> {
  emitBrowserPreviewHostMessage({
    type: "stream/start",
    payload: { messageId },
  });
  const failedResponse = (detail: string): Response =>
    new Response(JSON.stringify({ detail }), {
      status: 502,
      headers: { "content-type": "application/json" },
    });
  const cancelledResponse = (): Response =>
    new Response(JSON.stringify({ cancelled: true }), {
      status: 499,
      headers: { "content-type": "application/json" },
    });
  let terminal: "complete" | "error" | "cancelled" | undefined;
  const emitStreamError = (detail: string): Response => {
    if (!terminal) {
      terminal = "error";
      emitBrowserPreviewHostMessage({
        type: "stream/error",
        payload: {
          messageId,
          error: detail,
          category: "provider_error",
          retryable: true,
        },
      });
    }
    return failedResponse(detail);
  };
  const emitStreamCancelled = (): Response => {
    if (!terminal) {
      terminal = "cancelled";
      emitBrowserPreviewHostMessage({
        type: "stream/cancelled",
        payload: { messageId },
      });
    }
    return cancelledResponse();
  };
  if (signal.aborted) {
    return emitStreamCancelled();
  }
  if (!response.body) {
    return emitStreamError("Training card stream returned an empty body.");
  }

  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    reader = response.body.getReader();
    attachBrowserPreviewStreamReader(messageId, reader);
    const decoder = new TextDecoder();
    let buffer = "";
    let completion: Record<string, unknown> | undefined;
    let tokenCount = 0;

    const consumeBlock = (block: string) => {
      if (terminal) {
        return;
      }
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (dataLines.length === 0) {
        return;
      }
      let payload: Record<string, unknown> | undefined;
      try {
        const parsed: unknown = JSON.parse(dataLines.join("\n"));
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          payload = parsed as Record<string, unknown>;
        }
      } catch {
        throw new Error("Malformed training card stream event.");
      }
      if (!payload) {
        throw new Error("Malformed training card stream event.");
      }
      if (eventName === "complete") {
        completion = payload;
        return;
      }
      if (eventName === "error") {
        throw new Error(typeof payload.error === "string" ? payload.error : "Training card stream failed.");
      }
      const chunk = typeof payload.chunk === "string" ? payload.chunk : "";
      if (!chunk) {
        return;
      }
      tokenCount += 1;
      emitBrowserPreviewHostMessage({
        type: "stream/chunk",
        payload: { messageId, chunk },
      });
    };

    while (true) {
      if (signal.aborted) {
        return emitStreamCancelled();
      }
      const { value, done } = await reader.read();
      if (signal.aborted) {
        return emitStreamCancelled();
      }
      if (done) {
        buffer += decoder.decode();
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex >= 0) {
        consumeBlock(buffer.slice(0, separatorIndex));
        buffer = buffer.slice(separatorIndex + 2);
        if (completion) {
          break;
        }
        separatorIndex = buffer.indexOf("\n\n");
      }
      if (completion) {
        break;
      }
    }
    if (!completion && buffer.trim()) {
      consumeBlock(buffer);
    }
    if (!completion) {
      return emitStreamError("Training card stream ended before completion.");
    }
    terminal = "complete";
    emitBrowserPreviewHostMessage({
      type: "stream/complete",
      payload: { messageId, tokens: tokenCount },
    });
    const responsePayload = completion.response;
    return new Response(JSON.stringify(responsePayload ?? {}), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  } catch (error) {
    if (signal.aborted) {
      return emitStreamCancelled();
    }
    const detail = error instanceof Error ? error.message : String(error);
    return emitStreamError(detail || "Training card stream failed.");
  } finally {
    if (reader && terminal) {
      await reader.cancel().catch(() => undefined);
    }
    reader?.releaseLock();
  }
}

function isCompletedLivePreviewResourceIndex(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  const parseStatus = record.parse_status ?? record.parseStatus;
  const indexStatus = record.index_status ?? record.indexStatus;
  return parseStatus === "parsed" && indexStatus === "indexed";
}

function runBrowserPreviewWebviewAction(
  action: WebviewAction,
  language: ComposerLanguage,
): void {
  if (action.type === "request/bootstrap") {
    emitBrowserPreviewHostMessage({
      type: "bootstrap",
      payload: currentBrowserPreviewBootstrap(),
    });
    return;
  }

  const bootstrap = currentBrowserPreviewBootstrap();
  const result = runBrowserPreviewAction(action, bootstrap, language);
  if (result.patch) {
    const nextBootstrap = mergeBrowserPreviewPatch(bootstrap, result.patch);
    window.__TRAINER_BOOTSTRAP__ = nextBootstrap;
    emitBrowserPreviewHostMessage({
      type: "state/patch",
      payload: result.patch as Partial<BootstrapData>,
    });
  }
  if (action.type === "command/execute" && LIVE_TRAINING_PERSISTENCE_COMMAND_IDS.has(action.payload.commandId)) {
    const persistence = browserPreviewTrainingPersistenceRequest(action);
    emitBrowserPreviewTrainingPersistenceAck(persistence, result.tone !== "error", result.patch);
  }
  emitBrowserPreviewHostMessage({
    type: "operation/status",
    payload: {
      tone: result.tone,
      message: result.message,
    },
  });
}

function resolvePreviewScenarioCase(
  value: string | null,
): BrowserPreviewState["scenario"] | undefined {
  switch (value?.trim()) {
    case "deep-audit-provider-empty":
      return "blocked";
    default:
      return undefined;
  }
}

const guidedTrainingPreviewScenarioAliasMap: Record<string, GuidedTrainingPreviewScenario> = {
  "training-remote": "training-remote",
  remote_workspace: "training-remote",
  "training-debug": "training-debug",
  debug_loop: "training-debug",
  "training-function": "training-function",
  function_guidance: "training-function",
  "training-resource": "training-resource",
  resource_knowledge: "training-resource",
  "training-dependency": "training-dependency",
  dependency_mastery: "training-dependency",
};

type PreviewTextLocaleOverrides<T extends string | string[]> = Partial<
  Record<Exclude<ComposerLanguage, "zh-CN" | "en-US">, T>
>;

function previewText<T extends string | string[]>(
  language: ComposerLanguage,
  zh: T,
  en: T,
  localeOverrides: PreviewTextLocaleOverrides<T> = {},
): T {
  if (language === "zh-CN") {
    return zh;
  }
  if (language === "en-US") {
    return en;
  }
  return localeOverrides[language] ?? en;
}

type PreviewProviderLabel = "browser" | "local" | "preview";

type BrowserPreviewFirstLookCopy = {
  repoSummary: string;
  resourceBrief: string;
  whyThisGuess: string;
  riskZone: string;
  trainingOpportunity: string;
  unknown: string;
  recommendedNextStep: string;
};

const browserPreviewFirstLookCopy: Record<ComposerLanguage, BrowserPreviewFirstLookCopy> = {
  "zh-CN": {
    repoSummary: "这是一个包含 VS Code 扩展和 FastAPI 服务的项目。",
    resourceBrief: "这是当前项目的概览，先从最相关的资料开始。",
    whyThisGuess: "这里有依赖清单、源码目录和明确的 API 入口。",
    riskZone: "工程包含多个部分，先从一个小目标开始会更稳。",
    trainingOpportunity: "先围绕一个 API 入口完成一次可验证的小练习。",
    unknown: "还不确定现有代码已经稳定到什么程度。",
    recommendedNextStep: "先选一个 API 入口，完成一个小而可验证的练习。",
  },
  "en-US": {
    repoSummary: "This project contains a VS Code extension and a FastAPI service.",
    resourceBrief: "This is a project overview. Start with the most relevant material.",
    whyThisGuess: "It has dependency manifests, source directories, and clear API entry points.",
    riskZone: "The project spans several parts, so starting with one small goal is safer.",
    trainingOpportunity: "Start with one small, verifiable exercise around an API entry point.",
    unknown: "It is not clear yet how much of the current code is already stable.",
    recommendedNextStep: "Choose one API entry point and finish a small exercise you can verify.",
  },
  "es-ES": {
    repoSummary: "Este proyecto contiene una extensión de VS Code y un servicio FastAPI.",
    resourceBrief: "Este es un resumen del proyecto. Empieza por el material más relevante.",
    whyThisGuess: "Hay manifiestos de dependencias, directorios de código y puntos de entrada de API claros.",
    riskZone: "El proyecto abarca varias partes; es más seguro empezar con un objetivo pequeño.",
    trainingOpportunity: "Empieza con un ejercicio pequeño y verificable sobre un punto de entrada de la API.",
    unknown: "Aún no está claro qué partes del código actual ya son estables.",
    recommendedNextStep: "Elige un punto de entrada de la API y termina un ejercicio pequeño que puedas comprobar.",
  },
  "fr-FR": {
    repoSummary: "Ce projet contient une extension VS Code et un service FastAPI.",
    resourceBrief: "Voici un aperçu du projet. Commencez par le contenu le plus utile.",
    whyThisGuess: "Il contient des manifestes de dépendances, des dossiers source et des points d'entrée API clairs.",
    riskZone: "Le projet couvre plusieurs parties ; il vaut mieux commencer par un petit objectif.",
    trainingOpportunity: "Commencez par un petit exercice vérifiable autour d'un point d'entrée API.",
    unknown: "On ne sait pas encore quelles parties du code actuel sont déjà stables.",
    recommendedNextStep: "Choisissez un point d'entrée API et terminez un petit exercice vérifiable.",
  },
  "de-DE": {
    repoSummary: "Dieses Projekt enthält eine VS-Code-Erweiterung und einen FastAPI-Dienst.",
    resourceBrief: "Dies ist ein Projektüberblick. Beginnen Sie mit dem wichtigsten Material.",
    whyThisGuess: "Es gibt Abhängigkeitsdateien, Quellordner und klare API-Einstiegspunkte.",
    riskZone: "Das Projekt umfasst mehrere Bereiche. Ein kleines Ziel ist ein sicherer Einstieg.",
    trainingOpportunity: "Beginnen Sie mit einer kleinen, überprüfbaren Übung zu einem API-Einstiegspunkt.",
    unknown: "Es ist noch nicht klar, welche Teile des aktuellen Codes bereits stabil sind.",
    recommendedNextStep: "Wählen Sie einen API-Einstiegspunkt und schließen Sie eine kleine überprüfbare Übung ab.",
  },
  "ja-JP": {
    repoSummary: "このプロジェクトには VS Code 拡張機能と FastAPI サービスがあります。",
    resourceBrief: "これはプロジェクトの概要です。まずは関連性の高い資料から始めましょう。",
    whyThisGuess: "依存関係の定義、ソースディレクトリ、明確な API の入口があります。",
    riskZone: "複数の部分からなるプロジェクトなので、まず小さな目標から始めると安全です。",
    trainingOpportunity: "API の入口を一つ選び、小さく検証できる練習から始めましょう。",
    unknown: "現在のコードのどこまでが安定しているかは、まだ分かっていません。",
    recommendedNextStep: "API の入口を一つ選び、確認できる小さな練習を完了しましょう。",
  },
  "ko-KR": {
    repoSummary: "이 프로젝트에는 VS Code 확장과 FastAPI 서비스가 있습니다.",
    resourceBrief: "현재 프로젝트의 개요입니다. 가장 관련 있는 자료부터 시작하세요.",
    whyThisGuess: "의존성 설정, 소스 디렉터리, 분명한 API 진입점이 있습니다.",
    riskZone: "프로젝트가 여러 부분으로 나뉘어 있으므로 작은 목표부터 시작하는 편이 안전합니다.",
    trainingOpportunity: "API 진입점 하나를 골라 작고 검증 가능한 연습부터 시작하세요.",
    unknown: "현재 코드 중 어느 부분이 이미 안정적인지는 아직 알 수 없습니다.",
    recommendedNextStep: "API 진입점 하나를 고르고 확인할 수 있는 작은 연습을 마치세요.",
  },
  "pt-BR": {
    repoSummary: "Este projeto contém uma extensão do VS Code e um serviço FastAPI.",
    resourceBrief: "Este é um resumo do projeto. Comece pelo material mais relevante.",
    whyThisGuess: "Há manifestos de dependências, diretórios de código e pontos de entrada de API claros.",
    riskZone: "O projeto tem várias partes; é mais seguro começar com um objetivo pequeno.",
    trainingOpportunity: "Comece com um exercício pequeno e verificável em torno de um ponto de entrada da API.",
    unknown: "Ainda não está claro quanto do código atual já está estável.",
    recommendedNextStep: "Escolha um ponto de entrada da API e conclua um pequeno exercício que possa verificar.",
  },
};

function localizeBrowserPreviewFirstLook(
  bootstrap: typeof mockBootstrapData,
  language: ComposerLanguage,
): void {
  const workspaceUnderstanding = bootstrap.memory.workspaceUnderstanding;
  const firstLookSummary = workspaceUnderstanding?.firstLookSummary;
  if (!workspaceUnderstanding || !firstLookSummary) {
    return;
  }

  const copy = browserPreviewFirstLookCopy[language] ?? browserPreviewFirstLookCopy["en-US"];
  bootstrap.memory = {
    ...bootstrap.memory,
    workspaceUnderstanding: {
      ...workspaceUnderstanding,
      repoSummary: copy.repoSummary,
      resourceBrief: copy.resourceBrief,
      firstLookSummary: {
        ...firstLookSummary,
        whyThisGuess: copy.whyThisGuess,
        riskZones: [copy.riskZone],
        trainingOpportunities: [copy.trainingOpportunity],
        unknowns: [copy.unknown],
        recommendedNextStep: copy.recommendedNextStep,
      },
    },
  };
}

const previewProviderLabels: Record<ComposerLanguage, Record<PreviewProviderLabel, string>> = {
  "zh-CN": {
    browser: "浏览器预览",
    local: "本地兼容服务",
    preview: "预览兼容服务",
  },
  "en-US": {
    browser: "Browser preview",
    local: "Local compatible service",
    preview: "Preview compatible service",
  },
  "es-ES": {
    browser: "Vista previa del navegador",
    local: "Servicio local compatible",
    preview: "Servicio compatible de vista previa",
  },
  "fr-FR": {
    browser: "Aperçu dans le navigateur",
    local: "Service local compatible",
    preview: "Service d'aperçu compatible",
  },
  "de-DE": {
    browser: "Browser-Vorschau",
    local: "Lokaler kompatibler Dienst",
    preview: "Kompatibler Vorschau-Dienst",
  },
  "ja-JP": {
    browser: "ブラウザー プレビュー",
    local: "ローカル互換サービス",
    preview: "プレビュー互換サービス",
  },
  "ko-KR": {
    browser: "브라우저 미리 보기",
    local: "로컬 호환 서비스",
    preview: "미리 보기 호환 서비스",
  },
  "pt-BR": {
    browser: "Visualização do navegador",
    local: "Serviço local compatível",
    preview: "Serviço de visualização compatível",
  },
};

function previewProviderLabel(language: ComposerLanguage, label: PreviewProviderLabel): string {
  return previewProviderLabels[language][label];
}

type WorkspaceAdmissionPreviewCopy = {
  projectName: string;
  repoSummary: string;
  resourceBrief: string;
  whyThisGuess: string;
  riskZones: readonly [string, string];
  trainingOpportunities: readonly [string, string];
  unknowns: readonly [string];
  nextSteps: Record<"root-missing" | "project-found" | "managed" | "browse" | "ignored", string>;
  onboardingSummary: string;
  managedSummary: string;
};

const workspaceAdmissionPreviewCopy: Record<ComposerLanguage, WorkspaceAdmissionPreviewCopy> = {
  "zh-CN": {
    projectName: "Trainer 插件",
    repoSummary: "这是一个由 VS Code 扩展和 FastAPI sidecar 组成的项目。",
    resourceBrief: "代码、计划和训练记录都会回到受管的 Trainer 工作区。",
    whyThisGuess: "检测到 VS Code 扩展、React Webview 和 FastAPI sidecar。",
    riskZones: ["模型能力状态", "会话恢复"],
    trainingOpportunities: ["将项目加入 Trainer", "训练结果回流"],
    unknowns: ["应先管理哪条项目主线？"],
    nextSteps: {
      "root-missing": "先选择一个文件夹，用来保存 Trainer 的学习记录。",
      "project-found": "确认是否将这个项目加入 Trainer。",
      managed: "说说你想在这个项目中完成什么。",
      browse: "这个项目目前只浏览；加入 Trainer 后才能开始学习会话。",
      ignored: "这个项目暂未管理；准备好后可加入 Trainer。",
    },
    onboardingSummary: "先确认项目如何处理，再进入对话主线。",
    managedSummary: "项目已经加入 Trainer，可以从你的目标开始。",
  },
  "en-US": {
    projectName: "Trainer extension",
    repoSummary: "This project combines a VS Code extension with a FastAPI sidecar.",
    resourceBrief: "Code, plans, and training records return to a managed Trainer workspace.",
    whyThisGuess: "Detected a VS Code extension, React webview, and FastAPI sidecar.",
    riskZones: ["Model capability status", "Session recovery"],
    trainingOpportunities: ["Add the project to Trainer", "Return training evidence"],
    unknowns: ["Which project thread should be managed first?"],
    nextSteps: {
      "root-missing": "Choose a folder to keep Trainer learning records.",
      "project-found": "Decide whether to add this project to Trainer.",
      managed: "Tell me what you want to achieve in this project.",
      browse: "This project is browse-only. Add it to Trainer to start a learning session.",
      ignored: "This project is not managed yet. Add it to Trainer when you are ready.",
    },
    onboardingSummary: "Confirm how this project should be handled before entering the coaching thread.",
    managedSummary: "This project is in Trainer, so we can start with your goal.",
  },
  "es-ES": {
    projectName: "Extensión de Trainer",
    repoSummary: "Este proyecto combina una extensión de VS Code con un servicio auxiliar de FastAPI.",
    resourceBrief: "El código, los planes y los registros de entrenamiento vuelven al espacio de trabajo administrado de Trainer.",
    whyThisGuess: "Se detectaron una extensión de VS Code, un webview de React y un servicio auxiliar de FastAPI.",
    riskZones: ["Estado de las capacidades del modelo", "Recuperación de la sesión"],
    trainingOpportunities: ["Incorporar el proyecto a Trainer", "Devolver la evidencia de entrenamiento"],
    unknowns: ["¿Qué hilo del proyecto debería gestionarse primero?"],
    nextSteps: {
      "root-missing": "Elige una carpeta para guardar los registros de aprendizaje de Trainer.",
      "project-found": "Decide si quieres añadir este proyecto a Trainer.",
      managed: "Cuéntame qué quieres lograr en este proyecto.",
      browse: "Este proyecto es solo de lectura. Añádelo a Trainer para iniciar una sesión de aprendizaje.",
      ignored: "Este proyecto aún no se gestiona. Añádelo a Trainer cuando estés listo.",
    },
    onboardingSummary: "Confirma cómo se debe tratar este proyecto antes de entrar en la conversación de coaching.",
    managedSummary: "Este proyecto ya está en Trainer; podemos empezar por tu objetivo.",
  },
  "fr-FR": {
    projectName: "Extension Trainer",
    repoSummary: "Ce projet associe une extension VS Code à un service auxiliaire FastAPI.",
    resourceBrief: "Le code, les plans et les notes d'entraînement reviennent dans un espace de travail Trainer géré.",
    whyThisGuess: "Une extension VS Code, un webview React et un service auxiliaire FastAPI ont été détectés.",
    riskZones: ["État des capacités du modèle", "Récupération de session"],
    trainingOpportunities: ["Ajouter le projet à Trainer", "Renvoyer la preuve d'entraînement"],
    unknowns: ["Quel fil du projet faut-il gérer en premier ?"],
    nextSteps: {
      "root-missing": "Choisissez un dossier pour conserver les notes d'apprentissage de Trainer.",
      "project-found": "Décidez si vous souhaitez ajouter ce projet à Trainer.",
      managed: "Dites-moi ce que vous voulez accomplir dans ce projet.",
      browse: "Ce projet est en consultation seule. Ajoutez-le à Trainer pour lancer une session d'apprentissage.",
      ignored: "Ce projet n'est pas encore géré. Ajoutez-le à Trainer lorsque vous serez prêt.",
    },
    onboardingSummary: "Confirmez comment traiter ce projet avant d'entrer dans la conversation de coaching.",
    managedSummary: "Ce projet est déjà dans Trainer ; nous pouvons commencer par votre objectif.",
  },
  "de-DE": {
    projectName: "Trainer-Erweiterung",
    repoSummary: "Dieses Projekt verbindet eine VS-Code-Erweiterung mit einem FastAPI-Hilfsdienst.",
    resourceBrief: "Code, Pläne und Trainingsnotizen kehren in einen verwalteten Trainer-Arbeitsbereich zurück.",
    whyThisGuess: "Eine VS-Code-Erweiterung, ein React-Webview und ein FastAPI-Hilfsdienst wurden erkannt.",
    riskZones: ["Status der Modellfähigkeiten", "Sitzungswiederherstellung"],
    trainingOpportunities: ["Projekt zu Trainer hinzufügen", "Trainingsevidenz zurückgeben"],
    unknowns: ["Welcher Projektstrang soll zuerst verwaltet werden?"],
    nextSteps: {
      "root-missing": "Wähle einen Ordner für die Lernnotizen von Trainer.",
      "project-found": "Entscheide, ob dieses Projekt zu Trainer hinzugefügt werden soll.",
      managed: "Sag mir, was du in diesem Projekt erreichen möchtest.",
      browse: "Dieses Projekt ist nur zum Ansehen geöffnet. Füge es zu Trainer hinzu, um eine Lernsitzung zu starten.",
      ignored: "Dieses Projekt wird noch nicht verwaltet. Füge es zu Trainer hinzu, wenn du bereit bist.",
    },
    onboardingSummary: "Kläre zuerst, wie dieses Projekt behandelt wird, bevor der Coaching-Thread beginnt.",
    managedSummary: "Dieses Projekt ist in Trainer, daher können wir mit deinem Ziel beginnen.",
  },
  "ja-JP": {
    projectName: "Trainer 拡張機能",
    repoSummary: "このプロジェクトは、VS Code 拡張機能と FastAPI の補助サービスで構成されています。",
    resourceBrief: "コード、計画、トレーニング記録は管理された Trainer ワークスペースに戻ります。",
    whyThisGuess: "VS Code 拡張機能、React Webview、FastAPI の補助サービスを検出しました。",
    riskZones: ["モデル機能の状態", "セッションの復元"],
    trainingOpportunities: ["プロジェクトを Trainer に追加", "トレーニングの証拠を戻す"],
    unknowns: ["最初に管理するプロジェクトの主線はどれですか？"],
    nextSteps: {
      "root-missing": "Trainer の学習記録を保存するフォルダーを選択してください。",
      "project-found": "このプロジェクトを Trainer に追加するか決めてください。",
      managed: "このプロジェクトで達成したいことを教えてください。",
      browse: "このプロジェクトは閲覧専用です。学習セッションを始めるには Trainer に追加してください。",
      ignored: "このプロジェクトはまだ管理されていません。準備ができたら Trainer に追加してください。",
    },
    onboardingSummary: "対話の主線に入る前に、このプロジェクトの扱いを確認してください。",
    managedSummary: "このプロジェクトは Trainer に追加済みです。目標から始められます。",
  },
  "ko-KR": {
    projectName: "Trainer 확장 기능",
    repoSummary: "이 프로젝트는 VS Code 확장 기능과 FastAPI 보조 서비스로 구성되어 있습니다.",
    resourceBrief: "코드, 계획, 훈련 기록은 관리되는 Trainer 작업 공간으로 돌아갑니다.",
    whyThisGuess: "VS Code 확장 기능, React 웹뷰, FastAPI 보조 서비스를 감지했습니다.",
    riskZones: ["모델 기능 상태", "세션 복구"],
    trainingOpportunities: ["프로젝트를 Trainer에 추가", "훈련 근거 되돌리기"],
    unknowns: ["어떤 프로젝트 흐름을 먼저 관리할까요?"],
    nextSteps: {
      "root-missing": "Trainer 학습 기록을 저장할 폴더를 선택하세요.",
      "project-found": "이 프로젝트를 Trainer에 추가할지 결정하세요.",
      managed: "이 프로젝트에서 이루고 싶은 것을 알려 주세요.",
      browse: "이 프로젝트는 보기 전용입니다. 학습 세션을 시작하려면 Trainer에 추가하세요.",
      ignored: "이 프로젝트는 아직 관리되지 않습니다. 준비되면 Trainer에 추가하세요.",
    },
    onboardingSummary: "코칭 대화로 들어가기 전에 이 프로젝트를 어떻게 다룰지 확인하세요.",
    managedSummary: "이 프로젝트는 Trainer에 추가되어 있으므로 목표부터 시작할 수 있습니다.",
  },
  "pt-BR": {
    projectName: "Extensão do Trainer",
    repoSummary: "Este projeto combina uma extensão do VS Code com um serviço auxiliar FastAPI.",
    resourceBrief: "Código, planos e registros de treinamento voltam para um espaço de trabalho gerenciado do Trainer.",
    whyThisGuess: "Foram detectados uma extensão do VS Code, um webview React e um serviço auxiliar FastAPI.",
    riskZones: ["Estado das capacidades do modelo", "Recuperação de sessão"],
    trainingOpportunities: ["Adicionar o projeto ao Trainer", "Devolver evidências de treinamento"],
    unknowns: ["Qual fluxo do projeto deve ser gerenciado primeiro?"],
    nextSteps: {
      "root-missing": "Escolha uma pasta para guardar os registros de aprendizagem do Trainer.",
      "project-found": "Decida se quer adicionar este projeto ao Trainer.",
      managed: "Conte o que você quer alcançar neste projeto.",
      browse: "Este projeto é somente para visualização. Adicione-o ao Trainer para iniciar uma sessão de aprendizagem.",
      ignored: "Este projeto ainda não é gerenciado. Adicione-o ao Trainer quando estiver pronto.",
    },
    onboardingSummary: "Confirme como este projeto deve ser tratado antes de entrar na conversa de coaching.",
    managedSummary: "Este projeto está no Trainer; podemos começar pelo seu objetivo.",
  },
};

type LocalizedConnectedPlanPreviewCopy = {
  title: string;
  summary: string;
  stageTitles: readonly [string, string, string];
  stageObjectives: readonly [string, string, string];
  focus: string;
  nextStep: string;
  whyNow: string;
  verify: string;
  nextAfter: string;
  blockedReason: string;
  acceptanceCriteria: readonly [string, string, string];
};

const localizedConnectedPlanPreviewCopy: Partial<
  Record<ComposerLanguage, LocalizedConnectedPlanPreviewCopy>
> = {
  "es-ES": {
    title: "Hilo principal de aprendizaje",
    summary:
      "Usa el proyecto actual para convertir ideas en cambios pequeños, explicar las decisiones y comprobarlas de nuevo.",
    stageTitles: ["Leer el sistema actual", "Afinar el hilo principal", "Verificar y registrar lo aprendido"],
    stageObjectives: [
      "Localiza los archivos que definen la experiencia antes de tocar varias capas a la vez.",
      "Aclara la entrada, los mensajes y el área de redacción del coach.",
      "Comprueba que el recorrido es más claro y guarda la explicación para futuras revisiones.",
    ],
    focus: "Afinar el hilo del coach",
    nextStep:
      "Ajusta la entrada, los mensajes y el plan; luego confirma que la línea principal se entiende de inmediato.",
    whyNow: "Este paso decide si la persona entiende la línea principal al abrir Trainer.",
    verify:
      "Comprueba que la primera vista del plan muestra con claridad la línea principal, la tarea actual y el siguiente paso.",
    nextAfter: "Cuando este fragmento esté claro, sigue simplificando el flujo de mensajes y el área de redacción.",
    blockedReason: "La verificación del archivo actual aún no respalda este paso del plan.",
    acceptanceCriteria: [
      "La persona sabe qué cambiar primero y por qué.",
      "El coach da una siguiente acción clara sin sobrecarga.",
      "La revisión conecta la implementación con el principio de ingeniería.",
    ],
  },
  "fr-FR": {
    title: "Fil principal d'apprentissage",
    summary:
      "Utilisez le projet actuel pour transformer les idées en petites modifications, expliquer les décisions et les vérifier.",
    stageTitles: ["Lire le système actuel", "Resserrer le fil principal", "Vérifier et consigner l'apprentissage"],
    stageObjectives: [
      "Repérez les fichiers qui définissent vraiment l'expérience avant de modifier plusieurs couches.",
      "Resserrez l'entrée, la hiérarchie des messages et la zone de saisie du coach.",
      "Vérifiez que le parcours est plus clair, puis conservez l'explication pour les prochaines révisions.",
    ],
    focus: "Resserrer le fil du coach",
    nextStep:
      "Resserrez l'entrée, les messages et le plan, puis vérifiez que le fil principal se lit immédiatement.",
    whyNow: "Cette étape détermine si la personne comprend le fil principal en ouvrant Trainer.",
    verify:
      "Vérifiez que la première vue du plan montre clairement le fil principal, la tâche en cours et la prochaine étape.",
    nextAfter: "Une fois ce fragment clair, continuez a simplifier le flux des messages et la zone de saisie.",
    blockedReason: "La vérification du fichier actuel ne prend pas encore en charge cette étape du plan.",
    acceptanceCriteria: [
      "La personne sait quoi modifier en premier et pourquoi.",
      "Le coach propose une prochaine action claire sans surcharge.",
      "La révision relie l'implémentation au principe d'ingénierie.",
    ],
  },
  "de-DE": {
    title: "Hauptlernstrang",
    summary:
      "Nutze das aktuelle Projekt, um Ideen in kleine Änderungen zu übersetzen, Entscheidungen zu erklären und erneut zu prüfen.",
    stageTitles: ["Das aktuelle System lesen", "Den Hauptstrang schärfen", "Lernen prüfen und festhalten"],
    stageObjectives: [
      "Finde die Dateien, die das Erlebnis wirklich bestimmen, bevor mehrere Ebenen zugleich geändert werden.",
      "Schärfe Einstieg, Nachrichtenhierarchie und Eingabebereich des Coaches.",
      "Prüfe, ob der Ablauf klarer ist, und halte die Erklärung für spätere Wiederholungen fest.",
    ],
    focus: "Den Coach-Strang schärfen",
    nextStep:
      "Schärfe Einstieg, Nachrichten und Plan und prüfe dann, ob der Hauptstrang sofort verständlich ist.",
    whyNow: "Dieser Schritt entscheidet, ob man den Hauptstrang beim Öffnen von Trainer sofort versteht.",
    verify:
      "Prüfe, ob die erste Planansicht Hauptstrang, aktuelle Aufgabe und nächsten Schritt klar zeigt.",
    nextAfter: "Wenn dieser Ausschnitt klar ist, vereinfache weiter den Nachrichtenfluss und den Eingabebereich.",
    blockedReason: "Die Überprüfung der aktuellen Datei unterstützt diesen Planschritt noch nicht.",
    acceptanceCriteria: [
      "Man weiß, was zuerst zu ändern ist und warum.",
      "Der Coach gibt eine klare nächste Aktion ohne Überlastung.",
      "Die Überprüfung verbindet die Umsetzung mit dem technischen Prinzip.",
    ],
  },
  "ja-JP": {
    title: "学習のメインスレッド",
    summary: "現在のプロジェクトで、アイデアを小さな変更にし、判断を説明してからもう一度検証します。",
    stageTitles: ["現在の仕組みを読む", "メインスレッドを整える", "学びを検証して記録する"],
    stageObjectives: [
      "複数の層を同時に変える前に、体験を決めているファイルを見つけます。",
      "コーチの入口、メッセージの階層、入力欄を分かりやすく整えます。",
      "流れが分かりやすくなったか確認し、次の復習に使える説明を残します。",
    ],
    focus: "コーチのスレッドを整える",
    nextStep: "入口、メッセージ、計画を整え、メインスレッドがすぐ理解できるか確認します。",
    whyNow: "この段階で、Trainer を開いた人がメインスレッドをすぐ理解できるかが決まります。",
    verify: "最初の計画画面で、メインスレッド、現在の課題、次の一手が明確に見えることを確認します。",
    nextAfter: "この作業が明確になったら、メッセージの流れと入力欄をさらに簡潔にします。",
    blockedReason: "現在のファイル検証では、この計画ステップはまだ対応していません。",
    acceptanceCriteria: [
      "何を先に変えるか、その理由が分かる。",
      "コーチが負担を増やさず明確な次の行動を示す。",
      "レビューが実装を技術上の原則につなげる。",
    ],
  },
  "ko-KR": {
    title: "학습 메인 흐름",
    summary: "현재 프로젝트에서 아이디어를 작은 변경으로 만들고, 판단을 설명한 뒤 다시 검증합니다.",
    stageTitles: ["현재 시스템 읽기", "메인 흐름 다듬기", "학습 검증 및 기록"],
    stageObjectives: [
      "여러 계층을 한꺼번에 바꾸기 전에 경험을 결정하는 파일을 찾습니다.",
      "코치의 진입점, 메시지 계층, 입력 영역을 더 분명하게 다듬습니다.",
      "흐름이 더 명확해졌는지 확인하고 다음 복습을 위한 설명을 남깁니다.",
    ],
    focus: "코치 흐름 다듬기",
    nextStep: "진입점, 메시지, 계획을 다듬고 메인 흐름이 바로 이해되는지 확인합니다.",
    whyNow: "이 단계가 Trainer 를 열었을 때 사용자가 메인 흐름을 바로 이해하는지를 결정합니다.",
    verify: "첫 계획 화면에서 메인 흐름, 현재 과제, 다음 단계가 분명하게 보이는지 확인합니다.",
    nextAfter: "이 작업이 명확해지면 메시지 흐름과 입력 영역을 더 단순하게 만듭니다.",
    blockedReason: "현재 파일 검증은 아직 이 계획 단계를 지원하지 않습니다.",
    acceptanceCriteria: [
      "무엇을 먼저 바꿔야 하는지와 이유를 안다.",
      "코치가 부담 없이 분명한 다음 행동을 제시한다.",
      "검토가 구현을 기술 원칙과 다시 연결한다.",
    ],
  },
  "pt-BR": {
    title: "Linha principal de aprendizagem",
    summary:
      "Use o projeto atual para transformar ideias em pequenas mudanças, explicar as decisões e verificar tudo novamente.",
    stageTitles: ["Ler o sistema atual", "Ajustar a linha principal", "Verificar e registrar o aprendizado"],
    stageObjectives: [
      "Encontre os arquivos que definem a experiência antes de alterar várias camadas ao mesmo tempo.",
      "Ajuste a entrada, a hierarquia de mensagens e a área de escrita do coach.",
      "Confirme que o fluxo ficou mais claro e guarde a explicação para as próximas revisões.",
    ],
    focus: "Ajustar a linha do coach",
    nextStep: "Ajuste a entrada, as mensagens e o plano; depois confirme que a linha principal fica clara de imediato.",
    whyNow: "Esta etapa define se a pessoa entende a linha principal ao abrir o Trainer.",
    verify:
      "Confirme que a primeira tela do plano mostra claramente a linha principal, a tarefa atual e o próximo passo.",
    nextAfter: "Quando este trecho estiver claro, continue simplificando o fluxo de mensagens e a area de escrita.",
    blockedReason: "A verificação do arquivo atual ainda não oferece suporte a esta etapa do plano.",
    acceptanceCriteria: [
      "A pessoa sabe o que mudar primeiro e por que.",
      "O coach oferece uma próxima ação clara sem sobrecarga.",
      "A revisão conecta a implementação ao princípio de engenharia.",
    ],
  },
};

function applyLocalizedConnectedPlanPreview(
  bootstrap: typeof mockBootstrapData,
  language: ComposerLanguage,
): void {
  const copy = localizedConnectedPlanPreviewCopy[language];
  if (!copy) {
    return;
  }

  const stageTitleFor = (index: number, fallback: string) => copy.stageTitles[index] ?? fallback;
  const stageObjectiveFor = (index: number, fallback: string) => copy.stageObjectives[index] ?? fallback;

  bootstrap.plan = {
    ...bootstrap.plan,
    title: copy.title,
    summary: copy.summary,
    currentStep: copy.nextStep,
    whyNow: copy.whyNow,
    verifyMethod: [copy.verify],
    nextAfterCurrent: copy.nextAfter,
    stages: bootstrap.plan.stages.map((stage, index) => ({
      ...stage,
      title: stageTitleFor(index, stage.title),
      objective: stageObjectiveFor(index, stage.objective),
    })),
  };
  bootstrap.task = {
    ...bootstrap.task,
    title: copy.stageTitles[1],
    description: copy.summary,
    constraints: [copy.whyNow, copy.verify],
    acceptanceCriteria: [...copy.acceptanceCriteria],
    nextActionLabel: copy.nextStep,
  };
  bootstrap.memory = {
    ...bootstrap.memory,
    currentFocus: copy.focus,
    reviewSummary: copy.verify,
    reviewRhythm: copy.verify,
    activeThread: bootstrap.memory.activeThread
      ? {
          ...bootstrap.memory.activeThread,
          focusArea: copy.focus,
          summary: copy.summary,
          nextStep: copy.nextStep,
          blocker: "",
          verifiedResult: copy.verify,
        }
      : bootstrap.memory.activeThread,
    memoryEvidence: [copy.summary, copy.verify],
  };
  bootstrap.coachFocus = {
    ...bootstrap.coachFocus,
    currentFocus: copy.focus,
    reviewRhythm: copy.verify,
    nextStep: copy.nextStep,
    activeStage: copy.stageTitles[1],
    activeTask: copy.stageTitles[1],
    strategyPreferenceSummary: copy.summary,
    continuitySummary: copy.nextAfter,
    recentTeachingSignals: [copy.verify],
    teachingObservations: [copy.whyNow],
    recentWins: [copy.summary],
  };
  bootstrap.planRuntimeStatus = bootstrap.planRuntimeStatus
    ? {
        ...bootstrap.planRuntimeStatus,
        currentStage: bootstrap.planRuntimeStatus.currentStage
          ? {
              ...bootstrap.planRuntimeStatus.currentStage,
              title: copy.stageTitles[1],
              goal: copy.stageObjectives[1],
            }
          : bootstrap.planRuntimeStatus.currentStage,
        currentMainThread: bootstrap.planRuntimeStatus.currentMainThread
          ? {
              ...bootstrap.planRuntimeStatus.currentMainThread,
              focusArea: copy.focus,
              summary: copy.summary,
              nextStep: copy.nextStep,
              currentStep: copy.nextStep,
              whyNow: copy.whyNow,
              nextAfterCurrent: copy.nextAfter,
              verifyMethod: [copy.verify],
            }
          : bootstrap.planRuntimeStatus.currentMainThread,
        coachJudgment: bootstrap.planRuntimeStatus.coachJudgment
          ? {
              ...bootstrap.planRuntimeStatus.coachJudgment,
              summary: copy.summary,
              teachingGoal: copy.whyNow,
              supportStrategy: copy.verify,
              resumeThread: copy.nextStep,
            }
          : bootstrap.planRuntimeStatus.coachJudgment,
        reviewQueueSummary: copy.verify,
        nextTrainingAction: copy.nextStep,
        currentStep: copy.nextStep,
        whyNow: copy.whyNow,
        nextAfterCurrent: copy.nextAfter,
        verifyMethod: [copy.verify],
      }
    : bootstrap.planRuntimeStatus;
  bootstrap.coachingState = {
    ...bootstrap.coachingState,
    scenario: "plan",
    answerMode: "guided",
    learnerSignal: "steady",
    summary: copy.summary,
    nextStep: copy.nextStep,
    encouragement: copy.verify,
    updatedAt: "2026-07-11T08:00:00.000Z",
  };
  bootstrap.coachTurn = {
    ...bootstrap.coachTurn,
    scenario: "plan",
    learnerSignal: "steady",
    summary: copy.summary,
    nextStep: copy.nextStep,
    encouragement: copy.verify,
    activeStage: copy.stageTitles[1],
    activeTask: copy.stageTitles[1],
    teachingGoal: copy.whyNow,
    reviewQueueSummary: copy.verify,
  };
  bootstrap.evaluation = {
    ...bootstrap.evaluation,
    headline: copy.summary,
    summary: copy.whyNow,
    nextStep: copy.nextStep,
  };
}

type RecoveryPreviewCopy = {
  focus: string;
  summary: string;
  nextStep: string;
  whyNow: string;
  verify: string;
  blocker: string;
  artifactTitle: string;
};

const recoveryPreviewCopy: Record<ComposerLanguage, RecoveryPreviewCopy> = {
  "zh-CN": {
    focus: "恢复模型连接",
    summary: "这组已保存的连接还缺密钥，所以暂时不能继续。",
    nextStep: "在“设置”补上密钥，再回到这条主线。",
    whyNow: "确认连接可用后，再继续教学。",
    verify: "保存密钥后测试连接，再继续当前计划。",
    blocker: "连接还缺密钥。",
    artifactTitle: "恢复连接后继续",
  },
  "en-US": {
    focus: "Restore the model connection",
    summary: "This saved connection still needs its key, so Trainer cannot continue yet.",
    nextStep: "Add the key in Settings, then return to this thread.",
    whyNow: "Confirm the connection works before continuing.",
    verify: "Save the key, test the connection, then continue the current plan.",
    blocker: "This saved connection still needs its key.",
    artifactTitle: "Restore the connection, then continue",
  },
  "es-ES": {
    focus: "Restaurar la conexión del proveedor",
    summary: "A la conexión guardada le falta la clave API, por lo que Trainer no puede continuar este turno de coaching.",
    nextStep: "Añade la clave API en Ajustes y vuelve a este mismo hilo.",
    whyNow: "Sin una clave API verificada, un proveedor no debe considerarse listo para el coaching.",
    verify: "Guarda la clave API, ejecuta la prueba de conexión y continúa el plan actual.",
    blocker: "A la conexión guardada del proveedor le falta la clave API.",
    artifactTitle: "Restaura la conexión del proveedor y continúa",
  },
  "fr-FR": {
    focus: "Rétablir la connexion du fournisseur",
    summary: "Il manque la clé API à la connexion enregistrée, donc Trainer ne peut pas poursuivre ce tour de coaching.",
    nextStep: "Ajoutez la clé API dans Réglages, puis revenez à ce même fil.",
    whyNow: "Sans clé API vérifiée, un fournisseur ne doit pas être considéré comme prêt pour le coaching.",
    verify: "Enregistrez la clé API, lancez le test de connexion, puis poursuivez le plan actuel.",
    blocker: "Il manque la clé API à la connexion enregistrée du fournisseur.",
    artifactTitle: "Rétablir la connexion du fournisseur puis continuer",
  },
  "de-DE": {
    focus: "Provider-Verbindung wiederherstellen",
    summary: "Der gespeicherten Verbindung fehlt ein API-Schlüssel. Trainer kann diesen Coaching-Schritt deshalb nicht fortsetzen.",
    nextStep: "Füge den API-Schlüssel in Einstellungen hinzu und kehre dann zu diesem Thread zurück.",
    whyNow: "Ohne verifizierten API-Schlüssel darf ein Provider nicht als coachingbereit gelten.",
    verify: "Speichere den API-Schlüssel, führe den Verbindungstest aus und setze dann den aktuellen Plan fort.",
    blocker: "Der gespeicherten Provider-Verbindung fehlt ein API-Schlüssel.",
    artifactTitle: "Provider-Verbindung wiederherstellen und fortsetzen",
  },
  "ja-JP": {
    focus: "プロバイダー接続を復旧する",
    summary: "保存済みの接続には API キーがないため、Trainer はこのコーチングターンを続けられません。",
    nextStep: "設定で API キーを追加してから、この同じスレッドに戻ります。",
    whyNow: "検証済みの API キーなしに、プロバイダーをコーチング可能と扱うことはできません。",
    verify: "API キーを保存し、接続テストを実行してから現在の計画を続けます。",
    blocker: "保存済みのプロバイダー接続に API キーがありません。",
    artifactTitle: "プロバイダー接続を復旧して続ける",
  },
  "ko-KR": {
    focus: "Provider 연결 복구",
    summary: "저장된 연결에 API 키가 없어 Trainer가 이 코칭 턴을 계속할 수 없습니다.",
    nextStep: "설정에서 API 키를 추가한 뒤 이 스레드로 돌아오세요.",
    whyNow: "검증된 API 키 없이는 Provider를 코칭 준비 완료로 취급할 수 없습니다.",
    verify: "API 키를 저장하고 연결 테스트를 실행한 뒤 현재 계획을 계속하세요.",
    blocker: "저장된 Provider 연결에 API 키가 없습니다.",
    artifactTitle: "Provider 연결을 복구하고 계속하기",
  },
  "pt-BR": {
    focus: "Restaurar a conexão do provedor",
    summary: "Falta a chave de API na conexão salva, então o Trainer não pode continuar esta rodada de coaching.",
    nextStep: "Adicione a chave de API em Configurações e volte para esta mesma conversa.",
    whyNow: "Sem uma chave de API verificada, um provedor não pode ser tratado como pronto para coaching.",
    verify: "Salve a chave de API, execute o teste de conexão e continue o plano atual.",
    blocker: "Falta a chave de API na conexão salva do provedor.",
    artifactTitle: "Restaurar a conexão do provedor e continuar",
  },
};

function previewStorageKeyForLocation(): string {
  return `trainer:webview:preview:${window.location.search || "default"}`;
}

function loadPreviewProviderConfig(): PreviewProviderConfig | undefined {
  try {
    const raw = window.localStorage.getItem(previewStorageKeyForLocation());
    if (!raw) {
      return undefined;
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const provider = parsed.previewProviderConfig;
    if (!provider || typeof provider !== "object" || Array.isArray(provider)) {
      return undefined;
    }
    return sanitizeVisibleData(provider) as PreviewProviderConfig;
  } catch {
    return undefined;
  }
}

function loadPreviewActiveView(): PersistedWorkbenchState["activeView"] | undefined {
  try {
    const raw = window.localStorage.getItem(previewStorageKeyForLocation());
    if (!raw) {
      return undefined;
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const activeView = parsed.activeView;
    return activeView === "coach" ||
      activeView === "plan" ||
      activeView === "resources" ||
      activeView === "training" ||
      activeView === "settings"
      ? activeView
      : undefined;
  } catch {
    return undefined;
  }
}

function trimPreviewString(value: unknown): string | undefined {
  const trimmed = sanitizeVisibleText(value).trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function uniquePreviewStrings(values: ReadonlyArray<unknown> | undefined): string[] {
  if (!Array.isArray(values)) {
    return [];
  }
  return Array.from(
    new Set(
      values
        .filter((value): value is string => typeof value === "string")
        .map((value) => trimPreviewString(value))
        .filter((value): value is string => Boolean(value)),
    ),
  );
}

function createPreviewProfileId(label: string): string {
  const compact = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return compact || "preview-provider";
}

function resolveGuidedTrainingPreviewScenarioAlias(
  scenario: string | null,
): GuidedTrainingPreviewScenario | undefined {
  if (!scenario) {
    return undefined;
  }
  return guidedTrainingPreviewScenarioAliasMap[scenario];
}

function buildFallbackPreviewProviderProfiles(
  providerConfig: PreviewProviderConfig,
  availableModels: string[],
  resolvedModel?: string,
): Array<Record<string, unknown>> {
  if (providerConfig.configured === false) {
    return [];
  }

  const name = trimPreviewString(providerConfig.name);
  const profileLabel = trimPreviewString(providerConfig.profileLabel);
  const label = profileLabel ?? name ?? resolvedModel;
  if (!label) {
    return [];
  }

  return [
    {
      id: trimPreviewString(providerConfig.profileId) ?? createPreviewProfileId(label),
      label,
      name,
      protocol: providerConfig.protocol,
      mode: trimPreviewString(providerConfig.profileMode) ?? "direct",
      credentialMode: providerConfig.credentialMode ?? "ui_proxy",
      baseUrl: trimPreviewString(providerConfig.baseUrl),
      model: resolvedModel ?? "",
      availableModels,
    },
  ];
}

function applyPreviewProviderConfigBootstrap(
  bootstrap: typeof mockBootstrapData,
  providerConfig: PreviewProviderConfig,
): void {
  const resolvedModel =
    trimPreviewString(providerConfig.resolvedModel) ?? trimPreviewString(providerConfig.model);
  const availableModels = uniquePreviewStrings(providerConfig.availableModels);
  const effectiveAvailableModels =
    availableModels.length > 0 ? availableModels : resolvedModel ? [resolvedModel] : [];
  const providerProfiles = Array.isArray(providerConfig.providerProfiles)
    ? [...providerConfig.providerProfiles]
    : buildFallbackPreviewProviderProfiles(providerConfig, effectiveAvailableModels, resolvedModel);
  const fallbackActiveProfile =
    providerProfiles.find((profile) => {
      if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
        return false;
      }
      const record = profile as Record<string, unknown>;
      return trimPreviewString(record.id) === trimPreviewString(providerConfig.profileId);
    }) ?? providerProfiles[0];

  bootstrap.providerConfig = {
    ...bootstrap.providerConfig,
    ...providerConfig,
    model: trimPreviewString(providerConfig.model) ?? resolvedModel ?? bootstrap.providerConfig.model,
    resolvedModel,
    capabilities: {
      ...bootstrap.providerConfig.capabilities,
      ...(providerConfig.capabilities ?? {}),
    },
    availableModels: effectiveAvailableModels,
    profileId:
      trimPreviewString(providerConfig.profileId) ??
      (fallbackActiveProfile && typeof fallbackActiveProfile === "object" && !Array.isArray(fallbackActiveProfile)
        ? trimPreviewString((fallbackActiveProfile as Record<string, unknown>).id)
        : undefined),
    profileLabel:
      trimPreviewString(providerConfig.profileLabel) ??
      (fallbackActiveProfile && typeof fallbackActiveProfile === "object" && !Array.isArray(fallbackActiveProfile)
        ? trimPreviewString((fallbackActiveProfile as Record<string, unknown>).label)
        : undefined),
    profileCount:
      typeof providerConfig.profileCount === "number" && Number.isFinite(providerConfig.profileCount)
        ? providerConfig.profileCount
        : providerProfiles.length > 0
          ? providerProfiles.length
          : undefined,
    providerProfiles,
    providerDashboard:
      providerConfig.providerDashboard ??
      (fallbackActiveProfile
        ? {
            currentProfile: fallbackActiveProfile,
          }
        : undefined),
    modelListStatus:
      providerConfig.modelListStatus ?? (effectiveAvailableModels.length > 0 ? "ready" : "idle"),
  };

  if (bootstrap.connection.state !== "offline") {
    bootstrap.connection = {
      ...bootstrap.connection,
      provider: {
        ...bootstrap.connection.provider,
        name: bootstrap.providerConfig.name || bootstrap.connection.provider.name,
        model:
          bootstrap.providerConfig.resolvedModel?.trim() ||
          bootstrap.providerConfig.model?.trim() ||
          bootstrap.connection.provider.model,
        capabilities: {
          ...bootstrap.connection.provider.capabilities,
          ...bootstrap.providerConfig.capabilities,
        },
      },
    };
  }
}

const PREVIEW_FIXTURE_WORKSPACE_ID = "trainer-preview";

function bindPreviewWorkspaceScope(bootstrap: typeof mockBootstrapData): string {
  const workspaceId =
    bootstrap.memory.workspace?.workspaceId ??
    bootstrap.workspaceTrainingState?.workspaceId ??
    PREVIEW_FIXTURE_WORKSPACE_ID;
  bootstrap.memory = {
    ...bootstrap.memory,
    workspace: {
      ...bootstrap.memory.workspace,
      workspaceId,
    },
  };
  bootstrap.workspaceTrainingState = {
    ...bootstrap.workspaceTrainingState,
    workspaceId: bootstrap.workspaceTrainingState?.workspaceId ?? workspaceId,
  };
  return workspaceId;
}

function stampPreviewLastTest<T extends Record<string, unknown>>(
  bootstrap: typeof mockBootstrapData,
  lastTest: T,
): T & { workspaceId: string; profileId?: string } {
  const workspaceId = bindPreviewWorkspaceScope(bootstrap);
  return {
    ...lastTest,
    workspaceId,
    profileId: (lastTest.profileId as string | undefined) ?? bootstrap.providerConfig.profileId,
  };
}

function applyConnectedProviderBootstrap(
  bootstrap: typeof mockBootstrapData,
  language: ComposerLanguage,
): void {
  const checkedAt = new Date().toISOString();
  const providerName = previewProviderLabel(language, "local");
  const baseUrl = "http://localhost:1234/v1";
  const model = "gpt-4.1-mini-compatible";
  const availableModels = [model, "gpt-4.1", "gpt-4o-mini"];
  const capabilities = {
    chat: true,
    responses: true,
    vision: true,
    embeddings: false,
    tools: false,
    jsonSchema: false,
    structuredOutput: false,
    streaming: true,
  };
  const profile = {
    id: "preview-compatible-service",
    label: providerName,
    protocol: "openai_chat_completions_compatible" as const,
    mode: "direct" as const,
    credentialMode: "ui_proxy" as const,
    baseUrl,
    model,
    availableModels,
  };
  bootstrap.connection = {
    state: "connected",
    provider: {
      name: providerName,
      model,
      capabilities,
    },
  };
  bootstrap.providerConfig = {
    ...bootstrap.providerConfig,
    configured: true,
    name: providerName,
    baseUrl,
    model,
    apiKeyConfigured: true,
    protocol: profile.protocol,
    credentialMode: profile.credentialMode,
    profileId: profile.id,
    profileLabel: profile.label,
    profileMode: profile.mode,
    profileCount: 1,
    capabilities,
    availableModels,
    resolvedModel: model,
    providerProfiles: [profile],
    providerDashboard: {
      ...bootstrap.providerConfig.providerDashboard,
      currentProfile: profile,
      diagnostics: [
        previewText(language, "预览连接已准备好。", "Preview connection is ready."),
      ],
    },
    profileHistory: [],
    modelListStatus: "ready",
    modelListDetail: previewText(language, "模型列表已准备好。", "Model list is ready."),
    cacheFetchedAt: "2026-06-21T08:45:00.000Z",
    cacheExpiresAt: "2026-06-22T08:45:00.000Z",
    cacheSource: "live",
    modelErrorCategory: undefined,
    modelStatusCode: undefined,
    modelRetryable: undefined,
    lastTestResult: stampPreviewLastTest(bootstrap, {
      ok: true,
      status: "ok",
      detail: previewText(language, "连接、模型和 API key 都可用。", "Connection, model, and API key are all usable."),
      checkedAt,
      providerName,
      baseUrl,
      model,
      protocol: profile.protocol,
      profileId: profile.id,
      responseLanguage: language,
      streamingReady: true,
      streamProbeStatus: "verified" as const,
      capabilityEvidence: [
        { name: "streaming", declared: true, observed: true, state: "verified" as const },
      ],
    }),
  };
  if (language !== "zh-CN") {
    bootstrap.sessionLabel = "From idea to code";
    bootstrap.profile = {
      ...bootstrap.profile,
      learnerName: "You",
      goals: [
        "Turn vague ideas into clear implementation steps",
        "Learn the codebase through coaching, not just output",
      ],
      preferredStyle: "auto",
      targetProject: "Make Trainer a long-lived unified learning coach",
      preferredRhythm: "Move one tiny, verifiable slice at a time",
      preferredLearningMode: "Discuss the approach first, then land it in code together",
      onboardingRequest: "Lower sidebar friction, continuity gaps, and plan-reading cost first",
      projectContext: "This is a VS Code Trainer extension with a React webview and a FastAPI sidecar.",
    };
    bootstrap.memory = {
      ...bootstrap.memory,
      currentFocus: "The main goal is to keep the loop clear: idea, change, verification, and principle.",
      reviewSummary:
        "The strongest rhythm is idea -> file boundary -> current slice -> verification -> explanation -> review.",
      reviewRhythm: "After this UI pass, do one immediate review and one next-day review.",
      activeThread: bootstrap.memory.activeThread
        ? {
            ...bootstrap.memory.activeThread,
            focusArea: "Coach thread tightening",
            summary: "Compress the main thread into a more resumable coach experience.",
            nextStep: "Attach conversation, plan, and continuity memory to the same training thread.",
            blocker: "If the information hierarchy spreads out, the user cannot tell what matters now.",
            verifiedResult:
              "The top level has stabilized into five views, and Training no longer looks like a backend panel.",
          }
        : bootstrap.memory.activeThread,
      memoryEvidence: [
        "The top level has stabilized into five views, and Training no longer looks like a backend panel.",
        "The current blocker is that a scattered hierarchy hides the immediate task.",
        "Keep pushing the coach main thread toward one resumable slice.",
      ],
    };
    bootstrap.coachFocus = {
      ...bootstrap.coachFocus,
      currentFocus: "Coach thread tightening",
      reviewRhythm: "After this UI pass, do one immediate review and one next-day review.",
      nextStep: "Fix the login error message.",
      activeStage: "Tighten the main thread",
      activeTask: "Ship a coach-first sidebar rewrite",
      relationshipStage: "active",
      firstTurnPriority: "Clarify the goal, the project, and the blocker before choosing the coaching lane.",
      strategyPreferenceSummary: "The strongest turns start by narrowing the UI and landing one slice at a time.",
      continuitySummary: "Conversation shell -> plan expression -> input area",
      recentTeachingSignals: [
        "First shrink the slice, then expand again.",
        "The UI is strong when each turn can naturally continue the thread.",
      ],
      teachingObservations: [
        "When the coach names the file boundary first, the user gets moving faster.",
        "A plan page that reads like a training trace lowers the cost of understanding.",
      ],
      recentWins: [
        "You have made it clear that coaching strength comes from the backend, not from piling up front-end entry points.",
      ],
      dueReviewCount: 2,
      language,
    };
    bootstrap.plan = {
      ...bootstrap.plan,
      title: "Main training thread",
      cadence: "4 focused coding sessions per week",
      summary:
        "Use the current project as the training ground: turn ideas into file-level changes, explain as you go, and keep the key judgment in the review loop.",
      stages: [
        {
          id: "s1",
          title: "Read the current system",
          objective:
            "Locate the files that actually define the experience instead of changing front and back ends at once.",
          status: "done",
        },
        {
          id: "s2",
          title: "Push the main thread",
          objective:
            "Tighten the top entry, message hierarchy, and input area into a quieter coach sidebar.",
          status: "active",
        },
        {
          id: "s3",
          title: "Verify and record the teaching",
          objective:
            "Check whether the experience is clearer, then write the principle back into review nodes.",
          status: "queued",
        },
      ],
    };
    bootstrap.task = {
      ...bootstrap.task,
      title: "Land a coach-first refactor in the current codebase",
      description:
        "Work from the current repository and turn the idea into specific file changes, implementation order, and reasoning that the user can act on.",
      constraints: [
        "Do not skip reading and planning.",
        "The guidance must be based on the current repo, not generic advice.",
        "Explain the reason behind each code change when needed.",
      ],
      acceptanceCriteria: [
        "The user knows what to change first and why.",
        "The coach gives a clear next action without overload.",
        "Review feedback reconnects implementation details to engineering principles.",
      ],
      nextActionLabel: "Continue to the next step",
    };
    bootstrap.planRuntimeStatus = bootstrap.planRuntimeStatus
      ? {
          ...bootstrap.planRuntimeStatus,
          currentStage: bootstrap.planRuntimeStatus.currentStage
            ? {
                ...bootstrap.planRuntimeStatus.currentStage,
                title: "Tighten the main thread",
                goal: "Tighten the top entry, message hierarchy, and input area into a quieter coach sidebar.",
              }
            : bootstrap.planRuntimeStatus.currentStage,
          currentMainThread: bootstrap.planRuntimeStatus.currentMainThread
            ? {
                ...bootstrap.planRuntimeStatus.currentMainThread,
                focusArea: "Coach thread tightening",
                summary: "Compress the main thread into a more resumable coach experience.",
                nextStep:
                  "Fix the login error message.",
                currentStep:
                  "Fix the login error message.",
                whyNow:
                  "This step decides whether the user can instantly understand the main line, more than another visible entry point.",
                nextAfterCurrent: "If this slice is clear, keep compressing the message flow and the input area.",
              }
            : bootstrap.planRuntimeStatus.currentMainThread,
          coachJudgment: bootstrap.planRuntimeStatus.coachJudgment
            ? {
                ...bootstrap.planRuntimeStatus.coachJudgment,
                summary: "The focus now is to make the coach main line feel natural and sustainable.",
                teachingGoal: "Make the user instantly know what is happening, why it matters, and how to verify it.",
                supportStrategy: "Keep research and long-term memory in the lower layers instead of the top entry points.",
                resumeThread: "Continue the next round by tightening plan wording and the message flow.",
              }
            : bootstrap.planRuntimeStatus.coachJudgment,
          reviewQueueSummary: "There are 2 key judgments to revisit after this UI pass.",
          nextTrainingAction:
            "Fix the login error message.",
          currentStep:
            "Fix the login error message.",
          whyNow:
            "This step decides whether the user can instantly understand the main line, more than another visible entry point.",
          nextAfterCurrent: "If this slice is clear, keep compressing the message flow and the input area.",
          verifyMethod: [
            "Check that the first plan view makes the main line, current slice, and next step obvious at a glance.",
          ],
        }
      : bootstrap.planRuntimeStatus;
    bootstrap.coachingState = {
      ...bootstrap.coachingState,
      scenario: "general",
      answerMode: "guided",
      learnerSignal: "steady",
      summary: "The settings view now shows a usable state, not a backend form.",
      nextStep: "Jump back to Coach and continue with conversation, planning, and training.",
      encouragement: "The connection is ready, so the rest of the UI can feel like a real coach.",
      updatedAt: checkedAt,
    };
    bootstrap.evaluation = {
      ...bootstrap.evaluation,
      headline: "The main thread is clearer; the next step is to keep tightening the message expression",
      summary:
        "The direction is right, but the coach reply still needs to feel like continuous training rather than a one-off suggestion.",
      nextStep:
        "Keep tightening App, message hierarchy, and plan wording, then verify the user can instantly understand the current main line.",
    };
  }

  bootstrap.memory = {
    ...bootstrap.memory,
    workspace: {
      ...bootstrap.memory.workspace,
      trainerWorkspace: {
        status: "managed",
        rootPath: "G:\\trainer",
        projectId: "trainer-preview",
        projectName: "Trainer",
        projectPath: "G:\\trainer",
        updatedAt: "2026-07-11T08:00:00.000Z",
      },
    },
  };

  applyLocalizedConnectedPlanPreview(bootstrap, language);
}

function applyGuidedTrainingPreviewScenario(
  bootstrap: typeof mockBootstrapData,
  state: BrowserPreviewState,
): boolean {
  const scenario = state.scenario;
  if (!scenario || !guidedTrainingPreviewScenarios.includes(scenario as GuidedTrainingPreviewScenario)) {
    return false;
  }

  const language = state.composerLanguage;
  const isFlash = state.trainingSubmode === "flash";
  const pack = resolveGuidedTrainingPreviewScenarioData(
    scenario as GuidedTrainingPreviewScenario,
    language,
  );
  if (!pack) {
    return false;
  }

  const {
    sourceChain,
    currentFocus,
    coachSummary,
    practiceGoal,
    flashGoal,
    practiceNextStep,
    flashNextStep,
    practiceCard,
    flashCard,
  } = pack;

  const selectedCard = isFlash ? flashCard : practiceCard;
  const nextCard = isFlash ? practiceCard : flashCard;
  const nextHopSummary =
    nextCard.problemStatement ||
    nextCard.suggestedWorkspaceAction ||
    nextCard.deliverable ||
    (isFlash ? flashGoal : practiceGoal);
  const taskDescription = selectedCard.problemStatement || selectedCard.scenario || coachSummary;
  const nextActionLabel = isFlash ? flashNextStep : practiceNextStep;
  const reviewRequiresReflection = state.trainingSubmode === "review";
  const reviewSummary = previewText(
    language,
    "验证已经通过。先记录一条可复用的复盘，再完成回流。",
    "Verification passed. Record one reusable reflection before completing Return.",
    {
      "es-ES": "La verificaci\u00f3n se aprob\u00f3. Registra una reflexi\u00f3n reutilizable antes de completar el retorno.",
      "fr-FR": "La v\u00e9rification a r\u00e9ussi. Notez une r\u00e9flexion r\u00e9utilisable avant de terminer le retour.",
      "de-DE": "Die \u00dcberpr\u00fcfung war erfolgreich. Halte vor dem Abschluss der R\u00fcckgabe eine wiederverwendbare Reflexion fest.",
      "ja-JP": "\u691c\u8a3c\u306b\u5408\u683c\u3057\u307e\u3057\u305f\u3002\u623b\u308b\u524d\u306b\u518d\u5229\u7528\u3067\u304d\u308b\u632f\u308a\u8fd4\u308a\u3092\u8a18\u9332\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
      "ko-KR": "\uac80\uc99d\uc744 \ud1b5\uacfc\ud588\uc2b5\ub2c8\ub2e4. \ub3cc\uc544\uac00\uae30 \uc804\uc5d0 \uc7ac\uc0ac\uc6a9\ud560 \uc218 \uc788\ub294 \ud68c\uace0\ub97c \uae30\ub85d\ud558\uc138\uc694.",
      "pt-BR": "A verifica\u00e7\u00e3o foi aprovada. Registre uma reflex\u00e3o reutiliz\u00e1vel antes de concluir o retorno.",
    },
  );

  bootstrap.task = {
    ...bootstrap.task,
    id: isFlash ? `${scenario}-flash-task` : `${scenario}-practice-task`,
    title: selectedCard.title,
    description: taskDescription,
    constraints: selectedCard.constraints,
    acceptanceCriteria: selectedCard.learnerDeliverables,
    nextActionLabel,
  };
  bootstrap.memory = {
    ...bootstrap.memory,
    currentFocus: currentFocus,
    reviewSummary: coachSummary,
    activeThread: bootstrap.memory.activeThread
      ? {
          ...bootstrap.memory.activeThread,
          focusArea: currentFocus,
          summary: coachSummary,
          nextStep: selectedCard.suggestedWorkspaceAction || taskDescription,
          verifiedResult: selectedCard.successSignal,
        }
      : bootstrap.memory.activeThread,
  };
  bootstrap.coachingState = {
    ...bootstrap.coachingState,
    scenario: isFlash ? "review" : "task",
    answerMode: "guided",
    learnerSignal: "curious",
    summary: coachSummary,
    nextStep: selectedCard.suggestedWorkspaceAction || taskDescription,
    encouragement: previewText(
      language,
      "先把这一张卡讲实、练实，Trainer 的主线就会稳很多。",
      "Make this single card concrete first, and the Trainer main loop becomes much steadier.",
    ),
    updatedAt: "2026-06-29T10:00:00.000Z",
  };
  bootstrap.coachTurn = {
    ...bootstrap.coachTurn,
    scenario: isFlash ? "review" : "task",
    learnerSignal: "curious",
    summary: coachSummary,
    nextStep: selectedCard.suggestedWorkspaceAction || taskDescription,
    encouragement: previewText(
      language,
      "先把当前证据压到足够可信，再继续更深的计划或实现。",
      "Make the current evidence trustworthy first, then continue into deeper planning or implementation.",
    ),
    activeStage: isFlash
      ? previewText(language, "先压进记忆", "Lock it into memory first")
      : previewText(language, "先完成当前卡", "Finish the current card first"),
    activeTask: selectedCard.title,
    dueReviewCount: 0,
    reviewQueueSummary: previewText(
      language,
      "当前训练优先级是完成这一张卡，而不是并行打开更多面板。",
      "The training priority is to finish this one card, not open more panels in parallel.",
    ),
    artifactKinds: [],
    suggestedActionTypes: ["task"],
    backgroundMode: "embedded",
  };
  bootstrap.workspaceTrainingState = {
    workspaceId: "trainer-preview",
    latestConversationHandoff: {
      candidateId: `${scenario}-${selectedCard.type}`,
      candidateType: isFlash ? "flash_candidate" : "practice_candidate",
      targetKind: "training_card",
      targetId: selectedCard.cardId,
      continueIn: "training",
      acceptedInto: "training",
      handoffStatus: "accepted",
      handoffSummary: selectedCard.whyNow,
      cardType: selectedCard.type,
      cardTitle: selectedCard.title,
      learnerDeliverables: selectedCard.learnerDeliverables,
      verificationSteps: selectedCard.verificationSteps,
      successSignal: selectedCard.successSignal,
      returnWith: selectedCard.returnWith,
      nextAfterCompletion: selectedCard.nextAfterCompletion,
      judgedAt: "2026-06-29T10:00:00.000Z",
      sourceChain,
    },
    latestTrainingHandoff: {
      handoffId: `preview-${scenario}-${selectedCard.type}-handoff`,
      candidateId: `${scenario}-${selectedCard.type}`,
      candidateType: isFlash ? "flash_candidate" : "practice_candidate",
      targetKind: "training_card",
      targetId: selectedCard.cardId,
      continueIn: "training",
      acceptedInto: "training",
      handoffStatus: reviewRequiresReflection ? "needs_reflection" : "accepted",
      handoffSummary: selectedCard.whyNow,
      cardType: selectedCard.type,
      cardTitle: selectedCard.title,
      learnerDeliverables: selectedCard.learnerDeliverables,
      verificationSteps: selectedCard.verificationSteps,
      successSignal: selectedCard.successSignal,
      returnWith: selectedCard.returnWith,
      nextAfterCompletion: reviewRequiresReflection ? reviewSummary : selectedCard.nextAfterCompletion,
      returnSummary: reviewRequiresReflection ? reviewSummary : selectedCard.returnWith,
      judgedAt: "2026-06-29T10:00:00.000Z",
      sourceChain,
    },
    latestTrainingNextHop: {
      candidateId: `${scenario}-${nextCard.type}-next`,
      candidateType: nextCard.type === "flash" ? "flash_candidate" : "practice_candidate",
      title: nextCard.title,
      summary: nextHopSummary,
      whyNow: nextCard.whyNow,
      continueIn: "training",
      targetKind: "training_card",
      targetId: nextCard.cardId,
      acceptedInto: "training",
      status: reviewRequiresReflection ? "reflection_required" : "surfaced",
      handoffStatus: reviewRequiresReflection ? "reflection_required" : undefined,
      statusReason: reviewRequiresReflection ? reviewSummary : undefined,
      cardType: nextCard.type,
      cardTitle: nextCard.title,
      returnSummary: nextCard.returnWith,
      judgedAt: "2026-06-29T10:00:00.000Z",
      sourceChain,
    },
    latestTrainingSubmode: state.trainingSubmode,
    latestLearningFocusArea: currentFocus,
    latestLearningFollowup: selectedCard.returnWith,
    latestLearningVerifiedResult: "",
    latestLearningPartialProgress: reviewRequiresReflection
      ? reviewSummary
      : selectedCard.returnWith ||
        selectedCard.problemStatement ||
        selectedCard.suggestedWorkspaceAction ||
        coachSummary,
    selectedCardId: selectedCard.cardId,
    selectedCardType: selectedCard.type,
    selectedCardTitle: selectedCard.title,
    selectedCardStatus: "active",
    reviewArtifact: undefined,
    trainingCardCandidates: [selectedCard],
    activeTrainingCardRouting: {
      selectedCardId: selectedCard.cardId,
      selectedCard: { ...selectedCard },
      whyThisCard: selectedCard.whyNow,
      nextAfterCompletion: selectedCard.nextAfterCompletion,
      candidateCount: 1,
      eligibleCount: 1,
    },
    trainingEventLedger: [
      {
        eventId: `${scenario}-${selectedCard.type}-selected`,
        eventType: "card_status_transitioned",
        candidateId: `${scenario}-${selectedCard.type}`,
        candidateType: isFlash ? "flash_candidate" : "practice_candidate",
        candidateContinueIn: "training",
        selectedCardId: selectedCard.cardId,
        selectedCardType: selectedCard.type,
        selectedCardTitle: selectedCard.title,
        cardCandidateId: selectedCard.cardId,
        cardCandidateType: selectedCard.type,
        cardCandidateTitle: selectedCard.title,
        whyThisCard: selectedCard.whyNow,
        learnerDeliverables: selectedCard.learnerDeliverables,
        verificationSteps: selectedCard.verificationSteps,
        successSignal: selectedCard.successSignal,
        expectedSymbols: "expectedSymbols" in selectedCard ? selectedCard.expectedSymbols : undefined,
        filesToTouch: "filesToTouch" in selectedCard ? selectedCard.filesToTouch : undefined,
        returnWith: selectedCard.returnWith,
        nextAfterCompletion: selectedCard.nextAfterCompletion,
        sourceChain,
        statusSummary: previewText(language, "当前训练卡已就绪", "Current training card is ready"),
        statusKind: "active",
      },
    ],
    theoryDrill: {
      id: `theory-${scenario}`,
      title: flashCard.title,
      focusArea: currentFocus,
      status: isFlash ? "in_progress" : "ready",
      summary: flashCard.scenario,
      successSignal: flashCard.successSignal,
      returnWith: flashCard.returnWith,
      questions: [
        {
          id: `theory-${scenario}-q1`,
          prompt: flashCard.problemStatement,
        },
      ],
      updatedAt: "2026-06-29T10:00:00.000Z",
    },
    dueReviews: [],
  };

  return true;
}

function applyTrainingLifecyclePreviewScenario(
  bootstrap: typeof mockBootstrapData,
  state: BrowserPreviewState,
): boolean {
  if (state.activeView !== "training" || !state.scenario) {
    return false;
  }

  const language = state.composerLanguage;

  if (state.scenario === "done") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.workspaceTrainingState = {
      ...bootstrap.workspaceTrainingState,
      latestLearningVerifiedResult: previewText(
        language,
        "这一轮训练已经收口，可以把结果带回 Coach。",
        "This training round is closed and ready to return to Coach.",
      ),
      latestLearningPartialProgress: previewText(
        language,
        "其余材料已经收回到复盘层，不再和当前卡抢主线。",
        "The remaining material is folded back into review instead of competing with the current card.",
      ),
      latestLearningFollowup: previewText(
        language,
        "先把结果带回 Coach，再决定下一张卡。",
        "Bring the result back to Coach first, then choose the next card.",
      ),
      latestLearningBlocker: undefined,
      selectedCardStatus: "implemented",
      latestTrainingHandoff: {
        ...bootstrap.workspaceTrainingState?.latestTrainingHandoff,
        handoffStatus: "fed_back",
        returnMode: "result",
        returnSummary: previewText(
          language,
          "结果已经回到教练主线。",
          "The result has returned to the coach main line.",
        ),
      },
      latestTrainingNextHop: {
        ...bootstrap.workspaceTrainingState?.latestTrainingNextHop,
        status: "accepted",
        statusReason: previewText(
          language,
          "当前卡已经完成，下一步交给 Coach 决定。",
          "The current card is complete, so Coach decides the next step.",
        ),
      },
      reviewArtifact: {
        ...bootstrap.workspaceTrainingState?.reviewArtifact,
        status: "resolved",
        verifiedResult: previewText(
          language,
          "训练结果已经被验证。",
          "The training result has been verified.",
        ),
      },
      theoryDrill: {
        ...bootstrap.workspaceTrainingState?.theoryDrill,
        status: "completed",
      },
      scenarioLab: {
        ...bootstrap.workspaceTrainingState?.scenarioLab,
        status: "done",
      },
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "steady",
      summary: previewText(
        language,
        "这一轮做完了。改动能跑，提示也对得上。",
        "This round is done, so the UI should make the result, verification, and return path explicit.",
      ),
      nextStep: previewText(
        language,
        "把这次结果带回 Coach，然后再决定下一张卡。",
        "Bring this result back to Coach, then decide on the next card.",
      ),
      decision: previewText(
        language,
        "保留收口后的证据，再让教练决定是否继续扩展。",
        "Keep the closing evidence visible, then let Coach decide whether to expand further.",
      ),
      teachingNote: previewText(
        language,
        "先让用户一眼看到这轮已经收束，再展开下一跳。",
        "Make the closure obvious first, then open the next hop.",
      ),
      confidence: "high",
    };
    return true;
  }

  if (state.scenario === "blocked") {
    applyConnectedProviderBootstrap(bootstrap, language);
    const blocker = previewText(
      language,
      "当前交付物还没有被当前文件和验证证据稳住。",
      "The current deliverable is not yet supported by the file and verification evidence.",
    );
    bootstrap.workspaceTrainingState = {
      ...bootstrap.workspaceTrainingState,
      latestLearningVerifiedResult: "",
      latestLearningPartialProgress: previewText(
        language,
        "卡片还有效，但现在要先把 blocker 收窄成一条可修的证据链。",
        "The card is still valid, but the blocker needs to be narrowed into one repairable proof chain.",
      ),
      latestLearningFollowup: previewText(
        language,
        "先收紧 blocker，再回到同一张卡验证。",
        "Tighten the blocker first, then return to the same card and verify again.",
      ),
      latestLearningBlocker: blocker,
      selectedCardStatus: "blocked",
      latestTrainingHandoff: {
        ...bootstrap.workspaceTrainingState?.latestTrainingHandoff,
        handoffStatus: "blocked",
        blockedBy: blocker,
        returnMode: "blocker",
        returnSummary: previewText(
          language,
          "这轮还不能回流，必须先修正验证路径。",
          "This round cannot return yet; the verification path must be repaired first.",
        ),
      },
      latestTrainingNextHop: {
        ...bootstrap.workspaceTrainingState?.latestTrainingNextHop,
        status: "blocked",
        statusReason: previewText(
          language,
          "先收窄修复，再重新验证当前卡。",
          "Narrow the fix first, then re-verify the current card.",
        ),
        blockedBy: blocker,
      },
      reviewArtifact: {
        ...bootstrap.workspaceTrainingState?.reviewArtifact,
        status: "active",
        blockedReason: blocker,
      },
      theoryDrill: {
        ...bootstrap.workspaceTrainingState?.theoryDrill,
        status: "ready",
      },
      scenarioLab: {
        ...bootstrap.workspaceTrainingState?.scenarioLab,
        status: "ready",
      },
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "blocked",
      summary: previewText(
        language,
        "这不是 provider 卡死，而是当前训练卡还缺一条可信的验证证据。",
        "This is not a provider failure; the current training card is still missing one trustworthy proof point.",
      ),
      nextStep: previewText(
        language,
        "先把 blocker 写清楚，再决定最小修复。",
        "Write the blocker clearly first, then choose the smallest fix.",
      ),
      decision: previewText(
        language,
        "继续同一张卡，不要跳到新任务。",
        "Stay on the same card instead of jumping to a new task.",
      ),
      teachingNote: previewText(
        language,
        "阻塞时先收窄证据，再谈下一步。",
        "When blocked, narrow the evidence first before choosing the next move.",
      ),
      confidence: "medium",
    };
    return true;
  }

  if (state.scenario === "recovery") {
    applyConnectedProviderBootstrap(bootstrap, language);
    const recoveryReason = previewText(
      language,
      "先用复盘把失败收窄成一条能重新尝试的规则。",
      "Use reflection to compress the failure into one rule you can try again.",
    );
    bootstrap.workspaceTrainingState = {
      ...bootstrap.workspaceTrainingState,
      latestLearningVerifiedResult: "",
      latestLearningPartialProgress: previewText(
        language,
        "当前卡没有丢失，只是需要先复盘再重试。",
        "The current card is not lost; it just needs reflection before the retry.",
      ),
      latestLearningFollowup: previewText(
        language,
        "先复盘哪条证据缺失，再回到同一张卡。",
        "Reflect on which proof is missing, then return to the same card.",
      ),
      latestLearningBlocker: previewText(
        language,
        "这轮先不要扩范围，先把失败压成一条能带回主线的规则。",
        "Do not expand the scope yet; compress the failure into one rule you can bring back.",
      ),
      selectedCardStatus: "answered",
      latestTrainingHandoff: {
        ...bootstrap.workspaceTrainingState?.latestTrainingHandoff,
        handoffStatus: "needs_revision",
        blockedBy: recoveryReason,
        returnMode: "reflection_required",
        returnSummary: previewText(
          language,
          "先复盘，再回到这张卡继续。",
          "Reflect first, then return to this card and continue.",
        ),
      },
      latestTrainingNextHop: {
        ...bootstrap.workspaceTrainingState?.latestTrainingNextHop,
        status: "surfaced",
        statusReason: previewText(
          language,
          "复盘完成后继续同一张卡。",
          "Continue on the same card after reflection.",
        ),
      },
      reviewArtifact: {
        ...bootstrap.workspaceTrainingState?.reviewArtifact,
        status: "active",
        blockedReason: recoveryReason,
        nextSelfImplementationRule: previewText(
          language,
          "先把失败解释清楚，再改动当前文件。",
          "Explain the failure clearly before changing the current file.",
        ),
      },
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "blocked",
      summary: previewText(
        language,
        "当前更像一次恢复回合：先解释失败，再回到同一张卡。",
        "This is a recovery turn: explain the failure first, then return to the same card.",
      ),
      nextStep: previewText(
        language,
        "先说清楚是哪条证据缺失，再决定重试动作。",
        "Name the missing proof first, then decide how to retry.",
      ),
      decision: previewText(
        language,
        "先复盘，不要立刻切新卡。",
        "Reflect first instead of opening a new card immediately.",
      ),
      teachingNote: previewText(
        language,
        "恢复不是重做全部，而是把失败收窄到下一次能验证的程度。",
        "Recovery is not a full redo; it narrows the failure until the next verification is possible.",
      ),
      confidence: "medium",
    };
    return true;
  }

  return false;
}

function resolvePreviewState(): BrowserPreviewState {
  const search = new URLSearchParams(window.location.search);
  const requestedView = search.get("view");
  const requestedSubmode = search.get("submode");
  const requestedLanguage = search.get("lang");
  const requestedTheme = search.get("theme");
  const requestedVscodeTheme = search.get("vscodeTheme");
  const requestedConnection = search.get("connection");
  const requestedStreamingMode = search.get("stream");
  const requestedScenario = search.get("scenario") ?? resolvePreviewScenarioCase(search.get("case"));
  const requestedWorkspaceAdmission = search.get("workspaceAdmission");
  const requestedGuidedTrainingScenario = resolveGuidedTrainingPreviewScenarioAlias(requestedScenario ?? null);
  const persistedActiveView = loadPreviewActiveView();

  const resolvedLanguage = SUPPORTED_LANGUAGES.includes(requestedLanguage as ComposerLanguage)
    ? (requestedLanguage as ComposerLanguage)
    : "zh-CN";
  const explicitPreviewView =
    requestedView === "practice"
      ? "training"
      : requestedView === "plan" ||
          requestedView === "training" ||
          requestedView === "resources" ||
          requestedView === "settings"
        ? requestedView
        : requestedView === null
          ? undefined
          : "coach";
  const resolvedActiveView =
    explicitPreviewView ??
    persistedActiveView ??
    (requestedGuidedTrainingScenario ? "training" : "coach");
  const defaultGuidedTrainingScenario: GuidedTrainingPreviewScenario | undefined =
    requestedScenario === undefined && !requestedGuidedTrainingScenario && resolvedActiveView === "training"
      ? "training-function"
      : undefined;
  const resolvedTrainingSubmode =
    requestedSubmode === "flash" ||
    requestedSubmode === "learn-primer" ||
    requestedSubmode === "learn_primer" ||
    requestedSubmode === "review" ||
    requestedSubmode === "drill" ||
    requestedSubmode === "scenario" ||
    requestedSubmode === "transfer"
      ? requestedSubmode
      : "practice";
  const resolvedThemePreference =
    requestedTheme === "light" || requestedTheme === "dark" || requestedTheme === "system"
      ? requestedTheme
      : "dark";
  const resolvedVscodeTheme =
    requestedVscodeTheme === "light" || requestedVscodeTheme === "dark"
      ? requestedVscodeTheme
      : resolvedThemePreference === "light"
        ? "light"
        : "dark";
  const resolvedStreamingMode = requestedStreamingMode === "demo" ? "demo" : undefined;
  const resolvedScenario =
    requestedScenario === "stream" ||
    requestedScenario === "rich-content" ||
    requestedScenario === "blocked" ||
    requestedScenario === "recovery" ||
    requestedScenario === "ready" ||
    requestedScenario === "vision-ready" ||
    requestedScenario === "provider-failure" ||
    requestedScenario === "provider-failure-empty" ||
    requestedScenario === "provider-auth-failure" ||
    requestedScenario === "provider-auth-failure-empty" ||
    requestedScenario === "empty" ||
    requestedScenario === "plan-frozen" ||
    requestedScenario === "plan-blocked" ||
    requestedScenario === "done" ||
    requestedScenario === "resource-preview-loaded" ||
    requestedScenario === "workspace-admission"
      ? requestedScenario
      : requestedGuidedTrainingScenario
        ? requestedGuidedTrainingScenario
        : defaultGuidedTrainingScenario;
  const resolvedConnectionState =
    requestedConnection === "connected" || requestedConnection === "starting" || requestedConnection === "offline"
      ? requestedConnection
      : search.get("live") === "1" ||
          requestedGuidedTrainingScenario || resolvedActiveView === "plan" ||
          (resolvedScenario !== undefined && resolvedScenario !== "blocked")
        ? "connected"
        : "offline";
  const previewProviderConfig = loadPreviewProviderConfig();

  return {
    themePreference: resolvedThemePreference,
    learningSurfaceAlignment: "left",
    activeView: resolvedActiveView,
    trainingSubmode: resolvedTrainingSubmode,
    composerLanguage: resolvedLanguage,
    composerAnswerMode: "auto",
    teachingStyle: "auto",
    resourceSearchMode: "lexical",
    includeCurrentFile: true,
    includeSelection: true,
    includeDiagnostics: true,
    includeRelatedFiles: true,
    contextDetail: "balanced",
    followCurrentFile: true,
    coachDefaults: {
      memoryScope: "project",
      workingSetMode: "balanced",
      reviewCadence: "steady",
      reviewReminderMode: "due",
      workspaceMemoryToggles: {
        decisions: true,
        patterns: true,
        resources: true,
      },
    },
    composerDraft: "",
    connectionState: resolvedConnectionState,
    streamingMode: resolvedStreamingMode,
    vscodeTheme: resolvedVscodeTheme,
    scenario: resolvedScenario,
    workspaceAdmission:
      requestedWorkspaceAdmission === "root-missing" ||
      requestedWorkspaceAdmission === "project-found" ||
      requestedWorkspaceAdmission === "managed" ||
      requestedWorkspaceAdmission === "browse" ||
      requestedWorkspaceAdmission === "ignored"
        ? requestedWorkspaceAdmission
        : "project-found",
    previewProviderConfig,
  } as BrowserPreviewState;
}

function applyPreviewScenario(bootstrap: typeof mockBootstrapData, state: BrowserPreviewState): void {
  const language = state.composerLanguage;
  const scenario = state.scenario;
  if (!scenario) {
    return;
  }

  if (applyTrainingLifecyclePreviewScenario(bootstrap, state)) {
    return;
  }

  if (scenario === "workspace-admission") {
    applyConnectedProviderBootstrap(bootstrap, language);
    const projectPath = "D:\\TrainerWorkspace\\Projects\\trainer-extension";
    const admissionStatus = state.workspaceAdmission ?? "project-found";
    const copy = workspaceAdmissionPreviewCopy[language];
    const projectName = copy.projectName;
    const nextStep = copy.nextSteps[admissionStatus];
    bootstrap.conversation = [];
    bootstrap.memory = {
      ...bootstrap.memory,
      workspace: {
        ...bootstrap.memory.workspace,
        trainerWorkspace: {
          status: admissionStatus,
          rootPath: "D:\\TrainerWorkspace",
          projectId: "trainer-extension-preview",
          projectName,
          projectPath,
          updatedAt: "2026-07-11T08:00:00.000Z",
        },
      },
      workspaceUnderstanding: {
        repoSummary: copy.repoSummary,
        entryPoints: ["extension/src/extension.ts", "server/app/main.py"],
        featureLanes: ["Coach", "Plan", "Resources", "Training"],
        riskZones: [...copy.riskZones],
        trainingOpportunities: [...copy.trainingOpportunities],
        resourceBrief: copy.resourceBrief,
        firstLookSummary: {
          folderRole: "existing_engineering",
          projectTypeGuess: "desktop_app",
          confidence: 0.94,
          whyThisGuess: copy.whyThisGuess,
          entryPoints: ["extension/src/extension.ts", "server/app/main.py"],
          directoryAnchors: ["extension/", "server/", "shared/"],
          coreModulesOrMaterials: ["WorkbenchSidebarController", "TrainerRuntime"],
          riskZones: [...copy.riskZones],
          trainingOpportunities: [...copy.trainingOpportunities],
          unknowns: [...copy.unknowns],
          recommendedNextStep: nextStep,
          classificationMethod: "heuristic",
          classifiedAt: "2026-07-11T08:00:00.000Z",
        },
        updatedAt: "2026-07-11T08:00:00.000Z",
      },
    };
    bootstrap.coachingState = {
      scenario: "onboarding",
      answerMode: "guided",
      learnerSignal: "curious",
      summary: admissionStatus === "managed" ? copy.managedSummary : copy.onboardingSummary,
      nextStep,
      encouragement: "",
      updatedAt: "2026-07-11T08:00:00.000Z",
    };
    return;
  }

  if (scenario === "rich-content") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.streamingState = {
      ...bootstrap.streamingState,
      isStreaming: false,
      streamedContent: "",
      streamMessageId: undefined,
      agentActivity: [],
      agentStep: 0,
    };
    bootstrap.conversation = [
      {
        id: "preview-rich-content-1",
        role: "assistant",
        author: "Trainer",
        body: previewText(
          language,
          [
            "先把这段内容当成一个统一教学回合来看：同一条回复里可以同时讲代码、数学、流程和知识结构。",
            "",
            "```ts",
            "type RetryPolicy = {",
            "  maxAttempts: number;",
            "  backoffMs: number;",
            "};",
            "",
            "export async function fetchLesson(",
            "  lessonId: string,",
            "  policy: RetryPolicy,",
            "): Promise<Response> {",
            "  return request(`/api/lessons/${lessonId}`, policy);",
            "}",
            "```",
            "",
            "如果把一次 debug 的成本写成期望值，可以先看内联公式 `E = p * c_retry + (1 - p) * c_success`。",
            "",
            "$$",
            "T_{learn} = T_{observe} + T_{hypothesis} + T_{verify}",
            "$$",
            "",
            "| Phase | Goal | Verify |",
            "| --- | --- | --- |",
            "| Learn | 先理解对象和约束 | 能复述 contract 与边界 |",
            "| Try | 动手改一小步 | 改动只落在当前 slice |",
            "| Verify | 用证据确认结果 | 测试、输出或现象成立 |",
            "| Reflect | 回收原理 | 能解释为什么这样改 |",
            "",
            "```mermaid",
            "flowchart LR",
            "  Learn[Learn] --> Try[Try]",
            "  Try --> Verify[Verify]",
            "  Verify --> Reflect[Reflect]",
            "  Reflect --> Return[Return]",
            "```",
            "",
            "这也是 Trainer 之后扩到数学、英语、语文和书籍资料时的同一条原则：先讲清楚，再验证。",
          ].join("\n"),
          [
            "Treat this as one unified teaching turn: the same reply can explain code, math, process, and knowledge structure together.",
            "",
            "```ts",
            "type RetryPolicy = {",
            "  maxAttempts: number;",
            "  backoffMs: number;",
            "};",
            "",
            "export async function fetchLesson(",
            "  lessonId: string,",
            "  policy: RetryPolicy,",
            "): Promise<Response> {",
            "  return request(`/api/lessons/${lessonId}`, policy);",
            "}",
            "```",
            "",
            "For a debug cost model, start with the inline formula `E = p * c_retry + (1 - p) * c_success`.",
            "",
            "$$",
            "T_{learn} = T_{observe} + T_{hypothesis} + T_{verify}",
            "$$",
            "",
            "| Phase | Goal | Verify |",
            "| --- | --- | --- |",
            "| Learn | Understand the object and constraints first | Restate the contract and boundary |",
            "| Try | Change one small slice | Keep the edit inside the current slice |",
            "| Verify | Confirm with evidence | Tests, output, or observed behavior pass |",
            "| Reflect | Recover the principle | Explain why this change works |",
            "",
            "```mermaid",
            "flowchart LR",
            "  Learn[Learn] --> Try[Try]",
            "  Try --> Verify[Verify]",
            "  Verify --> Reflect[Reflect]",
            "  Reflect --> Return[Return]",
            "```",
            "",
            "This is the same rule Trainer will use later for math, literature, English, and book-based teaching: explain first, then verify.",
          ].join("\n"),
        ),
        timestamp: "18:26",
      },
    ];
    bootstrap.suggestedActions = [
      {
        id: "suggest-rich-content-1",
        label: previewText(language, "继续这个教学回合", "Continue this lesson turn"),
        action: "task",
        prompt: previewText(
          language,
          "继续按这个结构讲下去：先解释代码，再给一个小练习，最后告诉我怎么验证。",
          "Continue with this structure: explain the code, give one small exercise, then tell me how to verify it.",
        ),
        focusArea: previewText(language, "统一教学回合", "Unified teaching turn"),
        rationale: previewText(
          language,
          "验证 Coach 的回复是否已经能自然承载多种教学材料。",
          "Check whether Coach replies can now carry multiple teaching materials naturally.",
        ),
      },
    ];
    bootstrap.coachingState = {
      scenario: "principle",
      answerMode: "guided",
      learnerSignal: "curious",
      summary: previewText(
        language,
        "\u8fd9\u4e2a\u573a\u666f\u7528\u6765\u9a8c\u8bc1\uff1aCoach \u80fd\u4e0d\u80fd\u5728\u540c\u4e00\u6761\u56de\u590d\u91cc\u540c\u65f6\u6559\u4ee3\u7801\u3001\u6570\u5b66\u3001\u56fe\u89e3\u548c\u7ed3\u6784\u5316\u77e5\u8bc6\u3002",
        "This scenario verifies that Coach can teach code, math, diagrams, and structured knowledge in the same reply.",
      ),
      nextStep: previewText(
        language,
        "\u7ee7\u7eed\u7528\u201c\u5148\u8bb2\u6e05\u695a\uff0c\u518d\u5c0f\u6b65\u5c1d\u8bd5\uff0c\u7136\u540e\u9a8c\u8bc1\u201d\u7684\u8282\u594f\u63a8\u8fdb\u3002",
        "Continue with an explain first, try one small move, then verify rhythm.",
      ),
      encouragement: previewText(
        language,
        "\u8fd9\u91cc\u9a8c\u8bc1\u7684\u4e0d\u662f\u201c\u53ea\u4f1a\u8bb2\u4ee3\u7801\u201d\uff0c\u800c\u662f\u7edf\u4e00\u6559\u7ec3\u80fd\u5426\u628a\u4e0d\u540c\u6559\u5b66\u5bf9\u8c61\u653e\u5728\u540c\u4e00\u4e2a\u4f4e\u7406\u89e3\u6210\u672c\u7684\u56de\u5408\u91cc\u3002",
        "This checks whether the unified coach can carry different teaching objects in one low-friction turn, not whether it can only explain code.",
      ),
      updatedAt: "2026-07-08T18:26:00.000Z",
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "general",
      learnerSignal: "curious",
      summary: previewText(
        language,
        "\u76ee\u6807\u662f\u8ba9\u4e00\u6761 Coach \u56de\u590d\u5c31\u80fd\u81ea\u7136\u627f\u8f7d\u4ee3\u7801\u3001\u516c\u5f0f\u3001\u8868\u683c\u548c\u6d41\u7a0b\u56fe\u3002",
        "The goal is for one Coach reply to naturally carry code, formulas, tables, and flowcharts.",
      ),
      nextStep: previewText(
        language,
        "\u5148\u4fdd\u6301\u5c42\u7ea7\u5b89\u9759\u548c\u5c3a\u5bf8\u7a33\u5b9a\uff0c\u518d\u770b\u8fd9\u4e9b\u6559\u5b66\u6750\u6599\u80fd\u4e0d\u80fd\u4e00\u8d77\u8bfb\u5f97\u6e05\u695a\u3002",
        "Keep the hierarchy calm and the sizing stable, then verify that these teaching materials still read clearly together.",
      ),
      encouragement: previewText(
        language,
        "\u540c\u4e00\u5957 Learn -> Try -> Verify -> Reflect \u8282\u594f\uff0c\u5e94\u8be5\u80fd\u6559\u4ee3\u7801\uff0c\u4e5f\u80fd\u6559\u6570\u5b66\u3001\u8bed\u8a00\u548c\u4e66\u7c4d\u6750\u6599\u3002",
        "The same Learn -> Try -> Verify -> Reflect rhythm should teach code, math, language, and book-based study.",
      ),
      activeStage: previewText(language, "\u7edf\u4e00\u6559\u5b66\u56de\u5408", "Unified teaching turn"),
      activeTask: previewText(
        language,
        "\u9a8c\u8bc1\u4e00\u6761\u56de\u590d\u80fd\u5426\u540c\u65f6\u627f\u8f7d\u591a\u79cd\u6559\u5b66\u5a92\u4ecb",
        "Verify that one reply can carry multiple teaching media together",
      ),
      reviewQueueSummary: previewText(
        language,
        "\u8fd9\u4e00\u8f6e\u5148\u770b\u663e\u793a\u5bc6\u5ea6\u548c\u53ef\u8bfb\u6027\uff0c\u518d\u51b3\u5b9a\u8981\u4e0d\u8981\u6269\u5927\u6559\u5b66\u9762\u3002",
        "Check density and readability first, then decide whether to widen the teaching surface.",
      ),
      backgroundMode: "embedded",
    };
    bootstrap.coachFocus = {
      ...bootstrap.coachFocus,
      currentFocus: previewText(language, "\u7edf\u4e00\u6559\u5b66\u56de\u5408", "Unified teaching turn"),
      nextStep: previewText(
        language,
        "\u7ee7\u7eed\u6d4b\u4e00\u4e2a\u5c0f\u7ec3\u4e60\uff1a\u5148\u89e3\u91ca\u5bf9\u8c61\uff0c\u518d\u8ba9\u5b66\u4e60\u8005\u5c1d\u8bd5\u4e00\u6b65\uff0c\u6700\u540e\u7ed9\u51fa\u9a8c\u8bc1\u65b9\u5f0f\u3002",
        "Continue with one small exercise: explain the object, let the learner try one move, then give the verification step.",
      ),
      strategyPreferenceSummary: previewText(
        language,
        "\u4e00\u6761\u597d\u7684\u56de\u590d\u53ef\u4ee5\u5bb9\u7eb3\u591a\u79cd\u6559\u5b66\u6750\u6599\uff0c\u4f46\u9996\u5c4f\u5c42\u7ea7\u5fc5\u987b\u59cb\u7ec8\u7a33\u5b9a\u3002",
        "A strong reply can hold multiple teaching materials, but the first-viewport hierarchy must stay stable.",
      ),
      continuitySummary: previewText(
        language,
        "\u89e3\u91ca -> \u5c1d\u8bd5 -> \u9a8c\u8bc1 -> \u56de\u6d41",
        "Explain -> try -> verify -> return",
      ),
    };
    return;
  }

  if (scenario === "blocked") {
    bootstrap.connection = {
      state: "offline",
      provider: {
        name: previewProviderLabel(language, "browser"),
        model: "",
        capabilities: {
          chat: false,
          responses: false,
          vision: false,
          embeddings: false,
          tools: false,
          jsonSchema: false,
          structuredOutput: false,
          streaming: false,
        },
      },
    };
    bootstrap.providerConfig = {
      ...bootstrap.providerConfig,
      configured: false,
      name: "",
      baseUrl: "",
      model: "",
      apiKeyConfigured: false,
      availableModels: [],
      resolvedModel: undefined,
      modelListStatus: "idle",
      modelListDetail: undefined,
      cacheFetchedAt: undefined,
      cacheExpiresAt: undefined,
      cacheSource: undefined,
      modelErrorCategory: undefined,
      modelStatusCode: undefined,
      modelRetryable: undefined,
      lastTestResult: undefined,
      profileId: undefined,
      profileLabel: undefined,
      profileMode: undefined,
      profileCount: 0,
      profileHistory: [],
      providerProfiles: [],
      providerDashboard: undefined,
    };
    bootstrap.coachingState = {
      scenario: "onboarding",
      answerMode: "guided",
      learnerSignal: "blocked",
      summary: previewText(
        language,
        "现在还不能开始。先在“设置”完成模型连接。",
        "We cannot start yet. Finish the model connection in Settings first.",
      ),
      nextStep: previewText(
        language,
        "在“设置”完成连接后再试。",
        "Finish the connection in Settings, then try again.",
      ),
      encouragement: previewText(
        language,
        "完成连接后，就可以继续。",
        "Once the connection is ready, you can continue.",
      ),
      updatedAt: "2026-06-21T09:00:00.000Z",
    };
    bootstrap.coachTurn = {
      scenario: "onboarding",
      learnerSignal: "blocked",
      summary: previewText(
        language,
        "当前最重要的是先完成连接，不要把教练面板理解成空壳。",
        "The key move now is to finish setup, not treat the coach as an empty shell.",
      ),
      nextStep: previewText(
        language,
        "完成模型连接后再回来，我们就能开始。",
        "Finish the model connection, then come back and we can start.",
      ),
      encouragement: previewText(language, "先把底座补稳，体验才会真正成立。", "Stabilize the base first, and the experience will feel real."),
      activeStage: previewText(language, "先连接模型", "Connect the model first"),
      activeTask: previewText(language, "完成模型连接", "Finish the model connection"),
      dueReviewCount: 0,
      reviewQueueSummary: previewText(language, "暂时没有可继续推进的训练轮次。", "There is nothing meaningful to continue yet."),
      artifactKinds: [],
      suggestedActionTypes: ["task"],
      backgroundMode: "embedded",
    };
    bootstrap.conversation = [
      {
        id: "preview-blocked-1",
        role: "assistant",
        author: "Trainer",
        body: previewText(
          language,
          "我现在还不能开始。先在“设置”完成模型连接，我们再继续。",
          "I cannot start yet. Finish the model connection in Settings, then come back.",
        ),
        timestamp: "09:02",
      },
      {
        id: "preview-blocked-2",
        role: "user",
        author: previewText(language, "你先告诉我该点哪里", "Tell me where to click first"),
        body: previewText(
          language,
          "我想先把 Trainer 变得能用，再去看训练和计划。",
          "I want Trainer to become usable first, then I will inspect training and plan.",
        ),
        timestamp: "09:03",
      },
    ];
    bootstrap.suggestedActions = [];
    bootstrap.streamingState = {
      ...bootstrap.streamingState,
      isStreaming: false,
      streamedContent: "",
      streamMessageId: undefined,
      agentActivity: [],
      agentStep: 0,
    };
    return;
  }

  if (scenario === "stream") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.streamingState = {
      isStreaming: true,
      streamedContent: previewText(
        language,
        "我先检查当前工作区上下文，再把下一步压缩成一个清楚的动作。",
        "I am checking the current workspace context and compressing the next step into one clear move.",
      ),
      streamMessageId: "browser-preview-stream",
      agentActivity: [
        {
          id: "preview-tool-1",
          name: "search_resources",
          status: "running",
          args: { query: previewText(language, "当前工作区上下文", "current workspace context") },
          step: 1,
        },
        {
          id: "preview-tool-2",
          name: "align_plan",
          status: "succeeded",
          result: previewText(language, "计划已对齐到当前线程。", "The plan is aligned with the current thread."),
          step: 2,
        },
        {
          id: "preview-tool-3",
          name: "generate_cards",
          status: "failed",
          result: previewText(language, "没有生成新的训练卡。", "No new training card was generated."),
          step: 3,
        },
      ],
      agentStep: 3,
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "curious",
      summary: previewText(
        language,
        "当前消息会先带着工具活动出现，再收束成一条可执行的下一步。",
        "The current message surfaces tool activity first, then narrows into one executable next step.",
      ),
      nextStep: previewText(
        language,
        "先把当前切片收紧，再决定要不要继续扩展。",
        "Tighten the current slice before deciding whether to widen scope.",
      ),
      tone: "reflective",
      verbosityBias: "medium",
      backgroundMode: "embedded",
    };
    bootstrap.suggestedActions = [];
    return;
  }

  if (scenario === "recovery") {
    const recovery = recoveryPreviewCopy[language];
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.coachingState = {
      scenario: "project_adaptation",
      answerMode: "guided",
      learnerSignal: "blocked",
      summary: previewText(
        language,
        "这轮先把阻塞点说清楚，再让 Trainer 帮你回到主线。",
        "This turn first names the blocker, then brings Trainer back to the main line.",
      ),
      nextStep: previewText(
        language,
        "先确认为什么失败，再决定是修复、回退还是继续。",
        "Confirm why it failed first, then decide whether to fix, roll back, or continue.",
      ),
      encouragement: previewText(
        language,
        "恢复不是重做一切，而是把真正的卡点收束起来。",
        "Recovery is not a full redo; it is about narrowing the real blocker.",
      ),
      updatedAt: "2026-06-21T09:05:00.000Z",
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "blocked",
      summary: previewText(
        language,
        "当前回合更像一次恢复：先定位阻塞，再继续主线。",
        "This turn is a recovery pass: locate the blocker first, then resume the main line.",
      ),
      nextStep: previewText(
        language,
        "先恢复教练节奏，再决定下一张卡。",
        "Restore the coach rhythm first, then choose the next card.",
      ),
      encouragement: previewText(language, "先救回节奏，再谈扩展。", "Recover the rhythm first, then expand."),
      activeStage: previewText(language, "恢复当前主线", "Recover the current main line"),
      activeTask: previewText(language, "找出阻塞并收束下一步", "Find the blocker and narrow the next step"),
      dueReviewCount: 1,
      reviewQueueSummary: previewText(language, "有 1 个关键判断需要在恢复后回看。", "One key judgment needs a review after recovery."),
      artifactKinds: ["review", "next_step"],
      suggestedActionTypes: ["review", "task"],
      backgroundMode: "embedded",
    };
    bootstrap.streamingState = {
      isStreaming: true,
      streamedContent: previewText(
        language,
        "我先确认阻塞原因，再把下一步压缩到一个可验证的恢复动作。",
        "I am confirming the blocker first, then compressing the next step into one verifiable recovery move.",
      ),
      streamMessageId: "browser-preview-recovery",
      agentActivity: [
        {
          id: "recovery-tool-1",
          name: "read_workspace_file",
          status: "succeeded",
          result: previewText(language, "已读到当前文件上下文。", "Current file context is loaded."),
          step: 1,
        },
        {
          id: "recovery-tool-2",
          name: "run_diagnostics",
          status: "failed",
          result: previewText(language, "连接还没有完成。", "The connection is not set up yet."),
          step: 2,
        },
        {
          id: "recovery-tool-3",
          name: "align_plan",
          status: "succeeded",
          result: previewText(language, "恢复动作已收束到设置页。", "The recovery move has been narrowed to Settings."),
          step: 3,
        },
      ],
      agentStep: 3,
    };
    bootstrap.conversation = [
      {
        id: "preview-recovery-1",
        role: "assistant",
        author: "Trainer",
        body: previewText(
          language,
          "我先把阻塞点收紧：先确认连接可以使用，再继续。",
          "I am narrowing the blocker first: confirm the connection works, then continue.",
        ),
        timestamp: "09:08",
        artifacts: [
          {
            kind: "review",
            title: previewText(language, "先恢复主线，再继续训练", "Restore the main line, then continue training"),
            summary: previewText(
              language,
              "把失败原因、恢复动作和下一步放在同一条线里，用户才会知道该做什么。",
              "Put the failure reason, recovery move, and next step on the same line so the user knows what to do.",
            ),
            focusArea: previewText(language, "恢复节奏", "Recovery rhythm"),
            verification: [previewText(language, "确认连接已完成", "Confirm the connection is ready")],
            recommendedAction: "review",
          },
        ],
      },
      {
        id: "preview-recovery-2",
        role: "user",
        author: previewText(language, "我想先把卡住的地方修掉", "I want to fix the blocker first"),
        body: previewText(
          language,
          "先别扩展更多入口，先把当前卡住的位置变清楚。",
          "Do not expand more entry points yet; make the current blockage clear first.",
        ),
        timestamp: "09:09",
      },
    ];
    // Keep the recovery state internally coherent: transport can be reachable
    // while coaching remains blocked until the saved API key is restored.
    bootstrap.providerConfig = {
      ...bootstrap.providerConfig,
      apiKeyConfigured: false,
      lastTestResult: undefined,
    };
    bootstrap.coachingState = {
      ...bootstrap.coachingState,
      summary: recovery.summary,
      nextStep: recovery.nextStep,
      encouragement: recovery.nextStep,
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "blocked",
      summary: recovery.summary,
      nextStep: recovery.nextStep,
      encouragement: recovery.nextStep,
      activeStage: recovery.focus,
      activeTask: recovery.nextStep,
      dueReviewCount: 0,
      reviewQueueSummary: recovery.verify,
    };
    bootstrap.coachFocus = {
      ...bootstrap.coachFocus,
      currentFocus: recovery.focus,
      nextStep: recovery.nextStep,
      activeStage: recovery.focus,
      activeTask: recovery.nextStep,
      reviewRhythm: recovery.verify,
    };
    bootstrap.memory = {
      ...bootstrap.memory,
      currentFocus: recovery.focus,
      reviewSummary: recovery.verify,
      activeThread: bootstrap.memory.activeThread
        ? {
            ...bootstrap.memory.activeThread,
            focusArea: recovery.focus,
            summary: recovery.summary,
            nextStep: recovery.nextStep,
            blocker: recovery.blocker,
          }
        : bootstrap.memory.activeThread,
    };
    bootstrap.plan = {
      ...bootstrap.plan,
      title: recovery.focus,
      summary: recovery.summary,
      stages: bootstrap.plan.stages.map((stage, index) =>
        index === 0
          ? {
              ...stage,
              title: recovery.focus,
              objective: recovery.nextStep,
            }
          : stage,
      ),
    };
    if (bootstrap.planRuntimeStatus) {
      bootstrap.planRuntimeStatus = {
        ...bootstrap.planRuntimeStatus,
        currentStage: {
          ...bootstrap.planRuntimeStatus.currentStage,
          title: recovery.focus,
          goal: recovery.whyNow,
        },
        currentMainThread: {
          ...bootstrap.planRuntimeStatus.currentMainThread,
          focusArea: recovery.focus,
          summary: recovery.summary,
          nextStep: recovery.nextStep,
          currentStep: recovery.nextStep,
          whyNow: recovery.whyNow,
          verifyMethod: [recovery.verify],
          blocker: recovery.blocker,
          blockedReason: recovery.blocker,
          nextAfterCurrent: recovery.nextStep,
        },
        coachJudgment: {
          ...bootstrap.planRuntimeStatus.coachJudgment,
          summary: recovery.summary,
          teachingGoal: recovery.whyNow,
          supportStrategy: recovery.nextStep,
          resumeThread: recovery.nextStep,
        },
        nextTrainingAction: recovery.nextStep,
        reviewQueueSummary: recovery.verify,
        currentStep: recovery.nextStep,
        whyNow: recovery.whyNow,
        verifyMethod: [recovery.verify],
        blockedReason: recovery.blocker,
        nextAfterCurrent: recovery.nextStep,
      };
    }
    bootstrap.streamingState = {
      ...bootstrap.streamingState,
      isStreaming: false,
      streamedContent: "",
      streamMessageId: undefined,
      agentActivity: [],
      agentStep: 0,
    };
    bootstrap.conversation = [
      {
        id: "preview-recovery-1",
        role: "assistant",
        author: "Trainer",
        body: recovery.summary,
        timestamp: "09:08",
        artifacts: [
          {
            kind: "review",
            title: recovery.artifactTitle,
            summary: recovery.nextStep,
            focusArea: recovery.focus,
            verification: [recovery.verify],
            recommendedAction: "review",
          },
        ],
      },
    ];
    bootstrap.suggestedActions = [];
    return;
  }

  if (scenario === "ready" || scenario === "vision-ready") {
    const checkedAt = new Date().toISOString();
    if (scenario === "ready") {
      bootstrap.resources = [
        ...(bootstrap.resources ?? []),
        {
          id: "preview-project-refactor-notes",
          title: previewText(language, "\u9879\u76ee\u6539\u9020\u7b14\u8bb0", "Project refactor notes"),
          kind: "markdown",
          status: "ready",
          summary: previewText(
            language,
            "\u5f52\u7eb3\u9879\u76ee\u6539\u9020\u8fc7\u7a0b\u4e2d\u7684\u8bc1\u636e\u548c\u4e0b\u4e00\u6b65\u3002",
            "A concise record of the refactor evidence and next step.",
          ),
        },
      ];
    }
    bootstrap.connection = {
      ...bootstrap.connection,
      state: "connected",
      provider: {
        ...bootstrap.connection.provider,
        name: previewProviderLabel(language, "local"),
        model: "gpt-4.1-mini-compatible",
        protocol: "openai_chat_completions_compatible",
        protocolFamily: "openai",
        capabilities: {
          chat: true,
          responses: true,
          vision: true,
          embeddings: false,
          tools: scenario === "vision-ready",
          jsonSchema: false,
          structuredOutput: false,
          streaming: true,
        },
      },
    };
    bootstrap.providerConfig = {
      ...bootstrap.providerConfig,
      configured: true,
      name: previewProviderLabel(language, "local"),
      baseUrl: "http://localhost:1234/v1",
      model: "gpt-4.1-mini-compatible",
      protocol: "openai_chat_completions_compatible",
      protocolFamily: "openai",
      capabilities: {
        ...bootstrap.providerConfig.capabilities,
        vision: true,
        tools: scenario === "vision-ready",
      },
      apiKeyConfigured: true,
      availableModels: ["gpt-4.1-mini-compatible", "gpt-4.1", "gpt-4o-mini"],
      resolvedModel: "gpt-4.1-mini-compatible",
      modelListStatus: "ready",
      modelListDetail: previewText(language, "模型列表已准备好。", "Model list is ready."),
      cacheFetchedAt: "2026-06-21T08:45:00.000Z",
      cacheExpiresAt: "2026-06-22T08:45:00.000Z",
      cacheSource: "live",
      modelErrorCategory: undefined,
      modelStatusCode: undefined,
      modelRetryable: undefined,
      lastTestResult: stampPreviewLastTest(bootstrap, {
        ok: true,
        status: "ok",
        detail: previewText(language, "连接、模型和 API key 都可用。", "Connection, model, and API key are all usable."),
        checkedAt,
        providerName: previewProviderLabel(language, "local"),
        baseUrl: "http://localhost:1234/v1",
        model: "gpt-4.1-mini-compatible",
        protocol: "openai_chat_completions_compatible" as const,
        protocolFamily: "openai",
        profileId: bootstrap.providerConfig.profileId,
        responseLanguage: language,
        capabilityEvidence: [
          { name: "streaming", declared: true, observed: true, state: "verified" as const },
          ...(scenario === "vision-ready"
            ? [
                { name: "vision", declared: true, observed: true, state: "verified" as const },
                { name: "tools", declared: true, observed: true, state: "verified" as const },
              ]
            : []),
        ],
        streamingReady: true,
        streamProbeStatus: "verified" as const,
        visionReady: scenario === "vision-ready",
        visionProbeStatus: scenario === "vision-ready" ? ("verified" as const) : ("unverified" as const),
        toolsReady: scenario === "vision-ready",
        toolProbeStatus: scenario === "vision-ready" ? ("verified" as const) : ("unverified" as const),
      }),
    };
    bootstrap.profile = {
      ...bootstrap.profile,
      learnerName: previewText(language, "你", "You"),
      targetProject: previewText(
        language,
        "把当前 Trainer 做成长期代码教练插件",
        "Turn Trainer into a long-lived unified learning coach extension",
      ),
      preferredRhythm: previewText(
        language,
        "一次推进一个很小、可验证的改动切片",
        "Move one small verifiable slice at a time",
      ),
      preferredLearningMode: previewText(
        language,
        "先讨论思路，再一起把代码落到文件里",
        "Discuss the approach first, then land it in code together",
      ),
      onboardingRequest: previewText(
        language,
        "先把侧栏体验、连续记忆和计划理解成本压下来",
        "Lower sidebar friction, continuity gaps, and plan-reading cost first",
      ),
      projectContext: previewText(
        language,
        "当前项目是 VS Code Trainer 插件，前端是 React webview，后端是 FastAPI sidecar。",
        "This project is a VS Code Trainer extension with a React webview and FastAPI sidecar.",
      ),
    };
    bootstrap.coachingState = {
      scenario: "project_adaptation",
      answerMode: "guided",
      learnerSignal: "curious",
      summary: previewText(
        language,
        "设置页现在展示的是可用状态，不再像后端表单。",
        "The settings view now shows a usable state, not a backend form.",
      ),
      nextStep: previewText(
        language,
        "你可以直接回到 Coach 继续对话、计划和训练。",
        "You can jump back to Coach and continue with conversation, planning, and training.",
      ),
      encouragement: previewText(language, "连接已就绪，后面的界面会更像真实教练。", "The connection is ready, so the rest of the UI can feel like a real coach."),
      updatedAt: "2026-06-21T08:55:00.000Z",
    };
    applyLocalizedConnectedPlanPreview(bootstrap, language);
    return;
  }

  if (scenario === "provider-failure" || scenario === "provider-failure-empty") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.connection = {
      ...bootstrap.connection,
      state: "connected",
      provider: {
        ...bootstrap.connection.provider,
        name: previewProviderLabel(language, "preview"),
        model: "demo-model",
        protocol: "openai_chat_completions_compatible",
        protocolFamily: "openai",
      },
    };
    bootstrap.providerConfig = {
      ...bootstrap.providerConfig,
      configured: true,
      name: previewProviderLabel(language, "preview"),
      baseUrl: "http://localhost:1234/v1",
      model: "demo-model",
      protocol: "openai_chat_completions_compatible",
      protocolFamily: "openai",
      apiKeyConfigured: true,
      availableModels: [],
      resolvedModel: undefined,
      modelListStatus: "error",
      modelListDetail: previewText(
        language,
        "当前没有可用模型。请在“设置”换一个模型后重试。",
        "No model is available right now. Choose another one in Settings and try again.",
      ),
      cacheFetchedAt: "2026-06-21T08:45:00.000Z",
      cacheExpiresAt: "2026-06-22T08:45:00.000Z",
      cacheSource: "live",
      modelErrorCategory: "model_not_found",
      modelStatusCode: 503,
      modelRetryable: false,
      lastTestResult: {
        ok: false,
        status: "model_not_found",
        detail: previewText(
          language,
          "连接已保存，但当前模型暂时不能用。请换一个模型后重新测试。",
          "The connection is saved, but this model cannot be used right now. Choose another model and test again.",
        ),
        checkedAt: "2026-06-21T08:52:00.000Z",
        providerName: previewProviderLabel(language, "preview"),
        baseUrl: "http://localhost:1234/v1",
        model: "demo-model",
        protocol: "openai_chat_completions_compatible",
        protocolFamily: "openai",
        errorCategory: "model_not_found",
        retryable: false,
        statusCode: 503,
      },
    };
    bootstrap.coachingState = {
      scenario: "project_adaptation",
      answerMode: "guided",
      learnerSignal: "blocked",
      summary: previewText(
        language,
        "当前模型暂时不能用。",
        "The selected model cannot be used right now.",
      ),
      nextStep: previewText(
        language,
        "在“设置”中换一个模型，然后重新测试连接。",
        "Choose another model in Settings, then test the connection again.",
      ),
      encouragement: previewText(
        language,
        "连接已经保存，下一步换一个模型即可。",
        "The connection is saved; choose another model to continue.",
      ),
      updatedAt: "2026-06-21T08:53:00.000Z",
    };
    bootstrap.conversation =
      scenario === "provider-failure-empty"
        ? []
        : [
            {
              id: "preview-provider-failure-1",
              role: "assistant",
              author: "Trainer",
              body: previewText(
                language,
                "当前模型暂时不能用。请先在“设置”换一个模型，再回来继续。",
                "The selected model cannot be used right now. Choose another model in Settings, then come back to continue.",
              ),
              timestamp: "08:54",
            },
            {
              id: "preview-provider-failure-2",
              role: "user",
              author: previewText(language, "我先修复连接", "I will fix the connection first"),
              body: previewText(
                language,
                "首屏明确显示具体失败原因后，恢复起来会更轻松。",
                "It is easier to recover when the exact failure is visible in the first viewport.",
              ),
              timestamp: "08:55",
            },
          ];
    if (scenario === "provider-failure-empty") {
      bootstrap.workspaceTrainingState = undefined;
      bootstrap.memory = {
        ...bootstrap.memory,
        currentFocus: "",
      };
    }
    bootstrap.suggestedActions = [];
    return;
  }

  if (scenario === "provider-auth-failure" || scenario === "provider-auth-failure-empty") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.connection = {
      ...bootstrap.connection,
      state: "connected",
      provider: {
        ...bootstrap.connection.provider,
        name: previewProviderLabel(language, "preview"),
        model: "demo-model",
        protocol: "openai_chat_completions_compatible",
        protocolFamily: "openai",
      },
    };
    bootstrap.providerConfig = {
      ...bootstrap.providerConfig,
      configured: true,
      name: previewProviderLabel(language, "preview"),
      baseUrl: "http://localhost:1234/v1",
      model: "demo-model",
      apiKeyConfigured: true,
      availableModels: [],
      resolvedModel: undefined,
      modelListStatus: "error",
      modelListDetail: previewText(
        language,
        "这组连接暂时不能用。请在“设置”检查密钥后再试。",
        "This connection cannot be used right now. Check the key in Settings, then try again.",
      ),
      cacheFetchedAt: "2026-06-21T09:10:00.000Z",
      cacheExpiresAt: "2026-06-22T09:10:00.000Z",
      cacheSource: "live",
      modelErrorCategory: "invalid_key_or_permission",
      modelStatusCode: 401,
      modelRetryable: false,
      lastTestResult: {
        ok: false,
        status: "authentication_failed",
        detail: previewText(
          language,
          "连接已保存，但密钥暂时不能用。请更新后重新测试。",
          "The connection is saved, but its key cannot be used right now. Update it, then test again.",
        ),
        checkedAt: "2026-06-21T09:12:00.000Z",
        providerName: previewProviderLabel(language, "preview"),
        baseUrl: "http://localhost:1234/v1",
        model: "demo-model",
        errorCategory: "invalid_key_or_permission",
        retryable: false,
        statusCode: 401,
      },
    };
    bootstrap.coachingState = {
      scenario: "project_adaptation",
      answerMode: "guided",
      learnerSignal: "blocked",
      nextStep: previewText(
        language,
        "先检查密钥，确认连接可用后再继续。",
        "Check the key and confirm the connection works before continuing.",
      ),
      summary: previewText(
        language,
        "先在“设置”检查密钥，不要继续发送消息。",
        "Check the key in Settings before sending more messages.",
      ),
      teachingNote: previewText(
        language,
        "这组连接暂时不能用。请在“设置”检查密钥后再试。",
        "This connection cannot be used right now. Check the key in Settings, then try again.",
      ),
      encouragement: previewText(
        language,
        "更新密钥后重新测试即可。",
        "Update the key, then test again.",
      ),
      updatedAt: "2026-06-21T09:13:00.000Z",
    };
    bootstrap.conversation =
      scenario === "provider-auth-failure-empty"
        ? []
        : [
            {
              id: "preview-provider-auth-failure-1",
              role: "assistant",
              author: "Trainer",
              body: previewText(
                language,
                "这组连接暂时不能用。请先在“设置”更新密钥，再回来继续。",
                "This connection cannot be used right now. Update the key in Settings, then come back to continue.",
              ),
              timestamp: "09:13",
            },
          ];
    if (scenario === "provider-auth-failure-empty") {
      bootstrap.workspaceTrainingState = undefined;
      bootstrap.memory = {
        ...bootstrap.memory,
        currentFocus: "",
      };
    }
    bootstrap.suggestedActions = [];
    return;
  }

  if (scenario === "empty") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.resources = [];
    bootstrap.conversation = [];
    bootstrap.suggestedActions = [];
    bootstrap.workspaceTrainingState = undefined;
    bootstrap.memory = {
      ...bootstrap.memory,
      currentFocus: "",
    };
    bootstrap.coachFocus = {
      ...bootstrap.coachFocus,
      currentFocus: previewText(language, "先导入第一批可复用资料", "Import the first reusable materials"),
      reviewRhythm: previewText(language, "先让资源库有一个真正可检索的起点。", "Give the resource library a real searchable starting point first."),
      nextStep: previewText(language, "把一份代码、文档或链接导进来，再看资源视图如何收敛。", "Import one code file, doc, or link, then see how the resource view settles."),
    };
    return;
  }

  if (scenario === "plan-frozen") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.plan = {
      ...bootstrap.plan,
      frozen: true,
    };
    return;
  }

  if (scenario === "plan-blocked") {
    applyConnectedProviderBootstrap(bootstrap, language);
    const blocker = previewText(
      language,
      "\u5f53\u524d\u6587\u4ef6\u7684\u9a8c\u8bc1\u8bc1\u636e\u8fd8\u65e0\u6cd5\u652f\u6491\u8be5\u8ba1\u5212\u6b65\u9aa4\u3002",
      "The current file verification does not yet support this plan step.",
      {
        "es-ES": "La verificación del archivo actual aún no admite este paso del plan.",
        "fr-FR": "La vérification du fichier actuel ne prend pas encore en charge cette étape du plan.",
        "de-DE": "Die Überprüfung der aktuellen Datei unterstützt diesen Planschritt noch nicht.",
        "ja-JP": "現在のファイル検証では、この計画ステップはまだ対応していません。",
        "ko-KR": "현재 파일 검증은 아직 이 계획 단계를 지원하지 않습니다.",
        "pt-BR": "A verificação do arquivo atual ainda não oferece suporte a esta etapa do plano.",
      },
    );
    bootstrap.plan = {
      ...bootstrap.plan,
      frozen: false,
      blockedReason: blocker,
    };
    bootstrap.planRuntimeStatus = bootstrap.planRuntimeStatus
      ? {
          ...bootstrap.planRuntimeStatus,
          blockedReason: blocker,
        }
      : bootstrap.planRuntimeStatus;
    return;
  }

  if (scenario === "resource-preview-loaded") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.resources = [
      {
        id: "preview-notes",
        title: previewText(language, "登录错误码对照", "Coach prompt patterns"),
        kind: "markdown",
        status: "ready",
        summary: previewText(
          language,
          "登录失败时，常见返回码和对应提示。",
          "A reusable guide for turning ideas into verifiable implementation steps.",
        ),
        source: "H:/trainer_final/docs/trainer-ideal/resources/coach/patterns/coach-patterns.md",
        collectionPath: "knowledge/Docs/coach/patterns/coach-patterns.md",
        collectionRoot: "H:/trainer_final/knowledge",
        sandboxPath: "H:/trainer_final/.trainer/sandbox/knowledge/coach/patterns/coach-patterns.md",
        previewTier: "rich",
        previewKind: "markdown",
        trustScore: 0.92,
        freshness: "fresh",
        indexState: "indexed",
      },
      {
        id: "preview-table",
        title: previewText(language, "失败登录检查清单", "Training verification matrix"),
        kind: "text",
        status: "ready",
        summary: previewText(
          language,
          "改完后用错的账号登一次，看提示对不对。",
          "The evidence each practice, flash, and review card needs.",
        ),
        source: "H:/trainer_final/docs/trainer-ideal/resources/training/evidence/training-matrix.csv",
        collectionPath: "knowledge/docs/training/evidence/training-matrix.csv",
        collectionRoot: "H:/trainer_final/knowledge",
        sandboxPath: "H:/trainer_final/.trainer/sandbox/knowledge/training/evidence/training-matrix.csv",
        previewTier: "rich",
        previewKind: "table",
        trustScore: 0.88,
        freshness: "fresh",
        indexState: "indexed",
      },
      {
        id: "preview-brief",
        title: previewText(language, "当前文件错误处理笔记", "Project refactor brief"),
        kind: "pdf",
        status: "indexing",
        summary: previewText(
          language,
          "当前文件里登录失败分支的改动记录。",
          "A brief about reshaping an existing codebase around the product intent.",
        ),
        source: "H:/trainer_final/docs/trainer-ideal/projects/refactor/briefs/refactor-brief.pdf",
        collectionPath: "projects/Refactor/briefs/refactor-brief.pdf",
        collectionRoot: "H:/trainer_final/projects",
        sandboxPath: "H:/trainer_final/.trainer/sandbox/projects/refactor/briefs/refactor-brief.pdf",
        previewTier: "converted",
        previewKind: "document",
        trustScore: 0.81,
        freshness: "unknown",
        indexState: "indexing",
      },
    ];
    bootstrap.memory = {
      ...bootstrap.memory,
      selectedResourceDetail: {
        ...bootstrap.resources[0],
        sourceItems: ["H:/trainer_final/docs/trainer-ideal/resources/coach/patterns/coach-patterns.md"],
        tags: ["coach", "implementation", "verification"],
        warnings: [],
      },
      sandboxPreview: {
        path: "H:/trainer_final/.trainer/sandbox/knowledge/coach/patterns/coach-patterns.md",
        relativePath: "knowledge/coach/patterns/coach-patterns.md",
        title: previewText(language, "登录错误码对照", "Coach prompt patterns"),
        fileKind: "markdown",
        previewTier: "rich",
        previewKind: "markdown",
        languageHint: "markdown",
        renderedFrom: "raw",
        content: previewText(
          language,
          [
            "# 登录错误码对照",
            "",
            "## 常见失败",
            "",
            "- 401：账号或密码不对",
            "- 403：没有权限",
            "- 429：试得太勤",
            "",
            "改当前文件里的提示时，对着这张表核对。",
          ].join("\n"),
          [
            "# Coach prompt patterns",
            "",
            "## Break the task",
            "",
            "- Identify the real task",
            "  - Then cut a verifiable slice",
            "",
            "### Return",
            "",
            "Write the result back to Training or Plan.",
          ].join("\n"),
        ),
        excerpt: previewText(
          language,
          "登录失败时，提示要和返回码对上。",
          "Identify the real task, then reduce it to a verifiable slice.",
        ),
        isBinary: false,
        isEditable: true,
        canNativeOpen: true,
        structuredData: {
          kind: "document",
          format: "md",
          content: previewText(
            language,
            "先确认用户当前想完成的真实任务，而不是复述功能菜单。",
            "Identify the learner's real task before listing features.",
          ),
          sectionCount: 4,
          truncated: false,
        },
        metadata: {
          size_bytes: 512,
          content_truncated: false,
        },
      },
      sandboxState: {
        rootPath: "H:/trainer_final/.trainer/sandbox",
        sandboxRootPath: "H:/trainer_final/.trainer/sandbox",
        workspaceRootPath: "H:/trainer_final",
        activeWorkspaceRoot: "H:/trainer_final",
        managedRoots: ["knowledge", "projects"],
        ready: true,
        linkedResourceCount: 3,
        totalFiles: 3,
        totalDirectories: 8,
        totalSizeBytes: 6144,
        selectedPath: "H:/trainer_final/.trainer/sandbox/knowledge/coach/patterns/coach-patterns.md",
        authority: {
          activeWorkspaceRoot: "H:/trainer_final",
          rootUri: "file:///H:/trainer_final",
          authoritySource: "workspace_authority_service",
          remoteName: "local",
          authorityMode: "local",
          authorityScope: "trainer_sandbox",
          resourceWriteAllowed: true,
          resourceWriteEvidence: {
            operation: "write",
            scope: "trainer_sandbox",
            targetRoot: "H:/trainer_final/.trainer/sandbox",
            allowed: true,
          },
          permissionLevel: "read_write",
          permissionLabel: "Read / write",
          allowedOperations: ["read", "write", "preview", "refresh"],
        },
        nodes: [
          { path: "H:/trainer_final/.trainer/sandbox/knowledge", relativePath: "knowledge", name: "knowledge", nodeKind: "directory", childrenCount: 2 },
          { path: "H:/trainer_final/.trainer/sandbox/knowledge/coach", relativePath: "knowledge/coach", name: "coach", nodeKind: "directory", childrenCount: 1 },
          { path: "H:/trainer_final/.trainer/sandbox/knowledge/coach/patterns", relativePath: "knowledge/coach/patterns", name: "patterns", nodeKind: "directory", childrenCount: 1 },
          { path: "H:/trainer_final/.trainer/sandbox/knowledge/coach/patterns/coach-patterns.md", relativePath: "knowledge/coach/patterns/coach-patterns.md", name: "coach-patterns.md", nodeKind: "file", fileKind: "markdown", childrenCount: 0 },
          { path: "H:/trainer_final/.trainer/sandbox/knowledge/training", relativePath: "knowledge/training", name: "training", nodeKind: "directory", childrenCount: 1 },
          { path: "H:/trainer_final/.trainer/sandbox/knowledge/training/evidence", relativePath: "knowledge/training/evidence", name: "evidence", nodeKind: "directory", childrenCount: 1 },
          { path: "H:/trainer_final/.trainer/sandbox/knowledge/training/evidence/training-matrix.csv", relativePath: "knowledge/training/evidence/training-matrix.csv", name: "training-matrix.csv", nodeKind: "file", fileKind: "text", childrenCount: 0 },
          { path: "H:/trainer_final/.trainer/sandbox/projects", relativePath: "projects", name: "projects", nodeKind: "directory", childrenCount: 1 },
          { path: "H:/trainer_final/.trainer/sandbox/projects/refactor", relativePath: "projects/refactor", name: "refactor", nodeKind: "directory", childrenCount: 1 },
          { path: "H:/trainer_final/.trainer/sandbox/projects/refactor/briefs", relativePath: "projects/refactor/briefs", name: "briefs", nodeKind: "directory", childrenCount: 1 },
          { path: "H:/trainer_final/.trainer/sandbox/projects/refactor/briefs/refactor-brief.pdf", relativePath: "projects/refactor/briefs/refactor-brief.pdf", name: "refactor-brief.pdf", nodeKind: "file", fileKind: "pdf", childrenCount: 0 },
        ],
      },
    };
    bootstrap.coachFocus = {
      ...bootstrap.coachFocus,
      currentFocus: previewText(
        language,
        "资料预览正在显示真实已读取内容。",
        "Resource preview is showing real loaded content.",
      ),
      nextStep: previewText(
        language,
        "在预览里切换资料，确认正文、结构化内容和未读取状态分得清。",
        "Switch resources in Preview and verify loaded, structured, and pending states are distinct.",
      ),
    };
    return;
  }

  if (scenario === "done") {
    applyConnectedProviderBootstrap(bootstrap, language);
    bootstrap.workspaceTrainingState = {
      ...bootstrap.workspaceTrainingState,
      latestLearningVerifiedResult: previewText(
        language,
        "当前训练轮次已经收口，可以把结果带回 Coach。",
        "This training round is closed and the result can go back to Coach.",
      ),
      latestLearningPartialProgress: previewText(language, "剩余内容已经收进回看区。", "The remaining material is folded into the review area."),
      latestLearningFollowup: previewText(language, "把这次结果带回对话，再决定下一张卡。", "Bring this result back to the conversation, then choose the next card."),
      latestLearningBlocker: undefined,
      selectedCardStatus: "implemented",
      latestTrainingHandoff: {
        ...bootstrap.workspaceTrainingState?.latestTrainingHandoff,
        handoffStatus: "fed_back",
        returnMode: "result",
        returnSummary: previewText(language, "结果已回到教练主线。", "The result has returned to the coach main line."),
      },
      latestTrainingNextHop: {
        ...bootstrap.workspaceTrainingState?.latestTrainingNextHop,
        status: "accepted",
        statusReason: previewText(language, "当前卡已完成，下一步留给 Coach 决定。", "The current card is complete; the next step is for Coach to decide."),
      },
      reviewArtifact: {
        ...bootstrap.workspaceTrainingState?.reviewArtifact,
        status: "resolved",
        verifiedResult: previewText(language, "训练结果已经被验证。", "The training result has been verified."),
      },
      theoryDrill: {
        ...bootstrap.workspaceTrainingState?.theoryDrill,
        status: "completed",
      },
      scenarioLab: {
        ...bootstrap.workspaceTrainingState?.scenarioLab,
        status: "done",
      },
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "steady",
      summary: previewText(
        language,
        "这一轮已经完成，界面应该把结果、验证和下一跳都收得很清楚。",
        "This round is done, and the UI should now make the result, verification, and next hop very clear.",
      ),
      nextStep: previewText(
        language,
        "把结果带回 Coach，然后决定是否开新卡。",
        "Bring the result back to Coach, then decide whether to open a new card.",
      ),
      decision: previewText(
        language,
        "继续压缩消息流，同时保留最终决策和回续路径。",
        "Keep compressing the message flow while preserving the final decision and resume path.",
      ),
      teachingNote: previewText(
        language,
        "先让用户一眼看见这轮收束，再展开下一跳。",
        "Make the wrap-up obvious first, then open the next hop.",
      ),
      confidence: "high",
      evidence: [
        "App.tsx",
        "CoachMessageBubble.tsx",
        "styles.css",
      ],
      resumeThread: previewText(
        language,
        "下一轮从当前文件这一段接着改。",
        "Pick up from this error-handling block in the current file.",
      ),
      encouragement: previewText(language, "完成感要明确，但不要把它做成终点页。", "Completion should feel explicit, but not like a dead-end page."),
      backgroundMode: "embedded",
    };
    bootstrap.conversation = [
      {
        id: "preview-done-1",
        role: "assistant",
        author: "Trainer",
        body: previewText(
          language,
          "这轮已经收束。决策、教学提示和回续路径都已经固定下来，下一步只剩把结果带回主线。",
          "This turn is wrapped up. The decision, teaching note, and resume path are locked in; the only next move is to bring the result back to the main line.",
        ),
        timestamp: "09:20",
        parts: [
          {
            type: "coach_visible_status",
            status: "done",
            summary: previewText(
              language,
              "这一轮已经完成，结果、验证和下一跳都已经收束。",
              "This round is done, and the result, verification, and next hop are now wrapped up.",
            ),
            detail: previewText(
              language,
              "教练回合已经收口，可以用更小的切片继续。",
              "The coach loop is closed and ready to resume with a smaller slice.",
            ),
            nextStep: previewText(
              language,
              "把结果带回 Coach，然后决定是否开新卡。",
              "Bring the result back to Coach, then decide whether to open a new card.",
            ),
            resumeThread: previewText(
              language,
              "下一轮从当前文件这一段接着改。",
              "Pick up from this error-handling block in the current file.",
            ),
            stopReason: "coach_finalize",
            source: "agent_loop",
            toolNames: ["search_resources", "align_plan", "coach_finalize"],
            stepCount: 3,
            decision: previewText(
              language,
              "继续压缩消息流，同时保留最终决策和回续路径。",
              "Keep compressing the message flow while preserving the final decision and resume path.",
            ),
            teachingNote: previewText(
              language,
              "先让用户一眼看见这轮收束，再展开下一跳。",
              "Make the wrap-up obvious first, then open the next hop.",
            ),
            confidence: "high",
            evidence: ["App.tsx", "CoachMessageBubble.tsx", "styles.css"],
          },
        ],
        artifacts: [
          {
            kind: "next_step",
            title: previewText(language, "把结果带回 Coach", "Bring the result back to Coach"),
            summary: previewText(
              language,
              "收束后的信息会回到对话，再决定要不要开新卡。",
              "The wrapped-up signal comes back into the conversation, then we decide whether to open a new card.",
            ),
            verification: [
              previewText(
                language,
                "确认 bubble 里能看到 decision、teaching note、confidence 和 evidence。",
                "Confirm the bubble shows decision, teaching note, confidence, and evidence.",
              ),
            ],
            metadata: {
              decision: previewText(
                language,
                "继续压缩消息流，同时保留最终决策和回续路径。",
                "Keep compressing the message flow while preserving the final decision and resume path.",
              ),
              teaching_note: previewText(
                language,
                "先让用户一眼看见这轮收束，再展开下一跳。",
                "Make the wrap-up obvious first, then open the next hop.",
              ),
              confidence: "high",
              evidence: ["App.tsx", "CoachMessageBubble.tsx", "styles.css"],
            },
            recommendedAction: "task",
          },
        ],
      },
      {
        id: "preview-done-2",
        role: "user",
        author: previewText(language, "我看懂了，继续下一步吧", "I get it, keep going"),
        body: previewText(
          language,
          "这个收束方式挺清楚，下一轮就照这个节奏继续。",
          "This wrap-up reads clearly; continue the next round with the same rhythm.",
        ),
        timestamp: "09:21",
      },
    ];
    return;
  }
}

function scenarioOwnsCoachSeed(scenario: BrowserPreviewState["scenario"]): boolean {
  switch (scenario) {
    case "rich-content":
    case "blocked":
    case "recovery":
    case "provider-failure":
    case "provider-failure-empty":
    case "provider-auth-failure":
    case "provider-auth-failure-empty":
    case "empty":
    case "done":
    case "workspace-admission":
      return true;
    default:
      return false;
  }
}

function toPreviewPersistedState(state: BrowserPreviewState): PersistedWorkbenchState {
  return {
    themePreference: state.themePreference,
    learningSurfaceAlignment: state.learningSurfaceAlignment ?? "left",
    activeView: state.activeView,
    composerLanguage: state.composerLanguage,
    composerAnswerMode: state.composerAnswerMode,
    teachingStyle: state.teachingStyle,
    resourceSearchMode: state.resourceSearchMode,
    includeCurrentFile: state.includeCurrentFile,
    includeSelection: state.includeSelection,
    includeDiagnostics: state.includeDiagnostics,
    includeRelatedFiles: state.includeRelatedFiles,
    contextDetail: state.contextDetail,
    followCurrentFile: state.followCurrentFile,
    coachDefaults: state.coachDefaults,
    composerDraft: state.composerDraft,
    previewProviderConfig: stripProviderSnapshotSecrets(state.previewProviderConfig),
  };
}

function configureBrowserPreviewEnvironment(state: BrowserPreviewState): void {
  const previewStorageKey = `trainer:webview:preview:${window.location.search || "default"}`;
  window.__TRAINER_BROWSER_PREVIEW__ = true;
  window.__TRAINER_PREVIEW_STORAGE_KEY__ = previewStorageKey;
  document.body.classList.remove("vscode-light", "vscode-dark");
  document.body.classList.add(`vscode-${state.vscodeTheme ?? "dark"}`);
  window.addEventListener(PREVIEW_WEBVIEW_ACTION_EVENT, (event) => {
    if (typeof window.acquireVsCodeApi === "function") {
      return;
    }
    const action = (event as CustomEvent<unknown>).detail;
    if (!isWebviewAction(action)) {
      return;
    }
    if (action.type === "request/bootstrap") {
      if (isBrowserPreviewFixtureMode()) {
        emitBrowserPreviewHostMessage({
          type: "bootstrap",
          payload: currentBrowserPreviewBootstrap(),
        });
      } else {
        void refreshLiveBrowserPreviewBootstrap();
      }
      return;
    }
    if (
      state.connectionState !== "offline" &&
      action.type === "command/execute" &&
      LIVE_TRAINING_COMMAND_IDS.has(action.payload.commandId)
    ) {
      void runBrowserPreviewLiveTrainingAction(action, state.composerLanguage);
      return;
    }
    if (
      state.connectionState === "offline" &&
      action.type === "command/execute" &&
      LIVE_TRAINING_COMMAND_IDS.has(action.payload.commandId)
    ) {
      runBrowserPreviewWebviewAction(action, state.composerLanguage);
      return;
    }
    if (handleBrowserPreviewStreamCancel(action)) {
      return;
    }
    if (action.type === "session/sendMessage") {
      void sendBrowserPreviewMessage(action.payload)
        .then(({ sessionId, message }) => {
          livePreviewSessionId = sessionId;
          emitBrowserPreviewHostMessage(message);
        })
        .catch((error) => {
          emitBrowserPreviewHostMessage({
            type: "operation/status",
            payload: { tone: "error", message: error instanceof Error ? error.message : String(error) },
          });
        });
      return;
    }
    if (action.type === "session/sendStreamMessage") {
      void streamBrowserPreviewMessage(action.payload, action.payload.sessionId ?? "", {
        onStart: emitBrowserPreviewHostMessage,
        onChunk: emitBrowserPreviewHostMessage,
        onComplete: (message, sessionId) => {
          livePreviewSessionId = sessionId;
          emitBrowserPreviewHostMessage(message);
        },
        onError: emitBrowserPreviewHostMessage,
        onCancelled: emitBrowserPreviewHostMessage,
      });
      return;
    }
    void runBrowserPreviewLiveAction(action, state.composerLanguage);
  });
}

function persistExplicitBrowserPreviewTheme(state: BrowserPreviewState): void {
  const requestedTheme = new URLSearchParams(window.location.search).get("theme");
  if (requestedTheme !== "light" && requestedTheme !== "dark" && requestedTheme !== "system") {
    return;
  }

  const previewStorageKey = `trainer:webview:preview:${window.location.search || "default"}`;
  let persistedState: Record<string, unknown> = {};
  try {
    const raw = window.localStorage.getItem(previewStorageKey);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        persistedState = parsed as Record<string, unknown>;
      }
    }
    window.localStorage.setItem(
      previewStorageKey,
      JSON.stringify({
        ...persistedState,
        themePreference: state.themePreference,
      }),
    );
  } catch {
    // The standalone preview remains usable when browser storage is unavailable.
  }
}

/**
 * Marks the standalone page as a browser preview without injecting a fixture.
 * The application will then request the real Sidecar snapshot.
 */
export function installBrowserPreviewEnvironment(): void {
  const state = resolvePreviewState();
  configureBrowserPreviewEnvironment(state);
  persistExplicitBrowserPreviewTheme(state);
}

export function installBrowserPreviewHarness(): void {
  const state = resolvePreviewState();
  const previewStorageKey = previewStorageKeyForLocation();
  const bootstrap: BrowserPreviewBootstrap = structuredClone(mockBootstrapData);
  configureBrowserPreviewEnvironment(state);
  localizeBrowserPreviewFirstLook(bootstrap, state.composerLanguage);
  const connectionState = state.connectionState ?? "offline";
  const streamingMode = state.streamingMode;
  if (connectionState === "offline") {
    bootstrap.connection = {
      ...bootstrap.connection,
        state: "offline",
        provider: {
          ...bootstrap.connection.provider,
          name: previewProviderLabel(state.composerLanguage, "browser"),
          model: "",
      },
    };
    bootstrap.providerConfig = {
      ...bootstrap.providerConfig,
      configured: false,
      name: "",
      baseUrl: "",
      model: "",
      apiKeyConfigured: false,
      availableModels: [],
      resolvedModel: undefined,
      modelListStatus: "idle",
      modelListDetail: undefined,
      cacheFetchedAt: undefined,
      cacheExpiresAt: undefined,
      cacheSource: undefined,
      modelErrorCategory: undefined,
      modelStatusCode: undefined,
      modelRetryable: undefined,
      lastTestResult: undefined,
      profileId: undefined,
      profileLabel: undefined,
      profileMode: undefined,
      profileCount: 0,
      profileHistory: [],
      providerProfiles: [],
      providerDashboard: undefined,
    };
  } else {
    applyConnectedProviderBootstrap(bootstrap, state.composerLanguage);
    if (state.previewProviderConfig) {
      applyPreviewProviderConfigBootstrap(bootstrap, state.previewProviderConfig);
    }
    bootstrap.connection = {
      ...bootstrap.connection,
      state: connectionState,
    };
  }
  applyPreviewScenario(bootstrap, state);
  const scenarioOwnsPreviewSeed = scenarioOwnsCoachSeed(state.scenario);
  const preserveScenarioCoachSeed = state.activeView === "coach" && scenarioOwnsPreviewSeed;
  if (streamingMode === "demo") {
    bootstrap.streamingState = {
      isStreaming: true,
      streamedContent: previewText(
        state.composerLanguage,
        "我正在检查当前工作区上下文，并将下一步与当前计划对齐。",
        "I am checking the current workspace context and aligning the next step with the current plan.",
      ),
      streamMessageId: "browser-preview-stream",
      agentActivity: [
        {
          id: "preview-tool-1",
          name: "search_resources",
          status: "running",
          args: {
            query: previewText(state.composerLanguage, "当前工作区上下文", "workspace context"),
          },
          step: 1,
        },
        {
          id: "preview-tool-2",
          name: "align_plan",
          status: "succeeded",
          result: previewText(
            state.composerLanguage,
            "计划已与当前主线对齐。",
            "Plan aligned with the current thread.",
          ),
          step: 2,
        },
        {
          id: "preview-tool-3",
          name: "generate_cards",
          status: "failed",
          result: previewText(
            state.composerLanguage,
            "没有生成可继续的训练卡。",
            "No eligible training card was generated.",
          ),
          step: 3,
        },
      ],
      agentStep: 3,
    };
  }
  const language = state.composerLanguage;
  if (!preserveScenarioCoachSeed) {
    bootstrap.conversation =
    state.activeView === "coach"
      ? [
          {
            id: "preview-code-1",
            role: "assistant",
            author: "Trainer",
            body: previewText(
              language,
              "打开当前文件，改登录失败的提示。\n\n用错的账号登一次，看提示对不对。",
              "Open the current file and fix the login error message.\n\nSign in with a wrong account and see if the message matches.",
            ),
            timestamp: "18:12",
          },
        ]
      : [];
    bootstrap.suggestedActions = [];
  }
  if (state.activeView === "coach" && !preserveScenarioCoachSeed) {
    bootstrap.coachingState = {
      ...bootstrap.coachingState,
      scenario: "task",
      answerMode: "guided",
      learnerSignal: "steady",
      summary: previewText(
        language,
        "先改登录失败的提示。",
        "Fix the login error message.",
      ),
      nextStep: previewText(
        language,
        "改完跑一下，看提示对不对。",
        "Fix the login error message.",
      ),
      encouragement: previewText(
        language,
        "做完这一步再往下。",
        "Finish this step before starting the next one.",
      ),
      updatedAt: "2026-06-29T10:00:00.000Z",
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "steady",
      summary: previewText(
        language,
        "先把当前这一步做完。",
        "Finish this step first.",
      ),
      nextStep: previewText(
        language,
        "改登录失败的提示。",
        "Fix the login error message.",
      ),
      encouragement: previewText(
        language,
        "做完这一步再往下。",
        "Finish this step before starting the next one.",
      ),
      activeStage: previewText(language, "改这一处", "Fix this one place"),
      activeTask: previewText(
        language,
        "改登录失败的提示",
        "Fix the login error message",
      ),
      reviewQueueSummary: previewText(
        language,
        "有 2 件事做完后值得再看一遍。",
        "Two things to look at again after this step.",
      ),
    };
    bootstrap.coachFocus = {
      ...bootstrap.coachFocus,
      currentFocus: previewText(language, "登录失败的提示", "the login error message"),
      reviewRhythm: previewText(
        language,
        "改完以后，隔天再看一眼提示跟返回码。",
        "After this place is right, look back at why the message must match the status code.",
      ),
      nextStep: previewText(
        language,
        "改完跑一下，看提示对不对。",
        "Fix the login error message.",
      ),
      activeStage: previewText(language, "改这一处", "Fix this one place"),
      activeTask: previewText(
        language,
        "改登录失败的提示",
        "Fix the login error message",
      ),
      strategyPreferenceSummary: previewText(
        language,
        "先改当前这一处，再开下一件事。",
        "Fix this one place before starting something new.",
      ),
      continuitySummary: previewText(language, "改当前文件 -> 跑失败登录 -> 再补测试", "Fix the file -> try a failed login -> add a test"),
      recentTeachingSignals: previewText(
        language,
        ["先改当前文件这一段，再开下一件事。", "提示必须对上返回码。"],
        ["Fix this one place before starting something new.", "The error message must match the status code."],
      ),
      teachingObservations: previewText(
        language,
        [
          "先圈定当前文件里哪一段，再给下一步，更容易动手。",
          "提示必须对上返回码，否则后面排查会走偏。",
        ],
        [
          "Point to the exact block first, then give the next move.",
          "If the message does not match the status code, later debugging goes sideways.",
        ],
      ),
      recentWins: previewText(
        language,
        ["已经能指出要改当前文件里哪一段"],
        ["You can already point to the block that needs to change."],
      ),
      language,
    };
    if (bootstrap.planRuntimeStatus) {
      bootstrap.planRuntimeStatus = {
        ...bootstrap.planRuntimeStatus,
        currentStage: {
          ...bootstrap.planRuntimeStatus.currentStage,
          title: previewText(language, "改这一处", "Fix this one place"),
          goal: previewText(
            language,
            "先改当前文件里这一段，别同时动别的。",
            "Change only this error-handling block in the current file.",
          ),
        },
        currentMainThread: {
          ...bootstrap.planRuntimeStatus.currentMainThread,
          focusArea: previewText(language, "登录失败的提示", "the login error message"),
          summary: previewText(
            language,
            "先改当前文件里这一段错误处理。",
            "Fix the login error message first.",
          ),
          nextStep: previewText(
            language,
            "改登录失败的提示。",
            "Fix the login error message.",
          ),
          currentStep: previewText(
            language,
            "改登录失败的提示。",
            "Fix the login error message.",
          ),
          whyNow: previewText(
            language,
            "登录失败时提示不对，先改这里。",
            "This error message blocks login. Fix it first.",
          ),
          verifyMethod: previewText(
            language,
            ["用错的账号登一次，看提示对不对。"],
            ["After the change, run it. The error message should match the real response."],
          ),
          nextAfterCurrent: previewText(
            language,
            "对了再补测试。",
            "If this place is right, add a test next.",
          ),
        },
        coachJudgment: {
          ...bootstrap.planRuntimeStatus.coachJudgment,
          summary: previewText(
            language,
            "先把当前这一步做完。",
            "Finish this step first.",
          ),
          teachingGoal: previewText(
            language,
            "把这一步做完，确认能跑。",
            "Finish this step and confirm it runs.",
          ),
          supportStrategy: previewText(
            language,
            "先把这一处改完，再开下一件事。",
            "Finish this place before starting something new.",
          ),
          resumeThread: previewText(
            language,
            "下一轮从当前文件这一段接着改。",
            "Pick up from this error-handling block in the current file.",
          ),
        },
        nextTrainingAction: previewText(
          language,
          "改登录失败的提示。",
          "Fix the login error message.",
        ),
        reviewQueueSummary: previewText(
          language,
          "有 2 件事做完后值得再看一遍。",
          "Two things to look at again after this step.",
        ),
        currentStep: previewText(
          language,
          "改登录失败的提示。",
          "Fix the login error message.",
        ),
        whyNow: previewText(
          language,
          "登录失败时提示不对，先改这里。",
          "This error message blocks login. Fix it first.",
        ),
        verifyMethod: previewText(
          language,
          ["用错的账号登一次，看提示对不对。"],
          ["After the change, run it. The error message should match the real response."],
        ),
        nextAfterCurrent: previewText(
          language,
          "对了再补测试。",
          "If this place is right, add a test next.",
        ),
      };
    }
    bootstrap.reviewQueueSummary = previewText(
      language,
      "有 2 件事做完后值得再看一遍。",
      "Two things to look at again after this step.",
    );
  }
  if (state.activeView === "plan" && state.scenario !== "recovery") {
    bootstrap.plan = {
      ...bootstrap.plan,
      title: previewText(language, "登录错误提示", "Login error message"),
      cadence: previewText(language, "每周 4 次专注编码", "Four focused coding sessions each week"),
      summary: previewText(
        language,
        "先改登录失败的提示，对了再补测试。",
        "Fix the login error message first, then add a test.",
      ),
      stages: bootstrap.plan.stages.map((stage) => {
        if (stage.id === "s1") {
          return {
            ...stage,
            title: previewText(language, "找到会报错的那段", "Find the failing branch"),
            objective: previewText(
              language,
              "先打开当前文件，定位登录失败时走的那段错误处理。",
              "Open the current file and find the error-handling branch used on login failure.",
            ),
          };
        }
        if (stage.id === "s2") {
          return {
            ...stage,
            title: previewText(language, "改这一处", "Fix this one place"),
            objective: previewText(
              language,
              "先改当前文件里这一段，别同时动别的。",
              "Change only this error-handling block in the current file.",
            ),
          };
        }
        if (stage.id === "s3") {
          return {
            ...stage,
            title: previewText(language, "再补一条登录测试", "Add a login test next"),
            objective: previewText(
              language,
              "这一处对了以后，再补一条失败登录的测试。",
              "Once this place is right, add a failing-login test.",
            ),
          };
        }
        return stage;
      }),
    };
    bootstrap.coachingState = {
      ...bootstrap.coachingState,
      scenario: "task",
      answerMode: "guided",
      learnerSignal: "steady",
      summary: previewText(
        language,
        "先改登录失败的提示。",
        "Fix the login error message.",
      ),
      nextStep: previewText(
        language,
        "改完跑一下，看提示对不对。",
        "Fix the login error message.",
      ),
      encouragement: previewText(
        language,
        "做完这一步再往下。",
        "Finish this step before starting the next one.",
      ),
      updatedAt: "2026-06-29T10:00:00.000Z",
    };
    bootstrap.coachTurn = {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "steady",
      summary: previewText(
        language,
        "先把当前这一步做完。",
        "Finish this step first.",
      ),
      nextStep: previewText(
        language,
        "改登录失败的提示。",
        "Fix the login error message.",
      ),
      encouragement: previewText(
        language,
        "做完这一步再往下。",
        "Finish this step before starting the next one.",
      ),
      activeStage: previewText(language, "改这一处", "Fix this one place"),
      activeTask: previewText(
        language,
        "改登录失败的提示",
        "Fix the login error message",
      ),
      reviewQueueSummary: previewText(
        language,
        "有 2 件事做完后值得再看一遍。",
        "Two things to look at again after this step.",
      ),
    };
    bootstrap.coachFocus = {
      ...bootstrap.coachFocus,
      currentFocus: previewText(language, "登录失败的提示", "the login error message"),
      reviewRhythm: previewText(
        language,
        "改完以后，隔天再看一眼提示跟返回码。",
        "After this place is right, look back at why the message must match the status code.",
      ),
      nextStep: previewText(
        language,
        "改完跑一下，看提示对不对。",
        "Fix the login error message.",
      ),
      activeStage: previewText(language, "改这一处", "Fix this one place"),
      activeTask: previewText(
        language,
        "改登录失败的提示",
        "Fix the login error message",
      ),
      strategyPreferenceSummary: previewText(
        language,
        "先改当前这一处，再开下一件事。",
        "Fix this one place before starting something new.",
      ),
      continuitySummary: previewText(language, "改当前文件 -> 跑失败登录 -> 再补测试", "Fix the file -> try a failed login -> add a test"),
      recentTeachingSignals: previewText(
        language,
        ["先改当前文件这一段，再开下一件事。", "提示必须对上返回码。"],
        ["Fix this one place before starting something new.", "The error message must match the status code."],
      ),
      teachingObservations: previewText(
        language,
        [
          "先圈定当前文件里哪一段，再给下一步，更容易动手。",
          "提示必须对上返回码，否则后面排查会走偏。",
        ],
        [
          "Point to the exact block first, then give the next move.",
          "If the message does not match the status code, later debugging goes sideways.",
        ],
      ),
      recentWins: previewText(
        language,
        ["已经能指出要改当前文件里哪一段"],
        ["You can already point to the block that needs to change."],
      ),
      language,
    };
    if (bootstrap.planRuntimeStatus) {
      bootstrap.planRuntimeStatus = {
        ...bootstrap.planRuntimeStatus,
        currentStage: {
          ...bootstrap.planRuntimeStatus.currentStage,
          title: previewText(language, "改这一处", "Fix this one place"),
          goal: previewText(
            language,
            "先改当前文件里这一段，别同时动别的。",
            "Change only this error-handling block in the current file.",
          ),
        },
        currentMainThread: {
          ...bootstrap.planRuntimeStatus.currentMainThread,
          focusArea: previewText(language, "登录失败的提示", "the login error message"),
          summary: previewText(
            language,
            "先改当前文件里这一段错误处理。",
            "Fix the login error message first.",
          ),
          nextStep: previewText(
            language,
            "改登录失败的提示。",
            "Fix the login error message.",
          ),
          currentStep: previewText(
            language,
            "改登录失败的提示。",
            "Fix the login error message.",
          ),
          whyNow: previewText(
            language,
            "登录失败时提示不对，先改这里。",
            "This error message blocks login. Fix it first.",
          ),
          verifyMethod: previewText(
            language,
            ["用错的账号登一次，看提示对不对。"],
            ["After the change, run it. The error message should match the real response."],
          ),
          nextAfterCurrent: previewText(
            language,
            "对了再补测试。",
            "If this place is right, add a test next.",
          ),
        },
        reviewPoints: bootstrap.planRuntimeStatus.reviewPoints.map((item) => {
          if (item.concept === "错误提示要对上返回码") {
            return {
              ...item,
              concept: previewText(language, "错误提示要对上返回码", "Error message must match the status code"),
              reason: previewText(
                language,
                "回看：为什么提示文案要跟返回码对上。",
                "Look back: why the message must match the status code.",
              ),
            };
          }
          if (item.concept === "改动边界") {
            return {
              ...item,
              concept: previewText(language, "改动边界", "Change boundary"),
              reason: previewText(
                language,
                "回忆为什么先改当前文件这一段，而不是同时动别的文件。",
                "Recall why this block in the current file comes first, not other files at the same time.",
              ),
            };
          }
          return item;
        }),
        coachJudgment: {
          ...bootstrap.planRuntimeStatus.coachJudgment,
          summary: previewText(
            language,
            "先把当前这一步做完。",
            "Finish this step first.",
          ),
          teachingGoal: previewText(
            language,
            "把这一步做完，确认能跑。",
            "Finish this step and confirm it runs.",
          ),
          supportStrategy: previewText(
            language,
            "先把这一处改完，再开下一件事。",
            "Finish this place before starting something new.",
          ),
          resumeThread: previewText(
            language,
            "下一轮从当前文件这一段接着改。",
            "Pick up from this error-handling block in the current file.",
          ),
        },
        nextTrainingAction: previewText(
          language,
          "改登录失败的提示。",
          "Fix the login error message.",
        ),
        reviewQueueSummary: previewText(
          language,
          "有 2 件事做完后值得再看一遍。",
          "Two things to look at again after this step.",
        ),
        currentStep: previewText(
          language,
          "改登录失败的提示。",
          "Fix the login error message.",
        ),
        whyNow: previewText(
          language,
          "登录失败时提示不对，先改这里。",
          "This error message blocks login. Fix it first.",
        ),
        verifyMethod: previewText(
          language,
          ["用错的账号登一次，看提示对不对。"],
          ["After the change, run it. The error message should match the real response."],
        ),
        nextAfterCurrent: previewText(
          language,
          "对了再补测试。",
          "If this place is right, add a test next.",
        ),
      };
    }
    bootstrap.reviewQueueSummary = previewText(
      language,
      "有 2 件事做完后值得再看一遍。",
      "Two things to look at again after this step.",
    );
    applyLocalizedConnectedPlanPreview(bootstrap, language);
  }
  const guidedTrainingPreviewActive = applyGuidedTrainingPreviewScenario(bootstrap, state);
  const shouldApplyProviderTruthTrainingPreview =
    state.activeView === "training" &&
    !guidedTrainingPreviewActive &&
    (state.scenario === "ready" ||
      state.scenario === "provider-failure" ||
      state.scenario === "provider-failure-empty" ||
      state.scenario === "provider-auth-failure" ||
      state.scenario === "provider-auth-failure-empty");
  if (shouldApplyProviderTruthTrainingPreview) {
    const language = state.composerLanguage;
    bootstrap.task = {
      ...bootstrap.task,
      id: "task-provider-truth",
      title: previewText(
        language,
        "验证 provider 什么时候才算真正可用",
        "Verify when a provider is truly usable",
      ),
      description: previewText(
        language,
        "沿着当前 provider 链路，判断空内容、reasoning-only 和截断回复为什么都不能被当成“教练可用”。",
        "Walk the current provider chain and explain why empty content, reasoning-only, and truncated replies can never count as coach-ready.",
      ),
      constraints: [
        previewText(
          language,
          "不要把接口连通当成教练 ready",
          "Do not treat API reachability as coach readiness",
        ),
        previewText(
          language,
          "不要接受空内容或只有 reasoning 的回复",
          "Do not accept empty content or reasoning-only replies",
        ),
        previewText(
          language,
          "不要把截断回复误判成可继续教学",
          "Do not misread truncated replies as usable teaching output",
        ),
      ],
      acceptanceCriteria: previewText(
        language,
        ["能明确说出哪些返回必须判失败", "能把结果回带给对话继续决策"],
        ["Explain which returns must fail", "Bring the result back into the conversation"],
      ),
      nextActionLabel: previewText(language, "继续检查 provider 真相", "Keep checking provider truth"),
    };
    bootstrap.workspaceTrainingState = {
      ...bootstrap.workspaceTrainingState,
      latestConversationHandoff: {
        ...bootstrap.workspaceTrainingState?.latestConversationHandoff,
        candidateId: "cand-provider-truth",
        targetId: "card-practice-provider",
        handoffSummary: previewText(
          language,
          "先把 provider 可用性判断做实，再继续更深训练治理。",
          "Make the provider usability judgment real before going deeper into training governance.",
        ),
        cardTitle: previewText(language, "验证 provider 真相链路", "Verify the provider truth chain"),
      },
      latestTrainingHandoff: {
        ...bootstrap.workspaceTrainingState?.latestTrainingHandoff,
        candidateId: "cand-provider-truth",
        targetId: "card-practice-provider",
        handoffSummary: previewText(
          language,
          "当前训练先聚焦 provider 真相，不把接口连通误判成教练可用。",
          "This training card focuses on provider truth first, so API reachability is no longer mistaken for coach readiness.",
        ),
        cardTitle: previewText(language, "验证 provider 真相链路", "Verify the provider truth chain"),
        learnerDeliverables: previewText(
          language,
          ["列出哪些返回必须判失败", "确认当前链路有没有假阳性"],
          ["List which returns must fail", "Confirm whether the current chain has false positives"],
        ),
        verificationSteps: previewText(
          language,
          ["跑 provider 相关测试", "用真实 provider 烟测关键边界"],
          ["Run provider-related tests", "Smoke test key boundaries with the real provider"],
        ),
        successSignal: previewText(
          language,
          "空内容、reasoning-only、截断回复都不会再被误判为可用。",
          "Empty content, reasoning-only, and truncated replies are no longer treated as usable.",
        ),
        returnWith: previewText(
          language,
          "测试结果与真实烟测结论",
          "Test results and real smoke conclusions",
        ),
        returnSummary: previewText(
          language,
          "provider 真相确认后再回到下一张训练卡。",
          "Return to the next training card after provider truth is confirmed.",
        ),
      },
      latestTrainingNextHop: {
        ...bootstrap.workspaceTrainingState?.latestTrainingNextHop,
        candidateId: "cand-memory-truth",
        title: previewText(
          language,
          "回到训练记忆与掌握度真源",
          "Return to training memory and mastery truth",
        ),
        summary: previewText(
          language,
          "provider 真相收紧后，再继续训练主闭环。",
          "Tighten provider truth first, then continue the main training loop.",
        ),
        whyNow: previewText(
          language,
          "先修最底层的教练可用性，再推进更深治理。",
          "Fix the deepest coach-availability layer first, then move into deeper governance.",
        ),
        cardTitle: previewText(language, "梳理训练单一真源", "Clarify training's single source of truth"),
      },
      latestLearningFollowup: previewText(
        language,
        "确认 provider 真相后，再进入训练记忆与掌握度单一真源。",
        "Confirm provider truth, then move into the single source of truth for training memory and mastery.",
      ),
      latestLearningFocusArea: "provider truth",
      latestLearningVerifiedResult: previewText(
        language,
        "当前训练默认卡已经回到真实教练问题，而不是开发壳任务。",
        "The default training card is back on a real coach problem, not a shell-only implementation task.",
      ),
      latestLearningBlocker: previewText(
        language,
        "仍需确认真实 provider 链路边界。",
        "The real provider-boundary chain still needs confirmation.",
      ),
      latestLearningPartialProgress: previewText(
        language,
        "欢迎态与壳层已收口，provider 真相仍待闭环。",
        "The welcome state and shell are tightened up, but provider truth still needs closure.",
      ),
      selectedCardId: "card-practice-provider",
      selectedCardType: "practice",
      selectedCardTitle: previewText(language, "验证 provider 真相链路", "Verify the provider truth chain"),
      selectedCardStatus: "active",
      trainingCardCandidates: [
        {
          cardId: "card-practice-provider",
          type: "practice",
          title: previewText(language, "验证 provider 真相链路", "Verify the provider truth chain"),
          focusArea: "provider truth",
          targetSkill: previewText(
            language,
            "provider 可用性治理",
            "Provider usability governance",
          ),
          whyNow: previewText(
            language,
            "教练是否真的可用，决定了后面所有训练都值不值得继续。",
            "Whether the coach is truly usable decides if the rest of the training is worth continuing.",
          ),
          deliverable: previewText(
            language,
            "一条严格的 provider 可用性判断",
            "A strict provider-usability judgment",
          ),
          validationMethod: previewText(
            language,
            "测试 + 真实 provider 烟测",
            "Tests + real provider smoke",
          ),
          expectedSymbols: ["describeProviderSendState", "providerErrorHint"],
          apiHints: ["describeProviderSendState(config)"],
          suggestedWorkspaceAction: previewText(
            language,
            "先把 provider test 结果和用户真实烟测输出对成一条自洽的判断链。",
            "First connect the provider test result to the real smoke output with one coherent verdict chain.",
          ),
          scenario: previewText(
            language,
            "用户接入了 OpenAI-compatible provider，Trainer 必须明确区分 reachable 和 usable for coaching。",
            "The user connected an OpenAI-compatible provider, and Trainer must separate reachable from usable for coaching.",
          ),
          constraints: previewText(
            language,
            [
              "不能把 HTTP 200 直接当成教练已可用。",
              "不能用纯 reasoning 或空文本冒充回答。",
            ],
            [
              "Do not treat HTTP 200 as coach-ready by itself.",
              "Do not surface reasoning-only or empty text as a usable answer.",
            ],
          ),
          selfCheck: previewText(
            language,
            [
              "UI 是否同时说清 reachable、usable 和 reason？",
              "用户能否一眼看到下一个可信动作？",
            ],
            [
              "Does the UI clearly separate reachable, usable, and reason?",
              "Can the user see the next credible action at a glance?",
            ],
          ),
          filesToTouch: [
            "extension/src/commands/providerCommands.ts",
            "server/app/api/routers.py",
          ],
          hintLadder: previewText(
            language,
            [
              "先找到 provider test 在哪里返回结构化状态。",
              "再追踪前端如何把 detail 和 reachable 组合成可见文案。",
            ],
            [
              "Start with where the provider test returns structured status.",
              "Then trace how the frontend turns detail and reachable into the visible message.",
            ],
          ),
          commonMistakes: previewText(
            language,
            [
              "只检查 reachability，却忽略了上游拒绝原因。",
              "把后端原始报错直接塞进主要 UI 文案。",
            ],
            [
              "Checking reachability but ignoring the upstream rejection reason.",
              "Dumping raw backend error text into the primary UI.",
            ],
          ),
          stuckRecovery: previewText(
            language,
            "如果判断链又变得混乱，先把现状改写成 reachable / usable / next action 三行。",
            "If the verdict chain gets muddy again, rewrite it as reachable / usable / next action first.",
          ),
          reflectionPrompt: previewText(
            language,
            "这次你刚分清的是哪一条边界？它为什么会影响后面的训练体验？",
            "Which boundary did you just clarify, and why does it change the rest of the training experience?",
          ),
          returnWith: previewText(
            language,
            "带回最终判断文案、一条真实 smoke 证据，以及一个仍不能自动化的缺口。",
            "Bring back the final verdict copy, one real smoke proof point, and one gap that still cannot be automated.",
          ),
        },
      ],
      activeTrainingCardRouting: {
        selectedCardId: "card-practice-provider",
        selectedCard: {
          cardId: "card-practice-provider",
          type: "practice",
          title: previewText(language, "验证 provider 真相链路", "Verify the provider truth chain"),
          expectedSymbols: ["describeProviderSendState", "providerErrorHint"],
          apiHints: ["describeProviderSendState(config)"],
        },
        whyThisCard: previewText(
          language,
          "这是当前最直接决定教练可信度的一张卡。",
          "This card most directly decides whether the coach feels trustworthy.",
        ),
      },
      trainingEventLedger: [
        {
          eventId: "training-ledger-provider-preview",
          eventType: "card_status_transitioned",
          createdAt: "2026-06-04T18:10:00.000Z",
          selectedCardId: "card-practice-provider",
          selectedCardType: "practice",
          selectedCardTitle: previewText(language, "验证 provider 真相链路", "Verify the provider truth chain"),
          statusKind: "active",
          statusSummary: previewText(
            language,
            "当前训练已回到 provider 真相主卡。",
            "Training has returned to the provider-truth main card.",
          ),
        },
      ],
    };
    if (state.trainingSubmode === "flash") {
      bootstrap.task = {
        ...bootstrap.task,
        id: "task-provider-flash",
        title: previewText(
          language,
          "闪记 provider 失败边界",
          "Recall provider failure boundaries",
        ),
        description: previewText(
          language,
          "用一张闪记卡回忆空内容、reasoning-only 和截断回复为什么都不能继续教学。",
          "Use one flashcard to recall why empty content, reasoning-only, and truncated replies cannot continue teaching.",
        ),
        acceptanceCriteria: previewText(
          language,
          ["选出必须判失败的 provider 返回", "能用一句话解释为什么不能继续教学"],
          ["Pick the provider returns that must fail", "Explain in one sentence why teaching cannot continue"],
        ),
        nextActionLabel: previewText(language, "提交闪记答案", "Submit the flash answer"),
      };
      bootstrap.workspaceTrainingState = {
        ...bootstrap.workspaceTrainingState,
        latestTrainingSubmode: "flash",
        latestConversationHandoff: {
          ...bootstrap.workspaceTrainingState?.latestConversationHandoff,
          candidateId: "cand-provider-flash",
          targetId: "card-flash-provider-boundary",
          handoffSummary: previewText(
            language,
            "先把 provider 失败边界变成一张闪记卡。",
            "Turn provider failure boundaries into one flashcard first.",
          ),
          cardType: "flash",
          cardTitle: previewText(
            language,
            "闪记 provider 失败边界",
            "Recall provider failure boundaries",
          ),
        },
        latestTrainingHandoff: {
          ...bootstrap.workspaceTrainingState?.latestTrainingHandoff,
          candidateId: "cand-provider-flash",
          targetId: "card-flash-provider-boundary",
          handoffSummary: previewText(
            language,
            "当前训练先确认你能回忆 provider 失败边界。",
            "This training step first checks whether you can recall provider failure boundaries.",
          ),
          cardType: "flash",
          cardTitle: previewText(
            language,
            "闪记 provider 失败边界",
            "Recall provider failure boundaries",
          ),
          learnerDeliverables: previewText(
            language,
            ["答完这张闪记卡", "用一句话解释失败边界"],
            ["Finish this flashcard", "Explain the failure boundary in one sentence"],
          ),
          verificationSteps: previewText(
            language,
            ["优先选择题；不确定时切到填空或简答。"],
            ["Start with multiple choice; switch to fill or short answer if unsure."],
          ),
          returnWith: previewText(language, "闪记答案与自信度", "Flash answer and confidence"),
          returnSummary: previewText(
            language,
            "闪记通过后回到实战卡继续验证。",
            "Return to the practice card after the flashcard passes.",
          ),
        },
        latestTrainingNextHop: {
          ...bootstrap.workspaceTrainingState?.latestTrainingNextHop,
          candidateId: "cand-provider-practice-after-flash",
          candidateType: "practice_candidate",
          title: previewText(
            language,
            "把失败边界带回代码验证",
            "Bring failure boundaries back into code verification",
          ),
          summary: previewText(
            language,
            "闪记通过后，再回到实战卡检查 provider 真相链路。",
            "After the flashcard passes, return to the practice card and check the provider truth chain.",
          ),
          whyNow: previewText(
            language,
            "先确认概念能稳定回忆，再进入文件级验证。",
            "Confirm the concept is stable in memory before moving into file-level verification.",
          ),
          cardType: "practice",
          cardTitle: previewText(language, "验证 provider 真相链路", "Verify the provider truth chain"),
        },
        latestLearningFollowup: previewText(
          language,
          "先确认这个边界能被回忆出来，再回到实战卡。",
          "Confirm the boundary can be recalled, then return to the practice card.",
        ),
        latestLearningFocusArea: "provider readiness recall",
        selectedCardId: "card-flash-provider-boundary",
        selectedCardType: "flash",
        selectedCardTitle: previewText(
          language,
          "闪记 provider 失败边界",
          "Recall provider failure boundaries",
        ),
        selectedCardStatus: "active",
        trainingCardCandidates: [
          {
            cardId: "card-flash-provider-boundary",
            type: "flash",
            title: previewText(
              language,
              "闪记 provider 失败边界",
              "Recall provider failure boundaries",
            ),
            focusArea: "provider readiness recall",
            targetSkill: previewText(language, "失败边界回忆", "Failure-boundary recall"),
            whyNow: previewText(
              language,
              "先把判断标准记牢，后面的实战验证才不会漂。",
              "Lock the judgment criteria in memory first so the later practice work stays grounded.",
            ),
            deliverable: previewText(
              language,
              "一个能复述的失败边界",
              "A failure boundary you can restate",
            ),
            validationMethod: previewText(language, "选择 / 填空 / 简答", "Select / fill / short answer"),
          },
        ],
        activeTrainingCardRouting: {
          selectedCardId: "card-flash-provider-boundary",
          whyThisCard: previewText(
            language,
            "这是进入实战前最小的一次边界回忆。",
            "This is the smallest boundary recall before returning to practice.",
          ),
          selectedCard: {
            cardId: "card-flash-provider-boundary",
            type: "flash",
            title: previewText(
              language,
              "闪记 provider 失败边界",
              "Recall provider failure boundaries",
            ),
          },
        },
        trainingEventLedger: [
          {
            eventId: "training-ledger-provider-flash-preview",
            eventType: "card_status_transitioned",
            createdAt: "2026-06-04T18:16:00.000Z",
            selectedCardId: "card-flash-provider-boundary",
            selectedCardType: "flash",
            selectedCardTitle: previewText(
              language,
              "闪记 provider 失败边界",
              "Recall provider failure boundaries",
            ),
            statusKind: "active",
            statusSummary: previewText(
              language,
              "当前训练切到 provider 失败边界闪记卡。",
              "Training has switched to the provider failure-boundary flashcard.",
            ),
          },
        ],
        theoryDrill: {
          id: "theory-provider-boundary",
          title: previewText(language, "provider 失败边界", "Provider failure boundaries"),
          focusArea: "provider readiness recall",
          status: "active",
          summary: previewText(
            language,
            "确认你能判断哪些 provider 返回不能继续教学。",
            "Confirm that you can judge which provider returns cannot continue teaching.",
          ),
          successSignal: previewText(
            language,
            "能选出必须判失败的返回，并能简短解释。",
            "Pick the returns that must fail and explain why briefly.",
          ),
          returnWith: previewText(language, "闪记答案和解释", "Flash answer and explanation"),
          questions: [
            {
              id: "q-provider-boundary",
              prompt: previewText(
                language,
                "哪一种 provider 返回必须判为教练不可用？",
                "Which provider return must be marked unusable for coaching?",
              ),
              choices: previewText(
                language,
                [
                  "HTTP 200，但 visible content 为空或只有 reasoning",
                  "HTTP 200，且有完整可见教学内容",
                  "模型列表刷新成功，且还未发送教学消息",
                ],
                [
                  "HTTP 200, but visible content is empty or reasoning-only",
                  "HTTP 200 with complete visible teaching content",
                  "The model list refreshed successfully, and no teaching message has been sent yet",
                ],
              ),
              answer: previewText(
                language,
                "HTTP 200，但 visible content 为空或只有 reasoning",
                "HTTP 200, but visible content is empty or reasoning-only",
              ),
              explanation: previewText(
                language,
                "接口连通不等于教练可用；必须有可见、完整、可教学的内容。",
                "API reachability does not mean the coach is usable; the content must be visible, complete, and teachable.",
              ),
            },
          ],
          updatedAt: "2026-06-04T18:16:00.000Z",
        },
      };
    }
  }
  if (bootstrap.memory.workspace) {
    bootstrap.memory.workspace.responseLanguage = state.composerLanguage;
  }
  bootstrap.deletedResources = [
    {
      resourceId: "preview-deleted-reference",
      title: "Archived reference notes",
      collectionPath: "Library/Archive/reference-notes.md",
      deletedAt: "2026-06-18T09:30:00.000Z",
      recoverable: true,
    },
  ];
  bootstrap.activeView = state.activeView;
  if (connectionState !== "offline") {
    state.previewProviderConfig = structuredClone(bootstrap.providerConfig);
  }
  try {
    window.localStorage.setItem(previewStorageKey, JSON.stringify(toPreviewPersistedState(state)));
  } catch {
    // Browser preview should keep rendering even when storage is blocked.
  }

  window.__TRAINER_BOOTSTRAP__ = bootstrap;
  window.acquireVsCodeApi = () => ({
    getState() {
      return state;
    },
    setState(nextState) {
      if (!nextState || typeof nextState !== "object") {
        return;
      }
      Object.assign(state, nextState);
      try {
        window.localStorage.setItem(previewStorageKey, JSON.stringify(toPreviewPersistedState(state)));
      } catch {
        // Keep the preview interactive even when storage is unavailable.
      }
    },
    postMessage(message) {
      console.debug("[trainer:browser-preview]", message);
      if (isWebviewAction(message)) {
        if (handleBrowserPreviewStreamCancel(message)) {
          return;
        }
        if (
          state.connectionState !== "offline" &&
          message.type === "command/execute" &&
          LIVE_TRAINING_COMMAND_IDS.has(message.payload.commandId)
        ) {
          void runBrowserPreviewLiveTrainingAction(message, state.composerLanguage);
          return;
        }
        runBrowserPreviewWebviewAction(message, state.composerLanguage);
      }
    },
  });
}
