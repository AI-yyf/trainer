import * as vscode from 'vscode';
import * as path from 'node:path';
import { RemoteWorkspaceGateway } from '../workspace/remoteWorkspaceGateway';
import type { WorkspaceGateway } from '../workspace/workspaceGateway';

export type WorkspaceFileSnapshot = {
  is_remote: boolean;
  root_uri: string;
  files: Array<{ path: string; size?: number }>;
  contents: Record<string, { content: string; language_id?: string }>;
};

const LIST_LIMIT_LOCAL = 80;
const LIST_LIMIT_REMOTE = 200;
const CONTENT_FILE_LIMIT_LOCAL = 10;
const CONTENT_FILE_LIMIT_REMOTE = 48;
const CONTENT_CHAR_LIMIT_LOCAL = 80_000;
const CONTENT_CHAR_LIMIT_REMOTE = 400_000;
const PER_FILE_CHAR_LIMIT = 24_000;
const EXCLUDE_GLOB = '{**/node_modules/**,**/.git/**,**/dist/**,**/.venv/**,**/__pycache__/**}';
const INCLUDE_GLOB =
  '**/*.{py,ts,tsx,js,jsx,mjs,cjs,go,rs,java,kt,swift,c,cc,cpp,h,hpp,md,json,toml,yml,yaml,txt}';
const PRIORITY_BASENAMES = new Set([
  'readme.md',
  'readme',
  'setup.py',
  'pyproject.toml',
  'requirements.txt',
  'package.json',
  'cargo.toml',
  'go.mod',
  'cmakelists.txt',
  'environment.yml',
]);

const pendingExtraPaths = new WeakMap<object, string[]>();

export function rememberRequestedWorkspaceFiles(
  owner: object,
  paths: Iterable<unknown> | undefined,
): void {
  const next = [...(pendingExtraPaths.get(owner) ?? [])];
  for (const value of paths ?? []) {
    const cleaned = String(value ?? '')
      .replace(/\\/g, '/')
      .replace(/^\.\//, '')
      .trim();
    if (cleaned && !next.includes(cleaned)) {
      next.push(cleaned);
    }
  }
  if (next.length) {
    pendingExtraPaths.set(owner, next);
  }
}

export function consumeRequestedWorkspaceFiles(owner: object): string[] {
  const paths = pendingExtraPaths.get(owner) ?? [];
  pendingExtraPaths.delete(owner);
  return paths;
}

export function noteRequestedWorkspaceFileToolResult(
  owner: object,
  toolName: unknown,
  result: unknown,
): void {
  const name = String(toolName ?? '').trim();
  if (name !== 'read_workspace_file' && name !== 'import_workspace_file') {
    return;
  }
  if (!result || typeof result !== 'object') {
    return;
  }
  const record = result as { error?: unknown; path?: unknown; listed?: unknown };
  if (String(record.error ?? '') !== 'snapshot_content_unavailable') {
    return;
  }
  rememberRequestedWorkspaceFiles(owner, [record.path]);
}

export function noteRequestedWorkspaceFilesFromSessionResponse(
  owner: object,
  response: unknown,
): void {
  if (!response || typeof response !== 'object') {
    return;
  }
  const record = response as {
    requestedWorkspaceFiles?: unknown;
    requested_workspace_files?: unknown;
  };
  const listed = record.requestedWorkspaceFiles ?? record.requested_workspace_files;
  if (Array.isArray(listed)) {
    rememberRequestedWorkspaceFiles(owner, listed);
  }
}

export async function buildWorkspaceFileSnapshot(
  owner?: object,
): Promise<WorkspaceFileSnapshot | undefined> {
  const folder = vscode.workspace?.workspaceFolders?.[0];
  if (!folder) {
    return undefined;
  }
  const extraPaths = owner ? consumeRequestedWorkspaceFiles(owner) : [];
  const isRemote =
    Boolean(vscode.env?.remoteName?.trim()) || folder.uri.scheme === 'vscode-remote';
  const listLimit = isRemote ? LIST_LIMIT_REMOTE : LIST_LIMIT_LOCAL;
  const gateway = isRemote ? remoteSnapshotGateway(owner) : undefined;
  let listed: vscode.Uri[];
  if (gateway) {
    try {
      const caps = await gateway.capabilities();
      if (!caps.companionAvailable || caps.protocolVersion !== 2) {
        throw new Error('Remote Companion is unavailable.');
      }
      listed = await gateway.findFiles({ pattern: INCLUDE_GLOB, exclude: EXCLUDE_GLOB, max_results: listLimit });
    } catch (error) {
      reportRemoteSnapshotFailure('find', error);
      return { is_remote: true, root_uri: folder.uri.toString(), files: [], contents: {} };
    }
  } else listed = await vscode.workspace.findFiles(INCLUDE_GLOB, EXCLUDE_GLOB, listLimit);
  const files: Array<{ path: string; size?: number }> = [];
  const seen = new Set<string>();
  for (const uri of listed) {
    if (isRemote && !remoteUriWithinRoot(uri, folder.uri)) continue;
    const relative = vscode.workspace.asRelativePath(uri, false);
    if (!relative || relative === uri.fsPath) {
      continue;
    }
    const normalized = relative.replace(/\\/g, '/');
    let size: number | undefined;
    try {
      size = Number((await (gateway ? gateway.stat(uri) : vscode.workspace.fs.stat(uri))).size);
    } catch (error) {
      if (gateway) { reportRemoteSnapshotFailure('stat', error); continue; }
      size = undefined;
    }
    files.push({ path: normalized, size });
    seen.add(normalized);
  }
  for (const extra of extraPaths) {
    if (isRemote && (!extra || extra.split('/').some(part => part === '..' || part === '.') || extra.startsWith('/'))) continue;
    if (!seen.has(extra)) {
      let size: number | undefined;
      if (gateway) {
        try { size = (await gateway.stat(vscode.Uri.joinPath(folder.uri, ...extra.split('/')))).size; }
        catch (error) { reportRemoteSnapshotFailure('stat', error); continue; }
      }
      files.push({ path: extra, ...(size !== undefined ? { size } : {}) });
      seen.add(extra);
    }
  }

  const contentFileLimit = isRemote ? CONTENT_FILE_LIMIT_REMOTE : CONTENT_FILE_LIMIT_LOCAL;
  const contentCharLimit = isRemote ? CONTENT_CHAR_LIMIT_REMOTE : CONTENT_CHAR_LIMIT_LOCAL;
  const contents: Record<string, { content: string; language_id?: string }> = {};
  let usedChars = 0;
  const editor = vscode.window?.activeTextEditor;
  const extraUris = extraPaths.map((relative) =>
    vscode.Uri.joinPath(folder.uri, ...relative.split('/').filter(Boolean)),
  );
  const ranked = [...listed].sort((left, right) => {
    const leftPath = vscode.workspace.asRelativePath(left, false).replace(/\\/g, '/');
    const rightPath = vscode.workspace.asRelativePath(right, false).replace(/\\/g, '/');
    return contentPriority(leftPath) - contentPriority(rightPath);
  });
  const prioritized: vscode.Uri[] = [...extraUris];
  if (editor) {
    prioritized.push(editor.document.uri);
  }
  for (const uri of ranked) {
    if (prioritized.length >= contentFileLimit + extraUris.length) {
      break;
    }
    if (!prioritized.some((item) => item.toString() === uri.toString())) {
      prioritized.push(uri);
    }
  }

  for (const uri of prioritized) {
    if (usedChars >= contentCharLimit) {
      break;
    }
    if (isRemote && !remoteUriWithinRoot(uri, folder.uri)) continue;
    const relative = vscode.workspace.asRelativePath(uri, false).replace(/\\/g, '/');
    if (!relative || contents[relative]) {
      continue;
    }
    const text = await readWorkspaceText(uri, PER_FILE_CHAR_LIMIT, gateway);
    if (text === undefined) {
      continue;
    }
    const languageId = editor?.document.uri.toString() === uri.toString()
      ? editor.document.languageId
      : languageHint(relative);
    contents[relative] = { content: text, language_id: languageId };
    usedChars += text.length;
  }

  return {
    is_remote: isRemote,
    root_uri: folder.uri.toString(),
    files,
    contents,
  };
}

function contentPriority(relativePath: string): number {
  const lower = relativePath.toLowerCase();
  const base = lower.split('/').pop() || lower;
  const depth = relativePath.split('/').filter(Boolean).length;
  if (PRIORITY_BASENAMES.has(base)) {
    return depth;
  }
  if (lower.endsWith('.md')) {
    return 10 + depth;
  }
  if (lower.endsWith('.py') || lower.endsWith('.ts') || lower.endsWith('.tsx')) {
    return 20 + depth;
  }
  return 40 + depth;
}

function remoteUriWithinRoot(uri: vscode.Uri, root: vscode.Uri): boolean {
  const relative = path.posix.relative(root.path, uri.path);
  return uri.scheme === root.scheme && uri.authority === root.authority && !uri.query && !uri.fragment &&
    Boolean(relative && relative !== '..' && !relative.startsWith('../') && !path.posix.isAbsolute(relative));
}

function remoteSnapshotGateway(owner?: object): WorkspaceGateway {
  const candidate = owner && 'workspaceGateway' in owner ? owner.workspaceGateway : undefined;
  if (candidate && typeof candidate === 'object' &&
      'capabilities' in candidate && typeof candidate.capabilities === 'function' &&
      'findFiles' in candidate && typeof candidate.findFiles === 'function' &&
      'stat' in candidate && typeof candidate.stat === 'function' &&
      'readFile' in candidate && typeof candidate.readFile === 'function') return candidate as WorkspaceGateway;
  return new RemoteWorkspaceGateway(vscode.env.remoteName);
}

function reportRemoteSnapshotFailure(operation: string, error: unknown): void {
  console.warn(`[workspace-snapshot] remote ${operation} unavailable (${error instanceof Error ? error.name : 'Request failed'})`);
}

async function readWorkspaceText(uri: vscode.Uri, maxChars: number, gateway?: WorkspaceGateway): Promise<string | undefined> {
  try {
    const bytes = await (gateway ? gateway.readFile(uri) : vscode.workspace.fs.readFile(uri));
    if (bytes.includes(0)) {
      return undefined;
    }
    const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
    if (!text.trim()) {
      return undefined;
    }
    return text.length > maxChars ? text.slice(0, maxChars) : text;
  } catch (error) {
    if (gateway) reportRemoteSnapshotFailure('read', error);
    return undefined;
  }
}

function languageHint(relativePath: string): string | undefined {
  const extension = relativePath.split('.').pop()?.toLowerCase();
  const map: Record<string, string> = {
    py: 'python',
    ts: 'typescript',
    tsx: 'typescriptreact',
    js: 'javascript',
    jsx: 'javascriptreact',
    go: 'go',
    rs: 'rust',
    md: 'markdown',
    json: 'json',
  };
  return extension ? map[extension] : undefined;
}
