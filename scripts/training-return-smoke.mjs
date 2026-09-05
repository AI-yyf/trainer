import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";

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
  process.env.TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL ?? defaultSidecarUrl
)
  .trim()
  .replace(/\/+$/, "");
const providerBaseUrl = (
  process.env.TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_BASE_URL ?? ""
)
  .trim()
  .replace(/\/+$/, "");
const providerApiKey = (
  process.env.TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_API_KEY ?? ""
).trim();
const providerModel = (
  process.env.TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_MODEL ?? defaultModel
).trim();
const providerProtocol = normalizeProtocol(
  (process.env.TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_PROTOCOL ?? defaultProtocol).trim(),
);
const responseLanguage = (
  process.env.TRAINER_TRAINING_RETURN_SMOKE_RESPONSE_LANGUAGE ?? defaultResponseLanguage
).trim();

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

function recordValue(record, snakeKey, camelKey) {
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    return undefined;
  }
  return record[snakeKey] ?? record[camelKey];
}

function workspaceRecord(workspace, snakeKey, camelKey) {
  const value = recordValue(workspace, snakeKey, camelKey);
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function emitJson(stream, payload) {
  return new Promise((resolve, reject) => {
    stream.write(`${JSON.stringify(payload, null, 2)}\n`, (error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });
}

async function failure({ step, category, diagnostics, status }) {
  const report = {
    ok: false,
    step,
    category,
    error: "Smoke check failed. See step and category.",
    diagnostics,
    status,
    responseBodyRedacted: typeof status === "number",
    providerProtocol,
    responseLanguage,
    providerModel,
  };
  await emitJson(process.stderr, report);
  process.exitCode = 1;
  throw new Error("__training_return_smoke_failed__");
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
    name: "trainer-training-return-smoke",
    baseUrl: providerBaseUrl,
    apiKeyRef: "trainer.training-return-smoke",
    model: providerModel,
    protocol: providerProtocol,
  };
  const requestDefaults = providerRequestDefaults();
  if (Object.keys(requestDefaults).length > 0) {
    payload.requestDefaults = requestDefaults;
  }
  return payload;
}

function trainingTurnPayload(sessionId, workspaceId) {
  return {
    session_id: sessionId,
    workspace_id: workspaceId,
    intent: "coach",
    message:
      "Please create a learn-first practice card for VS Code Remote SSH, then let me practice and verify one tiny move.",
    response_language: responseLanguage,
    answer_mode: "coach-first",
    use_agent_loop: true,
    provider: providerPayload(),
    api_key: providerApiKey,
  };
}

function trainingCardPayload(workspaceId) {
  return {
    workspace_id: workspaceId,
    source: "conversation_gap",
    card_type: "practice",
    focus_area: "VS Code remote workspace",
    target_skill: "name the remote boundary",
    context_hint:
      "Create one learn-first practice card for VS Code Remote SSH, then verify one tiny move.",
    why_now: "The learner asked for one explicit practice card before verification.",
    response_language: responseLanguage,
    provider: providerPayload(),
    api_key: providerApiKey,
  };
}

async function createFixture() {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "trainer-training-return-smoke-"));
  const practicePath = path.join(tempDir, "practice.py");
  // Current-file evaluation runs pytest against the submitted file in an
  // isolated sandbox, so keep the verifier in that file to exercise the
  // required dynamic-check pass path.
  await fs.writeFile(
    practicePath,
    "def ok() -> bool:\n    return True\n\n\ndef test_ok() -> None:\n    assert ok() is True\n",
    "utf8",
  );
  return {
    tempDir,
    practicePath,
    practiceContent: await fs.readFile(practicePath, "utf8"),
  };
}

function assertPracticeRouting(payload, step, diagnostics) {
  const routing = payload?.active_routing ?? payload?.activeRouting;
  const selectedCard = routing?.selected_card ?? routing?.selectedCard;
  const selectedCardType = compact(selectedCard?.card_type ?? selectedCard?.type);
  const scenarioPack = compact(selectedCard?.scenario_pack ?? selectedCard?.scenarioPack);
  diagnostics.push(
    `${step}: training_card_is_practice=${String(selectedCardType === "practice")} training_pack_matches_expected=${String(scenarioPack === "remote_workspace")}`,
  );
  if (selectedCardType !== "practice") {
    return failure({
      step,
      category: "unexpected_training_card_type",
      detail: `Expected practice card, received ${selectedCardType || "(missing)"}.`,
      diagnostics,
      preview: JSON.stringify(routing),
    });
  }
  if (scenarioPack !== "remote_workspace") {
    return failure({
      step,
      category: "unexpected_training_scenario_pack",
      detail: `Expected remote_workspace scenario pack, received ${scenarioPack || "(missing)"}.`,
      diagnostics,
      preview: JSON.stringify(routing),
    });
  }
}

function assertPracticeTurn(payload, step, diagnostics) {
  const scenario = compact(payload?.coach_turn?.scenario);
  diagnostics.push(`${step}: scenario_matches_expected=${String(scenario === "remote_workspace")}`);
  if (scenario !== "remote_workspace") {
    return failure({
      step,
      category: "unexpected_scenario",
      detail: `Expected remote_workspace, received ${scenario || "(missing)"}.`,
      diagnostics,
      preview: compact(payload?.reply?.content),
    });
  }
  const routing = payload?.snapshot?.memory?.active_training_card_routing;
  diagnostics.push(`${step}: chat_training_routing_absent=${String(!routing)}`);
  if (routing) {
    return failure({
      step,
      category: "chat_minted_training_card",
      detail: "Composer chat returned active training-card routing; use the explicit generate-card binder.",
      diagnostics,
    });
  }
}

async function runProbe({ name, diagnosticsInput, expectPassed, fixture, diagnostics }) {
  const workspaceId = `training-return-smoke-${name}-${Date.now()}`;
  const sessionStart = await postJson("/session/start", {
    workspace_id: workspaceId,
    workspace_name: workspaceId,
    profile: {
      long_term_goal: `Verify live training return semantics (${name}).`,
      weekly_hours: 4,
      teaching_style: "guided",
      answer_policy: "coach-first",
    },
  });
  if (!sessionStart.response.ok || !sessionStart.json?.session_id) {
    return failure({
      step: `${name}_session_start`,
      category: "session_start_failed",
      detail: `Session start failed with HTTP ${sessionStart.response.status}.`,
      diagnostics,
      status: sessionStart.response.status,
      preview: compact(sessionStart.text),
    });
  }

  const sessionId = compact(sessionStart.json.session_id);
  diagnostics.push(`${name}_session_start: started=true`);

  const turn = await postJson("/turn", trainingTurnPayload(sessionId, workspaceId));
  if (!turn.response.ok || !turn.json) {
    return failure({
      step: `${name}_turn`,
      category: "turn_failed",
      detail: `Training turn failed with HTTP ${turn.response.status}.`,
      diagnostics,
      status: turn.response.status,
      preview: compact(turn.text),
    });
  }

  await assertPracticeTurn(turn.json, `${name}_turn`, diagnostics);

  const generated = await postJson(
    "/training/generate-card",
    trainingCardPayload(workspaceId),
  );
  if (!generated.response.ok || !generated.json) {
    return failure({
      step: `${name}_generate_card`,
      category: "card_generation_request_failed",
      detail: `Explicit card generation failed with HTTP ${generated.response.status}.`,
      diagnostics,
      status: generated.response.status,
    });
  }
  await assertPracticeRouting(generated.json, `${name}_generate_card`, diagnostics);
  const card = generated.json?.card;
  const trainingCardId = compact(card?.card_id ?? card?.cardId);
  const trainingCardTitle = compact(card?.title);
  if (!trainingCardId || !trainingCardTitle) {
      return failure({
        step: `${name}_generate_card`,
        category: "missing_training_card",
        detail: "Explicit card generation did not provide a durable card id and title.",
        diagnostics,
        preview: JSON.stringify(generated.json),
      });
  }

  const evaluation = await postJson("/evaluate/current-file", {
    session_id: sessionId,
    workspace_id: workspaceId,
    task_spec_id: `training-return-smoke-${name}`,
    file_path: fixture.practicePath,
    language_id: "python",
    content: fixture.practiceContent,
    diagnostics: diagnosticsInput,
    evaluation_source: "training",
    training_card_id: trainingCardId,
    training_card_title: trainingCardTitle,
    expected_symbols: ["ok"],
  });
  if (!evaluation.response.ok || !evaluation.json) {
    return failure({
      step: `${name}_evaluate`,
      category: "evaluation_request_failed",
      detail: `Current-file evaluation failed with HTTP ${evaluation.response.status}.`,
      diagnostics,
      status: evaluation.response.status,
      preview: compact(evaluation.text),
    });
  }
  diagnostics.push(`${name}_evaluate: passed=${String(Boolean(evaluation.json.passed))}`);
  if (Boolean(evaluation.json.passed) !== expectPassed) {
    return failure({
      step: `${name}_evaluate`,
      category: "unexpected_evaluation_result",
      detail: `Expected evaluation passed=${String(expectPassed)}, received ${String(Boolean(evaluation.json.passed))}.`,
      diagnostics,
      preview: JSON.stringify(evaluation.json),
    });
  }

  if (expectPassed) {
    const afterEvaluation = await getJson(
      `/memory/summary?session_id=${encodeURIComponent(sessionId)}`,
    );
    const workspace = afterEvaluation.json?.memory?.workspace;
    const handoff = workspaceRecord(workspace, "latest_training_handoff", "latestTrainingHandoff");
    const handoffId = compact(recordValue(handoff, "handoff_id", "handoffId"));
    if (!afterEvaluation.response.ok || !workspace || !handoffId) {
      return failure({
        step: `${name}_reflect`,
        category: "missing_handoff_after_verification",
        detail: "Successful verification did not produce a training handoff that can be reflected.",
        diagnostics,
        status: afterEvaluation.response.status,
      });
    }

    const reflection =
      compact(evaluation.json.reflection) ||
      "The evaluator verified the smallest practice result, so this evidence can return to Coach.";
    const reflected = await postJson("/training/reflect", {
      workspace_id: workspaceId,
      card_id: trainingCardId,
      handoff_id: handoffId,
      reflection,
    });
    if (!reflected.response.ok || !reflected.json?.workspace) {
      return failure({
        step: `${name}_reflect`,
        category: "reflection_request_failed",
        detail: `Training reflection failed with HTTP ${reflected.response.status}.`,
        diagnostics,
        status: reflected.response.status,
      });
    }

    const reflectedHandoff = workspaceRecord(
      reflected.json.workspace,
      "latest_training_handoff",
      "latestTrainingHandoff",
    );
    const reflectedHandoffId = compact(recordValue(reflectedHandoff, "handoff_id", "handoffId"));
    if (!reflectedHandoffId) {
      return failure({
        step: `${name}_return`,
        category: "missing_handoff_after_reflection",
        detail: "Training reflection did not preserve a handoff id for the explicit Return step.",
        diagnostics,
      });
    }

    const returned = await postJson("/training/return", {
      workspace_id: workspaceId,
      card_id: trainingCardId,
      handoff_id: reflectedHandoffId,
    });
    if (!returned.response.ok || !returned.json?.workspace) {
      return failure({
        step: `${name}_return`,
        category: "return_request_failed",
        detail: `Training return failed with HTTP ${returned.response.status}.`,
        diagnostics,
        status: returned.response.status,
      });
    }
    diagnostics.push(`${name}_reflect_return: completed=true`);
  }

  const summary = await getJson(
    `/memory/summary?session_id=${encodeURIComponent(sessionId)}`,
  );
  if (!summary.response.ok || !summary.json?.memory?.workspace) {
    return failure({
      step: `${name}_summary`,
      category: "summary_failed",
      detail: `Memory summary failed with HTTP ${summary.response.status}.`,
      diagnostics,
      status: summary.response.status,
      preview: compact(summary.text),
    });
  }
  const workspace = summary.json.memory.workspace;
  const handoff = workspaceRecord(workspace, "latest_training_handoff", "latestTrainingHandoff");
  const nextHop = workspaceRecord(workspace, "latest_training_next_hop", "latestTrainingNextHop");
  diagnostics.push(
    `${name}_summary: workspace_state_present=${String(Boolean(workspace.selected_card_status))} handoff_present=${String(Boolean(handoff.continue_in))} next_hop_present=${String(Boolean(nextHop.status))}`,
  );

  if (expectPassed) {
    const nextHopStatus = compact(recordValue(nextHop, "status", "status"));
    const selectedCardStatus = compact(recordValue(workspace, "selected_card_status", "selectedCardStatus"));
    if (selectedCardStatus !== "implemented") {
      return failure({
        step: `${name}_summary`,
        category: "pass_status_mismatch",
        detail: `Expected selected_card_status=implemented, received ${selectedCardStatus || "(missing)"}.`,
        diagnostics,
        preview: JSON.stringify(workspace),
      });
    }
    if (
      compact(recordValue(handoff, "continue_in", "continueIn")) !== "chat" ||
      compact(recordValue(handoff, "accepted_into", "acceptedInto")) !== "coach"
    ) {
      return failure({
        step: `${name}_summary`,
        category: "pass_handoff_mismatch",
        detail: "Successful practice verification did not return to Coach.",
        diagnostics,
        preview: JSON.stringify(handoff),
      });
    }
    if (
      compact(recordValue(nextHop, "continue_in", "continueIn")) !== "chat" ||
      compact(recordValue(nextHop, "accepted_into", "acceptedInto")) !== "coach" ||
      !["continued_in_chat", "accepted"].includes(nextHopStatus)
    ) {
      return failure({
        step: `${name}_summary`,
        category: "pass_next_hop_mismatch",
        detail: "Successful practice verification did not project the next hop back to Coach.",
        diagnostics,
        preview: JSON.stringify(nextHop),
      });
    }
    if (!compact(recordValue(workspace, "latest_learning_verified_result", "latestLearningVerifiedResult"))) {
      return failure({
        step: `${name}_summary`,
        category: "missing_verified_result",
        detail: "Successful practice verification did not persist a verified result summary.",
        diagnostics,
        preview: JSON.stringify(workspace),
      });
    }
  } else {
    const selectedCardStatus = compact(recordValue(workspace, "selected_card_status", "selectedCardStatus"));
    if (selectedCardStatus !== "blocked") {
      return failure({
        step: `${name}_summary`,
        category: "fail_status_mismatch",
        detail: `Expected selected_card_status=blocked after a blocked verification, received ${selectedCardStatus || "(missing)"}.`,
        diagnostics,
        preview: JSON.stringify(workspace),
      });
    }
    if (
      compact(recordValue(handoff, "continue_in", "continueIn")) !== "training" ||
      compact(recordValue(handoff, "accepted_into", "acceptedInto")) !== "training"
    ) {
      return failure({
        step: `${name}_summary`,
        category: "fail_handoff_mismatch",
        detail: "Blocked practice verification did not stay in Training.",
        diagnostics,
        preview: JSON.stringify(handoff),
      });
    }
    if (
      compact(recordValue(nextHop, "continue_in", "continueIn")) !== "training" ||
      compact(recordValue(nextHop, "accepted_into", "acceptedInto")) !== "training" ||
      compact(recordValue(nextHop, "status", "status")) !== "blocked"
    ) {
      return failure({
        step: `${name}_summary`,
        category: "fail_next_hop_mismatch",
        detail: "Blocked practice verification did not keep the next hop in Training.",
        diagnostics,
        preview: JSON.stringify(nextHop),
      });
    }
    if (!compact(recordValue(workspace, "latest_learning_blocker", "latestLearningBlocker"))) {
      return failure({
        step: `${name}_summary`,
        category: "missing_learning_blocker",
        detail: "Blocked practice verification did not persist a blocker summary.",
        diagnostics,
        preview: JSON.stringify(workspace),
      });
    }
  }

  return {
    workspaceId,
    sessionId,
    cardId: trainingCardId,
  };
}

async function main() {
  if (!providerBaseUrl) {
    return failure({
      step: "config",
      category: "missing_provider_base_url",
      detail: "Set TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_BASE_URL before running the training return smoke.",
      diagnostics: [],
    });
  }
  if (!providerApiKey) {
    return failure({
      step: "config",
      category: "missing_provider_api_key",
      detail: "Set TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_API_KEY before running the training return smoke.",
      diagnostics: [],
    });
  }

  const diagnostics = [];
  const fixture = await createFixture();

  try {
    const passProbe = await runProbe({
      name: "pass",
      diagnosticsInput: [],
      expectPassed: true,
      fixture,
      diagnostics,
    });
    const failProbe = await runProbe({
      name: "fail",
      diagnosticsInput: ["[error] practice.py:1: forced training return smoke diagnostic."],
      expectPassed: false,
      fixture,
      diagnostics,
    });

  return success({
    ok: true,
    providerProtocol,
    responseLanguage,
    providerModel,
      checks: {
        passReturn: "passed",
        failBlock: "passed",
      },
      probeCount: [passProbe, failProbe].length,
      diagnostics,
    });
  } finally {
    await fs.rm(fixture.tempDir, { recursive: true, force: true });
  }
}

main().catch(async (error) => {
  if (error instanceof Error && error.message === "__training_return_smoke_failed__") {
    return;
  }
  await failure({
    step: "runtime",
    category: "unexpected_error",
    detail: error instanceof Error ? error.message : String(error),
    diagnostics: [],
  });
});
