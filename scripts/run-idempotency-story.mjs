/**
 * Live-provider CLI verification runner for the Contract §10 "Idempotency" story.
 *
 * Requires external provider credentials via environment variables:
 *   PROBE_PROVIDER_BASE_URL
 *   PROBE_PROVIDER_API_KEY
 *   PROBE_PROVIDER_MODEL (optional, defaults to MiniMax-M3.1-Flash)
 *
 * Fails closed with exit code 2 when credentials are absent so live-model passes
 * can never be fabricated offline.
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const serverDir = path.join(repoRoot, "server");
const pythonBin = path.join(serverDir, ".venv", "bin", "python");

const providerBase = (process.env.PROBE_PROVIDER_BASE_URL || "").trim();
const providerKey = (process.env.PROBE_PROVIDER_API_KEY || "").trim();
const providerModel = (process.env.PROBE_PROVIDER_MODEL || "MiniMax-M3.1-Flash").trim();

const BANNED_LEARNER_TERMS = [
  "fsrs",
  "sidecar",
  "telemetry",
  "workbench",
  "attestation",
  "handoff",
];

if (!providerBase || !providerKey) {
  console.error(
    "Missing PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY. Supply live provider credentials to run scripts/run-idempotency-story.mjs.",
  );
  process.exit(2);
}

function allocatePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (!addr || typeof addr === "string") {
        server.close(() => reject(new Error("Failed to allocate localhost port.")));
        return;
      }
      const { port } = addr;
      server.close((err) => {
        if (err) reject(err);
        else resolve(port);
      });
    });
  });
}

async function waitForHealth(baseUrl) {
  for (let i = 0; i < 120; i += 1) {
    try {
      const resp = await fetch(`${baseUrl}/health`);
      if (resp.ok) return;
    } catch {
      // Sidecar still booting.
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`Sidecar failed to become healthy at ${baseUrl}`);
}

async function requestJson(baseUrl, pathname, method, body) {
  const resp = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers: body !== undefined ? { "content-type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  return { status: resp.status, json, text };
}

async function streamTurn(baseUrl, payload) {
  const startedAt = performance.now();
  const resp = await fetch(`${baseUrl}/turn/stream`, {
    method: "POST",
    headers: {
      accept: "text/event-stream",
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => "");
    throw new Error(`POST /turn/stream failed (${resp.status}): ${text.slice(0, 300)}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let visible = "";
  let rawEvents = "";
  let ttftMs = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    rawEvents += text;
    buffer += text;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const parsed = JSON.parse(line.slice(6));
        if (typeof parsed?.chunk === "string" && parsed.chunk.length > 0) {
          if (ttftMs === null) {
            ttftMs = Math.round(performance.now() - startedAt);
          }
          visible += parsed.chunk;
        }
      } catch {
        // Ignore non-JSON heartbeat lines.
      }
    }
  }
  const totalTurnMs = Math.round(performance.now() - startedAt);
  return {
    status: resp.status,
    ttftMs,
    totalTurnMs,
    visible,
    completed: rawEvents.includes("event: complete"),
  };
}

function assertNoBannedJargon(text, label) {
  const lowered = text.toLowerCase();
  for (const term of BANNED_LEARNER_TERMS) {
    if (lowered.includes(term)) {
      throw new Error(`Banned learner-facing term "${term}" found in ${label}: ${text.slice(0, 200)}`);
    }
  }
}

async function adoptWorkspace(baseUrl, workspaceOwnerId, trainerRoot, projectRepo) {
  const classified = await requestJson(baseUrl, "/workspace/classify", "POST", {
    workspace_id: workspaceOwnerId,
    folder_path: projectRepo,
    root_path: trainerRoot,
    response_language: "zh-CN",
  });
  if (classified.status !== 200 || !classified.json?.project_discovery?.discovery_id) {
    throw new Error(`/workspace/classify failed: ${classified.status} ${classified.text.slice(0, 300)}`);
  }
  const discoveryId = classified.json.project_discovery.discovery_id;
  const decided = await requestJson(baseUrl, "/workspace/discovery/decision", "POST", {
    workspace_id: workspaceOwnerId,
    discovery_id: discoveryId,
    decision: "adopt",
    root_path: trainerRoot,
  });
  if (decided.status !== 200) {
    throw new Error(`/workspace/discovery/decision failed: ${decided.status} ${decided.text.slice(0, 300)}`);
  }
  if (decided.json?.project_provisioning?.context_id) {
    return decided.json.project_provisioning.context_id;
  }
  const jobId = decided.json?.project_adoption_job?.job_id;
  if (!jobId) {
    throw new Error(`Missing adoption job_id: ${decided.text.slice(0, 300)}`);
  }
  for (let i = 0; i < 40; i += 1) {
    const query = new URLSearchParams({
      workspace_id: workspaceOwnerId,
      root_path: trainerRoot,
      job_id: jobId,
    });
    const polled = await requestJson(baseUrl, `/workspace/adoption-job?${query.toString()}`, "GET");
    if (polled.status === 200 && polled.json?.project_provisioning?.context_id) {
      return polled.json.project_provisioning.context_id;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Timed out waiting for project adoption job.");
}

async function main() {
  const tempBase = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-idempotency-live-"));
  const trainerRoot = path.join(tempBase, "library-root");
  const runtimeDir = path.join(trainerRoot, ".trainer", "runtime");
  const projectRepo = path.join(tempBase, "payments-service");
  fs.mkdirSync(runtimeDir, { recursive: true });
  fs.mkdirSync(projectRepo, { recursive: true });

  const paymentsCode = [
    "def charge(order_id: str, key: str, seen: dict[str, dict]) -> dict:",
    "    if key in seen:",
    "        return seen[key]",
    "    result = {'order_id': order_id, 'status': 'charged'}",
    "    seen[key] = result",
    "    return result",
    "",
  ].join("\n");
  fs.writeFileSync(path.join(projectRepo, "payments.py"), paymentsCode, "utf-8");

  const port = await allocatePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  let sidecar = null;
  let sidecarLog = "";

  try {
    sidecar = spawn(pythonBin, ["run_sidecar.py", "--host", "127.0.0.1", "--port", String(port)], {
      cwd: serverDir,
      env: {
        ...process.env,
        TRAINER_DATA_DIR: runtimeDir,
        TRAINER_ENABLE_NETWORK_FETCH: "0",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    sidecar.stdout.on("data", (chunk) => {
      sidecarLog += chunk.toString();
    });
    sidecar.stderr.on("data", (chunk) => {
      sidecarLog += chunk.toString();
    });

    await waitForHealth(baseUrl);

    const contextId = await adoptWorkspace(baseUrl, "live-idempotency", trainerRoot, projectRepo);
    const sessionStart = await requestJson(baseUrl, "/session/start", "POST", {
      workspace_id: contextId,
      workspace_name: "payments-service",
      workspace_path: projectRepo,
      workspace_trusted: true,
      profile: {
        long_term_goal: "Master HTTP retry idempotency",
        teaching_style: "guided",
        answer_policy: "guided",
      },
    });
    if (sessionStart.status !== 200 || !sessionStart.json?.session_id) {
      throw new Error(`/session/start failed: ${sessionStart.status} ${sessionStart.text.slice(0, 300)}`);
    }
    const sessionId = sessionStart.json.session_id;

    const providerPayload = {
      name: "idempotency-live-probe",
      baseUrl: providerBase,
      apiKeyRef: "idempotency-live-probe",
      model: providerModel,
      protocol: "openai_chat_completions_compatible",
    };
    const providerTest = await requestJson(baseUrl, "/provider/test", "POST", {
      provider: providerPayload,
      api_key: providerKey,
      response_language: "zh-CN",
    });
    if (providerTest.status !== 200 || providerTest.json?.ok !== true) {
      throw new Error(`/provider/test failed: ${providerTest.status} ${providerTest.text.slice(0, 300)}`);
    }

    const uploaded = await requestJson(baseUrl, "/resource/upload", "POST", {
      workspace_id: contextId,
      session_id: sessionId,
      name: "HTTP Idempotency Notes",
      kind: "markdown",
      source: "http-idempotency.md",
      content: "# HTTP Idempotency\n\nSame key replays the prior outcome without charging twice.\n",
      content_encoding: "utf-8",
    });
    if (uploaded.status !== 200 || !uploaded.json?.id) {
      throw new Error(`/resource/upload failed: ${uploaded.status} ${uploaded.text.slice(0, 300)}`);
    }
    const indexed = await requestJson(baseUrl, "/resource/index", "POST", {
      workspace_id: contextId,
      resource_id: uploaded.json.id,
    });
    if (indexed.status !== 200 || !indexed.json?.canonical_markdown_path) {
      throw new Error(`/resource/index failed: ${indexed.status} ${indexed.text.slice(0, 300)}`);
    }

    const turn1 = await streamTurn(baseUrl, {
      session_id: sessionId,
      workspace_id: contextId,
      message: "为什么 HTTP 重试幂等键不能只放在单个进程的内存 dict 里？请用一个具体故障场景带我判断。",
      intent: "coach",
      response_language: "zh-CN",
      provider: providerPayload,
      api_key: providerKey,
      last_test_result: providerTest.json,
      current_file: {
        path: path.join(projectRepo, "payments.py"),
        language_id: "python",
        content: paymentsCode,
      },
    });
    assertNoBannedJargon(turn1.visible, "turn1");

    const turn2 = await streamTurn(baseUrl, {
      session_id: sessionId,
      workspace_id: contextId,
      message: "如果进程重启或请求落到另一台实例，内存 dict 就丢了，对吧？那我接下来该怎么验证修复？",
      intent: "coach",
      response_language: "zh-CN",
      provider: providerPayload,
      api_key: providerKey,
      last_test_result: providerTest.json,
      current_file: {
        path: path.join(projectRepo, "payments.py"),
        language_id: "python",
        content: paymentsCode,
      },
    });
    assertNoBannedJargon(turn2.visible, "turn2");

    const storageTruth = await requestJson(
      baseUrl,
      `/workspace/storage-truth?workspace_id=${encodeURIComponent(contextId)}`,
      "GET",
    );
    if (
      storageTruth.status !== 200
      || storageTruth.json?.all_under_library_root !== true
      || (storageTruth.json?.outside_library_root?.length ?? 1) !== 0
    ) {
      throw new Error(`/workspace/storage-truth failed: ${storageTruth.text.slice(0, 300)}`);
    }

    const repoFiles = fs.readdirSync(projectRepo);
    if (repoFiles.length !== 1 || repoFiles[0] !== "payments.py") {
      throw new Error(`Code repo polluted! Found: ${JSON.stringify(repoFiles)}`);
    }

    const evidencePath = path.join(repoRoot, "output", "idempotency-story-evidence.json");
    fs.mkdirSync(path.dirname(evidencePath), { recursive: true });
    const evidence = {
      generatedAt: new Date().toISOString(),
      model: providerModel,
      libraryRoot: trainerRoot,
      contextId,
      canonicalMarkdownPath: indexed.json.canonical_markdown_path,
      storageTruth: storageTruth.json,
      projectRepoFiles: repoFiles,
      turns: [
        {
          turn: 1,
          ttftMs: turn1.ttftMs,
          totalTurnMs: turn1.totalTurnMs,
          completed: turn1.completed,
          replyLength: turn1.visible.length,
        },
        {
          turn: 2,
          ttftMs: turn2.ttftMs,
          totalTurnMs: turn2.totalTurnMs,
          completed: turn2.completed,
          replyLength: turn2.visible.length,
        },
      ],
    };
    fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf-8");
    console.log(
      `PASS idempotency-story-live model=${providerModel} turn1_ttft=${turn1.ttftMs}ms turn2_ttft=${turn2.ttftMs}ms evidence=${evidencePath}`,
    );
  } finally {
    if (sidecar && !sidecar.killed) {
      sidecar.kill("SIGTERM");
    }
    if (sidecarLog && process.env.DEBUG_SIDECAR_LOG) {
      console.error(sidecarLog);
    }
    fs.rmSync(tempBase, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
