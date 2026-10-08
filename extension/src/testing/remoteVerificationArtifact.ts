import * as path from 'node:path';
import * as vscode from 'vscode';
import type { RemoteVerificationArtifact } from '../../../shared/src/trainingVerification';
import type { RemoteVerificationResult } from '../../../shared/src/remoteProtocol';
import type { CommandContext } from '../core/commandContext';
import { normalizeRemoteWorkspaceIdentity } from '../core/trainerWorkspaceService';
import { getRuntimeWorkspaceContext, resolveWorkspaceUri } from '../commands/workspaceContext';

export interface CapturedRemoteArtifact {
  uri: vscode.Uri;
  workspaceUri: string;
  artifactUri: string;
  sha256: string;
}
const SHA256 = /^[a-f0-9]{64}$/;

/** Execution scope is independent of admission/evidence or temporary hash availability. */
export async function assertRemoteVerificationFileScope(context: CommandContext, uri: vscode.Uri): Promise<void> {
  const observed = resolveWorkspaceUri(context.getHostState().workspace);
  if (!observed) throw new Error('The current remote workspace is unknown.');
  const root = vscode.Uri.parse(observed, true);
  const relative = path.posix.relative(root.path, uri.path);
  if (uri.scheme !== root.scheme || uri.authority !== root.authority || uri.query || uri.fragment ||
      !relative || relative === '..' || relative.startsWith('../') || path.posix.isAbsolute(relative)) {
    throw new Error('The practice file belongs to another project or remote authority.');
  }
  // Companion stat enforces realpath containment, including file symlink targets.
  const stat = await context.workspaceGateway.stat(uri);
  if ((stat.type & vscode.FileType.File) === 0 || (stat.type & vscode.FileType.Directory) !== 0) {
    throw new Error('The practice file could not be verified inside this remote project.');
  }
  const admission = getRuntimeWorkspaceContext(context);
  if (admission.contextId && admission.canonicalProjectPath) {
    const environment = await context.workspaceGateway.environment();
    const canonical = vscode.Uri.parse(environment.canonical_workspace_uri ?? '', true);
    if (canonical.scheme !== 'file' || normalizeRemoteWorkspaceIdentity(root.with({ path: canonical.path }).toString()) !==
        normalizeRemoteWorkspaceIdentity(admission.canonicalProjectPath)) {
      throw new Error('The canonical remote project no longer matches the admitted identity.');
    }
  }
}

/** Hash the selected file through the Companion, within the admitted project. */
export async function captureRemoteVerificationArtifact(
  context: CommandContext, artifactUri?: string | vscode.Uri,
): Promise<CapturedRemoteArtifact> {
  const scope = getRuntimeWorkspaceContext(context);
  const observed = resolveWorkspaceUri(context.getHostState().workspace);
  if (!scope.contextId || !scope.canonicalProjectPath || !observed || !artifactUri) {
    throw new Error('Remote evidence requires an admitted project and a selected artifact.');
  }
  const uri = typeof artifactUri === 'string' ? vscode.Uri.parse(artifactUri, true) : artifactUri;
  const root = vscode.Uri.parse(observed, true);
  if (uri.scheme !== root.scheme || uri.authority !== root.authority || uri.query || uri.fragment) {
    throw new Error('The verification artifact belongs to another remote authority.');
  }
  const relative = path.posix.relative(root.path, uri.path);
  if (!relative || relative === '..' || relative.startsWith('../') || path.posix.isAbsolute(relative)) {
    throw new Error('The verification artifact is outside the current project.');
  }
  const environment = await context.workspaceGateway.environment();
  const canonicalRoot = vscode.Uri.parse(environment.canonical_workspace_uri ?? '', true);
  if (canonicalRoot.scheme !== 'file') throw new Error('The remote canonical directory is unknown.');
  const workspaceUri = normalizeRemoteWorkspaceIdentity(root.with({ path: canonicalRoot.path }).toString());
  if (workspaceUri !== normalizeRemoteWorkspaceIdentity(scope.canonicalProjectPath)) {
    throw new Error('The remote canonical directory no longer matches the admitted project.');
  }
  const sha256 = await context.workspaceGateway.hashArtifact(uri);
  if (!SHA256.test(sha256)) throw new Error('The remote artifact hash is unknown.');
  return { uri, workspaceUri, artifactUri: normalizeRemoteWorkspaceIdentity(
    root.with({ path: path.posix.join(canonicalRoot.path, relative) }).toString()), sha256 };
}

export async function finishRemoteVerificationArtifact(
  context: CommandContext, captured: CapturedRemoteArtifact | undefined,
  companionSessionId: string, result: RemoteVerificationResult,
): Promise<RemoteVerificationArtifact | undefined> {
  if (!captured || !companionSessionId || result.state !== 'completed' ||
      typeof result.exit_code !== 'number' || typeof result.execution_location !== 'string' ||
      !result.execution_location.startsWith('remote:')) return undefined;
  const scope = getRuntimeWorkspaceContext(context);
  if (!scope.contextId || !scope.canonicalProjectPath ||
      normalizeRemoteWorkspaceIdentity(scope.canonicalProjectPath) !== captured.workspaceUri) return undefined;
  const sha256 = await context.workspaceGateway.hashArtifact(captured.uri);
  if (!SHA256.test(sha256) || sha256 !== captured.sha256) return undefined;
  const observed = resolveWorkspaceUri(context.getHostState().workspace);
  if (!observed) return undefined;
  const root = vscode.Uri.parse(observed, true);
  const environment = await context.workspaceGateway.environment();
  const canonicalRoot = vscode.Uri.parse(environment.canonical_workspace_uri ?? '', true);
  if (canonicalRoot.scheme !== 'file' || normalizeRemoteWorkspaceIdentity(
    root.with({ path: canonicalRoot.path }).toString()) !== captured.workspaceUri) return undefined;
  return { workspace_uri: captured.workspaceUri, artifact_uri: captured.artifactUri, sha256,
    companion_session_id: companionSessionId, execution_location: 'remote' };
}
