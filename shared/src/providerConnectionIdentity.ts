import { normalizeProviderProtocol } from './providerProtocols';

/** Canonical host identity without folding case-sensitive paths or model IDs. */
export function providerEndpointIdentity(value: string | undefined | null): string {
  const trimmed = typeof value === 'string' ? value.trim().replace(/\/+$/, '') : '';
  if (!trimmed) {
    return '';
  }
  try {
    return new URL(trimmed).toString().replace(/\/+$/, '');
  } catch {
    return trimmed;
  }
}
interface ProviderRequestIdentity {
  baseUrl: string;
  model: string;
  protocol?: string;
  apiKeyRef?: string;
  profileId?: string;
}

export function sameProviderRequestIdentity(left: ProviderRequestIdentity | undefined, right: ProviderRequestIdentity | undefined): boolean {
  return Boolean(left && right &&
    providerEndpointIdentity(left.baseUrl) === providerEndpointIdentity(right.baseUrl) &&
    normalizeProviderProtocol(left.protocol) === normalizeProviderProtocol(right.protocol) &&
    left.model.trim() === right.model.trim() &&
    (left.apiKeyRef?.trim() ?? '') === (right.apiKeyRef?.trim() ?? '') &&
    (left.profileId?.trim() ?? '') === (right.profileId?.trim() ?? ''));
}

