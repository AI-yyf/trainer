// Restored behavioral regression test. Original file: extension/tests/settingsCapabilityGovernanceShared.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Settings capability governance: last-test scope selection with secret stripping and fail-closed unknown protocols.
//
// Restoration: partial - 3 of 13 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "verified plus observed live last-test can show ready"
//       fails at HEAD: deriveSettingsCapabilityChips is not a function
//   - "declared-only evidence stays unverified and not ready"
//       fails at HEAD: deriveSettingsCapabilityChips is not a function
//   - "missing last-test and mismatched scope stay unverified"
//       fails at HEAD: deriveSettingsCapabilityChip is not a function
//   - "ready flags without observed evidence never become ready"
//       fails at HEAD: deriveSettingsCapabilityChips is not a function
//   - "never-tested, failed, and unknown protocol hide chips and keep toolsReady false"
//       fails at HEAD: deriveSettingsCapabilityChip is not a function
//   - "failed last-test after success does not keep leftover ready chips"
//       fails at HEAD: deriveSettingsCapabilityChips is not a function
//   - "failed last-test and leftover verified evidence stay unverified and not ready"
//       fails at HEAD: deriveSettingsCapabilityChips is not a function
//   - "unknown last-test protocol never allows chips"
//       fails at HEAD: deriveSettingsCapabilityChip is not a function
//   - "chat-ok but stream-unverified is not streamingReady"
//       fails at HEAD: deriveSettingsCapabilityChip is not a function
//   - "saved capability picks cannot paint ready chips without verified last-test"
//       fails at HEAD: deriveSettingsCapabilityChips is not a function
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  deriveSettingsCapabilityChip,
  deriveSettingsCapabilityChips,
  scopedSettingsCapabilityTruth,
  selectScopedSettingsLastTest,
  settingsCapabilityChipsVisible,
  settingsCapabilityIsReady,
  settingsCapabilitySurfaceStatus,
  settingsLastTestAllowsChips,
  settingsProtocolIsKnown,
} = require('../dist/shared/src/settingsCapabilityGovernance.js');
const { defaultCapabilitiesForProtocol } = require('../dist/shared/src/providerProtocols.js');

const scope = { workspaceId: 'workspace-a', providerProfileId: 'profile-a' };

function lastTest(overrides = {}) {
  return {
    ok: true,
    workspaceId: 'workspace-a',
    profileId: 'profile-a',
    protocol: 'openai_chat_completions_compatible',
    toolsReady: false,
    toolProbeStatus: 'unverified',
    streamingReady: false,
    streamProbeStatus: 'unverified',
    thinkingReady: false,
    thinkingProbeStatus: 'unverified',
    visionReady: false,
    visionProbeStatus: 'unverified',
    capabilityEvidence: [],
    ...overrides,
  };
}

function verifiedEvidence(name) {
  return { name, declared: true, observed: true, state: 'verified' };
}

function declaredOnlyEvidence(name) {
  return { name, declared: true, observed: null, state: 'unverified' };
}



test('scoped last-test selection strips raw apiKey before UI handoff', () => {
  const polluted = lastTest({ apiKey: 'should-never-reach-settings' });
  const scoped = selectScopedSettingsLastTest(polluted, scope);
  assert.equal(scoped?.ok, true);
  assert.equal('apiKey' in (scoped ?? {}), false);
});

test('unknown protocol stays fail-closed and does not look compatible', () => {
  assert.equal(settingsProtocolIsKnown(undefined), false);
  assert.equal(settingsProtocolIsKnown('newapi'), false);
  assert.equal(settingsProtocolIsKnown('openai_chat_completions_compatible'), true);
  assert.deepEqual(defaultCapabilitiesForProtocol(undefined), {
    chat: false,
    responses: false,
    vision: false,
    embeddings: false,
    tools: false,
    jsonSchema: false,
    streaming: false,
    structuredOutput: false,
    thinking: false,
  });
});




test('missing protocol on ok last-test stays fail-closed', () => {
  const missingProtocol = lastTest({
    protocol: undefined,
    toolsReady: true,
    toolProbeStatus: 'verified',
    streamingReady: true,
    streamProbeStatus: 'verified',
    capabilityEvidence: [verifiedEvidence('tools'), verifiedEvidence('streaming')],
  });
  assert.equal(settingsLastTestAllowsChips(missingProtocol, scope), false);
  assert.equal(settingsCapabilitySurfaceStatus(missingProtocol, scope), 'unknown_protocol');
  assert.equal(settingsCapabilityChipsVisible(missingProtocol, scope), false);
  assert.equal(scopedSettingsCapabilityTruth(missingProtocol, scope).toolsReady, false);
  assert.equal(scopedSettingsCapabilityTruth(missingProtocol, scope).streamingReady, false);
});

