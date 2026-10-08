import * as vscode from 'vscode';
import { AsyncLocalStorage } from 'node:async_hooks';
import type { WebviewOperationIdentity, WebviewOperationPhase, WebviewSyncCursor } from '../../../shared/src/webviewSync';
import { TRAINER_OPERATION_COMPLETED_MARKER } from '../../../shared/src/protocol';

import { COMMAND_IDS, TRAINER_SIDEBAR_VIEW_ID } from './constants';
import { buildWorkbenchHtml } from './webviewContent';
import type { CommandRegistry } from './commandRegistry';
import type {
  ResourceTrainingHandoffResult,
  TrainerHostState,
  TrainerWebviewMessage,
} from './types';
import { sanitizeErrorSurfaceJson, sanitizeErrorSurfaceText } from '../../../shared/src/errorSurfaceSanitizer';
import {
  formatRuntimeMetrics,
  recordWebviewSync,
  recordWebviewSyncApplied,
  recordWebviewSyncReceipt,
  recordWebviewSyncFailure,
  recordWebviewSyncAttempt,
  recordWebviewVisibilityShow,
  snapshotRuntimeMetrics,
} from './runtimeMetrics';
import { toBootstrapPayload, toOperationStatus } from './workbenchData';
import { WebviewStateTransport } from './webviewStateTransport';
import { getRuntimeWorkspaceContext } from '../commands/workspaceContext';

const RESOURCE_OPERATION_REQUEST_ID_KEY = '__trainerResourceOperationId';
const RESOURCE_SEARCH_REQUEST_ID_KEY = 'requestId';
const RESOURCE_TRAINING_HANDOFF_REQUEST_ID_KEY = '__trainerResourceTrainingHandoffId';
const TRAINING_PERSISTENCE_REQUEST_ID_KEY = '__trainerTrainingPersistenceId';
const TRAINING_PERSISTENCE_COMMAND_IDS = new Set<string>([
  COMMAND_IDS.trainingFlashcardAnswer,
  COMMAND_IDS.trainingTheoryDrillAnswer,
  COMMAND_IDS.trainingPracticeReturn,
  COMMAND_IDS.trainingReflect,
  COMMAND_IDS.trainingReturn,
  COMMAND_IDS.evidenceEnqueue,
  COMMAND_IDS.trainingReviewArtifactAction,
  COMMAND_IDS.trainingCardStatusTransition,
]);

function resourceOperationStatusMessage(commandId: string, payload: unknown, message: string): string {
  const kind =
    commandId === COMMAND_IDS.uploadResource
      ? 'upload'
      : commandId === COMMAND_IDS.deleteResource
      ? 'delete'
      : commandId === COMMAND_IDS.restoreResource
        ? 'restore'
        : commandId === COMMAND_IDS.indexResources
          ? 'index'
          : commandId === COMMAND_IDS.searchResources
            ? 'search'
            : undefined;
  if (!kind || !payload || typeof payload !== 'object') {
    return message;
  }
  const payloadRecord = payload as Record<string, unknown>;
  const requestId =
    kind === 'search'
      ? payloadRecord[RESOURCE_SEARCH_REQUEST_ID_KEY] ??
        payloadRecord[RESOURCE_OPERATION_REQUEST_ID_KEY]
      : payloadRecord[RESOURCE_OPERATION_REQUEST_ID_KEY];
  const normalizedRequestId = typeof requestId === 'string' ? requestId.trim() : '';
  if (!/^[a-z0-9-]{1,96}$/i.test(normalizedRequestId)) {
    return message;
  }
  return `[[trainer-resource-operation:${kind}:${normalizedRequestId}]] ${message}`;
}

function readNonEmptyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function trainingPersistenceRequest(
  commandId: string,
  payload: unknown,
): { requestId: string; commandId: string } | undefined {
  if (!TRAINING_PERSISTENCE_COMMAND_IDS.has(commandId) || !payload || typeof payload !== 'object') {
    return undefined;
  }
  const requestId = readNonEmptyString(
    (payload as Record<string, unknown>)[TRAINING_PERSISTENCE_REQUEST_ID_KEY],
  );
  if (!requestId || !/^[a-z0-9-]{1,96}$/i.test(requestId)) {
    return undefined;
  }
  return { requestId, commandId };
}

function resourceTrainingHandoffRequest(
  payload: unknown,
): { requestId: string; resourceId: string } | undefined {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return undefined;
  }
  const record = payload as Record<string, unknown>;
  const requestId = readNonEmptyString(record[RESOURCE_TRAINING_HANDOFF_REQUEST_ID_KEY]);
  const resourceId = readNonEmptyString(record.resourceId ?? record.resource_id);
  if (!requestId || !resourceId || !/^[a-z0-9-]{1,96}$/i.test(requestId)) {
    return undefined;
  }
  return { requestId, resourceId };
}

function resourceTrainingHandoffResult(
  commandId: string,
  payload: unknown,
  result: { ok: boolean; data?: unknown; message?: string },
): ResourceTrainingHandoffResult | undefined {
  if (commandId !== COMMAND_IDS.trainingGenerateCard) {
    return undefined;
  }
  const request = resourceTrainingHandoffRequest(payload);
  if (!request) {
    return undefined;
  }
  const data =
    result.data && typeof result.data === 'object' && !Array.isArray(result.data)
      ? (result.data as Record<string, unknown>)
      : undefined;
  const generatedCardId = readNonEmptyString(data?.generatedCardId);
  const selectedCardId = readNonEmptyString(data?.selectedCardId);
  const generationSucceeded = data?.success === true;
  const outcome = !result.ok
    ? 'failed'
    : generationSucceeded && generatedCardId && selectedCardId === generatedCardId
      ? 'ready'
      : generationSucceeded && selectedCardId
        ? 'not-current'
        : 'blocked';
  const rawReason = [readNonEmptyString(result.message), readNonEmptyString(data?.reason)]
    .filter((value): value is string => Boolean(value))
    .join(' ')
    .toLowerCase();
  const reason = rawReason.includes('resource') && /(not found|missing|deleted)/.test(rawReason)
    ? 'resource_missing'
    : /(provider|api key|connection|sidecar|service unavailable|\b503\b)/.test(rawReason)
      ? 'connection'
      : /(index|fresh|trust|source|generated_card_blocked|\b409\b|conflict)/.test(rawReason)
        ? 'resource_needs_refresh'
        : outcome === 'ready' || outcome === 'not-current'
          ? undefined
          : 'unavailable';
  return {
    ...request,
    outcome,
    ...(reason ? { reason } : {}),
    generatedCardId,
    selectedCardId,
  };
}

export class WorkbenchSidebarController
  implements vscode.WebviewViewProvider, vscode.Disposable
{
  private static readonly debugMessageLimit = 20;
  private view?: vscode.WebviewView;
  private liveFollowEnabled = true;
  private refreshHandler?: () => Promise<void>;
  private lastRenderedHtml?: string;
  private lastLifecycleAckAt = 0;
  private awaitingLifecycleAck = false;
  private visibilityRecoveryTimer?: ReturnType<typeof setTimeout>;
  private visibilitySyncTimer?: ReturnType<typeof setTimeout>;
  private htmlRefreshPromise?: Promise<void>;
  private htmlRefreshView?: vscode.WebviewView;
  private bootstrapNonce = 0;
  private lastPostedMessageType?: string;
  private readonly recentOutboundMessageTypes: string[] = [];
  private lastRestorePayload?: unknown;
  private pendingRestoreMessage?: unknown;
  private lastOperationStatusPayload?: unknown;
  private lastVisibleFactsPayload?: unknown;
  /**
   * Incremental sync bookkeeping: the bootstrap payload as last delivered to
   * the webview, plus per-key serialized fingerprints. Unchanged top-level
   * keys are never re-sent, so a sync after a tiny state change ships a small
   * `state/patch` instead of the full bootstrap.
   */
  private lastSeenHostState?: TrainerHostState;
  private readonly stateTransport: WebviewStateTransport;
  private readonly operationContext = new AsyncLocalStorage<WebviewOperationIdentity>();
  private readonly operationRequests = new Map<string, WebviewOperationPhase>();
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    private readonly extensionContext: vscode.ExtensionContext,
    private readonly commandRegistry: CommandRegistry,
    private readonly getState: () => TrainerHostState,
    private readonly outputChannel: vscode.OutputChannel,
  ) {
    this.stateTransport = new WebviewStateTransport({
      send: async (message) => {
        recordWebviewSync({ full: message.sync.baseRevision === 0, bytes: JSON.stringify(message).length });
        const delivered = await this.deliverMessage(message);
        if (!delivered) recordWebviewSyncFailure();
        return delivered;
      },
      received: recordWebviewSyncReceipt,
      attempt: recordWebviewSyncAttempt,
      acknowledged: (hostState, elapsedMs) => {
        this.lastSeenHostState = hostState as TrainerHostState;
        if (elapsedMs >= 0) recordWebviewSyncApplied(elapsedMs);
      },
      status: (status, generation) => {
        if (status === 'stale') {
          this.outputChannel.appendLine('[webview] state apply acknowledgement exhausted; waiting for recovery');
          void this.deliverMessage({ type: 'state/syncStatus', payload: { status, generation } });
        }
      },
    });
  }

  async show(): Promise<void> {
    await vscode.commands.executeCommand('workbench.view.extension.trainer');
    try {
      await vscode.commands.executeCommand(`${TRAINER_SIDEBAR_VIEW_ID}.focus`);
    } catch {
      // Some VS Code builds do not expose the generated focus command consistently.
    }
    if (this.view) {
      try {
        await this.ensureRendered(this.view, 'show()');
        this.outputChannel.appendLine('[webview] show() ensured html');
      } catch (error) {
        this.outputChannel.appendLine(
          `[webview] show() refresh failed: ${
            error instanceof Error ? error.stack ?? error.message : String(error)
          }`,
        );
      }
    }
    await this.syncState();
  }

  async resolveWebviewView(webviewView: vscode.WebviewView): Promise<void> {
    this.outputChannel.appendLine('[webview] resolve start');
    try {
      this.view = webviewView;
      webviewView.title = 'Trainer';
      webviewView.webview.options = {
        enableScripts: true,
        localResourceRoots: [this.extensionContext.extensionUri],
      };

      webviewView.onDidDispose(() => {
        this.clearVisibilityRecoveryTimer();
        this.clearVisibilitySyncTimer();
        if (this.view === webviewView) {
          this.view = undefined;
          this.resetSyncedPayload();
        }
      });

      webviewView.onDidChangeVisibility(() => {
        if (webviewView.visible) {
          // Phase-A metric: a show must never fan out into provider, catalog,
          // or engine work. The counters make regressions measurable.
          recordWebviewVisibilityShow();
          this.outputChannel.appendLine(
            `[webview] visible -> rehydrating state ${formatRuntimeMetrics(snapshotRuntimeMetrics())}`,
          );
          void this.syncVisibleState(webviewView, 'visibility');
          return;
        }
        this.clearVisibilityRecoveryTimer();
        this.clearVisibilitySyncTimer();
      });

      webviewView.webview.onDidReceiveMessage((message: TrainerWebviewMessage) => {
        void this.handleMessage(message);
      });

      await this.refreshHtml(webviewView, 'resolve');
      this.outputChannel.appendLine('[webview] html ready');

      await this.syncState({ forceFull: true });
      this.outputChannel.appendLine('[webview] bootstrap posted');
    } catch (error) {
      this.outputChannel.appendLine(
        `[webview] resolve failed: ${
          error instanceof Error ? error.stack ?? error.message : String(error)
        }`,
      );
      throw error;
    }
  }

  async syncState(options?: { forceFull?: boolean }): Promise<void> {
    if (!this.view) {
      return;
    }

    await this.ensureRendered(this.view, 'syncState');
    await this.postIncrementalPatch(options);
  }

  async syncLiveContext(): Promise<void> {
    if (!this.view || !this.liveFollowEnabled) {
      return;
    }

    await this.postIncrementalPatch();
  }

  /**
   * Ship only the top-level bootstrap keys that actually changed since the
   * last successful delivery. Reference equality gives an O(1) fast path per
   * key (host state is rebuilt immutably); a serialized fingerprint guards
   * against equal-content rebuilds.
   */
  private async postIncrementalPatch(options?: { forceFull?: boolean }): Promise<void> {
    const hostState = this.getState();
    const payload = toBootstrapPayload(hostState) as unknown as Record<string, unknown>;
    await this.stateTransport.publish({
      payload,
      hostState,
      workspaceId: getRuntimeWorkspaceContext({ getHostState: () => hostState }).workspaceId,
      sessionId: hostState.sessionId ?? '',
      runtimeGeneration: payload.runtimeDataGeneration,
    }, options?.forceFull === true);
  }

  private resetSyncedPayload(): void {
    this.stateTransport.reset();
    this.lastSeenHostState = undefined;
  }

  private isHostStateDirty(): boolean {
    return this.lastSeenHostState !== this.getState();
  }

  async postMessage(message: unknown): Promise<void> {
    // All state publications use the ACK-governed transport, including callers
    // that formerly posted unversioned patches directly through CommandContext.
    if (message && typeof message === 'object' && 'type' in message &&
        (message.type === 'bootstrap' || message.type === 'state/patch')) {
      await this.syncState({ forceFull: message.type === 'bootstrap' });
      return;
    }
    await this.deliverMessage(message);
  }

  private async deliverMessage(message: unknown): Promise<boolean> {
    const view = this.view;
    if (!view) return false;
    try {
      await this.ensureRendered(view, 'postMessage');
      if (this.view !== view) return false;
      const record = message && typeof message === 'object' ? message as Record<string, unknown> : undefined;
      const operation = this.operationContext.getStore();
      const stateMessage = record?.type === 'bootstrap' || record?.type === 'state/patch' || record?.type === 'state/syncStatus';
      const scopedMessage = record && !stateMessage && (operation || record.scope) ? { ...record,
        scope: record.scope ?? (operation ? { ...this.currentScope(), ...operation, messageId: '' } : this.currentScope()),
        ...(operation && !record.operation ? { operation } : {}),
      } : message;
      this.queueRestoreUntilWebviewReady(scopedMessage);
      this.recordOutboundMessage(scopedMessage);
      const delivered = await view.webview.postMessage(scopedMessage);
      if (!delivered) this.outputChannel.appendLine('[webview] postMessage returned false');
      return delivered;
    } catch (error) {
      this.outputChannel.appendLine(`[webview] postMessage failed: ${sanitizeErrorSurfaceText(error)}`);
      return false;
    }
  }

  dispose(): void {
    this.clearVisibilityRecoveryTimer();
    this.clearVisibilitySyncTimer();
    this.stateTransport.dispose();
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
    this.view = undefined;
  }

  setRefreshHandler(handler: (() => Promise<void>) | undefined): void {
    this.refreshHandler = handler;
  }

  resolveWebviewUriForPath(filePath: string): string | undefined {
    if (!this.view) {
      return undefined;
    }
    try {
      return this.view.webview.asWebviewUri(vscode.Uri.file(filePath)).toString();
    } catch {
      return undefined;
    }
  }

  getDebugSnapshot(): {
    bootstrapNonce: number;
    awaitingLifecycleAck: boolean;
    lastLifecycleAckAt: number;
    liveFollowEnabled: boolean;
    viewVisible: boolean;
    lastPostedMessageType?: string;
    recentOutboundMessageTypes: string[];
    lastRestorePayload?: unknown;
    lastOperationStatusPayload?: unknown;
    lastVisibleFactsPayload?: unknown;
    stateSync: WebviewStateTransport['debug'];
  } {
    return {
      stateSync: this.stateTransport.debug,
      bootstrapNonce: this.bootstrapNonce,
      awaitingLifecycleAck: this.awaitingLifecycleAck,
      lastLifecycleAckAt: this.lastLifecycleAckAt,
      liveFollowEnabled: this.liveFollowEnabled,
      viewVisible: this.view?.visible === true,
      lastPostedMessageType: this.lastPostedMessageType,
      recentOutboundMessageTypes: [...this.recentOutboundMessageTypes],
      lastRestorePayload: cloneDebugValue(this.lastRestorePayload),
      lastOperationStatusPayload: cloneDebugValue(this.lastOperationStatusPayload),
      lastVisibleFactsPayload: cloneDebugValue(this.lastVisibleFactsPayload),
    };
  }

  private currentScope(): WebviewSyncCursor {
    const state = this.getState();
    return { ...this.stateTransport.scope, messageId: '',
      workspaceId: getRuntimeWorkspaceContext({ getHostState: () => state }).workspaceId,
      sessionId: state.sessionId ?? '',
    };
  }

  private async postOperationPhase(identity: WebviewOperationIdentity, phase: WebviewOperationPhase): Promise<void> {
    this.operationRequests.set(identity.requestId, phase);
    if (this.operationRequests.size > 128) {
      for (const [requestId, value] of this.operationRequests) {
        if (value !== 'pending' && value !== 'running') { this.operationRequests.delete(requestId); break; }
      }
    }
    await this.postMessage({ type: 'operation/lifecycle', payload: { identity, phase } });
  }

  private async handleMessage(message: TrainerWebviewMessage): Promise<void> {
    const command = this.resolveCommand(message);
    const identity = message.operation && command ? { ...message.operation, commandId: command.commandId } : undefined;
    if (!identity) { await this.handleScopedMessage(message); return; }
    const scope = this.currentScope();
    if (!/^[a-z0-9-]{1,128}$/i.test(identity.requestId)) return;
    if (identity.generation !== scope.generation ||
        identity.workspaceId !== scope.workspaceId || identity.sessionId !== scope.sessionId ||
        identity.revision > scope.revision) {
      this.outputChannel.appendLine('[webview] ignored command from an outdated UI scope');
      // Rejecting before execution still needs a terminal response for the
      // originating UI. Keep its old identity so a newer session cannot
      // mistake this rejection for one of its own operation outcomes.
      await this.postOperationPhase(identity, 'interrupted');
      await this.deliverMessage({ type: 'operation/status', operation: identity,
        scope: { ...identity, messageId: '' },
        payload: { tone: 'error', message: '[[trainer-operation-scope-changed]]' },
      });
      await this.syncState({ forceFull: true });
      return;
    }
    if (this.operationRequests.has(identity.requestId)) return;
    await this.operationContext.run(identity, async () => {
      await this.postOperationPhase(identity, 'pending');
      await this.postOperationPhase(identity, 'running');
      await this.handleScopedMessage(message);
    });
  }

  private async synchronizeAppliedState(): Promise<boolean> {
    await this.syncState();
    return this.stateTransport.whenApplied();
  }

  private async handleScopedMessage(message: TrainerWebviewMessage): Promise<void> {
    if (!this.view) {
      return;
    }
    try {
      if (message.type === 'webview/ready') {
        this.lastLifecycleAckAt = Date.now();
        this.awaitingLifecycleAck = false;
        this.outputChannel.appendLine(`[webview] lifecycle ${message.type}`);
        const pendingRestoreMessage = this.pendingRestoreMessage;
        this.pendingRestoreMessage = undefined;
        await this.syncState({ forceFull: true });
        if (pendingRestoreMessage !== undefined) {
          await this.postMessage(pendingRestoreMessage);
        }
        return;
      }

      if (message.type === 'state/ack') {
        this.stateTransport.acknowledge(message.payload);
        return;
      }

      if (message.type === 'request/bootstrap') {
        this.outputChannel.appendLine('[webview] lifecycle request/bootstrap');
        await this.refreshHostAndSync('request/bootstrap', { forceFull: true });
        return;
      }

      if (message.type === 'debug/error') {
        this.outputChannel.appendLine(
          `[webview:${message.payload.source}] ${sanitizeErrorSurfaceText(message.payload.message)}${
            message.payload.stack ? `\n${sanitizeErrorSurfaceText(message.payload.stack)}` : ''
          }`,
        );
        return;
      }

      if (message.type === 'debug/visibleFacts') {
        this.lastVisibleFactsPayload = cloneDebugValue(message.payload);
        return;
      }

      if (message.type === 'ui/liveFollow') {
        this.liveFollowEnabled = message.payload.enabled;
        if (this.liveFollowEnabled) {
          await this.syncState();
        }
        return;
      }

      const command = this.resolveCommand(message);
      if (command) {
        const result = await this.commandRegistry.execute(command.commandId, command.payload);
        const identity = this.operationContext.getStore();
        if (identity) {
          const data = result.data && typeof result.data === 'object' ? result.data as Record<string, unknown> : undefined;
          const phase: WebviewOperationPhase = result.cancelled || data?.state === 'cancelled' ? 'cancelled'
            : data?.state === 'connection_lost' || data?.state === 'timed_out' ? 'interrupted'
            : result.ok ? 'succeeded' : 'failed';
          await this.postOperationPhase(identity, phase);
          const current = this.currentScope();
          if (identity.generation !== current.generation || identity.workspaceId !== current.workspaceId ||
              identity.sessionId !== current.sessionId) { await this.syncState(); return; }
        }
        if (command.commandId === COMMAND_IDS.remoteCompanionState) {
          // A quiet query: the Settings panel consumes the dedicated state
          // message instead of a toast.
          const data = (result.data ?? {}) as { state?: string; remoteName?: string };
          await this.postMessage({
            type: 'remoteCompanion/state',
            payload: {
              state: data.state ?? 'not_installed',
              ...(data.remoteName ? { remoteName: data.remoteName } : {}),
            },
          });
          return;
        }
        const trainingPersistence = trainingPersistenceRequest(command.commandId, command.payload);
        const resourceTrainingHandoff = resourceTrainingHandoffResult(
          command.commandId,
          command.payload,
          result,
        );
        if (resourceTrainingHandoff) {
          if (!(await this.synchronizeAppliedState())) return;
          await this.postMessage({
            type: 'training/resourceHandoff',
            payload: resourceTrainingHandoff,
          });
          return;
        }
        if (trainingPersistence) {
          // The acknowledgement is emitted only after the refreshed snapshot has
          // reached the webview, so a follow-up training stream sees durable state.
          if (!(await this.synchronizeAppliedState())) return;
          await this.postMessage({
            type: 'training/persistenceAck',
            payload: {
              ...trainingPersistence,
              ok: result.ok && !result.cancelled,
              ...(result.data !== undefined ? { data: result.data } : {}),
              ...(!result.ok || result.cancelled
                ? {
                    message: sanitizeErrorSurfaceText(
                      result.message ?? 'Trainer could not complete this action. Try again.',
                    ),
                  }
                : {}),
            },
          });
          if (result.ui?.focusProviderApiKey) {
            await this.postMessage({
              type: 'ui/restoreView',
              payload: { activeView: 'settings', focusProviderApiKey: true },
            });
          }
          if (!result.cancelled && command.commandId !== COMMAND_IDS.primeProviderModels) {
            await this.postMessage(
              toOperationStatus(
                result.ok,
                resourceOperationStatusMessage(
                  command.commandId,
                  command.payload,
                  result.message ?? TRAINER_OPERATION_COMPLETED_MARKER,
                ),
                result.providerTest,
              ),
            );
          }
          return;
        }
        if (result.ui?.focusProviderApiKey) {
          await this.syncState();
          await this.postMessage({
            type: 'ui/restoreView',
            payload: { activeView: 'settings', focusProviderApiKey: true },
          });
          if (!result.cancelled && command.commandId !== COMMAND_IDS.primeProviderModels) {
            await this.postMessage(
              toOperationStatus(
                result.ok,
                resourceOperationStatusMessage(
                  command.commandId,
                  command.payload,
                  result.message ?? TRAINER_OPERATION_COMPLETED_MARKER,
                ),
                result.providerTest,
              ),
            );
          }
          return;
        }
        if (!result.cancelled && command.commandId !== COMMAND_IDS.primeProviderModels) {
          await this.postMessage(
            toOperationStatus(
              result.ok,
              resourceOperationStatusMessage(
                command.commandId,
                command.payload,
                result.message ?? TRAINER_OPERATION_COMPLETED_MARKER,
              ),
              result.providerTest,
            ),
          );
        }
        // Speed-test latency rows are data, not an operation status message:
        // the settings panel renders them directly from this dedicated ack.
        if (command.commandId === COMMAND_IDS.providerSpeedTest && result.data) {
          await this.postMessage({
            type: 'provider/speedTest',
            payload: result.data as { results: unknown[] },
          });
        }
        // The session list is data for the coach history panel, not a status
        // line, so it travels on its own ack channel like the speed test.
        if (command.commandId === COMMAND_IDS.listCoachSessions) {
          await this.postMessage({
            type: 'session/list',
            payload: {
              ok: result.ok,
              sessions: result.ok && result.data ? (result.data as { sessions?: unknown[] }).sessions ?? [] : [],
              ...(!result.ok ? { message: result.message ?? 'Trainer could not load sessions.' } : {}),
            },
          });
        }
        await this.syncState();
        return;
      }

      this.outputChannel.appendLine(
        `[webview] Unknown message: ${sanitizeErrorSurfaceJson(message)}`,
      );
    } catch (error) {
      const identity = this.operationContext.getStore();
      if (identity) await this.postOperationPhase(identity, 'failed');
      this.outputChannel.appendLine(
        `[webview] handleMessage failed: ${sanitizeErrorSurfaceText(
          error instanceof Error ? error.stack ?? error.message : String(error),
        )}`,
      );
      const command = this.resolveCommand(message);
      if (command && command.commandId !== COMMAND_IDS.primeProviderModels) {
        const trainingPersistence = trainingPersistenceRequest(command.commandId, command.payload);
        const resourceTrainingHandoff = resourceTrainingHandoffResult(
          command.commandId,
          command.payload,
          {
            ok: false,
            message: error instanceof Error ? error.message : String(error),
          },
        );
        if (resourceTrainingHandoff) {
          await this.syncState();
          await this.postMessage({
            type: 'training/resourceHandoff',
            payload: resourceTrainingHandoff,
          });
          return;
        }
        if (trainingPersistence) {
          await this.syncState();
          await this.postMessage({
            type: 'training/persistenceAck',
            payload: {
              ...trainingPersistence,
              ok: false,
              data: undefined,
              message: sanitizeErrorSurfaceText(
                error instanceof Error ? error.message : 'Trainer could not complete this action. Try again.',
              ),
            },
          });
          await this.postMessage(
            toOperationStatus(
              false,
              resourceOperationStatusMessage(
                command.commandId,
                command.payload,
                'Trainer could not complete this action. Try again.',
              ),
            ),
          );
          return;
        }
        await this.postMessage(
          toOperationStatus(
            false,
            resourceOperationStatusMessage(
              command.commandId,
              command.payload,
              'Trainer could not complete this action. Try again.',
            ),
          ),
        );
        await this.syncState();
      }
    }
  }

  private async buildHtml(view: vscode.WebviewView): Promise<string> {
    this.bootstrapNonce += 1;
    return buildWorkbenchHtml(
      this.extensionContext,
      view.webview,
      this.getState(),
    );
  }

  private async refreshHtml(view: vscode.WebviewView, reason: string): Promise<void> {
    if (this.view !== view) {
      return;
    }
    if (this.htmlRefreshPromise && this.htmlRefreshView === view) {
      await this.htmlRefreshPromise;
      return;
    }

    const refresh = (async () => {
      const html = await this.buildHtml(view);
      if (this.view !== view) {
        return;
      }
      this.lastRenderedHtml = html;
      this.lastLifecycleAckAt = 0;
      this.awaitingLifecycleAck = true;
      // A fresh webview starts with an empty store: full payload on next sync.
      this.resetSyncedPayload();
      view.webview.html = html;
      this.outputChannel.appendLine(`[webview] html refreshed (${reason})`);
    })();
    this.htmlRefreshPromise = refresh;
    this.htmlRefreshView = view;
    try {
      await refresh;
    } finally {
      if (this.htmlRefreshPromise === refresh) {
        this.htmlRefreshPromise = undefined;
        this.htmlRefreshView = undefined;
      }
    }
  }

  private async ensureRendered(view: vscode.WebviewView, reason: string): Promise<void> {
    const currentHtml = view.webview.html?.trim();
    if (currentHtml) {
      return;
    }
    if (this.lastRenderedHtml?.trim()) {
      await this.refreshHtml(view, `${reason}:cached`);
      this.outputChannel.appendLine(`[webview] restored cached html (${reason})`);
      return;
    }
    await this.refreshHtml(view, reason);
  }

  private async syncVisibleState(
    view: vscode.WebviewView,
    reason: string,
    forceRefresh = false,
  ): Promise<void> {
    const htmlPresent = Boolean(view.webview.html?.trim());
    const lifecycleAge =
      this.lastLifecycleAckAt > 0 ? Date.now() - this.lastLifecycleAckAt : Number.POSITIVE_INFINITY;
    const shouldRefreshHtml =
      forceRefresh ||
      !htmlPresent ||
      (this.awaitingLifecycleAck && (this.lastLifecycleAckAt === 0 || lifecycleAge > 1200));

    if (shouldRefreshHtml) {
      await this.refreshHtml(view, reason);
      // A rebuilt page has an empty store: the full payload is mandatory.
      this.resetSyncedPayload();
      await this.refreshHostAndSync(reason);
      this.scheduleVisibilityRecovery(view, reason);
      return;
    }

    // Healthy page + unchanged host state: the last incremental delivery is
    // still authoritative — visibility itself must not cost a derivation.
    if (!this.isHostStateDirty()) {
      this.scheduleVisibilityRecovery(view, reason);
      return;
    }

    await this.refreshHostAndSync(reason);
    this.scheduleVisibilityRecovery(view, reason);
  }

  private clearVisibilityRecoveryTimer(): void {
    if (this.visibilityRecoveryTimer) {
      clearTimeout(this.visibilityRecoveryTimer);
      this.visibilityRecoveryTimer = undefined;
    }
  }

  private clearVisibilitySyncTimer(): void {
    if (this.visibilitySyncTimer) {
      clearTimeout(this.visibilitySyncTimer);
      this.visibilitySyncTimer = undefined;
    }
  }

  private scheduleVisibilityRecovery(view: vscode.WebviewView, reason: string): void {
    this.clearVisibilityRecoveryTimer();
    this.clearVisibilitySyncTimer();
    this.visibilityRecoveryTimer = setTimeout(() => {
      void this.recoverVisibilityIfNeeded(view, reason);
    }, 1200);
    this.visibilitySyncTimer = setTimeout(() => {
      void this.syncVisibleViewIfNeeded(view, reason);
    }, 260);
  }

  private async recoverVisibilityIfNeeded(
    view: vscode.WebviewView,
    reason: string,
  ): Promise<void> {
    this.visibilityRecoveryTimer = undefined;
    if (this.view !== view || !view.visible) {
      return;
    }

    if (!this.awaitingLifecycleAck) {
      return;
    }

    const lifecycleAge = Date.now() - this.lastLifecycleAckAt;
    if (this.lastLifecycleAckAt > 0 && lifecycleAge < 1000) {
      return;
    }

    this.outputChannel.appendLine(
      `[webview] visibility recovery triggered (${reason}); last lifecycle ack age=${lifecycleAge}`,
    );
    await this.refreshHtml(view, `${reason}:recovery`);
    await this.refreshHostAndSync(`${reason}:recovery`);
  }

  private async syncVisibleViewIfNeeded(
    view: vscode.WebviewView,
    reason: string,
  ): Promise<void> {
    this.visibilitySyncTimer = undefined;
    if (this.view !== view || !view.visible) {
      return;
    }

    try {
      await this.refreshHostAndSync(`${reason}:sync`);
    } catch (error) {
      this.outputChannel.appendLine(
        `[webview] visibility sync failed: ${
          error instanceof Error ? error.stack ?? error.message : String(error)
        }`,
      );
    }
  }

  private async refreshHostAndSync(
    reason: string,
    options?: { forceFull?: boolean },
  ): Promise<void> {
    if (!this.view) {
      return;
    }
    await this.ensureRendered(this.view, reason);
    if (this.refreshHandler) {
      try {
        await this.refreshHandler();
      } catch (error) {
        this.outputChannel.appendLine(
          `[webview] refresh handler failed (${reason}): ${
            error instanceof Error ? error.stack ?? error.message : String(error)
          }`,
        );
      }
    }
    // A refresh re-derives host state and ships one incremental patch; the
    // full payload is reserved for fresh webviews and explicit repair
    // requests (request/bootstrap).
    await this.syncState(options);
  }

  private resolveCommand(
    message: TrainerWebviewMessage,
  ): { commandId: string; payload?: unknown } | undefined {
    switch (message.type) {
      case 'command/execute':
        return {
          commandId: message.payload.commandId,
          payload: message.payload.payload,
        };
      case 'settings/primeProviderModels':
        return { commandId: COMMAND_IDS.primeProviderModels };
      case 'session/sendMessage':
        return { commandId: COMMAND_IDS.sendMessage, payload: message.payload };
      case 'session/sendStreamMessage':
        return { commandId: COMMAND_IDS.sendStreamMessage, payload: message.payload };
      case 'session/cancelStreamMessage':
        return { commandId: COMMAND_IDS.cancelStreamMessage, payload: message.payload };
      case 'settings/saveCoach':
        return { commandId: COMMAND_IDS.saveCoachSettings, payload: message.payload };
      case 'plan/generate':
        return { commandId: COMMAND_IDS.generatePlan };
      case 'plan/freeze':
        return {
          commandId: COMMAND_IDS.updatePlan,
          payload: { frozen: message.payload.frozen },
        };
      case 'task/specify':
        return {
          commandId: COMMAND_IDS.taskSpecify,
          payload: message.payload,
        };
      case 'task/next':
        return { commandId: COMMAND_IDS.nextTask };
      case 'task/evaluateCurrentFile':
        return {
          commandId: COMMAND_IDS.evaluateCurrentFile,
          payload: message.payload,
        };
      case 'resource/upload':
        return { commandId: COMMAND_IDS.uploadResource, payload: message.payload };
      case 'resource/open':
        return {
          commandId: COMMAND_IDS.openResource,
          payload: message.payload,
        };
      case 'ui/liveFollow':
      case 'ui/focus':
        return undefined;
      default:
        return this.resolveResearchCompatibilityCommand(message);
    }
  }

  private resolveResearchCompatibilityCommand(
    message: TrainerWebviewMessage,
  ): { commandId: string; payload?: unknown } | undefined {
    switch (message.type) {
      case 'research/create':
        return { commandId: COMMAND_IDS.createResearch, payload: message.payload };
      case 'research/addTheme':
        return { commandId: COMMAND_IDS.addResearchTheme, payload: message.payload };
      case 'research/activateTheme':
        return { commandId: COMMAND_IDS.activateResearchTheme, payload: message.payload };
      case 'research/advance':
        return { commandId: COMMAND_IDS.advanceResearch, payload: message.payload };
      case 'research/message':
        return { commandId: COMMAND_IDS.researchMessage, payload: message.payload };
      case 'research/streamMessage':
        return { commandId: COMMAND_IDS.researchStreamMessage, payload: message.payload };
      case 'research/approve':
        return { commandId: COMMAND_IDS.approveResearchDecision, payload: message.payload };
      case 'research/getStatus':
        return { commandId: COMMAND_IDS.getResearchStatus, payload: message.payload };
      default:
        return undefined;
    }
  }

  private recordOutboundMessage(message: unknown): void {
    if (!message || typeof message !== 'object') {
      this.lastPostedMessageType = undefined;
      return;
    }

    const record = message as { type?: unknown; payload?: unknown };
    if (typeof record.type !== 'string') {
      this.lastPostedMessageType = undefined;
      return;
    }

    this.lastPostedMessageType = record.type;
    this.recentOutboundMessageTypes.push(record.type);
    if (this.recentOutboundMessageTypes.length > WorkbenchSidebarController.debugMessageLimit) {
      this.recentOutboundMessageTypes.shift();
    }

    if (record.type === 'ui/restoreView') {
      this.lastRestorePayload = cloneDebugValue(record.payload);
    } else if (record.type === 'operation/status') {
      this.lastOperationStatusPayload = cloneDebugValue(record.payload);
    }
  }

  private queueRestoreUntilWebviewReady(message: unknown): void {
    if (!this.awaitingLifecycleAck || !message || typeof message !== 'object') {
      return;
    }
    const record = message as { type?: unknown; payload?: unknown };
    if (record.type === 'ui/restoreView') {
      this.pendingRestoreMessage = cloneDebugValue(message);
    }
  }
}

function cloneDebugValue<T>(value: T): T {
  if (value === undefined) {
    return value;
  }
  return JSON.parse(JSON.stringify(value)) as T;
}
