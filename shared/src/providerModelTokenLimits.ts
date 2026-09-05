import type { ProviderModelTokenLimit } from "./models";

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function toPositiveNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}

function sortModelTokenLimits(
  limits: Record<string, ProviderModelTokenLimit>,
): Record<string, ProviderModelTokenLimit> {
  return Object.fromEntries(
    Object.entries(limits).sort(([left], [right]) => left.localeCompare(right, undefined, { sensitivity: "base" })),
  );
}

export function normalizeProviderModelTokenLimits(
  value: unknown,
): Record<string, ProviderModelTokenLimit> | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const normalized: Record<string, ProviderModelTokenLimit> = {};
  for (const [rawModel, rawLimit] of Object.entries(record)) {
    const model = rawModel.trim();
    const limitRecord = asRecord(rawLimit);
    if (!model || !limitRecord) {
      continue;
    }

    const contextWindowTokens = toPositiveNumber(
      limitRecord.contextWindowTokens ?? limitRecord.context_window_tokens,
    );
    const maxOutputTokens = toPositiveNumber(
      limitRecord.maxOutputTokens ?? limitRecord.max_output_tokens,
    );

    if (contextWindowTokens === undefined && maxOutputTokens === undefined) {
      continue;
    }

    normalized[model] = {
      ...(contextWindowTokens !== undefined ? { contextWindowTokens } : {}),
      ...(maxOutputTokens !== undefined ? { maxOutputTokens } : {}),
    };
  }

  return Object.keys(normalized).length > 0 ? sortModelTokenLimits(normalized) : undefined;
}

export function readProviderModelTokenLimit(
  limits: Record<string, ProviderModelTokenLimit> | undefined,
  model: string | undefined,
): ProviderModelTokenLimit | undefined {
  const normalizedModel = model?.trim();
  if (!normalizedModel) {
    return undefined;
  }
  return normalizeProviderModelTokenLimits(limits)?.[normalizedModel];
}

export function withProviderModelTokenLimit(
  limits: Record<string, ProviderModelTokenLimit> | undefined,
  model: string | undefined,
  next: ProviderModelTokenLimit | undefined,
): Record<string, ProviderModelTokenLimit> | undefined {
  const normalizedModel = model?.trim();
  const normalizedLimits = { ...(normalizeProviderModelTokenLimits(limits) ?? {}) };
  if (!normalizedModel) {
    return Object.keys(normalizedLimits).length > 0 ? normalizedLimits : undefined;
  }

  const contextWindowTokens = toPositiveNumber(next?.contextWindowTokens);
  const maxOutputTokens = toPositiveNumber(next?.maxOutputTokens);

  if (contextWindowTokens === undefined && maxOutputTokens === undefined) {
    delete normalizedLimits[normalizedModel];
  } else {
    normalizedLimits[normalizedModel] = {
      ...(contextWindowTokens !== undefined ? { contextWindowTokens } : {}),
      ...(maxOutputTokens !== undefined ? { maxOutputTokens } : {}),
    };
  }

  return Object.keys(normalizedLimits).length > 0 ? sortModelTokenLimits(normalizedLimits) : undefined;
}

export function providerModelTokenLimitsKey(
  limits: Record<string, ProviderModelTokenLimit> | undefined,
): string {
  return JSON.stringify(normalizeProviderModelTokenLimits(limits) ?? {});
}

export function mergeProviderModelTokenLimits(
  preferred: Record<string, ProviderModelTokenLimit> | undefined,
  fallback: Record<string, ProviderModelTokenLimit> | undefined,
): Record<string, ProviderModelTokenLimit> | undefined {
  const normalizedPreferred = normalizeProviderModelTokenLimits(preferred);
  const normalizedFallback = normalizeProviderModelTokenLimits(fallback);

  if (!normalizedPreferred && !normalizedFallback) {
    return undefined;
  }

  const merged: Record<string, ProviderModelTokenLimit> = {
    ...(normalizedFallback ?? {}),
  };

  for (const [model, limit] of Object.entries(normalizedPreferred ?? {})) {
    merged[model] = {
      ...(merged[model] ?? {}),
      ...limit,
    };
  }

  return Object.keys(merged).length > 0 ? sortModelTokenLimits(merged) : undefined;
}

export function resolveProviderModelTokenState(
  existing:
    | {
        model?: string;
        contextWindowTokens?: number;
        maxOutputTokens?: number;
        modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
      }
    | undefined,
  model: string | undefined,
  options?: {
    modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
    hasModelTokenLimits?: boolean;
    contextWindowTokens?: number | null;
    maxOutputTokens?: number | null;
    hasContextWindowTokens?: boolean;
    hasMaxOutputTokens?: boolean;
  },
): {
  modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  contextWindowTokens?: number;
  maxOutputTokens?: number;
} {
  const normalizedModel = model?.trim();
  const baseLimits =
    options?.hasModelTokenLimits
      ? normalizeProviderModelTokenLimits(options.modelTokenLimits)
      : normalizeProviderModelTokenLimits(options?.modelTokenLimits) ??
        normalizeProviderModelTokenLimits(existing?.modelTokenLimits);
  const savedLimit = readProviderModelTokenLimit(baseLimits, normalizedModel);
  const matchesExistingModel = normalizedModel !== undefined && existing?.model?.trim() === normalizedModel;

  const contextWindowTokens = options?.hasContextWindowTokens
    ? toPositiveNumber(options.contextWindowTokens ?? undefined)
    : savedLimit?.contextWindowTokens ?? (matchesExistingModel ? existing?.contextWindowTokens : undefined);
  const maxOutputTokens = options?.hasMaxOutputTokens
    ? toPositiveNumber(options.maxOutputTokens ?? undefined)
    : savedLimit?.maxOutputTokens ?? (matchesExistingModel ? existing?.maxOutputTokens : undefined);

  return {
    contextWindowTokens,
    maxOutputTokens,
    modelTokenLimits: withProviderModelTokenLimit(baseLimits, normalizedModel, {
      contextWindowTokens,
      maxOutputTokens,
    }),
  };
}

export function applyProviderModelSelection<
  T extends {
    model?: string;
    contextWindowTokens?: number;
    maxOutputTokens?: number;
    modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  },
>(existing: T, model: string | undefined): T {
  const normalizedModel = model?.trim() || existing.model?.trim();
  const tokenState = resolveProviderModelTokenState(existing, normalizedModel, {
    hasContextWindowTokens: false,
    hasMaxOutputTokens: false,
    hasModelTokenLimits: false,
  });

  return {
    ...existing,
    ...(normalizedModel ? { model: normalizedModel } : {}),
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    modelTokenLimits: tokenState.modelTokenLimits,
  };
}

export function applyProviderModelCatalog<
  T extends {
    model?: string;
    contextWindowTokens?: number;
    maxOutputTokens?: number;
    modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  },
>(
  existing: T,
  options?: {
    resolvedModel?: string;
    modelTokenLimits?: Record<string, ProviderModelTokenLimit>;
  },
): T {
  const normalizedModel = options?.resolvedModel?.trim() || existing.model?.trim();
  const mergedModelTokenLimits = mergeProviderModelTokenLimits(
    existing.modelTokenLimits,
    options?.modelTokenLimits,
  );
  const tokenState = resolveProviderModelTokenState(existing, normalizedModel, {
    modelTokenLimits: mergedModelTokenLimits,
    hasModelTokenLimits: true,
    hasContextWindowTokens: false,
    hasMaxOutputTokens: false,
  });

  return {
    ...existing,
    ...(normalizedModel ? { model: normalizedModel } : {}),
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    modelTokenLimits: tokenState.modelTokenLimits,
  };
}
