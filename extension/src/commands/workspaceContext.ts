import * as crypto from 'node:crypto';
import type { CommandContext, TrainerRuntimeWorkspaceContext } from '../core/commandContext';
import type { WorkspaceSnapshot } from '../core/types';
import { basenameFs, resolveSovereignWorkspaceRootPath } from '../core/workspaceRoots';

const DEFAULT_WORKSPACE_ID = 'workspace-default';
const DEFAULT_WORKSPACE_NAME = 'Trainer';

export function isRemoteWorkspaceSnapshot(workspace: WorkspaceSnapshot | undefined): boolean {
  return Boolean(
    workspace?.isRemoteWorkspace ||
      workspace?.remoteName?.trim() ||
      (workspace?.remoteType && workspace.remoteType !== 'local') ||
      workspace?.scheme === 'vscode-remote',
  );
}

export function resolveWorkspaceUri(workspace: WorkspaceSnapshot | undefined): string | undefined {
  if (!workspace || !isRemoteWorkspaceSnapshot(workspace)) {
    return undefined;
  }
  const serialized = workspace.workspaceUri?.trim();
  if (serialized && serialized.includes('://')) {
    return serialized;
  }

  const scheme = workspace.scheme?.trim();
  const authority = workspace.authority?.trim() || workspace.remoteName?.trim();
  if (!scheme || !authority) {
    return undefined;
  }
  const displayPath =
    workspace.displayPath?.trim() ||
    workspace.activeWorkspaceRoot?.trim() ||
    workspace.workspaceFolder?.trim();
  if (!displayPath) {
    return undefined;
  }
  const pathPart = displayPath.startsWith('/') ? displayPath : `/${displayPath}`;
  return `${scheme}://${authority}${pathPart}`;
}

/**
 * Return the physical local path for local workspaces and an opaque hash of an
 * authority-qualified URI for remote workspaces. Remote fsPath values are only
 * display/compatibility data, never the workspace identity.
 */
export function resolveWorkspaceIdentity(workspace: WorkspaceSnapshot | undefined): string | undefined {
  if (isRemoteWorkspaceSnapshot(workspace)) {
    const uri = resolveWorkspaceUri(workspace);
    return uri
      ? `remote-${crypto.createHash('sha256').update(uri).digest('hex')}`
      : undefined;
  }
  return resolveSovereignWorkspaceRootPath(workspace);
}

export function getWorkspaceId(context: CommandContext): string {
  return resolveWorkspaceIdentity(context.getHostState().workspace) ?? DEFAULT_WORKSPACE_ID;
}

export function getRuntimeWorkspaceContext(
  context: Pick<CommandContext, 'getHostState'>,
): TrainerRuntimeWorkspaceContext {
  const state = context.getHostState();
  const remote = isRemoteWorkspaceSnapshot(state.workspace);
  const remoteWorkspaceUri = resolveWorkspaceUri(state.workspace);
  const resolvedIdentity = resolveWorkspaceIdentity(state.workspace);
  const workspaceIdentity = remote
    ? resolvedIdentity ?? state.workspace.activeWorkspaceRoot ?? state.workspace.workspaceFolder
    : resolveSovereignWorkspaceRootPath(state.workspace);
  const sovereignWorkspacePath = remote ? undefined : workspaceIdentity;
  const legacyWorkspaceId = remote
    ? workspaceIdentity
    : sovereignWorkspacePath ?? state.workspace.workspaceFolder ?? workspaceIdentity;
  const admission = state.bootstrap.memory?.workspace?.trainerWorkspace;
  const contextId =
    admission?.status === 'managed' && admission.contextId?.trim()
      ? admission.contextId
      : undefined;

  return {
    workspaceId: contextId ?? workspaceIdentity ?? DEFAULT_WORKSPACE_ID,
    canonicalProjectPath: admission?.canonicalProjectPath ?? remoteWorkspaceUri ?? sovereignWorkspacePath,
    rootId: contextId ? admission?.rootId : undefined,
    projectId: contextId ? admission?.projectId : undefined,
    contextId,
    legacyWorkspaceId,
  };
}

export function getRuntimeWorkspaceId(context: Pick<CommandContext, 'getHostState'>): string {
  return getRuntimeWorkspaceContext(context).workspaceId;
}

export function getWorkspaceName(context: CommandContext): string {
  const workspace = context.getHostState().workspace;
  const workspaceFolder = resolveWorkspaceIdentity(workspace);
  if (!workspaceFolder) {
    return DEFAULT_WORKSPACE_NAME;
  }
  const displayPath = isRemoteWorkspaceSnapshot(workspace)
    ? workspace.displayPath ?? resolveWorkspaceUri(workspace) ?? workspaceFolder
    : workspaceFolder;
  return basenameFs(displayPath) || displayPath;
}

export function withWorkspaceQuery(
  pathname: string,
  context: CommandContext,
  workspaceId = getRuntimeWorkspaceId(context),
): string {
  const params = new URLSearchParams();
  params.set('workspace_id', workspaceId);
  const sessionId = context.getSessionId();
  if (sessionId) {
    params.set('session_id', sessionId);
  }
  return `${pathname}?${params.toString()}`;
}
