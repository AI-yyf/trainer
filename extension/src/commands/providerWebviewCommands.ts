import { createHash } from 'node:crypto';

import * as vscode from 'vscode';

import type { CommandContext } from '../core/commandContext';
import { SIDECAR_DEFAULTS } from '../core/constants';
import type {
  CapabilityFlags,
  CommandExecutionResult,
  ProviderConfig,
  ProviderCredentialMode,
  ProviderLastTestResult,
} from '../core/types';
import { defaultProviderCredentialMode, normalizeProviderRequestDefaults } from '../core/providerDefaults';
import { resolveProviderApiKeyRef } from '../provider/providerConfigStore';
import { applyDerivedHostState } from '../core/workbenchData';
import { getRuntimeWorkspaceId } from './workspaceContext';
import { normalizeProviderConnectionType } from '../../../shared/src/providerGateway';
import {
  defaultCapabilitiesForProtocol,
  normalizeProviderProtocol,
  OPENAI_COMPATIBLE_PROTOCOL,
  providerProtocolFamily,
} from '../../../shared/src/providerProtocols';
import {
  applyProviderModelCatalog,
  normalizeProviderModelTokenLimits,
  providerModelTokenLimitsKey,
  resolveProviderModelTokenState,
} from '../../../shared/src/providerModelTokenLimits';
import {
  evaluateProviderModelPolicy,
  filterProviderModelOptions,
  type ProviderModelPolicyEvaluation,
} from '../../../shared/src/providerModelPolicy';
import { normalizeProviderCapabilityTruth } from '../../../shared/src/providerTest';
import { providerTransportIsConfigured } from '../../../shared/src/providerStatus';
import { stripHostLastTestSecrets } from '../../../shared/src/hostLastTestGovernance';
import { sanitizeErrorSurfaceText } from '../../../shared/src/errorSurfaceSanitizer';
import { isComposerLanguage, type ComposerLanguage } from '../../../shared/src/types';

type SaveProviderPayload = {
  name?: string;
  protocol?: string;
  connectionType?: string;
  mode?: ProviderConfig['mode'];
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
  replaceApiKey?: boolean;
  responseLanguage?: ComposerLanguage;
  capabilities?: Partial<CapabilityFlags>;
  requestDefaults?: Record<string, unknown>;
};

type ProviderModelDiscoveryDraft = {
  name?: string;
  protocol?: string;
  baseUrl?: string;
  model?: string;
  apiKey?: string;
  credentialMode?: ProviderCredentialMode;
  allowedModels?: string[];
  deniedModels?: string[];
  capabilities?: Partial<CapabilityFlags>;
  requestDefaults?: Record<string, unknown>;
};

export type RefreshProviderModelsPayload = {
  draft?: ProviderModelDiscoveryDraft;
};

type SwitchProviderModelPayload = {
  model?: string;
  reason?: string;
};

type ProviderModelsResponse = {
  ok?: boolean;
  detail?: string;
  available_models?: string[];
  resolved_model?: string | null;
  model_token_limits?: ProviderConfig['modelTokenLimits'];
  modelTokenLimits?: ProviderConfig['modelTokenLimits'];
  resolved_from_input?: boolean;
  listed?: boolean;
  error_category?: string;
  retryable?: boolean;
  status_code?: number;
  diagnostics?: string[];
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

type ProviderModelLookupResult = {
  ok: boolean;
  detail?: string;
  availableModels: string[];
  resolvedModel?: string;
  modelTokenLimits?: ProviderConfig['modelTokenLimits'];
  source: 'live' | 'cache';
  fetchedAt?: string;
  expiresAt?: string;
  errorCategory?: string;
  retryable?: boolean;
  statusCode?: number;
};

type DraftProviderModelLookup = {
  config?: ProviderConfig;
  apiKey?: string;
  message?: string;
};

type ProviderDashboardSnapshot = Record<string, unknown>;

const inflightModelLookups = new Map<string, Promise<ProviderModelLookupResult>>();
const draftModelLookupGenerations = new WeakMap<object, number>();
const activeProviderModelLookupGenerations = new WeakMap<object, number>();

const defaultCapabilities: CapabilityFlags = defaultCapabilitiesForProtocol(
  'openai_chat_completions_compatible',
);

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

function allowedResolvedModel(config: ProviderConfig, resolvedModel: string | undefined): string | undefined {
  if (!resolvedModel?.trim()) {
    return undefined;
  }
  const evaluation = evaluateProviderModelPolicy(resolvedModel, config);
  return evaluation.allowed ? evaluation.model : undefined;
}

function applyProviderModelPolicyToLookup(
  config: ProviderConfig,
  lookup: ProviderModelLookupResult,
): ProviderModelLookupResult {
  const resolvedModel = allowedResolvedModel(config, lookup.resolvedModel);
  const resolvedModelWasRejected = Boolean(lookup.resolvedModel?.trim()) && !resolvedModel;
  const resolutionMessage = resolvedModelWasRejected
    ? `${providerModelPolicyMessage(evaluateProviderModelPolicy(lookup.resolvedModel, config))} Trainer kept the current model.`
    : undefined;
  const detail = resolutionMessage
    ? [lookup.detail?.trim(), resolutionMessage].filter(Boolean).join(' ')
    : lookup.detail;
  const safeDetail = detail?.trim() ? sanitizeErrorSurfaceText(detail) : detail;

  return {
    ...lookup,
    availableModels: filterProviderModelOptions(lookup.availableModels, config, {
      retainModels: [config.model],
    }),
    resolvedModel,
    detail: safeDetail,
  };
}

function mergeAvailableModels(
  current: string[] | undefined,
  incoming: string[],
): string[] {
  return Array.from(
    new Set(
      [
        ...incoming.map((value) => value.trim()).filter(Boolean),
        ...(current ?? []).map((value) => value.trim()).filter(Boolean),
      ],
    ),
  );
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

function applyModelLookupToProviderConfig(
  config: ProviderConfig,
  lookup: Pick<
    ProviderModelLookupResult,
    'ok' | 'availableModels' | 'resolvedModel' | 'modelTokenLimits'
  >,
): ProviderConfig {
  const resolvedModel = allowedResolvedModel(config, lookup.resolvedModel) ?? config.model;
  const nextCatalogConfig = applyProviderModelCatalog(config, {
    resolvedModel,
    modelTokenLimits: lookup.modelTokenLimits,
  });

  return {
    ...nextCatalogConfig,
    availableModels: lookup.ok
      ? mergeAvailableModels(undefined, lookup.availableModels)
      : config.availableModels ?? [],
    catalogModels: mergeCatalogModels(
      config.catalogModels,
      nextCatalogConfig.catalogModels,
      config.model,
      resolvedModel,
    ),
  };
}

function providerCatalogConfigDiffers(left: ProviderConfig, right: ProviderConfig): boolean {
  return (
    left.model !== right.model ||
    left.contextWindowTokens !== right.contextWindowTokens ||
    left.maxOutputTokens !== right.maxOutputTokens ||
    providerModelTokenLimitsKey(left.modelTokenLimits) !== providerModelTokenLimitsKey(right.modelTokenLimits) ||
    JSON.stringify(left.catalogModels ?? []) !== JSON.stringify(right.catalogModels ?? []) ||
    JSON.stringify(left.availableModels ?? []) !== JSON.stringify(right.availableModels ?? [])
  );
}

function hasOwn(value: unknown, key: PropertyKey): boolean {
  return Boolean(value) && Object.prototype.hasOwnProperty.call(value, key);
}

type ProviderModelLookupTarget = {
  name: string;
  baseUrl: string;
  protocol: string;
  model: string;
  apiKeyRef: string;
  profileId: string;
};

function providerModelLookupTarget(config: ProviderConfig): ProviderModelLookupTarget {
  const protocol = normalizeProviderProtocol(config.protocol);
  return {
    name: config.name.trim().toLowerCase(),
    baseUrl: normalizeBaseUrl(config.baseUrl, protocol),
    protocol: protocol ?? '',
    model: config.model.trim().toLowerCase(),
    apiKeyRef: config.apiKeyRef.trim(),
    profileId: config.profileId?.trim() ?? '',
  };
}

function sameProviderModelLookupTarget(left: ProviderConfig, right: ProviderConfig): boolean {
  const expected = providerModelLookupTarget(left);
  const current = providerModelLookupTarget(right);
  return (
    expected.name === current.name &&
    expected.baseUrl === current.baseUrl &&
    expected.protocol === current.protocol &&
    expected.model === current.model &&
    expected.apiKeyRef === current.apiKeyRef &&
    expected.profileId === current.profileId
  );
}

function activeProfileId(context: CommandContext): string | undefined {
  const store = context.providerStore as typeof context.providerStore & {
    getProfileRegistrySnapshot?: () => { activeProfileId?: unknown };
  };
  const value = store.getProfileRegistrySnapshot?.().activeProfileId;
  return typeof value === 'string' ? value.trim() : undefined;
}

function activeProfileStillMatches(context: CommandContext, config: ProviderConfig): boolean {
  const expectedProfileId = config.profileId?.trim();
  if (!expectedProfileId) {
    return true;
  }
  const currentProfileId = activeProfileId(context);
  return currentProfileId === undefined || currentProfileId === expectedProfileId;
}

function nextActiveProviderModelLookupGeneration(context: CommandContext): number {
  const next = (activeProviderModelLookupGenerations.get(context) ?? 0) + 1;
  activeProviderModelLookupGenerations.set(context, next);
  return next;
}

function activeProviderModelLookupGeneration(context: CommandContext): number {
  return activeProviderModelLookupGenerations.get(context) ?? 0;
}

async function isCurrentProviderModelLookup(
  context: CommandContext,
  config: ProviderConfig,
  apiKey: string,
  generation?: number,
): Promise<boolean> {
  if (
    (generation !== undefined && generation !== activeProviderModelLookupGeneration(context)) ||
    !activeProfileStillMatches(context, config)
  ) {
    return false;
  }
  const currentConfig = context.providerStore.getConfig();
  if (!currentConfig || !sameProviderModelLookupTarget(config, currentConfig)) {
    return false;
  }

  try {
    const currentApiKey = await context.providerStore.getApiKey();
    const normalizedCurrentApiKey = currentApiKey?.trim();
    return (
      (generation === undefined || generation === activeProviderModelLookupGeneration(context)) &&
      activeProfileStillMatches(context, config) &&
      Boolean(normalizedCurrentApiKey) &&
      normalizedCurrentApiKey === apiKey.trim()
    );
  } catch {
    return false;
  }
}

function sameCurrentProviderConfig(
  context: CommandContext,
  expectedConfig: ProviderConfig | undefined,
): boolean {
  const currentConfig = context.providerStore.getConfig();
  if (!expectedConfig) {
    return !currentConfig;
  }
  return Boolean(
    currentConfig &&
      activeProfileStillMatches(context, expectedConfig) &&
      sameProviderModelLookupTarget(expectedConfig, currentConfig),
  );
}

function nextDraftModelLookupGeneration(context: CommandContext): number {
  const next = (draftModelLookupGenerations.get(context) ?? 0) + 1;
  draftModelLookupGenerations.set(context, next);
  return next;
}

function isLatestDraftModelLookup(context: CommandContext, generation: number): boolean {
  return draftModelLookupGenerations.get(context) === generation;
}

function staleModelLookupResult(
  context: CommandContext,
  fallback: ProviderConfig,
): CommandExecutionResult<ProviderConfig> {
  return {
    ok: true,
    message: 'The connection changed while models were refreshing, so Trainer kept your newer choice.',
    data: context.providerStore.getConfig() ?? fallback,
  };
}

function providerModelLookupRequestKey(config: ProviderConfig, apiKey: string): string {
  const target = providerModelLookupTarget(config);
  const apiKeyFingerprint = createHash('sha256').update(apiKey).digest('hex');
  return [
    target.name,
    target.baseUrl,
    target.protocol,
    target.model,
    target.apiKeyRef,
    target.profileId,
    apiKeyFingerprint,
  ].join('::');
}

function providerModelsRequestBody(
  context: CommandContext,
  config: ProviderConfig & { apiKey?: string },
  apiKey: string,
  responseLanguage = resolveProviderResponseLanguage(context),
): Record<string, unknown> {
  const { apiKey: _embeddedApiKey, ...provider } = config;
  return {
    provider,
    workspace_id: getRuntimeWorkspaceId(context),
    api_key_ref: config.apiKeyRef,
    apiKey,
    response_language: responseLanguage,
  };
}

async function verifyProviderAfterSave(
  context: CommandContext,
  config: ProviderConfig,
  apiKey: string,
  responseLanguage = resolveProviderResponseLanguage(context),
  generation?: number,
): Promise<ProviderLastTestResult | undefined> {
  if (!(await context.trustGuard.ensureTrusted('test the provider connection'))) {
    return {
      ok: false,
      status: 'workspace_trust',
      detail:
        'Provider settings were saved locally. Trust this workspace before Trainer sends the API key to test the connection.',
      checkedAt: new Date().toISOString(),
      providerName: config.name,
      baseUrl: config.baseUrl,
      model: config.model,
      protocol: normalizeProviderProtocol(config.protocol),
      protocolFamily: providerProtocolFamily(normalizeProviderProtocol(config.protocol)),
      errorCategory: 'workspace_trust',
      retryable: false,
      responseLanguage,
      capabilityEvidence: [],
      toolsReady: false,
      toolProbeStatus: 'unverified',
      streamingReady: false,
      streamProbeStatus: 'unverified',
      visionReady: false,
      visionProbeStatus: 'unverified',
      thinkingReady: false,
      thinkingProbeStatus: 'unverified',
    };
  }
  let lastTestResult: ProviderLastTestResult;
  try {
    const status = await context.sidecarManager.ensureRunning();
    if (status.lifecycle !== 'ready' || !status.port) {
      throw new Error('sidecar unavailable');
    }

    const response = await context.sidecarClient.postJson<ProviderTestResponse>(
      status.port,
      '/provider/test',
      providerModelsRequestBody(context, config, apiKey, responseLanguage),
      { timeoutMs: SIDECAR_DEFAULTS.providerRequestTimeoutMs },
    );
    const capabilityTruth = normalizeProviderCapabilityTruth(response);
    lastTestResult = {
      ok: Boolean(response.ok),
      status: response.status ?? (response.ok ? 'connected' : 'failed'),
      detail: sanitizeErrorSurfaceText(
        response.detail?.trim() ||
          (response.ok
            ? 'Provider connected.'
            : 'Trainer could not verify this provider yet.'),
      ),
      checkedAt: new Date().toISOString(),
      workspaceId: getRuntimeWorkspaceId(context),
      profileId: config.profileId,
      providerName: response.provider_name?.trim() || config.name,
      baseUrl: config.baseUrl,
      model: config.model,
      protocol: normalizeProviderProtocol(config.protocol),
      protocolFamily: providerProtocolFamily(normalizeProviderProtocol(config.protocol)),
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
  } catch {
    lastTestResult = {
      ok: false,
      status: 'sidecar_unavailable',
      detail: 'Trainer could not finish the connection check. Try the check again in a moment.',
      checkedAt: new Date().toISOString(),
      workspaceId: getRuntimeWorkspaceId(context),
      profileId: config.profileId,
      providerName: config.name,
      baseUrl: config.baseUrl,
      model: config.model,
      protocol: normalizeProviderProtocol(config.protocol),
      protocolFamily: providerProtocolFamily(normalizeProviderProtocol(config.protocol)),
      errorCategory: 'sidecar_unavailable',
      retryable: true,
      responseLanguage,
      capabilityEvidence: [],
      toolsReady: false,
      toolProbeStatus: 'unverified',
      streamingReady: false,
      streamProbeStatus: 'unverified',
      visionReady: false,
      visionProbeStatus: 'unverified',
      thinkingReady: false,
      thinkingProbeStatus: 'unverified',
    };
  }
  if (!(await isCurrentProviderModelLookup(context, config, apiKey, generation))) {
    return undefined;
  }
  if (typeof context.providerStore.saveLastTestResult === 'function') {
    return await context.providerStore.saveLastTestResult(config, lastTestResult, {
      workspaceId: getRuntimeWorkspaceId(context),
    });
  }
  return stripHostLastTestSecrets({
    ...(lastTestResult as unknown as Record<string, unknown>),
  }) as unknown as ProviderLastTestResult;
}

function isHardBlockingProviderError(category?: string): boolean {
  return (
    category === 'invalid_key_or_permission' ||
    category === 'model_unsupported' ||
    category === 'model_not_found' ||
    category === 'language_corruption'
  );
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

function storedLastTestResult(
  context: CommandContext,
  config: ProviderConfig | undefined,
) {
  return context.providerStore.getLastTestResult(config, {
    workspaceId: getRuntimeWorkspaceId(context),
  });
}

function protocolPatch(config: Pick<ProviderConfig, 'protocol'>): {
  protocol?: ProviderConfig['protocol'];
  protocolFamily?: string;
} {
  const protocol = normalizeProviderProtocol(config.protocol);
  return {
    protocol,
    protocolFamily: providerProtocolFamily(protocol),
  };
}

function providerConnectionPatch(config: ProviderConfig) {
  return {
    name: config.name,
    model: config.model,
    capabilities: config.capabilities,
    ...protocolPatch(config),
  };
}

async function reconcileProviderSuccessState(
  context: CommandContext,
  config: ProviderConfig,
  apiKey: string,
  generation?: number,
): Promise<void> {
  if (!(await isCurrentProviderModelLookup(context, config, apiKey, generation))) {
    return;
  }

  const lastTestResult = context.providerStore.getLastTestResult(config, {
    workspaceId: getRuntimeWorkspaceId(context),
  });
  if (!lastTestResult || lastTestResult.ok || !isHardBlockingProviderError(lastTestResult.errorCategory)) {
    return;
  }

  await context.providerStore.clearLastTestResult(config, {
    workspaceId: getRuntimeWorkspaceId(context),
  });

  const currentView = context.getHostState().bootstrap.providerConfig;
  if (
    currentView.name !== config.name ||
    currentView.baseUrl !== config.baseUrl ||
    normalizeProviderProtocol(currentView.protocol) !== normalizeProviderProtocol(config.protocol)
  ) {
    return;
  }

  await context.patchWorkbenchData({
    providerConfig: {
      ...currentView,
      lastTestResult: undefined,
    },
  });
}

export async function saveProviderFromWebviewCommand(
  context: CommandContext,
  payload?: unknown,
): Promise<CommandExecutionResult<ProviderConfig>> {
  const input = (payload ?? {}) as SaveProviderPayload;
  const existing = context.providerStore.getConfig();

  const name = input.name?.trim() || existing?.name?.trim() || 'custom-openai-compatible';
  const protocol = normalizeProviderProtocol(input.protocol ?? existing?.protocol);
  if (input.protocol && !protocol) {
    return {
      ok: false,
      message:
        'Select a chat protocol before saving. A gateway connection type is not a protocol, and unknown gateways are not assumed OpenAI-compatible.',
    };
  }
  const resolvedProtocol = protocol ?? OPENAI_COMPATIBLE_PROTOCOL;
  const baseUrl = normalizeBaseUrl(
    input.baseUrl ?? existing?.baseUrl ?? 'http://localhost:1234/v1',
    resolvedProtocol,
  );
  const model = (input.model ?? existing?.model ?? 'gpt-4.1-mini').trim();

  if (!baseUrl || !model) {
    return {
      ok: false,
      message: 'Add the service root and model before saving this connection.',
    };
  }

  const previousProtocol = normalizeProviderProtocol(existing?.protocol);
  const protocolChanged = resolvedProtocol !== previousProtocol;
  const sameConnection =
    Boolean(existing) &&
    previousProtocol === resolvedProtocol &&
    normalizeBaseUrl(existing?.baseUrl ?? '', previousProtocol) === baseUrl;
  const capabilities: CapabilityFlags = protocolChanged
    ? defaultCapabilitiesForProtocol(resolvedProtocol)
    : {
        ...defaultCapabilitiesForProtocol(resolvedProtocol),
        ...(existing?.capabilities ?? {}),
        ...(input.capabilities ?? {}),
      };
  const credentialMode =
    input.credentialMode ??
    existing?.credentialMode ??
    defaultProviderCredentialMode(context.getHostState().workspace);
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

  const config: ProviderConfig = {
    name,
    label: name,
    profileLabel: name,
    baseUrl,
    model,
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    modelTokenLimits: tokenState.modelTokenLimits,
    protocol: resolvedProtocol,
    connectionType: normalizeProviderConnectionType(input.connectionType ?? existing?.connectionType),
    mode: input.mode ?? existing?.mode,
    apiKeyRef: resolveProviderApiKeyRef(existing, {
      baseUrl,
      protocol: resolvedProtocol,
      profileId: existing?.profileId,
    }),
    capabilities,
    credentialMode,
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
      {
        name,
        baseUrl,
        model,
      },
      input.requestDefaults ?? (sameConnection ? existing?.requestDefaults ?? {} : {}),
    ),
  };

  const modelPolicy = evaluateProviderModelPolicy(config.model, config);
  if (!modelPolicy.allowed) {
    return providerModelPolicyFailure(
      modelPolicy,
      'This connection was not saved, and your existing connection was not changed.',
    );
  }

  const providerChangeGeneration = nextActiveProviderModelLookupGeneration(context);

  const shouldReplaceApiKey = input.replaceApiKey === true || !existing || existing.apiKeyRef !== config.apiKeyRef;
  if (
    existing &&
    existing.apiKeyRef !== config.apiKeyRef &&
    typeof context.providerStore.clearModelCache === 'function'
  ) {
    await context.providerStore.clearModelCache(existing);
  }
  await context.providerStore.saveConfig(config, shouldReplaceApiKey ? input.apiKey : undefined);
  const savedConfig = preferPersistedProviderConfig(context.providerStore.getConfig(), config);
  const apiKey = await context.providerStore.getApiKey();
  const hasApiKey = Boolean(apiKey?.trim());
  const cachedModels = context.providerStore.getModelCache(savedConfig);
  const cacheUsable =
    hasApiKey &&
    context.providerStore.isModelCacheFresh(cachedModels) &&
    context.providerStore.isModelCacheCompatible(savedConfig, cachedModels, apiKey ?? undefined);
  await context.patchWorkbenchData({
    providerConfig: {
      ...applyDerivedHostState(
        context.getHostState().bootstrap,
        savedConfig,
        context.getHostState().sidecar,
        context.getHostState().workspace,
        context.getSessionId(),
        hasApiKey,
      ).providerConfig,
      availableModels: cacheUsable ? cachedModels?.availableModels ?? [] : [],
      resolvedModel: cacheUsable ? cachedModels?.resolvedModel : undefined,
      modelListStatus: hasApiKey ? 'loading' : 'idle',
      modelListDetail: hasApiKey
        ? cacheUsable
          ? 'Trainer loaded cached models and is checking for a fresher list.'
          : 'Trainer is fetching available models from this provider.'
        : 'Add an API key to let Trainer fetch live models.',
      cacheFetchedAt: cacheUsable ? cachedModels?.fetchedAt : undefined,
      cacheExpiresAt: cacheUsable ? cachedModels?.expiresAt : undefined,
      cacheSource: cacheUsable ? 'cache' : undefined,
      modelErrorCategory: cacheUsable ? cachedModels?.lastErrorCategory : undefined,
      modelStatusCode: cacheUsable ? cachedModels?.lastStatusCode : undefined,
      modelRetryable: cacheUsable ? cachedModels?.retryable : undefined,
      lastTestResult: storedLastTestResult(context, savedConfig),
    },
  });
  await context.workbench.syncState();

  let finalConfig = savedConfig;
  let finalLastTestResult = storedLastTestResult(context, savedConfig);
  const responseLanguage = resolveProviderResponseLanguage(context, input.responseLanguage);
  let message = hasApiKey
    ? 'Provider settings saved. Trainer is fetching live models and checking reply health.'
    : 'Provider settings saved, but Trainer still cannot work yet because no API key is stored. Add one before starting coaching.';

  if (hasApiKey) {
    const modelLookup = await fetchProviderModels(context, savedConfig, apiKey ?? '', {
      preferCache: true,
      backgroundRefresh: true,
      responseLanguage,
      generation: providerChangeGeneration,
    });
    if (!(await isCurrentProviderModelLookup(context, savedConfig, apiKey ?? '', providerChangeGeneration))) {
      return staleModelLookupResult(context, savedConfig);
    }
    const catalogConfig = modelLookup
      ? applyModelLookupToProviderConfig(savedConfig, modelLookup)
      : savedConfig;
    if (providerCatalogConfigDiffers(savedConfig, catalogConfig)) {
      finalConfig = catalogConfig;
      await context.providerStore.saveConfig(finalConfig);
      finalConfig = context.providerStore.getConfig() ?? finalConfig;
      if (modelLookup && finalConfig.model !== savedConfig.model) {
        await context.providerStore.saveModelCache(finalConfig, {
          availableModels: modelLookup.availableModels,
          resolvedModel: modelLookup.resolvedModel,
          modelTokenLimits: modelLookup.modelTokenLimits,
          lastError: modelLookup.ok ? undefined : modelLookup.detail,
          lastErrorCategory: modelLookup.errorCategory,
          lastStatusCode: modelLookup.statusCode,
          retryable: modelLookup.retryable,
          fetchedAt: modelLookup.fetchedAt,
          source: modelLookup.source,
          apiKey: apiKey ?? undefined,
        });
      }
    } else {
      finalConfig = catalogConfig;
    }

    // A number of compatible gateways expose chat but intentionally omit a
    // model-list endpoint. The configured model can still be checked safely,
    // so model discovery must not be a prerequisite for connection testing.
    if (finalConfig.model.trim() && modelLookup?.errorCategory !== 'workspace_trust') {
      finalLastTestResult =
        (await verifyProviderAfterSave(
          context,
          finalConfig,
          apiKey ?? '',
          responseLanguage,
          providerChangeGeneration,
        )) ??
        storedLastTestResult(context, finalConfig);
    } else {
      finalLastTestResult = storedLastTestResult(context, finalConfig);
    }

    if (!(await isCurrentProviderModelLookup(context, finalConfig, apiKey ?? '', providerChangeGeneration))) {
      return staleModelLookupResult(context, finalConfig);
    }

    const finalViewState = applyDerivedHostState(
      context.getHostState().bootstrap,
      finalConfig,
      context.getHostState().sidecar,
      context.getHostState().workspace,
      context.getSessionId(),
      true,
    ).providerConfig;

    await context.patchWorkbenchData({
      providerConfig: {
        ...finalViewState,
        availableModels: modelLookup?.ok
          ? mergeAvailableModels(undefined, modelLookup.availableModels)
          : finalConfig.availableModels ?? [],
        resolvedModel: modelLookup?.resolvedModel ?? finalConfig.model,
        modelListStatus: modelLookup?.ok ? 'ready' : 'error',
        modelListDetail:
          modelLookup?.detail ??
          'Trainer could not fetch live models for this provider.',
        cacheFetchedAt: modelLookup?.fetchedAt,
        cacheExpiresAt: modelLookup?.expiresAt,
        cacheSource: modelLookup?.source,
        modelErrorCategory: modelLookup?.errorCategory,
        modelStatusCode: modelLookup?.statusCode,
        modelRetryable: modelLookup?.retryable,
        lastTestResult: finalLastTestResult,
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

    if (modelLookup?.ok && modelLookup.availableModels.length > 0) {
      const resolvedSuffix =
        modelLookup.resolvedModel && modelLookup.resolvedModel !== savedConfig.model
          ? ` Trainer resolved the configured model to ${modelLookup.resolvedModel}.`
          : '';
      const sourcePrefix = modelLookup.source === 'cache' ? 'Used cached models.' : 'Loaded';
      if (finalLastTestResult?.ok) {
        message = `${sourcePrefix} ${modelLookup.availableModels.length} live models and verified the current connection.${resolvedSuffix}`;
      } else if (finalLastTestResult?.errorCategory === 'language_probe_inconclusive') {
        message =
          `${sourcePrefix} ${modelLookup.availableModels.length} live models, ` +
          `but zh-CN integrity still needs verification on this connection. ${finalLastTestResult.detail}${resolvedSuffix}`;
      } else if (finalLastTestResult?.detail) {
        message =
          `${sourcePrefix} ${modelLookup.availableModels.length} live models, ` +
          `but Trainer cannot coach with this connection yet. ${finalLastTestResult.detail}${resolvedSuffix}`;
      } else {
        message = `${sourcePrefix} ${modelLookup.availableModels.length} live models.${resolvedSuffix}`;
      }
    } else if (modelLookup?.detail) {
      if (finalLastTestResult?.ok) {
        message =
          `The current model is connected and ready. This provider did not return a live model list, ` +
          `so Trainer kept the saved model. ${modelLookup.detail}`;
      } else if (finalLastTestResult?.detail) {
        message =
          `Provider settings saved, but Trainer could not verify the current model yet. ` +
          `${finalLastTestResult.detail}`;
      } else {
        message = `Provider settings saved, but Trainer could not get the live model list yet. ${modelLookup.detail}`;
      }
    }
  }

  return {
    ok: true,
    message,
    data: finalConfig,
  };
}

export async function openWorkspaceConfigCommand(
  context: CommandContext,
): Promise<CommandExecutionResult<{ path: string }>> {
  const workspaceRootUri =
    vscode.workspace.workspaceFolders?.[0]?.uri ??
    resolveWorkspaceRootUri(context);
  if (!workspaceRootUri) {
    return {
      ok: false,
      message: 'Open a workspace folder before editing Trainer config.',
    };
  }

  const configUri = vscode.Uri.joinPath(workspaceRootUri, '.vscode', 'trainer.json');

  try {
    await vscode.workspace.fs.createDirectory(vscode.Uri.joinPath(workspaceRootUri, '.vscode'));
  } catch {
    // Directory may already exist.
  }

  try {
    await vscode.workspace.fs.stat(configUri);
  } catch {
    const provider = context.providerStore.getConfig();
    const initialConfig = JSON.stringify(
      {
        provider: provider
          ? {
              name: provider.name,
              protocol: normalizeProviderProtocol(provider.protocol) ?? OPENAI_COMPATIBLE_PROTOCOL,
              baseUrl: provider.baseUrl,
              model: provider.model,
              capabilities: provider.capabilities,
              requestDefaults: normalizeProviderRequestDefaults(
                {
                  name: provider.name,
                  baseUrl: provider.baseUrl,
                  model: provider.model,
                },
                provider.requestDefaults ?? {},
              ),
            }
          : {
              name: 'custom-openai-compatible',
              protocol: OPENAI_COMPATIBLE_PROTOCOL,
              baseUrl: 'http://localhost:1234/v1',
              model: 'gpt-4.1-mini',
              capabilities: defaultCapabilities,
              requestDefaults: {},
            },
        behavior: {
          answerMode: 'auto',
          contextDetail: 'balanced',
          includeCurrentFile: true,
          includeSelection: true,
          includeDiagnostics: true,
          includeRelatedFiles: true,
          followCurrentFile: true,
          language: 'zh-CN',
        },
      },
      null,
      2,
    );
    await vscode.workspace.fs.writeFile(configUri, Buffer.from(`${initialConfig}\n`, 'utf8'));
  }

  const document = await vscode.workspace.openTextDocument(configUri);
  await vscode.window.showTextDocument(document, { preview: false });

  return {
    ok: true,
    message: 'Opened workspace Trainer config. You can adjust model and coach defaults here.',
    data: { path: configUri.fsPath },
  };
}

export async function refreshProviderProfilesCommand(
  context: CommandContext,
): Promise<CommandExecutionResult<ProviderDashboardSnapshot>> {
  const providerStore = context.providerStore as typeof context.providerStore & {
    getProfileRegistrySnapshot?: () => {
      activeProfileId?: string;
      profiles?: unknown[];
      switchHistory?: unknown[];
    };
    getApiKey?: () => Promise<string | undefined>;
  };
  const currentConfig = context.providerStore.getConfig() as (ProviderConfig & Record<string, unknown>) | undefined;
  const localRegistry = providerStore.getProfileRegistrySnapshot?.();
  const profiles = localRegistry?.profiles ?? currentConfig?.providerProfiles ?? [];
  const switchHistory = localRegistry?.switchHistory ?? currentConfig?.profileHistory ?? [];
  const dashboard: ProviderDashboardSnapshot = {
    active_profile_id: localRegistry?.activeProfileId ?? currentConfig?.profileId,
    profiles,
    switch_history: switchHistory,
    profile_count: Array.isArray(profiles) ? profiles.length : 0,
  };
  const currentProfile = resolveCurrentProfileSnapshot(dashboard);
  const storedApiKey = providerStore.getApiKey ? await providerStore.getApiKey() : undefined;
  const currentView = context.getHostState().bootstrap.providerConfig;
  const providerConfigured = providerTransportIsConfigured({
    name: currentConfig?.name ?? asString(currentProfile?.name) ?? currentView.name,
    baseUrl: currentConfig?.baseUrl ?? asString(currentProfile?.baseUrl) ?? currentView.baseUrl,
    model: currentConfig?.model ?? asString(currentProfile?.model) ?? currentView.model,
  });
  const currentProtocol = normalizeProviderProtocol(
    currentConfig?.protocol ?? currentView.protocol ?? asString(currentProfile?.protocol),
  );
  const providerPatch = {
    ...currentView,
    configured: providerConfigured,
    name: currentConfig?.name ?? currentView.name,
    baseUrl: currentConfig?.baseUrl ?? currentView.baseUrl,
    model: currentConfig?.model ?? currentView.model,
    protocol: currentProtocol,
    protocolFamily: providerProtocolFamily(currentProtocol),
    apiKeyConfigured: providerConfigured && Boolean(storedApiKey?.trim() || currentView.apiKeyConfigured),
    capabilities: currentConfig?.capabilities ?? currentView.capabilities,
    requestDefaults: normalizeProviderRequestDefaults(
      {
        name: currentConfig?.name ?? currentView.name,
        baseUrl: currentConfig?.baseUrl ?? currentView.baseUrl,
        model: currentConfig?.model ?? currentView.model,
      },
      currentConfig?.requestDefaults ?? currentView.requestDefaults ?? {},
    ),
    availableModels:
      Array.isArray(currentConfig?.availableModels)
        ? (currentConfig.availableModels as string[])
        : currentView.availableModels,
    resolvedModel: currentConfig?.model ?? currentView.resolvedModel,
    modelListStatus: providerConfigured ? currentView.modelListStatus ?? 'idle' : 'idle',
    profileId:
      asString(currentConfig?.profileId) ??
      asString(dashboard.active_profile_id) ??
      asString(currentProfile?.id),
    profileLabel:
      asString(currentConfig?.profileLabel) ??
      asString(currentProfile?.label),
    profileMode:
      asString(currentConfig?.profileMode) ??
      asString(currentProfile?.mode),
    profileCount:
      asNumber(currentConfig?.profileCount) ??
      asNumber(dashboard.profile_count) ??
      (Array.isArray(dashboard.profiles) ? dashboard.profiles.length : 0),
    providerProfiles:
      currentConfig?.providerProfiles ??
      normalizeProviderProfilesList(dashboard.profiles),
    profileHistory:
      currentConfig?.profileHistory ??
      normalizeProfileHistory(dashboard.switch_history),
    providerDashboard: {
      currentProfile,
      templateCount:
        asNumber(dashboard.template_count) ??
        (Array.isArray(dashboard.templates) ? dashboard.templates.length : 0),
      taskBindingCount:
        asNumber(dashboard.task_binding_count) ??
        (Array.isArray(dashboard.task_binding_resolutions)
          ? dashboard.task_binding_resolutions.length
          : 0),
      protocolCatalog: normalizeProtocolCatalog(dashboard.protocol_catalog),
      diagnostics: dashboard.diagnostics ?? undefined,
    },
  };

  await context.patchWorkbenchData({
    providerConfig: providerPatch as unknown as ReturnType<typeof applyDerivedHostState>['providerConfig'],
  });
  await context.workbench.syncState();

  return {
    ok: true,
    message: 'Provider profiles refreshed from local secure storage.',
    data: dashboard,
  };
}

function normalizeBaseUrl(
  baseUrl: string,
  protocol: ProviderConfig['protocol'] = 'openai_chat_completions_compatible',
): string {
  const trimmed = baseUrl.trim();
  if (!trimmed) {
    return '';
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return trimmed.replace(/\/+$/, '');
    }

    const normalizedProtocol = normalizeProviderProtocol(protocol);
    let pathname = parsed.pathname.replace(/\/+$/, '');
    const loweredPathname = pathname.toLowerCase();
    if (
      normalizedProtocol === 'openai_responses' ||
      normalizedProtocol === 'openai_chat_completions' ||
      normalizedProtocol === 'openai_chat_completions_compatible'
    ) {
      for (const suffix of ['/chat/completions', '/responses']) {
        if (loweredPathname.endsWith(suffix)) {
          pathname = pathname.slice(0, -suffix.length) || '/';
          break;
        }
      }
    } else if (
      normalizedProtocol === 'anthropic_messages' &&
      loweredPathname.endsWith('/messages')
    ) {
      pathname = pathname.slice(0, -'/messages'.length) || '/';
    } else if (
      normalizedProtocol === 'gemini_generate_content' &&
      loweredPathname.endsWith(':generatecontent')
    ) {
      const modelMarker = '/models/';
      const markerIndex = loweredPathname.lastIndexOf(modelMarker);
      if (markerIndex >= 0) {
        pathname = pathname.slice(0, markerIndex) || '/';
      }
    }

    parsed.pathname = pathname || '/';
    parsed.search = '';
    parsed.hash = '';
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return trimmed.replace(/\/+$/, '');
  }
}

function resolveWorkspaceRootUri(context: CommandContext): vscode.Uri | undefined {
  const workspaceRoot =
    context.getHostState().workspace.activeWorkspaceRoot ??
    context.getHostState().workspace.workspaceFolder;
  if (!workspaceRoot) {
    return undefined;
  }
  if (typeof vscode.Uri?.file === "function") {
    return vscode.Uri.file(workspaceRoot);
  }
  return { fsPath: workspaceRoot } as vscode.Uri;
}

function resolveCurrentProfileSnapshot(
  dashboard: ProviderDashboardSnapshot,
): Record<string, unknown> | undefined {
  const currentProfile = asRecord(dashboard.current_profile);
  if (currentProfile) {
    return normalizeProviderProfileEntry(currentProfile);
  }

  const activeProfileId = asString(dashboard.active_profile_id);
  const profiles = Array.isArray(dashboard.profiles) ? dashboard.profiles : [];
  const matchedProfile = profiles.find((profile) => {
    const record = asRecord(profile);
    return record && asString(record.id) === activeProfileId;
  });
  return normalizeProviderProfileEntry(asRecord(matchedProfile));
}

function normalizeProviderProfilesList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => normalizeProviderProfileEntry(asRecord(entry)))
    .filter((entry): entry is Record<string, unknown> => Boolean(entry));
}

function normalizeProviderProfileEntry(
  profile: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  if (!profile) {
    return undefined;
  }

  return {
    ...profile,
    id: asString(profile.id),
    label: asString(profile.label),
    protocol: asString(profile.protocol),
    mode: asString(profile.mode),
    credentialMode: asString(profile.credentialMode),
    baseUrl: asString(profile.baseUrl),
    apiKeyRef: asString(profile.apiKeyRef),
    model: asString(profile.model),
    requestDefaults: normalizeProviderRequestDefaults(
      {
        name: asString(profile.label) ?? asString(profile.name),
        baseUrl: asString(profile.baseUrl),
        model: asString(profile.model),
      },
      profile.requestDefaults ?? profile.request_defaults,
    ),
  };
}

function normalizeProfileHistory(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return [];
  }
  const normalized: Array<Record<string, unknown>> = [];
  for (const entry of value) {
    const record = asRecord(entry);
    if (!record) {
      continue;
    }
    normalized.push({
      ...record,
      entryId: asString(record.entryId),
      fromProfileId: asString(record.fromProfileId),
      toProfileId: asString(record.toProfileId),
      reason: asString(record.reason),
      timestamp: asString(record.timestamp),
    });
  }
  return normalized;
}

function normalizeProtocolCatalog(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return [];
  }
  const normalized: Array<Record<string, unknown>> = [];
  for (const entry of value) {
    const record = asRecord(entry);
    if (!record) {
      continue;
    }
    normalized.push({
      ...record,
      protocol: asString(record.protocol),
      protocolFamily: asString(record.protocol_family),
      clientKind: asString(record.client_kind),
      completionLabel: asString(record.completion_label),
      endpointHint: asString(record.endpoint_hint),
      testMode: asString(record.test_mode),
    });
  }
  return normalized;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value
        .filter((entry): entry is string => typeof entry === 'string')
        .map((entry) => entry.trim())
        .filter(Boolean)
    : [];
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function draftCapabilities(
  protocol: ProviderConfig['protocol'] | undefined,
  value: unknown,
): CapabilityFlags {
  const defaults = defaultCapabilitiesForProtocol(protocol);
  const supplied = asRecord(value);
  for (const capability of Object.keys(defaults) as Array<keyof CapabilityFlags>) {
    if (typeof supplied?.[capability] === 'boolean') {
      defaults[capability] = supplied[capability] as boolean;
    }
  }
  return defaults;
}

async function resolveDraftProviderModelLookup(
  context: CommandContext,
  payload: unknown,
): Promise<DraftProviderModelLookup> {
  const input = asRecord(payload);
  const protocolRaw = asString(input?.protocol);
  const protocol = normalizeProviderProtocol(protocolRaw);
  if (protocolRaw && !protocol) {
    return {
      message:
        'Select a chat protocol before finding models. A gateway connection type is not a protocol, and unknown gateways are not assumed OpenAI-compatible.',
    };
  }
  const baseUrl = normalizeBaseUrl(asString(input?.baseUrl) ?? '', protocol);
  if (!baseUrl) {
    return { message: 'Add the service root before finding models.' };
  }

  const name = asString(input?.name) ?? 'custom-openai-compatible';
  const model = asString(input?.model) ?? '';
  const credentialMode =
    input?.credentialMode === 'workspace_secret' || input?.credentialMode === 'ui_proxy'
      ? input.credentialMode
      : defaultProviderCredentialMode(context.getHostState().workspace);
  const config: ProviderConfig = {
    name,
    baseUrl,
    model,
    protocol,
    apiKeyRef: 'trainer.provider.draft',
    credentialMode,
    allowedModels: asStringArray(input?.allowedModels),
    deniedModels: asStringArray(input?.deniedModels),
    capabilities: draftCapabilities(protocol, input?.capabilities),
    requestDefaults: normalizeProviderRequestDefaults(
      { name, baseUrl, model },
      asRecord(input?.requestDefaults) ?? {},
    ),
  };

  const suppliedApiKey = asString(input?.apiKey);
  if (suppliedApiKey) {
    return { config, apiKey: suppliedApiKey };
  }

  // An omitted key can safely reuse the active secret only for the same service root and protocol.
  if (!hasOwn(input, 'apiKey')) {
    const saved = context.providerStore.getConfig();
    if (
      saved &&
      normalizeProviderProtocol(saved.protocol) === protocol &&
      normalizeBaseUrl(saved.baseUrl, saved.protocol) === baseUrl
    ) {
      const storedApiKey = await context.providerStore.getApiKey();
      if (storedApiKey?.trim()) {
        return { config, apiKey: storedApiKey.trim() };
      }
    }
  }

  return { config, message: 'Add an API key before finding models.' };
}

function draftModelListing(
  config: ProviderConfig,
  result: ProviderModelLookupResult,
): Record<string, unknown> {
  return {
    source: 'draft',
    name: config.name,
    baseUrl: config.baseUrl,
    protocol: normalizeProviderProtocol(config.protocol),
    protocolFamily: providerProtocolFamily(normalizeProviderProtocol(config.protocol)),
    model: config.model,
    availableModels: result.availableModels,
    resolvedModel: result.resolvedModel,
    modelTokenLimits: result.modelTokenLimits,
    fetchedAt: result.fetchedAt,
    errorCategory: result.errorCategory,
    retryable: result.retryable,
    statusCode: result.statusCode,
  };
}

export async function fetchProviderModels(
  context: CommandContext,
  config: ProviderConfig,
  apiKey: string,
  options?: {
    preferCache?: boolean;
    backgroundRefresh?: boolean;
    forceRefresh?: boolean;
    transient?: boolean;
    responseLanguage?: ComposerLanguage;
    generation?: number;
  },
): Promise<
  | ProviderModelLookupResult
  | undefined
> {
  if (config.model.trim()) {
    const modelPolicy = evaluateProviderModelPolicy(config.model, config);
    if (!modelPolicy.allowed) {
      return {
        ok: false,
        detail: `${providerModelPolicyMessage(modelPolicy)} Trainer did not contact the provider.`,
        availableModels: filterProviderModelOptions(config.availableModels ?? [], config, {
          retainModels: [config.model],
        }),
        source: options?.transient ? 'live' : 'cache',
        errorCategory: `model_${modelPolicy.reason}`,
        retryable: false,
      };
    }
  }

  if (!options?.transient) {
    const cache = context.providerStore.getModelCache(config);
    const cacheFresh =
      context.providerStore.isModelCacheFresh(cache) &&
      context.providerStore.isModelCacheCompatible(config, cache, apiKey);
    if (options?.preferCache && cacheFresh && !options?.forceRefresh) {
      const cachedEntry = cache;
      if (!cachedEntry) {
        return undefined;
      }
      const cachedResult: ProviderModelLookupResult = {
        ok: cachedEntry.availableModels.length > 0,
        detail: sanitizeErrorSurfaceText(
          cachedEntry.lastError || `Using cached model list from ${cachedEntry.fetchedAt}.`,
        ),
        availableModels: cachedEntry.availableModels,
        resolvedModel: cachedEntry.resolvedModel,
        modelTokenLimits: cachedEntry.modelTokenLimits,
        source: 'cache',
        fetchedAt: cachedEntry.fetchedAt,
        expiresAt: cachedEntry.expiresAt,
        errorCategory: cachedEntry.lastErrorCategory,
        retryable: cachedEntry.retryable,
        statusCode: cachedEntry.lastStatusCode,
      };

      if (options.backgroundRefresh) {
        void refreshProviderModelsInBackground(
          context,
          config,
          apiKey,
          options.generation ?? activeProviderModelLookupGeneration(context),
        );
      }
      return applyProviderModelPolicyToLookup(config, cachedResult);
    }
  }

  if (!(await context.trustGuard.ensureTrusted('fetch provider models'))) {
    return {
      ok: false,
      detail: 'Workspace trust is required before Trainer can fetch provider models.',
      availableModels: [],
      source: options?.transient ? 'live' : 'cache',
      errorCategory: 'workspace_trust',
      retryable: false,
    };
  }

  const status = await context.sidecarManager.ensureRunning();
  if (status.lifecycle !== 'ready' || !status.port) {
    return {
      ok: false,
      detail: status.detail ?? 'Sidecar is unavailable, so Trainer could not fetch models.',
      availableModels: [],
      source: options?.transient ? 'live' : 'cache',
      errorCategory: 'sidecar_unavailable',
      retryable: true,
    };
  }
  const port = status.port;

  const requestKey = options?.transient
    ? undefined
    : providerModelLookupRequestKey(config, apiKey);
  if (requestKey) {
    const existingLookup = inflightModelLookups.get(requestKey);
    if (existingLookup) {
      return existingLookup;
    }
  }

  const lookupPromise = (async (): Promise<ProviderModelLookupResult> => {
    const fetchedAt = new Date().toISOString();
    try {
      const response = await context.sidecarClient.postJson<ProviderModelsResponse>(
        port,
        '/provider/models',
        providerModelsRequestBody(context, config, apiKey, options?.responseLanguage),
        { timeoutMs: SIDECAR_DEFAULTS.providerRequestTimeoutMs },
      );

      const availableModels = Array.isArray(response.available_models) ? response.available_models : [];
      const resolvedModel =
        typeof response.resolved_model === 'string' && response.resolved_model.trim()
          ? response.resolved_model.trim()
          : undefined;
      const modelTokenLimits = normalizeProviderModelTokenLimits(
        response.model_token_limits ?? response.modelTokenLimits,
      );
      // Fail-closed: never persist/UI key-shaped model-list detail.
      const safeDetail = response.detail?.trim()
        ? sanitizeErrorSurfaceText(response.detail)
        : undefined;
      const lookup = applyProviderModelPolicyToLookup(config, {
        ok: Boolean(response.ok),
        detail: safeDetail,
        availableModels,
        resolvedModel,
        modelTokenLimits,
        source: 'live',
        fetchedAt,
        errorCategory: response.error_category,
        retryable: response.retryable,
        statusCode: response.status_code,
      });
      if (options?.transient) {
        return lookup;
      }

      const effectiveCacheConfig = applyProviderModelCatalog(config, {
        resolvedModel: lookup.resolvedModel ?? config.model,
        modelTokenLimits: lookup.modelTokenLimits,
      });
      const savedCache = await context.providerStore.saveModelCache(effectiveCacheConfig, {
        availableModels: lookup.availableModels,
        resolvedModel: lookup.resolvedModel,
        modelTokenLimits: lookup.modelTokenLimits,
        lastError: response.ok ? undefined : safeDetail ?? lookup.detail,
        lastErrorCategory: response.error_category,
        lastStatusCode: response.status_code,
        retryable: response.retryable,
        fetchedAt,
        source: 'live',
        apiKey,
      });
      if (response.ok) {
        await reconcileProviderSuccessState(context, config, apiKey, options?.generation);
      }

      return {
        ...lookup,
        fetchedAt: savedCache.fetchedAt,
        expiresAt: savedCache.expiresAt,
      };
    } catch {
      if (options?.transient) {
        return {
          ok: false,
          detail: 'Trainer could not get the model list right now. Check the service root and key, then try again.',
          availableModels: [],
          source: 'live',
          fetchedAt,
          errorCategory: 'sidecar_request_failed',
          retryable: true,
        };
      }
      const savedCache = await context.providerStore.saveModelCache(config, {
        availableModels: [],
        lastError: 'Trainer could not get the model list right now. The saved model can still be tested.',
        lastErrorCategory: 'sidecar_request_failed',
        retryable: true,
        fetchedAt,
        source: 'live',
        apiKey,
      });
      return {
        ok: false,
        detail: 'Trainer could not get the model list right now. The saved model can still be tested.',
        availableModels: [],
        source: 'live',
        fetchedAt: savedCache.fetchedAt,
        expiresAt: savedCache.expiresAt,
        errorCategory: 'sidecar_request_failed',
        retryable: true,
      };
    }
  })();

  if (requestKey) {
    inflightModelLookups.set(requestKey, lookupPromise);
  }
  try {
    return await lookupPromise;
  } finally {
    if (requestKey) {
      inflightModelLookups.delete(requestKey);
    }
  }
}

async function refreshProviderModelsInBackground(
  context: CommandContext,
  config: ProviderConfig,
  apiKey: string,
  generation: number,
): Promise<void> {
  const result = await fetchProviderModels(context, config, apiKey, {
    preferCache: false,
    backgroundRefresh: false,
    forceRefresh: true,
    generation,
  });
  if (!result) {
    return;
  }

  if (!(await isCurrentProviderModelLookup(context, config, apiKey, generation))) {
    return;
  }

  let finalConfig = config;
  const nextConfig = applyModelLookupToProviderConfig(config, result);
  if (providerCatalogConfigDiffers(config, nextConfig)) {
    await context.providerStore.saveConfig(nextConfig, undefined);
    finalConfig = context.providerStore.getConfig() ?? nextConfig;
    if (finalConfig.model !== config.model) {
      await context.providerStore.saveModelCache(finalConfig, {
        availableModels: result.availableModels,
        resolvedModel: result.resolvedModel,
        modelTokenLimits: result.modelTokenLimits,
        lastError: result.ok ? undefined : result.detail,
        lastErrorCategory: result.errorCategory,
        lastStatusCode: result.statusCode,
        retryable: result.retryable,
        fetchedAt: result.fetchedAt,
        source: 'live',
        apiKey,
      });
    }
  } else {
    finalConfig = nextConfig;
  }

  const finalViewState = applyDerivedHostState(
    context.getHostState().bootstrap,
    finalConfig,
    context.getHostState().sidecar,
    context.getHostState().workspace,
    context.getSessionId(),
    true,
  ).providerConfig;

  await context.patchWorkbenchData({
    providerConfig: {
      ...finalViewState,
      availableModels: result.availableModels,
      resolvedModel: result.resolvedModel,
      modelListStatus: result.ok ? 'ready' : 'error',
      modelListDetail: result.detail,
      cacheFetchedAt: result.fetchedAt,
      cacheExpiresAt: result.expiresAt,
      cacheSource: result.source,
      modelErrorCategory: result.errorCategory,
      modelStatusCode: result.statusCode,
      modelRetryable: result.retryable,
      lastTestResult: storedLastTestResult(context, finalConfig),
    },
  });
  await context.workbench.syncState();
}

async function refreshDraftProviderModelsCommand(
  context: CommandContext,
  draftPayload: unknown,
): Promise<CommandExecutionResult<ProviderConfig>> {
  const draft = await resolveDraftProviderModelLookup(context, draftPayload);
  if (!draft.config || !draft.apiKey) {
    return {
      ok: false,
      message: draft.message ?? 'Add the service root and API key before finding models.',
    };
  }

  const config = draft.config;
  const draftGeneration = nextDraftModelLookupGeneration(context);
  const activeModelLookupGeneration = activeProviderModelLookupGeneration(context);
  const activeConfigAtStart = context.providerStore.getConfig();
  const currentView = context.getHostState().bootstrap.providerConfig;
  await context.patchWorkbenchData({
    providerConfig: {
      ...currentView,
      modelListStatus: 'loading',
      modelListDetail: 'Trainer is checking the draft connection for available models.',
      modelListing: {
        source: 'draft',
        name: config.name,
        baseUrl: config.baseUrl,
        protocol: normalizeProviderProtocol(config.protocol),
        protocolFamily: providerProtocolFamily(normalizeProviderProtocol(config.protocol)),
        model: config.model,
        status: 'loading',
      },
    },
  });
  await context.workbench.syncState();

  const result = await fetchProviderModels(context, config, draft.apiKey, {
    forceRefresh: true,
    transient: true,
  });
  if (!result) {
    return {
      ok: false,
      message: 'Trainer could not find models for this draft connection.',
    };
  }

  if (
    !isLatestDraftModelLookup(context, draftGeneration) ||
    activeModelLookupGeneration !== activeProviderModelLookupGeneration(context) ||
    !sameCurrentProviderConfig(context, activeConfigAtStart)
  ) {
    return staleModelLookupResult(context, config);
  }

  await context.patchWorkbenchData({
    providerConfig: {
      ...context.getHostState().bootstrap.providerConfig,
      modelListStatus: result.ok ? 'ready' : 'error',
      modelListDetail: result.detail,
      cacheFetchedAt: result.fetchedAt,
      cacheExpiresAt: undefined,
      cacheSource: result.source,
      modelErrorCategory: result.errorCategory,
      modelStatusCode: result.statusCode,
      modelRetryable: result.retryable,
      modelListing: draftModelListing(config, result),
    },
  });
  await context.workbench.syncState();

  return {
    ok: result.ok,
    message:
      result.detail ??
      (result.ok
        ? 'Draft model list refreshed. Your saved connection was not changed.'
        : 'Trainer could not find models for this draft connection.'),
    data: config,
  };
}

export async function refreshProviderModelsCommand(
  context: CommandContext,
  payload?: RefreshProviderModelsPayload,
): Promise<CommandExecutionResult<ProviderConfig>> {
  if (hasOwn(payload, 'draft')) {
    return refreshDraftProviderModelsCommand(context, payload?.draft);
  }

  const modelLookupGeneration = nextActiveProviderModelLookupGeneration(context);
  const config = context.providerStore.getConfig();
  if (!config) {
    return {
      ok: false,
      message: 'Save a provider before refreshing the model list.',
    };
  }

  const apiKey = await context.providerStore.getApiKey();
  if (!apiKey?.trim()) {
    return {
      ok: false,
      message: 'Add an API key before refreshing live models.',
    };
  }

  await context.patchWorkbenchData({
    providerConfig: {
      ...context.getHostState().bootstrap.providerConfig,
      modelListStatus: 'loading',
      modelListDetail: 'Trainer is refreshing the live model list now.',
      lastTestResult: storedLastTestResult(context, config),
    },
  });
  await context.workbench.syncState();

  const result = await fetchProviderModels(context, config, apiKey, {
    preferCache: false,
    backgroundRefresh: false,
    forceRefresh: true,
    generation: modelLookupGeneration,
  });

  if (!result) {
    return {
      ok: false,
      message: 'Trainer could not refresh the model list.',
    };
  }

  if (!(await isCurrentProviderModelLookup(context, config, apiKey, modelLookupGeneration))) {
    return staleModelLookupResult(context, config);
  }

  const nextConfig = applyModelLookupToProviderConfig(config, result);
  let effectiveConfig = config;
  if (providerCatalogConfigDiffers(config, nextConfig)) {
    await context.providerStore.saveConfig(nextConfig, undefined);
    effectiveConfig = context.providerStore.getConfig() ?? nextConfig;
    if (effectiveConfig.model !== config.model) {
      await context.providerStore.saveModelCache(
        effectiveConfig,
        {
          availableModels: result.availableModels,
          resolvedModel: result.resolvedModel,
          modelTokenLimits: result.modelTokenLimits,
          lastError: result.ok ? undefined : result.detail,
          lastErrorCategory: result.errorCategory,
          lastStatusCode: result.statusCode,
          retryable: result.retryable,
          fetchedAt: result.fetchedAt,
          source: 'live',
          apiKey,
        },
      );
    }
  } else {
    effectiveConfig = nextConfig;
  }

  const finalViewState = applyDerivedHostState(
    context.getHostState().bootstrap,
    effectiveConfig,
    context.getHostState().sidecar,
    context.getHostState().workspace,
    context.getSessionId(),
    true,
  ).providerConfig;

  await context.patchWorkbenchData({
    providerConfig: {
      ...finalViewState,
      availableModels: result.availableModels,
      resolvedModel: result.resolvedModel,
      modelListStatus: result.ok ? 'ready' : 'error',
      modelListDetail: result.detail,
      cacheFetchedAt: result.fetchedAt,
      cacheExpiresAt: result.expiresAt,
      cacheSource: result.source,
      modelErrorCategory: result.errorCategory,
      modelStatusCode: result.statusCode,
      modelRetryable: result.retryable,
      lastTestResult: storedLastTestResult(context, effectiveConfig),
    },
  });
  await context.workbench.syncState();

  return {
    ok: result.ok,
    message:
      result.detail ??
      (result.ok
        ? 'Live model list refreshed.'
        : 'Trainer could not refresh the provider model list.'),
    data: effectiveConfig,
  };
}

export async function switchProviderModelCommand(
  context: CommandContext,
  payload?: SwitchProviderModelPayload,
): Promise<CommandExecutionResult<ProviderConfig>> {
  const model = payload?.model?.trim();
  if (!model) {
    return {
      ok: false,
      message: 'model is required.',
    };
  }

  const config = context.providerStore.getConfig();
  if (!config) {
    return {
      ok: false,
      message: 'Save a provider before switching models.',
    };
  }

  const modelPolicy = evaluateProviderModelPolicy(model, config);
  if (!modelPolicy.allowed) {
    return providerModelPolicyFailure(
      modelPolicy,
      'Trainer kept your current model and did not change the connection.',
    );
  }

  nextActiveProviderModelLookupGeneration(context);

  const currentView = context.getHostState().bootstrap.providerConfig;
  const availableModels = Array.from(
    new Set(
      [
        ...(Array.isArray(config.availableModels) ? config.availableModels : []),
        ...(Array.isArray(currentView.availableModels) ? currentView.availableModels : []),
      ]
        .map((entry) => (typeof entry === 'string' ? entry.trim() : ''))
        .filter(Boolean),
    ),
  );
  const configuredModelCatalog = Array.from(
    new Set(
      [
        ...(Array.isArray(config.catalogModels) ? config.catalogModels : []),
        ...(Array.isArray(currentView.catalogModels) ? currentView.catalogModels : []),
        ...Object.keys(config.modelTokenLimits ?? {}),
        ...Object.keys(currentView.modelTokenLimits ?? {}),
      ]
        .map((entry) => entry.trim())
        .filter(Boolean),
    ),
  );
  const selectableModels = Array.from(new Set([...availableModels, ...configuredModelCatalog]));
  if (
    selectableModels.length > 0 &&
    !selectableModels.some((entry) => entry.toLowerCase() === model.toLowerCase())
  ) {
    return {
      ok: false,
      message: `Model '${model}' is not in the current provider model list or configured model catalog.`,
    };
  }

  const currentModel = config.model?.trim() || currentView.model?.trim();
  if (currentModel?.toLowerCase() === model.toLowerCase()) {
    return {
      ok: true,
      message: `Model '${model}' is already active.`,
      data: config,
    };
  }

  const tokenState = resolveProviderModelTokenState(config, model, {
    hasContextWindowTokens: false,
    hasMaxOutputTokens: false,
    hasModelTokenLimits: false,
  });
  const selectedModelIsLive = availableModels.some(
    (entry) => entry.toLowerCase() === model.toLowerCase(),
  );
  const nextConfig: ProviderConfig = {
    ...config,
    model,
    contextWindowTokens: tokenState.contextWindowTokens,
    maxOutputTokens: tokenState.maxOutputTokens,
    modelTokenLimits: tokenState.modelTokenLimits,
    catalogModels: mergeCatalogModels(
      config.catalogModels,
      currentView.catalogModels,
      config.model,
      currentView.model,
      model,
    ),
    availableModels: availableModels.length > 0 ? availableModels : config.availableModels,
  };
  await context.providerStore.saveConfig(nextConfig);
  if (typeof context.providerStore.clearLastTestResult === 'function') {
    await context.providerStore.clearLastTestResult(nextConfig, {
      workspaceId: getRuntimeWorkspaceId(context),
    });
  }

  const apiKey = await context.providerStore.getApiKey();
  const effectiveConfig = context.providerStore.getConfig() ?? nextConfig;
  const nextViewState = applyDerivedHostState(
    context.getHostState().bootstrap,
    effectiveConfig,
    context.getHostState().sidecar,
    context.getHostState().workspace,
    context.getSessionId(),
    Boolean(apiKey?.trim()),
  ).providerConfig;
  const selectionDetail = `Trainer switched to ${model}. Test or send next to verify reply quality on this model.`;

  await context.patchWorkbenchData({
    providerConfig: {
      ...nextViewState,
      ...effectiveConfig,
      availableModels: availableModels.length > 0 ? availableModels : nextViewState.availableModels,
      resolvedModel: model,
      modelListStatus: selectedModelIsLive ? 'ready' : 'idle',
      modelListDetail: selectedModelIsLive
        ? selectionDetail
        : `Trainer switched to ${model} from the configured catalog. Test or refresh models before treating it as available.`,
      modelErrorCategory: undefined,
      modelStatusCode: undefined,
      modelRetryable: undefined,
      lastTestResult: storedLastTestResult(context, effectiveConfig),
    },
    connection: {
      ...context.getHostState().bootstrap.connection,
      provider: {
        ...context.getHostState().bootstrap.connection.provider,
        ...providerConnectionPatch({
          ...effectiveConfig,
          model,
        }),
      },
    },
  });
  await context.workbench.syncState();

  return {
    ok: true,
    message: `Switched to model '${model}'.`,
    data: effectiveConfig,
  };
}

export async function primeProviderModelsState(context: CommandContext): Promise<void> {
  const modelLookupGeneration = activeProviderModelLookupGeneration(context);
  const config = context.providerStore.getConfig();
  const apiKey = await context.providerStore.getApiKey();

  if (!config || !apiKey?.trim()) {
    return;
  }

  const result = await fetchProviderModels(context, config, apiKey, {
    preferCache: true,
    backgroundRefresh: true,
    generation: modelLookupGeneration,
  });

  if (!result) {
    return;
  }

  if (!(await isCurrentProviderModelLookup(context, config, apiKey, modelLookupGeneration))) {
    return;
  }

  let finalConfig = config;
  const nextConfig = applyModelLookupToProviderConfig(config, result);
  if (providerCatalogConfigDiffers(config, nextConfig)) {
    await context.providerStore.saveConfig(nextConfig, undefined);
    finalConfig = context.providerStore.getConfig() ?? nextConfig;
    if (finalConfig.model !== config.model) {
      await context.providerStore.saveModelCache(finalConfig, {
        availableModels: result.availableModels,
        resolvedModel: result.resolvedModel,
        modelTokenLimits: result.modelTokenLimits,
        lastError: result.ok ? undefined : result.detail,
        lastErrorCategory: result.errorCategory,
        lastStatusCode: result.statusCode,
        retryable: result.retryable,
        fetchedAt: result.fetchedAt,
        source: result.source,
        apiKey,
      });
    }
  } else {
    finalConfig = nextConfig;
  }

  const finalViewState = applyDerivedHostState(
    context.getHostState().bootstrap,
    finalConfig,
    context.getHostState().sidecar,
    context.getHostState().workspace,
    context.getSessionId(),
    true,
  ).providerConfig;

  await context.patchWorkbenchData({
    providerConfig: {
      ...finalViewState,
      availableModels: result.availableModels,
      resolvedModel: result.resolvedModel,
      modelListStatus: result.ok ? 'ready' : 'error',
      modelListDetail: result.detail,
      cacheFetchedAt: result.fetchedAt,
      cacheExpiresAt: result.expiresAt,
      cacheSource: result.source,
      modelErrorCategory: result.errorCategory,
      modelStatusCode: result.statusCode,
      modelRetryable: result.retryable,
      lastTestResult: storedLastTestResult(context, finalConfig),
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
}
