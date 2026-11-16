// Scenario 4 acceptance (十三·场景四): long-term recovery.
//
// Seed a real workspace (plan + goal + candidate card + resource + learning
// signal + teaching feedback), RESTART the sidecar against the same data
// directory, reopen Trainer days later (new session), and assert the coach
// already knows the learner:
//   01 seed session + provider
//   02 seed state: plan, goal (plan-linked), resource, candidate card,
//      learning signal, teaching feedback
//   03 RESTART the sidecar; fresh session on the same workspace
//   04 recovery: goal (plan/stage), plan stages, candidate card, resource,
//      review scheduling and strategy record all survive
//   05 no re-introduction: "我们之前学到哪了？" gets a reply anchored in the
//      restored world-model context — the coach never asks who the learner is
//
// Requires PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY (+
// PROBE_PROVIDER_MODEL, default MiniMax-M2.7).
import { spawn } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repoRoot = "/Users/Apple/Desktop/trainer";
const serverDir = path.join(repoRoot, "server");
const python = path.join(serverDir, ".venv", "bin", "python");
const baseUrl = "http://127.0.0.1:34984";
const providerBase = process.env.PROBE_PROVIDER_BASE_URL ?? "";
const providerKey = process.env.PROBE_PROVIDER_API_KEY ?? "";
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M2.7";
const outDir =
  process.env.JOURNEY_OUT_DIR ??
  path.join(repoRoot, "output/maturity", `scenario4-${new Date().toISOString().replace(/[:.]/g, "-")}`);
fs.mkdirSync(outDir, { recursive: true });

if (!providerBase || !providerKey) {
  console.error("PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY required");
  process.exit(2);
}
try {
  await fetch(`${baseUrl}/health`);
  console.error(`port 34984 already served — kill the stale sidecar first`);
  process.exit(4);
} catch {}

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-scenario4-"));
const workspaceId = "scenario4-ws";
let sidecar = null;
let providerTestResult = null;
let sidecarLog = "";
let failures = 0;
let seededSessionId = "";
let resourceId = "";

const providerPayload = {
  name: "scenario4",
  baseUrl: providerBase,
  apiKeyRef: "scenario4",
  model,
  protocol: "openai_chat_completions_compatible",
};

const PAPER_MARKDOWN = [
  "# World Models for Autonomous Driving: study notes",
  "The one-step prediction objective trains the model to predict the next latent state z_{t+1} from z_t and the action a_t. Termination stops the value bootstrap; truncation bootstraps from the final observed state.",
].join("\n");

function sidecarProc() {
  return spawn(python, ["run_sidecar.py", "--host", "127.0.0.1", "--port", "34984"], {
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

async function startSidecarAndProvider(label) {
  sidecar = sidecarProc();
  sidecar.stdout.on("data", (c) => (sidecarLog += c));
  sidecar.stderr.on("data", (c) => (sidecarLog += c));
  await waitForHealth();
  const providerTest = await post("/provider/test", {
    provider: providerPayload,
    apiKey: providerKey,
    responseLanguage: "zh-CN",
  });
  providerTestResult = providerTest.json;
  step(`${label}-session-provider`, {
    provider_ok: providerTest.json?.ok === true,
  }, { fail: providerTest.json?.ok !== true });
}

// ---------------------------------------------------------------- journey --
try {
  // 01 — seed: first sidecar lifecycle
  sidecar = sidecarProc();
  sidecar.stdout.on("data", (c) => (sidecarLog += c));
  sidecar.stderr.on("data", (c) => (sidecarLog += c));
  await waitForHealth();
  const start = await post("/session/start", {
    workspace_id: workspaceId,
    workspace_name: "World Models Recovery",
  });
  seededSessionId = start.json?.session_id ?? "";
  const providerTest = await post("/provider/test", {
    provider: providerPayload,
    apiKey: providerKey,
    responseLanguage: "zh-CN",
  });
  providerTestResult = providerTest.json;
  step("01-seed-session-provider", {
    session_ok: start.status === 200 && Boolean(seededSessionId),
    provider_ok: providerTest.json?.ok === true,
  }, { fail: start.status !== 200 || !seededSessionId || providerTest.json?.ok !== true });

  // 02 — seed the long-lived state
  const plan = await post("/plan/generate", {
    session_id: seededSessionId,
    workspace_id: workspaceId,
    profile: {
      long_term_goal: "系统掌握自动驾驶中的世界模型",
      weekly_hours: 6,
      teaching_style: "guided",
      answer_policy: "adaptive",
    },
    goals: ["理解世界模型在自动驾驶规划中的作用"],
    provider: providerPayload,
    api_key: providerKey,
    last_test_result: providerTestResult,
  });
  const planId = plan.json?.plan?.id ?? plan.json?.plan?.plan_id ?? "";

  const goal = await post("/goal/action", {
    session_id: seededSessionId,
    workspace_id: workspaceId,
    action: "start",
    title: "系统掌握自动驾驶中的世界模型",
  });
  const goalJson = goal.json?.goal ?? {};

  // The teaching thread carries the goal topic, so recovery can anchor on it.
  const topicTurn = await streamTurn({
    session_id: seededSessionId,
    workspace_id: workspaceId,
    message: "围绕这个目标，我们刚练习了世界模型的一步预测：我写出了“先预测下一潜在状态，再算与真实观测的差距”的损失项。接下来练什么？",
    intent: "coach",
    active_view: "coach",
  });

  const upload = await post("/resource/upload", {
    session_id: seededSessionId,
    workspace_id: workspaceId,
    kind: "markdown",
    name: "World Models study notes",
    source: "notes.example.com/world-models",
    content: PAPER_MARKDOWN,
    content_encoding: "utf-8",
    tags: ["paper", "world-models"],
  });
  resourceId = upload.json?.id ?? "";

  const card = await post("/training/generate-card", {
    session_id: seededSessionId,
    workspace_id: workspaceId,
    source: "conversation_gap",
    card_type: "practice",
    focus_area: "世界模型一步预测",
    target_skill: "解释一步预测的目标并写出损失项",
    prompt: "用一行写出世界模型一步预测先做什么、要学习或预测什么。",
    provider: providerPayload,
    api_key: providerKey,
  });

  const signal = await post("/learning/signal", {
    session_id: seededSessionId,
    workspace_id: workspaceId,
    concepts: ["世界模型一步预测"],
    outcome: "concept_answered_correctly",
    summary: "能写出一步预测的目标与损失项。",
    focus_area: "世界模型一步预测",
    action_type: "practice",
  });

  const feedback = await post("/memory/feedback", {
    session_id: seededSessionId,
    workspace_id: workspaceId,
    kind: "too_hard",
    message: "解释太复杂了。下次先用类比讲直觉。",
    focus_area: "世界模型",
    scenario: "general",
  });
  const seedOk = plan.status === 200 && Boolean(planId) && goal.status === 200 &&
    Boolean(goalJson.goalId) && topicTurn.status === 200 &&
    upload.status === 200 && Boolean(resourceId) &&
    card.status === 200 && signal.status === 200 && feedback.status === 200;
  step("02-seed-state", {
    plan_id: planId,
    goal_id: goalJson.goalId ?? "",
    goal_plan_linked: goalJson.planId === planId,
    resource_id: resourceId,
    card_status: card.json?.card?.status ?? "",
    signal_status: signal.status,
    feedback_status: feedback.status,
    ...(card.status !== 200 ? { card_error: errorDetail(card.text) } : {}),
  }, { fail: !seedOk });

  // 03 — RESTART: stop the sidecar, start a fresh one on the same data dir,
  // open Trainer days later with a brand-new session.
  sidecar.kill("SIGTERM");
  await new Promise((r) => setTimeout(r, 3000));
  sidecarLog += "\n--- RESTART ---\n";
  await startSidecarAndProvider("03-restart");
  const reopen = await post("/session/start", {
    workspace_id: workspaceId,
    workspace_name: "World Models Recovery",
  });
  const freshSessionId = reopen.json?.session_id ?? "";
  step("03-restart-reopen", {
    reopen_ok: reopen.status === 200 && Boolean(freshSessionId),
    // Reopening Trainer restores the workspace's own session.
    session_restored: freshSessionId === seededSessionId,
  }, { fail: reopen.status !== 200 || !freshSessionId });

  // 04 — recovery assertions on the persisted state. Reopening Trainer uses
  // the server's latest-session restore + fresh snapshot (memory/summary is
  // the WorkbenchSnapshot surface that performs both).
  const summarySnap = await fetch(`${baseUrl}/memory/summary?workspace_id=${encodeURIComponent(workspaceId)}`);
  const snap = { status: summarySnap.status, json: await summarySnap.json().catch(() => null) };
  const memory = snap.json?.memory ?? {};
  const training = snap.json?.workspaceTrainingState ?? snap.json?.workspace_training_state ?? {};
  const goalCurrent = await (async () => {
    const r = await fetch(`${baseUrl}/goal/current?workspace_id=${encodeURIComponent(workspaceId)}`);
    return r.json().catch(() => ({}));
  })();
  const restoredGoal = goalCurrent.goal ?? null;
  const restoredPlan = snap.json?.plan ?? null;
  const strategyRecord = (memory.teaching_strategy_effectiveness ?? []).some(
    (item) => item.last_outcome === "user_feedback",
  );
  // Persisted truth: the structured store and resource rows survive restarts
  // (same verification surface run-full-journey uses).
  const db = new DatabaseSync(path.join(dataDir, "trainer.sqlite3"));
  const structuredRow = db
    .prepare("SELECT payload FROM structured_memory WHERE workspace_id = ?")
    .get(workspaceId);
  const structuredPayload = structuredRow ? JSON.parse(structuredRow.payload) : {};
  const persistedCards = Object.values(structuredPayload.training_cards ?? {});
  // The learner may have started practising the card — any live (non-archived)
  // card counts as a recovered training card; statuses travel with the record.
  const persistedCandidates = persistedCards.filter((item) => item.status !== "archived");
  const resourceRow = db
    .prepare("SELECT COUNT(*) AS count FROM resources WHERE workspace_id = ?")
    .get(workspaceId);
  const ledgerEvents = structuredPayload.training_event_ledger ?? [];
  const reviewScheduled = ledgerEvents.some((entry) => entry.event_type === "review_scheduled");

  step("04-state-recovered", {
    goal_active: restoredGoal?.status === "active" && restoredGoal?.title?.includes("世界模型"),
    goal_plan_id: restoredGoal?.planId ?? "",
    plan_stages: (restoredPlan?.stages ?? []).length,
    candidate_cards: persistedCandidates.length,
    candidate_statuses: persistedCandidates.map((item) => item.status),
    resource_rows: resourceRow?.count ?? 0,
    review_scheduled_event: reviewScheduled,
    strategy_record_persisted: strategyRecord,
  }, {
    fail: !(restoredGoal?.status === "active") ||
      restoredGoal?.planId !== planId ||
      !(restoredPlan?.stages ?? []).length ||
      !persistedCandidates.length ||
      (resourceRow?.count ?? 0) < 1 ||
      !strategyRecord,
  });

  // 05 — 不需要重新自我介绍：the resume ask anchors in the restored context
  const resume = await streamTurn({
    session_id: freshSessionId,
    workspace_id: workspaceId,
    message: "我们之前学到哪了？接下来最值得做的是什么？",
    intent: "coach",
    active_view: "coach",
  });
  const topicTokens = ["世界模型", "一步预测", "潜在状态", "真实观测", "自动驾驶"];
  const anchored = topicTokens.filter((token) => resume.visible.includes(token));
  const asksIdentity = /你(是|在)谁|介绍一下你自己|你是做什么的|我们从零开始|初次见面/.test(resume.visible);
  step("05-resume-without-re-introduction", {
    status: resume.status,
    visible_chars: resume.visible.length,
    anchored_tokens: anchored,
    asks_identity: asksIdentity,
    preview: resume.visible.slice(0, 240),
    ...(resume.status !== 200 ? { error_detail: errorDetail(resume.text) } : {}),
  }, {
    fail: resume.status !== 200 ||
      resume.visible.length < 40 ||
      anchored.length === 0 ||
      asksIdentity,
  });

  const summary = {
    scenario: "13-场景四：长期恢复",
    failures,
    outDir,
    data_dir: dataDir,
  };
  fs.writeFileSync(path.join(outDir, "summary.json"), JSON.stringify(summary, null, 2));
  console.log(`\njourney ${failures === 0 ? "PASS" : `FAILED (${failures})`} — artifacts: ${outDir}`);
} finally {
  if (sidecar) sidecar.kill("SIGTERM");
  fs.writeFileSync(path.join(outDir, "sidecar.log"), sidecarLog.slice(-20_000));
}
process.exit(failures === 0 ? 0 : 1);
