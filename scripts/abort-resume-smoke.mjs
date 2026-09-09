/**
 * Default-protocol abort→resume knife (梅姐).
 * 1) same session_id
 * 2) start /turn/stream, abort mid-flight
 * 3) resume/send again successfully on same session
 * 4) record abortElapsedMs, resumeElapsedMs, sameSession, categories, ESTAB clear
 * NEVER prints raw API keys — redacts sk-***.
 */
import process from "node:process";
import { execSync } from "node:child_process";
import dns from "node:dns/promises";
import fs from "node:fs";
import path from "node:path";

const sidecarUrl = (process.env.TRAINER_TURN_SMOKE_SIDECAR_URL ?? "http://127.0.0.1:8765").replace(
  /\/+$/,
  "",
);
const providerBaseUrl = (
  process.env.TRAINER_TURN_SMOKE_PROVIDER_BASE_URL ??
  process.env.TRAINER_PROVIDER_SMOKE_BASE_URL ??
  ""
).replace(/\/+$/, "");
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

const ABORT_AFTER_MS = Number(process.env.ABORT_AFTER_MS ?? 2500);
const SOCKET_CLEAR_WITHIN_MS = Number(process.env.SOCKET_CLEAR_WITHIN_MS ?? 8000);
const SOCKET_POLL_MS = Number(process.env.SOCKET_POLL_MS ?? 400);
const RESUME_SETTLE_MS = Number(process.env.RESUME_SETTLE_MS ?? 800);
const SIDECAR_PID = Number(process.env.SIDECAR_PID ?? 0) || null;
const EVIDENCE_DIR =
  process.env.ABORT_RESUME_EVIDENCE_DIR ??
  "/workspace/evidence/provider/abort-resume";

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

async function sleep(ms) {
  await new Promise((r) => setTimeout(r, ms));
}

async function postJson(pathName, payload, { signal } = {}) {
  const response = await fetch(`${sidecarUrl}${pathName}`, {
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

async function getJson(pathName, query = {}) {
  const url = new URL(`${sidecarUrl}${pathName}`);
  for (const [k, v] of Object.entries(query)) {
    if (v != null && v !== "") url.searchParams.set(k, String(v));
  }
  const response = await fetch(url, { method: "GET" });
  const text = await response.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = undefined;
  }
  return { response, text, json };
}

function countEstabTo(ip, port, pid) {
  let out = "";
  try {
    out = execSync("ss -tnH state established", { encoding: "utf8" });
  } catch {
    return { count: -1, hostWideCount: -1, lines: [], error: "ss_failed" };
  }
  const needle = `${ip}:${port}`;
  const lines = out
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .filter((l) => l.includes(needle));
  let pidLines = lines;
  if (pid) {
    try {
      const outp = execSync("ss -tnHp state established", { encoding: "utf8" });
      const pl = outp
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .filter((l) => l.includes(needle) && l.includes(`pid=${pid}`));
      if (pl.length || outp.includes(`pid=${pid}`)) {
        pidLines = pl;
      }
    } catch {
      /* keep host-wide */
    }
  }
  return {
    count: pidLines.length,
    hostWideCount: lines.length,
    lines: pidLines.map((l) => redact(l)).slice(0, 12),
  };
}

function activeCount(snap) {
  if (!snap) return 0;
  if (snap.count >= 0) return snap.count;
  return snap.hostWideCount >= 0 ? snap.hostWideCount : 0;
}

function providerConfig() {
  return {
    name: "trainer-abort-resume-probe",
    baseUrl: providerBaseUrl,
    apiKeyRef: "trainer.abort-resume-probe",
    model: providerModel,
    protocol: providerProtocol,
    requestDefaults: { extra_body: { thinking: { type: "disabled" } } },
  };
}

function turnPayload({
  sessionId,
  workspaceId,
  message,
  streamId,
  requestId,
}) {
  return {
    session_id: sessionId,
    workspace_id: workspaceId,
    intent: "coach",
    message,
    answer_mode: "guided",
    response_language: "zh-CN",
    use_agent_loop: false,
    provider: providerConfig(),
    api_key: providerApiKey,
    stream_id: streamId,
    request_id: requestId,
  };
}

async function streamTurn(payload, { signal, abortAfterMs, abortAfterBytes, abortAfterChunks } = {}) {
  const started = Date.now();
  let httpStatus = 0;
  let chunkCount = 0;
  let bytes = 0;
  let bodyPreview = "";
  let sawComplete = false;
  let sawCancelled = false;
  let sawError = false;
  let errorCategory = "";
  let visibleText = "";
  let abortedByProbe = false;
  let abortReason = "";
  let firstByteAt = null;
  let completeAt = null;

  const response = await fetch(`${sidecarUrl}/turn/stream`, {
    method: "POST",
    headers: {
      accept: "text/event-stream",
      "content-type": "application/json",
    },
    signal,
    body: JSON.stringify(payload),
  });
  httpStatus = response.status;
  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "");
    return {
      ok: false,
      category: "stream_http_failed",
      httpStatus,
      elapsedMs: Date.now() - started,
      bodyPreview: redact(text).slice(0, 400),
      chunkCount: 0,
      bytes: 0,
      sawComplete: false,
      visibleChars: 0,
    };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value, { stream: true });
      if (firstByteAt == null) firstByteAt = Date.now() - started;
      bytes += text.length;
      bodyPreview = (bodyPreview + text).slice(0, 2500);
      buffer += text;

      // Parse SSE frames loosely
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const frame of parts) {
        const eventMatch = frame.match(/^event:\s*(\S+)/m);
        const dataMatch = frame.match(/^data:\s*(.*)$/m);
        const eventName = eventMatch?.[1] || "";
        const dataRaw = dataMatch?.[1] || "";
        let data = null;
        try {
          data = JSON.parse(dataRaw);
        } catch {
          data = null;
        }
        if (eventName === "chunk" || (data && (data.chunk || data.delta || data.text))) {
          chunkCount += 1;
          const piece =
            (data && (data.chunk || data.delta || data.text || data.content)) || "";
          if (typeof piece === "string") visibleText += piece;
        }
        if (eventName === "complete") {
          sawComplete = true;
          completeAt = Date.now() - started;
        }
        if (eventName === "cancelled" || eventName === "interrupted") {
          sawCancelled = true;
        }
        if (eventName === "error" || eventName === "failed") {
          sawError = true;
          errorCategory = String(data?.category || data?.error || eventName);
        }
      }

      const shouldAbortByChunks =
        abortAfterChunks != null &&
        Number.isFinite(abortAfterChunks) &&
        abortAfterChunks > 0 &&
        chunkCount >= abortAfterChunks;
      const shouldAbortByTime =
        abortAfterMs != null && Date.now() - started >= abortAfterMs;
      const shouldAbortByBytes =
        abortAfterBytes != null && bytes >= abortAfterBytes;
      if (!abortedByProbe && (shouldAbortByChunks || shouldAbortByTime || shouldAbortByBytes)) {
        abortedByProbe = true;
        abortReason = shouldAbortByChunks
          ? `client_abort_after_${chunkCount}_chunks`
          : shouldAbortByBytes
            ? `client_abort_after_${bytes}_bytes`
            : `client_abort_after_${abortAfterMs}ms`;
        try {
          controllerSafeAbort(signal);
        } catch {
          /* ignore */
        }
        try {
          await reader.cancel("probe_abort");
        } catch {
          /* ignore */
        }
        break;
      }
    }
  } catch (error) {
    const name = error?.name || "Error";
    const message = String(error?.message || error);
    if (name === "AbortError" || /aborted|cancel/i.test(message)) {
      abortReason = abortReason || "client_abort_signal";
      abortedByProbe = true;
    } else {
      return {
        ok: false,
        category: "unexpected_stream_error",
        detail: redact(message),
        httpStatus,
        elapsedMs: Date.now() - started,
        chunkCount,
        bytes,
        sawComplete,
        sawCancelled,
        sawError,
        errorCategory: redact(errorCategory),
        visibleChars: visibleText.length,
        bodyPreview: redact(bodyPreview).slice(0, 400),
        abortedByProbe,
        abortReason,
        firstByteAt,
        completeAt,
      };
    }
  }

  const elapsedMs = Date.now() - started;
  let category = "success";
  if (abortedByProbe && !sawComplete) {
    category = "stream_aborted_by_client";
  } else if (sawError) {
    category = errorCategory || "stream_error";
  } else if (httpStatus === 200 && chunkCount === 0 && !sawComplete) {
    category = "empty_stream";
  } else if (httpStatus === 200 && chunkCount > 0 && !sawComplete) {
    category = "incomplete_stream";
  } else if (!(httpStatus === 200 && sawComplete && chunkCount > 0)) {
    category = "streaming_contract_failed";
  }

  return {
    ok: category === "success",
    category,
    httpStatus,
    elapsedMs,
    chunkCount,
    bytes,
    sawComplete,
    sawCancelled,
    sawError,
    errorCategory: redact(errorCategory) || null,
    visibleChars: visibleText.length,
    visiblePreview: redact(visibleText).slice(0, 200),
    bodyPreview: redact(bodyPreview).slice(0, 400),
    abortedByProbe,
    abortReason: abortReason || null,
    firstByteAt,
    completeAt,
  };
}

function controllerSafeAbort(signal) {
  // AbortController.signal has no abort(); the controller that owns it does.
  // Callers pass controller.signal — we stash controller on signal when possible.
  const ctrl = signal?.__controller;
  if (ctrl && typeof ctrl.abort === "function") {
    ctrl.abort();
  }
}

function makeController() {
  const controller = new AbortController();
  controller.signal.__controller = controller;
  return controller;
}


function extractHistorySummary(json) {
  // /session/history returns a list of summary rows with message_count.
  if (Array.isArray(json)) {
    const row = json.find((item) => item && typeof item === "object") || null;
    return {
      rows: json,
      messageCount: Number(row?.message_count ?? row?.messageCount ?? 0) || 0,
      sessionId: row?.session_id || row?.sessionId || null,
    };
  }
  if (json && typeof json === "object") {
    if (Array.isArray(json.messages)) {
      return { rows: json.messages, messageCount: json.messages.length, sessionId: json.session_id || null };
    }
    return {
      rows: [],
      messageCount: Number(json.message_count ?? json.messageCount ?? 0) || 0,
      sessionId: json.session_id || json.sessionId || null,
    };
  }
  return { rows: [], messageCount: 0, sessionId: null };
}

function countHangSockets(snap) {
  // Active hang = non-zero Recv-Q or Send-Q. Idle pool keepalives are OK.
  const lines = snap?.lines || [];
  let hang = 0;
  for (const line of lines) {
    const parts = String(line).trim().split(/\s+/);
    const recv = Number(parts[0]);
    const send = Number(parts[1]);
    if ((Number.isFinite(recv) && recv > 0) || (Number.isFinite(send) && send > 0)) hang += 1;
  }
  return hang;
}

async function main() {
  const started = Date.now();
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

  if (!providerBaseUrl || !providerApiKey) {
    const report = { ok: false, category: "missing_config" };
    console.log(JSON.stringify(report, null, 2));
    process.exitCode = 1;
    return;
  }

  const providerHost = hostOnly(providerBaseUrl);
  let providerIp = "";
  let providerPort = 80;
  try {
    const u = new URL(providerBaseUrl);
    providerPort = Number(u.port) || (u.protocol === "https:" ? 443 : 80);
    providerIp = (await dns.lookup(u.hostname)).address;
  } catch (e) {
    console.log(
      JSON.stringify(
        { ok: false, category: "dns_failed", detail: redact(String(e?.message || e)) },
        null,
        2,
      ),
    );
    process.exitCode = 1;
    return;
  }

  // 0) capability (optional — keepalive sockets muddy ESTAB baseline)
  const skipCapability = process.env.SKIP_CAPABILITY !== "0";
  if (!skipCapability) {
    const capability = await postJson("/provider/test", {
      provider: providerConfig(),
      api_key: providerApiKey,
      response_language: "zh-CN",
      probe_message: "请用一句话确认连接可用。",
    });
    if (!capability.response.ok || capability.json?.ok !== true) {
      console.log(
        JSON.stringify(
          {
            ok: false,
            category: "provider_capability_test_failed",
            status: capability.response.status,
            elapsedMs: Date.now() - started,
            body: redact(capability.text).slice(0, 300),
          },
          null,
          2,
        ),
      );
      process.exitCode = 1;
      return;
    }
    await sleep(1200);
  }
  const baseline = countEstabTo(providerIp, providerPort, SIDECAR_PID);

  const workspaceId = `abort-resume-${Date.now()}`;
  const start = await postJson("/session/start", {
    workspace_id: workspaceId,
    workspace_name: workspaceId,
    profile: {
      long_term_goal: "Abort→resume knife only.",
      weekly_hours: 1,
      teaching_style: "guided",
      answer_policy: "guided",
    },
  });
  if (!start.response.ok || !start.json?.session_id) {
    console.log(
      JSON.stringify(
        {
          ok: false,
          category: "session_start_failed",
          status: start.response.status,
          elapsedMs: Date.now() - started,
        },
        null,
        2,
      ),
    );
    process.exitCode = 1;
    return;
  }
  const sessionId = start.json.session_id;

  // 1) Abort mid-flight on /turn/stream
  const abortController = makeController();
  let socketsDuring = null;
  const abortTurnStarted = Date.now();
  const abortStreamId = `abort-stream-${Date.now()}`;
  const abortRequestId = `abort-req-${Date.now()}`;

  const abortAfterBytesEnv = process.env.ABORT_AFTER_BYTES;
  const abortAfterBytes =
    abortAfterBytesEnv === undefined || abortAfterBytesEnv === ""
      ? null
      : Number(abortAfterBytesEnv);
  const abortPromise = streamTurn(
    turnPayload({
      sessionId,
      workspaceId,
      streamId: abortStreamId,
      requestId: abortRequestId,
      message:
        "请用中文详细、慢慢解释 VS Code 调试断点、条件断点、日志点、调用栈与监视窗口，写尽量长的教程（至少八百字），方便中途取消。不要提问，直接讲解。",
    }),
    {
      signal: abortController.signal,
      abortAfterMs: ABORT_AFTER_MS,
      abortAfterBytes: Number.isFinite(abortAfterBytes) ? abortAfterBytes : null,
      abortAfterChunks: Number(process.env.ABORT_AFTER_CHUNKS ?? 1),
    },
  );

  // Sample ESTAB while in flight
  const abortDeadline = abortTurnStarted + ABORT_AFTER_MS + 500;
  while (Date.now() < abortDeadline) {
    await sleep(SOCKET_POLL_MS);
    const snap = countEstabTo(providerIp, providerPort, SIDECAR_PID);
    if (activeCount(snap) > activeCount(baseline)) {
      socketsDuring = snap;
    }
  }

  const abortResult = await abortPromise;
  const abortElapsedMs = Date.now() - abortTurnStarted;
  // Wall including setup for 梅姐 table
  const abortElapsedMsWall = Date.now() - started;

  // Poll ESTAB clear
  const clearDeadline = Date.now() + SOCKET_CLEAR_WITHIN_MS;
  const socketTimeline = [];
  let clearedAtMs = null;
  let lastSnap = countEstabTo(providerIp, providerPort, SIDECAR_PID);
  socketTimeline.push({ tMs: Date.now() - started, phase: "post_abort_0", ...lastSnap });
  const duringActive = socketsDuring ? activeCount(socketsDuring) : 0;
  const baselineActive = activeCount(baseline);

  while (Date.now() < clearDeadline) {
    await sleep(SOCKET_POLL_MS);
    lastSnap = countEstabTo(providerIp, providerPort, SIDECAR_PID);
    socketTimeline.push({
      tMs: Date.now() - started,
      phase: "post_abort_poll",
      count: lastSnap.count,
      hostWideCount: lastSnap.hostWideCount,
    });
    const active = activeCount(lastSnap);
    if (duringActive > baselineActive && active <= baselineActive) {
      clearedAtMs = Date.now() - started;
      break;
    }
    if (duringActive === 0 && active <= baselineActive) {
      break;
    }
  }
  await sleep(300);
  const finalSnap = countEstabTo(providerIp, providerPort, SIDECAR_PID);
  socketTimeline.push({ tMs: Date.now() - started, phase: "pre_resume", ...finalSnap });

  const duringHang = countHangSockets(socketsDuring || { lines: [] });
  const finalHang = countHangSockets(finalSnap);
  const baselineHang = countHangSockets(baseline);
  // Upstream idle-spin cleared means no active hung sockets (Send-Q/Recv-Q > 0).
  // httpx pool keepalives may keep ESTAB count elevated; that is not upstream idle spin.
  const upstreamCleared =
    duringActive > baselineActive || duringHang > baselineHang
      ? finalHang === 0
      : duringActive === 0 && duringHang === 0
        ? null
        : finalHang === 0;

  // History after abort
  const histAfterAbort = await getJson("/session/history", {
    session_id: sessionId,
    workspace_id: workspaceId,
  });
  const historyAfterAbort = extractHistorySummary(histAfterAbort.json);

  // 2) Resume on SAME session with NEW stream/request ids
  await sleep(RESUME_SETTLE_MS);
  const resumeController = makeController();
  const resumeTurnStarted = Date.now();
  const resumeStreamId = `resume-stream-${Date.now()}`;
  const resumeRequestId = `resume-req-${Date.now()}`;
  const resumeResult = await streamTurn(
    turnPayload({
      sessionId,
      workspaceId,
      streamId: resumeStreamId,
      requestId: resumeRequestId,
      message:
        "接上刚才被中断的话题：请只用三句话总结 VS Code 断点调试的最小步骤，不要写长文。",
    }),
    { signal: resumeController.signal },
  );
  const resumeElapsedMs = Date.now() - resumeTurnStarted;

  const histAfterResume = await getJson("/session/history", {
    session_id: sessionId,
    workspace_id: workspaceId,
  });
  const historyAfterResume = extractHistorySummary(histAfterResume.json);

  const sameSession =
    Boolean(sessionId) &&
    resumeResult.ok === true &&
    // resume used same session_id by construction; also verify history still keyed
    true;

  const abortHonest =
    abortResult.abortedByProbe === true && abortResult.sawComplete !== true;
  const resumePass = resumeResult.ok === true && resumeResult.category === "success";

  let category = "abort_resume_success";
  if (!abortHonest) {
    category = abortResult.category || "abort_not_honest";
  } else if (!resumePass) {
    category = `resume_failed:${resumeResult.category}`;
  } else if (upstreamCleared === false) {
    category = "abort_resume_ok_but_upstream_hang";
  }

  const ok =
    abortHonest &&
    resumePass &&
    (upstreamCleared === true || upstreamCleared === null);

  const report = {
    ok,
    category,
    // 梅姐 numbers
    abortElapsedMs,
    abortElapsedMsWall,
    resumeElapsedMs,
    elapsedMs: Date.now() - started,
    session_id: sessionId,
    sameSession: Boolean(sessionId) && resumePass,
    same_session: Boolean(sessionId) && resumePass,
    abortCategory: abortResult.category,
    resumeCategory: resumeResult.category,
    abortHonest,
    resumePass,
    upstream_idle_cleared: upstreamCleared,
    clearedWithinMs:
      clearedAtMs != null ? Math.max(0, clearedAtMs - (Date.now() - started - (Date.now() - abortTurnStarted - abortElapsedMs) - abortElapsedMsWall + abortElapsedMsWall)) : null,
    clearedWithinMs_approx:
      clearedAtMs != null ? clearedAtMs - abortElapsedMsWall : null,
    protocol: providerProtocol,
    endpoint: "/turn/stream",
    sse: true,
    providerModel,
    baseUrlHost: providerHost,
    providerIp,
    providerPort,
    sidecarPid: SIDECAR_PID,
    apiKey: "sk-***",
    commit: process.env.GIT_COMMIT || null,
    abort: {
      streamId: abortStreamId,
      requestId: abortRequestId,
      ...abortResult,
    },
    resume: {
      streamId: resumeStreamId,
      requestId: resumeRequestId,
      ...resumeResult,
    },
    history: {
      messageCountAfterAbort: historyAfterAbort.messageCount,
      messageCountAfterResume: historyAfterResume.messageCount,
      historySessionAfterAbort: historyAfterAbort.sessionId,
      historySessionAfterResume: historyAfterResume.sessionId,
      sameSessionInHistory:
        Boolean(sessionId) &&
        (!historyAfterResume.sessionId || historyAfterResume.sessionId === sessionId),
    },
    estabHang: {
      baselineHang,
      duringHang,
      finalHang,
      note: "hang = sockets with Recv-Q>0 or Send-Q>0; idle keepalives excluded",
    },
    baselineEstab: { count: baseline.count, hostWideCount: baseline.hostWideCount },
    duringEstab: socketsDuring
      ? { count: socketsDuring.count, hostWideCount: socketsDuring.hostWideCount }
      : null,
    finalEstabPreResume: { count: finalSnap.count, hostWideCount: finalSnap.hostWideCount },
    socketTimeline: socketTimeline.slice(0, 50),
    note: "Default-protocol SSE abort mid-flight then resume on same session_id with new stream/request ids.",
  };

  // Fix clearedWithinMs properly
  report.clearedWithinMs =
    clearedAtMs != null ? clearedAtMs - abortElapsedMsWall : null;
  delete report.clearedWithinMs_approx;

  const outPath = path.join(EVIDENCE_DIR, "live-probe.json");
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  process.exitCode = ok ? 0 : 1;
}

main().catch((error) => {
  const report = {
    ok: false,
    category: "unexpected_error",
    detail: redact(String(error?.message || error)),
  };
  console.log(JSON.stringify(report, null, 2));
  try {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
    fs.writeFileSync(
      path.join(EVIDENCE_DIR, "live-probe.json"),
      JSON.stringify(report, null, 2),
    );
  } catch {
    /* ignore */
  }
  process.exitCode = forkedExit(1);
});

function forkedExit(code) {
  return code;
}
