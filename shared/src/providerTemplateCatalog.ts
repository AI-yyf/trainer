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
  'New API',
];
