export type WorkspaceTrustState = "unknown" | "untrusted" | "remote" | "trusted";

export type WorkspaceTrustSurfaceLanguage =
  | "zh-CN"
  | "en-US"
  | "es-ES"
  | "fr-FR"
  | "de-DE"
  | "ja-JP"
  | "ko-KR"
  | "pt-BR";

const TRUST_STATES = new Set<WorkspaceTrustState>([
  "unknown",
  "untrusted",
  "remote",
  "trusted",
]);

const TRUST_SENTENCES: Record<
  WorkspaceTrustState,
  Partial<Record<WorkspaceTrustSurfaceLanguage, string>> & Record<"zh-CN" | "en-US", string>
> = {
  unknown: {
    "zh-CN": "需要信任此工作区后，Trainer 才能读取项目文件。",
    "en-US": "Trust this workspace before Trainer can read project files.",
  },
  untrusted: {
    "zh-CN": "此工作区未受信任，Trainer 只会读取，不会写入。",
    "en-US": "This workspace is untrusted; Trainer stays read-only.",
  },
  remote: {
    "zh-CN": "远程工作区，破坏性操作默认关闭。",
    "en-US": "Remote workspace; destructive actions stay off.",
  },
  trusted: {
    "zh-CN": "工作区可用。",
    "en-US": "This workspace is trusted.",
  },
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

export function normalizeWorkspaceTrustState(value: unknown): WorkspaceTrustState {
  const raw = String(value ?? "")
    .trim()
    .toLowerCase();
  if (TRUST_STATES.has(raw as WorkspaceTrustState)) {
    return raw as WorkspaceTrustState;
  }
  return "unknown";
}

/** Read live capability summary trust; missing/leftover → unknown (never invent trusted). */
export function readWorkspaceTrustStateFromCapabilitySummary(
  capabilitySummary: Record<string, unknown> | null | undefined,
): WorkspaceTrustState {
  if (!capabilitySummary) {
    return "unknown";
  }
  const platform =
    asRecord(capabilitySummary.platform) ?? asRecord(capabilitySummary.Platform);
  if (!platform) {
    return "unknown";
  }
  return normalizeWorkspaceTrustState(
    platform.workspace_trust_state ?? platform.workspaceTrustState,
  );
}

export function describeWorkspaceTrustState(
  state: unknown,
  language: WorkspaceTrustSurfaceLanguage | string = "en-US",
): string {
  const normalized = normalizeWorkspaceTrustState(state);
  const localized = TRUST_SENTENCES[normalized];
  if (language === "zh-CN") {
    return localized["zh-CN"];
  }
  return localized[language as WorkspaceTrustSurfaceLanguage] ?? localized["en-US"];
}
