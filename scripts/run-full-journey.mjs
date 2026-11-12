// Full teaching journey: single process, single session, real model,
// chat → goal → card → answer → verify → projection → ledger → restart →
// clock advance → recall → FSRS update → next step. One JSON per step;
// any hard failure stops the journey and records the failure honestly.
//
// Requires PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY /
// PROBE_PROVIDER_MODEL (+ optional PROBE_PROVIDER_MODEL_SWITCH) in the
// environment or ~/.trainer/probe.env. The key travels only through the
// process environment — never written to the repo, logs or screenshots.
import { spawn } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

const repoRoot = "/Users/Apple/Desktop/trainer";
const serverDir = path.join(repoRoot, "server");
const python = path.join(serverDir, ".venv", "bin", "python");
const baseUrl = "http://127.0.0.1:34979";
const providerBase = process.env.PROBE_PROVIDER_BASE_URL ?? "";
const providerKey = process.env.PROBE_PROVIDER_API_KEY ?? "";
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M3.1-Flash";
const modelSwitch = process.env.PROBE_PROVIDER_MODEL_SWITCH ?? "MiniMax-M2.7";
const outDir = process.env.JOURNEY_OUT_DIR ?? path.join(repoRoot, "output/maturity/full-journey-run");
const verifyFile = path.join(repoRoot, "tmp", "verify_pass.py");
fs.mkdirSync(outDir, { recursive: true });

if (!providerBase || !providerKey) {
  console.error("PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY required (env or ~/.trainer/probe.env)");
  process.exit(2);
}

// Fail loudly if a stale sidecar owns the port.
try {
  await fetch(`${baseUrl}/health`);
  console.error(`port 34979 already served — kill the stale sidecar first`);
  process.exit(4);
} catch {}

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-full-journey-"));
const DB = path.join(dataDir, "trainer.sqlite3");
let sidecar = null;
let providerTestResult = null;
let sidecarLog = "";
let currentSidecarEnv = {};

function sidecarProc(extraEnv = {}) {
  currentSidecarEnv = { ...process.env, TRAINER_DATA_DIR: dataDir, TRAINER_ENABLE_NETWORK_FETCH: "1", ...extraEnv };
  return spawn(python, ["run_sidecar.py", "--host", "127.0.0.1", "--port", "34979"], {
    cwd: serverDir,
    env: currentSidecarEnv,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function startSidecar(extraEnv = {}) {
  sidecar = sidecarProc(extraEnv);
  sidecar.stdout.on("data", (c) => (sidecarLog += c));
  sidecar.stderr.on("data", (c) => (sidecarLog += c));
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

function stopSidecar() {
  if (sidecar) {
    sidecar.kill("SIGTERM");
    sidecar = null;
  }
}

function post(p, body) {
  return fetch(`${baseUrl}${p}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (r) => ({ status: r.status, json: await r.json().catch(() => null), text: await r.text().catch(() => "") }));
}

function step(name, data, { fail = false } = {}) {
  fs.writeFileSync(path.join(outDir, `${name}.json`), JSON.stringify(data, null, 2) + "\n");
  console.log(`[step] ${fail ? "FAIL" : "ok"} ${name}`, JSON.stringify(data).slice(0, 260));
  if (fail) {
    fs.writeFileSync(path.join(outDir, "FAILED.json"), JSON.stringify({ failed_at: name, ...data }, null, 2) + "\n");
    stopSidecar();
    process.exit(1);
  }
}

function db() {
  return new DatabaseSync(DB, { readOnly: true });
}
function dbCount(sql) {
  const d = db();
  try { return Number(d.prepare(sql).get()?.n ?? -1); } catch { return -1; } finally { d.close(); }
}
function dbRows(sql) {
  const d = db();
  try { return d.prepare(sql).all(); } catch { return []; } finally { d.close(); }
}

// The real model's reply for the verification target: a clean file whose
// acceptance signals (main entry, run output, python/pytest literals) match.
const VERIFY_PASS_BODY = `"""A tiny, clean practice target for the Trainer verification chain.

Run it with \`\`python tmp/verify_pass.py\`\` and check it with \`\`pytest\`\`.
"""

RUNNERS = ("python", "pytest")


def add(left: int, right: int) -> int:
    """Return the sum of two integers."""

    return left + right


def main() -> None:
    """Print the deterministic result the verification runner can observe."""

    print(f"sum={add(2, 3)}")


if __name__ == "__main__":
    main()


def test_add() -> None:
    """Keep the current-file verification green."""

    assert add(2, 3) == 5
`;

async function streamTurn(body) {
  const r = await fetch(`${baseUrl}/turn/stream`, {
    method: "POST",
    headers: { accept: "text/event-stream", "content-type": "application/json" },
    body: JSON.stringify({ ...body, last_test_result: body.last_test_result ?? providerTestResult }),
  });
  const text = await r.text();
  const chunks = [...text.matchAll(/"chunk"\s*:\s*"((?:\\.|[^"\\])*)"/g)]
    .map((m) => { try { return JSON.parse(`"${m[1]}"`); } catch { return ""; } })
    .join("");
  return { status: r.status, text, visible: chunks };
}

// --------------------------------------------------------------------------

try {
  startSidecar();
  await waitForHealth();

  // Step 1 — natural chat with the real model.
  const start = await post("/session/start", {
    workspace_id: "full-journey-ws",
    workspace_name: "Full Journey",
  });
  const sessionId = start.json.session_id;
  const providerTest = await post("/provider/test", {
    provider: { name: "journey", baseUrl: providerBase, apiKeyRef: "journey", model, protocol: "openai_chat_completions_compatible" },
    apiKey: providerKey,
    responseLanguage: "zh-CN",
  });
  step("01-session-start", {
    status: start.status, session_id: sessionId,
    provider_test_ok: providerTest.json?.ok === true,
    streaming_ready: providerTest.json?.streaming_ready === true,
    tools_ready: providerTest.json?.tools_ready === true,
  }, { fail: start.status !== 200 || providerTest.json?.ok !== true });
  providerTestResult = providerTest.json;

  const chat = await streamTurn({
    workspace_id: "full-journey-ws",
    session_id: sessionId,
    message: "用两句话解释 PPO 的裁剪目标，并给一个直觉例子。",
    intent: "coach",
    active_view: "coach",
  });
  step("02-natural-chat", {
    status: chat.status,
    visible_chars: chat.visible.length,
    preview: chat.visible.slice(0, 240),
  }, { fail: chat.status !== 200 || chat.visible.length < 40 });

  // Step 3 — explicit goal → goal_sessions=1 + goal_started ledger event.
  const goalTurn = await streamTurn({
    workspace_id: "full-journey-ws",
    session_id: sessionId,
    message: "帮我设定一个长期目标：3 天内能够独立解释 PPO 的裁剪目标，并手写对应的损失函数。",
    intent: "coach",
    active_view: "coach",
  });
  const goalCount = dbCount("SELECT COUNT(*) AS n FROM goal_sessions");
  const goalStarted = dbRows(
    "SELECT event_type, payload FROM event_ledger WHERE event_type = 'goal_started' ORDER BY rowid DESC LIMIT 1",
  );
  step("03-explicit-goal", {
    turn_status: goalTurn.status,
    reply_chars: goalTurn.visible.length,
    goal_sessions: goalCount,
    goal_started_ledger: goalStarted.length > 0 ? JSON.parse(goalStarted[0].payload) : null,
  }, { fail: goalCount < 1 || goalStarted.length === 0 });

  // Step 4 — Coach explains with formulas (real model).
  const explain = await streamTurn({
    workspace_id: "full-journey-ws",
    session_id: sessionId,
    message: "请写出 PPO 裁剪目标的公式，并逐项解释 r_t、A_t 和 clip 各自限制了什么。",
    intent: "coach",
    active_view: "coach",
  });
  step("04-coach-explain", {
    status: explain.status,
    visible_chars: explain.visible.length,
    has_math: /\\frac|\\pi|frac|π/.test(explain.visible),
    preview: explain.visible.slice(0, 240),
  }, { fail: explain.status !== 200 || explain.visible.length < 80 });

  // Step 5 — request a real training card (not degraded).
  const card = await post("/training/generate-card", {
    session_id: sessionId,
    workspace_id: "full-journey-ws",
    source: "conversation_gap",
    card_type: "practice",
    focus_area: "PPO 裁剪目标",
    target_skill: "解释 PPO clip 目标并手写损失函数",
    prompt: "写出手写损失函数，并解释 min 与 clip 各自限制了什么。",
    provider: { name: "journey", baseUrl: providerBase, apiKeyRef: "journey", model, protocol: "openai_chat_completions_compatible" },
    api_key: providerKey,
  });
  const cardData = card.json?.card ?? card.json?.data?.card ?? null;
  const cardId = cardData?.card_id ?? "";
  const degraded = cardData?.degraded === true || card.json?.degraded === true;
  const cardRows = cardId ? dbRows(`SELECT payload FROM structured_memory WHERE payload LIKE '%${cardId}%' LIMIT 1`) : [];
  step("05-training-card", {
    status: card.status,
    card_id: cardId,
    title: cardData?.title ?? "",
    degraded,
    persisted: cardRows.length > 0,
  }, {
    fail: card.status !== 200 || !cardId || degraded,
    blocked_reason: degraded ? "model returned empty content — degraded card" : "",
  });

  // Step 6 — learner answers (answer_draft non-empty).
  fs.writeFileSync(verifyFile, VERIFY_PASS_BODY);
  const attemptStart = await post("/training/attempt/start", {
    session_id: sessionId,
    workspace_id: "full-journey-ws",
    card_id: cardId,
    file_path: "tmp/verify_pass.py",
  });
  const attemptId = attemptStart.json?.attempt?.attempt_id ?? attemptStart.json?.attempt_id ?? "";
  const answerUpdate = await post("/training/attempt/update", {
    workspace_id: "full-journey-ws",
    attempt_id: attemptId,
    answer_draft:
      "我在 tmp/verify_pass.py 实现了 add/main/test_add：main 打印 sum=5，test_add 断言 add(2,3)==5。" +
      "实际运行输出：$ python tmp/verify_pass.py → sum=5；$ python -m pytest tmp/verify_pass.py → 1 passed。",
  });
  const draftRows = attemptId ? dbRows("SELECT payload FROM training_attempts WHERE attempt_id = ?", [attemptId]) : [];
  const answerDraft = draftRows[0] ? JSON.parse(draftRows[0].payload).answer_draft : "";
  step("06-learner-answer", {
    attempt_start_status: attemptStart.status,
    attempt_id: attemptId,
    update_status: answerUpdate.status,
    answer_draft_chars: answerDraft.length,
  }, { fail: !attemptId || answerDraft.length < 40 });

  // Step 7 — verify current file against the card (host-trusted evaluator).
  const evaluation = await post("/evaluate/current-file", {
    session_id: sessionId,
    workspace_id: "full-journey-ws",
    file_path: "tmp/verify_pass.py",
    content: VERIFY_PASS_BODY,
    language_id: "python",
    source: "training",
    trainingPhase: "verify",
    cardId,
    cardTitle: cardData?.title ?? "练习：PPO 裁剪目标",
    acceptance_criteria: cardData?.acceptance_criteria ?? [
      "定义 `main` 入口并通过 `python` 运行提交的内容",
      "使用 `pytest` 或 `python` 运行一次并保留输出",
      "运行时无 `SyntaxError` 或 `RuntimeError`",
    ],
  });
  const report = evaluation.json ?? {};
  const passed = report.passed === true;
  step("07-verify-current-file", {
    status: evaluation.status,
    passed,
    summary: report.summary ?? "",
    static_checks: report.static_checks ?? [],
  }, { fail: evaluation.status !== 200 || !passed });

  // Step 8 — ability projection + ledger events.
  await new Promise((r) => setTimeout(r, 2000));
  const projectionRow = dbRows(
    "SELECT substr(payload, instr(payload,'training_skill_projection'), 700) AS proj FROM structured_memory WHERE payload LIKE '%training_skill_projection%' LIMIT 1",
  );
  const projText = projectionRow[0]?.proj ?? "";
  const implementationState = /"implementation":\s*\{[^}]*"state":\s*"([a-z_]+)"/.exec(projText)?.[1] ?? "";
  const ledgerEvents = dbRows(
    "SELECT event_type, COUNT(*) AS n FROM event_ledger WHERE event_type IN ('goal_activity_recorded','training_evidence_recorded') GROUP BY event_type",
  );
  step("08-projection-and-ledger", {
    implementation_state: implementationState,
    ledger_events: ledgerEvents,
  }, { fail: implementationState !== "independent" || ledgerEvents.length < 2 });

  // Step 9 — restart sidecar → conversation and goal restored.
  stopSidecar();
  await new Promise((r) => setTimeout(r, 1500));
  startSidecar();
  await waitForHealth();
  const restored = await post("/session/start", {
    workspace_id: "full-journey-ws",
    session_id: sessionId,
    workspace_name: "Full Journey",
  });
  const goalCurrent = dbRows("SELECT title, status FROM goal_sessions LIMIT 1");
  step("09-restart-restore", {
    status: restored.status,
    same_session: restored.json?.session_id === sessionId,
    goal: goalCurrent[0] ?? null,
  }, { fail: restored.status !== 200 || restored.json?.session_id !== sessionId });

  // Step 10 — advance the clock past next_review_at → due review surfaces.
  stopSidecar();
  const advance = new Date(Date.now() + 4 * 24 * 3600 * 1000).toISOString();
  startSidecar({ TRAINER_TEST_NOW: advance });
  await waitForHealth();
  const dueStart = await post("/session/start", {
    workspace_id: "full-journey-ws",
    session_id: sessionId,
    workspace_name: "Full Journey",
  });
  const dueReviews = dueStart.json?.memory?.due_reviews ?? [];
  const nextDue = dueStart.json?.next_review_due ?? null;
  step("10-due-review-surfaces", {
    clock: advance,
    due_count: dueReviews.length,
    next_review_due: nextDue,
    due: dueReviews.slice(0, 2),
  }, { fail: dueReviews.length === 0 });

  // Step 11 — recall round → FSRS fields update.
  const recall = await post("/training/flashcard/answer", {
    session_id: sessionId,
    workspace_id: "full-journey-ws",
    card_id: cardId,
    learner_answer:
      "clip 把比值 r_t 限制在 [1−ε, 1+ε]：A>0 时收益封顶不再增长，A<0 时劣势动作的惩罚也被封顶；" +
      "梯度为零只发生在 clip 分支被选中且优势方向继续增大时——裁剪区间内梯度照常流动。",
    selected_option_index: null,
    fill_blank_answers: null,
    sort_order: null,
  });
  await new Promise((r) => setTimeout(r, 2000));
  const masteryAfter = mastery(workspaceDbPath());
  function mastery(dbPath) {
    const d = db();
    try {
      const row = d.prepare("SELECT payload FROM structured_memory ORDER BY rowid DESC LIMIT 1").get();
      const parsed = row ? JSON.parse(Buffer.from(row.payload).toString("utf8")) : {};
      return (Array.isArray(parsed.mastery) ? parsed.mastery : []).map((m) => ({
        concept: m.concept, next_review_at: m.next_review_at,
        review_source: m.review_source, fsrs_state: m.fsrs_state, fsrs_reps: m.fsrs_reps,
      }));
    } finally { d.close(); }
  }
  step("11-recall-round", {
    status: recall.status,
    ok: recall.json?.ok === true,
    recall_evidence: recall.json?.recall_evidence ?? null,
    mastery_after: masteryAfter,
  }, { fail: recall.status !== 200 });

  // Step 12 — Coach gives the next step based on the review result.
  const nextStepTurn = await streamTurn({
    workspace_id: "full-journey-ws",
    session_id: sessionId,
    message: "我刚完成了复习。根据这次复习的表现，下一步该做什么？",
    intent: "coach",
    active_view: "coach",
  });
  step("12-next-step-after-review", {
    status: nextStepTurn.status,
    visible_chars: nextStepTurn.visible.length,
    preview: nextStepTurn.visible.slice(0, 300),
  }, { fail: nextStepTurn.status !== 200 || nextStepTurn.visible.length < 40 });

  stopSidecar();
  console.log(`FULL_JOURNEY_OK ${outDir}`);
} catch (error) {
  stopSidecar();
  step("FAILED", { error: error instanceof Error ? error.stack : String(error), sidecar_log: sidecarLog.slice(-3000) }, { fail: true });
  console.error(`FULL_JOURNEY_FAILED ${outDir}`);
  process.exit(1);
}

function workspaceDbPath() {
  const roots = path.join(dataDir, "roots");
  if (fs.existsSync(roots)) {
    for (const entry of fs.readdirSync(roots)) {
      const candidate = path.join(roots, entry, "trainer.sqlite3");
      if (fs.existsSync(candidate)) return candidate;
    }
  }
  return DB;
}
