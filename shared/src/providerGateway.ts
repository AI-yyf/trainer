export const NEWAPI_CONNECTION_TYPE = 'newapi_channel_conn';

const NEWAPI_CONNECTION_ALIASES = new Set([
  'newapi_channel_conn',
  'newapi',
  'new-api',
  'new_api',
  'oneapi',
  'one-api',
]);

export type ProviderGatewayKind = 'newapi' | 'unknown';

export interface ProviderGatewayFingerprint {
  kind: ProviderGatewayKind;
  connectionType?: string;
  version?: string;
  catalogEndpointTypes: readonly string[];
}

function headerMap(headers: unknown): Record<string, string> {
  if (!headers || typeof headers !== 'object') {
    return {};
  }
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers as Record<string, unknown>)) {
    if (typeof value === 'string' && value.trim()) {
      result[key.trim().toLowerCase()] = value.trim();
    }
  }
  return result;
}

/** Connection types are not protocols. Unknown values stay unknown. */
export function normalizeProviderConnectionType(
  value: string | undefined,
): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }
  const normalized = value.trim().toLowerCase().replace(/\s+/g, '_');
  if (!normalized) {
    return undefined;
  }
  if (NEWAPI_CONNECTION_ALIASES.has(normalized)) {
    return NEWAPI_CONNECTION_TYPE;
  }
  return undefined;
}

export function isNewApiConnectionType(value: string | undefined): boolean {
  return normalizeProviderConnectionType(value) === NEWAPI_CONNECTION_TYPE;
}

export function inspectProviderGatewayHeaders(headers: unknown): ProviderGatewayFingerprint {
  const normalized = headerMap(headers);
  const version = normalized['x-new-api-version'];
  const oneApiRequest = normalized['x-oneapi-request-id'];
  if (version || oneApiRequest) {
    return {
      kind: 'newapi',
      connectionType: NEWAPI_CONNECTION_TYPE,
      ...(version ? { version } : {}),
      catalogEndpointTypes: [],
    };
  }
  return {
    kind: 'unknown',
    catalogEndpointTypes: [],
  };
}

export function gatewayFingerprintDiagnostics(fingerprint: ProviderGatewayFingerprint): string[] {
  if (fingerprint.kind === 'newapi') {
    const version = fingerprint.version ? ` ${fingerprint.version}` : '';
    const claims = fingerprint.catalogEndpointTypes.length
      ? ` Catalog claimed endpoint types: ${fingerprint.catalogEndpointTypes.join(', ')}.`
      : '';
    return [
      `Gateway fingerprint: ${NEWAPI_CONNECTION_TYPE} (New API${version}).` +
        ' Catalog endpoint types are claims, not live protocol evidence.' +
        ' Unknown fields will not be sent.' +
        claims,
    ];
  }
  return [
    'Gateway fingerprint: unknown. Trainer will not assume OpenAI-compatible until a live protocol probe succeeds.',
  ];
}

export interface ParsedProviderConnectionPaste {
  baseUrl: string;
  apiKey: string;
  connectionType?: string;
}

const PROVIDER_CONNECTION_PASTE_MAX_LENGTH = 4096;

const PROVIDER_CONNECTION_URL_FIELDS = [
  'url',
  'base_url',
  'baseUrl',
  'endpoint',
  'api_base',
  'apiBase',
  'host',
] as const;

const PROVIDER_CONNECTION_KEY_FIELDS = [
  'key',
  'api_key',
  'apiKey',
  'token',
  'access_token',
  'accessToken',
  'secret',
] as const;

const PROVIDER_CONNECTION_TYPE_FIELDS = ['_type', 'connection_type', 'connectionType'] as const;

/**
 * Strip common copy wrappers around a pasted JSON blob: whitespace, one pair
 * of surrounding quotes/backticks, or a fenced ```json block. Returns the
 * innermost candidate text.
 */
function unwrapPastedConnectionText(text: string): string {
  let cleaned = text.trim();
  const fence = cleaned.match(/^```[a-zA-Z0-9]*\s*([\s\S]*?)\s*```$/);
  if (fence) {
    cleaned = fence[1].trim();
  }
  if (
    (cleaned.startsWith('`') && cleaned.endsWith('`') && cleaned.length >= 2) ||
    (cleaned.startsWith('"') && cleaned.endsWith('"') && cleaned.length >= 2)
  ) {
    cleaned = cleaned.slice(1, -1).trim();
  }
  return cleaned;
}

function looksLikeProviderServiceAddress(value: string): boolean {
  if (/^https?:\/\//i.test(value)) {
    return true;
  }
  if (/\s/.test(value)) {
    return false;
  }
  const host = value.split('/')[0];
  return (
    host === 'localhost' ||
    /^localhost:\d+$/.test(host) ||
    /^(\d{1,3}\.){3}\d{1,3}(:\d+)?$/.test(host) ||
    (/^[a-z0-9][a-z0-9.-]*(:\d+)?$/i.test(host) && host.includes('.'))
  );
}

/**
 * Recognize a pasted relay "connection info" JSON blob (New API style:
 * {"_type":"newapi_channel_conn","key":"sk-…","url":"https://…"}) and split it
 * into base URL + API key so the settings form can fill both fields in one
 * paste. JSON.parse only — no execution, size-capped, and both a URL-shaped
 * and key-shaped field must be present before the paste is claimed.
 */
export function parseProviderConnectionPaste(
  text: string,
): ParsedProviderConnectionPaste | null {
  if (typeof text !== 'string') {
    return null;
  }
  const cleaned = unwrapPastedConnectionText(text);
  if (!cleaned || cleaned.length > PROVIDER_CONNECTION_PASTE_MAX_LENGTH) {
    return null;
  }
  if (!cleaned.startsWith('{') || !cleaned.endsWith('}')) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(cleaned);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return null;
  }
  const record = parsed as Record<string, unknown>;
  const readStringField = (...names: readonly string[]): string => {
    for (const name of names) {
      const value = record[name];
      if (typeof value === 'string' && value.trim()) {
        return value.trim();
      }
    }
    return '';
  };
  const url = readStringField(...PROVIDER_CONNECTION_URL_FIELDS);
  const apiKey = readStringField(...PROVIDER_CONNECTION_KEY_FIELDS);
  if (!url || !apiKey || !looksLikeProviderServiceAddress(url)) {
    return null;
  }
  const connectionType = readStringField(...PROVIDER_CONNECTION_TYPE_FIELDS);
  return {
    baseUrl: url,
    apiKey,
    ...(connectionType ? { connectionType } : {}),
  };
}
