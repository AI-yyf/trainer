import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionDir, "..");
const verifyScript = path.join(__dirname, "verify-vsix-e2e.mjs");

const roundsRequested = readIntegerEnv("TRAINER_E2E_STABILITY_ROUNDS", 5, 1, 50);
const minPassRate = readFloatEnv("TRAINER_E2E_STABILITY_MIN_PASS_RATE", 1, 0, 1);
const perRoundTimeoutMs = readIntegerEnv(
  "TRAINER_E2E_STABILITY_PER_ROUND_TIMEOUT_MS",
  15 * 60 * 1000,
  60_000,
  60 * 60 * 1000,
);
const requireProvider = process.env.TRAINER_E2E_REQUIRE_PROVIDER !== "0";

const providerBaseUrl = (process.env.TRAINER_E2E_PROVIDER_BASE_URL ?? "").trim();
const providerApiKey = (process.env.TRAINER_E2E_PROVIDER_API_KEY ?? "").trim();
const providerModel = (process.env.TRAINER_E2E_PROVIDER_MODEL ?? "").trim();

if (requireProvider && (!providerBaseUrl || !providerApiKey || !providerModel)) {
  fail(
    "Stability run requires TRAINER_E2E_PROVIDER_BASE_URL, TRAINER_E2E_PROVIDER_API_KEY, and TRAINER_E2E_PROVIDER_MODEL.",
  );
}

if (!fs.existsSync(verifyScript)) {
  fail(`Missing script: ${verifyScript}`);
}

const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
const outputRoot = path.resolve(
  process.env.TRAINER_E2E_STABILITY_OUTPUT_DIR ||
    path.join(repoRoot, "output", "playwright", "sidebar-audit", "stability"),
);
fs.mkdirSync(outputRoot, { recursive: true });

const rounds = [];
const stepStats = new Map();
const startedAt = new Date().toISOString();
const overallStart = Date.now();
let timeoutSignatureCount = 0;

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
    (step) =>
      asRecord(step)?.name === "provider-and-message" && asRecord(step)?.skipped === true,
  );
  const skippedReason = providerSkipped
    ? String(
        asRecord(
          steps.find(
            (step) =>
              asRecord(step)?.name === "provider-and-message" &&
              asRecord(step)?.skipped === true,
          ),
        )?.reason ?? "",
      )
    : undefined;

  let roundOk =
    Boolean(asRecord(resolved)?.ok) &&
    result.status === 0 &&
    !result.signal &&
    (!requireProvider || !providerSkipped);

  const stepFailures = [];
  let roundTimeoutSignatures = 0;
  for (const rawStep of steps) {
    const step = asRecord(rawStep);
    if (!step || typeof step.name !== "string") {
      continue;
    }
    const name = step.name;
    const ok = Boolean(step.ok);
    const errorText = String(step.error ?? "");
    const timedOut = isTimeoutSignature(errorText);
    if (!ok) {
      stepFailures.push({
        name,
        error: errorText || "Unknown step failure",
      });
    }
    if (timedOut) {
      roundTimeoutSignatures += 1;
    }
    const entry = stepStats.get(name) ?? {
      total: 0,
      pass: 0,
      fail: 0,
      timeoutSignatures: 0,
      skipped: 0,
    };
    entry.total += 1;
    if (step.skipped === true) {
      entry.skipped += 1;
    } else if (ok) {
      entry.pass += 1;
    } else {
      entry.fail += 1;
    }
    if (timedOut) {
      entry.timeoutSignatures += 1;
    }
    stepStats.set(name, entry);
  }

  const stderrTimeout = isTimeoutSignature(result.stderr ?? "");
  const stdoutTimeout = isTimeoutSignature(result.stdout ?? "");
  if (stderrTimeout || stdoutTimeout) {
    roundTimeoutSignatures += 1;
  }
  timeoutSignatureCount += roundTimeoutSignatures;

  if (requireProvider && providerSkipped) {
    roundOk = false;
    stepFailures.push({
      name: "provider-and-message",
      error:
        skippedReason ||
        "Provider steps were skipped even though TRAINER_E2E_REQUIRE_PROVIDER=1.",
    });
  }

  const round = {
    index,
    ok: roundOk,
    durationMs,
    exitCode: result.status,
    signal: result.signal ?? null,
    reportPath,
    providerSkipped,
    timeoutSignatureCount: roundTimeoutSignatures,
    failureCount: stepFailures.length,
    failedSteps: stepFailures,
  };
  rounds.push(round);

  const statusText = roundOk ? "PASS" : "FAIL";
  const timeoutText =
    roundTimeoutSignatures > 0
      ? ` timeout-signatures=${roundTimeoutSignatures}`
      : "";
  console.log(
    `[stability][round ${String(index).padStart(2, "0")}/${String(roundsRequested).padStart(2, "0")}] ${statusText} duration=${durationMs}ms${timeoutText} report=${reportPath}`,
  );
}

const completedAt = new Date().toISOString();
const totalDurationMs = Date.now() - overallStart;
const passCount = rounds.filter((round) => round.ok).length;
const failCount = rounds.length - passCount;
const passRate = rounds.length > 0 ? passCount / rounds.length : 0;
const thresholdMet = passRate >= minPassRate;

const durations = rounds.map((round) => round.durationMs);
const minDurationMs = durations.length > 0 ? Math.min(...durations) : 0;
const maxDurationMs = durations.length > 0 ? Math.max(...durations) : 0;
const avgDurationMs =
  durations.length > 0
    ? Math.round(durations.reduce((acc, value) => acc + value, 0) / durations.length)
    : 0;

const perStep = Object.fromEntries(
  Array.from(stepStats.entries())
    .sort((left, right) => left[0].localeCompare(right[0]))
    .map(([name, stats]) => [name, stats]),
);

const sendCoachStats = perStep["send-coach-message"] ?? {
  total: 0,
  pass: 0,
  fail: 0,
  timeoutSignatures: 0,
  skipped: 0,
};

const summary = {
  ok: thresholdMet,
  startedAt,
  completedAt,
  roundsRequested,
  roundsCompleted: rounds.length,
  passCount,
  failCount,
  passRate,
  minPassRate,
  requireProvider,
  timeoutSignatureCount,
  durationMs: {
    total: totalDurationMs,
    min: minDurationMs,
    max: maxDurationMs,
    average: avgDurationMs,
  },
  sendCoachMessage: sendCoachStats,
  outputRoot,
  rounds,
  perStep,
};

const summaryPath = path.join(outputRoot, `stability-summary-${timestamp}.json`);
const latestSummaryPath = path.join(outputRoot, "stability-summary-latest.json");
fs.writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
fs.writeFileSync(latestSummaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");

console.log(
  [
    "[stability][summary]",
    `rounds=${rounds.length}`,
    `pass=${passCount}`,
    `fail=${failCount}`,
    `passRate=${(passRate * 100).toFixed(2)}%`,
    `send-coach-message(pass/fail/skip)=${sendCoachStats.pass}/${sendCoachStats.fail}/${sendCoachStats.skipped}`,
    `timeout-signatures=${timeoutSignatureCount}`,
    `summary=${summaryPath}`,
  ].join(" "),
);

if (!thresholdMet) {
  fail(
    `Stability threshold not met: passRate=${(passRate * 100).toFixed(
      2,
    )}% < minPassRate=${(minPassRate * 100).toFixed(2)}%.`,
  );
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : undefined;
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
    if (firstBrace >= 0) {
      const candidate = trimmed.slice(firstBrace);
      try {
        return JSON.parse(candidate);
      } catch {
        return undefined;
      }
    }
    return undefined;
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

function isTimeoutSignature(text) {
  const normalized = String(text ?? "");
  if (!normalized) {
    return false;
  }
  return /\btimeout\b|timed out|etimedout|status code 408|\(408\)|\b504\b/i.test(normalized);
}

function fail(message) {
  console.error(`[stability] ${message}`);
  process.exit(1);
}
