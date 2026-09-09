import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";

/**
 * Live Resources main-path smoke.
 * Steps:
 *  1) provider/test → session/start
 *  2) upload → index → FTS /resource/search (elapsedMs)
 *  3) honest failure categories: bad_file / missing / sidecar_down
 *  4) Coach handoff via /session/message — same session_id continuity
 * Prefers NewAPI via TRAINER_RESOURCES_SMOKE_* / TRAINER_PROVIDER_SMOKE_*.
 */

const defaultSidecarUrl = "http://127.0.0.1:8765";
const defaultModel = "MiniMax-M3";
const defaultProtocol = "openai_chat_completions_compatible";
const defaultResponseLanguage = "en-US";
const SUPPORTED_PROTOCOLS = new Set([
  "openai_responses",
  "openai_chat_completions",
  "anthropic_messages",
  "openai_chat_completions_compatible",
  "gemini_generate_content",
]);

const sidecarUrl = (
  process.env.TRAINER_RESOURCES_SMOKE_SIDECAR_URL ??
    process.env.TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL ??
    process.env.TRAINER_TURN_SMOKE_SIDECAR_URL ??
    defaultSidecarUrl
)
  .trim()
  .replace(/\/+$/, "");
const providerBaseUrl = (
  process.env.TRAINER_RESOURCES_SMOKE_PROVIDER_BASE_URL ??
    process.env.TRAINER_PROVIDER_SMOKE_BASE_URL ??
    ""
)
  .trim()
  .replace(/\/+$/, "");
const providerApiKey = (
  process.env.TRAINER_RESOURCES_SMOKE_PROVIDER_API_KEY ??
    process.env.TRAINER_PROVIDER_SMOKE_API_KEY ??
    ""
).trim();
const providerModel = (
  process.env.TRAINER_RESOURCES_SMOKE_PROVIDER_MODEL ??
    process.env.TRAINER_PROVIDER_SMOKE_MODEL ??
    defaultModel
).trim();
const providerProtocol = normalizeProtocol(
  (
    process.env.TRAINER_RESOURCES_SMOKE_PROVIDER_PROTOCOL ??
      process.env.TRAINER_PROVIDER_SMOKE_PROTOCOL ??
      defaultProtocol
  ).trim(),
);
const responseLanguage = (
  process.env.TRAINER_RESOURCES_SMOKE_RESPONSE_LANGUAGE ?? defaultResponseLanguage
).trim();
const skipCoach =
  String(process.env.TRAINER_RESOURCES_SMOKE_SKIP_COACH || "").trim() === "1";
const deadSidecarUrl = (
  process.env.TRAINER_RESOURCES_SMOKE_DEAD_SIDECAR_URL ?? "http://127.0.0.1:17999"
)
  .trim()
  .replace(/\/+$/, "");

const smokeStartedAt = Date.now();
let lastSessionId = "";
let lastWorkspaceId = "";
const MARKER = "RESOURCE-SMOKE-MARKER-ALPHA-7f3c";

function elapsedMs() {
  return Date.now() - smokeStartedAt;
}

function normalizeProtocol(value) {
  return SUPPORTED_PROTOCOLS.has(value) ? value : defaultProtocol;
}

function providerRequestDefaults() {
  if (
    providerProtocol === "openai_responses" ||
    providerProtocol === "openai_chat_completions" ||
    providerProtocol === "openai_chat_completions_compatible"
  ) {
    return {
      extra_body: {
        thinking: {
          type: "disabled",
        },
      },
    };
  }
  return {};
}

function compact(value) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function redactSecrets(value) {
  return String(value || "").replace(/sk-[A-Za-z0-9_-]+/g, "sk-***");
}

async function emitJson(stream, report) {
  await new Promise((resolve, reject) => {
    stream.write(`${JSON.stringify(report)}\n`, (error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });
}

async function failure({ step, category, detail, diagnostics, status, sessionId, workspaceId }) {
  const report = {
    ok: false,
    step,
    category,
    detail: compact(detail) || "Smoke check failed. See step and category.",
    diagnostics,
    status,
    responseBodyRedacted: typeof status === "number",
    providerProtocol,
    responseLanguage,
    providerModel,
    elapsedMs: elapsedMs(),
    sessionContinuity: {
      sessionId: compact(sessionId) || lastSessionId || null,
      workspaceId: compact(workspaceId) || lastWorkspaceId || null,
      preserved: Boolean(compact(sessionId) || lastSessionId),
    },
  };
  await emitJson(process.stderr, report);
  process.exitCode = 1;
  throw new Error("__resources_smoke_failed__");
}

async function success(report) {
  await emitJson(process.stdout, report);
  process.exitCode = 0;
}

async function postJson(route, payload, { baseUrl = sidecarUrl, timeoutMs = 240000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${baseUrl}${route}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const text = await response.text();
    let json;
    try {
      json = JSON.parse(text);
    } catch {
      json = undefined;
    }
    return { response, text, json };
  } finally {
    clearTimeout(timer);
  }
}

function providerPayload() {
  const payload = {
    name: "trainer-resources-smoke",
    baseUrl: providerBaseUrl,
    apiKeyRef: "trainer.resources-smoke",
    model: providerModel,
    protocol: providerProtocol,
  };
  const requestDefaults = providerRequestDefaults();
  if (Object.keys(requestDefaults).length > 0) {
    payload.requestDefaults = requestDefaults;
  }
  return payload;
}

async function createFixture() {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "trainer-resources-smoke-"));
  const notePath = path.join(tempDir, "coach-notes.md");
  const body =
    `# Resources smoke notes\n\n`
    + `This document contains the unique token ${MARKER} so FTS can ground Coach.\n`
    + `Resources first viewport must stay trustworthy and never invent missing files.\n`;
  await fs.writeFile(notePath, body, "utf8");
  return { tempDir, notePath, noteContent: body };
}

function collectCoachEvidence(payload, expectedTitle) {
  const meta =
    payload?.reply?.metadata ||
    payload?.reply?.meta ||
    payload?.metadata ||
    {};
  const toolEvents = Array.isArray(meta.tool_events)
    ? meta.tool_events
    : Array.isArray(meta.toolEvents)
      ? meta.toolEvents
      : [];
  const coachVisible =
    meta.coach_visible_status || meta.coachVisibleStatus || {};
  const toolNames = Array.isArray(coachVisible.toolNames)
    ? coachVisible.toolNames
    : Array.isArray(coachVisible.tool_names)
      ? coachVisible.tool_names
      : [];
  let searchCalls = 0;
  let searchResults = 0;
  const titles = [];
  for (const event of toolEvents) {
    const name = compact(event?.name || event?.tool || event?.tool_name);
    if (name === "search_resources") {
      searchCalls += 1;
      const result = event?.result || event?.output || {};
      const hits = Array.isArray(result.hits)
        ? result.hits
        : Array.isArray(result.results)
          ? result.results
          : [];
      searchResults += hits.length;
      for (const hit of hits) {
        titles.push(compact(hit?.title || hit?.name));
      }
    }
  }
  if (toolNames.includes("search_resources") && searchCalls === 0) {
    searchCalls = 1;
  }
  const replyContent = compact(
    payload?.reply?.content || payload?.coach_turn?.summary || "",
  );
  return {
    autoResourceLookup: Boolean(meta.auto_resource_lookup ?? meta.autoResourceLookup),
    searchCalls,
    searchResults,
    matchedExpectedTitle: titles.includes(expectedTitle),
    replyPresent: Boolean(replyContent),
    toolNames,
    stopReason: compact(coachVisible.stopReason || coachVisible.stop_reason || meta.stop_reason),
  };
}

async function main() {
  if (!providerBaseUrl) {
    return failure({
      step: "config",
      category: "missing_provider_base_url",
      detail:
        "Set TRAINER_RESOURCES_SMOKE_PROVIDER_BASE_URL or TRAINER_PROVIDER_SMOKE_BASE_URL before running the resources smoke.",
      diagnostics: [],
    });
  }
  if (!providerApiKey) {
    return failure({
      step: "config",
      category: "missing_provider_api_key",
      detail:
        "Set TRAINER_RESOURCES_SMOKE_PROVIDER_API_KEY or TRAINER_PROVIDER_SMOKE_API_KEY before running the resources smoke.",
      diagnostics: [],
    });
  }

  const diagnostics = [];
  const steps = [];
  const failureCategories = {};

  const stepStart = (name) => {
    const started = Date.now();
    return {
      finish(ok, extra = {}) {
        const row = {
          step: name,
          ok,
          elapsedMs: Date.now() - started,
          ...extra,
        };
        steps.push(row);
        diagnostics.push(
          `${name}: ok=${String(ok)} elapsedMs=${row.elapsedMs}${
            extra.detail ? ` detail=${compact(String(extra.detail))}` : ""
          }`,
        );
        return row;
      },
    };
  };

  // 0) Sidecar-down probe (expected failure category; must not 200)
  {
    const timed = stepStart("failure_sidecar_down");
    try {
      await postJson(
        "/resource/search",
        { workspace_id: "unused", query: "x", top_k: 1 },
        { baseUrl: deadSidecarUrl, timeoutMs: 2500 },
      );
      timed.finish(false, { detail: "dead sidecar unexpectedly answered" });
      return failure({
        step: "failure_sidecar_down",
        category: "sidecar_down_not_detected",
        detail: `Expected connection failure against ${deadSidecarUrl}, but the request completed.`,
        diagnostics,
      });
    } catch (error) {
      const message = compact(String(error?.cause?.code || error?.code || error?.message || error));
      const looksDown =
        /ECONNREFUSED|ENOTFOUND|EHOSTUNREACH|fetch failed|aborted|AbortError|network/i.test(
          message,
        ) || error?.name === "AbortError";
      if (!looksDown) {
        timed.finish(false, { detail: message });
        return failure({
          step: "failure_sidecar_down",
          category: "sidecar_down_unexpected_error",
          detail: `Dead-sidecar probe failed with unexpected error: ${redactSecrets(message)}`,
          diagnostics,
        });
      }
      failureCategories.sidecar_down = {
        ok: true,
        category: "sidecar_down",
        detail: redactSecrets(message),
      };
      timed.finish(true, { category: "sidecar_down", detail: message });
    }
  }

  // 1) Provider capability probe (needed for Coach handoff / tools)
  {
    const timed = stepStart("provider_test");
    const capabilityTest = await postJson("/provider/test", {
      provider: providerPayload(),
      api_key: providerApiKey,
      response_language: responseLanguage,
      probe_message: "Reply with one short sentence confirming the coach connection.",
    });
    if (!capabilityTest.response.ok || capabilityTest.json?.ok !== true) {
      timed.finish(false, { status: capabilityTest.response.status });
      return failure({
        step: "provider_test",
        category: "provider_capability_test_failed",
        detail: `Provider capability test failed with HTTP ${capabilityTest.response.status}.`,
        diagnostics,
        status: capabilityTest.response.status,
      });
    }
    const toolsReady = Boolean(
      capabilityTest.json?.tools_ready ?? capabilityTest.json?.toolsReady,
    );
    timed.finish(true, { toolsReady });
    if (!skipCoach && !toolsReady) {
      return failure({
        step: "provider_test",
        category: "tools_not_verified",
        detail:
          "Coach handoff requires tools_ready from POST /provider/test. Re-run capability verification.",
        diagnostics,
      });
    }
  }

  const fixture = await createFixture();
  try {
    const workspaceId = `resources-smoke-${Date.now()}`;
    lastWorkspaceId = workspaceId;

    // 2) Session start
    let sessionId = "";
    {
      const timed = stepStart("session_start");
      const sessionStart = await postJson("/session/start", {
        workspace_id: workspaceId,
        workspace_name: "Resources smoke lab",
        workspace_path: fixture.tempDir,
        profile: {
          long_term_goal: "Keep Resources load + Coach handoff honest under live NewAPI.",
          weekly_hours: 4,
          teaching_style: "guided",
          answer_policy: "coach-first",
        },
      });
      if (!sessionStart.response.ok || !sessionStart.json?.session_id) {
        timed.finish(false, { status: sessionStart.response.status });
        return failure({
          step: "session_start",
          category: "session_start_failed",
          detail: `Session start failed with HTTP ${sessionStart.response.status}.`,
          diagnostics,
          status: sessionStart.response.status,
          workspaceId,
        });
      }
      sessionId = compact(sessionStart.json.session_id);
      lastSessionId = sessionId;
      timed.finish(true, { sessionId });
    }

    // 3) Happy path: upload → index → FTS search
    let resourceId = "";
    const resourceName = "coach-notes.md";
    {
      const timed = stepStart("resource_upload");
      const uploaded = await postJson("/resource/upload", {
        workspace_id: workspaceId,
        session_id: sessionId,
        kind: "markdown",
        name: resourceName,
        source: `inline://${resourceName}`,
        content: fixture.noteContent,
        content_encoding: "utf-8",
        tags: ["resources-smoke", "live"],
      });
      if (!uploaded.response.ok || !uploaded.json?.id) {
        timed.finish(false, { status: uploaded.response.status });
        return failure({
          step: "resource_upload",
          category: "resource_upload_failed",
          detail: `Resource upload failed with HTTP ${uploaded.response.status}.`,
          diagnostics,
          status: uploaded.response.status,
          sessionId,
          workspaceId,
        });
      }
      resourceId = compact(uploaded.json.id);
      timed.finish(true, { resourceId, indexStatus: uploaded.json.index_status });
    }

    {
      const timed = stepStart("resource_index");
      const indexed = await postJson("/resource/index", {
        workspace_id: workspaceId,
        session_id: sessionId,
        resource_id: resourceId,
        enable_network: false,
      });
      if (!indexed.response.ok || !indexed.json) {
        timed.finish(false, { status: indexed.response.status });
        return failure({
          step: "resource_index",
          category: "resource_index_failed",
          detail: `Resource index failed with HTTP ${indexed.response.status}.`,
          diagnostics,
          status: indexed.response.status,
          sessionId,
          workspaceId,
        });
      }
      const indexStatus = compact(indexed.json.index_status || indexed.json.indexStatus);
      if (indexStatus !== "indexed") {
        timed.finish(false, { indexStatus });
        return failure({
          step: "resource_index",
          category: "resource_not_indexed",
          detail: `Expected index_status=indexed, got ${indexStatus || "(missing)"}.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      timed.finish(true, {
        resourceId,
        indexStatus,
        trustState: compact(indexed.json.trust_state || indexed.json.trustState),
      });
    }

    {
      const timed = stepStart("resource_fts_search");
      const searched = await postJson("/resource/search", {
        workspace_id: workspaceId,
        session_id: sessionId,
        query: MARKER,
        top_k: 5,
      });
      if (!searched.response.ok || !searched.json) {
        timed.finish(false, { status: searched.response.status });
        return failure({
          step: "resource_fts_search",
          category: "resource_search_failed",
          detail: `FTS search failed with HTTP ${searched.response.status}.`,
          diagnostics,
          status: searched.response.status,
          sessionId,
          workspaceId,
        });
      }
      const total = Number(searched.json.total || 0);
      const ranking = compact(
        searched.json.ranking_strategy || searched.json.rankingStrategy,
      );
      const hits = Array.isArray(searched.json.hits)
        ? searched.json.hits
        : Array.isArray(searched.json.results)
          ? searched.json.results
          : [];
      const matched = hits.some(
        (hit) =>
          compact(hit.resource_id || hit.resourceId) === resourceId ||
          compact(hit.title || hit.name) === resourceName,
      );
      if (total < 1 || !matched) {
        timed.finish(false, { total, ranking, matched });
        return failure({
          step: "resource_fts_search",
          category: "fts_missed_indexed_resource",
          detail: `FTS search did not return uploaded resource ${resourceId} (total=${total}, ranking=${ranking || "(none)"}).`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      if (ranking && ranking !== "lexical_first" && ranking !== "metadata_only") {
        // Accept lexical_first (FTS5) as the primary path; metadata_only is a degraded but honest mode.
        timed.finish(false, { ranking });
        return failure({
          step: "resource_fts_search",
          category: "unexpected_ranking_strategy",
          detail: `Unexpected ranking_strategy=${ranking}.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      timed.finish(true, { total, ranking: ranking || "lexical_first", resourceId });
    }

    // 4) Honest failure: bad_file (empty content → index failed / no_content)
    {
      const timed = stepStart("failure_bad_file");
      const uploaded = await postJson("/resource/upload", {
        workspace_id: workspaceId,
        session_id: sessionId,
        kind: "markdown",
        name: "empty-bad.md",
        source: "inline://empty-bad.md",
        content: "",
        content_encoding: "utf-8",
        tags: ["resources-smoke", "bad-file"],
      });
      if (!uploaded.response.ok || !uploaded.json?.id) {
        timed.finish(false, { status: uploaded.response.status });
        return failure({
          step: "failure_bad_file",
          category: "bad_file_upload_unexpected",
          detail: `Empty bad-file upload failed with HTTP ${uploaded.response.status}.`,
          diagnostics,
          status: uploaded.response.status,
          sessionId,
          workspaceId,
        });
      }
      const badId = compact(uploaded.json.id);
      const indexed = await postJson("/resource/index", {
        workspace_id: workspaceId,
        session_id: sessionId,
        resource_id: badId,
        enable_network: false,
      });
      if (!indexed.response.ok || !indexed.json) {
        timed.finish(false, { status: indexed.response.status });
        return failure({
          step: "failure_bad_file",
          category: "bad_file_not_classified",
          detail: `Expected HTTP 200 with failed index for empty file, got HTTP ${indexed.response.status}.`,
          diagnostics,
          status: indexed.response.status,
          sessionId,
          workspaceId,
        });
      }
      const indexStatus = compact(indexed.json.index_status || indexed.json.indexStatus);
      const flags = Array.isArray(indexed.json.quality_flags)
        ? indexed.json.quality_flags
        : Array.isArray(indexed.json.qualityFlags)
          ? indexed.json.qualityFlags
          : [];
      if (indexStatus !== "failed" || !flags.includes("no_content")) {
        timed.finish(false, { indexStatus, flags });
        return failure({
          step: "failure_bad_file",
          category: "bad_file_not_classified",
          detail: `Expected index_status=failed + no_content, got index_status=${indexStatus || "(missing)"} flags=${flags.join(",") || "(none)"}.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      failureCategories.bad_file = {
        ok: true,
        category: "bad_file",
        indexStatus,
        qualityFlags: flags,
        resourceId: badId,
      };
      timed.finish(true, { category: "bad_file", resourceId: badId });
    }

    // 5) Honest failure: missing (path does not exist → 400)
    {
      const timed = stepStart("failure_missing");
      const missingPath = path.join(fixture.tempDir, "does-not-exist-resource.md");
      const uploaded = await postJson("/resource/upload", {
        workspace_id: workspaceId,
        session_id: sessionId,
        kind: "markdown",
        name: "does-not-exist-resource.md",
        source: missingPath,
      });
      const detail = compact(
        typeof uploaded.json?.detail === "string"
          ? uploaded.json.detail
          : JSON.stringify(uploaded.json?.detail || uploaded.text || ""),
      );
      const looksMissing =
        uploaded.response.status === 400 &&
        /does not exist|not found|missing/i.test(detail);
      if (!looksMissing) {
        // Also accept missing resource_id on index as the missing category.
        const missIndex = await postJson("/resource/index", {
          workspace_id: workspaceId,
          session_id: sessionId,
          resource_id: "resource-does-not-exist-xyz",
          enable_network: false,
        });
        const missDetail = compact(
          typeof missIndex.json?.detail === "string"
            ? missIndex.json.detail
            : JSON.stringify(missIndex.json?.detail || missIndex.text || ""),
        );
        if (missIndex.response.status !== 404) {
          timed.finish(false, {
            uploadStatus: uploaded.response.status,
            indexStatus: missIndex.response.status,
          });
          return failure({
            step: "failure_missing",
            category: "missing_not_classified",
            detail: `Expected missing-path 400 or missing-id 404; got upload=${uploaded.response.status} index=${missIndex.response.status}.`,
            diagnostics,
            sessionId,
            workspaceId,
          });
        }
        failureCategories.missing = {
          ok: true,
          category: "missing",
          status: 404,
          detail: redactSecrets(missDetail),
        };
        timed.finish(true, { category: "missing", status: 404 });
      } else {
        failureCategories.missing = {
          ok: true,
          category: "missing",
          status: 400,
          detail: redactSecrets(detail),
        };
        timed.finish(true, { category: "missing", status: 400 });
      }
    }

    // 6) Coach handoff with same session_id
    let coachEvidence = null;
    if (!skipCoach) {
      const timed = stepStart("coach_handoff");
      const prompt =
        responseLanguage.toLowerCase().startsWith("zh")
          ? `我刚导入了 ${resourceName}。请基于已索引资源回答：文档里的标记词是什么？并说明 Resources 视图不能捏造缺失文件。`
          : `I just indexed ${resourceName}. Using the indexed Resources library, what unique marker token appears in that document, and remind me that Resources must not invent missing files.`;
      const message = await postJson(
        "/session/message",
        {
          session_id: sessionId,
          workspace_id: workspaceId,
          message: prompt,
          response_language: responseLanguage,
          provider: providerPayload(),
          api_key: providerApiKey,
          use_agent_loop: true,
        },
        { timeoutMs: 300000 },
      );
      if (!message.response.ok || !message.json) {
        timed.finish(false, { status: message.response.status });
        return failure({
          step: "coach_handoff",
          category: "coach_handoff_failed",
          detail: `Coach /session/message failed with HTTP ${message.response.status}.`,
          diagnostics,
          status: message.response.status,
          sessionId,
          workspaceId,
        });
      }
      const returnedSession = compact(
        message.json.session_id || message.json.sessionId || sessionId,
      );
      if (returnedSession && returnedSession !== sessionId) {
        timed.finish(false, { returnedSession });
        return failure({
          step: "coach_handoff",
          category: "session_id_desync",
          detail: `Coach response session_id ${returnedSession} != ${sessionId}.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      coachEvidence = collectCoachEvidence(message.json, resourceName);
      const grounded =
        coachEvidence.searchCalls > 0 ||
        coachEvidence.autoResourceLookup ||
        coachEvidence.toolNames.includes("search_resources");
      if (!grounded) {
        timed.finish(false, coachEvidence);
        return failure({
          step: "coach_handoff",
          category: "coach_missing_resource_grounding",
          detail: `Coach handoff did not show resource grounding evidence: ${JSON.stringify(coachEvidence)}.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      if (!coachEvidence.replyPresent) {
        timed.finish(false, coachEvidence);
        return failure({
          step: "coach_handoff",
          category: "coach_missing_reply",
          detail: "Coach handoff returned no visible reply.",
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      timed.finish(true, {
        sessionId,
        searchCalls: coachEvidence.searchCalls,
        matchedExpectedTitle: coachEvidence.matchedExpectedTitle,
      });
    } else {
      diagnostics.push("coach_handoff: skipped via TRAINER_RESOURCES_SMOKE_SKIP_COACH=1");
    }

    const report = {
      ok: true,
      checks: {
        resource_load: "passed",
        fts_search: "passed",
        failure_bad_file: "passed",
        failure_missing: "passed",
        failure_sidecar_down: "passed",
        coach_handoff: skipCoach ? "skipped" : "passed",
        session_continuity: "passed",
      },
      failureCategories,
      steps,
      diagnostics,
      providerProtocol,
      responseLanguage,
      providerModel,
      elapsedMs: elapsedMs(),
      sessionContinuity: {
        sessionId,
        workspaceId,
        preserved: true,
      },
      resourceId,
      coachEvidence,
    };
    if (JSON.stringify(report).includes(providerApiKey) || /sk-[A-Za-z0-9]{8,}/.test(JSON.stringify(report))) {
      return failure({
        step: "security",
        category: "api_key_leak",
        detail: "Smoke report attempted to emit a raw API key; refusing to print.",
        diagnostics,
        sessionId,
        workspaceId,
      });
    }
    await success(report);
  } finally {
    await fs.rm(fixture.tempDir, { recursive: true, force: true }).catch(() => {});
  }
}

main().catch(async (error) => {
  if (String(error?.message || error) === "__resources_smoke_failed__") {
    return;
  }
  const message = redactSecrets(compact(String(error?.stack || error?.message || error)));
  await emitJson(process.stderr, {
    ok: false,
    step: "runtime",
    category: "smoke_crashed",
    detail: message,
    elapsedMs: elapsedMs(),
    sessionContinuity: {
      sessionId: lastSessionId || null,
      workspaceId: lastWorkspaceId || null,
      preserved: Boolean(lastSessionId),
    },
  });
  process.exitCode = 1;
});
