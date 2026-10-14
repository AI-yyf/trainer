import type { CommandContext } from '../core/commandContext';
import type { CommandExecutionResult } from '../core/types';
import { getRuntimeWorkspaceId } from './workspaceContext';

/**
 * Internal bridge commands for the Library's real-folder space.
 *
 * The webview sends one `command/execute` carrying a per-request
 * `operationId`; the host answers with a `library/folders` host message
 * carrying the same id — the same correlation pattern as
 * `training/resourceHandoff`. The browser-preview lane calls the sidecar
 * directly and never reaches these commands.
 */

function readStringField(payload: unknown, key: string): string {
  if (!payload || typeof payload !== 'object') {
    return '';
  }
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === 'string' ? value.trim() : '';
}

async function answerLibraryFolders(
  context: CommandContext,
  operationId: string,
  ok: boolean,
  message: string,
  folders?: unknown,
): Promise<void> {
  if (!operationId) {
    return;
  }
  await context.workbench.postMessage({
    type: 'library/folders',
    payload: {
      operationId,
      ok,
      message,
      ...(folders === undefined ? {} : { folders }),
    },
  });
}

function failureMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function libraryFoldersListCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  const operationId = readStringField(payload, 'operationId');
  try {
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      throw new Error(status.detail ?? 'Sidecar is unavailable.');
    }
    const workspaceId = getRuntimeWorkspaceId(context);
    const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : '';
    const tree = await context.sidecarClient.getJson<unknown>(status.port, `/library/groups${query}`);
    await answerLibraryFolders(context, operationId, true, '', tree);
    return { ok: true };
  } catch (error) {
    const message = failureMessage(error);
    await answerLibraryFolders(context, operationId, false, message);
    return { ok: false, message };
  }
}

async function mutateLibraryFolder(
  context: CommandContext,
  payload: unknown,
  operation: 'create' | 'rename' | 'delete',
): Promise<CommandExecutionResult> {
  const operationId = readStringField(payload, 'operationId');
  const folderPath = readStringField(payload, 'path');
  const nextPath = readStringField(payload, 'new_path') || readStringField(payload, 'newPath');
  if (!folderPath) {
    const message = 'A folder path is required.';
    await answerLibraryFolders(context, operationId, false, message);
    return { ok: false, message };
  }
  if (operation === 'rename' && !nextPath) {
    const message = 'A new folder path is required.';
    await answerLibraryFolders(context, operationId, false, message);
    return { ok: false, message };
  }
  if (!(await context.trustGuard.ensureTrusted('organize the resource library'))) {
    const message = 'Workspace trust is required to organize the resource library.';
    await answerLibraryFolders(context, operationId, false, message);
    return { ok: false, message };
  }
  try {
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      throw new Error(status.detail ?? 'Sidecar is unavailable.');
    }
    const workspaceId = getRuntimeWorkspaceId(context);
    const body = {
      path: folderPath,
      workspace_id: workspaceId,
      session_id: context.getSessionId(),
    };
    if (operation === 'create') {
      await context.sidecarClient.postJson<unknown>(status.port, '/library/groups', body);
    } else if (operation === 'rename') {
      await context.sidecarClient.postJson<unknown>(status.port, '/library/groups/rename', {
        ...body,
        new_path: nextPath,
      });
    } else {
      await context.sidecarClient.deleteJson<unknown>(status.port, '/library/groups', body);
    }
    await answerLibraryFolders(context, operationId, true, '');
    return { ok: true };
  } catch (error) {
    const message = failureMessage(error);
    await answerLibraryFolders(context, operationId, false, message);
    return { ok: false, message };
  }
}

export function libraryFoldersCreateCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  return mutateLibraryFolder(context, payload, 'create');
}

export function libraryFoldersRenameCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  return mutateLibraryFolder(context, payload, 'rename');
}

export function libraryFoldersDeleteCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult> {
  return mutateLibraryFolder(context, payload, 'delete');
}
