/**
 * Remote workspace type enumeration
 */
export type RemoteWorkspaceType =
  | "local"           // Local filesystem
  | "remote_ssh"      // VS Code Remote SSH
  | "remote_tunnels"   // VS Code Remote Tunnels
  | "dev_containers"   // Dev Containers
  | "wsl"              // Windows Subsystem for Linux
  | "docker";

export interface RemoteWorkspaceUriContext {
  uri?: string | {
    scheme?: string | null;
    authority?: string | null;
  } | null;
  remoteName?: string | null;
  authority?: string | null;
}

function normalizeRemoteSignal(value: string | null | undefined): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/%2b/gi, "+")
    .replace(/%3a/gi, ":");
}

function remoteTypeFromSignal(signal: string): RemoteWorkspaceType | undefined {
  const normalized = normalizeRemoteSignal(signal);
  if (!normalized) {
    return undefined;
  }
  if (
    normalized.startsWith("ssh-remote") ||
    normalized.startsWith("ssh+") ||
    normalized.startsWith("ssh://") ||
    normalized.includes("+ssh://")
  ) {
    return "remote_ssh";
  }
  if (
    normalized.startsWith("tunnel") ||
    normalized.startsWith("remote-tunnels") ||
    normalized.startsWith("remote-tunnel") ||
    normalized.includes("tunnel://")
  ) {
    return "remote_tunnels";
  }
  if (
    normalized.startsWith("dev-container") ||
    normalized.startsWith("dev_containers") ||
    normalized.includes("dev.container")
  ) {
    return "dev_containers";
  }
  if (normalized.startsWith("wsl") || normalized.includes("wsl://")) {
    return "wsl";
  }
  if (normalized.startsWith("docker") || normalized.includes("docker://")) {
    return "docker";
  }
  return undefined;
}

function uriSignals(uri: RemoteWorkspaceUriContext["uri"]): string[] {
  if (!uri) {
    return [];
  }
  if (typeof uri === "string") {
    const normalized = normalizeRemoteSignal(uri);
    const signals = [normalized];
    try {
      const parsed = new URL(uri);
      signals.push(parsed.protocol.replace(/:$/, ""), parsed.host, parsed.hostname);
    } catch {
      // URI-like strings without a URL authority are still handled by the raw signal.
    }
    return signals;
  }
  return [String(uri.scheme ?? ""), String(uri.authority ?? "")];
}

/**
 * Detect the workspace kind from both VS Code's remoteName and URI authority.
 * Remote SSH URIs normally look like vscode-remote://ssh-remote+host/path;
 * checking only the URI prefix misses the important authority component.
 */
export function detectRemoteWorkspaceTypeFromContext(
  context: RemoteWorkspaceUriContext,
): RemoteWorkspaceType {
  const signals = [
    ...uriSignals(context.uri),
    context.authority ?? "",
    context.remoteName ?? "",
  ];
  const hasRemoteScheme = signals.some((signal) => {
    const normalized = normalizeRemoteSignal(signal);
    return normalized === "vscode-remote" || normalized === "vscode-remote-resource";
  });

  for (const signal of signals) {
    const detected = remoteTypeFromSignal(signal);
    if (detected) {
      return detected;
    }
  }

  if (hasRemoteScheme) {
    return "remote_ssh";
  }

  return "local";
}
