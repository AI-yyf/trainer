import process from "node:process";

const defaultSidecarUrl = "http://127.0.0.1:8765";
const defaultModel = "MiniMax-M3";
const defaultProtocol = "openai_chat_completions_compatible";
const defaultResponseLanguage = "zh-CN";
const SUPPORTED_PROTOCOLS = new Set([
  "openai_responses",
  "openai_chat_completions",
  "anthropic_messages",
  "openai_chat_completions_compatible",
  "gemini_generate_content",
]);

const sidecarUrl = (process.env.TRAINER_TURN_SMOKE_SIDECAR_URL ?? defaultSidecarUrl)
  .trim()
  .replace(/\/+$/, "");
const providerBaseUrl = (
  process.env.TRAINER_TURN_SMOKE_PROVIDER_BASE_URL ?? process.env.TRAINER_PROVIDER_SMOKE_BASE_URL ?? ""
)
  .trim()
  .replace(/\/+$/, "");
const providerApiKey = (
  process.env.TRAINER_TURN_SMOKE_PROVIDER_API_KEY ?? process.env.TRAINER_PROVIDER_SMOKE_API_KEY ?? ""
).trim();
const providerModel = (
  process.env.TRAINER_TURN_SMOKE_PROVIDER_MODEL ?? process.env.TRAINER_PROVIDER_SMOKE_MODEL ?? defaultModel
).trim();
const providerProtocol = normalizeProtocol(
  (process.env.TRAINER_TURN_SMOKE_PROVIDER_PROTOCOL ?? process.env.TRAINER_PROVIDER_SMOKE_PROTOCOL ?? defaultProtocol).trim(),
);
const responseLanguage = (
  process.env.TRAINER_TURN_SMOKE_RESPONSE_LANGUAGE ?? defaultResponseLanguage
).trim();
const smokeStartedAt = Date.now();

function elapsedMs() {
  return Date.now() - smokeStartedAt;
}

const zhRemoteMessage =
  "\u8bf7\u521b\u5efa\u4e00\u5f20 learn-first practice card\uff0c\u4e3b\u9898\u662f VS Code Remote SSH\u3002\u5148\u8ba9\u6211\u7ec3\u4e60\u4e00\u4e2a\u5f88\u5c0f\u4e14\u53ef\u9a8c\u8bc1\u7684\u6b65\u9aa4\uff0c\u518d\u5e2e\u6211\u9a8c\u8bc1\u7ed3\u679c\u3002";
const zhDebugMessage =
  "\u8bf7\u521b\u5efa\u4e00\u5f20 learn-first practice card\uff0c\u4e3b\u9898\u662f\u5728 VS Code \u91cc debug Python\u3002\u5148\u8ba9\u6211\u7ec3\u4e60\u4e00\u4e2a breakpoint \u548c\u4e00\u4e2a\u53ef\u9a8c\u8bc1\u7684 value\uff0c\u518d\u5e2e\u6211\u9a8c\u8bc1\u3002";
const zhFunctionGuidanceMessage =
  "\u8bf7\u521b\u5efa\u4e00\u5f20 learn-first practice card\uff0c\u4e3b\u9898\u662f TypeScript fetch options \u7684\u4e00\u4e2a\u771f\u5b9e call site\u3002\u5148\u8ba9\u6211\u7ec3\u4e60\u4e00\u4e2a\u53ef\u9a8c\u8bc1\u7684\u5c0f\u6b65\uff0c\u518d\u5e2e\u6211\u9a8c\u8bc1\u3002";

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
    category,
    providerModel,
    providerProtocol,
    model: providerModel,
    protocol: providerProtocol,
    elapsedMs: elapsedMs(),
    chunkCount: 0,
    ok: false,
  };
  await emitJson(process.stderr, report);
  process.exitCode = 1;
  throw new Error("__trainer_turn_smoke_failed__");
}

async function success(report) {
  await emitJson(process.stdout, report);
  process.exitCode = 0;
}

async function postJson(path, payload) {
  const response = await fetch(`${sidecarUrl}${path}`, {
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

async function postStreaming(path, payload) {
  const response = await fetch(`${sidecarUrl}${path}`, {
    method: "POST",
    headers: {
      "accept": "text/event-stream",
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  let body = "";
  if (response.body) {
    for await (const chunk of response.body) {
      body += Buffer.from(chunk).toString("utf8");
    }
  }
  const chunks = [...body.matchAll(/data:\s*\{[^\n]*"chunk"\s*:/g)].length;
  const hasComplete = /event:\s*complete\s*\n/.test(body);
  const visibleText = [...body.matchAll(/"chunk"\s*:\s*"((?:\\.|[^"\\])*)"/g)]
    .map((match) => {
      try {
        return JSON.parse(`"${match[1]}"`);
      } catch {
        return "";
      }
    })
    .join("");
  return { response, body, chunks, hasComplete, visibleText };
}

function providerPayload() {
  const payload = {
    name: "trainer-turn-smoke",
    baseUrl: providerBaseUrl,
    apiKeyRef: "trainer.turn-smoke",
    model: providerModel,
    protocol: providerProtocol,
  };
  const requestDefaults = providerRequestDefaults();
  if (Object.keys(requestDefaults).length > 0) {
    payload.requestDefaults = requestDefaults;
  }
  return payload;
}

function buildTurnPayload(
  sessionId,
  workspaceId,
  message,
  answerMode = "guided",
  { responseLanguageOverride } = {},
) {
  return {
    session_id: sessionId,
    workspace_id: workspaceId,
    intent: "coach",
    message,
    response_language: responseLanguageOverride ?? responseLanguage,
    answer_mode: answerMode,
    use_agent_loop: true,
    provider: providerPayload(),
    api_key: providerApiKey,
  };
}

const TRAINING_SCENARIO_DEFAULTS = Object.freeze({
  remote_workspace: {
    focus_area: "VS Code remote workspace",
    target_skill: "name the remote boundary",
  },
  debug_loop: {
    focus_area: "VS Code debug loop",
    target_skill: "stop at one meaningful state change",
  },
  function_guidance: {
    focus_area: "function contract",
    target_skill: "read one real call site",
  },
});

function buildTrainingCardPayload(workspaceId, message, responseLanguage, scenario) {
  const defaults = TRAINING_SCENARIO_DEFAULTS[scenario] ?? TRAINING_SCENARIO_DEFAULTS.remote_workspace;
  return {
    workspace_id: workspaceId,
    source: "conversation_gap",
    card_type: "practice",
    focus_area: defaults.focus_area,
    target_skill: defaults.target_skill,
    context_hint: `Coach request: ${message}`,
    why_now:
      responseLanguage === "zh-CN"
        ? "\u5b66\u4e60\u8005\u8bf7\u6c42\u5148\u5b66\u540e\u7ec3\u7684\u4e00\u4e2a\u6700\u5c0f\u8bad\u7ec3\u52a8\u4f5c\u3002"
        : "The learner asked for one learn-first training move.",
    response_language: responseLanguage,
    provider: providerPayload(),
    api_key: providerApiKey,
  };
}

function currentFocusOf(payload) {
  return compact(payload?.snapshot?.memory?.current_focus);
}

function replyOf(payload) {
  return compact(payload?.reply?.content);
}

function scenarioOf(payload) {
  return compact(payload?.coach_turn?.scenario);
}

function routingOf(payload) {
  return payload?.snapshot?.memory?.active_training_card_routing;
}

function hasAnyMarker(value, markers) {
  const lowered = compact(value).toLowerCase();
  return markers.some((marker) => lowered.includes(marker.toLowerCase()));
}

function hasChineseText(value) {
  return /[\u3400-\u9fff]{2,}/u.test(String(value ?? ""));
}

function providerErrorContainsSecret(value) {
  const text = String(value ?? "");
  return providerApiKey.length > 0 && text.includes(providerApiKey);
}

function assertScenario(payload, expectedScenario, step, diagnostics) {
  const actual = scenarioOf(payload);
  diagnostics.push(`${step}: scenario_matches_expected=${String(actual === expectedScenario)}`);
  if (actual !== expectedScenario) {
    return failure({
      step,
      category: "unexpected_scenario",
      detail: `Expected ${expectedScenario}, received ${actual || "(missing)"}.`,
      diagnostics,
      preview: replyOf(payload),
    });
  }
}

function assertFocusMarkers(payload, { required, forbidden }, step, diagnostics) {
  const currentFocus = currentFocusOf(payload);
  diagnostics.push(`${step}: current_focus_present=${String(Boolean(currentFocus))}`);
  if (!currentFocus) {
    return failure({
      step,
      category: "missing_current_focus",
      detail: "Trainer returned no current_focus for this coaching turn.",
      diagnostics,
      preview: replyOf(payload),
    });
  }
  if (required?.length && !hasAnyMarker(currentFocus, required)) {
    return failure({
      step,
      category: "focus_mismatch",
      detail: `current_focus did not include any of: ${required.join(", ")}.`,
      diagnostics,
      preview: currentFocus,
    });
  }
  if (forbidden?.length && hasAnyMarker(currentFocus, forbidden)) {
    return failure({
      step,
      category: "lane_contamination",
      detail: `current_focus still referenced a previous lane: ${forbidden.join(", ")}.`,
      diagnostics,
      preview: currentFocus,
    });
  }
}

function assertReplyMarkers(payload, { forbidden }, step, diagnostics) {
  const reply = replyOf(payload);
  diagnostics.push(`${step}: reply_present=${String(Boolean(reply))}`);
  if (!reply) {
    return failure({
      step,
      category: "missing_reply",
      detail: "Trainer returned no visible coaching reply.",
      diagnostics,
    });
  }
  if (forbidden?.length && hasAnyMarker(reply, forbidden)) {
    return failure({
      step,
      category: "lane_contamination",
      detail: `Visible reply still referenced a previous lane: ${forbidden.join(", ")}.`,
      diagnostics,
      preview: reply,
    });
  }
}

function assertTrainingRouting(payload, step, diagnostics, expectedScenarioPack) {
  const routing = routingOf(payload);
  if (!routing || typeof routing !== "object") {
    return failure({
      step,
      category: "missing_training_routing",
      detail: "Explicit practice request did not materialize active_training_card_routing.",
      diagnostics,
      preview: replyOf(payload),
    });
  }
  const selectedCard = routing.selected_card ?? routing.selectedCard;
  const selectedCardType = compact(selectedCard?.card_type ?? selectedCard?.type);
  const scenarioPack = compact(selectedCard?.scenario_pack ?? selectedCard?.scenarioPack);
  diagnostics.push(
    `${step}: training_card_is_practice=${String(selectedCardType === "practice")} training_pack_matches_expected=${String(scenarioPack === expectedScenarioPack)}`,
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
  if (scenarioPack !== expectedScenarioPack) {
    return failure({
      step,
      category: "unexpected_training_scenario_pack",
      detail: `Expected ${expectedScenarioPack} scenario pack, received ${scenarioPack || "(missing)"}.`,
      diagnostics,
      preview: JSON.stringify(routing),
    });
  }
}

function assertChatDoesNotMintTrainingCard(payload, step, diagnostics) {
  const routing = routingOf(payload);
  diagnostics.push(`${step}: chat_training_routing_absent=${String(!routing)}`);
  if (routing && typeof routing === "object") {
    return failure({
      step,
      category: "chat_minted_training_card",
      detail: "Composer chat returned active training-card routing; use the explicit generate-card binder.",
      diagnostics,
    });
  }
}

function assertGeneratedTrainingCard(payload, step, diagnostics, expectedScenarioPack) {
  const card = payload?.card;
  const cardType = compact(card?.card_type ?? card?.cardType);
  const scenarioPack = compact(card?.scenario_pack ?? card?.scenarioPack);
  diagnostics.push(
    `${step}: explicit_card_is_practice=${String(cardType === "practice")} explicit_pack_matches_expected=${String(scenarioPack === expectedScenarioPack)}`,
  );
  if (!card || typeof card !== "object") {
    return failure({
      step,
      category: "missing_training_card",
      detail: "The explicit generate-card binder returned no card.",
      diagnostics,
    });
  }
  if (cardType !== "practice") {
    return failure({
      step,
      category: "unexpected_training_card_type",
      detail: `Expected practice card, received ${cardType || "(missing)"}.`,
      diagnostics,
    });
  }
  if (scenarioPack !== expectedScenarioPack) {
    return failure({
      step,
      category: "unexpected_training_scenario_pack",
      detail: `Expected ${expectedScenarioPack} scenario pack, received ${scenarioPack || "(missing)"}.`,
      diagnostics,
    });
  }
  if (!compact(card.card_id ?? card.cardId)) {
    return failure({
      step,
      category: "missing_training_card",
      detail: "The explicit generate-card binder returned no durable card id.",
      diagnostics,
    });
  }
}

function assertGeneratedTrainingCardLocalized(payload, step, diagnostics, expectedLanguage) {
  if (expectedLanguage !== "zh-CN") {
    return;
  }
  const card = payload?.card ?? {};
  const fields = [
    ["title", compact(card.title)],
    ["problem_statement", compact(card.problem_statement ?? card.problemStatement)],
    [
      "suggested_workspace_action",
      compact(card.suggested_workspace_action ?? card.suggestedWorkspaceAction),
    ],
  ];
  const missing = fields.filter(([, value]) => !hasChineseText(value)).map(([field]) => field);
  diagnostics.push(`${step}: explicit_card_localized=${String(missing.length === 0)}`);
  if (missing.length > 0) {
    return failure({
      step,
      category: "training_card_language_mismatch",
      detail: `Expected zh-CN card copy in ${missing.join(", ")}.`,
      diagnostics,
    });
  }
}

async function generateExplicitTrainingCard({
  workspaceId,
  message,
  responseLanguage,
  scenario,
  diagnostics,
  step,
}) {
  const generated = await postJson(
    "/training/generate-card",
    buildTrainingCardPayload(workspaceId, message, responseLanguage, scenario),
  );
  if (!generated.response.ok || !generated.json) {
    return failure({
      step,
      category: "training_card_request_failed",
      detail: `Explicit generate-card request failed with HTTP ${generated.response.status}.`,
      diagnostics,
      status: generated.response.status,
    });
  }
  await assertGeneratedTrainingCard(generated.json, step, diagnostics, scenario);
  return generated.json;
}

function assertReplyLocalized(payload, step, diagnostics, expectedLanguage) {
  const reply = replyOf(payload);
  diagnostics.push(`${step}: localized_reply_has_cjk=${String(hasChineseText(reply))}`);
  if (!reply) {
    return failure({
      step,
      category: "missing_reply",
      detail: "Trainer returned no visible coaching reply.",
      diagnostics,
    });
  }
  if (expectedLanguage === "zh-CN" && !hasChineseText(reply)) {
    return failure({
      step,
      category: "reply_language_mismatch",
      detail:
        "Expected a zh-CN coaching reply with Chinese text, but the visible reply did not contain a Chinese phrase.",
      diagnostics,
      preview: reply,
    });
  }
}

function assertTrainingCardLocalized(payload, step, diagnostics, expectedLanguage) {
  const routing = routingOf(payload);
  const selectedCard = routing?.selected_card ?? routing?.selectedCard;
  const title = compact(selectedCard?.title);
  const problemStatement = compact(selectedCard?.problem_statement ?? selectedCard?.problemStatement);
  const workspaceAction = compact(
    selectedCard?.suggested_workspace_action ?? selectedCard?.suggestedWorkspaceAction,
  );
  diagnostics.push(
    `${step}: localized_card_fields=title:${String(Boolean(title))},problem:${String(
      Boolean(problemStatement),
    )},workspace_action:${String(Boolean(workspaceAction))}`,
  );
  if (expectedLanguage === "zh-CN") {
    const localizedFields = [
      ["title", title],
      ["problem_statement", problemStatement],
      ["suggested_workspace_action", workspaceAction],
    ];
    const fieldsWithoutChinese = localizedFields
      .filter(([, value]) => !hasChineseText(value))
      .map(([field]) => field);
    if (fieldsWithoutChinese.length > 0) {
      return failure({
        step,
        category: "training_card_language_mismatch",
        detail:
          `Expected zh-CN training-card copy in title, problem_statement, and suggested_workspace_action; ${fieldsWithoutChinese.join(", ")} lacked a Chinese phrase.`,
        diagnostics,
        preview: JSON.stringify({
          title,
          problemStatement,
          workspaceAction,
        }),
      });
    }
  }
}

function assertCurrentFocusLocalized(payload, step, diagnostics, expectedLanguage) {
  const currentFocus = currentFocusOf(payload);
  diagnostics.push(`${step}: localized_focus_has_cjk=${String(hasChineseText(currentFocus))}`);
  if (!currentFocus) {
    return failure({
      step,
      category: "missing_current_focus",
      detail: "Trainer returned no current_focus for this coaching turn.",
      diagnostics,
      preview: replyOf(payload),
    });
  }
  if (expectedLanguage === "zh-CN" && !hasChineseText(currentFocus)) {
    return failure({
      step,
      category: "focus_language_mismatch",
      detail: "Expected zh-CN current_focus with Chinese text, but it did not contain a Chinese phrase.",
      diagnostics,
      preview: currentFocus,
    });
  }
}

async function main() {
  let streamChunkCount = 0;
  if (!providerBaseUrl) {
    return failure({
      step: "config",
      category: "missing_provider_base_url",
      detail: "Set TRAINER_PROVIDER_SMOKE_BASE_URL or TRAINER_TURN_SMOKE_PROVIDER_BASE_URL.",
      diagnostics: [],
    });
  }
  if (!providerApiKey) {
    return failure({
      step: "config",
      category: "missing_provider_api_key",
      detail: "Set TRAINER_PROVIDER_SMOKE_API_KEY.",
      diagnostics: [],
    });
  }

  const diagnostics = [];
  const capabilityTest = await postJson("/provider/test", {
    provider: providerPayload(),
    api_key: providerApiKey,
    response_language: responseLanguage,
    probe_message: "请用一句话确认当前连接可以进行中文教练对话。",
  });
  if (!capabilityTest.response.ok || capabilityTest.json?.ok !== true) {
    return failure({
      step: "provider_test",
      category: "provider_capability_test_failed",
      detail: `Provider capability test failed with HTTP ${capabilityTest.response.status}.`,
      diagnostics,
      status: capabilityTest.response.status,
    });
  }
  diagnostics.push("provider_test: chat_probe=verified");
  const workspaceId = `trainer-turn-smoke-${Date.now()}`;
  const start = await postJson("/session/start", {
    workspace_id: workspaceId,
    workspace_name: workspaceId,
    profile: {
      long_term_goal: "Keep Trainer lane continuity and explicit practice-card routing honest.",
      weekly_hours: 4,
      teaching_style: "guided",
      answer_policy: "guided",
    },
  });
  if (!start.response.ok || !start.json?.session_id) {
    return failure({
      step: "session_start",
      category: "session_start_failed",
      detail: `Session start failed with HTTP ${start.response.status}.`,
      diagnostics,
      status: start.response.status,
      preview: compact(start.text),
    });
  }
  const sessionId = compact(start.json.session_id);
  diagnostics.push("session_start: started=true");

  const stream = await postStreaming(
    "/turn/stream",
    buildTurnPayload(
      sessionId,
      workspaceId,
      "请用中文给我一个最小的 VS Code 断点验证步骤，只说明动作和成功信号。",
      "guided",
      { responseLanguageOverride: "zh-CN" },
    ),
  );
  streamChunkCount = stream.chunks;
  const streamOk =
    stream.response.status === 200 &&
    stream.chunks > 0 &&
    stream.hasComplete &&
    hasChineseText(stream.visibleText) &&
    !providerErrorContainsSecret(stream.body);
  if (!streamOk) {
    return failure({
      step: "turn_stream",
      category: "streaming_contract_failed",
      diagnostics,
      status: stream.response.status,
    });
  }

  const remoteTurn = await postJson(
    "/turn",
    buildTurnPayload(
      sessionId,
      workspaceId,
      "Teach me the VS Code remote workflow for SSH and dev containers. Keep it to one real workspace checkpoint first.",
    ),
  );
  if (!remoteTurn.response.ok || !remoteTurn.json) {
    return failure({
      step: "remote_workspace",
      category: "turn_failed",
      detail: `Remote turn failed with HTTP ${remoteTurn.response.status}.`,
      diagnostics,
      status: remoteTurn.response.status,
      preview: compact(remoteTurn.text),
    });
  }
  await assertScenario(remoteTurn.json, "remote_workspace", "remote_workspace", diagnostics);
  await assertFocusMarkers(
    remoteTurn.json,
    {
      required: [
        "remote workspace",
        "VS Code remote workflow",
        "\u8fdc\u7a0b\u5de5\u4f5c\u533a",
        "\u5de5\u4f5c\u533a\u8fb9\u754c",
      ],
      forbidden: [
        "debug loop",
        "function contract",
        "\u8c03\u8bd5\u95ed\u73af",
        "\u51fd\u6570\u5951\u7ea6",
      ],
    },
    "remote_workspace",
    diagnostics,
  );
  if (responseLanguage === "zh-CN") {
    await assertCurrentFocusLocalized(remoteTurn.json, "remote_workspace", diagnostics, "zh-CN");
  }

  const debugTurn = await postJson(
    "/turn",
    buildTurnPayload(
      sessionId,
      workspaceId,
      "Teach me how to debug Python in VS Code. Keep it to one breakpoint and one value first.",
    ),
  );
  if (!debugTurn.response.ok || !debugTurn.json) {
    return failure({
      step: "debug_loop",
      category: "turn_failed",
      detail: `Debug turn failed with HTTP ${debugTurn.response.status}.`,
      diagnostics,
      status: debugTurn.response.status,
      preview: compact(debugTurn.text),
    });
  }
  await assertScenario(debugTurn.json, "debug_loop", "debug_loop", diagnostics);
  await assertFocusMarkers(
    debugTurn.json,
    {
      required: ["debug loop", "\u8c03\u8bd5\u95ed\u73af", "\u65ad\u70b9", "debug"],
      forbidden: [
        "remote workspace",
        "remote lane",
        "ssh",
        "credential mode",
        "\u8fdc\u7a0b\u5de5\u4f5c\u533a",
        "\u8fdc\u7a0b\u8fb9\u754c",
      ],
    },
    "debug_loop",
    diagnostics,
  );
  await assertReplyMarkers(
    debugTurn.json,
    {
      forbidden: [
        "remote workspace",
        "remote lane",
        "ssh",
        "credential mode",
        "\u8fdc\u7a0b\u5de5\u4f5c\u533a",
        "\u8fdc\u7a0b\u8fb9\u754c",
      ],
    },
    "debug_loop",
    diagnostics,
  );
  if (responseLanguage === "zh-CN") {
    await assertCurrentFocusLocalized(debugTurn.json, "debug_loop", diagnostics, "zh-CN");
  }

  const functionTurn = await postJson(
    "/turn",
    buildTurnPayload(
      sessionId,
      workspaceId,
      "Guide me through function hints in VS Code on one real call site first.",
    ),
  );
  if (!functionTurn.response.ok || !functionTurn.json) {
    return failure({
      step: "function_guidance",
      category: "turn_failed",
      detail: `Function-guidance turn failed with HTTP ${functionTurn.response.status}.`,
      diagnostics,
      status: functionTurn.response.status,
      preview: compact(functionTurn.text),
    });
  }
  await assertScenario(functionTurn.json, "function_guidance", "function_guidance", diagnostics);
  await assertFocusMarkers(
    functionTurn.json,
    {
      required: ["function contract", "call site", "\u51fd\u6570\u5951\u7ea6", "\u8c03\u7528\u70b9"],
      forbidden: [
        "remote workspace",
        "remote lane",
        "debug loop",
        "ssh",
        "\u8fdc\u7a0b\u5de5\u4f5c\u533a",
        "\u8c03\u8bd5\u95ed\u73af",
      ],
    },
    "function_guidance",
    diagnostics,
  );
  await assertReplyMarkers(
    functionTurn.json,
    {
      forbidden: [
        "remote workspace",
        "remote lane",
        "debug loop",
        "ssh",
        "\u8fdc\u7a0b\u5de5\u4f5c\u533a",
        "\u8c03\u8bd5\u95ed\u73af",
      ],
    },
    "function_guidance",
    diagnostics,
  );
  if (responseLanguage === "zh-CN") {
    await assertCurrentFocusLocalized(functionTurn.json, "function_guidance", diagnostics, "zh-CN");
  }

  const trainingWorkspaceId = `${workspaceId}-training`;
  const trainingStart = await postJson("/session/start", {
    workspace_id: trainingWorkspaceId,
    workspace_name: trainingWorkspaceId,
    profile: {
      long_term_goal: "Check explicit practice-card training routing.",
      weekly_hours: 4,
      teaching_style: "guided",
      answer_policy: "coach-first",
    },
  });
  if (!trainingStart.response.ok || !trainingStart.json?.session_id) {
    return failure({
      step: "training_session_start",
      category: "session_start_failed",
      detail: `Training session start failed with HTTP ${trainingStart.response.status}.`,
      diagnostics,
      status: trainingStart.response.status,
      preview: compact(trainingStart.text),
    });
  }

  const trainingTurn = await postJson(
    "/turn",
    buildTurnPayload(
      compact(trainingStart.json.session_id),
      trainingWorkspaceId,
      "Please create a learn-first practice card for VS Code Remote SSH, then let me practice and verify one tiny move.",
      "coach-first",
    ),
  );
  if (!trainingTurn.response.ok || !trainingTurn.json) {
    return failure({
      step: "training_route",
      category: "turn_failed",
      detail: `Training routing turn failed with HTTP ${trainingTurn.response.status}.`,
      diagnostics,
      status: trainingTurn.response.status,
      preview: compact(trainingTurn.text),
    });
  }
  await assertScenario(trainingTurn.json, "remote_workspace", "training_route", diagnostics);
  await assertChatDoesNotMintTrainingCard(trainingTurn.json, "training_route", diagnostics);
  await generateExplicitTrainingCard({
    workspaceId: trainingWorkspaceId,
    message:
      "Please create a learn-first practice card for VS Code Remote SSH, then let me practice and verify one tiny move.",
    responseLanguage,
    scenario: "remote_workspace",
    diagnostics,
    step: "training_route_explicit_card",
  });

  const trainingZhWorkspaceId = `${workspaceId}-training-zh`;
  const trainingZhStart = await postJson("/session/start", {
    workspace_id: trainingZhWorkspaceId,
    workspace_name: trainingZhWorkspaceId,
    profile: {
      long_term_goal: "Check zh-CN explicit practice-card routing.",
      weekly_hours: 4,
      teaching_style: "guided",
      answer_policy: "coach-first",
    },
  });
  if (!trainingZhStart.response.ok || !trainingZhStart.json?.session_id) {
    return failure({
      step: "training_zh_session_start",
      category: "session_start_failed",
      detail: `zh-CN remote training session start failed with HTTP ${trainingZhStart.response.status}.`,
      diagnostics,
      status: trainingZhStart.response.status,
      preview: compact(trainingZhStart.text),
    });
  }

  const trainingZhTurn = await postJson(
    "/turn",
    buildTurnPayload(
      compact(trainingZhStart.json.session_id),
      trainingZhWorkspaceId,
      zhRemoteMessage,
      "coach-first",
      { responseLanguageOverride: "zh-CN" },
    ),
  );
  if (!trainingZhTurn.response.ok || !trainingZhTurn.json) {
    return failure({
      step: "training_route_zh",
      category: "turn_failed",
      detail: `zh-CN remote training routing turn failed with HTTP ${trainingZhTurn.response.status}.`,
      diagnostics,
      status: trainingZhTurn.response.status,
      preview: compact(trainingZhTurn.text),
    });
  }
  await assertScenario(trainingZhTurn.json, "remote_workspace", "training_route_zh", diagnostics);
  await assertFocusMarkers(
    trainingZhTurn.json,
    {
      required: ["\u8fdc\u7a0b\u5de5\u4f5c\u533a", "\u5de5\u4f5c\u533a\u8fb9\u754c"],
      forbidden: ["\u8c03\u8bd5\u95ed\u73af", "\u51fd\u6570\u5951\u7ea6"],
    },
    "training_route_zh",
    diagnostics,
  );
  await assertChatDoesNotMintTrainingCard(trainingZhTurn.json, "training_route_zh", diagnostics);
  const trainingZhCard = await generateExplicitTrainingCard({
    workspaceId: trainingZhWorkspaceId,
    message: zhRemoteMessage,
    responseLanguage: "zh-CN",
    scenario: "remote_workspace",
    diagnostics,
    step: "training_route_zh_explicit_card",
  });
  await assertCurrentFocusLocalized(trainingZhTurn.json, "training_route_zh", diagnostics, "zh-CN");
  await assertReplyLocalized(trainingZhTurn.json, "training_route_zh", diagnostics, "zh-CN");
  await assertGeneratedTrainingCardLocalized(
    trainingZhCard,
    "training_route_zh_explicit_card",
    diagnostics,
    "zh-CN",
  );

  const debugTrainingZhWorkspaceId = `${workspaceId}-debug-training-zh`;
  const debugTrainingZhStart = await postJson("/session/start", {
    workspace_id: debugTrainingZhWorkspaceId,
    workspace_name: debugTrainingZhWorkspaceId,
    profile: {
      long_term_goal: "Check zh-CN debug explicit practice-card routing.",
      weekly_hours: 4,
      teaching_style: "guided",
      answer_policy: "coach-first",
    },
  });
  if (!debugTrainingZhStart.response.ok || !debugTrainingZhStart.json?.session_id) {
    return failure({
      step: "debug_training_zh_session_start",
      category: "session_start_failed",
      detail: `zh-CN debug training session start failed with HTTP ${debugTrainingZhStart.response.status}.`,
      diagnostics,
      status: debugTrainingZhStart.response.status,
      preview: compact(debugTrainingZhStart.text),
    });
  }

  const debugTrainingZhTurn = await postJson(
    "/turn",
    buildTurnPayload(
      compact(debugTrainingZhStart.json.session_id),
      debugTrainingZhWorkspaceId,
      zhDebugMessage,
      "coach-first",
      { responseLanguageOverride: "zh-CN" },
    ),
  );
  if (!debugTrainingZhTurn.response.ok || !debugTrainingZhTurn.json) {
    return failure({
      step: "debug_training_route_zh",
      category: "turn_failed",
      detail: `zh-CN debug training routing turn failed with HTTP ${debugTrainingZhTurn.response.status}.`,
      diagnostics,
      status: debugTrainingZhTurn.response.status,
      preview: compact(debugTrainingZhTurn.text),
    });
  }
  await assertScenario(debugTrainingZhTurn.json, "debug_loop", "debug_training_route_zh", diagnostics);
  await assertFocusMarkers(
    debugTrainingZhTurn.json,
    {
      required: ["\u8c03\u8bd5\u95ed\u73af", "\u65ad\u70b9"],
      forbidden: ["\u8fdc\u7a0b\u5de5\u4f5c\u533a", "\u51fd\u6570\u5951\u7ea6"],
    },
    "debug_training_route_zh",
    diagnostics,
  );
  await assertChatDoesNotMintTrainingCard(debugTrainingZhTurn.json, "debug_training_route_zh", diagnostics);
  const debugTrainingZhCard = await generateExplicitTrainingCard({
    workspaceId: debugTrainingZhWorkspaceId,
    message: zhDebugMessage,
    responseLanguage: "zh-CN",
    scenario: "debug_loop",
    diagnostics,
    step: "debug_training_route_zh_explicit_card",
  });
  await assertCurrentFocusLocalized(debugTrainingZhTurn.json, "debug_training_route_zh", diagnostics, "zh-CN");
  await assertReplyLocalized(debugTrainingZhTurn.json, "debug_training_route_zh", diagnostics, "zh-CN");
  await assertGeneratedTrainingCardLocalized(
    debugTrainingZhCard,
    "debug_training_route_zh_explicit_card",
    diagnostics,
    "zh-CN",
  );

  const functionTrainingWorkspaceId = `${workspaceId}-function-training`;
  const functionTrainingStart = await postJson("/session/start", {
    workspace_id: functionTrainingWorkspaceId,
    workspace_name: functionTrainingWorkspaceId,
    profile: {
      long_term_goal: "Check function-guidance explicit practice-card training routing.",
      weekly_hours: 4,
      teaching_style: "guided",
      answer_policy: "coach-first",
    },
  });
  if (!functionTrainingStart.response.ok || !functionTrainingStart.json?.session_id) {
    return failure({
      step: "function_training_session_start",
      category: "session_start_failed",
      detail: `Function-guidance training session start failed with HTTP ${functionTrainingStart.response.status}.`,
      diagnostics,
      status: functionTrainingStart.response.status,
      preview: compact(functionTrainingStart.text),
    });
  }

  const functionTrainingTurn = await postJson(
    "/turn",
    buildTurnPayload(
      compact(functionTrainingStart.json.session_id),
      functionTrainingWorkspaceId,
      "Please create a learn-first practice card for TypeScript fetch options at one real call site, then let me practice and verify it.",
      "coach-first",
    ),
  );
  if (!functionTrainingTurn.response.ok || !functionTrainingTurn.json) {
    return failure({
      step: "function_training_route",
      category: "turn_failed",
      detail: `Function-guidance training routing turn failed with HTTP ${functionTrainingTurn.response.status}.`,
      diagnostics,
      status: functionTrainingTurn.response.status,
      preview: compact(functionTrainingTurn.text),
    });
  }
  await assertScenario(
    functionTrainingTurn.json,
    "function_guidance",
    "function_training_route",
    diagnostics,
  );
  await assertChatDoesNotMintTrainingCard(functionTrainingTurn.json, "function_training_route", diagnostics);
  await generateExplicitTrainingCard({
    workspaceId: functionTrainingWorkspaceId,
    message:
      "Please create a learn-first practice card for TypeScript fetch options at one real call site, then let me practice and verify it.",
    responseLanguage,
    scenario: "function_guidance",
    diagnostics,
    step: "function_training_route_explicit_card",
  });

  const functionTrainingZhWorkspaceId = `${workspaceId}-function-training-zh`;
  const functionTrainingZhStart = await postJson("/session/start", {
    workspace_id: functionTrainingZhWorkspaceId,
    workspace_name: functionTrainingZhWorkspaceId,
    profile: {
      long_term_goal: "Check zh-CN function-guidance explicit practice-card routing and recovery.",
      weekly_hours: 4,
      teaching_style: "guided",
      answer_policy: "coach-first",
    },
  });
  if (!functionTrainingZhStart.response.ok || !functionTrainingZhStart.json?.session_id) {
    return failure({
      step: "function_training_zh_session_start",
      category: "session_start_failed",
      detail: `zh-CN function-guidance training session start failed with HTTP ${functionTrainingZhStart.response.status}.`,
      diagnostics,
      status: functionTrainingZhStart.response.status,
      preview: compact(functionTrainingZhStart.text),
    });
  }

  const functionTrainingZhTurn = await postJson(
    "/turn",
    buildTurnPayload(
      compact(functionTrainingZhStart.json.session_id),
      functionTrainingZhWorkspaceId,
      zhFunctionGuidanceMessage,
      "coach-first",
      { responseLanguageOverride: "zh-CN" },
    ),
  );
  if (!functionTrainingZhTurn.response.ok || !functionTrainingZhTurn.json) {
    return failure({
      step: "function_training_route_zh",
      category: "turn_failed",
      detail: `zh-CN function-guidance training routing turn failed with HTTP ${functionTrainingZhTurn.response.status}.`,
      diagnostics,
      status: functionTrainingZhTurn.response.status,
      preview: compact(functionTrainingZhTurn.text),
    });
  }
  await assertScenario(
    functionTrainingZhTurn.json,
    "function_guidance",
    "function_training_route_zh",
    diagnostics,
  );
  await assertFocusMarkers(
    functionTrainingZhTurn.json,
    {
      required: ["\u51fd\u6570\u5951\u7ea6", "\u8c03\u7528\u70b9"],
      forbidden: ["\u8fdc\u7a0b\u5de5\u4f5c\u533a", "\u8c03\u8bd5\u95ed\u73af"],
    },
    "function_training_route_zh",
    diagnostics,
  );
  await assertChatDoesNotMintTrainingCard(
    functionTrainingZhTurn.json,
    "function_training_route_zh",
    diagnostics,
  );
  const functionTrainingZhCard = await generateExplicitTrainingCard({
    workspaceId: functionTrainingZhWorkspaceId,
    message: zhFunctionGuidanceMessage,
    responseLanguage: "zh-CN",
    scenario: "function_guidance",
    diagnostics,
    step: "function_training_route_zh_explicit_card",
  });
  await assertCurrentFocusLocalized(functionTrainingZhTurn.json, "function_training_route_zh", diagnostics, "zh-CN");
  await assertReplyLocalized(functionTrainingZhTurn.json, "function_training_route_zh", diagnostics, "zh-CN");
  await assertGeneratedTrainingCardLocalized(
    functionTrainingZhCard,
    "function_training_route_zh_explicit_card",
    diagnostics,
    "zh-CN",
  );

  return success({
    category: "success",
    providerModel,
    providerProtocol,
    model: providerModel,
    protocol: providerProtocol,
    elapsedMs: elapsedMs(),
    chunkCount: streamChunkCount,
    ok: true,
  });
}

main().catch(async (error) => {
  if (error instanceof Error && error.message === "__trainer_turn_smoke_failed__") {
    return;
  }
  await failure({
    step: "runtime",
    category: "unexpected_error",
    detail: error instanceof Error ? error.message : String(error),
    diagnostics: [],
  });
});
