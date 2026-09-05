import * as vscode from 'vscode';

import { registerCommands } from './commands';
import { primeProviderModelsState } from './commands/providerWebviewCommands';
import { invalidateActiveTrainerStreams } from './commands/sessionCommands';
import { getRuntimeWorkspaceContext } from './commands/workspaceContext';
import { CONTEXT_KEYS, OUTPUT_CHANNEL_NAME, STORAGE_KEYS } from './core/constants';
import type { CommandContext } from './core/commandContext';
import { SidecarHttpClient } from './core/httpClient';
import { SidecarProcessManager } from './core/sidecarProcessManager';
import type { TrainerHostState } from './core/types';
import { WorkbenchSidebarController } from './core/webviewBridge';
import {
  applyDerivedHostState,
  createDefaultBootstrapData,
  patchHostState,
} from './core/workbenchData';
import { WorkspaceTrustGuard } from './core/workspaceTrust';
import { TrainerWorkspaceService } from './core/trainerWorkspaceService';
import { resolveTrainerWorkspaceAdmission } from './core/trainerWorkspaceAdmission';
import { ProviderConfigStore } from './provider/providerConfigStore';
import { TrainerTestController } from './testing/testController';
import { TRAINER_SIDEBAR_VIEW_ID } from './core/constants';
import {
  buildTrainerRuntimeStatus,
  rehydrateWorkbenchRuntime,
} from './core/runtimeRehydration';
import { createEmptyTrainerStreamingState } from '../../shared/src/protocol';

let sidecarManagerRef: SidecarProcessManager | undefined;

type TrainerExtensionDebugApi = {
  getDebugState: () => {
    sessionId?: string;
    sidecar: TrainerHostState['sidecar'];
    workspace: TrainerHostState['workspace'];
    streamingState: TrainerHostState['streamingState'];
    bootstrap: TrainerHostState['bootstrap'];
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
  const trustGuard = new WorkspaceTrustGuard();
  const trainerWorkspace = new TrainerWorkspaceService(extensionContext);
  trustGuard.rememberActiveEditor();
  const tests = new TrainerTestController();

  sidecarManagerRef = sidecarManager;

  const initialApiKey = await providerStore.getApiKey();
  const initialWorkspace = trustGuard.getSnapshot();
  const initialTrainerWorkspaceAdmission = await resolveTrainerWorkspaceAdmission(
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
  );
  const initialRuntimeWorkspace = await applyManagedDataRootScope(sidecarManager, hostState);
  hostState = withManagedDataFolderSnapshot(
    hostState,
    sidecarManager,
    initialRuntimeWorkspace.legacyWorkspaceId,
  );
  const getHostState = (): TrainerHostState => hostState;
  const syncProviderLastTestScope = (): string => {
    const workspaceId = getRuntimeWorkspaceContext({ getHostState }).workspaceId;
    providerStore.setActiveWorkspaceId(workspaceId);
    return workspaceId;
  };
  syncProviderLastTestScope();
  const updateDerivedHostState = async (): Promise<void> => {
    syncProviderLastTestScope();
    const apiKey = await providerStore.getApiKey();
    const streamingState = hostState.streamingState ?? hostState.bootstrap.streamingState;
    const workspace = trustGuard.getSnapshot();
    const trainerWorkspaceAdmission = await resolveTrainerWorkspaceAdmission(
      trainerWorkspace,
      workspace,
    );
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
  };

  const restoreProviderModelCache = async (): Promise<void> => {
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

    const cache = providerStore.getModelCache(provider);
    const hardBlockedByLastTest = Boolean(
      lastTestResult &&
        lastTestResult.ok === false &&
        (lastTestResult.errorCategory === 'invalid_key_or_permission' ||
          lastTestResult.errorCategory === 'model_unsupported' ||
          lastTestResult.errorCategory === 'model_not_found'),
    );
    const hardBlockedByCache = Boolean(
      cache &&
        (cache.lastErrorCategory === 'invalid_key_or_permission' ||
          cache.lastErrorCategory === 'model_unsupported' ||
          cache.lastErrorCategory === 'model_not_found'),
    );
    const cacheUsable =
      !hardBlockedByCache &&
      providerStore.isModelCacheFresh(cache) &&
      providerStore.isModelCacheCompatible(provider, cache, apiKey);
    const restoreBlockedByLastTest = hardBlockedByLastTest && !cacheUsable;

    hostState = {
      ...hostState,
      bootstrap: {
        ...baseBootstrap,
        providerConfig: {
          ...baseBootstrap.providerConfig,
          availableModels: cacheUsable ? cache?.availableModels ?? [] : [],
          resolvedModel: cacheUsable ? cache?.resolvedModel : undefined,
          modelListStatus:
            restoreBlockedByLastTest || hardBlockedByCache
              ? 'error'
              : cacheUsable
                ? 'ready'
                : 'idle',
          modelListDetail:
            restoreBlockedByLastTest
              ? lastTestResult?.detail
              : hardBlockedByCache
                ? cache?.lastError || 'Trainer restored the last provider failure for this provider.'
                : cacheUsable
                  ? cache?.lastError || 'Trainer restored the cached model list for this provider.'
                  : baseBootstrap.providerConfig.modelListDetail,
          cacheFetchedAt: cacheUsable ? cache?.fetchedAt : undefined,
          cacheExpiresAt: cacheUsable ? cache?.expiresAt : undefined,
          cacheSource: cacheUsable || hardBlockedByCache ? 'cache' : undefined,
          modelErrorCategory: restoreBlockedByLastTest
            ? lastTestResult?.errorCategory
            : hardBlockedByCache
              ? cache?.lastErrorCategory
              : cacheUsable
                ? cache?.lastErrorCategory
                : undefined,
          modelStatusCode: restoreBlockedByLastTest
            ? lastTestResult?.statusCode
            : hardBlockedByCache
              ? cache?.lastStatusCode
              : cacheUsable
                ? cache?.lastStatusCode
                : undefined,
          modelRetryable: restoreBlockedByLastTest
            ? lastTestResult?.retryable
            : hardBlockedByCache
              ? cache?.retryable
              : cacheUsable
                ? cache?.retryable
                : undefined,
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

  const commandContext: CommandContext = {
    ...bootstrapContext,
    workbench,
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
  };
  registry.setContext(commandContext);
  tests.setAttestationRuntime(commandContext);
  workbench.setRefreshHandler(async () => {
    await rehydrateWorkbenchRuntime(commandContext, {
      ensureSidecar: false,
      syncWorkbench: false,
    });
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
        visibleFacts: workbenchSnapshot.lastVisibleFactsPayload,
        hostState: snapshot,
        workbench: workbenchSnapshot,
      };
    },
  };
}

export async function deactivate(): Promise<void> {
  if (sidecarManagerRef) {
    await sidecarManagerRef.stop();
    sidecarManagerRef = undefined;
  }
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
