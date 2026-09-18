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
    label: 'Zhipu GLM',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    apiKeyRef: 'zhipu.default',
    model: 'glm-4.6',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'glm-4.5-air',
      'coach-deep': 'glm-4.6',
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
    label: 'Qwen',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    apiKeyRef: 'qwen.default',
    model: 'qwen-plus',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'qwen-plus',
      'coach-deep': 'qwen-max',
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
    label: 'SiliconFlow',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.siliconflow.cn/v1',
    apiKeyRef: 'siliconflow.default',
    model: 'Qwen/Qwen2.5-72B-Instruct',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'Qwen/Qwen2.5-7B-Instruct',
      'coach-deep': 'Qwen/Qwen2.5-72B-Instruct',
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
    label: 'xAI',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.x.ai/v1',
    apiKeyRef: 'xai.default',
    model: 'grok-3',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'grok-3-mini',
      'coach-deep': 'grok-3',
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
    label: 'Groq',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.groq.com/openai/v1',
    apiKeyRef: 'groq.default',
    model: 'llama-3.3-70b-versatile',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'llama-3.1-8b-instant',
      'coach-deep': 'llama-3.3-70b-versatile',
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
    label: 'Mistral',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.mistral.ai/v1',
    apiKeyRef: 'mistral.default',
    model: 'mistral-large-latest',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'mistral-small-latest',
      'coach-deep': 'mistral-large-latest',
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
    label: 'Together AI',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.together.xyz/v1',
    apiKeyRef: 'together.default',
    model: 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'meta-llama/Llama-3.3-8B-Instruct-Turbo',
      'coach-deep': 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
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
  {
    label: 'z.ai',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.z.ai/api/paas/v4',
    apiKeyRef: 'zai.default',
    model: 'glm-4.6',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'glm-4.5-air',
      'coach-deep': 'glm-4.6',
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
    label: 'Kimi (Global)',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.moonshot.ai/v1',
    apiKeyRef: 'kimi-global.default',
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
    label: 'MiniMax (Global)',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.minimax.io/v1',
    apiKeyRef: 'minimax-global.default',
    model: 'MiniMax-M3',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'MiniMax-M2.7-highspeed',
      'coach-deep': 'MiniMax-M3',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_chat_completions_compatible', 'coach-fast'),
      resource_rerank: templateRerankBinding('coach-fast'),
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
    label: 'Volcengine',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    apiKeyRef: 'volcengine.default',
    model: 'doubao-seed-1-6-250615',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'doubao-seed-1-6-flash-250828',
      'coach-deep': 'doubao-seed-1-6-250615',
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
    label: 'StepFun',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.stepfun.com/v1',
    apiKeyRef: 'stepfun.default',
    model: 'step-3',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'step-3',
      'coach-deep': 'step-3',
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
    label: 'Fireworks',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.fireworks.ai/inference/v1',
    apiKeyRef: 'fireworks.default',
    model: 'accounts/fireworks/models/llama-v3p3-70b-instruct',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'accounts/fireworks/models/llama-v3p1-8b-instruct',
      'coach-deep': 'accounts/fireworks/models/llama-v3p3-70b-instruct',
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
    label: 'Novita',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.novita.ai/v3/openai',
    apiKeyRef: 'novita.default',
    model: 'deepseek/deepseek-v3-0324',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'deepseek/deepseek-v3-0324',
      'coach-deep': 'deepseek/deepseek-v3-0324',
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
    label: 'NVIDIA NIM',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    apiKeyRef: 'nvidia.default',
    model: 'meta/llama-3.3-70b-instruct',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'meta/llama-3.1-8b-instruct',
      'coach-deep': 'meta/llama-3.3-70b-instruct',
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
    label: 'Hugging Face',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://router.huggingface.co/v1',
    apiKeyRef: 'huggingface.default',
    model: 'meta-llama/Llama-3.3-70B-Instruct',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'meta-llama/Llama-3.1-8B-Instruct',
      'coach-deep': 'meta-llama/Llama-3.3-70B-Instruct',
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
    label: 'Nebius',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.tokenfactory.nebius.com/v1',
    apiKeyRef: 'nebius.default',
    model: 'meta-llama/Llama-3.3-70B-Instruct',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'meta-llama/Llama-3.1-8B-Instruct',
      'coach-deep': 'meta-llama/Llama-3.3-70B-Instruct',
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
    label: 'GMI Cloud',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.gmi-serving.com/v1',
    apiKeyRef: 'gmi.default',
    model: '',
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
    capabilities: templateCapabilities('openai_chat_completions_compatible', {
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
    }),
    modelCapabilities: {},
  },
  {
    label: 'Arcee',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://conductor.arcee.ai/v1',
    apiKeyRef: 'arcee.default',
    model: 'auto',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'auto',
      'coach-deep': 'auto',
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
    label: 'AI Gateway',
    protocol: 'openai_chat_completions_compatible',
    mode: 'gateway',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://ai-gateway.vercel.sh/v1',
    apiKeyRef: 'ai-gateway.default',
    model: '',
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
    capabilities: templateCapabilities('openai_chat_completions_compatible', {
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
    }),
    modelCapabilities: {},
  },
  {
    label: 'Ollama Cloud',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://ollama.com/v1',
    apiKeyRef: 'ollama-cloud.default',
    model: 'gpt-oss:120b-cloud',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'gpt-oss:20b-cloud',
      'coach-deep': 'gpt-oss:120b-cloud',
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
    label: 'LM Studio',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'http://localhost:1234/v1',
    apiKeyRef: 'lmstudio.default',
    model: '',
    catalogSource: 'manual',
    cacheTtlSeconds: 3600,
    modelAliases: {},
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
    label: 'Azure AI Foundry',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'azure-foundry.default',
    model: '',
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
  {
    label: 'Custom (OpenAI-compatible)',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'custom.default',
    model: '',
    catalogSource: 'manual',
    cacheTtlSeconds: 3600,
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
  {
    label: 'GitHub Copilot',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.githubcopilot.com',
    apiKeyRef: 'copilot.default',
    model: 'gpt-4.1',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'gpt-4.1',
      'coach-deep': 'claude-sonnet-4',
    },
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
  {
    label: 'OpenAI Codex',
    protocol: 'openai_responses',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://chatgpt.com/backend-api/codex',
    apiKeyRef: 'openai-codex.default',
    model: 'gpt-5.1-codex',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'gpt-5.1-codex-mini',
      'coach-deep': 'gpt-5.1-codex',
    },
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_responses', 'coach-fast'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('openai_responses'),
    modelCapabilities: {},
  },
  {
    label: 'Nous Portal',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://inference-api.nousresearch.com/v1',
    apiKeyRef: 'nous.default',
    model: 'Hermes-4-70B',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'Hermes-4-70B',
      'coach-deep': 'Hermes-4-405B',
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
    label: 'Qwen Portal',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://portal.qwen.ai/v1',
    apiKeyRef: 'qwen-portal.default',
    model: 'qwen3-coder-plus',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'qwen3-coder-flash',
      'coach-deep': 'qwen3-coder-plus',
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
    label: 'AWS Bedrock',
    protocol: 'openai_chat_completions_compatible',
    mode: 'gateway',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'bedrock.default',
    model: '',
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
  {
    label: 'Tencent TokenHub',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.lkeap.cloud.tencent.com/v1',
    apiKeyRef: 'tencent-tokenhub.default',
    model: 'deepseek-v3',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {
      'coach-fast': 'deepseek-v3',
      'coach-deep': 'deepseek-r1',
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
    label: 'Ramp Router',
    protocol: 'openai_responses',
    mode: 'gateway',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'ramp-router.default',
    model: '',
    catalogSource: 'provider_live',
    cacheTtlSeconds: 43200,
    modelAliases: {},
    availableModels: [],
    allowedModels: [],
    deniedModels: [],
    taskBindings: {
      coach_reply: templateCoachReplyBinding('openai_responses', 'coach-fast'),
      resource_rerank: templateRerankBinding('coach-fast'),
    },
    requestDefaults: {},
    capabilities: templateCapabilities('openai_responses'),
    modelCapabilities: {},
  },
  {
    label: 'Kilo Code',
    protocol: 'openai_chat_completions_compatible',
    mode: 'gateway',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://api.kilo.ai/api/gateway',
    apiKeyRef: 'kilocode.default',
    model: '',
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
  {
    label: 'OpenCode Zen',
    protocol: 'openai_chat_completions_compatible',
    mode: 'gateway',
    credentialMode: 'ui_proxy',
    baseUrl: 'https://opencode.ai/zen/v1',
    apiKeyRef: 'opencode-zen.default',
    model: '',
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
  {
    label: 'Xiaomi MiMo',
    protocol: 'openai_chat_completions_compatible',
    mode: 'direct',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'xiaomi.default',
    model: '',
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
  {
    label: 'CommandCode',
    protocol: 'openai_chat_completions_compatible',
    mode: 'gateway',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'commandcode.default',
    model: '',
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
  {
    label: 'GitHub Copilot (ACP)',
    protocol: 'openai_chat_completions_compatible',
    mode: 'gateway',
    credentialMode: 'ui_proxy',
    baseUrl: '',
    apiKeyRef: 'copilot-acp.default',
    model: '',
    catalogSource: 'manual',
    cacheTtlSeconds: 3600,
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
   * Create a profile from a template. Optional overrides let callers derive
   * zero-config variants (for example the local practice-mode trial) from the
   * same template catalog without adding entries to it.
   */
  async createFromTemplate(
    templateIndex: number,
    apiKey?: string,
    overrides?: Partial<Omit<ProviderProfileConfig, 'id'>>,
  ): Promise<ProviderProfileConfig | undefined> {
    if (templateIndex < 0 || templateIndex >= PROVIDER_PROFILE_TEMPLATES.length) {
      return undefined;
    }

    const template = PROVIDER_PROFILE_TEMPLATES[templateIndex];
    const base = { ...template, ...overrides };
    const profile = await this.createProfile({
      ...base,
      credentialMode:
        defaultProviderCredentialMode({
          remoteName: vscode.env.remoteName ?? undefined,
          isRemoteWorkspace: Boolean(vscode.env.remoteName),
        }) === 'workspace_secret'
          ? 'workspace_secret'
          : base.credentialMode,
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
