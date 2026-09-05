import * as vscode from 'vscode';

import type { CommandContext } from '../core/commandContext';
import { SIDECAR_DEFAULTS } from '../core/constants';
import { trainerSessionBlockReason } from '../core/runtimeRehydration';
import { defaultProviderCredentialMode, normalizeProviderRequestDefaults } from '../core/providerDefaults';
import type {
  CapabilityFlags,
  CommandExecutionResult,
  ProviderConfig,
  ProviderConfigView,
  ProviderCredentialMode,
  ProviderLastTestResult,
  ProviderProtocol,
} from '../core/types';
import { applyDerivedHostState } from '../core/workbenchData';
import { getRuntimeWorkspaceId, withWorkspaceQuery } from './workspaceContext';
import { fetchProviderModels } from './providerWebviewCommands';
import {
  createProviderApiKeyRef,
  providerConnectionMatches,
  resolveProviderApiKeyRef,
} from '../provider/providerConfigStore';
import { PROVIDER_PROFILE_TEMPLATES } from '../provider/providerProfileRegistry';
import {
  defaultCapabilitiesForProtocol,
  normalizeProviderProtocol,
  OPENAI_COMPATIBLE_PROTOCOL,
  providerProtocolFamily,
} from '../../../shared/src/providerProtocols';
import {
  applyProviderModelCatalog,
  resolveProviderModelTokenState,
} from '../../../shared/src/providerModelTokenLimits';
import {
  evaluateProviderModelPolicy,
  filterProviderModelOptions,
  type ProviderModelPolicyEvaluation,
} from '../../../shared/src/providerModelPolicy';
import { normalizeProviderCapabilityTruth } from '../../../shared/src/providerTest';
import { stripHostLastTestSecrets } from '../../../shared/src/hostLastTestGovernance';
import { sanitizeErrorSurfaceText } from '../../../shared/src/errorSurfaceSanitizer';
import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';

const capabilityOrder: Array<keyof CapabilityFlags> = [
  'chat',
  'responses',
  'vision',
  'embeddings',
  'tools',
  'jsonSchema',
  'structuredOutput',
  'streaming',
];

const DEFAULT_PROVIDER_PROTOCOL: ProviderProtocol = OPENAI_COMPATIBLE_PROTOCOL;

function providerModelPolicyMessage(evaluation: ProviderModelPolicyEvaluation): string {
  if (evaluation.reason === 'denied') {
    return `Model '${evaluation.model}' is blocked for this connection. Choose another model, or remove it from the blocked-model list.`;
  }
  if (evaluation.reason === 'not_allowed') {
    return `Model '${evaluation.model}' is not enabled for this connection. Choose a model from the allowed list, or add it there.`;
  }
  return 'Choose a model before continuing.';
}

function providerModelPolicyFailure<T>(
  evaluation: ProviderModelPolicyEvaluation,
  unchangedSuffix?: string,
): CommandExecutionResult<T> {
  return {
    ok: false,
    message: `${providerModelPolicyMessage(evaluation)}${unchangedSuffix ? ` ${unchangedSuffix}` : ''}`,
  };
}

type CreateProviderProfileFromDraftPayload = {
  name?: string;
  protocol?: string;
  baseUrl?: string;
  model?: string;
  contextWindowTokens?: number | null;
  maxOutputTokens?: number | null;
  modelTokenLimits?: ProviderConfig['modelTokenLimits'];
  catalogModels?: string[];
  allowedModels?: string[];
  deniedModels?: string[];
  apiKey?: string;
  credentialMode?: ProviderCredentialMode;
  capabilities?: Partial<CapabilityFlags>;
  requestDefaults?: Record<string, unknown>;
  profileLabel?: string;
  reason?: string;
};

type ProviderDraftTestInput = {
  name?: string;
  protocol?: string;
  baseUrl?: string;
  model?: string;
  contextWindowTokens?: number | null;
  maxOutputTokens?: number | null;
  modelTokenLimits?: ProviderConfig['modelTokenLimits'];
  credentialMode?: ProviderCredentialMode;
  catalogModels?: string[];
  allowedModels?: string[];
  deniedModels?: string[];
  embeddingModel?: string | null;
  catalogSource?: ProviderConfig['catalogSource'];
  cacheTtlSeconds?: number | null;
  apiKey?: string;
  capabilities?: Partial<CapabilityFlags>;
  requestDefaults?: Record<string, unknown>;
};

/**
 * `draft` probes an unsaved Settings form without changing the active
 * provider, its SecretStorage entry, its cache, or its test history.
 */
export type ProviderTestCommandPayload = {
  protocol?: string;
  responseLanguage?: ComposerLanguage;
  draft?: ProviderDraftTestInput;
};

type ProviderTestResponse = {
  ok?: boolean;
  configured?: boolean;
  api_key_supplied?: boolean;
  reachable?: boolean;
  success?: boolean;
  status?: string;
  provider_name?: string;
  detail?: string;
  diagnostics?: string[];
  error_category?: string;
  retryable?: boolean;
  status_code?: number;
  capability_evidence?: unknown;
  capabilityEvidence?: unknown;
  tools_ready?: boolean;
  toolsReady?: boolean;
  tool_probe_status?: unknown;
  toolProbeStatus?: unknown;
  streaming_ready?: boolean;
  streamingReady?: boolean;
  stream_probe_status?: unknown;
  streamProbeStatus?: unknown;
  vision_ready?: boolean;
  visionReady?: boolean;
  vision_probe_status?: unknown;
  visionProbeStatus?: unknown;
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function toStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function mergeCatalogModels(...groups: Array<string[] | string | undefined>): string[] {
  const next: string[] = [];
  const seen = new Set<string>();

  for (const group of groups) {
    const values = Array.isArray(group) ? group : [group];
    for (const rawValue of values) {
      const value = typeof rawValue === 'string' ? rawValue.trim() : '';
      if (!value) {
        continue;
      }
      const key = value.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      next.push(value);
    }
  }

  return next;
}

function toRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : [];
}

function toBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function toOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed || undefined;
}

function resolveProviderName(value: unknown, fallback?: string): string {
  return toOptionalString(value) ?? toOptionalString(fallback) ?? 'custom-openai-compatible';
}

function hasOwn(value: unknown, key: PropertyKey): boolean {
  return Boolean(value) && Object.prototype.hasOwnProperty.call(value, key);
}

function toTaskBindingDiagnostics(value: unknown): Array<Record<string, unknown>> {
  return toRecordArray(value).map((record) => {
    const normalized: Record<string, unknown> = { ...record };
    const taskBindingKey = toOptionalString(record.task_binding_key) ?? toOptionalString(record.taskBindingKey);
    const resolvedModel = toOptionalString(record.resolved_model) ?? toOptionalString(record.resolvedModel);
    const fallbackAliases = toStringArray(record.fallback_aliases ?? record.fallbackAliases);
    const requiredCapabilities = toStringArray(record.required_capabilities ?? record.requiredCapabilities);
    const missingCapabilities = toStringArray(record.missing_capabilities ?? record.missingCapabilities);

    if (taskBindingKey) {
      normalized.taskBindingKey = taskBindingKey;
    }
    if (resolvedModel) {
      normalized.resolvedModel = resolvedModel;
    }
    if (fallbackAliases.length > 0) {
      normalized.fallbackAliases = fallbackAliases;
    }
    if (requiredCapabilities.length > 0) {
      normalized.requiredCapabilities = requiredCapabilities;
    }
    if (missingCapabilities.length > 0) {
      normalized.missingCapabilities = missingCapabilities;
    }
    return normalized;
  });
}

function toModelDiagnostics(value: unknown): Array<Record<string, unknown>> {
  return toRecordArray(value).map((record) => {
    const normalized: Record<string, unknown> = { ...record };
    const taskBindings = toStringArray(record.task_bindings ?? record.taskBindings);
    const missingCapabilities = toStringArray(record.missing_capabilities ?? record.missingCapabilities);

    if (taskBindings.length > 0) {
      normalized.taskBindings = taskBindings;
    }
    if (missingCapabilities.length > 0) {
      normalized.missingCapabilities = missingCapabilities;
    }
    return normalized;
  });
}

function sanitizeProviderSurfaceDetail(value: unknown): string | undefined {
  const text = toOptionalString(value);
  return text ? sanitizeErrorSurfaceText(text) : undefined;
}

function redactProviderSurfaceDetailFields(record: Record<string, unknown>): Record<string, unknown> {
  for (const key of ['detail', 'diagnosticsSummary', 'diagnostics_summary'] as const) {
    if (typeof record[key] === 'string') {
      record[key] = sanitizeErrorSurfaceText(record[key]);
    }
  }
  return record;
}

function toProviderModelTest(value: unknown): Record<string, unknown> | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const normalized: Record<string, unknown> = { ...record };
  const resolvedModel = toOptionalString(record.resolved_model) ?? toOptionalString(record.resolvedModel);
  const taskBindingKey = toOptionalString(record.task_binding_key) ?? toOptionalString(record.taskBindingKey);
  const taskBindingSupported = toBoolean(record.task_binding_supported ?? record.taskBindingSupported);
  const modelCapabilities = asRecord(record.model_capabilities) ?? asRecord(record.modelCapabilities);
  const diagnosticsSummary = sanitizeProviderSurfaceDetail(
    toOptionalString(record.diagnostics_summary) ?? toOptionalString(record.diagnosticsSummary),
  );
  const protocolFamily = toOptionalString(record.protocol_family) ?? toOptionalString(record.protocolFamily);
  const providerReachable = toBoolean(record.provider_reachable ?? record.providerReachable);
  const modelSupported = toBoolean(record.model_supported ?? record.modelSupported);

  if (resolvedModel) {
    normalized.resolvedModel = resolvedModel;
  }
  if (taskBindingKey) {
    normalized.taskBindingKey = taskBindingKey;
  }
  if (taskBindingSupported !== undefined) {
    normalized.taskBindingSupported = taskBindingSupported;
  }
  if (modelCapabilities) {
    normalized.modelCapabilities = modelCapabilities;
  }
  if (diagnosticsSummary) {
    normalized.diagnosticsSummary = diagnosticsSummary;
    normalized.diagnostics_summary = diagnosticsSummary;
  }
  if (protocolFamily) {
    normalized.protocolFamily = protocolFamily;
  }
  if (providerReachable !== undefined) {
    normalized.providerReachable = providerReachable;
  }
  if (modelSupported !== undefined) {
    normalized.modelSupported = modelSupported;
  }
  return redactProviderSurfaceDetailFields(normalized);
}

function toProviderModelListing(value: unknown): Record<string, unknown> | undefined {
  const record = asRecord(value);
  if (!record) {
    return undefined;
  }

  const normalized: Record<string, unknown> = { ...record };
  const resolvedModel = toOptionalString(record.resolved_model) ?? toOptionalString(record.resolvedModel);
  const taskBindingKey = toOptionalString(record.task_binding_key) ?? toOptionalString(record.taskBindingKey);
  const modelCapabilities = asRecord(record.model_capabilities) ?? asRecord(record.modelCapabilities);
  const diagnosticsSummary = sanitizeProviderSurfaceDetail(
    toOptionalString(record.diagnostics_summary) ?? toOptionalString(record.diagnosticsSummary),
  );
  const protocolFamily = toOptionalString(record.protocol_family) ?? toOptionalString(record.protocolFamily);

  if (resolvedModel) {
    normalized.resolvedModel = resolvedModel;
  }
  if (taskBindingKey) {
    normalized.taskBindingKey = taskBindingKey;
  }
  if (modelCapabilities) {
    normalized.modelCapabilities = modelCapabilities;
  }
  if (diagnosticsSummary) {
    normalized.diagnosticsSummary = diagnosticsSummary;
    normalized.diagnostics_summary = diagnosticsSummary;
  }
  if (protocolFamily) {
    normalized.protocolFamily = protocolFamily;
  }
  return redactProviderSurfaceDetailFields(normalized);
}

function toProviderDiagnostics(value: unknown): Array<Record<string, unknown>> {
  return toRecordArray(value).map((record) => {
    const normalized: Record<string, unknown> = { ...record };
    const providerFingerprint = toOptionalString(record.provider_fingerprint) ?? toOptionalString(record.providerFingerprint);
    const providerName = toOptionalString(record.provider_name) ?? toOptionalString(record.providerName);
    const protocolFamily = toOptionalString(record.protocol_family) ?? toOptionalString(record.protocolFamily);
    const credentialMode = toOptionalString(record.credential_mode) ?? toOptionalString(record.credentialMode);
    const workspaceSecretConfigured = toBoolean(record.workspace_secret_configured ?? record.workspaceSecretConfigured);
    const capabilitySummary = toStringArray(record.capability_summary ?? record.capabilitySummary);
    const taskBindingSummary = toStringArray(record.task_binding_summary ?? record.taskBindingSummary);
    const checkedAt = toOptionalString(record.checked_at) ?? toOptionalString(record.checkedAt);

    if (providerFingerprint) {
      normalized.providerFingerprint = providerFingerprint;
    }
    if (providerName) {
      normalized.providerName = providerName;
    }
    if (protocolFamily) {
      normalized.protocolFamily = protocolFamily;
    }
    if (credentialMode) {
      normalized.credentialMode = credentialMode;
    }
    if (workspaceSecretConfigured !== undefined) {
      normalized.workspaceSecretConfigured = workspaceSecretConfigured;
    }
    if (capabilitySummary.length > 0) {
      normalized.capabilitySummary = capabilitySummary;
    }
    if (taskBindingSummary.length > 0) {
      normalized.taskBindingSummary = taskBindingSummary;
    }
    if (checkedAt) {
      normalized.checkedAt = checkedAt;
    }
    return normalized;
  });
}

function preferPersistedProviderConfig(
  persisted: ProviderConfig | undefined,
  requested: ProviderConfig,
): ProviderConfig {
  if (!persisted) {
    return requested;
  }

  const sameProvider =
    persisted.name.trim() === requested.name.trim() &&
    persisted.baseUrl.trim() === requested.baseUrl.trim() &&
    persisted.model.trim() === requested.model.trim() &&
    normalizeProviderProtocol(persisted.protocol) === normalizeProviderProtocol(requested.protocol);

  return sameProvider ? persisted : requested;
}

async function resolveProviderApiKey(
  context: CommandContext,
  config: ProviderConfig & { apiKey?: string },
): Promise<string | undefined> {
  const inlineApiKey = toOptionalString(config.apiKey);
  if (inlineApiKey) {
    return inlineApiKey;
  }
  const store = context.providerStore as typeof context.providerStore & {
    getApiKey?: () => Promise<string | undefined> | string | undefined;
  };
  return toOptionalString(await Promise.resolve(store.getApiKey?.()));
}

function buildDraftTestConfig(
  context: CommandContext,
  input: ProviderDraftTestInput,
  existing: ProviderConfig | undefined,
): ProviderConfig | undefined {
  const name = resolveProviderName(input.name, existing?.name);
  const baseUrl = normalizeBaseUrl(input.baseUrl ?? existing?.baseUrl ?? '');
  const model = (input.model ?? existing?.model ?? '').trim();
  if (!baseUrl || !model) {
    return undefined;
  }

  const rawProtocol = input.protocol ?? existing?.protocol ?? DEFAULT_PROVIDER_PROTOCOL;
  const protocol = normalizeProviderProtocol(rawProtocol);
  if (!protocol) {
    return undefined;
  }
  const sameConnection = providerConnectionMatches(existing, { baseUrl, protocol });
  const protocolChanged = normalizeProviderProtocol(existing?.protocol) !== protocol;
  const hasEmbeddingModel = hasOwn(input, 'embeddingModel');
  const hasCacheTtlSeconds = hasOwn(input, 'cacheTtlSeconds');
  const tokenState = resolveProviderModelTokenState(sameConnection ? existing : undefined, model, {
    modelTokenLimits: input.modelTokenLimits,
    hasModelTokenLimits: hasOwn(input, 'modelTokenLimits'),
    contextWindowTokens: input.contextWindowTokens,
    maxOutputTokens: input.maxOutputTokens,
    hasContextWindowTokens: hasOwn(input, 'contextWindowTokens'),
    hasMaxOutputTokens: hasOwn(input, 'maxOutputTokens'),
  });

  return {
    name,
    baseUrl,
    model,
    protocol,
    apiKeyRef: resolveProviderApiKeyRef(existing, { baseUrl, protocol }),
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    modelTokenLimits: tokenState.modelTokenLimits,
    credentialMode:
      input.credentialMode ??
      existing?.credentialMode ??
      defaultProviderCredentialMode(context.getHostState().workspace),
    capabilities: protocolChanged
      ? defaultCapabilitiesForProtocol(protocol)
      : {
          ...defaultCapabilitiesForProtocol(protocol),
          ...(existing?.capabilities ?? {}),
          ...(input.capabilities ?? {}),
        },
    catalogModels: mergeCatalogModels(
      input.catalogModels,
      sameConnection ? existing?.catalogModels : undefined,
      sameConnection ? existing?.model : undefined,
      model,
    ),
    allowedModels: input.allowedModels ?? (sameConnection ? existing?.allowedModels ?? [] : []),
    deniedModels: input.deniedModels ?? (sameConnection ? existing?.deniedModels ?? [] : []),
    embeddingModel: hasEmbeddingModel
      ? (typeof input.embeddingModel === 'string' && input.embeddingModel.trim()
          ? input.embeddingModel.trim()
          : undefined)
      : sameConnection
        ? existing?.embeddingModel
        : undefined,
    catalogSource: input.catalogSource ?? (sameConnection ? existing?.catalogSource : undefined) ?? 'provider_live',
    cacheTtlSeconds: hasCacheTtlSeconds
      ? (typeof input.cacheTtlSeconds === 'number' &&
        Number.isFinite(input.cacheTtlSeconds) &&
        input.cacheTtlSeconds > 0
          ? Math.round(input.cacheTtlSeconds)
          : undefined)
      : sameConnection
        ? existing?.cacheTtlSeconds
        : undefined,
    requestDefaults: normalizeProviderRequestDefaults(
      { name, baseUrl, model },
      input.requestDefaults ?? (sameConnection ? existing?.requestDefaults ?? {} : {}),
    ),
  };
}

async function resolveDraftTestApiKey(
  context: CommandContext,
  input: ProviderDraftTestInput,
  draft: ProviderConfig,
  existing: ProviderConfig | undefined,
): Promise<string | undefined> {
  const inlineApiKey = toOptionalString(input.apiKey);
  if (inlineApiKey) {
    return inlineApiKey;
  }

  if (!providerConnectionMatches(existing, draft)) {
    return undefined;
  }

  return existing ? resolveProviderApiKey(context, existing as ProviderConfig & { apiKey?: string }) : undefined;
}

export async function configureProviderCommand(
  context: CommandContext,
): Promise<CommandExecutionResult<ProviderConfig>> {
  const existing = context.providerStore.getConfig();
  const protocol = normalizeProviderProtocol(existing?.protocol);

  const name = await prompt('Provider name', existing?.name ?? 'custom-openai-compatible');
  if (!name) {
    return { ok: false, message: 'Provider configuration cancelled.' };
  }

  const baseUrl = await prompt('Base URL', existing?.baseUrl ?? 'http://localhost:1234/v1');
  if (!baseUrl) {
    return { ok: false, message: 'Provider configuration cancelled.' };
  }

  const model = await prompt('Chat model', existing?.model ?? 'gpt-4.1-mini');
  if (!model) {
    return { ok: false, message: 'Provider configuration cancelled.' };
  }

  const capabilities = await promptCapabilities(existing?.capabilities, protocol);
  if (!capabilities) {
    return { ok: false, message: 'Provider configuration cancelled.' };
  }

  const apiKey = await prompt(
    'API key (leave blank to keep current or store none)',
    '',
    true,
    'Paste provider API key',
  );
  if (apiKey === undefined) {
    return { ok: false, message: 'Provider configuration cancelled.' };
  }

  const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
  const sameConnection = providerConnectionMatches(existing, {
    baseUrl: normalizedBaseUrl,
    protocol,
  });
  const config: ProviderConfig = {
    name: name.trim(),
    baseUrl: normalizedBaseUrl,
    model: model.trim(),
    protocol,
    apiKeyRef: resolveProviderApiKeyRef(existing, {
      baseUrl: normalizedBaseUrl,
      protocol,
      profileId: existing?.profileId,
    }),
    capabilities,
    allowedModels: sameConnection ? existing?.allowedModels ?? [] : [],
    deniedModels: sameConnection ? existing?.deniedModels ?? [] : [],
    requestDefaults: normalizeProviderRequestDefaults(
      {
        name: name.trim(),
        baseUrl: normalizedBaseUrl,
        model: model.trim(),
      },
      existing?.requestDefaults ?? {},
    ),
  };

  const modelPolicy = evaluateProviderModelPolicy(config.model, config);
  if (!modelPolicy.allowed) {
    return providerModelPolicyFailure(
      modelPolicy,
      'Trainer did not change the saved connection.',
    );
  }

  await context.providerStore.saveConfig(config, apiKey);
  const savedConfig = preferPersistedProviderConfig(context.providerStore.getConfig(), config);
  const storedApiKey = await context.providerStore.getApiKey();
  await context.patchWorkbenchData(
    applyDerivedHostState(
      context.getHostState().bootstrap,
      savedConfig,
      context.getHostState().sidecar,
      context.getHostState().workspace,
      context.getSessionId(),
      Boolean(storedApiKey?.trim()),
    ),
  );
  await context.workbench.syncState();

  vscode.window.showInformationMessage('Trainer provider configuration saved.');
  return {
    ok: true,
    message: 'Provider configuration saved.',
    data: savedConfig,
  };
}

export async function clearProviderCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const existing = context.providerStore.getConfig();
  if (!existing) {
    return { ok: true, message: 'No provider configuration to clear.' };
  }

  const decision = await vscode.window.showWarningMessage(
    `Clear provider configuration for ${existing.name}?`,
    { modal: true },
    'Clear',
  );
  if (!decision) {
    return { ok: false, message: 'Provider clear cancelled.' };
  }

  await context.providerStore.clear();
  await context.patchWorkbenchData(
    applyDerivedHostState(
      context.getHostState().bootstrap,
      undefined,
      context.getHostState().sidecar,
      context.getHostState().workspace,
      context.getSessionId(),
      false,
    ),
  );
  await context.workbench.syncState();
  return { ok: true, message: 'Provider configuration cleared.' };
}

export async function testProviderCommand(
  context: CommandContext,
  payload?: ProviderTestCommandPayload,
): Promise<CommandExecutionResult> {
  const savedConfig = await context.providerStore.getResolvedConfig();
  const draftInput = payload?.draft;
  const draftConfig = draftInput ? buildDraftTestConfig(context, draftInput, savedConfig) : undefined;
  const resolvedConfig = draftInput ? draftConfig : savedConfig;

  if (draftInput && !draftConfig) {
    const hasTarget = Boolean(
      (draftInput.baseUrl ?? savedConfig?.baseUrl)?.trim() && (draftInput.model ?? savedConfig?.model)?.trim(),
    );
    return {
      ok: false,
      message: hasTarget
        ? 'Select a chat protocol before testing. A gateway connection type is not a protocol, and unknown gateways are not assumed OpenAI-compatible. Your saved connection was not changed.'
        : 'Add the service root and model before testing this draft. Your saved connection was not changed.',
    };
  }

  if (!resolvedConfig) {
    vscode.window.showWarningMessage('Configure a provider before testing.');
    return { ok: false, message: 'Provider is not configured.' };
  }

  const requestedProtocol = normalizeProviderProtocol(payload?.protocol ?? resolvedConfig.protocol);
  if (!requestedProtocol) {
    return {
      ok: false,
      message:
        'Select a chat protocol before testing. A gateway connection type is not a protocol, and unknown gateways are not assumed OpenAI-compatible.',
    };
  }
  const testConfig: ProviderConfig = {
    ...resolvedConfig,
    protocol: requestedProtocol,
    capabilities:
      resolvedConfig.capabilities ?? defaultCapabilitiesForProtocol(requestedProtocol),
  };
  const modelPolicy = evaluateProviderModelPolicy(testConfig.model, testConfig);
  if (!modelPolicy.allowed) {
    return providerModelPolicyFailure(
      modelPolicy,
      draftInput
        ? 'Your saved connection was not changed.'
        : 'Trainer did not run the connection check.',
    );
  }
  const apiKey = draftInput
    ? await resolveDraftTestApiKey(context, draftInput, testConfig, savedConfig)
    : await resolveProviderApiKey(context, testConfig);
  if (draftInput && !apiKey) {
    const message =
      'Add an API key for this draft before testing it. Trainer did not reuse the saved key for a different connection.';
    vscode.window.showWarningMessage(message);
    return { ok: false, message };
  }

  if (!(await context.trustGuard.ensureTrusted('test the provider'))) {
    return {
      ok: false,
      message: draftInput
        ? 'Trust this workspace before testing the draft. Your saved connection was not changed.'
        : 'Workspace trust is required to test the provider.',
    };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return {
      ok: false,
      message: status.detail ?? 'Sidecar is unavailable; provider test skipped.',
    };
  }

  const responseLanguage = resolveProviderResponseLanguage(context, payload?.responseLanguage);
  const shouldPersistResult =
    !draftInput &&
    (!payload?.protocol ||
      normalizeProviderProtocol(payload.protocol) === normalizeProviderProtocol(resolvedConfig.protocol));
  let response: ProviderTestResponse;
  try {
    response = await context.sidecarClient.postJson<ProviderTestResponse>(
      status.port,
      '/provider/test',
      buildProviderTestRequestBody(context, testConfig, apiKey, responseLanguage),
      { timeoutMs: SIDECAR_DEFAULTS.providerRequestTimeoutMs },
    );
  } catch {
    response = {
      ok: false,
      configured: true,
      reachable: false,
      success: false,
      status: 'sidecar_unavailable',
      provider_name: testConfig.name,
      detail: 'Trainer could not finish the connection check. Your saved settings are unchanged; try again in a moment.',
      error_category: 'sidecar_unavailable',
      retryable: true,
    };
  }

  const baseMessage = formatProviderTestMessage(response, testConfig.name);
  // Fail-closed: never toast/persist raw key-shaped strings from provider detail.
  const message = sanitizeErrorSurfaceText(
    draftInput
      ? `${baseMessage} Your saved connection was not changed.`
      : baseMessage,
  );
  const ok = Boolean(response.ok);
  const capabilityTruth = normalizeProviderCapabilityTruth(response);
  if (shouldPersistResult) {
    const lastTestResult: ProviderLastTestResult = {
      ok,
      status: response.status ?? (ok ? 'connected' : 'failed'),
      detail: message,
      checkedAt: new Date().toISOString(),
      workspaceId: getRuntimeWorkspaceId(context),
      profileId: testConfig.profileId,
      providerName: testConfig.name,
      baseUrl: testConfig.baseUrl,
      model: testConfig.model,
      protocol: requestedProtocol,
      protocolFamily: providerProtocolFamily(requestedProtocol),
      errorCategory: response.error_category,
      retryable: response.retryable,
      statusCode: response.status_code,
      responseLanguage,
      capabilityEvidence: capabilityTruth.capabilityEvidence,
      toolsReady: capabilityTruth.toolsReady,
      toolProbeStatus: capabilityTruth.toolProbeStatus,
      streamingReady: capabilityTruth.streamingReady,
      streamProbeStatus: capabilityTruth.streamProbeStatus,
      visionReady: capabilityTruth.visionReady,
      visionProbeStatus: capabilityTruth.visionProbeStatus,
      thinkingReady: capabilityTruth.thinkingReady,
      thinkingProbeStatus: capabilityTruth.thinkingProbeStatus,
    };
    await context.providerStore.saveLastTestResult(testConfig, lastTestResult, {
      workspaceId: getRuntimeWorkspaceId(context),
    });
    await context.patchWorkbenchData({
      providerConfig: {
        ...context.getHostState().bootstrap.providerConfig,
        lastTestResult: stripHostLastTestSecrets({
          ...(lastTestResult as unknown as Record<string, unknown>),
        }) as unknown as typeof lastTestResult,
      },
    });
    await context.workbench.syncState();
  }

  if (response.status === 'connected' || response.success) {
    vscode.window.showInformationMessage(message);
  } else if (
    response.status === 'scaffold' ||
    response.status === 'incomplete' ||
    response.status === 'language_probe_inconclusive' ||
    response.error_category === 'sidecar_unavailable'
  ) {
    vscode.window.showWarningMessage(message);
  } else {
    vscode.window.showErrorMessage(message);
  }

  return {
    ok,
    message,
    data: response,
  };
}

function buildProviderTestRequestBody(
  context: CommandContext,
  config: ProviderConfig & { apiKey?: string },
  apiKey?: string,
  responseLanguage?: string,
): Record<string, unknown> {
  const provider = providerTransportConfig(config);
  return {
    // The sidecar receives the transient key only in the dedicated field. Keeping it
    // out of the provider record prevents accidental logging or future persistence.
    provider,
    workspace_id: getRuntimeWorkspaceId(context),
    api_key_ref: config.apiKeyRef,
    apiKey,
    response_language: responseLanguage,
  };
}

function providerTransportConfig(
  config: ProviderConfig & { apiKey?: string },
): ProviderConfig {
  const { apiKey: _resolvedApiKey, ...provider } = config;
  return provider;
}

function resolveProviderResponseLanguage(
  context: CommandContext,
  requestedLanguage?: ComposerLanguage,
): ComposerLanguage | undefined {
  if (isComposerLanguage(requestedLanguage)) {
    return requestedLanguage;
  }
  const workspaceLanguage = context.getHostState().bootstrap.memory.workspace?.responseLanguage;
  return isComposerLanguage(workspaceLanguage) ? workspaceLanguage : undefined;
}

async function resolveProviderConfig(context: CommandContext): Promise<ProviderConfig | undefined> {
  const store = context.providerStore as typeof context.providerStore & {
    getActiveProfileConfig?: () => ProviderConfig | undefined | Promise<ProviderConfig | undefined>;
    getActiveProfile?: () => ProviderConfig | undefined | Promise<ProviderConfig | undefined>;
    getResolvedConfig?: () => ProviderConfig | undefined | Promise<ProviderConfig | undefined>;
    getConfig?: () => ProviderConfig | undefined;
  };
  const candidates: Array<() => ProviderConfig | undefined | Promise<ProviderConfig | undefined>> = [
    () => store.getActiveProfileConfig?.(),
    () => store.getActiveProfile?.(),
    () => store.getResolvedConfig?.(),
    () => store.getConfig?.(),
  ];
  for (const candidate of candidates) {
    const resolved = await Promise.resolve(candidate());
    if (resolved) {
      return resolved;
    }
  }
  return undefined;
}

function resolveProfileIdentifier(config: ProviderConfig | undefined): string | undefined {
  if (!config) {
    return undefined;
  }
  const record = asRecord(config as unknown);
  if (!record) {
    return undefined;
  }
  for (const key of ['profileId', 'id', 'profile_id', 'apiKeyRef', 'name'] as const) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return undefined;
}

function sameProviderModelLookupTarget(left: ProviderConfig, right: ProviderConfig): boolean {
  return (
    left.name.trim().toLowerCase() === right.name.trim().toLowerCase() &&
    providerConnectionMatches(left, right) &&
    left.model.trim().toLowerCase() === right.model.trim().toLowerCase() &&
    left.apiKeyRef.trim() === right.apiKeyRef.trim() &&
    (left.profileId?.trim() ?? '') === (right.profileId?.trim() ?? '')
  );
}

function currentActiveProfileId(context: CommandContext): string | undefined {
  const store = context.providerStore as typeof context.providerStore & {
    getProfileRegistrySnapshot?: () => { activeProfileId?: unknown };
  };
  return toOptionalString(store.getProfileRegistrySnapshot?.().activeProfileId);
}

function activeProfileStillMatches(context: CommandContext, config: ProviderConfig): boolean {
  const expectedProfileId = config.profileId?.trim();
  if (!expectedProfileId) {
    return true;
  }
  const activeProfileId = currentActiveProfileId(context);
  return activeProfileId === undefined || activeProfileId === expectedProfileId;
}

async function isCurrentProviderProfileModelLookup(
  context: CommandContext,
  config: ProviderConfig,
  apiKey: string,
): Promise<boolean> {
  if (!activeProfileStillMatches(context, config)) {
    return false;
  }

  try {
    const currentConfig = await resolveProviderConfig(context);
    if (!currentConfig || !sameProviderModelLookupTarget(config, currentConfig)) {
      return false;
    }
    const store = context.providerStore as typeof context.providerStore & {
      getApiKey?: () => Promise<string | undefined> | string | undefined;
    };
    const currentApiKey = await Promise.resolve(store.getApiKey?.());
    return (
      activeProfileStillMatches(context, config) &&
      Boolean(currentApiKey?.trim()) &&
      currentApiKey?.trim() === apiKey.trim()
    );
  } catch {
    return false;
  }
}

async function staleProviderProfileModelLookupResult(
  context: CommandContext,
  fallback: ProviderConfig,
): Promise<CommandExecutionResult<ProviderConfig>> {
  const currentConfig = await resolveProviderConfig(context);
  const { apiKey: _apiKey, ...currentConfigWithoutApiKey } = (currentConfig ?? {}) as ProviderConfig & {
    apiKey?: string;
  };
  return {
    ok: true,
    message: 'The connection changed while models were refreshing, so Trainer kept your newer choice.',
    data: currentConfig ? currentConfigWithoutApiKey : fallback,
  };
}

function buildProviderDiagnosticsPatch(
  context: CommandContext,
  config: ProviderConfig,
  response: Record<string, unknown>,
): ProviderConfigView {
  const bootstrapProvider = context.getHostState().bootstrap.providerConfig;
  const protocol = normalizeProviderProtocol(
    (response.protocol as string | undefined) ?? config.protocol ?? DEFAULT_PROVIDER_PROTOCOL,
  );
  const configRecord = asRecord(config) ?? {};
  const protocolDiagnostic = asRecord(response.protocol_diagnostic);
  const modelTest = asRecord(response.model_test);
  const modelListing = asRecord(response.model_listing);
  const normalizedModelTest = toProviderModelTest(modelTest);
  const normalizedModelListing = toProviderModelListing(modelListing);
  const responseResolvedModel = toOptionalString(response.resolved_model);
  const resolvedModel =
    responseResolvedModel && evaluateProviderModelPolicy(responseResolvedModel, config).allowed
      ? responseResolvedModel
      : config.model;
  const taskBindingDiagnostics = hasOwn(response, 'task_binding_diagnostics')
    ? toTaskBindingDiagnostics(response.task_binding_diagnostics)
    : bootstrapProvider.taskBindingDiagnostics ?? [];
  const modelDiagnostics = hasOwn(response, 'model_diagnostics')
    ? toModelDiagnostics(response.model_diagnostics)
    : bootstrapProvider.modelDiagnostics ?? [];
  const availableModels = filterProviderModelOptions(
    hasOwn(response, 'available_models')
      ? toStringArray(response.available_models)
      : (bootstrapProvider.availableModels?.length
          ? bootstrapProvider.availableModels
          : config.availableModels ?? config.catalogModels ?? []),
    config,
    {
      retainModels: [config.model],
    },
  );
  const diagnostics = hasOwn(response, 'diagnostics')
    ? toStringArray(response.diagnostics)
    : bootstrapProvider.diagnostics ?? [];
  const warnings = hasOwn(response, 'warnings')
    ? toStringArray(response.warnings)
    : bootstrapProvider.warnings ?? [];
  const modelCapabilities =
    (hasOwn(response, 'model_capabilities') ? asRecord(response.model_capabilities) : undefined) ??
    bootstrapProvider.modelCapabilities ??
    config.modelCapabilities ??
    {};
  // Fail-closed: never persist/UI raw key-shaped strings from provider detail.
  const safeDetail = sanitizeProviderSurfaceDetail(response.detail) ?? '';

  return {
    ...bootstrapProvider,
    configured: toBoolean(response.configured) ?? true,
    name: (response.provider_name as string | undefined)?.trim() || config.name,
    baseUrl: (response.base_url as string | undefined)?.trim() || config.baseUrl,
    model: resolvedModel,
    protocol,
    protocolFamily: (response.protocol_family as string | undefined) ?? providerProtocolFamily(protocol),
    profileId:
      (response.profile_id as string | undefined)?.trim() ||
      (typeof configRecord.profileId === 'string' ? configRecord.profileId.trim() : undefined) ||
      (typeof configRecord.id === 'string' ? configRecord.id.trim() : undefined),
    profileLabel:
      (response.profile_label as string | undefined)?.trim() ||
      config.profileLabel ||
      config.name,
    profileMode:
      (response.profile_mode as string | undefined)?.trim() ||
      config.profileMode ||
      config.mode,
    credentialMode: (response.credential_mode as ProviderConfig['credentialMode'] | undefined) ?? config.credentialMode,
    workspaceSecretConfigured: toBoolean(response.workspace_secret_configured),
    apiKeyConfigured: toBoolean(response.api_key_supplied) ?? Boolean((config as { apiKey?: string }).apiKey),
    availableModels,
    resolvedModel,
    modelCapabilities: modelCapabilities as Record<string, CapabilityFlags>,
    protocolDiagnostic:
      protocolDiagnostic ??
      ({
        protocol,
        protocol_family: response.protocol_family,
        base_url: response.base_url ?? config.baseUrl,
        endpoint_hint: response.endpoint_hint,
        supported: response.supported,
        notes: diagnostics,
      } as Record<string, unknown>),
    taskBindingDiagnostics,
    modelDiagnostics,
    modelTest:
      normalizedModelTest ??
      ({
        ok: response.ok,
        detail: safeDetail,
        providerReachable: response.reachable ?? response.ok,
        provider_reachable: response.reachable ?? response.ok,
        modelSupported: response.model_supported,
        model_supported: response.model_supported,
        protocol,
        protocolFamily: response.protocol_family,
        protocol_family: response.protocol_family,
        resolvedModel,
        resolved_model: resolvedModel,
        taskBindingKey: toOptionalString(response.task_binding_key),
        task_binding_key: response.task_binding_key,
        taskBindingSupported: response.task_binding_supported,
        task_binding_supported: response.task_binding_supported,
        modelCapabilities: response.model_capabilities ?? {},
        model_capabilities: response.model_capabilities ?? {},
        diagnosticsSummary: safeDetail,
        diagnostics_summary: safeDetail,
      } as Record<string, unknown>),
    modelListing:
      normalizedModelListing ??
      ({
        ok: response.ok,
        detail: safeDetail,
        available_models: availableModels,
        resolvedModel,
        resolved_model: resolvedModel,
        listed: availableModels.length > 0,
        protocol,
        protocolFamily: response.protocol_family,
        protocol_family: response.protocol_family,
        modelCapabilities: response.model_capabilities ?? {},
        model_capabilities: response.model_capabilities ?? {},
        taskBindingKey: toOptionalString(response.task_binding_key),
        task_binding_key: response.task_binding_key,
        diagnosticsSummary: safeDetail,
        diagnostics_summary: safeDetail,
      } as Record<string, unknown>),
    diagnostics,
    warnings,
  };
}

function providerConnectionPatch(config: ProviderConfig) {
  const protocol = normalizeProviderProtocol(config.protocol);
  return {
    name: config.name,
    model: config.model,
    capabilities: config.capabilities,
    protocol,
    protocolFamily: providerProtocolFamily(protocol),
  };
}

async function switchActiveProfileCompat(
  context: CommandContext,
  profileId: string,
  reason: string,
): Promise<boolean> {
  const store = context.providerStore as typeof context.providerStore & {
    switchActiveProfile?: (profileId: string, reason: string) => Promise<boolean> | boolean;
    switchToProfile?: (profileId: string, reason?: string) => Promise<boolean> | boolean;
  };
  return Boolean(
    (await Promise.resolve(store.switchActiveProfile?.(profileId, reason))) ??
      (await Promise.resolve(store.switchToProfile?.(profileId, reason))),
  );
}

const profileActivationTails = new WeakMap<object, Promise<void>>();

async function withProfileActivationLock<T>(
  context: CommandContext,
  operation: () => Promise<T>,
): Promise<T> {
  const previous = profileActivationTails.get(context) ?? Promise.resolve();
  let releaseCurrent!: () => void;
  const current = new Promise<void>((resolve) => {
    releaseCurrent = resolve;
  });
  profileActivationTails.set(context, current);
  await previous.catch(() => undefined);

  try {
    return await operation();
  } finally {
    releaseCurrent();
    if (profileActivationTails.get(context) === current) {
      profileActivationTails.delete(context);
    }
  }
}

type ProfileSwitchPreparation = {
  previousProfileId?: string;
  targetModelPolicy?: ProviderModelPolicyEvaluation;
};

function prepareProfileSwitch(
  context: CommandContext,
  profileId: string,
): ProfileSwitchPreparation {
  const store = context.providerStore as typeof context.providerStore & {
    getProfileRegistrySnapshot?: () => { activeProfileId?: unknown; profiles?: unknown[] };
  };
  const snapshot = store.getProfileRegistrySnapshot?.();
  const profile = toRecordArray(snapshot?.profiles).find(
    (entry) => toOptionalString(entry.id) === profileId,
  );
  const model = toOptionalString(profile?.model);
  if (!model) {
    return { previousProfileId: toOptionalString(snapshot?.activeProfileId) };
  }
  return {
    previousProfileId: toOptionalString(snapshot?.activeProfileId),
    targetModelPolicy: evaluateProviderModelPolicy(model, {
      allowedModels: toStringArray(profile?.allowedModels),
      deniedModels: toStringArray(profile?.deniedModels),
    }),
  };
}

async function restorePreviousProfileIfStillCurrent(
  context: CommandContext,
  targetProfileId: string,
  previousProfileId: string | undefined,
): Promise<'restored' | 'newer_choice' | 'unavailable'> {
  if (!previousProfileId || previousProfileId === targetProfileId) {
    return 'unavailable';
  }
  if (currentActiveProfileId(context) !== targetProfileId) {
    return 'newer_choice';
  }

  const restored = await switchActiveProfileCompat(context, previousProfileId, 'policy_rejected');
  if (!restored) {
    return 'unavailable';
  }
  return currentActiveProfileId(context) === previousProfileId ? 'restored' : 'newer_choice';
}

type ProfileActivationOutcome =
  | { result: CommandExecutionResult }
  | { syncConfig: ProviderConfig };

async function activateProviderProfile(
  context: CommandContext,
  profileId: string,
  reason: string,
): Promise<ProfileActivationOutcome> {
  return withProfileActivationLock(context, async () => {
    const switchPreparation = prepareProfileSwitch(context, profileId);
    if (switchPreparation.targetModelPolicy && !switchPreparation.targetModelPolicy.allowed) {
      return {
        result: providerModelPolicyFailure(
          switchPreparation.targetModelPolicy,
          'Trainer kept the current connection active.',
        ),
      };
    }

    const switched = await switchActiveProfileCompat(context, profileId, reason);
    if (!switched) {
      return { result: { ok: false, message: `Profile '${profileId}' could not be activated.` } };
    }

    const activeProfileId = currentActiveProfileId(context);
    if (activeProfileId !== undefined && activeProfileId !== profileId) {
      const currentConfig = await resolveProviderConfig(context);
      if (currentConfig) {
        return { result: await staleProviderProfileModelLookupResult(context, currentConfig) };
      }
      return {
        result: {
          ok: true,
          message: 'The connection changed while Trainer was switching, so Trainer kept your newer choice.',
        },
      };
    }

    const activeConfig = await resolveProviderConfig(context);
    const { apiKey: _apiKey, ...activeConfigWithoutApiKey } = (activeConfig ?? {}) as ProviderConfig & {
      apiKey?: string;
    };
    const syncConfig: ProviderConfig = {
      ...activeConfigWithoutApiKey,
      profileId,
    };
    const activeModelPolicy = evaluateProviderModelPolicy(syncConfig.model, syncConfig);
    if (activeModelPolicy.allowed) {
      return { syncConfig };
    }

    const recovery = await restorePreviousProfileIfStillCurrent(
      context,
      profileId,
      switchPreparation.previousProfileId,
    );
    if (recovery === 'newer_choice') {
      return { result: await staleProviderProfileModelLookupResult(context, syncConfig) };
    }
    return {
      result: providerModelPolicyFailure(
        activeModelPolicy,
        recovery === 'restored'
          ? 'Trainer restored your previous connection. Choose another model before switching this connection.'
          : 'Trainer could not finish the switch. Choose another model before using this connection.',
      ),
    };
  });
}

export async function diagnoseProviderCommand(
  context: CommandContext,
): Promise<CommandExecutionResult> {
  const config = await resolveProviderConfig(context);
  if (!config) {
    return { ok: false, message: 'Provider is not configured.' };
  }

  const modelPolicy = evaluateProviderModelPolicy(config.model, config);
  if (!modelPolicy.allowed) {
    return providerModelPolicyFailure(
      modelPolicy,
      'Trainer did not run diagnostics for this connection.',
    );
  }

  if (!(await context.trustGuard.ensureTrusted('diagnose the provider'))) {
    return { ok: false, message: 'Workspace trust is required to diagnose the provider.' };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return {
      ok: false,
      message: status.detail ?? 'Sidecar is unavailable; provider diagnostics skipped.',
    };
  }

  const apiKey = await resolveProviderApiKey(context, config);

  const response = await context.sidecarClient.postJson<Record<string, unknown>>(
    status.port,
    '/provider/test',
    buildProviderTestRequestBody(context, config, apiKey, resolveProviderResponseLanguage(context)),
    { timeoutMs: SIDECAR_DEFAULTS.providerRequestTimeoutMs },
  );

  const providerConfigPatch = buildProviderDiagnosticsPatch(context, config, response);
  await context.patchWorkbenchData({
    providerConfig: providerConfigPatch,
  });

  if (!trainerSessionBlockReason(context)) {
    const memoryResponse = await context.sidecarClient.getJson<Record<string, unknown>>(
      status.port,
      withWorkspaceQuery('/memory/summary', context),
    );
    const memoryRecord = (memoryResponse.memory as Record<string, unknown> | undefined) ?? {};
    const providerDiagnostics = toProviderDiagnostics(memoryRecord.provider_diagnostics ?? memoryRecord.providerDiagnostics);
    await context.patchWorkbenchData({
      memory: {
        ...context.getHostState().bootstrap.memory,
        providerDiagnostics,
      },
    });
  }
  await context.workbench.syncState();

  return {
    ok: Boolean(response.ok ?? true),
    // Fail-closed: diagnose message must not carry key-shaped detail to toast/UI.
    message: sanitizeErrorSurfaceText(
      String(response.detail ?? 'Provider diagnostics complete.'),
    ),
    data: response,
  };
}

export async function switchProviderProfileCommand(
  context: CommandContext,
  payload?: { profileId?: string; reason?: string },
): Promise<CommandExecutionResult> {
  const profileId = payload?.profileId?.trim();
  if (!profileId) {
    return { ok: false, message: 'profileId is required.' };
  }

  const reason = payload?.reason?.trim() || 'manual_switch';
  const activation = await activateProviderProfile(context, profileId, reason);
  if ('result' in activation) {
    return activation.result;
  }
  const syncConfig = activation.syncConfig;
  const store = context.providerStore as typeof context.providerStore & {
    syncWorkspaceProviderOverride?: (config: ProviderConfig | undefined) => Promise<void> | void;
    getApiKey?: () => Promise<string | undefined> | string | undefined;
    getLastTestResult?: (
      config?: ProviderConfig,
      scope?: { workspaceId?: string },
    ) => ProviderLastTestResult | undefined;
    saveConfig?: (config: ProviderConfig, apiKey?: string) => Promise<void> | void;
  };
  if (store.syncWorkspaceProviderOverride) {
    await store.syncWorkspaceProviderOverride(syncConfig);
  }

  const apiKey = await Promise.resolve(store.getApiKey?.());
  let finalConfig = syncConfig;
  let modelLookupMessage: string | undefined;
  let modelPatch: Partial<ProviderConfigView> = {};
  if (apiKey?.trim()) {
    const modelLookup = await fetchProviderModels(context, syncConfig, apiKey.trim(), {
      preferCache: true,
      backgroundRefresh: true,
    });
    if (!(await isCurrentProviderProfileModelLookup(context, syncConfig, apiKey.trim()))) {
      return staleProviderProfileModelLookupResult(context, syncConfig);
    }
    if (modelLookup) {
      modelLookupMessage = modelLookup.detail;
      const resolvedModel =
        modelLookup.resolvedModel && evaluateProviderModelPolicy(modelLookup.resolvedModel, syncConfig).allowed
          ? modelLookup.resolvedModel
          : syncConfig.model;
      const catalogConfig = {
        ...applyProviderModelCatalog(syncConfig, {
          resolvedModel,
          modelTokenLimits: modelLookup.modelTokenLimits,
        }),
        catalogModels: mergeCatalogModels(
          syncConfig.catalogModels,
          syncConfig.model,
          resolvedModel,
        ),
        availableModels: Array.from(
          new Set(
            [
              ...modelLookup.availableModels.map((entry) => entry.trim()).filter(Boolean),
              ...(syncConfig.availableModels ?? []).map((entry) => entry.trim()).filter(Boolean),
            ],
          ),
        ),
      };
      const needsCatalogSave =
        syncConfig.model !== catalogConfig.model ||
        syncConfig.contextWindowTokens !== catalogConfig.contextWindowTokens ||
        syncConfig.maxOutputTokens !== catalogConfig.maxOutputTokens ||
        JSON.stringify(syncConfig.catalogModels ?? []) !== JSON.stringify(catalogConfig.catalogModels ?? []) ||
        JSON.stringify(syncConfig.availableModels ?? []) !== JSON.stringify(catalogConfig.availableModels ?? []) ||
        JSON.stringify(syncConfig.modelTokenLimits ?? {}) !== JSON.stringify(catalogConfig.modelTokenLimits ?? {});
      if (needsCatalogSave) {
        finalConfig = catalogConfig;
        await Promise.resolve(store.saveConfig?.(finalConfig));
        const persistedConfig = await resolveProviderConfig(context);
        if (persistedConfig && !sameProviderModelLookupTarget(catalogConfig, persistedConfig)) {
          return staleProviderProfileModelLookupResult(context, catalogConfig);
        }
        finalConfig = persistedConfig ?? finalConfig;
        if (!(await isCurrentProviderProfileModelLookup(context, finalConfig, apiKey.trim()))) {
          return staleProviderProfileModelLookupResult(context, finalConfig);
        }
        if (store.syncWorkspaceProviderOverride) {
          await store.syncWorkspaceProviderOverride(finalConfig);
        }
      }
      modelPatch = {
        availableModels: modelLookup.availableModels,
        resolvedModel,
        modelListStatus: modelLookup.ok ? 'ready' : 'error',
        modelListDetail: modelLookup.detail,
        cacheFetchedAt: modelLookup.fetchedAt,
        cacheExpiresAt: modelLookup.expiresAt,
        cacheSource: modelLookup.source,
        modelErrorCategory: modelLookup.errorCategory,
        modelStatusCode: modelLookup.statusCode,
        modelRetryable: modelLookup.retryable,
      };
    }
  }

  if (apiKey?.trim() && !(await isCurrentProviderProfileModelLookup(context, finalConfig, apiKey.trim()))) {
    return staleProviderProfileModelLookupResult(context, finalConfig);
  }

  await context.patchWorkbenchData({
    providerConfig: {
      ...applyDerivedHostState(
        context.getHostState().bootstrap,
        finalConfig,
        context.getHostState().sidecar,
        context.getHostState().workspace,
        context.getSessionId(),
        Boolean(apiKey?.trim()),
      ).providerConfig,
      ...finalConfig,
      ...modelPatch,
      lastTestResult: store.getLastTestResult?.(finalConfig, {
        workspaceId: getRuntimeWorkspaceId(context),
      }),
    },
    connection: {
      ...context.getHostState().bootstrap.connection,
      provider: {
        ...context.getHostState().bootstrap.connection.provider,
        ...providerConnectionPatch(finalConfig),
      },
    },
  });
  await context.workbench.syncState();

  return {
    ok: true,
    message:
      modelLookupMessage ??
      `Switched to profile '${profileId}'.`,
    data: finalConfig,
  };
}

export async function createProviderProfileFromDraftCommand(
  context: CommandContext,
  payload?: CreateProviderProfileFromDraftPayload,
): Promise<CommandExecutionResult<ProviderConfig>> {
  const input = (payload ?? {}) as CreateProviderProfileFromDraftPayload;
  const existing = await resolveProviderConfig(context);

  const name = resolveProviderName(input.name, existing?.name);
  const baseUrl = normalizeBaseUrl(input.baseUrl ?? existing?.baseUrl ?? '');
  const model = (input.model ?? existing?.model ?? '').trim();
  if (!baseUrl || !model) {
    return {
      ok: false,
      message: 'Base URL and model are required before saving a profile.',
    };
  }

  const rawProtocol = input.protocol ?? existing?.protocol;
  const protocol = normalizeProviderProtocol(rawProtocol) ?? (rawProtocol ? undefined : DEFAULT_PROVIDER_PROTOCOL);
  if (!protocol) {
    return {
      ok: false,
      message:
        'Select a chat protocol before saving. A gateway connection type is not a protocol, and unknown gateways are not assumed OpenAI-compatible.',
    };
  }
  const sameConnection =
    Boolean(existing) &&
    normalizeProviderProtocol(existing?.protocol) === protocol &&
    normalizeBaseUrl(existing?.baseUrl ?? '') === baseUrl;
  const profileLabel = input.profileLabel?.trim() || name;
  const allowedModels = input.allowedModels ?? (sameConnection ? existing?.allowedModels ?? [] : []);
  const deniedModels = input.deniedModels ?? (sameConnection ? existing?.deniedModels ?? [] : []);
  const modelPolicy = evaluateProviderModelPolicy(model, { allowedModels, deniedModels });
  if (!modelPolicy.allowed) {
    return providerModelPolicyFailure(
      modelPolicy,
      'Trainer did not create or switch to a new connection.',
    );
  }
  const fallbackApiKey = existing
    ? await resolveProviderApiKey(context, existing as ProviderConfig & { apiKey?: string })
    : undefined;
  const copiedApiKey = toOptionalString(input.apiKey) ?? fallbackApiKey;
  const credentialMode =
    input.credentialMode ??
    existing?.credentialMode ??
    defaultProviderCredentialMode(context.getHostState().workspace);
  const capabilities: CapabilityFlags = {
    ...defaultCapabilitiesForProtocol(protocol),
    ...(sameConnection ? existing?.capabilities ?? {} : {}),
    ...(input.capabilities ?? {}),
  };
  const tokenState = resolveProviderModelTokenState(sameConnection ? existing : undefined, model, {
    modelTokenLimits: input.modelTokenLimits,
    hasModelTokenLimits: hasOwn(input, 'modelTokenLimits'),
    contextWindowTokens: input.contextWindowTokens,
    maxOutputTokens: input.maxOutputTokens,
    hasContextWindowTokens: hasOwn(input, 'contextWindowTokens'),
    hasMaxOutputTokens: hasOwn(input, 'maxOutputTokens'),
  });
  const config: ProviderConfig = {
    name,
    label: profileLabel,
    profileLabel,
    baseUrl,
    model,
    protocol,
    apiKeyRef: createProviderApiKeyRef(),
    mode: sameConnection ? existing?.mode : 'direct',
    credentialMode,
    capabilities,
    requestDefaults: normalizeProviderRequestDefaults(
      {
        name,
        baseUrl,
        model,
      },
      input.requestDefaults ?? (sameConnection ? existing?.requestDefaults ?? {} : {}),
    ),
    availableModels: sameConnection ? existing?.availableModels ?? [] : [],
    catalogModels: mergeCatalogModels(
      input.catalogModels,
      sameConnection ? existing?.catalogModels ?? [] : [],
      sameConnection ? existing?.model : undefined,
      model,
    ),
    allowedModels,
    deniedModels,
    modelAliases: sameConnection ? existing?.modelAliases ?? {} : {},
    modelCapabilities: sameConnection ? existing?.modelCapabilities ?? {} : {},
    modelTokenLimits: tokenState.modelTokenLimits,
    taskBindings: sameConnection ? existing?.taskBindings ?? {} : {},
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    embeddingModel: sameConnection ? existing?.embeddingModel : undefined,
    catalogSource: sameConnection ? existing?.catalogSource : 'manual',
    cacheTtlSeconds: sameConnection ? existing?.cacheTtlSeconds : undefined,
  };

  const store = context.providerStore as typeof context.providerStore & {
    createProfileFromConfig?: (
      config: ProviderConfig,
      apiKey?: string,
      reason?: string,
    ) => Promise<ProviderConfig | undefined>;
    getApiKey?: () => Promise<string | undefined> | string | undefined;
    getLastTestResult?: (
      config?: ProviderConfig,
      scope?: { workspaceId?: string },
    ) => ProviderLastTestResult | undefined;
  };
  const createdConfig = await store.createProfileFromConfig?.(
    config,
    copiedApiKey,
    input.reason?.trim() || 'manual_create_from_draft',
  );
  if (!createdConfig) {
    return { ok: false, message: 'Trainer could not save the current draft as a provider profile.' };
  }

  const hasApiKey = Boolean((await Promise.resolve(store.getApiKey?.()))?.trim());
  await context.patchWorkbenchData({
    providerConfig: {
      ...applyDerivedHostState(
        context.getHostState().bootstrap,
        createdConfig,
        context.getHostState().sidecar,
        context.getHostState().workspace,
        context.getSessionId(),
        hasApiKey,
      ).providerConfig,
      ...createdConfig,
      lastTestResult: store.getLastTestResult?.(createdConfig, {
        workspaceId: getRuntimeWorkspaceId(context),
      }),
    },
    connection: {
      ...context.getHostState().bootstrap.connection,
      provider: {
        ...context.getHostState().bootstrap.connection.provider,
        ...providerConnectionPatch(createdConfig),
      },
    },
  });
  await context.workbench.syncState();

  return {
    ok: true,
    message: `Saved provider draft as profile '${createdConfig.profileLabel ?? createdConfig.name}'.`,
    data: createdConfig,
  };
}

export async function createProviderProfileFromTemplateCommand(
  context: CommandContext,
  payload?: { templateIndex?: number; templateLabel?: string; skipPicker?: boolean; apiKey?: string },
): Promise<CommandExecutionResult> {
  const templateItems = PROVIDER_PROFILE_TEMPLATES.map((template, templateIndex) => ({
    label: template.label,
    description: 'Add an API key now or later',
    detail: 'You can change the model later in Settings.',
    templateIndex,
  }));

  const directTemplate =
    typeof payload?.templateIndex === 'number'
      ? templateItems.find((item) => item.templateIndex === payload.templateIndex)
      : payload?.templateLabel?.trim()
        ? templateItems.find((item) => item.label === payload.templateLabel?.trim())
        : undefined;
  const picked =
    directTemplate && payload?.skipPicker
       ? directTemplate
       : await vscode.window.showQuickPick(templateItems, {
          title: 'Choose a provider template',
          placeHolder: 'Choose how you want to connect',
          canPickMany: false,
          ignoreFocusOut: true,
        });
  if (!picked) {
    return { ok: false, cancelled: true };
  }

  const useWebviewKeyEntry = Boolean(directTemplate && payload?.skipPicker && payload.apiKey === undefined);
  const apiKey =
    payload?.apiKey ??
    (useWebviewKeyEntry
      ? ''
      : await vscode.window.showInputBox({
          title: `Add API key for ${picked.label}`,
          prompt: 'Paste the API key now, or leave this empty and add it later in Settings.',
          password: true,
          ignoreFocusOut: true,
        }));
  if (apiKey === undefined) {
    return { ok: false, cancelled: true };
  }

  const store = context.providerStore as typeof context.providerStore & {
    createProfileFromTemplate?: (templateIndex: number, apiKey?: string) => Promise<ProviderConfig | undefined>;
    createFromTemplate?: (templateIndex: number, apiKey?: string) => Promise<ProviderConfig | undefined>;
    syncWorkspaceProviderOverride?: (config: ProviderConfig | undefined) => Promise<void> | void;
    getApiKey?: () => Promise<string | undefined> | string | undefined;
  };
  const createdProfile =
    (await store.createProfileFromTemplate?.(picked.templateIndex, apiKey)) ??
    (await store.createFromTemplate?.(picked.templateIndex, apiKey));
  if (!createdProfile) {
    return { ok: false, message: 'Trainer could not create a provider profile from that template.' };
  }

  const profileId = resolveProfileIdentifier(createdProfile) ?? `template-${picked.templateIndex}`;
  const switched = await switchActiveProfileCompat(context, profileId, 'template_create');
  if (!switched) {
    return { ok: false, message: 'Trainer created the template, but could not activate it.' };
  }

  const activeConfig = await resolveProviderConfig(context);
  const sourceConfig = activeConfig ?? createdProfile;
  const { apiKey: _apiKey, ...sourceConfigWithoutApiKey } = (sourceConfig ?? {}) as ProviderConfig & {
    apiKey?: string;
  };
  const syncConfig: ProviderConfig = {
    ...sourceConfigWithoutApiKey,
    profileId,
    profileLabel: (createdProfile as { label?: string }).label ?? createdProfile.name,
    profileMode: (createdProfile as { mode?: string }).mode,
  };
  if (store.syncWorkspaceProviderOverride) {
    await store.syncWorkspaceProviderOverride(syncConfig);
  }

  await context.patchWorkbenchData({
    providerConfig: {
      ...applyDerivedHostState(
        context.getHostState().bootstrap,
        syncConfig,
        context.getHostState().sidecar,
        context.getHostState().workspace,
        context.getSessionId(),
        Boolean((await Promise.resolve(store.getApiKey?.()))?.trim()),
      ).providerConfig,
      ...syncConfig,
    },
  });
  await context.workbench.syncState();

  return {
    ok: true,
    message: `Created provider profile from template '${picked.label}'.`,
    data: syncConfig,
    ui: !apiKey?.trim() && directTemplate && payload?.skipPicker
      ? { focusProviderApiKey: true }
      : undefined,
  };
}

async function prompt(
  title: string,
  value: string,
  password = false,
  promptText?: string,
): Promise<string | undefined> {
  return vscode.window.showInputBox({
    title,
    value,
    password,
    ignoreFocusOut: true,
    prompt: promptText ?? title,
  });
}

async function promptCapabilities(
  existing?: CapabilityFlags,
  _protocol: string = DEFAULT_PROVIDER_PROTOCOL,
): Promise<CapabilityFlags | undefined> {
  // Fail-closed: do not seed protocol-default chips as ready. Only pre-pick
  // previously saved capabilities; readiness itself stays last-test-only.
  const defaults: CapabilityFlags = existing ?? {
    chat: false,
    responses: false,
    vision: false,
    embeddings: false,
    tools: false,
    jsonSchema: false,
    structuredOutput: false,
    streaming: false,
  };

  const items = capabilityOrder.map((capability) => ({
    label: capability,
    picked: Boolean(defaults[capability]),
  }));

  const picked = await vscode.window.showQuickPick(items, {
    title: 'Provider capabilities',
    canPickMany: true,
    ignoreFocusOut: true,
  });

  if (!picked) {
    return undefined;
  }

  const selected = new Set(picked.map((item) => item.label as keyof CapabilityFlags));
  return capabilityOrder.reduce(
    (accumulator, capability) => {
      accumulator[capability] = selected.has(capability);
      return accumulator;
    },
    {} as CapabilityFlags,
  );
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '');
}

function formatProviderTestMessage(
  response: ProviderTestResponse,
  fallbackName: string,
): string {
  const providerName = response.provider_name?.trim() || fallbackName;
  const detailRaw = response.detail?.trim();
  // Pattern-match on raw detail for routing; never embed unsanitized detail in output.
  const detail = detailRaw ? sanitizeErrorSurfaceText(detailRaw) : undefined;

  if (response.status === 'connected' || response.success) {
    return sanitizeErrorSurfaceText(
      `${providerName} is connected. ${detail ?? 'Trainer can use this model now.'}`,
    );
  }

  if (response.status === 'missing_api_key' || response.status === 'scaffold') {
    return `${providerName} is saved, but no API key is stored yet. Trainer cannot work until you add one.`;
  }

  if (response.error_category === 'sidecar_unavailable') {
    return (
      detail ??
      'Trainer could not finish the connection check. Try again in a moment.'
    );
  }

  if (response.status === 'incomplete' || response.configured === false) {
    return (
      detail ??
      `${providerName} is missing required settings. Save the provider name, base URL, and model first.`
    );
  }

  if (
    response.status === 'language_corruption' ||
    response.error_category === 'language_corruption' ||
    (detailRaw && /question marks|corrupted chinese input/i.test(detailRaw))
  ) {
    return sanitizeErrorSurfaceText(
      `${providerName} is reachable, but Chinese input was corrupted before the model saw it. ${detail ?? ''}`.trim(),
    );
  }

  if (
    response.status === 'language_probe_inconclusive' ||
    response.error_category === 'language_probe_inconclusive' ||
    (detailRaw &&
      /language integrity probe was inconclusive|could not fully verify zh-cn input integrity/i.test(
        detailRaw,
      ))
  ) {
    return sanitizeErrorSurfaceText(
      `${providerName} is reachable, but zh-CN integrity is not fully verified yet. ${detail ?? ''}`.trim(),
    );
  }

  if (
    response.status === 'empty_response' ||
    response.error_category === 'empty_response' ||
    (detailRaw && /empty content|empty response|reply was unusable/i.test(detailRaw))
  ) {
    return sanitizeErrorSurfaceText(
      `${providerName} is reachable, but the reply was unusable. ${detail ?? ''}`.trim(),
    );
  }

  if (detail && response.reachable) {
    return sanitizeErrorSurfaceText(
      `${providerName} responded, but Trainer still cannot use it yet. ${detail}`,
    );
  }

  if (detail) {
    return sanitizeErrorSurfaceText(`${providerName} could not be reached. ${detail}`);
  }

  return `${providerName} could not be reached. Check the base URL, model, and API key, then try again.`;
}
