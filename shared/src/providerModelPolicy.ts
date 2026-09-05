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
