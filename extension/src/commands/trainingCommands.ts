import * as vscode from "vscode";
import type { CommandContext } from "../core/commandContext";
import type { CommandExecutionResult } from "../core/types";
import { SidecarRequestAbortedError, type SSEMessage } from "../core/httpClient";
import { SIDECAR_DEFAULTS } from "../core/constants";
import { mergeMemorySummarySnapshot } from "../core/workbenchData";
import { isComposerLanguage } from "../../../shared/src/types";
import { deriveResourceTrustState } from "../../../shared/src/resourceTrust";
import {
  createEmptyTrainerStreamingState,
  normalizeTrainerStreamingState,
} from "../../../shared/src/protocol";
import {
  sanitizeErrorSurfaceText,
  waitingComposerEnqueueFailureText,
} from "../../../shared/src/errorSurfaceSanitizer";
import { getRuntimeWorkspaceId } from "./workspaceContext";
import { withWorkspaceQuery } from "./workspaceContext";
import { stripHostLastTestSecrets } from "../../../shared/src/hostLastTestGovernance";

type ActiveTrainingCardStream = {
  messageId: string;
  requestId: string;
  abortController: AbortController;
  sidecarPort: number;
  generation: number;
};

type AppliedTrainingGenerateCardBind = {
  selectedCardId: string;
};

const activeTrainingCardStreams = new WeakMap<CommandContext, ActiveTrainingCardStream>();
const trainingStreamGenerations = new WeakMap<CommandContext, number>();
/** Fail-closed: same request_id binds once — waiter/replay complete must not remint or clobber leftover. */
const appliedTrainingGenerateCardBinds = new WeakMap<
  CommandContext,
  Map<string, AppliedTrainingGenerateCardBind>
>();

/**
 * Claim the sole host bind for a generate-card request_id.
 * First successful complete → apply; duplicate same request_id → ignore.
 */
export function claimTrainingGenerateCardCompleteBind(
  context: CommandContext,
  requestId: string | undefined,
  selectedCardId: string | undefined,
): boolean {
  const normalizedRequestId = readNonEmptyString(requestId);
  if (!normalizedRequestId) {
    return true;
  }
  let applied = appliedTrainingGenerateCardBinds.get(context);
  if (!applied) {
    applied = new Map();
    appliedTrainingGenerateCardBinds.set(context, applied);
  }
  if (applied.has(normalizedRequestId)) {
    return false;
  }
  applied.set(normalizedRequestId, {
    selectedCardId: readNonEmptyString(selectedCardId) ?? "",
  });
  return true;
}

function trainingCardGenerationSucceeded(response: {
  card?: Record<string, unknown>;
  success?: boolean;
  reliability?: { outcome?: string };
}): boolean {
  if (response.success === false) {
    return false;
  }
  const outcome = String(response.reliability?.outcome ?? "").trim().toLowerCase();
  if (outcome === "failure" || outcome === "cancelled") {
    return false;
  }
  return Boolean(readNonEmptyString(response.card?.card_id));
}

export function hasTrainingGenerateCardCompleteBind(
  context: CommandContext,
  requestId: string | undefined,
): boolean {
  const normalizedRequestId = readNonEmptyString(requestId);
  if (!normalizedRequestId) {
    return false;
  }
  return appliedTrainingGenerateCardBinds.get(context)?.has(normalizedRequestId) === true;
}

/**
 * Fail-closed UI ack: clear/complete stream only when global streamMessageId
 * still belongs to this card stream — never clobber a newer Coach stream.
 * Claim-once host bind is independent of ownership (see complete paths).
 */
function generateCardOwnsStreamMessageId(
  context: CommandContext,
  messageId: string | undefined,
): boolean {
  const normalized = readNonEmptyString(messageId);
  if (!normalized) {
    return false;
  }
  return readTrainerStreamingState(context).streamMessageId === normalized;
}

type TrainingCurrentFilePayload = {
  path: string;
  language_id: string;
  content: string;
  content_excerpt?: string;
  content_line_span?: string;
  content_strategy?: string;
  selection_text?: string;
  selection_range?: string;
  diagnostics?: string[];
  recent_files?: string[];
  recent_edited_files?: string[];
  related_files?: Array<{ path: string; reason: string; excerpt?: string; line_span?: string }>;
};

async function attachLiveProviderToTrainingRequest(
  context: CommandContext,
  requestBody: Record<string, unknown>,
): Promise<void> {
  const providerConfig = context.providerStore.getConfig();
  const apiKey = await context.providerStore.getApiKey();
  if (providerConfig) {
    requestBody.provider = providerConfig;
  }
  if (apiKey?.trim()) {
    requestBody.api_key = apiKey;
    requestBody.apiKey = apiKey;
  }
  const lastTest = context.getHostState().bootstrap.providerConfig.lastTestResult;
  if (lastTest && typeof lastTest === "object") {
    requestBody.lastTestResult = stripHostLastTestSecrets({
      ...(lastTest as unknown as Record<string, unknown>),
    });
  }
}

type TrainingGenerateCardWaiterInput = {
  source: string;
  cardType: string;
  submode: string;
  resourceId?: string;
  focusArea?: string;
  targetSkill?: string;
  prompt?: string;
  responseLanguage?: string;
  currentFile: TrainingCurrentFilePayload | undefined;
  workspaceId: string;
};

/**
 * Join an in-flight owner generate for the same request_id.
 * Fail-closed: no generation bump, reuse owner streamMessageId so the first
 * complete still reaches pending→success/failure→ack while isStreaming is true.
 */
async function settleTrainingGenerateCardWaiter(
  context: CommandContext,
  owner: ActiveTrainingCardStream,
  input: TrainingGenerateCardWaiterInput,
): Promise<CommandExecutionResult> {
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  const messageId = owner.messageId;
  const requestId = owner.requestId;
  type TrainingCardGenerationResponse = {
    card?: Record<string, unknown>;
    score?: number;
    success?: boolean;
    reason?: string;
    active_routing?: { selected_card_id?: string | null };
  };
  const requestBody: {
    source: string;
    card_type: string;
    submode: string;
    resource_id: string;
    focus_area: string;
    target_skill: string;
    context_hint: string;
    workspace_id: string;
    plan_stage_id: string;
    current_file: TrainingCurrentFilePayload | undefined;
    response_language?: string;
    stream_id?: string;
    request_id?: string;
  } = {
    source: input.source,
    card_type: input.cardType,
    submode: input.submode,
    resource_id: input.resourceId ?? "",
    focus_area: input.focusArea ?? "",
    target_skill: input.targetSkill ?? "",
    context_hint: buildTrainingContextHint(
      {
        source: input.source,
        cardType: input.cardType,
        submode: input.submode,
        focusArea: input.focusArea,
        targetSkill: input.targetSkill,
        prompt: input.prompt,
      },
      input.currentFile,
    ),
    workspace_id: input.workspaceId,
    plan_stage_id: "",
    current_file: input.currentFile,
    // Distinct stream_id for transport; UI events reuse owner messageId.
    stream_id: `training_waiter_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    request_id: requestId,
  };
  if (input.responseLanguage) {
    requestBody.response_language = input.responseLanguage;
  }
  await attachLiveProviderToTrainingRequest(
    context,
    requestBody as unknown as Record<string, unknown>,
  );

  try {
    let response: TrainingCardGenerationResponse | undefined;
    let tokenCount = 0;
    const supportsStreaming = typeof context.sidecarClient.fetchSSE === "function";
    if (supportsStreaming) {
      for await (const event of context.sidecarClient.fetchSSE(
        status.port,
        "/training/generate-card/stream",
        requestBody,
        // Card generation performs a full LLM turn inside the sidecar; the
        // default 15s request window is too tight and aborts healthy runs.
        { timeoutMs: SIDECAR_DEFAULTS.providerRequestTimeoutMs },
      )) {
        if (activeTrainingCardStreams.get(context) !== owner) {
          return { ok: true, message: "Training stream invalidated." };
        }
        const parsed = parseTrainingSseJson(event);
        if (event.event === "complete") {
          const candidate = parsed?.response;
          if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
            throw new Error("Training card stream ended without a valid completion response.");
          }
          response = candidate as TrainingCardGenerationResponse;
          break;
        }
        if (event.event === "error") {
          throw new Error(
            typeof parsed?.error === "string" ? parsed.error : "Training card stream failed.",
          );
        }
        // Owner owns chunk UI; waiter only settles the complete honesty path.
        if (typeof parsed?.chunk === "string" || event.data) {
          tokenCount += 1;
        }
      }
    } else {
      response = await context.sidecarClient.postJson<TrainingCardGenerationResponse>(
        status.port,
        "/training/generate-card",
        requestBody,
      );
    }
    if (!response) {
      throw new Error("Training card stream ended before completion.");
    }
    if (activeTrainingCardStreams.get(context) !== owner) {
      return { ok: true, message: "Training stream invalidated." };
    }
    const success = trainingCardGenerationSucceeded(response);
    const generatedCardId = readNonEmptyString(response.card?.card_id);
    const selectedCardId = readNonEmptyString(response.active_routing?.selected_card_id);
    // Claim-once bind even if Coach replaced streamMessageId; ack only when we still own it.
    const shouldApplyHostState = success
      ? claimTrainingGenerateCardCompleteBind(
          context,
          requestId,
          selectedCardId ?? generatedCardId,
        )
      : !hasTrainingGenerateCardCompleteBind(context, requestId);
    if (generateCardOwnsStreamMessageId(context, messageId)) {
      await writeTrainerStreamingState(context, {
        ...readTrainerStreamingState(context),
        isStreaming: false,
        streamMessageId: messageId,
        streamError: undefined,
      });
      if (typeof context.workbench.postMessage === "function") {
        await context.workbench.postMessage({
          type: "stream/complete",
          payload: { messageId, tokens: tokenCount },
        });
      }
    }
    if (shouldApplyHostState) {
      await rehydrateTrainingSummary(context, status.port);
      if (activeTrainingCardStreams.get(context) !== owner) {
        return { ok: true, message: "Training stream invalidated." };
      }
      await context.workbench.syncState();
    }
    return {
      ok: success,
      message: success
        ? undefined
        : readNonEmptyString(response.reason) ?? "Training card was not ready.",
      data: { ...response, success, generatedCardId, selectedCardId },
    };
  } catch (error) {
    if (activeTrainingCardStreams.get(context) !== owner) {
      return { ok: true, message: "Training stream invalidated." };
    }
    if (generateCardOwnsStreamMessageId(context, messageId)) {
      await writeTrainerStreamingState(context, {
        ...readTrainerStreamingState(context),
        isStreaming: false,
        streamMessageId: messageId,
        streamError: sanitizeErrorSurfaceText(error),
      });
      if (typeof context.workbench.postMessage === "function") {
        await context.workbench.postMessage({
          type: "stream/error",
          payload: {
            messageId,
            error: sanitizeErrorSurfaceText(error),
            reliabilityPhase: "acked",
            reliabilityOutcome: "failure",
          },
        });
      }
    }
    return { ok: false, message: sanitizeErrorSurfaceText(error) };
  }
}

function nextTrainingStreamGeneration(context: CommandContext): number {
  const generation = (trainingStreamGenerations.get(context) ?? 0) + 1;
  trainingStreamGenerations.set(context, generation);
  return generation;
}

function isCurrentTrainingGeneration(context: CommandContext, generation: number): boolean {
  return trainingStreamGenerations.get(context) === generation;
}

function isCurrentTrainingCardStream(
  context: CommandContext,
  stream: ActiveTrainingCardStream,
): boolean {
  return (
    isCurrentTrainingGeneration(context, stream.generation) &&
    activeTrainingCardStreams.get(context) === stream &&
    !stream.abortController.signal.aborted
  );
}

function isInvalidatedTrainingCardStream(
  context: CommandContext,
  stream: ActiveTrainingCardStream | undefined,
  generation: number,
): boolean {
  return (
    !isCurrentTrainingGeneration(context, generation) ||
    (stream !== undefined && activeTrainingCardStreams.get(context) !== stream)
  );
}

function requestTrainingStreamCancellation(
  context: CommandContext,
  stream: ActiveTrainingCardStream,
): void {
  void context.sidecarClient
    .postJson(
      stream.sidecarPort,
      "/stream/cancel",
      { stream_id: stream.messageId },
      { timeoutMs: 2000 },
    )
    .catch(() => {
      // The local abort is authoritative when the sidecar is unavailable.
    });
}

/**
 * Ends a training-card stream before changing workspace/session scope.
 *
 * This is intentionally distinct from a learner-requested cancellation: the
 * old stream must not publish a cancelled state into the next workspace.
 */
export function invalidateActiveTrainingCardStream(context: CommandContext): boolean {
  nextTrainingStreamGeneration(context);
  const active = activeTrainingCardStreams.get(context);
  if (!active) {
    return false;
  }

  activeTrainingCardStreams.delete(context);
  active.abortController.abort();
  requestTrainingStreamCancellation(context, active);
  return true;
}

function readTrainerStreamingState(context: CommandContext) {
  const getStreamingState = (
    context as CommandContext & { getStreamingState?: () => unknown }
  ).getStreamingState;
  return normalizeTrainerStreamingState(
    typeof getStreamingState === "function" ? getStreamingState() : undefined,
  );
}

async function writeTrainerStreamingState(
  context: CommandContext,
  streamingState: ReturnType<typeof normalizeTrainerStreamingState>,
): Promise<void> {
  const setStreamingState = (
    context as CommandContext & { setStreamingState?: (state: unknown) => Promise<void> }
  ).setStreamingState;
  if (typeof setStreamingState === "function") {
    await setStreamingState(streamingState);
  }
}

async function rehydrateTrainingSummary(
  context: CommandContext,
  port: number,
  workspaceId?: string,
): Promise<void> {
  const summary = await context.sidecarClient.getJson<unknown>(
    port,
    withWorkspaceQuery("/memory/summary", context, workspaceId),
  );
  await context.patchWorkbenchData(
    mergeMemorySummarySnapshot(
      context.getHostState().bootstrap,
      summary,
      workspaceId ?? getRuntimeWorkspaceId(context),
    ),
  );
}

function getCurrentTrainingFilePayload(
  context: CommandContext,
): TrainingCurrentFilePayload | undefined {
  const editor = vscode.window?.activeTextEditor;
  if (!editor) {
    return undefined;
  }

  const content = editor.document.getText();
  if (!content.trim()) {
    return undefined;
  }

  const selection = editor.selection;
  const selectionText = selection.isEmpty ? undefined : editor.document.getText(selection);
  const selectionRange = selection.isEmpty
    ? undefined
    : `${selection.start.line + 1}:${selection.start.character + 1}-${selection.end.line + 1}:${selection.end.character + 1}`;
  const diagnostics = (vscode.languages?.getDiagnostics?.(editor.document.uri) ?? []).map(
    (item) => `[${diagnosticSeverityLabel(item.severity)}] line ${item.range.start.line + 1}: ${item.message}`,
  );
  const workspace = context.getHostState().workspace;

  return {
    path: editor.document.uri.fsPath,
    language_id: editor.document.languageId,
    content,
    content_excerpt: buildTrainingExcerpt(editor.document, selection),
    content_line_span: buildTrainingLineSpan(editor.document, selection),
    content_strategy: selection.isEmpty ? "active-file" : "selection-window",
    selection_text: selectionText,
    selection_range: selectionRange,
    diagnostics: diagnostics.slice(0, 20),
    recent_files: workspace.recentFiles?.slice(0, 5),
    recent_edited_files: workspace.recentEditedFiles?.slice(0, 5),
    related_files: [],
  };
}

function getTrainingResponseLanguage(context: CommandContext): string | undefined {
  const workspaceLanguage = context.getHostState().bootstrap.memory.workspace?.responseLanguage;
  return isComposerLanguage(workspaceLanguage) ? workspaceLanguage : undefined;
}

function resourceTrainingMessage(
  context: CommandContext,
  chinese: string,
  english: string,
): string {
  return getTrainingResponseLanguage(context) === "zh-CN" ? chinese : english;
}

function resourceTrainingGate(
  context: CommandContext,
  source: string,
  resourceId: string | undefined,
): CommandExecutionResult | undefined {
  if (source.trim().toLowerCase() !== "resource_knowledge") {
    return undefined;
  }

  const workspace = context.getHostState().bootstrap.memory.workspace;
  if (workspace?.trainerWorkspace?.status !== "managed") {
    return {
      ok: false,
      message: resourceTrainingMessage(
        context,
        "请先把这个项目加入 Trainer，再用资料生成复习卡。",
        "Add this project to Trainer before creating review cards from resources.",
      ),
    };
  }

  const resource = context.getHostState().bootstrap.resources.find(
    (item) => item.id === resourceId,
  );
  if (!resource) {
    return {
      ok: false,
      message: resourceTrainingMessage(
        context,
        "找不到这份资料。刷新资料页后再试一次。",
        "This resource is no longer available. Refresh Resources and try again.",
      ),
    };
  }

  if (resource.status !== "ready" || resource.indexState !== "indexed") {
    return {
      ok: false,
      message: resourceTrainingMessage(
        context,
        "这份资料还在整理中。完成整理和索引后就能生成复习卡。",
        "This resource is still being prepared. Finish organizing and indexing it first.",
      ),
    };
  }

  if (resource.freshness !== "fresh") {
    return {
      ok: false,
      message: resourceTrainingMessage(
        context,
        "这份资料需要先更新，再生成复习卡。",
        "Update this resource before creating a review card.",
      ),
    };
  }

  const explicitTrustState = resource.trustState?.trim().toLowerCase() || undefined;
  const derivedTrustState = deriveResourceTrustState({
    trustScore: resource.trustScore,
    freshness: resource.freshness,
    qualityFlags: resource.qualityFlags,
  });
  if (
    (explicitTrustState !== undefined && explicitTrustState !== "trusted") ||
    derivedTrustState !== "trusted"
  ) {
    return {
      ok: false,
      message: resourceTrainingMessage(
        context,
        "这份资料还需要确认内容后，才能生成复习卡。",
        "Review this resource before creating a review card from it.",
      ),
    };
  }

  return undefined;
}

function buildTrainingContextHint(
  payload: {
    source: string;
    cardType: string;
    submode: string;
    focusArea?: string;
    targetSkill?: string;
    prompt?: string;
  },
  currentFile: TrainingCurrentFilePayload | undefined,
): string {
  const parts: string[] = [];
  if (payload.prompt?.trim()) {
    parts.push(payload.prompt.trim());
  }
  if (payload.focusArea?.trim()) {
    parts.push(`Focus area: ${payload.focusArea.trim()}`);
  }
  if (payload.targetSkill?.trim()) {
    parts.push(`Target skill: ${payload.targetSkill.trim()}`);
  }
  parts.push(`Source: ${payload.source}`);
  parts.push(`Card type: ${payload.cardType}`);
  if (currentFile) {
    const fileName = currentFile.path.replace(/\\/g, "/").split("/").pop() ?? currentFile.path;
    parts.push(`Current IDE file: ${fileName}`);
    parts.push(`Language: ${currentFile.language_id}`);
    if (currentFile.selection_range) {
      parts.push(`Selection: ${currentFile.selection_range}`);
    }
    if (currentFile.content_line_span) {
      parts.push(`Excerpt lines: ${currentFile.content_line_span}`);
    }
    if (currentFile.diagnostics && currentFile.diagnostics.length > 0) {
      parts.push(`Diagnostics: ${currentFile.diagnostics.length}`);
    }
  }
  if (parts.length === 0) {
    return payload.submode === "flash"
      ? "Generate a flash card grounded in the current project."
      : "Generate a practice card grounded in the current IDE file.";
  }
  return parts.join("\n");
}

function buildTrainingExcerpt(
  document: vscode.TextDocument,
  selection: vscode.Selection,
): string | undefined {
  const totalLines = document.lineCount;
  if (totalLines <= 0) {
    return undefined;
  }

  const startLine = selection.isEmpty ? 0 : Math.max(0, selection.start.line - 8);
  const endLine = selection.isEmpty
    ? Math.min(totalLines - 1, Math.max(79, Math.min(119, totalLines - 1)))
    : Math.min(totalLines - 1, selection.end.line + 16);
  return collectDocumentLines(document, startLine, endLine, 6000);
}

function buildTrainingLineSpan(
  document: vscode.TextDocument,
  selection: vscode.Selection,
): string | undefined {
  const totalLines = document.lineCount;
  if (totalLines <= 0) {
    return undefined;
  }

  const startLine = selection.isEmpty ? 0 : Math.max(0, selection.start.line - 8);
  const endLine = selection.isEmpty
    ? Math.min(totalLines - 1, Math.max(79, Math.min(119, totalLines - 1)))
    : Math.min(totalLines - 1, selection.end.line + 16);
  return `${startLine + 1}-${endLine + 1}`;
}

function collectDocumentLines(
  document: vscode.TextDocument,
  startLine: number,
  endLine: number,
  maxChars: number,
): string {
  const parts: string[] = [];
  for (let line = startLine; line <= endLine; line += 1) {
    parts.push(document.lineAt(line).text);
  }
  const value = parts.join("\n");
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxChars - 1))}...`;
}

function diagnosticSeverityLabel(severity: vscode.DiagnosticSeverity): string {
  switch (severity) {
    case vscode.DiagnosticSeverity.Error:
      return "error";
    case vscode.DiagnosticSeverity.Warning:
      return "warning";
    case vscode.DiagnosticSeverity.Information:
      return "info";
    case vscode.DiagnosticSeverity.Hint:
    default:
      return "hint";
  }
}

function readPayloadRecord(payload: unknown): Record<string, unknown> {
  return payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
}

function reliabilityRequestId(record: Record<string, unknown>): string {
  // Prefer webview persistence id when non-empty; empty string stays legacy-compatible.
  const candidates = [
    record.__trainerTrainingPersistenceId,
    record.requestId,
    record.request_id,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return "";
}

function reliabilityFields(payload: unknown): {
  request_id: string;
  idempotency_key: string;
  revision: number;
  timeout_ms: number;
  cancel: boolean;
} {
  const record = readPayloadRecord(payload);
  const requestId = reliabilityRequestId(record);
  const idempotencyKeyRaw =
    typeof record.idempotencyKey === "string"
      ? record.idempotencyKey
      : typeof record.idempotency_key === "string"
        ? record.idempotency_key
        : requestId;
  const idempotencyKey =
    typeof idempotencyKeyRaw === "string" && idempotencyKeyRaw.trim()
      ? idempotencyKeyRaw.trim()
      : requestId;
  const revision =
    typeof record.revision === "number" && Number.isFinite(record.revision) ? record.revision : 0;
  const timeoutMs =
    typeof record.timeoutMs === "number" && Number.isFinite(record.timeoutMs)
      ? record.timeoutMs
      : typeof record.timeout_ms === "number" && Number.isFinite(record.timeout_ms)
        ? record.timeout_ms
        : 30_000;
  return {
    request_id: requestId,
    idempotency_key: idempotencyKey,
    revision,
    timeout_ms: timeoutMs,
    cancel: record.cancel === true,
  };
}

function leftoverCardStatusHttpFailure(error: unknown): CommandExecutionResult | undefined {
  if (typeof error !== "object" || error === null) {
    return undefined;
  }
  const statusCode = "statusCode" in error ? error.statusCode : undefined;
  if (statusCode !== 409) {
    return undefined;
  }
  const metadata = "metadata" in error ? error.metadata : undefined;
  const metadataDetail =
    typeof metadata === "object" && metadata !== null && "detail" in metadata
      ? metadata.detail
      : undefined;
  const message = error instanceof Error ? error.message : String(error);
  const detail = `${typeof metadataDetail === "string" ? metadataDetail : ""} ${message}`.toLowerCase();
  if (!/leftover-not-live|does not match live selected_card_id/.test(detail)) {
    return undefined;
  }
  return {
    ok: false,
    message:
      "Recovered training card is leftover-not-live. Trainer will not skip, grade, reflect, return, or resurrect leftover as live.",
  };
}

/**
 * §9.5 Card status transition: POST /training/card-status
 * Sends card status change from webview to sidecar.
 */
export async function trainingCardStatusTransitionCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const { cardId, newStatus, reason } = extractCardStatusPayload(payload);
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  try {
    const response = await context.sidecarClient.postJson<{
      card: Record<string, unknown>;
      error?: string;
    }>(status.port, "/training/card-status", {
        workspace_id: workspaceId,
        card_id: cardId,
        new_status: newStatus,
        reason: reason ?? "",
        ...reliabilityFields(payload),
      });
    if (response.error) {
      context.outputChannel.appendLine(`[training] Card status transition failed: ${response.error}`);
      return { ok: false, message: response.error };
    }
    context.outputChannel.appendLine(
      `[training] Card ${cardId} transitioned to ${newStatus}`,
    );
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true };
  } catch (error) {
    context.outputChannel.appendLine(
      `[training] Card status transition error: ${error}`,
    );
    return leftoverCardStatusHttpFailure(error) ?? { ok: false, message: String(error) };
  }
}

/**
 * §1.16 Card generation: POST /training/generate-card
 * Triggers structured card creation from a specified source.
 */
export async function trainingGenerateCardCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const { source, cardType, submode, focusArea, targetSkill, resourceId, prompt, requestId: payloadRequestId } =
    extractGenerateCardPayload(payload);
  const resourceTrainingBlock = resourceTrainingGate(context, source, resourceId);
  if (resourceTrainingBlock) {
    return resourceTrainingBlock;
  }
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  // If submode is "flash", override cardType to "flash"
  const finalCardType = submode === "flash" ? "flash" : cardType;
  const currentFile = getCurrentTrainingFilePayload(context);
  const responseLanguage = getTrainingResponseLanguage(context);
  const streamingState = readTrainerStreamingState(context);
  const activeOwnerStream = activeTrainingCardStreams.get(context);
  const incomingRequestId = readNonEmptyString(payloadRequestId);
  if (streamingState.isStreaming) {
    // Same request_id waiter may finish while owner is still flagged streaming.
    // Distinct ids stay blocked; waiter must not bump generation / remint.
    if (
      incomingRequestId &&
      activeOwnerStream?.requestId &&
      activeOwnerStream.requestId === incomingRequestId
    ) {
      return settleTrainingGenerateCardWaiter(context, activeOwnerStream, {
        source,
        cardType: finalCardType,
        submode: submode ?? "",
        resourceId,
        focusArea,
        targetSkill,
        prompt,
        responseLanguage,
        currentFile,
        workspaceId,
      });
    }
    return { ok: false, message: "Another Trainer stream is already in progress." };
  }
  const streamGeneration = nextTrainingStreamGeneration(context);
  let messageId: string | undefined;
  let requestId: string | undefined;
  let abortController: AbortController | undefined;
  let activeTrainingStream: ActiveTrainingCardStream | undefined;
  try {
  const requestBody: {
      source: string;
      card_type: string;
      submode: string;
      resource_id: string;
      focus_area: string;
      target_skill: string;
      context_hint: string;
      workspace_id: string;
      plan_stage_id: string;
      current_file: TrainingCurrentFilePayload | undefined;
      response_language?: string;
      stream_id?: string;
      request_id?: string;
    } = {
      source,
      card_type: finalCardType,
      submode: submode ?? "",
      resource_id: resourceId ?? "",
      focus_area: focusArea ?? "",
      target_skill: targetSkill ?? "",
      context_hint: buildTrainingContextHint(
        {
          source,
          cardType: finalCardType,
          submode,
          focusArea,
          targetSkill,
          prompt,
        },
        currentFile,
      ),
      workspace_id: workspaceId,
      plan_stage_id: "",
      current_file: currentFile,
    };
    if (responseLanguage) {
      requestBody.response_language = responseLanguage;
    }
    await attachLiveProviderToTrainingRequest(
      context,
      requestBody as unknown as Record<string, unknown>,
    );

    type TrainingCardGenerationResponse = {
      card?: Record<string, unknown>;
      score?: number;
      success?: boolean;
      reason?: string;
      active_routing?: { selected_card_id?: string | null };
    };
    const supportsStreaming =
      typeof context.sidecarClient.fetchSSE === "function" &&
      typeof context.workbench.postMessage === "function" &&
      typeof (
        (context as CommandContext & { setStreamingState?: unknown }).setStreamingState
      ) === "function";

    if (!supportsStreaming) {
      messageId = `training_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      requestId = payloadRequestId ?? messageId;
      requestBody.request_id = requestId;
      await writeTrainerStreamingState(context, {
        ...createEmptyTrainerStreamingState(),
        isStreaming: true,
        streamMessageId: messageId,
      });
      await context.workbench.postMessage({
        type: "stream/start",
        payload: { messageId },
      });
      try {
        const response = await context.sidecarClient.postJson<TrainingCardGenerationResponse>(
          status.port,
          "/training/generate-card",
          requestBody,
        );
        if (!isCurrentTrainingGeneration(context, streamGeneration)) {
          return { ok: true, message: "Training stream invalidated." };
        }
        const success = trainingCardGenerationSucceeded(response);
        const generatedCardId = readNonEmptyString(response.card?.card_id);
        const selectedCardId = readNonEmptyString(response.active_routing?.selected_card_id);
        if (!success) {
          throw new Error(
            readNonEmptyString(response.reason) ?? "Training card was not ready.",
          );
        }
        // Claim-once bind even if Coach owns stream; ack only when we still own it.
        const shouldBind = claimTrainingGenerateCardCompleteBind(
          context,
          requestId,
          selectedCardId ?? generatedCardId,
        );
        if (generateCardOwnsStreamMessageId(context, messageId)) {
          await writeTrainerStreamingState(context, {
            ...readTrainerStreamingState(context),
            isStreaming: false,
            streamError: undefined,
          });
          await context.workbench.postMessage({
            type: "stream/complete",
            payload: { messageId, tokens: 0 },
          });
        }
        if (shouldBind) {
          await rehydrateTrainingSummary(context, status.port);
          if (!isCurrentTrainingGeneration(context, streamGeneration)) {
            return { ok: true, message: "Training stream invalidated." };
          }
          await context.workbench.syncState();
        }
        return {
          ok: true,
          message: undefined,
          data: { ...response, success: true, generatedCardId, selectedCardId },
        };
      } catch (error) {
        if (isInvalidatedTrainingCardStream(context, undefined, streamGeneration)) {
          return { ok: true, message: "Training stream invalidated." };
        }
        if (generateCardOwnsStreamMessageId(context, messageId)) {
          await writeTrainerStreamingState(context, {
            ...readTrainerStreamingState(context),
            isStreaming: false,
            streamError: sanitizeErrorSurfaceText(error),
          });
          await context.workbench.postMessage({
            type: "stream/error",
            payload: {
              messageId,
              error: sanitizeErrorSurfaceText(error),
              reliabilityPhase: "acked",
              reliabilityOutcome: "failure",
            },
          });
        }
        context.outputChannel.appendLine(
          `[training] Card generation error: ${sanitizeErrorSurfaceText(error)}`,
        );
        return { ok: false, message: sanitizeErrorSurfaceText(error) };
      }
    }

    messageId = `training_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    requestId = payloadRequestId ?? messageId;
    requestBody.stream_id = messageId;
    requestBody.request_id = requestId;
    abortController = new AbortController();
    activeTrainingStream = {
      messageId,
      requestId,
      abortController,
      sidecarPort: status.port,
      generation: streamGeneration,
    };
    if (!isCurrentTrainingGeneration(context, streamGeneration)) {
      return { ok: true, message: "Training stream invalidated." };
    }
    activeTrainingCardStreams.set(context, activeTrainingStream);
    await writeTrainerStreamingState(context, {
      ...createEmptyTrainerStreamingState(),
      isStreaming: true,
      streamMessageId: messageId,
    });
    if (!isCurrentTrainingCardStream(context, activeTrainingStream)) {
      return { ok: true, message: "Training stream invalidated." };
    }
    await context.workbench.postMessage({
      type: "stream/start",
      payload: { messageId },
    });

    let response: TrainingCardGenerationResponse | undefined;
    let tokenCount = 0;
    for await (const event of context.sidecarClient.fetchSSE(
      status.port,
      "/training/generate-card/stream",
      requestBody,
      { signal: abortController.signal },
    )) {
      if (!isCurrentTrainingCardStream(context, activeTrainingStream)) {
        return { ok: true, message: "Training stream invalidated." };
      }
      const parsed = parseTrainingSseJson(event);
      if (event.event === "complete") {
        const candidate = parsed?.response;
        if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
          throw new Error("Training card stream ended without a valid completion response.");
        }
        response = candidate as typeof response;
        break;
      }
      if (event.event === "error") {
        throw new Error(
          typeof parsed?.error === "string" ? parsed.error : "Training card stream failed.",
        );
      }
      const chunk = typeof parsed?.chunk === "string" ? parsed.chunk : event.data;
      if (!chunk) {
        continue;
      }
      tokenCount += 1;
      if (generateCardOwnsStreamMessageId(context, messageId)) {
        await writeTrainerStreamingState(context, {
          ...readTrainerStreamingState(context),
          isStreaming: true,
          streamedContent: readTrainerStreamingState(context).streamedContent + chunk,
        });
        if (!isCurrentTrainingCardStream(context, activeTrainingStream)) {
          return { ok: true, message: "Training stream invalidated." };
        }
        await context.workbench.postMessage({
          type: "stream/chunk",
          payload: { messageId, chunk },
        });
      }
    }
    if (!response) {
      throw new Error("Training card stream ended before completion.");
    }
    if (!isCurrentTrainingCardStream(context, activeTrainingStream)) {
      return { ok: true, message: "Training stream invalidated." };
    }
    const success = trainingCardGenerationSucceeded(response);
    const generatedCardId = readNonEmptyString(response.card?.card_id);
    const selectedCardId = readNonEmptyString(response.active_routing?.selected_card_id);
    context.outputChannel.appendLine(
      `[training] Generated ${response.card?.card_type ?? finalCardType} card from ${source} (score: ${response.score})`,
    );
    // Claim-once bind even if Coach replaced streamMessageId; ack only when we still own it.
    const shouldApplyHostState = success
      ? claimTrainingGenerateCardCompleteBind(
          context,
          requestId,
          selectedCardId ?? generatedCardId,
        )
      : !hasTrainingGenerateCardCompleteBind(context, requestId);
    if (generateCardOwnsStreamMessageId(context, messageId)) {
      await writeTrainerStreamingState(context, {
        ...readTrainerStreamingState(context),
        isStreaming: false,
        streamError: undefined,
      });
      if (!isCurrentTrainingCardStream(context, activeTrainingStream)) {
        return { ok: true, message: "Training stream invalidated." };
      }
      await context.workbench.postMessage({
        type: "stream/complete",
        payload: { messageId, tokens: tokenCount },
      });
    }
    if (shouldApplyHostState) {
      await rehydrateTrainingSummary(context, status.port);
      if (!isCurrentTrainingCardStream(context, activeTrainingStream)) {
        return { ok: true, message: "Training stream invalidated." };
      }
      await context.workbench.syncState();
    }
    return {
      ok: success,
      message: success ? undefined : readNonEmptyString(response.reason) ?? "Training card was not ready.",
      data: { ...response, success, generatedCardId, selectedCardId },
    };
  } catch (error) {
    if (isInvalidatedTrainingCardStream(context, activeTrainingStream, streamGeneration)) {
      return { ok: true, message: "Training stream invalidated." };
    }
    if (messageId && (error instanceof SidecarRequestAbortedError || abortController?.signal.aborted)) {
      if (generateCardOwnsStreamMessageId(context, messageId)) {
        await writeTrainerStreamingState(context, {
          ...readTrainerStreamingState(context),
          isStreaming: false,
          streamError: undefined,
          completionStopReason: "cancelled",
        });
        await context.workbench.postMessage({
          type: "stream/cancelled",
          payload: { messageId },
        });
      }
      return { ok: true, message: "Training stream cancelled." };
    }
    if (messageId && generateCardOwnsStreamMessageId(context, messageId)) {
      await writeTrainerStreamingState(context, {
        ...readTrainerStreamingState(context),
        isStreaming: false,
        streamError: sanitizeErrorSurfaceText(error),
      });
      await context.workbench.postMessage({
        type: "stream/error",
        payload: {
          messageId,
          error: sanitizeErrorSurfaceText(error),
          reliabilityPhase: "acked",
          reliabilityOutcome: "failure",
        },
      });
    }
    context.outputChannel.appendLine(
      `[training] Card generation error: ${sanitizeErrorSurfaceText(error)}`,
    );
    return { ok: false, message: sanitizeErrorSurfaceText(error) };
  } finally {
    if (activeTrainingStream && activeTrainingCardStreams.get(context) === activeTrainingStream) {
      activeTrainingCardStreams.delete(context);
    }
  }
}

export async function cancelTrainingCardStreamCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult | undefined> {
  const active = activeTrainingCardStreams.get(context);
  if (!active) {
    return undefined;
  }
  const requestedMessageId =
    payload && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as { messageId?: unknown }).messageId
      : undefined;
  if (
    typeof requestedMessageId === "string" &&
    requestedMessageId.trim() &&
    requestedMessageId !== active.messageId
  ) {
    return { ok: false, message: "The requested Trainer stream is no longer current." };
  }
  active.abortController.abort();
  requestTrainingStreamCancellation(context, active);
  return { ok: true, message: "Training stream cancellation requested." };
}

function parseTrainingSseJson(event: SSEMessage): Record<string, unknown> | undefined {
  try {
    const parsed: unknown = JSON.parse(event.data);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

function readNonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/**
 * §7.1 Evidence enqueue: POST /evidence/enqueue
 * Adds structured learning evidence to the pending queue.
 */
function evidenceEnqueueFailureMessage(
  error: unknown,
  waitingComposer: boolean,
  language?: string,
): string {
  if (waitingComposer) {
    return waitingComposerEnqueueFailureText(error, language);
  }
  const sanitized = sanitizeErrorSurfaceText(error, language);
  return sanitized || waitingComposerEnqueueFailureText(error, language);
}

export async function evidenceEnqueueCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as Record<string, unknown> | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const waitingComposer = p?.waitingComposer === true;
  const language = getTrainingResponseLanguage(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return {
      ok: false,
      message: evidenceEnqueueFailureMessage("Sidecar is not running.", waitingComposer, language),
    };
  }
  const summary = typeof p?.summary === "string" ? p.summary.trim() : "";
  try {
    await context.sidecarClient.postJson<unknown>(
      status.port,
      "/evidence/enqueue",
      waitingComposer
        ? {
            workspace_id: workspaceId,
            waiting_composer: true,
            summary,
          }
        : {
            workspace_id: workspaceId,
            source: typeof p?.source === "string" ? p.source : "card_result",
            summary,
            concepts: Array.isArray(p?.concepts) ? p.concepts : [],
            outcome: typeof p?.outcome === "string" ? p.outcome : "pass",
            source_card_id: typeof p?.sourceCardId === "string" ? p.sourceCardId : "",
            target_plan_stage_id: typeof p?.targetPlanStageId === "string" ? p.targetPlanStageId : "",
            confidence: typeof p?.confidence === "number" ? p.confidence : 0.75,
          },
    );
    context.outputChannel.appendLine("[evidence] Enqueued evidence item");
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true };
  } catch (error) {
    const message = evidenceEnqueueFailureMessage(error, waitingComposer, language);
    context.outputChannel.appendLine(`[evidence] Enqueue error: ${message}`);
    return { ok: false, message };
  }
}

/**
 * Evidence defer: POST /evidence/defer
 * Defers a queued evidence item for later review.
 */
export async function evidenceDeferCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as { evidenceId?: string; reason?: string } | undefined;
  const evidenceId = p?.evidenceId ?? "";
  const workspaceId = getRuntimeWorkspaceId(context);
  if (!evidenceId) {
    return { ok: false, message: "Missing evidenceId." };
  }
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  try {
    await context.sidecarClient.postJson<unknown>(status.port, "/evidence/defer", {
      workspace_id: workspaceId,
      evidence_id: evidenceId,
      reason: p?.reason ?? "",
    });
    context.outputChannel.appendLine(`[evidence] Deferred ${evidenceId}`);
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true };
  } catch (error) {
    context.outputChannel.appendLine(`[evidence] Defer error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

/**
 * §7.1 Evidence adopt: POST /evidence/adopt
 * Adopts a pending evidence item into the plan.
 */
export async function evidenceAdoptCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as { evidenceId?: string } | undefined;
  const evidenceId = p?.evidenceId ?? "";
  const workspaceId = getRuntimeWorkspaceId(context);
  if (!evidenceId) {
    return { ok: false, message: "Missing evidenceId." };
  }
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  try {
    const response = await context.sidecarClient.postJson<{
      plan_updated: boolean;
      plan_change_summary: string;
    }>(status.port, "/evidence/adopt", {
      workspace_id: workspaceId,
      evidence_id: evidenceId,
    });
    context.outputChannel.appendLine(
      `[evidence] Adopted ${evidenceId}, plan_updated=${response.plan_updated}`,
    );
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[evidence] Adopt error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

/**
 * §7.1 Evidence reject: POST /evidence/reject
 * Rejects a pending evidence item.
 */
export async function evidenceRejectCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as { evidenceId?: string; reason?: string } | undefined;
  const evidenceId = p?.evidenceId ?? "";
  const workspaceId = getRuntimeWorkspaceId(context);
  if (!evidenceId) {
    return { ok: false, message: "Missing evidenceId." };
  }
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  try {
    await context.sidecarClient.postJson<unknown>(status.port, "/evidence/reject", {
      workspace_id: workspaceId,
      evidence_id: evidenceId,
      reason: p?.reason ?? "",
    });
    context.outputChannel.appendLine(`[evidence] Rejected ${evidenceId}`);
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true };
  } catch (error) {
    context.outputChannel.appendLine(`[evidence] Reject error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

/**
 * §7.1 Evidence refresh: GET /evidence/queue
 * Refreshes the evidence queue snapshot.
 */
export async function evidenceRefreshQueueCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as { action?: string; concept?: string; scope?: string } | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  try {
    if (p?.action && p.concept) {
      // Forward structured action to server for queue mutation
      await context.sidecarClient.postJson<unknown>(
        status.port,
        "/evidence/enqueue",
        {
          workspace_id: workspaceId,
          source: "review_queue_action",
          summary: `${p.action} ${p.concept}`,
          concepts: [p.concept],
          outcome: p.action,
          source_card_id: "",
        },
      );
    }
    await context.sidecarClient.getJson<unknown>(
      status.port, `/evidence/queue?workspace_id=${encodeURIComponent(workspaceId)}`,
    );
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true };
  } catch (error) {
    return { ok: false, message: String(error) };
  }
}

/**
 * §1.10 Create flashcard: POST /training/generate-card with card_type=flash
 */
export async function flashcardCreateCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as {
    question?: string;
    answerMode?: string;
    options?: string[];
    expectedAnswer?: string;
    correctOptionIndex?: number;
    correctOptionIndices?: number[];
    correctSortOrder?: number[];
    fillBlankAnswers?: Record<number, string>;
    hintLadder?: string[];
    context?: string;
  } | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  try {
    const responseLanguage = getTrainingResponseLanguage(context);
    const requestBody: {
      source: string;
      card_type: string;
      focus_area: string;
      target_skill: string;
      context_hint: string;
      workspace_id: string;
      plan_stage_id: string;
      response_language?: string;
    } = {
      source: "coach_action_flashcard_create",
      card_type: "flash",
      focus_area: p?.question ?? p?.context ?? "",
      target_skill: p?.expectedAnswer ?? "",
      context_hint: JSON.stringify(p ?? {}),
      workspace_id: workspaceId,
      plan_stage_id: "",
    };
    if (responseLanguage) {
      requestBody.response_language = responseLanguage;
    }
    await attachLiveProviderToTrainingRequest(
      context,
      requestBody as unknown as Record<string, unknown>,
    );
    const response = await context.sidecarClient.postJson<{
      card: Record<string, unknown>;
      score: number;
    }>(status.port, "/training/generate-card", requestBody);
    context.outputChannel.appendLine(
      `[training] Created flashcard (score: ${response.score})`,
    );
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(
      `[training] Flashcard creation error: ${error}`,
    );
    return { ok: false, message: String(error) };
  }
}

function extractCardStatusPayload(
  payload: unknown,
): { cardId: string; newStatus: string; reason?: string } {
  const p = payload as { cardId?: string; newStatus?: string; reason?: string } | undefined;
  return {
    cardId: p?.cardId ?? "",
    newStatus: p?.newStatus ?? "active",
    reason: p?.reason,
  };
}

function extractGenerateCardPayload(
  payload: unknown,
): {
  source: string;
  cardType: string;
  submode: string;
  focusArea?: string;
  targetSkill?: string;
  resourceId?: string;
  prompt?: string;
  requestId?: string;
} {
  const p = payload as {
    source?: string;
    cardType?: string;
    submode?: string;
    focusArea?: string;
    targetSkill?: string;
    resourceId?: string;
    resource_id?: string;
    prompt?: string;
    requestId?: string;
    request_id?: string;
  } | undefined;
  return {
    source: p?.source ?? "conversation_gap",
    cardType: p?.cardType ?? "practice",
    submode: p?.submode ?? "",
    focusArea: p?.focusArea,
    targetSkill: p?.targetSkill,
    resourceId: p?.resourceId ?? p?.resource_id,
    prompt: p?.prompt,
    requestId: readNonEmptyString(p?.requestId) ?? readNonEmptyString(p?.request_id),
  };
}


// ------------------------------------------------------------------
// Training action command handlers
// ------------------------------------------------------------------

export async function trainingFlashcardAnswerCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as {
    cardId?: string;
    learnerAnswer?: string;
    answer?: string;
    selectedOptionIndex?: number;
    selectedOptionIndices?: number[];
    fillBlankAnswers?: Record<number, string>;
    sortOrder?: number[];
  } | undefined;
  const learnerAnswer = p?.learnerAnswer ?? p?.answer ?? '';
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const requestBody: Record<string, unknown> = {
      workspace_id: workspaceId,
      card_id: p?.cardId ?? '',
      learner_answer: learnerAnswer,
      selected_option_index: p?.selectedOptionIndex ?? null,
    };
    if (Array.isArray(p?.selectedOptionIndices)) {
      requestBody.selected_option_indices = p.selectedOptionIndices;
    }
    if (p?.fillBlankAnswers && typeof p.fillBlankAnswers === 'object') {
      requestBody.fill_blank_answers = p.fillBlankAnswers;
    }
    if (Array.isArray(p?.sortOrder)) {
      requestBody.sort_order = p.sortOrder;
    }
    const response = await context.sidecarClient.postJson<{
      correct: boolean;
      score?: number;
      detail: string;
      feedback?: Record<string, unknown>;
    }>(
      status.port,
      '/training/flashcard/answer',
      requestBody,
    );
    context.outputChannel.appendLine('[training] Flashcard answer submitted');
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Flashcard answer error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

export async function trainingTheoryDrillAnswerCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as {
    theoryDrillId?: string;
    questionId?: string;
    learnerAnswer?: string;
    answer?: string;
    selectedOptionIndex?: number;
  } | undefined;
  const learnerAnswer = p?.learnerAnswer ?? p?.answer ?? '';
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const response = await context.sidecarClient.postJson<{ ok: boolean; detail: string }>(
      status.port,
      '/training/theory-drill/answer',
      {
        workspace_id: workspaceId,
        theory_drill_id: p?.theoryDrillId ?? '',
        question_id: p?.questionId ?? '',
        learner_answer: learnerAnswer,
        selected_option_index: p?.selectedOptionIndex ?? null,
      },
    );
    context.outputChannel.appendLine('[training] Theory drill answer submitted');
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Theory drill answer error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

export async function trainingPracticeReturnCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as {
    cardId?: string;
    passed?: boolean;
    summary?: string;
    nextStep?: string;
    focusArea?: string;
    failedChecks?: string[];
    missingRequirements?: string[];
    evidenceSource?: string;
  } | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const response = await context.sidecarClient.postJson<{ ok: boolean; workspace?: unknown }>(
      status.port,
      '/training/practice-return',
      {
        workspace_id: workspaceId,
        card_id: p?.cardId ?? '',
        passed: p?.passed === true,
        summary: p?.summary ?? '',
        next_step: p?.nextStep ?? '',
        focus_area: p?.focusArea ?? '',
        failed_checks: Array.isArray(p?.failedChecks) ? p.failedChecks : [],
        missing_requirements: Array.isArray(p?.missingRequirements) ? p.missingRequirements : [],
        evidence_source: p?.evidenceSource ?? 'learner_return',
        ...reliabilityFields(payload),
      },
    );
    context.outputChannel.appendLine('[training] Practice return submitted');
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Practice return error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

export async function trainingReflectCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as { cardId?: string; handoffId?: string; reflection?: string } | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const response = await context.sidecarClient.postJson<{ ok: boolean; workspace?: unknown }>(
      status.port,
      '/training/reflect',
      {
        workspace_id: workspaceId,
        card_id: p?.cardId ?? '',
        handoff_id: p?.handoffId ?? '',
        reflection: p?.reflection ?? '',
        ...reliabilityFields(payload),
      },
    );
    if (!response.ok) {
      return { ok: false, message: 'Training reflection was not recorded.', data: response };
    }
    context.outputChannel.appendLine('[training] Reflection recorded');
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Reflection error: ${error}`);
    return leftoverCardStatusHttpFailure(error) ?? { ok: false, message: String(error) };
  }
}

export async function trainingReturnCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as { cardId?: string; handoffId?: string } | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const response = await context.sidecarClient.postJson<{ ok: boolean; workspace?: unknown }>(
      status.port,
      '/training/return',
      {
        workspace_id: workspaceId,
        card_id: p?.cardId ?? '',
        handoff_id: p?.handoffId ?? '',
        ...reliabilityFields(payload),
      },
    );
    if (!response.ok) {
      return { ok: false, message: 'Training return was not completed.', data: response };
    }
    context.outputChannel.appendLine('[training] Return completed');
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Return error: ${error}`);
    return leftoverCardStatusHttpFailure(error) ?? { ok: false, message: String(error) };
  }
}

export async function trainingReliabilityControlCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const record = readPayloadRecord(payload);
  const action =
    record.action === "recover" || record.action === "expire" || record.action === "cancel"
      ? record.action
      : "";
  if (!action) {
    return { ok: false, message: "A cancel, expire, or recover action is required." };
  }
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== "ready" || !status.port) {
    return { ok: false, message: "Sidecar is not running." };
  }
  try {
    const response = await context.sidecarClient.postJson<{ ok: boolean; workspace?: unknown }>(
      status.port,
      "/training/reliability/control",
      {
        workspace_id: workspaceId,
        action,
        card_id: typeof record.cardId === "string" ? record.cardId : "",
        command_id: typeof record.commandId === "string" ? record.commandId : "",
        ...reliabilityFields(payload),
      },
    );
    if (!response.ok) {
      return { ok: false, message: "Training reliability control was not acknowledged.", data: response };
    }
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Reliability control error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

export async function trainingDependencySkillMapActionCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as { dependencyKey?: string; action?: string; note?: string; focusItemKey?: string; relatedApi?: string; scenario?: string } | undefined;
  const action = p?.action?.trim() ?? '';
  if (["mark_practiced", "mark_applied", "mark_transferable"].includes(action)) {
    const isChinese = getTrainingResponseLanguage(context) === 'zh-CN';
    return {
      ok: false,
      message: isChinese
        ? '先验证当前文件；填写说明不会直接改变掌握记录。'
        : 'Verify the current file first. A note alone does not update your mastery.',
    };
  }
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const response = await context.sidecarClient.postJson<{
      maps: unknown[];
      history: unknown[];
      scenario_lab: unknown;
      detail?: string;
    }>(
      status.port,
      '/training/dependency-skill-map/action',
      {
        workspace_id: workspaceId,
        dependency_key: p?.dependencyKey ?? '',
        action,
        note: p?.note ?? '',
        focus_item_key: p?.focusItemKey ?? '',
        related_api: p?.relatedApi ?? '',
        scenario: p?.scenario ?? '',
      },
    );
    context.outputChannel.appendLine('[training] Dependency skill map action applied');
    await rehydrateTrainingSummary(context, status.port, workspaceId);
    await context.workbench.syncState();
    return { ok: true, message: response.detail, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Dependency skill map action error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

export async function trainingReviewQueueActionCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as {
    concept?: string;
    action?: string;
    scope?: string;
    batchLimit?: number;
    focusArea?: string;
    taskHint?: string;
    note?: string;
  } | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const response = await context.sidecarClient.postJson<{ ok: boolean; detail: string }>(
      status.port,
      '/training/review-queue/action',
      {
        workspace_id: workspaceId,
        concept: p?.concept ?? '',
        action: p?.action ?? '',
        scope: p?.scope ?? 'single',
        batch_limit: p?.batchLimit ?? 4,
        focus_area: p?.focusArea ?? '',
        task_hint: p?.taskHint ?? '',
        note: p?.note ?? '',
      },
    );
    context.outputChannel.appendLine('[training] Review queue action applied');
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Review queue action error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

export async function trainingReviewArtifactActionCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as {
    reviewArtifactId?: string;
    action?: string;
    note?: string;
    editPatch?: Record<string, unknown>;
  } | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const response = await context.sidecarClient.postJson<{ ok: boolean; detail?: string }>(
      status.port,
      '/training/review-artifact/action',
      {
        workspace_id: workspaceId,
        review_artifact_id: p?.reviewArtifactId ?? '',
        action: p?.action ?? '',
        note: p?.note ?? '',
        edit_patch: p?.editPatch ?? {},
      },
    );
    context.outputChannel.appendLine('[training] Review result recorded');
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Review result error: ${error}`);
    return { ok: false, message: String(error) };
  }
}

export async function trainingScenarioLabActionCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const p = payload as { scenarioLabId?: string; action?: string; note?: string } | undefined;
  const workspaceId = getRuntimeWorkspaceId(context);
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: 'Sidecar is not running.' };
  }
  try {
    const response = await context.sidecarClient.postJson<{ ok: boolean; detail: string }>(
      status.port,
      '/training/scenario-lab/action',
      {
        workspace_id: workspaceId,
        scenario_lab_id: p?.scenarioLabId ?? '',
        action: p?.action ?? '',
        note: p?.note ?? '',
      },
    );
    context.outputChannel.appendLine('[training] Scenario lab action applied');
    await rehydrateTrainingSummary(context, status.port);
    await context.workbench.syncState();
    return { ok: true, data: response };
  } catch (error) {
    context.outputChannel.appendLine(`[training] Scenario lab action error: ${error}`);
    return { ok: false, message: String(error) };
  }
}
