// Full teaching journey: single process, single session, real model,
// chat → goal → card → answer → verify → projection → ledger → restart →
// clock advance → recall → FSRS update → next step. One JSON per step;
// any hard failure stops the journey and records the failure honestly.
//
// Set PROBE_PROVIDER_BASE_URL and PROBE_PROVIDER_API_KEY in the environment.
// PROBE_PROVIDER_MODEL optionally overrides the MiniMax default.
import { spawn } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

const repoRoot = fileURLToPath(new URL("../", import.meta.url));
const serverDir = path.join(repoRoot, "server");
const python = path.join(serverDir, ".venv", "bin", "python");
const port = Number(process.env.TRAINER_JOURNEY_PORT ?? "34979");
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("Invalid Trainer journey port.");
const baseUrl = `http://127.0.0.1:${port}`;
const providerBase = process.env.PROBE_PROVIDER_BASE_URL ?? "";
const providerKey = process.env.PROBE_PROVIDER_API_KEY ?? "";
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M3.1-Flash";

const outDir =
  process.env.JOURNEY_OUT_DIR ||
  path.join(
    repoRoot,
    "output/maturity",
    `full-journey-${new Date().toISOString().replace(/[:.]/g, "-")}`,
  );
fs.mkdirSync(outDir, { recursive: true });

if (!providerBase || !providerKey) {
  console.error("Set PROBE_PROVIDER_BASE_URL and PROBE_PROVIDER_API_KEY.");
  process.exit(2);
}

// Fail loudly if a stale sidecar owns the port.
try {
  await fetch(`${baseUrl}/health`);
  console.error(`Port ${port} is already serving a process.`);
  process.exit(4);
} catch {}

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-full-journey-"));
const DB = path.join(dataDir, "trainer.sqlite3");
const projectDir = path.join(dataDir, "learner-workspace");
fs.mkdirSync(projectDir);
let sidecar = null;
let providerTestResult = null;

function sidecarProc(extraEnv = {}) {
  const env = { ...process.env, TRAINER_DATA_DIR: dataDir, ...extraEnv };
  delete env.PROBE_PROVIDER_API_KEY;
  return spawn(python, ["run_sidecar.py", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: serverDir,
    env,
    stdio: ["ignore", "ignore", "ignore"],
  });
}

function startSidecar(extraEnv = {}) {
  sidecar = sidecarProc(extraEnv);
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

async function stopSidecar() {
  const child = sidecar;
  sidecar = null;
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  const exited = once(child, "exit");
  child.kill("SIGTERM");
  const killTimer = setTimeout(() => child.kill("SIGKILL"), 5000);
  try {
    await exited;
  } finally {
    clearTimeout(killTimer);
  }
}

const provider = {
  name: "journey",
  baseUrl: providerBase,
  apiKeyRef: "journey",
  model,
  protocol: "openai_chat_completions_compatible",
};

function redact(value) {
  return String(value ?? "").replaceAll(providerKey, "[redacted]");
}

async function learnerAnswer(name, messages) {
  const attempts = [];
  const endpoints = /\/v1$/.test(providerBase.replace(/\/$/, "")) ? [""] : ["/v1", ""];
  for (const prefix of endpoints) {
    writeArtifact(`${name}-request.json`, { messages, attempts });
    const response = await fetch(
      `${providerBase.replace(/\/$/, "")}${prefix}/chat/completions`,
      {
        method: "POST",
        signal: AbortSignal.timeout(480_000),
        headers: { "content-type": "application/json", authorization: `Bearer ${providerKey}` },
        body: JSON.stringify({ model, reasoning_effort: "low", max_tokens: 16384, messages }),
      },
    );
    const body = await response.json().catch(() => null);
    const choice = body?.choices?.[0];
    attempts.push({ endpoint: `${prefix}/chat/completions`, status: response.status, finish: choice?.finish_reason });
    if (response.status === 404 || response.status === 405) continue;
    const raw = choice?.message?.content;
    writeArtifact(`${name}-request.json`, { messages, attempts });
    if (typeof raw === "string") {
      if (raw.includes(providerKey)) throw new Error("Learner output contained the provider credential.");
      fs.writeFileSync(path.join(outDir, `${name}-raw.txt`), raw);
    }
    if (!response.ok || typeof raw !== "string" || !raw.trim() || choice.finish_reason === "length") {
      throw new Error(`No complete learner answer for ${name} (HTTP ${response.status}, finish=${choice?.finish_reason ?? "unknown"}).`);
    }
    return raw;
  }
  writeArtifact(`${name}-request.json`, { messages, attempts });
  throw new Error("The provider did not expose a supported chat completions endpoint.");
}

function pythonSubmission(raw) {
  const fenced = /^\s*```(?:python|py)?[ \t]*\r?\n([\s\S]*?)```\s*$/i.exec(raw);
  return fenced ? fenced[1] : raw;
}

function learnerTask(card, target) {
  const {
    title, scenario, problem_statement, constraints, deliverable, learner_deliverables,
    acceptance_criteria, expected_symbols,
  } = card;
  const contract = {
    file: target, title, scenario, problem_statement, constraints, deliverable,
    learner_deliverables, acceptance_criteria, expected_symbols,
  };
  return [
    {
      role: "system",
      content: "你是正在完成练习的学习者。实现题目要求的实际行为。只输出完整 Python 文件内容。",
    },
    { role: "user", content: JSON.stringify(contract, null, 2) },
  ];
}

async function post(route, body) {
  const response = await fetch(`${baseUrl}${route}`, {
    method: "POST",
    signal: AbortSignal.timeout(480_000),
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    // Keep non-JSON host errors in the artifact.
  }
  return { status: response.status, json, text };
}

function writeArtifact(file, data) {
  fs.writeFileSync(path.join(outDir, file), redact(JSON.stringify(data, null, 2)) + "\n");
}

const outcomes = {};
function step(name, data, { fail = false } = {}) {
  outcomes[name] = fail ? "failed" : "passed";
  writeArtifact(`${name}.json`, data);
  console.log(`[step] ${fail ? "FAIL" : "ok"} ${name}`);
  if (fail) {
    writeArtifact("FAILED.json", { failed_at: name, db_path: DB, data_dir: dataDir, ...data });
    throw new Error(`Acceptance failed at ${name}.`);
  }
}

function db() {
  return new DatabaseSync(DB, { readOnly: true });
}
function dbCount(sql) {
  const d = db();
  try { return Number(d.prepare(sql).get()?.n ?? -1); } catch { return -1; } finally { d.close(); }
}
function dbRows(sql, params = []) {
  const d = db();
  try { return d.prepare(sql).all(...params); } catch { return []; } finally { d.close(); }
}

// Ledger writes for a turn can commit during post-processing that runs just
// after the last SSE frame is flushed, so an immediate read can miss them.
// Poll briefly instead of failing the step on timing alone.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitForLedgerEvent(eventType, timeoutMs = 10_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    // The store's payload column is payload_ref_json (not payload).
    const rows = dbRows(
      "SELECT event_type, payload_ref_json AS payload FROM event_ledger WHERE event_type = ? ORDER BY rowid",
      [eventType],
    );
    if (rows.length > 0) return rows;
    await sleep(300);
  }
  return [];
}

async function streamRequest(route, body, requestId = crypto.randomUUID()) {
  const startedAt = performance.now();
  const streamId = crypto.randomUUID();
  const response = await fetch(`${baseUrl}${route}`, {
    method: "POST",
    signal: AbortSignal.timeout(480_000),
    headers: { accept: "text/event-stream", "content-type": "application/json" },
    body: JSON.stringify({
      ...body,
      provider,
      api_key: providerKey,
      last_test_result: providerTestResult,
      request_id: requestId,
      stream_id: streamId,
    }),
  });
  const result = {
    status: response.status, requestId, streamId, visible: "", chunkCount: 0,
    firstChunkMs: null, completed: false, outcome: null, json: null, errors: [], errorDetail: "",
  };
  if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
    result.errorDetail = errorDetail(await response.text());
    return result;
  }

  function readFrame(block) {
    const lines = block.split(/\r?\n/);
    const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
    const data = lines.filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, "")).join("\n");
    if (!data) return;
    const frame = JSON.parse(data);
    if (typeof frame.chunk === "string" && frame.chunk) {
      result.firstChunkMs ??= Math.round(performance.now() - startedAt);
      result.visible += frame.chunk;
      result.chunkCount += 1;
    }
    if (event === "complete") {
      result.completed = true;
      result.outcome = frame.reliability?.outcome ?? frame.response?.reliability?.outcome;
      result.json = frame.response;
    }
    if (event === "error") result.errors.push({ error: frame.error, terminal: frame.terminal === true });
  }

  let buffer = "";
  try {
    for await (const text of response.body.pipeThrough(new TextDecoderStream())) {
      const frames = (buffer + text).split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      frames.forEach(readFrame);
    }
  } catch (error) {
    result.errors.push({ error: redact(error), terminal: true });
  }
  result.errorDetail = result.errors.length ? errorDetail(JSON.stringify(result.errors)) : "";
  return result;
}

function streamSucceeded(stream) {
  return stream.status === 200 && stream.completed && stream.outcome === "success" &&
    !stream.errors.some((error) => error.terminal);
}

function streamSummary(stream) {
  const { status, requestId, streamId, chunkCount, firstChunkMs, completed, outcome, errors, errorDetail } = stream;
  return { status, requestId, streamId, chunkCount, firstChunkMs, completed, outcome, errors, errorDetail };
}

async function streamTurn(name, body) {
  writeArtifact(`${name}-request.json`, body);
  const turn = await streamRequest("/turn/stream", body);
  writeArtifact(`${name}-response.json`, {
    ...streamSummary(turn), visible: turn.visible, terminal_reply: turn.json?.reply,
  });
  return turn;
}

function errorDetail(text) {
  return redact(text).slice(0, 600);
}

// --------------------------------------------------------------------------

try {
  startSidecar();
  await waitForHealth();

  // Step 1 — natural chat with the real model.
  const start = await post("/session/start", {
    workspace_id: "full-journey-ws",
    workspace_name: "Full Journey",
    workspace_path: projectDir,
    workspace_trusted: true,
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

  const chat = await streamTurn("02-natural-chat", {
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
    stream: streamSummary(chat),
  }, { fail: !streamSucceeded(chat) || chat.visible.length < 40 });

  // Step 3 — explicit goal → goal_sessions=1 + goal_started ledger event.
  const goalTurn = await streamTurn("03-explicit-goal", {
    workspace_id: "full-journey-ws",
    session_id: sessionId,
    message: "帮我设定一个长期目标：3 天内能够独立解释 PPO 的裁剪目标，并手写对应的损失函数。",
    intent: "coach",
    active_view: "coach",
  });
  const goalCount = dbCount("SELECT COUNT(*) AS n FROM goal_sessions");
  const goalStarted = await waitForLedgerEvent("goal_started");
  step("03-explicit-goal", {
    turn_status: goalTurn.status,
    reply_chars: goalTurn.visible.length,
    goal_sessions: goalCount,
    goal_started_ledger: goalStarted.length > 0 ? JSON.parse(goalStarted[0].payload) : null,
    stream: streamSummary(goalTurn),
  }, { fail: !streamSucceeded(goalTurn) || goalCount !== 1 || goalStarted.length === 0 });

  // Step 4 — Coach explains with formulas (real model).
  const explain = await streamTurn("04-coach-explain", {
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
    stream: streamSummary(explain),
  }, { fail: !streamSucceeded(explain) || explain.visible.length < 80 });

  const cardRoute = "/training/generate-card/stream";
  const cardRequestBody = {
    session_id: sessionId,
    workspace_id: "full-journey-ws",
    source: "conversation_gap",
    card_type: "practice",
    focus_area: "PPO 裁剪目标",
    target_skill: "解释 PPO clip 目标并手写损失函数",
    context_hint: "请出一道可使用 Python 标准库完成的独立编程练习。输入为新旧对数概率列表、优势列表和裁剪阈值，输出为标量损失。写明函数名称、参数、边界条件和可运行的行为验收用例，并提供一道开卷学习后能独立回忆的概念题及其参考答案。",
    response_language: "zh-CN",
  };
  writeArtifact("05-card-request.json", { route: cardRoute, body: cardRequestBody });
  const cardAttempts = [];
  let card;
  for (let number = 1; number <= 2; number += 1) {
    card = await streamRequest(cardRoute, cardRequestBody);
    const attempt = streamSummary(card);
    cardAttempts.push(attempt);
    writeArtifact(`05-card-stream-${number}.json`, {
      ...attempt, visible: card.visible, terminal_response: card.json,
    });
    if (card.status < 500 && card.status !== 429 && card.outcome !== "failure") break;
    if (number === 1) await sleep(3000);
  }
  const cardData = card.json?.card ?? card.json?.data?.card;
  const cardId = cardData?.card_id ?? "";
  const degraded = cardData?.degraded === true || card.json?.degraded === true;
  const cardRows = cardId
    ? dbRows("SELECT payload FROM structured_memory WHERE payload LIKE ? LIMIT 1", [`%${cardId}%`]) : [];
  step("05-training-card", {
    route: cardRoute, status: card.status, card_id: cardId, title: cardData?.title,
    card_status: cardData?.status, card_scenario: cardData?.scenario_pack,
    degraded, persisted: cardRows.length > 0, stream_attempts: cardAttempts,
    behavior_contract: cardData?.python_behavior_contract,
  }, {
    fail: !streamSucceeded(card) || card.chunkCount === 0 || !cardId || degraded ||
      !cardRows.length || !cardData?.python_behavior_contract?.cases?.length,
  });

  const cardTarget = String(cardData.files_to_touch?.[0] ?? "ppo_clip_loss.py")
    .trim().replace(/^[`'"]+|[`'"]+$/g, "").replaceAll("\\", "/");
  const targetPath = path.resolve(projectDir, cardTarget);
  if (!targetPath.startsWith(projectDir + path.sep) || path.extname(targetPath) !== ".py") {
    throw new Error("The model card did not name a usable Python path in the isolated workspace.");
  }
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  const task = learnerTask(cardData, cardTarget);
  const raw = await learnerAnswer("06-original-answer", task);
  let submission = pythonSubmission(raw);
  const attemptStart = await post("/training/attempt/start", {
    workspace_id: "full-journey-ws", card_id: cardId, file_path: cardTarget,
    assistance_level: "none",
  });
  const attemptId = attemptStart.json?.attempt?.attempt_id;
  const assistance = [];
  async function saveSubmission(text, number) {
    fs.writeFileSync(targetPath, text);
    fs.writeFileSync(path.join(outDir, `06-submitted-${number}.py`), text);
    const sha256 = crypto.createHash("sha256").update(text).digest("hex");
    const update = await post("/training/attempt/update", {
      workspace_id: "full-journey-ws", attempt_id: attemptId,
      answer_draft: text, file_hash: sha256, file_path: cardTarget,
    });
    if (update.status !== 200) throw new Error(`Could not save learner submission ${number}.`);
    return sha256;
  }
  let hash = attemptId ? await saveSubmission(submission, 1) : null;
  step("06-learner-answer", {
    attempt_start_status: attemptStart.status, attempt_id: attemptId, submission_sha256: hash,
    workspace_file: cardTarget, simulation: "MiniMax acting as learner", assistance,
  }, { fail: !attemptId || !hash });

  async function grade(content, number, artifactHash) {
    const evaluation = await post("/evaluate/current-file", {
      session_id: sessionId, workspace_id: "full-journey-ws", file_path: cardTarget,
      content, language_id: "python", evaluation_source: "training",
      training_phase: "verify", training_card_id: cardId,
    });
    const report = evaluation.json ?? {};
    writeArtifact(`07-evaluation-${number}.json`, {
      http_status: evaluation.status, sha256: artifactHash, assistance,
      report, ...(evaluation.status !== 200 ? { error: errorDetail(evaluation.text) } : {}),
    });
    return { status: evaluation.status, report };
  }

  const gradingAttempts = [];
  let gradeResult = await grade(submission, 1, hash);
  gradingAttempts.push({ sha256: hash, http: gradeResult.status, passed: gradeResult.report.passed });
  if (gradeResult.status === 200 && gradeResult.report.passed === false && gradeResult.report.verification_scope === "behavior") {
    const hint = cardData.hint_ladder?.[0] ?? "";
    const feedback = {
      summary: gradeResult.report.summary,
      next_step: gradeResult.report.next_step,
      checks: gradeResult.report.dynamic_checks?.filter((check) => check.status !== "passed"),
    };
    assistance.push({ type: "grader_feedback", feedback });
    if (hint) assistance.push({ type: "card_hint", text: hint });
    writeArtifact("07-assistance.json", assistance);
    const updated = await post("/training/attempt/update", {
      workspace_id: "full-journey-ws", attempt_id: attemptId, assistance_level: "hint_level_1",
    });
    if (updated.json?.attempt?.assistance_level !== "hint_level_1") {
      throw new Error("Assistance was not persisted before retry.");
    }
    const revised = await learnerAnswer("07-revised-answer", [
      ...task,
      { role: "assistant", content: raw },
      { role: "user", content: `根据以下实际反馈修正实现，输出完整 Python 文件。\n${JSON.stringify({ feedback, hint })}` },
    ]);
    submission = pythonSubmission(revised);
    hash = await saveSubmission(submission, 2);
    gradeResult = await grade(submission, 2, hash);
    gradingAttempts.push({ sha256: hash, http: gradeResult.status, passed: gradeResult.report.passed });
  }
  const { report } = gradeResult;
  step("07-verify-current-file", {
    status: gradeResult.status, passed: report.passed, verification_scope: report.verification_scope,
    card_target: cardTarget, summary: report.summary, grading_attempts: gradingAttempts, assistance,
  }, { fail: gradeResult.status !== 200 || report.passed !== true || report.verification_scope !== "behavior" });

  const query = new URLSearchParams({ workspace_id: "full-journey-ws" });
  const projectionResponse = await fetch(`${baseUrl}/training/attempt/${encodeURIComponent(attemptId)}/projection?${query}`);
  const { projection = {} } = await projectionResponse.json();
  const requiredAssistance = assistance.length ? "hint_level_1" : "none";
  const nextState = assistance.length ? "assisted" : "independent";
  const dimension = Object.entries(projection).find(([, state]) =>
    state.evidence?.some((item) => item.attempt_id === attemptId &&
      item.trust_level === "controlled_check" && item.result === "passed" &&
      item.assistance_level === requiredAssistance)
  );
  const goalLedger = await waitForLedgerEvent("goal_activity_recorded");
  const evidenceLedger = await waitForLedgerEvent("training_evidence_recorded");
  step("08-projection-and-ledger", {
    expected_state: nextState, dimension: dimension?.[0], projected: dimension?.[1],
    goal_activity_events: goalLedger.length, training_evidence_events: evidenceLedger.length,
  }, {
    fail: !projectionResponse.ok || dimension?.[1]?.state !== nextState || !goalLedger.length || !evidenceLedger.length,
  });

  // Step 9 — restart sidecar → conversation and goal restored.
  await stopSidecar();
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

  function savedSchedule(snapshot) {
    return snapshot?.memory?.workspace?.latest_training_fsrs_states?.[cardId] ??
      snapshot?.memory?.workspace?.latestTrainingFsrsStates?.[cardId];
  }
  const initialSchedule = savedSchedule(restored.json);
  const dueAt = Date.parse(initialSchedule?.next_due_at ?? initialSchedule?.due ?? "");
  if (!Number.isFinite(dueAt)) {
    step("10-due-review-surfaces", { card_id: cardId, initial_schedule: initialSchedule }, { fail: true });
  }
  const advance = new Date(Math.max(Date.now(), dueAt) + 60_000).toISOString();
  await stopSidecar();
  startSidecar({ TRAINER_TEST_NOW: advance });
  await waitForHealth();
  const dueStart = await post("/session/start", {
    workspace_id: "full-journey-ws", session_id: sessionId, workspace_name: "Full Journey",
  });
  const dueReviews = dueStart.json?.memory?.due_reviews ?? [];
  const dueCard = dueReviews.find((review) => review.training_card_id === cardId);
  step("10-due-review-surfaces", {
    clock: advance, initial_schedule: initialSchedule, due_card: dueCard, due_count: dueReviews.length,
  }, { fail: !dueCard });

  const recallAnswer = await learnerAnswer("11-recall-answer", [
    { role: "system", content: "你是正在完成延迟复习的学习者。根据问题给出你的回答。" },
    { role: "user", content: cardData.question },
  ]);
  const recall = await post("/training/flashcard/answer", {
    workspace_id: "full-journey-ws", card_id: cardId, learner_answer: recallAnswer,
  });
  const afterRecall = await post("/session/start", {
    workspace_id: "full-journey-ws", session_id: sessionId, workspace_name: "Full Journey",
  });
  const recalledSchedule = savedSchedule(afterRecall.json);
  const fsrsUpdated = Boolean(recalledSchedule?.last_reviewed_at &&
    recalledSchedule.last_reviewed_at !== initialSchedule.last_reviewed_at &&
    Number(recalledSchedule.reps) > Number(initialSchedule.reps));
  step("11-recall-round", {
    status: recall.status, recall_correct: recall.json?.correct, recall_evidence: recall.json?.recall_evidence,
    schedule_before: initialSchedule, schedule_after: recalledSchedule, fsrs_updated: fsrsUpdated,
  }, { fail: recall.status !== 200 || !fsrsUpdated });

  // Step 12 — Coach gives the next step based on the review result.
  const nextStepTurn = await streamTurn("12-next-step-after-review", {
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
    stream: streamSummary(nextStepTurn),
  }, { fail: !streamSucceeded(nextStepTurn) || nextStepTurn.visible.length < 40 });

  console.log(`FULL_JOURNEY_OK ${outDir}`);
} catch (error) {
  writeArtifact("error.json", { error: error instanceof Error ? error.stack : String(error) });
  console.error(`FULL_JOURNEY_FAILED ${outDir}`, redact(error));
  process.exitCode = 1;
} finally {
  await stopSidecar();
  writeArtifact("journey-report.json", {
    steps: outcomes,
    connectivity: outcomes["01-session-start"] ?? "unverified",
    structural_learning_evidence: outcomes["08-projection-and-ledger"] ?? "unverified",
    delayed_recall: outcomes["11-recall-round"] ?? "unverified",
    teaching_quality: "requires review of the captured model responses",
    interaction_quality: "requires the separate VS Code visual journey",
  });
}
