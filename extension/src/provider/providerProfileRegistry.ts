import * as crypto from 'node:crypto';
import * as vscode from 'vscode';

import { SECRET_KEYS, STORAGE_KEYS } from '../core/constants';
import { defaultProviderCredentialMode } from '../core/providerDefaults';
import {
  defaultCapabilitiesForProtocol,
  defaultTaskBindingRequiredCapabilities,
} from '../../../shared/src/providerProtocols';
import type {
  CapabilityFlags,
  ProviderCredentialMode,
  ProviderProtocol,
  ProviderTaskBinding,
  ProviderRequestDefaults,
  ProviderConfig,
} from '../core/types';

/**
 * Provider v2 Profile Registry
 * 
 * Implements cc-switch style profile management:
 * - Multiple profiles with different protocols/models
 * - Active profile tracking with .current marker
 * - Profile switch history
 * - Model aliases and task bindings
 * - Capability matrix per model
 * - Atomic writes with backup
 */

export interface ProviderProfileConfig {
  id: string;
  label: string;
  protocol: ProviderProtocol;
  mode: 'direct' | 'gateway';
  credentialMode: ProviderCredentialMode;
  baseUrl: string;
  apiKeyRef: string;
  model: string;
  connectionType?: string;
  contextWindowTokens?: number;
  maxOutputTokens?: number;
  embeddingModel?: string;
  catalogSource: 'provider_live' | 'cached' | 'manual';
  cacheTtlSeconds: number;
  modelAliases: Record<string, string>;
  availableModels: string[];
  catalogModels?: string[];
  allowedModels: string[];
  deniedModels: string[];
  taskBindings: Record<string, ProviderTaskBinding>;
  requestDefaults: ProviderRequestDefaults;
  thinkingConfig?: import('../../../shared/src/providerThinking').ProviderThinkingConfig;
  capabilities: CapabilityFlags;
  modelCapabilities: Record<string, CapabilityFlags>;
  modelTokenLimits?: Record<string, { contextWindowTokens?: number; maxOutputTokens?: number }>;
}

export interface ProviderProfileSwitchHistoryEntry {
  entryId: string;
  fromProfileId: string;
  toProfileId: string;
  reason: string;
  timestamp: string;
}

export interface ProviderProfileRegistryData {
  version: string;
  activeProfileId: string;
  profiles: ProviderProfileConfig[];
  switchHistory: ProviderProfileSwitchHistoryEntry[];
  lastModified: string;
}

/**
 * Template profiles for quick start
 */
function templateCapabilities(
  protocol: ProviderProtocol,
  overrides: Partial<CapabilityFlags> = {},
): CapabilityFlags {
  return {
    ...defaultCapabilitiesForProtocol(protocol),
    ...overrides,
  };
}

function templateTaskBinding(
  alias: string,
  options: {
    protocol?: ProviderProtocol;
    taskBindingKey?: 'coach_reply' | 'coach_critique' | 'resource_rerank' | 'plan_summary' | 'resource_embedding';
    fallbackAliases?: string[];
    requiredCapabilities?: string[];
  } = {},
): ProviderTaskBinding {
  return {
    alias,
    fallbackAliases: options.fallbackAliases ?? [],
    requiredCapabilities:
      options.requiredCapabilities ??
      (options.protocol && options.taskBindingKey
        ? defaultTaskBindingRequiredCapabilities(options.protocol, options.taskBindingKey)
        : []),
  };
}

function templateCoachReplyBinding(
  protocol: ProviderProtocol,
  alias: string,
  fallbackAlias = 'coach-deep',
): ProviderTaskBinding {
  return templateTaskBinding(alias, {
    protocol,
    taskBindingKey: 'coach_reply',
    fallbackAliases: [fallbackAlias],
  });
}

function templateRerankBinding(alias: string, fallbackAlias = 'coach-deep'): ProviderTaskBinding {
  return templateTaskBinding(alias, {
    taskBindingKey: 'resource_rerank',
    fallbackAliases: [fallbackAlias],
  });
}

export const PROVIDER_PROFILE_TEMPLATES: Omit<ProviderProfileConfig, 'id'>[] = [
  {
    label: 'OpenAI',
    protocol: 'openai_responses',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyRef: 'openai.default',
    model: 'gpt-5-mini',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'gpt-5-mini',
      'coach-deep': 'gpt-5.1',
      'critic': 'gpt-5.1',
      'summary': 'gpt-5-mini',
      'embed': 'text-embedding-3-small',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_responses', 'coach-fast'),
      coach_critique: templateTaskBinding('critic'),
      resource_rerank: templateRerankBinding('coach-fast'),
      plan_summary: templateTaskBinding('summary'),
      resource_embedding: templateTaskBinding('embed'),
    },
    requestDefaults: {
      store: false,
      reasoningEffort: 'medium',
      serviceTier: 'auto',
      promptCache: 'auto',
    },
    capabilities: templateCapabilities('openai_responses', { embeddings: true }),
    modelCapabilities: {},
  },
  {
    label: 'OpenAI Chat Completions',
    protocol: 'openai_chat_completions',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyRef: 'openai.chat.default',
    model: 'gpt-5-mini',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'gpt-5-mini',
      'coach-deep': 'gpt-5.1',
      'critic': 'gpt-5.1',
      'summary': 'gpt-5-mini',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_chat_completions', 'coach-fast'),
      coach_critique: templateTaskBinding('critic'),
      resource_rerank: templateRerankBinding('coach-fast'),
      plan_summary: templateTaskBinding('summary'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('openai_chat_completions'),
    modelCapabilities: {},
  },
  {
    label: 'Anthropic',
    protocol: 'anthropic_messages',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.anthropic.com',
    apiKeyRef: 'anthropic.default',
    model: 'claude-sonnet-4-20250514',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'claude-haiku-4-5',
      'coach-deep': 'claude-sonnet-4-20250514',
      'critic': 'claude-sonnet-4-20250514',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('anthropic_messages', 'coach-fast'),
      coach_critique: templateTaskBinding('critic'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {
      maxTokens: 4096,
      thinkingBudget: 'auto',
      promptCache: 'auto',
    },
    capabilities: templateCapabilities('anthropic_messages'),
    modelCapabilities: {},
  },
  {
    label: 'Gemini',
    protocol: 'gemini_generate_content',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://generativelanguage.googleapis.com',
    apiKeyRef: 'gemini.default',
    model: 'gemini-2.0-flash',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'gemini-2.0-flash',
      'coach-deep': 'gemini-2.0-flash-lite',
      'critic': 'gemini-2.0-flash',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('gemini_generate_content', 'coach-fast'),
      coach_critique: templateTaskBinding('critic'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('gemini_generate_content'),
    modelCapabilities: {},
  },
  {
    label: 'OpenRouter',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://openrouter.ai/api/v1',
    apiKeyRef: 'openrouter.default',
    model: 'openai/gpt-5-mini',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'openai/gpt-5-mini',
      'coach-deep': 'anthropic/claude-sonnet-4-6',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_chat_completions_compatible', 'coach-fast'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('openai_chat_completions_compatible', {
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
    }),
    modelCapabilities: {},
  },
  {
    label: 'Ollama (Local)',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'http://localhost:11434/v1',
    apiKeyRef: 'ollama.default',
    model: 'llama3.2',
    catalogSource: 'manual',
    cacheTtlSeconds: 3600,
    modelAliases: {
      'coach-fast': 'llama3.2',
      'coach-deep': 'llama3.2',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_chat_completions_compatible', 'coach-fast'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('openai_chat_completions_compatible', {
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
    }),
    modelCapabilities: {},
  },
  {
    label: 'DeepSeek',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.deepseek.com/v1',
    apiKeyRef: 'deepseek.default',
    model: 'deepseek-chat',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'deepseek-chat',
      'coach-deep': 'deepseek-chat',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_chat_completions_compatible', 'coach-fast'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('openai_chat_completions_compatible', {
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
    }),
    modelCapabilities: {},
  },
  {
    label: 'Kimi',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.moonshot.cn/v1',
    apiKeyRef: 'kimi.default',
    model: 'kimi-k3',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'kimi-k3',
      'coach-deep': 'kimi-k3',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_chat_completions_compatible', 'coach-fast'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('openai_chat_completions_compatible', {
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
    }),
    modelCapabilities: {},
  },
  {
    label: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.minimaxi.com/v1',
    apiKeyRef: 'minimax.default',
    model: 'MiniMax-M3',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'MiniMax-M2.7-highspeed',
      'coach-deep': 'MiniMax-M3',
      'critic': 'MiniMax-M3',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_chat_completions_compatible', 'coach-fast', 'coach-deep'),
      coach_critique: templateTaskBinding('critic'),
      resource_rerank: templateRerankBinding('coach-fast', 'coach-deep'),
    },
    requestDefaults: {
      extra_body: {
        thinking: {
          type: 'disabled',
        },
      },
    },
    thinkingConfig: {
      mode: 'disabled',
    },
    capabilities: templateCapabilities('openai_chat_completions_compatible', {
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      structuredOutput: false,
      thinking: false,
    }),
    modelCapabilities: {},
  },
  {
    label: 'New API',
    protocol: 'openai_chat_completions_compatible',
    mode: 'gateway',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'newapi.default',
    model: '',
    connectionType: 'newapi_channel_conn',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {},
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_chat_completions_compatible', 'coach-fast'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('openai_chat_completions_compatible'),
    modelCapabilities: {},
  },
];

export class ProviderProfileRegistry implements vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<ProviderProfileRegistryData | undefined>();
  private readonly _onActiveProfileChanged = new vscode.EventEmitter<ProviderProfileConfig | undefined>();
  
  readonly onDidChange = this.emitter.event;
  readonly onActiveProfileChanged = this._onActiveProfileChanged.event;

  constructor(private readonly extensionContext: vscode.ExtensionContext) {
    this.extensionContext.globalState.setKeysForSync([
      STORAGE_KEYS.providerProfileRegistry,
      STORAGE_KEYS.providerActiveProfileId,
      STORAGE_KEYS.providerProfileSwitchHistory,
    ]);
  }

  /**
   * Get the current profile registry
   */
  getRegistry(): ProviderProfileRegistryData | undefined {
    return this.extensionContext.globalState.get<ProviderProfileRegistryData>(STORAGE_KEYS.providerProfileRegistry);
  }

  /**
   * Replace the current registry with a new snapshot.
   */
  async setRegistry(registry: ProviderProfileRegistryData): Promise<void> {
    const nextRegistry = {
      ...registry,
      activeProfileId: this.normalizeProfileId(registry.activeProfileId) ?? '',
      profiles: Array.isArray(registry.profiles) ? registry.profiles : [],
      switchHistory: Array.isArray(registry.switchHistory) ? registry.switchHistory : [],
      lastModified: registry.lastModified || new Date().toISOString(),
    };
    const previousActive = this.getActiveProfileId();
    await this.saveRegistry(nextRegistry);
    this.emitter.fire(nextRegistry);
    const nextActive = this.getActiveProfileId();
    if (previousActive !== nextActive) {
      this._onActiveProfileChanged.fire(this.getActiveProfile());
    }
  }

  /**
   * Export the current registry snapshot.
   */
  exportRegistry(): ProviderProfileRegistryData | undefined {
    return this.getRegistry();
  }

  /**
   * Get the currently active profile ID
   */
  getActiveProfileId(): string | undefined {
    const registry = this.getRegistry();
    const registryActiveProfileId = this.normalizeProfileId(registry?.activeProfileId);
    if (registryActiveProfileId) {
      return registryActiveProfileId;
    }
    return this.normalizeProfileId(this.extensionContext.globalState.get<string>(STORAGE_KEYS.providerActiveProfileId));
  }

  /**
   * Get the currently active profile configuration
   */
  getActiveProfile(): ProviderProfileConfig | undefined {
    const registry = this.getRegistry();
    const activeId = this.getActiveProfileId();
    
    if (!registry || !activeId) {
      return undefined;
    }
    
    return registry.profiles.find(p => p.id === activeId);
  }

  /**
   * Get a specific profile by ID
   */
  getProfile(profileId: string): ProviderProfileConfig | undefined {
    const registry = this.getRegistry();
    if (!registry) {
      return undefined;
    }
    return registry.profiles.find(p => p.id === profileId);
  }

  /**
   * Get all profiles
   */
  getAllProfiles(): ProviderProfileConfig[] {
    const registry = this.getRegistry();
    return registry?.profiles ?? [];
  }

  /**
   * Get profile switch history
   */
  getSwitchHistory(): ProviderProfileSwitchHistoryEntry[] {
    const registry = this.getRegistry();
    return registry?.switchHistory ?? [];
  }

  /**
   * Create and add a new profile
   */
  async createProfile(profile: Omit<ProviderProfileConfig, 'id'>): Promise<ProviderProfileConfig> {
    const newProfile: ProviderProfileConfig = {
      ...profile,
      id: this.generateProfileId(profile.label),
    };

    const registry = this.getRegistry() ?? this.createEmptyRegistry();
    registry.profiles.push(newProfile);
    registry.lastModified = new Date().toISOString();

    await this.saveRegistry(registry);
    this.emitter.fire(registry);
    
    return newProfile;
  }

  /**
   * Update an existing profile
   */
  async updateProfile(profileId: string, updates: Partial<ProviderProfileConfig>): Promise<ProviderProfileConfig | undefined> {
    const registry = this.getRegistry();
    if (!registry) {
      return undefined;
    }

    const index = registry.profiles.findIndex(p => p.id === profileId);
    if (index === -1) {
      return undefined;
    }

    const oldProfile = registry.profiles[index];
    registry.profiles[index] = { ...oldProfile, ...updates };
    registry.lastModified = new Date().toISOString();

    await this.saveRegistry(registry);
    this.emitter.fire(registry);

    // If this is the active profile, notify listeners
    if (profileId === this.getActiveProfileId()) {
      this._onActiveProfileChanged.fire(registry.profiles[index]);
    }

    return registry.profiles[index];
  }

  /**
   * Delete a profile
   */
  async deleteProfile(profileId: string): Promise<boolean> {
    const registry = this.getRegistry();
    if (!registry) {
      return false;
    }

    const index = registry.profiles.findIndex(p => p.id === profileId);
    if (index === -1) {
      return false;
    }

    // Prevent deleting the active profile without switching first
    if (profileId === registry.activeProfileId) {
      throw new Error('Cannot delete the active profile. Switch to another profile first.');
    }

    registry.profiles.splice(index, 1);
    registry.lastModified = new Date().toISOString();

    await this.saveRegistry(registry);
    this.emitter.fire(registry);

    return true;
  }

  /**
   * Switch to a different profile
   */
  async switchToProfile(profileId: string, reason?: string): Promise<boolean> {
    const registry = this.getRegistry();
    if (!registry) {
      return false;
    }

    const targetProfile = registry.profiles.find(p => p.id === profileId);
    if (!targetProfile) {
      return false;
    }

    const fromProfileId = registry.activeProfileId;

    // Add to switch history
    const historyEntry: ProviderProfileSwitchHistoryEntry = {
      entryId: this.generateEntryId(),
      fromProfileId: fromProfileId ?? 'none',
      toProfileId: profileId,
      reason: reason ?? 'manual_switch',
      timestamp: new Date().toISOString(),
    };
    registry.switchHistory.unshift(historyEntry);

    // Keep only last 50 history entries
    if (registry.switchHistory.length > 50) {
      registry.switchHistory = registry.switchHistory.slice(0, 50);
    }

    // Update active profile
    registry.activeProfileId = profileId;
    registry.lastModified = new Date().toISOString();

    await this.saveRegistry(registry);
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerActiveProfileId, profileId);

    this.emitter.fire(registry);
    this._onActiveProfileChanged.fire(targetProfile);

    return true;
  }

  /**
   * Clear the active profile while keeping the registry intact.
   */
  async clearActiveProfile(reason?: string): Promise<boolean> {
    const registry = this.getRegistry();
    if (!registry) {
      return false;
    }

    const fromProfileId = registry.activeProfileId;
    if (!fromProfileId) {
      return true;
    }

    registry.switchHistory.unshift({
      entryId: this.generateEntryId(),
      fromProfileId,
      toProfileId: '',
      reason: reason ?? 'manual_clear',
      timestamp: new Date().toISOString(),
    });
    if (registry.switchHistory.length > 50) {
      registry.switchHistory = registry.switchHistory.slice(0, 50);
    }

    registry.activeProfileId = '';
    registry.lastModified = new Date().toISOString();

    await this.saveRegistry(registry);
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerActiveProfileId, undefined);

    this.emitter.fire(registry);
    this._onActiveProfileChanged.fire(undefined);
    return true;
  }

  /**
   * Create a profile from a template
   */
  async createFromTemplate(templateIndex: number, apiKey?: string): Promise<ProviderProfileConfig | undefined> {
    if (templateIndex < 0 || templateIndex >= PROVIDER_PROFILE_TEMPLATES.length) {
      return undefined;
    }

    const template = PROVIDER_PROFILE_TEMPLATES[templateIndex];
    const profile = await this.createProfile({
      ...template,
      credentialMode:
        defaultProviderCredentialMode({
          remoteName: vscode.env.remoteName ?? undefined,
          isRemoteWorkspace: Boolean(vscode.env.remoteName),
        }) === 'workspace_secret'
          ? 'workspace_secret'
          : template.credentialMode,
    });

    if (apiKey && apiKey.trim()) {
      await this.saveApiKey(profile.apiKeyRef, apiKey.trim());
    }

    return profile;
  }

  /**
   * Initialize with template profiles (first-time setup)
   */
  async initializeWithTemplate(templateIndex: number, apiKey: string): Promise<ProviderProfileConfig | undefined> {
    const profile = await this.createFromTemplate(templateIndex, apiKey);
    if (profile) {
      await this.switchToProfile(profile.id, 'initial_setup');
    }
    return profile;
  }

  /**
   * Migrate from legacy single-config to profile registry
   */
  async migrateFromLegacyConfig(legacyConfig: ProviderConfig, apiKey?: string): Promise<void> {
    const profile: Omit<ProviderProfileConfig, 'id'> = {
      label: legacyConfig.label ?? legacyConfig.name,
      protocol: legacyConfig.protocol ?? 'openai_chat_completions_compatible',
      mode: 'direct',
      credentialMode: legacyConfig.credentialMode ?? 'ui_proxy',
      baseUrl: legacyConfig.baseUrl,
      apiKeyRef: legacyConfig.apiKeyRef,
      model: legacyConfig.model,
      contextWindowTokens: legacyConfig.contextWindowTokens,
      maxOutputTokens: legacyConfig.maxOutputTokens,
      catalogSource: 'manual',
      cacheTtlSeconds: 43200,
      modelAliases: legacyConfig.modelAliases ?? {},
      availableModels: legacyConfig.availableModels ?? [],
      catalogModels: [legacyConfig.model],
      allowedModels: [],
      deniedModels: [],
      modelCapabilities: legacyConfig.modelCapabilities ?? {},
      modelTokenLimits: legacyConfig.modelTokenLimits,
      taskBindings: (legacyConfig.taskBindings as Record<string, ProviderTaskBinding>) ?? {},
      requestDefaults: legacyConfig.requestDefaults ?? {},
      capabilities: legacyConfig.capabilities,
    };

    const newProfile = await this.createProfile(profile);

    if (apiKey && apiKey.trim()) {
      await this.saveApiKey(profile.apiKeyRef, apiKey.trim());
    }

    await this.switchToProfile(newProfile.id, 'migrated_from_legacy');
  }

  /**
   * Materialize a registry from an existing single-config setup when needed.
   */
  async ensureRegistryFromLegacyConfig(
    legacyConfig: ProviderConfig | undefined,
    apiKey?: string,
  ): Promise<ProviderProfileConfig | undefined> {
    const registry = this.getRegistry();
    if (registry?.profiles.length) {
      if (!this.getActiveProfile() && registry.profiles[0]) {
        await this.switchToProfile(registry.profiles[0].id, 'recover_active_profile');
      }
      return this.getActiveProfile() ?? registry.profiles[0];
    }
    if (!legacyConfig) {
      return undefined;
    }

    await this.migrateFromLegacyConfig(legacyConfig, apiKey);
    return this.getActiveProfile();
  }

  /**
   * Check if the registry has any profiles
   */
  hasProfiles(): boolean {
    const registry = this.getRegistry();
    return registry !== undefined && registry.profiles.length > 0;
  }

  /**
   * Check if there is an active profile
   */
  hasActiveProfile(): boolean {
    return this.getActiveProfileId() !== undefined && this.getActiveProfile() !== undefined;
  }

  /**
   * Get API key for a profile
   */
  async getApiKey(profileId: string): Promise<string | undefined> {
    const profile = this.getProfile(profileId);
    if (!profile) {
      return undefined;
    }
    return this.extensionContext.secrets.get(this.secretKey(profile.apiKeyRef));
  }

  /**
   * Save API key for a profile
   */
  async saveApiKey(apiKeyRef: string, apiKey: string): Promise<void> {
    if (apiKey.trim()) {
      await this.extensionContext.secrets.store(this.secretKey(apiKeyRef), apiKey.trim());
    } else {
      await this.extensionContext.secrets.delete(this.secretKey(apiKeyRef));
    }
  }

  /**
   * Get API key for the active profile
   */
  async getActiveProfileApiKey(): Promise<string | undefined> {
    const activeProfile = this.getActiveProfile();
    if (!activeProfile) {
      return undefined;
    }
    return this.getApiKey(activeProfile.id);
  }

  /**
   * Clear all data (for testing/reset)
   */
  async clearAll(): Promise<void> {
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerProfileRegistry, undefined);
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerActiveProfileId, undefined);
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerProfileSwitchHistory, undefined);
    this.emitter.fire(undefined);
  }

  dispose(): void {
    this.emitter.dispose();
    this._onActiveProfileChanged.dispose();
  }

  private createEmptyRegistry(): ProviderProfileRegistryData {
    return {
      version: '2.0.0',
      activeProfileId: '',
      profiles: [],
      switchHistory: [],
      lastModified: new Date().toISOString(),
    };
  }

  private async saveRegistry(registry: ProviderProfileRegistryData): Promise<void> {
    // Atomic write: update registry and history
    await this.extensionContext.globalState.update(STORAGE_KEYS.providerProfileRegistry, registry);
    await this.extensionContext.globalState.update(
      STORAGE_KEYS.providerProfileSwitchHistory,
      registry.switchHistory
    );
    await this.extensionContext.globalState.update(
      STORAGE_KEYS.providerActiveProfileId,
      this.normalizeProfileId(registry.activeProfileId),
    );
  }

  private normalizeProfileId(profileId: string | undefined | null): string | undefined {
    const normalized = typeof profileId === 'string' ? profileId.trim() : '';
    return normalized ? normalized : undefined;
  }

  private generateProfileId(label: string): string {
    const timestamp = Date.now().toString(36);
    const hash = crypto.createHash('md5').update(`${label}-${timestamp}`).digest('hex').slice(0, 8);
    return `${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${hash}`;
  }

  private generateEntryId(): string {
    return `entry-${Date.now().toString(36)}-${crypto.randomBytes(4).toString('hex')}`;
  }

  private secretKey(apiKeyRef: string): string {
    return `${SECRET_KEYS.providerApiKeyPrefix}.${apiKeyRef}`;
  }
}
