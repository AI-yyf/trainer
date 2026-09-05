import type { ProviderCredentialMode, WorkspaceSnapshot } from './types';
import { normalizeProviderRequestDefaults } from '../../../shared/src/providerRequestDefaults';

export function defaultProviderCredentialMode(
  workspace: Pick<WorkspaceSnapshot, 'remoteName' | 'isRemoteWorkspace'> | undefined,
): ProviderCredentialMode {
  return workspace?.isRemoteWorkspace || workspace?.remoteName ? 'workspace_secret' : 'ui_proxy';
}

export { normalizeProviderRequestDefaults };
