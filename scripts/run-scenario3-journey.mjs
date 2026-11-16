// Scenario 3 acceptance (十三·场景三): personalized teaching.
//
// "你这次解释得太复杂了，换一种容易理解的方式。" — the journey drives:
//   01 session + provider test
//   02 first explanation of a concept (baseline: a detailed reply)
//   03 the simplification ask — Trainer re-explains in an easier way about
//      the SAME concept
//   04 the learner records the feedback via /memory/feedback (too_hard)
//   05 the teaching-adaptation loop: the feedback lands in the persisted
//      teaching strategy effectiveness record (last_outcome=user_feedback)
//      and the workspace feedback state carries the learner's words
//
// Requires PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY (+
// PROBE_PROVIDER_MODEL, default MiniMax-M2.7).
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repoRoot = "/Users/Apple/Desktop/trainer";
const serverDir = path.join(repoRoot, "server");
const python = path.join(serverDir, ".venv", "bin", "python");
const baseUrl = "http://127.0.0.1:34983";
const providerBase = process.env.PROBE_PROVIDER_BASE_URL ?? "";
const providerKey = process.env.PROBE_PROVIDER_API_KEY ?? "";
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M2.7";
const outDir =
  process.env.JOURNEY_OUT_DIR ??
  path.join(repoRoot, "output/maturity", `scenario3-${new Date().toISOString().replace(/[:.]/g, "-")}`);
fs.mkdirSync(outDir, { recursive: true });

if (!providerBase || !providerKey) {
  console.error("PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY required");
  process.exit(2);
}
try {
  await fetch(`${baseUrl}/health`);
  console.error(`port 34983 already served — kill the stale sidecar first`);
  process.exit(4);
} catch {}

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-scenario3-"));
let sidecar = null;
let providerTestResult = null;
let sidecarLog = "";
let failures = 0;

const providerPayload = {
  name: "scenario3",
  baseUrl: providerBase,
  apiKeyRef: "scenario3",
  model,
  protocol: "openai_chat_completions_compatible",
};

function sidecarProc() {
  return spawn(python, ["run_sidecar.py", "--host", "127.0.0.1", "--port", "34983"], {
    cwd: serverDir,
    env: { ...process.env, TRAINER_DATA_DIR: dataDir, TRAINER_ENABLE_NETWORK_FETCH: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
}

async function waitForHealth(timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await fetch(`${baseUrl}/health`);
      if (r.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("sidecar never became healthy");
}

async function post(pathname, body, { attempts = 2 } = {}) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const r = await fetch(`${baseUrl}${pathname}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const text = await r.text();
      let json = null;
      try { json = JSON.parse(text); } catch {}
      return { status: r.status, json, text };
    } catch (error) {
      if (attempt === attempts) {
        return { status: 0, json: null, text: String(error) };
      }
      await new Promise((r) => setTimeout(r, 15_000));
    }
  }
}

async function streamTurn(body) {
  const r = await fetch(`${baseUrl}/turn/stream`, {
    method: "POST",
    headers: { accept: "text/event-stream", "content-type": "application/json" },
    body: JSON.stringify({
      ...body,
      provider: providerPayload,
      api_key: providerKey,
      last_test_result: providerTestResult,
    }),
  });
  const text = await r.text();
  const chunks = [...text.matchAll(/"chunk"\s*:\s*"((?:\\.|[^"\\])*)"/g)]
    .map((m) => { try { return JSON.parse(`"${m[1]}"`); } catch { return ""; } })
    .join("");
  return { status: r.status, text, visible: chunks };
}

function step(name, data, { fail = false } = {}) {
  const record = { step: name, ok: !fail, ...data };
  fs.writeFileSync(path.join(outDir, `${name}.json`), JSON.stringify(record, null, 2));
  console.log(`${fail ? "FAIL" : "PASS"}  ${name}`);
  if (fail) failures += 1;
}

function errorDetail(text) {
  return String(text || "").slice(0, 400);
}

async function snapshot(workspaceId, sessionId) {
  const query = new URLSearchParams({ workspace_id: workspaceId });
  if (sessionId) query.set("session_id", sessionId);
  const r = await fetch(`${baseUrl}/snapshot?${query.toString()}`);
  const payload = await r.json().catch(() => null);
  return { status: r.status, json: payload?.snapshot ?? payload };
}

// ---------------------------------------------------------------- journey --
const sidecarProcess = sidecarProc();
sidecarProcess.stdout.on("data", (c) => (sidecarLog += c));
sidecarProcess.stderr.on("data", (c) => (sidecarLog += c));
try {
  await waitForHealth();

  // 01 — session + provider
  const start = await post("/session/start", {
    workspace_id: "scenario3-ws",
    workspace_name: "Personalized Teaching Journey",
  });
  const sessionId = start.json?.session_id ?? "";
  const providerTest = await post("/provider/test", {
    provider: providerPayload,
    apiKey: providerKey,
    responseLanguage: "zh-CN",
  });
  providerTestResult = providerTest.json;
  step("01-session-provider", {
    session_ok: start.status === 200 && Boolean(sessionId),
    provider_ok: providerTest.json?.ok === true,
  }, { fail: start.status !== 200 || !sessionId || providerTest.json?.ok !== true });

  // 02 — first (complex) explanation of the same concept
  const first = await streamTurn({
    session_id: sessionId,
    workspace_id: "scenario3-ws",
    message: "请详细解释自动驾驶世界模型中的潜在空间（latent space）是什么，包括它的技术原理。",
    intent: "coach",
    active_view: "coach",
  });
  const firstOk = first.status === 200 && first.visible.length >= 200;
  step("02-first-explanation", {
    status: first.status,
    visible_chars: first.visible.length,
    preview: first.visible.slice(0, 200),
    ...(first.status !== 200 ? { error_detail: errorDetail(first.text) } : {}),
  }, { fail: !firstOk });

  // 03 — the learner asks for an easier re-explanation of the SAME concept
  const second = await streamTurn({
    session_id: sessionId,
    workspace_id: "scenario3-ws",
    message: "你这次解释得太复杂了，换一种容易理解的方式。用类比，不要太长。",
    intent: "coach",
    active_view: "coach",
  });
  const shortened = second.visible.length > 0 &&
    second.visible.length < Math.max(first.visible.length, 400);
  const sameTopic = /潜在空间|latent|类比|比喻|像|好比/iu.test(second.visible);
  step("03-easier-re-explanation", {
    status: second.status,
    first_chars: first.visible.length,
    second_chars: second.visible.length,
    shortened,
    same_topic: sameTopic,
    preview: second.visible.slice(0, 220),
    ...(second.status !== 200 ? { error_detail: errorDetail(second.text) } : {}),
  }, { fail: second.status !== 200 || !sameTopic || !shortened });

  // 04 — the learner records the feedback through the governed feedback path
  const feedback = await post("/memory/feedback", {
    session_id: sessionId,
    workspace_id: "scenario3-ws",
    kind: "too_hard",
    message: "解释太复杂了。下次用类比先讲直觉，再讲细节。",
    focus_area: "潜在空间",
    scenario: "general",
  });
  step("04-feedback-recorded", {
    status: feedback.status,
    ok: feedback.json?.ok === true || feedback.status === 200,
  }, { fail: feedback.status !== 200 });

  // 05 — the teaching-adaptation loop persists the strategy record
  const snap = await snapshot("scenario3-ws", sessionId);
  const strategies = snap.json?.memory?.teaching_strategy_effectiveness ?? [];
  const feedbackRecord = strategies.find((item) => item.last_outcome === "user_feedback");
  const workspace = snap.json?.memory?.workspace ?? {};
  const feedbackCarried =
    (workspace.latest_user_feedback ?? workspace.latest_user_feedback_kind ?? "") !== "";
  step("05-strategy-effectiveness-persisted", {
    strategy_records: strategies.length,
    has_user_feedback_record: Boolean(feedbackRecord),
    feedback_bias: feedbackRecord?.next_step_bias ?? "",
    workspace_feedback_carried: feedbackCarried,
  }, { fail: !feedbackRecord });

  const summary = {
    scenario: "13-场景三：个性化教学",
    failures,
    outDir,
  };
  fs.writeFileSync(path.join(outDir, "summary.json"), JSON.stringify(summary, null, 2));
  console.log(`\njourney ${failures === 0 ? "PASS" : `FAILED (${failures})`} — artifacts: ${outDir}`);
} finally {
  sidecarProcess.kill("SIGTERM");
  fs.writeFileSync(path.join(outDir, "sidecar.log"), sidecarLog.slice(-20_000));
}
process.exit(failures === 0 ? 0 : 1);
