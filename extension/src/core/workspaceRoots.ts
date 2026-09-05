import * as path from 'node:path';
import * as vscode from 'vscode';

export interface WorkspaceRootSource {
  activeWorkspaceRoot?: string;
  workspaceFolder?: string;
}

const WINDOWS_DRIVE_ABSOLUTE = /^[a-zA-Z]:[\\/]/;
const UNC_ABSOLUTE = /^\\\\/;

export function looksLikeWindowsAbsolutePath(value: string): boolean {
  return WINDOWS_DRIVE_ABSOLUTE.test(value) || UNC_ABSOLUTE.test(value);
}

export function normalizeFsPath(value: string | undefined): string {
  const raw = String(value ?? '').trim();
  if (!raw) {
    return '';
  }
  // Windows-style absolute paths (drive/UNC) are opaque workspace identifiers
  // on POSIX hosts: they must never be resolved against the POSIX cwd. Every
  // other value (posix-absolute or relative) resolves with the host's own
  // path rules so POSIX paths stay intact on POSIX hosts.
  if (looksLikeWindowsAbsolutePath(raw)) {
    return path.win32.normalize(raw);
  }
  return path.resolve(raw);
}

/**
 * Separator-aware basename: a Windows-style identifier (drive/UNC/backslash
 * path) keeps win32 basename semantics even on POSIX hosts, so display names
 * and upload names resolve to the same final segment on every platform.
 */
export function basenameFs(value: string | undefined): string {
  const raw = String(value ?? '').trim();
  if (!raw) {
    return '';
  }
  if (looksLikeWindowsAbsolutePath(raw) || raw.includes('\\')) {
    return path.win32.basename(raw);
  }
  return path.basename(raw);
}

function isPathWithin(candidate: string, root: string): boolean {
  if (!candidate || !root) {
    return false;
  }
  // Windows-style values (drive/UNC roots) are opaque identifiers, but
  // containment inside them is still defined by win32 path rules — apply
  // those rules on every host so multi-root detection works when a
  // Windows-style workspace id reaches a POSIX host.
  if (looksLikeWindowsAbsolutePath(candidate) || looksLikeWindowsAbsolutePath(root)) {
    const candidateLower = path.win32.normalize(candidate).toLowerCase();
    const rootLower = path.win32.normalize(root).toLowerCase();
    return candidateLower === rootLower || candidateLower.startsWith(`${rootLower}\\`);
  }
  if (process.platform === 'win32') {
    const candidateLower = candidate.toLowerCase();
    const rootLower = root.toLowerCase();
    return candidateLower === rootLower || candidateLower.startsWith(`${rootLower}${path.sep}`);
  }
  return candidate === root || candidate.startsWith(`${root}${path.sep}`);
}

export function resolveWorkspaceFolderPathForFile(filePath: string | undefined): string | undefined {
  const folders = vscode.workspace?.workspaceFolders ?? [];
  const activeFile = String(filePath ?? '').trim();
  if (!activeFile || folders.length === 0) {
    return undefined;
  }
  const normalizedActiveFile = normalizeFsPath(activeFile);
  for (const folder of folders) {
    const normalizedFolder = normalizeFsPath(folder.uri.fsPath);
    if (isPathWithin(normalizedActiveFile, normalizedFolder)) {
      return folder.uri.fsPath;
    }
  }
  return undefined;
}

export function resolveWorkspaceFolderPathForKnownFiles(
  filePaths: readonly string[] | undefined,
): string | undefined {
  if (!filePaths?.length) {
    return undefined;
  }

  for (const filePath of filePaths) {
    const resolved = resolveWorkspaceFolderPathForFile(filePath);
    if (resolved) {
      return resolved;
    }
  }

  return undefined;
}

export function resolveActiveWorkspaceFolder(): vscode.WorkspaceFolder | undefined {
  const folders = vscode.workspace?.workspaceFolders ?? [];
  if (folders.length === 0) {
    return undefined;
  }
  if (folders.length === 1) {
    return folders[0];
  }

  const activeFile = vscode.window?.activeTextEditor?.document.uri.fsPath;
  const activeFolderPath = resolveWorkspaceFolderPathForFile(activeFile);
  if (activeFolderPath) {
    return folders.find((folder) => folder.uri.fsPath === activeFolderPath);
  }

  return undefined;
}

export function resolveActiveWorkspaceFolderPath(): string | undefined {
  return resolveActiveWorkspaceFolder()?.uri.fsPath;
}

export function resolveWorkspaceRootPath(
  workspace: WorkspaceRootSource | undefined,
): string | undefined {
  const activeWorkspaceRoot = String(workspace?.activeWorkspaceRoot ?? '').trim();
  if (activeWorkspaceRoot) {
    return normalizeFsPath(activeWorkspaceRoot);
  }

  const activeFolderPath = resolveActiveWorkspaceFolderPath();
  if (activeFolderPath) {
    return activeFolderPath;
  }

  const workspaceFolder = String(workspace?.workspaceFolder ?? '').trim();
  if (workspaceFolder) {
    return normalizeFsPath(workspaceFolder);
  }

  return undefined;
}

export function resolveSovereignWorkspaceRootPath(
  workspace: WorkspaceRootSource | undefined,
): string | undefined {
  const activeWorkspaceRoot = String(workspace?.activeWorkspaceRoot ?? '').trim();
  if (activeWorkspaceRoot) {
    return normalizeFsPath(activeWorkspaceRoot);
  }

  const activeFolderPath = resolveActiveWorkspaceFolderPath();
  if (activeFolderPath) {
    return activeFolderPath;
  }

  const folders = vscode.workspace?.workspaceFolders ?? [];
  if (folders.length <= 1) {
    const workspaceFolder = String(workspace?.workspaceFolder ?? '').trim();
    if (workspaceFolder) {
      return normalizeFsPath(workspaceFolder);
    }
  }

  return undefined;
}
