import process from "node:process";

const defaultProtocol = "openai_chat_completions_compatible";
const defaultResponseLanguage = "zh-CN";

const SUPPORTED_PROTOCOLS = new Set([
  "openai_responses",
  "openai_chat_completions",
  "anthropic_messages",
  "openai_chat_completions_compatible",
  "gemini_generate_content",
]);

const baseUrl = (process.env.TRAINER_PROVIDER_SMOKE_BASE_URL ?? "")
  .trim()
  .replace(/\/+$/, "");
const apiKey = (process.env.TRAINER_PROVIDER_SMOKE_API_KEY ?? "").trim();
const model = (process.env.TRAINER_PROVIDER_SMOKE_MODEL ?? "").trim();
const protocol = normalizeProtocol(
  (process.env.TRAINER_PROVIDER_SMOKE_PROTOCOL ?? defaultProtocol).trim(),
);
const responseLanguage = (
  process.env.TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE ?? defaultResponseLanguage
).trim();
const smokeStartedAt = Date.now();

const DEFAULT_PROBE_OUTPUT_TOKENS = 96;
// Keep in sync with server/app/llm/provider_service.py _visible_probe_max_tokens:
// reasoning-first gateways can spend 256+ output tokens on hidden reasoning
// before the first visible token, so the generous tier grants 1024.
const GENEROUS_PROBE_OUTPUT_TOKENS = 1024;

function needsGenerousProbeBudget() {
  return (
    /minimax|kimi|moonshot/i.test(`${model} ${baseUrl}`) ||
    /deepseek[-_. ]?r|deepseek[-_. ]?reasoner|qwq|o1(?:[-_.](?:mini|preview|pro))?|o3(?:[-_.]mini)?|o4[-_.]mini|glm[-_. ]?\d*[-_. ]?z|thinking|reasoner/i.test(
      model,
    )
  );
}

const probeOutputTokens = needsGenerousProbeBudget()
  ? GENEROUS_PROBE_OUTPUT_TOKENS
  : DEFAULT_PROBE_OUTPUT_TOKENS;

function elapsedMs() {
  return Date.now() - smokeStartedAt;
}

const QUESTION_RUN_PATTERN = /\?{4,}/;
const CJK_CHAR_PATTERN = /[\u3400-\u9fff]/u;
const CYRILLIC_CHAR_PATTERN = /[\u0400-\u04FF]/u;
const THINK_BLOCK_PATTERN = /<think\b[^>]*>[\s\S]*?<\/think>/gi;
const THINK_TAG_PATTERN = /<\/?think\b[^>]*>/gi;
const INPUT_CORRUPTION_MARKERS = [
  "question mark",
  "question marks",
  "garbled",
  "corrupted",
  "cannot read",
  "can't read",
  "could not read",
  "only saw",
  "only see",
  "\u95ee\u53f7",
  "\u4e71\u7801",
  "\u53ea\u80fd\u770b\u5230\u4e00\u4e32",
  "\u770b\u8d77\u6765\u4f60\u53d1\u8fc7\u6765\u7684\u5185\u5bb9\u91cc\u4e2d\u6587\u90fd\u53d8\u6210\u4e86\u95ee\u53f7",
  "\u7f16\u7801",
  "\u8f93\u5165\u6cd5",
];
const zhProbeExact =
  "Repeat exactly: \u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u5b66\u518d\u6d4b\u3002" +
  "\u8bf7\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\u3002ABC123";
const zhProbeCheckpoint =
  "\u8bfb\u8fd9\u53e5\u8bdd\uff0c\u53ea\u56de\u590d\u6700\u540e\u56db\u4e2a\u6c49\u5b57\uff0c" +
  "\u4e0d\u8981\u89e3\u91ca\uff1a\u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u7528\u6700\u5c0f" +
  "\u6559\u5b66\u6b65\u9aa4\u6559\u6211\u5982\u4f55\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a" +
  "\u8fb9\u754c\uff0c\u518d\u7ed9\u6211\u4e00\u4e2a\u5f88\u5c0f\u7684\u9a8c\u8bc1\u52a8\u4f5c";
const zhCheckpointExpected = "\u9a8c\u8bc1\u52a8\u4f5c";
const naturalZhProbe =
  "\u53ea\u7528\u7b80\u4f53\u4e2d\u6587\u56de\u590d\u4e00\u53e5\u8bdd\uff0c" +
  "\u5e76\u5b8c\u6574\u4fdd\u7559\u300c\u5148\u5b66\u518d\u6d4b\u300d\u548c\u300cVS Code\u300d\u3002" +
  "\u4e0d\u8981\u89e3\u91ca\uff0c\u4e0d\u8981\u52a0\u5f15\u53f7\u3002";
const naturalZhFragments = ["\u5148\u5b66\u518d\u6d4b", "VS Code"];
const enProbeExact =
  "Repeat exactly: Learn first, then verify. Use a tiny remote workspace checkpoint. ABC123";

const LANGUAGE_PROBE_VARIANTS = {
  "zh-CN": [
    {
      prompt: zhProbeExact,
      expected: zhProbeExact,
      failureDetail:
        "Provider reachable, but it corrupted Chinese input into question marks before the model saw it.",
      inconclusiveDetail:
        "Language integrity probe was inconclusive. The provider replied, but it did not preserve the mixed CJK/ASCII probe text exactly enough for Trainer to trust it.",
    },
    {
      prompt: zhProbeCheckpoint,
      expected: zhCheckpointExpected,
      failureDetail:
        "Provider reachable, but it corrupted Chinese instructional text before the model could preserve the final Chinese checkpoint.",
      inconclusiveDetail:
        "Language integrity probe was inconclusive. The provider replied, but it did not preserve the Chinese checkpoint exactly enough for Trainer to trust it.",
    },
  ],
  "en-US": [
    {
      prompt: enProbeExact,
      expected: enProbeExact,
      failureDetail:
        "Provider reachable, but it corrupted the English smoke text before the model could echo it back.",
      inconclusiveDetail:
        "Language integrity probe was inconclusive. The provider replied, but it did not preserve the English probe text exactly enough for Trainer to trust it.",
    },
  ],
};

function normalizeProtocol(value) {
  return SUPPORTED_PROTOCOLS.has(value) ? value : defaultProtocol;
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function redactProviderError(value, { fallback = "Provider request failed", upstreamBody = false } = {}) {
  if (upstreamBody) {
    return `${fallback}; upstream response body redacted.`;
  }
  if (value instanceof Error) {
    return fallback;
  }

  let text;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value);
  } catch {
    return fallback;
  }
  if (!text) {
    return fallback;
  }

  if (apiKey) {
    text = text.split(apiKey).join("[REDACTED]");
  }
  text = text.replace(
    /([?&](?:[a-z0-9]+[-_])*(?:api[-_]?key|access[-_]?token|authorization|token|secret|password|key)=)[^&#\s]+/gi,
    "$1[REDACTED]",
  );
  text = text.replace(/\bBearer\s+[^\s,;]+/gi, "Bearer [REDACTED]");
  text = text.replace(
    /\b(api[-_]?key|access[-_]?token|authorization|token|secret|password|key)\b\s*[:=]\s*("[^"]*"|'[^']*'|[^,\s}\]]+)/gi,
    "$1=[REDACTED]",
  );
  text = text.replace(
    /\b(?:upstream|provider|response)\s+(?:body|payload|content)\s*(?:[:=]|was|is)\s*[\s\S]*/gi,
    "upstream response body redacted",
  );
  return text.replace(/\s+/g, " ").trim().slice(0, 400) || fallback;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function prefersChinese(language) {
  return String(language || "").toLowerCase().startsWith("zh");
}

function compactVisibleText(value) {
  if (typeof value !== "string") {
    return "";
  }
  return value.replace(/\s+/g, " ").trim();
}

function stripReasoningBlocks(value) {
  if (typeof value !== "string") {
    return "";
  }
  return compactVisibleText(
    value.replace(THINK_BLOCK_PATTERN, " ").replace(THINK_TAG_PATTERN, " "),
  );
}

function containsCjk(value) {
  return CJK_CHAR_PATTERN.test(value);
}

function containsCyrillic(value) {
  return CYRILLIC_CHAR_PATTERN.test(value);
}

function openAiHeaders() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${apiKey}`,
  };
}

function anthropicHeaders() {
  return {
    "Content-Type": "application/json",
    "anthropic-version": "2023-06-01",
    "x-api-key": apiKey,
  };
}

function geminiHeaders() {
  return {
    "Content-Type": "application/json",
    "x-goog-api-key": apiKey,
  };
}

function anthropicBaseUrl() {
  let resolved = baseUrl;
  if (resolved.endsWith("/v1")) {
    resolved = resolved.slice(0, -3);
  }
  return resolved || "https://api.anthropic.com";
}

function normalizedOpenAiCompatibleBaseUrl() {
  let resolved = baseUrl;
  if (!resolved) {
    return resolved;
  }

  const lowered = resolved.toLowerCase().replace(/\/+$/, "");
  if (protocol === "gemini_generate_content" && lowered.includes("googleapis.com")) {
    return resolved;
  }
  if (protocol === "anthropic_messages" && lowered.includes("anthropic.com")) {
    return resolved;
  }

  let pathname = "";
  try {
    pathname = new URL(resolved).pathname ?? "";
  } catch {
    return resolved;
  }
  const loweredPath = pathname.toLowerCase().replace(/\/+$/, "");
  if (loweredPath.endsWith("/v1") || loweredPath.endsWith("/v1beta")) {
    return resolved;
  }

  const needsOpenAiCompatibleRoot =
    protocol === "openai_chat_completions" ||
    protocol === "openai_chat_completions_compatible" ||
    protocol === "openai_responses" ||
    (protocol === "gemini_generate_content" && !lowered.includes("googleapis.com")) ||
    (protocol === "anthropic_messages" && !lowered.includes("anthropic.com"));
  if (!needsOpenAiCompatibleRoot) {
    return resolved;
  }
  if (loweredPath && loweredPath !== "/") {
    return resolved;
  }
  return `${resolved}/v1`;
}

function geminiBaseUrl() {
  let resolved = baseUrl;
  if (!resolved) {
    resolved = "https://generativelanguage.googleapis.com/v1beta";
  }
  return resolved;
}

function geminiModelsEndpoint() {
  let resolved = geminiBaseUrl();
  if (resolved.endsWith(":generateContent")) {
    resolved = resolved.includes("/models/") ? resolved.split("/models/")[0] : resolved;
  }
  if (resolved.includes("/models/")) {
    resolved = resolved.split("/models/")[0];
  }
  if (resolved.replace(/\/+$/, "").endsWith("/models")) {
    return resolved;
  }
  if (resolved.endsWith("/v1") || resolved.endsWith("/v1beta")) {
    return `${resolved}/models`;
  }
  return `${resolved}/v1beta/models`;
}

function geminiGenerateContentEndpoint() {
  let resolved = geminiBaseUrl();
  if (resolved.endsWith(":generateContent")) {
    return resolved;
  }
  if (resolved.includes("/models/")) {
    return `${resolved}:generateContent`;
  }
  if (!(resolved.endsWith("/v1") || resolved.endsWith("/v1beta"))) {
    resolved = `${resolved}/v1beta`;
  }
  return `${resolved}/models/${encodeURIComponent(model).replace(/%2F/g, "/")}:generateContent`;
}

function isGoogleNativeGeminiBaseUrl() {
  return geminiBaseUrl().toLowerCase().includes("googleapis.com");
}

function extractErrorMessage(body) {
  if (!body || typeof body !== "object") {
    return undefined;
  }
  const error = body.error;
  if (error && typeof error === "object" && typeof error.message === "string") {
    return error.message.trim() || undefined;
  }
  if (typeof body.detail === "string") {
    return body.detail.trim() || undefined;
  }
  if (typeof body.message === "string") {
    return body.message.trim() || undefined;
  }
  return undefined;
}

function extractOpenAiChatContent(body) {
  const messageContent = body?.choices?.[0]?.message?.content;
  if (typeof messageContent === "string") {
    return messageContent;
  }
  if (Array.isArray(messageContent)) {
    return messageContent
      .map((part) => {
        if (typeof part === "string") {
          return part;
        }
        if (part && typeof part === "object" && typeof part.text === "string") {
          return part.text;
        }
        return "";
      })
      .join("");
  }
  if (typeof body?.choices?.[0]?.text === "string") {
    return body.choices[0].text;
  }
  return "";
}

function extractOpenAiResponsesContent(body) {
  if (typeof body?.output_text === "string") {
    return body.output_text;
  }
  const textParts = [];
  for (const item of body?.output ?? []) {
    if (!item || typeof item !== "object") {
      continue;
    }
    if (Array.isArray(item.content)) {
      for (const part of item.content) {
        if (part && typeof part === "object" && typeof part.text === "string") {
          textParts.push(part.text);
        }
      }
    }
  }
  return textParts.join("");
}

function extractAnthropicContent(body) {
  return (body?.content ?? [])
    .map((item) =>
      item && typeof item === "object" && item.type === "text" && typeof item.text === "string"
        ? item.text
        : "",
    )
    .join("");
}

function extractGeminiContent(body) {
  const parts = [];
  for (const candidate of body?.candidates ?? []) {
    if (!candidate || typeof candidate !== "object") {
      continue;
    }
    for (const part of candidate?.content?.parts ?? []) {
      if (part && typeof part === "object" && typeof part.text === "string") {
        parts.push(part.text);
      }
    }
  }
  return parts.join("");
}

function extractContentForProtocol(currentProtocol, body) {
  if (currentProtocol === "openai_responses") {
    return extractOpenAiResponsesContent(body);
  }
  if (currentProtocol === "anthropic_messages") {
    return extractAnthropicContent(body);
  }
  if (currentProtocol === "gemini_generate_content" && isGoogleNativeGeminiBaseUrl()) {
    return extractGeminiContent(body);
  }
  return extractOpenAiChatContent(body);
}

function classifyHttpFailure(step, response, bodyText, bodyJson, modelId) {
  const rawDetail = extractErrorMessage(bodyJson) ?? bodyText.trim();
  const detail = redactProviderError(rawDetail, {
    fallback: `${step} request failed with HTTP ${response.status}.`,
    upstreamBody: true,
  });
  const lowerText = `${rawDetail}\n${bodyText}`.toLowerCase();
  if (response.status === 401 || response.status === 403) {
    return {
      step,
      category: "authentication_failed",
      status: response.status,
      detail: detail || `${step} request was rejected by the provider.`,
    };
  }
  if (response.status === 404) {
    return {
      step,
      category: "endpoint_not_found",
      status: response.status,
      detail: detail || `${step} endpoint was not found at ${response.url}.`,
    };
  }
  if (response.status === 429) {
    return {
      step,
      category: "rate_limit",
      status: response.status,
      detail: detail || `${step} request hit a rate limit.`,
    };
  }
  if (response.status === 408 || response.status === 504) {
    return {
      step,
      category: "timeout",
      status: response.status,
      detail: detail || `${step} request timed out.`,
    };
  }
  if (
    response.status === 503 &&
    /model_not_found|no available channel for model/.test(lowerText)
  ) {
    return {
      step,
      category: "model_not_found",
      status: response.status,
      detail: detail || `${modelId} is not available on this gateway.`,
    };
  }
  return {
    step,
    category: "request_failed",
    status: response.status,
    detail: detail || `${step} request failed with HTTP ${response.status}.`,
  };
}

async function readResponse(step, url, init, modelId) {
  let lastFailure;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(url, init);
      const text = await response.text();
      const json = parseJson(text);
      return {
        ok: response.ok,
        response,
        text,
        json,
        failure: response.ok
          ? undefined
          : classifyHttpFailure(step, response, text, json, modelId),
      };
    } catch (error) {
      lastFailure = {
        step,
        category: "network_error",
        detail: redactProviderError(error),
      };
      if (attempt < 2) {
        await delay(250 * (attempt + 1));
      }
    }
  }
  return {
    ok: false,
    failure: lastFailure ?? {
      step,
      category: "network_error",
      detail: "fetch failed",
    },
  };
}

function buildFailureReport({ model: resolvedModel, protocol: resolvedProtocol, failure }) {
  return {
    ok: false,
    category: failure.category,
    model: resolvedModel,
    protocol: resolvedProtocol,
    elapsedMs: elapsedMs(),
  };
}

function buildProbeVariants(language) {
  if (prefersChinese(language)) {
    return LANGUAGE_PROBE_VARIANTS["zh-CN"];
  }
  return LANGUAGE_PROBE_VARIANTS["en-US"];
}

function acceptedRepliesForProbe(probe) {
  const accepted = [probe.expected];
  const prefix = "Repeat exactly: ";
  if (probe.expected.startsWith(prefix)) {
    accepted.push(probe.expected.slice(prefix.length));
  }
  return accepted;
}

function looksLikeInputCorruptionReply(reply, expectedProbe) {
  const visible = compactVisibleText(reply);
  if (!visible) {
    return false;
  }
  if (expectedProbe && visible.includes(expectedProbe)) {
    return false;
  }
  const lowered = visible.toLowerCase();
  const hasMarker = INPUT_CORRUPTION_MARKERS.some((marker) =>
    lowered.includes(marker.toLowerCase()),
  );
  const expectedAsciiFragments = expectedProbe.match(/[A-Za-z0-9]{3,}/g) ?? [];
  const carriesExpectedAscii = expectedAsciiFragments.some((fragment) =>
    visible.includes(fragment),
  );
  if (hasMarker && (visible.includes("?") || QUESTION_RUN_PATTERN.test(visible))) {
    return true;
  }
  const expectedHasCjk = containsCjk(expectedProbe);
  if (
    carriesExpectedAscii &&
    expectedHasCjk &&
    !containsCjk(visible) &&
    (visible.includes("?") ||
      QUESTION_RUN_PATTERN.test(visible) ||
      containsCyrillic(visible))
  ) {
    return true;
  }
  return false;
}

function looksLikeMixedScriptNoise(reply, expectedProbe) {
  const visible = compactVisibleText(reply);
  if (!visible || !containsCjk(expectedProbe)) {
    return false;
  }
  const expectedAsciiFragments = expectedProbe.match(/[A-Za-z0-9]{3,}/g) ?? [];
  const carriesExpectedAscii = expectedAsciiFragments.some((fragment) =>
    visible.includes(fragment),
  );
  return carriesExpectedAscii && !containsCjk(visible) && containsCyrillic(visible);
}

function openAiChatPayload(prompt, systemPrompt) {
  return {
    model,
    messages: [
      {
        role: "system",
        content: systemPrompt,
      },
      {
        role: "user",
        content: prompt,
      },
    ],
    temperature: 0,
    max_tokens: probeOutputTokens,
    thinking: { type: "disabled" },
  };
}

function openAiResponsesPayload(prompt, systemPrompt) {
  return {
    model,
    instructions: systemPrompt,
    input: prompt,
    temperature: 0,
    max_output_tokens: probeOutputTokens,
  };
}

function anthropicPayload(prompt, systemPrompt) {
  return {
    model,
    system: systemPrompt,
    messages: [
      {
        role: "user",
        content: prompt,
      },
    ],
    max_tokens: probeOutputTokens,
    temperature: 0,
  };
}

function geminiPayload(prompt, systemPrompt) {
  return {
    systemInstruction: {
      parts: [{ text: systemPrompt }],
    },
    contents: [
      {
        role: "user",
        parts: [{ text: prompt }],
      },
    ],
    generationConfig: {
      temperature: 0,
      maxOutputTokens: probeOutputTokens,
    },
  };
}

async function readProtocolText(step, prompt, systemPrompt, diagnostics, modelIds, lastPreview) {
  if (protocol === "openai_responses") {
    const openAiBaseUrl = normalizedOpenAiCompatibleBaseUrl();
    const response = await readResponse(
      step,
      `${openAiBaseUrl}/responses`,
      {
        method: "POST",
        headers: openAiHeaders(),
        body: JSON.stringify(openAiResponsesPayload(prompt, systemPrompt)),
      },
      model,
    );
    if (response.failure) {
      throw Object.assign(new Error(response.failure.detail), {
        report: buildFailureReport({
          baseUrl,
          model,
          protocol,
          responseLanguage,
          modelIds,
          diagnostics,
          failure: response.failure,
          preview: lastPreview,
        }),
      });
    }
    return compactVisibleText(extractOpenAiResponsesContent(response.json));
  }

  if (protocol === "anthropic_messages") {
    const response = await readResponse(
      step,
      `${anthropicBaseUrl()}/v1/messages`,
      {
        method: "POST",
        headers: anthropicHeaders(),
        body: JSON.stringify(anthropicPayload(prompt, systemPrompt)),
      },
      model,
    );
    if (response.failure) {
      throw Object.assign(new Error(response.failure.detail), {
        report: buildFailureReport({
          baseUrl,
          model,
          protocol,
          responseLanguage,
          modelIds,
          diagnostics,
          failure: response.failure,
          preview: lastPreview,
        }),
      });
    }
    return compactVisibleText(extractAnthropicContent(response.json));
  }

  if (protocol === "gemini_generate_content" && isGoogleNativeGeminiBaseUrl()) {
    const response = await readResponse(
      step,
      geminiGenerateContentEndpoint(),
      {
        method: "POST",
        headers: geminiHeaders(),
        body: JSON.stringify(geminiPayload(prompt, systemPrompt)),
      },
      model,
    );
    if (response.failure) {
      throw Object.assign(new Error(response.failure.detail), {
        report: buildFailureReport({
          baseUrl,
          model,
          protocol,
          responseLanguage,
          modelIds,
          diagnostics,
          failure: response.failure,
          preview: lastPreview,
        }),
      });
    }
    return compactVisibleText(extractGeminiContent(response.json));
  }

  const openAiBaseUrl = normalizedOpenAiCompatibleBaseUrl();
  const response = await readResponse(
    step,
    `${openAiBaseUrl}/chat/completions`,
    {
      method: "POST",
      headers: openAiHeaders(),
      body: JSON.stringify(openAiChatPayload(prompt, systemPrompt)),
    },
    model,
  );
  if (response.failure) {
    throw Object.assign(new Error(response.failure.detail), {
      report: buildFailureReport({
        baseUrl,
        model,
        protocol,
        responseLanguage,
        modelIds,
        diagnostics,
        failure: response.failure,
        preview: lastPreview,
      }),
    });
  }
  return compactVisibleText(extractOpenAiChatContent(response.json));
}

async function runNaturalZhProbe(diagnostics, modelIds, lastPreview) {
  const preview = await readProtocolText(
    "chat",
    naturalZhProbe,
    "Reply in Chinese only. Keep required phrases exactly. Do not explain or add quotes.",
    diagnostics,
    modelIds,
    lastPreview,
  );
  const sanitizedPreview = stripReasoningBlocks(preview);
  if (preview.includes("<think>")) {
    diagnostics.push(
      "Raw provider response included <think>; continuing with sanitized visible text because Trainer strips reasoning blocks before display.",
    );
  }
  if (!sanitizedPreview) {
    return { ok: false };
  }
  if (
    looksLikeInputCorruptionReply(sanitizedPreview, naturalZhProbe) ||
    looksLikeMixedScriptNoise(sanitizedPreview, naturalZhProbe)
  ) {
    return { ok: false };
  }
  if (!containsCjk(sanitizedPreview)) {
    return { ok: false };
  }
  if (!naturalZhFragments.every((fragment) => sanitizedPreview.includes(fragment))) {
    return { ok: false };
  }
  return {
    ok: true,
    preview: sanitizedPreview,
    kind: "natural_language_fallback",
  };
}

function normalizeModelIds(items) {
  return items
    .map((item) => {
      if (typeof item === "string") {
        return item.trim();
      }
      if (item && typeof item === "object") {
        if (typeof item.id === "string") {
          return item.id.trim();
        }
        if (typeof item.name === "string") {
          return item.name.replace(/^models\//, "").trim();
        }
      }
      return "";
    })
    .filter(Boolean);
}

async function listModelsOpenAiCompatible(diagnostics) {
  const openAiBaseUrl = normalizedOpenAiCompatibleBaseUrl();
  if (openAiBaseUrl !== baseUrl) {
    diagnostics.push(
      `Normalized ${protocol} base URL to ${openAiBaseUrl} for OpenAI-compatible models and chat surfaces.`,
    );
  }
  const models = await readResponse(
    "models",
    `${openAiBaseUrl}/models`,
    { headers: openAiHeaders() },
    model,
  );
  if (models.failure) {
    throw Object.assign(new Error(models.failure.detail), {
      report: buildFailureReport({
        baseUrl,
        model,
        protocol,
        responseLanguage,
        modelIds: [],
        diagnostics,
        failure: models.failure,
      }),
    });
  }
  if (!Array.isArray(models.json?.data)) {
    const failure = {
      step: "models",
      category: "malformed_response",
      detail: "models.data must be an array.",
    };
    throw Object.assign(new Error(failure.detail), {
      report: buildFailureReport({
        baseUrl,
        model,
        protocol,
        responseLanguage,
        modelIds: [],
        diagnostics,
        failure,
      }),
    });
  }
  return normalizeModelIds(models.json.data);
}

async function assertModelCatalog(diagnostics) {
  let modelIds;
  if (protocol === "anthropic_messages") {
    diagnostics.push("Using native anthropic_messages model listing.");
    const models = await readResponse(
      "models",
      `${anthropicBaseUrl()}/v1/models`,
      { headers: anthropicHeaders() },
      model,
    );
    if (models.failure) {
      throw Object.assign(new Error(models.failure.detail), {
        report: buildFailureReport({
          baseUrl,
          model,
          protocol,
          responseLanguage,
          modelIds: [],
          diagnostics,
          failure: models.failure,
        }),
      });
    }
    if (!Array.isArray(models.json?.data)) {
      const failure = {
        step: "models",
        category: "malformed_response",
        detail: "models.data must be an array.",
      };
      throw Object.assign(new Error(failure.detail), {
        report: buildFailureReport({
          baseUrl,
          model,
          protocol,
          responseLanguage,
          modelIds: [],
          diagnostics,
          failure,
        }),
      });
    }
    modelIds = normalizeModelIds(models.json.data);
  } else if (protocol === "gemini_generate_content" && isGoogleNativeGeminiBaseUrl()) {
    diagnostics.push("Using native gemini_generate_content model listing.");
    const models = await readResponse(
      "models",
      geminiModelsEndpoint(),
      { headers: geminiHeaders() },
      model,
    );
    if (models.failure) {
      throw Object.assign(new Error(models.failure.detail), {
        report: buildFailureReport({
          baseUrl,
          model,
          protocol,
          responseLanguage,
          modelIds: [],
          diagnostics,
          failure: models.failure,
        }),
      });
    }
    if (!Array.isArray(models.json?.models)) {
      const failure = {
        step: "models",
        category: "malformed_response",
        detail: "models must be an array.",
      };
      throw Object.assign(new Error(failure.detail), {
        report: buildFailureReport({
          baseUrl,
          model,
          protocol,
          responseLanguage,
          modelIds: [],
          diagnostics,
          failure,
        }),
      });
    }
    modelIds = normalizeModelIds(models.json.models);
  } else {
    if (protocol === "gemini_generate_content") {
      diagnostics.push(
        "Protocol gemini_generate_content is pointed at a non-Google gateway; using OpenAI-compatible /models for this smoke.",
      );
    } else if (protocol === "openai_responses") {
      diagnostics.push("Using OpenAI-compatible /models for openai_responses smoke.");
    } else {
      diagnostics.push(`Using OpenAI-compatible /models for ${protocol} smoke.`);
    }
    modelIds = await listModelsOpenAiCompatible(diagnostics);
  }

  if (modelIds.length === 0) {
    const failure = {
      step: "models",
      category: "empty_model_catalog",
      detail: "The provider returned an empty model list.",
    };
    throw Object.assign(new Error(failure.detail), {
      report: buildFailureReport({
        baseUrl,
        model,
        protocol,
        responseLanguage,
        modelIds,
        diagnostics,
        failure,
      }),
    });
  }
  if (!modelIds.includes(model)) {
    const failure = {
      step: "models",
      category: "model_missing_from_catalog",
      detail: `${model} was not present in the provider model list.`,
    };
    throw Object.assign(new Error(failure.detail), {
      report: buildFailureReport({
        baseUrl,
        model,
        protocol,
        responseLanguage,
        modelIds,
        diagnostics,
        failure,
      }),
    });
  }
  return modelIds;
}

async function runProtocolProbe(diagnostics, modelIds) {
  const probeVariants = buildProbeVariants(responseLanguage);
  let lastPreview = "";
  let lastFailure;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    let naturalFallbackAttempted = false;

    for (const probe of probeVariants) {
      const acceptedReplies = acceptedRepliesForProbe(probe);
      const rawPreview = await readProtocolText(
        "chat",
        probe.prompt,
        "Return exactly the requested text. Do not explain or add quotes.",
        diagnostics,
        modelIds,
        lastPreview,
      );
      const preview = stripReasoningBlocks(rawPreview);
      if (rawPreview.includes("<think>")) {
        diagnostics.push(
          "Raw provider response included <think>; continuing with sanitized visible text because Trainer strips reasoning blocks before display.",
        );
      }
      lastPreview = preview;

      if (!preview) {
        lastFailure = {
          step: "chat",
          category: "reasoning_leak",
          detail: "Protocol probe returned only hidden reasoning and no usable visible text.",
        };
        if (prefersChinese(responseLanguage) && !naturalFallbackAttempted) {
          naturalFallbackAttempted = true;
          const fallback = await runNaturalZhProbe(diagnostics, modelIds, lastPreview);
          if (fallback.ok) {
            return fallback.preview;
          }
        }
        continue;
      }

      if (acceptedReplies.some((accepted) => preview.includes(accepted))) {
        return lastPreview;
      }

      if (
        looksLikeInputCorruptionReply(preview, probe.expected) ||
        looksLikeMixedScriptNoise(preview, probe.expected)
      ) {
        const failure = {
          step: "chat",
          category: "language_corruption",
          detail: probe.failureDetail,
        };
        throw Object.assign(new Error(failure.detail), {
          report: buildFailureReport({
            baseUrl,
            model,
            protocol,
            responseLanguage,
            modelIds,
            diagnostics,
            failure,
            preview: lastPreview,
          }),
        });
      }

      if (prefersChinese(responseLanguage) && !naturalFallbackAttempted) {
        naturalFallbackAttempted = true;
        const fallback = await runNaturalZhProbe(diagnostics, modelIds, lastPreview);
        if (fallback.ok) {
          return fallback.preview;
        }
      }

      lastFailure = {
        step: "chat",
        category: "language_probe_inconclusive",
        detail: probe.inconclusiveDetail,
      };
    }
  }

  const failure = lastFailure ?? {
    step: "chat",
    category: "language_probe_inconclusive",
    detail: "Language integrity probe returned no usable signal after connectivity succeeded.",
  };
  throw Object.assign(new Error(failure.detail), {
    report: buildFailureReport({
      baseUrl,
      model,
      protocol,
      responseLanguage,
      modelIds,
      diagnostics,
      failure,
      preview: lastPreview,
    }),
  });
}

async function main() {
  const missingConfiguration = [];
  if (!apiKey) {
    missingConfiguration.push("TRAINER_PROVIDER_SMOKE_API_KEY");
  }
  if (!(process.env.TRAINER_PROVIDER_SMOKE_BASE_URL ?? "").trim()) {
    missingConfiguration.push("TRAINER_PROVIDER_SMOKE_BASE_URL");
  }
  if (!(process.env.TRAINER_PROVIDER_SMOKE_MODEL ?? "").trim()) {
    missingConfiguration.push("TRAINER_PROVIDER_SMOKE_MODEL");
  }
  if (missingConfiguration.length > 0) {
    console.error(
      JSON.stringify(
        {
          ok: false,
          category: "configuration_missing",
          missing: missingConfiguration,
          elapsedMs: elapsedMs(),
        },
        null,
        2,
      ),
    );
    process.exitCode = 1;
    return;
  }

  const diagnostics = [`protocol=${protocol}`];
  const modelIds = await assertModelCatalog(diagnostics);
  const preview = await runProtocolProbe(diagnostics, modelIds);

  console.log(
    JSON.stringify(
      {
        ok: true,
        category: "success",
        model,
        protocol,
        elapsedMs: elapsedMs(),
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  const report = error && typeof error === "object" ? error.report : undefined;
  console.error(
    JSON.stringify(
      report ?? {
        ok: false,
        category: "unexpected_error",
        model,
        protocol,
        elapsedMs: elapsedMs(),
      },
      null,
      2,
    ),
  );
  process.exitCode = 1;
});
