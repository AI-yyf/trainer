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

  if (/Return exactly the requested text/i.test(systemText)) {
    const exactMatch = userText.match(/Repeat exactly:\s*([\s\S]+)/i);
    if (exactMatch?.[1]?.trim()) {
      return exactMatch[1].trim();
    }
    return userText.trim() || "fixture integrity acknowledgement";
  }

  // Card generation asks for JSON only. Coach prose here causes stream/non-stream
  // fail-closed minting (invalid_json → CardGenerationStreamError / ProviderFailure),
  // which the host surfaces as opaque "Provider request failed." after redaction.
  const cardReply = fixtureTrainingCardReply(systemText, userText);
  if (cardReply) {
    return cardReply;
  }

  if (userText.includes("只用简体中文回答") || (userText.includes("先学再测") && userText.includes("VS Code"))) {
    return "先学再测，并在 VS Code 中完成一个最小验证动作。";
  }
  if (containsCjk(userText)) {
    return "先把目标缩小为一个可验证的练习：选出当前项目中的一个入口文件，写下它的输入、输出和一个不确定点。完成后把这三项发给我，我再带你走下一步。";
  }
  return "Start with one small, verifiable step: identify one entry point, its input, its output, and one uncertainty. Share those three facts before moving on.";
}

function fixtureTrainingCardReply(systemText, userText) {
  const asksForCard =
    /Generate the training card now\.?/i.test(userText) ||
    /Output valid JSON only/i.test(systemText) ||
    /generating one grounded (flash|practice) card/i.test(systemText) ||
    /Create one grounded (flash|practice) card/i.test(systemText);
  if (!asksForCard) {
    return null;
  }

  const preferChinese =
    containsCjk(systemText) ||
    containsCjk(userText) ||
    /\bzh(?:-CN)?\b/i.test(systemText) ||
    /简体中文|中文/.test(systemText);
  const isFlash =
    /grounded flash card/i.test(systemText) ||
    /flash card/i.test(systemText) ||
    /"knowledge_type"/i.test(systemText);
  const focusArea =
    contextField(systemText, "focus_area") ||
    (preferChinese ? "依赖注入" : "dependency injection");
  const targetSkill =
    contextField(systemText, "target_skill") ||
    (preferChinese ? "FastAPI Depends" : "FastAPI Depends");

  if (isFlash) {
    return JSON.stringify(fixtureFlashCardPayload({ focusArea, targetSkill, preferChinese }));
  }
  return JSON.stringify(fixturePracticeCardPayload({ focusArea, targetSkill, preferChinese }));
}

function contextField(systemText, fieldName) {
  const match = systemText.match(new RegExp(`-\\s*${fieldName}:\\s*(.+)`, "i"));
  if (!match?.[1]) {
    return "";
  }
  const value = match[1].trim();
  if (!value || value === "None" || value === "null" || value === '""') {
    return "";
  }
  return value;
}

function fixtureFlashCardPayload({ focusArea, targetSkill, preferChinese }) {
  if (preferChinese) {
    return {
      title: `闪记：${focusArea}`,
      why_now: `先稳住 ${targetSkill} 的边界，再进入更大的练习。`,
      focus_area: focusArea,
      target_skill: targetSkill,
      knowledge_type: "engineering_concept",
      question: `用一句话说清 ${targetSkill} 解决的边界问题是什么？`,
      context: `学习者刚在对话里碰到 ${focusArea}，需要先做一次短回忆。`,
      answer_mode: "text",
      expected_answer: `${targetSkill} 把共享依赖从路由处理函数中抽离，并在边界注入。`,
      problem_statement: `还不能稳定说出 ${targetSkill} 的职责边界。`,
      suggested_workspace_action: "打开一个路由文件，标出 Depends 注入点。",
      deliverable: "一句边界说明 + 一个 Depends 注入点位置",
      learner_deliverables: ["一句边界说明", "一个 Depends 注入点位置"],
      verification_steps: ["对照路由签名确认注入点", "确认处理函数不再自行创建依赖"],
      success_signal: "能指出 Depends 的注入边界，而不是背定义",
      reflection_prompt: "哪一条边界让你确认这不是普通函数参数？",
      return_with: "把边界说明带回教练对话",
      next_after_completion: "进入一次最小 Depends 练习",
      hint_ladder: ["先找路由函数签名", "再找 Depends(...)", "对照依赖由谁创建"],
      common_mistakes: ["把 Depends 当成普通默认参数", "在路由里直接 new 依赖"],
      feedback: {
        correct: "你已经抓住了注入边界。",
        incorrect: "再对照路由签名，区分注入点与普通参数。",
      },
    };
  }
  return {
    title: `Flash: ${focusArea}`,
    why_now: `Stabilize the ${targetSkill} boundary before a larger practice loop.`,
    focus_area: focusArea,
    target_skill: targetSkill,
    knowledge_type: "engineering_concept",
    question: `In one sentence, what boundary problem does ${targetSkill} solve?`,
    context: `The learner just hit ${focusArea} in conversation and needs a short recall check.`,
    answer_mode: "text",
    expected_answer: `${targetSkill} extracts shared dependencies and injects them at the route boundary.`,
    problem_statement: `The learner cannot yet name the ${targetSkill} responsibility boundary.`,
    suggested_workspace_action: "Open one route file and mark the Depends injection site.",
    deliverable: "One boundary sentence plus one Depends injection site",
    learner_deliverables: ["One boundary sentence", "One Depends injection site"],
    verification_steps: ["Confirm the injection site on the route signature", "Confirm the handler does not construct the dependency itself"],
    success_signal: "The learner can point at the Depends boundary instead of reciting a definition",
    reflection_prompt: "Which boundary proved this is not an ordinary function argument?",
    return_with: "Bring the boundary sentence back into Coach",
    next_after_completion: "Move into one minimal Depends practice card",
    hint_ladder: ["Find the route signature", "Find Depends(...)", "Ask who constructs the dependency"],
    common_mistakes: ["Treating Depends like a default argument", "Constructing the dependency inside the route"],
    feedback: {
      correct: "You named the injection boundary.",
      incorrect: "Look at the route signature again and separate injection from ordinary parameters.",
    },
  };
}

function fixturePracticeCardPayload({ focusArea, targetSkill, preferChinese }) {
  if (preferChinese) {
    return {
      title: `练习：${focusArea}`,
      focus_area: focusArea,
      target_skill: targetSkill,
      scenario: `围绕 ${focusArea} 做一个最小可验证练习。`,
      problem_statement: `还不能把 ${targetSkill} 接到一个真实路由边界上。`,
      api_hints: ["Depends", "Annotated", targetSkill],
      deliverable: "一个带 Depends 的最小路由切片",
      self_check: ["依赖是否在边界注入", "处理函数是否避免自行创建依赖"],
      grading_rubric: ["注入点清晰", "边界保持最小", "能说明验证方式"],
      stuck_recovery: "先写一个空依赖函数，再接到路由签名上。",
      reflection_prompt: "注入边界相对普通参数多了哪一步？",
    };
  }
  return {
    title: `Practice: ${focusArea}`,
    focus_area: focusArea,
    target_skill: targetSkill,
    scenario: `Run one minimal verifiable practice around ${focusArea}.`,
    problem_statement: `The learner has not yet wired ${targetSkill} onto a real route boundary.`,
    api_hints: ["Depends", "Annotated", targetSkill],
    deliverable: "One minimal route slice that uses Depends",
    self_check: ["Is the dependency injected at the boundary?", "Does the handler avoid constructing it?"],
    grading_rubric: ["Injection site is clear", "Boundary stays minimal", "Verification path is named"],
    stuck_recovery: "Write an empty dependency callable first, then attach it to the route signature.",
    reflection_prompt: "What extra step does injection add beyond an ordinary parameter?",
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
