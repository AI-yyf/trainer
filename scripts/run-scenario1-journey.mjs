// Scenario 1 acceptance (十三·场景一): "我想系统掌握自动驾驶中的世界模型".
//
// Real-model full chain against a live provider:
//   01 session + provider test
//   02 摸底 chat — the coach orients on the learner's background
//   03 /plan/generate — research-aware long-term route (prerequisites first)
//   04 goal/action start — the micro-goal inherits plan_id + current stage
//   05 instant practice — "给我出一道练习题" answers inline and mints NO card
//   06 candidate save — the learner asks to keep it; a candidate card exists
//      in the pool (status candidate) with the ledger event recorded
//   07 evidence — a real /learning/signal records the practice outcome and
//      joins the learner profile; the step records honestly whether the plan
//      adjustment pipeline produced a change candidate.
//
// Requires PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY (+
// PROBE_PROVIDER_MODEL, default MiniMax-M2.7) in the environment.
// Any hard failure stops the journey and writes the failure honestly.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repoRoot = "/Users/Apple/Desktop/trainer";
const serverDir = path.join(repoRoot, "server");
const python = path.join(serverDir, ".venv", "bin", "python");
const baseUrl = "http://127.0.0.1:34980";
const providerBase = process.env.PROBE_PROVIDER_BASE_URL ?? "";
const providerKey = process.env.PROBE_PROVIDER_API_KEY ?? "";
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M2.7";
const outDir =
  process.env.JOURNEY_OUT_DIR ??
  path.join(repoRoot, "output/maturity", `scenario1-${new Date().toISOString().replace(/[:.]/g, "-")}`);
fs.mkdirSync(outDir, { recursive: true });

if (!providerBase || !providerKey) {
  console.error("PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY required");
  process.exit(2);
}
try {
  await fetch(`${baseUrl}/health`);
  console.error(`port 34980 already served — kill the stale sidecar first`);
  process.exit(4);
} catch {}

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-scenario1-"));
let sidecar = null;
let providerTestResult = null;
let sidecarLog = "";
let failures = 0;

const providerPayload = {
  name: "scenario1",
  baseUrl: providerBase,
  apiKeyRef: "scenario1",
  model,
  protocol: "openai_chat_completions_compatible",
};

function sidecarProc() {
  return spawn(python, ["run_sidecar.py", "--host", "127.0.0.1", "--port", "34980"], {
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

function step(name, data, { fail = false, partial = false } = {}) {
  const record = { step: name, ok: !fail, ...(partial && !fail ? { partial: true } : {}), ...data };
  fs.writeFileSync(path.join(outDir, `${name}.json`), JSON.stringify(record, null, 2));
  console.log(`${fail ? "FAIL" : partial ? "PARTIAL" : "PASS"}  ${name}`);
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
  // GET /snapshot wraps the state in an {snapshot_revision, snapshot} envelope.
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
    workspace_id: "scenario1-ws",
    workspace_name: "World Models Journey",
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
    streaming_ready: providerTest.json?.streaming_ready === true,
  }, { fail: start.status !== 200 || !sessionId || providerTest.json?.ok !== true });

  // 02 — 摸底：learner states the goal and their background
  const background = await streamTurn({
    session_id: sessionId,
    workspace_id: "scenario1-ws",
    message: "我想系统掌握自动驾驶中的世界模型。我目前会 Python，懂基础机器学习（学过回归和神经网络），但没系统学过强化学习。我应该从哪里开始？",
    intent: "coach",
    active_view: "coach",
  });
  const bgOk = background.status === 200 && background.visible.length >= 40;
  step("02-background-chat", {
    status: background.status,
    visible_chars: background.visible.length,
    preview: background.visible.slice(0, 240),
    ...(background.status !== 200 ? { error_detail: errorDetail(background.text) } : {}),
  }, { fail: !bgOk });

  // 03 — 长期路线：research-aware plan generation (prerequisites first)
  const plan = await post("/plan/generate", {
    session_id: sessionId,
    workspace_id: "scenario1-ws",
    profile: {
      long_term_goal: "系统掌握自动驾驶中的世界模型",
      weekly_hours: 6,
      teaching_style: "guided",
      answer_policy: "adaptive",
      preferred_libraries: ["gymnasium", "pytorch"],
    },
    goals: [
      "理解世界模型在自动驾驶规划中的作用",
      "掌握一步预测与潜在动力学模型",
    ],
    provider: providerPayload,
    api_key: providerKey,
    last_test_result: providerTestResult,
  });
  const planStages = plan.json?.plan?.stages ?? plan.json?.stages ?? [];
  const planId = plan.json?.plan?.id ?? plan.json?.plan?.plan_id ?? "";
  const stageTitles = planStages.map((stage) => String(stage.title ?? ""));
  const routeOk = plan.status === 200 && planStages.length >= 2 && Boolean(planId);
  step("03-long-term-route", {
    status: plan.status,
    plan_id: planId,
    stage_count: planStages.length,
    stage_titles: stageTitles,
    ...(plan.status !== 200 ? { error_detail: errorDetail(plan.text) } : {}),
  }, { fail: !routeOk });

  // 04 — 微目标：goal starts and inherits the plan link
  const goal = await post("/goal/action", {
    session_id: sessionId,
    workspace_id: "scenario1-ws",
    action: "start",
    title: "系统掌握自动驾驶中的世界模型",
  });
  const goalJson = goal.json?.goal ?? {};
  const goalLinked = goal.status === 200 &&
    goalJson.planId === planId &&
    Boolean(String(goalJson.stageId ?? ""));
  step("04-goal-links-plan", {
    status: goal.status,
    goal_id: goalJson.goalId ?? "",
    plan_id: goalJson.planId ?? "",
    stage_id: goalJson.stageId ?? "",
    position: goalJson.currentPosition ?? "",
  }, { fail: !goalLinked });

  // 05 — 即时练习：practice request answers inline and mints NO card
  const beforeCards = await snapshot("scenario1-ws", sessionId);
  const cardsBefore = beforeCards.json?.memory?.training_card_candidates?.length ?? 0;
  const practice = await streamTurn({
    session_id: sessionId,
    workspace_id: "scenario1-ws",
    message: "给我出一道练习题，检验我对世界模型一步预测的理解。",
    intent: "coach",
    active_view: "coach",
  });
  const afterCards = await snapshot("scenario1-ws", sessionId);
  const cardsAfter = afterCards.json?.memory?.training_card_candidates?.length ?? 0;
  const practiceOk = practice.status === 200 && practice.visible.length >= 40;
  const noCardMinted = cardsAfter === cardsBefore;
  step("05-instant-practice-no-card", {
    status: practice.status,
    visible_chars: practice.visible.length,
    cards_before: cardsBefore,
    cards_after: cardsAfter,
    preview: practice.visible.slice(0, 200),
  }, { fail: !practiceOk || !noCardMinted });

  // 06 — 候选卡：the learner explicitly asks to keep it
  const card = await post("/training/generate-card", {
    session_id: sessionId,
    workspace_id: "scenario1-ws",
    source: "conversation_gap",
    card_type: "practice",
    focus_area: "世界模型一步预测",
    target_skill: "解释一步预测的目标并写出损失项",
    prompt: "用一行写出世界模型一步预测先做什么、要学习或预测什么，并指出损失项由哪些部分组成。",
    provider: providerPayload,
    api_key: providerKey,
  });
  const cardJson = card.json?.card ?? {};
  // Fresh snapshot: the ledger must be read AFTER the card generation.
  const afterCandidate = await snapshot("scenario1-ws", sessionId);
  // The unified ledger surfaces card intake as memory.learning_activity.
  const learningActivity = afterCandidate.json?.memory?.learning_activity ?? [];
  const candidateOk = card.status === 200 &&
    (cardJson.status ?? "candidate") === "candidate" &&
    Boolean(cardJson.card_id ?? "");
  const ledgerHasCandidate = learningActivity.some(
    (entry) => entry.eventType === "card_candidate_created" ||
      entry.event_type === "card_candidate_created"
  );
  step("06-candidate-card", {
    status: card.status,
    card_id: cardJson.card_id ?? "",
    card_status: cardJson.status ?? "",
    ledger_event: ledgerHasCandidate,
    activity_dump: learningActivity.slice(0, 6),
    ...(card.status !== 200 ? { error_detail: errorDetail(card.text) } : {}),
  }, { fail: !candidateOk || !ledgerHasCandidate });

  // 07 — 证据：a real learning signal records the practice outcome
  const signal = await post("/learning/signal", {
    session_id: sessionId,
    workspace_id: "scenario1-ws",
    concepts: ["世界模型一步预测"],
    outcome: "concept_answered_correctly",
    summary: "能够写出一步预测的目标：先根据动作预测下一状态，再对预测状态与真实状态的差距计算损失。",
    checks: ["能写出一步预测的损失项"],
    focus_area: "世界模型一步预测",
    action_type: "practice",
    verified_result: "",
  });
  const afterSignal = await snapshot("scenario1-ws", sessionId);
  const goalAfter = afterSignal.json?.goal ?? {};
  const activities = Array.isArray(goalAfter.activities) ? goalAfter.activities : [];
  const changeCandidates = afterSignal.json?.memory?.plan_change_candidates ?? [];
  step("07-evidence-and-plan", {
    signal_status: signal.status,
    signal_ok: signal.status === 200,
    goal_activities: activities.length,
    plan_change_candidates: changeCandidates.length,
    plan_change_titles: changeCandidates.map((item) => item.title ?? item.reason ?? ""),
    note: "记录真实学习信号；计划调整建议按现有治理管线如实记录（有无均为诚实结果）。",
  }, { fail: signal.status !== 200 });

  // Summary
  const summary = {
    scenario: "13-场景一：长期学习（世界模型）",
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
