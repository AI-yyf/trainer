import * as vscode from "vscode";

import {
  detectRemoteWorkspaceTypeFromContext,
  type RemoteWorkspaceType,
} from "../../../shared/src/remoteWorkspace";
import type { WorkspaceUriDto } from "../../../shared/src/remoteProtocol";

/** Values accepted by the workspace gateway at an API boundary. */
export type WorkspaceUriInput = vscode.Uri | string | WorkspaceUriDto;

export function isWorkspaceUri(value: unknown): value is vscode.Uri {
  return Boolean(
    value &&
      typeof value === "object" &&
      typeof (value as { scheme?: unknown }).scheme === "string" &&
      typeof (value as { path?: unknown }).path === "string" &&
      typeof (value as { fsPath?: unknown }).fsPath === "string" &&
      typeof (value as { toString?: unknown }).toString === "function",
  );
}

export function isWorkspaceUriDto(value: unknown): value is WorkspaceUriDto {
  return Boolean(
    value &&
      typeof value === "object" &&
      !isWorkspaceUri(value) &&
      typeof (value as { scheme?: unknown }).scheme === "string" &&
      typeof (value as { authority?: unknown }).authority === "string" &&
      typeof (value as { path?: unknown }).path === "string",
  );
}

/** Parse a serialized URI or convert a protocol DTO into a VS Code URI. */
export function toWorkspaceUri(value: WorkspaceUriInput): vscode.Uri {
  if (isWorkspaceUri(value)) {
    return value;
  }
  if (typeof value === "string") {
    const serialized = value.trim();
    if (!serialized) {
      throw new Error("Workspace URI must not be empty.");
    }
    return vscode.Uri.parse(serialized, true);
  }
  if (isWorkspaceUriDto(value)) {
    return vscode.Uri.from({
      scheme: value.scheme,
      authority: value.authority,
      path: value.path,
      query: value.query,
      fragment: value.fragment,
    });
  }
  throw new TypeError("Unsupported workspace URI value.");
}

export function parseWorkspaceUri(value: string): vscode.Uri {
  return toWorkspaceUri(value);
}

export function workspaceUriToDto(uri: vscode.Uri): WorkspaceUriDto {
  return {
    scheme: uri.scheme,
    authority: uri.authority,
    path: uri.path,
    query: uri.query,
    fragment: uri.fragment,
  };
}

export function toWorkspaceUriDto(value: WorkspaceUriInput): WorkspaceUriDto {
  return workspaceUriToDto(toWorkspaceUri(value));
}

export function workspaceUriToString(value: WorkspaceUriInput): string {
  return toWorkspaceUri(value).toString(true);
}

export function workspaceUriFromDto(value: WorkspaceUriDto): vscode.Uri {
  return toWorkspaceUri(value);
}

export function detectWorkspaceUriType(
  value: WorkspaceUriInput,
  remoteName?: string,
): RemoteWorkspaceType {
  const uri = toWorkspaceUri(value);
  return detectRemoteWorkspaceTypeFromContext({
    uri: { scheme: uri.scheme, authority: uri.authority },
    remoteName,
  });
}

export function isRemoteWorkspaceUri(value: WorkspaceUriInput, remoteName?: string): boolean {
  const uri = toWorkspaceUri(value);
  return (
    uri.scheme !== "file" ||
    Boolean(remoteName?.trim()) ||
    detectWorkspaceUriType(uri, remoteName) !== "local"
  );
}

export function getWorkspaceRootUri(): vscode.Uri | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri;
}

export function getWorkspaceUriLocation(
  value: WorkspaceUriInput,
  remoteName?: string,
): {
  uri: vscode.Uri;
  scheme: string;
  authority: string;
  path: string;
  displayPath: string;
  remoteType: RemoteWorkspaceType;
} {
  const uri = toWorkspaceUri(value);
  return {
    uri,
    scheme: uri.scheme,
    authority: uri.authority,
    path: uri.path,
    displayPath: uri.fsPath || uri.path,
    remoteType: detectWorkspaceUriType(uri, remoteName),
  };
}
