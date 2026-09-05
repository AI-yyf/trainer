import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';

import { SECRET_KEYS, STORAGE_KEYS } from '../core/constants';
import type {
  CapabilityFlags,
  ProviderConfig,
  ProviderProtocol,
  ProviderTaskBinding,
  ProviderLastTestResult,
  ProviderCapabilityVerificationState,
  ProviderModelCache,
  ResolvedProviderConfig,
} from '../core/types';
import type { ProviderCapabilityEvidence } from '../../../shared/src/providerTest';
import { normalizeProviderRequestDefaults } from '../core/providerDefaults';
import { mergeProviderRequestDefaults } from '../../../shared/src/providerRequestDefaults';
import { defaultCapabilitiesForProtocol, normalizeProviderProtocol, OPENAI_COMPATIBLE_PROTOCOL } from '../../../shared/src/providerProtocols';
import { normalizeProviderConnectionType } from '../../../shared/src/providerGateway';
import { normalizeProviderThinkingConfig } from '../../../shared/src/providerThinking';
import {
  clearHostLastTest,
  selectHostLastTest,
  stripHostLastTestSecrets,
  writeHostLastTest,
  type HostLastTestScope,
} from '../../../shared/src/hostLastTestGovernance';
import {
  mergeProviderModelTokenLimits,
  normalizeProviderModelTokenLimits,
  readProviderModelTokenLimit,
  withProviderModelTokenLimit,
} from '../../../shared/src/providerModelTokenLimits';
import {
  type ProviderProfileConfig,
  type ProviderProfileRegistryData,
  ProviderProfileRegistry,
} from './providerProfileRegistry';

const PROVIDER_API_KEY_REF_PREFIX = 'trainer.provider';

function textScope(value: string | undefined): string {
  return value?.trim() ?? '';
}

function asVerificationState(value: unknown): ProviderCapabilityVerificationState | undefined {
  return value === 'verified' || value === 'unsupported' || value === 'unverified' || value === 'disabled'
    ? value
    : undefined;
}

function asStoredLastTestResult(value: Record<string, unknown>): ProviderLastTestResult | undefined {
  const providerName = typeof value.providerName === 'string' ? value.providerName.trim() : '';
  const baseUrl = typeof value.baseUrl === 'string' ? value.baseUrl.trim() : '';
  const model = typeof value.model === 'string' ? value.model.trim() : '';
  const checkedAt = typeof value.checkedAt === 'string' ? value.checkedAt.trim() : '';
  const status = typeof value.status === 'string' ? value.status.trim() : '';
  const detail = typeof value.detail === 'string' ? value.detail : '';
  if (!providerName || !baseUrl || !model || !checkedAt || !status) {
    return undefined;
  }
  return {
    ok: value.ok === true,
    status,
    detail,
    checkedAt,
    workspaceId: typeof value.workspaceId === 'string' ? value.workspaceId : undefined,
    profileId: typeof value.profileId === 'string' ? value.profileId : undefined,
    providerName,
    baseUrl,
    model,
    protocol: typeof value.protocol === 'string' ? normalizeProviderProtocol(value.protocol) : undefined,
    protocolFamily: typeof value.protocolFamily === 'string' ? value.protocolFamily : undefined,
    errorCategory: typeof value.errorCategory === 'string' ? value.errorCategory : undefined,
    retryable: typeof value.retryable === 'boolean' ? value.retryable : undefined,
    statusCode: typeof value.statusCode === 'number' ? value.statusCode : undefined,
    responseLanguage: typeof value.responseLanguage === 'string' ? value.responseLanguage : undefined,
    capabilityEvidence: Array.isArray(value.capabilityEvidence)
      ? value.capabilityEvidence.flatMap((item): ProviderCapabilityEvidence[] => {
          if (!item || typeof item !== 'object') {
            return [];
          }
          const entry = item as Record<string, unknown>;
          const name = typeof entry.name === 'string' ? entry.name.trim() : '';
          const state = asVerificationState(entry.state);
          if (!name || !state) {
            return [];
          }
          return [
            {
              name,
              declared: entry.declared === true,
              observed: typeof entry.observed === 'boolean' ? entry.observed : null,
              state,
            },
          ];
        })
      : undefined,
    toolsReady: typeof value.toolsReady === 'boolean' ? value.toolsReady : undefined,
    toolProbeStatus: asVerificationState(value.toolProbeStatus),
    streamingReady: typeof value.streamingReady === 'boolean' ? value.streamingReady : undefined,
    streamProbeStatus: asVerificationState(value.streamProbeStatus),
    visionReady: typeof value.visionReady === 'boolean' ? value.visionReady : undefined,
    visionProbeStatus: asVerificationState(value.visionProbeStatus),
    thinkingReady: typeof value.thinkingReady === 'boolean' ? value.thinkingReady : undefined,
    thinkingProbeStatus: asVerificationState(value.thinkingProbeStatus),
  };
}

type ProviderConnectionReference = Pick<ProviderConfig, 'baseUrl'> &
  Partial<Pick<ProviderConfig, 'protocol' | 'profileId'>>;

/**
 * SecretStorage keys are opaque identifiers. They must never be derived from
 * a display label because distinct non-ASCII labels can normalize to the same
 * ASCII string.
 */
export function createProviderApiKeyRef(): string {
  return `${PROVIDER_API_KEY_REF_PREFIX}.${crypto.randomUUID()}`;
}

export function providerConnectionMatches(
  existing: Pick<ProviderConfig, 'baseUrl' | 'protocol'> | undefined,
  candidate: ProviderConnectionReference,
): boolean {
  if (!existing) {
    return false;
  }

  const normalizeBaseUrl = (value: string) => value.trim().replace(/\/+$/, '').toLowerCase();
  return (
    normalizeProviderProtocol(existing.protocol) === normalizeProviderProtocol(candidate.protocol) &&
    normalizeBaseUrl(existing.baseUrl) === normalizeBaseUrl(candidate.baseUrl)
  );
}

/**
 * Keep the reference for the same saved connection, while assigning every new
 * connection an opaque UUID-backed reference. Legacy references remain valid.
 */
export function resolveProviderApiKeyRef(
  existing: ProviderConfig | undefined,
  candidate: ProviderConnectionReference,
): string {
  const existingRef = existing?.apiKeyRef?.trim();
  if (!existingRef) {
    return createProviderApiKeyRef();
  }

  const candidateProfileId = candidate.profileId?.trim();
  if (candidateProfileId && candidateProfileId === existing?.profileId?.trim()) {
    return existingRef;
  }

  return providerConnectionMatches(existing, candidate) ? existingRef : createProviderApiKeyRef();
}

export class ProviderConfigStore implements vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<ProviderConfig | undefined>();
  private readonly profileRegistry: ProviderProfileRegistry;
  private static readonly MODEL_CACHE_TTL_MS = 1000 * 60 * 60 * 12;
  private static readonly LAST_TEST_RESULT_STORAGE_KEY = 'trainer.provider.lastTestResult';
  private activeWorkspaceId: string | undefined;

  readonly onDidChange = this.emitter.event;

  constructor(private readonly extensionContext: vscode.ExtensionContext) {
    this.extensionContext.globalState.setKeysForSync([STORAGE_KEYS.providerConfig]);
    this.profileRegistry = new ProviderProfileRegistry(extensionContext);
  }

  getStoredConfig(): ProviderConfig | undefined {
    const stored = this.extensionContext.globalState.get<ProviderConfig>(STORAGE_KEYS.providerConfig);
    return stored ? this.materializeProviderConfig(stored) : undefined;
  }

  getConfig(): ProviderConfig | undefined {
    const stored = this.getStoredConfig();
    const profileConfig = this.getWorkspaceProfileConfig() ?? this.getActiveRegistryProfileConfig();
    return this.getWorkspaceOverrideConfig(profileConfig ?? stored) ?? profileConfig ?? stored;
  }

  async getResolvedConfig(): Promise<ResolvedProviderConfig | undefined> {
    const config = this.getConfig();
    if (!config) {
      return undefined;
    }

    const apiKey = await this.extensionContext.secrets.get(this.secretKey(config.apiKeyRef));
    return {
      ...config,
      apiKey: apiKey ?? undefined,
    };
  }

  getActiveProfileConfig(): ProviderConfig | undefined {
    const profileConfig = this.getWorkspaceProfileConfig() ?? this.getActiveRegistryProfileConfig();
    if (!profileConfig) {
      return this.getConfig();
    }
    return this.getWorkspaceOverrideConfig(profileConfig) ?? profileConfig;
  }

  getActiveProfile(): ProviderConfig | undefined {
    return this.getActiveProfileConfig();
  }

  getProfileRegistrySnapshot(): ProviderProfileRegistryData {
    const registry = this.profileRegistry.getRegistry();
    if (registry) {
      return {
        ...registry,
        profiles: [...registry.profiles],
        switchHistory: [...registry.switchHistory],
      };
    }

    return {
      version: '2.0.0',
      activeProfileId: this.profileRegistry.getActiveProfileId() ?? '',
      profiles: this.profileRegistry.getAllProfiles(),
      switchHistory: this.profileRegistry.getSwitchHistory(),
      lastModified: new Date().toISOString(),
    };
  }

  async saveConfig(config: ProviderConfig, apiKey?: string): Promise<void> {
    const previousStored = this.getStoredConfig();
    const previousEffective = this.getConfig();
    const targetProfileId = this.resolveKnownProfileId(config, previousEffective);
    const previousTargetProfile = targetProfileId
      ? this.getProfileConfigById(targetProfileId)
      : undefined;
    const requestedApiKeyRef = config.apiKeyRef?.trim();
    const conflictingApiKeyRef = Boolean(
      requestedApiKeyRef && this.isApiKeyRefUsedByAnotherProfile(requestedApiKeyRef, targetProfileId),
    );
    const shouldMoveSharedProfileCredential = Boolean(
      conflictingApiKeyRef &&
        targetProfileId &&
        previousTargetProfile?.apiKeyRef.trim() === requestedApiKeyRef &&
        apiKey === undefined,
    );
    const inheritedApiKey = shouldMoveSharedProfileCredential
      ? await this.extensionContext.secrets.get(this.secretKey(requestedApiKeyRef ?? ''))
      : undefined;
    const configWithSafeApiKeyRef: ProviderConfig = {
      ...config,
      apiKeyRef:
        requestedApiKeyRef && !conflictingApiKeyRef
          ? requestedApiKeyRef
          : createProviderApiKeyRef(),
    };

    if (targetProfileId) {
      await this.updateProfileConfig(targetProfileId, configWithSafeApiKeyRef);
    }

    const nextConfig = this.materializeProviderConfig(
      configWithSafeApiKeyRef,
      targetProfileId ? this.getProfileConfigById(targetProfileId) : previousEffective,
    );
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerConfig, nextConfig);
    await this.syncWorkspaceProviderOverride(nextConfig);

    const configsToClean = this.previousConfigsForSave(
      targetProfileId,
      previousStored,
      previousEffective,
      previousTargetProfile,
    );
    for (const apiKeyRef of this.collectPreviousApiKeyRefs(configsToClean, nextConfig)) {
      if (!this.isApiKeyRefUsedByAnotherProfile(apiKeyRef, targetProfileId)) {
        await this.extensionContext.secrets.delete(this.secretKey(apiKeyRef));
      }
    }

    for (const previous of configsToClean) {
      if (this.providerFingerprint(previous) !== this.providerFingerprint(nextConfig)) {
        await this.clearModelCache(previous);
        await this.clearLastTestResult(previous);
      }
    }

    if (apiKey !== undefined) {
      if (apiKey.trim()) {
        await this.extensionContext.secrets.store(this.secretKey(nextConfig.apiKeyRef), apiKey.trim());
      } else if (!this.isApiKeyRefUsedByAnotherProfile(nextConfig.apiKeyRef, targetProfileId)) {
        await this.extensionContext.secrets.delete(this.secretKey(nextConfig.apiKeyRef));
      }
      await this.clearLastTestResult(nextConfig);
    } else if (inheritedApiKey?.trim()) {
      await this.extensionContext.secrets.store(this.secretKey(nextConfig.apiKeyRef), inheritedApiKey);
    }

    this.emitter.fire(this.getConfig() ?? nextConfig);
  }

  async clear(): Promise<void> {
    const previousStored = this.getStoredConfig();
    const previousEffective = this.getConfig();
    const profileSource = previousEffective ?? previousStored;
    const targetProfileId = profileSource
      ? this.resolveKnownProfileId(profileSource, previousEffective)
      : undefined;
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerConfig, undefined);
    await this.syncWorkspaceProviderOverride(undefined);
    if (this.profileRegistry.getActiveProfileId()) {
      await this.profileRegistry.clearActiveProfile('manual_clear');
    }
    for (const apiKeyRef of this.collectPreviousApiKeyRefs([previousStored, previousEffective])) {
      if (!this.isApiKeyRefUsedByAnotherProfile(apiKeyRef, targetProfileId)) {
        await this.extensionContext.secrets.delete(this.secretKey(apiKeyRef));
      }
    }
    for (const previous of this.uniquePreviousConfigs(previousStored, previousEffective)) {
      await this.clearModelCache(previous);
      await this.clearLastTestResult(previous);
    }
    this.emitter.fire(this.getConfig());
  }

  async getApiKey(): Promise<string | undefined> {
    const config = this.getConfig();
    if (!config) {
      return undefined;
    }

    return this.extensionContext.secrets.get(this.secretKey(config.apiKeyRef));
  }

  getModelCache(config = this.getConfig()): ProviderModelCache | undefined {
    if (!config) {
      return undefined;
    }

    const allCaches =
      this.extensionContext.globalState.get<Record<string, ProviderModelCache>>(STORAGE_KEYS.providerModelCache) ?? {};
    return allCaches[this.providerFingerprint(config)];
  }

  async saveModelCache(
    config: ProviderConfig,
    payload: {
      availableModels: string[];
      resolvedModel?: string;
      modelTokenLimits?: ProviderConfig['modelTokenLimits'];
      lastError?: string;
      lastErrorCategory?: string;
      lastStatusCode?: number;
      retryable?: boolean;
      fetchedAt?: string;
      ttlMs?: number;
      source?: 'live' | 'cache';
      apiKey?: string;
    },
  ): Promise<ProviderModelCache> {
    const allCaches =
      this.extensionContext.globalState.get<Record<string, ProviderModelCache>>(STORAGE_KEYS.providerModelCache) ?? {};
    const cacheKey = this.providerFingerprint(config);
    const existing = allCaches[cacheKey];
    const preserveCachedModels =
      payload.availableModels.length === 0 &&
      Boolean(existing?.availableModels.length) &&
      existing.providerFingerprint === cacheKey;
    const fetchedAt = preserveCachedModels
      ? existing?.fetchedAt ?? new Date().toISOString()
      : payload.fetchedAt ?? new Date().toISOString();
    const ttlMs = payload.ttlMs ?? ProviderConfigStore.MODEL_CACHE_TTL_MS;
    const expiresAt = preserveCachedModels
      ? existing?.expiresAt ?? new Date(Date.parse(fetchedAt) + ttlMs).toISOString()
      : new Date(Date.parse(fetchedAt) + ttlMs).toISOString();
    const nextModelTokenLimits = mergeProviderModelTokenLimits(
      normalizeProviderModelTokenLimits(payload.modelTokenLimits),
      existing?.modelTokenLimits,
    );
    const nextEntry: ProviderModelCache = {
      providerFingerprint: cacheKey,
      availableModels: preserveCachedModels ? [...(existing?.availableModels ?? [])] : [...payload.availableModels],
      resolvedModel: payload.resolvedModel ?? (preserveCachedModels ? existing?.resolvedModel : undefined),
      modelTokenLimits: nextModelTokenLimits,
      fetchedAt,
      expiresAt,
      source: preserveCachedModels ? 'cache' : payload.source ?? 'live',
      apiKeyDigest: this.apiKeyDigest(payload.apiKey) ?? existing?.apiKeyDigest,
      lastError: payload.lastError,
      lastErrorCategory: payload.lastErrorCategory,
      lastStatusCode: payload.lastStatusCode,
      retryable: payload.retryable,
    };
    allCaches[nextEntry.providerFingerprint] = nextEntry;
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerModelCache, allCaches);
    return nextEntry;
  }

  async clearModelCache(config = this.getConfig()): Promise<void> {
    if (!config) {
      return;
    }
    const allCaches =
      this.extensionContext.globalState.get<Record<string, ProviderModelCache>>(STORAGE_KEYS.providerModelCache) ?? {};
    delete allCaches[this.providerFingerprint(config)];
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerModelCache, allCaches);
  }

  setActiveWorkspaceId(workspaceId: string | undefined): void {
    const next = workspaceId?.trim();
    this.activeWorkspaceId = next || undefined;
  }

  getLastTestResult(
    config = this.getConfig(),
    scope?: Partial<HostLastTestScope>,
  ): ProviderLastTestResult | undefined {
    if (!config) {
      return undefined;
    }
    const resolved = this.resolveLastTestScope(config, scope);
    if (!resolved) {
      return undefined;
    }
    const allResults =
      this.extensionContext.globalState.get<Record<string, unknown>>(
        ProviderConfigStore.LAST_TEST_RESULT_STORAGE_KEY,
      ) ?? {};
    const selected = selectHostLastTest(allResults, resolved, this.providerFingerprint(config));
    return selected ? asStoredLastTestResult(selected) : undefined;
  }

  async saveLastTestResult(
    config: ProviderConfig,
    result: ProviderLastTestResult,
    scope?: Partial<HostLastTestScope>,
  ): Promise<ProviderLastTestResult> {
    const resolved = this.resolveLastTestScope(config, scope);
    if (!resolved) {
      return stripHostLastTestSecrets({
        ...(result as unknown as Record<string, unknown>),
        workspaceId: result.workspaceId,
        profileId: result.profileId ?? config.profileId,
      }) as unknown as ProviderLastTestResult;
    }
    const allResults =
      this.extensionContext.globalState.get<Record<string, unknown>>(
        ProviderConfigStore.LAST_TEST_RESULT_STORAGE_KEY,
      ) ?? {};
    writeHostLastTest(
      allResults,
      resolved,
      this.providerFingerprint(config),
      {
        ...result,
        workspaceId: resolved.workspaceId,
        profileId: resolved.providerProfileId,
      },
    );
    await this.extensionContext.globalState.update(
      ProviderConfigStore.LAST_TEST_RESULT_STORAGE_KEY,
      allResults,
    );
    return stripHostLastTestSecrets({
      ...(result as unknown as Record<string, unknown>),
      workspaceId: resolved.workspaceId,
      profileId: resolved.providerProfileId,
    }) as unknown as ProviderLastTestResult;
  }

  async clearLastTestResult(
    config = this.getConfig(),
    scope?: Partial<HostLastTestScope>,
  ): Promise<void> {
    if (!config) {
      return;
    }
    const resolved = this.resolveLastTestScope(config, scope);
    const allResults =
      this.extensionContext.globalState.get<Record<string, unknown>>(
        ProviderConfigStore.LAST_TEST_RESULT_STORAGE_KEY,
      ) ?? {};
    const fingerprint = this.providerFingerprint(config);
    if (resolved) {
      clearHostLastTest(allResults, resolved, fingerprint);
    } else {
      delete allResults[fingerprint];
      for (const key of Object.keys(allResults)) {
        if (key.endsWith(`|fp:${fingerprint}`)) {
          delete allResults[key];
        }
      }
    }
    await this.extensionContext.globalState.update(
      ProviderConfigStore.LAST_TEST_RESULT_STORAGE_KEY,
      allResults,
    );
  }

  private resolveLastTestScope(
    config: Pick<ProviderConfig, 'profileId'>,
    scope?: Partial<HostLastTestScope>,
  ): HostLastTestScope | undefined {
    const workspaceId = textScope(scope?.workspaceId ?? this.activeWorkspaceId);
    if (!workspaceId) {
      return undefined;
    }
    return {
      workspaceId,
      providerProfileId: textScope(scope?.providerProfileId ?? config.profileId) || undefined,
    };
  }

  isModelCacheFresh(cache: ProviderModelCache | undefined, now = new Date()): boolean {
    if (!cache?.expiresAt) {
      return false;
    }
    const expiresAt = Date.parse(cache.expiresAt);
    return Number.isFinite(expiresAt) && expiresAt > now.getTime();
  }

  isModelCacheCompatible(
    config: ProviderConfig,
    cache: ProviderModelCache | undefined,
    apiKey?: string,
  ): boolean {
    if (!cache) {
      return false;
    }
    if (cache.providerFingerprint !== this.providerFingerprint(config)) {
      return false;
    }
    if (cache.resolvedModel && config.model.trim() && cache.resolvedModel !== config.model.trim()) {
      const requested = config.model.trim().toLowerCase();
      const resolved = cache.resolvedModel.trim().toLowerCase();
      const flattenedRequested = requested.replace(/[._-]/g, '');
      const flattenedResolved = resolved.replace(/[._-]/g, '');
      const availableByLower = new Set(cache.availableModels.map((model) => model.trim().toLowerCase()));
      const requestedListed = availableByLower.has(requested);
      if (requestedListed) {
        return false;
      }
      if (requested !== resolved && flattenedRequested !== flattenedResolved) {
        return false;
      }
    }
    if (cache.apiKeyDigest && apiKey) {
      return cache.apiKeyDigest === this.apiKeyDigest(apiKey);
    }
    return !cache.apiKeyDigest || !apiKey;
  }

  async promptForApiKey(): Promise<void> {
    const existing = this.getConfig() ?? this.createDefaultConfig();
    const apiKey = await vscode.window.showInputBox({
      title: 'Trainer API key',
      prompt: 'Paste the provider API key to store in VS Code SecretStorage.',
      password: true,
      ignoreFocusOut: true,
    });

    if (apiKey === undefined) {
      return;
    }

    await this.saveConfig(existing, apiKey);
  }

  dispose(): void {
    this.profileRegistry.dispose();
    this.emitter.dispose();
  }

  async switchActiveProfile(profileId: string, reason = 'manual_switch'): Promise<boolean> {
    const switched = await this.profileRegistry.switchToProfile(profileId, reason);
    if (!switched) {
      return false;
    }
    this.emitter.fire(this.getConfig());
    return true;
  }

  async switchToProfile(profileId: string, reason = 'manual_switch'): Promise<boolean> {
    return this.switchActiveProfile(profileId, reason);
  }

  async createProfileFromTemplate(
    templateIndex: number,
    apiKey?: string,
  ): Promise<ProviderConfig | undefined> {
    const profile = await this.profileRegistry.createFromTemplate(templateIndex);
    if (!profile) {
      return undefined;
    }

    const updatedProfile = await this.profileRegistry.updateProfile(profile.id, {
      apiKeyRef: createProviderApiKeyRef(),
    });
    const nextProfile = updatedProfile ?? profile;
    if (apiKey?.trim()) {
      await this.extensionContext.secrets.store(this.secretKey(nextProfile.apiKeyRef), apiKey.trim());
    }
    return this.profileToProviderConfig(nextProfile);
  }

  async createProfileFromConfig(
    config: ProviderConfig,
    apiKey?: string,
    reason = 'manual_create_from_draft',
  ): Promise<ProviderConfig | undefined> {
    const protocol = normalizeProviderProtocol(config.protocol);
    if (!protocol) {
      return undefined;
    }
    const profile = await this.profileRegistry.createProfile(
      this.profileFromProviderConfig({
        ...config,
        protocol,
        apiKeyRef: createProviderApiKeyRef(),
      }),
    );
    const trimmedApiKey = apiKey?.trim();
    if (trimmedApiKey) {
      await this.extensionContext.secrets.store(this.secretKey(profile.apiKeyRef), trimmedApiKey);
    }
    await this.profileRegistry.switchToProfile(profile.id, reason);

    const nextConfig = this.getProfileConfigById(profile.id) ?? this.profileToProviderConfig(profile);
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerConfig, nextConfig);
    await this.syncWorkspaceProviderOverride(nextConfig);
    this.emitter.fire(this.getConfig() ?? nextConfig);
    return this.getConfig() ?? nextConfig;
  }

  async createFromTemplate(templateIndex: number, apiKey?: string): Promise<ProviderConfig | undefined> {
    return this.createProfileFromTemplate(templateIndex, apiKey);
  }

  async importProfileRegistry(registry: unknown): Promise<void> {
    const normalizedRegistry = this.normalizeImportedRegistry(registry);
    if (!normalizedRegistry) {
      return;
    }
    await this.profileRegistry.setRegistry(normalizedRegistry);
    this.emitter.fire(this.getConfig());
  }

  async clearAllProfiles(): Promise<void> {
    const registry = this.getProfileRegistrySnapshot();
    const profileConfigs = registry.profiles.map((profile) => this.profileToProviderConfig(profile));
    const profileIds = new Set(registry.profiles.map((profile) => profile.id));
    const storedConfig = this.getStoredConfig();
    const effectiveConfig = this.getConfig();
    const profileBackedConfigs = [storedConfig, effectiveConfig].filter(
      (config): config is ProviderConfig =>
        Boolean(config?.profileId && profileIds.has(config.profileId)),
    );
    const configsToClear = this.uniquePreviousConfigs(
      ...profileConfigs,
      ...profileBackedConfigs,
    );

    await this.profileRegistry.clearAll();

    if (profileBackedConfigs.length > 0) {
      await this.extensionContext.globalState.update(STORAGE_KEYS.providerConfig, undefined);
      await this.syncWorkspaceProviderOverride(undefined);
    }

    for (const config of configsToClear) {
      if (config.apiKeyRef.trim()) {
        await this.extensionContext.secrets.delete(this.secretKey(config.apiKeyRef));
      }
      await this.clearModelCache(config);
      await this.clearLastTestResult(config);
    }

    this.emitter.fire(this.getConfig());
  }

  private secretKey(apiKeyRef: string): string {
    return `${SECRET_KEYS.providerApiKeyPrefix}.${apiKeyRef}`;
  }

  private providerFingerprint(config: ProviderConfig): string {
    return [
      normalizeProviderProtocol(config.protocol) ?? '',
      config.name.trim().toLowerCase(),
      config.baseUrl.trim().toLowerCase(),
      config.model.trim().toLowerCase(),
      config.apiKeyRef.trim().toLowerCase(),
    ].join('::');
  }

  private apiKeyDigest(apiKey: string | undefined): string | undefined {
    if (!apiKey?.trim()) {
      return undefined;
    }
    return crypto.createHash('sha256').update(apiKey.trim()).digest('hex');
  }

  private createDefaultConfig(): ProviderConfig {
    const protocol: ProviderProtocol = OPENAI_COMPATIBLE_PROTOCOL;
    const capabilities: CapabilityFlags = defaultCapabilitiesForProtocol(protocol);
    const model = 'gpt-4.1-mini';

    return {
      name: 'custom-openai-compatible',
      baseUrl: 'http://localhost:1234/v1',
      apiKeyRef: 'custom-openai-compatible.default',
      model,
      protocol,
      capabilities,
      catalogModels: [model],
      modelCapabilities: {},
    };
  }

  private uniquePreviousConfigs(...configs: Array<ProviderConfig | undefined>): ProviderConfig[] {
    const unique = new Map<string, ProviderConfig>();
    for (const config of configs) {
      if (!config) {
        continue;
      }
      unique.set(this.providerFingerprint(config), config);
    }
    return [...unique.values()];
  }

  private previousConfigsForSave(
    targetProfileId: string | undefined,
    previousStored: ProviderConfig | undefined,
    previousEffective: ProviderConfig | undefined,
    previousTargetProfile: ProviderConfig | undefined,
  ): ProviderConfig[] {
    if (!targetProfileId) {
      return this.uniquePreviousConfigs(previousStored, previousEffective);
    }

    return this.uniquePreviousConfigs(
      previousTargetProfile,
      this.readProfileId(previousStored) === targetProfileId ? previousStored : undefined,
      this.readProfileId(previousEffective) === targetProfileId ? previousEffective : undefined,
    );
  }

  private collectPreviousApiKeyRefs(
    previousConfigs: Array<ProviderConfig | undefined>,
    nextConfig?: ProviderConfig,
  ): string[] {
    const refs = new Set<string>();
    for (const config of previousConfigs) {
      if (config?.apiKeyRef?.trim()) {
        refs.add(config.apiKeyRef.trim());
      }
    }
    if (nextConfig?.apiKeyRef?.trim()) {
      refs.delete(nextConfig.apiKeyRef.trim());
    }
    return [...refs];
  }

  private isApiKeyRefUsedByAnotherProfile(
    apiKeyRef: string,
    targetProfileId: string | undefined,
  ): boolean {
    const normalizedRef = apiKeyRef.trim();
    return Boolean(
      normalizedRef &&
        this.profileRegistry
          .getAllProfiles()
          .some((profile) => profile.id !== targetProfileId && profile.apiKeyRef.trim() === normalizedRef),
    );
  }

  private getWorkspaceOverrideConfig(baseConfig: ProviderConfig | undefined): ProviderConfig | undefined {
    const workspaceDocument = this.readWorkspaceConfig();
    const providerRecord = this.asRecord(workspaceDocument?.provider);
    if (!providerRecord) {
      return undefined;
    }

    const fallback = baseConfig ?? this.createDefaultConfig();
    const name = this.readString(providerRecord, 'name') ?? fallback.name;
    const declaredProtocol = this.readString(providerRecord, 'protocol');
    const protocol = normalizeProviderProtocol(
      declaredProtocol ?? (baseConfig ? fallback.protocol : undefined),
    );
    const baseUrl = this.readString(providerRecord, 'baseUrl') ?? fallback.baseUrl;
    const model = this.readString(providerRecord, 'model') ?? fallback.model;
    const capabilities = {
      ...defaultCapabilitiesForProtocol(protocol),
      ...(baseConfig?.capabilities ?? {}),
      ...this.readCapabilities(providerRecord.capabilities),
    };
    const requestDefaults = normalizeProviderRequestDefaults(
      {
        name,
        baseUrl,
        model,
        protocol,
        knownModels: this.readStringArray(providerRecord.availableModels) ?? fallback.availableModels,
      },
      this.readRequestDefaults(providerRecord.requestDefaults) ??
      this.readRequestDefaults(providerRecord.request_defaults) ??
      fallback.requestDefaults ??
      {},
    );
    const modelCapabilities =
      this.readModelCapabilities(providerRecord.modelCapabilities, protocol) ?? fallback.modelCapabilities ?? {};
    const catalogModels = this.mergeCatalogModels(
      this.readStringArray(providerRecord.catalogModels),
      fallback.catalogModels ?? [],
      model.trim(),
    );

    if (!name.trim() || !baseUrl.trim() || !model.trim() || !fallback.apiKeyRef.trim()) {
      return undefined;
    }

    const workspaceMode = this.readString(providerRecord, 'mode');
    const workspaceCredentialMode = this.readString(providerRecord, 'credentialMode');
    const workspaceOverride: ProviderConfig = {
      ...fallback,
      name: name.trim(),
      label: this.readString(providerRecord, 'label') ?? fallback.label ?? name.trim(),
      baseUrl: this.normalizeBaseUrl(baseUrl),
      apiKeyRef: fallback.apiKeyRef,
      model: model.trim(),
      protocol,
      mode:
        workspaceMode === 'direct' || workspaceMode === 'gateway'
          ? workspaceMode
          : fallback.mode,
      credentialMode:
        workspaceCredentialMode === 'workspace_secret' || workspaceCredentialMode === 'ui_proxy'
          ? workspaceCredentialMode
          : fallback.credentialMode,
      capabilities,
      requestDefaults,
      modelCapabilities,
      catalogModels,
      modelTokenLimits:
        normalizeProviderModelTokenLimits(providerRecord.modelTokenLimits) ??
        fallback?.modelTokenLimits,
    };

    return this.materializeProviderConfig(workspaceOverride, baseConfig);
  }

  async syncWorkspaceProviderOverride(config: ProviderConfig | undefined): Promise<void> {
    const workspaceConfigPath = this.workspaceConfigPath();
    if (!workspaceConfigPath || !fs.existsSync(workspaceConfigPath)) {
      return;
    }

    const current = this.readWorkspaceConfig() ?? {};
    if (config) {
      current.provider = this.workspaceProviderOverride(config);
    } else {
      delete current.provider;
    }

    await fs.promises.mkdir(path.dirname(workspaceConfigPath), { recursive: true });
    await fs.promises.writeFile(workspaceConfigPath, `${JSON.stringify(current, null, 2)}\n`, 'utf8');
  }

  private workspaceProviderOverride(config: ProviderConfig): Record<string, unknown> {
    const normalized = this.materializeProviderConfig(config);
    const workspaceProvider: Record<string, unknown> = {
      name: normalized.name,
      label: normalized.label,
      protocol: normalizeProviderProtocol(normalized.protocol),
      model: normalized.model,
      mode: normalized.mode,
      connectionType: normalizeProviderConnectionType(normalized.connectionType),
      credentialMode: normalized.credentialMode,
      capabilities: { ...normalized.capabilities },
      requestDefaults: normalizeProviderRequestDefaults(
        {
          name: normalized.name,
          baseUrl: normalized.baseUrl,
          model: normalized.model,
          protocol: normalized.protocol,
        },
        this.readRequestDefaults(normalized.requestDefaults) ?? {},
      ),
      thinkingConfig: normalized.thinkingConfig,
      modelCapabilities: normalized.modelCapabilities,
      modelTokenLimits: normalized.modelTokenLimits,
      availableModels: normalized.availableModels,
      catalogModels: normalized.catalogModels,
      allowedModels: normalized.allowedModels,
      deniedModels: normalized.deniedModels,
      modelAliases: normalized.modelAliases,
      taskBindings: normalized.taskBindings,
      contextWindowTokens: normalized.contextWindowTokens,
      maxOutputTokens: normalized.maxOutputTokens,
      embeddingModel: normalized.embeddingModel,
      catalogSource: normalized.catalogSource,
      cacheTtlSeconds: normalized.cacheTtlSeconds,
    };
    const profileId = this.readProfileId(normalized);
    if (profileId && this.profileRegistry.getProfile(profileId)) {
      workspaceProvider.profileId = profileId;
    }
    return workspaceProvider;
  }

  private readWorkspaceConfig(): Record<string, unknown> | undefined {
    const workspaceConfigPath = this.workspaceConfigPath();
    if (!workspaceConfigPath || !fs.existsSync(workspaceConfigPath)) {
      return undefined;
    }

    try {
      const raw = fs.readFileSync(workspaceConfigPath, 'utf8');
      const parsed = JSON.parse(raw) as unknown;
      return this.asRecord(parsed);
    } catch {
      return undefined;
    }
  }

  private workspaceConfigPath(): string | undefined {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    return workspaceFolder ? path.join(workspaceFolder.uri.fsPath, '.vscode', 'trainer.json') : undefined;
  }

  private getWorkspaceProfileConfig(): ProviderConfig | undefined {
    const workspaceDocument = this.readWorkspaceConfig();
    const providerRecord = this.asRecord(workspaceDocument?.provider);
    const workspaceProfileId =
      this.readString(providerRecord ?? {}, 'profileId') ??
      this.readString(providerRecord ?? {}, 'profile_id');
    return workspaceProfileId ? this.getProfileConfigById(workspaceProfileId) : undefined;
  }

  private getActiveRegistryProfileConfig(): ProviderConfig | undefined {
    const activeProfileId = this.profileRegistry.getActiveProfileId();
    return activeProfileId ? this.getProfileConfigById(activeProfileId) : undefined;
  }

  private getProfileConfigById(profileId: string): ProviderConfig | undefined {
    const profile = this.profileRegistry.getProfile(profileId);
    return profile ? this.profileToProviderConfig(profile) : undefined;
  }

  private profileToProviderConfig(
    profile: ProviderProfileConfig,
    registrySnapshot = this.profileRegistry.getRegistry(),
  ): ProviderConfig {
    const registry = registrySnapshot ?? {
      version: '2.0.0',
      activeProfileId: this.profileRegistry.getActiveProfileId() ?? '',
      profiles: this.profileRegistry.getAllProfiles(),
      switchHistory: this.profileRegistry.getSwitchHistory(),
      lastModified: new Date().toISOString(),
    };

    return {
      name: profile.label,
      label: profile.label,
      protocol: profile.protocol,
      mode: profile.mode,
      connectionType: profile.connectionType,
      credentialMode: profile.credentialMode,
      baseUrl: this.normalizeBaseUrl(profile.baseUrl),
      apiKeyRef: profile.apiKeyRef,
      model: profile.model,
      contextWindowTokens: profile.contextWindowTokens,
      maxOutputTokens: profile.maxOutputTokens,
      modelTokenLimits: normalizeProviderModelTokenLimits(profile.modelTokenLimits),
      embeddingModel: profile.embeddingModel,
      catalogSource: profile.catalogSource,
      cacheTtlSeconds: profile.cacheTtlSeconds,
      availableModels: [...profile.availableModels],
      catalogModels: this.mergeCatalogModels(profile.catalogModels ?? [], profile.model),
      allowedModels: [...profile.allowedModels],
      deniedModels: [...profile.deniedModels],
      modelAliases: { ...profile.modelAliases },
      modelCapabilities: { ...profile.modelCapabilities },
      taskBindings: { ...profile.taskBindings },
      requestDefaults: normalizeProviderRequestDefaults(
        {
          name: profile.label,
          baseUrl: profile.baseUrl,
          model: profile.model,
          protocol: profile.protocol,
          knownModels: profile.availableModels,
        },
        profile.requestDefaults,
      ),
      thinkingConfig: normalizeProviderThinkingConfig(profile.thinkingConfig ?? profile.requestDefaults, profile.protocol),
      capabilities: { ...profile.capabilities },
      profileId: profile.id,
      profileLabel: profile.label,
      profileMode: profile.mode,
      profileCount: registry.profiles.length,
      profileHistory: registry.switchHistory.map((entry) => ({ ...entry })),
      providerProfiles: registry.profiles.map((entry) => ({ ...entry })),
    };
  }

  private profileFromProviderConfig(config: ProviderConfig): Omit<ProviderProfileConfig, 'id'> {
    const protocol = normalizeProviderProtocol(config.protocol);
    if (!protocol) {
      throw new Error('Select a chat protocol before saving this connection.');
    }
    const label = config.profileLabel?.trim() || config.label?.trim() || config.name.trim();
    const normalized = this.materializeProviderConfig(
      {
        ...config,
        label,
        profileId: undefined,
        profileLabel: undefined,
        profileMode: undefined,
        profileCount: undefined,
        profileHistory: undefined,
        providerProfiles: undefined,
        providerDashboard: undefined,
      },
      undefined,
    );

    return {
      label,
      protocol,
      mode: normalized.mode === 'gateway' ? 'gateway' : 'direct',
      connectionType: normalizeProviderConnectionType(normalized.connectionType),
      credentialMode: normalized.credentialMode === 'workspace_secret' ? 'workspace_secret' : 'ui_proxy',
      baseUrl: normalized.baseUrl,
      apiKeyRef: normalized.apiKeyRef,
      model: normalized.model,
      contextWindowTokens: normalized.contextWindowTokens,
      maxOutputTokens: normalized.maxOutputTokens,
      embeddingModel: normalized.embeddingModel,
      catalogSource: normalized.catalogSource ?? 'manual',
      cacheTtlSeconds: normalized.cacheTtlSeconds ?? 43200,
      modelAliases: { ...(normalized.modelAliases ?? {}) },
      availableModels: [...(normalized.availableModels ?? [])],
      catalogModels: this.mergeCatalogModels(normalized.catalogModels ?? [], normalized.model),
      allowedModels: [...(normalized.allowedModels ?? [])],
      deniedModels: [...(normalized.deniedModels ?? [])],
      modelTokenLimits: normalizeProviderModelTokenLimits(normalized.modelTokenLimits),
      taskBindings: this.normalizeTaskBindings(normalized.taskBindings) ?? {},
      thinkingConfig: normalizeProviderThinkingConfig(normalized.thinkingConfig ?? normalized.requestDefaults, protocol),
      requestDefaults: normalizeProviderRequestDefaults(
        {
          name: normalized.name,
          baseUrl: normalized.baseUrl,
          model: normalized.model,
          protocol,
          knownModels: normalized.availableModels,
        },
        this.readRequestDefaults(normalized.requestDefaults) ?? {},
      ),
      capabilities: { ...normalized.capabilities },
      modelCapabilities: { ...(normalized.modelCapabilities ?? {}) },
    };
  }

  private resolveKnownProfileId(
    config: ProviderConfig,
    fallback: ProviderConfig | undefined,
  ): string | undefined {
    const candidates = [
      this.readProfileId(config),
      this.getWorkspaceProfileConfig()?.profileId,
      this.readProfileId(fallback),
      this.profileRegistry.getActiveProfileId(),
    ];

    for (const candidate of candidates) {
      if (candidate && this.profileRegistry.getProfile(candidate)) {
        return candidate;
      }
    }

    return undefined;
  }

  private readProfileId(config: ProviderConfig | undefined): string | undefined {
    if (!config) {
      return undefined;
    }
    return config.profileId?.trim() || undefined;
  }

  private materializeProviderConfig(
    config: ProviderConfig,
    fallback?: ProviderConfig,
  ): ProviderConfig {
    const protocol = normalizeProviderProtocol(config.protocol ?? fallback?.protocol);
    const model = config.model.trim();
    const normalizedModelTokenLimits =
      normalizeProviderModelTokenLimits(config.modelTokenLimits) ??
      normalizeProviderModelTokenLimits(fallback?.modelTokenLimits);
    const configuredModelTokenLimit = readProviderModelTokenLimit(normalizedModelTokenLimits, model);
    const fallbackMatchesModel = fallback?.model?.trim() === model;
    const effectiveContextWindowTokens =
      config.contextWindowTokens ??
      configuredModelTokenLimit?.contextWindowTokens ??
      (fallbackMatchesModel ? fallback?.contextWindowTokens : undefined);
    const effectiveMaxOutputTokens =
      config.maxOutputTokens ??
      configuredModelTokenLimit?.maxOutputTokens ??
      (fallbackMatchesModel ? fallback?.maxOutputTokens : undefined);
    const nextModelTokenLimits = withProviderModelTokenLimit(normalizedModelTokenLimits, model, {
      contextWindowTokens: effectiveContextWindowTokens,
      maxOutputTokens: effectiveMaxOutputTokens,
    });
    return {
      ...fallback,
      ...config,
      name: config.name.trim(),
      label: config.label?.trim() || fallback?.label || config.name.trim(),
      baseUrl: this.normalizeBaseUrl(config.baseUrl),
      apiKeyRef: config.apiKeyRef.trim(),
      model,
      protocol,
      connectionType: normalizeProviderConnectionType(config.connectionType ?? fallback?.connectionType),
      contextWindowTokens: effectiveContextWindowTokens,
      maxOutputTokens: effectiveMaxOutputTokens,
      capabilities: {
        ...defaultCapabilitiesForProtocol(protocol),
        ...(fallback?.capabilities ?? {}),
        ...config.capabilities,
      },
      profileId: fallback?.profileId ?? config.profileId,
      profileLabel: config.profileLabel?.trim() || fallback?.profileLabel || config.label?.trim() || config.name.trim(),
      profileMode: fallback?.profileMode ?? config.profileMode,
      profileCount: fallback?.profileCount ?? config.profileCount,
      profileHistory: fallback?.profileHistory ?? config.profileHistory,
      providerProfiles: fallback?.providerProfiles ?? config.providerProfiles,
      modelTokenLimits: nextModelTokenLimits,
      requestDefaults: normalizeProviderRequestDefaults(
        {
          name: config.name.trim(),
          baseUrl: this.normalizeBaseUrl(config.baseUrl),
          model,
          protocol,
        },
        mergeProviderRequestDefaults(
          this.readRequestDefaults(fallback?.requestDefaults) ?? {},
          this.readRequestDefaults(config.requestDefaults) ?? {},
        ),
      ),
      thinkingConfig: normalizeProviderThinkingConfig(
        config.thinkingConfig ?? fallback?.thinkingConfig ?? config.requestDefaults ?? fallback?.requestDefaults,
        protocol,
      ),
      modelCapabilities: config.modelCapabilities ?? fallback?.modelCapabilities ?? {},
    };
  }

  private async updateProfileConfig(profileId: string, config: ProviderConfig): Promise<void> {
    const currentProfile = this.profileRegistry.getProfile(profileId);
    if (!currentProfile) {
      return;
    }

    const nextConfig = this.materializeProviderConfig(config, this.profileToProviderConfig(currentProfile));
    await this.profileRegistry.updateProfile(profileId, {
      label: nextConfig.profileLabel?.trim() || nextConfig.label?.trim() || nextConfig.name,
      protocol: normalizeProviderProtocol(nextConfig.protocol ?? currentProfile.protocol) ?? currentProfile.protocol,
      mode: nextConfig.mode ?? currentProfile.mode,
      connectionType:
        normalizeProviderConnectionType(nextConfig.connectionType) ?? currentProfile.connectionType,
      credentialMode: nextConfig.credentialMode ?? currentProfile.credentialMode,
      baseUrl: nextConfig.baseUrl,
      apiKeyRef: nextConfig.apiKeyRef,
      model: nextConfig.model,
      contextWindowTokens: nextConfig.contextWindowTokens ?? currentProfile.contextWindowTokens,
      maxOutputTokens: nextConfig.maxOutputTokens ?? currentProfile.maxOutputTokens,
      modelTokenLimits:
        normalizeProviderModelTokenLimits(nextConfig.modelTokenLimits) ??
        currentProfile.modelTokenLimits,
      embeddingModel: nextConfig.embeddingModel ?? currentProfile.embeddingModel,
      catalogSource: nextConfig.catalogSource ?? currentProfile.catalogSource,
      cacheTtlSeconds: nextConfig.cacheTtlSeconds ?? currentProfile.cacheTtlSeconds,
      modelAliases: nextConfig.modelAliases ?? currentProfile.modelAliases,
      availableModels: nextConfig.availableModels ?? currentProfile.availableModels,
      catalogModels: this.mergeCatalogModels(
        nextConfig.catalogModels ?? currentProfile.catalogModels ?? [],
        nextConfig.model,
      ),
      allowedModels: nextConfig.allowedModels ?? currentProfile.allowedModels,
      deniedModels: nextConfig.deniedModels ?? currentProfile.deniedModels,
      taskBindings: this.normalizeTaskBindings(nextConfig.taskBindings) ?? currentProfile.taskBindings,
      requestDefaults: normalizeProviderRequestDefaults(
        {
          name: nextConfig.profileLabel?.trim() || nextConfig.label?.trim() || nextConfig.name,
          baseUrl: nextConfig.baseUrl,
          model: nextConfig.model,
          protocol: nextConfig.protocol,
        },
        mergeProviderRequestDefaults(
          currentProfile.requestDefaults ?? {},
          nextConfig.requestDefaults ?? {},
        ),
      ),
      thinkingConfig: normalizeProviderThinkingConfig(
        nextConfig.thinkingConfig ?? nextConfig.requestDefaults ?? currentProfile.thinkingConfig ?? currentProfile.requestDefaults,
        nextConfig.protocol,
      ),
      capabilities: nextConfig.capabilities,
      modelCapabilities: nextConfig.modelCapabilities ?? currentProfile.modelCapabilities,
    });
  }

  private normalizeImportedRegistry(registry: unknown): ProviderProfileRegistryData | undefined {
    const record = this.asRecord(registry);
    if (!record) {
      return undefined;
    }

    const apiKeyRefs = new Set<string>();
    const profiles = Array.isArray(record.profiles)
      ? record.profiles
          .map((profile) => this.normalizeImportedProfile(profile))
          .filter((profile): profile is ProviderProfileConfig => Boolean(profile))
          .map((profile) => {
            const normalizedRef = profile.apiKeyRef.trim().toLowerCase();
            if (normalizedRef && !apiKeyRefs.has(normalizedRef)) {
              apiKeyRefs.add(normalizedRef);
              return profile;
            }

            const apiKeyRef = createProviderApiKeyRef();
            apiKeyRefs.add(apiKeyRef.toLowerCase());
            return { ...profile, apiKeyRef };
          })
      : [];

    return {
      version: this.readString(record, 'version') ?? '2.0.0',
      activeProfileId: this.readString(record, 'activeProfileId') ?? '',
      profiles,
      switchHistory: Array.isArray(record.switchHistory)
        ? record.switchHistory
            .map((entry) => this.normalizeImportedHistoryEntry(entry))
            .filter((entry): entry is ProviderProfileRegistryData['switchHistory'][number] => Boolean(entry))
        : [],
      lastModified: this.readString(record, 'lastModified') ?? new Date().toISOString(),
    };
  }

  private normalizeImportedProfile(profile: unknown): ProviderProfileConfig | undefined {
    const record = this.asRecord(profile);
    if (!record) {
      return undefined;
    }

    const label = this.readString(record, 'label') ?? this.readString(record, 'name');
    const baseUrl = this.readString(record, 'baseUrl');
    const model = this.readString(record, 'model');
    const apiKeyRef = this.readString(record, 'apiKeyRef');
    const rawProtocol = this.readString(record, 'protocol');

    if (!label || !baseUrl || !model || !apiKeyRef || !rawProtocol) {
      return undefined;
    }

    const protocol = normalizeProviderProtocol(rawProtocol);
    if (!protocol) {
      return undefined;
    }
    return {
      id: this.readString(record, 'id') ?? this.createApiKeyRef(label),
      label,
      protocol,
      mode: this.readString(record, 'mode') === 'gateway' ? 'gateway' : 'direct',
      connectionType: normalizeProviderConnectionType(
        this.readString(record, 'connectionType') ?? this.readString(record, 'connection_type'),
      ),
      credentialMode:
        this.readString(record, 'credentialMode') === 'workspace_secret' ? 'workspace_secret' : 'ui_proxy',
      baseUrl: this.normalizeBaseUrl(baseUrl),
      apiKeyRef: apiKeyRef.trim(),
      model: model.trim(),
      contextWindowTokens: this.readNumber(record, 'contextWindowTokens'),
      maxOutputTokens: this.readNumber(record, 'maxOutputTokens'),
      modelTokenLimits: normalizeProviderModelTokenLimits(record.modelTokenLimits),
      embeddingModel: this.readString(record, 'embeddingModel'),
      catalogSource: this.readCatalogSource(record.catalogSource),
      cacheTtlSeconds: this.readNumber(record, 'cacheTtlSeconds') ?? 43200,
      modelAliases: this.readStringRecord(record.modelAliases) ?? {},
      availableModels: this.readStringArray(record.availableModels),
      catalogModels: this.mergeCatalogModels(this.readStringArray(record.catalogModels), model.trim()),
      allowedModels: this.readStringArray(record.allowedModels),
      deniedModels: this.readStringArray(record.deniedModels),
      taskBindings: this.normalizeTaskBindings(record.taskBindings ?? record.task_bindings) ?? {},
      thinkingConfig: normalizeProviderThinkingConfig(
        record.thinkingConfig ?? record.thinking_config ?? record.requestDefaults ?? record.request_defaults,
        protocol,
      ),
      requestDefaults: normalizeProviderRequestDefaults(
        {
          name: label ?? '',
          baseUrl: baseUrl ?? '',
          model: model ?? '',
          protocol,
        },
        this.readRequestDefaults(record.requestDefaults) ?? {},
      ),
      capabilities: {
        ...defaultCapabilitiesForProtocol(protocol),
        ...this.readCapabilities(record.capabilities),
      },
      modelCapabilities: this.readModelCapabilities(record.modelCapabilities, protocol) ?? {},
    };
  }

  private normalizeImportedHistoryEntry(
    entry: unknown,
  ): ProviderProfileRegistryData['switchHistory'][number] | undefined {
    const record = this.asRecord(entry);
    if (!record) {
      return undefined;
    }

    return {
      entryId: this.readString(record, 'entryId') ?? `entry-${Date.now().toString(36)}`,
      fromProfileId: this.readString(record, 'fromProfileId') ?? '',
      toProfileId: this.readString(record, 'toProfileId') ?? '',
      reason: this.readString(record, 'reason') ?? 'import',
      timestamp: this.readString(record, 'timestamp') ?? new Date().toISOString(),
    };
  }

  private normalizeTaskBindings(value: unknown): Record<string, ProviderTaskBinding> | undefined {
    const record = this.asRecord(value);
    if (!record) {
      return undefined;
    }

    const next: Record<string, ProviderTaskBinding> = {};
    for (const [key, rawBinding] of Object.entries(record)) {
      const bindingRecord = this.asRecord(rawBinding);
      if (!bindingRecord) {
        continue;
      }
      const alias = this.readString(bindingRecord, 'alias');
      if (!alias) {
        continue;
      }
      next[key] = {
        alias,
        fallbackAliases: this.readStringArray(bindingRecord.fallbackAliases),
        requiredCapabilities: this.readStringArray(bindingRecord.requiredCapabilities),
      };
    }

    return next;
  }

  private readCapabilities(value: unknown): Partial<CapabilityFlags> {
    const record = this.asRecord(value);
    if (!record) {
      return {};
    }

    const partial: Partial<CapabilityFlags> = {};
    for (const key of [
      'chat',
      'responses',
      'vision',
      'embeddings',
      'tools',
      'jsonSchema',
      'structuredOutput',
      'streaming',
    ] as const) {
      if (typeof record[key] === 'boolean') {
        partial[key] = record[key];
      }
    }
    if (typeof record.json_schema === 'boolean') {
      partial.jsonSchema = record.json_schema;
    }
    if (typeof record.structured_output === 'boolean') {
      partial.structuredOutput = record.structured_output;
    }
    return partial;
  }

  private readRequestDefaults(value: unknown): Record<string, unknown> | undefined {
    const record = this.asRecord(value);
    if (!record) {
      return undefined;
    }

    return { ...record };
  }

  private readModelCapabilities(
    value: unknown,
    protocol: string | undefined,
  ): Record<string, CapabilityFlags> | undefined {
    const record = this.asRecord(value);
    if (!record) {
      return undefined;
    }

    const next: Record<string, CapabilityFlags> = {};
    for (const [model, rawCapabilities] of Object.entries(record)) {
      const capabilities = this.readCapabilities(rawCapabilities);
      next[model] = {
        ...defaultCapabilitiesForProtocol(normalizeProviderProtocol(protocol)),
        ...capabilities,
      };
    }
    return next;
  }

  private readString(record: Record<string, unknown>, key: string): string | undefined {
    const value = record[key];
    return typeof value === 'string' ? value : undefined;
  }

  private readNumber(record: Record<string, unknown>, key: string): number | undefined {
    const value = record[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
  }

  private readStringArray(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : [];
  }

  private mergeCatalogModels(...groups: Array<string[] | string | undefined>): string[] {
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

  private readStringRecord(value: unknown): Record<string, string> | undefined {
    const record = this.asRecord(value);
    if (!record) {
      return undefined;
    }

    const next: Record<string, string> = {};
    for (const [key, entry] of Object.entries(record)) {
      if (typeof entry === 'string') {
        next[key] = entry;
      }
    }
    return next;
  }

  private readCatalogSource(value: unknown): ProviderProfileConfig['catalogSource'] {
    if (value === 'provider_live' || value === 'cached' || value === 'manual') {
      return value;
    }
    return 'manual';
  }

  private asRecord(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : undefined;
  }

  private createApiKeyRef(name: string): string {
    void name;
    return createProviderApiKeyRef();
  }

  private normalizeBaseUrl(baseUrl: string): string {
    return baseUrl.trim().replace(/\/+$/, '');
  }
}
