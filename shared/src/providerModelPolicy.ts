export interface ProviderModelPolicy {
  allowedModels?: readonly string[];
  deniedModels?: readonly string[];
}

export type ProviderModelPolicyReason = "allowed" | "empty" | "not_allowed" | "denied";

export interface ProviderModelPolicyEvaluation {
  model: string;
  allowed: boolean;
  reason: ProviderModelPolicyReason;
}

export interface FilterProviderModelOptionsOptions {
  retainModels?: readonly string[];
}

function normalizedModelKey(value: string | undefined): string {
  return value?.trim().toLowerCase() ?? "";
}

function modelKeySet(models: readonly string[] | undefined): Set<string> {
  return new Set((models ?? []).map(normalizedModelKey).filter(Boolean));
}

/**
 * Evaluates a model against the connection's configured allow and deny lists.
 * Denied models always stay blocked, including when the same name is allowed.
 */
export function evaluateProviderModelPolicy(
  model: string | undefined,
  policy: ProviderModelPolicy = {},
): ProviderModelPolicyEvaluation {
  const normalizedModel = model?.trim() ?? "";
  const key = normalizedModelKey(normalizedModel);
  if (!key) {
    return { model: normalizedModel, allowed: false, reason: "empty" };
  }

  const deniedModels = modelKeySet(policy.deniedModels);
  if (deniedModels.has(key)) {
    return { model: normalizedModel, allowed: false, reason: "denied" };
  }

  const allowedModels = modelKeySet(policy.allowedModels);
  if (allowedModels.size > 0 && !allowedModels.has(key)) {
    return { model: normalizedModel, allowed: false, reason: "not_allowed" };
  }

  return { model: normalizedModel, allowed: true, reason: "allowed" };
}

/**
 * Filters a model list with the connection's allow and deny policy.
 * Retained names stay visible for recovery, but callers still need the evaluator
 * before treating one as a new selection.
 */
export function filterProviderModelOptions(
  models: readonly string[],
  policy: ProviderModelPolicy = {},
  options: FilterProviderModelOptionsOptions = {},
): string[] {
  const retainedModelKeys = modelKeySet(options.retainModels);
  const seen = new Set<string>();
  const filtered: string[] = [];

  for (const rawModel of models) {
    const model = rawModel.trim();
    const key = normalizedModelKey(model);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);

    if (retainedModelKeys.has(key) || evaluateProviderModelPolicy(model, policy).allowed) {
      filtered.push(model);
    }
  }

  return filtered;
}

// Match quick-pick tiers as separator-delimited tokens so brand names that
// merely contain them ("MiniMax") are not mistaken for a tier hint.
const FRESH_MODEL_QUICK_PICK_PATTERN = /(?:^|[-_. ])(?:highspeed|fast|mini|lite|flash|turbo)(?:[-_. ]|$)/i;

/** Deterministic quick-pick: fast/tier models first, then alphabetical order. */
export function pickDefaultModelFromList(availableModels: string[]): string | undefined {
  const sorted = [...availableModels].sort((left, right) => left.localeCompare(right));
  return sorted.find((item) => FRESH_MODEL_QUICK_PICK_PATTERN.test(item)) ?? sorted[0];
}

/**
 * CC-Switch-style adoption for first-touch connections: a save that did not
 * name a model (fresh relay paste, or a switched connection whose carried-over
 * model is not offered) adopts a sensible model from the live list instead of
 * failing its very first verification with the silent placeholder. Models the
 * user typed explicitly, and carried-over models the provider still offers,
 * are never overridden.
 */
export function pickFreshConnectionModel(
  existingModel: string | undefined,
  availableModels: string[],
  hasExplicitModel: boolean,
): string | undefined {
  if (hasExplicitModel || availableModels.length === 0) {
    return undefined;
  }
  const existing = existingModel?.trim().toLowerCase();
  if (existing && availableModels.some((item) => item.toLowerCase() === existing)) {
    return undefined;
  }
  return pickDefaultModelFromList(availableModels);
}
