import http from "node:http";
import { fileURLToPath } from "node:url";

export const VSIX_E2E_FIXTURE_PROVIDER_MODEL = "trainer-e2e-fixture-model";
export const VSIX_E2E_FIXTURE_PROVIDER_PROTOCOL = "openai_chat_completions_compatible";

const MAX_REQUEST_BYTES = 2 * 1024 * 1024;

export async function startVsixE2EFixtureProvider({
  apiKey,
  host = "127.0.0.1",
  port = 0,
} = {}) {
  if (typeof apiKey !== "string" || !apiKey.trim()) {
    throw new Error("VSIX E2E fixture provider requires a runtime API key.");
  }

  const stats = {
    modelsRequests: 0,
    chatCompletionRequests: 0,
    responsesRequests: 0,
    streamingRequests: 0,
    toolProbeRequests: 0,
  };
  let responseSequence = 0;
  const server = http.createServer(async (request, response) => {
    const requestUrl = new URL(request.url ?? "/", `http://${host}`);
    const pathname = requestUrl.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "GET" && pathname === "/health") {
      return sendJson(response, 200, { status: "ok" });
    }

    if (!hasFixtureAuthorization(request, apiKey)) {
      return sendJson(response, 401, openAiError("Fixture provider authorization was not supplied."));
    }

    if (request.method === "GET" && pathname === "/v1/models") {
      stats.modelsRequests += 1;
      return sendJson(response, 200, {
        object: "list",
        data: [
          {
            id: VSIX_E2E_FIXTURE_PROVIDER_MODEL,
            object: "model",
            created: 0,
            owned_by: "trainer-vsix-e2e",
          },
        ],
      });
    }

    if (request.method === "GET" && pathname === "/__trainer_fixture__/stats") {
      return sendJson(response, 200, { ...stats });
    }

    if (request.method !== "POST" || !["/v1/chat/completions", "/v1/responses"].includes(pathname)) {
      return sendJson(response, 404, openAiError("Fixture provider route was not found."));
    }

    let payload;
    try {
      payload = await readJsonBody(request);
    } catch (error) {
      return sendJson(response, 400, openAiError(error instanceof Error ? error.message : "Invalid JSON."));
    }

    if (pathname === "/v1/chat/completions") {
      stats.chatCompletionRequests += 1;
      if (payload.stream === true) {
        stats.streamingRequests += 1;
      }
    } else {
      stats.responsesRequests += 1;
    }

    const requestedToolName = requestedFixtureToolName(payload);
    if (requestedToolName === "trainer_capability_probe") {
      stats.toolProbeRequests += 1;
    }

    responseSequence += 1;
    const responseId = `trainer-e2e-fixture-${responseSequence}`;
    const reply = fixtureReplyFor(payload);
    if (pathname === "/v1/responses") {
      return sendJson(response, 200, buildResponsesResponse(responseId, payload, reply, requestedToolName));
    }
    if (payload.stream === true) {
      return sendChatCompletionStream(response, responseId, payload, reply);
    }
    return sendJson(response, 200, buildChatCompletionResponse(responseId, payload, reply, requestedToolName));
  });

  await listen(server, host, port);
  const address = server.address();
  if (!address || typeof address === "string") {
    await closeServer(server);
    throw new Error("VSIX E2E fixture provider did not expose a TCP address.");
  }

  return {
    baseUrl: `http://${host}:${address.port}/v1`,
    model: VSIX_E2E_FIXTURE_PROVIDER_MODEL,
    protocol: VSIX_E2E_FIXTURE_PROVIDER_PROTOCOL,
    async stop() {
      await closeServer(server);
    },
  };
}

function hasFixtureAuthorization(request, apiKey) {
  return request.headers.authorization === `Bearer ${apiKey}`;
}

function requestedFixtureToolName(payload) {
  const toolChoice = payload && typeof payload === "object" ? payload.tool_choice : undefined;
  if (!toolChoice || typeof toolChoice !== "object") {
    return undefined;
  }
  const functionName = toolChoice.function && typeof toolChoice.function === "object"
    ? toolChoice.function.name
    : undefined;
  return typeof functionName === "string" && functionName.trim() ? functionName.trim() : undefined;
}

function fixtureReplyFor(payload) {
  const userText = latestUserText(payload);
  const systemText = allSystemText(payload);

  // This is a deterministic transport fixture, never model-quality evidence.
  // Native card journeys still pass the real Sidecar's card validator.
  if (/^Generate the training card now\./.test(userText) && /You are generating one .*grounded (?:training|flash) card for Trainer\./.test(systemText)) {
    return JSON.stringify(fixtureTrainingCard(systemText));
  }

  if (/Return exactly the requested text/i.test(systemText)) {
    const exactMatch = userText.match(/Repeat exactly:\s*([\s\S]+)/i);
    if (exactMatch?.[1]?.trim()) {
      return exactMatch[1].trim();
    }
    return userText.trim() || "fixture integrity acknowledgement";
  }
  if (userText.includes("只用简体中文回答") || (userText.includes("先学再测") && userText.includes("VS Code"))) {
    return "先学再测，并在 VS Code 中完成一个最小验证动作。";
  }
  if (containsCjk(userText)) {
    return "先把目标缩小为一个可验证的练习：选出当前项目中的一个入口文件，写下它的输入、输出和一个不确定点。完成后把这三项发给我，我再带你走下一步。";
  }
  return "Start with one small, verifiable step: identify one entry point, its input, its output, and one uncertainty. Share those three facts before moving on.";
}

function fixtureTrainingCard(systemText) {
  const focus = systemText.match(/^- focus_area:\s*(.+)$/m)?.[1]?.trim() || "workspace boundary";
  const target = systemText.match(/^- target_skill:\s*(.+)$/m)?.[1]?.trim() || focus;
  const flash = systemText.includes("grounded flash card for Trainer");
  const chinese = /Respond in zh-CN/.test(systemText);
  const choose = (english, zh) => chinese ? zh : english;
  const question = choose(
    `Why must one request retain its original workspace_id while practicing ${focus}?`,
    `练习${focus}时，为什么一次请求必须保留原来的 workspace_id？`,
  );
  const deliverable = choose(
    "Explain the original workspace_id, the received workspace_id, and how to reject a mismatch.",
    "说明原始 workspace_id、收到的 workspace_id，以及不匹配时如何拒绝结果。",
  );
  const verify = choose(
    "Compare `workspace_id` before applying the result; a mismatch must remain rejected.",
    "应用结果前比较 `workspace_id`；不匹配的结果必须保持拒绝。",
  );
  const base = {
    title: choose(`Fixture ${flash ? "recall" : "practice"}: ${focus}`, `Fixture ${flash ? "闪记" : "练习"}：${focus}`),
    why_now: choose("This fixture checks one request boundary without claiming learner mastery.", "这个 fixture 检查一次请求边界，不声明学习者已经掌握。"),
    focus_area: focus,
    target_skill: target,
    scenario: choose("An asynchronous result returns after the selected workspace changes.", "异步结果返回时，所选工作区已经改变。"),
    problem_statement: question,
    suggested_workspace_action: choose("Describe one request and its original workspace_id.", "描述一次请求及其原始 workspace_id。"),
    deliverable,
    learner_deliverables: [deliverable],
    verification_steps: [verify],
    success_signal: choose("The learner names the mismatch and rejects the unrelated result.", "学习者指出不匹配并拒绝无关结果。"),
    stuck_recovery: choose("Compare only the two workspace_id values first.", "先只比较两个 workspace_id。"),
    reflection_prompt: choose("Which boundary prevents a late result from changing another workspace?", "哪个边界能阻止迟到结果改变另一个工作区？"),
    return_with: choose("Return the explanation and any unresolved mismatch to Coach.", "把说明和未解决的不匹配带回教练。"),
    next_after_completion: choose("Discuss the same boundary before widening the task.", "扩大任务前，先讨论同一个边界。"),
    acceptance_criteria: [
      choose("Use `workspace_id` to name the original scope.", "使用 `workspace_id` 指出原始范围。"),
      choose("Use `workspace_id` to compare the returned scope.", "使用 `workspace_id` 比较返回范围。"),
      choose("Via `workspace_id` reject a mismatched result.", "通过 `workspace_id` 拒绝不匹配的结果。"),
    ],
  };
  return flash ? {
    ...base,
    knowledge_type: "concept",
    question,
    context: base.scenario,
    answer_mode: "text",
    expected_answer: choose("The original workspace_id owns the request; applying a different scope would change unrelated state.", "原来的 workspace_id 拥有这次请求；应用另一个范围的结果会改变无关状态。"),
    hint_ladder: [verify],
    common_mistakes: [choose("Using the newly selected workspace as the original request scope.", "把新选择的工作区当作原始请求范围。")],
    feedback: { correct: verify, incorrect: base.stuck_recovery },
  } : {
    ...base,
    api_hints: ["workspace_id"],
    constraints: [choose("Use fixture data only; do not modify another workspace.", "只使用 fixture 数据，不修改另一个工作区。")],
    self_check: [verify],
    validation_method: verify,
    grading_rubric: base.acceptance_criteria,
    expected_symbols: ["workspace_id"],
    files_to_touch: [],
  };
}

function latestUserText(payload) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === "user") {
      return messageContentText(message.content);
    }
  }
  return typeof payload?.input === "string" ? payload.input : "";
}

function allSystemText(payload) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  return messages
    .filter((message) => message?.role === "system")
    .map((message) => messageContentText(message.content))
    .join("\n");
}

function messageContentText(content) {
  if (typeof content === "string") {
    return content;
  }
  if (!Array.isArray(content)) {
    return "";
  }
  return content
    .map((part) => {
      if (typeof part === "string") {
        return part;
      }
      if (part && typeof part === "object" && typeof part.text === "string") {
        return part.text;
      }
      return "";
    })
    .join("\n");
}

function containsCjk(value) {
  return /[\u3400-\u9fff]/.test(value);
}

function buildChatCompletionResponse(responseId, payload, reply, toolName) {
  const toolCall = toolName === "trainer_capability_probe" ? fixtureToolCall(toolName) : undefined;
  return {
    id: responseId,
    object: "chat.completion",
    created: 0,
    model: requestedModel(payload),
    choices: [
      {
        index: 0,
        message: toolCall
          ? { role: "assistant", content: null, tool_calls: [toolCall] }
          : { role: "assistant", content: reply },
        finish_reason: toolCall ? "tool_calls" : "stop",
      },
    ],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  };
}

function buildResponsesResponse(responseId, payload, reply, toolName) {
  const toolCall = toolName === "trainer_capability_probe";
  return {
    id: responseId,
    object: "response",
    status: "completed",
    model: requestedModel(payload),
    output_text: toolCall ? "" : reply,
    output: toolCall
      ? [
          {
            type: "function_call",
            id: `${responseId}-call-1`,
            call_id: `${responseId}-call-1`,
            name: toolName,
            arguments: '{"probe":"ok"}',
          },
        ]
      : [
          {
            type: "message",
            role: "assistant",
            content: [{ type: "output_text", text: reply }],
          },
        ],
    usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
  };
}

function sendChatCompletionStream(response, responseId, payload, reply) {
  const firstChunk = {
    id: responseId,
    object: "chat.completion.chunk",
    created: 0,
    model: requestedModel(payload),
    choices: [{ index: 0, delta: { role: "assistant", content: reply }, finish_reason: null }],
  };
  const finalChunk = {
    id: responseId,
    object: "chat.completion.chunk",
    created: 0,
    model: requestedModel(payload),
    choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
  };
  response.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache",
    connection: "keep-alive",
  });
  response.write(`data: ${JSON.stringify(firstChunk)}\n\n`);
  response.write(`data: ${JSON.stringify(finalChunk)}\n\n`);
  response.end("data: [DONE]\n\n");
}

function fixtureToolCall(name) {
  return {
    id: "trainer-e2e-fixture-tool-call",
    type: "function",
    function: { name, arguments: '{"probe":"ok"}' },
  };
}

function requestedModel(payload) {
  return typeof payload?.model === "string" && payload.model.trim()
    ? payload.model.trim()
    : VSIX_E2E_FIXTURE_PROVIDER_MODEL;
}

function openAiError(message) {
  return { error: { message, type: "invalid_request_error" } };
}

function sendJson(response, statusCode, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  response.end(body);
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_REQUEST_BYTES) {
        reject(new Error("Fixture request exceeded the size limit."));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("error", reject);
    request.on("end", () => {
      try {
        const text = Buffer.concat(chunks).toString("utf8");
        resolve(text ? JSON.parse(text) : {});
      } catch {
        reject(new Error("Fixture request body was not valid JSON."));
      }
    });
  });
}

function listen(server, host, port) {
  return new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.off("error", onError);
      resolve();
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(port, host);
  });
}

function closeServer(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

async function runFixtureProcess() {
  const apiKey = process.env.TRAINER_VSIX_E2E_FIXTURE_API_KEY;
  const fixture = await startVsixE2EFixtureProvider({ apiKey });
  process.stdout.write(`${JSON.stringify({
    type: "trainer-vsix-e2e-fixture-ready",
    baseUrl: fixture.baseUrl,
    model: fixture.model,
    protocol: fixture.protocol,
  })}\n`);

  let stopping = false;
  const stop = async () => {
    if (stopping) {
      return;
    }
    stopping = true;
    try {
      await fixture.stop();
      process.exitCode = 0;
    } catch (error) {
      process.stderr.write(`Fixture provider shutdown failed: ${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 1;
    }
  };
  process.once("SIGTERM", stop);
  process.once("SIGINT", stop);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  runFixtureProcess().catch((error) => {
    process.stderr.write(`Fixture provider failed to start: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
