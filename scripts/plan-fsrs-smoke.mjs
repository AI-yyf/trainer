import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";

/**
 * Live Plan → Training-card → FSRS main-path smoke.
 * Steps: provider/test → session/start → /plan/generate → /training/generate-card
 * → /evaluate/current-file → memory summary asserts plan advance + FSRS write-back
 * + session_id continuity. Prefers NewAPI via TRAINER_PROVIDER_SMOKE_* / PLAN_FSRS_*.
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
  process.env.TRAINER_PLAN_FSRS_SMOKE_SIDECAR_URL ??
    process.env.TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL ??
    defaultSidecarUrl
)
  .trim()
  .replace(/\/+$/, "");
const providerBaseUrl = (
  process.env.TRAINER_PLAN_FSRS_SMOKE_PROVIDER_BASE_URL ??
    process.env.TRAINER_PROVIDER_SMOKE_BASE_URL ??
    ""
)
  .trim()
  .replace(/\/+$/, "");
const providerApiKey = (
  process.env.TRAINER_PLAN_FSRS_SMOKE_PROVIDER_API_KEY ??
    process.env.TRAINER_PROVIDER_SMOKE_API_KEY ??
    ""
).trim();
const providerModel = (
  process.env.TRAINER_PLAN_FSRS_SMOKE_PROVIDER_MODEL ??
    process.env.TRAINER_PROVIDER_SMOKE_MODEL ??
    defaultModel
).trim();
const providerProtocol = normalizeProtocol(
  (
    process.env.TRAINER_PLAN_FSRS_SMOKE_PROVIDER_PROTOCOL ??
      process.env.TRAINER_PROVIDER_SMOKE_PROTOCOL ??
      defaultProtocol
  ).trim(),
);
const responseLanguage = (
  process.env.TRAINER_PLAN_FSRS_SMOKE_RESPONSE_LANGUAGE ?? defaultResponseLanguage
).trim();
const smokeStartedAt = Date.now();
let lastSessionId = "";
let lastWorkspaceId = "";

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

function recordValue(record, snake, camel) {
  if (!record || typeof record !== "object") {
    return undefined;
  }
  return record[snake] ?? record[camel];
}

function workspaceRecord(workspace, snake, camel) {
  if (!workspace || typeof workspace !== "object") {
    return {};
  }
  const value = workspace[snake] ?? workspace[camel];
  return value && typeof value === "object" ? value : {};
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
  throw new Error("__plan_fsrs_smoke_failed__");
}

async function success(report) {
  await emitJson(process.stdout, report);
  process.exitCode = 0;
}

async function postJson(route, payload) {
  const response = await fetch(`${sidecarUrl}${route}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
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

async function getJson(route) {
  const response = await fetch(`${sidecarUrl}${route}`);
  const text = await response.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = undefined;
  }
  return { response, text, json };
}

function providerPayload() {
  const payload = {
    name: "trainer-plan-fsrs-smoke",
    baseUrl: providerBaseUrl,
    apiKeyRef: "trainer.plan-fsrs-smoke",
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
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "trainer-plan-fsrs-smoke-"));
  const practicePath = path.join(tempDir, "practice.py");
  await fs.writeFile(
    practicePath,
    "def require_fresh(token):\n"
      + "    if not token:\n"
      + "        raise ValueError('expired')\n"
      + "    return token\n"
      + "\n"
      + "\n"
      + "def test_require_fresh_rejects_empty() -> None:\n"
      + "    try:\n"
      + "        require_fresh('')\n"
      + "    except ValueError:\n"
      + "        pass\n"
      + "    else:\n"
      + "        raise AssertionError('empty token must fail')\n"
      + "    assert require_fresh('tok') == 'tok'\n",
    "utf8",
  );
  return {
    tempDir,
    practicePath,
    practiceContent: await fs.readFile(practicePath, "utf8"),
  };
}

async function main() {
  if (!providerBaseUrl) {
    return failure({
      step: "config",
      category: "missing_provider_base_url",
      detail:
        "Set TRAINER_PLAN_FSRS_SMOKE_PROVIDER_BASE_URL or TRAINER_PROVIDER_SMOKE_BASE_URL before running the plan-fsrs smoke.",
      diagnostics: [],
    });
  }
  if (!providerApiKey) {
    return failure({
      step: "config",
      category: "missing_provider_api_key",
      detail:
        "Set TRAINER_PLAN_FSRS_SMOKE_PROVIDER_API_KEY or TRAINER_PROVIDER_SMOKE_API_KEY before running the plan-fsrs smoke.",
      diagnostics: [],
    });
  }

  const diagnostics = [];
  const steps = [];

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
            extra.detail ? ` detail=${compact(extra.detail)}` : ""
          }`,
        );
        return row;
      },
    };
  };

  // 1) Provider capability probe (chat; tools optional for this path)
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
  }

  const fixture = await createFixture();
  try {
    const workspaceId = `plan-fsrs-smoke-${Date.now()}`;
    lastWorkspaceId = workspaceId;

    // 2) Session start
    let sessionId = "";
    {
      const timed = stepStart("session_start");
      const sessionStart = await postJson("/session/start", {
        workspace_id: workspaceId,
        workspace_name: "Plan FSRS smoke lab",
        workspace_path: fixture.tempDir,
        profile: {
          long_term_goal: "Ship fail-closed token expiry under a live plan.",
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

    // 3) Explicit plan generate — bind live plan_id + stage/step
    let planId = "";
    let stepBefore = "";
    let stageBefore = "";
    {
      const timed = stepStart("plan_generate");
      const generated = await postJson("/plan/generate", {
        session_id: sessionId,
        workspace_id: workspaceId,
        objectives: ["Ship fail-closed token refresh auth"],
        response_language: responseLanguage,
        provider: providerPayload(),
        api_key: providerApiKey,
      });
      if (!generated.response.ok || !generated.json) {
        timed.finish(false, { status: generated.response.status });
        return failure({
          step: "plan_generate",
          category: "plan_generate_failed",
          detail: `Plan generate failed with HTTP ${generated.response.status}.`,
          diagnostics,
          status: generated.response.status,
          sessionId,
          workspaceId,
        });
      }
      const plan = generated.json.plan || generated.json;
      planId = compact(plan?.id ?? plan?.plan_id ?? plan?.planId);
      stepBefore = compact(plan?.current_step ?? plan?.currentStep);
      stageBefore = compact(plan?.current_stage_id ?? plan?.currentStageId);
      const liveRuntime = workspaceRecord(
        (generated.json.memory || {}).workspace,
        "latest_plan_runtime",
        "latestPlanRuntime",
      );
      const runtimePlanId = compact(
        recordValue(liveRuntime, "plan_id", "planId"),
      );
      if (!planId || !stepBefore) {
        timed.finish(false, { planId, stepBefore });
        return failure({
          step: "plan_generate",
          category: "plan_missing_identity",
          detail: "Plan generate did not return a durable plan_id and current_step.",
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      if (runtimePlanId && runtimePlanId !== planId) {
        timed.finish(false, { planId, runtimePlanId });
        return failure({
          step: "plan_generate",
          category: "plan_runtime_desync",
          detail: `Runtime plan_id ${runtimePlanId} != formal plan_id ${planId}.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      timed.finish(true, { planId, stepBefore, stageBefore, runtimePlanId: runtimePlanId || planId });
    }

    // 4) Explicit training card mint (NewAPI)
    let cardId = "";
    let cardTitle = "";
    {
      const timed = stepStart("card_mint");
      const generated = await postJson("/training/generate-card", {
        workspace_id: workspaceId,
        session_id: sessionId,
        source: "conversation_gap",
        card_type: "practice",
        focus_area: "token expiry",
        target_skill: "auth expiry",
        context_hint:
          "Create one practice card for fail-closed token expiry under the live plan.",
        why_now: "Live plan is bound; mint one practice card before verify.",
        response_language: responseLanguage,
        provider: providerPayload(),
        api_key: providerApiKey,
      });
      if (!generated.response.ok || !generated.json) {
        timed.finish(false, { status: generated.response.status });
        return failure({
          step: "card_mint",
          category: "card_generation_request_failed",
          detail: `Explicit card generation failed with HTTP ${generated.response.status}.`,
          diagnostics,
          status: generated.response.status,
          sessionId,
          workspaceId,
        });
      }
      const card = generated.json.card || {};
      cardId = compact(card.card_id ?? card.cardId);
      cardTitle = compact(card.title);
      const routing = generated.json.active_routing || generated.json.activeRouting || {};
      const selected = routing.selected_card || routing.selectedCard || {};
      const selectedId = compact(
        routing.selected_card_id
          ?? routing.selectedCardId
          ?? selected.card_id
          ?? selected.cardId,
      );
      const cardType = compact(selected.card_type ?? selected.type ?? card.card_type ?? card.type);
      if (!cardId || !cardTitle) {
        timed.finish(false);
        return failure({
          step: "card_mint",
          category: "missing_training_card",
          detail: "Explicit card generation did not provide a durable card id and title.",
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      if (selectedId !== cardId) {
        timed.finish(false, { cardId, selectedId });
        return failure({
          step: "card_mint",
          category: "card_not_live_selected",
          detail: `Minted card ${cardId} was not live-selected (selected=${selectedId || "(missing)"}).`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      if (cardType && cardType !== "practice") {
        timed.finish(false, { cardType });
        return failure({
          step: "card_mint",
          category: "unexpected_training_card_type",
          detail: `Expected practice card, received ${cardType}.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      timed.finish(true, { cardId, cardTitle, cardType: cardType || "practice" });
    }

    // 5) Evaluate current-file under training card → plan advance + FSRS
    {
      const timed = stepStart("evaluate_verify");
      const evaluation = await postJson("/evaluate/current-file", {
        session_id: sessionId,
        workspace_id: workspaceId,
        file_path: fixture.practicePath,
        language_id: "python",
        content: fixture.practiceContent,
        diagnostics: [],
        evaluation_source: "training",
        training_card_id: cardId,
        training_card_title: cardTitle,
        expected_symbols: ["require_fresh"],
        acceptance_criteria: ["Implement require_fresh for fail-closed expiry."],
      });
      if (!evaluation.response.ok || !evaluation.json) {
        timed.finish(false, { status: evaluation.response.status });
        return failure({
          step: "evaluate_verify",
          category: "evaluation_request_failed",
          detail: `Current-file evaluation failed with HTTP ${evaluation.response.status}.`,
          diagnostics,
          status: evaluation.response.status,
          sessionId,
          workspaceId,
        });
      }
      if (evaluation.json.passed !== true) {
        timed.finish(false, { passed: false });
        return failure({
          step: "evaluate_verify",
          category: "unexpected_evaluation_result",
          detail: "Expected evaluation passed=true for the practice fixture.",
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      timed.finish(true, { passed: true });
    }

    // 6) Memory summary — plan stage change + FSRS write-back + session continuity
    let stepAfter = "";
    let stageAfter = "";
    let fsrsReps = 0;
    let fsrsState = "";
    let advanceStamp = null;
    {
      const timed = stepStart("memory_assert");
      const summary = await getJson(
        `/memory/summary?session_id=${encodeURIComponent(sessionId)}&workspace_id=${encodeURIComponent(workspaceId)}`,
      );
      if (!summary.response.ok || !summary.json?.memory) {
        timed.finish(false, { status: summary.response.status });
        return failure({
          step: "memory_assert",
          category: "summary_failed",
          detail: `Memory summary failed with HTTP ${summary.response.status}.`,
          diagnostics,
          status: summary.response.status,
          sessionId,
          workspaceId,
        });
      }

      const memory = summary.json.memory;
      const workspace = memory.workspace || {};
      const planRuntime = workspaceRecord(workspace, "latest_plan_runtime", "latestPlanRuntime");
      const runtimePlanId = compact(recordValue(planRuntime, "plan_id", "planId"));
      stepAfter = compact(recordValue(planRuntime, "current_step", "currentStep"));
      stageAfter = compact(
        recordValue(planRuntime, "current_stage_id", "currentStageId"),
      );

      const planRuntimeStatus =
        summary.json.plan_runtime_status
        || summary.json.planRuntimeStatus
        || memory.plan_runtime_status
        || memory.planRuntimeStatus
        || {};
      advanceStamp =
        planRuntimeStatus.verify_plan_advance
        || planRuntimeStatus.verifyPlanAdvance
        || null;

      const fsrsStates =
        workspace.latest_training_fsrs_states
        || workspace.latestTrainingFsrsStates
        || {};
      const cardFsrs = fsrsStates[cardId] || {};
      fsrsReps = Number(cardFsrs.reps || 0);
      fsrsState = compact(cardFsrs.state);

      const sessionPreserved = Boolean(sessionId) && runtimePlanId === planId;
      const planAdvanced =
        Boolean(advanceStamp?.advanced) ||
        (stepAfter && stepAfter !== stepBefore) ||
        (stageAfter && stageAfter !== stageBefore);
      const fsrsWritten = Boolean(cardId && cardId in fsrsStates && fsrsReps >= 1);

      diagnostics.push(
        `memory_assert: session_id=${sessionId} plan_id=${planId} runtime_plan_id=${runtimePlanId || "(missing)"} step_before=${stepBefore} step_after=${stepAfter || "(missing)"} stage_before=${stageBefore || "(none)"} stage_after=${stageAfter || "(none)"} advance=${String(Boolean(advanceStamp?.advanced))} fsrs_reps=${fsrsReps} fsrs_state=${fsrsState || "(missing)"}`,
      );

      if (!sessionPreserved) {
        timed.finish(false, { runtimePlanId, planId });
        return failure({
          step: "memory_assert",
          category: "session_continuity_failed",
          detail: `Expected runtime plan_id=${planId} under session ${sessionId}, got ${runtimePlanId || "(missing)"}.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      if (!planAdvanced) {
        timed.finish(false, { stepBefore, stepAfter, stageBefore, stageAfter });
        return failure({
          step: "plan_stage_change",
          category: "plan_did_not_advance",
          detail:
            "Evaluator-acked verify did not advance formal/runtime plan step/stage or stamp verify_plan_advance.",
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      if (!fsrsWritten) {
        timed.finish(false, { fsrsKeys: Object.keys(fsrsStates) });
        return failure({
          step: "fsrs_writeback",
          category: "fsrs_schedule_missing",
          detail: `Expected latest_training_fsrs_states[${cardId}] with reps>=1 after verify.`,
          diagnostics,
          sessionId,
          workspaceId,
        });
      }
      timed.finish(true, {
        planAdvanced: true,
        fsrsWritten: true,
        fsrsReps,
        fsrsState,
        advance: Boolean(advanceStamp?.advanced),
      });
    }

    return success({
      ok: true,
      providerProtocol,
      responseLanguage,
      providerModel,
      elapsedMs: elapsedMs(),
      sessionContinuity: {
        sessionId,
        workspaceId,
        planId,
        cardId,
        preserved: true,
      },
      checks: {
        provider_test: "passed",
        session_start: "passed",
        plan_generate: "passed",
        card_mint: "passed",
        evaluate_verify: "passed",
        plan_stage_change: "passed",
        fsrs_writeback: "passed",
        session_continuity: "passed",
      },
      plan: {
        planId,
        stepBefore,
        stepAfter,
        stageBefore,
        stageAfter,
        advance: advanceStamp,
      },
      fsrs: {
        cardId,
        reps: fsrsReps,
        state: fsrsState,
      },
      steps,
      diagnostics,
    });
  } finally {
    await fs.rm(fixture.tempDir, { recursive: true, force: true });
  }
}

main().catch(async (error) => {
  if (error instanceof Error && error.message === "__plan_fsrs_smoke_failed__") {
    return;
  }
  await failure({
    step: "runtime",
    category: "unexpected_error",
    detail: error instanceof Error ? error.message : String(error),
    diagnostics: [],
  });
});
