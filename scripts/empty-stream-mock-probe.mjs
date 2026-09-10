/**
 * True empty SSE mock fixture knife.
 * Proves category=empty_stream (not nonempty_sse_no_visible_content / max_tokens=1 length).
 * Never prints raw API keys.
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const OUT_DIR = (
  process.env.EMPTY_STREAM_MOCK_OUT_DIR ||
  "/workspace/evidence/provider/empty-stream-mock"
).replace(/\/+$/, "");
const sidecarUrl = (
  process.env.TRAINER_TURN_SMOKE_SIDECAR_URL ||
  process.env.TRAINER_PROVIDER_SMOKE_SIDECAR_URL ||
  "http://127.0.0.1:8765"
).replace(/\/+$/, "");
const MOCK_KEY = "sk-empty-stream-mock-fixture";
const MOCK_MODEL = "empty-stream-mock-model";
const PROTOCOL = "openai_chat_completions_compatible";

function redact(value) {
  return String(value ?? "")
    .replaceAll(MOCK_KEY, "sk-***")
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, "sk-***");
}

function writeJson(fileName, payload) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const target = path.join(OUT_DIR, fileName);
  fs.writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  return target;
}

function listen(server, host = "127.0.0.1", port = 0) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => resolve(server.address()));
  });
}

function closeServer(server) {
  return new Promise((resolve) => {
    server.close(() => resolve());
  });
}

/**
 * Mock OpenAI-compatible upstream.
 * streamMode:
 *   - empty_sse: HTTP 200 SSE, zero data: events (true empty)
 *   - done_only: only data: [DONE]
 *   - empty_delta_done: role + empty content + finish stop + DONE
 *   - length_empty: empty content + finish length + DONE (control: nonempty_sse_no_visible_content)
 *   - visible_ok: normal visible stream/text
 *   - pass_then_empty: non-stream + first N streams visible; later streams empty_sse
 */
function startEmptyStreamMockUpstream({
  streamMode = "empty_sse",
  passStreamBudget = 2,
  apiKey = MOCK_KEY,
  model = MOCK_MODEL,
} = {}) {
  const stats = {
    models: 0,
    chatNonStream: 0,
    chatStream: 0,
    streamModeHits: {},
  };
  let streamCalls = 0;

  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    const pathname = url.pathname.replace(/\/+$/, "") || "/";
    const auth = String(request.headers.authorization || "");
    if (!auth.includes(apiKey)) {
      response.writeHead(401, { "content-type": "application/json; charset=utf-8" });
      response.end(JSON.stringify({ error: { message: "unauthorized", type: "invalid_request_error" } }));
      return;
    }

    if (request.method === "GET" && pathname === "/v1/models") {
      stats.models += 1;
      response.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      response.end(JSON.stringify({ object: "list", data: [{ id: model, object: "model" }] }));
      return;
    }

    if (request.method !== "POST" || pathname !== "/v1/chat/completions") {
      response.writeHead(404, { "content-type": "application/json; charset=utf-8" });
      response.end(JSON.stringify({ error: { message: "not found" } }));
      return;
    }

    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    let payload = {};
    try {
      payload = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
    } catch {
      payload = {};
    }
    const wantsStream = payload.stream === true;

    if (!wantsStream) {
      stats.chatNonStream += 1;
      const emptyModes = new Set(["empty_sse", "done_only", "empty_delta_done", "length_empty"]);
      const content =
        streamMode === "pass_then_empty" || streamMode === "visible_ok" || !emptyModes.has(streamMode)
          ? "OK"
          : "";
      response.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      response.end(
        JSON.stringify({
          id: "chatcmpl-empty-mock",
          object: "chat.completion",
          model,
          choices: [
            {
              index: 0,
              message: { role: "assistant", content },
              finish_reason: content ? "stop" : "stop",
            },
          ],
        }),
      );
      return;
    }

    streamCalls += 1;
    stats.chatStream += 1;
    let effectiveMode = streamMode;
    if (streamMode === "pass_then_empty") {
      effectiveMode = streamCalls <= passStreamBudget ? "visible_ok" : "empty_sse";
    }
    stats.streamModeHits[effectiveMode] = (stats.streamModeHits[effectiveMode] || 0) + 1;

    response.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      connection: "keep-alive",
    });

    const id = `chatcmpl-empty-mock-stream-${streamCalls}`;
    if (effectiveMode === "empty_sse") {
      // True empty SSE: headers only, no data: frames.
      response.end();
      return;
    }
    if (effectiveMode === "done_only") {
      response.write("data: [DONE]\n\n");
      response.end();
      return;
    }
    if (effectiveMode === "empty_delta_done") {
      response.write(
        `data: ${JSON.stringify({
          id,
          object: "chat.completion.chunk",
          model,
          choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }],
        })}\n\n`,
      );
      response.write(
        `data: ${JSON.stringify({
          id,
          object: "chat.completion.chunk",
          model,
          choices: [{ index: 0, delta: { content: "" }, finish_reason: null }],
        })}\n\n`,
      );
      response.write(
        `data: ${JSON.stringify({
          id,
          object: "chat.completion.chunk",
          model,
          choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
        })}\n\n`,
      );
      response.write("data: [DONE]\n\n");
      response.end();
      return;
    }
    if (effectiveMode === "length_empty") {
      response.write(
        `data: ${JSON.stringify({
          id,
          object: "chat.completion.chunk",
          model,
          choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }],
        })}\n\n`,
      );
      response.write(
        `data: ${JSON.stringify({
          id,
          object: "chat.completion.chunk",
          model,
          choices: [{ index: 0, delta: {}, finish_reason: "length" }],
        })}\n\n`,
      );
      response.write("data: [DONE]\n\n");
      response.end();
      return;
    }
    // visible_ok
    response.write(
      `data: ${JSON.stringify({
        id,
        object: "chat.completion.chunk",
        model,
        choices: [{ index: 0, delta: { role: "assistant", content: "OK" }, finish_reason: null }],
      })}\n\n`,
    );
    response.write(
      `data: ${JSON.stringify({
        id,
        object: "chat.completion.chunk",
        model,
        choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
      })}\n\n`,
    );
    response.write("data: [DONE]\n\n");
    response.end();
  });

  return listen(server).then((address) => {
    const baseUrl = `http://127.0.0.1:${address.port}/v1`;
    return {
      baseUrl,
      apiKey,
      model,
      stats,
      async stop() {
        await closeServer(server);
      },
    };
  });
}

/** Same contract as live-timeout-empty direct probe: empty_stream iff HTTP 200 and zero data events. */
async function classifyUpstreamSse(baseUrl, apiKey, model, label) {
  const started = Date.now();
  const url = `${baseUrl.replace(/\/+$/, "")}/chat/completions`;
  let status = 0;
  let dataEvents = 0;
  let jsonEvents = 0;
  let doneEvents = 0;
  let contentChars = 0;
  let reasoningChars = 0;
  let malformed = 0;
  const finishReasons = [];
  let firstEventMs = null;
  let error = null;
  let rawPreview = "";

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        authorization: `Bearer ${apiKey}`,
        "content-type": "application/json",
        accept: "text/event-stream",
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "Reply OK." }],
        temperature: 0,
        max_tokens: 16,
        stream: true,
      }),
      signal: AbortSignal.timeout(15000),
    });
    status = response.status;
    const text = await response.text();
    rawPreview = text.slice(0, 400);
    for (const line of text.split(/\r?\n/)) {
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (!data) continue;
      if (firstEventMs == null) firstEventMs = Date.now() - started;
      dataEvents += 1;
      if (data === "[DONE]") {
        doneEvents += 1;
        continue;
      }
      try {
        const obj = JSON.parse(data);
        jsonEvents += 1;
        for (const choice of obj.choices || []) {
          const delta = choice.delta || {};
          if (typeof delta.content === "string") contentChars += delta.content.length;
          const rr = delta.reasoning_content || delta.reasoning;
          if (typeof rr === "string") reasoningChars += rr.length;
          if (choice.finish_reason != null && !finishReasons.includes(String(choice.finish_reason))) {
            finishReasons.push(String(choice.finish_reason));
          }
        }
      } catch {
        malformed += 1;
      }
    }
  } catch (exc) {
    error = `${exc?.name || "Error"}: ${redact(exc?.message || exc)}`;
  }

  const elapsedMs = Date.now() - started;
  let category;
  if (status === 200 && dataEvents === 0) category = "empty_stream";
  else if (error) category = "request_error";
  else if (status !== 200) category = "http_error";
  else if (contentChars === 0) category = "nonempty_sse_no_visible_content";
  else category = "nonempty_sse";

  return {
    label,
    live: false,
    mock: true,
    providerHost: "127.0.0.1",
    providerModel: model,
    protocol: PROTOCOL,
    apiKey: "sk-***",
    httpStatus: status,
    elapsedMs,
    firstEventMs,
    category,
    sseDataEvents: dataEvents,
    jsonEvents,
    doneEvents,
    contentChars,
    reasoningChars,
    finishReasons,
    malformedEvents: malformed,
    error,
    rawPreviewRedacted: redact(rawPreview),
  };
}

function classifyProviderTestFailure(response, body) {
  const httpStatus = response?.status;
  const payload = body && typeof body === "object" ? body : {};
  const nestedStatus = Number(payload.status_code);
  const status = Number.isFinite(nestedStatus) && nestedStatus > 0 ? nestedStatus : httpStatus;
  const rawCategory = String(payload.error_category || payload.status || "")
    .trim()
    .toLowerCase();

  if (
    status === 401 ||
    status === 403 ||
    rawCategory === "authentication_failed" ||
    rawCategory === "invalid_key_or_permission" ||
    rawCategory === "missing_api_key"
  ) {
    return { category: "authentication_failed", status: status || httpStatus || 401, rawCategory };
  }
  if (status === 429 || rawCategory === "rate_limit") {
    return { category: "rate_limit", status: status || httpStatus || 429, rawCategory };
  }
  if (status === 408 || status === 504 || rawCategory === "timeout") {
    return { category: "timeout", status: status || httpStatus || 408, rawCategory };
  }
  if (
    rawCategory === "empty_stream" ||
    rawCategory === "incomplete_stream" ||
    rawCategory === "empty_response"
  ) {
    return {
      category: rawCategory === "empty_response" ? "empty_stream" : rawCategory,
      status: status || httpStatus,
      rawCategory,
    };
  }
  return {
    category: "provider_capability_test_failed",
    status: status || httpStatus,
    rawCategory,
  };
}

async function driveProviderTest(mock) {
  const started = Date.now();
  const response = await fetch(`${sidecarUrl}/provider/test`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      provider: {
        name: "empty-stream-mock",
        baseUrl: mock.baseUrl,
        apiKeyRef: "trainer.empty-stream-mock",
        model: mock.model,
        protocol: PROTOCOL,
      },
      api_key: mock.apiKey,
      response_language: "zh-CN",
      probe_message: "请用一句话确认当前连接可以进行中文教练对话。",
    }),
    signal: AbortSignal.timeout(60000),
  });
  const text = await response.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = undefined;
  }
  const classified = classifyProviderTestFailure(response, json);
  return {
    step: "provider_test",
    ok: false,
    elapsedMs: Date.now() - started,
    httpStatus: response.status,
    category: classified.category,
    rawCategory: classified.rawCategory,
    nestedStatus: classified.status,
    sidecarOk: json?.ok === true,
    detailRedacted: redact(json?.detail || ""),
    diagnosticsRedacted: Array.isArray(json?.diagnostics)
      ? json.diagnostics.map((d) => redact(d)).slice(0, 12)
      : [],
    apiKey: "sk-***",
    providerBaseUrl: mock.baseUrl,
    providerModel: mock.model,
    protocol: PROTOCOL,
  };
}

async function driveCoachTurnEmptySidecar() {
  // Reuse existing classifier contract via trainer-turn-smoke + mock sidecar empty mode
  // (already unit-tested); run inline for evidence elapsedMs.
  const turnBodies = [];
  let sessionCounter = 0;
  const server = http.createServer((request, response) => {
    if (request.url === "/provider/test" && request.method === "POST") {
      response.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      response.end(
        JSON.stringify({
          ok: true,
          configured: true,
          api_key_supplied: true,
          reachable: true,
          success: true,
          status: "connected",
          detail: "mock provider test ok",
          diagnostics: ["mock"],
          capability_evidence: [],
          tools_ready: false,
          streaming_ready: false,
        }),
      );
      return;
    }
    if (request.url === "/session/start" && request.method === "POST") {
      sessionCounter += 1;
      response.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      response.end(JSON.stringify({ session_id: `empty-mock-session-${sessionCounter}` }));
      return;
    }
    if (request.url === "/turn/stream" && request.method === "POST") {
      // True empty coach SSE: HTTP 200, no chunk/complete events.
      response.writeHead(200, {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        connection: "keep-alive",
      });
      response.end();
      return;
    }
    // Drain unused routes with empty JSON so smoke fails at turn_stream honestly.
    let body = "";
    request.setEncoding("utf8");
    request.on("data", (c) => {
      body += c;
    });
    request.on("end", () => {
      turnBodies.push(body.slice(0, 80));
      response.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      response.end("{}");
    });
  });

  const address = await listen(server);
  const mockSidecarUrl = `http://127.0.0.1:${address.port}`;
  const started = Date.now();

  const child = spawn(
    process.execPath,
    [path.join(repoRoot, "scripts", "trainer-turn-smoke.mjs")],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        TRAINER_TURN_SMOKE_SIDECAR_URL: mockSidecarUrl,
        TRAINER_PROVIDER_SMOKE_BASE_URL: "http://127.0.0.1:9/v1",
        TRAINER_PROVIDER_SMOKE_API_KEY: "sk-mock-fixture-key",
        TRAINER_PROVIDER_SMOKE_MODEL: MOCK_MODEL,
        TRAINER_PROVIDER_SMOKE_PROTOCOL: PROTOCOL,
        TRAINER_TURN_SMOKE_TIMEOUT_MS: "30000",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (c) => {
    stdout += c;
  });
  child.stderr.on("data", (c) => {
    stderr += c;
  });

  const code = await new Promise((resolve) => child.on("close", resolve));
  await closeServer(server);
  const elapsedMs = Date.now() - started;
  let report = null;
  try {
    report = JSON.parse(stderr.trim() || "{}");
  } catch {
    try {
      const lines = stderr.trim().split("\n").filter(Boolean);
      report = JSON.parse(lines.at(-1) || "{}");
    } catch {
      report = null;
    }
  }
  return {
    step: "coach_turn_empty_sidecar_sse",
    exitCode: code,
    elapsedMs,
    category: report?.category || null,
    ok: report?.ok === false && report?.category === "empty_stream",
    report,
    stdoutRedacted: redact(stdout).slice(0, 500),
    stderrRedacted: redact(stderr).slice(0, 500),
  };
}

async function driveRealSidecarTurnPassThenEmpty(mock) {
  // provider/test must pass streaming; later coaching streams are empty_sse.
  const started = Date.now();
  const provider = {
    name: "empty-stream-mock-pass-then-empty",
    baseUrl: mock.baseUrl,
    apiKeyRef: "trainer.empty-stream-mock",
    model: mock.model,
    protocol: PROTOCOL,
  };
  const api_key = mock.apiKey;

  const testRes = await fetch(`${sidecarUrl}/provider/test`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      provider,
      api_key,
      response_language: "zh-CN",
      probe_message: "请用一句话确认当前连接可以进行中文教练对话。",
    }),
    signal: AbortSignal.timeout(90000),
  });
  const testText = await testRes.text();
  let testJson;
  try {
    testJson = JSON.parse(testText);
  } catch {
    testJson = undefined;
  }
  if (!testRes.ok || testJson?.ok !== true) {
    const classified = classifyProviderTestFailure(testRes, testJson);
    return {
      step: "turn_after_pass_then_empty",
      phase: "provider_test",
      ok: false,
      elapsedMs: Date.now() - started,
      category: classified.category,
      rawCategory: classified.rawCategory,
      detailRedacted: redact(testJson?.detail || ""),
      streaming_ready: testJson?.streaming_ready,
      apiKey: "sk-***",
    };
  }

  const workspaceId = `empty-stream-mock-ws-${Date.now()}`;
  const startRes = await fetch(`${sidecarUrl}/session/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      workspace_id: workspaceId,
      workspace_name: workspaceId,
      profile: {
        long_term_goal: "Empty stream mock fixture",
        weekly_hours: 1,
        teaching_style: "guided",
        answer_policy: "guided",
      },
    }),
    signal: AbortSignal.timeout(30000),
  });
  const startJson = await startRes.json();
  const sessionId = startJson?.session_id;
  if (!sessionId) {
    return {
      step: "turn_after_pass_then_empty",
      phase: "session_start",
      ok: false,
      elapsedMs: Date.now() - started,
      category: "session_start_failed",
      apiKey: "sk-***",
    };
  }

  const streamRes = await fetch(`${sidecarUrl}/turn/stream`, {
    method: "POST",
    headers: {
      accept: "text/event-stream",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
      workspace_id: workspaceId,
      intent: "coach",
      message: "请用中文给我一个最小的 VS Code 断点验证步骤。",
      response_language: "zh-CN",
      answer_mode: "guided",
      use_agent_loop: false,
      provider,
      api_key,
    }),
    signal: AbortSignal.timeout(120000),
  });
  const body = streamRes.body ? await new Response(streamRes.body).text() : "";
  const chunks = [...body.matchAll(/data:\s*\{[^\n]*"chunk"\s*:/g)].length;
  const hasComplete = /event:\s*complete\s*\n/.test(body);
  const hasError = /event:\s*error\s*\n/.test(body);
  const stopReasonMatch = body.match(/"stop_reason"\s*:\s*"([^"]+)"/);
  const recoveredMatch = body.match(/"recovered_stop_reason"\s*:\s*"([^"]+)"/);
  const errorCategoryMatch = body.match(/"error_category"\s*:\s*"([^"]+)"/);

  let category = "streaming_contract_failed";
  if (streamRes.status === 409) {
    category = /工具|tools/i.test(body)
      ? "tools_not_verified"
      : /流式|streaming/i.test(body)
        ? "streaming_not_verified"
        : "precondition_failed";
  } else if (streamRes.status === 200 && chunks === 0 && !hasComplete) {
    category = "empty_stream";
  } else if (streamRes.status === 200 && chunks > 0 && !hasComplete) {
    category = "incomplete_stream";
  } else if (
    stopReasonMatch?.[1] === "empty_response" ||
    recoveredMatch?.[1] === "empty_response" ||
    errorCategoryMatch?.[1] === "empty_response" ||
    errorCategoryMatch?.[1] === "empty_stream"
  ) {
    category = "empty_stream";
  } else if (hasComplete && chunks > 0) {
    // Coach may scaffold after empty upstream; still record honesty.
    category = "recovered_or_nonempty_stream";
  }

  return {
    step: "turn_after_pass_then_empty",
    phase: "turn_stream",
    ok: category === "empty_stream",
    elapsedMs: Date.now() - started,
    httpStatus: streamRes.status,
    category,
    chunkCount: chunks,
    hasComplete,
    hasError,
    stopReason: stopReasonMatch?.[1] || null,
    recoveredStopReason: recoveredMatch?.[1] || null,
    errorCategory: errorCategoryMatch?.[1] || null,
    bodyPreviewRedacted: redact(body).slice(0, 1200),
    mockStats: { ...mock.stats },
    session_id: sessionId,
    apiKey: "sk-***",
  };
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const results = [];

  // 1) Direct true empty SSE vs length_empty control
  const emptyMock = await startEmptyStreamMockUpstream({ streamMode: "empty_sse" });
  try {
    const emptyDirect = await classifyUpstreamSse(
      emptyMock.baseUrl,
      emptyMock.apiKey,
      emptyMock.model,
      "mock-true-empty-sse",
    );
    writeJson("01-direct-true-empty-sse.json", emptyDirect);
    results.push({ name: "direct_true_empty_sse", ...emptyDirect });

    const providerEmpty = await driveProviderTest(emptyMock);
    writeJson("02-provider-test-empty-mock.json", providerEmpty);
    results.push({ name: "provider_test_empty_mock", ...providerEmpty });
  } finally {
    await emptyMock.stop();
  }

  const lengthMock = await startEmptyStreamMockUpstream({ streamMode: "length_empty" });
  try {
    const lengthDirect = await classifyUpstreamSse(
      lengthMock.baseUrl,
      lengthMock.apiKey,
      lengthMock.model,
      "mock-length-empty-control",
    );
    writeJson("03-direct-length-empty-control.json", lengthDirect);
    results.push({ name: "direct_length_empty_control", ...lengthDirect });
  } finally {
    await lengthMock.stop();
  }

  // 2) Coach/turn smoke classifier via empty sidecar SSE (contract used by UI matrix)
  const coachEmpty = await driveCoachTurnEmptySidecar();
  writeJson("04-coach-turn-empty-sidecar.json", coachEmpty);
  results.push({ name: "coach_turn_empty_sidecar", ...coachEmpty });

  // 3) Real sidecar turn after pass-then-empty upstream (honest outcome)
  const passThenEmpty = await startEmptyStreamMockUpstream({
    streamMode: "pass_then_empty",
    // Only the streaming capability probe may see visible tokens; coach turn must hit empty_sse.
    passStreamBudget: 1,
  });
  try {
    const turnResult = await driveRealSidecarTurnPassThenEmpty(passThenEmpty);
    writeJson("05-sidecar-turn-pass-then-empty.json", turnResult);
    results.push({ name: "sidecar_turn_pass_then_empty", ...turnResult });
  } finally {
    await passThenEmpty.stop();
  }

  const emptyStreamHits = results.filter((r) => r.category === "empty_stream");
  const summary = {
    title: "true empty SSE mock fixture — close empty_stream yellow flag",
    timeUtc: new Date().toISOString(),
    sidecarUrl,
    protocol: PROTOCOL,
    apiKey: "sk-***",
    results: results.map((r) => ({
      name: r.name,
      category: r.category,
      elapsedMs: r.elapsedMs,
      ok: r.ok,
      sseDataEvents: r.sseDataEvents,
      rawCategory: r.rawCategory,
      stopReason: r.stopReason,
      recoveredStopReason: r.recoveredStopReason,
    })),
    empty_stream_count: emptyStreamHits.length,
    closed:
      results.some((r) => r.name === "direct_true_empty_sse" && r.category === "empty_stream") &&
      results.some((r) => r.name === "direct_length_empty_control" && r.category === "nonempty_sse_no_visible_content") &&
      results.some((r) => r.name === "provider_test_empty_mock" && r.category === "empty_stream") &&
      results.some((r) => r.name === "coach_turn_empty_sidecar" && r.category === "empty_stream"),
    note_for_ahui:
      "UI already has empty_stream draft-retain copy in buildTrainerStreamingErrorMessage / MATRIX_TO_UI; confirm Coach surfaces category=empty_stream (same copy as empty_response).",
  };
  writeJson("SUMMARY.json", summary);
  writeJson(
    "SUMMARY.txt",
    // writeJson stringifies; also write plain text separately below
    summary,
  );
  const txt = [
    "true empty SSE mock — empty_stream yellow flag",
    `time: ${summary.timeUtc}`,
    `sidecar: ${sidecarUrl}`,
    `closed: ${summary.closed}`,
    `empty_stream_count: ${summary.empty_stream_count}`,
    "",
    "| path | category | elapsedMs |",
    "|------|----------|-----------|",
    ...summary.results.map(
      (r) => `| ${r.name} | ${r.category} | ${r.elapsedMs ?? ""} |`,
    ),
    "",
    "Control: length_empty must be nonempty_sse_no_visible_content (not empty_stream).",
    "阿辉: UI empty_stream draft-retain copy already present — confirm category wires through Coach.",
    "Keys: sk-*** only.",
  ].join("\n");
  fs.writeFileSync(path.join(OUT_DIR, "SUMMARY.txt"), `${txt}\n`, "utf8");

  // Copy probe script into evidence for audit.
  fs.copyFileSync(
    path.join(repoRoot, "scripts", "empty-stream-mock-probe.mjs"),
    path.join(OUT_DIR, "empty-stream-mock-probe.mjs"),
  );

  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
  process.exitCode = summary.closed ? 0 : 1;
}

main().catch((error) => {
  process.stderr.write(`${redact(error?.stack || error)}\n`);
  process.exitCode = 1;
});
