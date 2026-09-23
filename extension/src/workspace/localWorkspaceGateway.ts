import * as crypto from 'node:crypto';
import * as vscode from 'vscode';

import type {
  RemoteSearchMatch,
  RemoteSearchRequest,
  RemoteVerificationRequest,
  RemoteVerificationResult,
} from '../../../shared/src/remoteProtocol';
import {
  detectRemoteWorkspaceTypeFromContext,
  type RemoteWorkspaceType,
} from '../../../shared/src/remoteWorkspace';
import type {
  WorkspaceDiagnosticDto,
  WorkspaceDiagnosticsDto,
  WorkspaceEnvironmentDto,
  WorkspaceFindDto,
  WorkspaceFindOptions,
  WorkspaceGatewayCapability,
  WorkspaceGatewayCapabilities as ProtocolWorkspaceGatewayCapabilities,
  WorkspaceHashAlgorithm,
  WorkspaceHashDto,
  WorkspaceListDto,
  WorkspaceReadDto,
  WorkspaceSearchDto,
  WorkspaceSearchOptions,
  WorkspaceStatDto,
  WorkspaceUriDto,
} from '../../../shared/src/remoteProtocol';
import {
  toWorkspaceUri,
  toWorkspaceUriDto,
  workspaceUriToString,
  type WorkspaceUriInput,
} from './remoteUri';
import {
  WorkspaceProtocolGatewayBase,
  type WorkspaceCapabilities,
  type WorkspaceDiagnostic,
  type WorkspaceDirectoryEntry,
  type WorkspaceEnvironment,
  type WorkspaceFileStat,
  type WorkspaceGateway,
  type WorkspaceLocation,
  type WorkspaceReadOptions,
  type WorkspaceSearchMatch,
} from './workspaceGateway';

const MAX_READ_BYTES = 1_000_000;
const MAX_SEARCH_BYTES = 500_000;
const MAX_SEARCH_RESULTS = 200;
const MAX_SEARCH_FILES = 1_000;
const MAX_SEARCH_PREVIEW_CHARS = 400;
const DEFAULT_FIND_RESULTS = 100;
const DEFAULT_READ_CHARS = 80_000;
const DEFAULT_EXCLUDE = '{**/node_modules/**,**/.git/**,**/dist/**,**/.venv/**,**/__pycache__/**}';

type WorkspaceFileType = 'file' | 'directory' | 'unknown';

export class LocalWorkspaceGateway extends WorkspaceProtocolGatewayBase implements WorkspaceGateway {
  get protocolCapabilities(): ProtocolWorkspaceGatewayCapabilities {
    const location = this.location();
    const available = Boolean(location);
    const kind: 'local' | 'remote' = location && isRemoteLocation(location) ? 'remote' : 'local';
    return {
      kind,
      stat: available,
      read: available,
      list: available,
      find: available,
      search: available,
      hash: available,
      diagnostics: available,
      environment: true,
      verify: available,
      ...(vscode.env.remoteName?.trim() ? { remoteName: vscode.env.remoteName.trim() } : {}),
    };
  }

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
        remoteName: vscode.env.remoteName,
      }),
    };
  }

  async capabilities(): Promise<WorkspaceCapabilities> {
    const capabilities = this.protocolCapabilities;
    return {
      kind: capabilities.kind,
      stat: capabilities.stat,
      read: capabilities.read,
      list: capabilities.list,
      find: capabilities.find,
      search: capabilities.search,
      hash: capabilities.hash,
      diagnostics: capabilities.diagnostics,
      environment: capabilities.environment,
      verify: capabilities.verify,
      remoteName: capabilities.remoteName,
      companionAvailable: false,
    };
  }

  async stat(uri: vscode.Uri): Promise<WorkspaceFileStat> {
    const stat = await vscode.workspace.fs.stat(uri);
    return { uri: uri.toString(true), type: stat.type, size: stat.size, mtime: stat.mtime };
  }

  async readFile(uri: vscode.Uri): Promise<Uint8Array> {
    const bytes = await vscode.workspace.fs.readFile(uri);
    if (bytes.byteLength > MAX_READ_BYTES) {
      throw new Error('Workspace file exceeds the read limit.');
    }
    return bytes;
  }

  async readText(uri: vscode.Uri, maxChars = DEFAULT_READ_CHARS): Promise<string> {
    const bytes = await this.readFile(uri);
    if (bytes.includes(0)) throw new Error('Workspace file is binary.');
    return new TextDecoder('utf-8', { fatal: false }).decode(bytes).slice(0, maxChars);
  }

  async listDirectory(uri: vscode.Uri): Promise<WorkspaceDirectoryEntry[]> {
    return (await vscode.workspace.fs.readDirectory(uri)).map(([name, type]) => ({ name, type }));
  }

  async findFiles(query: RemoteSearchRequest): Promise<vscode.Uri[]> {
    const pattern = query.pattern?.trim() || '**/*';
    const exclude = query.exclude?.trim() || DEFAULT_EXCLUDE;
    const limit = boundedInteger(query.max_results, 1, MAX_SEARCH_RESULTS, DEFAULT_FIND_RESULTS);
    return vscode.workspace.findFiles(pattern, exclude, limit);
  }

  async searchText(query: RemoteSearchRequest): Promise<WorkspaceSearchMatch[]> {
    const needle = query.text?.trim();
    if (!needle) throw new Error('Search text is required.');
    const matches: WorkspaceSearchMatch[] = [];
    const files = await this.findFiles(query);
    const foldedNeedle = needle.toLocaleLowerCase();
    for (const uri of files) {
      if (matches.length >= MAX_SEARCH_RESULTS) break;
      let bytes: Uint8Array;
      try {
        bytes = await vscode.workspace.fs.readFile(uri);
      } catch {
        continue;
      }
      if (bytes.byteLength > MAX_SEARCH_BYTES || bytes.includes(0)) continue;
      const lines = new TextDecoder('utf-8', { fatal: false }).decode(bytes).split(/\r?\n/);
      lines.forEach((line, index) => {
        if (matches.length < MAX_SEARCH_RESULTS && line.toLocaleLowerCase().includes(foldedNeedle)) {
          matches.push({ uri: uri.toString(true), line: index + 1, text: line.slice(0, MAX_SEARCH_PREVIEW_CHARS) });
        }
      });
    }
    return matches;
  }

  async hashArtifact(uri: vscode.Uri): Promise<string> {
    return crypto.createHash('sha256').update(await vscode.workspace.fs.readFile(uri)).digest('hex');
  }

  async diagnostics(uri?: vscode.Uri): Promise<WorkspaceDiagnostic[]> {
    const records = uri
      ? [[uri, vscode.languages.getDiagnostics(uri)] as const]
      : vscode.languages.getDiagnostics();
    return records.flatMap(([itemUri, items]) => items.map((item) => ({
      uri: itemUri.toString(true),
      severity: item.severity,
      message: item.message,
      line: item.range.start.line + 1,
      character: item.range.start.character + 1,
    })));
  }

  async environment(): Promise<WorkspaceEnvironment> {
    const location = this.location();
    return {
      remote_name: vscode.env.remoteName || undefined,
      workspace_uri: location?.uri.toString(true),
      os: process.platform,
      arch: process.arch,
      node_version: process.version,
      workspace_name: vscode.workspace.name || undefined,
    };
  }

  async verify(spec: RemoteVerificationRequest): Promise<RemoteVerificationResult> {
    throw new Error(`Local verification must use the existing Trainer test controller: ${spec.command}`);
  }

  async statDto(value: WorkspaceUriInput): Promise<WorkspaceStatDto> {
    const uri = toWorkspaceUri(value);
    const stat = await vscode.workspace.fs.stat(uri);
    return {
      uri: toWorkspaceUriDto(uri),
      type: fileTypeToDto(stat.type),
      size: stat.size,
      ctime: stat.ctime,
      mtime: stat.mtime,
    };
  }

  async readDto(value: WorkspaceUriInput, options: WorkspaceReadOptions = {}): Promise<WorkspaceReadDto> {
    const uri = toWorkspaceUri(value);
    const bytes = await vscode.workspace.fs.readFile(uri);
    const maxBytes = boundedInteger(options.maxBytes, 1, MAX_READ_BYTES, MAX_READ_BYTES);
    const truncated = bytes.byteLength > maxBytes;
    const contentBytes = truncated ? bytes.slice(0, maxBytes) : bytes;
    const binary = contentBytes.includes(0);
    const requestedEncoding = options.encoding ?? 'utf8';
    if (requestedEncoding === 'base64' || binary) {
      return {
        uri: toWorkspaceUriDto(uri),
        content: Buffer.from(contentBytes).toString('base64'),
        encoding: 'base64',
        size: bytes.byteLength,
        truncated,
        binary,
      };
    }
    return {
      uri: toWorkspaceUriDto(uri),
      content: new TextDecoder('utf-8', { fatal: false }).decode(contentBytes),
      encoding: 'utf8',
      size: bytes.byteLength,
      truncated,
      binary: false,
    };
  }

  async listDto(value: WorkspaceUriInput): Promise<WorkspaceListDto> {
    const uri = toWorkspaceUri(value);
    const entries = await vscode.workspace.fs.readDirectory(uri);
    return {
      uri: toWorkspaceUriDto(uri),
      entries: entries.map(([name, type]) => ({
        name,
        uri: toWorkspaceUriDto(vscode.Uri.joinPath(uri, name)),
        type: fileTypeToDto(type),
      })),
    };
  }

  async findDto(options: WorkspaceFindOptions): Promise<WorkspaceFindDto> {
    const include = options.include?.trim();
    if (!include) throw new Error('Find include pattern is required.');
    const exclude = options.exclude?.trim() || DEFAULT_EXCLUDE;
    const maxResults = boundedInteger(options.maxResults, 1, MAX_SEARCH_FILES, DEFAULT_FIND_RESULTS);
    const includePattern: vscode.GlobPattern = options.root
      ? new vscode.RelativePattern(toWorkspaceUri(options.root), include)
      : include;
    const uris = await vscode.workspace.findFiles(includePattern, exclude, maxResults);
    return { uris: uris.map(toWorkspaceUriDto) };
  }

  async searchDto(options: WorkspaceSearchOptions): Promise<WorkspaceSearchDto> {
    const query = options.query.trim();
    if (!query) throw new Error('Search query is required.');
    const maxMatches = boundedInteger(options.maxMatches, 1, MAX_SEARCH_RESULTS, MAX_SEARCH_RESULTS);
    const maxMatchesPerFile = boundedInteger(options.maxMatchesPerFile, 1, maxMatches, maxMatches);
    const files = await this.findDto(options);
    const matches: WorkspaceSearchDto['matches'] = [];
    let filesScanned = 0;
    const foldedQuery = options.caseSensitive ? query : query.toLocaleLowerCase();
    for (const value of files.uris) {
      if (matches.length >= maxMatches) break;
      const uri = toWorkspaceUri(value);
      let bytes: Uint8Array;
      try {
        bytes = await vscode.workspace.fs.readFile(uri);
      } catch {
        continue;
      }
      filesScanned += 1;
      if (bytes.byteLength > MAX_SEARCH_BYTES || bytes.includes(0)) continue;
      const lines = new TextDecoder('utf-8', { fatal: false }).decode(bytes).split(/\r?\n/);
      let fileMatches = 0;
      lines.forEach((line, lineIndex) => {
        if (matches.length >= maxMatches || fileMatches >= maxMatchesPerFile) return;
        const haystack = options.caseSensitive ? line : line.toLocaleLowerCase();
        const column = haystack.indexOf(foldedQuery);
        if (column >= 0) {
          matches.push({
            uri: toWorkspaceUriDto(uri),
            line: lineIndex + 1,
            column: column + 1,
            preview: line.slice(0, MAX_SEARCH_PREVIEW_CHARS),
          });
          fileMatches += 1;
        }
      });
    }
    return { query, matches, filesScanned };
  }

  async hashDto(value: WorkspaceUriInput, algorithm: WorkspaceHashAlgorithm = 'sha256'): Promise<WorkspaceHashDto> {
    if (algorithm !== 'sha256') throw new Error(`Unsupported workspace hash algorithm: ${algorithm}.`);
    const uri = toWorkspaceUri(value);
    const bytes = await vscode.workspace.fs.readFile(uri);
    return {
      uri: toWorkspaceUriDto(uri),
      algorithm,
      hash: crypto.createHash(algorithm).update(bytes).digest('hex'),
      size: bytes.byteLength,
    };
  }

  async diagnosticsDto(value?: WorkspaceUriInput): Promise<WorkspaceDiagnosticsDto> {
    const uri = value === undefined ? undefined : toWorkspaceUri(value);
    if (uri) {
      const diagnosticsForUri = vscode.languages.getDiagnostics(uri);
      return {
        uri: toWorkspaceUriDto(uri),
        diagnostics: diagnosticsForUri.map(toDiagnosticDto),
      };
    }

    const diagnosticsForWorkspace = vscode.languages.getDiagnostics();
    const entries = diagnosticsForWorkspace.flatMap(([itemUri, items]) => items.map((item) => ({
      item,
      uri: itemUri,
    })));
    return {
      uri: toWorkspaceUriDto(this.location()?.uri ?? vscode.Uri.file('.')),
      diagnostics: entries.map(({ item }) => toDiagnosticDto(item)),
    };
  }

  environmentDto(): WorkspaceEnvironmentDto {
    const location = this.location();
    const remote = Boolean(vscode.env.remoteName?.trim()) || Boolean(location && isRemoteLocation(location));
    return {
      kind: remote ? 'remote' : 'local',
      isRemote: remote,
      ...(vscode.env.remoteName?.trim() ? { remoteName: vscode.env.remoteName.trim() } : {}),
      ...(location?.scheme ? { scheme: location.scheme } : {}),
      ...(location?.authority ? { authority: location.authority } : {}),
      workspaceTrusted: vscode.workspace.isTrusted,
      platform: platformName(process.platform),
    };
  }

  async verifyDto(capability: WorkspaceGatewayCapability) {
    return super.verifyDto(capability);
  }
}

function boundedInteger(value: number | undefined, min: number, max: number, fallback: number): number {
  const numeric = typeof value === 'number' && Number.isFinite(value) ? Math.floor(value) : fallback;
  return Math.max(min, Math.min(max, numeric));
}

function fileTypeToDto(type: vscode.FileType): 'file' | 'directory' | 'unknown' {
  if ((type & vscode.FileType.Directory) !== 0) return 'directory';
  if ((type & vscode.FileType.File) !== 0) return 'file';
  return 'unknown';
}

function isRemoteLocation(location: WorkspaceLocation): boolean {
  return Boolean(location.remoteType !== 'local' || location.scheme !== 'file');
}

function toDiagnosticDto(item: vscode.Diagnostic): WorkspaceDiagnosticDto {
  return {
    message: item.message,
    severity: diagnosticSeverity(item.severity),
    ...(item.source ? { source: item.source } : {}),
    ...(normalizeDiagnosticCode(item.code) !== undefined ? { code: normalizeDiagnosticCode(item.code) } : {}),
    range: {
      start: { line: item.range.start.line, character: item.range.start.character },
      end: { line: item.range.end.line, character: item.range.end.character },
    },
  };
}

function normalizeDiagnosticCode(code: vscode.Diagnostic['code']): string | number | undefined {
  return typeof code === 'string' || typeof code === 'number' ? code : undefined;
}

function diagnosticSeverity(severity: vscode.DiagnosticSeverity): WorkspaceDiagnosticDto['severity'] {
  switch (severity) {
    case vscode.DiagnosticSeverity.Error: return 'error';
    case vscode.DiagnosticSeverity.Warning: return 'warning';
    case vscode.DiagnosticSeverity.Information: return 'information';
    case vscode.DiagnosticSeverity.Hint: return 'hint';
    default: return 'unknown';
  }
}

function platformName(platform: string): WorkspaceEnvironmentDto['platform'] {
  if (platform === 'darwin' || platform === 'win32' || platform === 'linux') return platform;
  return 'unknown';
}
