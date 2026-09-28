import * as vscode from 'vscode';

import type {
  RemoteCompanionCapabilities,
  RemoteCompanionRequest,
  RemoteCompanionResponse,
  RemoteProcessSpec,
  RemoteProcessState,
  RemoteSearchRequest,
  RemoteVerificationResult,
  RemoteVerificationSessionRef,
  RemoteVerificationStatus,
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
      if (!response || response.protocol_version !== 2) {
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

  async verifyStart(spec: RemoteProcessSpec): Promise<RemoteVerificationSessionRef> {
    const response = await this.request({ operation: 'verify_start', spec });
    if (!response.verification_session) {
      throw new Error('Remote companion omitted the verification session handle.');
    }
    return response.verification_session;
  }

  async verifyStatus(
    sessionId: string,
    stdoutOffset = 0,
    stderrOffset = 0,
  ): Promise<RemoteVerificationStatus> {
    const response = await this.request({
      operation: 'verify_status',
      session_id: sessionId,
      stdout_offset: stdoutOffset,
      stderr_offset: stderrOffset,
    });
    if (!response.verification_status) {
      throw new Error('Remote companion omitted the verification status.');
    }
    return response.verification_status;
  }

  async verifyCancel(sessionId: string): Promise<RemoteVerificationSessionRef> {
    const response = await this.request({ operation: 'verify_cancel', session_id: sessionId });
    if (!response.verification_cancelled) {
      throw new Error('Remote companion omitted the cancellation handle.');
    }
    return response.verification_cancelled;
  }

  /**
   * Runs one verification spec to a terminal state, streaming output chunks
   * through `onChunk` and honouring `signal` (cancel → the session is
   * cancelled on the companion, the result reports `cancelled` — never a
   * fabricated pass/fail).
   */
  async runVerification(
    spec: RemoteProcessSpec,
    hooks: {
      onChunk?: (chunk: { stream: 'stdout' | 'stderr'; text: string }) => void;
      signal?: { aborted: boolean };
      pollIntervalMs?: number;
    } = {},
  ): Promise<RemoteVerificationResult> {
    const session = await this.verifyStart(spec);
    const pollIntervalMs = hooks.pollIntervalMs ?? 400;
    let stdoutOffset = 0;
    let stderrOffset = 0;
    let stdout = '';
    let stderr = '';
    for (;;) {
      if (hooks.signal?.aborted) {
        const cancelled = await this.verifyCancel(session.session_id);
        return this.composeResult(cancelled.session_id, cancelled.state, spec, stdout, stderr);
      }
      let status: RemoteVerificationStatus;
      try {
        status = await this.verifyStatus(session.session_id, stdoutOffset, stderrOffset);
      } catch (error) {
        // Bridge hiccup: report unknown outcome instead of inventing a result.
        return this.composeResult(
          session.session_id,
          'connection_lost' satisfies RemoteProcessState,
          spec,
          stdout,
          stderr,
        );
      }
      if (status.stdout_chunk) {
        hooks.onChunk?.({ stream: 'stdout', text: status.stdout_chunk });
        stdoutOffset += status.stdout_chunk.length;
        stdout = (stdout + status.stdout_chunk).slice(-100_000);
      }
      if (status.stderr_chunk) {
        hooks.onChunk?.({ stream: 'stderr', text: status.stderr_chunk });
        stderrOffset += status.stderr_chunk.length;
        stderr = (stderr + status.stderr_chunk).slice(-100_000);
      }
      if (status.state !== 'running') {
        return {
          ...(status.result ? { result: status.result } : {}),
          spec,
          state: status.state,
          execution_location: this.executionLocation(),
          started_at: status.started_at,
          finished_at: status.finished_at ?? new Date().toISOString(),
          exit_code: status.exit_code ?? null,
          stdout,
          stderr,
          environment: status.environment,
        };
      }
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }
  }

  private executionLocation(): string {
    const remoteName = this.remoteName || vscode.env.remoteName;
    return remoteName ? `remote:${remoteName}` : 'workspace';
  }

  private composeResult(
    sessionId: string,
    state: RemoteProcessState,
    spec: RemoteProcessSpec,
    stdout: string,
    stderr: string,
  ): RemoteVerificationResult {
    void sessionId;
    // No `result` field: an interrupted run has no outcome evidence.
    return {
      spec,
      state,
      execution_location: this.executionLocation(),
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
      exit_code: null,
      stdout,
      stderr,
      environment: {
        os: process.platform,
        arch: process.arch,
        node_version: process.version,
      },
    };
  }

  private async request(
    request: Omit<RemoteCompanionRequest, 'protocol_version'>,
  ): Promise<RemoteCompanionResponse> {
    const response = await vscode.commands.executeCommand<RemoteCompanionResponse>(
      COMPANION_REQUEST_COMMAND,
      { protocol_version: 2, ...request },
    );
    return assertRemoteResponse(response);
  }
}
