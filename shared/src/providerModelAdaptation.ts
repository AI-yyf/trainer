/**
 * Model-aware capability guidance.
 *
 * This is deliberately advisory: a model name can suggest which controls are
 * worth surfacing and what thinking effort to start from, but it is never
 * treated as verified capability evidence. The settings UI keeps observed
 * capability chips separate from these suggestions.
 */

export type ProviderModelFamily =
  | "openai"
  | "anthropic"
  | "deepseek"
  | "glm"
  | "minimax"
  | "qwen"
  | "gemini"
  | "kimi"
  | "unknown";

export type ProviderModelAdaptationConfidence = "known" | "inferred" | "unknown";

export interface ProviderModelAdaptation {
  family: ProviderModelFamily;
  confidence: ProviderModelAdaptationConfidence;
  supportsTools: boolean;
  supportsVision: boolean;
  supportsThinking: boolean;
  /** Suggested starting effort when the protocol carries reasoning_effort. */
  suggestedEffort?: "low" | "medium" | "high";
  reason: string;
}

export interface ProviderModelAdaptationInput {
  model: string;
  protocol?: string;
  baseUrl?: string;
  providerName?: string;
}

function normalized(value: string | undefined): string {
  return String(value ?? "").trim().toLowerCase();
}

function has(value: string, ...needles: string[]): boolean {
  return needles.some((needle) => value.includes(needle));
}

export function inferProviderModelFamily(input: ProviderModelAdaptationInput): ProviderModelFamily {
  const model = normalized(input.model);
  const provider = normalized(input.providerName);
  const baseUrl = normalized(input.baseUrl);
  const haystack = `${model} ${provider} ${baseUrl}`;
  if (has(haystack, "deepseek")) return "deepseek";
  if (has(haystack, "claude", "anthropic")) return "anthropic";
  if (has(haystack, "glm", "zhipu", "bigmodel")) return "glm";
  if (has(haystack, "minimax")) return "minimax";
  if (has(haystack, "qwen", "qianwen", "dashscope", "tongyi")) return "qwen";
  if (has(haystack, "gemini", "google")) return "gemini";
  if (has(haystack, "kimi", "moonshot")) return "kimi";
  if (has(haystack, "gpt", "openai", "o1", "o3", "o4", "chatgpt")) return "openai";
  return "unknown";
}

/**
 * Infer a conservative starting configuration from the model family and name.
 * Unknown models keep tools/vision/thinking off until a real test observes
 * them; known families still say "test to confirm" in the UI.
 */
export function inferProviderModelAdaptation(
  input: ProviderModelAdaptationInput,
): ProviderModelAdaptation {
  const model = normalized(input.model);
  const family = inferProviderModelFamily(input);
  if (!model) {
    return {
      family: "unknown",
      confidence: "unknown",
      supportsTools: false,
      supportsVision: false,
      supportsThinking: false,
      reason: "No model selected yet.",
    };
  }

  const visionModel = has(model, "vl", "vision", "4v", "4.5v", "4.6v", "omni");
  const reasoningModel = has(
    model,
    "reason",
    "thinking",
    "r1",
    "o1",
    "o3",
    "o4",
    "gpt-5",
    "m1",
    "m2",
    "m3",
    "glm-4.5",
    "glm-4.6",
    "glm-5",
    "qwen3",
    "k2",
    "k3",
  );

  const base = (flags: Omit<ProviderModelAdaptation, "family" | "confidence" | "reason">, reason: string): ProviderModelAdaptation => ({
    ...flags,
    family,
    confidence: "known",
    reason,
  });

  switch (family) {
    case "deepseek":
      return base(
        {
          supportsTools: true,
          supportsVision: visionModel,
          supportsThinking: reasoningModel || has(model, "v4"),
          suggestedEffort: "medium",
        },
        "DeepSeek family: tools are advertised; the v4/reasoner line can carry thinking.",
      );
    case "anthropic":
      return base(
        {
          supportsTools: true,
          supportsVision: true,
          supportsThinking: has(model, "3-7", "3.7", "4", "sonnet", "opus"),
          suggestedEffort: "high",
        },
        "Claude family: tools and vision are standard; extended thinking is model-version dependent.",
      );
    case "glm":
      return base(
        {
          supportsTools: true,
          supportsVision: visionModel,
          supportsThinking: reasoningModel || has(model, "glm-4.5", "glm-4.6", "glm-5"),
          suggestedEffort: "medium",
        },
        "GLM family: tools are standard; vision and thinking follow the model suffix.",
      );
    case "minimax":
      return base(
        {
          supportsTools: true,
          supportsVision: visionModel,
          supportsThinking: reasoningModel || has(model, "m1", "m2", "m3"),
          suggestedEffort: "medium",
        },
        "MiniMax family: reasoning models can carry a thinking switch; vision needs a VL model.",
      );
    case "qwen":
      return base(
        {
          supportsTools: true,
          supportsVision: visionModel,
          supportsThinking: reasoningModel || has(model, "qwen3"),
          suggestedEffort: "medium",
        },
        "Qwen family: tools are standard; VL models add vision and Qwen3 adds thinking.",
      );
    case "gemini":
      return base(
        {
          supportsTools: true,
          supportsVision: true,
          supportsThinking: has(model, "2.5", "3"),
          suggestedEffort: "high",
        },
        "Gemini family: tools and vision are standard; newer models can expose thinking effort.",
      );
    case "kimi":
      return base(
        {
          supportsTools: true,
          supportsVision: visionModel,
          supportsThinking: reasoningModel || has(model, "k2", "k3"),
          suggestedEffort: "medium",
        },
        "Kimi family: tools are standard; K2/K3 reasoning models can carry thinking.",
      );
    case "openai":
      return base(
        {
          supportsTools: true,
          supportsVision: true,
          supportsThinking: has(model, "o1", "o3", "o4", "gpt-5"),
          suggestedEffort: has(model, "o3", "o4", "gpt-5") ? "high" : "medium",
        },
        "OpenAI family: tools and vision are standard; o-series/GPT-5 add reasoning effort.",
      );
    default:
      return {
        family,
        confidence: "unknown",
        supportsTools: false,
        supportsVision: false,
        supportsThinking: false,
        reason: "Unknown model family; keep capabilities off until a real test observes them.",
      };
  }
}

const NON_CHAT_MODEL_MARKERS = [
  "embed",
  "embedding",
  "tts",
  "whisper",
  "audio",
  "speech",
  "rerank",
  "moderation",
  "dall-e",
  "image",
  "video",
  "ocr",
];

/** Prefer an actual chat model from a fetched /models list. */
export function recommendProviderModel(
  models: readonly string[],
  input: Omit<ProviderModelAdaptationInput, "model">,
): string | undefined {
  const candidates = models
    .map((value) => value.trim())
    .filter(Boolean)
    .filter((value) => {
      const lower = value.toLowerCase();
      return !NON_CHAT_MODEL_MARKERS.some((marker) => lower.includes(marker));
    });
  if (candidates.length === 0) {
    return undefined;
  }
  const desiredFamily = inferProviderModelFamily({ ...input, model: "" });
  const sameFamily = candidates.filter(
    (value) => inferProviderModelFamily({ ...input, model: value }) === desiredFamily,
  );
  const pool = sameFamily.length > 0 ? sameFamily : candidates;
  const preferred = pool.find((value) => {
    const lower = value.toLowerCase();
    return !has(lower, "preview", "beta", "experimental");
  });
  return preferred ?? pool[0];
}
