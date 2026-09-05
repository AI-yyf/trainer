export type SandboxNarrativeLanguage = "zh-CN" | "en-US" | "es-ES" | "fr-FR" | "de-DE" | "ja-JP" | "ko-KR" | "pt-BR";

export type SandboxNetworkExecutionLaneKey =
  | "audited_python"
  | "unaudited_python"
  | "non_python"
  | "child_process"
  | "os_container";

export interface SandboxNetworkExecutionLaneFactLike {
  status: string;
  currentEnforcement: string;
  nextRequirement: string;
  reasonCode?: string;
  reason?: string;
  requiredExecutor?: string;
}

export interface SandboxOsContainerExecutorProbeLike {
  availability: string;
  selectedRuntime: string;
  selectedExecutorMode: string;
  selectedEntryRuntime?: string;
  supportedEntryRuntimes?: string[];
  reasonCode?: string;
  reason?: string;
  imageReference?: string;
  imageRepoDigests?: string[];
  selectedImageRepoDigest?: string;
  imageTrustPolicy?: string;
  imageTrustStatus?: string;
}

export interface SandboxOsContainerExecutionPlanLike {
  status: string;
  runtime: string;
  executorMode: string;
  selectedEntryRuntime?: string;
  networkAllowlist?: string[];
  containerRootPath?: string;
  containerWorkdir?: string;
  containerInputPath?: string;
  containerOutputPaths?: string[];
  runtimeCommand?: string[];
  containerImage?: string;
  containerImageRepoDigest?: string;
  imageTrustPolicy?: string;
  imageTrustStatus?: string;
  reasonCode?: string;
  reason?: string;
}

export interface SandboxNetworkExecutionFactsLike {
  auditedPython: SandboxNetworkExecutionLaneFactLike;
  unauditedPython: SandboxNetworkExecutionLaneFactLike;
  nonPython: SandboxNetworkExecutionLaneFactLike;
  childProcess: SandboxNetworkExecutionLaneFactLike;
  osContainer: SandboxNetworkExecutionLaneFactLike;
  osContainerProbe?: SandboxOsContainerExecutorProbeLike;
}

export interface SandboxCapabilityStatusLike {
  summary?: string;
  reasonCode?: string;
  reasons?: string[];
  networkFacts?: SandboxNetworkExecutionFactsLike;
}

const SKILL_RUNTIME_POLICY = "trainer.resource_sandbox.skill_runtime.v1";
const SKILL_RUN_GATE_POLICY = "trainer.resource_sandbox.skill_run_gate.v1";
const SKILL_ISOLATED_EXECUTOR_POLICY = "trainer.resource_sandbox.skill_isolated_executor.v1";

export function describeSandboxNetworkCapabilityHeadline(
  status: SandboxCapabilityStatusLike | undefined,
  platformOs: string | undefined,
  language: SandboxNarrativeLanguage,
): string {
  const os = normalizeText(platformOs) ?? (isZh(language) ? "\u672a\u8bb0\u5f55" : "unknown");
  const reason = describeSandboxNetworkReasonCode(status?.reasonCode, language);
  if (isZh(language)) {
    return reason ? `\u5e73\u53f0 ${os} / ${reason}` : `\u5e73\u53f0 ${os} / \u7f51\u7edc\u80fd\u529b\u7531\u670d\u52a1\u7aef\u53d7\u63a7\u5224\u5b9a`;
  }
  return reason ? `Platform ${os} / ${reason}` : `Platform ${os} / network capability is server-governed`;
}

function isZh(language: SandboxNarrativeLanguage): boolean {
  return language === "zh-CN";
}

function normalizeText(value: string | undefined): string | undefined {
  const text = String(value ?? "").trim();
  return text.length > 0 ? text : undefined;
}

function uniqueValues(values: string[] | undefined): string[] {
  return Array.from(
    new Set((values ?? []).map((item) => String(item ?? "").trim()).filter(Boolean)),
  );
}

function normalizedValues(values: string[] | undefined): string[] {
  return (values ?? []).map((item) => String(item ?? "").trim()).filter(Boolean);
}

function joinFacts(values: Array<string | undefined>): string {
  return values.filter((value): value is string => Boolean(value)).join(" | ");
}

function laneLabel(key: SandboxNetworkExecutionLaneKey, language: SandboxNarrativeLanguage): string {
  if (isZh(language)) {
    return {
      audited_python: "\u5df2\u5ba1\u8ba1 Python",
      unaudited_python: "\u672a\u5ba1\u8ba1 Python",
      non_python: "\u975e Python",
      child_process: "\u5b50\u8fdb\u7a0b",
      os_container: "\u7cfb\u7edf/\u5bb9\u5668\u9694\u79bb",
    }[key];
  }
  return {
    audited_python: "audited python",
    unaudited_python: "unaudited python",
    non_python: "non-python",
    child_process: "child process",
    os_container: "os/container isolation",
  }[key];
}

function laneStatusLabel(status: string, language: SandboxNarrativeLanguage): string {
  if (isZh(language)) {
    return {
      guarded_allowlist_only: "\u53ea\u5141\u8bb8\u767d\u540d\u5355\u7f51\u57df",
      blocked: "\u53d7\u963b",
      blocked_by_preflight: "\u88ab\u9884\u68c0\u62e6\u622a",
      missing: "\u7f3a\u5931",
      enforced: "\u5df2\u5f3a\u5236",
    }[status] ?? status;
  }
  return {
    guarded_allowlist_only: "guarded",
    blocked: "blocked",
    blocked_by_preflight: "preflight-blocked",
    missing: "missing",
    enforced: "enforced",
  }[status] ?? status;
}

function currentEnforcementLabel(value: string, language: SandboxNarrativeLanguage): string {
  if (isZh(language)) {
    return {
      python_socket_guard: "\u5f53\u524d\u5b88\u536b\uff1apython_socket_guard",
      node_socket_guard: "\u5f53\u524d\u5b88\u536b\uff1anode_socket_guard",
      runtime_preflight: "\u5f53\u524d\u5b88\u536b\uff1aruntime_preflight",
      os_container_egress: "\u5f53\u524d\u5b88\u536b\uff1aos/container egress",
      missing: "\u5f53\u524d\u5b88\u536b\uff1amissing",
    }[value] ?? `\u5f53\u524d\u5b88\u536b\uff1a${value}`;
  }
  return {
    python_socket_guard: "current: python_socket_guard",
    node_socket_guard: "current: node_socket_guard",
    runtime_preflight: "current: runtime_preflight",
    os_container_egress: "current: os/container egress",
    missing: "current: missing",
  }[value] ?? `current: ${value}`;
}

function nextRequirementLabel(value: string, language: SandboxNarrativeLanguage): string {
  if (isZh(language)) {
    return {
      none: "\u4e0b\u4e00\u6b65\uff1a\u65e0",
      audited_sandbox_python_script: "\u4e0b\u4e00\u6b65\uff1a\u5df2\u5ba1\u8ba1 Python \u5165\u53e3\u811a\u672c",
      subprocess_free_audited_entrypoint:
        "\u4e0b\u4e00\u6b65\uff1a\u65e0\u5b50\u8fdb\u7a0b\u7684\u5df2\u5ba1\u8ba1\u5165\u53e3",
      os_or_container_egress_enforcement:
        "\u4e0b\u4e00\u6b65\uff1aOS/\u5bb9\u5668 egress enforcement",
    }[value] ?? `\u4e0b\u4e00\u6b65\uff1a${value}`;
  }
  return {
    none: "next: none",
    audited_sandbox_python_script: "next: audited python script",
    subprocess_free_audited_entrypoint: "next: subprocess-free audited entrypoint",
    os_or_container_egress_enforcement: "next: os/container egress",
  }[value] ?? `next: ${value}`;
}

function osContainerProbeAvailabilityLabel(
  availability: string,
  language: SandboxNarrativeLanguage,
): string {
  if (isZh(language)) {
    return {
      available: "\u53ef\u7528",
      unavailable_runtime_missing: "\u5bbf\u4e3b\u7f3a\u5c11 runtime",
      unavailable_daemon_unreachable: "daemon \u4e0d\u53ef\u8fbe",
      unavailable_image_missing: "\u5bb9\u5668\u955c\u50cf\u7f3a\u5931",
      unavailable_image_untrusted: "\u5bb9\u5668\u955c\u50cf\u4e0d\u53d7\u4fe1\u4efb",
      unavailable_executor_not_implemented: "\u6267\u884c\u5668\u672a\u5b9e\u88c5",
      probe_failed: "\u63a2\u6d4b\u5931\u8d25",
    }[availability] ?? availability;
  }
  return {
    available: "available",
    unavailable_runtime_missing: "runtime missing",
    unavailable_daemon_unreachable: "daemon unreachable",
    unavailable_image_missing: "image missing",
    unavailable_image_untrusted: "image untrusted",
    unavailable_executor_not_implemented: "executor not implemented",
    probe_failed: "probe failed",
  }[availability] ?? availability;
}

function osContainerPlanStatusLabel(status: string, language: SandboxNarrativeLanguage): string {
  if (status === "planned_probe_ready") {
    return isZh(language)
      ? "runtime \u5df2\u63a2\u6d4b\u5230\uff0c\u4f46\u6267\u884c\u5668\u8fd8\u672a\u5c31\u7eea"
      : "runtime detected but executor not ready";
  }
  if (isZh(language)) {
    return {
      not_needed: "\u65e0\u9700\u5bb9\u5668\u8ba1\u5212",
      planned_blocked: "\u5df2\u89c4\u5212\u4f46\u53d7\u963b",
      planned_ready: "\u5df2\u89c4\u5212\u5e76\u5c31\u7eea",
    }[status] ?? status;
  }
  return {
    not_needed: "not needed",
    planned_blocked: "planned but blocked",
    planned_ready: "planned and ready",
  }[status] ?? status;
}

function osContainerEntryRuntimeLabel(
  value: string | undefined,
  language: SandboxNarrativeLanguage,
): string | undefined {
  const runtime = normalizeText(value);
  if (!runtime || runtime === "none") {
    return undefined;
  }
  return isZh(language) ? `\u5165\u53e3 runtime\uff1a${runtime}` : `entry: ${runtime}`;
}

function osContainerSupportedEntryRuntimesLabel(
  values: string[] | undefined,
  language: SandboxNarrativeLanguage,
): string | undefined {
  const runtimes = uniqueValues(values);
  if (runtimes.length === 0) {
    return undefined;
  }
  return isZh(language)
    ? `\u652f\u6301\u5165\u53e3\uff1a${runtimes.join(", ")}`
    : `supported entries: ${runtimes.join(", ")}`;
}

function fallbackSummary(
  status: SandboxCapabilityStatusLike | undefined,
  language: SandboxNarrativeLanguage,
): string {
  if (isZh(language)) {
    return (
      describeSandboxNetworkReasonCode(status?.reasonCode, language) ??
      "\u8d44\u6599\u6c99\u7bb1\u80fd\u529b\u7531\u670d\u52a1\u7aef\u7edf\u4e00\u5224\u5b9a\uff1b\u8fd9\u91cc\u53ea\u5c55\u793a\u53d7\u6cbb\u7406\u540e\u7684\u53ea\u8bfb\u4e8b\u5b9e\u3002"
    );
  }
  return (
    describeSandboxNetworkReasonCode(status?.reasonCode, language) ??
    normalizeText(status?.reasons?.[0]) ??
    normalizeText(status?.summary) ??
    ""
  );
}

export function describeSandboxNetworkReasonCode(
  reasonCode: string | undefined,
  language: SandboxNarrativeLanguage,
): string | undefined {
  if (!reasonCode) {
    return undefined;
  }
  if (isZh(language)) {
    return {
      network_egress_non_python_entrypoint:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u975e Python \u5165\u53e3\u4e0d\u53ef\u76f4\u63a5\u8054\u7f51",
      network_egress_unaudited_command_path:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u672a\u5ba1\u8ba1\u7684\u547d\u4ee4\u8def\u5f84\u4e0d\u53ef\u901a\u884c",
      network_egress_requires_os_container_executor:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u9700\u8981\u7cfb\u7edf/\u5bb9\u5668\u9694\u79bb\u6267\u884c\u901a\u9053",
      network_egress_enforcement_missing:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u7f3a\u5c11\u9694\u79bb\u7f51\u7edc\u5b88\u536b",
      network_egress_os_container_executor_unavailable:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5bb9\u5668\u6267\u884c\u901a\u9053\u4e0d\u53ef\u7528",
      network_egress_os_container_runtime_missing:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5bbf\u4e3b\u7f3a\u5c11\u5bb9\u5668\u8fd0\u884c\u73af\u5883",
      network_egress_os_container_daemon_unreachable:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5bb9\u5668\u670d\u52a1\u4e0d\u53ef\u8fbe",
      network_egress_os_container_image_missing:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5bb9\u5668\u955c\u50cf\u7f3a\u5931",
      network_egress_os_container_image_untrusted:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5bb9\u5668\u955c\u50cf\u672a\u901a\u8fc7\u4fe1\u4efb\u6821\u9a8c",
      network_egress_os_container_executor_not_implemented:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5bb9\u5668\u6267\u884c\u901a\u9053\u5c1a\u672a\u5b9e\u88c5",
      network_egress_os_container_probe_failed:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5bb9\u5668\u80fd\u529b\u63a2\u6d4b\u5931\u8d25",
      network_egress_unsupported_node_entrypoint:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5f53\u524d Node \u5165\u53e3\u5f62\u6001\u4e0d\u53d7\u652f\u6301",
      network_egress_child_process_escape_blocked:
        "\u7f51\u7edc\u53d7\u63a7\uff1a\u5b50\u8fdb\u7a0b\u9003\u9038\u8def\u5f84\u5df2\u88ab\u62e6\u622a",
    }[reasonCode] ?? `\u539f\u56e0\u7801\uff1a${reasonCode}`;
  }
  return {
    network_egress_non_python_entrypoint: "network gate: non-python entrypoint",
    network_egress_unaudited_command_path: "network gate: unaudited command path",
    network_egress_requires_os_container_executor: "network gate: os/container executor required",
    network_egress_enforcement_missing: "network gate: egress enforcement missing",
    network_egress_os_container_executor_unavailable: "network gate: container executor unavailable",
    network_egress_os_container_runtime_missing: "network gate: container runtime missing",
    network_egress_os_container_daemon_unreachable: "network gate: container daemon unreachable",
    network_egress_os_container_image_missing: "network gate: container image missing",
    network_egress_os_container_image_untrusted: "network gate: container image untrusted",
    network_egress_os_container_executor_not_implemented:
      "network gate: container executor not implemented",
    network_egress_os_container_probe_failed: "network gate: container probe failed",
    network_egress_unsupported_node_entrypoint: "network gate: unsupported node entrypoint",
    network_egress_child_process_escape_blocked: "network gate: child-process escape blocked",
  }[reasonCode] ?? `reason: ${reasonCode}`;
}

export function describeSandboxNetworkLaneFact(
  key: SandboxNetworkExecutionLaneKey,
  fact: SandboxNetworkExecutionLaneFactLike,
  language: SandboxNarrativeLanguage,
): string {
  return joinFacts([
    `${laneLabel(key, language)}: ${laneStatusLabel(fact.status, language)}`,
    currentEnforcementLabel(fact.currentEnforcement, language),
    nextRequirementLabel(fact.nextRequirement, language),
  ]);
}

export function describeSandboxOsContainerProbe(
  probe: SandboxOsContainerExecutorProbeLike | undefined,
  language: SandboxNarrativeLanguage,
): string | undefined {
  if (!probe) {
    return undefined;
  }
  const runtime =
    normalizeText(probe.selectedRuntime) && probe.selectedRuntime !== "none"
      ? probe.selectedRuntime
      : isZh(language)
        ? "\u672a\u9009\u5b9a"
        : "none";
  const detail = normalizeText(probe.reason);
  const image = normalizeText(probe.imageReference);
  const trust = normalizeText(probe.imageTrustStatus);
  return joinFacts([
    isZh(language)
      ? `OS/\u5bb9\u5668\u63a2\u6d4b\uff1a${osContainerProbeAvailabilityLabel(probe.availability, language)}`
      : `os/container probe: ${osContainerProbeAvailabilityLabel(probe.availability, language)}`,
    isZh(language) ? `\u8fd0\u884c\u65f6\uff1a${runtime}` : `runtime: ${runtime}`,
    osContainerEntryRuntimeLabel(probe.selectedEntryRuntime, language),
    osContainerSupportedEntryRuntimesLabel(probe.supportedEntryRuntimes, language),
    image ? (isZh(language) ? `\u955c\u50cf\uff1a${image}` : `image: ${image}`) : undefined,
    trust ? (isZh(language) ? `\u955c\u50cf\u4fe1\u4efb\uff1a${trust}` : `trust: ${trust}`) : undefined,
    detail ? (isZh(language) ? `\u8bf4\u660e\uff1a${detail}` : `detail: ${detail}`) : undefined,
  ]);
}

export function describeSandboxOsContainerExecutionPlan(
  plan: SandboxOsContainerExecutionPlanLike | undefined,
  language: SandboxNarrativeLanguage,
): string[] {
  if (!plan || plan.status === "not_needed") {
    return [];
  }

  const allowlist = uniqueValues(plan.networkAllowlist);
  const outputs = uniqueValues(plan.containerOutputPaths);
  const runtimeCommand = normalizedValues(plan.runtimeCommand);
  const facts: string[] = [
    isZh(language)
      ? `\u5bb9\u5668\u8ba1\u5212\uff1a${osContainerPlanStatusLabel(plan.status, language)} / \u8fd0\u884c\u65f6\uff1a${plan.runtime || "none"} / \u6267\u884c\u5668\uff1a${plan.executorMode || "none"}`
      : `container plan: ${osContainerPlanStatusLabel(plan.status, language)} / runtime: ${plan.runtime || "none"} / executor: ${plan.executorMode || "none"}`,
  ];

  if (allowlist.length > 0) {
    facts.push(
      isZh(language)
        ? `\u5141\u8bb8\u7f51\u57df\uff1a${allowlist.join(", ")}`
        : `allowlist: ${allowlist.join(", ")}`,
    );
  }
  const entryRuntime = normalizeText(plan.selectedEntryRuntime);
  if (entryRuntime && entryRuntime !== "none") {
    facts.push(
      isZh(language) ? `\u5165\u53e3 runtime\uff1a${entryRuntime}` : `entry: ${entryRuntime}`,
    );
  }
  if (plan.containerRootPath) {
    facts.push(
      isZh(language)
        ? `\u5bb9\u5668\u6839\u76ee\u5f55\uff1a${plan.containerRootPath}`
        : `container root: ${plan.containerRootPath}`,
    );
  }
  if (plan.containerWorkdir) {
    facts.push(
      isZh(language) ? `\u5de5\u4f5c\u76ee\u5f55\uff1a${plan.containerWorkdir}` : `workdir: ${plan.containerWorkdir}`,
    );
  }
  if (plan.containerInputPath) {
    facts.push(
      isZh(language) ? `\u8f93\u5165\u8def\u5f84\uff1a${plan.containerInputPath}` : `input: ${plan.containerInputPath}`,
    );
  }
  if (outputs.length > 0) {
    facts.push(
      isZh(language) ? `\u8f93\u51fa\u8def\u5f84\uff1a${outputs.join(", ")}` : `outputs: ${outputs.join(", ")}`,
    );
  }
  if (runtimeCommand.length > 0) {
    facts.push(
      isZh(language)
        ? `runtime \u547d\u4ee4\uff1a${runtimeCommand.join(" ")}`
        : `runtime cmd: ${runtimeCommand.join(" ")}`,
    );
  }
  if (plan.containerImage) {
    facts.push(isZh(language) ? `\u955c\u50cf\uff1a${plan.containerImage}` : `image: ${plan.containerImage}`);
  }
  if (plan.containerImageRepoDigest) {
    facts.push(
      isZh(language)
        ? `\u955c\u50cf digest\uff1a${plan.containerImageRepoDigest}`
        : `image digest: ${plan.containerImageRepoDigest}`,
    );
  }
  if (plan.imageTrustStatus) {
    facts.push(
      isZh(language) ? `\u955c\u50cf\u4fe1\u4efb\uff1a${plan.imageTrustStatus}` : `image trust: ${plan.imageTrustStatus}`,
    );
  }
  const reasonLine =
    describeSandboxNetworkReasonCode(plan.reasonCode, language) ??
    normalizeText(plan.reason);
  if (reasonLine) {
    facts.push(reasonLine);
  }
  return facts;
}

export function describeSandboxNetworkCapabilityFacts(
  facts: SandboxNetworkExecutionFactsLike | undefined,
  language: SandboxNarrativeLanguage,
): string[] {
  if (!facts) {
    return [];
  }
  return [
    describeSandboxNetworkLaneFact("audited_python", facts.auditedPython, language),
    describeSandboxNetworkLaneFact("unaudited_python", facts.unauditedPython, language),
    describeSandboxNetworkLaneFact("non_python", facts.nonPython, language),
    describeSandboxNetworkLaneFact("child_process", facts.childProcess, language),
    describeSandboxNetworkLaneFact("os_container", facts.osContainer, language),
    describeSandboxOsContainerProbe(facts.osContainerProbe, language),
  ].filter((value): value is string => Boolean(value));
}

function coachLaneFact(
  key: SandboxNetworkExecutionLaneKey,
  fact: SandboxNetworkExecutionLaneFactLike,
  language: SandboxNarrativeLanguage,
): string {
  const zh = isZh(language);
  const status = laneStatusLabel(fact.status, language);
  if (key === "audited_python" && fact.status === "guarded_allowlist_only") {
    return zh
      ? "\u5df2\u5ba1\u8ba1 Python \u5165\u53e3\uff1a\u53ea\u5141\u8bb8\u5728\u767d\u540d\u5355\u7f51\u57df\u5185\u8054\u7f51"
      : "Audited Python entry: networking is allowed only for approved hosts";
  }
  if (key === "unaudited_python" && fact.status === "blocked") {
    return zh
      ? "\u672a\u5ba1\u8ba1 Python \u547d\u4ee4\uff1a\u9ed8\u8ba4\u7981\u6b62\u8054\u7f51"
      : "Unaudited Python commands: networking stays blocked by default";
  }
  if (key === "non_python" && fact.status === "blocked") {
    return zh
      ? "\u901a\u7528\u975e Python \u547d\u4ee4\uff1a\u9ed8\u8ba4\u7981\u6b62\u8054\u7f51"
      : "Generic non-Python commands: networking stays blocked by default";
  }
  if (key === "child_process" && fact.status === "blocked_by_preflight") {
    return zh
      ? "\u5b50\u8fdb\u7a0b\u8def\u5f84\uff1a\u9884\u68c0\u9636\u6bb5\u5df2\u62e6\u622a\u9003\u9038\u98ce\u9669"
      : "Child-process lane: preflight blocks escape risk before execution";
  }
  if (key === "os_container") {
    return zh
      ? `\u7cfb\u7edf/\u5bb9\u5668\u9694\u79bb\u901a\u9053\uff1a${status}`
      : `OS/container isolated lane: ${status}`;
  }
  if (zh) {
    return `${laneLabel(key, language)}\uff1a${status}`;
  }
  return `${laneLabel(key, language)}: ${status}`;
}

function coachProbeFact(
  probe: SandboxOsContainerExecutorProbeLike | undefined,
  language: SandboxNarrativeLanguage,
): string | undefined {
  if (!probe) {
    return undefined;
  }
  const zh = isZh(language);
  const availability = osContainerProbeAvailabilityLabel(probe.availability, language);
  const runtime =
    normalizeText(probe.selectedRuntime) && probe.selectedRuntime !== "none"
      ? probe.selectedRuntime
      : zh
        ? "\u672a\u9009\u5b9a"
        : "none";
  const supported = uniqueValues(probe.supportedEntryRuntimes);
  const supportLine =
    supported.length > 0
      ? zh
        ? `\u53ef\u7528\u5165\u53e3\uff1a${supported.join(", ")}`
        : `supported entries: ${supported.join(", ")}`
      : undefined;
  return joinFacts([
    zh
      ? `\u7cfb\u7edf/\u5bb9\u5668\u63a2\u6d4b\uff1a${availability} / \u8fd0\u884c\u65f6\uff1a${runtime}`
      : `OS/container probe: ${availability} / runtime: ${runtime}`,
    supportLine,
  ]);
}

export function describeSandboxNetworkCapabilityCoachFacts(
  facts: SandboxNetworkExecutionFactsLike | undefined,
  language: SandboxNarrativeLanguage,
): string[] {
  if (!facts) {
    return [];
  }
  return [
    coachLaneFact("audited_python", facts.auditedPython, language),
    coachLaneFact("unaudited_python", facts.unauditedPython, language),
    coachLaneFact("non_python", facts.nonPython, language),
    coachLaneFact("child_process", facts.childProcess, language),
    coachLaneFact("os_container", facts.osContainer, language),
    coachProbeFact(facts.osContainerProbe, language),
  ].filter((value): value is string => Boolean(value));
}

export function describeSandboxNetworkCapabilityCoachDetail(
  status: SandboxCapabilityStatusLike | undefined,
  language: SandboxNarrativeLanguage,
): string {
  const facts = describeSandboxNetworkCapabilityCoachFacts(status?.networkFacts, language);
  if (facts.length > 0) {
    return facts.join(" | ");
  }
  return fallbackSummary(status, language);
}

function normalizePolicyToken(value: string | undefined): string | undefined {
  const normalized = normalizeText(value);
  return normalized ? normalized.toLowerCase() : undefined;
}

function collectPolicyTokens(values: Array<string | undefined>): string[] {
  const tokens = new Set<string>();
  values.forEach((value) => {
    const normalized = normalizePolicyToken(value);
    if (!normalized) {
      return;
    }
    normalized
      .split(/[;,|\s]+/g)
      .map((item) => item.trim())
      .filter(Boolean)
      .forEach((token) => tokens.add(token));
  });
  return Array.from(tokens);
}

export function describeSkillRuntimeGateCoachPolicyFacts(
  params: {
    state?: string;
    policies?: Array<string | undefined>;
    language: SandboxNarrativeLanguage;
  },
): string[] {
  const language = params.language;
  const zh = isZh(language);
  const tokens = collectPolicyTokens(params.policies ?? []);
  const hasRuntime = tokens.includes(SKILL_RUNTIME_POLICY);
  const hasRunGate = tokens.includes(SKILL_RUN_GATE_POLICY);
  const hasIsolatedExecutor = tokens.includes(SKILL_ISOLATED_EXECUTOR_POLICY);
  const state = normalizePolicyToken(params.state) ?? "not_requested";
  const facts: string[] = [];

  if (hasRuntime) {
    facts.push(
      zh
        ? "预检边界：先验证是否满足安全入口，再决定是否放行。"
        : "Preflight boundary: validates safe entry conditions before any run can proceed.",
    );
  }
  if (hasRunGate) {
    facts.push(
      zh
        ? "运行闸门：请求会先过教练边界，避免越权运行。"
        : "Run gate: requests pass coach boundary checks before execution.",
    );
  }
  if (hasIsolatedExecutor) {
    facts.push(
      zh
        ? "隔离执行器：只有受审计的受控通道才允许联网执行。"
        : "Isolated executor: only audited controlled lanes can run with network access.",
    );
  }

  if (facts.length === 0) {
    if (state === "not_requested") {
      facts.push(
        zh
          ? "当前还没有发起运行请求，系统保持教练只读边界。"
          : "No run has been requested yet; coach-only boundary remains in place.",
      );
    } else {
      facts.push(
        zh
          ? "这次请求仍受教练边界治理，只会按受控流程推进。"
          : "This request remains coach-governed and can only move through controlled flow.",
      );
    }
  }
  return facts;
}

export function describeSkillRuntimeThreatCoachFact(
  threatCategory: string | undefined,
  language: SandboxNarrativeLanguage,
): string | undefined {
  const threat = normalizePolicyToken(threatCategory);
  if (!threat) {
    return undefined;
  }
  const zh = isZh(language);
  if (threat === "network_exfiltration") {
    return zh ? "风险类型：可疑外联行为已被拦截。" : "Risk type: suspicious outbound network behavior was blocked.";
  }
  if (threat === "credential_access") {
    return zh ? "风险类型：凭据访问尝试已被拦截。" : "Risk type: credential access attempt was blocked.";
  }
  if (threat === "path_escape") {
    return zh ? "风险类型：路径越界访问已被拦截。" : "Risk type: path boundary escape was blocked.";
  }
  if (threat === "supply_chain") {
    return zh ? "风险类型：不受信任的执行链路已被拦截。" : "Risk type: untrusted execution chain was blocked.";
  }
  if (threat === "prompt_injection") {
    return zh ? "风险类型：提示注入风险已被拦截。" : "Risk type: prompt-injection risk was blocked.";
  }
  if (threat === "malicious_document") {
    return zh ? "风险类型：可疑文档载荷已被拦截。" : "Risk type: suspicious document payload was blocked.";
  }
  if (threat === "mutation_blocked") {
    return zh ? "风险类型：越权变更尝试已被拦截。" : "Risk type: unauthorized mutation attempt was blocked.";
  }
  return zh ? "风险类型：受控边界拦截了不安全请求。" : "Risk type: controlled boundary blocked an unsafe request.";
}

export function describeSandboxNetworkCapabilityDetail(
  status: SandboxCapabilityStatusLike | undefined,
  language: SandboxNarrativeLanguage,
): string {
  const factLines = describeSandboxNetworkCapabilityFacts(status?.networkFacts, language);
  if (factLines.length > 0) {
    return factLines.join(" | ");
  }
  return fallbackSummary(status, language);
}
