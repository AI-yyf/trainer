import * as vscode from 'vscode';

import type {
  RemoteCompanionCapabilities,
  RemoteCompanionRequest,
  RemoteCompanionResponse,
  RemoteSearchRequest,
  RemoteVerificationRequest,
} from '../../../shared/src/remoteProtocol';
import { detectRemoteWorkspaceTypeFromContext } from '../../../shared/src/remoteWorkspace';
import {
  assertRemoteResponse,
  companionCapabilitiesToWorkspaceCapabilities,
  decodeRemoteContent,
  type WorkspaceCapabilities,
  type WorkspaceDiagnostic,
  type WorkspaceDirectoryEntry,
  type WorkspaceEnvironment,
  type WorkspaceFileStat,
  type WorkspaceGateway,
  type WorkspaceLocation,
  type WorkspaceSearchMatch,
} from './workspaceGateway';

const COMPANION_CAPABILITIES_COMMAND = 'trainer.remote.capabilities';
const COMPANION_REQUEST_COMMAND = 'trainer.remote.request';

export class RemoteWorkspaceGateway implements WorkspaceGateway {
  constructor(private readonly remoteName?: string) {}

  location(): WorkspaceLocation | undefined {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) return undefined;
    return {
      uri: folder.uri,
      scheme: folder.uri.scheme,
      authority: folder.uri.authority,
      path: folder.uri.path,
      displayPath: folder.uri.fsPath || folder.uri.path,
      remoteType: detectRemoteWorkspaceTypeFromContext({
        uri: { scheme: folder.uri.scheme, authority: folder.uri.authority },
        remoteName: this.remoteName || vscode.env.remoteName,
      }),
    };
  }

  async capabilities(): Promise<WorkspaceCapabilities> {
    try {
      const response = await vscode.commands.executeCommand<RemoteCompanionCapabilities>(
        COMPANION_CAPABILITIES_COMMAND,
      );
      if (!response || response.protocol_version !== 1) {
        throw new Error('Remote companion returned an invalid capability response.');
      }
      return companionCapabilitiesToWorkspaceCapabilities(response);
    } catch {
      return {
        kind: 'remote',
        stat: true,
        read: true,
        list: false,
        find: false,
        search: false,
        hash: false,
        diagnostics: false,
        environment: false,
        verify: false,
        remoteName: this.remoteName || vscode.env.remoteName || undefined,
        companionAvailable: false,
      };
    }
  }

  async stat(uri: vscode.Uri): Promise<WorkspaceFileStat> {
    const response = await this.request({ operation: 'stat', uri: uri.toString(true) });
    if (!response.stat) throw new Error('Remote companion omitted file stat.');
    return response.stat;
  }

  async readFile(uri: vscode.Uri): Promise<Uint8Array> {
    return decodeRemoteContent(await this.request({ operation: 'read_file', uri: uri.toString(true) }));
  }

  async readText(uri: vscode.Uri, maxChars = 80_000): Promise<string> {
    const bytes = await this.readFile(uri);
    if (bytes.includes(0)) throw new Error('Workspace file is binary.');
    return new TextDecoder('utf-8', { fatal: false }).decode(bytes).slice(0, maxChars);
  }

  async listDirectory(uri: vscode.Uri): Promise<WorkspaceDirectoryEntry[]> {
    const response = await this.request({ operation: 'list_directory', uri: uri.toString(true) });
    return response.entries ?? [];
  }

  async findFiles(query: RemoteSearchRequest): Promise<vscode.Uri[]> {
    const response = await this.request({ operation: 'find_files', query });
    return (response.files ?? []).map((value) => vscode.Uri.parse(value, true));
  }

  async searchText(query: RemoteSearchRequest): Promise<WorkspaceSearchMatch[]> {
    const response = await this.request({ operation: 'search_text', query });
    return response.matches ?? [];
  }

  async hashArtifact(uri: vscode.Uri): Promise<string> {
    const response = await this.request({ operation: 'hash_artifact', uri: uri.toString(true) });
    if (!response.artifact_hash) throw new Error('Remote companion omitted artifact hash.');
    return response.artifact_hash;
  }

  async diagnostics(uri?: vscode.Uri): Promise<WorkspaceDiagnostic[]> {
    const response = await this.request({ operation: 'diagnostics', uri: uri?.toString(true) });
    return response.diagnostics ?? [];
  }

  async environment(): Promise<WorkspaceEnvironment> {
    const response = await this.request({ operation: 'environment' });
    if (!response.environment) throw new Error('Remote companion omitted environment.');
    return response.environment;
  }

  async verify(spec: RemoteVerificationRequest): Promise<NonNullable<ReturnType<WorkspaceGateway['verify']> extends Promise<infer T> ? T : never>> {
    const response = await this.request({ operation: 'verify', spec });
    if (!response.verification) throw new Error('Remote companion omitted verification result.');
    return response.verification;
  }

  private async request(
    request: Omit<RemoteCompanionRequest, 'protocol_version'>,
  ): Promise<RemoteCompanionResponse> {
    const response = await vscode.commands.executeCommand<RemoteCompanionResponse>(
      COMPANION_REQUEST_COMMAND,
      { protocol_version: 1, ...request },
    );
    return assertRemoteResponse(response);
  }
}
