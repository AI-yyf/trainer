/**
 * Serializable workspace gateway and remote companion protocol.
 *
 * This module intentionally has no VS Code or Node imports. The local Trainer
 * extension and the workspace companion both map their host APIs to these
 * JSON-safe DTOs.
 */

export type WorkspaceGatewayKind = "local" | "remote";

export type WorkspaceUriDto = {
  scheme: string;
  authority: string;
  path: string;
  query: string;
  fragment: string;
};

/** Alias kept for callers that use the acronym-style DTO spelling. */
export type WorkspaceUriDTO = WorkspaceUriDto;

export type WorkspaceFileType = "file" | "directory" | "unknown";

export type WorkspaceGatewayCapability =
  | "stat"
  | "read"
  | "list"
  | "find"
  | "search"
  | "hash"
  | "diagnostics"
  | "environment"
  | "verify";

export const WORKSPACE_GATEWAY_CAPABILITIES: readonly WorkspaceGatewayCapability[] = [
  "stat",
  "read",
  "list",
  "find",
  "search",
  "hash",
  "diagnostics",
  "environment",
  "verify",
];

export type WorkspaceGatewayCapabilities = {
  kind: WorkspaceGatewayKind;
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
};

export type WorkspaceGatewayCapabilitiesDTO = WorkspaceGatewayCapabilities;

const ALL_WORKSPACE_GATEWAY_CAPABILITIES: Omit<WorkspaceGatewayCapabilities, "kind"> = {
  stat: true,
  read: true,
  list: true,
  find: true,
  search: true,
  hash: true,
  diagnostics: true,
  environment: true,
  verify: true,
};

/** Return a fresh capability object so callers cannot mutate the defaults. */
export function createWorkspaceGatewayCapabilities(
  kind: WorkspaceGatewayKind = "local",
  remoteName?: string,
): WorkspaceGatewayCapabilities {
  return {
    kind,
    ...ALL_WORKSPACE_GATEWAY_CAPABILITIES,
    ...(remoteName ? { remoteName } : {}),
  };
}

export const LOCAL_WORKSPACE_GATEWAY_CAPABILITIES =
  createWorkspaceGatewayCapabilities("local");
export const REMOTE_WORKSPACE_GATEWAY_CAPABILITIES =
  createWorkspaceGatewayCapabilities("remote");
export const LOCAL_WORKSPACE_CAPABILITIES = LOCAL_WORKSPACE_GATEWAY_CAPABILITIES;
export const REMOTE_WORKSPACE_CAPABILITIES = REMOTE_WORKSPACE_GATEWAY_CAPABILITIES;

export type WorkspaceStatDto = {
  uri: WorkspaceUriDto;
  type: WorkspaceFileType;
  size: number;
  ctime: number;
  mtime: number;
};

export type WorkspaceStatDTO = WorkspaceStatDto;

export type WorkspaceReadEncoding = "utf8" | "base64";

export type WorkspaceReadDto = {
  uri: WorkspaceUriDto;
  content: string;
  encoding: WorkspaceReadEncoding;
  size: number;
  truncated: boolean;
  binary: boolean;
};

export type WorkspaceReadDTO = WorkspaceReadDto;

export type WorkspaceListEntryDto = {
  name: string;
  uri: WorkspaceUriDto;
  type: WorkspaceFileType;
};

export type WorkspaceListDto = {
  uri: WorkspaceUriDto;
  entries: WorkspaceListEntryDto[];
};

export type WorkspaceListDTO = WorkspaceListDto;

export type WorkspaceFindOptions = {
  include: string;
  exclude?: string;
  maxResults?: number;
  root?: WorkspaceUriDto;
};

export type WorkspaceFindDto = {
  uris: WorkspaceUriDto[];
};

export type WorkspaceFindDTO = WorkspaceFindDto;

export type WorkspaceSearchOptions = WorkspaceFindOptions & {
  query: string;
  caseSensitive?: boolean;
  maxMatches?: number;
  maxMatchesPerFile?: number;
};

export type WorkspaceSearchMatchDto = {
  uri: WorkspaceUriDto;
  line: number;
  column: number;
  preview: string;
};

export type WorkspaceSearchDto = {
  query: string;
  matches: WorkspaceSearchMatchDto[];
  filesScanned: number;
};

export type WorkspaceSearchDTO = WorkspaceSearchDto;

export type WorkspaceHashAlgorithm = "sha256";

export type WorkspaceHashDto = {
  uri: WorkspaceUriDto;
  algorithm: WorkspaceHashAlgorithm;
  hash: string;
  size: number;
};

export type WorkspaceHashDTO = WorkspaceHashDto;

export type WorkspaceDiagnosticSeverity =
  | "error"
  | "warning"
  | "information"
  | "hint"
  | "unknown";

export type WorkspaceDiagnosticRangeDto = {
  start: { line: number; character: number };
  end: { line: number; character: number };
};

export type WorkspaceDiagnosticDto = {
  message: string;
  severity: WorkspaceDiagnosticSeverity;
  source?: string;
  code?: string | number;
  range: WorkspaceDiagnosticRangeDto;
};

export type WorkspaceDiagnosticsDto = {
  uri: WorkspaceUriDto;
  diagnostics: WorkspaceDiagnosticDto[];
};

export type WorkspaceDiagnosticsDTO = WorkspaceDiagnosticsDto;

export type WorkspaceEnvironmentDto = {
  kind: WorkspaceGatewayKind;
  isRemote: boolean;
  remoteName?: string;
  scheme?: string;
  authority?: string;
  workspaceTrusted: boolean;
  platform: "darwin" | "win32" | "linux" | "unknown";
};

export type WorkspaceEnvironmentDTO = WorkspaceEnvironmentDto;

export type WorkspaceVerificationRequest = {
  requestId: string;
  operation: "verify";
  capability: WorkspaceGatewayCapability;
};

export type WorkspaceStatRequest = {
  requestId: string;
  operation: "stat";
  uri: WorkspaceUriDto;
};

export type WorkspaceReadRequest = {
  requestId: string;
  operation: "read";
  uri: WorkspaceUriDto;
  encoding?: WorkspaceReadEncoding;
  maxBytes?: number;
};

export type WorkspaceListRequest = {
  requestId: string;
  operation: "list";
  uri: WorkspaceUriDto;
};

export type WorkspaceFindRequest = WorkspaceFindOptions & {
  requestId: string;
  operation: "find";
};

export type WorkspaceSearchRequest = WorkspaceSearchOptions & {
  requestId: string;
  operation: "search";
};

export type WorkspaceHashRequest = {
  requestId: string;
  operation: "hash";
  uri: WorkspaceUriDto;
  algorithm?: WorkspaceHashAlgorithm;
};

export type WorkspaceDiagnosticsRequest = {
  requestId: string;
  operation: "diagnostics";
  uri: WorkspaceUriDto;
};

export type WorkspaceEnvironmentRequest = {
  requestId: string;
  operation: "environment";
};

export type WorkspaceGatewayRequest =
  | WorkspaceStatRequest
  | WorkspaceReadRequest
  | WorkspaceListRequest
  | WorkspaceFindRequest
  | WorkspaceSearchRequest
  | WorkspaceHashRequest
  | WorkspaceDiagnosticsRequest
  | WorkspaceEnvironmentRequest
  | WorkspaceVerificationRequest;

export type WorkspaceGatewayRequestDTO = WorkspaceGatewayRequest;

export type WorkspaceGatewayResult =
  | WorkspaceStatDto
  | WorkspaceReadDto
  | WorkspaceListDto
  | WorkspaceFindDto
  | WorkspaceSearchDto
  | WorkspaceHashDto
  | WorkspaceDiagnosticsDto
  | WorkspaceEnvironmentDto
  | WorkspaceGatewayVerificationResult;

export type WorkspaceGatewayError = {
  code: string;
  message: string;
};

export type WorkspaceGatewayResponse<T extends WorkspaceGatewayResult = WorkspaceGatewayResult> = {
  requestId: string;
  operation: WorkspaceGatewayRequest["operation"];
  ok: boolean;
  result?: T;
  error?: WorkspaceGatewayError;
};

export type WorkspaceGatewayResponseDTO<T extends WorkspaceGatewayResult = WorkspaceGatewayResult> =
  WorkspaceGatewayResponse<T>;

export type WorkspaceGatewayVerificationResult = {
  ok: boolean;
  capability: WorkspaceGatewayCapability;
  kind: WorkspaceGatewayKind;
  checkedAt: string;
  detail: string;
  errorCode?: string;
};

export type WorkspaceVerificationResult = WorkspaceGatewayVerificationResult;

/* ------------------------------------------------------------------------- *
 * Remote workspace companion contract
 * ------------------------------------------------------------------------- */

export type RemoteCompanionCapabilityFlags = {
  stat: boolean;
  read_file: boolean;
  list_directory: boolean;
  find_files: boolean;
  search_text: boolean;
  hash_artifact: boolean;
  diagnostics: boolean;
  environment: boolean;
  verify: boolean;
};

export type RemoteCompanionCapabilities = {
  protocol_version: 1;
  available: boolean;
  workspace_uri?: string;
  remote_name?: string;
  capabilities: RemoteCompanionCapabilityFlags;
};

export type RemoteFileStat = {
  uri: string;
  /** VS Code FileType bitmask, kept numeric for JSON compatibility. */
  type: number;
  size: number;
  mtime: number;
};

export type RemoteDirectoryEntry = {
  name: string;
  /** VS Code FileType bitmask, kept numeric for JSON compatibility. */
  type: number;
};

export type RemoteSearchRequest = {
  pattern?: string;
  exclude?: string;
  max_results?: number;
  text?: string;
};

export type RemoteSearchMatch = {
  uri: string;
  line: number;
  text: string;
};

export type RemoteDiagnostic = {
  uri: string;
  severity: number;
  message: string;
  line: number;
  character: number;
};

export type RemoteEnvironment = {
  remote_name?: string;
  workspace_uri?: string;
  os: string;
  arch: string;
  node_version: string;
  workspace_name?: string;
};

export type RemoteVerificationRequest = {
  command: string;
  cwd?: string;
};

export type RemoteVerificationResult = {
  result: "passed" | "failed";
  command: string;
  execution_location: string;
  started_at: string;
  finished_at: string;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  environment: RemoteEnvironment;
};

export type RemoteCompanionOperation =
  | "capabilities"
  | "stat"
  | "read_file"
  | "list_directory"
  | "find_files"
  | "search_text"
  | "hash_artifact"
  | "diagnostics"
  | "environment"
  | "verify";

/** Request envelope used by the companion command bridge. */
export type RemoteCompanionRequest = {
  protocol_version: 1;
  operation: RemoteCompanionOperation;
  uri?: string;
  query?: RemoteSearchRequest;
  spec?: RemoteVerificationRequest;
};

export type RemoteCompanionError = {
  code: string;
  detail: string;
};

/** Response envelope used by the companion command bridge. */
export type RemoteCompanionResponse = {
  ok: boolean;
  error?: RemoteCompanionError;
  capabilities?: RemoteCompanionCapabilities;
  stat?: RemoteFileStat;
  content_base64?: string;
  entries?: RemoteDirectoryEntry[];
  files?: string[];
  matches?: RemoteSearchMatch[];
  artifact_hash?: string;
  diagnostics?: RemoteDiagnostic[];
  environment?: RemoteEnvironment;
  verification?: RemoteVerificationResult;
};
