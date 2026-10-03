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
  RemoteProcessSpec,
  RemoteSearchMatch,
  RemoteSearchRequest,
} from '../../shared/src/remoteProtocol';
import { createVerificationSessionManager } from './verificationSessions';

const MAX_READ_BYTES = 1_000_000;
const MAX_SEARCH_RESULTS = 200;
const MAX_SEARCH_FILE_BYTES = 500_000;

const verificationSessions = createVerificationSessionManager({
  spawnVerification: spawnVerificationProcess,
  environment: () => environment(),
});

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
  // Losing the companion host means running verifications can no longer be
  // observed: mark them connection_lost and kill their trees so nothing
  // keeps executing unobserved on the remote machine.
  verificationSessions.disposeAll();
}

/**
 * Platform process control for the session manager. `shell: false` always —
 * the spec's executable and args are passed to the OS verbatim.
 */
function spawnVerificationProcess(
  spec: RemoteProcessSpec,
  cwd: string | undefined,
) {
  const detached = process.platform !== 'win32';
  const child = spawn(spec.executable, spec.args, {
    cwd,
    env: spec.env ? { ...process.env, ...spec.env } : process.env,
    shell: false,
    stdio: ['ignore', 'pipe', 'pipe'],
    detached,
  });
  const stdoutChunks: Array<(chunk: string) => void> = [];
  const stderrChunks: Array<(chunk: string) => void> = [];
  child.stdout?.setEncoding('utf8');
  child.stderr?.setEncoding('utf8');
  child.stdout?.on('data', (chunk: string) => {
    for (const listener of stdoutChunks) {
      listener(chunk);
    }
  });
  child.stderr?.on('data', (chunk: string) => {
    for (const listener of stderrChunks) {
      listener(chunk);
    }
  });
  const killTree = () => {
    if (child.pid === undefined || child.exitCode !== null) {
      return;
    }
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore' });
      return;
    }
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      child.kill('SIGTERM');
    }
  };
  return {
    pid: child.pid,
    killTree,
    exited: new Promise<{ code: number | null; error?: string }>((resolve, reject) => {
      child.on('error', (error: Error) => reject(error));
      child.on('close', (code: number | null) => resolve({ code }));
    }),
    onStdout: (listener: (chunk: string) => void) => {
      stdoutChunks.push(listener);
    },
    onStderr: (listener: (chunk: string) => void) => {
      stderrChunks.push(listener);
    },
  };
}

function describeCapabilities(): RemoteCompanionCapabilities {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return {
    protocol_version: 2,
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
  if (!isRecord(value) || value.protocol_version !== 2 || typeof value.operation !== 'string') {
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
      case 'verify_start':
        return {
          ok: true,
          verification_session: await verifyStart(value.spec),
        };
      case 'verify_status': {
        const status = verificationSessions.status(
          requireSessionId(value.session_id),
          boundedInteger(value.stdout_offset, 0, Number.MAX_SAFE_INTEGER, 0),
          boundedInteger(value.stderr_offset, 0, Number.MAX_SAFE_INTEGER, 0),
        );
        return { ok: true, verification_status: status };
      }
      case 'verify_cancel': {
        const status = verificationSessions.cancel(requireSessionId(value.session_id));
        return {
          ok: true,
          verification_cancelled: { session_id: status.session_id, state: status.state },
        };
      }
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

/**
 * Starts a verification session in the remote workspace. The spec's cwd is
 * workspace-validated; args stay structured end to end (protocol v2 has no
 * shell-string path at all).
 */
async function verifyStart(value: unknown): Promise<RemoteCompanionResponse['verification_session']> {
  const rawSpec = isRecord(value) ? value : {};
  const executable = typeof rawSpec.executable === 'string' ? rawSpec.executable.trim() : '';
  const args = Array.isArray(rawSpec.args) ? rawSpec.args.map((entry) => String(entry)) : [];
  if (!executable) {
    throw new Error('Verification requires an explicit executable.');
  }
  const cwdUri = typeof rawSpec.cwd === 'string' && rawSpec.cwd.trim()
    ? await resolveUri(rawSpec.cwd)
    : vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!cwdUri) throw new Error('Verification workspace is unavailable.');

  const spec: RemoteProcessSpec = {
    executable,
    args,
    cwd: cwdUri.fsPath,
    timeout_ms: typeof rawSpec.timeout_ms === 'number' && rawSpec.timeout_ms > 0
      ? Math.floor(rawSpec.timeout_ms)
      : undefined,
    env: isRecord(rawSpec.env)
      ? Object.fromEntries(
          Object.entries(rawSpec.env)
            .filter(([key, entry]) => typeof key === 'string' && typeof entry === 'string')
            .map(([key, entry]) => [key, String(entry)]),
        )
      : undefined,
  };
  const status = await verificationSessions.startSession(spec);
  return { session_id: status.session_id, state: status.state };
}

function requireSessionId(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error('A verification session id is required.');
  }
  return value;
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
