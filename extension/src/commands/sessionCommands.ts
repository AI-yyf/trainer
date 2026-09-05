import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';

import type { CommandContext } from '../core/commandContext';
import { SIDECAR_DEFAULTS } from '../core/constants';
import { SidecarHttpError, SidecarRequestAbortedError, type SSEMessage } from '../core/httpClient';
import { trainerSessionBlockReason } from '../core/runtimeRehydration';
import type {
  BootstrapData,
  CoachSettingsPayload,
  CommandExecutionResult,
  MessageAttachmentPayload,
  ProviderConfig,
  SessionMessagePayload,
  SidecarStatus,
  StreamMessagePayload,
} from '../core/types';
import {
  mergeMemorySummarySnapshot,
  mergePlanResultSnapshot,
  mergeSessionStartSnapshot,
  mergeSessionMessageSnapshot,
  mergeTaskResultSnapshot,
} from '../core/workbenchData';
import {
  getRuntimeWorkspaceContext,
  getRuntimeWorkspaceId,
  getWorkspaceId,
} from './workspaceContext';
import {
  describeProviderImageInputState,
  describeProviderSendState,
  providerTransportIsConfigured,
} from '../../../shared/src/providerStatus';
import {
  normalizeProviderProtocol,
  providerProtocolFamily,
} from '../../../shared/src/providerProtocols';
import { stripHostLastTestSecrets } from '../../../shared/src/hostLastTestGovernance';
import {
  buildWorkspaceFileSnapshot,
  noteRequestedWorkspaceFileToolResult,
  noteRequestedWorkspaceFilesFromSessionResponse,
} from '../core/workspaceFileSnapshot';
import { normalizeRecoveredPlanResumeTurn } from '../../../shared/src/planOrientationGovernance';
import {
  evaluateProviderModelPolicy,
  type ProviderModelPolicyEvaluation,
} from '../../../shared/src/providerModelPolicy';
import { normalizeResourceSearchMode } from '../../../shared/src/resourceSearch';
import { shouldAttachCurrentFile } from '../../../shared/src/sendIntelligence';
import {
  createEmptyTrainerStreamingState,
  normalizeTrainerStreamingState,
  upsertTrainerToolActivity,
  type TrainerStreamingState,
} from '../../../shared/src/protocol';
import {
  mapStreamStatusToReliabilityPhase,
  operationReliabilityLooksSuccessful,
  readOperationReliability,
  type OperationReliabilityOutcome,
  type OperationReliabilityPhase,
} from '../../../shared/src/operationReliabilityGovernance';
import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';
import {
  sanitizeErrorSurfaceText,
  sanitizeHostToolResult,
} from '../../../shared/src/errorSurfaceSanitizer';
import { normalizeProviderCapabilityTruth } from '../../../shared/src/providerTest';
import {
  asNonEmptyString,
  asRecord as asTrainingRecord,
  buildMemorySummaryQueryPath,
  resolveExplicitTrainingRestoreStepFromSummary,
  resolveLatestTrainingNextHopFromSummary,
} from './trainingRestoreGovernance';
import {
  cancelTrainingCardStreamCommand,
  invalidateActiveTrainingCardStream,
} from './trainingCommands';

const activeCoachStreamContexts = new WeakSet<CommandContext>();
type ActiveCoachStream = {
  messageId: string;
  abortController: AbortController;
  sidecarPort: number;
  generation: number;
};
const activeCoachStreams = new WeakMap<CommandContext, ActiveCoachStream>();
const streamGenerations = new WeakMap<CommandContext, number>();

function nextStreamGeneration(context: CommandContext): number {
  const generation = (streamGenerations.get(context) ?? 0) + 1;
  streamGenerations.set(context, generation);
  return generation;
}

function isCurrentCoachStream(
  context: CommandContext,
  stream: ActiveCoachStream,
): boolean {
  return (
    streamGenerations.get(context) === stream.generation &&
    activeCoachStreams.get(context) === stream &&
    !stream.abortController.signal.aborted
  );
}

function isWorkspaceInvalidatedCoachStream(
  context: CommandContext,
  stream: ActiveCoachStream,
): boolean {
  return (
    streamGenerations.get(context) !== stream.generation ||
    activeCoachStreams.get(context) !== stream
  );
}

/**
 * Invalidates all Trainer SSE streams before a workspace/session switch.
 *
 * The generation bump makes any already-buffered coach SSE events stale even
 * when the async iterator yields one more event after AbortController.abort().
 * Training card streams are cancelled through their existing command-local
 * controller.
 */
export async function invalidateActiveTrainerStreams(
  context: CommandContext,
): Promise<void> {
  nextStreamGeneration(context);

  const activeCoach = activeCoachStreams.get(context);
  activeCoachStreamContexts.delete(context);
  if (activeCoach) {
    activeCoachStreams.delete(context);
    activeCoach.abortController.abort();
    void context.sidecarClient
      .postJson(
        activeCoach.sidecarPort,
        '/stream/cancel',
        { stream_id: activeCoach.messageId },
        { timeoutMs: 2000 },
      )
      .catch(() => {
        // Local abort remains the fallback when the sidecar is unavailable.
      });
  }

  invalidateActiveTrainingCardStream(context);
}

type ResourceComposerIntentPayload = {
  mode: 'locate' | 'download' | 'organize' | 'cards';
  resourceIds?: string[];
};

type ResourceComposerSessionMessagePayload = SessionMessagePayload & {
  resourceComposerIntent?: ResourceComposerIntentPayload;
};

type ResourceComposerStreamMessagePayload = StreamMessagePayload & {
  resourceComposerIntent?: ResourceComposerIntentPayload;
};

type ProviderSendConfig = Pick<
  ProviderConfig,
  'name' | 'baseUrl' | 'model' | 'credentialMode' | 'allowedModels' | 'deniedModels'
>;

/** Host-only organize confirm: pending proposal from tool result; armed only by user confirm click. */
const resourceOrganizationPendingByContext = new WeakMap<object, boolean>();
const resourceOrganizationArmedByContext = new WeakMap<object, boolean>();
/** True while confirmResourceOrganizationCommand awaits its stamp turn. */
const resourceOrganizationConfirmInFlightByContext = new WeakMap<object, boolean>();

function asToolResultRecord(result: unknown): Record<string, unknown> | undefined {
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    return undefined;
  }
  return result as Record<string, unknown>;
}

function organizationProposalOperationCount(result: Record<string, unknown>): number | undefined {
  const operations = result.operations;
  return Array.isArray(operations) ? operations.length : undefined;
}

/**
 * Track organize_resources proposal/commit from agent tool results.
 * Returns a webview payload when pending state changes; null when irrelevant.
 */
export function noteResourceOrganizationToolResult(
  context: CommandContext,
  name: unknown,
  result: unknown,
): { pending: boolean; operationCount?: number } | null {
  if (String(name ?? '').trim() !== 'organize_resources') {
    return null;
  }
  const record = asToolResultRecord(result);
  if (!record) {
    return null;
  }
  if (record.committed === true) {
    resourceOrganizationPendingByContext.set(context, false);
    resourceOrganizationArmedByContext.set(context, false);
    return { pending: false };
  }
  // Fail-closed: stamp-without-pending / cancel-won must not resurrect confirm UI.
  if (record.ok === false && record.requires_confirmation === true) {
    resourceOrganizationPendingByContext.set(context, false);
    resourceOrganizationArmedByContext.set(context, false);
    return { pending: false };
  }
  if (record.ok === true && record.requires_confirmation === true) {
    resourceOrganizationPendingByContext.set(context, true);
    return {
      pending: true,
      operationCount: organizationProposalOperationCount(record),
    };
  }
  return null;
}

/**
 * Non-stream `/session/message` and `/turn` mirror stream tool_result handling:
 * surface the same pending confirm proposal when organize_resources requires confirmation.
 */
export function noteResourceOrganizationFromSessionResponse(
  context: CommandContext,
  response: unknown,
  responseLanguage?: string,
): { pending: boolean; operationCount?: number } | null {
  let latest: { pending: boolean; operationCount?: number } | null = null;
  const consider = (name: unknown, result: unknown): void => {
    const sanitized = sanitizeHostToolResult(result, responseLanguage);
    const noted = noteResourceOrganizationToolResult(context, name, sanitized);
    noteRequestedWorkspaceFileToolResult(context, name, sanitized);
    if (noted) {
      latest = noted;
    }
  };

  const visitToolEvents = (events: unknown): void => {
    if (!Array.isArray(events)) {
      return;
    }
    for (const event of events) {
      const record = asToolResultRecord(event);
      if (!record || String(record.type ?? '').trim() !== 'tool_result') {
        continue;
      }
      consider(record.name ?? record.tool_name, record.result);
    }
  };

  const visitParts = (parts: unknown): void => {
    if (!Array.isArray(parts)) {
      return;
    }
    for (const part of parts) {
      const record = asToolResultRecord(part);
      if (!record || String(record.type ?? '').trim() !== 'tool_result') {
        continue;
      }
      consider(record.name, record.result);
    }
  };

  const root = asToolResultRecord(response);
  if (!root) {
    return null;
  }

  const agentMeta =
    asToolResultRecord(root.agent_meta) ??
    asToolResultRecord(root.agentMeta) ??
    asToolResultRecord(root.agent);
  if (agentMeta) {
    visitToolEvents(agentMeta.tool_events ?? agentMeta.toolEvents);
  }

  const reply = asToolResultRecord(root.reply);
  const replyMetadata = asToolResultRecord(reply?.metadata);
  if (replyMetadata) {
    visitParts(replyMetadata.parts);
  }

  const snapshot = asToolResultRecord(root.snapshot);
  const messages = snapshot?.messages;
  if (Array.isArray(messages)) {
    for (const message of messages) {
      const record = asToolResultRecord(message);
      if (!record) {
        continue;
      }
      visitParts(record.parts);
      const metadata = asToolResultRecord(record.metadata);
      if (metadata) {
        visitParts(metadata.parts);
      }
    }
  }

  return latest;
}

/** Arm one-shot host stamp only when a proposal is pending. Webview cannot self-arm. */
export function armResourceOrganizationConfirm(context: CommandContext): boolean {
  if (resourceOrganizationPendingByContext.get(context) !== true) {
    return false;
  }
  resourceOrganizationArmedByContext.set(context, true);
  return true;
}

export function cancelResourceOrganizationConfirm(context: CommandContext): void {
  resourceOrganizationPendingByContext.set(context, false);
  resourceOrganizationArmedByContext.set(context, false);
}

export function markResourceOrganizationConfirmInFlight(
  context: CommandContext,
  inFlight: boolean,
): void {
  resourceOrganizationConfirmInFlightByContext.set(context, inFlight);
}

export function isResourceOrganizationConfirmInFlight(context: CommandContext): boolean {
  return resourceOrganizationConfirmInFlightByContext.get(context) === true;
}

export function isResourceOrganizationPending(context: CommandContext): boolean {
  return resourceOrganizationPendingByContext.get(context) === true;
}

/**
 * Consume the host-armed stamp for the outgoing sidecar request.
 * Fail-closed: webview payload flags are ignored; only an armed host click stamps.
 */
export function consumeResourceOrganizationConfirmed(context: CommandContext): boolean {
  if (resourceOrganizationArmedByContext.get(context) !== true) {
    return false;
  }
  resourceOrganizationArmedByContext.set(context, false);
  return true;
}

async function notifyResourceOrganizationPending(
  context: CommandContext,
  payload: { pending: boolean; operationCount?: number },
): Promise<void> {
  await context.workbench.postMessage({
    type: 'resourceOrganization/pending',
    payload,
  });
}

function trainerWorkspaceSessionGate(
  context: CommandContext,
): CommandExecutionResult | undefined {
  const blockReason = trainerSessionBlockReason(context);
  if (!blockReason) {
    return undefined;
  }
  return {
    ok: false,
    message: blockReason,
  };
}

type WorkspaceCoachSettings = NonNullable<BootstrapData['memory']['workspace']>;
type WorkspaceCoachDefaults = NonNullable<WorkspaceCoachSettings['coachDefaults']>;

function mergeLocalCoachSettings(
  workspace: WorkspaceCoachSettings | undefined,
  settings: CoachSettingsPayload | undefined,
): WorkspaceCoachSettings {
  const next: WorkspaceCoachSettings = { ...(workspace ?? {}) };
  if (!settings) {
    return next;
  }

  if (settings.responseLanguage) {
    next.responseLanguage = settings.responseLanguage;
  }
  if (settings.answerMode) {
    next.answerMode = settings.answerMode;
  }
  if (settings.resourceSearchMode) {
    next.resourceSearchMode = normalizeResourceSearchMode(settings.resourceSearchMode);
  }
  if (settings.followCurrentFile !== undefined) {
    next.followCurrentFile = settings.followCurrentFile;
  }
  if (settings.contextDetail) {
    next.contextDetail = settings.contextDetail;
  }
  if (settings.includeCurrentFile !== undefined) {
    next.includeCurrentFile = settings.includeCurrentFile;
  }
  if (settings.includeSelection !== undefined) {
    next.includeSelection = settings.includeSelection;
  }
  if (settings.includeDiagnostics !== undefined) {
    next.includeDiagnostics = settings.includeDiagnostics;
  }
  if (settings.includeRelatedFiles !== undefined) {
    next.includeRelatedFiles = settings.includeRelatedFiles;
  }

  const incomingDefaults = settings.coachDefaults;
  if (!incomingDefaults) {
    return next;
  }

  const currentDefaults = next.coachDefaults ?? {};
  const mergedDefaults: WorkspaceCoachDefaults = { ...currentDefaults };
  let defaultsChanged = false;
  if (incomingDefaults.memoryScope) {
    mergedDefaults.memoryScope = incomingDefaults.memoryScope;
    defaultsChanged = true;
  }
  if (incomingDefaults.workingSetMode) {
    mergedDefaults.workingSetMode = incomingDefaults.workingSetMode;
    defaultsChanged = true;
  }
  if (incomingDefaults.reviewCadence) {
    mergedDefaults.reviewCadence = incomingDefaults.reviewCadence;
    defaultsChanged = true;
  }
  if (incomingDefaults.reviewReminderMode) {
    mergedDefaults.reviewReminderMode = incomingDefaults.reviewReminderMode;
    defaultsChanged = true;
  }

  const incomingToggles = incomingDefaults.workspaceMemoryToggles;
  if (incomingToggles) {
    const mergedToggles = { ...(currentDefaults.workspaceMemoryToggles ?? {}) };
    let togglesChanged = false;
    if (incomingToggles.decisions !== undefined) {
      mergedToggles.decisions = incomingToggles.decisions;
      togglesChanged = true;
    }
    if (incomingToggles.patterns !== undefined) {
      mergedToggles.patterns = incomingToggles.patterns;
      togglesChanged = true;
    }
    if (incomingToggles.resources !== undefined) {
      mergedToggles.resources = incomingToggles.resources;
      togglesChanged = true;
    }
    if (togglesChanged) {
      mergedDefaults.workspaceMemoryToggles = mergedToggles;
      defaultsChanged = true;
    }
  }

  if (defaultsChanged) {
    next.coachDefaults = mergedDefaults;
  }
  return next;
}

function providerSendGuard(
  context: CommandContext,
  providerConfig?: ProviderSendConfig,
  apiKey?: string,
  responseLanguage?: string,
  options?: {
    deferReplyProof?: boolean;
  },
): { blocked: boolean; message?: string } {
  const language = resolveProviderGuardLanguage(context, responseLanguage);
  if (providerConfig) {
    const modelPolicy = evaluateProviderModelPolicy(providerConfig.model, providerConfig);
    if (!modelPolicy.allowed) {
      return {
        blocked: true,
        message: providerModelPolicySendGuardMessage(modelPolicy, language),
      };
    }
  }

  const currentView = context.getHostState().bootstrap.providerConfig;
  const hasCurrentProviderShape =
    currentView.configured !== undefined ||
    currentView.apiKeyConfigured !== undefined ||
    currentView.modelListStatus !== undefined ||
    Boolean(currentView.name || currentView.baseUrl || currentView.model);
  const provider =
    hasCurrentProviderShape
      ? {
          ...currentView,
          configured: providerTransportIsConfigured({
            name: currentView.name ?? providerConfig?.name,
            baseUrl: currentView.baseUrl ?? providerConfig?.baseUrl,
            model: currentView.model ?? providerConfig?.model,
          }),
          apiKeyConfigured:
            currentView.apiKeyConfigured ??
            (providerUsesWorkspaceSecret(providerConfig) || Boolean(apiKey?.trim())),
          model: currentView.model ?? providerConfig?.model ?? '',
          availableModels: currentView.availableModels ?? [],
          modelListStatus: currentView.modelListStatus ?? 'idle',
        }
      : {
          name: currentView.name ?? providerConfig?.name,
          baseUrl: currentView.baseUrl ?? providerConfig?.baseUrl,
          configured: providerTransportIsConfigured({
            name: currentView.name ?? providerConfig?.name,
            baseUrl: currentView.baseUrl ?? providerConfig?.baseUrl,
            model: currentView.model ?? providerConfig?.model,
          }),
          apiKeyConfigured:
            providerUsesWorkspaceSecret(providerConfig) || Boolean(apiKey?.trim()),
          model: currentView.model ?? providerConfig?.model ?? '',
          resolvedModel: currentView.resolvedModel ?? providerConfig?.model,
          availableModels: currentView.availableModels ?? [],
          modelListStatus: currentView.modelListStatus ?? 'idle',
          modelListDetail: currentView.modelListDetail,
          modelErrorCategory: currentView.modelErrorCategory,
          modelRetryable: currentView.modelRetryable,
          lastTestResult: currentView.lastTestResult,
        };
  const sendState = describeProviderSendState(
    provider,
    language,
  );

  // Transport-level problems (no connection, no key, unusable model list, a
  // failing probe) still stop the send here. Proof *gaps* — a missing test or
  // a past success that went stale — are settled downstream instead: the
  // non-stream path runs an automatic /provider/test preflight, and the
  // stream path lets the stream itself re-verify the connection.
  if (
    sendState.blocked &&
    !isDownstreamProvableSendBlock(provider, sendState, options?.deferReplyProof === true)
  ) {
    return {
      blocked: true,
      message: sendState.reason,
    };
  }

  return {
    blocked: false,
    message: sendState.blocked ? undefined : sendState.reason,
  };
}

/**
 * True when describeProviderSendState blocked only because reply proof is
 * missing or stale — a state the caller can resolve by probing (non-stream)
 * or by running the real stream (deferReplyProof). Hard failures of a past
 * probe (ok === false), language-mismatched proofs on a Chinese surface, and
 * transport/model-list problems stay blocking.
 */
function isDownstreamProvableSendBlock(
  provider: {
    configured?: boolean;
    apiKeyConfigured?: boolean;
    protocol?: string;
    modelListStatus?: string;
    lastTestResult?: { ok?: boolean };
  },
  sendState: { blocked: boolean; status?: string },
  deferReplyProof: boolean,
): boolean {
  if (!sendState.blocked || sendState.status !== 'blocked_error') {
    return false;
  }
  if (provider.configured !== true || provider.apiKeyConfigured !== true) {
    return false;
  }
  const declaredProtocol = typeof provider.protocol === 'string' ? provider.protocol.trim() : '';
  if (declaredProtocol && !normalizeProviderProtocol(declaredProtocol)) {
    return false;
  }
  if (provider.modelListStatus === 'error') {
    return false;
  }
  const lastTest = provider.lastTestResult;
  if (lastTest === undefined) {
    // No proof at all — the non-stream preflight probes before the turn.
    return true;
  }
  // A past success that went stale, targeted another connection, or skipped
  // the Chinese integrity probe only re-proves itself through the real stream.
  return lastTest.ok === true && deferReplyProof;
}

function providerModelPolicySendGuardMessage(
  evaluation: ProviderModelPolicyEvaluation,
  language: ComposerLanguage,
): string {
  if (evaluation.reason === 'allowed') {
    return 'This connection is ready to send.';
  }

  const model = evaluation.model || 'the current model';
  const messages: Record<
    Exclude<ProviderModelPolicyEvaluation['reason'], 'allowed'>,
    Record<ComposerLanguage, string>
  > = {
    empty: {
      'zh-CN': '这个连接还没有选择模型。请到“设置”中选择一个模型后再发送。',
      'en-US': 'This connection does not have a model selected yet. Open Settings and choose one before sending.',
      'es-ES': 'Esta conexión todavía no tiene un modelo seleccionado. Abre Configuración y elige uno antes de enviar.',
      'fr-FR': 'Cette connexion n’a pas encore de modèle sélectionné. Ouvrez les paramètres et choisissez-en un avant d’envoyer.',
      'de-DE': 'Für diese Verbindung ist noch kein Modell ausgewählt. Öffne die Einstellungen und wähle vor dem Senden eines aus.',
      'ja-JP': 'この接続にはまだモデルが選ばれていません。送信する前に設定でモデルを選んでください。',
      'ko-KR': '이 연결에는 아직 선택된 모델이 없습니다. 보내기 전에 설정에서 모델을 선택하세요.',
      'pt-BR': 'Esta conexão ainda não tem um modelo selecionado. Abra Configurações e escolha um antes de enviar.',
    },
    denied: {
      'zh-CN': `当前模型“${model}”已被这个连接禁用。请到“设置”中选择其他模型后再发送。`,
      'en-US': `The current model, “${model}”, is blocked for this connection. Open Settings and choose another model before sending.`,
      'es-ES': `El modelo actual, “${model}”, está bloqueado para esta conexión. Abre Configuración y elige otro modelo antes de enviar.`,
      'fr-FR': `Le modèle actuel, « ${model} », est bloqué pour cette connexion. Ouvrez les paramètres et choisissez un autre modèle avant d’envoyer.`,
      'de-DE': `Das aktuelle Modell „${model}“ ist für diese Verbindung gesperrt. Öffne die Einstellungen und wähle vor dem Senden ein anderes Modell aus.`,
      'ja-JP': `現在のモデル「${model}」はこの接続では使えません。送信する前に設定で別のモデルを選んでください。`,
      'ko-KR': `현재 모델 “${model}”은(는) 이 연결에서 사용할 수 없습니다. 보내기 전에 설정에서 다른 모델을 선택하세요.`,
      'pt-BR': `O modelo atual, “${model}”, está bloqueado para esta conexão. Abra Configurações e escolha outro modelo antes de enviar.`,
    },
    not_allowed: {
      'zh-CN': `当前模型“${model}”不在这个连接允许使用的模型列表中。请到“设置”中选择允许的模型后再发送。`,
      'en-US': `The current model, “${model}”, is not enabled for this connection. Open Settings and choose a model from the allowed list before sending.`,
      'es-ES': `El modelo actual, “${model}”, no está habilitado para esta conexión. Abre Configuración y elige un modelo de la lista permitida antes de enviar.`,
      'fr-FR': `Le modèle actuel, « ${model} », n’est pas activé pour cette connexion. Ouvrez les paramètres et choisissez un modèle de la liste autorisée avant d’envoyer.`,
      'de-DE': `Das aktuelle Modell „${model}“ ist für diese Verbindung nicht freigegeben. Öffne die Einstellungen und wähle vor dem Senden ein Modell aus der erlaubten Liste.`,
      'ja-JP': `現在のモデル「${model}」はこの接続では許可されていません。送信する前に設定で許可されたモデルを選んでください。`,
      'ko-KR': `현재 모델 “${model}”은(는) 이 연결에서 허용되지 않았습니다. 보내기 전에 설정에서 허용된 모델을 선택하세요.`,
      'pt-BR': `O modelo atual, “${model}”, não está habilitado para esta conexão. Abra Configurações e escolha um modelo da lista permitida antes de enviar.`,
    },
  };
  return messages[evaluation.reason][language];
}

function providerImageInputGuard(
  context: CommandContext,
  providerConfig?: {
    model?: string;
    credentialMode?: string;
    protocol?: ProviderConfig['protocol'];
    capabilities?: {
      vision?: boolean;
      tools?: boolean;
    };
  },
  apiKey?: string,
  responseLanguage?: string,
): { blocked: boolean; message?: string } {
  const currentView = context.getHostState().bootstrap.providerConfig;
  const hasCurrentProviderShape =
    currentView.configured !== undefined ||
    currentView.apiKeyConfigured !== undefined ||
    currentView.modelListStatus !== undefined ||
    Boolean(currentView.name || currentView.baseUrl || currentView.model);
  const provider =
    hasCurrentProviderShape
      ? {
          ...currentView,
          configured: providerTransportIsConfigured({
            name: currentView.name,
            baseUrl: currentView.baseUrl,
            model: currentView.model ?? providerConfig?.model,
          }),
          apiKeyConfigured:
            currentView.apiKeyConfigured ??
            (providerUsesWorkspaceSecret(providerConfig) || Boolean(apiKey?.trim())),
          model: currentView.model ?? providerConfig?.model ?? '',
          availableModels: currentView.availableModels ?? [],
          modelListStatus: currentView.modelListStatus ?? 'idle',
          capabilities: currentView.capabilities ?? providerConfig?.capabilities,
        }
      : {
          configured: providerTransportIsConfigured({
            name: currentView.name,
            baseUrl: currentView.baseUrl,
            model: providerConfig?.model ?? currentView.model,
          }),
          apiKeyConfigured:
            providerUsesWorkspaceSecret(providerConfig) || Boolean(apiKey?.trim()),
          model: providerConfig?.model ?? '',
          resolvedModel: currentView.resolvedModel ?? providerConfig?.model,
          availableModels: currentView.availableModels ?? [],
          modelListStatus: currentView.modelListStatus ?? 'idle',
          modelListDetail: currentView.modelListDetail,
          modelErrorCategory: currentView.modelErrorCategory,
          modelRetryable: currentView.modelRetryable,
          protocol: currentView.protocol ?? providerConfig?.protocol,
          capabilities: currentView.capabilities ?? providerConfig?.capabilities,
        };
  const imageState = describeProviderImageInputState(
    provider,
    resolveProviderGuardLanguage(context, responseLanguage),
  );
  return {
    blocked: !imageState.supported,
    message: imageState.reason ?? imageState.detail,
  };
}

function providerHasVerifiedStreamingProbe(
  provider: Pick<NonNullable<ReturnType<CommandContext['getHostState']>['bootstrap']['providerConfig']>, 'lastTestResult'>,
): boolean {
  const lastTest = provider.lastTestResult;
  const streamingEvidence = lastTest?.capabilityEvidence?.find((entry) => {
    const name = entry.name.trim().toLowerCase();
    return name === 'streaming' || name === 'stream';
  });

  return (
    lastTest?.ok === true &&
    lastTest.streamingReady === true &&
    lastTest.streamProbeStatus === 'verified' &&
    streamingEvidence?.state === 'verified' &&
    streamingEvidence.observed === true
  );
}

function streamingCapabilityBlockReason(language: ComposerLanguage): string {
  return language === 'zh-CN'
    ? '\u5f53\u524d\u8fde\u63a5\u8fd8\u6ca1\u6709\u9a8c\u8bc1\u771f\u5b9e\u6d41\u5f0f\u8f93\u51fa\u3002\u8bf7\u5728\u8bbe\u7f6e\u4e2d\u91cd\u65b0\u6d4b\u8bd5 Provider\uff0c\u786e\u8ba4\u80fd\u89c2\u5bdf\u5230\u589e\u91cf\u7247\u6bb5\u540e\u518d\u5bf9\u8bdd\u3002'
    : 'This connection has not verified real incremental output yet. Retest the provider in Settings and continue after a visible stream chunk is observed.';
}

function streamCapabilityDecision(
  context: CommandContext,
): 'verified' | 'unusable-honest' | 'unverified-stream' {
  const lastTest = context.getHostState().bootstrap.providerConfig.lastTestResult;
  if (providerHasVerifiedStreamingProbe({ lastTestResult: lastTest })) {
    return 'verified';
  }
  if (lastTest?.ok === true) {
    return 'unverified-stream';
  }
  return 'unusable-honest';
}

function resolveProviderGuardLanguage(
  context: CommandContext,
  responseLanguage?: string,
): ComposerLanguage {
  if (isComposerLanguage(responseLanguage)) {
    return responseLanguage;
  }

  const workspaceLanguage = context.getHostState().bootstrap.memory.workspace?.responseLanguage;
  return isComposerLanguage(workspaceLanguage) ? workspaceLanguage : 'en-US';
}

function streamAlreadyInProgressMessage(language: ComposerLanguage): string {
  const messages: Record<ComposerLanguage, string> = {
    'zh-CN': 'Trainer 正在处理上一条消息。等它结束后再发送。',
    'en-US': 'Trainer is still working on the previous message. Send the next one when it finishes.',
    'es-ES': 'Trainer sigue trabajando en el mensaje anterior. Envía el siguiente cuando termine.',
    'fr-FR': 'Trainer traite encore le message précédent. Envoyez le suivant une fois terminé.',
    'de-DE': 'Trainer bearbeitet noch die vorherige Nachricht. Sende die nächste, wenn sie fertig ist.',
    'ja-JP': 'Trainer は前のメッセージを処理中です。完了してから次のメッセージを送ってください。',
    'ko-KR': 'Trainer가 이전 메시지를 처리하고 있습니다. 완료된 뒤 다음 메시지를 보내세요.',
    'pt-BR': 'O Trainer ainda está trabalhando na mensagem anterior. Envie a próxima quando terminar.',
  };
  return messages[language];
}

function frozenPlanGenerationMessage(language: ComposerLanguage): string {
  const messages: Record<ComposerLanguage, string> = {
    'zh-CN': '这条计划已冻结。先恢复为可编辑状态，再生成新的版本。',
    'en-US': 'This plan is frozen. Resume it before creating a new version.',
    'es-ES': 'Este plan esta congelado. Reanúdalo antes de crear una nueva versión.',
    'fr-FR': 'Ce plan est gelé. Reprenez-le avant de créer une nouvelle version.',
    'de-DE': 'Dieser Plan ist eingefroren. Setzen Sie ihn fort, bevor Sie eine neue Version erstellen.',
    'ja-JP': 'この計画は固定されています。新しい版を作る前に、再開してください。',
    'ko-KR': '이 계획은 고정되어 있습니다. 새 버전을 만들기 전에 다시 시작하세요.',
    'pt-BR': 'Este plano está congelado. Retome-o antes de criar uma nova versão.',
  };
  return messages[language];
}

async function ensureCoachProviderReady(
  context: CommandContext,
  action: string,
  options?: {
    probeMessage?: string;
    responseLanguage?: string;
    deferReplyProof?: boolean;
  },
): Promise<CommandExecutionResult | undefined> {
  const providerConfig = context.providerStore.getConfig();
  const apiKey = await context.providerStore.getApiKey();
  if (!providerConfig) {
    return {
      ok: false,
      message: `Trainer needs a saved provider before it can ${action}.`,
    };
  }

  if (!providerUsesWorkspaceSecret(providerConfig) && !apiKey?.trim()) {
    return {
      ok: false,
      message: `Trainer needs a saved provider and API key before it can ${action}.`,
    };
  }

  const sendGuard = providerSendGuard(
    context,
    providerConfig,
    apiKey,
    options?.responseLanguage,
    { deferReplyProof: options?.deferReplyProof === true },
  );
  if (sendGuard.blocked) {
    return {
      ok: false,
      message: sendGuard.message ?? `Trainer cannot ${action} until the provider state is ready.`,
    };
  }

  if (options?.deferReplyProof) {
    return undefined;
  }

  return ensureCoachReplyProof(context, providerConfig, apiKey, action, options);
}

type ProviderFailureMeta = {
  category?: string;
  statusCode?: number;
  retryable?: boolean;
  detail: string;
};

type StreamAgentCompletionMeta = {
  agentic: boolean;
  summary?: string;
  nextStep?: string;
  stopReason?: string;
  toolCount?: number;
};

type CoachCheckpointScope = {
  workspaceId: string;
  sessionId: string;
};

type LatestCoachCheckpoint = {
  checkpointId: string;
  sessionId: string;
  createdAt?: string;
  nextStep?: string;
};

function currentStreamingState(context: CommandContext): TrainerStreamingState {
  return normalizeTrainerStreamingState(context.getStreamingState());
}

async function updateStreamingState(
  context: CommandContext,
  updater: (state: TrainerStreamingState) => TrainerStreamingState,
): Promise<TrainerStreamingState> {
  const next = updater(currentStreamingState(context));
  await context.setStreamingState(next);
  return next;
}

type ProviderTestResponse = {
  ok?: boolean;
  status?: string;
  provider_name?: string;
  detail?: string;
  error_category?: string;
  retryable?: boolean;
  status_code?: number;
  capability_evidence?: unknown;
  capabilityEvidence?: unknown;
  tools_ready?: boolean;
  toolsReady?: boolean;
  tool_probe_status?: unknown;
  toolProbeStatus?: unknown;
  streaming_ready?: boolean;
  streamingReady?: boolean;
  stream_probe_status?: unknown;
  streamProbeStatus?: unknown;
};

type ResumeProjectLanePayload = {
  workspaceId: string;
  workspacePath?: string;
  workspaceLabel?: string;
  resumeSessionId?: string;
  sessionId?: string;
  targetView?: string;
  activeView?: string;
  targetTrainingSubmode?: string;
  trainingSubmode?: string;
  trainingRestoreTarget?: string;
  theoryDrillId?: string;
  scenarioLabId?: string;
  reviewArtifactId?: string;
  resourceSurface?: string;
  resourceId?: string;
  sandboxPath?: string;
  resourceDetailId?: string;
  previewPath?: string;
  resumeReason?: string;
  focusArea?: string;
  currentStageTitle?: string;
  latestSummary?: string;
};

function normalizeErrorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function userFacingErrorText(error: unknown, language?: string): string {
  return sanitizeErrorSurfaceText(normalizeErrorText(error), language);
}

/** Stable marker webview maps to local 8-lang live-plan gate copy (never raw sidecar prose). */
function livePlanTaskGateCommandFailure(error: unknown): CommandExecutionResult | undefined {
  if (!(error instanceof SidecarHttpError) || error.statusCode !== 409) {
    return undefined;
  }
  const detail = `${error.metadata.detail ?? ''} ${error.message}`.toLowerCase();
  // Only live-plan leftover/no-live gates — not frozen-plan or other 409 conflicts.
  if (!/leftover-not-live|no live learning plan/.test(detail)) {
    return undefined;
  }
  const kind = /leftover/.test(detail) ? 'leftover' : 'no_live';
  return {
    ok: false,
    message: `[[trainer-live-plan-task-gate:${kind}]]`,
  };
}

function detailLooksLikeLanguageCorruption(detail: string | undefined): boolean {
  const lowered = detail?.toLowerCase() ?? '';
  return /question marks|corrupted chinese input|trainer cannot safely coach in zh-cn|model never saw your actual sentence/.test(
    lowered,
  );
}

function extractStatusCode(detail: string): number | undefined {
  const match = detail.match(/\((\d{3})\)/);
  if (match) {
    const value = Number.parseInt(match[1] ?? '', 10);
    if (Number.isFinite(value)) {
      return value;
    }
  }
  const looseMatch = detail.match(/\b(401|403|408|429|500|502|503|504)\b/);
  if (looseMatch) {
    const value = Number.parseInt(looseMatch[1] ?? '', 10);
    if (Number.isFinite(value)) {
      return value;
    }
  }
  return undefined;
}

function classifyProviderFailure(detail: string): ProviderFailureMeta {
  const normalized = detail.trim();
  const lowered = normalized.toLowerCase();
  const statusCode = extractStatusCode(normalized);

  if (
    statusCode === 401 ||
    statusCode === 403 ||
    /invalid[_\s-]?api[_\s-]?key|incorrect api key|unauthorized|forbidden|permission denied|not authorized|invalid_key_or_permission/.test(
      lowered,
    )
  ) {
    return {
      category: 'invalid_key_or_permission',
      statusCode: statusCode ?? (lowered.includes('403') ? 403 : 401),
      retryable: false,
      detail: normalized,
    };
  }

  if (
    /model_unsupported|unsupported model|model_not_found|does not exist.*model|not supported model/.test(
      lowered,
    )
  ) {
    return {
      category: 'model_unsupported',
      statusCode: statusCode ?? 400,
      retryable: false,
      detail: normalized,
    };
  }

  if (statusCode === 429 || /rate limit|too many requests/.test(lowered)) {
    return {
      category: 'rate_limit',
      statusCode: statusCode ?? 429,
      retryable: true,
      detail: normalized,
    };
  }

  if (statusCode === 408 || /timeout|timed out/.test(lowered)) {
    return {
      category: 'timeout',
      statusCode: statusCode ?? 408,
      retryable: true,
      detail: normalized,
    };
  }

  if (
    /language_probe_inconclusive|language integrity probe was inconclusive|could not fully verify zh-cn input integrity/.test(
      lowered,
    )
  ) {
    return {
      category: 'language_probe_inconclusive',
      statusCode,
      retryable: false,
      detail: normalized,
    };
  }

  if (
    /language_corruption|question marks|corrupted chinese input|trainer cannot safely coach in zh-cn/.test(
      lowered,
    )
  ) {
    return {
      category: 'language_corruption',
      statusCode,
      retryable: false,
      detail: normalized,
    };
  }

  if (
    /empty_response|empty content|no final coaching reply content|reasoning-only content|final reply content/.test(
      lowered,
    )
  ) {
    return {
      category: 'empty_response',
      statusCode,
      retryable: false,
      detail: normalized,
    };
  }

  if (
    /network|connection refused|failed to fetch|name or service not known|sidecar request failed \(5\d{2}\)|could not reach the provider endpoint|econnrefused|enotfound/.test(
      lowered,
    )
  ) {
    return {
      category: 'network',
      statusCode,
      retryable: true,
      detail: normalized,
    };
  }

  if (/malformed response|invalid json|unexpected response/.test(lowered)) {
    return {
      category: 'malformed_response',
      statusCode,
      retryable: false,
      detail: normalized,
    };
  }

  return {
    detail: normalized,
    statusCode,
  };
}

async function patchProviderFailureState(
  context: CommandContext,
  failure: ProviderFailureMeta,
): Promise<void> {
  const providerConfig = context.providerStore.getConfig();
  const apiKey = await context.providerStore.getApiKey();
  const currentView = context.getHostState().bootstrap.providerConfig;

  if (!providerConfig) {
    return;
  }

  const cache = context.providerStore.getModelCache(providerConfig);
  const preserveModels =
    failure.category !== 'invalid_key_or_permission' &&
    failure.category !== 'model_unsupported' &&
    context.providerStore.isModelCacheFresh(cache) &&
    context.providerStore.isModelCacheCompatible(providerConfig, cache, apiKey);

  await context.providerStore.saveModelCache(providerConfig, {
    availableModels: preserveModels ? cache?.availableModels ?? [] : [],
    resolvedModel: preserveModels ? cache?.resolvedModel : undefined,
    lastError: failure.detail,
    lastErrorCategory: failure.category,
    lastStatusCode: failure.statusCode,
    retryable: failure.retryable,
    source: preserveModels ? 'cache' : 'live',
    apiKey,
  });

  await context.patchWorkbenchData({
    providerConfig: {
      ...currentView,
      configured: true,
      name: providerConfig.name,
      baseUrl: providerConfig.baseUrl,
      model: providerConfig.model,
      ...protocolPatch(providerConfig),
      apiKeyConfigured: true,
      capabilities: providerConfig.capabilities,
      availableModels: preserveModels ? cache?.availableModels ?? [] : [],
      resolvedModel: preserveModels ? cache?.resolvedModel : undefined,
      modelListStatus: 'error',
      modelListDetail: failure.detail,
      cacheFetchedAt: preserveModels ? cache?.fetchedAt : undefined,
      cacheExpiresAt: preserveModels ? cache?.expiresAt : undefined,
      cacheSource: preserveModels && cache ? 'cache' : 'live',
      modelErrorCategory: failure.category,
      modelStatusCode: failure.statusCode,
      modelRetryable: failure.retryable,
      lastTestResult: currentView.lastTestResult,
    },
  });
}

function providerUsesWorkspaceSecret(
  providerConfig:
    | { credentialMode?: string }
    | undefined,
): boolean {
  return providerConfig?.credentialMode === 'workspace_secret';
}

function protocolPatch(providerConfig: Pick<ProviderConfig, 'protocol'>): {
  protocol?: ProviderConfig['protocol'];
  protocolFamily?: string;
} {
  const protocol = normalizeProviderProtocol(providerConfig.protocol);
  return {
    protocol,
    protocolFamily: providerProtocolFamily(protocol),
  };
}

function buildCoachProviderRequestBody(
  context: CommandContext,
  providerConfig: { apiKeyRef?: string; credentialMode?: string } | undefined,
  apiKey: string | undefined,
): Record<string, unknown> {
  const lastTest = currentProviderLastTestResult(
    context,
    providerConfig as ProviderConfig | undefined,
  );
  const strippedLastTest =
    lastTest && typeof lastTest === 'object'
      ? stripHostLastTestSecrets({ ...(lastTest as unknown as Record<string, unknown>) })
      : undefined;
  return {
    workspace_id: getRuntimeWorkspaceId(context),
    api_key_ref: providerConfig?.apiKeyRef,
    api_key: apiKey,
    apiKey,
    last_test_result: strippedLastTest,
    lastTestResult: strippedLastTest,
  };
}

function currentProviderLastTestResult(
  context: CommandContext,
  _providerConfig: ProviderConfig | undefined,
) {
  return context.getHostState().bootstrap.providerConfig.lastTestResult;
}

function lastTestProvesReplyUnusable(
  result:
    | {
        ok?: boolean;
        status?: string;
        detail?: string;
        errorCategory?: string;
      }
    | undefined,
): boolean {
  if (!result || result.ok !== false) {
    return false;
  }
  const status = result.status?.toLowerCase() ?? '';
  const errorCategory = result.errorCategory?.toLowerCase() ?? '';
  const detail = result.detail?.toLowerCase() ?? '';
  return (
    status === 'language_corruption' ||
    errorCategory === 'language_corruption' ||
    detailLooksLikeLanguageCorruption(detail) ||
    status === 'empty_response' ||
    errorCategory === 'empty_response' ||
    /empty content|unusable|no final coaching reply content|final reply content/.test(detail)
  );
}

function usableReplyFailureMessage(
  detail: string | undefined,
  categoryOrStatus?: string | undefined,
  responseLanguage: ComposerLanguage = 'en-US',
): string {
  const normalized = detail?.trim();
  const normalizedCategory = categoryOrStatus?.trim().toLowerCase();
  if (
    normalizedCategory === 'language_corruption' ||
    detailLooksLikeLanguageCorruption(normalized)
  ) {
    const localized: Record<ComposerLanguage, string> = {
      'zh-CN': '这次没有收到可靠的中文回复。请检查模型连接后再试。',
      'en-US': 'This connection did not return a reliable reply. Check the model connection and try again.',
      'es-ES': 'Esta conexion no devolvio una respuesta fiable. Revisa la conexion del modelo e intentalo de nuevo.',
      'fr-FR': 'Cette connexion n a pas renvoye de reponse fiable. Verifiez la connexion du modele, puis reessayez.',
      'de-DE': 'Diese Verbindung hat keine verlaessliche Antwort geliefert. Pruefen Sie die Modellverbindung und versuchen Sie es erneut.',
      'ja-JP': 'この接続では信頼できる応答を受け取れませんでした。モデル接続を確認して、もう一度試してください。',
      'ko-KR': '이 연결에서 신뢰할 수 있는 답변을 받지 못했습니다. 모델 연결을 확인한 뒤 다시 시도해 주세요.',
      'pt-BR': 'Esta conexao nao retornou uma resposta confiavel. Verifique a conexao do modelo e tente novamente.',
    };
    return localized[responseLanguage];
  }
  const localized: Record<ComposerLanguage, string> = {
    'zh-CN': '这次没有收到可用回复。请检查连接后再试。',
    'en-US': 'No usable reply arrived this time. Check the connection and try again.',
    'es-ES': 'Esta vez no llego una respuesta util. Revisa la conexion e intentalo de nuevo.',
    'fr-FR': 'Aucune reponse exploitable n est arrivee cette fois. Verifiez la connexion, puis reessayez.',
    'de-DE': 'Dieses Mal ist keine nutzbare Antwort eingetroffen. Pruefen Sie die Verbindung und versuchen Sie es erneut.',
    'ja-JP': '今回は利用できる回答を受け取れませんでした。接続を確認して、もう一度試してください。',
    'ko-KR': '이번에는 사용할 수 있는 답변을 받지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.',
    'pt-BR': 'Nenhuma resposta utilizavel chegou desta vez. Verifique a conexao e tente novamente.',
  };
  return localized[responseLanguage];
}

type FriendlyStreamFailureCategory =
  | 'invalid_key_or_permission'
  | 'model_unsupported'
  | 'rate_limit'
  | 'timeout'
  | 'network'
  | 'unknown';

const FRIENDLY_STREAM_FAILURE_MESSAGES: Record<
  FriendlyStreamFailureCategory,
  Record<ComposerLanguage, string>
> = {
  invalid_key_or_permission: {
    'zh-CN': '模型连接需要更新。请到“设置”检查 API key 和访问权限。',
    'en-US': 'This model connection needs an updated API key or permission.',
    'es-ES': 'Esta conexión necesita una API key o permisos actualizados.',
    'fr-FR': "Cette connexion a besoin d'une clé API ou d'une autorisation à jour.",
    'de-DE': 'Diese Verbindung braucht einen aktuellen API-Schlüssel oder die nötige Berechtigung.',
    'ja-JP': 'この接続には、有効な API キーまたはアクセス権が必要です。',
    'ko-KR': '이 연결에는 유효한 API 키 또는 접근 권한이 필요합니다.',
    'pt-BR': 'Esta conexão precisa de uma chave de API ou permissão atualizada.',
  },
  model_unsupported: {
    'zh-CN': '当前模型暂时不可用。请到“设置”选择可用模型。',
    'en-US': 'This model is not available on the current connection. Choose another model in Settings.',
    'es-ES': 'Este modelo no está disponible en la conexión actual. Elige otro modelo en Configuración.',
    'fr-FR': "Ce modèle n'est pas disponible avec cette connexion. Choisissez-en un autre dans les paramètres.",
    'de-DE': 'Dieses Modell ist in der aktuellen Verbindung nicht verfügbar. Wählen Sie in den Einstellungen ein anderes Modell.',
    'ja-JP': 'このモデルは現在の接続では使えません。設定で別のモデルを選んでください。',
    'ko-KR': '이 모델은 현재 연결에서 사용할 수 없습니다. 설정에서 다른 모델을 선택하세요.',
    'pt-BR': 'Este modelo não está disponível na conexão atual. Escolha outro modelo em Configurações.',
  },
  rate_limit: {
    'zh-CN': '模型服务正在限流，请稍后再试。',
    'en-US': 'The model service is busy right now. Try again in a moment.',
    'es-ES': 'El servicio del modelo está ocupado ahora. Vuelve a intentarlo en un momento.',
    'fr-FR': 'Le service du modèle est occupé. Réessayez dans un instant.',
    'de-DE': 'Der Modelldienst ist gerade beschäftigt. Versuchen Sie es gleich noch einmal.',
    'ja-JP': 'モデルサービスが混み合っています。少し待ってからもう一度試してください。',
    'ko-KR': '모델 서비스가 지금 혼잡합니다. 잠시 후 다시 시도해 주세요.',
    'pt-BR': 'O serviço do modelo está ocupado agora. Tente novamente em alguns instantes.',
  },
  timeout: {
    'zh-CN': '模型响应太慢，这次没能完成。请稍后再试。',
    'en-US': 'The model took too long to respond. Try again in a moment.',
    'es-ES': 'El modelo tardó demasiado en responder. Vuelve a intentarlo en un momento.',
    'fr-FR': 'Le modèle a mis trop de temps à répondre. Réessayez dans un instant.',
    'de-DE': 'Die Modellantwort hat zu lange gedauert. Versuchen Sie es gleich noch einmal.',
    'ja-JP': 'モデルの応答に時間がかかりすぎました。少し待ってからもう一度試してください。',
    'ko-KR': '모델 응답이 너무 오래 걸렸습니다. 잠시 후 다시 시도해 주세요.',
    'pt-BR': 'O modelo demorou demais para responder. Tente novamente em alguns instantes.',
  },
  network: {
    'zh-CN': '暂时连不上模型服务。请检查连接后再试。',
    'en-US': 'Trainer could not reach the model service. Check the connection and try again.',
    'es-ES': 'Trainer no puede conectarse al servicio del modelo. Revisa la conexión e intentalo de nuevo.',
    'fr-FR': 'Trainer ne peut pas joindre le service du modèle. Vérifiez la connexion, puis réessayez.',
    'de-DE': 'Trainer kann den Modelldienst nicht erreichen. Prüfen Sie die Verbindung und versuchen Sie es erneut.',
    'ja-JP': 'モデルサービスに接続できません。接続を確認して、もう一度試してください。',
    'ko-KR': '모델 서비스에 연결할 수 없습니다. 연결을 확인한 뒤 다시 시도해 주세요.',
    'pt-BR': 'Trainer não consegue se conectar ao serviço do modelo. Verifique a conexão e tente novamente.',
  },
  unknown: {
    'zh-CN': '这次没能完成回复。请稍后再试。',
    'en-US': 'Trainer could not complete this reply. Try again in a moment.',
    'es-ES': 'Trainer no pudo completar esta respuesta. Vuelve a intentarlo en un momento.',
    'fr-FR': "Trainer n'a pas pu terminer cette réponse. Réessayez dans un instant.",
    'de-DE': 'Trainer konnte diese Antwort nicht abschliessen. Versuchen Sie es gleich noch einmal.',
    'ja-JP': '今回は返信を完了できませんでした。少し待ってからもう一度試してください。',
    'ko-KR': '이번 답변을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.',
    'pt-BR': 'Trainer não conseguiu concluir esta resposta. Tente novamente em alguns instantes.',
  },
};

function friendlyStreamFailureMessage(
  failure: ProviderFailureMeta,
  responseLanguage: ComposerLanguage,
): string {
  switch (failure.category) {
    case 'language_corruption':
    case 'empty_response':
      return usableReplyFailureMessage(failure.detail, failure.category, responseLanguage);
    case 'invalid_key_or_permission':
    case 'model_unsupported':
    case 'rate_limit':
    case 'timeout':
    case 'network':
      return FRIENDLY_STREAM_FAILURE_MESSAGES[failure.category][responseLanguage];
    default:
      return FRIENDLY_STREAM_FAILURE_MESSAGES.unknown[responseLanguage];
  }
}

async function persistProviderLastTestResult(
  context: CommandContext,
  providerConfig: ProviderConfig | undefined,
  result: {
    ok: boolean;
    status: string;
    detail: string;
    checkedAt: string;
    providerName: string;
    baseUrl: string;
    model: string;
    errorCategory?: string;
    retryable?: boolean;
    statusCode?: number;
    responseLanguage?: ComposerLanguage;
    protocol?: NonNullable<ProviderConfig['protocol']>;
    protocolFamily?: string;
    capabilityEvidence?: ReturnType<typeof normalizeProviderCapabilityTruth>['capabilityEvidence'];
    toolsReady?: boolean;
    toolProbeStatus?: ReturnType<typeof normalizeProviderCapabilityTruth>['toolProbeStatus'];
    streamingReady?: boolean;
    streamProbeStatus?: ReturnType<typeof normalizeProviderCapabilityTruth>['streamProbeStatus'];
  },
): Promise<void> {
  const currentView = context.getHostState().bootstrap.providerConfig;
  const protocol = normalizeProviderProtocol(
    result.protocol ?? providerConfig?.protocol ?? currentView.protocol,
  );
  const normalizedResult = {
    ...result,
    protocol,
    protocolFamily: result.protocolFamily ?? providerProtocolFamily(protocol),
  };
  if (providerConfig && typeof context.providerStore.saveLastTestResult === 'function') {
    await context.providerStore.saveLastTestResult(providerConfig, normalizedResult, {
      workspaceId: getRuntimeWorkspaceId(context),
    });
  }
  await context.patchWorkbenchData({
    providerConfig: {
      ...currentView,
      lastTestResult: stripHostLastTestSecrets({
        ...(normalizedResult as unknown as Record<string, unknown>),
      }) as unknown as typeof normalizedResult,
    },
  });
}

function detailForUnusableReply(
  stopReason: string,
  completionMeta: StreamAgentCompletionMeta,
): string {
  const summary = completionMeta.summary?.trim();
  const nextStep = completionMeta.nextStep?.trim();
  if (summary && nextStep) {
    return `${summary} Next step: ${nextStep}`;
  }
  if (summary) {
    return summary;
  }
  if (stopReason === 'language_corruption') {
    return 'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.';
  }
  return 'Provider replied with reasoning-only content and no final coaching reply content.';
}

function unusableReplyFailure(
  completionMeta: StreamAgentCompletionMeta,
): ProviderFailureMeta | undefined {
  const stopReason = completionMeta.stopReason?.trim().toLowerCase();
  if (
    stopReason !== 'language_corruption' &&
    stopReason !== 'empty_response' &&
    stopReason !== 'reasoning_only' &&
    stopReason !== 'truncated' &&
    stopReason !== 'truncated_or_empty'
  ) {
    return undefined;
  }
  return {
    category: stopReason,
    statusCode: 200,
    retryable: false,
    detail: detailForUnusableReply(stopReason, completionMeta),
  };
}

function extractUnusableReplyFailureFromResponse(
  response: unknown,
): ProviderFailureMeta | undefined {
  return unusableReplyFailure(extractStreamAgentCompletion(response));
}

function resolveStreamOperationReliability(
  response: unknown,
  completionMeta: StreamAgentCompletionMeta,
  replyFailure: ProviderFailureMeta | undefined,
): { phase: OperationReliabilityPhase; outcome: OperationReliabilityOutcome } {
  const record = readOperationReliability(response);
  const phase = record?.phase ?? 'acked';
  let outcome: OperationReliabilityOutcome = record?.outcome ?? 'success';
  const looksSuccessful = operationReliabilityLooksSuccessful({
    phase,
    outcome,
    stopReason: completionMeta.stopReason,
  });
  if (replyFailure || !looksSuccessful) {
    if (outcome === 'success' || outcome === '') {
      outcome = 'failure';
    }
  }
  return { phase, outcome };
}

async function markProviderReplyUnusable(
  context: CommandContext,
  providerConfig: ProviderConfig | undefined,
  failure: ProviderFailureMeta,
  responseLanguage = resolveProviderGuardLanguage(context),
): Promise<void> {
  if (!failure.category) {
    return;
  }
  await patchProviderFailureState(context, failure);
  const currentView = context.getHostState().bootstrap.providerConfig;
  await persistProviderLastTestResult(context, providerConfig, {
    ok: false,
    status: failure.category,
    detail: failure.detail,
    checkedAt: new Date().toISOString(),
    providerName: providerConfig?.name ?? currentView.name ?? 'Provider',
    baseUrl: providerConfig?.baseUrl ?? currentView.baseUrl ?? '',
    model: providerConfig?.model ?? currentView.model ?? '',
    errorCategory: failure.category,
    retryable: failure.retryable,
    statusCode: failure.statusCode,
    responseLanguage,
  });
}

async function failCoachReplyProof(
  context: CommandContext,
  providerConfig: ProviderConfig | undefined,
  error: unknown,
  responseLanguage: ComposerLanguage,
): Promise<CommandExecutionResult> {
  const classified = classifyProviderFailure(normalizeErrorText(error));
  const failure: ProviderFailureMeta = {
    ...classified,
    category: classified.category ?? 'unknown',
    detail: friendlyStreamFailureMessage(classified, responseLanguage),
  };

  try {
    await markProviderReplyUnusable(context, providerConfig, failure, responseLanguage);
  } catch {
    context.outputChannel.appendLine(
      `[provider] Could not save the provider failure state (${failure.category ?? 'unknown'}).`,
    );
  }

  return { ok: false, message: failure.detail };
}

async function ensureCoachReplyProof(
  context: CommandContext,
  providerConfig: ProviderConfig | undefined,
  apiKey: string | undefined,
  action: string,
  options?: {
    probeMessage?: string;
    responseLanguage?: string;
  },
): Promise<CommandExecutionResult | undefined> {
  const currentView = context.getHostState().bootstrap.providerConfig;
  const responseLanguage = resolveProviderGuardLanguage(context, options?.responseLanguage);
  const lastTestResult = currentProviderLastTestResult(context, providerConfig);
  if (lastTestProvesReplyUnusable(lastTestResult)) {
    return {
      ok: false,
      message: usableReplyFailureMessage(
        lastTestResult?.detail,
        lastTestResult?.errorCategory ?? lastTestResult?.status,
        responseLanguage,
      ),
    };
  }
  if (lastTestResult?.ok) {
    return undefined;
  }
  if (currentView.configured !== true) {
    return undefined;
  }

  let status: SidecarStatus;
  try {
    status = await context.sidecarManager.ensureRunning();
  } catch (error) {
    return failCoachReplyProof(context, providerConfig, error, responseLanguage);
  }
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  let response: ProviderTestResponse;
  try {
    response = await context.sidecarClient.postJson<ProviderTestResponse>(
      status.port,
      '/provider/test',
      {
        provider: providerConfig,
        probe_message: options?.probeMessage,
        response_language: responseLanguage,
        ...buildCoachProviderRequestBody(context, providerConfig, apiKey),
      },
      { timeoutMs: SIDECAR_DEFAULTS.providerRequestTimeoutMs },
    );
  } catch (error) {
    return failCoachReplyProof(context, providerConfig, error, responseLanguage);
  }

  const ok = Boolean(response.ok);
  const detail = response.detail?.trim() || `Trainer could not ${action}.`;
  const capabilityTruth = normalizeProviderCapabilityTruth(response);
  const savedResult = {
    ok,
    status: response.status ?? (ok ? 'connected' : 'failed'),
    detail,
    checkedAt: new Date().toISOString(),
    providerName: response.provider_name?.trim() || providerConfig?.name || 'Provider',
    baseUrl: providerConfig?.baseUrl ?? '',
    model: providerConfig?.model ?? '',
    errorCategory: response.error_category,
    retryable: response.retryable,
    statusCode: response.status_code ?? undefined,
    responseLanguage,
      capabilityEvidence: capabilityTruth.capabilityEvidence,
      toolsReady: capabilityTruth.toolsReady,
      toolProbeStatus: capabilityTruth.toolProbeStatus,
      streamingReady: capabilityTruth.streamingReady,
      streamProbeStatus: capabilityTruth.streamProbeStatus,
      visionReady: capabilityTruth.visionReady,
      visionProbeStatus: capabilityTruth.visionProbeStatus,
      thinkingReady: capabilityTruth.thinkingReady,
      thinkingProbeStatus: capabilityTruth.thinkingProbeStatus,
    };
  await persistProviderLastTestResult(context, providerConfig, savedResult);

  if (ok) {
    return undefined;
  }

  if (
    response.error_category === 'language_probe_inconclusive' ||
    response.status === 'language_probe_inconclusive'
  ) {
    return undefined;
  }

  return {
    ok: false,
    message:
      response.error_category === 'empty_response' ||
      response.status === 'empty_response' ||
      response.error_category === 'language_corruption' ||
      response.status === 'language_corruption'
        ? usableReplyFailureMessage(
            detail,
            response.error_category ?? response.status,
            responseLanguage,
          )
        : detail,
  };
}

function isRetryableTimeoutFailure(error: unknown): boolean {
  return classifyProviderFailure(normalizeErrorText(error)).category === 'timeout';
}

function normalizeWorkspacePath(value: string | undefined): string | undefined {
  return value ? path.normalize(value).replace(/[\\\/]+$/, '').toLowerCase() : undefined;
}

function sameWorkspacePath(left: string | undefined, right: string | undefined): boolean {
  return Boolean(
    left &&
      right &&
      normalizeWorkspacePath(left) === normalizeWorkspacePath(right),
  );
}

function activeWorkspaceRoot(context: CommandContext): string | undefined {
  return (
    context.getHostState().workspace.activeWorkspaceRoot ??
    context.getHostState().workspace.workspaceFolder
  );
}

function deriveImplicitTrainingRestorePayload(
  summary: unknown,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  if (payload.trainingRestoreTarget) {
    return payload;
  }
  const memory = asTrainingRecord(asTrainingRecord(summary)?.memory);
  if (!memory) {
    return payload;
  }
  const theoryDrillId = asNonEmptyString(asTrainingRecord(memory.theory_drill)?.id);
  if (theoryDrillId && Array.isArray(memory.theory_drill_history) && memory.theory_drill_history.length > 0) {
    return {
      ...payload,
      trainingRestoreTarget: 'theory_drill',
      theoryDrillId,
    };
  }
  const scenarioLabId = asNonEmptyString(asTrainingRecord(memory.scenario_lab)?.id);
  if (scenarioLabId && Array.isArray(memory.scenario_lab_history) && memory.scenario_lab_history.length > 0) {
    return {
      ...payload,
      trainingRestoreTarget: 'scenario_lab',
      scenarioLabId,
    };
  }
  const reviewArtifactId = asNonEmptyString(asTrainingRecord(memory.review_artifact)?.id);
  if (
    reviewArtifactId &&
    Array.isArray(memory.review_artifact_history) &&
    memory.review_artifact_history.length > 0
  ) {
    return {
      ...payload,
      trainingRestoreTarget: 'review_artifact',
      reviewArtifactId,
    };
  }
  return payload;
}

function resolveResumeTrainingSubmode(
  summary: unknown,
  fallback: string | undefined,
): string | undefined {
  return (
    asNonEmptyString(asTrainingRecord(asTrainingRecord(asTrainingRecord(summary)?.memory)?.workspace)?.latest_training_submode) ??
    fallback
  );
}

function resolveResumeFocusArea(
  summary: unknown,
  fallback: string | undefined,
): string | undefined {
  return (
    asNonEmptyString(asTrainingRecord(asTrainingRecord(asTrainingRecord(summary)?.memory)?.workspace)?.latest_learning_focus_area) ??
    fallback
  );
}

async function fetchMemorySummaryForWorkspace(
  context: CommandContext,
  workspaceId: string,
  sessionId: string | undefined,
): Promise<unknown> {
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    throw new Error(status.detail ?? 'Sidecar is unavailable.');
  }

  return context.sidecarClient.getJson<unknown>(
    status.port,
    buildMemorySummaryQueryPath(workspaceId, sessionId),
  );
}

function currentCoachCheckpointScope(context: CommandContext): CoachCheckpointScope | undefined {
  const sessionId = asNonEmptyString(context.getSessionId());
  if (!sessionId) {
    return undefined;
  }
  return {
    workspaceId: getRuntimeWorkspaceContext(context).workspaceId,
    sessionId,
  };
}

function buildLatestCoachCheckpointQueryPath(scope: CoachCheckpointScope): string {
  const params = new URLSearchParams();
  params.set('workspace_id', scope.workspaceId);
  params.set('session_id', scope.sessionId);
  params.set('limit', '1');
  return `/session/checkpoints?${params.toString()}`;
}

function isCoachCheckpointId(value: string): boolean {
  return /^[a-z0-9][a-z0-9_-]{0,127}$/i.test(value);
}

function parseLatestCoachCheckpoint(
  value: unknown,
  scope: CoachCheckpointScope,
): LatestCoachCheckpoint | undefined {
  const record = asTrainingRecord(value);
  const checkpointId = asNonEmptyString(record?.checkpoint_id);
  const sessionId = asNonEmptyString(record?.session_id);
  if (!checkpointId || !sessionId || !isCoachCheckpointId(checkpointId) || sessionId !== scope.sessionId) {
    return undefined;
  }
  return {
    checkpointId,
    sessionId,
    createdAt: asNonEmptyString(record?.created_at),
    nextStep: asNonEmptyString(record?.next_step),
  };
}

function checkpointUserMessage(kind: 'noSession' | 'none' | 'unavailable' | 'invalid'): string {
  switch (kind) {
    case 'noSession':
      return 'There is no Coach conversation to restore yet.';
    case 'none':
      return 'There is no saved Coach checkpoint for this conversation yet.';
    case 'unavailable':
      return 'Trainer cannot reach saved Coach progress right now. Try again in a moment.';
    case 'invalid':
      return 'Trainer found saved Coach progress, but it cannot be opened safely.';
  }
}

function logCheckpointFailure(context: CommandContext, action: string, error: unknown): void {
  context.outputChannel.appendLine(`[checkpoint:${action}] ${userFacingErrorText(error)}`);
}

async function findLatestCoachCheckpoint(
  context: CommandContext,
  port: number,
  scope: CoachCheckpointScope,
): Promise<{ checkpoint?: LatestCoachCheckpoint; message?: string }> {
  let response: unknown;
  try {
    response = await context.sidecarClient.getJson<unknown>(
      port,
      buildLatestCoachCheckpointQueryPath(scope),
    );
  } catch (error) {
    logCheckpointFailure(context, 'list', error);
    return { message: checkpointUserMessage('unavailable') };
  }

  const checkpoints = asTrainingRecord(response)?.checkpoints;
  if (!Array.isArray(checkpoints)) {
    return { message: checkpointUserMessage('invalid') };
  }
  if (checkpoints.length === 0) {
    return { message: checkpointUserMessage('none') };
  }

  const checkpoint = parseLatestCoachCheckpoint(checkpoints[0], scope);
  return checkpoint
    ? { checkpoint }
    : { message: checkpointUserMessage('invalid') };
}

function formatCheckpointText(value: unknown): string | undefined {
  return asNonEmptyString(value)?.replace(/\r\n/g, '\n');
}

function formatCheckpointCode(value: unknown): string | undefined {
  const text = formatCheckpointText(value);
  return text ? text.replace(/```/g, '``\\`') : undefined;
}

function formatSavedCoachTrace(
  replayResponse: unknown,
  checkpoint: LatestCoachCheckpoint,
): string | undefined {
  const replay = asTrainingRecord(replayResponse);
  if (replay?.mode !== 'stored_trace' || replay.replayed !== true || replay.executed !== false) {
    return undefined;
  }

  const storedCheckpoint = asTrainingRecord(replay.checkpoint);
  if (!storedCheckpoint || asNonEmptyString(storedCheckpoint.checkpoint_id) !== checkpoint.checkpointId) {
    return undefined;
  }

  const request = asTrainingRecord(storedCheckpoint.request);
  const final = asTrainingRecord(storedCheckpoint.final);
  const recovery = asTrainingRecord(storedCheckpoint.recovery);
  const trace = asTrainingRecord(storedCheckpoint.trace);
  const requestMessage = formatCheckpointText(request?.message);
  const reply = formatCheckpointText(final?.content);
  const nextStep = formatCheckpointText(recovery?.next_step) ?? checkpoint.nextStep;
  const traceJson = trace ? formatCheckpointCode(JSON.stringify(trace, null, 2)) : undefined;
  const lines = [
    '# Saved Coach checkpoint',
    '',
    'This is a saved replay. Trainer did not send a new message, run tools, or call a model.',
    '',
    `Saved: ${checkpoint.createdAt ?? 'Unknown time'}`,
  ];

  if (requestMessage) {
    lines.push('', '## Your saved message', '', requestMessage);
  }
  if (reply) {
    lines.push('', '## Trainer\'s saved reply', '', reply);
  }
  if (nextStep) {
    lines.push('', '## Saved next step', '', nextStep);
  }
  if (traceJson) {
    lines.push('', '## Saved activity', '', '```json', traceJson, '```');
  }

  return lines.join('\n');
}

async function openSavedCoachTrace(context: CommandContext, content: string): Promise<void> {
  const document = await vscode.workspace.openTextDocument({
    content,
    language: 'markdown',
  });
  await vscode.window.showTextDocument(document, {
    preview: true,
    preserveFocus: false,
  });
  await vscode.window.showInformationMessage(
    'Opened the saved Coach trace. Your current conversation is unchanged.',
  );
}

export async function resumeLatestCoachCheckpointCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const workspaceGate = trainerWorkspaceSessionGate(context);
  if (workspaceGate) {
    return workspaceGate;
  }

  const scope = currentCoachCheckpointScope(context);
  if (!scope) {
    return { ok: false, message: checkpointUserMessage('noSession') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? checkpointUserMessage('unavailable') };
  }

  const latest = await findLatestCoachCheckpoint(context, status.port, scope);
  if (!latest.checkpoint) {
    return { ok: false, message: latest.message ?? checkpointUserMessage('none') };
  }

  let resumeResponse: unknown;
  try {
    resumeResponse = await context.sidecarClient.postJson<unknown>(
      status.port,
      `/session/checkpoints/${latest.checkpoint.checkpointId}/resume`,
      {
        workspaceId: scope.workspaceId,
        sessionId: scope.sessionId,
      },
    );
  } catch (error) {
    logCheckpointFailure(context, 'resume', error);
    return {
      ok: false,
      message: 'Trainer could not restore that saved Coach progress. Your current conversation is unchanged.',
    };
  }

  const resumedSessionId = asNonEmptyString(asTrainingRecord(resumeResponse)?.session_id);
  if (resumedSessionId !== scope.sessionId || asTrainingRecord(resumeResponse)?.executed !== false) {
    return { ok: false, message: checkpointUserMessage('invalid') };
  }

  let summary: unknown;
  try {
    summary = await fetchMemorySummaryForWorkspace(context, scope.workspaceId, resumedSessionId);
  } catch (error) {
    logCheckpointFailure(context, 'refresh', error);
    return {
      ok: false,
      message: 'Trainer restored the saved progress, but could not refresh the Coach view. Try again.',
    };
  }

  await context.patchWorkbenchData(
    mergeMemorySummarySnapshot(context.getHostState().bootstrap, summary, scope.workspaceId),
  );
  await context.setSessionId(resumedSessionId);
  await context.setStreamingState(createEmptyTrainerStreamingState());
  await context.workbench.show();
  await context.workbench.syncState();
  await context.workbench.postMessage({
    type: 'ui/restoreView',
    payload: {
      sessionId: resumedSessionId,
      activeView: 'coach',
      resumeReason: latest.checkpoint.nextStep,
    },
  });

  return {
    ok: true,
    message: 'Restored the latest saved Coach checkpoint. You can continue when ready.',
    data: resumeResponse,
  };
}

export async function replayLatestCoachCheckpointCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const workspaceGate = trainerWorkspaceSessionGate(context);
  if (workspaceGate) {
    return workspaceGate;
  }

  const scope = currentCoachCheckpointScope(context);
  if (!scope) {
    return { ok: false, message: checkpointUserMessage('noSession') };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? checkpointUserMessage('unavailable') };
  }

  const latest = await findLatestCoachCheckpoint(context, status.port, scope);
  if (!latest.checkpoint) {
    return { ok: false, message: latest.message ?? checkpointUserMessage('none') };
  }

  let replayResponse: unknown;
  try {
    replayResponse = await context.sidecarClient.postJson<unknown>(
      status.port,
      `/session/checkpoints/${latest.checkpoint.checkpointId}/replay`,
      {
        workspaceId: scope.workspaceId,
        sessionId: scope.sessionId,
      },
    );
  } catch (error) {
    logCheckpointFailure(context, 'replay', error);
    return {
      ok: false,
      message: 'Trainer could not open that saved Coach trace. Your current conversation is unchanged.',
    };
  }

  const trace = formatSavedCoachTrace(replayResponse, latest.checkpoint);
  if (!trace) {
    return { ok: false, message: checkpointUserMessage('invalid') };
  }

  try {
    await openSavedCoachTrace(context, trace);
  } catch (error) {
    logCheckpointFailure(context, 'display', error);
    return {
      ok: false,
      message: 'Trainer could not show that saved Coach trace. Your current conversation is unchanged.',
    };
  }

  return {
    ok: true,
    message: 'Opened the saved Coach trace. Your current conversation is unchanged.',
    data: replayResponse,
  };
}

export async function sendMessageCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('send Trainer session messages'))) {
    return { ok: false, message: 'Workspace trust is required for session messages.' };
  }

  const workspaceGate = trainerWorkspaceSessionGate(context);
  if (workspaceGate) {
    return workspaceGate;
  }
  const requestWorkspaceId = getRuntimeWorkspaceId(context);
  const requestWorkspaceFolder = context.getHostState().workspace.workspaceFolder;
  const requestIsCurrent = (): boolean =>
    getRuntimeWorkspaceId(context) === requestWorkspaceId &&
    context.getHostState().workspace.workspaceFolder === requestWorkspaceFolder;

  const message =
    extractSessionPayload(payload)?.text ??
    (await vscode.window.showInputBox({
      title: 'Trainer message',
      prompt: 'Describe your learning goal, change request, or question.',
      ignoreFocusOut: true,
    }));

  if (!message) {
    return { ok: false, message: 'No message provided.' };
  }

  const sessionPayload = extractSessionPayload(payload);
  const providerConfig = context.providerStore.getConfig();
  const apiKey = await context.providerStore.getApiKey();
  if (!requestIsCurrent()) {
    return {
      ok: true,
      message: 'Session response discarded after the workspace changed.',
    };
  }
  if (!providerConfig) {
    return {
      ok: false,
      message: 'Trainer needs a saved provider before sending messages.',
    };
  }
  if (!providerUsesWorkspaceSecret(providerConfig) && !apiKey?.trim()) {
    return {
      ok: false,
      message: 'Trainer needs a saved provider and API key before sending messages.',
    };
  }
  const providerGuard = await ensureCoachProviderReady(context, 'send messages', {
    probeMessage: message,
    responseLanguage: sessionPayload?.responseLanguage,
  });
  if (providerGuard) {
    return providerGuard;
  }
  if (!requestIsCurrent()) {
    return {
      ok: true,
      message: 'Session response discarded after the workspace changed.',
    };
  }
  if (sessionPayload?.attachments?.length) {
    const imageGuard = providerImageInputGuard(
      context,
      providerConfig,
      apiKey,
      sessionPayload?.responseLanguage,
    );
    if (imageGuard.blocked) {
      return {
        ok: false,
        message:
          imageGuard.message ??
          'This provider connection cannot send images to the model yet.',
      };
    }
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }
  if (!requestIsCurrent()) {
    return {
      ok: true,
      message: 'Session response discarded after the workspace changed.',
    };
  }

  const requestPath = usesSessionMessageRoute(sessionPayload) ? '/session/message' : '/turn';
  const workspaceFileSnapshot = await buildWorkspaceFileSnapshot(context);
  const requestBody = {
    session_id: context.getSessionId(),
    intent: sessionPayload?.intent ?? 'coach',
    formal_plan_mutation: sessionPayload?.formalPlanMutation === true,
    // Host-armed only — ignore any webview self-attestation.
    resource_organization_confirmed: consumeResourceOrganizationConfirmed(context),
    active_view: sessionPayload?.activeView,
    message,
    provider: providerConfig,
    resource_ids: sessionPayload?.resourceIds ?? [],
    resource_composer_intent: resourceComposerIntentWire(sessionPayload?.resourceComposerIntent),
    current_file: getCurrentFilePayload(context, sessionPayload, message),
    workspace_file_snapshot: workspaceFileSnapshot,
    response_language: sessionPayload?.responseLanguage,
    answer_mode: normalizeAnswerMode(sessionPayload?.answerMode),
    teaching_style: sessionPayload?.teachingStyle,
    coach_defaults: sessionPayload?.coachDefaults,
    attachments: normalizeAttachments(sessionPayload?.attachments),
    use_agent_loop: sessionPayload?.useAgentLoop,
    request_id:
      sessionPayload?.requestId?.trim() ||
      `coach-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    plan_runtime_recovery: sessionPayload?.planRuntimeRecovery,
    // Mid-session host re-attest (never JSON-omit undefined).
    remote_name: context.getHostState().workspace.remoteName ?? '',
    workspace_trusted: Boolean(context.getHostState().workspace.trusted),
    ...buildCoachProviderRequestBody(context, providerConfig, apiKey),
  };
  const port = status.port;

  const sendRequest = async () =>
    context.sidecarClient.postJson<unknown>(port, requestPath, requestBody, {
      timeoutMs: SIDECAR_DEFAULTS.providerRequestTimeoutMs,
    });

  let response: unknown;
  try {
    response = await sendRequest();
  } catch (error) {
    if (false) {
      response = await sendRequest().catch(async (retryError) => {
        if (!requestIsCurrent()) {
          throw retryError;
        }
        const retryFailure = classifyProviderFailure(normalizeErrorText(retryError));
        if (retryFailure.category) {
          await patchProviderFailureState(context, retryFailure);
        }
        throw retryError;
      });
    } else {
      if (!requestIsCurrent()) {
        throw error;
      }
      const failure = classifyProviderFailure(normalizeErrorText(error));
      if (failure.category) {
        await patchProviderFailureState(context, failure);
      }
      if (isRetryableTimeoutFailure(error)) {
        return { ok: false, message: userFacingErrorText(error) };
      }
      throw error;
    }
  }

  if (!requestIsCurrent()) {
    return {
      ok: true,
      message: 'Session response discarded after the workspace changed.',
    };
  }
  const { sessionId, patch } = mergeSessionMessageSnapshot(
    context.getHostState().bootstrap,
    response,
    message,
    getRuntimeWorkspaceId(context),
  );
  await context.setSessionId(sessionId ?? context.getSessionId());
  if (!requestIsCurrent()) {
    return {
      ok: true,
      message: 'Session response discarded after the workspace changed.',
    };
  }
  await context.patchWorkbenchData(patch);
  if (requestIsCurrent()) {
    noteRequestedWorkspaceFilesFromSessionResponse(context, response);
    const organizationPending = noteResourceOrganizationFromSessionResponse(
      context,
      response,
      sessionPayload?.responseLanguage,
    );
    if (organizationPending) {
      await notifyResourceOrganizationPending(context, organizationPending);
    }
  }
  const replyFailure = extractUnusableReplyFailureFromResponse(response);
  if (replyFailure && requestIsCurrent()) {
    await markProviderReplyUnusable(context, providerConfig, replyFailure);
  }
  return {
    ok: true,
    message: 'Session message sent.',
    data: response,
  };
}

export async function sendStreamMessageCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('send Trainer session messages'))) {
    return { ok: false, message: 'Workspace trust is required for session messages.' };
  }

  const workspaceGate = trainerWorkspaceSessionGate(context);
  if (workspaceGate) {
    return workspaceGate;
  }

  const streamPayload = extractStreamPayload(payload);
  if (!streamPayload?.text) {
    return { ok: false, message: 'No message provided.' };
  }
  const responseLanguage = resolveProviderGuardLanguage(context, streamPayload.responseLanguage);
  if (
    activeCoachStreamContexts.has(context) ||
    normalizeTrainerStreamingState(context.getStreamingState()).isStreaming
  ) {
    return {
      ok: false,
      message: streamAlreadyInProgressMessage(responseLanguage),
    };
  }

  const streamGeneration = nextStreamGeneration(context);
  activeCoachStreamContexts.add(context);
  let activeCoachStream: ActiveCoachStream | undefined;
  try {
    const providerConfig = context.providerStore.getConfig();
    const apiKey = await context.providerStore.getApiKey();
    if (!providerConfig) {
      return {
        ok: false,
        message: 'Trainer needs a saved provider before streaming messages.',
      };
    }
    if (!providerUsesWorkspaceSecret(providerConfig) && !apiKey?.trim()) {
      return {
        ok: false,
        message: 'Trainer needs a saved provider and API key before streaming messages.',
      };
    }
    const providerGuard = await ensureCoachProviderReady(context, 'stream messages', {
      responseLanguage: streamPayload.responseLanguage,
      deferReplyProof: true,
    });
    if (providerGuard) {
      return providerGuard;
    }
    if (streamPayload.attachments?.length) {
      const imageGuard = providerImageInputGuard(
        context,
        providerConfig,
        apiKey,
        streamPayload.responseLanguage,
      );
      if (imageGuard.blocked) {
        return {
          ok: false,
          message:
            imageGuard.message ??
            'This provider connection cannot send images to the model yet.',
        };
      }
    }
    const capabilityDecision = streamCapabilityDecision(context);
    if (capabilityDecision === 'unverified-stream') {
      const blockedMessageId = `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      await failClosedUnverifiedStreaming(context, blockedMessageId, responseLanguage);
      return {
        ok: false,
        message: streamingCapabilityBlockReason(responseLanguage),
      };
    }
    if (streamPayload.attachments?.length) {
      const imageGuard = providerImageInputGuard(
        context,
        providerConfig,
        apiKey,
        streamPayload.responseLanguage,
      );
      if (imageGuard.blocked) {
        return {
          ok: false,
          message:
            imageGuard.message ??
            'This provider connection cannot send images to the model yet.',
        };
      }
    }

    if (streamGenerations.get(context) !== streamGeneration) {
      return { ok: true, message: 'Stream invalidated.' };
    }
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
    }
    if (streamGenerations.get(context) !== streamGeneration) {
      return { ok: true, message: 'Stream invalidated.' };
    }

    const messageId = `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const abortController = new AbortController();
    activeCoachStream = {
      messageId,
      abortController,
      sidecarPort: status.port,
      generation: streamGeneration,
    };
    activeCoachStreams.set(context, activeCoachStream);

    await context.setStreamingState({
      ...createEmptyTrainerStreamingState(),
      isStreaming: true,
      streamMessageId: messageId,
      reliabilityPhase: 'pending',
    });

    // Notify webview that streaming is starting.
    await context.workbench.postMessage({
      type: 'stream/start',
      payload: { messageId },
    });
    await postStreamReliabilityStatus(context, 'pending', responseLanguage);

    try {
    const requestPath = usesSessionMessageRoute(streamPayload)
      ? '/session/message/stream'
      : '/turn/stream';
    const workspaceFileSnapshot = await buildWorkspaceFileSnapshot(context);
    const requestBody = {
      session_id: context.getSessionId(),
      stream_id: messageId,
      intent: streamPayload.intent ?? 'coach',
      formal_plan_mutation: streamPayload.formalPlanMutation === true,
      // Host-armed only — ignore any webview self-attestation.
      resource_organization_confirmed: consumeResourceOrganizationConfirmed(context),
      goals: streamPayload.goals ?? [],
      active_view: streamPayload.activeView,
      message: streamPayload.text,
      provider: providerConfig,
      resource_ids: streamPayload.resourceIds ?? [],
      resource_composer_intent: resourceComposerIntentWire(streamPayload.resourceComposerIntent),
      current_file: getCurrentFilePayload(context, streamPayload, streamPayload.text),
      workspace_file_snapshot: workspaceFileSnapshot,
      response_language: streamPayload.responseLanguage,
      answer_mode: normalizeAnswerMode(streamPayload.answerMode),
      teaching_style: streamPayload.teachingStyle,
      coach_defaults: streamPayload.coachDefaults,
      attachments: normalizeAttachments(streamPayload.attachments),
      use_agent_loop: streamPayload.useAgentLoop,
      request_id: streamPayload.requestId?.trim() || `coach-${messageId}`,
      plan_runtime_recovery: streamPayload.planRuntimeRecovery,
      stream: true,
      // F3: slim complete frames (revision + dirty keys only); the host
      // refetches the authoritative snapshot via GET /snapshot on merge.
      fields: 'slim',
      // Mid-session host re-attest (never JSON-omit undefined).
      remote_name: context.getHostState().workspace.remoteName ?? '',
      workspace_trusted: Boolean(context.getHostState().workspace.trusted),
      ...buildCoachProviderRequestBody(context, providerConfig, apiKey),
    };

    let totalTokens = 0;
    let completionMeta: StreamAgentCompletionMeta = { agentic: false };
    let completionResponse: unknown;
    let sawCompletion = false;

    for await (const event of context.sidecarClient.fetchSSE(
      status.port,
      requestPath,
      requestBody,
      {
        timeoutMs: SIDECAR_DEFAULTS.providerRequestTimeoutMs,
        signal: abortController.signal,
      },
    )) {
      if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
        return {
          ok: true,
          message: 'Stream invalidated.',
        };
      }

      if (event.event === 'complete') {
        const completion = parseSseJson(event);
        const response = completion?.response;
        if (!completion || !response || typeof response !== 'object' || Array.isArray(response)) {
          throw new Error('SSE stream ended without a valid completion response.');
        }
        sawCompletion = true;
        completionMeta = extractStreamAgentCompletion(response);
        if (typeof completion?.tokens === 'number') {
          totalTokens = completion.tokens;
        }

        if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
          return {
            ok: true,
            message: 'Stream invalidated.',
          };
        }
        // F3: slim complete frames carry snapshot_revision instead of the full
        // snapshot; refetch the authoritative snapshot once before merging.
        const responseRecord: Record<string, unknown> = {
          ...(response as Record<string, unknown>),
        };
        let effectiveResponse: Record<string, unknown> = responseRecord;
        if (!('snapshot' in responseRecord) && responseRecord.snapshot_revision != null) {
          try {
            const statusForSnapshot = await context.sidecarManager.ensureRunning();
            if (statusForSnapshot.lifecycle === 'ready' && statusForSnapshot.port) {
              const sessionParam = context.getSessionId()
                ? `&session_id=${encodeURIComponent(context.getSessionId() ?? '')}`
                : '';
              const full = await context.sidecarClient.getJson<{ snapshot?: unknown }>(
                statusForSnapshot.port,
                `/snapshot?fields=full${sessionParam}`,
              );
              if (full && full.snapshot) {
                effectiveResponse = { ...responseRecord, snapshot: full.snapshot };
              }
            }
          } catch (error) {
            const detail = error instanceof Error ? error.message : String(error);
            context.outputChannel.appendLine(
              `[trainer] slim snapshot refetch failed: ${detail}`,
            );
          }
        }
        completionResponse = effectiveResponse;
        const { sessionId, patch } = mergeSessionMessageSnapshot(
          context.getHostState().bootstrap,
          effectiveResponse,
          streamPayload.text,
          getRuntimeWorkspaceId(context),
        );
        await context.setSessionId(sessionId ?? context.getSessionId());
        if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
          return {
            ok: true,
            message: 'Stream invalidated.',
          };
        }
        await context.patchWorkbenchData(patch);
        break;
      }

      if (event.event === 'tool_call') {
        const parsed = parseSseJson(event);
        if (parsed) {
          if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
            return { ok: true, message: 'Stream invalidated.' };
          }
          await updateStreamingState(context, (state) => ({
            ...state,
            isStreaming: true,
            agentActivity: upsertTrainerToolActivity(state.agentActivity, {
              id: typeof parsed.id === 'string' ? parsed.id : String(parsed.id ?? ''),
              name: typeof parsed.name === 'string' ? parsed.name : String(parsed.name ?? ''),
              status: 'running',
              args:
                parsed.arguments && typeof parsed.arguments === 'object' && !Array.isArray(parsed.arguments)
                  ? (sanitizeHostToolResult(parsed.arguments, responseLanguage) as Record<string, unknown>)
                  : undefined,
              step: typeof parsed.step === 'number' ? parsed.step : undefined,
            }),
          }));
          if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
            return { ok: true, message: 'Stream invalidated.' };
          }
          await context.workbench.postMessage({
            type: 'stream/tool_call',
            payload: {
              messageId,
              id: typeof parsed.id === 'string' ? parsed.id : String(parsed.id ?? ''),
              name: typeof parsed.name === 'string' ? parsed.name : String(parsed.name ?? ''),
              arguments: sanitizeHostToolResult(parsed.arguments, responseLanguage),
              step: typeof parsed.step === 'number' ? parsed.step : undefined,
            },
          });
        }
        continue;
      }

      if (event.event === 'tool_result') {
        const parsed = parseSseJson(event);
        if (parsed) {
          if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
            return { ok: true, message: 'Stream invalidated.' };
          }
          const toolName =
            typeof parsed.name === 'string' ? parsed.name : String(parsed.name ?? '');
          const sanitizedResult = sanitizeHostToolResult(parsed.result, responseLanguage);
          await updateStreamingState(context, (state) => ({
            ...state,
            isStreaming: true,
            agentActivity: upsertTrainerToolActivity(state.agentActivity, {
              id: typeof parsed.id === 'string' ? parsed.id : String(parsed.id ?? ''),
              name: toolName,
              status: Boolean(parsed.ok) ? 'succeeded' : 'failed',
              result: sanitizedResult,
              step: typeof parsed.step === 'number' ? parsed.step : undefined,
            }),
          }));
          if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
            return { ok: true, message: 'Stream invalidated.' };
          }
          await context.workbench.postMessage({
            type: 'stream/tool_result',
            payload: {
              messageId,
              id: typeof parsed.id === 'string' ? parsed.id : String(parsed.id ?? ''),
              name: toolName,
              ok: Boolean(parsed.ok),
              result: sanitizedResult,
              step: typeof parsed.step === 'number' ? parsed.step : undefined,
            },
          });
          noteRequestedWorkspaceFileToolResult(context, toolName, sanitizedResult);
          const organizationPending = noteResourceOrganizationToolResult(
            context,
            toolName,
            sanitizedResult,
          );
          if (organizationPending) {
            await notifyResourceOrganizationPending(context, organizationPending);
          }
        }
        continue;
      }

      if (event.event === 'step') {
        const parsed = parseSseJson(event);
        if (parsed) {
          if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
            return { ok: true, message: 'Stream invalidated.' };
          }
          await updateStreamingState(context, (state) => ({
            ...state,
            isStreaming: true,
            agentStep: typeof parsed.index === 'number' ? parsed.index : 0,
          }));
          if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
            return { ok: true, message: 'Stream invalidated.' };
          }
          await context.workbench.postMessage({
            type: 'stream/step',
            payload: {
              messageId,
              index: typeof parsed.index === 'number' ? parsed.index : 0,
              stop_reason:
                typeof parsed.stop_reason === 'string' || parsed.stop_reason === null
                  ? (parsed.stop_reason as string | null)
                  : undefined,
            },
          });
        }
        continue;
      }

      if (event.event === 'status') {
        const parsed = parseSseJson(event);
        const phase = typeof parsed?.phase === 'string' ? parsed.phase : undefined;
        const reliabilityPhase = mapStreamStatusToReliabilityPhase(phase);
        if (reliabilityPhase) {
          if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
            return { ok: true, message: 'Stream invalidated.' };
          }
          await updateStreamingState(context, (state) => ({
            ...state,
            isStreaming: true,
            reliabilityPhase,
            reliabilityOutcome:
              reliabilityPhase === 'failed'
                ? 'failure'
                : reliabilityPhase === 'cancelled'
                  ? 'cancelled'
                  : state.reliabilityOutcome,
          }));
        }
        if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
          return { ok: true, message: 'Stream invalidated.' };
        }
        await postStreamReliabilityStatus(context, phase, responseLanguage);
        continue;
      }

      if (event.event === 'error') {
        if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
          return { ok: true, message: 'Stream invalidated.' };
        }
        const parsed = parseSseJson(event);
        const detail =
          typeof parsed?.error === 'string'
            ? parsed.error
            : typeof parsed?.detail === 'string'
              ? parsed.detail
              : event.data;
        const explicitlyRecoverable = parsed?.recoverable === true || parsed?.terminal === false;
        const explicitlyTerminal = parsed?.terminal === true || parsed?.recoverable === false;
        if (explicitlyRecoverable && !explicitlyTerminal) {
          const failure = classifyProviderFailure(detail);
          const message =
            failure.category && failure.category !== 'unknown'
              ? friendlyStreamFailureMessage(failure, responseLanguage)
              : responseLanguage === 'zh-CN'
                ? 'Provider 流式传输已降级；Trainer 会继续等待完整回复，不会伪装成增量文本。'
                : 'Provider streaming is degraded; Trainer will finish this reply without pretending buffered text is incremental.';
          await context.workbench.postMessage({
            type: 'operation/status',
            payload: { tone: 'info', message },
          });
          continue;
        }
        throw new Error(detail || 'SSE stream failed.');
      }

      const parsed = parseSseJson(event);
      const chunkText = typeof parsed?.chunk === 'string' ? parsed.chunk : undefined;
      if (chunkText) {
        totalTokens += 1;
        if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
          return { ok: true, message: 'Stream invalidated.' };
        }
        await updateStreamingState(context, (state) => ({
          ...state,
          isStreaming: true,
          streamedContent: state.streamedContent + chunkText,
        }));
        if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
          return { ok: true, message: 'Stream invalidated.' };
        }
        await context.workbench.postMessage({
          type: 'stream/chunk',
          payload: { messageId, chunk: chunkText },
        });
        continue;
      }

      await updateStreamingState(context, (state) => ({
        ...state,
        isStreaming: true,
        streamedContent: state.streamedContent + event.data,
      }));
      if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
        return { ok: true, message: 'Stream invalidated.' };
      }
      await context.workbench.postMessage({
        type: 'stream/chunk',
        payload: { messageId, chunk: event.data },
      });
    }

    if (!sawCompletion || completionResponse === undefined) {
      throw new Error('SSE stream ended before a valid completion event.');
    }

    if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
      return { ok: true, message: 'Stream invalidated.' };
    }
    const replyFailure =
      completionResponse !== undefined
        ? extractUnusableReplyFailureFromResponse(completionResponse)
        : unusableReplyFailure(completionMeta);
    const reliability = resolveStreamOperationReliability(
      completionResponse,
      completionMeta,
      replyFailure,
    );
    await updateStreamingState(context, (state) => ({
      ...state,
      isStreaming: false,
      streamError: undefined,
      completionSummary: completionMeta.summary,
      completionNextStep: completionMeta.nextStep,
      completionStopReason: completionMeta.stopReason,
      toolCount:
        completionMeta.toolCount ?? (state.agentActivity.length > 0 ? state.agentActivity.length : undefined),
      agentic: completionMeta.agentic,
      reliabilityPhase: reliability.phase,
      reliabilityOutcome: reliability.outcome,
    }));
    if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
      return { ok: true, message: 'Stream invalidated.' };
    }
    if (replyFailure) {
      await markProviderReplyUnusable(context, providerConfig, replyFailure);
    }
    if (!activeCoachStream || !isCurrentCoachStream(context, activeCoachStream)) {
      return { ok: true, message: 'Stream invalidated.' };
    }
    await context.workbench.syncState();
    await context.workbench.postMessage({
      type: 'stream/complete',
      payload: {
        messageId,
        tokens: totalTokens,
        agentic: completionMeta.agentic,
        summary: completionMeta.summary,
        nextStep: completionMeta.nextStep,
        stopReason: completionMeta.stopReason,
        toolCount: completionMeta.toolCount,
        reliabilityPhase: reliability.phase,
        reliabilityOutcome: reliability.outcome,
      },
    });
    return {
      ok: true,
      message: 'Stream message completed.',
    };
  } catch (error) {
    if (
      error instanceof SidecarRequestAbortedError ||
      activeCoachStream?.abortController.signal.aborted ||
      (activeCoachStream !== undefined &&
        isWorkspaceInvalidatedCoachStream(context, activeCoachStream))
    ) {
      if (
        activeCoachStream !== undefined &&
        isWorkspaceInvalidatedCoachStream(context, activeCoachStream)
      ) {
        return {
          ok: true,
          message: 'Stream invalidated.',
        };
      }
      // Fail-closed OS timeline: pending→…→failure→ack (not silent success). Keep draft.
      await updateStreamingState(context, (state) => ({
        ...state,
        isStreaming: true,
        streamError: undefined,
        reliabilityPhase: 'failed',
        reliabilityOutcome: 'failure',
      }));
      await postStreamReliabilityStatus(context, 'failed', responseLanguage);
      await updateStreamingState(context, (state) => ({
        ...state,
        isStreaming: false,
        streamError: undefined,
        completionStopReason: 'cancelled',
        reliabilityPhase: 'acked',
        reliabilityOutcome: 'failure',
      }));
      await postStreamReliabilityStatus(context, 'acked', responseLanguage);
      await context.workbench.syncState();
      await context.workbench.postMessage({
        type: 'stream/cancelled',
        payload: { messageId },
      });
      return {
        ok: true,
        message: 'Stream cancelled.',
      };
    }
    const errorMessage = normalizeErrorText(error);
    const failure = classifyProviderFailure(errorMessage);
    const userMessage = sanitizeErrorSurfaceText(
      friendlyStreamFailureMessage(failure, responseLanguage),
    );
    if (failure.category) {
      await patchProviderFailureState(context, failure);
    }
    await updateStreamingState(context, (state) => ({
      ...state,
      isStreaming: false,
      streamError: userMessage,
      reliabilityPhase: 'acked',
      reliabilityOutcome: 'failure',
    }));
    await postStreamReliabilityStatus(context, 'failed', responseLanguage);
    await postStreamReliabilityStatus(context, 'acked', responseLanguage);
    await context.workbench.postMessage({
      type: 'stream/error',
      payload: {
        messageId,
        error: userMessage,
        category: failure.category,
        statusCode: failure.statusCode,
        retryable: failure.retryable,
        reliabilityPhase: 'acked',
        reliabilityOutcome: 'failure',
      },
    });
    return {
      ok: false,
      message: userMessage,
    };
    }
  } finally {
    if (activeCoachStream && activeCoachStreams.get(context) === activeCoachStream) {
      activeCoachStreams.delete(context);
      activeCoachStreamContexts.delete(context);
    } else if (
      !activeCoachStream &&
      streamGenerations.get(context) === streamGeneration
    ) {
      activeCoachStreamContexts.delete(context);
    }
  }
}

export async function cancelStreamMessageCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const active = activeCoachStreams.get(context);
  if (!active) {
    const trainingCancellation = await cancelTrainingCardStreamCommand(context, payload);
    if (trainingCancellation) {
      return trainingCancellation;
    }
    return {
      ok: false,
      message: 'No Trainer stream is currently running.',
    };
  }

  const requestedMessageId =
    payload && typeof payload === 'object' && !Array.isArray(payload)
      ? (payload as { messageId?: unknown }).messageId
      : undefined;
  if (typeof requestedMessageId === 'string' && requestedMessageId.trim() && requestedMessageId !== active.messageId) {
    return {
      ok: false,
      message: 'The requested Trainer stream is no longer current.',
    };
  }

  active.abortController.abort();
  void context.sidecarClient
    .postJson(
      active.sidecarPort,
      '/stream/cancel',
      { stream_id: active.messageId },
      { timeoutMs: 2000 },
    )
    .catch(() => {
      // The local abort remains the fallback when the sidecar has already
      // disconnected or is shutting down.
    });
  return {
    ok: true,
    message: 'Cancellation requested.',
  };
}

export async function generatePlanCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (context.getHostState().bootstrap.plan.frozen) {
    return {
      ok: false,
      message: frozenPlanGenerationMessage(resolveProviderGuardLanguage(context)),
    };
  }

  const goals = extractGoals(payload) ?? context.getHostState().bootstrap.profile.goals;
  const responseLanguage = resolveProviderGuardLanguage(context);
  const goalText = goals.length > 0 ? goals.join('; ') : 'the current learning goal';
  return sendStreamMessageCommand(context, {
    text: `Generate a formal learning plan for ${goalText}. Use the attached library materials as evidence, ask for clarification when the goal or available time is ambiguous, and explain stages, why now, verification, and the next step.`,
    intent: 'plan',
    activeView: 'plan',
    formalPlanMutation: true,
    resourceIds: context.getHostState().bootstrap.resources.map((resource) => resource.id),
    responseLanguage,
    useAgentLoop: true,
  });
}

export async function updatePlanCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const payloadRecord = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : undefined;
  if (
    payloadRecord &&
    (
      payloadRecord.evidenceAction !== undefined ||
      payloadRecord.evidenceActionScope !== undefined ||
      payloadRecord.evidenceIds !== undefined ||
      payloadRecord.evidenceFocusArea !== undefined ||
      payloadRecord.dryRun === true ||
      payloadRecord.restoreOrchestrationRunId !== undefined ||
      payloadRecord.restoreOrchestrationSteps !== undefined
    )
  ) {
    return {
      ok: false,
      message: 'This governed plan route is not supported in the current Trainer command surface.',
    };
  }

  const instructions =
    typeof payloadRecord?.instructions === 'string'
      ? payloadRecord.instructions
      : extractTextPayload(payload) ?? '';
  const planId = context.getHostState().bootstrap.plan.id;
  const restorePlanHistoryEntryId =
    typeof payloadRecord?.restorePlanHistoryEntryId === 'string'
      ? payloadRecord.restorePlanHistoryEntryId
      : undefined;
  const restorePlanHistoryVersion =
    typeof payloadRecord?.restorePlanHistoryVersion === 'number'
      ? payloadRecord.restorePlanHistoryVersion
      : undefined;

  if (restorePlanHistoryEntryId !== undefined || restorePlanHistoryVersion !== undefined) {
    const restoreResult = await runPlanCommand(
      context,
      '/plan/update',
      'Update Trainer plan',
      {
        plan_id: planId,
        workspace_id: getRuntimeWorkspaceId(context),
        instructions,
        restorePlanHistoryEntryId,
        restorePlanHistoryVersion,
      },
    );
    if (restoreResult.ok) {
      await context.patchWorkbenchData(
        mergePlanResultSnapshot(
          context.getHostState().bootstrap,
          restoreResult.data,
          getRuntimeWorkspaceId(context),
        ),
      );
    }
    return restoreResult;
  }

  const frozen =
    payloadRecord && 'frozen' in payloadRecord
      ? Boolean(payloadRecord.frozen)
      : true;
  const result = await runPlanCommand(
    context,
    '/plan/update',
    'Update Trainer plan',
    {
      plan_id: planId,
      workspace_id: getRuntimeWorkspaceId(context),
      instructions,
      freeze: frozen,
      frozen,
    },
  );
  if (result.ok) {
    await context.patchWorkbenchData(
      mergePlanResultSnapshot(
        context.getHostState().bootstrap,
        result.data,
        getRuntimeWorkspaceId(context),
      ),
    );
  }
  return result;
}

export async function createGlobalPlanCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const request = {
    session_id: context.getSessionId(),
    workspace_id: getRuntimeWorkspaceId(context),
    ...globalPlanCreateOverrides(payload),
  };
  return runGlobalPlanCommand(
    context,
    'post',
    '/plan/global',
    'Create global Trainer plan',
    request,
  );
}

export async function linkCurrentProjectPlanCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const projectPlanId = context.getHostState().bootstrap.plan.id.trim();
  if (!projectPlanId) {
    return {
      ok: false,
      message: 'Create a project plan before linking it to a global plan.',
    };
  }

  return runGlobalPlanCommand(
    context,
    'put',
    '/plan/global/projects',
    'Link current project plan',
    {
      session_id: context.getSessionId(),
      workspace_id: getRuntimeWorkspaceId(context),
      project_plan_id: projectPlanId,
    },
  );
}

export async function specifyTaskCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('turn a natural-language goal into a task spec'))) {
    return { ok: false, message: 'Workspace trust is required to specify a Trainer task.' };
  }

  const providerGuard = await ensureCoachProviderReady(context, 'specify training tasks');
  if (providerGuard) {
    return providerGuard;
  }

  const naturalLanguageGoal =
    extractTextPayload(payload) ??
    (await vscode.window.showInputBox({
      title: 'Specify Trainer task',
      prompt: 'Describe the coding task in natural language.',
      ignoreFocusOut: true,
    }));

  if (!naturalLanguageGoal) {
    return { ok: false, message: 'No natural-language goal provided.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  let response: unknown;
  try {
    response = await context.sidecarClient.postJson<unknown>(status.port, '/task/specify', {
      session_id: context.getSessionId(),
      workspace_id: getRuntimeWorkspaceId(context),
      natural_language_goal: naturalLanguageGoal,
    });
  } catch (error) {
    const gateFailure = livePlanTaskGateCommandFailure(error);
    if (gateFailure) {
      return gateFailure;
    }
    return { ok: false, message: userFacingErrorText(error) };
  }

  await context.patchWorkbenchData(
    mergeTaskResultSnapshot(
      context.getHostState().bootstrap,
      response,
      getRuntimeWorkspaceId(context),
    ),
  );
  return {
    ok: true,
    message: 'Trainer turned the prompt into a task spec.',
    data: response,
  };
}

export async function nextTaskCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('request the next Trainer task'))) {
    return { ok: false, message: 'Workspace trust is required to request the next task.' };
  }

  const providerGuard = await ensureCoachProviderReady(context, 'generate the next training task');
  if (providerGuard) {
    return providerGuard;
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const focusArea =
    extractTextPayload(payload) ?? context.getHostState().bootstrap.profile.focusAreas[0];
  let response: unknown;
  try {
    response = await context.sidecarClient.postJson<unknown>(status.port, '/task/next', {
      session_id: context.getSessionId(),
      workspace_id: getRuntimeWorkspaceId(context),
      focus_area: focusArea,
    });
  } catch (error) {
    const gateFailure = livePlanTaskGateCommandFailure(error);
    if (gateFailure) {
      return gateFailure;
    }
    return { ok: false, message: userFacingErrorText(error) };
  }

  await context.patchWorkbenchData(
    mergeTaskResultSnapshot(
      context.getHostState().bootstrap,
      response,
      getRuntimeWorkspaceId(context),
    ),
  );
  return {
    ok: true,
    message: 'Trainer generated the next task.',
    data: response,
  };
}

export async function saveCoachSettingsCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('save Trainer coach settings'))) {
    return { ok: false, message: 'Workspace trust is required to save coach settings.' };
  }

  const settings = extractCoachSettingsPayload(payload);
  const resourceSearchMode = settings?.resourceSearchMode
    ? normalizeResourceSearchMode(settings.resourceSearchMode)
    : undefined;
  const workspaceGate = trainerWorkspaceSessionGate(context);
  if (workspaceGate) {
    const current = context.getHostState().bootstrap;
    const localPatch: Partial<BootstrapData> = {
      memory: {
        ...current.memory,
        workspace: mergeLocalCoachSettings(current.memory.workspace, settings),
      },
    };
    if (settings?.teachingStyle) {
      localPatch.profile = {
        ...current.profile,
        preferredStyle: settings.teachingStyle,
      };
    }
    await context.patchWorkbenchData(localPatch);
    return {
      ok: true,
      message: 'Coach settings stay local until the current project is admitted to Trainer.',
    };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const response = await context.sidecarClient.postJson<unknown>(status.port, '/memory/settings', {
    session_id: context.getSessionId(),
    workspace_id: getRuntimeWorkspaceId(context),
    response_language: settings?.responseLanguage,
    answer_mode: settings?.answerMode,
    resource_search_mode: resourceSearchMode,
    teaching_style: settings?.teachingStyle,
    coach_defaults: settings?.coachDefaults,
    follow_current_file: settings?.followCurrentFile,
    context_detail: settings?.contextDetail,
    include_current_file: settings?.includeCurrentFile,
    include_selection: settings?.includeSelection,
    include_diagnostics: settings?.includeDiagnostics,
    include_related_files: settings?.includeRelatedFiles,
  });

  await context.patchWorkbenchData(
    mergeMemorySummarySnapshot(
      context.getHostState().bootstrap,
      response,
      getRuntimeWorkspaceId(context),
    ),
  );
  await context.workbench.syncState();

  return {
    ok: true,
    message: 'Coach settings saved.',
    data: response,
  };
}

function normalizeResumeProjectLanePayload(payload: unknown): ResumeProjectLanePayload | undefined {
  if (!payload || typeof payload !== 'object') {
    return undefined;
  }

  const record = payload as Record<string, unknown>;
  const workspaceId = typeof record.workspaceId === 'string' ? record.workspaceId : undefined;
  if (!workspaceId) {
    return undefined;
  }

  return {
    workspaceId,
    workspacePath: typeof record.workspacePath === 'string' ? record.workspacePath : undefined,
    workspaceLabel: typeof record.workspaceLabel === 'string' ? record.workspaceLabel : undefined,
    resumeSessionId:
      typeof record.resumeSessionId === 'string' ? record.resumeSessionId : undefined,
    sessionId: typeof record.sessionId === 'string' ? record.sessionId : undefined,
    targetView: typeof record.targetView === 'string' ? record.targetView : undefined,
    activeView: typeof record.activeView === 'string' ? record.activeView : undefined,
    targetTrainingSubmode:
      typeof record.targetTrainingSubmode === 'string'
        ? record.targetTrainingSubmode
        : undefined,
    trainingSubmode:
      typeof record.trainingSubmode === 'string' ? record.trainingSubmode : undefined,
    trainingRestoreTarget:
      typeof record.trainingRestoreTarget === 'string' ? record.trainingRestoreTarget : undefined,
    theoryDrillId: typeof record.theoryDrillId === 'string' ? record.theoryDrillId : undefined,
    scenarioLabId: typeof record.scenarioLabId === 'string' ? record.scenarioLabId : undefined,
    reviewArtifactId:
      typeof record.reviewArtifactId === 'string' ? record.reviewArtifactId : undefined,
    resourceSurface:
      typeof record.resourceSurface === 'string' ? record.resourceSurface : undefined,
    resourceId: typeof record.resourceId === 'string' ? record.resourceId : undefined,
    sandboxPath: typeof record.sandboxPath === 'string' ? record.sandboxPath : undefined,
    resourceDetailId:
      typeof record.resourceDetailId === 'string' ? record.resourceDetailId : undefined,
    previewPath: typeof record.previewPath === 'string' ? record.previewPath : undefined,
    resumeReason: typeof record.resumeReason === 'string' ? record.resumeReason : undefined,
    focusArea: typeof record.focusArea === 'string' ? record.focusArea : undefined,
    currentStageTitle:
      typeof record.currentStageTitle === 'string' ? record.currentStageTitle : undefined,
    latestSummary:
      typeof record.latestSummary === 'string' ? record.latestSummary : undefined,
  };
}

export async function resumeProjectLaneCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const resumePayload = normalizeResumeProjectLanePayload(payload);
  if (!resumePayload) {
    return { ok: false, message: 'No workspace lane was provided to resume.' };
  }

  const requestedSessionId = resumePayload.resumeSessionId ?? resumePayload.sessionId;
  const currentWorkspace = activeWorkspaceRoot(context);
  const requestedWorkspacePath = resumePayload.workspacePath ?? resumePayload.workspaceId;
  if (
    !sameWorkspacePath(currentWorkspace, resumePayload.workspaceId) &&
    !sameWorkspacePath(currentWorkspace, requestedWorkspacePath)
  ) {
    const pendingResume = {
      workspaceId: resumePayload.workspaceId,
      workspacePath: requestedWorkspacePath,
      workspaceLabel: resumePayload.workspaceLabel,
      resumeSessionId: requestedSessionId,
      targetView: resumePayload.targetView,
      targetTrainingSubmode: resumePayload.targetTrainingSubmode ?? resumePayload.trainingSubmode,
      activeView: resumePayload.targetView ?? resumePayload.activeView,
      trainingSubmode: resumePayload.targetTrainingSubmode ?? resumePayload.trainingSubmode,
      resourceSurface: resumePayload.resourceSurface,
      trainingRestoreTarget: resumePayload.trainingRestoreTarget,
      theoryDrillId: resumePayload.theoryDrillId,
      scenarioLabId: resumePayload.scenarioLabId,
      reviewArtifactId: resumePayload.reviewArtifactId,
      resourceId: resumePayload.resourceId,
      sandboxPath: resumePayload.sandboxPath,
      resourceDetailId: resumePayload.resourceDetailId,
      previewPath: resumePayload.previewPath,
      resumeReason: resumePayload.resumeReason,
      focusArea: resumePayload.focusArea,
      currentStageTitle: resumePayload.currentStageTitle,
      latestSummary: resumePayload.latestSummary,
    };
    await context.extensionContext.globalState.update(
      'trainer.session.pendingResumeProjectLane',
      pendingResume,
    );
    await vscode.commands.executeCommand(
      'vscode.openFolder',
      vscode.Uri.file(requestedWorkspacePath),
      false,
    );
    return {
      ok: true,
      message: 'Opening the target workspace so Trainer can resume the saved lane.',
      data: pendingResume,
    };
  }

  const workspaceGate = trainerWorkspaceSessionGate(context);
  if (workspaceGate) {
    return workspaceGate;
  }

  let summary = await fetchMemorySummaryForWorkspace(
    context,
    resumePayload.workspaceId,
    requestedSessionId,
  );
  const derivedPayload = deriveImplicitTrainingRestorePayload(summary, {
    ...resumePayload,
    resumeReason: resumePayload.resumeReason,
  });
  const restoreStep = resolveExplicitTrainingRestoreStepFromSummary(
    summary,
    derivedPayload,
    resumePayload.workspaceId,
  );
  if (derivedPayload.trainingRestoreTarget && !restoreStep) {
    return {
      ok: false,
      message: 'No governed restore history is available for that training asset.',
    };
  }

  if (restoreStep) {
    await context.patchWorkbenchData(
      mergeMemorySummarySnapshot(
        context.getHostState().bootstrap,
        summary,
        resumePayload.workspaceId,
      ),
    );
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
    }
    await context.sidecarClient.postJson(status.port, restoreStep.requestPath, restoreStep.body);
    summary = await fetchMemorySummaryForWorkspace(
      context,
      resumePayload.workspaceId,
      requestedSessionId,
    );
    await context.patchWorkbenchData(
      mergeMemorySummarySnapshot(
        context.getHostState().bootstrap,
        summary,
        resumePayload.workspaceId,
      ),
    );
  } else {
    await context.patchWorkbenchData(
      mergeMemorySummarySnapshot(
        context.getHostState().bootstrap,
        summary,
        resumePayload.workspaceId,
      ),
    );
  }

  await context.setSessionId(requestedSessionId ?? context.getSessionId());
  await context.workbench.syncState();

  const latestTrainingNextHop = resolveLatestTrainingNextHopFromSummary(summary);
  const memoryRecord = asTrainingRecord(asTrainingRecord(summary)?.memory);
  const theoryDrillRecord = asTrainingRecord(memoryRecord?.theory_drill);
  const scenarioLabRecord = asTrainingRecord(memoryRecord?.scenario_lab);
  const reviewArtifactRecord = asTrainingRecord(memoryRecord?.review_artifact);
  const restorePayload: Record<string, unknown> = {
    sessionId: requestedSessionId ?? context.getSessionId(),
    activeView: 'training',
    trainingSubmode: resolveResumeTrainingSubmode(
      summary,
      resumePayload.targetTrainingSubmode ?? resumePayload.trainingSubmode,
    ),
    workspaceLabel: resumePayload.workspaceLabel,
    resumeReason: resumePayload.resumeReason,
    focusArea: resolveResumeFocusArea(summary, resumePayload.focusArea),
    currentStageTitle: resumePayload.currentStageTitle,
    latestSummary: resumePayload.latestSummary,
    latestTrainingNextHop,
    resourceSurface: resumePayload.resourceSurface,
    resourceId: resumePayload.resourceId,
    sandboxPath: resumePayload.sandboxPath,
    resourceDetailId: resumePayload.resourceDetailId,
    previewPath: resumePayload.previewPath,
  };
  if (restoreStep?.target === 'theory_drill') {
    restorePayload.trainingRestoreTarget = 'theory_drill';
    restorePayload.theoryDrillId =
      asNonEmptyString(theoryDrillRecord?.id) ??
      derivedPayload.theoryDrillId;
  } else if (restoreStep?.target === 'scenario_lab') {
    restorePayload.trainingRestoreTarget = 'scenario_lab';
    restorePayload.scenarioLabId =
      asNonEmptyString(scenarioLabRecord?.id) ??
      derivedPayload.scenarioLabId;
  } else if (restoreStep?.target === 'review_artifact') {
    restorePayload.trainingRestoreTarget = 'review_artifact';
    restorePayload.reviewArtifactId =
      asNonEmptyString(reviewArtifactRecord?.id) ??
      derivedPayload.reviewArtifactId;
  }

  await context.workbench.postMessage({
    type: 'ui/restoreView',
    payload: restorePayload,
  });

  return {
    ok: true,
    message: 'Trainer resumed the requested project lane.',
    data: restorePayload,
  };
}

export async function restartSessionCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const workspaceGate = trainerWorkspaceSessionGate(context);
  if (workspaceGate) {
    return workspaceGate;
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const runtimeWorkspace = getRuntimeWorkspaceContext(context);
  const workspacePath =
    runtimeWorkspace.canonicalProjectPath ?? activeWorkspaceRoot(context) ?? getWorkspaceId(context);
  const workspaceName =
    vscode.workspace.name ?? path.basename(workspacePath) ?? workspacePath;
  const workspaceFileSnapshot = await buildWorkspaceFileSnapshot(context);
  const response = await context.sidecarClient.postJson<unknown>(status.port, '/session/start', {
    workspace_id: runtimeWorkspace.workspaceId,
    workspace_name: workspaceName,
    workspace_path: workspacePath,
    remote_name: context.getHostState().workspace.remoteName ?? '',
    workspace_trusted: Boolean(context.getHostState().workspace.trusted),
    force_new: true,
    ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
  });
  const startedSessionId =
    asNonEmptyString(asTrainingRecord(response)?.session_id) ?? context.getSessionId();
  await context.setStreamingState(createEmptyTrainerStreamingState());
  await context.setSessionId(startedSessionId);
  await context.patchWorkbenchData(
    mergeSessionStartSnapshot(
      context.getHostState().bootstrap,
      response,
      runtimeWorkspace.workspaceId,
    ),
  );

  const summary = await fetchMemorySummaryForWorkspace(
    context,
    runtimeWorkspace.workspaceId,
    startedSessionId,
  );
  await context.patchWorkbenchData(
    mergeMemorySummarySnapshot(
      context.getHostState().bootstrap,
      summary,
      runtimeWorkspace.workspaceId,
    ),
  );
  await context.workbench.syncState();
  await context.workbench.postMessage({
    type: 'ui/restoreView',
    payload: {
      sessionId: startedSessionId,
      activeView: 'coach',
    },
  });

  return {
    ok: true,
    message: 'Trainer restarted the current coaching session.',
    data: summary,
  };
}

async function runPlanCommand(
  context: CommandContext,
  path: string,
  title: string,
  requestBody?: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('work with learning plans'))) {
    return { ok: false, message: 'Workspace trust is required for plan operations.' };
  }

  const providerGuard = await ensureCoachProviderReady(context, 'work with learning plans');
  if (providerGuard) {
    return providerGuard;
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  try {
    const response = await context.sidecarClient.postJson<unknown>(
      status.port,
      path,
      requestBody,
    );

    await context.workbench.syncState();
    return {
      ok: true,
      message: `${title} request sent.`,
      data: response,
    };
  } catch (error) {
    const gateFailure = livePlanTaskGateCommandFailure(error);
    if (gateFailure) {
      return gateFailure;
    }
    return { ok: false, message: userFacingErrorText(error) };
  }
}

async function runGlobalPlanCommand(
  context: CommandContext,
  method: 'post' | 'put',
  path: string,
  title: string,
  requestBody: unknown,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('manage global learning plans'))) {
    return { ok: false, message: 'Workspace trust is required for global plan operations.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return { ok: false, message: status.detail ?? 'Sidecar is unavailable.' };
  }

  const response =
    method === 'put'
      ? await context.sidecarClient.putJson<unknown>(status.port, path, requestBody)
      : await context.sidecarClient.postJson<unknown>(status.port, path, requestBody);
  await context.patchWorkbenchData(
    mergePlanResultSnapshot(
      context.getHostState().bootstrap,
      response,
      getRuntimeWorkspaceId(context),
    ),
  );
  await context.workbench.syncState();

  return {
    ok: true,
    message: `${title} request sent.`,
    data: response,
  };
}

function globalPlanCreateOverrides(payload: unknown): Record<string, string | string[]> {
  const record = asTrainingRecord(payload);
  if (!record) {
    return {};
  }

  const title = asNonEmptyString(record.title);
  const summary = asNonEmptyString(record.summary);
  const goals = Array.isArray(record.goals)
    ? record.goals.filter(
        (goal): goal is string => typeof goal === 'string' && goal.trim().length > 0,
      )
    : undefined;

  return {
    ...(title ? { title } : {}),
    ...(summary ? { summary } : {}),
    ...(goals && goals.length > 0 ? { goals } : {}),
  };
}

function shouldPreferNonStreamingCoachTruth(
  payload: StreamMessagePayload,
): boolean {
  const intent = payload.intent ?? 'coach';
  if (intent !== 'coach') {
    return false;
  }
  const text = payload.text.trim();
  if (!text) {
    return false;
  }
  const lowered = text.toLowerCase();
  const asksPromise =
    lowered.includes('first viewport promise') || text.includes('首屏承诺');
  const asksBoundary =
    lowered.includes('must not become') ||
    text.includes('绝不能变成') ||
    text.includes('不能变成') ||
    text.includes('不能成为') ||
    text.includes('不应该变成');
  const mentionsView = [
    'coach view',
    'coach 视图',
    '对话视图',
    'plan view',
    'plan 视图',
    '计划视图',
    'resources view',
    'resources 视图',
    '资料视图',
    '资源视图',
    'training view',
    'training 视图',
    '训练视图',
    'settings view',
    'settings 视图',
    '设置视图',
  ].some((marker) => lowered.includes(marker.toLowerCase()));
  return asksPromise && asksBoundary && mentionsView;
}

function extractTextPayload(payload: unknown): string | undefined {
  if (typeof payload === 'string') {
    return payload;
  }
  return extractSessionPayload(payload)?.text;
}

function extractSessionPayload(payload: unknown): ResourceComposerSessionMessagePayload | undefined {
  if (!payload || typeof payload !== 'object') {
    return undefined;
  }

  const text = 'text' in payload ? (payload as { text?: unknown }).text : undefined;
  if (typeof text !== 'string') {
    return undefined;
  }

  const asRecord = payload as Record<string, unknown>;
  const coachDefaultsRecord =
    asRecord.coachDefaults && typeof asRecord.coachDefaults === 'object'
      ? (asRecord.coachDefaults as Record<string, unknown>)
      : undefined;
  const workspaceMemoryRecord =
    coachDefaultsRecord?.workspaceMemoryToggles &&
    typeof coachDefaultsRecord.workspaceMemoryToggles === 'object'
      ? (coachDefaultsRecord.workspaceMemoryToggles as Record<string, unknown>)
      : undefined;
  return {
    text,
    intent:
      asRecord.intent === 'coach' ||
      asRecord.intent === 'next_task' ||
      asRecord.intent === 'review' ||
      asRecord.intent === 'plan' ||
      asRecord.intent === 'task'
        ? (asRecord.intent as SessionMessagePayload['intent'])
        : undefined,
    formalPlanMutation:
      asRecord.formalPlanMutation === true ? true : undefined,
    activeView:
      asRecord.activeView === 'coach' ||
      asRecord.activeView === 'plan' ||
      asRecord.activeView === 'resources' ||
      asRecord.activeView === 'training' ||
      asRecord.activeView === 'settings'
        ? (asRecord.activeView as SessionMessagePayload['activeView'])
        : undefined,
    resourceIds:
      Array.isArray(asRecord.resourceIds)
        ? asRecord.resourceIds.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        : undefined,
    resourceComposerIntent: extractResourceComposerIntent(asRecord.resourceComposerIntent),
    includeCurrentFile:
      typeof asRecord.includeCurrentFile === 'boolean' ? asRecord.includeCurrentFile : undefined,
    includeSelection:
      typeof asRecord.includeSelection === 'boolean' ? asRecord.includeSelection : undefined,
    includeDiagnostics:
      typeof asRecord.includeDiagnostics === 'boolean' ? asRecord.includeDiagnostics : undefined,
    includeRelatedFiles:
      typeof asRecord.includeRelatedFiles === 'boolean' ? asRecord.includeRelatedFiles : undefined,
    contextDetail:
      asRecord.contextDetail === 'focused' ||
      asRecord.contextDetail === 'balanced' ||
      asRecord.contextDetail === 'full'
        ? asRecord.contextDetail
        : undefined,
    responseLanguage:
      isComposerLanguage(asRecord.responseLanguage) ? asRecord.responseLanguage : undefined,
    answerMode:
      asRecord.answerMode === 'auto' ||
      asRecord.answerMode === 'coach-first' ||
      asRecord.answerMode === 'balanced' ||
      asRecord.answerMode === 'direct'
        ? asRecord.answerMode
        : undefined,
    coachDefaults: coachDefaultsRecord
      ? {
          memoryScope:
            coachDefaultsRecord.memoryScope === 'project' ||
            coachDefaultsRecord.memoryScope === 'personal' ||
            coachDefaultsRecord.memoryScope === 'session'
              ? coachDefaultsRecord.memoryScope
              : undefined,
          workingSetMode:
            coachDefaultsRecord.workingSetMode === 'focused' ||
            coachDefaultsRecord.workingSetMode === 'balanced' ||
            coachDefaultsRecord.workingSetMode === 'broad'
              ? coachDefaultsRecord.workingSetMode
              : undefined,
          reviewCadence:
            coachDefaultsRecord.reviewCadence === 'light' ||
            coachDefaultsRecord.reviewCadence === 'steady' ||
            coachDefaultsRecord.reviewCadence === 'active'
              ? coachDefaultsRecord.reviewCadence
              : undefined,
          reviewReminderMode:
            coachDefaultsRecord.reviewReminderMode === 'due' ||
            coachDefaultsRecord.reviewReminderMode === 'ahead' ||
            coachDefaultsRecord.reviewReminderMode === 'digest'
              ? coachDefaultsRecord.reviewReminderMode
              : undefined,
          workspaceMemoryToggles: workspaceMemoryRecord
            ? {
                decisions:
                  typeof workspaceMemoryRecord.decisions === 'boolean'
                    ? workspaceMemoryRecord.decisions
                    : undefined,
                patterns:
                  typeof workspaceMemoryRecord.patterns === 'boolean'
                    ? workspaceMemoryRecord.patterns
                    : undefined,
                resources:
                  typeof workspaceMemoryRecord.resources === 'boolean'
                    ? workspaceMemoryRecord.resources
                    : undefined,
              }
            : undefined,
        }
      : undefined,
    attachments: extractAttachmentsPayload(asRecord.attachments),
    useAgentLoop:
      typeof asRecord.useAgentLoop === 'boolean' ? asRecord.useAgentLoop : undefined,
    requestId:
      typeof asRecord.requestId === 'string' && asRecord.requestId.trim()
        ? asRecord.requestId.trim()
        : undefined,
    planRuntimeRecovery: normalizeRecoveredPlanResumeTurn(asRecord.planRuntimeRecovery),
  };
}

function extractResourceComposerIntent(value: unknown): ResourceComposerIntentPayload | undefined {
  if (!value || typeof value !== 'object') {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const mode =
    record.mode === 'locate' ||
    record.mode === 'download' ||
    record.mode === 'organize' ||
    record.mode === 'cards'
      ? record.mode
      : undefined;
  if (!mode) {
    return undefined;
  }
  const resourceIds = Array.isArray(record.resourceIds)
    ? record.resourceIds
        .filter((item): item is string => typeof item === 'string')
        .map((item) => item.trim())
        .filter((item) => isOpaqueResourceId(item))
        .filter((item, index, values) => values.indexOf(item) === index)
        .slice(0, 12)
    : undefined;
  return {
    mode,
    resourceIds: resourceIds && resourceIds.length > 0 ? resourceIds : undefined,
  };
}

function isOpaqueResourceId(value: string): boolean {
  return (
    value.length > 0 &&
    value.length <= 160 &&
    !value.includes('\0') &&
    !value.includes('/') &&
    !value.includes('\\') &&
    !value.includes('..')
  );
}

function resourceComposerIntentWire(
  intent: ResourceComposerIntentPayload | undefined,
): { mode: ResourceComposerIntentPayload['mode']; resource_ids: string[] } | undefined {
  if (!intent) {
    return undefined;
  }
  return {
    mode: intent.mode,
    resource_ids: intent.resourceIds ?? [],
  };
}

function extractAttachmentsPayload(value: unknown): MessageAttachmentPayload[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const normalized: MessageAttachmentPayload[] = [];
  for (const item of value) {
    if (!item || typeof item !== 'object') {
      continue;
    }
    const record = item as Record<string, unknown>;
    const id = typeof record.id === 'string' ? record.id : undefined;
    const kindRaw = typeof record.kind === 'string' ? record.kind : 'image';
    const kind = kindRaw === 'file' ? 'file' : 'image';
    const mimeType = typeof record.mimeType === 'string' ? record.mimeType : 'image/png';
    if (!id) {
      continue;
    }
    normalized.push({
      id,
      kind,
      mimeType,
      dataBase64: typeof record.dataBase64 === 'string' ? record.dataBase64 : undefined,
      sourcePath: typeof record.sourcePath === 'string' ? record.sourcePath : undefined,
      name: typeof record.name === 'string' ? record.name : undefined,
      caption: typeof record.caption === 'string' ? record.caption : undefined,
      byteSize: typeof record.byteSize === 'number' ? record.byteSize : undefined,
    });
  }
  return normalized.length > 0 ? normalized : undefined;
}

function normalizeAttachments(
  attachments: MessageAttachmentPayload[] | undefined,
): Array<Record<string, unknown>> | undefined {
  if (!attachments || attachments.length === 0) {
    return undefined;
  }
  return attachments.map((attachment) => ({
    id: attachment.id,
    kind: attachment.kind,
    mimeType: attachment.mimeType,
    dataBase64: attachment.dataBase64,
    sourcePath: attachment.sourcePath,
    name: attachment.name,
    caption: attachment.caption,
    byteSize: attachment.byteSize,
  }));
}

function extractStreamPayload(payload: unknown): ResourceComposerStreamMessagePayload | undefined {
  const sessionPayload = extractSessionPayload(payload);
  if (!sessionPayload) {
    return undefined;
  }

  return {
    ...sessionPayload,
    stream: true,
    sessionId:
      payload && typeof payload === 'object' && 'sessionId' in payload
        ? String((payload as { sessionId?: unknown }).sessionId)
        : undefined,
  };
}

function extractGoals(payload: unknown): string[] | undefined {
  if (!payload || typeof payload !== 'object') {
    return undefined;
  }
  if ('goals' in payload && Array.isArray((payload as { goals?: unknown }).goals)) {
    return (payload as { goals: unknown[] }).goals.filter(
      (goal): goal is string => typeof goal === 'string' && goal.trim().length > 0,
    );
  }
  return undefined;
}

function getCurrentFilePayload(
  context: CommandContext,
  payload?: SessionMessagePayload,
  message?: string,
):
  | {
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
    }
  | undefined {
  const editor = vscode.window?.activeTextEditor;
  if (!editor) {
    return undefined;
  }

  const selection = editor.selection;
  const includeCurrentFile =
    payload?.includeCurrentFile ??
    shouldAttachCurrentFile(message ?? payload?.text ?? '', payload?.intent);
  const includeSelection = payload?.includeSelection ?? true;
  const hasSelection = includeSelection && Boolean(selection) && !selection.isEmpty;
  if (!includeCurrentFile && !hasSelection) {
    return undefined;
  }

  const selectionOnly = !includeCurrentFile;
  const includeDiagnostics = payload?.includeDiagnostics ?? true;
  const includeRelatedFiles = payload?.includeRelatedFiles ?? true;
  const workingSetMode = payload?.coachDefaults?.workingSetMode;
  const contextDetail =
    payload?.contextDetail ??
    (workingSetMode === 'focused' ? 'focused' : workingSetMode === 'broad' ? 'full' : 'balanced');
  const primaryExcerpt = buildPrimaryExcerpt(editor.document, selection, contextDetail);
  const diagnostics = !selectionOnly && includeDiagnostics
    ? vscode.languages.getDiagnostics(editor.document.uri).map(
        (item) =>
          `[${diagnosticSeverityLabel(item.severity)}] line ${item.range.start.line + 1}: ${item.message}`,
      )
    : undefined;
  const relatedFiles =
    !selectionOnly && includeRelatedFiles
      ? resolveRelatedFiles(editor.document, contextDetail, workingSetMode)
      : undefined;
  const workspace = !selectionOnly ? context.getHostState().workspace : undefined;

  return {
    path: editor.document.uri.fsPath,
    language_id: editor.document.languageId,
    content: selectionOnly ? primaryExcerpt.excerpt : editor.document.getText(),
    content_excerpt: primaryExcerpt.excerpt,
    content_line_span: primaryExcerpt.lineSpan,
    content_strategy: primaryExcerpt.strategy,
    selection_text:
      hasSelection
        ? editor.document.getText(selection)
        : undefined,
    selection_range:
      hasSelection
        ? `${selection.start.line + 1}:${selection.start.character + 1}-${selection.end.line + 1}:${selection.end.character + 1}`
        : undefined,
    diagnostics: diagnostics && diagnostics.length > 0 ? diagnostics.slice(0, 20) : undefined,
    recent_files: workspace?.recentFiles?.slice(0, 5),
    recent_edited_files: workspace?.recentEditedFiles?.slice(0, 5),
    related_files: relatedFiles,
  };
}

function resolveRelatedFiles(
  document: vscode.TextDocument,
  contextDetail: 'focused' | 'balanced' | 'full',
  workingSetMode?: 'focused' | 'balanced' | 'broad',
): Array<{ path: string; reason: string; excerpt?: string; line_span?: string }> | undefined {
  const baseDir = path.dirname(document.uri.fsPath);
  const language = document.languageId;
  const matches = new Map<string, string>();

  for (const reference of extractImportReferences(document.getText(), language)) {
    const resolved = resolveImportReference(baseDir, language, reference);
    if (!resolved || resolved.path === document.uri.fsPath) {
      continue;
    }
    if (!matches.has(resolved.path)) {
      matches.set(resolved.path, reference.reason);
    }
  }

  return matches.size > 0
    ? Array.from(matches.entries())
        .slice(0, workingSetMode === 'focused' ? 2 : workingSetMode === 'broad' ? 6 : 4)
        .map(([resolvedPath, reason]) => ({
          path: resolvedPath,
          reason,
          ...buildRelatedFileExcerpt(resolvedPath, contextDetail),
        }))
    : undefined;
}

function buildPrimaryExcerpt(
  document: vscode.TextDocument,
  selection: vscode.Selection,
  contextDetail: 'focused' | 'balanced' | 'full',
): { excerpt: string; lineSpan: string; strategy: string } {
  const totalLines = document.lineCount;
  const maxChars = contextDetail === 'full' ? 12000 : contextDetail === 'focused' ? 3500 : 6000;

  if (!selection.isEmpty) {
    const before = contextDetail === 'focused' ? 6 : contextDetail === 'full' ? 16 : 10;
    const after = contextDetail === 'focused' ? 12 : contextDetail === 'full' ? 32 : 20;
    const startLine = Math.max(0, selection.start.line - before);
    const endLine = Math.min(totalLines - 1, selection.end.line + after);
    return {
      excerpt: collectDocumentLines(document, startLine, endLine, maxChars),
      lineSpan: `${startLine + 1}-${endLine + 1}`,
      strategy: `selection-window:${contextDetail}`,
    };
  }

  if (contextDetail !== 'full' && (document.getText().length > 12000 || totalLines > 200)) {
    const endLine = Math.min(totalLines - 1, contextDetail === 'focused' ? 79 : 119);
    return {
      excerpt: collectDocumentLines(document, 0, endLine, maxChars),
      lineSpan: `1-${endLine + 1}`,
      strategy: `head-window:${contextDetail}`,
    };
  }

  const endLine = Math.max(0, contextDetail === 'full' ? totalLines - 1 : Math.min(totalLines - 1, 199));
  return {
    excerpt: collectDocumentLines(document, 0, endLine, contextDetail === 'full' ? 24000 : maxChars),
    lineSpan: `1-${endLine + 1}`,
    strategy: contextDetail === 'full' ? 'full-file' : `wide-window:${contextDetail}`,
  };
}

function extractImportReferences(
  content: string,
  languageId: string,
): Array<{ specifier: string; reason: string }> {
  const results: Array<{ specifier: string; reason: string }> = [];
  const push = (specifier: string, reason: string) => {
    if (specifier.startsWith('.')) {
      results.push({ specifier, reason });
    }
  };

  if (languageId === 'python') {
    for (const match of content.matchAll(/^\s*from\s+([.\w]+)\s+import\s+/gm)) {
      push(match[1], 'relative import');
    }
    return results;
  }

  for (const match of content.matchAll(/from\s+["']([^"']+)["']/g)) {
    push(match[1], 'import');
  }
  for (const match of content.matchAll(/import\s*\(\s*["']([^"']+)["']\s*\)/g)) {
    push(match[1], 'dynamic import');
  }
  return results;
}

function resolveImportReference(
  baseDir: string,
  languageId: string,
  reference: { specifier: string; reason: string },
): { path: string; reason: string } | undefined {
  const candidateBases =
    languageId === 'python'
      ? resolvePythonSpecifier(baseDir, reference.specifier)
      : [path.resolve(baseDir, reference.specifier)];

  const extensions =
    languageId === 'python'
      ? ['.py', path.sep + '__init__.py']
      : ['', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json', path.sep + 'index.ts', path.sep + 'index.tsx', path.sep + 'index.js'];

  for (const candidateBase of candidateBases) {
    for (const extension of extensions) {
      const candidatePath =
        extension.startsWith(path.sep) ? `${candidateBase}${extension}` : `${candidateBase}${extension}`;
      if (fs.existsSync(candidatePath) && fs.statSync(candidatePath).isFile()) {
        return { path: candidatePath, reason: reference.reason };
      }
    }
  }

  return undefined;
}

function resolvePythonSpecifier(baseDir: string, specifier: string): string[] {
  const leadingDots = specifier.match(/^\.+/)?.[0].length ?? 0;
  const remainder = specifier.slice(leadingDots).replace(/\./g, path.sep);
  let resolvedBase = baseDir;
  for (let index = 1; index < leadingDots; index += 1) {
    resolvedBase = path.dirname(resolvedBase);
  }
  return [path.resolve(resolvedBase, remainder)];
}

function buildRelatedFileExcerpt(
  filePath: string,
  contextDetail: 'focused' | 'balanced' | 'full',
): { excerpt?: string; line_span?: string } {
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    const lines = content.split(/\r?\n/);
    const endLine = Math.min(lines.length, contextDetail === 'focused' ? 20 : contextDetail === 'full' ? 80 : 40);
    return {
      excerpt: truncateLargeBlock(
        lines.slice(0, endLine).join('\n'),
        contextDetail === 'focused' ? 1200 : contextDetail === 'full' ? 5000 : 2500,
      ),
      line_span: `1-${endLine}`,
    };
  } catch {
    return {};
  }
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
  return truncateLargeBlock(parts.join('\n'), maxChars);
}

/*
function truncateLargeBlock(value: string, maxChars: number): string {
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, maxChars - 1)}…`;
}

*/

function truncateLargeBlock(value: string, maxChars: number): string {
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxChars - 1))}...`;
}

function normalizeAnswerMode(
  value: SessionMessagePayload['answerMode'] | undefined,
): 'auto' | 'guided' | 'balanced' | 'direct' | undefined {
  if (value === 'auto') {
    return 'auto';
  }
  if (value === 'balanced' || value === 'direct') {
    return value;
  }
  if (value === 'coach-first') {
    return 'guided';
  }
  return undefined;
}

function usesSessionMessageRoute(
  payload: SessionMessagePayload | undefined,
): boolean {
  return (
    (!payload?.intent || payload.intent === 'coach') &&
    (!payload?.activeView || payload.activeView === 'coach')
  );
}

function diagnosticSeverityLabel(severity: vscode.DiagnosticSeverity): string {
  switch (severity) {
    case vscode.DiagnosticSeverity.Error:
      return 'error';
    case vscode.DiagnosticSeverity.Warning:
      return 'warning';
    case vscode.DiagnosticSeverity.Information:
      return 'info';
    case vscode.DiagnosticSeverity.Hint:
    default:
      return 'hint';
  }
}

function extractCoachSettingsPayload(payload: unknown): CoachSettingsPayload | undefined {
  if (!payload || typeof payload !== 'object') {
    return undefined;
  }

  const asRecord = payload as Record<string, unknown>;
  const coachDefaultsRecord =
    asRecord.coachDefaults && typeof asRecord.coachDefaults === 'object'
      ? (asRecord.coachDefaults as Record<string, unknown>)
      : undefined;
  const workspaceMemoryRecord =
    coachDefaultsRecord?.workspaceMemoryToggles &&
    typeof coachDefaultsRecord.workspaceMemoryToggles === 'object'
      ? (coachDefaultsRecord.workspaceMemoryToggles as Record<string, unknown>)
      : undefined;

  return {
    responseLanguage:
      isComposerLanguage(asRecord.responseLanguage) ? asRecord.responseLanguage : undefined,
    answerMode:
      asRecord.answerMode === 'auto' ||
      asRecord.answerMode === 'coach-first' ||
      asRecord.answerMode === 'balanced' ||
      asRecord.answerMode === 'direct'
        ? asRecord.answerMode
        : undefined,
    resourceSearchMode: extractResourceSearchMode(asRecord.resourceSearchMode),
    teachingStyle:
      asRecord.teachingStyle === 'auto' ||
      asRecord.teachingStyle === 'guided' ||
      asRecord.teachingStyle === 'concept-first' ||
      asRecord.teachingStyle === 'hands-on' ||
      asRecord.teachingStyle === 'challenging'
        ? asRecord.teachingStyle
        : undefined,
    followCurrentFile:
      typeof asRecord.followCurrentFile === 'boolean' ? asRecord.followCurrentFile : undefined,
    contextDetail:
      asRecord.contextDetail === 'focused' ||
      asRecord.contextDetail === 'balanced' ||
      asRecord.contextDetail === 'full'
        ? asRecord.contextDetail
        : undefined,
    includeCurrentFile:
      typeof asRecord.includeCurrentFile === 'boolean' ? asRecord.includeCurrentFile : undefined,
    includeSelection:
      typeof asRecord.includeSelection === 'boolean' ? asRecord.includeSelection : undefined,
    includeDiagnostics:
      typeof asRecord.includeDiagnostics === 'boolean' ? asRecord.includeDiagnostics : undefined,
    includeRelatedFiles:
      typeof asRecord.includeRelatedFiles === 'boolean' ? asRecord.includeRelatedFiles : undefined,
    coachDefaults: coachDefaultsRecord
      ? {
          memoryScope:
            coachDefaultsRecord.memoryScope === 'project' ||
            coachDefaultsRecord.memoryScope === 'personal' ||
            coachDefaultsRecord.memoryScope === 'session'
              ? coachDefaultsRecord.memoryScope
              : undefined,
          workingSetMode:
            coachDefaultsRecord.workingSetMode === 'focused' ||
            coachDefaultsRecord.workingSetMode === 'balanced' ||
            coachDefaultsRecord.workingSetMode === 'broad'
              ? coachDefaultsRecord.workingSetMode
              : undefined,
          reviewCadence:
            coachDefaultsRecord.reviewCadence === 'light' ||
            coachDefaultsRecord.reviewCadence === 'steady' ||
            coachDefaultsRecord.reviewCadence === 'active'
              ? coachDefaultsRecord.reviewCadence
              : undefined,
          reviewReminderMode:
            coachDefaultsRecord.reviewReminderMode === 'due' ||
            coachDefaultsRecord.reviewReminderMode === 'ahead' ||
            coachDefaultsRecord.reviewReminderMode === 'digest'
              ? coachDefaultsRecord.reviewReminderMode
              : undefined,
          workspaceMemoryToggles: workspaceMemoryRecord
            ? {
                decisions:
                  typeof workspaceMemoryRecord.decisions === 'boolean'
                    ? workspaceMemoryRecord.decisions
                    : undefined,
                patterns:
                  typeof workspaceMemoryRecord.patterns === 'boolean'
                    ? workspaceMemoryRecord.patterns
                    : undefined,
                resources:
                  typeof workspaceMemoryRecord.resources === 'boolean'
                    ? workspaceMemoryRecord.resources
                    : undefined,
              }
            : undefined,
        }
      : undefined,
  };
}

function parseSseJson(event: SSEMessage): Record<string, unknown> | undefined {
  try {
    const parsed = JSON.parse(event.data);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}

function streamStatusMessage(
  phase: string | undefined,
  responseLanguage: ComposerLanguage,
): string | undefined {
  if (!phase) {
    return undefined;
  }
  const timeline: Record<string, Record<ComposerLanguage, string>> = {
    pending: {
      'zh-CN': '这一轮已受理，正在等待执行。',
      'en-US': 'This turn is pending. Trainer accepted it and has not finished yet.',
      'es-ES': 'Este turno está pendiente. Trainer lo aceptó y aún no ha terminado.',
      'fr-FR': 'Ce tour est en attente. Trainer l’a accepté et n’a pas encore terminé.',
      'de-DE': 'Dieser Zug wartet. Trainer hat ihn angenommen und ist noch nicht fertig.',
      'ja-JP': 'このターンは受付済みです。まだ完了していません。',
      'ko-KR': '이 턴은 접수되었습니다. 아직 끝나지 않았습니다.',
      'pt-BR': 'Este turno está pendente. O Trainer aceitou e ainda não terminou.',
    },
    executing: {
      'zh-CN': '正在执行这一轮，还没有确认结果。',
      'en-US': 'This turn is running. Wait for acknowledgement before treating it as done.',
      'es-ES': 'Este turno se está ejecutando. Espera el acuse antes de darlo por hecho.',
      'fr-FR': 'Ce tour est en cours. Attendez l’accusé avant de le considérer comme terminé.',
      'de-DE': 'Dieser Zug läuft. Warte auf die Bestätigung, bevor du ihn als erledigt siehst.',
      'ja-JP': 'このターンを実行中です。確認が戻るまで完了としないでください。',
      'ko-KR': '이 턴을 실행 중입니다. 확인이 오기 전에 완료로 보지 마세요.',
      'pt-BR': 'Este turno está em execução. Espere o reconhecimento antes de tratar como concluído.',
    },
    failed: {
      'zh-CN': '这一轮失败了，不能当成成功回复。',
      'en-US': 'This turn failed. It is not a successful reply.',
      'es-ES': 'Este turno falló. No es una respuesta correcta.',
      'fr-FR': 'Ce tour a échoué. Ce n’est pas une réponse réussie.',
      'de-DE': 'Dieser Zug ist fehlgeschlagen. Das ist keine erfolgreiche Antwort.',
      'ja-JP': 'このターンは失敗しました。成功した返信ではありません。',
      'ko-KR': '이 턴은 실패했습니다. 성공한 답변이 아닙니다.',
      'pt-BR': 'Este turno falhou. Não é uma resposta bem-sucedida.',
    },
    acked: {
      'zh-CN': '结果已记录。可以重试，或去设置里修复连接。',
      'en-US': 'Trainer recorded the result. Retry, or repair the connection in Settings.',
      'es-ES': 'Trainer registró el resultado. Reintenta o repara la conexión en Ajustes.',
      'fr-FR': 'Trainer a enregistré le résultat. Réessayez, ou réparez la connexion dans Réglages.',
      'de-DE': 'Trainer hat das Ergebnis festgehalten. Erneut versuchen oder die Verbindung in den Einstellungen reparieren.',
      'ja-JP': '結果を記録しました。再試行するか、設定で接続を直してください。',
      'ko-KR': '결과를 기록했습니다. 다시 시도하거나 설정에서 연결을 고치세요.',
      'pt-BR': 'O Trainer registrou o resultado. Tente de novo ou repare a conexão em Configurações.',
    },
    cancelled: {
      'zh-CN': '这一轮已取消。',
      'en-US': 'This turn was cancelled.',
      'es-ES': 'Este turno se canceló.',
      'fr-FR': 'Ce tour a été annulé.',
      'de-DE': 'Dieser Zug wurde abgebrochen.',
      'ja-JP': 'このターンはキャンセルされました。',
      'ko-KR': '이 턴이 취소되었습니다.',
      'pt-BR': 'Este turno foi cancelado.',
    },
  };
  const localized = timeline[phase];
  if (localized) {
    return localized[responseLanguage] ?? localized['en-US'];
  }
  const preparing = responseLanguage === 'zh-CN'
    ? {
        preparing_context: '\u6b63\u5728\u51c6\u5907\u5f53\u524d\u5de5\u4f5c\u533a\u548c\u5b66\u4e60\u4e0a\u4e0b\u6587\u3002',
        requesting_model: '\u6b63\u5728\u5411\u5df2\u914d\u7f6e\u7684\u6a21\u578b\u8bf7\u6c42\u56de\u590d\u3002',
      }
    : {
        preparing_context: 'Preparing the current workspace and learning context.',
        requesting_model: 'Requesting a reply from the configured model.',
      };
  return phase === 'preparing_context' || phase === 'requesting_model'
    ? preparing[phase]
    : undefined;
}

async function postStreamReliabilityStatus(
  context: CommandContext,
  phase: string | undefined,
  responseLanguage: ComposerLanguage,
): Promise<void> {
  const message = streamStatusMessage(phase, responseLanguage);
  if (!message || !phase) {
    return;
  }
  const reliabilityPhase = mapStreamStatusToReliabilityPhase(phase);
  await context.workbench.postMessage({
    type: 'operation/status',
    payload: {
      tone: reliabilityPhase === 'failed' ? 'error' : 'info',
      message,
      phase,
    },
  });
}

async function failClosedUnverifiedStreaming(
  context: CommandContext,
  messageId: string,
  responseLanguage: ComposerLanguage,
): Promise<void> {
  const reason = streamingCapabilityBlockReason(responseLanguage);
  await context.setStreamingState({
    ...createEmptyTrainerStreamingState(),
    isStreaming: true,
    streamMessageId: messageId,
    reliabilityPhase: 'pending',
  });
  await context.workbench.postMessage({
    type: 'stream/start',
    payload: { messageId },
  });
  for (const phase of ['pending', 'executing', 'failed'] as const) {
    await updateStreamingState(context, (state) => ({
      ...state,
      isStreaming: true,
      reliabilityPhase: phase,
      reliabilityOutcome: phase === 'failed' ? 'failure' : undefined,
    }));
    await postStreamReliabilityStatus(context, phase, responseLanguage);
  }
  await updateStreamingState(context, (state) => ({
    ...state,
    isStreaming: false,
    streamError: reason,
    reliabilityPhase: 'acked',
    reliabilityOutcome: 'failure',
  }));
  await postStreamReliabilityStatus(context, 'acked', responseLanguage);
  await context.workbench.postMessage({
    type: 'stream/error',
    payload: {
      messageId,
      error: reason,
      retryable: false,
      reliabilityPhase: 'acked',
      reliabilityOutcome: 'failure',
    },
  });
}

function extractResourceSearchMode(value: unknown): CoachSettingsPayload['resourceSearchMode'] {
  return value === 'lexical' ||
    value === 'trusted' ||
    value === 'semantic' ||
    value === 'coach'
    ? normalizeResourceSearchMode(value)
    : undefined;
}

function extractStreamAgentCompletion(response: unknown): StreamAgentCompletionMeta {
  if (!response || typeof response !== 'object') {
    return { agentic: false };
  }

  const responseRecord = response as Record<string, unknown>;
  const agent =
    typeof responseRecord.agent === 'object' && responseRecord.agent
      ? (responseRecord.agent as Record<string, unknown>)
      : typeof responseRecord.agent_meta === 'object' && responseRecord.agent_meta
        ? (responseRecord.agent_meta as Record<string, unknown>)
        : undefined;
  if (!agent) {
    return { agentic: false };
  }

  const rawToolEvents = Array.isArray(agent.tool_events) ? agent.tool_events : [];
  const toolCount = rawToolEvents.filter((item) => {
    return Boolean(item && typeof item === 'object' && (item as Record<string, unknown>).type === 'tool_call');
  }).length;
  const summary =
    typeof agent.summary === 'string' && agent.summary.trim().length > 0
      ? agent.summary.trim()
      : undefined;
  const nextStep =
    typeof agent.next_step === 'string' && agent.next_step.trim().length > 0
      ? agent.next_step.trim()
      : typeof agent.nextStep === 'string' && agent.nextStep.trim().length > 0
        ? agent.nextStep.trim()
        : undefined;
  const stopReason =
    typeof agent.stop_reason === 'string' && agent.stop_reason.trim().length > 0
      ? agent.stop_reason.trim()
      : typeof agent.stopReason === 'string' && agent.stopReason.trim().length > 0
        ? agent.stopReason.trim()
        : undefined;

  return {
    agentic: Boolean(agent.agentic),
    summary,
    nextStep,
    stopReason,
    toolCount: toolCount > 0 ? toolCount : undefined,
  };
}
