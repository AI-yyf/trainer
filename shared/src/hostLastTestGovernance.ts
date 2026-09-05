import { sanitizeHostToolResult } from "./errorSurfaceSanitizer";

export type HostLastTestScope = {
  workspaceId: string;
  providerProfileId?: string;
};

const SECRET_KEYS = new Set([
  "apikey",
  "api_key",
  "api-key",
  "secret",
  "token",
  "authorization",
  "password",
]);

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export function hostLastTestStorageKey(scope: HostLastTestScope, fingerprint: string): string {
  const workspaceId = text(scope.workspaceId);
  const profileId = text(scope.providerProfileId) || "_";
  const fp = text(fingerprint);
  return `ws:${workspaceId}|profile:${profileId}|fp:${fp}`;
}

export function stripHostLastTestSecrets<T extends Record<string, unknown>>(value: T): T {
  const cleaned = { ...value };
  for (const key of Object.keys(cleaned)) {
    if (SECRET_KEYS.has(key.toLowerCase())) {
      delete cleaned[key];
    }
  }
  // Fail-closed: also pattern-redact bearer/sk-/api-key shapes inside detail
  // and nested string fields (not only drop secret keys).
  return sanitizeHostToolResult(cleaned) as T;
}

/** Fail-closed strip for webview/host provider snapshots before persist or UI handoff. */
export function stripProviderSnapshotSecrets<T>(value: T): T {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return value;
  }
  const cleaned = stripHostLastTestSecrets({ ...(value as Record<string, unknown>) });
  const lastTest = cleaned.lastTestResult ?? cleaned.last_test_result;
  if (lastTest && typeof lastTest === "object" && !Array.isArray(lastTest)) {
    const strippedLastTest = stripHostLastTestSecrets({
      ...(lastTest as Record<string, unknown>),
    });
    if ("lastTestResult" in cleaned) {
      cleaned.lastTestResult = strippedLastTest;
    }
    if ("last_test_result" in cleaned) {
      cleaned.last_test_result = strippedLastTest;
    }
  }
  return cleaned as T;
}

export function isHostLastTestCurrentForScope(
  record: unknown,
  scope: HostLastTestScope,
): boolean {
  const row = asRecord(record);
  if (!row) {
    return false;
  }
  const recordWorkspaceId = text(row.workspaceId ?? row.workspace_id);
  const scopeWorkspaceId = text(scope.workspaceId);
  if (!recordWorkspaceId || !scopeWorkspaceId || recordWorkspaceId !== scopeWorkspaceId) {
    return false;
  }
  const recordProfileId = text(row.profileId ?? row.providerProfileId ?? row.provider_profile_id);
  const scopeProfileId = text(scope.providerProfileId);
  if (scopeProfileId) {
    return Boolean(recordProfileId) && recordProfileId === scopeProfileId;
  }
  return !recordProfileId;
}

export function selectHostLastTest(
  store: Record<string, unknown> | undefined,
  scope: HostLastTestScope,
  fingerprint: string,
): Record<string, unknown> | undefined {
  if (!store || !text(scope.workspaceId) || !text(fingerprint)) {
    return undefined;
  }
  const scopedKey = hostLastTestStorageKey(scope, fingerprint);
  const scoped = asRecord(store[scopedKey]);
  if (scoped && isHostLastTestCurrentForScope(scoped, scope)) {
    return stripHostLastTestSecrets(scoped);
  }
  const legacy = asRecord(store[fingerprint]);
  if (legacy && isHostLastTestCurrentForScope(legacy, scope)) {
    return stripHostLastTestSecrets(legacy);
  }
  return undefined;
}

export function writeHostLastTest(
  store: Record<string, unknown>,
  scope: HostLastTestScope,
  fingerprint: string,
  result: Record<string, unknown>,
): Record<string, unknown> {
  const cleaned = stripHostLastTestSecrets({
    ...result,
    workspaceId: text(scope.workspaceId),
    profileId: text(scope.providerProfileId) || undefined,
  });
  delete store[fingerprint];
  if (!text(scope.workspaceId) || !text(fingerprint)) {
    return store;
  }
  store[hostLastTestStorageKey(scope, fingerprint)] = cleaned;
  return store;
}

export function clearHostLastTest(
  store: Record<string, unknown>,
  scope: HostLastTestScope,
  fingerprint: string,
): Record<string, unknown> {
  delete store[fingerprint];
  if (text(scope.workspaceId) && text(fingerprint)) {
    delete store[hostLastTestStorageKey(scope, fingerprint)];
  }
  return store;
}
