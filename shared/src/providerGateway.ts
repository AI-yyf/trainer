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
