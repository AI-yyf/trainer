import * as vscode from 'vscode';

import type {
  RemoteCompanionCapabilities,
  RemoteCompanionResponse,
  RemoteDirectoryEntry,
  RemoteDiagnostic,
  RemoteEnvironment,
  RemoteFileStat,
  RemoteSearchMatch,
  RemoteSearchRequest,
  RemoteVerificationRequest,
} from '../../../shared/src/remoteProtocol';
import type {
  WorkspaceDiagnosticDto,
  WorkspaceDiagnosticsDto,
  WorkspaceEnvironmentDto,
  WorkspaceFindDto,
  WorkspaceFindOptions,
  WorkspaceGatewayCapability,
  WorkspaceGatewayCapabilities as ProtocolWorkspaceGatewayCapabilities,
  WorkspaceGatewayRequest,
  WorkspaceGatewayResponse,
  WorkspaceGatewayResult,
  WorkspaceGatewayVerificationResult,
  WorkspaceHashAlgorithm,
  WorkspaceHashDto,
  WorkspaceListDto,
  WorkspaceReadDto,
  WorkspaceReadEncoding,
  WorkspaceSearchDto,
  WorkspaceSearchOptions,
  WorkspaceStatDto,
  WorkspaceUriDto,
} from '../../../shared/src/remoteProtocol';
import type { RemoteWorkspaceType } from '../../../shared/src/remoteWorkspace';
import type { WorkspaceUriInput } from './remoteUri';

export type WorkspaceLocation = {
  uri: vscode.Uri;
  scheme: string;
  authority: string;
  path: string;
  displayPath: string;
  remoteType: RemoteWorkspaceType;
};

/** Legacy companion-facing capability shape. */
export type WorkspaceCapabilities = {
  kind: 'local' | 'remote';
  stat: boolean;
  read: boolean;
  list: boolean;
  find: boolean;
  search: boolean;
  hash: boolean;
  diagnostics: boolean;
  environment: boolean;
  verify: boolean;
  remoteName?: string;
  companionAvailable?: boolean;
};

export type WorkspaceFileStat = RemoteFileStat;
export type WorkspaceDirectoryEntry = RemoteDirectoryEntry;
export type WorkspaceSearchMatch = RemoteSearchMatch;
export type WorkspaceEnvironment = RemoteEnvironment;
export type WorkspaceVerificationRequest = RemoteVerificationRequest;
export type WorkspaceDiagnostic = RemoteDiagnostic;

export type WorkspaceReadOptions = {
  encoding?: WorkspaceReadEncoding;
  maxBytes?: number;
};

/** Strict serializable gateway API used by the local workspace implementation. */
export interface WorkspaceProtocolGateway {
  readonly protocolCapabilities: ProtocolWorkspaceGatewayCapabilities;
  statDto(uri: WorkspaceUriInput): Promise<WorkspaceStatDto>;
  readDto(uri: WorkspaceUriInput, options?: WorkspaceReadOptions): Promise<WorkspaceReadDto>;
  listDto(uri: WorkspaceUriInput): Promise<WorkspaceListDto>;
  findDto(options: WorkspaceFindOptions): Promise<WorkspaceFindDto>;
  searchDto(options: WorkspaceSearchOptions): Promise<WorkspaceSearchDto>;
  hashDto(uri: WorkspaceUriInput, algorithm?: WorkspaceHashAlgorithm): Promise<WorkspaceHashDto>;
  diagnosticsDto(uri?: WorkspaceUriInput): Promise<WorkspaceDiagnosticsDto>;
  environmentDto(): WorkspaceEnvironmentDto;
  verifyDto(capability: WorkspaceGatewayCapability): Promise<WorkspaceGatewayVerificationResult>;
  handle(request: WorkspaceGatewayRequest): Promise<WorkspaceGatewayResponse>;
  request(request: WorkspaceGatewayRequest): Promise<WorkspaceGatewayResponse>;
}

/** Existing companion-facing API retained for the remote extension adapter. */
export interface WorkspaceGateway {
  location(): WorkspaceLocation | undefined;
  capabilities(): Promise<WorkspaceCapabilities>;
  stat(uri: vscode.Uri): Promise<WorkspaceFileStat>;
  readFile(uri: vscode.Uri): Promise<Uint8Array>;
  readText(uri: vscode.Uri, maxChars?: number): Promise<string>;
  listDirectory(uri: vscode.Uri): Promise<WorkspaceDirectoryEntry[]>;
  findFiles(query: RemoteSearchRequest): Promise<vscode.Uri[]>;
  searchText(query: RemoteSearchRequest): Promise<WorkspaceSearchMatch[]>;
  hashArtifact(uri: vscode.Uri): Promise<string>;
  diagnostics(uri?: vscode.Uri): Promise<WorkspaceDiagnostic[]>;
  environment(): Promise<WorkspaceEnvironment>;
  verify(spec: WorkspaceVerificationRequest): Promise<RemoteCompanionResponse['verification'] extends infer T ? NonNullable<T> : never>;
}

export function isRemoteWorkspaceLocation(location: WorkspaceLocation | undefined): boolean {
  return Boolean(location && (location.remoteType !== 'local' || location.scheme !== 'file'));
}

export function asRemoteRequestUri(uri: vscode.Uri): string {
  return uri.toString(true);
}

export function decodeRemoteContent(response: RemoteCompanionResponse): Uint8Array {
  if (!response.ok || typeof response.content_base64 !== 'string') {
    throw new Error(response.error?.detail || 'Remote file content was unavailable.');
  }
  return Uint8Array.from(Buffer.from(response.content_base64, 'base64'));
}

export function assertRemoteResponse(response: RemoteCompanionResponse): RemoteCompanionResponse {
  if (!response.ok) {
    throw new Error(response.error?.detail || 'Remote workspace operation failed.');
  }
  return response;
}

export function companionCapabilitiesToWorkspaceCapabilities(
  capabilities: RemoteCompanionCapabilities,
): WorkspaceCapabilities {
  return {
    kind: 'remote',
    stat: capabilities.capabilities.stat,
    read: capabilities.capabilities.read_file,
    list: capabilities.capabilities.list_directory,
    find: capabilities.capabilities.find_files,
    search: capabilities.capabilities.search_text,
    hash: capabilities.capabilities.hash_artifact,
    diagnostics: capabilities.capabilities.diagnostics,
    environment: capabilities.capabilities.environment,
    verify: capabilities.capabilities.verify,
    remoteName: capabilities.remote_name,
    companionAvailable: capabilities.available,
  };
}

export function workspaceGatewaySuccess<T extends WorkspaceGatewayResult>(
  request: WorkspaceGatewayRequest,
  result: T,
): WorkspaceGatewayResponse<T> {
  return {
    requestId: request.requestId,
    operation: request.operation,
    ok: true,
    result,
  };
}

export function workspaceGatewayFailure(
  request: Pick<WorkspaceGatewayRequest, 'requestId' | 'operation'>,
  code: string,
  message: string,
): WorkspaceGatewayResponse {
  return {
    requestId: request.requestId,
    operation: request.operation,
    ok: false,
    error: { code, message },
  };
}

export abstract class WorkspaceProtocolGatewayBase implements WorkspaceProtocolGateway {
  abstract readonly protocolCapabilities: ProtocolWorkspaceGatewayCapabilities;

  abstract statDto(uri: WorkspaceUriInput): Promise<WorkspaceStatDto>;
  abstract readDto(uri: WorkspaceUriInput, options?: WorkspaceReadOptions): Promise<WorkspaceReadDto>;
  abstract listDto(uri: WorkspaceUriInput): Promise<WorkspaceListDto>;
  abstract findDto(options: WorkspaceFindOptions): Promise<WorkspaceFindDto>;
  abstract searchDto(options: WorkspaceSearchOptions): Promise<WorkspaceSearchDto>;
  abstract hashDto(uri: WorkspaceUriInput, algorithm?: WorkspaceHashAlgorithm): Promise<WorkspaceHashDto>;
  abstract diagnosticsDto(uri?: WorkspaceUriInput): Promise<WorkspaceDiagnosticsDto>;
  abstract environmentDto(): WorkspaceEnvironmentDto;

  async verifyDto(capability: WorkspaceGatewayCapability): Promise<WorkspaceGatewayVerificationResult> {
    const enabled = this.protocolCapabilities[capability];
    return {
      ok: enabled,
      capability,
      kind: this.protocolCapabilities.kind,
      checkedAt: new Date().toISOString(),
      detail: enabled
        ? `${capability} is available on the ${this.protocolCapabilities.kind} workspace gateway.`
        : `${capability} is not available on the ${this.protocolCapabilities.kind} workspace gateway.`,
      ...(enabled ? {} : { errorCode: 'capability_unavailable' }),
    };
  }

  async handle(request: WorkspaceGatewayRequest): Promise<WorkspaceGatewayResponse> {
    const capability = request.operation;
    if (!this.protocolCapabilities[capability]) {
      return workspaceGatewayFailure(
        request,
        'capability_unavailable',
        `Workspace gateway capability is unavailable: ${capability}.`,
      );
    }

    try {
      let result: WorkspaceGatewayResult;
      switch (request.operation) {
        case 'stat':
          result = await this.statDto(request.uri);
          break;
        case 'read':
          result = await this.readDto(request.uri, {
            encoding: request.encoding,
            maxBytes: request.maxBytes,
          });
          break;
        case 'list':
          result = await this.listDto(request.uri);
          break;
        case 'find':
          result = await this.findDto(request);
          break;
        case 'search':
          result = await this.searchDto(request);
          break;
        case 'hash':
          result = await this.hashDto(request.uri, request.algorithm);
          break;
        case 'diagnostics':
          result = await this.diagnosticsDto(request.uri);
          break;
        case 'environment':
          result = this.environmentDto();
          break;
        case 'verify':
          result = await this.verifyDto(request.capability);
          break;
      }
      return workspaceGatewaySuccess(request, result);
    } catch (error) {
      return workspaceGatewayFailure(request, errorCode(error), errorMessage(error));
    }
  }

  request(request: WorkspaceGatewayRequest): Promise<WorkspaceGatewayResponse> {
    return this.handle(request);
  }
}

function errorCode(error: unknown): string {
  if (error && typeof error === 'object' && 'code' in error) {
    const code = (error as { code?: unknown }).code;
    if (typeof code === 'string' && code.trim()) return code.trim();
  }
  return 'workspace_gateway_error';
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return String(error ?? 'Workspace gateway operation failed.');
}

