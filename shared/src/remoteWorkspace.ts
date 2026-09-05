/**
 * Remote Workspace Types
 *
 * Type definitions for remote workspace support including credentialMode and mount manifests.
 * Reference: docs/open-source-fit-and-provider-strategy.md §7.10, §7.11
 */

import type { ProviderCredentialMode } from "./models";

/**
 * Remote workspace type enumeration
 */
export type RemoteWorkspaceType =
  | "local"           // Local filesystem
  | "remote_ssh"      // VS Code Remote SSH
  | "remote_tunnels"   // VS Code Remote Tunnels
  | "dev_containers"   // Dev Containers
  | "wsl"              // Windows Subsystem for Linux
  | "docker";          // Docker container (advanced)

/**
 * Remote workspace connection state
 */
export type RemoteConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

/**
 * Mount manifest entry for tracking remote workspace mounts
 */
export interface RemoteMountManifest {
  /** Unique mount identifier */
  mount_id: string;
  /** Remote workspace name/identifier */
  remote_name: string;
  /** Remote URI (vscode-remote:// or ssh://) */
  remote_uri: string;
  /** Credential mode for this mount */
  credential_mode: ProviderCredentialMode;
  /** Workspace type */
  workspace_type: RemoteWorkspaceType;
  /** Mount point in local terms (if applicable) */
  local_mount_point?: string;
  /** When this mount was established */
  mounted_at: string;
  /** Last successful connection */
  last_connected_at?: string;
  /** Last sync timestamp */
  last_sync_at?: string;
  /** Whether this mount is currently active */
  is_active: boolean;
  /** Connection state */
  connection_state: RemoteConnectionState;
  /** Error message if connection failed */
  error_message?: string;
  /** Metadata about the remote environment */
  remote_metadata?: RemoteWorkspaceMetadata;
}

/**
 * Metadata about the remote workspace environment
 */
export interface RemoteWorkspaceMetadata {
  /** Remote OS type */
  os_type: "linux" | "darwin" | "windows" | "unknown";
  /** Remote hostname */
  hostname: string;
  /** Remote working directory */
  working_directory: string;
  /** Available CPU cores */
  cpu_cores?: number;
  /** Available memory in MB */
  memory_mb?: number;
  /** GPU available */
  has_gpu?: boolean;
  /** Python version (if applicable) */
  python_version?: string;
  /** Node.js version (if applicable) */
  node_version?: string;
}

/**
 * Credential mode configuration for remote workspaces
 */
export interface CredentialModeConfig {
  /** Selected credential mode */
  mode: ProviderCredentialMode;
  /** Whether credentials are configured */
  is_configured: boolean;
  /** Human-readable status */
  status: string;
  /** Instructions for configuration */
  instructions: string;
}

/**
 * Credential mode options
 */
export const CREDENTIAL_MODE_OPTIONS: Record<ProviderCredentialMode, {
  label: string;
  description: string;
  securityLevel: "low" | "medium" | "high";
}> = {
  workspace_secret: {
    label: "Workspace Secret",
    description: "Store API key in workspace-secure storage on the remote host. Suitable for personal remote machines.",
    securityLevel: "medium",
  },
  ui_proxy: {
    label: "UI Proxy",
    description: "API key stays in local UI, proxied through the connection. Safer for shared or untrusted remote hosts.",
    securityLevel: "high",
  },
};

/**
 * Get credential mode configuration
 */
export function getCredentialModeConfig(mode: ProviderCredentialMode): CredentialModeConfig {
  const option = CREDENTIAL_MODE_OPTIONS[mode];
  return {
    mode,
    is_configured: false, // Will be set by actual implementation
    status: option.description,
    instructions: mode === "workspace_secret"
      ? "API key will be stored in the remote workspace's secure storage."
      : "API key remains in the local UI and is forwarded through the connection.",
  };
}

/**
 * Remote workspace connection options
 */
export interface RemoteWorkspaceConnectionOptions {
  /** Remote URI */
  remote_uri: string;
  /** Workspace type */
  workspace_type: RemoteWorkspaceType;
  /** Credential mode */
  credential_mode: ProviderCredentialMode;
  /** Connection timeout in ms */
  timeout_ms?: number;
  /** Whether to auto-reconnect */
  auto_reconnect?: boolean;
}

/**
 * Detect remote workspace type from URI
 */
export function detectRemoteWorkspaceType(uri: string): RemoteWorkspaceType {
  if (uri.startsWith("vscode-remote://")) {
    if (uri.includes("+ssh://")) {
      return "remote_ssh";
    }
    if (uri.includes("tunnel://")) {
      return "remote_tunnels";
    }
    if (uri.includes("dev.container")) {
      return "dev_containers";
    }
    if (uri.includes("wsl://")) {
      return "wsl";
    }
  }
  return "local";
}

/**
 * Get display name for remote workspace type
 */
export function getRemoteWorkspaceTypeLabel(type: RemoteWorkspaceType, language: "en" | "zh" = "en"): string {
  const labels: Record<RemoteWorkspaceType, { en: string; zh: string }> = {
    local: { en: "Local", zh: "本地" },
    remote_ssh: { en: "Remote SSH", zh: "远程 SSH" },
    remote_tunnels: { en: "Remote Tunnels", zh: "远程隧道" },
    dev_containers: { en: "Dev Containers", zh: "开发容器" },
    wsl: { en: "WSL", zh: "WSL" },
    docker: { en: "Docker", zh: "Docker" },
  };
  return labels[type]?.[language] ?? type;
}

/**
 * Check if credential mode is secure for a given workspace type
 */
export function isCredentialModeSecureForWorkspace(
  mode: ProviderCredentialMode,
  workspaceType: RemoteWorkspaceType,
): boolean {
  // ui_proxy is always secure
  if (mode === "ui_proxy") {
    return true;
  }

  // workspace_secret has varying security depending on workspace type
  const secureFor: RemoteWorkspaceType[] = ["local", "remote_ssh", "wsl"];
  return secureFor.includes(workspaceType);
}

/**
 * Get recommended credential mode for a workspace type
 */
export function getRecommendedCredentialMode(
  workspaceType: RemoteWorkspaceType,
): ProviderCredentialMode {
  const recommendations: Partial<Record<RemoteWorkspaceType, ProviderCredentialMode>> = {
    local: "workspace_secret",
    remote_ssh: "ui_proxy", // Safer for shared SSH hosts
    remote_tunnels: "ui_proxy",
    dev_containers: "workspace_secret",
    wsl: "workspace_secret",
    docker: "ui_proxy",
  };
  return recommendations[workspaceType] ?? "ui_proxy";
}

/**
 * Serialize mount manifest for storage
 */
export function serializeMountManifest(manifest: RemoteMountManifest): string {
  return JSON.stringify(manifest, null, 2);
}

/**
 * Deserialize mount manifest from storage
 */
export function deserializeMountManifest(data: string): RemoteMountManifest | null {
  try {
    const parsed = JSON.parse(data);
    return RemoteMountManifestSchema.parse(parsed);
  } catch {
    return null;
  }
}

// Simple validation schema (in production, use zod or similar)
const RemoteMountManifestSchema = {
  parse(obj: unknown): RemoteMountManifest | null {
    if (typeof obj !== "object" || obj === null) {
      return null;
    }
    const record = obj as Record<string, unknown>;
    if (typeof record.mount_id !== "string" || typeof record.remote_uri !== "string") {
      return null;
    }
    return {
      mount_id: record.mount_id as string,
      remote_name: (record.remote_name as string) || "",
      remote_uri: record.remote_uri as string,
      credential_mode: (record.credential_mode as ProviderCredentialMode) || "ui_proxy",
      workspace_type: (record.workspace_type as RemoteWorkspaceType) || "local",
      local_mount_point: record.local_mount_point as string | undefined,
      mounted_at: (record.mounted_at as string) || new Date().toISOString(),
      last_connected_at: record.last_connected_at as string | undefined,
      last_sync_at: record.last_sync_at as string | undefined,
      is_active: Boolean(record.is_active),
      connection_state: (record.connection_state as RemoteConnectionState) || "disconnected",
      error_message: record.error_message as string | undefined,
      remote_metadata: record.remote_metadata as RemoteWorkspaceMetadata | undefined,
    };
  },
};