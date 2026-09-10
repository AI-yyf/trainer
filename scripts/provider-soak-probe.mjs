import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");

const sidecarUrl = (process.env.TRAINER_TURN_SMOKE_SIDECAR_URL ?? "http://127.0.0.1:8765")
  .trim()
  .replace(/\/+$/, "");
const providerBaseUrl = (
  process.env.TRAINER_TURN_SMOKE_PROVIDER_BASE_URL ??
  process.env.TRAINER_PROVIDER_SMOKE_BASE_URL ??
  ""
)
  .trim()
  .replace(/\/+$/, "");
const providerApiKey = (
  process.env.TRAINER_TURN_SMOKE_PROVIDER_API_KEY ??
  process.env.TRAINER_PROVIDER_SMOKE_API_KEY ??
  ""
).trim();
const providerModel = (
  process.env.TRAINER_TURN_SMOKE_PROVIDER_MODEL ??
  process.env.TRAINER_PROVIDER_SMOKE_MODEL ??
  "MiniMax-M3"
).trim();
const providerProtocol = (
  process.env.TRAINER_TURN_SMOKE_PROVIDER_PROTOCOL ??
  process.env.TRAINER_PROVIDER_SMOKE_PROTOCOL ??
  "openai_chat_completions_compatible"
).trim();
const soakTurns = Math.max(2, Number(process.env.TRAINER_SOAK_TURNS ?? "4") || 4);
const modeArg = (process.argv[2] ?? process.env.TRAINER_SOAK_MODE ?? "all").trim().toLowerCase();

function redact(text) {
  let out = String(text ?? "");
  if (providerApiKey) out = out.split(providerApiKey).join("sk-***");
  out = out.replace(/sk-[A-Za-z0-9_-]{8,}/g, "sk-***");
  return out;
}

function hostOnly(url) {
  try {
    return new URL(url).host;
  } catch {
    return "(invalid-url)";
  }
}

function providerPayload(name = "trainer-soak-probe") {
  return {
    name,
    baseUrl: providerBaseUrl,
    apiKeyRef: "trainer.soak-probe",
    model: providerModel,
    protocol: providerProtocol,
    requestDefaults: {
      extra_body: {
        thinking: { type: "disabled" },
      },
    },
  };
}

async function postJson(url, payload, { signal } = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  const text = await response.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = undefined;
  }
  return { response, text, json };
}

async function getHealth(base = sidecarUrl) {
  const response = await fetch(`${base}/health`, { method: "GET" });
  const text = await response.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = undefined;
  }
  return { ok: response.ok, status: response.status, text, json };
}

async function waitForHealth({ timeoutMs = 60000, expectDownFirst = false } = {}) {
  const started = Date.now();
  let sawDown = !expectDownFirst;
  while (Date.now() - started < timeoutMs) {
    try {
      const health = await getHealth();
      if (!health.ok) {
        sawDown = true;
      } else if (sawDown || !expectDownFirst) {
        return { ok: true, elapsedMs: Date.now() - started, health };
      }
    } catch {
      sawDown = true;
    }
    await delay(500);
  }
  return { ok: false, elapsedMs: Date.now() - started, sawDown };
}

async function startSession(workspaceId) {
  return postJson(`${sidecarUrl}/session/start`, {
    workspace_id: workspaceId,
    workspace_name: workspaceId,
    profile: {
      long_term_goal: "Soak-probe conversation continuity.",
      weekly_hours: 2,
      teaching_style: "guided",
      answer_policy: "guided",
    },
  });
}

function turnPayload(sessionId, workspaceId, message) {
  return {
    session_id: sessionId,
    workspace_id: workspaceId,
    intent: "coach",
    message,
    answer_mode: "guided",
    response_language: "zh-CN",
    use_agent_loop: false,
    provider: providerPayload(),
    api_key: providerApiKey,
  };
}

async function shortTurn(sessionId, workspaceId, message) {
  const started = Date.now();
  const result = await postJson(`${sidecarUrl}/turn`, turnPayload(sessionId, workspaceId, message));
  const reply = String(result.json?.reply?.content ?? "").trim();
  const secretClean = !providerApiKey || !String(result.text).includes(providerApiKey);
  const responseSessionId = String(
    result.json?.session_id ?? result.json?.snapshot?.session_id ?? "",
  ).trim();
  const messageCount = Array.isArray(result.json?.snapshot?.messages)
    ? result.json.snapshot.messages.length
    : 0;
  let category = "success";
  if (!result.response.ok) {
    const detailState = result.json?.detail?.state || result.json?.detail?.status;
    if (result.response.status === 401 || result.response.status === 403) category = "authentication_failed";
    else if (result.response.status === 429) category = "rate_limit";
    else if (result.response.status === 409 && String(detailState || "").includes("session_not_found")) {
      category = "session_not_found";
    } else category = "turn_failed";
  } else if (!reply) {
    category = "empty_stream";
  } else if (!secretClean) {
    category = "secret_leak";
  }
  return {
    httpStatus: result.response.status,
    ok: result.response.ok && Boolean(reply) && secretClean,
    replyChars: reply.length,
    secretClean,
    responseSessionId,
    messageCount,
    sameSession: !responseSessionId || responseSessionId === sessionId,
    elapsedMs: Date.now() - started,
    category,
  };
}

async function fetchSessionHistory(sessionId, workspaceId) {
  const url = new URL(`${sidecarUrl}/session/history`);
  url.searchParams.set("session_id", sessionId);
  url.searchParams.set("workspace_id", workspaceId);
  url.searchParams.set("limit", "20");
  const response = await fetch(url, { method: "GET" });
  const text = await response.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = undefined;
  }
  return { ok: response.ok, status: response.status, json, text: redact(text) };
}

function durableDataEnv(baseEnv = process.env) {
  const dataDir = path.join(repoRoot, ".trainer");
  return {
    ...baseEnv,
    TRAINER_DATA_DIR: dataDir,
  };
}

function spawnSidecar() {
  const child = spawn(
    path.join(repoRoot, "server", ".venv", "bin", "python"),
    [path.join(repoRoot, "server", "run_sidecar.py"), "--host", "127.0.0.1", "--port", "8765", "--reload"],
    {
      // Keep cwd at repo root + absolute TRAINER_DATA_DIR so restart cannot split SQLite.
      cwd: repoRoot,
      detached: true,
      stdio: "ignore",
      env: durableDataEnv(),
    },
  );
  child.unref();
  return child;
}

async function hardRestartSidecar() {
  const pids = await listSidecarPids();
  for (const pid of pids) {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      /* ignore */
    }
  }
  await delay(1000);
  for (const pid of await listSidecarPids()) {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      /* ignore */
    }
  }
  let restarted = await waitForHealth({ timeoutMs: 5000, expectDownFirst: false });
  if (restarted.ok) {
    // Still healthy somehow; force another terminate cycle.
    for (const pid of await listSidecarPids()) {
      try {
        process.kill(pid, "SIGKILL");
      } catch {
        /* ignore */
      }
    }
    await delay(500);
  }
  spawnSidecar();
  restarted = await waitForHealth({ timeoutMs: 60000, expectDownFirst: false });
  return restarted;
}

function buildGrowingCoachPrompts(count) {
  const baseFacts = [
    "断点（breakpoint）是调试器在源码位置暂停执行的标记。",
    "命中信号：调试器停住、当前行高亮、变量面板可展开。",
    "最小下一步：在可疑赋值行设断点，然后单步观察变量变化。",
    "条件断点适合只在计数器>10 时停下，避免噪声。",
    "日志点（logpoint）可打印表达式而不永久停住。",
    "调用栈面板帮助确认是否进了错误的重载路径。",
    "监视表达式应只盯关键状态，而不是整对象树。",
    "会话连续性要求：同一 session_id 下历史消息应累积增长。",
  ];
  const prompts = [];
  for (let i = 0; i < count; i += 1) {
    const retained = baseFacts.slice(0, Math.min(i + 1, baseFacts.length));
    const baggage = retained
      .map((fact, idx) => `F${idx + 1}: ${fact}`)
      .join("\n");
    const growingTail = retained.join(" ").repeat(Math.max(1, Math.floor((i + 1) / 2)));
    prompts.push(
      [
        `【长上下文浸泡 第${i + 1}/${count}轮】请继续同一调试教练会话。`,
        "下列既有事实必须视为本会话已讨论内容（请勿否认先前轮次）：",
        baggage,
        `扩展上下文块（刻意拉长输入以增长上下文）：${growingTail}`,
        i === 0
          ? "任务：用一句话解释断点是什么，并引用 F1。"
          : i === count - 1
            ? "任务：用三句话总结本会话全部要点，并明确回答：我们是否仍在同一 session 的调试主题上？"
            : `任务：基于 F1..F${retained.length}，给出一个新的最小下一步，并点名上轮主题仍在继续。`,
      ].join("\n"),
    );
  }
  return prompts;
}

async function runCoachTurnSoak({ probe, turnCount, evidenceSubdir } = {}) {
  const started = Date.now();
  const targetTurns = Math.max(2, Number(turnCount ?? soakTurns) || soakTurns);
  if (!providerBaseUrl || !providerApiKey) {
    return { ok: false, category: "missing_config", probe };
  }
  const health = await getHealth();
  if (!health.ok) {
    return { ok: false, category: "sidecar_unhealthy", probe, status: health.status };
  }

  const workspaceId = `soak-${probe}-${Date.now()}`;
  const start = await startSession(workspaceId);
  if (!start.response.ok || !start.json?.session_id) {
    return {
      ok: false,
      category: "session_start_failed",
      probe,
      status: start.response.status,
    };
  }
  const sessionId = start.json.session_id;
  const prompts = buildGrowingCoachPrompts(targetTurns);
  const turns = [];
  let prevMessageCount = 0;

  for (let i = 0; i < prompts.length; i += 1) {
    const turn = await shortTurn(sessionId, workspaceId, prompts[i]);
    const grew =
      typeof turn.messageCount === "number" && turn.messageCount > prevMessageCount;
    const record = {
      index: i + 1,
      ok: turn.ok && turn.sameSession !== false,
      category:
        !turn.ok
          ? turn.category
          : turn.sameSession === false
            ? "session_id_drift"
            : "success",
      replyChars: turn.replyChars,
      elapsedMs: turn.elapsedMs,
      messageCount: turn.messageCount,
      responseSessionId: turn.responseSessionId || sessionId,
      sameSession: turn.sameSession !== false,
      contextGrew: grew || i === 0,
      promptChars: prompts[i].length,
    };
    turns.push(record);
    if (!record.ok) {
      const failed = {
        ok: false,
        probe,
        category: record.category,
        sessionId,
        turnCount: turns.length,
        turns,
        totalElapsedMs: Date.now() - started,
        elapsedMs: Date.now() - started,
        sessionIdPreserved: turns.every((t) => t.sameSession),
        providerModel,
        providerProtocol,
        baseUrlHost: hostOnly(providerBaseUrl),
        apiKey: "sk-***",
        evidenceSubdir: evidenceSubdir || null,
      };
      return failed;
    }
    prevMessageCount = Math.max(prevMessageCount, Number(turn.messageCount) || 0);
  }

  const sessionIdPreserved = turns.every((t) => t.sameSession);
  const contextGrewOverall =
    turns.length >= 2 &&
    Number(turns[turns.length - 1].messageCount || 0) > Number(turns[0].messageCount || 0);
  const ok = sessionIdPreserved && turns.every((t) => t.ok) && (contextGrewOverall || turns.length < 2);

  return {
    ok,
    probe,
    category: ok ? "success" : !sessionIdPreserved ? "session_id_drift" : "context_did_not_grow",
    sessionId,
    turnCount: turns.length,
    turns: turns.map((t) => ({
      index: t.index,
      ok: t.ok,
      category: t.category,
      replyChars: t.replyChars,
      elapsedMs: t.elapsedMs,
      messageCount: t.messageCount,
      sameSession: t.sameSession,
      contextGrew: t.contextGrew,
      promptChars: t.promptChars,
    })),
    totalElapsedMs: Date.now() - started,
    elapsedMs: Date.now() - started,
    sessionIdPreserved,
    contextGrewOverall,
    finalMessageCount: turns[turns.length - 1]?.messageCount ?? 0,
    providerModel,
    providerProtocol,
    baseUrlHost: hostOnly(providerBaseUrl),
    apiKey: "sk-***",
    evidenceSubdir: evidenceSubdir || null,
  };
}

async function runMultiTurnSoak() {
  return runCoachTurnSoak({
    probe: "multi_turn_soak",
    turnCount: Math.min(soakTurns, 5),
  });
}

async function runLongContextSoak() {
  const longTurns = Math.max(8, Number(process.env.TRAINER_LONG_CONTEXT_TURNS ?? soakTurns) || 8);
  return runCoachTurnSoak({
    probe: "long_context_soak",
    turnCount: longTurns,
    evidenceSubdir: "long-context-soak",
  });
}

async function listSidecarPids() {
  try {
    const { stdout } = await execFileAsync("bash", ["-lc", "pgrep -f 'run_sidecar.py' || true"]);
    return stdout
      .split(/\s+/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map(Number)
      .filter((n) => Number.isFinite(n) && n > 0);
  } catch {
    return [];
  }
}

async function runReconnectSoak() {
  const started = Date.now();
  if (!providerBaseUrl || !providerApiKey) {
    return { ok: false, category: "missing_config", probe: "reconnect_after_restart" };
  }
  const before = await getHealth();
  if (!before.ok) {
    return { ok: false, category: "sidecar_unhealthy", probe: "reconnect_after_restart" };
  }

  const workspaceId = `soak-reconnect-${Date.now()}`;
  const start = await startSession(workspaceId);
  if (!start.response.ok || !start.json?.session_id) {
    return {
      ok: false,
      category: "session_start_failed",
      probe: "reconnect_after_restart",
      status: start.response.status,
    };
  }
  const sessionId = start.json.session_id;
  const preMarker = "重启前：用一句话确认教练连接可用。";
  const pre = await shortTurn(sessionId, workspaceId, preMarker);
  if (!pre.ok) {
    return {
      ok: false,
      probe: "reconnect_after_restart",
      category: pre.category,
      phase: "pre_restart_turn",
      elapsedMs: Date.now() - started,
    };
  }

  // Dotfiles are ignored by uvicorn/watchfiles, so prefer an explicit clean restart
  // with absolute TRAINER_DATA_DIR (same SQLite across process death).
  const touchPath = path.join(repoRoot, "server", "soak_reload_touch.py");
  fs.writeFileSync(touchPath, `# soak reload touch ${Date.now()}\n`);
  let restarted = await waitForHealth({ timeoutMs: 15000, expectDownFirst: true });
  if (!restarted.ok) {
    restarted = await hardRestartSidecar();
    if (!restarted.ok) {
      return {
        ok: false,
        probe: "reconnect_after_restart",
        category: "sidecar_restart_failed",
        elapsedMs: Date.now() - started,
      };
    }
  }

  const postHealth = await getHealth();
  const workspaceId2 = `soak-reconnect-post-${Date.now()}`;
  const start2 = await startSession(workspaceId2);
  if (!start2.response.ok || !start2.json?.session_id) {
    return {
      ok: false,
      probe: "reconnect_after_restart",
      category: "session_start_failed_after_restart",
      status: start2.response.status,
      elapsedMs: Date.now() - started,
    };
  }
  const post = await shortTurn(
    start2.json.session_id,
    workspaceId2,
    "重启后：用一句话确认教练连接仍然可用。",
  );

  let oldSession = { attempted: true, ok: false, category: "not_attempted" };
  try {
    oldSession = {
      attempted: true,
      ...(await shortTurn(sessionId, workspaceId, "重启后续聊：还记得重启前的确认吗？一句话即可。")),
    };
  } catch (error) {
    oldSession = {
      attempted: true,
      ok: false,
      category: "old_session_error",
      detail: redact(String(error?.message || error)),
    };
  }

  const history = await fetchSessionHistory(sessionId, workspaceId);
  const historyItem = Array.isArray(history.json) ? history.json[0] || {} : history.json || {};
  const historyMessageCount = Number(historyItem.message_count || 0);
  const historyLatestUser = String(historyItem.latest_user_message || "");
  const sameSession = oldSession.sameSession !== false;
  const durableMessageCount = Number(oldSession.messageCount || 0) >= 4;
  // /session/history returns a summary row (latest messages), so require turn snapshot
  // messageCount>=4 plus same session_id — that proves pre+post restart turns survived.
  const continuityOk =
    Boolean(oldSession.ok) && sameSession && durableMessageCount && historyMessageCount >= 4;

  // Leave sidecar healthy for subsequent probes/agents.
  let finalHealth = await getHealth();
  if (!finalHealth.ok) {
    spawnSidecar();
    const recovered = await waitForHealth({ timeoutMs: 60000, expectDownFirst: false });
    finalHealth = recovered.ok ? recovered.health ?? (await getHealth()) : await getHealth();
  }

  const ok = post.ok === true && finalHealth.ok === true && continuityOk;
  return {
    ok,
    probe: "reconnect_after_restart",
    category: !post.ok
      ? post.category
      : !finalHealth.ok
        ? "sidecar_unhealthy_after_probe"
        : !continuityOk
          ? oldSession.category === "session_not_found"
            ? "old_session_not_found"
            : "old_session_not_continued"
          : "success",
    preRestart: { ok: pre.ok, category: pre.category, elapsedMs: pre.elapsedMs },
    postRestart: { ok: post.ok, category: post.category, elapsedMs: post.elapsedMs },
    oldSessionContinuity: {
      attempted: oldSession.attempted,
      ok: continuityOk,
      category: continuityOk ? "success" : oldSession.category,
      sameSession,
      responseSessionId: oldSession.responseSessionId || "",
      messageCount: oldSession.messageCount || 0,
      historyMessageCount,
      historyLatestUserChars: historyLatestUser.length,
      historyStatus: history.status,
      databasePath: postHealth.json?.database_path || before.json?.database_path || "",
      note: continuityOk
        ? "Old session_id continued after clean sidecar restart via durable SQLite restore."
        : "Old session_id did not continue after restart; refusing fake success.",
    },
    healthAfter: { ok: finalHealth.ok, status: finalHealth.status },
    elapsedMs: Date.now() - started,
    providerModel,
    baseUrlHost: hostOnly(providerBaseUrl),
    apiKey: "sk-***",
  };
}

function startRateLimitMock() {
  return new Promise((resolve) => {
    const server = http.createServer((request, response) => {
      if (request.url?.startsWith("/v1/models") && request.method === "GET") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ data: [{ id: providerModel }] }));
        return;
      }
      if (request.method === "POST") {
        response.writeHead(429, { "content-type": "application/json", "retry-after": "1" });
        response.end(
          JSON.stringify({
            error: { message: "Rate limit exceeded", type: "rate_limit_error", code: 429 },
          }),
        );
        return;
      }
      response.writeHead(404);
      response.end("not found");
    });
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      resolve({
        baseUrl: `http://127.0.0.1:${port}/v1`,
        close: () =>
          new Promise((res, rej) => {
            server.close((err) => (err ? rej(err) : res()));
          }),
      });
    });
  });
}

async function runRateLimitProbe() {
  const started = Date.now();
  const mock = await startRateLimitMock();
  try {
    const capability = await postJson(`${sidecarUrl}/provider/test`, {
      provider: {
        name: "trainer-soak-rate-limit",
        baseUrl: mock.baseUrl,
        apiKeyRef: "trainer.soak-rate-limit",
        model: providerModel,
        protocol: providerProtocol,
      },
      api_key: "sk-soak-mock-key-not-real",
      response_language: "en-US",
      probe_message: "ping",
    });
    const body = capability.json ?? {};
    const category =
      body.error_category ||
      body.errorCategory ||
      (capability.response.status === 429 ? "rate_limit" : undefined) ||
      body.category;
    const detail = redact(String(body.detail ?? body.message ?? capability.text ?? ""));

    const smoke = await new Promise((resolve) => {
      const child = spawn(process.execPath, [path.join(repoRoot, "scripts", "provider-smoke.mjs")], {
        env: {
          ...process.env,
          TRAINER_PROVIDER_SMOKE_BASE_URL: mock.baseUrl.replace(/\/v1$/, ""),
          TRAINER_PROVIDER_SMOKE_API_KEY: "sk-soak-mock-key-not-real",
          TRAINER_PROVIDER_SMOKE_MODEL: providerModel,
          TRAINER_PROVIDER_SMOKE_PROTOCOL: providerProtocol,
          TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: "en-US",
        },
        cwd: repoRoot,
      });
      let stdout = "";
      let stderr = "";
      child.stdout.on("data", (c) => {
        stdout += c;
      });
      child.stderr.on("data", (c) => {
        stderr += c;
      });
      child.on("close", (code) => resolve({ code, stdout: redact(stdout), stderr: redact(stderr) }));
    });
    let smokeCategory = "unknown";
    try {
      const report = JSON.parse(smoke.stderr || smoke.stdout || "{}");
      smokeCategory = report.category ?? "unknown";
    } catch {
      smokeCategory = "parse_failed";
    }

    // Provider-smoke is the authoritative HTTP classification path for mock 429.
    // /provider/test may short-circuit to model_not_tested depending on probe order;
    // record it but do not treat loose body regex as honesty.
    const smokeHonest = smokeCategory === "rate_limit" && smoke.code === 1;
    const providerTestHonest = category === "rate_limit";
    const ok = smokeHonest;
    return {
      ok,
      probe: "rate_limit_mock",
      category: ok ? "rate_limit" : "rate_limit_mismatch",
      honest_failure: smokeHonest,
      provider_test_rate_limit: providerTestHonest,
      providerTest: {
        httpStatus: capability.response.status,
        errorCategory: category ?? null,
        detailPreview: detail.slice(0, 240),
        okFlag: body.ok === true,
      },
      providerSmoke: {
        exitCode: smoke.code,
        category: smokeCategory,
      },
      elapsedMs: Date.now() - started,
      apiKey: "sk-***",
    };
  } finally {
    await mock.close();
  }
}

async function runAbortBeforeContent() {
  const started = Date.now();
  if (!providerBaseUrl || !providerApiKey) {
    return { ok: false, category: "missing_config", probe: "abort_before_content" };
  }
  const workspaceId = `soak-abort-${Date.now()}`;
  const start = await startSession(workspaceId);
  if (!start.response.ok || !start.json?.session_id) {
    return {
      ok: false,
      category: "session_start_failed",
      probe: "abort_before_content",
      status: start.response.status,
    };
  }

  const controller = new AbortController();
  let chunkCount = 0;
  let bytes = 0;
  let bodyPreview = "";
  let abortReason = "";
  let sawComplete = false;
  let httpStatus = 0;
  let sawStatusEvent = false;

  try {
    const response = await fetch(`${sidecarUrl}/turn/stream`, {
      method: "POST",
      headers: {
        accept: "text/event-stream",
        "content-type": "application/json",
      },
      signal: controller.signal,
      body: JSON.stringify({
        ...turnPayload(
          start.json.session_id,
          workspaceId,
          "请用中文慢慢解释 VS Code 断点，尽量多写几句，方便在首个内容块前取消。",
        ),
        use_agent_loop: true,
      }),
    });
    httpStatus = response.status;
    if (!response.body) throw new Error("missing_body");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value, { stream: true });
      bytes += text.length;
      bodyPreview = (bodyPreview + text).slice(0, 2000);
      if (/event:\s*status\s*\n/.test(text) || /"phase"\s*:/.test(text)) {
        sawStatusEvent = true;
      }
      chunkCount += [...text.matchAll(/data:\s*\{[^\n]*"chunk"\s*:/g)].length;
      if (/event:\s*complete\s*\n/.test(bodyPreview)) sawComplete = true;
      if (chunkCount >= 1) {
        abortReason = "client_abort_after_first_chunk";
        controller.abort();
        break;
      }
      if (sawStatusEvent || bytes > 20) {
        abortReason = "client_abort_before_content";
        controller.abort();
        break;
      }
    }
  } catch (error) {
    const message = String(error?.message || error);
    if (error?.name === "AbortError" || /aborted/i.test(message)) {
      abortReason = abortReason || "client_abort_signal";
    } else {
      return {
        ok: false,
        probe: "abort_before_content",
        category: "unexpected_stream_error",
        detail: redact(message),
        elapsedMs: Date.now() - started,
      };
    }
  }

  const beforeContent = chunkCount === 0 && sawComplete === false && Boolean(abortReason);
  const honest = beforeContent && abortReason.startsWith("client_abort") && !sawComplete;

  return {
    ok: honest,
    probe: "abort_before_content",
    category: "stream_aborted_by_client",
    honest_failure: honest,
    fake_success_avoided: sawComplete === false,
    abort_before_content: beforeContent,
    abortReason,
    httpStatus,
    chunkCount,
    bytes,
    sawComplete,
    sawStatusEvent,
    bodyPreviewRedacted: redact(bodyPreview).slice(0, 400),
    elapsedMs: Date.now() - started,
    providerModel,
    baseUrlHost: hostOnly(providerBaseUrl),
    apiKey: "sk-***",
  };
}

async function main() {
  const started = Date.now();
  const wanted =
    modeArg === "all"
      ? ["multi_turn_soak", "rate_limit_mock", "abort_before_content", "reconnect_after_restart"]
      : [modeArg];

  const runners = {
    multi_turn_soak: runMultiTurnSoak,
    multi: runMultiTurnSoak,
    "multi-turn": runMultiTurnSoak,
    long_context_soak: runLongContextSoak,
    "long-context": runLongContextSoak,
    "long-context-soak": runLongContextSoak,
    long_context: runLongContextSoak,
    rate_limit_mock: runRateLimitProbe,
    "rate-limit": runRateLimitProbe,
    rate_limit: runRateLimitProbe,
    abort_before_content: runAbortBeforeContent,
    abort: runAbortBeforeContent,
    reconnect_after_restart: runReconnectSoak,
    reconnect: runReconnectSoak,
  };

  const results = [];
  for (const name of wanted) {
    const runner = runners[name];
    if (!runner) {
      results.push({ ok: false, probe: name, category: "unknown_probe" });
      continue;
    }
    try {
      results.push(await runner());
    } catch (error) {
      results.push({
        ok: false,
        probe: name,
        category: "unexpected_error",
        detail: redact(String(error?.message || error)),
      });
    }
  }

  const ok = results.every((r) => r.ok);
  const summary = {
    ok,
    mode: modeArg,
    probes: results,
    elapsedMs: Date.now() - started,
    providerModel,
    providerProtocol,
    baseUrlHost: hostOnly(providerBaseUrl),
    apiKey: "sk-***",
  };
  const longContextMode =
    modeArg === "long-context" ||
    modeArg === "long-context-soak" ||
    modeArg === "long_context_soak" ||
    modeArg === "long_context";
  const evidenceDir = path.join(
    "/workspace/evidence/provider",
    longContextMode ? "long-context-soak" : "soak",
  );
  try {
    fs.mkdirSync(evidenceDir, { recursive: true });
    const evidenceName =
      modeArg === "reconnect" || modeArg === "reconnect_after_restart"
        ? "reconnect.json"
        : longContextMode
          ? "long-context-soak.json"
          : modeArg === "all"
            ? "SOAK-RUN.json"
            : `${modeArg.replace(/[^a-z0-9_-]+/gi, "-")}.json`;
    fs.writeFileSync(path.join(evidenceDir, evidenceName), `${JSON.stringify(summary, null, 2)}\n`);
    if (longContextMode) {
      const probe = results[0] || {};
      const lines = [
        `Long-context multi-turn soak — ${new Date().toISOString()}`,
        `protocol=${providerProtocol} model=${providerModel} host=${hostOnly(providerBaseUrl)}`,
        `ok=${summary.ok} category=${probe.category || "n/a"}`,
        `session_id=${probe.sessionId || "n/a"} preserved=${probe.sessionIdPreserved}`,
        `turnCount=${probe.turnCount || 0} totalElapsedMs=${probe.totalElapsedMs || summary.elapsedMs}`,
        `contextGrewOverall=${probe.contextGrewOverall} finalMessageCount=${probe.finalMessageCount}`,
        "per-turn:",
        ...(Array.isArray(probe.turns)
          ? probe.turns.map(
              (t) =>
                `  #${t.index} ok=${t.ok} cat=${t.category} ms=${t.elapsedMs} msgs=${t.messageCount} sameSession=${t.sameSession} promptChars=${t.promptChars} replyChars=${t.replyChars}`,
            )
          : ["  (none)"]),
        "apiKey=sk-***",
      ];
      fs.writeFileSync(path.join(evidenceDir, "LONG-CONTEXT-SUMMARY.txt"), `${lines.join("\n")}\n`);
    }
  } catch {
    /* evidence is best-effort */
  }
  console.log(JSON.stringify(summary, null, 2));
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  console.log(
    JSON.stringify(
      {
        ok: false,
        category: "unexpected_error",
        detail: redact(String(error?.message || error)),
      },
      null,
      2,
    ),
  );
  process.exitCode = 1;
});
