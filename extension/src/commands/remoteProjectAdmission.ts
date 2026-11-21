import * as vscode from 'vscode';
import type { CommandContext } from '../core/commandContext';
import { normalizeRemoteWorkspaceIdentity, type TrainerManagedProjectIdentity } from '../core/trainerWorkspaceService';
import { resolveCurrentTrainerProjectPath } from '../core/trainerWorkspaceAdmission';
import { hostCommandCopy, resolveHostCommandLanguage } from './hostCommandCopy';
import { resolveWorkspaceIdentity } from './workspaceContext';

/** The UI host observes remote identity; the sidecar only provisions its local brain lane. */
export async function provisionRemoteProject(
  context: CommandContext,
  projectUri: string,
  root: { rootId?: string; canonicalRootPath: string },
  postAdmission: <T>(path: string, body: unknown) => Promise<T>,
): Promise<TrainerManagedProjectIdentity & { agentSessionId: string }> {
  const lang = resolveHostCommandLanguage(context);
  const current = () => resolveCurrentTrainerProjectPath(context.getHostState().workspace);
  const expected = normalizeRemoteWorkspaceIdentity(projectUri);
  const scopeIsCurrent = () => normalizeRemoteWorkspaceIdentity(current() ?? '') === expected &&
    context.trainerWorkspace.getRoot() === root.canonicalRootPath && context.getHostState().workspace.trusted;
  const folders = vscode.workspace.workspaceFolders ?? [];
  const observedRoot =
    folders.find(
      (folder) =>
        folder.uri.scheme === 'vscode-remote' &&
        normalizeRemoteWorkspaceIdentity(folder.uri.toString()) === expected,
    )?.uri ?? folders[0]?.uri;
  if (!observedRoot || observedRoot.scheme !== 'vscode-remote' ||
      normalizeRemoteWorkspaceIdentity(observedRoot.toString()) !== expected || !scopeIsCurrent()) {
    throw new Error(hostCommandCopy(lang, 'remoteAdoptMustUseCurrentAuthority'));
  }
  const caps = await context.workspaceGateway.capabilities();
  if (!caps.companionAvailable || caps.protocolVersion !== 2) {
    throw new Error(hostCommandCopy(lang, 'remoteAdoptCompanionInactive'));
  }
  const [stat, environment] = await Promise.all([
    context.workspaceGateway.stat(observedRoot),
    context.workspaceGateway.environment(),
  ]);
  if ((stat.type & vscode.FileType.Directory) === 0 || !scopeIsCurrent()) {
    throw new Error(hostCommandCopy(lang, 'remoteAdoptDirUnverified'));
  }
  const companionRoot = vscode.Uri.parse(environment.canonical_workspace_uri ?? '', true);
  if (companionRoot.scheme !== 'file') {
    throw new Error(hostCommandCopy(lang, 'remoteAdoptMissingCanonicalDir'));
  }
  const canonicalUri = normalizeRemoteWorkspaceIdentity(observedRoot.with({ path: companionRoot.path }).toString());
  const response = await postAdmission<{
    project_identity?: TrainerManagedProjectIdentity;
    project_provisioning?: { agent_session_id?: string };
  }>('/workspace/remote/adopt', {
    workspace_id: resolveWorkspaceIdentity(context.getHostState().workspace), project_name: vscode.workspace.name,
    root_id: root.rootId, root_path: root.canonicalRootPath,
    workspace_trusted: context.getHostState().workspace.trusted,
    remote_project: { protocol_version: 2, directory: true,
      workspace_uri: expected, canonical_uri: canonicalUri,
      remote_name: context.getHostState().workspace.remoteName,
    },
  });
  if (!scopeIsCurrent() || !response.project_identity ||
      normalizeRemoteWorkspaceIdentity(response.project_identity.canonicalProjectPath) !== canonicalUri ||
      !response.project_provisioning?.agent_session_id) {
    throw new Error(hostCommandCopy(lang, 'remoteAdoptIdentityMismatch'));
  }
  return { ...response.project_identity, agentSessionId: response.project_provisioning.agent_session_id };
}
