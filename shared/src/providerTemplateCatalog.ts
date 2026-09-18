/**
 * Provider template labels for the webview "start from a template" picker.
 *
 * These strings MUST match `PROVIDER_PROFILE_TEMPLATES[].label` in
 * `extension/src/provider/providerProfileRegistry.ts` exactly — the webview
 * sends the label back and the host resolves the template by it. A parity test
 * (providerTemplateCatalogParity.test.js) guards the two lists.
 */
export const PROVIDER_TEMPLATE_LABELS: readonly string[] = [
  'OpenAI',
  'OpenAI Chat Completions',
  'Anthropic',
  'Gemini',
  'OpenRouter',
  'Ollama (Local)',
  'DeepSeek',
  'Kimi',
  'MiniMax',
  'Zhipu GLM',
  'Qwen',
  'SiliconFlow',
  'xAI',
  'Groq',
  'Mistral',
  'Together AI',
  'New API',
  'z.ai',
  'Kimi (Global)',
  'MiniMax (Global)',
  'Volcengine',
  'StepFun',
  'Fireworks',
  'Novita',
  'NVIDIA NIM',
  'Hugging Face',
  'Nebius',
  'GMI Cloud',
  'Arcee',
  'AI Gateway',
  'Ollama Cloud',
  'LM Studio',
  'Azure AI Foundry',
  'Custom (OpenAI-compatible)',
  'GitHub Copilot',
  'OpenAI Codex',
  'Nous Portal',
  'Qwen Portal',
  'AWS Bedrock',
  'Tencent TokenHub',
  'Ramp Router',
  'Kilo Code',
  'OpenCode Zen',
  'Xiaomi MiMo',
  'CommandCode',
  'GitHub Copilot (ACP)',
];

export type ProviderTemplateGroup =
  | 'major'
  | 'china'
  | 'aggregator'
  | 'subscription'
  | 'local'
  | 'custom';

/**
 * Display grouping for the settings picker — the catalog stays flat so the
 * host contract (label → template) never depends on presentation order.
 */
export const PROVIDER_TEMPLATE_GROUPS: Readonly<
  Record<string, ProviderTemplateGroup>
> = {
  OpenAI: 'major',
  'OpenAI Chat Completions': 'major',
  Anthropic: 'major',
  Gemini: 'major',
  xAI: 'major',
  Mistral: 'major',
  'Zhipu GLM': 'china',
  'z.ai': 'china',
  Qwen: 'china',
  DeepSeek: 'china',
  Kimi: 'china',
  'Kimi (Global)': 'china',
  MiniMax: 'china',
  'MiniMax (Global)': 'china',
  Volcengine: 'china',
  StepFun: 'china',
  SiliconFlow: 'china',
  'Tencent TokenHub': 'china',
  'Xiaomi MiMo': 'china',
  OpenRouter: 'aggregator',
  Groq: 'aggregator',
  'Together AI': 'aggregator',
  Fireworks: 'aggregator',
  Novita: 'aggregator',
  'NVIDIA NIM': 'aggregator',
  'Hugging Face': 'aggregator',
  Nebius: 'aggregator',
  'GMI Cloud': 'aggregator',
  Arcee: 'aggregator',
  'AI Gateway': 'aggregator',
  'Ollama Cloud': 'aggregator',
  'Kilo Code': 'aggregator',
  'OpenCode Zen': 'aggregator',
  'Ramp Router': 'aggregator',
  'GitHub Copilot': 'subscription',
  'OpenAI Codex': 'subscription',
  'Nous Portal': 'subscription',
  'Qwen Portal': 'subscription',
  'Ollama (Local)': 'local',
  'LM Studio': 'local',
  'New API': 'custom',
  'Azure AI Foundry': 'custom',
  'AWS Bedrock': 'custom',
  CommandCode: 'custom',
  'GitHub Copilot (ACP)': 'custom',
  'Custom (OpenAI-compatible)': 'custom',
};

export const PROVIDER_TEMPLATE_GROUP_ORDER: readonly ProviderTemplateGroup[] = [
  'major',
  'china',
  'aggregator',
  'subscription',
  'local',
  'custom',
];

export type ProviderTemplatePreset = {
  protocol: string;
  baseUrl: string;
  model: string;
};

/**
 * Minimal connection preset per template label — enough for non-host
 * environments (browser preview) to apply a template. The extension host
 * still resolves the full `PROVIDER_PROFILE_TEMPLATES` entry by label; the
 * parity test keeps these values in sync with the registry.
 */
export const PROVIDER_TEMPLATE_PRESETS: Readonly<
  Record<string, ProviderTemplatePreset>
> = {
  OpenAI: {
    protocol: 'openai_responses',
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-5-mini',
  },
  'OpenAI Chat Completions': {
    protocol: 'openai_chat_completions',
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-5-mini',
  },
  Anthropic: {
    protocol: 'anthropic_messages',
    baseUrl: 'https://api.anthropic.com',
    model: 'claude-sonnet-4-20250514',
  },
  Gemini: {
    protocol: 'gemini_generate_content',
    baseUrl: 'https://generativelanguage.googleapis.com',
    model: 'gemini-2.0-flash',
  },
  OpenRouter: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://openrouter.ai/api/v1',
    model: 'openai/gpt-5-mini',
  },
  'Ollama (Local)': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://localhost:11434/v1',
    model: 'llama3.2',
  },
  DeepSeek: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
  },
  Kimi: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.moonshot.cn/v1',
    model: 'kimi-k3',
  },
  MiniMax: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.minimaxi.com/v1',
    model: 'MiniMax-M3',
  },
  'Zhipu GLM': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4.6',
  },
  Qwen: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
  },
  SiliconFlow: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.siliconflow.cn/v1',
    model: 'Qwen/Qwen2.5-72B-Instruct',
  },
  xAI: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.x.ai/v1',
    model: 'grok-3',
  },
  Groq: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.groq.com/openai/v1',
    model: 'llama-3.3-70b-versatile',
  },
  Mistral: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.mistral.ai/v1',
    model: 'mistral-large-latest',
  },
  'Together AI': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.together.xyz/v1',
    model: 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
  },
  'New API': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: '',
    model: '',
  },
  'z.ai': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.z.ai/api/paas/v4',
    model: 'glm-4.6',
  },
  'Kimi (Global)': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.moonshot.ai/v1',
    model: 'kimi-k3',
  },
  'MiniMax (Global)': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.minimax.io/v1',
    model: 'MiniMax-M3',
  },
  Volcengine: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    model: 'doubao-seed-1-6-250615',
  },
  StepFun: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.stepfun.com/v1',
    model: 'step-3',
  },
  Fireworks: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.fireworks.ai/inference/v1',
    model: 'accounts/fireworks/models/llama-v3p3-70b-instruct',
  },
  Novita: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.novita.ai/v3/openai',
    model: 'deepseek/deepseek-v3-0324',
  },
  'NVIDIA NIM': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://integrate.api.nvidia.com/v1',
    model: 'meta/llama-3.3-70b-instruct',
  },
  'Hugging Face': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://router.huggingface.co/v1',
    model: 'meta-llama/Llama-3.3-70B-Instruct',
  },
  Nebius: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.tokenfactory.nebius.com/v1',
    model: 'meta-llama/Llama-3.3-70B-Instruct',
  },
  'GMI Cloud': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.gmi-serving.com/v1',
    model: '',
  },
  Arcee: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://conductor.arcee.ai/v1',
    model: 'auto',
  },
  'AI Gateway': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://ai-gateway.vercel.sh/v1',
    model: '',
  },
  'Ollama Cloud': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://ollama.com/v1',
    model: 'gpt-oss:120b-cloud',
  },
  'LM Studio': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: '',
  },
  'Azure AI Foundry': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: '',
    model: '',
  },
  'Custom (OpenAI-compatible)': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: '',
    model: '',
  },
  'GitHub Copilot': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.githubcopilot.com',
    model: 'gpt-4.1',
  },
  'OpenAI Codex': {
    protocol: 'openai_responses',
    baseUrl: 'https://chatgpt.com/backend-api/codex',
    model: 'gpt-5.1-codex',
  },
  'Nous Portal': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://inference-api.nousresearch.com/v1',
    model: 'Hermes-4-70B',
  },
  'Qwen Portal': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://portal.qwen.ai/v1',
    model: 'qwen3-coder-plus',
  },
  'AWS Bedrock': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: '',
    model: '',
  },
  'Tencent TokenHub': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.lkeap.cloud.tencent.com/v1',
    model: 'deepseek-v3',
  },
  'Ramp Router': {
    protocol: 'openai_responses',
    baseUrl: '',
    model: '',
  },
  'Kilo Code': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.kilo.ai/api/gateway',
    model: '',
  },
  'OpenCode Zen': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://opencode.ai/zen/v1',
    model: '',
  },
  'Xiaomi MiMo': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: '',
    model: '',
  },
  CommandCode: {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: '',
    model: '',
  },
  'GitHub Copilot (ACP)': {
    protocol: 'openai_chat_completions_compatible',
    baseUrl: '',
    model: '',
  },
};
