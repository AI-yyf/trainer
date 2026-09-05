import { normalizeProviderProtocol } from "./providerProtocols";
import { stripHostLastTestSecrets } from "./hostLastTestGovernance";

export type SettingsCapabilityName = "tools" | "streaming" | "thinking" | "vision";
export type SettingsCapabilityChipKind = "ready" | "unsupported" | "unverified";

export type SettingsLastTestScope = {
  workspaceId?: string;
  providerProfileId?: string;
};

export type SettingsCapabilityEvidenceLike = {
  name?: string;
  declared?: boolean;
  observed?: boolean | null;
  state?: string;
};

export type SettingsLastTestLike = {
  workspaceId?: string;
  profileId?: string;
  providerProfileId?: string;
  ok?: boolean;
  status?: string;
  detail?: string;
  checkedAt?: string;
  providerName?: string;
  baseUrl?: string;
  model?: string;
  errorCategory?: string;
  retryable?: boolean;
  responseLanguage?: string;
  toolsReady?: boolean;
  toolProbeStatus?: string;
  streamingReady?: boolean;
  streamProbeStatus?: string;
  thinkingReady?: boolean;
  thinkingProbeStatus?: string;
  visionReady?: boolean;
  visionProbeStatus?: string;
  capabilityEvidence?: SettingsCapabilityEvidenceLike[];
  protocol?: string;
};

export type SettingsCapabilityTruth = {
  toolsReady: boolean;
  streamingReady: boolean;
  thinkingReady: boolean;
  visionReady: boolean;
};

export type SettingsCapabilityChips = {
  tools: SettingsCapabilityChipKind;
  streaming: SettingsCapabilityChipKind;
  thinking: SettingsCapabilityChipKind;
  vision: SettingsCapabilityChipKind;
};

export type SettingsCapabilitySurfaceStatus =
  | "never_tested"
  | "failed"
  | "unknown_protocol"
  | "live";

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function evidenceName(name: SettingsCapabilityName): string[] {
  if (name === "streaming") {
    return ["streaming", "stream"];
  }
  return [name];
}

function findEvidence(
  lastTest: SettingsLastTestLike | undefined,
  name: SettingsCapabilityName,
): SettingsCapabilityEvidenceLike | undefined {
  const aliases = evidenceName(name);
  return lastTest?.capabilityEvidence?.find((entry) => {
    const entryName = text(entry.name).toLowerCase();
    return aliases.includes(entryName);
  });
}

function readyFlag(lastTest: SettingsLastTestLike, name: SettingsCapabilityName): boolean {
  if (name === "tools") {
    return lastTest.toolsReady === true;
  }
  if (name === "streaming") {
    return lastTest.streamingReady === true;
  }
  if (name === "thinking") {
    return lastTest.thinkingReady === true;
  }
  return lastTest.visionReady === true;
}

function probeStatus(lastTest: SettingsLastTestLike, name: SettingsCapabilityName): string {
  if (name === "tools") {
    return text(lastTest.toolProbeStatus).toLowerCase();
  }
  if (name === "streaming") {
    return text(lastTest.streamProbeStatus).toLowerCase();
  }
  if (name === "thinking") {
    return text(lastTest.thinkingProbeStatus).toLowerCase();
  }
  return text(lastTest.visionProbeStatus).toLowerCase();
}

export function selectScopedSettingsLastTest<T extends SettingsLastTestLike>(
  lastTest: T | undefined,
  scope: SettingsLastTestScope,
): T | undefined {
  if (!lastTest) {
    return undefined;
  }
  const scopeWorkspaceId = text(scope.workspaceId);
  const recordWorkspaceId = text(lastTest.workspaceId);
  if (!scopeWorkspaceId || !recordWorkspaceId || recordWorkspaceId !== scopeWorkspaceId) {
    return undefined;
  }
  const scopeProfileId = text(scope.providerProfileId);
  const recordProfileId = text(lastTest.profileId ?? lastTest.providerProfileId);
  if (scopeProfileId && (!recordProfileId || recordProfileId !== scopeProfileId)) {
    return undefined;
  }
  return stripHostLastTestSecrets({ ...(lastTest as Record<string, unknown>) }) as T;
}

export function settingsProtocolIsKnown(protocol: string | undefined): boolean {
  return Boolean(normalizeProviderProtocol(protocol));
}

export function settingsLastTestAllowsChips(
  lastTest: SettingsLastTestLike | undefined,
  scope: SettingsLastTestScope,
): boolean {
  const scoped = selectScopedSettingsLastTest(lastTest, scope);
  if (!scoped || scoped.ok !== true) {
    return false;
  }
  // Fail-closed: missing/empty protocol is unknown — never promote chips or tools_ready.
  if (!settingsProtocolIsKnown(text(scoped.protocol))) {
    return false;
  }
  return true;
}

export function settingsCapabilityIsReady(
  lastTest: SettingsLastTestLike | undefined,
  name: SettingsCapabilityName,
  scope: SettingsLastTestScope,
): boolean {
  if (!settingsLastTestAllowsChips(lastTest, scope)) {
    return false;
  }
  const scoped = selectScopedSettingsLastTest(lastTest, scope);
  if (!scoped) {
    return false;
  }
  const evidence = findEvidence(scoped, name);
  return (
    readyFlag(scoped, name) &&
    probeStatus(scoped, name) === "verified" &&
    evidence?.state === "verified" &&
    evidence.observed === true
  );
}

export function deriveSettingsCapabilityChip(
  lastTest: SettingsLastTestLike | undefined,
  name: SettingsCapabilityName,
  scope: SettingsLastTestScope,
): SettingsCapabilityChipKind {
  if (!settingsLastTestAllowsChips(lastTest, scope)) {
    return "unverified";
  }
  const scoped = selectScopedSettingsLastTest(lastTest, scope);
  if (!scoped) {
    return "unverified";
  }
  if (settingsCapabilityIsReady(scoped, name, scope)) {
    return "ready";
  }
  const evidence = findEvidence(scoped, name);
  if (evidence?.state === "unsupported" && evidence.observed === false) {
    return "unsupported";
  }
  return "unverified";
}

export function deriveSettingsCapabilityChips(
  lastTest: SettingsLastTestLike | undefined,
  scope: SettingsLastTestScope,
): SettingsCapabilityChips {
  return {
    tools: deriveSettingsCapabilityChip(lastTest, "tools", scope),
    streaming: deriveSettingsCapabilityChip(lastTest, "streaming", scope),
    thinking: deriveSettingsCapabilityChip(lastTest, "thinking", scope),
    vision: deriveSettingsCapabilityChip(lastTest, "vision", scope),
  };
}

export function scopedSettingsCapabilityTruth(
  lastTest: SettingsLastTestLike | undefined,
  scope: SettingsLastTestScope,
): SettingsCapabilityTruth {
  return {
    toolsReady: settingsCapabilityIsReady(lastTest, "tools", scope),
    streamingReady: settingsCapabilityIsReady(lastTest, "streaming", scope),
    thinkingReady: settingsCapabilityIsReady(lastTest, "thinking", scope),
    visionReady: settingsCapabilityIsReady(lastTest, "vision", scope),
  };
}

export function settingsCapabilitySurfaceStatus(
  lastTest: SettingsLastTestLike | undefined,
  scope: SettingsLastTestScope,
  protocol?: string,
): SettingsCapabilitySurfaceStatus {
  const currentProtocol = text(protocol) || text(lastTest?.protocol);
  if (currentProtocol && !settingsProtocolIsKnown(currentProtocol)) {
    return "unknown_protocol";
  }
  const scoped = selectScopedSettingsLastTest(lastTest, scope);
  if (!scoped) {
    return "never_tested";
  }
  if (scoped.ok !== true) {
    return "failed";
  }
  // Live ok last-test still needs a known protocol before chips are honest.
  if (!settingsProtocolIsKnown(text(scoped.protocol) || currentProtocol)) {
    return "unknown_protocol";
  }
  return settingsLastTestAllowsChips(scoped, scope) ? "live" : "never_tested";
}

export function settingsCapabilityChipsVisible(
  lastTest: SettingsLastTestLike | undefined,
  scope: SettingsLastTestScope,
  protocol?: string,
): boolean {
  return settingsCapabilitySurfaceStatus(lastTest, scope, protocol) === "live";
}
