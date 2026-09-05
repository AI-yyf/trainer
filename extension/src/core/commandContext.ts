import type * as vscode from 'vscode';

import type { ProviderConfigStore } from '../provider/providerConfigStore';
import type { TrainerTestController } from '../testing/testController';
import type { SidecarHttpClient } from './httpClient';
import type { SidecarProcessManager } from './sidecarProcessManager';
import type { BootstrapData, TrainerHostState } from './types';
import type { WorkspaceTrustGuard } from './workspaceTrust';
import type { TrainerWorkspaceService } from './trainerWorkspaceService';
import type { TrainerStreamingState } from '../../../shared/src/protocol';

export interface TrainerRuntimeWorkspaceContext {
  workspaceId: string;
  canonicalProjectPath?: string;
  rootId?: string;
  projectId?: string;
  contextId?: string;
  legacyWorkspaceId?: string;
}

export interface WorkbenchHost {
  show(): Promise<void>;
  syncState(): Promise<void>;
  postMessage(message: unknown): Promise<void>;
  setRefreshHandler(handler: (() => Promise<void>) | undefined): void;
  resolveWebviewUriForPath?(filePath: string): string | undefined;
}

export interface CommandContext {
  extensionContext: vscode.ExtensionContext;
  outputChannel: vscode.OutputChannel;
  providerStore: ProviderConfigStore;
  sidecarClient: SidecarHttpClient;
  sidecarManager: SidecarProcessManager;
  trustGuard: WorkspaceTrustGuard;
  trainerWorkspace: TrainerWorkspaceService;
  tests: TrainerTestController;
  workbench: WorkbenchHost;
  getHostState(): TrainerHostState;
  patchWorkbenchData(patch: Partial<BootstrapData>): Promise<void>;
  getStreamingState(): TrainerStreamingState;
  setStreamingState(streamingState: TrainerStreamingState): Promise<void>;
  getSessionId(): string | undefined;
  setSessionId(sessionId: string | undefined): Promise<void>;
}
