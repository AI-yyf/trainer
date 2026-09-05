import * as vscode from 'vscode';
import * as path from 'node:path';
import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';
import { SidecarHttpError, type SidecarErrorPathState } from '../core/httpClient';

import type { CommandContext } from '../core/commandContext';
import { rehydrateWorkbenchRuntime } from '../core/runtimeRehydration';
import { resolveTrainerWorkspaceAdmission } from '../core/trainerWorkspaceAdmission';
import { resolveCurrentTrainerProjectPath } from '../core/trainerWorkspaceAdmission';
import { failClosedWorkbenchAfterWorkspaceTransfer } from '../core/workbenchData';
import {
  applyExcludedWorkspacesToBootstrap,
  flushPendingTransferPromotionScope,
  postOrQueueTransferPromotionScope,
} from '../core/transferPromotionScope';
import {
  basenameFs,
  looksLikeWindowsAbsolutePath,
  normalizeFsPath,
  resolveSovereignWorkspaceRootPath,
} from '../core/workspaceRoots';
import {
  buildWorkspaceFileSnapshot,
  type WorkspaceFileSnapshot,
} from '../core/workspaceFileSnapshot';
import type { BootstrapData, CommandExecutionResult, FirstLookSummary } from '../core/types';
import {
  TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY,
  type TrainerManagedProjectIdentity,
  type TrainerProjectAdoptionMode,
  type TrainerWorkspaceManifest,
} from '../core/trainerWorkspaceService';

type ProjectDiscoveryPayload = {
  discovery_id?: string;
  status?: string;
  available_decisions?: string[];
  availableDecisions?: string[];
  is_browse_only?: boolean;
  isBrowseOnly?: boolean;
};

type ProjectProvisioningPayload = {
  agent_session_id?: string;
  root_id?: string;
  rootId?: string;
  root_path?: string;
  rootPath?: string;
};

type ProjectClassificationResponse = {
  root_identity?: { rootId?: string; rootPath?: string };
  project_discovery?: ProjectDiscoveryPayload;
  folder_role?: FirstLookSummary['folderRole'];
  project_type_guess?: FirstLookSummary['projectTypeGuess'];
  confidence?: number;
  why_this_guess?: string;
  entry_points?: string[];
  directory_anchors?: string[];
  core_modules_or_materials?: string[];
  risk_zones?: string[];
  training_opportunities?: string[];
  unknowns?: string[];
  recommended_next_step?: string;
  classification_method?: FirstLookSummary['classificationMethod'];
  classified_at?: string;
};

type ProjectAdoptionJobPayload = {
  job_id?: string;
  status?: string;
  progress?: number;
  progress_message?: string;
  retry_reason?: string;
  root_path?: string;
  workspace_id?: string;
  context_id?: string;
};

type ProjectDecisionResponse = {
  project_discovery?: ProjectDiscoveryPayload;
  project_provisioning?: ProjectProvisioningPayload;
  project_adoption_job?: ProjectAdoptionJobPayload;
  project_identity?: TrainerManagedProjectIdentity;
};

type ProjectProvisioningResponse = {
  project_provisioning?: ProjectProvisioningPayload;
};

type SelectedTrainerRoot = {
  canonicalRootPath: string;
  rootId?: string;
};

type WorkspaceClassificationRequest = {
  workspace_id: string;
  folder_path: string;
  root_id?: string;
  root_path: string;
  remote_name: string;
  workspace_file_snapshot?: WorkspaceFileSnapshot;
  response_language?: string;
};

type ReadOnlyAdmissionMode = Extract<TrainerProjectAdoptionMode, 'browse' | 'ignored'>;
type WorkspaceAdmissionErrorCode =
  | 'root_missing'
  | 'root_id_mismatch'
  | 'root_path_unavailable'
  | 'backend_unavailable';

type WorkspaceAdmissionFailure = {
  errorCode: WorkspaceAdmissionErrorCode;
  category: 'workspace_root' | 'backend';
  pathState: SidecarErrorPathState;
};

type WorkspaceAdmissionCommandPayload = {
  responseLanguage?: unknown;
  projectPath?: unknown;
};

function firstLookSummaryFromClassification(
  response: ProjectClassificationResponse,
): FirstLookSummary | undefined {
  if (!response.classified_at) {
    return undefined;
  }
  return {
    folderRole: response.folder_role ?? 'mixed_uncertain',
    projectTypeGuess: response.project_type_guess ?? 'unknown',
    confidence: response.confidence ?? 0,
    whyThisGuess: response.why_this_guess ?? '',
    entryPoints: response.entry_points ?? [],
    directoryAnchors: response.directory_anchors ?? [],
    coreModulesOrMaterials: response.core_modules_or_materials ?? [],
    riskZones: response.risk_zones ?? [],
    trainingOpportunities: response.training_opportunities ?? [],
    unknowns: response.unknowns ?? [],
    recommendedNextStep: response.recommended_next_step ?? '',
    classificationMethod: response.classification_method ?? 'heuristic',
    classifiedAt: response.classified_at,
  };
}

function workspaceAdmissionFailure(error: unknown): WorkspaceAdmissionFailure | undefined {
  const metadata = error instanceof SidecarHttpError
    ? error.metadata
    : typeof error === 'object' && error !== null && 'metadata' in error
      ? (error as { metadata?: { code?: string; category?: string; pathState?: SidecarErrorPathState } }).metadata ?? {}
      : {};
  const rawCode = metadata.code?.toLowerCase();
  if (rawCode === 'root_id_mismatch' || rawCode === 'root_path_unavailable' || rawCode === 'root_missing') {
    return {
      errorCode: rawCode,
      category: 'workspace_root',
      pathState: metadata.pathState ?? (rawCode === 'root_missing' ? 'missing' : 'unavailable'),
    };
  }
  if (rawCode === 'backend_unavailable') {
    return { errorCode: rawCode, category: 'backend', pathState: metadata.pathState ?? 'unknown' };
  }
  return undefined;
}

function workspaceAdmissionFailureMessage(
  failure: WorkspaceAdmissionFailure,
  language: ComposerLanguage | undefined,
): string {
  const chinese = language === 'zh-CN';
  const next = failure.errorCode === 'root_missing'
    ? (chinese ? '请先选择 Trainer 工作区根目录。' : 'Choose the Trainer workspace root first.')
    : failure.errorCode === 'root_id_mismatch'
      ? (chinese ? '请重新选择与该路径匹配的 Trainer 工作区根目录后重试。' : 'Re-select the Trainer workspace root that matches this path, then retry.')
      : failure.errorCode === 'root_path_unavailable'
        ? (chinese ? '请确认根目录仍可访问，再重新选择并重试。' : 'Verify that the root is accessible, re-select it, and retry.')
        : (chinese ? '请确认工作区受信任且 sidecar 可用，然后重试。' : 'Verify workspace trust and sidecar availability, then retry.');
  return `${chinese ? '无法添加项目' : 'Project could not be added'} (${failure.errorCode}). ${next}`;
}

function safeWorkspaceAdmissionLog(failure: WorkspaceAdmissionFailure, statusCode?: number): string {
  return `[workspace-admission] status=${statusCode ?? 'unknown'} code=${failure.errorCode} category=${failure.category} path_state=${failure.pathState}`;
}

function resolveWorkspaceAdmissionResponseLanguage(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): ComposerLanguage | undefined {
  if (isComposerLanguage(payload?.responseLanguage)) {
    return payload.responseLanguage;
  }
  const workspaceLanguage = context.getHostState().bootstrap.memory.workspace?.responseLanguage;
  return isComposerLanguage(workspaceLanguage) ? workspaceLanguage : undefined;
}

async function withUserInitiatedProjectAdmission<T>(
  context: CommandContext,
  operation: () => Promise<T>,
): Promise<T> {
  const restoreMode = currentReadOnlyAdmissionMode(context);
  if (!restoreMode) {
    return operation();
  }

  context.sidecarClient.setTrainerAdmissionMode(undefined);
  try {
    return await operation();
  } finally {
    context.sidecarClient.setTrainerAdmissionMode(restoreMode);
  }
}

function pathsEqual(left: string, right: string): boolean {
  const normalize = (value: string): string => {
    // Windows drive/UNC paths are opaque absolute identifiers on POSIX hosts:
    // resolving them against the POSIX cwd would corrupt the comparison.
    if (/^([a-zA-Z]:[\/]|\\)/.test(value)) {
      const winNormalized = path.win32.normalize(value);
      return process.platform === 'win32'
        ? winNormalized.toLocaleLowerCase('en-US')
        : winNormalized;
    }
    const normalized = path.normalize(path.resolve(value));
    return process.platform === 'win32' ? normalized.toLocaleLowerCase('en-US') : normalized;
  };
  return normalize(left) === normalize(right);
}

function selectedRootFromManifest(manifest: TrainerWorkspaceManifest): SelectedTrainerRoot {
  return {
    // Windows drive/UNC roots are opaque absolute identifiers on POSIX hosts:
    // normalize them with filesystem-aware rules instead of path.resolve,
    // which would wrongly join them onto the POSIX cwd.
    canonicalRootPath: normalizeFsPath(manifest.canonicalRootPath),
    rootId: manifest.rootId,
  };
}

function runtimeDataRootUnder(rootPath: string): string {
  // Windows-style roots keep win32 join semantics on every host so the
  // configured managed-data location stays a well-formed identifier.
  if (looksLikeWindowsAbsolutePath(rootPath)) {
    return path.win32.join(rootPath, '.trainer', 'runtime');
  }
  return path.join(rootPath, TRAINER_WORKSPACE_RUNTIME_DATA_DIRECTORY);
}

async function readSelectedTrainerRoot(context: CommandContext): Promise<SelectedTrainerRoot> {
  const manifest = await context.trainerWorkspace.readWorkspaceManifest();
  if (!manifest) {
    const configuredRoot = context.trainerWorkspace.getRoot();
    throw new Error(
      configuredRoot
        ? `Project could not be added (root_path_unavailable). The selected Trainer workspace root is unavailable: ${configuredRoot}. Choose the Trainer workspace root again, then click Add to Trainer to retry.`
        : 'Project could not be added (root_missing). No Trainer workspace root is selected. Choose the Trainer workspace root, then click Add to Trainer to retry.',
    );
  }
  return selectedRootFromManifest(manifest);
}

function unresolvableProjectPathResult(context: CommandContext): CommandExecutionResult {
  const language = resolveWorkspaceAdmissionResponseLanguage(context);
  const failure: WorkspaceAdmissionFailure = {
    errorCode: 'root_missing',
    category: 'workspace_root',
    pathState: 'missing',
  };
  const workspace = context.getHostState().workspace;
  const resolvedPath = workspace.activeWorkspaceRoot ?? workspace.workspaceFolder;
  const resolutionDetail = resolvedPath
    ? `Trainer could not resolve the current project folder (resolved workspace folder: ${resolvedPath}).`
    : 'Trainer could not resolve the current project folder (no workspace folder is open).';
  return {
    ok: false,
    message: `${workspaceAdmissionFailureMessage(failure, language)} ${resolutionDetail} Reopen the project folder, then click Add to Trainer again to retry.`,
    data: failure,
  };
}

function serverRootPath(response: ProjectDecisionResponse): string | undefined {
  const identityPath = response.project_identity?.canonicalRootPath;
  const provisioningPath =
    response.project_provisioning?.root_path ?? response.project_provisioning?.rootPath;
  if (identityPath && provisioningPath && !pathsEqual(identityPath, provisioningPath)) {
    throw new Error('Trainer backend returned conflicting workspace-root paths.');
  }
  return identityPath ?? provisioningPath;
}

function serverRootId(response: ProjectDecisionResponse): string | undefined {
  const identityId = response.project_identity?.rootId;
  const provisioningId = response.project_provisioning?.root_id ?? response.project_provisioning?.rootId;
  if (identityId && provisioningId && identityId !== provisioningId) {
    throw new Error('Trainer backend returned conflicting workspace-root IDs.');
  }
  return identityId ?? provisioningId;
}

function assertProvisioningMatchesSelectedRoot(
  response: ProjectDecisionResponse,
  selectedRoot: SelectedTrainerRoot,
): void {
  const returnedRootPath = serverRootPath(response);
  const returnedRootId = serverRootId(response);
  if (!returnedRootPath || !pathsEqual(returnedRootPath, selectedRoot.canonicalRootPath)) {
    throw new Error('Trainer backend did not keep this project under the selected Trainer workspace.');
  }
  if (!returnedRootId) {
    throw new Error('Trainer backend did not return the stable identity for the selected workspace.');
  }
  if (selectedRoot.rootId && selectedRoot.rootId !== returnedRootId) {
    throw new Error('Trainer workspace changed while this project was being added.');
  }
}

export async function chooseTrainerWorkspaceRootCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('set up the Trainer workspace root'))) {
    return { ok: false, message: 'Workspace trust is required to set up the Trainer workspace root.' };
  }

  const currentRoot = context.trainerWorkspace.getRoot();
  const picks = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri: currentRoot ? vscode.Uri.file(currentRoot) : undefined,
    openLabel: 'Use as Trainer Workspace',
    title: 'Choose Trainer Workspace Root',
  });
  const rootPath = picks?.[0]?.fsPath;
  if (!rootPath) {
    return { ok: false, message: 'Trainer Workspace Root selection cancelled.' };
  }

  const { result: manifest, restartedSidecar } = await runWithQuiescentManagedData(
    context,
    async () => context.trainerWorkspace.selectRoot(rootPath),
    (selectedManifest) => runtimeDataRootUnder(selectedManifest.rootPath),
  );
  await patchTrainerWorkspaceAdmission(context);
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar);
  return {
    ok: true,
    message: `Trainer Workspace is ready at ${manifest.rootPath}.`,
    data: manifest,
  };
}

export async function migrateTrainerWorkspaceRootCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('migrate the Trainer workspace root'))) {
    return { ok: false, message: 'Workspace trust is required to migrate the Trainer workspace root.' };
  }

  const targetRoot = await pickTrainerWorkspaceDirectory({
    currentRoot: context.trainerWorkspace.getRoot(),
    openLabel: 'Migrate Trainer Workspace Here',
    title: 'Choose an Empty Folder for the Migrated Trainer Workspace',
  });
  if (!targetRoot) {
    return { ok: false, message: 'Trainer Workspace migration cancelled.' };
  }

  const { result: migration, restartedSidecar } = await runWithQuiescentManagedData(
    context,
    async (managedDataRoot) =>
      context.trainerWorkspace.migrateWorkspaceRoot(targetRoot, { managedDataRoot }),
    (result) => result.managedDataRoot,
  );
  await patchTrainerWorkspaceAdmission(context);
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar);
  return {
    ok: true,
    message: `Trainer Workspace was copied to ${migration.targetRoot}. The previous root was left unchanged.`,
    data: migration,
  };
}

export async function backupTrainerWorkspaceCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('back up the Trainer workspace root'))) {
    return { ok: false, message: 'Workspace trust is required to back up the Trainer workspace root.' };
  }

  const backupRoot = await pickTrainerWorkspaceDirectory({
    currentRoot: context.trainerWorkspace.getRoot(),
    openLabel: 'Save Trainer Workspace Backup Here',
    title: 'Choose an Empty Folder for the Trainer Workspace Backup',
  });
  if (!backupRoot) {
    return { ok: false, message: 'Trainer Workspace backup cancelled.' };
  }

  const { result: backup, restartedSidecar } = await runWithQuiescentManagedData(
    context,
    async (managedDataRoot) => context.trainerWorkspace.backupWorkspace(backupRoot, { managedDataRoot }),
  );
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar);
  return {
    ok: true,
    message: `Trainer Workspace backup was created at ${backup.backupRoot}.`,
    data: backup,
  };
}

export async function restoreTrainerWorkspaceBackupCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('restore a Trainer workspace backup'))) {
    return { ok: false, message: 'Workspace trust is required to restore a Trainer workspace backup.' };
  }

  const backupRoot = await pickTrainerWorkspaceDirectory({
    openLabel: 'Use This Trainer Workspace Backup',
    title: 'Choose a Trainer Workspace Backup',
  });
  if (!backupRoot) {
    return { ok: false, message: 'Trainer Workspace restore cancelled.' };
  }

  const targetRoot = await pickTrainerWorkspaceDirectory({
    currentRoot: context.trainerWorkspace.getRoot(),
    openLabel: 'Restore Trainer Workspace Here',
    title: 'Choose an Empty Folder for the Restored Trainer Workspace',
  });
  if (!targetRoot) {
    return { ok: false, message: 'Trainer Workspace restore cancelled.' };
  }

  const { result: restoration, restartedSidecar } = await runWithQuiescentManagedData(
    context,
    async () => context.trainerWorkspace.restoreWorkspaceBackup(backupRoot, targetRoot),
    (result) => result.managedDataRoot,
  );
  await patchTrainerWorkspaceAdmission(context);
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar);
  return {
    ok: true,
    message: `Trainer Workspace was restored to ${restoration.targetRoot}.`,
    data: restoration,
  };
}

async function runWithQuiescentManagedData<T>(
  context: CommandContext,
  operation: (managedDataRoot: string) => Promise<T>,
  resolveNextManagedDataRoot?: (result: T) => string | undefined,
): Promise<{ result: T; restartedSidecar: boolean }> {
  const workspaceFolder = context.getHostState().workspace.workspaceFolder;
  const currentData = context.sidecarManager.getManagedDataFolderSnapshot(workspaceFolder);
  const priorLifecycle = context.sidecarManager.getStatus().lifecycle;
  const wasReady = priorLifecycle === 'ready' || priorLifecycle === 'starting';
  const previousWorkspaceRoot = context.trainerWorkspace.getRoot();
  let operationFailure: unknown;

  if (wasReady) {
    await context.setSessionId(undefined);
    await context.sidecarManager.stop();
  }

  try {
    const result = await operation(currentData.effectivePath);
    if (resolveNextManagedDataRoot) {
      const nextManagedDataRoot = resolveNextManagedDataRoot(result);
      if (!nextManagedDataRoot) {
        throw new Error('Workspace transfer did not include the runtime data required to resume Trainer.');
      }
      await context.sidecarManager.configureManagedDataFolder(nextManagedDataRoot, workspaceFolder, {
        allowExistingTarget: true,
      });
    }
    return { result, restartedSidecar: wasReady };
  } catch (error) {
    operationFailure = error;
    if (resolveNextManagedDataRoot) {
      await context.trainerWorkspace.rollbackWorkspaceRoot(previousWorkspaceRoot).catch(() => undefined);
      await patchTrainerWorkspaceAdmission(context).catch(() => undefined);
    }
    throw error;
  } finally {
    if (wasReady) {
      try {
        const status = await context.sidecarManager.restart();
        if (!operationFailure && status.lifecycle !== 'ready') {
          throw new Error(status.detail ?? 'Trainer backend did not restart after workspace data transfer.');
        }
      } catch (error) {
        if (!operationFailure) {
          throw error;
        }
      }
    }
  }
}

async function rehydrateAfterWorkspaceDataTransfer(
  context: CommandContext,
  restartedSidecar: boolean,
): Promise<void> {
  const incomingWorkspaceId = incomingWorkspaceIdAfterAdmission(
    context,
    context.getHostState().bootstrap.memory.workspace?.trainerWorkspace,
  );
  await context.patchWorkbenchData(
    failClosedWorkbenchAfterWorkspaceTransfer(context.getHostState().bootstrap, incomingWorkspaceId),
  );
  if (!restartedSidecar) {
    return;
  }
  await context.setSessionId(undefined);
  await rehydrateWorkbenchRuntime(context, {
    ensureSidecar: false,
    syncWorkbench: true,
  });
  await context.patchWorkbenchData(
    failClosedWorkbenchAfterWorkspaceTransfer(context.getHostState().bootstrap, incomingWorkspaceId),
  );
}

export async function adoptWorkspaceProjectCommand(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): Promise<CommandExecutionResult> {
  return setCurrentWorkspaceProjectAdmission(
    context,
    'managed',
    resolveWorkspaceAdmissionResponseLanguage(context, payload),
    typeof payload?.projectPath === 'string' ? payload.projectPath : undefined,
  );
}

export async function chooseWorkspaceProjectCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('choose the Trainer project folder'))) {
    return { ok: false, message: 'Workspace trust is required to choose the Trainer project folder.' };
  }
  const picks = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    openLabel: 'Use as Trainer Project',
    title: 'Choose Trainer Project Folder',
  });
  const projectPath = picks?.[0]?.fsPath;
  if (!projectPath) {
    return { ok: false, cancelled: true, message: 'Trainer project folder selection cancelled.' };
  }
  return setCurrentWorkspaceProjectAdmission(context, 'managed', undefined, projectPath);
}

export async function browseWorkspaceProjectCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  return setCurrentWorkspaceProjectAdmission(context, 'browse');
}

export async function ignoreWorkspaceProjectCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  return setCurrentWorkspaceProjectAdmission(context, 'ignored');
}

export async function deleteWorkspaceProjectCommand(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('delete the Trainer project'))) {
    return { ok: false, message: 'Workspace trust is required to delete a Trainer project.' };
  }

  const projectPath =
    (typeof payload?.projectPath === 'string' ? payload.projectPath.trim() : '') ||
    resolveCurrentTrainerProjectPath(context.getHostState().workspace);
  if (!projectPath) {
    return {
      ok: false,
      message: 'Open the project you want to delete from Trainer.',
    };
  }

  const existing = await context.trainerWorkspace.getProject(projectPath);
  if (!existing || existing.adoptionMode !== 'managed') {
    return {
      ok: false,
      message: 'This folder is not a managed Trainer project.',
    };
  }

  const confirmed = await vscode.window.showWarningMessage(
    'Delete this project from Trainer? Stored records stay on the project lane. Live plan, task, and cards will not stay open here.',
    { modal: true },
    'Delete project',
  );
  if (confirmed !== 'Delete project') {
    return { ok: false, cancelled: true, message: 'Trainer project delete cancelled.' };
  }

  const deleted = await context.trainerWorkspace.deleteManagedProject(projectPath);
  const liveDeleted = deletedProjectIsLiveOnWorkbench(context.getHostState().bootstrap, deleted);
  const excludedWorkspaceIds = await excludeDeletedProjectFromTransferPromotion(context, deleted);
  const demotedBeforeAdmission = applyExcludedWorkspacesToBootstrap(
    context.getHostState().bootstrap,
    excludedWorkspaceIds,
  );
  if (liveDeleted) {
    await patchWorkbenchAfterDeletedLiveProject(context);
  } else {
    await patchTrainerWorkspaceAdmission(context);
  }
  if (!liveDeleted && demotedBeforeAdmission) {
    const current = context.getHostState().bootstrap;
    await context.patchWorkbenchData({
      memory: {
        ...current.memory,
        ...(demotedBeforeAdmission.memory ?? {}),
        workspace: {
          ...current.memory.workspace,
          ...(demotedBeforeAdmission.memory?.workspace ?? {}),
          latestTransferState: demotedBeforeAdmission.memory?.workspace?.latestTransferState,
        },
      },
      workspaceTrainingState: {
        ...(current.workspaceTrainingState ?? {}),
        ...(demotedBeforeAdmission.workspaceTrainingState ?? {}),
        latestTransferState: demotedBeforeAdmission.workspaceTrainingState?.latestTransferState,
      },
    });
  }
  return {
    ok: true,
    message: 'The Trainer project was deleted. Stored records remain on the project lane.',
    data: deleted,
  };
}

export async function retryWorkspaceAdmissionCommand(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): Promise<CommandExecutionResult> {
  return adoptWorkspaceProjectCommand(context, payload);
}

export async function continueWorkspaceAdmissionCommand(
  context: CommandContext,
  payload?: WorkspaceAdmissionCommandPayload,
): Promise<CommandExecutionResult> {
  return adoptWorkspaceProjectCommand(context, payload);
}

export async function abandonWorkspaceAdmissionCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const projectPath = resolveCurrentTrainerProjectPath(context.getHostState().workspace);
  if (!projectPath) return { ok: false, message: 'Open the pending project before abandoning reconciliation.' };
  await context.trainerWorkspace.abandonManagedProvisioning(projectPath);
  await patchTrainerWorkspaceAdmission(context);
  return { ok: true, message: 'Pending workspace reconciliation was cleared; the project was not changed.' };
}

function incomingWorkspaceIdAfterAdmission(
  context: CommandContext,
  trainerWorkspace: NonNullable<BootstrapData['memory']['workspace']>['trainerWorkspace'],
): string | undefined {
  if (trainerWorkspace?.status === 'managed') {
    const contextId = trainerWorkspace.contextId?.trim();
    if (contextId) {
      return contextId;
    }
  }
  if (
    trainerWorkspace?.status === 'ignored' ||
    trainerWorkspace?.status === 'browse' ||
    (trainerWorkspace?.status === 'root-missing' && !trainerWorkspace.projectPath)
  ) {
    return undefined;
  }
  return (
    resolveSovereignWorkspaceRootPath(context.getHostState().workspace) ??
    trainerWorkspace?.canonicalProjectPath ??
    trainerWorkspace?.projectPath ??
    trainerWorkspace?.rootPath
  );
}

function uniqueWorkspaceScopeIds(...values: Array<string | undefined>): string[] {
  const ids: string[] = [];
  for (const value of values) {
    const cleaned = value?.trim();
    if (!cleaned || ids.includes(cleaned)) {
      continue;
    }
    ids.push(cleaned);
  }
  return ids;
}

async function excludeDeletedProjectFromTransferPromotion(
  context: CommandContext,
  deleted: {
    projectId?: string;
    contextId?: string;
    projectPath?: string;
    canonicalProjectPath?: string;
  },
): Promise<string[]> {
  const current = context.getHostState().bootstrap;
  const workspaceIds = uniqueWorkspaceScopeIds(
    deleted.contextId,
    deleted.projectId,
    deleted.projectPath,
    deleted.canonicalProjectPath,
    deletedProjectIsLiveOnWorkbench(current, deleted) ? current.memory.workspace?.workspaceId : undefined,
  );
  await postOrQueueTransferPromotionScope(
    context,
    'exclude',
    workspaceIds,
    'Trainer kept the project deleted, but could not exclude leftover transfer scenes',
  );
  return workspaceIds;
}

async function includeAdoptedProjectInTransferPromotion(
  context: CommandContext,
  identity: TrainerManagedProjectIdentity | undefined,
  projectPath: string,
): Promise<void> {
  await postOrQueueTransferPromotionScope(
    context,
    'include',
    uniqueWorkspaceScopeIds(
      identity?.contextId,
      identity?.projectId,
      identity?.canonicalProjectPath,
      projectPath,
    ),
    'Trainer added the project, but could not restore leftover transfer scenes to the promotion set',
  );
}

export { flushPendingTransferPromotionScope };

function deletedProjectIsLiveOnWorkbench(
  current: BootstrapData,
  deleted: { projectId?: string; contextId?: string; projectPath?: string; canonicalProjectPath?: string },
): boolean {
  const admission = current.memory.workspace?.trainerWorkspace;
  const liveIds = [
    admission?.projectId,
    admission?.contextId,
    admission?.projectPath,
    admission?.canonicalProjectPath,
    current.memory.workspace?.workspaceId,
    current.workspaceTrainingState?.workspaceId,
  ]
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  const deletedIds = [
    deleted.projectId,
    deleted.contextId,
    deleted.projectPath,
    deleted.canonicalProjectPath,
  ]
    .map((value) => value?.trim())
    .filter((value): value is string => Boolean(value));
  return deletedIds.some((deletedId) =>
    liveIds.some((liveId) => liveId === deletedId || path.resolve(liveId) === path.resolve(deletedId)),
  );
}

async function patchWorkbenchAfterDeletedLiveProject(context: CommandContext): Promise<void> {
  const current = context.getHostState().bootstrap;
  const failClosed = failClosedWorkbenchAfterWorkspaceTransfer(current, undefined);
  const trainerWorkspace = await resolveTrainerWorkspaceAdmission(
    context.trainerWorkspace,
    context.getHostState().workspace,
  );
  const resourceSandbox = context.sidecarManager.getManagedDataFolderSnapshot(
    context.getHostState().workspace.workspaceFolder,
  );
  context.sidecarClient.setTrainerAdmissionMode?.(trainerWorkspace?.status);
  await context.patchWorkbenchData({
    ...failClosed,
    memory: {
      ...failClosed.memory,
      workspace: {
        ...(failClosed.memory?.workspace ?? {}),
        trainerWorkspace,
        resourceSandbox,
      },
    },
  } as Partial<BootstrapData>);
  await context.setSessionId(undefined);
}

export async function patchTrainerWorkspaceAdmission(context: CommandContext): Promise<void> {
  const current = context.getHostState().bootstrap;
  const trainerWorkspace = await resolveTrainerWorkspaceAdmission(
    context.trainerWorkspace,
    context.getHostState().workspace,
  );
  const incomingWorkspaceId = incomingWorkspaceIdAfterAdmission(context, trainerWorkspace);
  const failClosed = failClosedWorkbenchAfterWorkspaceTransfer(current, incomingWorkspaceId);
  const resourceSandbox = context.sidecarManager.getManagedDataFolderSnapshot(
    context.getHostState().workspace.workspaceFolder,
  );
  context.sidecarClient.setTrainerAdmissionMode?.(trainerWorkspace?.status);
  await context.patchWorkbenchData({
    ...failClosed,
    memory: {
      ...failClosed.memory,
      workspace: {
        ...(failClosed.memory?.workspace ?? {}),
        trainerWorkspace,
        resourceSandbox,
      },
    },
  } as Partial<BootstrapData>);
  await patchProjectFoundFirstLookSummary(context, trainerWorkspace);
}

async function patchProjectFoundFirstLookSummary(
  context: CommandContext,
  trainerWorkspace: NonNullable<BootstrapData['memory']['workspace']>['trainerWorkspace'],
): Promise<void> {
  const projectPath = trainerWorkspace?.projectPath;
  if (trainerWorkspace?.status !== 'project-found' || !projectPath || !trainerWorkspace.rootPath) {
    return;
  }

  let selectedRoot: SelectedTrainerRoot;
  try {
    selectedRoot = await readSelectedTrainerRoot(context);
  } catch (error) {
    context.outputChannel.appendLine(
      `Trainer First Look skipped because the selected workspace root is unavailable: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
    return;
  }
  if (
    !pathsEqual(selectedRoot.canonicalRootPath, trainerWorkspace.rootPath) ||
    (trainerWorkspace.rootId && selectedRoot.rootId && trainerWorkspace.rootId !== selectedRoot.rootId)
  ) {
    return;
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    context.outputChannel.appendLine(
      `Trainer First Look skipped because the backend is unavailable: ${
        status.detail ?? 'sidecar did not report a ready port'
      }`,
    );
    return;
  }

  try {
    const responseLanguage = resolveWorkspaceAdmissionResponseLanguage(context);
    const workspaceFileSnapshot = await buildWorkspaceFileSnapshot(context);
    const classification = await classifyProjectForAdmission(context, status.port, {
      workspace_id: projectPath,
      folder_path: projectPath,
      root_id: selectedRoot.rootId,
      root_path: selectedRoot.canonicalRootPath,
      remote_name: context.getHostState().workspace.remoteName ?? '',
      ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
      ...(responseLanguage ? { response_language: responseLanguage } : {}),
    });
    const firstLookSummary = firstLookSummaryFromClassification(classification);
    if (!firstLookSummary) {
      context.outputChannel.appendLine('Trainer First Look skipped because the backend returned no summary.');
      return;
    }

    const current = context.getHostState().bootstrap;
    await context.patchWorkbenchData({
      memory: {
        ...current.memory,
        workspaceUnderstanding: {
          ...current.memory.workspaceUnderstanding,
          firstLookSummary,
        },
      },
    } as Partial<BootstrapData>);
  } catch (error) {
    const failure = workspaceAdmissionFailure(error);
    context.outputChannel.appendLine(
      failure
        ? `Trainer First Look classification failed: ${safeWorkspaceAdmissionLog(
            failure,
            error instanceof SidecarHttpError ? error.statusCode : undefined,
          )}`
        : 'Trainer First Look classification failed: backend error details were omitted.',
    );
  }
}

async function setCurrentWorkspaceProjectAdmission(
  context: CommandContext,
  adoptionMode: TrainerProjectAdoptionMode,
  responseLanguage?: ComposerLanguage,
  selectedProjectPath?: string,
): Promise<CommandExecutionResult> {
  if (!(await context.trustGuard.ensureTrusted('set the current Trainer project admission mode'))) {
    return { ok: false, message: 'Workspace trust is required to update the Trainer project admission.' };
  }

  const projectPath = selectedProjectPath?.trim() || resolveCurrentTrainerProjectPath(context.getHostState().workspace);
  if (!projectPath) {
    return unresolvableProjectPathResult(context);
  }

  let managedIdentity: TrainerManagedProjectIdentity | undefined;
  if (adoptionMode === 'managed') {
    try {
      const provisioned = await provisionManagedProject(context, projectPath, responseLanguage);
      if (provisioned.kind === 'browse') {
        const project = await context.trainerWorkspace.setProjectAdmission(projectPath, 'browse');
        await patchTrainerWorkspaceAdmission(context);
        return {
          ok: true,
          message: 'The current project will stay browse-only and will not receive long-lived project memory.',
          data: project,
        };
      }
      managedIdentity = provisioned.identity;
    } catch (error) {
      const failure = workspaceAdmissionFailure(error);
      if (!failure) {
        const fallback = error instanceof Error ? error.message : String(error);
        await context.trainerWorkspace.recordManagedProvisioningPending(projectPath, fallback).catch(() => undefined);
        return { ok: false, message: fallback };
      }
      const language = resolveWorkspaceAdmissionResponseLanguage(context, { responseLanguage });
      const message = workspaceAdmissionFailureMessage(failure, language);
      context.outputChannel.appendLine(
        safeWorkspaceAdmissionLog(failure, error instanceof SidecarHttpError ? error.statusCode : undefined),
      );
      await context.trainerWorkspace.recordManagedProvisioningPending(projectPath, message).catch(() => undefined);
      return { ok: false, message, data: failure };
    }
  } else {
    try {
      await assertProjectCanUseNonManagedAdmission(context, projectPath);
    } catch (error) {
      return {
        ok: false,
        message: error instanceof Error ? error.message : String(error),
      };
    }
  }

  const project = await context.trainerWorkspace.setProjectAdmission(
    projectPath,
    adoptionMode,
    managedIdentity,
  );
  if (adoptionMode === 'managed') {
    await includeAdoptedProjectInTransferPromotion(context, managedIdentity, projectPath);
  }
  await patchTrainerWorkspaceAdmission(context);
  if (adoptionMode === 'managed') {
    await rehydrateWorkbenchRuntime(context, {
      ensureSidecar: true,
      syncWorkbench: true,
    });
  }
  const description =
    adoptionMode === 'managed'
      ? 'was added to Trainer with an isolated project lane.'
      : adoptionMode === 'browse'
        ? 'will stay browse-only and will not receive long-lived project memory.'
        : 'will be ignored by Trainer.';
  return {
    ok: true,
    message: `The current project ${description}`,
    data: project,
  };
}

function discoveryDecisionFromClassification(
  classification: ProjectClassificationResponse,
  remoteName: string,
): 'adopt' | 'browse' {
  const discovery = classification.project_discovery;
  const available = discovery?.available_decisions ?? discovery?.availableDecisions;
  if (Array.isArray(available) && available.length > 0) {
    if (available.includes('adopt')) {
      return 'adopt';
    }
    if (available.includes('browse')) {
      return 'browse';
    }
  }
  if (discovery?.is_browse_only === true || discovery?.isBrowseOnly === true) {
    return 'browse';
  }
  if (remoteName.trim()) {
    return 'browse';
  }
  return 'adopt';
}

async function relocateWorkspaceRootForProject(
  context: CommandContext,
  projectPath: string,
  selectedRoot: SelectedTrainerRoot,
): Promise<SelectedTrainerRoot> {
  const normalizedProject = normalizeFsPath(projectPath);
  const windowsStyleProject = looksLikeWindowsAbsolutePath(normalizedProject);
  const parentRoot = windowsStyleProject
    ? path.win32.normalize(path.win32.dirname(normalizedProject))
    : path.resolve(path.dirname(normalizedProject));
  const filesystemRoot = windowsStyleProject
    ? path.win32.parse(normalizedProject).root
    : path.parse(normalizedProject).root;
  if (
    !parentRoot ||
    pathsEqual(parentRoot, normalizedProject) ||
    pathsEqual(parentRoot, filesystemRoot)
  ) {
    throw new Error(
      'The current project is also the Trainer workspace root, and no separate parent folder is available for the workspace. Choose a different Trainer workspace root, then add the project again.',
    );
  }

  context.outputChannel.appendLine(
    `[workspace-admission] The project folder is the workspace root; relocating the Trainer workspace root to its parent: ${parentRoot}`,
  );
  const { result: manifest, restartedSidecar } = await runWithQuiescentManagedData(
    context,
    async () => context.trainerWorkspace.selectRoot(parentRoot),
    (selectedManifest) => runtimeDataRootUnder(selectedManifest.rootPath),
  );
  await patchTrainerWorkspaceAdmission(context);
  await rehydrateAfterWorkspaceDataTransfer(context, restartedSidecar);
  void vscode.window.showInformationMessage(
    `The Trainer workspace root was moved to ${parentRoot} so the project can be added as a project lane.`,
  );
  return selectedRootFromManifest(manifest);
}

async function classifyProjectForAdmission(
  context: CommandContext,
  port: number,
  body: WorkspaceClassificationRequest,
): Promise<ProjectClassificationResponse> {
  try {
    return await postUserInitiatedProjectAdmission<ProjectClassificationResponse>(
      context,
      port,
      '/workspace/classify',
      body,
    );
  } catch (error) {
    const failure = workspaceAdmissionFailure(error);
    if (failure?.errorCode !== 'root_path_unavailable' || !body.root_id || !body.root_path) {
      throw error;
    }
    // The backend rejected this root identity as unknown or unavailable (for
    // example after the sidecar data directory was reset). A retry must stay a
    // fresh attempt instead of replaying the same stale identity forever:
    // re-register the selected root by path so the backend returns a fresh
    // root_identity, which the caller persists before the admission decision.
    context.outputChannel.appendLine(
      `[workspace-admission] backend rejected root identity ${body.root_id} (root_path_unavailable); re-registering the selected root by path`,
    );
    const reRegistrationBody: WorkspaceClassificationRequest = {
      workspace_id: body.workspace_id,
      folder_path: body.folder_path,
      root_path: body.root_path,
      remote_name: body.remote_name,
      ...(body.workspace_file_snapshot ? { workspace_file_snapshot: body.workspace_file_snapshot } : {}),
      ...(body.response_language ? { response_language: body.response_language } : {}),
    };
    return postUserInitiatedProjectAdmission<ProjectClassificationResponse>(
      context,
      port,
      '/workspace/classify',
      reRegistrationBody,
    );
  }
}

async function provisionManagedProject(
  context: CommandContext,
  projectPath: string,
  responseLanguage?: ComposerLanguage,
): Promise<{ kind: 'managed'; identity: TrainerManagedProjectIdentity } | { kind: 'browse' }> {
  let selectedRoot = await readSelectedTrainerRoot(context);
  if (pathsEqual(selectedRoot.canonicalRootPath, projectPath)) {
    selectedRoot = await relocateWorkspaceRootForProject(context, projectPath, selectedRoot);
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    throw new Error(status.detail ?? 'Trainer backend is unavailable.');
  }

  const workspaceName = basenameFs(projectPath) || 'Trainer';
  const workspaceFileSnapshot = await buildWorkspaceFileSnapshot(context);
  const classification = await classifyProjectForAdmission(context, status.port, {
    workspace_id: projectPath,
    folder_path: projectPath,
    root_id: selectedRoot.rootId,
    root_path: selectedRoot.canonicalRootPath,
    remote_name: context.getHostState().workspace.remoteName ?? '',
    ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
    ...(responseLanguage ? { response_language: responseLanguage } : {}),
  });
  const registeredRootId = classification.root_identity?.rootId;
  const registeredRootPath = classification.root_identity?.rootPath;
  if (!registeredRootId || !registeredRootPath) {
    throw new Error('Trainer backend did not register the selected workspace root before adding the project.');
  }
  await context.trainerWorkspace.setRootIdentity(registeredRootId, registeredRootPath);
  selectedRoot = await readSelectedTrainerRoot(context);
  const started = await postUserInitiatedProjectAdmission<{ session_id?: string }>(
    context,
    status.port,
    '/session/start',
    {
      workspace_id: projectPath,
      workspace_name: workspaceName,
      workspace_path: projectPath,
      root_id: selectedRoot.rootId,
      root_path: selectedRoot.canonicalRootPath,
      remote_name: context.getHostState().workspace.remoteName ?? '',
      workspace_trusted: Boolean(context.getHostState().workspace.trusted),
      ...(workspaceFileSnapshot ? { workspace_file_snapshot: workspaceFileSnapshot } : {}),
      ...(responseLanguage ? { response_language: responseLanguage } : {}),
    },
  );
  const discoveryId = classification.project_discovery?.discovery_id;
  if (!discoveryId) {
    throw new Error('Trainer backend did not return a project discovery record.');
  }
  const decisionKind = discoveryDecisionFromClassification(
    classification,
    context.getHostState().workspace.remoteName ?? '',
  );
  const decision = await postUserInitiatedProjectAdmission<ProjectDecisionResponse>(
    context,
    status.port,
    '/workspace/discovery/decision',
    {
      workspace_id: projectPath,
      discovery_id: discoveryId,
      decision: decisionKind,
      root_id: selectedRoot.rootId,
      root_path: selectedRoot.canonicalRootPath,
    },
  );
  if (decisionKind === 'browse') {
    const sessionId = started.session_id?.trim();
    if (sessionId) {
      await context.setSessionId(sessionId);
    }
    return { kind: 'browse' };
  }
  const completed = await waitForManagedProjectAdoption(
    context,
    status.port,
    selectedRoot,
    projectPath,
    decision,
  );
  await context.setSessionId(completed.project_provisioning!.agent_session_id!);
  return { kind: 'managed', identity: completed.project_identity! };
}

function currentReadOnlyAdmissionMode(context: CommandContext): ReadOnlyAdmissionMode | undefined {
  const status = context.getHostState().bootstrap.memory.workspace?.trainerWorkspace?.status;
  return status === 'browse' || status === 'ignored' ? status : undefined;
}

async function postUserInitiatedProjectAdmission<T>(
  context: CommandContext,
  port: number,
  requestPath: string,
  body: unknown,
): Promise<T> {
  return withUserInitiatedProjectAdmission(context, () =>
    context.sidecarClient.postJson<T>(port, requestPath, body),
  );
}

async function getUserInitiatedProjectAdmission<T>(
  context: CommandContext,
  port: number,
  requestPath: string,
): Promise<T> {
  return withUserInitiatedProjectAdmission(context, () => context.sidecarClient.getJson<T>(port, requestPath));
}

function projectAdoptionPollingPath(jobId: string, rootPath: string, workspaceId: string): string {
  const params = new URLSearchParams({
    job_id: jobId,
    root_path: rootPath,
    workspace_id: workspaceId,
  });
  return `/workspace/adoption-job?${params.toString()}`;
}

function managedAdoptionFailureMessage(status: string | undefined, reason: string | undefined): string {
  const normalizedStatus = status?.trim().toLowerCase();
  if (normalizedStatus === 'interrupted') {
    return reason
      ? `Trainer adoption indexing was interrupted: ${reason}`
      : 'Trainer adoption indexing was interrupted.';
  }
  if (normalizedStatus === 'retry_required') {
    return reason ? `Trainer adoption indexing needs retry: ${reason}` : 'Trainer adoption indexing needs retry.';
  }
  return reason
    ? `Trainer adoption indexing timed out before completion: ${reason}`
    : 'Trainer adoption indexing timed out before completion.';
}

async function waitForManagedProjectAdoption(
  context: CommandContext,
  port: number,
  selectedRoot: SelectedTrainerRoot,
  projectPath: string,
  initialDecision: ProjectDecisionResponse,
): Promise<ProjectDecisionResponse> {
  const completedStatus = initialDecision.project_adoption_job?.status?.trim().toLowerCase();
  if (
    completedStatus === 'completed' &&
    initialDecision.project_discovery?.status === 'adopted' &&
    initialDecision.project_provisioning?.agent_session_id &&
    initialDecision.project_identity
  ) {
    const currentSelectedRoot = await readSelectedTrainerRoot(context);
    if (
      !pathsEqual(currentSelectedRoot.canonicalRootPath, selectedRoot.canonicalRootPath) ||
      currentSelectedRoot.rootId !== selectedRoot.rootId
    ) {
      throw new Error('Trainer workspace changed while this project was being added.');
    }
    assertProvisioningMatchesSelectedRoot(initialDecision, currentSelectedRoot);
    return initialDecision;
  }

  const jobId = initialDecision.project_adoption_job?.job_id?.trim();
  if (!jobId) {
    if (
      initialDecision.project_discovery?.status === 'adopted' &&
      initialDecision.project_provisioning?.agent_session_id &&
      initialDecision.project_identity
    ) {
      const currentSelectedRoot = await readSelectedTrainerRoot(context);
      if (
        !pathsEqual(currentSelectedRoot.canonicalRootPath, selectedRoot.canonicalRootPath) ||
        currentSelectedRoot.rootId !== selectedRoot.rootId
      ) {
        throw new Error('Trainer workspace changed while this project was being added.');
      }
      assertProvisioningMatchesSelectedRoot(initialDecision, currentSelectedRoot);
      return initialDecision;
    }
    throw new Error('Trainer backend did not start a project adoption job.');
  }

  const timeoutMs = 15_000;
  const pollIntervalMs = 250;
  const deadlineMs = Date.now() + timeoutMs;
  let lastStatus = initialDecision.project_adoption_job;

  while (Date.now() <= deadlineMs) {
    const currentSelectedRoot = await readSelectedTrainerRoot(context);
    if (
      !pathsEqual(currentSelectedRoot.canonicalRootPath, selectedRoot.canonicalRootPath) ||
      currentSelectedRoot.rootId !== selectedRoot.rootId
    ) {
      throw new Error('Trainer workspace changed while this project was being added.');
    }

    const response = await getUserInitiatedProjectAdmission<ProjectDecisionResponse>(
      context,
      port,
      projectAdoptionPollingPath(jobId, selectedRoot.canonicalRootPath, projectPath),
    );
    lastStatus = response.project_adoption_job ?? lastStatus;
    const status = response.project_adoption_job?.status?.trim().toLowerCase();
    if (status === 'completed') {
      const agentSessionId = response.project_provisioning?.agent_session_id;
      if (!agentSessionId || !response.project_identity || response.project_discovery?.status !== 'adopted') {
        throw new Error('Trainer backend completed adoption without returning the required project state.');
      }
      const finalSelectedRoot = await readSelectedTrainerRoot(context);
      if (
        !pathsEqual(finalSelectedRoot.canonicalRootPath, selectedRoot.canonicalRootPath) ||
        finalSelectedRoot.rootId !== selectedRoot.rootId
      ) {
        throw new Error('Trainer workspace changed while this project was being added.');
      }
      assertProvisioningMatchesSelectedRoot(response, finalSelectedRoot);
      return response;
    }
    if (status === 'interrupted' || status === 'retry_required') {
      throw new Error(managedAdoptionFailureMessage(status, response.project_adoption_job?.retry_reason));
    }

    const remainingMs = deadlineMs - Date.now();
    if (remainingMs <= 0) {
      break;
    }
    await new Promise<void>((resolve) => setTimeout(resolve, Math.min(pollIntervalMs, remainingMs)));
  }

  throw new Error(managedAdoptionFailureMessage(lastStatus?.status, lastStatus?.retry_reason));
}

async function assertProjectCanUseNonManagedAdmission(
  context: CommandContext,
  projectPath: string,
): Promise<void> {
  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    throw new Error(
      'Trainer could not verify whether this project is already managed. Browse or ignore was not applied.',
    );
  }

  let response: ProjectProvisioningResponse;
  try {
    response = await context.sidecarClient.getJson<ProjectProvisioningResponse>(
      status.port,
      `/workspace/project-provisioning?workspace_id=${encodeURIComponent(projectPath)}`,
    );
  } catch (error) {
    if (isSidecarNotFound(error)) {
      return;
    }
    throw new Error(
      'Trainer could not verify whether this project is already managed. Browse or ignore was not applied.',
    );
  }

  if (!response?.project_provisioning?.agent_session_id) {
    throw new Error(
      'Trainer received an incomplete project-management response. Browse or ignore was not applied.',
    );
  }
  throw new Error(
    'This project is already managed by Trainer. Use an explicit retire or revoke project flow before changing it to browse or ignore.',
  );
}

function isSidecarNotFound(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'statusCode' in error &&
    (error as { statusCode?: unknown }).statusCode === 404
  );
}

async function pickTrainerWorkspaceDirectory(input: {
  currentRoot?: string;
  openLabel: string;
  title: string;
}): Promise<string | undefined> {
  const picks = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    defaultUri: input.currentRoot ? vscode.Uri.file(input.currentRoot) : undefined,
    openLabel: input.openLabel,
    title: input.title,
  });
  return picks?.[0]?.fsPath;
}
