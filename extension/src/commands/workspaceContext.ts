import type { CommandContext, TrainerRuntimeWorkspaceContext } from '../core/commandContext';
import { basenameFs, resolveSovereignWorkspaceRootPath } from '../core/workspaceRoots';

const DEFAULT_WORKSPACE_ID = 'workspace-default';
const DEFAULT_WORKSPACE_NAME = 'Trainer';

export function getWorkspaceId(context: CommandContext): string {
  return resolveSovereignWorkspaceRootPath(context.getHostState().workspace) ?? DEFAULT_WORKSPACE_ID;
}

export function getRuntimeWorkspaceContext(
  context: Pick<CommandContext, 'getHostState'>,
): TrainerRuntimeWorkspaceContext {
  const state = context.getHostState();
  const sovereignWorkspacePath = resolveSovereignWorkspaceRootPath(state.workspace);
  const legacyWorkspaceId = sovereignWorkspacePath ?? state.workspace.workspaceFolder;
  const admission = state.bootstrap.memory?.workspace?.trainerWorkspace;
  const contextId =
    admission?.status === 'managed' && admission.contextId?.trim()
      ? admission.contextId
      : undefined;

  return {
    workspaceId: contextId ?? sovereignWorkspacePath ?? DEFAULT_WORKSPACE_ID,
    canonicalProjectPath: admission?.canonicalProjectPath ?? sovereignWorkspacePath,
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
  const workspaceFolder = resolveSovereignWorkspaceRootPath(context.getHostState().workspace);
  if (!workspaceFolder) {
    return DEFAULT_WORKSPACE_NAME;
  }
  return basenameFs(workspaceFolder) || workspaceFolder;
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
