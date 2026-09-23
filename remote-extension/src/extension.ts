import * as crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import * as path from 'node:path';
import * as vscode from 'vscode';

import type {
  RemoteCompanionCapabilities,
  RemoteCompanionRequest,
  RemoteCompanionResponse,
  RemoteDiagnostic,
  RemoteDirectoryEntry,
  RemoteEnvironment,
  RemoteFileStat,
  RemoteSearchMatch,
  RemoteSearchRequest,
  RemoteVerificationRequest,
} from '../../shared/src/remoteProtocol';

const MAX_READ_BYTES = 1_000_000;
const MAX_SEARCH_RESULTS = 200;
const MAX_SEARCH_FILE_BYTES = 500_000;

export function activate(context: vscode.ExtensionContext): void {
  const capabilitiesCommand = vscode.commands.registerCommand(
    'trainer.remote.capabilities',
    () => describeCapabilities(),
  );
  const requestCommand = vscode.commands.registerCommand(
    'trainer.remote.request',
    (request: unknown) => handleRequest(request),
  );
  context.subscriptions.push(capabilitiesCommand, requestCommand);
}

export function deactivate(): void {
  // The companion has no process or credential state to dispose.
}

function describeCapabilities(): RemoteCompanionCapabilities {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return {
    protocol_version: 1,
    available: Boolean(folder),
    workspace_uri: folder?.uri.toString(),
    remote_name: vscode.env.remoteName || undefined,
    capabilities: {
      stat: Boolean(folder),
      read_file: Boolean(folder),
      list_directory: Boolean(folder),
      find_files: Boolean(folder),
      search_text: Boolean(folder),
      hash_artifact: Boolean(folder),
      diagnostics: Boolean(folder),
      environment: Boolean(folder),
      verify: Boolean(folder),
    },
  };
}

async function handleRequest(value: unknown): Promise<RemoteCompanionResponse> {
  if (!isRecord(value) || value.protocol_version !== 1 || typeof value.operation !== 'string') {
    return failure('invalid_request', 'Remote request has an invalid protocol shape.');
  }
  try {
    switch (value.operation) {
      case 'capabilities':
        return { ok: true, capabilities: describeCapabilities() };
      case 'stat':
        return { ok: true, stat: await statUri(value.uri) };
      case 'read_file':
        return { ok: true, content_base64: encode(await readFile(value.uri)) };
      case 'list_directory':
        return { ok: true, entries: await listDirectory(value.uri) };
      case 'find_files':
        return { ok: true, files: await findFiles(value.query) };
      case 'search_text':
        return { ok: true, matches: await searchText(value.query) };
      case 'hash_artifact':
        return { ok: true, artifact_hash: await hashArtifact(value.uri) };
      case 'diagnostics':
        return { ok: true, diagnostics: diagnostics(value.uri) };
      case 'environment':
        return { ok: true, environment: await environment() };
      case 'verify':
        return { ok: true, verification: await verify(value.spec) };
      default:
        return failure('unsupported_operation', `Unsupported remote operation: ${value.operation}.`);
    }
  } catch (error) {
    return failure('operation_failed', error instanceof Error ? error.message : String(error));
  }
}

async function resolveUri(value: unknown): Promise<vscode.Uri> {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error('A workspace URI is required.');
  }
  const uri = vscode.Uri.parse(value, true);
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    throw new Error('No workspace folder is open.');
  }
  if (uri.scheme !== folder.uri.scheme || uri.authority !== folder.uri.authority) {
    throw new Error('Remote request URI belongs to a different workspace authority.');
  }
  const relative = path.posix.relative(folder.uri.path, uri.path);
  if (relative.startsWith('../') || relative === '..' || path.posix.isAbsolute(relative)) {
    throw new Error('Remote request URI is outside the active workspace.');
  }
  return uri;
}

async function statUri(value: unknown): Promise<RemoteFileStat> {
  const uri = await resolveUri(value);
  const stat = await vscode.workspace.fs.stat(uri);
  return { uri: uri.toString(), type: stat.type, size: stat.size, mtime: stat.mtime };
}

async function readFile(value: unknown): Promise<Uint8Array> {
  const uri = await resolveUri(value);
  const bytes = await vscode.workspace.fs.readFile(uri);
  if (bytes.byteLength > MAX_READ_BYTES) {
    throw new Error(`Remote file exceeds the ${MAX_READ_BYTES} byte limit.`);
  }
  return bytes;
}

async function listDirectory(value: unknown): Promise<RemoteDirectoryEntry[]> {
  const uri = await resolveUri(value);
  const entries = await vscode.workspace.fs.readDirectory(uri);
  return entries.map(([name, type]) => ({ name, type }));
}

async function findFiles(value: unknown): Promise<string[]> {
  const query = isRecord(value) ? value : {};
  const pattern = typeof query.pattern === 'string' && query.pattern.trim() ? query.pattern : '**/*';
  const exclude = typeof query.exclude === 'string' ? query.exclude : '{**/node_modules/**,**/.git/**,**/dist/**}';
  const maxResults = boundedInteger(query.max_results, 1, MAX_SEARCH_RESULTS, 100);
  const files = await vscode.workspace.findFiles(pattern, exclude, maxResults);
  return files.map((uri) => uri.toString());
}

async function searchText(value: unknown): Promise<RemoteSearchMatch[]> {
  const query = isRecord(value) ? value : {};
  const needle = typeof query.text === 'string' ? query.text : '';
  if (!needle.trim()) {
    throw new Error('A non-empty search text is required.');
  }
  const files = await findFiles(query);
  const matches: RemoteSearchMatch[] = [];
  for (const serializedUri of files) {
    if (matches.length >= MAX_SEARCH_RESULTS) break;
    const uri = vscode.Uri.parse(serializedUri, true);
    let bytes: Uint8Array;
    try {
      bytes = await vscode.workspace.fs.readFile(uri);
    } catch {
      continue;
    }
    if (bytes.byteLength > MAX_SEARCH_FILE_BYTES || bytes.includes(0)) continue;
    const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
    const lines = text.split(/\r?\n/);
    lines.forEach((line, index) => {
      if (matches.length < MAX_SEARCH_RESULTS && line.toLocaleLowerCase().includes(needle.toLocaleLowerCase())) {
        matches.push({ uri: serializedUri, line: index + 1, text: line.slice(0, 400) });
      }
    });
  }
  return matches;
}

async function hashArtifact(value: unknown): Promise<string> {
  const bytes = await readFile(value);
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function diagnostics(value: unknown): RemoteDiagnostic[] {
  const uri = typeof value === 'string' && value.trim() ? vscode.Uri.parse(value, true) : undefined;
  const records: Array<[vscode.Uri, vscode.Diagnostic[]]> = uri
    ? [[uri, vscode.languages.getDiagnostics(uri)]]
    : vscode.languages.getDiagnostics();
  return records.flatMap(([itemUri, items]) => items.map((item) => ({
    uri: itemUri.toString(),
    severity: item.severity,
    message: item.message,
    line: item.range.start.line + 1,
    character: item.range.start.character + 1,
  })));
}

async function environment(): Promise<RemoteEnvironment> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return {
    remote_name: vscode.env.remoteName || undefined,
    workspace_uri: folder?.uri.toString(),
    os: process.platform,
    arch: process.arch,
    node_version: process.version,
    workspace_name: vscode.workspace.name || undefined,
  };
}

async function verify(value: unknown): Promise<RemoteCompanionResponse['verification']> {
  const spec = isRecord(value) ? value : {};
  const command = typeof spec.command === 'string' ? spec.command.trim() : '';
  if (!command) {
    throw new Error('Verification requires an explicit command.');
  }
  const cwdUri = typeof spec.cwd === 'string' && spec.cwd.trim()
    ? await resolveUri(spec.cwd)
    : vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!cwdUri) throw new Error('Verification workspace is unavailable.');
  const cwd = cwdUri.fsPath;
  const [executable, ...args] = command.split(/\s+/);
  const startedAt = new Date().toISOString();
  const result = await new Promise<{ code: number | null; stdout: string; stderr: string }>((resolve, reject) => {
    const child = spawn(executable, args, { cwd, shell: false });
    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
    child.stderr?.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });
    child.on('error', reject);
    child.on('close', (code: number | null) => resolve({ code, stdout, stderr }));
  });
  return {
    result: result.code === 0 ? 'passed' : 'failed',
    command,
    execution_location: vscode.env.remoteName ? `remote:${vscode.env.remoteName}` : 'workspace',
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    exit_code: result.code,
    stdout: result.stdout.slice(0, 20_000),
    stderr: result.stderr.slice(0, 20_000),
    environment: await environment(),
  };
}

function encode(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString('base64');
}

function boundedInteger(value: unknown, min: number, max: number, fallback: number): number {
  const numeric = typeof value === 'number' && Number.isFinite(value) ? Math.floor(value) : fallback;
  return Math.max(min, Math.min(max, numeric));
}

function failure(code: string, detail: string): RemoteCompanionResponse {
  return { ok: false, error: { code, detail } };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
