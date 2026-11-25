import type { ProviderProtocol } from "./models";
import { inferProviderModelFamily, type ProviderModelFamily } from "./providerModelAdaptation";
import { normalizeProviderProtocol } from "./providerProtocols";

/**
 * Default context window and output budgets in the 1M-context era.
 * Used as the smart runtime/display baseline whenever neither the user nor
 * the provider catalog pinned a narrower model limit.
 */
export const DEFAULT_SMART_CONTEXT_WINDOW_TOKENS = 1_000_000;
export const DEFAULT_SMART_MAX_OUTPUT_TOKENS = 65_536;

export const SMART_CONTEXT_WINDOW_PRESETS = [
  131_072,
  262_144,
  524_288,
  1_000_000,
  2_000_000,
] as const;

export const SMART_MAX_OUTPUT_PRESETS = [
  16_384,
  32_768,
  65_536,
  131_072,
  262_144,
] as const;

export interface SmartModelTokenDefaults {
  family: ProviderModelFamily;
  contextWindowTokens: number;
  maxOutputTokens: number;
  inferredFromModel: boolean;
}

export interface SmartThinkingBudgetPlan {
  min: number;
  max: number;
  low: number;
  medium: number;
  high: number;
  recommendedCustom: number;
  presets: number[];
  visibleReplyReserve: number;
  cappedBy: "output" | "context" | "protocol";
}

export interface SmartTokenBudgetProfile {
  family: ProviderModelFamily;
  effectiveContextWindowTokens: number;
  effectiveMaxOutputTokens: number;
  contextSource: "configured" | "model" | "default";
  outputSource: "configured" | "model" | "default";
  thinkingBudget: SmartThinkingBudgetPlan;
}

function toPositiveInt(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : undefined;
}

/**
 * Format a context-window or output limit cleanly without the 1,000,000 -> 977K
 * binary division glitch.
 */
export function formatCompactTokenLimit(value: number | undefined): string {
  const tokens = toPositiveInt(value);
  if (tokens === undefined) {
    return "";
  }
  if (tokens === 1_000_000 || tokens === 1_048_576) {
    return "1M";
  }
  if (tokens === 2_000_000 || tokens === 2_097_152) {
    return "2M";
  }
  if (tokens >= 1_000_000) {
    if (tokens % 1_048_576 === 0) {
      return `${tokens / 1_048_576}M`;
    }
    if (tokens % 1_000_000 === 0) {
      return `${tokens / 1_000_000}M`;
    }
    return `${Number((tokens / 1_000_000).toFixed(1))}M`;
  }
  if (tokens >= 1024 && tokens % 1024 === 0) {
    return `${tokens / 1024}K`;
  }
  if (tokens >= 1000 && tokens % 1000 === 0) {
    return `${tokens / 1000}K`;
  }
  if (tokens >= 1000) {
    return `${Math.round(tokens / 1000)}K`;
  }
  return String(tokens);
}

/**
 * Infer smart default context & output limits for modern models when the catalog
 * does not explicitly report limits. Defaults to 1M context rather than legacy 128K.
 */
export function inferModelDefaultTokenLimits(input: {
  model?: string;
  protocol?: ProviderProtocol | string;
  providerName?: string;
  baseUrl?: string;
}): SmartModelTokenDefaults {
  const model = String(input.model ?? "").trim().toLowerCase();
  const protocol = normalizeProviderProtocol(input.protocol);
  const family = inferProviderModelFamily({
    model,
    protocol: protocol ?? undefined,
    providerName: input.providerName,
    baseUrl: input.baseUrl,
  });

  switch (family) {
    case "minimax":
      return {
        family,
        contextWindowTokens: 1_000_000,
        maxOutputTokens: 131_072,
        inferredFromModel: Boolean(model),
      };
    case "gemini":
      return {
        family,
        contextWindowTokens: 1_048_576,
        maxOutputTokens: 65_536,
        inferredFromModel: Boolean(model),
      };
    case "openai":
      if (/\b(?:o1|o3|o4)\b/.test(model)) {
        return {
          family,
          contextWindowTokens: 200_000,
          maxOutputTokens: 100_000,
          inferredFromModel: true,
        };
      }
      if (model.includes("gpt-4o")) {
        return {
          family,
          contextWindowTokens: 128_000,
          maxOutputTokens: 16_384,
          inferredFromModel: true,
        };
      }
      return {
        family,
        contextWindowTokens: 1_000_000,
        maxOutputTokens: 131_072,
        inferredFromModel: Boolean(model),
      };
    case "anthropic":
      if (/(?:3[.-]?5|3[.-]?7)/.test(model)) {
        return {
          family,
          contextWindowTokens: 200_000,
          maxOutputTokens: 64_000,
          inferredFromModel: true,
        };
      }
      return {
        family,
        contextWindowTokens: 1_000_000,
        maxOutputTokens: 65_536,
        inferredFromModel: Boolean(model),
      };
    case "qwen":
      return {
        family,
        contextWindowTokens: 1_000_000,
        maxOutputTokens: 65_536,
        inferredFromModel: Boolean(model),
      };
    case "kimi":
      return {
        family,
        contextWindowTokens: 1_000_000,
        maxOutputTokens: 65_536,
        inferredFromModel: Boolean(model),
      };
    case "glm":
      if (/(?:4[.-]?5|4[.-]?6)/.test(model)) {
        return {
          family,
          contextWindowTokens: 200_000,
          maxOutputTokens: 98_304,
          inferredFromModel: true,
        };
      }
      return {
        family,
        contextWindowTokens: 1_000_000,
        maxOutputTokens: 131_072,
        inferredFromModel: Boolean(model),
      };
    case "deepseek":
      if (!model.includes("v4") && model.length > 0) {
        return {
          family,
          contextWindowTokens: 131_072,
          maxOutputTokens: 65_536,
          inferredFromModel: true,
        };
      }
      return {
        family,
        contextWindowTokens: 1_000_000,
        maxOutputTokens: 65_536,
        inferredFromModel: Boolean(model),
      };
    default:
      return {
        family,
        contextWindowTokens: DEFAULT_SMART_CONTEXT_WINDOW_TOKENS,
        maxOutputTokens: DEFAULT_SMART_MAX_OUTPUT_TOKENS,
        inferredFromModel: false,
      };
  }
}

function alignPresetTokenValue(value: number): number {
  if (value >= 2048) {
    return Math.max(1024, Math.floor(value / 1024) * 1024);
  }
  return Math.max(512, Math.floor(value / 256) * 256);
}

function buildAdaptiveThinkingPresets(safeMax: number, min: number): number[] {
  let base: number[];
  if (safeMax >= 196_608) {
    base = [16_384, 32_768, 65_536, 131_072, alignPresetTokenValue(safeMax)];
  } else if (safeMax >= 122_880) {
    base = [8_192, 16_384, 32_768, 65_536, alignPresetTokenValue(safeMax)];
  } else if (safeMax >= 57_344) {
    base = [4_096, 8_192, 16_384, 32_768, alignPresetTokenValue(safeMax)];
  } else if (safeMax >= 28_672) {
    base = [2_048, 4_096, 8_192, 16_384, alignPresetTokenValue(safeMax)];
  } else {
    const standard = [1_024, 2_048, 4_096, 8_192, 16_384].filter(
      (value) => value >= min && value <= safeMax,
    );
    const alignedCap = alignPresetTokenValue(safeMax);
    const last = standard[standard.length - 1] ?? 0;
    if (alignedCap >= min && alignedCap <= safeMax && alignedCap - last >= 1024) {
      standard.push(alignedCap);
    }
    base = standard.length > 0 ? standard : [safeMax];
  }

  const unique: number[] = [];
  for (const item of base) {
    const clamped = Math.max(min, Math.min(safeMax, item));
    if (!unique.includes(clamped)) {
      unique.push(clamped);
    }
  }
  return unique.sort((left, right) => left - right).slice(0, 5);
}

/**
 * Compute adaptive context window, max output, and safe thinking token budgets
 * so thinking never starves visible reply capacity.
 */
export function resolveEffectiveTokenBudgetProfile(input: {
  protocol?: ProviderProtocol | string;
  model?: string;
  providerName?: string;
  baseUrl?: string;
  configuredContextWindowTokens?: number;
  configuredMaxOutputTokens?: number;
  protocolBudgetMax?: number;
}): SmartTokenBudgetProfile {
  const protocol = normalizeProviderProtocol(input.protocol);
  const inferred = inferModelDefaultTokenLimits({
    model: input.model,
    protocol: protocol ?? undefined,
    providerName: input.providerName,
    baseUrl: input.baseUrl,
  });

  const configuredContext = toPositiveInt(input.configuredContextWindowTokens);
  const configuredOutput = toPositiveInt(input.configuredMaxOutputTokens);

  const effectiveContextWindowTokens = configuredContext ?? inferred.contextWindowTokens;
  const effectiveMaxOutputTokens = Math.min(
    effectiveContextWindowTokens,
    configuredOutput ?? inferred.maxOutputTokens,
  );

  const contextSource: "configured" | "model" | "default" = configuredContext
    ? "configured"
    : inferred.inferredFromModel
      ? "model"
      : "default";
  const outputSource: "configured" | "model" | "default" = configuredOutput
    ? "configured"
    : inferred.inferredFromModel
      ? "model"
      : "default";

  const protocolCap =
    toPositiveInt(input.protocolBudgetMax) ??
    (protocol === "gemini_generate_content" ? 65_536 : 262_144);
  const visibleReplyReserve =
    effectiveMaxOutputTokens > 2048
      ? Math.min(8_192, Math.max(1_024, Math.floor(effectiveMaxOutputTokens * 0.125)))
      : Math.max(256, Math.floor(effectiveMaxOutputTokens * 0.25));

  const outputCeiling = Math.max(512, effectiveMaxOutputTokens - visibleReplyReserve);
  const contextCeiling = Math.max(1_024, Math.floor(effectiveContextWindowTokens * 0.25));
  const safeMax = Math.max(512, Math.min(protocolCap, outputCeiling, contextCeiling));

  const cappedBy: "output" | "context" | "protocol" =
    outputCeiling <= protocolCap && outputCeiling <= contextCeiling
      ? "output"
      : contextCeiling <= protocolCap
        ? "context"
        : "protocol";

  const min = 1;
  const presets = buildAdaptiveThinkingPresets(safeMax, min);

  const pickNearestAtOrBelow = (target: number): number => {
    let best = presets[0] ?? Math.min(safeMax, target);
    for (const candidate of presets) {
      if (candidate <= target) {
        best = candidate;
      }
    }
    return Math.min(safeMax, best);
  };

  const lowTarget = safeMax >= 32_768 ? 4_096 : safeMax >= 8_192 ? 2_048 : 1_024;
  const mediumTarget = safeMax >= 65_536 ? 16_384 : safeMax >= 16_384 ? 8_192 : Math.floor(safeMax * 0.5);
  const highTarget = safeMax >= 122_880 ? 65_536 : safeMax >= 32_768 ? 16_384 : Math.floor(safeMax * 0.85);

  const low = pickNearestAtOrBelow(lowTarget);
  const mediumCandidate = pickNearestAtOrBelow(mediumTarget);
  const nextPresetAbove = (floor: number): number | undefined =>
    presets.find((candidate) => candidate > floor && candidate <= safeMax);
  const medium =
    mediumCandidate > low
      ? mediumCandidate
      : nextPresetAbove(low) ?? Math.max(low, mediumCandidate);
  const highCandidate = pickNearestAtOrBelow(highTarget);
  const high =
    highCandidate > medium
      ? highCandidate
      : nextPresetAbove(medium) ?? Math.max(medium, highCandidate);
  const recommendedCustom =
    presets.find((value) => value >= medium && value < high) ?? medium;

  return {
    family: inferred.family,
    effectiveContextWindowTokens,
    effectiveMaxOutputTokens,
    contextSource,
    outputSource,
    thinkingBudget: {
      min,
      max: safeMax,
      low,
      medium,
      high,
      recommendedCustom,
      presets,
      visibleReplyReserve,
      cappedBy,
    },
  };
}
