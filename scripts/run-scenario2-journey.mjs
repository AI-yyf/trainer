// Scenario 2 acceptance (十三·场景二): "围绕这篇论文，帮我完成备课".
//
// Real-model chain against a live provider:
//   01 session + provider test
//   02 ingest the paper (markdown upload -> resource library -> indexed)
//   03 lesson-prep ask in the Resources lane (analyze mode + resource ids):
//      the reply must build on the paper's own concepts (grounded analysis)
//   04 lesson-prep output: /resource/research-brief/draft turns the reply
//      into a saved research_brief asset; P2.6 auto-links the live plan and
//      sourced findings stay traceable
//   05 candidate card: /training/generate-card from the resource
//      (source=resource_knowledge) -> status candidate with pinned provenance
//
// Requires PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY (+
// PROBE_PROVIDER_MODEL, default MiniMax-M2.7).
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const repoRoot = "/Users/Apple/Desktop/trainer";
const serverDir = path.join(repoRoot, "server");
const python = path.join(serverDir, ".venv", "bin", "python");
const baseUrl = "http://127.0.0.1:34982";
const providerBase = process.env.PROBE_PROVIDER_BASE_URL ?? "";
const providerKey = process.env.PROBE_PROVIDER_API_KEY ?? "";
const model = process.env.PROBE_PROVIDER_MODEL ?? "MiniMax-M2.7";
const outDir =
  process.env.JOURNEY_OUT_DIR ??
  path.join(repoRoot, "output/maturity", `scenario2-${new Date().toISOString().replace(/[:.]/g, "-")}`);
fs.mkdirSync(outDir, { recursive: true });

if (!providerBase || !providerKey) {
  console.error("PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY required");
  process.exit(2);
}
try {
  await fetch(`${baseUrl}/health`);
  console.error(`port 34982 already served — kill the stale sidecar first`);
  process.exit(4);
} catch {}

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-scenario2-"));
let sidecar = null;
let providerTestResult = null;
let sidecarLog = "";
let failures = 0;

const providerPayload = {
  name: "scenario2",
  baseUrl: providerBase,
  apiKeyRef: "scenario2",
  model,
  protocol: "openai_chat_completions_compatible",
};

// A small self-contained "paper" (deterministic concepts the assertions can
// pin): episode boundaries for world-model rollouts.
const PAPER_MARKDOWN = [
  "# Episode Boundaries in World-Model Rollouts",
  "",
  "## 1. Termination versus truncation",
  "A rollout ends in one of two ways. **Termination** means the environment reached a true final state: the reward stream stops, and the value of every state after termination is treated as zero. **Truncation** means sampling was stopped early (a frame or step budget); the value bootstrap continues from the final observed state's value estimate.",
  "",
  "## 2. One-step prediction objective",
  "The world model learns a one-step dynamics model: given the encoded latent state z_t and the executed action a_t, it predicts the next latent state z_{t+1}. Training minimizes the reconstruction and prediction error between the predicted next latent and the encoder output of the real next observation.",
  "",
  "## 3. Rollout imagination",
  "After training, the model imagines rollouts by iterating its own predictions without touching the real environment. imagined trajectories feed the policy optimization, which is why boundary handling (termination vs truncation) directly changes the value targets used during imagination.",
  "",
  "## 4. Related work divergence",
  "Earlier agent papers stopped the gradient at imagined states to stabilize training; later work lets gradients flow through the whole imagination trajectory but clips the value loss. The two lines disagree on where the value bootstrap should stop.",
].join("\n");

function sidecarProc() {
  return spawn(python, ["run_sidecar.py", "--host", "127.0.0.1", "--port", "34982"], {
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
  const wsDir = path.join(dataDir, "workspace");
  fs.mkdirSync(wsDir, { recursive: true });
  // 01b — 加入 Trainer: resource-grounded cards require an adopted workspace.
  // Headless journeys seed the same canonical Root/Project/Context bundle the
  // host admission route writes (idempotent, repository-level).
  const provisioning = spawnSync(
    python,
    [path.join(repoRoot, "scripts", "journey_provision.py"), dataDir, "trainer.sqlite3", "scenario2-ws", "Lesson Prep Journey"],
    { cwd: serverDir, env: process.env, encoding: "utf8" },
  );
  const contextId = (provisioning.stdout ?? "").trim() || "scenario2-ws";
  step("01-provision-adopted", {
    provisioning_status: provisioning.status,
    provisioning_error: provisioning.status !== 0 ? (provisioning.stderr ?? "").slice(0, 300) : undefined,
    context_id: contextId,
  }, { fail: provisioning.status !== 0 });

  const start = await post("/session/start", {
    workspace_id: "scenario2-ws",
    workspace_name: "Lesson Prep Journey",
    workspace_path: wsDir,
  });
  const sessionId = start.json?.session_id ?? "";
  const providerTest = await post("/provider/test", {
    provider: providerPayload,
    apiKey: providerKey,
    responseLanguage: "zh-CN",
  });
  providerTestResult = providerTest.json;
  step("02-session-provider", {
    session_ok: start.status === 200 && Boolean(sessionId),
    provider_ok: providerTest.json?.ok === true,
  }, { fail: start.status !== 200 || !sessionId || providerTest.json?.ok !== true });


  // 02 — 获取原始论文：ingest the paper into the resource library
  fs.writeFileSync(path.join(dataDir, "paper-episode-boundaries.md"), PAPER_MARKDOWN);
  const upload = await post("/resource/upload", {
    session_id: sessionId,
    workspace_id: "scenario2-ws",
    kind: "markdown",
    name: "Episode Boundaries in World-Model Rollouts",
    source: "papers.example.com/episode-boundaries",
    content: PAPER_MARKDOWN,
    content_encoding: "utf-8",
    tags: ["paper", "world-models"],
  });
  const resourceId = upload.json?.id ?? "";
  // Index the paper so the analyze lane has verified excerpts to ground on.
  let indexed = "";
  if (resourceId) {
    const index = await post("/resource/index", {
      session_id: sessionId,
      workspace_id: "scenario2-ws",
      resource_id: resourceId,
    });
    indexed = String(index.json?.index_status ?? index.json?.resource?.index_status ?? "");
    for (let poll = 0; poll < 15 && indexed !== "indexed"; poll += 1) {
      await new Promise((r) => setTimeout(r, 1000));
      const snap = await snapshot(contextId, sessionId);
      const record = (snap.json?.resources ?? []).find((item) => item.id === resourceId);
      indexed = String(record?.index_status ?? indexed);
    }
  }
  step("03-paper-ingested", {
    status: upload.status,
    resource_id: resourceId,
    index_status: indexed,
  }, { fail: upload.status !== 200 || !resourceId });

  // 03 — 备课 ask：analyze mode bound to the paper
  const prep = await streamTurn({
    session_id: sessionId,
    workspace_id: "scenario2-ws",
    message: "围绕这篇论文，帮我完成备课，重点研究它的技术原理、相关工作和关键创新。",
    intent: "coach",
    active_view: "resources",
    resource_composer_intent: { mode: "analyze", resource_ids: resourceId ? [resourceId] : [] },
    resource_ids: resourceId ? [resourceId] : [],
  });
  const prepText = prep.visible;
  // Grounded analysis: the reply must name concepts that exist in the paper.
  const grounded = ["termination", "truncation", "终止", "截断", "一步预测", "rollout", "imagination", "value"]
    .filter((token) => prepText.toLowerCase().includes(token.toLowerCase()));
  const prepOk = prep.status === 200 && prepText.length >= 200 && grounded.length >= 2;
  step("04-lesson-prep-ask", {
    status: prep.status,
    visible_chars: prepText.length,
    grounded_tokens: grounded,
    preview: prepText.slice(0, 220),
    ...(prep.status !== 200 ? { error_detail: errorDetail(prep.text) } : {}),
  }, { fail: !prepOk });

  // 04 — 备课产出：draft -> saved research brief (P2.6 plan link included)
  const draft = await post("/resource/research-brief/draft", {
    session_id: sessionId,
    workspace_id: "scenario2-ws",
    context_id: contextId,
    researchGoal: "围绕《Episode Boundaries in World-Model Rollouts》完成备课",
    reply: prepText.slice(0, 12000),
    resourceIds: resourceId ? [resourceId] : [],
    responseLanguage: "zh-CN",
    title: "备课简报：Episode Boundaries",
    save: true,
    provider: providerPayload,
    api_key: providerKey,
  });
  const brief = draft.json?.brief ?? {};
  const briefOk = draft.status === 200 && draft.json?.saved === true &&
    Array.isArray(brief.keyQuestions) &&
    (brief.findings ?? []).length > 0 &&
    Boolean(brief.researchGoal);
  step("05-research-brief-saved", {
    status: draft.status,
    error_detail: draft.status !== 200 ? errorDetail(draft.text) : undefined,
    saved: draft.json?.saved ?? false,
    plan_id: brief.planId ?? "",
    stage_id: brief.stageId ?? "",
    findings: (brief.findings ?? []).map((f) => ({ status: f.claimStatus, statement: f.statement?.slice(0, 60) })),
    check_questions: (brief.checkQuestions ?? []).length,
  }, { fail: !briefOk });

  // 05 — 训练卡候选：a resource-grounded candidate from the paper (the
  // workspace was adopted in 01b, which the resource card path requires).
  // Runtime verify (same gate the card route uses) — prints the exact
  // integrity reason if the lanes were disturbed by earlier turns.
  const runtimeVerify = spawnSync(
    python,
    [
      "-c",
      [
        "import sys",
        "from pathlib import Path",
        "sys.path.insert(0, 'server')",
        "from app.db.repository import TrainerRepository",
        "from app.memory.service import MemoryService",
        "from app.planner.service import PlannerService",
        "from app.workspace.provisioning import ProjectProvisioningService, ProjectProvisioningIntegrityError",
        "repo = TrainerRepository(Path(sys.argv[1]) / 'trainer.sqlite3')",
        "service = ProjectProvisioningService(repository=repo, memory_service=MemoryService(repo, event_ledger=None), planner_service=PlannerService(repository=repo))",
        "try:",
        "    prov = service.get(sys.argv[2])",
        "    print('VERIFY_OK', prov is not None)",
        "except ProjectProvisioningIntegrityError as exc:",
        "    print('VERIFY_FAIL', exc)",
      ].join("\n"),
      dataDir,
      "scenario2-ws",
    ],
    { cwd: serverDir, env: process.env, encoding: "utf8" },
  );
  console.log((runtimeVerify.stdout ?? "").trim());
  const card = await post("/training/generate-card", {
    session_id: sessionId,
    workspace_id: "scenario2-ws",
    source: "resource_knowledge",
    card_type: "practice",
    submode: "practice",
    resource_id: resourceId,
    focus_area: "Episode boundaries",
    target_skill: "区分 termination 与 truncation 对价值目标的影响",
    prompt: "围绕这篇论文出一张练习：给出一段 rollout 场景，判断它是 termination 还是 truncation，并说明价值目标如何处理。",
    provider: providerPayload,
    api_key: providerKey,
  });
  const cardJson = card.json?.card ?? {};
  const candidateOk = card.status === 200 && (cardJson.status ?? "candidate") === "candidate";
  const provenanceOk = (cardJson.resource_id ?? "") === resourceId;
  // The unified ledger surfaces intake as learning activity; poll briefly so
  // a just-recorded event is visible to the snapshot read.
  let ledgerOk = false;
  for (let poll = 0; poll < 5 && !ledgerOk; poll += 1) {
    await new Promise((r) => setTimeout(r, 1200));
    const snap = await snapshot(contextId, sessionId);
    const learningActivity = snap.json?.memory?.learning_activity ?? [];
    ledgerOk = learningActivity.some(
      (entry) => (entry.eventType ?? entry.event_type) === "card_candidate_created",
    );
  }
  const lastSnap = await snapshot(contextId, sessionId);
  step("06-resource-candidate-card", {
    status: card.status,
    card_id: cardJson.card_id ?? "",
    card_status: cardJson.status ?? "",
    resource_pinned: provenanceOk,
    ledger_event: ledgerOk,
    activity_kinds: (lastSnap.json?.memory?.learning_activity ?? []).map((a) => a.eventType ?? a.event_type),
    candidates_len: (lastSnap.json?.workspaceTrainingState?.trainingCardCandidates ?? []).length,
    ...(card.status !== 200 ? { error_detail: errorDetail(card.text) } : {}),
  }, { fail: !candidateOk || !provenanceOk || !ledgerOk });

  const summary = {
    scenario: "13-场景二：研究与备课",
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
