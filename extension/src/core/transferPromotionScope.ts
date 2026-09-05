import { demoteTransferSkillAfterExcludedWorkspaces } from '../../../shared/src/transferSkillGovernance';
import type { CommandContext } from './commandContext';
import { STORAGE_KEYS } from './constants';
import type { BootstrapData } from './types';

export type PendingTransferPromotionScope = {
  excludeWorkspaceIds: string[];
  includeWorkspaceIds: string[];
};

function uniqueIds(values: readonly string[]): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const cleaned = value.trim();
    if (!cleaned) {
      continue;
    }
    const key = cleaned.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    ids.push(cleaned);
  }
  return ids;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return uniqueIds(value.filter((item): item is string => typeof item === 'string'));
}

export function readPendingTransferPromotionScope(
  context: CommandContext,
): PendingTransferPromotionScope {
  const raw = context.extensionContext?.globalState?.get<unknown>(STORAGE_KEYS.pendingTransferPromotionScope);
  if (!raw || typeof raw !== 'object') {
    return { excludeWorkspaceIds: [], includeWorkspaceIds: [] };
  }
  const record = raw as PendingTransferPromotionScope;
  return {
    excludeWorkspaceIds: asStringArray(record.excludeWorkspaceIds),
    includeWorkspaceIds: asStringArray(record.includeWorkspaceIds),
  };
}

async function writePendingTransferPromotionScope(
  context: CommandContext,
  pending: PendingTransferPromotionScope,
): Promise<void> {
  const excludeWorkspaceIds = uniqueIds(pending.excludeWorkspaceIds);
  const includeWorkspaceIds = uniqueIds(pending.includeWorkspaceIds).filter(
    (id) => !excludeWorkspaceIds.some((excluded) => excluded.toLowerCase() === id.toLowerCase()),
  );
  if (excludeWorkspaceIds.length === 0 && includeWorkspaceIds.length === 0) {
    await context.extensionContext.globalState.update(STORAGE_KEYS.pendingTransferPromotionScope, undefined);
    return;
  }
  await context.extensionContext.globalState.update(STORAGE_KEYS.pendingTransferPromotionScope, {
    excludeWorkspaceIds,
    includeWorkspaceIds,
  });
}

export async function queuePendingTransferPromotionScope(
  context: CommandContext,
  action: 'exclude' | 'include',
  workspaceIds: readonly string[],
): Promise<PendingTransferPromotionScope> {
  const pending = readPendingTransferPromotionScope(context);
  const incoming = uniqueIds([...workspaceIds]);
  if (action === 'exclude') {
    pending.excludeWorkspaceIds = uniqueIds([...pending.excludeWorkspaceIds, ...incoming]);
    pending.includeWorkspaceIds = pending.includeWorkspaceIds.filter(
      (id) => !incoming.some((excluded) => excluded.toLowerCase() === id.toLowerCase()),
    );
  } else {
    pending.includeWorkspaceIds = uniqueIds([...pending.includeWorkspaceIds, ...incoming]);
    pending.excludeWorkspaceIds = pending.excludeWorkspaceIds.filter(
      (id) => !incoming.some((included) => included.toLowerCase() === id.toLowerCase()),
    );
  }
  await writePendingTransferPromotionScope(context, pending);
  return readPendingTransferPromotionScope(context);
}

export function applyExcludedWorkspacesToBootstrap(
  current: BootstrapData,
  excludedWorkspaceIds: readonly string[],
): Partial<BootstrapData> | undefined {
  const ids = uniqueIds([...excludedWorkspaceIds]);
  if (ids.length === 0) {
    return undefined;
  }
  const currentWorkspaceId =
    current.workspaceTrainingState?.workspaceId ?? current.memory.workspace?.workspaceId;
  const language = current.memory.workspace?.responseLanguage;
  const memoryTransfer = demoteTransferSkillAfterExcludedWorkspaces(
    current.memory.workspace?.latestTransferState,
    ids,
    { language, currentWorkspaceId },
  );
  const trainingTransfer = demoteTransferSkillAfterExcludedWorkspaces(
    current.workspaceTrainingState?.latestTransferState,
    ids,
    { language, currentWorkspaceId },
  );
  const memoryChanged = memoryTransfer !== current.memory.workspace?.latestTransferState;
  const trainingChanged = trainingTransfer !== current.workspaceTrainingState?.latestTransferState;
  if (!memoryChanged && !trainingChanged) {
    return undefined;
  }
  return {
    memory: {
      ...current.memory,
      workspace: {
        ...current.memory.workspace,
        latestTransferState: memoryTransfer,
      },
    },
    workspaceTrainingState: {
      ...(current.workspaceTrainingState ?? {}),
      latestTransferState: trainingTransfer,
    },
  };
}

async function postTransferPromotionScopeNow(
  context: CommandContext,
  requestPath: '/memory/transfer/exclude-workspace' | '/memory/transfer/include-workspace',
  workspaceIds: string[],
  failureLog: string,
): Promise<boolean> {
  if (workspaceIds.length === 0) {
    return true;
  }
  const status = context.sidecarManager.getStatus();
  const port = status.port;
  if (status.lifecycle !== 'ready' || !port) {
    return false;
  }
  const restoreMode =
    context.getHostState().bootstrap.memory.workspace?.trainerWorkspace?.status === 'browse' ||
    context.getHostState().bootstrap.memory.workspace?.trainerWorkspace?.status === 'ignored'
      ? context.getHostState().bootstrap.memory.workspace?.trainerWorkspace?.status
      : undefined;
  if (restoreMode) {
    context.sidecarClient.setTrainerAdmissionMode?.(undefined);
  }
  try {
    await context.sidecarClient.postJson(port, requestPath, { workspaceIds });
    return true;
  } catch (error) {
    context.outputChannel.appendLine(
      `${failureLog}: ${error instanceof Error ? error.message : String(error)}`,
    );
    return false;
  } finally {
    if (restoreMode) {
      context.sidecarClient.setTrainerAdmissionMode?.(restoreMode);
    }
  }
}

export async function postOrQueueTransferPromotionScope(
  context: CommandContext,
  action: 'exclude' | 'include',
  workspaceIds: string[],
  failureLog: string,
): Promise<void> {
  const ids = uniqueIds(workspaceIds);
  if (ids.length === 0) {
    return;
  }
  const requestPath =
    action === 'exclude' ? '/memory/transfer/exclude-workspace' : '/memory/transfer/include-workspace';
  const posted = await postTransferPromotionScopeNow(context, requestPath, ids, failureLog);
  if (!posted) {
    await queuePendingTransferPromotionScope(context, action, ids);
  }
}

export async function flushPendingTransferPromotionScope(context: CommandContext): Promise<void> {
  const pending = readPendingTransferPromotionScope(context);
  if (pending.excludeWorkspaceIds.length === 0 && pending.includeWorkspaceIds.length === 0) {
    return;
  }
  const status = context.sidecarManager.getStatus();
  if (status.lifecycle !== 'ready' || !status.port) {
    return;
  }
  const remaining: PendingTransferPromotionScope = {
    excludeWorkspaceIds: [],
    includeWorkspaceIds: [],
  };
  if (pending.excludeWorkspaceIds.length > 0) {
    const excluded = await postTransferPromotionScopeNow(
      context,
      '/memory/transfer/exclude-workspace',
      pending.excludeWorkspaceIds,
      'Trainer kept the project deleted, but could not exclude leftover transfer scenes',
    );
    if (excluded) {
      const demoted = applyExcludedWorkspacesToBootstrap(
        context.getHostState().bootstrap,
        pending.excludeWorkspaceIds,
      );
      if (demoted) {
        await context.patchWorkbenchData(demoted);
      }
    } else {
      remaining.excludeWorkspaceIds = pending.excludeWorkspaceIds;
    }
  }
  if (pending.includeWorkspaceIds.length > 0) {
    const included = await postTransferPromotionScopeNow(
      context,
      '/memory/transfer/include-workspace',
      pending.includeWorkspaceIds,
      'Trainer added the project, but could not restore leftover transfer scenes to the promotion set',
    );
    if (!included) {
      remaining.includeWorkspaceIds = pending.includeWorkspaceIds;
    }
  }
  await writePendingTransferPromotionScope(context, remaining);
}
