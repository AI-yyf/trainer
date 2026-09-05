import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionDir, "..");
const verifyScript = path.join(__dirname, "verify-vsix-e2e.mjs");

const roundsRequested = readIntegerEnv("TRAINER_E2E_RESOURCE_TRAINING_ROUNDS", 10, 1, 30);
const minPassRate = readFloatEnv("TRAINER_E2E_RESOURCE_TRAINING_MIN_PASS_RATE", 1, 0, 1);
const maxLeakRounds = readIntegerEnv("TRAINER_E2E_RESOURCE_TRAINING_MAX_LEAK_ROUNDS", 0, 0, 30);
const maxBridgeMissingRounds = readIntegerEnv(
  "TRAINER_E2E_RESOURCE_TRAINING_MAX_BRIDGE_MISSING_ROUNDS",
  0,
  0,
  30,
);
const maxNextHopMissingRounds = readIntegerEnv(
  "TRAINER_E2E_RESOURCE_TRAINING_MAX_NEXT_HOP_MISSING_ROUNDS",
  0,
  0,
  30,
);
const maxFaultRecoveryMissRounds = readIntegerEnv(
  "TRAINER_E2E_RESOURCE_TRAINING_MAX_FAULT_RECOVERY_MISS_ROUNDS",
  0,
  0,
  30,
);
const faultProfile = (process.env.TRAINER_E2E_FAULT_PROFILE || "sidecar-restart").trim();
const perRoundTimeoutMs = readIntegerEnv(
  "TRAINER_E2E_RESOURCE_TRAINING_PER_ROUND_TIMEOUT_MS",
  18 * 60 * 1000,
  60_000,
  60 * 60 * 1000,
);
const requireProvider = process.env.TRAINER_E2E_REQUIRE_PROVIDER !== "0";

const providerBaseUrl = (process.env.TRAINER_E2E_PROVIDER_BASE_URL ?? "").trim();
const providerApiKey = (process.env.TRAINER_E2E_PROVIDER_API_KEY ?? "").trim();
const providerModel = (process.env.TRAINER_E2E_PROVIDER_MODEL ?? "").trim();

if (requireProvider && (!providerBaseUrl || !providerApiKey || !providerModel)) {
  fail(
    "Resource-training stability run requires TRAINER_E2E_PROVIDER_BASE_URL, TRAINER_E2E_PROVIDER_API_KEY, and TRAINER_E2E_PROVIDER_MODEL.",
  );
}

if (!fs.existsSync(verifyScript)) {
  fail(`Missing script: ${verifyScript}`);
}

const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
const outputRoot = path.resolve(
  process.env.TRAINER_E2E_RESOURCE_TRAINING_OUTPUT_DIR ||
    path.join(repoRoot, "output", "playwright", "sidebar-audit", "resource-training-stability"),
);
fs.mkdirSync(outputRoot, { recursive: true });

const startedAt = new Date().toISOString();
const suiteStart = Date.now();
const rounds = [];

const criticalStepStats = {
  resourcesDetail: { total: 0, pass: 0, fail: 0, invalidEvidence: 0 },
  resourcesSandboxPreview: { total: 0, pass: 0, fail: 0, invalidEvidence: 0 },
  resourcesSandboxCapability: { total: 0, pass: 0, fail: 0, invalidEvidence: 0 },
  crossWorkspaceRestore: { total: 0, pass: 0, fail: 0, leaks: 0, bridgeMissing: 0 },
  trainingNextHop: { total: 0, pass: 0, fail: 0, missingMaterializedEvent: 0 },
  sidecarFaultRecovery: { total: 0, pass: 0, fail: 0, missed: 0 },
};

for (let index = 1; index <= roundsRequested; index += 1) {
  const roundStamp = new Date().toISOString().replace(/[:.]/g, "-");
  const reportPath = path.join(
    outputRoot,
    `round-${String(index).padStart(2, "0")}-${roundStamp}.json`,
  );
  const roundStart = Date.now();
  const env = {
    ...process.env,
    TRAINER_E2E_EXPORT_REPORT_PATH: reportPath,
    TRAINER_E2E_FAULT_PROFILE: faultProfile,
  };
  const result = spawnSync(process.execPath, [verifyScript], {
    cwd: extensionDir,
    encoding: "utf8",
    env,
    timeout: perRoundTimeoutMs,
  });
  const durationMs = Date.now() - roundStart;

  const parsedStdout = parseJsonOutput(result.stdout ?? "");
  const exported = readJsonIfExists(reportPath);
  const resolved = exported ?? parsedStdout;
  const report = asRecord(resolved?.report);
  const steps = Array.isArray(report?.steps) ? report.steps : [];

  const providerSkipped = steps.some(
    (step) => asRecord(step)?.name === "provider-and-message" && asRecord(step)?.skipped === true,
  );
  const basePass =
    Boolean(asRecord(resolved)?.ok) &&
    result.status === 0 &&
    !result.signal &&
    (!requireProvider || !providerSkipped);

  const detailStep = findStep(steps, "assert-resources-resource-detail-visible-truth");
  const previewStep = findStep(steps, "assert-resources-sandbox-native-open-truth");
  const capabilityStep = findStep(steps, "assert-resources-sandbox-capability-visible-truth");
  const crossStep = findStep(steps, "assert-cross-workspace-reopen-history-truth");
  const nextHopStep = findStep(steps, "assert-training-next-hop-visible-truth");
  const faultStep = findStep(steps, "inject-sidecar-restart-fault");

  const detailStepOk = Boolean(detailStep?.ok);
  const previewStepOk = Boolean(previewStep?.ok);
  const capabilityStepOk = Boolean(capabilityStep?.ok);
  const crossStepOk = Boolean(crossStep?.ok);
  const nextHopStepOk = Boolean(nextHopStep?.ok);
  const faultStepOk = faultProfile ? Boolean(faultStep?.ok) : true;

  const detailData = asRecord(detailStep?.data);
  const previewData = asRecord(previewStep?.data);
  const capabilityData = asRecord(capabilityStep?.data);
  const crossData = asRecord(crossStep?.data);
  const nextHopData = asRecord(nextHopStep?.data);
  const faultData = asRecord(faultStep?.data);

  const detailEvidenceOk = hasResourceDetailEvidence(detailData);
  const previewEvidenceOk = hasSandboxPreviewEvidence(previewData);
  const capabilityEvidenceOk = hasSandboxCapabilityEvidence(capabilityData);
  const crossLeakDetected = detectCrossWorkspaceLeak(crossData);
  const resourceBridgeMissing = !hasResourceBridgeEvidence(crossData);
  const nextHopMissingMaterializedEvent = !hasMaterializedEventEvidence(nextHopData);
  const faultRecoveryMiss = faultProfile ? !hasSidecarFaultRecoveryEvidence(faultData) : false;

  accumulateStat(criticalStepStats.resourcesDetail, detailStepOk, !detailEvidenceOk);
  accumulateStat(criticalStepStats.resourcesSandboxPreview, previewStepOk, !previewEvidenceOk);
  accumulateStat(criticalStepStats.resourcesSandboxCapability, capabilityStepOk, !capabilityEvidenceOk);

  criticalStepStats.crossWorkspaceRestore.total += 1;
  criticalStepStats.crossWorkspaceRestore.pass += crossStepOk ? 1 : 0;
  criticalStepStats.crossWorkspaceRestore.fail += crossStepOk ? 0 : 1;
  criticalStepStats.crossWorkspaceRestore.leaks += crossLeakDetected ? 1 : 0;
  criticalStepStats.crossWorkspaceRestore.bridgeMissing += resourceBridgeMissing ? 1 : 0;

  criticalStepStats.trainingNextHop.total += 1;
  criticalStepStats.trainingNextHop.pass += nextHopStepOk ? 1 : 0;
  criticalStepStats.trainingNextHop.fail += nextHopStepOk ? 0 : 1;
  criticalStepStats.trainingNextHop.missingMaterializedEvent +=
    nextHopMissingMaterializedEvent ? 1 : 0;

  criticalStepStats.sidecarFaultRecovery.total += 1;
  criticalStepStats.sidecarFaultRecovery.pass += faultStepOk ? 1 : 0;
  criticalStepStats.sidecarFaultRecovery.fail += faultStepOk ? 0 : 1;
  criticalStepStats.sidecarFaultRecovery.missed += faultRecoveryMiss ? 1 : 0;

  const roundOk =
    basePass &&
    detailStepOk &&
    previewStepOk &&
    capabilityStepOk &&
    crossStepOk &&
    nextHopStepOk &&
    detailEvidenceOk &&
    previewEvidenceOk &&
    capabilityEvidenceOk &&
    !crossLeakDetected &&
    !resourceBridgeMissing &&
    !nextHopMissingMaterializedEvent &&
    faultStepOk &&
    !faultRecoveryMiss;

  const failedReasons = [];
  if (!basePass) {
    failedReasons.push("base-e2e-failed");
  }
  if (!detailStepOk) {
    failedReasons.push("resources-detail-step-failed");
  }
  if (!detailEvidenceOk) {
    failedReasons.push("resources-detail-evidence-mismatch");
  }
  if (!previewStepOk) {
    failedReasons.push("resources-sandbox-native-open-step-failed");
  }
  if (!previewEvidenceOk) {
    failedReasons.push("resources-sandbox-native-open-evidence-mismatch");
  }
  if (!capabilityStepOk) {
    failedReasons.push("resources-sandbox-capability-step-failed");
  }
  if (!capabilityEvidenceOk) {
    failedReasons.push("resources-sandbox-capability-evidence-mismatch");
  }
  if (!crossStepOk) {
    failedReasons.push("cross-workspace-step-failed");
  }
  if (crossLeakDetected) {
    failedReasons.push("cross-workspace-leak-detected");
  }
  if (resourceBridgeMissing) {
    failedReasons.push("resource-to-training-bridge-missing");
  }
  if (!nextHopStepOk) {
    failedReasons.push("next-hop-step-failed");
  }
  if (nextHopMissingMaterializedEvent) {
    failedReasons.push("next-hop-materialized-event-missing");
  }
  if (!faultStepOk) {
    failedReasons.push("sidecar-fault-step-failed");
  }
  if (faultRecoveryMiss) {
    failedReasons.push("sidecar-fault-recovery-miss");
  }

  rounds.push({
    index,
    ok: roundOk,
    durationMs,
    exitCode: result.status,
    signal: result.signal ?? null,
    reportPath,
    providerSkipped,
    failedReasons,
    resourcesDetail: summarizeResourceDetailRound(detailData, detailStepOk, detailEvidenceOk),
    resourcesSandboxPreview: summarizeSandboxPreviewRound(previewData, previewStepOk, previewEvidenceOk),
    resourcesSandboxCapability: summarizeSandboxCapabilityRound(
      capabilityData,
      capabilityStepOk,
      capabilityEvidenceOk,
    ),
    crossWorkspace: summarizeCrossWorkspaceRound(
      crossData,
      crossStepOk,
      crossLeakDetected,
      resourceBridgeMissing,
    ),
    nextHop: summarizeNextHopRound(nextHopData, nextHopStepOk, nextHopMissingMaterializedEvent),
    sidecarFaultRecovery: summarizeSidecarFaultRound(faultData, faultStepOk, faultRecoveryMiss),
  });

  const status = roundOk ? "PASS" : "FAIL";
  const reasonSuffix = failedReasons.length ? ` reasons=${failedReasons.join(",")}` : "";
  console.log(
    `[resource-training][round ${String(index).padStart(2, "0")}/${String(roundsRequested).padStart(2, "0")}] ${status} duration=${durationMs}ms${reasonSuffix} report=${reportPath}`,
  );
}

const completedAt = new Date().toISOString();
const totalDurationMs = Date.now() - suiteStart;
const passCount = rounds.filter((round) => round.ok).length;
const failCount = rounds.length - passCount;
const passRate = rounds.length > 0 ? passCount / rounds.length : 0;
const leakRounds = rounds.filter((round) => round.crossWorkspace.leakDetected).length;
const bridgeMissingRounds = rounds.filter((round) => round.crossWorkspace.resourceBridgeMissing).length;
const nextHopMaterializedEventMissingRounds = rounds.filter(
  (round) => round.nextHop.materializedEventMissing,
).length;
const faultRecoveryMissRounds = rounds.filter((round) => round.sidecarFaultRecovery.missed).length;

const summary = {
  ok:
    passRate >= minPassRate &&
    leakRounds <= maxLeakRounds &&
    bridgeMissingRounds <= maxBridgeMissingRounds &&
    nextHopMaterializedEventMissingRounds <= maxNextHopMissingRounds &&
    faultRecoveryMissRounds <= maxFaultRecoveryMissRounds,
  startedAt,
  completedAt,
  roundsRequested,
  roundsCompleted: rounds.length,
  passCount,
  failCount,
  passRate,
  minPassRate,
  leakRounds,
  maxLeakRounds,
  bridgeMissingRounds,
  maxBridgeMissingRounds,
  nextHopMaterializedEventMissingRounds,
  maxNextHopMissingRounds,
  faultProfile,
  faultRecoveryMissRounds,
  maxFaultRecoveryMissRounds,
  requireProvider,
  durationMs: {
    total: totalDurationMs,
    average: rounds.length
      ? Math.round(rounds.reduce((acc, round) => acc + round.durationMs, 0) / rounds.length)
      : 0,
    min: rounds.length ? Math.min(...rounds.map((round) => round.durationMs)) : 0,
    max: rounds.length ? Math.max(...rounds.map((round) => round.durationMs)) : 0,
  },
  criticalStepStats,
  outputRoot,
  rounds,
};

const summaryPath = path.join(outputRoot, `resource-training-summary-${timestamp}.json`);
const latestSummaryPath = path.join(outputRoot, "resource-training-summary-latest.json");
fs.writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
fs.writeFileSync(latestSummaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");

console.log(
  [
    "[resource-training][summary]",
    `rounds=${rounds.length}`,
    `pass=${passCount}`,
    `fail=${failCount}`,
    `passRate=${(passRate * 100).toFixed(2)}%`,
    `leakRounds=${leakRounds}`,
    `bridgeMissingRounds=${bridgeMissingRounds}`,
    `nextHopMaterializedEventMissingRounds=${nextHopMaterializedEventMissingRounds}`,
    `faultRecoveryMissRounds=${faultRecoveryMissRounds}`,
    `summary=${summaryPath}`,
  ].join(" "),
);

if (!summary.ok) {
  fail(
    `Resource-training stability threshold failed: passRate=${(passRate * 100).toFixed(
      2,
    )}% (min ${(minPassRate * 100).toFixed(2)}%), leakRounds=${leakRounds} (max ${maxLeakRounds}), bridgeMissingRounds=${bridgeMissingRounds} (max ${maxBridgeMissingRounds}), nextHopMissing=${nextHopMaterializedEventMissingRounds} (max ${maxNextHopMissingRounds}), faultRecoveryMissRounds=${faultRecoveryMissRounds} (max ${maxFaultRecoveryMissRounds}).`,
  );
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : undefined;
}

function findStep(steps, name) {
  return steps.find((step) => asRecord(step)?.name === name);
}

function accumulateStat(stat, stepOk, invalidEvidence) {
  stat.total += 1;
  stat.pass += stepOk ? 1 : 0;
  stat.fail += stepOk ? 0 : 1;
  stat.invalidEvidence += invalidEvidence ? 1 : 0;
}

function detectCrossWorkspaceLeak(crossData) {
  if (!crossData) {
    return true;
  }
  const userLeak = crossData.userLeaksOldWorkspaceMarker === true;
  const historyLeak = crossData.historyLeaksOldWorkspaceMarker === true;
  const routeMismatch =
    typeof crossData.workspaceId === "string" &&
    typeof crossData.trainingRouteWorkspaceId === "string" &&
    crossData.workspaceId.length > 0 &&
    crossData.trainingRouteWorkspaceId.length > 0 &&
    crossData.workspaceId !== crossData.trainingRouteWorkspaceId;
  return userLeak || historyLeak || routeMismatch;
}

function hasMaterializedEventEvidence(nextHopData) {
  if (!nextHopData) {
    return false;
  }
  return Boolean(
    nextHopData.hasMaterializedEvent === true ||
      nextHopData.bootstrapLatestMaterializedEventType === "training_next_hop_materialized",
  );
}

function hasResourceBridgeEvidence(crossData) {
  if (!crossData) {
    return false;
  }
  const resourceNames = Array.isArray(crossData.resourceNames) ? crossData.resourceNames : [];
  const hasExpectedResource = resourceNames.includes("VSIX Reopen Resource");
  const detailNameMatches = crossData.resourceDetailName === "VSIX Reopen Resource";
  const summaryText = String(crossData.resourceDetailSummary ?? "");
  const summaryLooksCorrect = /installed extension authoritative/i.test(summaryText);
  return hasExpectedResource && detailNameMatches && summaryLooksCorrect;
}

function hasResourceDetailEvidence(detailData) {
  if (!detailData) {
    return false;
  }
  return Boolean(
    detailData.hasVisibleFacts === true &&
      detailData.surface === "resources" &&
      detailData.activeView === "resources" &&
      detailData.activeSurface === "detail" &&
      detailData.resourceDetailVisible === true &&
      typeof detailData.resourceId === "string" &&
      detailData.resourceId.length > 0 &&
      detailData.resourceDetailId === detailData.resourceId &&
      detailData.selectedResourceId === detailData.resourceId &&
      typeof detailData.resourceDetailTitle === "string" &&
      detailData.resourceDetailTitle.length > 0 &&
      detailData.singleWorkbenchSurface === true &&
      detailData.compactMode === true &&
      detailData.detailPaneVisible === true &&
      detailData.sandboxPaneVisible === false &&
      detailData.previewPaneVisible === false,
  );
}

function hasSandboxPreviewEvidence(previewData) {
  if (!previewData) {
    return false;
  }
  return Boolean(
    previewData.nativeOpen === true &&
      previewData.nativeOpenPath === previewData.sandboxPath &&
      typeof previewData.sandboxPath === "string" &&
      previewData.sandboxPath.length > 0,
  );
}

function hasSandboxCapabilityEvidence(capabilityData) {
  if (!capabilityData) {
    return false;
  }
  return Boolean(
    capabilityData.hasVisibleFacts === true &&
      capabilityData.surface === "resources" &&
      capabilityData.activeView === "resources" &&
      capabilityData.activeSurface === "sandbox" &&
      capabilityData.permissionState === "coach_only" &&
      capabilityData.networkExecutionStatus === "degraded" &&
      typeof capabilityData.networkReasonCode === "string" &&
      capabilityData.networkReasonCode.length > 0 &&
      capabilityData.singleWorkbenchSurface === true &&
      capabilityData.compactMode === true &&
      capabilityData.modebarHiddenInCompact === true,
  );
}

function summarizeCrossWorkspaceRound(crossData, stepOk, leakDetected, resourceBridgeMissing) {
  return {
    stepOk,
    leakDetected,
    resourceBridgeMissing,
    workspaceId: crossData?.workspaceId ?? null,
    trainingRouteWorkspaceId: crossData?.trainingRouteWorkspaceId ?? null,
    userLeak: crossData?.userLeaksOldWorkspaceMarker === true,
    historyLeak: crossData?.historyLeaksOldWorkspaceMarker === true,
    resourceNames: Array.isArray(crossData?.resourceNames) ? crossData.resourceNames : [],
    resourceDetailName: crossData?.resourceDetailName ?? null,
  };
}

function summarizeNextHopRound(nextHopData, stepOk, materializedEventMissing) {
  return {
    stepOk,
    materializedEventMissing,
    hasMaterializedEvent: nextHopData?.hasMaterializedEvent === true,
    bootstrapLatestMaterializedEventType: nextHopData?.bootstrapLatestMaterializedEventType ?? null,
    candidateType: nextHopData?.nextHopCandidateType ?? null,
    targetId: nextHopData?.nextHopTargetId ?? null,
  };
}

function summarizeResourceDetailRound(detailData, stepOk, evidenceOk) {
  return {
    stepOk,
    evidenceOk,
    activeSurface: detailData?.activeSurface ?? null,
    resourceId: detailData?.resourceId ?? null,
    resourceDetailId: detailData?.resourceDetailId ?? null,
    detailPaneVisible: detailData?.detailPaneVisible === true,
  };
}

function summarizeSandboxPreviewRound(previewData, stepOk, evidenceOk) {
  return {
    stepOk,
    evidenceOk,
    sandboxPath: previewData?.sandboxPath ?? null,
    nativeOpen: previewData?.nativeOpen === true,
    nativeOpenPath: previewData?.nativeOpenPath ?? null,
  };
}

function summarizeSandboxCapabilityRound(capabilityData, stepOk, evidenceOk) {
  return {
    stepOk,
    evidenceOk,
    activeSurface: capabilityData?.activeSurface ?? null,
    permissionState: capabilityData?.permissionState ?? null,
    networkExecutionStatus: capabilityData?.networkExecutionStatus ?? null,
    networkReasonCode: capabilityData?.networkReasonCode ?? null,
  };
}

function hasSidecarFaultRecoveryEvidence(faultData) {
  if (!faultData) {
    return false;
  }
  return Boolean(
    faultData.stoppedOk === true &&
      faultData.restartedOk === true &&
      faultData.restartedLifecycle === "ready" &&
      Number.isFinite(faultData.restartedPort) &&
      faultData.healthOk === true &&
      faultData.recoveredMemoryOk === true,
  );
}

function summarizeSidecarFaultRound(faultData, stepOk, missed) {
  return {
    stepOk,
    missed,
    stoppedOk: faultData?.stoppedOk === true,
    restartedOk: faultData?.restartedOk === true,
    restartedLifecycle: faultData?.restartedLifecycle ?? null,
    restartedPort: faultData?.restartedPort ?? null,
    healthOk: faultData?.healthOk === true,
    recoveredMemoryOk: faultData?.recoveredMemoryOk === true,
  };
}

function parseJsonOutput(text) {
  const trimmed = (text ?? "").trim();
  if (!trimmed) {
    return undefined;
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    const firstBrace = trimmed.indexOf("{");
    if (firstBrace < 0) {
      return undefined;
    }
    try {
      return JSON.parse(trimmed.slice(firstBrace));
    } catch {
      return undefined;
    }
  }
}

function readJsonIfExists(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return undefined;
    }
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return undefined;
  }
}

function readIntegerEnv(name, fallback, min, max) {
  const raw = process.env[name];
  if (!raw || !raw.trim()) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return clamp(parsed, min, max);
}

function readFloatEnv(name, fallback, min, max) {
  const raw = process.env[name];
  if (!raw || !raw.trim()) {
    return fallback;
  }
  const parsed = Number.parseFloat(raw);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return clamp(parsed, min, max);
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function fail(message) {
  console.error(`[resource-training] ${message}`);
  process.exit(1);
}
