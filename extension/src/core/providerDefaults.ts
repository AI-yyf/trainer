import type { ProviderCredentialMode, WorkspaceSnapshot } from './types';
import { normalizeProviderRequestDefaults } from '../../../shared/src/providerRequestDefaults';

export function defaultProviderCredentialMode(
  workspace: Pick<WorkspaceSnapshot, 'remoteName' | 'isRemoteWorkspace'> | undefined,
): ProviderCredentialMode {
  // The UI extension's SecretStorage is always local to this host. Remote
  // workspace detection therefore cannot justify claiming remote secret storage.
  return 'ui_proxy';
}

export { normalizeProviderRequestDefaults };
