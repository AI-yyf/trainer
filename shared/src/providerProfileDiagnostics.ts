import type { CapabilityFlags, ProviderProfileConfig, ProviderTaskBinding } from "./models";
import { evaluateProviderModelPolicy } from "./providerModelPolicy";
import { defaultCapabilitiesForProtocol } from "./providerProtocols";

export type ProviderProfileDiagnosticLevel = "info" | "warn" | "error";

export interface ProviderProfileDiagnosticIssue {
  level: ProviderProfileDiagnosticLevel;
  code: string;
  message: string;
  taskBindingKey?: string;
  alias?: string;
  model?: string;
}

export interface ProviderProfileDiagnosticsSummary {
  ok: boolean;
  status: string;
  detail: string;
  errorCount: number;
  warningCount: number;
  issues: ProviderProfileDiagnosticIssue[];
}

type SurfaceLanguage = "en-US" | "zh-CN";

const CAPABILITY_REQUIREMENT_MAP: Record<string, keyof CapabilityFlags> = {
  chat: "chat",
  responses: "responses",
  vision: "vision",
  embeddings: "embeddings",
  tools: "tools",
  jsonSchema: "jsonSchema",
  structuredOutput: "structuredOutput",
  streaming: "streaming",
};

function localize(language: SurfaceLanguage, en: string, zh: string): string {
  return language === "zh-CN" ? zh : en;
}

function normalizedModelKey(model: string | undefined): string {
  return model?.trim().toLowerCase() ?? "";
}

function catalogIncludesModel(catalog: readonly string[], model: string | undefined): boolean {
  const modelKey = normalizedModelKey(model);
  return Boolean(modelKey) && catalog.some((candidate) => normalizedModelKey(candidate) === modelKey);
}

function resolveCapabilityFlags(profile: ProviderProfileConfig, model: string): CapabilityFlags {
  const protocol = profile.protocol ?? "openai_chat_completions";
  return (
    profile.modelCapabilities?.[model] ??
    (model === profile.model ? profile.capabilities : defaultCapabilitiesForProtocol(protocol))
  );
}

function hasCapability(capabilities: CapabilityFlags, requirement: string): boolean {
  const mappedKey = CAPABILITY_REQUIREMENT_MAP[requirement];
  if (!mappedKey) {
    return true;
  }
  if (mappedKey === "structuredOutput") {
    return capabilities.structuredOutput === true || capabilities.jsonSchema === true;
  }
  return capabilities[mappedKey] === true;
}

export function describeProviderProfileDiagnostics(
  profile: ProviderProfileConfig | undefined,
  language: SurfaceLanguage = "en-US",
): ProviderProfileDiagnosticsSummary {
  if (!profile) {
    return {
      ok: false,
      status: localize(language, "No profile configured", "No profile configured"),
      detail: localize(
        language,
        "No provider profile is available for diagnostics.",
        "No provider profile is available for diagnostics.",
      ),
      errorCount: 1,
      warningCount: 0,
      issues: [
        {
          level: "error",
          code: "missing_profile",
          message: "No provider profile is available for diagnostics.",
        },
      ],
    };
  }

  const issues: ProviderProfileDiagnosticIssue[] = [];
  const aliases = profile.modelAliases ?? {};
  const availableModels = profile.availableModels ?? [];
  const allowedModels = profile.allowedModels ?? [];
  const deniedModels = profile.deniedModels ?? [];

  if (!profile.model.trim()) {
    issues.push({
      level: "error",
      code: "missing_model",
      message: "The profile is missing a model.",
    });
  }

  if (!profile.baseUrl.trim()) {
    issues.push({
      level: "error",
      code: "missing_base_url",
      message: "The profile is missing a base URL.",
    });
  }

  if (availableModels.length > 0 && profile.model.trim() && !catalogIncludesModel(availableModels, profile.model)) {
    issues.push({
      level: "warn",
      code: "model_not_listed",
      model: profile.model,
      message: `Primary model ${profile.model} is not present in the current catalog.`,
    });
  }

  const primaryModelPolicy = evaluateProviderModelPolicy(profile.model, {
    allowedModels,
    deniedModels,
  });
  if (primaryModelPolicy.reason === "denied") {
    issues.push({
      level: "error",
      code: "model_denied",
      model: profile.model,
      message: `Primary model ${profile.model} is blocked by deniedModels.`,
    });
  } else if (primaryModelPolicy.reason === "not_allowed") {
    issues.push({
      level: "error",
      code: "model_not_allowed",
      model: profile.model,
      message: `Primary model ${profile.model} is not included in allowedModels.`,
    });
  }

  if (Object.keys(aliases).length === 0) {
    issues.push({
      level: "warn",
      code: "no_model_aliases",
      message: "This profile does not define modelAliases, so task bindings can only fall back to the primary model.",
    });
  }

  for (const [taskBindingKey, binding] of Object.entries(profile.taskBindings ?? {}) as [
    string,
    ProviderTaskBinding,
  ][]) {
    const alias = String(binding.alias ?? "").trim();
    const fallbackAliases = (binding.fallbackAliases ?? []).map((item) => String(item ?? "").trim()).filter(Boolean);
    const requiredCapabilities = binding.requiredCapabilities ?? [];
    const resolvedAlias = alias || fallbackAliases[0] || profile.model;
    const resolvedModel = aliases[resolvedAlias] ?? aliases[alias] ?? resolvedAlias;
    const resolvedCapabilities = resolveCapabilityFlags(profile, resolvedModel);

    if (!alias) {
      issues.push({
        level: "warn",
        code: "binding_missing_alias",
        taskBindingKey,
        message: `Task binding ${taskBindingKey} has no alias and falls back to the primary model.`,
      });
    } else if (!aliases[alias] && alias !== profile.model) {
      issues.push({
        level: "warn",
        code: "alias_not_declared",
        taskBindingKey,
        alias,
        model: resolvedModel,
        message: `Task binding ${taskBindingKey} alias ${alias} is not declared in modelAliases.`,
      });
    }

    const bindingModelPolicy = evaluateProviderModelPolicy(resolvedModel, {
      allowedModels,
      deniedModels,
    });
    if (bindingModelPolicy.reason === "denied") {
      issues.push({
        level: "error",
        code: "binding_denied_model",
        taskBindingKey,
        alias,
        model: resolvedModel,
        message: `Task binding ${taskBindingKey} resolves to denied model ${resolvedModel}.`,
      });
    } else if (bindingModelPolicy.reason === "not_allowed") {
      issues.push({
        level: "error",
        code: "binding_model_not_allowed",
        taskBindingKey,
        alias,
        model: resolvedModel,
        message: `Task binding ${taskBindingKey} resolves to ${resolvedModel}, which is not included in allowedModels.`,
      });
    }

    if (availableModels.length > 0 && !catalogIncludesModel(availableModels, resolvedModel)) {
      issues.push({
        level: "warn",
        code: "binding_model_not_listed",
        taskBindingKey,
        alias,
        model: resolvedModel,
        message: `Task binding ${taskBindingKey} resolves to ${resolvedModel}, which is not present in the current catalog.`,
      });
    }

    const missingCapabilities = requiredCapabilities.filter((capability) => !hasCapability(resolvedCapabilities, capability));
    if (missingCapabilities.length > 0) {
      issues.push({
        level: "error",
        code: "binding_missing_capabilities",
        taskBindingKey,
        alias,
        model: resolvedModel,
        message: `Task binding ${taskBindingKey} is missing capabilities: ${missingCapabilities.join(", ")}.`,
      });
    }
  }

  const errorCount = issues.filter((issue) => issue.level === "error").length;
  const warningCount = issues.filter((issue) => issue.level === "warn").length;
  const ok = errorCount === 0;
  const status =
    errorCount > 0
      ? localize(language, "Config needs attention", "Config needs attention")
      : warningCount > 0
        ? localize(language, "Config ready with warnings", "Config ready with warnings")
        : localize(language, "Config ready", "Config ready");
  const detail =
    issues.slice(0, 3).map((issue) => issue.message).join(language === "zh-CN" ? " \u8def " : " \u00b7 ") ||
    localize(
      language,
      "No obvious conflicts were found across aliases, task bindings, and the capability matrix.",
      "No obvious conflicts were found across aliases, task bindings, and the capability matrix.",
    );

  return {
    ok,
    status,
    detail,
    errorCount,
    warningCount,
    issues,
  };
}

