'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const machinePath = path.resolve(__dirname, '..', 'dist', 'shared', 'src', 'providerSetupState.js');

const {
  deriveProviderSetupState,
  PROVIDER_SETUP_STATE_DESCRIPTORS,
} = require(machinePath);

const READY_INPUT = {
  workspaceRootMissing: false,
  workspaceTrusted: true,
  availabilityMode: 'ready',
  draftNeedsModelChoice: false,
  draftModelDiscoveryPossible: false,
  draftHasDiscoveredModels: false,
  draftModelBlockedByPolicy: false,
  draftNeedsApiKey: false,
  draftReadyForTest: true,
  draftTestPending: false,
  savedNeedsKey: false,
  savedCredentialsRejected: false,
  savedNeedsTest: false,
};

function input(overrides) {
  return { ...READY_INPUT, ...overrides };
}

test('every ProviderSetupState has a descriptor with tone and action', () => {
  const states = ['needs_root', 'needs_trust', 'needs_key', 'needs_test', 'needs_model', 'ready'];
  assert.deepEqual(Object.keys(PROVIDER_SETUP_STATE_DESCRIPTORS).sort(), states.sort());
  for (const descriptor of Object.values(PROVIDER_SETUP_STATE_DESCRIPTORS)) {
    assert.ok(['neutral', 'pending', 'warning', 'positive'].includes(descriptor.tone));
    assert.ok(['choose_root', 'trust_window', 'enter_key', 'pick_model', 'save_or_test', 'none'].includes(descriptor.action));
  }
  assert.equal(PROVIDER_SETUP_STATE_DESCRIPTORS.ready.tone, 'positive');
  assert.equal(PROVIDER_SETUP_STATE_DESCRIPTORS.ready.action, 'none');
  assert.equal(PROVIDER_SETUP_STATE_DESCRIPTORS.needs_root.action, 'choose_root');
  assert.equal(PROVIDER_SETUP_STATE_DESCRIPTORS.needs_trust.action, 'trust_window');
  assert.equal(PROVIDER_SETUP_STATE_DESCRIPTORS.needs_key.action, 'enter_key');
});

test('ready state: saved, keyed, unblocked connection with no draft', () => {
  const result = deriveProviderSetupState(READY_INPUT);
  assert.equal(result.state, 'ready');
  assert.equal(result.reason, 'ready');
  assert.equal(result.descriptor.tone, 'positive');
  assert.equal(result.descriptor.action, 'none');
});

test('needs_root outranks everything when the workspace root is missing', () => {
  const result = deriveProviderSetupState(input({ workspaceRootMissing: true }));
  assert.equal(result.state, 'needs_root');
  assert.equal(result.reason, 'workspace_root_missing');
  assert.equal(result.descriptor.tone, 'warning');
  assert.equal(result.descriptor.action, 'choose_root');
});

test('needs_trust fires when the window is not trusted and root is chosen', () => {
  for (const trustState of [false]) {
    const result = deriveProviderSetupState(input({ workspaceTrusted: trustState }));
    assert.equal(result.state, 'needs_trust');
    assert.equal(result.reason, 'workspace_untrusted');
    assert.equal(result.descriptor.action, 'trust_window');
  }
});

test('draft ladder keeps the previous precedence: model → key → test', () => {
  const search = deriveProviderSetupState(input({
    availabilityMode: 'draft',
    draftNeedsModelChoice: true,
    draftModelDiscoveryPossible: true,
  }));
  assert.equal(search.state, 'needs_model');
  assert.equal(search.reason, 'draft_model_search');

  const pick = deriveProviderSetupState(input({
    availabilityMode: 'draft',
    draftNeedsModelChoice: true,
    draftHasDiscoveredModels: true,
  }));
  assert.equal(pick.state, 'needs_model');
  assert.equal(pick.reason, 'draft_model_pick');

  const policy = deriveProviderSetupState(input({
    availabilityMode: 'draft',
    draftModelBlockedByPolicy: true,
    draftNeedsModelChoice: true,
    draftHasDiscoveredModels: true,
  }));
  assert.equal(policy.state, 'needs_model');
  assert.equal(policy.reason, 'draft_model_policy');
  assert.equal(policy.descriptor.tone, 'warning');

  const key = deriveProviderSetupState(input({
    availabilityMode: 'draft',
    draftNeedsApiKey: true,
    draftReadyForTest: true,
  }));
  assert.equal(key.state, 'needs_key');
  assert.equal(key.reason, 'draft_needs_key');

  const incomplete = deriveProviderSetupState(input({
    availabilityMode: 'draft',
    draftReadyForTest: false,
  }));
  assert.equal(incomplete.state, 'needs_test');
  assert.equal(incomplete.reason, 'draft_incomplete');

  const ready = deriveProviderSetupState(input({
    availabilityMode: 'draft',
    draftReadyForTest: true,
  }));
  assert.equal(ready.state, 'needs_test');
  assert.equal(ready.reason, 'draft_ready');

  const awaiting = deriveProviderSetupState(input({
    availabilityMode: 'draft',
    draftReadyForTest: true,
    draftTestPending: true,
  }));
  assert.equal(awaiting.reason, 'draft_await_test');
});

test('saved-connection health maps to needs_key / needs_test / provider_failure', () => {
  const key = deriveProviderSetupState(input({ availabilityMode: 'missing_api_key' }));
  assert.equal(key.state, 'needs_key');
  assert.equal(key.reason, 'saved_needs_key');
  assert.equal(key.descriptor.tone, 'warning');

  const rejected = deriveProviderSetupState(input({ availabilityMode: 'recent_failure', savedCredentialsRejected: true }));
  assert.equal(rejected.state, 'needs_key');
  assert.equal(rejected.reason, 'credentials_rejected');

  const retest = deriveProviderSetupState(input({ availabilityMode: 'needs_test' }));
  assert.equal(retest.state, 'needs_test');
  assert.equal(retest.reason, 'saved_needs_test');

  const failure = deriveProviderSetupState(input({ availabilityMode: 'blocked_error' }));
  assert.equal(failure.state, 'needs_test');
  assert.equal(failure.reason, 'provider_failure');
});

test('warming / refreshing / missing_provider keep their previous meanings', () => {
  const warming = deriveProviderSetupState(input({ availabilityMode: 'warming' }));
  assert.equal(warming.state, 'needs_test');
  assert.equal(warming.reason, 'checking');

  const refreshing = deriveProviderSetupState(input({ availabilityMode: 'refreshing' }));
  assert.equal(refreshing.state, 'needs_model');
  assert.equal(refreshing.reason, 'refreshing');

  const fresh = deriveProviderSetupState(input({ availabilityMode: 'missing_provider' }));
  assert.equal(fresh.state, 'needs_model');
  assert.equal(fresh.reason, 'fresh_setup');
  assert.equal(fresh.descriptor.tone, 'pending');
});
