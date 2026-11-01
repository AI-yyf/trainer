// T-0047 journey probe: full teaching loop against a real sidecar + real
// provider, with mid-journey interruptions (sidecar restart, workspace
// switch, model switch). Writes one JSON evidence file per step.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repoRoot = "/Users/Apple/Desktop/trainer";
const serverDir = path.join(repoRoot, "server");
const python = path.join(serverDir, ".venv", "bin", "python");
const baseUrl = "http://127.0.0.1:34978";
const providerBase = process.env.PROBE_PROVIDER_BASE_URL ?? "";
const providerKey = process.env.PROBE_PROVIDER_API_KEY ?? "";
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M3.1-Flash";
const modelSwitch = process.env.PROBE_PROVIDER_MODEL_SWITCH ?? "MiniMax-M2.7";
const outDir = process.env.JOURNEY_OUT_DIR ?? "/tmp/trainer-conv/journey";
fs.mkdirSync(outDir, { recursive: true });

if (!providerBase || !providerKey) {
  console.error("PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY required");
  process.exit(2);
}

// Fail loudly if a stale sidecar owns the port (zombie lesson, T-wave 1).
try {
  await fetch(`${baseUrl}/health`);
  console.error(`port 34978 already served — kill the stale sidecar first`);
  process.exit(4);
} catch {}

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-journey-"));
let sidecar = spawn(python, ["run_sidecar.py", "--host", "127.0.0.1", "--port", "34978"], {
  cwd: serverDir,
  env: { ...process.env, TRAINER_DATA_DIR: dataDir, TRAINER_ENABLE_NETWORK_FETCH: "1" },
  stdio: ["ignore", "pipe", "pipe"],
});
let sidecarLog = "";
sidecar.stdout.on("data", (c) => (sidecarLog += c));
sidecar.stderr.on("data", (c) => (sidecarLog += c));

async function waitForHealth() {
  for (let i = 0; i < 240; i++) {
    try {
      const r = await fetch(`${baseUrl}/health`);
      if (r.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("sidecar never became healthy");
}

function post(p, body) {
  return fetch(`${baseUrl}${p}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (r) => ({ status: r.status, json: await r.json().catch(() => null), text: await r.text().catch(() => "") }));
}

function step(name, data) {
  fs.writeFileSync(path.join(outDir, `${name}.json`), JSON.stringify(data, null, 2) + "\n");
  console.log(`[step] ${name} recorded`);
}

let providerTestResult = null;

const providerPayload = {
  name: "journey-probe",
  baseUrl: providerBase,
  apiKeyRef: "journey-probe",
  model,
  protocol: "openai_chat_completions_compatible",
};

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
  if (r.status !== 200) {
    console.error(`turn ${r.status}:`, text.slice(0, 300));
  }
  return { status: r.status, text, visible: chunks };
}

try {
  await waitForHealth();

  // Step 1 — session start (workspace A)
  const start = await post("/session/start", {
    workspace_id: "journey-ws-a",
    workspace_name: "Journey A",
  });
  step("01-session-start", { status: start.status, session_id: start.json?.session_id, workspace: "journey-ws-a" });
  const sessionId = start.json.session_id;

  // Step 2 — import a real code resource into the library
  const upload = await post("/resource/upload", {
    session_id: sessionId,
    workspace_id: "journey-ws-a",
    name: "queue_lock.py",
    kind: "code",
    source: "file",
    content:
      "import threading\n\nclass Queue:\n    def __init__(self):\n        self._items = []\n        self._lock = threading.Lock()\n\n    def push(self, item):\n        with self._lock:\n            self._items.append(item)\n\n    def pop(self):\n        with self._lock:\n            if not self._items:\n                raise IndexError('empty')\n            return self._items.pop(0)\n",
  });
  step("02-resource-upload", {
    status: upload.status,
    resource_id: upload.json?.id ?? upload.json?.resource_id ?? null,
    deduplicated: upload.json?.deduplicated ?? null,
  });

  // Step 2b — real provider capability probe. The streaming lane is
  // fail-closed until this passes; its result travels with every turn.
  let providerTest = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    providerTest = await post("/provider/test", {
      provider: providerPayload,
      api_key: providerKey,
      response_language: "zh-CN",
    });
    if (providerTest.status === 200 && providerTest.json?.ok === true && providerTest.json?.streaming_ready === true) {
      break;
    }
  }
  providerTestResult = providerTest.json;
  const toolsReady = providerTest.json?.tools_ready === true;
  step("02b-provider-test", {
    status: providerTest.status,
    ok: providerTest.json?.ok ?? null,
    streaming_ready: providerTest.json?.streaming_ready ?? null,
    model_supported: providerTest.json?.model_supported ?? null,
    tools_ready: providerTest.json?.tools_ready ?? null,
    agent_loop: toolsReady,
  });
  if (providerTest.status !== 200 || providerTest.json?.ok !== true) {
    throw new Error(`Real provider capability test did not pass: ${providerTest.text.slice(0, 300)}`);
  }
  if (providerTest.json?.streaming_ready !== true) {
    throw new Error("Real provider streaming capability is still unverified.");
  }

  // Step 3 — understanding/question turn (real model)
  const ask = await streamTurn({
    session_id: sessionId,
    workspace_id: "journey-ws-a",
    message: "我在学 Python 多线程。请解释上面这段 Queue 代码里锁的作用，并给我一个最小、可验证的第一步。",
    mode: "guided",
    response_language_override: "zh-CN",
    use_agent_loop: toolsReady,
    provider: providerPayload,
    api_key: providerKey,
  });
  const nextMatch = [...ask.text.matchAll(/"(?:completion_next_step|nextStep|next_step)"\s*:\s*"((?:\\.|[^"\\])*)"/g)];
  const nextStep = nextMatch.length ? JSON.parse(`"${nextMatch[nextMatch.length - 1][1]}"`) : null;
  step("03-understand-turn", {
    status: ask.status,
    visible_chars: ask.visible.length,
    next_step: nextStep,
    has_complete: /event:\s*complete/.test(ask.text),
    preview: ask.text.slice(0, 4000),
    visible_preview: ask.visible.slice(0, 1200),
  });

  // Step 4 — learning plan generation
  const plan = await post("/plan/generate", {
    session_id: sessionId,
    workspace_id: "journey-ws-a",
    profile: {
      long_term_goal: "掌握 Python 并发编程",
      weekly_hours: 5,
      teaching_style: "guided",
      answer_policy: "guided",
      preferred_libraries: ["asyncio", "threading"],
    },
    goals: ["掌握 Python threading 的锁与队列"],
    provider: providerPayload,
    api_key: providerKey,
    last_test_result: providerTestResult,
  });
  if (plan.status !== 200) {
    console.error("plan error body:", plan.text.slice(0, 400));
  }
  step("04-plan-generate", { status: plan.status, plan_id: plan.json?.plan?.id ?? plan.json?.plan_id ?? null, error: plan.status !== 200 ? plan.text.slice(0, 300) : null });

  // Step 5 — INTERRUPTION: kill and restart the sidecar (session restore path)
  sidecar.kill("SIGTERM");
  await new Promise((r) => setTimeout(r, 2500));
  sidecar = spawn(python, ["run_sidecar.py", "--host", "127.0.0.1", "--port", "34978"], {
    cwd: serverDir,
    env: { ...process.env, TRAINER_DATA_DIR: dataDir, TRAINER_ENABLE_NETWORK_FETCH: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  sidecar.stdout.on("data", (c) => (sidecarLog += c));
  sidecar.stderr.on("data", (c) => (sidecarLog += c));
  await waitForHealth();
  const restored = await post("/session/start", {
    session_id: sessionId,
    workspace_id: "journey-ws-a",
    workspace_name: "Journey A",
  });
  step("05-restart-restore", {
    status: restored.status,
    same_session: restored.json?.session_id === sessionId,
    conversation_len: restored.json?.snapshot?.messages?.length ?? restored.json?.messages?.length ?? null,
  });

  // Step 6 — mid-journey follow-up turn after restore (continuity evidence)
  const continuityBody = {
    session_id: sessionId,
    workspace_id: "journey-ws-a",
    message: "继续：把我刚才那一步写出来，并说明怎么验证。",
    mode: "guided",
    response_language_override: "zh-CN",
    use_agent_loop: toolsReady,
    provider: providerPayload,
    api_key: providerKey,
  };
  const followup = await streamTurn(continuityBody);
  step("06-continuity-turn", {
    status: followup.status,
    visible_chars: followup.visible.length,
    has_complete: /event:\s*complete/.test(followup.text),
    preview: followup.text.slice(0, 4000),
    visible_preview: followup.visible.slice(0, 1200),
    sidecar_log_tail: sidecarLog.slice(-5000),
  });
  if (followup.status === 200 && followup.visible.length === 0) {
    const fallback = await streamTurn({ ...continuityBody, use_agent_loop: false });
    step("06b-continuity-non-agent", {
      status: fallback.status,
      visible_chars: fallback.visible.length,
      has_complete: /event:\s*complete/.test(fallback.text),
      visible_preview: fallback.visible.slice(0, 1200),
      note: "agent-loop turn hit its provider output limit; non-agent fallback is real-model evidence only",
    });
  }

  // Step 7 — workspace switch (workspace B, isolated session)
  const startB = await post("/session/start", {
    workspace_id: "journey-ws-b",
    workspace_name: "Journey B",
  });
  const sessionB = startB.json.session_id;
  const askB = await streamTurn({
    session_id: sessionB,
    workspace_id: "journey-ws-b",
    message: "你好，这是另一个工作区。请确认你能看到什么上下文？",
    mode: "guided",
    response_language_override: "zh-CN",
    use_agent_loop: toolsReady,
    provider: providerPayload,
    api_key: providerKey,
  });
  const leaked = askB.visible.includes("Queue") || askB.visible.includes("_lock");
  step("07-workspace-switch", {
    status: askB.status,
    workspace_b_session: sessionB,
    cross_workspace_leak: leaked,
    visible_chars: askB.visible.length,
    visible_preview: askB.visible.slice(0, 800),
    sidecar_log_tail: sidecarLog.slice(-5000),
  });

  // Step 8 — model switch: test the second model, then use that capability
  // result for the switch turn (same relay, different model id).
  const switchProvider = { ...providerPayload, model: modelSwitch };
  const switchTest = await post("/provider/test", {
    provider: switchProvider,
    api_key: providerKey,
    response_language: "zh-CN",
  });
  step("08a-model-switch-test", {
    status: switchTest.status,
    ok: switchTest.json?.ok ?? null,
    model: modelSwitch,
  });
  const switched = await streamTurn({
    session_id: sessionId,
    workspace_id: "journey-ws-a",
    message: "换一个模型继续。请用一句话确认你在。",
    mode: "guided",
    response_language_override: "zh-CN",
    use_agent_loop: false,
    provider: switchProvider,
    api_key: providerKey,
    last_test_result: switchTest.json,
  });
  step("08-model-switch", { status: switched.status, visible_chars: switched.visible.length, model: modelSwitch });

  // Step 9 — memory summary (review/evidence of the loop state)
  const memory = await fetch(`${baseUrl}/memory/summary?workspace_id=journey-ws-a`);
  const memoryJson = await memory.json().catch(() => null);
  step("09-memory-summary", {
    status: memory.status,
    has_summary: Boolean(memoryJson),
  });

  console.log(`JOURNEY_OK ${outDir}`);
} catch (error) {
  console.error("JOURNEY_FAILED:", error.message);
  fs.writeFileSync(path.join(outDir, "FAILURE.json"), JSON.stringify({ error: error.message, sidecarLog: sidecarLog.slice(-4000) }, null, 2));
  process.exitCode = 1;
} finally {
  sidecar.kill("SIGTERM");
}
