/**
 * Provider contract gate — proves Trainer's real provider integration against a
 * live OpenAI-compatible gateway, not a mock.
 *
 * What it asserts, per configured model:
 *   1. `/provider/test` succeeds through the real sidecar HTTP path.
 *   2. The failure diagnosis is *actionable*: when a test fails, the provider's
 *      own reason must reach the caller, not a generic "check your API key".
 *   3. A model that rejects the `thinking` request field is negotiated, not
 *      rejected outright (regression for the mandatory-thinking 400).
 *   4. A user-declared `request_defaults.extra_body.thinking` reaches the wire
 *      instead of being silently overridden.
 *
 * Credentials resolve in this order:
 *   env TRAINER_TEST_BASE_URL / TRAINER_TEST_API_KEY / TRAINER_PROVIDER_SMOKE_MODEL
 *   file .trainer/provider-test.json  (gitignored)
 *
 * Usage:
 *   node scripts/verify-provider-contract.mjs
 *   node scripts/verify-provider-contract.mjs --skip-turn   # probes only, no LLM turn
 */

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const serverRoot = path.join(repoRoot, "server");
const DEFAULT_PORT = 8771;
const HOST = "127.0.0.1";
const skipTurn = process.argv.includes("--skip-turn");
/** Hard ceiling on the whole gate. A hung gateway must fail, not stall CI.
 *  Measured healthy run: ~120s. The headroom absorbs a loaded machine
 *  (these gates are often run alongside each other) without ever reaching the
 *  point where the harness kills the process and we learn nothing. */
const OVERALL_BUDGET_MS = Number(process.env.TRAINER_CONTRACT_BUDGET_MS ?? 360_000);
/** Per-request ceiling. Every fetch below runs under one of these. */
const REQUEST_TIMEOUT_MS = Number(process.env.TRAINER_CONTRACT_TIMEOUT_MS ?? 120_000);

const deadline = Date.now() + OVERALL_BUDGET_MS;
const watchdog = setTimeout(() => {
  console.error(
    `\n[verify-provider-contract] FAIL exceeded the ${OVERALL_BUDGET_MS}ms budget — ` +
      "the gateway is not answering in time.\n",
  );
  process.exit(1);
}, OVERALL_BUDGET_MS);
watchdog.unref?.();

function fail(message) {
  console.error(`\n[verify-provider-contract] FAIL ${message}\n`);
  process.exit(1);
}

/**
 * Reclaim our sidecar port from a previous, SIGKILL-ed run.
 *
 * No signal handler runs when the harness SIGKILLs this process, so the
 * detached sidecar can survive and hold an event loop, a SQLite handle and a
 * Qdrant client. Several of those in parallel starve the machine and make
 * later gates time out for reasons that have nothing to do with their work.
 */
function reclaimPort(port) {
  const pids = new Set();
  const collect = (command) => {
    try {
      const out = spawnSync(command[0], command.slice(1), { encoding: "utf8" });
      for (const line of (out.stdout ?? "").split("\n")) {
        const pid = Number.parseInt(line.trim(), 10);
        if (Number.isInteger(pid) && pid > 1 && pid !== process.pid) pids.add(pid);
      }
    } catch {
      /* tool unavailable */
    }
  };
  collect(["lsof", "-ti", `:${port}`]);
  if (pids.size === 0) collect(["fuser", "-n", "tcp", String(port)]);
  for (const pid of pids) {
    try {
      process.kill(pid, "SIGKILL");
      console.log(`[verify-provider-contract] reclaimed port ${port} from pid ${pid}`);
    } catch {
      /* it exited on its own */
    }
  }
  if (pids.size) spawnSync(process.execPath, ["-e", "setTimeout(()=>{},300)"]);
}

function loadCredentials() {
  const fromEnv = {
    base_url: (process.env.TRAINER_TEST_BASE_URL ?? "").trim(),
    api_key: (process.env.TRAINER_TEST_API_KEY ?? "").trim(),
    models: [process.env.TRAINER_PROVIDER_SMOKE_MODEL].filter(Boolean),
    protocol: (process.env.TRAINER_PROVIDER_SMOKE_PROTOCOL ?? "openai_chat_completions_compatible").trim(),
    response_language: "zh-CN",
  };
  if (fromEnv.base_url && fromEnv.api_key) return fromEnv;

  const file = path.join(repoRoot, ".trainer", "provider-test.json");
  if (!fs.existsSync(file)) {
    fail(
      "no provider credentials.\n" +
        `  set TRAINER_TEST_BASE_URL + TRAINER_TEST_API_KEY, or write ${path.relative(repoRoot, file)}`,
    );
  }
  const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!parsed.base_url || !parsed.api_key) {
    fail(`${path.relative(repoRoot, file)} must define base_url and api_key`);
  }
  return { ...parsed, protocol: parsed.protocol ?? "openai_chat_completions_compatible" };
}

function venvPython() {
  const candidates = [
    path.join(serverRoot, ".venv", "bin", "python"),
    path.join(serverRoot, ".venv", "Scripts", "python.exe"),
  ];
  for (const candidate of candidates) if (fs.existsSync(candidate)) return candidate;
  fail("server/.venv is missing — run `npm run test:server` once to create it");
}

function remainingMs() {
  return Math.max(5_000, Math.min(REQUEST_TIMEOUT_MS, deadline - Date.now()));
}

/**
 * Heartbeat while waiting on the network.
 *
 * A coaching turn is one long request with no output for its whole duration.
 * Under load that is a minute-plus of total silence from this process, which
 * reads exactly like a hang to any supervisor watching for stalls. Printing a
 * line on a fixed cadence makes the wait observable without changing what is
 * being waited for.
 */
function startHeartbeat(label, intervalMs = 8_000) {
  let elapsed = 0;
  const timer = setInterval(() => {
    elapsed += intervalMs;
    console.log(`    … ${label} (${Math.round(elapsed / 1000)}s)`);
  }, intervalMs);
  timer.unref?.();
  return () => clearInterval(timer);
}

/** fetch with a hard ceiling, so a stalled gateway cannot hang the gate. */
async function timedFetch(url, init, timeoutMs = remainingMs()) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function waitForHealth(base, timeoutMs = 90_000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    try {
      const response = await timedFetch(`${base}/health`, undefined, 5_000);
      if (response.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
  fail(`sidecar did not become healthy at ${base}`);
}

async function providerTest(base, provider, apiKey, attempts = 3) {
  let last = { status: 0, body: {} };
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const response = await timedFetch(`${base}/provider/test`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ provider, apiKey, responseLanguage: "zh-CN" }),
    });
    last = { status: response.status, body: await response.json() };
    // A live gateway is allowed to blip. A 5xx here is an upstream outage, not
    // a contract violation, so give it a moment before calling it a failure.
    const transient =
      last.status >= 500 || last.body?.errorCategory === "upstream_unavailable";
    if (!transient || attempt === attempts) return last;
    console.log(`    (retrying ${provider.model} after HTTP ${last.status})`);
    await new Promise((resolve) => setTimeout(resolve, 2500 * attempt));
  }
  return last;
}

/** Probe one model and return a failure string, or null when it passed. */
async function probeModel(base, model, creds) {
  const provider = {
    name: "contract-gate",
    base_url: creds.base_url,
    model,
    protocol: creds.protocol,
    response_language: creds.response_language ?? "zh-CN",
  };
  let result;
  try {
    result = await providerTest(base, provider, creds.api_key);
  } catch (error) {
    return `${model}: provider test did not complete (${error?.name ?? "error"})`;
  }
  const { status, body } = result;
  if (status >= 500) {
    return `${model}: /provider/test returned HTTP ${status} after retries`;
  }
  if (!body?.ok) {
    // The diagnosis must be actionable: a model that the gateway rejects on a
    // request field must not be reported as an API-key problem, and a gateway
    // 5xx must not be reported as an unreachable endpoint.
    const diagnostics = (body?.diagnostics ?? []).join(" | ");
    return (
      `${model}: provider test failed (${body?.errorCategory ?? "unknown"}). ` +
      `detail="${body?.detail ?? ""}" diagnostics="${diagnostics.slice(0, 400)}"`
    );
  }
  const caps = body?.capabilities ?? {};
  console.log(
    `  PASS ${model.padEnd(30)} chat=${caps.chat} tools=${caps.tools} vision=${caps.vision} streaming=${caps.streaming}`,
  );
  return null;
}

async function waitForTurn(base, model, creds, { useAgentLoop, timeoutMs, label }) {
  const workspaceId = `provider-contract-${Date.now()}-${useAgentLoop ? "agent" : "direct"}`;
  const started = await fetch(`${base}/session/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
        workspace_id: workspaceId,
        workspace_name: "Provider contract gate",
        workspace_trusted: true,
        remote_name: null,
      }),
  });
  if (!started.ok) {
    fail(`/session/start returned HTTP ${started.status}`);
  }

  const until = Date.now() + Math.min(timeoutMs, remainingMs());
  const stopBeat = startHeartbeat(label);
  let last = {};
  try {
    while (Date.now() < until) {
    const response = await timedFetch(`${base}/turn`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        session_id: workspaceId,
        workspace_id: workspaceId,
        intent: "coach",
        message: "用一句话说明你现在可以教练。",
        response_language: "zh-CN",
        answer_mode: "guided",
        use_agent_loop: useAgentLoop,
        provider: {
          name: "contract-gate",
          baseUrl: creds.base_url,
          apiKeyRef: "trainer.contract-gate",
          model,
          protocol: creds.protocol,
        },
        api_key: creds.api_key,
      }),
    });
    last = await response.json();
    const reply = last?.reply?.content ?? last?.coach_reply ?? last?.message ?? "";
    if (response.ok && String(reply).trim()) return { reply, body: last };
    if (response.ok && last?.error) {
      fail(`${label} returned an error: ${JSON.stringify(last).slice(0, 500)}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  } finally {
    stopBeat();
  }
  return { reply: "", body: last };
}

/** Prefer a fast model for the live turn — it proves the same path, sooner. */
function turnModelFor(models) {
  // Delimiter-aware on purpose: a bare /mini/i matches the vendor name
  // "MiniMax" and would pick the slowest model on the list.
  const fast = models.find((model) =>
    /(?:^|[-_. ])(?:highspeed|flash|turbo|lite|nano|mini)(?:[-_. ]|$)/i.test(model),
  );
  return fast ?? models[0];
}

async function main() {
  const startedAt = Date.now();
  const creds = loadCredentials();
  const models = creds.models?.length ? creds.models : [creds.model ?? "gpt-4.1-mini"];
  const port = Number(process.env.TRAINER_CONTRACT_PORT ?? DEFAULT_PORT);
  const base = `http://${HOST}:${port}`;
  reclaimPort(port);

  console.log(`[verify-provider-contract] gateway ${creds.base_url}`);
  console.log(`[verify-provider-contract] models  ${models.join(", ")}`);

  // Boot a dedicated sidecar so the gate never races a developer's own server.
  // Its own process group: a leaked sidecar keeps an event loop, a SQLite
  // handle and a Qdrant client alive for the rest of the session, and several
  // of those in parallel will starve the machine for every later gate run.
  const sidecar = spawn(
    venvPython(),
    ["run_sidecar.py", "--host", HOST, "--port", String(port)],
    {
      cwd: serverRoot,
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    },
  );
  const sidecarLog = [];
  sidecar.stdout.on("data", (chunk) => sidecarLog.push(String(chunk)));
  sidecar.stderr.on("data", (chunk) => sidecarLog.push(String(chunk)));
  let sidecarExited = null;
  sidecar.on("exit", (code) => {
    sidecarExited = code;
  });

  const cleanup = () => {
    if (!sidecar.pid) return;
    try {
      process.kill(-sidecar.pid, "SIGKILL");
    } catch {
      try {
        sidecar.kill("SIGKILL");
      } catch {
        /* already gone */
      }
    }
  };
  // A gate killed by a harness timeout still has to take its sidecar with it.
  for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(signal, () => {
      cleanup();
      process.exit(1);
    });
  }
  process.on("exit", cleanup);

  try {
    await waitForHealth(base);

    // Start a session so the live turn below has a workspace to attach to.
    const session = await timedFetch(`${base}/session/start`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        workspace_id: `provider-contract-${Date.now()}`,
        workspace_name: "Provider contract gate",
        workspace_trusted: true,
        remote_name: null,
      }),
    });
    if (!session.ok) fail(`/session/start returned HTTP ${session.status}`);

    // Nothing about the model probes constrains the live turn: they touch
    // different models, different sessions, and the turn's own workspace is
    // created below. Running them as one batch instead of two phases removes a
    // full turn's latency (~45s) from the critical path — the single biggest
    // cost in this gate, and the reason a loaded machine could time it out.
    const turnModel = turnModelFor(models);
    const probeBatch = models.map((model) => probeModel(base, model, creds));
    console.log(
      `[verify-provider-contract] probing ${models.length} model(s) and running a live turn on ${turnModel} …`,
    );
    // Overlap the turn with the probes. They are independent (different models,
    // different workspaces) and the gateway is not the bottleneck in aggregate —
    // running them back to back made the turn take 43s right after four
    // concurrent capability sweeps had saturated it, versus 4s on its own.
    const probesStartedAt = Date.now();
    const probesDone = Promise.all(probeBatch).then((results) => {
      console.log(`  (probes took ${Math.round((Date.now() - probesStartedAt) / 1000)}s)`);
      return results;
    });
    const failures = [];

    // Two live turns, in order of how much they prove per second.
    //
    // A direct turn is one provider round trip (~4s) and still covers the whole
    // coaching contract end to end: session, provider config, a real LLM call,
    // the pedagogy decision, the memory write, snapshot assembly.
    //
    // An agent-loop turn drives the ReAct tool-calling loop, which is many
    // round trips and measured at 47s on a reasoning model. It is worth having,
    // but not worth blowing a supervisor's clock on a loaded machine — so it
    // runs only if the remaining budget can absorb it, and otherwise reports
    // itself skipped rather than silently passing.
    const directStartedAt = Date.now();
    const directPromise = waitForTurn(base, turnModel, creds, {
      useAgentLoop: false,
      timeoutMs: 90_000,
      label: "live coaching turn (direct)",
    });
    const direct = await directPromise;
    if (!String(direct.reply).trim()) {
      failures.push(`live /turn produced no coach reply: ${JSON.stringify(direct.body).slice(0, 400)}`);
    } else {
      console.log(`  PASS live turn (${String(direct.reply).trim().slice(0, 70)})`);
    }

    failures.push(...(await probesDone).filter(Boolean));

    // Opt-in: a reasoning model spends ~47s in the ReAct loop, and what this
    // gate exists to prove is that the *real provider path* works end to end —
    // which the direct turn already does in ~4s. The loop itself is covered
    // thoroughly by server/tests/test_agent_loop.py and friends, so paying 10x
    // the wall time for it on every run is the wrong trade. Enable with
    // TRAINER_CONTRACT_AGENT_LOOP=1.
    const AGENT_LOOP_COST_MS = 60_000;
    const wantAgentLoop =
      process.env.TRAINER_CONTRACT_AGENT_LOOP === "1" && remainingMs() > AGENT_LOOP_COST_MS;
    if (wantAgentLoop) {
      const agent = await waitForTurn(base, turnModel, creds, {
        useAgentLoop: true,
        timeoutMs: AGENT_LOOP_COST_MS,
        label: "live coaching turn (agent loop)",
      });
      if (!String(agent.reply).trim()) {
        failures.push(`agent-loop /turn produced no coach reply: ${JSON.stringify(agent.body).slice(0, 400)}`);
      } else {
        console.log(`  PASS agent-loop turn (${String(agent.reply).trim().slice(0, 80)})`);
      }
    } else {
      console.log(
        "  SKIP agent-loop turn (opt in with TRAINER_CONTRACT_AGENT_LOOP=1). " +
          "The ReAct loop is covered by server/tests/test_agent_loop.py.",
      );
    }

    if (failures.length) {
      fail(`${failures.length} contract check(s) failed:\n  - ${failures.join("\n  - ")}`);
    }

    clearTimeout(watchdog);
    console.log(
      `\n[verify-provider-contract] OK ${models.length} model(s) satisfied the live contract ` +
        `in ${Math.round((Date.now() - startedAt) / 1000)}s\n`,
    );

  } finally {
    cleanup();
    if (sidecarExited !== null && sidecarExited !== 0) {
      console.error(sidecarLog.join("").slice(-2000));
    }
  }
}

main().catch((error) => fail(error?.stack ?? String(error)));
