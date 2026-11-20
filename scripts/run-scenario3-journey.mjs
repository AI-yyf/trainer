// Scenario 3 acceptance (十三·场景三): personalized teaching.
//
// "你这次解释得太复杂了，换一种容易理解的方式。" — the journey drives:
//   01 session + provider test
//   02 first explanation of a concept (baseline: a detailed reply)
//   03 the simplification ask — Trainer re-explains in an easier way about
//      the SAME concept
//   04 feedback spoken in the conversation lands in memory as a dated
//      observation, without a separate feedback action or mastery claim
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
const revisionAsk = "你这次解释得太复杂了，换一种容易理解的方式。用类比，不要太长。";

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
    message: revisionAsk,
    intent: "coach",
    active_view: "coach",
  });
  const shortened = second.visible.length > 0 &&
    second.visible.length < Math.max(first.visible.length, 400);
  const sameTopic = /潜在空间|隐空间|潜变量|latent/iu.test(second.visible);
  const usesAnalogy = /类比|比喻|像|好比|想象|比如/iu.test(second.visible);
  const checksUnderstanding = /[？?]/u.test(second.visible);
  const asksForRepeat = /(?:再贴|贴一下|重新贴|重新发|再发|发给我|提供).{0,12}(?:原文|刚才|上文|那段)|(?:刚才|原文|那段).{0,15}(?:再贴|贴一下|重新贴|重新发)/u.test(second.visible);
  step("03-easier-re-explanation", {
    status: second.status,
    first_chars: first.visible.length,
    second_chars: second.visible.length,
    shortened,
    same_topic: sameTopic,
    uses_analogy: usesAnalogy,
    checks_understanding: checksUnderstanding,
    asks_for_repeat: asksForRepeat,
    preview: second.visible.slice(0, 220),
    ...(second.status !== 200 ? { error_detail: errorDetail(second.text) } : {}),
  }, {
    fail: second.status !== 200 || !sameTopic || !shortened ||
      !usesAnalogy || !checksUnderstanding || asksForRepeat,
  });

  // 04 — verify the conversational feedback without a manual feedback POST.
  const snap = await snapshot("scenario3-ws", sessionId);
  const memory = snap.json?.memory ?? {};
  const strategies = memory.teaching_strategy_effectiveness ?? [];
  const feedbackRecord = strategies.find((item) =>
    item.scenario === "explanation_revision" && item.last_outcome === "user_feedback"
  );
  const observation = (memory.userFeedback ?? memory.user_feedback ?? []).find((item) =>
    item.kind === "too_hard" && item.message === revisionAsk && item.reply_message_id
  );
  const masteryUnaffected = feedbackRecord?.total_count === 0 &&
    !(memory.learning_outcomes ?? []).some((item) => item.action_type === "user_feedback");
  step("04-conversational-feedback-persisted", {
    status: snap.status,
    strategy_records: strategies.length,
    has_user_feedback_record: Boolean(feedbackRecord),
    reply_message_id: observation?.reply_message_id ?? "",
    mastery_unaffected: masteryUnaffected,
  }, { fail: snap.status !== 200 || !observation || !masteryUnaffected });

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
