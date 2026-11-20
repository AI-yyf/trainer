// Scenario 2 acceptance (十三·场景二): "围绕这篇论文，帮我完成备课".
//
// Real-model chain against a live provider:
//   01 session + provider test
//   02 ingest the primary paper and a related note into the indexed library
//   03 lesson-prep ask in the Resources lane (analyze mode + resource ids):
//      the reply must compare the two definitions of a time boundary
//   04 lesson-prep output: the requested preparation saves a research_brief
//      with the live plan and traceable findings in the same turn
//   05 candidate card: /training/generate-card from the resource
//      (source=resource_knowledge) -> status candidate with pinned provenance
//
// Requires PROBE_PROVIDER_BASE_URL / PROBE_PROVIDER_API_KEY (+
// PROBE_PROVIDER_MODEL, default MiniMax-M2.7).
// --public-sources captures a versioned arXiv PDF and a commit-pinned GitHub file.
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
const usePublicSources = process.argv.includes("--public-sources");
const publicPaper = {
  kind: "pdf",
  title: "Gymnasium: A Standard Interface for Reinforcement Learning Environments",
  url: "https://arxiv.org/pdf/2407.17032v3#page=5",
  page: 5,
};
const publicTutorial = {
  kind: "web",
  title: "Gymnasium: Handling Time Limits",
  url: "https://github.com/Farama-Foundation/Gymnasium/blob/5b6c5280e1e23a6f41b3cdfb297a26e349f6ef73/docs/tutorials/gymnasium_basics/handling_time_limits.py",
};
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
const RELATED_MARKDOWN = [
  "# Finite-horizon task semantics",
  "",
  "## When time is part of the task",
  "In a finite-horizon task, reaching the task's declared final decision step is a termination because the task itself is complete. The remaining time must be part of the observed state for the dynamics to remain Markovian.",
  "",
  "## Budget cutoffs outside the task",
  "Stopping collection with an external budget is a truncation even when a wall-clock timeout caused it. Such a cutoff preserves the value estimate of the last observed state.",
  "",
  "## Teaching check",
  "Give two examples with identical step counts, one declared by the task and one imposed by a collector. Have the learner classify each boundary and say whether to bootstrap.",
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
  return { status: r.status, text };
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

async function ingestSource(sessionId, contextId, name, filename, content) {
  const upload = await post("/resource/upload", {
    session_id: sessionId, workspace_id: contextId, kind: "markdown", name,
    source: filename, content, content_encoding: "utf-8", tags: ["world-models"],
  });
  const id = upload.json?.id;
  if (upload.status !== 200 || !id) throw new Error(`Could not upload the source ${name}: ${upload.status}`);
  const index = await post("/resource/index", {
    session_id: sessionId, workspace_id: contextId, resource_id: id,
  });
  if (index.status !== 200) throw new Error(`Could not index the source ${name}: ${index.status}`);
  let record = index.json?.resource ?? index.json;
  for (let poll = 0; poll < 15 && record?.index_status !== "indexed"; poll += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const current = (await snapshot(contextId, sessionId)).json;
    record = (current?.memory?.resources ?? current?.resources ?? []).find((item) => item.id === id) ?? record;
  }
  return { id, name, content, record };
}

async function capturePublicSource(sessionId, contextId, workspace, source) {
  const { kind, title, url, page } = source;
  const { status, json: record, text } = await post("/resources/capture", {
    session_id: sessionId, workspace_id: contextId, kind, title, url,
  }, { attempts: 1 });
  if (status !== 200 || !record?.canonical_markdown_path) {
    throw new Error(`Could not capture ${url}: ${status} ${errorDetail(text)}`);
  }
  const markdown = fs.readFileSync(path.resolve(workspace, record.canonical_markdown_path), "utf8");
  const frontMatter = markdown.match(/^---\n([\s\S]*?)\n---\n\n/u);
  const sourceLine = frontMatter?.[1].split("\n").find((line) => line.startsWith("source_url: "));
  const recordedUrl = sourceLine?.slice("source_url: ".length);
  if (recordedUrl !== url && recordedUrl !== JSON.stringify(url)) {
    throw new Error(`Canonical Markdown lost its original location: ${url} (${recordedUrl})`);
  }
  return { id: record.id, name: record.name, record, content: markdown.slice(frontMatter[0].length), url, page };
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


  const [primary, related] = usePublicSources
    ? await Promise.all([publicPaper, publicTutorial].map((source) => capturePublicSource(sessionId, contextId, wsDir, source)))
    : [
      await ingestSource(sessionId, contextId, "Episode Boundaries in World-Model Rollouts",
        "paper-episode-boundaries.md", PAPER_MARKDOWN),
      await ingestSource(sessionId, contextId, "Finite-horizon task semantics",
        "notes-finite-horizon.md", RELATED_MARKDOWN),
    ];
  const sourceById = new Map([primary, related].map((source) => [source.id, source]));
  const resourceIds = [...sourceById.keys()];
  const resourceId = primary.id;
  step("03-paper-ingested", {
    sources: [...sourceById.values()].map(({ id, name, record, url, page }) => ({
      id, name, url, page, index_status: record?.index_status,
      version_id: record?.version_id, content_hash: record?.content_hash,
    })),
  }, { fail: [...sourceById.values()].some(({ record }) => record?.index_status !== "indexed" ||
    !record?.version_id || !record?.content_hash) });

  // 03 — 备课 ask：analyze mode bound to the paper
  const prepRequest = {
    session_id: sessionId,
    workspace_id: "scenario2-ws",
    message: usePublicSources
      ? "围绕 Gymnasium 论文第 5 页的第 4.2 节和官方 Handling Time Limits 教程，帮我完成备课。比较 termination、truncation、finite horizon 和 external time limit，说明何时 value bootstrapping。请在同一条核心结论中引用两份资料的简短原文，附上一个课堂检查问题。"
      : "围绕这篇论文和附上的有限时域笔记，帮我完成备课。比较任务内时间上限和采集预算截断，说明何时价值自举，并设计一题检验区别。引用两份资料中的原文依据。",
    intent: "coach",
    active_view: "resources",
    request_id: "scenario2-prepare-lesson",
    resource_ids: resourceIds,
    response_language: "zh-CN",
  };
  const prep = await streamTurn(prepRequest);
  const savedTurn = await snapshot(contextId, sessionId);
  const savedReply = savedTurn.json?.messages?.findLast((item) => item.role === "assistant");
  const replyStatus = savedReply?.metadata?.coach_visible_status;
  const prepText = savedReply?.content ?? "";
  // Grounded analysis: the reply must name concepts that exist in the paper.
  const grounded = ["termination", "truncation", "终止", "截断", "一步预测", "rollout", "imagination", "value"]
    .filter((token) => prepText.toLowerCase().includes(token.toLowerCase()));
  const comparedIds = new Set(savedReply?.metadata?.resource_ids ?? []);
  const citations = (savedReply?.metadata?.parts ?? []).filter(({ type }) => type === "citation");
  const hasExpectedCitations = !usePublicSources || [...sourceById.values()].every(({ id, page, record }) =>
    citations.some(({ resourceId, location, versionId, contentHash }) => resourceId === id &&
      Boolean(location?.anchor_id) && (!page || location.page === page) &&
      versionId === record.version_id && contentHash === record.content_hash));
  const prepOk = prep.status === 200 && savedTurn.status === 200 && prepText.length >= 200 &&
    grounded.length >= 2 && resourceIds.every((id) => comparedIds.has(id)) &&
    hasExpectedCitations && replyStatus?.status === "done";
  step("04-lesson-prep-ask", {
    status: prep.status,
    visible_chars: prepText.length,
    reply_status: replyStatus?.status,
    stop_reason: replyStatus?.stopReason,
    attached_sources: [...comparedIds],
    citations: citations.map(({ resourceId, location }) => ({ resource_id: resourceId, location })),
    grounded_tokens: grounded,
    preview: prepText.slice(0, 220),
    ...(prep.status !== 200 ? { error_detail: errorDetail(prep.text) } : {}),
  }, { fail: !prepOk });

  // 04 — The conversational result identifies the saved brief. Reopen it
  // from Resources and check whether replaying the original request duplicates it.
  const preparation = savedReply?.metadata?.research_preparation;
  const catalog = savedTurn.json?.memory?.asset_catalog ?? savedTurn.json?.memory?.assetCatalog;
  const catalogHasBrief = catalog?.active?.some(({ asset }) => asset.id === preparation?.asset_id);
  const scopeQuery = new URLSearchParams({ context_id: contextId });
  const stored = preparation?.asset_id ? await fetch(`${baseUrl}/resource/research-briefs/${preparation.asset_id}?${scopeQuery}`) : null;
  const saved = stored?.ok ? await stored.json() : null;
  const replay = preparation?.asset_id ? await streamTurn(prepRequest) : null;
  const listResponse = await fetch(`${baseUrl}/resource/research-briefs?${scopeQuery}`);
  const listed = listResponse.ok ? await listResponse.json() : null;
  const brief = saved?.brief ?? {};
  const findings = Array.isArray(brief.findings) ? brief.findings : [];
  const sourcedFindings = findings.filter((finding) => finding.claimStatus === "sourced");
  const pinnedFindings = sourcedFindings.filter((finding) => finding.sourceRefs?.length > 0 &&
    finding.sourceRefs.every(({ ref, metadata }) => {
      const location = metadata?.location;
      const source = sourceById.get(ref);
      if (!source || !location || !Number.isInteger(location.line_start) || !Number.isInteger(location.line_end) ||
        location.line_start < 1 || location.line_end < location.line_start) return false;
      const body = source.content.split("\n").slice(location.line_start - 1, location.line_end).join("\n");
      return metadata.resource_id === ref && metadata.version_id === source.record?.version_id &&
        metadata.content_hash === source.record?.content_hash && Boolean(location.anchor_id &&
          metadata.excerpt && body.includes(metadata.excerpt));
    }));
  const comparisons = pinnedFindings.filter((finding) =>
    [...sourceById.values()].every(({ id, page }) => finding.sourceRefs.some(({ ref, metadata }) =>
      ref === id && (!page || metadata.location.page === page))));
  const replayedSameBrief = replay?.status === 200 && replay.text.includes(preparation?.asset_id) &&
    listed?.total === 1 && listed.items?.[0]?.asset?.id === preparation?.asset_id;
  const briefOk = preparation?.status === "saved" && saved?.asset?.scope === "project" &&
    catalogHasBrief && replayedSameBrief && brief.keyQuestions?.length > 0 && brief.checkQuestions?.length > 0 &&
    comparisons.length > 0 && pinnedFindings.length === sourcedFindings.length &&
    brief.planId === "plan-scenario2-ws" && brief.stageId === "stage-foundations";
  step("05-research-brief-saved", {
    status: stored?.status,
    preparation_status: preparation?.status,
    asset_id: preparation?.asset_id,
    present_in_catalog_snapshot: catalogHasBrief === true,
    replayed_same_brief: replayedSameBrief,
    plan_id: brief.planId ?? "",
    stage_id: brief.stageId ?? "",
    findings: findings.map((f) => ({
      status: f.claimStatus, statement: f.statement,
      source_locations: f.sourceRefs?.map(({ ref, metadata }) => ({ ref, location: metadata.location })),
    })),
    sourced_findings_checked_against_paper: pinnedFindings.length,
    verified_cross_source_findings: comparisons.length,
    verified_comparison_sources: comparisons[0]?.sourceRefs.map(({ ref, metadata }) => ({ ref, location: metadata.location })),
    reopened_saved_asset: stored?.ok === true,
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
  const candidateOk = card.status === 200 && cardJson.review_state === "pending" && !card.json?.active_routing;
  const provenanceOk = cardJson.resource_id === resourceId &&
    cardJson.resource_version_id === primary.record.version_id &&
    cardJson.resource_content_hash === primary.record.content_hash;
  // The unified ledger surfaces intake as learning activity; poll briefly so
  // a just-recorded event is visible to the snapshot read.
  let ledgerOk = false;
  for (let poll = 0; poll < 5 && !ledgerOk; poll += 1) {
    await new Promise((r) => setTimeout(r, 1200));
    const snap = await snapshot(contextId, sessionId);
    const learningActivity = snap.json?.memory?.learning_activity ?? [];
    ledgerOk = learningActivity.some(
      (entry) => (entry.card_id ?? entry.cardId) === cardJson.card_id &&
        (entry.eventType ?? entry.event_type) === "card_candidate_created",
    );
  }
  const lastSnap = await snapshot(contextId, sessionId);
  const pendingCandidate = lastSnap.json?.memory?.training_card_candidates?.some(
    (item) => item.card_id === cardJson.card_id && item.review_state === "pending",
  );
  const startedEarly = lastSnap.json?.memory?.learning_activity?.some((entry) =>
    (entry.card_id ?? entry.cardId) === cardJson.card_id &&
    (entry.eventType ?? entry.event_type) === "card_status_transitioned" && entry.result === "started",
  );
  step("06-resource-candidate-card", {
    status: card.status,
    card_id: cardJson.card_id ?? "",
    card_status: cardJson.status ?? "",
    resource_pinned: provenanceOk,
    ledger_event: ledgerOk,
    activity_kinds: (lastSnap.json?.memory?.learning_activity ?? []).map((a) => a.eventType ?? a.event_type),
    persisted_pending_candidate: pendingCandidate === true,
    started_early: startedEarly === true,
    ...(card.status !== 200 ? { error_detail: errorDetail(card.text) } : {}),
  }, { fail: !candidateOk || !provenanceOk || !ledgerOk || !pendingCandidate || startedEarly });

  const summary = {
    scenario: "13-场景二：研究与备课",
    public_sources: usePublicSources,
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
