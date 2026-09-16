/**
 * Provider setup state machine (batch 2 refactor).
 *
 * Replaces the nested-ternary ladders in CoachSettingsView with an explicit
 * derivation: `deriveProviderSetupState` folds workspace admission, window
 * trust, saved-connection health and provider-draft progress into one
 * `ProviderSetupState`, plus a `reason` that preserves the old ladder's
 * sub-case copy. `PROVIDER_SETUP_STATE_DESCRIPTORS` is the single
 * state → { tone, action } map the settings view renders from.
 */

export type ProviderSetupState =
  | 'needs_root'
  | 'needs_trust'
  | 'needs_key'
  | 'needs_test'
  | 'needs_model'
  | 'ready';

/**
 * Why the machine landed on a state. Mirrors the sub-cases of the previous
 * nested ternaries so copy stays identical per path.
 */
export type ProviderSetupReason =
  | 'workspace_root_missing'
  | 'workspace_untrusted'
  // Draft (unsaved) connection sub-cases, in previous ladder order:
  | 'draft_model_search'
  | 'draft_model_pick'
  | 'draft_model_policy'
  | 'draft_needs_key'
  | 'draft_incomplete'
  | 'draft_await_test'
  | 'draft_ready'
  // Saved-connection sub-cases:
  | 'saved_needs_key'
  | 'credentials_rejected'
  | 'saved_needs_test'
  | 'provider_failure'
  | 'checking'
  | 'refreshing'
  | 'fresh_setup'
  | 'ready';

export type ProviderSetupAction =
  | 'choose_root'
  | 'trust_window'
  | 'enter_key'
  | 'pick_model'
  | 'save_or_test'
  | 'none';

export type ProviderSetupTone = 'neutral' | 'pending' | 'warning' | 'positive';

export interface ProviderSetupStateDescriptor {
  state: ProviderSetupState;
  tone: ProviderSetupTone;
  action: ProviderSetupAction;
}

export interface ProviderSetupDerivation {
  state: ProviderSetupState;
  reason: ProviderSetupReason;
  descriptor: ProviderSetupStateDescriptor;
}

export interface ProviderSetupMachineInput {
  workspaceRootMissing: boolean;
  workspaceTrusted: boolean;
  /**
   * One of the previous `availabilityMode` values
   * (`draft | warming | recent_failure | needs_test | ready | refreshing |
   * missing_api_key | missing_provider | degraded_error | blocked_error`).
   */
  availabilityMode: string;
  draftNeedsModelChoice: boolean;
  draftModelDiscoveryPossible: boolean;
  draftHasDiscoveredModels: boolean;
  draftModelBlockedByPolicy: boolean;
  draftNeedsApiKey: boolean;
  draftReadyForTest: boolean;
  draftTestPending: boolean;
  savedNeedsKey: boolean;
  savedCredentialsRejected: boolean;
  savedNeedsTest: boolean;
}

export const PROVIDER_SETUP_STATE_DESCRIPTORS: Record<ProviderSetupState, ProviderSetupStateDescriptor> = {
  needs_root: { state: 'needs_root', tone: 'warning', action: 'choose_root' },
  needs_trust: { state: 'needs_trust', tone: 'warning', action: 'trust_window' },
  needs_key: { state: 'needs_key', tone: 'warning', action: 'enter_key' },
  needs_model: { state: 'needs_model', tone: 'pending', action: 'pick_model' },
  needs_test: { state: 'needs_test', tone: 'pending', action: 'save_or_test' },
  ready: { state: 'ready', tone: 'positive', action: 'none' },
};

function derivation(state: ProviderSetupState, reason: ProviderSetupReason): ProviderSetupDerivation {
  let tone: ProviderSetupTone = PROVIDER_SETUP_STATE_DESCRIPTORS[state].tone;
  if (reason === 'credentials_rejected' || reason === 'saved_needs_key' || reason === 'draft_model_policy') {
    tone = 'warning';
  }
  return { state, reason, descriptor: { ...PROVIDER_SETUP_STATE_DESCRIPTORS[state], tone } };
}

/**
 * Derive the provider setup state. Priority: workspace root → window trust →
 * provider draft progress → saved-connection health → ready.
 */
export function deriveProviderSetupState(input: ProviderSetupMachineInput): ProviderSetupDerivation {
  if (input.workspaceRootMissing) {
    return derivation('needs_root', 'workspace_root_missing');
  }
  if (!input.workspaceTrusted) {
    return derivation('needs_trust', 'workspace_untrusted');
  }

  if (input.availabilityMode === 'draft') {
    if (input.draftModelBlockedByPolicy) {
      return derivation('needs_model', 'draft_model_policy');
    }
    if (input.draftNeedsModelChoice && input.draftHasDiscoveredModels) {
      return derivation('needs_model', 'draft_model_pick');
    }
    if (input.draftNeedsModelChoice && input.draftModelDiscoveryPossible) {
      return derivation('needs_model', 'draft_model_search');
    }
    if (input.draftNeedsApiKey) {
      return derivation('needs_key', 'draft_needs_key');
    }
    return derivation(
      'needs_test',
      input.draftTestPending ? 'draft_await_test' : input.draftReadyForTest ? 'draft_ready' : 'draft_incomplete',
    );
  }
  if (input.availabilityMode === 'warming') {
    return derivation('needs_test', 'checking');
  }
  if (input.availabilityMode === 'refreshing') {
    return derivation('needs_model', 'refreshing');
  }
  if (input.availabilityMode === 'missing_provider') {
    return derivation('needs_model', 'fresh_setup');
  }
  if (input.availabilityMode === 'missing_api_key') {
    return derivation('needs_key', 'saved_needs_key');
  }
  if (input.availabilityMode === 'ready') {
    return derivation('ready', 'ready');
  }
  // recent_failure / needs_test / degraded_error / blocked_error:
  if (input.savedCredentialsRejected) {
    return derivation('needs_key', 'credentials_rejected');
  }
  if (input.savedNeedsKey) {
    return derivation('needs_key', 'saved_needs_key');
  }
  return derivation(
    'needs_test',
    input.availabilityMode === 'needs_test' ? 'saved_needs_test' : 'provider_failure',
  );
}
