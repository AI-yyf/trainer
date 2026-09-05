import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionDir, "..");
const verifyScript = path.join(__dirname, "verify-vsix-e2e.mjs");

const roundsRequested = readIntegerEnv("TRAINER_E2E_MULTI_WORKSPACE_ROUNDS", 3, 1, 20);
const minPassRate = readFloatEnv("TRAINER_E2E_MULTI_WORKSPACE_MIN_PASS_RATE", 1, 0, 1);
const maxLeakRounds = readIntegerEnv("TRAINER_E2E_MULTI_WORKSPACE_MAX_LEAK_ROUNDS", 0, 0, 20);
const perRoundTimeoutMs = readIntegerEnv(
  "TRAINER_E2E_MULTI_WORKSPACE_PER_ROUND_TIMEOUT_MS",
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
    "Multi-workspace stability run requires TRAINER_E2E_PROVIDER_BASE_URL, TRAINER_E2E_PROVIDER_API_KEY, and TRAINER_E2E_PROVIDER_MODEL.",
  );
}

if (!fs.existsSync(verifyScript)) {
  fail(`Missing script: ${verifyScript}`);
}

const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
const outputRoot = path.resolve(
  process.env.TRAINER_E2E_MULTI_WORKSPACE_OUTPUT_DIR ||
    path.join(repoRoot, "output", "playwright", "sidebar-audit", "multi-workspace-stability"),
);
fs.mkdirSync(outputRoot, { recursive: true });

const startedAt = new Date().toISOString();
const suiteStart = Date.now();
const rounds = [];

const criticalStepStats = {
  crossWorkspaceRestore: { total: 0, pass: 0, fail: 0, leaks: 0 },
  trainingNextHop: { total: 0, pass: 0, fail: 0, missingMaterializedEvent: 0 },
  topTitleThemeTypography: { total: 0, pass: 0, fail: 0 },
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

  const crossStep = findStep(steps, "assert-cross-workspace-reopen-history-truth");
  const nextHopStep = findStep(steps, "assert-training-next-hop-visible-truth");
  const titleThemeStep = findStep(steps, "assert-top-title-and-theme-typography-truth");

  const crossStepOk = Boolean(crossStep?.ok);
  const nextHopStepOk = Boolean(nextHopStep?.ok);
  const titleThemeStepOk = Boolean(titleThemeStep?.ok);

  const crossData = asRecord(crossStep?.data);
  const nextHopData = asRecord(nextHopStep?.data);
  const crossLeakDetected = detectCrossWorkspaceLeak(crossData);
  const nextHopMissingMaterializedEvent = !hasMaterializedEventEvidence(nextHopData);

  criticalStepStats.crossWorkspaceRestore.total += 1;
  criticalStepStats.crossWorkspaceRestore.pass += crossStepOk ? 1 : 0;
  criticalStepStats.crossWorkspaceRestore.fail += crossStepOk ? 0 : 1;
  criticalStepStats.crossWorkspaceRestore.leaks += crossLeakDetected ? 1 : 0;

  criticalStepStats.trainingNextHop.total += 1;
  criticalStepStats.trainingNextHop.pass += nextHopStepOk ? 1 : 0;
  criticalStepStats.trainingNextHop.fail += nextHopStepOk ? 0 : 1;
  criticalStepStats.trainingNextHop.missingMaterializedEvent +=
    nextHopMissingMaterializedEvent ? 1 : 0;

  criticalStepStats.topTitleThemeTypography.total += 1;
  criticalStepStats.topTitleThemeTypography.pass += titleThemeStepOk ? 1 : 0;
  criticalStepStats.topTitleThemeTypography.fail += titleThemeStepOk ? 0 : 1;

  const roundOk =
    basePass &&
    crossStepOk &&
    nextHopStepOk &&
    titleThemeStepOk &&
    !crossLeakDetected &&
    !nextHopMissingMaterializedEvent;

  const failedReasons = [];
  if (!basePass) {
    failedReasons.push("base-e2e-failed");
  }
  if (!crossStepOk) {
    failedReasons.push("cross-workspace-step-failed");
  }
  if (!nextHopStepOk) {
    failedReasons.push("next-hop-step-failed");
  }
  if (!titleThemeStepOk) {
    failedReasons.push("title-theme-step-failed");
  }
  if (crossLeakDetected) {
    failedReasons.push("cross-workspace-leak-detected");
  }
  if (nextHopMissingMaterializedEvent) {
    failedReasons.push("next-hop-materialized-event-missing");
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
    crossWorkspace: summarizeCrossWorkspaceRound(crossData, crossStepOk, crossLeakDetected),
    nextHop: summarizeNextHopRound(nextHopData, nextHopStepOk, nextHopMissingMaterializedEvent),
    topTitleThemeTypography: {
      stepOk: titleThemeStepOk,
      expectedThemesCovered: extractThemeCoverage(titleThemeStep?.data),
    },
  });

  const status = roundOk ? "PASS" : "FAIL";
  const reasonSuffix = failedReasons.length ? ` reasons=${failedReasons.join(",")}` : "";
  console.log(
    `[multi-workspace][round ${String(index).padStart(2, "0")}/${String(roundsRequested).padStart(2, "0")}] ${status} duration=${durationMs}ms${reasonSuffix} report=${reportPath}`,
  );
}

const completedAt = new Date().toISOString();
const totalDurationMs = Date.now() - suiteStart;
const passCount = rounds.filter((round) => round.ok).length;
const failCount = rounds.length - passCount;
const passRate = rounds.length > 0 ? passCount / rounds.length : 0;
const leakRounds = rounds.filter((round) => round.crossWorkspace.leakDetected).length;
const nextHopMaterializedEventMissingRounds = rounds.filter(
  (round) => round.nextHop.materializedEventMissing,
).length;

const summary = {
  ok: passRate >= minPassRate && leakRounds <= maxLeakRounds,
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
  nextHopMaterializedEventMissingRounds,
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

const summaryPath = path.join(outputRoot, `multi-workspace-summary-${timestamp}.json`);
const latestSummaryPath = path.join(outputRoot, "multi-workspace-summary-latest.json");
fs.writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
fs.writeFileSync(latestSummaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");

console.log(
  [
    "[multi-workspace][summary]",
    `rounds=${rounds.length}`,
    `pass=${passCount}`,
    `fail=${failCount}`,
    `passRate=${(passRate * 100).toFixed(2)}%`,
    `leakRounds=${leakRounds}`,
    `nextHopMaterializedEventMissingRounds=${nextHopMaterializedEventMissingRounds}`,
    `summary=${summaryPath}`,
  ].join(" "),
);

if (!summary.ok) {
  fail(
    `Multi-workspace stability threshold failed: passRate=${(passRate * 100).toFixed(
      2,
    )}% (min ${(minPassRate * 100).toFixed(2)}%), leakRounds=${leakRounds} (max ${maxLeakRounds}).`,
  );
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : undefined;
}

function findStep(steps, name) {
  return steps.find((step) => asRecord(step)?.name === name);
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

function summarizeCrossWorkspaceRound(crossData, stepOk, leakDetected) {
  return {
    stepOk,
    leakDetected,
    workspaceId: crossData?.workspaceId ?? null,
    trainingRouteWorkspaceId: crossData?.trainingRouteWorkspaceId ?? null,
    userLeak: crossData?.userLeaksOldWorkspaceMarker === true,
    historyLeak: crossData?.historyLeaksOldWorkspaceMarker === true,
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

function extractThemeCoverage(data) {
  const record = asRecord(data);
  const themeRuns = Array.isArray(record?.themeRuns) ? record.themeRuns : [];
  return themeRuns.map((run) => ({
    id: asRecord(run)?.id ?? null,
    kindMatch: asRecord(run)?.kindMatch === true,
    screenshotExists: asRecord(asRecord(run)?.screenshot)?.exists === true,
  }));
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
  console.error(`[multi-workspace] ${message}`);
  process.exit(1);
}
