import * as vscode from 'vscode';

import { registerCommands } from './commands';
import { createBrowserCaptureRuntime } from './browserCapture/runtime';
import { evaluatePublishedFileCommand } from './commands/evaluationCommands';
import { primeProviderModelsState } from './commands/providerWebviewCommands';
import { invalidateActiveTrainerStreams } from './commands/sessionCommands';
import { getRuntimeWorkspaceContext } from './commands/workspaceContext';
import { CONTEXT_KEYS, OUTPUT_CHANNEL_NAME, STORAGE_KEYS } from './core/constants';
import type { CommandContext } from './core/commandContext';
import { BootstrapSnapshotCache } from './core/bootstrapSnapshotCache';
import { SidecarHttpClient } from './core/httpClient';
import { SidecarProcessManager } from './core/sidecarProcessManager';
import type { TrainerHostState } from './core/types';
import { WorkbenchSidebarController } from './core/webviewBridge';
import { WorkbenchEditorPanel } from './core/workbenchPanel';
import {
  applyDerivedHostState,
  createDefaultBootstrapData,
  patchHostState,
} from './core/workbenchData';
import { WorkspaceTrustGuard } from './core/workspaceTrust';
import { TrainerWorkspaceService } from './core/trainerWorkspaceService';
import { resolveTrainerWorkspaceAdmission, resolveTrainerProjectsList } from './core/trainerWorkspaceAdmission';
import { ProviderConfigStore } from './provider/providerConfigStore';
import { disposeTrialProviderServer } from './provider/trialProviderServer';
import { TrainerTestController } from './testing/testController';
import { TRAINER_SIDEBAR_VIEW_ID } from './core/constants';
import {
  buildTrainerRuntimeStatus,
  rehydrateWorkbenchRuntime,
} from './core/runtimeRehydration';
import { createEmptyTrainerStreamingState } from '../../shared/src/protocol';
import { LocalWorkspaceGateway } from './workspace/localWorkspaceGateway';
import { RemoteWorkspaceGateway } from './workspace/remoteWorkspaceGateway';
import type { WorkspaceGateway } from './workspace/workspaceGateway';

let sidecarManagerRef: SidecarProcessManager | undefined;
let bootstrapCacheRef: BootstrapSnapshotCache | undefined;

type TrainerExtensionDebugApi = {
  getDebugState: () => {
    sessionId?: string;
    sidecar: TrainerHostState['sidecar'];
    workspace: TrainerHostState['workspace'];
    streamingState: TrainerHostState['streamingState'];
    bootstrap: TrainerHostState['bootstrap'];
    /** Last stale-while-revalidate snapshot persisted for this workspace. */
    cachedBootstrap?: TrainerHostState['bootstrap'];
    hostState: TrainerHostState;
    workbench: ReturnType<WorkbenchSidebarController['getDebugSnapshot']>;
  };
};

export async function activate(
  extensionContext: vscode.ExtensionContext,
): Promise<TrainerExtensionDebugApi> {
  const outputChannel = vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME);
  const providerStore = new ProviderConfigStore(extensionContext);
  const sidecarClient = new SidecarHttpClient();
  const sidecarManager = new SidecarProcessManager(extensionContext, outputChannel);
  sidecarClient.setInstanceTokenProvider(() => sidecarManager.getInstanceToken());
  const trustGuard = new WorkspaceTrustGuard();
  const trainerWorkspace = new TrainerWorkspaceService(extensionContext);
  const bootstrapCache = new BootstrapSnapshotCache(extensionContext);
  bootstrapCacheRef = bootstrapCache;
  trustGuard.rememberActiveEditor();
  const tests = new TrainerTestController();

  sidecarManagerRef = sidecarManager;

  const initialApiKey = await providerStore.getApiKey();
  const initialWorkspace = trustGuard.getSnapshot();
  let workspaceGateway: WorkspaceGateway = initialWorkspace.isRemoteWorkspace
    ? new RemoteWorkspaceGateway(initialWorkspace.remoteName)
    : new LocalWorkspaceGateway();
  const initialTrainerWorkspaceAdmission = await resolveTrainerWorkspaceAdmission(
    trainerWorkspace,
    initialWorkspace,
  );
  const initialTrainerProjectsList = await resolveTrainerProjectsList(
    trainerWorkspace,
    initialWorkspace,
  );
  sidecarClient.setTrainerAdmissionMode(initialTrainerWorkspaceAdmission?.status);
  let hostState: TrainerHostState = withTrainerWorkspaceSnapshot(
    {
      provider: providerStore.getConfig(),
      providerApiKeyConfigured: Boolean(initialApiKey?.trim()),
      sidecar: sidecarManager.getStatus(),
      workspace: initialWorkspace,
      sessionId: undefined,
      streamingState: createEmptyTrainerStreamingState(),
      bootstrap: createDefaultBootstrapData(
        initialWorkspace,
        providerStore.getConfig(),
        sidecarManager.getStatus(),
      ),
    },
    initialTrainerWorkspaceAdmission,
    initialTrainerProjectsList,
  );
  const initialRuntimeWorkspace = await applyManagedDataRootScope(sidecarManager, hostState);
  hostState = withManagedDataFolderSnapshot(
    hostState,
    sidecarManager,
    initialRuntimeWorkspace.legacyWorkspaceId,
  );
  // Overlap the PyInstaller cold start with the rest of activation. Previously
  // the engine only started after provider restore + the first webview render,
  // so every window paid the full cold-start latency on top of first paint. The
  // later rehydration call joins this same ensureRunning() promise.
  if (vscode.workspace.isTrusted) {
    outputChannel.appendLine('[sidecar] prewarm requested during activation');
    void sidecarManager.ensureRunning().then(
      (status) => outputChannel.appendLine(`[sidecar] prewarm ${status.lifecycle}`),
      (error) =>
        outputChannel.appendLine(
          `[sidecar] prewarm failed: ${error instanceof Error ? error.message : String(error)}`,
        ),
    );
  }
  const getHostState = (): TrainerHostState => hostState;
  const syncProviderLastTestScope = (): string => {
    const workspaceId = getRuntimeWorkspaceContext({ getHostState }).workspaceId;
    providerStore.setActiveWorkspaceId(workspaceId);
    return workspaceId;
  };
  syncProviderLastTestScope();
  // Stale-while-revalidate: seed the last known bootstrap before the view
  // provider is registered, so even the very first resolve already carries the
  // restored thread. The sidecar's cold start no longer gates first paint; the
  // authoritative snapshot from rehydration replaces this when it lands.
  const cacheEntry = bootstrapCache.load(
    getRuntimeWorkspaceContext({ getHostState }).workspaceId,
  );
  if (cacheEntry) {
    // A cached thread is only seeded when it belongs to the session this
    // window is about to restore (or when either side is still unknown). A
    // mismatch means the cache is from a discarded session: drop it instead
    // of flashing someone else's thread (issue T-0005).
    const sessionMatches =
      !cacheEntry.sessionId ||
      !hostState.sessionId ||
      cacheEntry.sessionId === hostState.sessionId;
    if (!sessionMatches) {
      await bootstrapCache.clear(getRuntimeWorkspaceContext({ getHostState }).workspaceId);
      outputChannel.appendLine('[activation] dropped cached bootstrap from a different session');
    } else {
      hostState = {
        ...hostState,
        bootstrap: {
          ...cacheEntry.bootstrap,
          connection: hostState.bootstrap.connection,
          streamingState: hostState.bootstrap.streamingState,
        },
      };
      outputChannel.appendLine('[activation] seeded cached bootstrap (stale-while-revalidate)');
    }
  }
  const updateDerivedHostState = async (): Promise<void> => {
    syncProviderLastTestScope();
    const apiKey = await providerStore.getApiKey();
    const streamingState = hostState.streamingState ?? hostState.bootstrap.streamingState;
    const workspace = trustGuard.getSnapshot();
    const trainerWorkspaceAdmission = await resolveTrainerWorkspaceAdmission(
      trainerWorkspace,
      workspace,
    );
    const trainerProjectsList = await resolveTrainerProjectsList(trainerWorkspace, workspace);
    sidecarClient.setTrainerAdmissionMode(trainerWorkspaceAdmission?.status);
    const derivedState = withTrainerWorkspaceSnapshot(
      {
        ...hostState,
        provider: providerStore.getConfig(),
        providerApiKeyConfigured: Boolean(apiKey?.trim()),
        sidecar: sidecarManager.getStatus(),
        workspace,
        streamingState,
        bootstrap: applyDerivedHostState(
          hostState.bootstrap,
          providerStore.getConfig(),
          sidecarManager.getStatus(),
          workspace,
          hostState.sessionId,
          Boolean(apiKey?.trim()),
        ),
      },
      trainerWorkspaceAdmission,
      trainerProjectsList,
    );
    const runtimeWorkspace = await applyManagedDataRootScope(sidecarManager, derivedState);
    hostState = withManagedDataFolderSnapshot(
      derivedState,
      sidecarManager,
      runtimeWorkspace.legacyWorkspaceId,
    );
    hostState.bootstrap = {
      ...hostState.bootstrap,
      streamingState,
    };
    // Stale-while-revalidate cache: every authoritative state landing while the
    // runtime is live refreshes the snapshot the next activation restores.
    if (
      sidecarManager.getStatus().lifecycle === 'ready' &&
      hostState.sessionId
    ) {
      bootstrapCache.schedulePersist(
        getRuntimeWorkspaceContext({ getHostState }).workspaceId,
        hostState.bootstrap,
        hostState.sessionId,
      );
    }
  };

  const restoreProviderModelCache = async (): Promise<void> => {
    // P0 startup semantics: activation only restores configuration, the key
    // reference, and the historical model-catalog cache. Historical failures
    // (invalid_key_or_permission / model_unsupported / model_not_found) stay
    // diagnostic history — they are attached for the diagnostics UI but are
    // never restored as a current blocker, and nothing here probes the
    // network.
    const provider = providerStore.getConfig();
    const apiKey = await providerStore.getApiKey();
    const lastTestResult = providerStore.getLastTestResult(provider, {
      workspaceId: syncProviderLastTestScope(),
    });
    const baseBootstrap = applyDerivedHostState(
      hostState.bootstrap,
      provider,
      sidecarManager.getStatus(),
      trustGuard.getSnapshot(),
      hostState.sessionId,
      Boolean(apiKey?.trim()),
    );

    if (!provider || !apiKey?.trim()) {
      hostState = {
        ...hostState,
        bootstrap: {
          ...baseBootstrap,
          providerConfig: {
            ...baseBootstrap.providerConfig,
            lastTestResult,
          },
        },
      };
      return;
    }

    // The cached catalog is restored regardless of TTL freshness: a known
    // model list is still the user's catalog (picker refresh stays explicit),
    // and a stale list never blocks anything.
    const cache = providerStore.getModelCache(provider);
    const restoredModels = cache?.availableModels ?? [];

    hostState = {
      ...hostState,
      bootstrap: {
        ...baseBootstrap,
        providerConfig: {
          ...baseBootstrap.providerConfig,
          availableModels: restoredModels,
          resolvedModel: cache?.resolvedModel,
          modelListStatus: restoredModels.length > 0 ? 'ready' : 'idle',
          modelListDetail:
            restoredModels.length > 0
              ? cache?.lastError ||
                `Trainer restored ${restoredModels.length} known model${restoredModels.length === 1 ? '' : 's'} for this connection.`
              : baseBootstrap.providerConfig.modelListDetail,
          cacheFetchedAt: cache?.fetchedAt,
          cacheExpiresAt: cache?.expiresAt,
          cacheSource: cache ? 'cache' : undefined,
          // Diagnostic history only — modelListStatus stays non-error.
          modelErrorCategory: cache?.lastErrorCategory,
          modelStatusCode: cache?.lastStatusCode,
          modelRetryable: cache?.retryable,
          lastTestResult,
        },
      },
    };
  };

  const bootstrapContext = {
    extensionContext,
    outputChannel,
    providerStore,
    sidecarClient,
    sidecarManager,
    trustGuard,
    trainerWorkspace,
    workspaceGateway,
    tests,
    getHostState,
  };

  const placeholderWorkbench = {
    show: async () => undefined,
    syncState: async () => undefined,
    postMessage: async () => undefined,
    setRefreshHandler: () => undefined,
  };
  const registry = registerCommands(extensionContext, {
    ...bootstrapContext,
    patchWorkbenchData: async () => undefined,
    getStreamingState: () => hostState.streamingState,
    setStreamingState: async () => undefined,
    getSessionId: () => hostState.sessionId,
    setSessionId: async () => undefined,
    workbench: placeholderWorkbench,
  });

  const workbench = new WorkbenchSidebarController(
    extensionContext,
    registry,
    getHostState,
    outputChannel,
  );
  const editorPanel = new WorkbenchEditorPanel(
    extensionContext,
    registry,
    getHostState,
    outputChannel,
    () => workbench.show(),
  );
  // One host facade for commands: sidebar operations stay exactly as before,
  // and the panel-aware operations drive the editor surface. `syncState` and
  // host-authored messages fan out so a command run on either surface leaves
  // both surfaces current.
  const workbenchHost: CommandContext['workbench'] = {
    show: () => workbench.show(),
    syncState: async () => {
      await workbench.syncState();
      await editorPanel.syncState();
    },
    postMessage: async (message) => {
      await workbench.postMessage(message);
      await editorPanel.postHostMessage(message);
    },
    setRefreshHandler: (handler) => workbench.setRefreshHandler(handler),
    resolveWebviewUriForPath: (filePath) => workbench.resolveWebviewUriForPath(filePath),
    openInEditor: (view) => editorPanel.open(view),
    collapseToSidebar: () => editorPanel.collapseToSidebar(),
    // Either surface being visible drives the browser-capture draft poll;
    // "open but hidden behind another tab" must not keep polling.
    isVisible: () => workbench.isVisible() || editorPanel.isVisible(),
  };

  const commandContext: CommandContext = {
    ...bootstrapContext,
    workbench: workbenchHost,
    patchWorkbenchData: async (patch) => {
      hostState = patchHostState(hostState, patch);
      await updateDerivedHostState();
    },
    getStreamingState: () => hostState.streamingState,
    setStreamingState: async (streamingState) => {
      hostState = {
        ...hostState,
        streamingState,
        bootstrap: {
          ...hostState.bootstrap,
          streamingState,
        },
      };
    },
    getSessionId: () => hostState.sessionId,
    setSessionId: async (sessionId) => {
      hostState = {
        ...hostState,
        sessionId,
      };
      await persistWorkspaceSessionId(extensionContext, trustGuard.getSnapshot().workspaceFolder, sessionId);
      await updateDerivedHostState();
    },
    clearBootstrapCache: async () => {
      await bootstrapCache.clear(
        getRuntimeWorkspaceContext({ getHostState }).workspaceId,
      );
    },
  };
  registry.setContext(commandContext);

  // Browser capture lane: one runtime owns the pairing ledger, the
  // visibility-gated pending-draft poller, and the deep-link entry
  // (vscode://local.trainer-extension/library/<resourceId>).
  const browserCapture = createBrowserCaptureRuntime({
    sidecarClient,
    getWorkspaceId: () => getRuntimeWorkspaceContext({ getHostState }).workspaceId,
    getSidecarStatus: () => {
      const status = sidecarManager.getStatus();
      return { lifecycle: status.lifecycle, port: status.port };
    },
    ensureSidecarPort: async () => {
      const status = await sidecarManager.ensureRunning();
      if (status.lifecycle !== 'ready' || !status.port) {
        throw new Error(status.detail ?? 'Sidecar is unavailable.');
      }
      return status.port;
    },
    workbench: workbenchHost,
    outputChannel,
  });
  commandContext.browserCapture = browserCapture;
  // A forwarded draft is acknowledged to the sidecar only after the workbench
  // confirms the prefill was applied; both surfaces report the same receipt.
  const handleDraftPrefillReceipt = (draftId: string): void => {
    browserCapture.notifyDraftApplied(draftId);
  };
  workbench.setDraftPrefillReceiptHandler(handleDraftPrefillReceipt);
  editorPanel.setDraftPrefillReceiptHandler(handleDraftPrefillReceipt);
  browserCapture.drafts.start();
  extensionContext.subscriptions.push(
    browserCapture,
    vscode.window.registerUriHandler(browserCapture.uriHandler),
  );

  tests.setVerificationRuntime({
    evaluateFile: uri => evaluatePublishedFileCommand(commandContext, uri),
    outputChannel,
  });
  workbench.setRefreshHandler(async () => {
    // Visibility/refresh must never re-initialize the runtime: the Trainer
    // Engine keeps session, memory, and the provider session alive behind the
    // panel. A refresh only re-derives host state and pushes a patch.
    await syncExtensionState(commandContext);
  });

  extensionContext.subscriptions.push(
    vscode.window.registerWebviewViewProvider(TRAINER_SIDEBAR_VIEW_ID, workbench, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
  );

  extensionContext.subscriptions.push(
    outputChannel,
    providerStore,
    sidecarManager,
    tests,
    workbench,
    editorPanel,
    bootstrapCache,
    providerStore.onDidChange(() => {
      void syncExtensionState(commandContext);
    }),
    sidecarManager.onDidChangeStatus((status) => {
      if (status.lifecycle === 'ready') {
        void rehydrateWorkbenchRuntime(commandContext, {
          ensureSidecar: false,
          syncWorkbench: true,
        });
        return;
      }
      void syncExtensionState(commandContext);
    }),
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      trustGuard.rememberActiveEditor(editor);
      scheduleSyncLiveContext(workbench);
    }),
    vscode.window.onDidChangeTextEditorSelection(() => {
      scheduleSyncLiveContext(workbench);
    }),
    vscode.workspace.onDidChangeTextDocument((event) => {
      trustGuard.rememberDocumentEdit(event.document);
      scheduleSyncLiveContext(workbench);
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      const previousWorkspaceFolder = hostState.workspace.workspaceFolder;
      const previousSessionId = hostState.sessionId;
      const nextWorkspace = trustGuard.getSnapshot();
      workspaceGateway = nextWorkspace.isRemoteWorkspace
        ? new RemoteWorkspaceGateway(nextWorkspace.remoteName)
        : new LocalWorkspaceGateway();
      commandContext.workspaceGateway = workspaceGateway;

      if (previousWorkspaceFolder === nextWorkspace.workspaceFolder) {
        void workbench.syncLiveContext();
        return;
      }

      // Invalidate before resetting host state. The call synchronously aborts
      // local stream readers and marks their buffered events stale; its remote
      // cancellation request intentionally finishes in the background.
      void invalidateActiveTrainerStreams(commandContext).catch((error) => {
        outputChannel.appendLine(
          `[workspace] active stream invalidation failed: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      });

      // Clear session-scoped state synchronously so a command sent during the
      // asynchronous workspace refresh cannot carry the previous workspace's
      // session or conversation into the new workspace.
      hostState = {
        ...hostState,
        workspace: nextWorkspace,
        sessionId: undefined,
        streamingState: createEmptyTrainerStreamingState(),
        bootstrap: createDefaultBootstrapData(
          nextWorkspace,
          providerStore.getConfig(),
          sidecarManager.getStatus(),
        ),
      };
      syncProviderLastTestScope();

      void (async () => {
        await persistWorkspaceSessionId(
          extensionContext,
          previousWorkspaceFolder,
          previousSessionId,
        );
        await updateDerivedHostState();

        const restoredSessionId = getPersistedWorkspaceSessionId(
          extensionContext,
          trustGuard.getSnapshot().workspaceFolder,
        );
        if (restoredSessionId) {
          hostState = {
            ...hostState,
            sessionId: restoredSessionId,
          };
          await updateDerivedHostState();
        }

        await rehydrateWorkbenchRuntime(commandContext, {
          ensureSidecar: true,
          syncWorkbench: true,
        });
        await workbench.syncLiveContext();
      })().catch((error) => {
        outputChannel.appendLine(
          `[workspace] session rehydration failed: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
        void syncExtensionState(commandContext);
      });
    }),
  );

  outputChannel.appendLine('[activation] Trainer extension host activated');
  const restoredSessionId = getPersistedWorkspaceSessionId(
    extensionContext,
    trustGuard.getSnapshot().workspaceFolder,
  );
  if (restoredSessionId) {
    hostState = {
      ...hostState,
      sessionId: restoredSessionId,
    };
    await updateDerivedHostState();
  }
  await restoreProviderModelCache();
  await syncExtensionState(commandContext);

  if (vscode.workspace.isTrusted) {
    void rehydrateWorkbenchRuntime(commandContext, {
      ensureSidecar: true,
      syncWorkbench: true,
    }).then(
      async () => {
        const runtimeStatus = buildTrainerRuntimeStatus(commandContext);
        await workbench.postMessage({
          type: 'operation/status',
          payload: {
            tone: runtimeStatus.tone,
            message: runtimeStatus.message,
          },
        });
      },
      async (error) => {
        outputChannel.appendLine(
          `[activation] sidecar startup failed: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
        await syncExtensionState(commandContext);
        await workbench.postMessage({
          type: 'operation/status',
          payload: {
            tone: 'error',
            message:
              error instanceof Error
                ? `Trainer backend failed to start: ${error.message}`
                : `Trainer backend failed to start: ${String(error)}`,
          },
        });
      },
    );
  }

  return {
    getDebugState: () => {
      const snapshot = structuredClone(getHostState());
      const workbenchSnapshot = workbench.getDebugSnapshot();
      return {
        sessionId: snapshot.sessionId,
        sidecar: snapshot.sidecar,
        workspace: snapshot.workspace,
        streamingState: snapshot.streamingState,
        bootstrap: snapshot.bootstrap,
        cachedBootstrap: bootstrapCache.load(
          getRuntimeWorkspaceContext({ getHostState }).workspaceId,
        )?.bootstrap,
        visibleFacts: workbenchSnapshot.lastVisibleFactsPayload,
        hostState: snapshot,
        workbench: workbenchSnapshot,
      };
    },
  };
}

export async function deactivate(): Promise<void> {
  // Flush the deferred bootstrap write before the host goes away; otherwise a
  // debounce armed during the last streaming burst is lost with the process.
  if (bootstrapCacheRef) {
    await bootstrapCacheRef.flush();
    bootstrapCacheRef = undefined;
  }
  if (sidecarManagerRef) {
    await sidecarManagerRef.stop();
    sidecarManagerRef = undefined;
  }
  await disposeTrialProviderServer();
}

function withManagedDataFolderSnapshot(
  state: TrainerHostState,
  sidecarManager: SidecarProcessManager,
  workspaceFolder: string | undefined,
): TrainerHostState {
  const resourceSandbox = sidecarManager.getManagedDataFolderSnapshot(workspaceFolder);
  return {
    ...state,
    bootstrap: {
      ...state.bootstrap,
      memory: {
        ...state.bootstrap.memory,
        workspace: {
          ...(state.bootstrap.memory.workspace ?? {}),
          resourceSandbox,
        },
      },
    },
  };
}

async function applyManagedDataRootScope(
  sidecarManager: SidecarProcessManager,
  state: TrainerHostState,
) {
  const runtimeWorkspace = getRuntimeWorkspaceContext({
    getHostState: () => state,
  });
  await sidecarManager.setManagedDataRootScope({
    rootId: runtimeWorkspace.rootId,
    legacyWorkspaceFolder: runtimeWorkspace.legacyWorkspaceId,
  });
  return runtimeWorkspace;
}

function withTrainerWorkspaceSnapshot(
  state: TrainerHostState,
  trainerWorkspace: NonNullable<TrainerHostState['bootstrap']['memory']['workspace']>['trainerWorkspace'],
  trainerProjects?: NonNullable<TrainerHostState['bootstrap']['memory']['workspace']>['trainerProjects'],
): TrainerHostState {
  return {
    ...state,
    bootstrap: {
      ...state.bootstrap,
      memory: {
        ...state.bootstrap.memory,
        workspace: {
          ...(state.bootstrap.memory.workspace ?? {}),
          trainerWorkspace,
          trainerProjects,
        },
      },
    },
  };
}

async function syncExtensionState(context: CommandContext): Promise<void> {
  await context.patchWorkbenchData({});
  const state = context.getHostState();
  await Promise.all([
    vscode.commands.executeCommand('setContext', CONTEXT_KEYS.providerConfigured, Boolean(state.provider)),
    vscode.commands.executeCommand('setContext', CONTEXT_KEYS.workspaceTrusted, state.workspace.trusted),
    vscode.commands.executeCommand('setContext', CONTEXT_KEYS.sidecarReady, state.sidecar.lifecycle === 'ready'),
    context.workbench.syncState(),
  ]);
}

let liveContextSyncTimer: NodeJS.Timeout | undefined;

function scheduleSyncLiveContext(workbench: WorkbenchSidebarController): void {
  if (liveContextSyncTimer) {
    clearTimeout(liveContextSyncTimer);
  }
  liveContextSyncTimer = setTimeout(() => {
    liveContextSyncTimer = undefined;
    void workbench.syncLiveContext();
  }, 250);
}

function getPersistedWorkspaceSessionId(
  extensionContext: vscode.ExtensionContext,
  workspaceFolder: string | undefined,
): string | undefined {
  if (!workspaceFolder) {
    return undefined;
  }
  const storageKey = `${STORAGE_KEYS.sessionByWorkspacePrefix}:${workspaceFolder}`;
  return extensionContext.workspaceState.get<string>(storageKey);
}

async function persistWorkspaceSessionId(
  extensionContext: vscode.ExtensionContext,
  workspaceFolder: string | undefined,
  sessionId: string | undefined,
): Promise<void> {
  if (!workspaceFolder) {
    return;
  }
  const storageKey = `${STORAGE_KEYS.sessionByWorkspacePrefix}:${workspaceFolder}`;
  await extensionContext.workspaceState.update(storageKey, sessionId);
}
