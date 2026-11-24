#!/usr/bin/env node
/**
 * Black-box checks against the sidecar binary that actually ships in the VSIX.
 *
 * The unit suites run the Python sources. This gate runs the frozen native
 * executable from `extension/bundled/bin/<platform>-<arch>/` and proves the
 * delivered runtime still enforces the behaviours the sources were fixed for:
 *
 *   1. the per-instance token guard (no token -> 401);
 *   2. a versioned plan refuses a save without `expected_revision` (428),
 *      accepts the observed head, and reports a stale head as 409;
 *   3. two sidecar processes over one data directory — the real two-window
 *      shape — keep BOTH processes' memory settings instead of the later
 *      whole-object write erasing the earlier one.
 *
 * Everything goes through HTTP plus a direct read of the SQLite file; the
 * dev virtualenv is only used to seed one plan and to read the stored truth.
 *
 * Usage: node scripts/verify-frozen-sidecar-fixes.mjs
 * Exit codes: 0 = green, 1 = a check failed, 2 = prerequisite missing.
 */
import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const extensionDir = path.join(repoRoot, "extension");
const serverDir = path.join(repoRoot, "server");

const WORKSPACE_ID = "frozen-sidecar-probe";
const PLAN_ID = "frozen-probe-plan";
const PLAN_TITLE_ACCEPTED = "Renamed with the observed revision";
const PLAN_TITLE_STALE = "Stale save must never land";

// A content-changing plan save is gated on a usable provider (the real host
// configures one through its preflight). The probe supplies a one-request
// override so the revision checks are reached without a live model: a title
// change never calls the provider.
const PROBE_PROVIDER = {
  name: "frozen-probe",
  baseUrl: "http://127.0.0.1:9/v1",
  apiKeyRef: "trainer.frozen-probe",
  model: "probe-model",
  capabilities: { chat: true, streaming: true },
};

const results = [];
function record(name, ok, detail = {}) {
  results.push({ name, ok: ok === true, ...detail });
  console.log(`  ${ok === true ? "ok " : "FAIL"}  ${name}${detail && Object.keys(detail).length ? ` — ${JSON.stringify(detail)}` : ""}`);
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function sidecarBinaryPath() {
  const executable = process.platform === "win32" ? "trainer-sidecar.exe" : "trainer-sidecar";
  const directory = path.join(extensionDir, "bundled", "bin", `${process.platform}-${process.arch}`);
  return (
    [path.join(directory, executable), path.join(directory, "trainer-sidecar", executable)].find(
      (candidate) => fs.existsSync(candidate),
    ) ?? path.join(directory, executable)
  );
}

function devPythonPath() {
  return process.platform === "win32"
    ? path.join(serverDir, ".venv", "Scripts", "python.exe")
    : path.join(serverDir, ".venv", "bin", "python");
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function runPython(source, args) {
  const result = spawnSync(devPythonPath(), ["-c", source, ...args], {
    cwd: serverDir,
    encoding: "utf8",
    env: { ...process.env, PYTHONUTF8: "1" },
  });
  if (result.status !== 0) {
    throw new Error(`python helper failed (${result.status}): ${result.stderr || result.stdout}`);
  }
  return JSON.parse(result.stdout.trim().split("\n").at(-1));
}

const SEED_PLAN = `
import json, sys
from pathlib import Path
from app.core.models import LearningPlan, PlanStage
from app.db.repository import TrainerRepository
repository = TrainerRepository(Path(sys.argv[1]))
plan = LearningPlan(
    id=sys.argv[3],
    title="Frozen probe plan",
    summary="Plan used by the frozen-sidecar black-box probe.",
    current_step="Read the first step",
    why_now="Probe the delivered runtime.",
    next_after_current="Probe complete",
    stages=[PlanStage(id="stage-1", title="Step one", goal="Read the first step", outcomes=["step read"], status="active")],
)
repository.save_plan(sys.argv[2], plan)
print(json.dumps({"revision": repository.get_plan_revision(sys.argv[2], plan.id)}))
`;

const READ_TRUTH = `
import json, sys
from pathlib import Path
from app.db.repository import TrainerRepository
repository = TrainerRepository(Path(sys.argv[1]))
entry = repository.load_structured_memory_entry(sys.argv[2])
plan_record = repository.get_plan_by_id(sys.argv[3])
print(json.dumps({
    "memory": entry[0] if entry else None,
    "plan_title": plan_record[1].title if plan_record else None,
    "plan_revision": repository.get_plan_revision(sys.argv[2], sys.argv[3]) if plan_record else None,
}))
`;

async function main() {
  const binary = sidecarBinaryPath();
  const python = devPythonPath();
  if (!fs.existsSync(binary)) {
    console.error(`Frozen sidecar binary missing: ${binary}. Build it first (npm run package:vsix).`);
    process.exitCode = 2;
    return;
  }
  if (!fs.existsSync(python)) {
    console.error(`Server dev virtualenv missing: ${python}. Run npm run bootstrap.`);
    process.exitCode = 2;
    return;
  }

  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-frozen-probe-"));
  const database = path.join(dataDir, "trainer.sqlite3");
  const token = crypto.randomBytes(24).toString("base64url");
  const children = [];
  const logs = new Map();

  const startSidecar = async (label) => {
    const port = await freePort();
    const child = spawn(binary, ["--host", "127.0.0.1", "--port", String(port)], {
      cwd: path.dirname(binary),
      env: { ...process.env, TRAINER_DATA_DIR: dataDir, TRAINER_SIDECAR_TOKEN: token },
      stdio: ["ignore", "pipe", "pipe"],
    });
    logs.set(label, "");
    child.stdout.on("data", (chunk) => logs.set(label, logs.get(label) + chunk.toString()));
    child.stderr.on("data", (chunk) => logs.set(label, logs.get(label) + chunk.toString()));
    children.push(child);
    const baseUrl = `http://127.0.0.1:${port}`;
    const deadline = Date.now() + 40_000;
    while (Date.now() < deadline) {
      try {
        const response = await fetch(`${baseUrl}/health`, { headers: { "x-trainer-token": token } });
        if (response.ok) return { baseUrl, port };
      } catch {
        // still booting
      }
      await sleep(250);
    }
    throw new Error(`sidecar ${label} never became healthy. Log tail:\n${logs.get(label).slice(-2000)}`);
  };

  const call = async (baseUrl, route, { method = "POST", body, authorized = true } = {}) => {
    const headers = {};
    if (body !== undefined) headers["content-type"] = "application/json";
    if (authorized) headers["x-trainer-token"] = token;
    const response = await fetch(`${baseUrl}${route}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let json;
    try {
      json = JSON.parse(text);
    } catch {
      json = undefined;
    }
    return { status: response.status, json, text };
  };

  const stopChildren = async () => {
    for (const child of children) {
      if (child.exitCode !== null || child.signalCode !== null) continue;
      child.kill("SIGTERM");
    }
    await sleep(800);
    for (const child of children) {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    }
    await sleep(300);
  };

  try {
    const first = await startSidecar("first");
    record("sidecar-booted", true, { binary, port: first.port });

    // 1. The packaged guard: a caller without the instance token is refused.
    const unauthorized = await call(first.baseUrl, "/health", { method: "GET", authorized: false });
    const authorized = await call(first.baseUrl, "/health", { method: "GET" });
    record("token-guard", unauthorized.status === 401 && authorized.status === 200, {
      withoutToken: unauthorized.status,
      withToken: authorized.status,
    });

    // 2. Optimistic lock on a versioned plan.
    const seeded = runPython(SEED_PLAN, [database, WORKSPACE_ID, PLAN_ID]);
    record("plan-seeded", seeded.revision === 1, seeded);

    const session = await call(first.baseUrl, "/session/start", {
      body: {
        workspace_id: WORKSPACE_ID,
        workspace_name: "Frozen probe",
        profile: { long_term_goal: "Probe the delivered runtime" },
      },
    });
    const contextId = String(session.json?.contextId || WORKSPACE_ID);
    record("session-started", session.status === 200, { status: session.status, contextId });

    const missingRevision = await call(first.baseUrl, "/plan/update", {
      body: { workspace_id: contextId, plan_id: PLAN_ID, title: PLAN_TITLE_STALE },
    });
    record("plan-revision-required", missingRevision.status === 428 && missingRevision.json?.detail?.code === "plan_revision_required", {
      status: missingRevision.status,
      code: missingRevision.json?.detail?.code ?? null,
    });

    const accepted = await call(first.baseUrl, "/plan/update", {
      body: {
        workspace_id: contextId,
        plan_id: PLAN_ID,
        title: PLAN_TITLE_ACCEPTED,
        expected_revision: 1,
        provider: PROBE_PROVIDER,
        api_key: "frozen-probe-key",
      },
    });
    record("plan-revision-accepted", accepted.status === 200 && accepted.json?.plan_revision === 2, {
      status: accepted.status,
      planRevision: accepted.json?.plan_revision ?? null,
    });

    const stale = await call(first.baseUrl, "/plan/update", {
      body: {
        workspace_id: contextId,
        plan_id: PLAN_ID,
        title: PLAN_TITLE_STALE,
        expected_revision: 1,
        provider: PROBE_PROVIDER,
        api_key: "frozen-probe-key",
      },
    });
    record("plan-revision-conflict", stale.status === 409 && stale.json?.detail?.code === "plan_revision_conflict", {
      status: stale.status,
      code: stale.json?.detail?.code ?? null,
      currentRevision: stale.json?.detail?.current_revision ?? null,
    });

    // 3. Two real processes over one data directory. The second must load the
    // workspace BEFORE the first writes, so its baseline is genuinely stale.
    const second = await startSidecar("second");
    const secondSession = await call(second.baseUrl, "/session/start", {
      body: {
        workspace_id: WORKSPACE_ID,
        workspace_name: "Frozen probe",
        profile: { long_term_goal: "Probe the delivered runtime" },
      },
    });
    const secondSummary = await call(
      second.baseUrl,
      `/memory/summary?workspace_id=${encodeURIComponent(contextId)}`,
      { method: "GET" },
    );
    record("second-window-loaded", secondSession.status === 200 && secondSummary.status === 200, {
      port: second.port,
      sessionStatus: secondSession.status,
      summaryStatus: secondSummary.status,
    });

    const firstWrite = await call(first.baseUrl, "/memory/settings", {
      body: { workspace_id: contextId, response_language: "zh-CN" },
    });
    const secondWrite = await call(second.baseUrl, "/memory/settings", {
      body: { workspace_id: contextId, answer_mode: "guided" },
    });
    record("both-windows-wrote", firstWrite.status === 200 && secondWrite.status === 200, {
      first: firstWrite.status,
      second: secondWrite.status,
    });

    await stopChildren();

    const truth = runPython(READ_TRUTH, [database, contextId, PLAN_ID]);
    const storedWorkspace = truth.memory?.workspace ?? {};
    record(
      "cross-process-merge",
      storedWorkspace.response_language === "zh-CN" && storedWorkspace.answer_mode === "guided",
      {
        responseLanguage: storedWorkspace.response_language ?? null,
        answerMode: storedWorkspace.answer_mode ?? null,
      },
    );
    record(
      "stale-save-never-landed",
      truth.plan_title === PLAN_TITLE_ACCEPTED && truth.plan_revision === 2,
      { planTitle: truth.plan_title, planRevision: truth.plan_revision },
    );
  } catch (error) {
    record("fatal", false, { error: error instanceof Error ? error.stack : String(error) });
  } finally {
    await stopChildren();
    fs.rmSync(dataDir, { recursive: true, force: true });
  }

  const failures = results.filter((item) => !item.ok);
  if (failures.length > 0) {
    for (const [label, log] of logs) {
      if (log.trim()) console.error(`--- sidecar ${label} log tail ---\n${log.slice(-1500)}`);
    }
  }
  console.log(
    `\n[${failures.length === 0 ? "PASS" : "FAIL"}] ${results.length - failures.length}/${results.length} frozen-sidecar checks`,
  );
  if (failures.length > 0) process.exitCode = 1;
}

main().catch((error) => {
  console.error(`[verify-frozen-sidecar] ${error instanceof Error ? error.stack : String(error)}`);
  process.exitCode = 1;
});
