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

test('verified plus observed live last-test can show ready', () => {
  const live = lastTest({
    toolsReady: true,
    toolProbeStatus: 'verified',
    streamingReady: true,
    streamProbeStatus: 'verified',
    thinkingReady: true,
    thinkingProbeStatus: 'verified',
    visionReady: true,
    visionProbeStatus: 'verified',
    capabilityEvidence: [
      verifiedEvidence('tools'),
      verifiedEvidence('streaming'),
      verifiedEvidence('thinking'),
      verifiedEvidence('vision'),
    ],
  });

  assert.deepEqual(deriveSettingsCapabilityChips(live, scope), {
    tools: 'ready',
    streaming: 'ready',
    thinking: 'ready',
    vision: 'ready',
  });
  assert.deepEqual(scopedSettingsCapabilityTruth(live, scope), {
    toolsReady: true,
    streamingReady: true,
    thinkingReady: true,
    visionReady: true,
  });
});

test('declared-only evidence stays unverified and not ready', () => {
  const declared = lastTest({
    toolsReady: true,
    streamingReady: true,
    thinkingReady: true,
    visionReady: true,
    capabilityEvidence: [
      declaredOnlyEvidence('tools'),
      declaredOnlyEvidence('streaming'),
      declaredOnlyEvidence('thinking'),
      declaredOnlyEvidence('vision'),
    ],
  });

  assert.deepEqual(deriveSettingsCapabilityChips(declared, scope), {
    tools: 'unverified',
    streaming: 'unverified',
    thinking: 'unverified',
    vision: 'unverified',
  });
  assert.deepEqual(scopedSettingsCapabilityTruth(declared, scope), {
    toolsReady: false,
    streamingReady: false,
    thinkingReady: false,
    visionReady: false,
  });
});

test('missing last-test and mismatched scope stay unverified', () => {
  const live = lastTest({
    toolsReady: true,
    toolProbeStatus: 'verified',
    capabilityEvidence: [verifiedEvidence('tools')],
  });

  assert.equal(deriveSettingsCapabilityChip(undefined, 'tools', scope), 'unverified');
  assert.equal(
    deriveSettingsCapabilityChip(live, 'tools', { workspaceId: 'workspace-b', providerProfileId: 'profile-a' }),
    'unverified',
  );
  assert.equal(
    deriveSettingsCapabilityChip(live, 'tools', { workspaceId: 'workspace-a', providerProfileId: 'profile-b' }),
    'unverified',
  );
  assert.equal(
    deriveSettingsCapabilityChip({ ...live, workspaceId: undefined }, 'tools', scope),
    'unverified',
  );
  assert.equal(selectScopedSettingsLastTest(live, { workspaceId: 'workspace-b' }), undefined);
});

test('scoped last-test selection strips raw apiKey before UI handoff', () => {
  const polluted = lastTest({ apiKey: 'should-never-reach-settings' });
  const scoped = selectScopedSettingsLastTest(polluted, scope);
  assert.equal(scoped?.ok, true);
  assert.equal('apiKey' in (scoped ?? {}), false);
});

test('ready flags without observed evidence never become ready', () => {
  const leftoverFlags = lastTest({
    toolsReady: true,
    toolProbeStatus: 'verified',
    streamingReady: true,
    thinkingReady: true,
    visionReady: true,
    capabilityEvidence: [],
  });

  assert.deepEqual(deriveSettingsCapabilityChips(leftoverFlags, scope), {
    tools: 'unverified',
    streaming: 'unverified',
    thinking: 'unverified',
    vision: 'unverified',
  });
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

test('never-tested, failed, and unknown protocol hide chips and keep toolsReady false', () => {
  const live = lastTest({
    toolsReady: true,
    toolProbeStatus: 'verified',
    capabilityEvidence: [verifiedEvidence('tools')],
  });

  assert.equal(settingsCapabilitySurfaceStatus(undefined, scope), 'never_tested');
  assert.equal(settingsCapabilityChipsVisible(undefined, scope), false);
  assert.equal(scopedSettingsCapabilityTruth(undefined, scope).toolsReady, false);

  const failedAfterSuccess = lastTest({
    ok: false,
    status: 'failed',
    toolsReady: true,
    toolProbeStatus: 'verified',
    capabilityEvidence: [verifiedEvidence('tools')],
  });
  assert.equal(settingsLastTestAllowsChips(failedAfterSuccess, scope), false);
  assert.equal(settingsCapabilitySurfaceStatus(failedAfterSuccess, scope), 'failed');
  assert.equal(settingsCapabilityChipsVisible(failedAfterSuccess, scope), false);
  assert.equal(deriveSettingsCapabilityChip(failedAfterSuccess, 'tools', scope), 'unverified');
  assert.equal(scopedSettingsCapabilityTruth(failedAfterSuccess, scope).toolsReady, false);

  const unknownProtocol = lastTest({
    protocol: 'newapi',
    toolsReady: true,
    toolProbeStatus: 'verified',
    capabilityEvidence: [verifiedEvidence('tools')],
  });
  assert.equal(settingsCapabilitySurfaceStatus(unknownProtocol, scope, 'newapi'), 'unknown_protocol');
  assert.equal(settingsCapabilityChipsVisible(unknownProtocol, scope, 'newapi'), false);
  assert.equal(scopedSettingsCapabilityTruth(unknownProtocol, scope).toolsReady, false);

  assert.equal(settingsCapabilityChipsVisible(live, scope), true);
  assert.equal(deriveSettingsCapabilityChip(live, 'tools', scope), 'ready');
});

test('failed last-test after success does not keep leftover ready chips', () => {
  const success = lastTest({
    toolsReady: true,
    toolProbeStatus: 'verified',
    streamingReady: true,
    streamProbeStatus: 'verified',
    capabilityEvidence: [verifiedEvidence('tools'), verifiedEvidence('streaming')],
  });
  assert.deepEqual(deriveSettingsCapabilityChips(success, scope).tools, 'ready');

  const failed = lastTest({
    ok: false,
    status: 'failed',
    toolsReady: false,
    toolProbeStatus: 'unverified',
    streamingReady: false,
    streamProbeStatus: 'unverified',
    capabilityEvidence: [],
  });
  assert.deepEqual(deriveSettingsCapabilityChips(failed, scope), {
    tools: 'unverified',
    streaming: 'unverified',
    thinking: 'unverified',
    vision: 'unverified',
  });
  assert.equal(settingsCapabilityChipsVisible(failed, scope), false);
});

test('failed last-test and leftover verified evidence stay unverified and not ready', () => {
  const failed = lastTest({
    ok: false,
    toolsReady: true,
    toolProbeStatus: 'verified',
    streamingReady: true,
    streamProbeStatus: 'verified',
    thinkingReady: true,
    thinkingProbeStatus: 'verified',
    visionReady: true,
    visionProbeStatus: 'verified',
    capabilityEvidence: [
      verifiedEvidence('tools'),
      verifiedEvidence('streaming'),
      verifiedEvidence('thinking'),
      verifiedEvidence('vision'),
    ],
  });

  assert.equal(settingsLastTestAllowsChips(failed, scope), false);
  assert.deepEqual(deriveSettingsCapabilityChips(failed, scope), {
    tools: 'unverified',
    streaming: 'unverified',
    thinking: 'unverified',
    vision: 'unverified',
  });
  assert.deepEqual(scopedSettingsCapabilityTruth(failed, scope), {
    toolsReady: false,
    streamingReady: false,
    thinkingReady: false,
    visionReady: false,
  });
});

test('unknown last-test protocol never allows chips', () => {
  const unknown = lastTest({
    protocol: 'newapi_channel_conn',
    toolsReady: true,
    toolProbeStatus: 'verified',
    capabilityEvidence: [verifiedEvidence('tools')],
  });
  assert.equal(settingsLastTestAllowsChips(unknown, scope), false);
  assert.equal(deriveSettingsCapabilityChip(unknown, 'tools', scope), 'unverified');
  assert.equal(scopedSettingsCapabilityTruth(unknown, scope).toolsReady, false);
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

test('chat-ok but stream-unverified is not streamingReady', () => {
  const chatOkStreamUnverified = lastTest({
    toolsReady: false,
    toolProbeStatus: 'unverified',
    streamingReady: false,
    streamProbeStatus: 'unverified',
    capabilityEvidence: [
      { name: 'streaming', declared: true, observed: null, state: 'unverified' },
    ],
  });
  assert.equal(settingsCapabilitySurfaceStatus(chatOkStreamUnverified, scope), 'live');
  assert.equal(deriveSettingsCapabilityChip(chatOkStreamUnverified, 'streaming', scope), 'unverified');
  assert.equal(scopedSettingsCapabilityTruth(chatOkStreamUnverified, scope).streamingReady, false);
  assert.equal(scopedSettingsCapabilityTruth(chatOkStreamUnverified, scope).toolsReady, false);
});

test('saved capability picks cannot paint ready chips without verified last-test', () => {
  // Old sessions may still have all-true saved picks. Chip readiness APIs take lastTest only
  // (lastTest, name, scope) — saved picks are not a parameter and cannot OR into ready.
  const savedPicksAllTrue = {
    chat: true,
    responses: true,
    vision: true,
    embeddings: true,
    tools: true,
    jsonSchema: true,
    streaming: true,
    structuredOutput: true,
    thinking: true,
  };
  assert.equal(settingsCapabilityIsReady.length, 3);
  assert.equal(savedPicksAllTrue.tools && savedPicksAllTrue.streaming, true);

  assert.equal(settingsCapabilityChipsVisible(undefined, scope), false);
  assert.equal(settingsCapabilityIsReady(undefined, 'tools', scope), false);
  assert.equal(settingsCapabilityIsReady(undefined, 'streaming', scope), false);
  assert.equal(settingsCapabilityIsReady(undefined, 'thinking', scope), false);
  assert.equal(settingsCapabilityIsReady(undefined, 'vision', scope), false);
  assert.deepEqual(deriveSettingsCapabilityChips(undefined, scope), {
    tools: 'unverified',
    streaming: 'unverified',
    thinking: 'unverified',
    vision: 'unverified',
  });
  assert.deepEqual(scopedSettingsCapabilityTruth(undefined, scope), {
    toolsReady: false,
    streamingReady: false,
    thinkingReady: false,
    visionReady: false,
  });

  const failed = lastTest({
    ok: false,
    status: 'failed',
    toolsReady: false,
    streamingReady: false,
    thinkingReady: false,
    visionReady: false,
    capabilityEvidence: [],
  });
  assert.equal(settingsCapabilityChipsVisible(failed, scope), false);
  assert.equal(settingsCapabilityIsReady(failed, 'tools', scope), false);
  assert.equal(settingsCapabilityIsReady(failed, 'streaming', scope), false);
  assert.equal(settingsCapabilityIsReady(failed, 'thinking', scope), false);
  assert.equal(settingsCapabilityIsReady(failed, 'vision', scope), false);
  assert.deepEqual(deriveSettingsCapabilityChips(failed, scope), {
    tools: 'unverified',
    streaming: 'unverified',
    thinking: 'unverified',
    vision: 'unverified',
  });
  assert.deepEqual(scopedSettingsCapabilityTruth(failed, scope), {
    toolsReady: false,
    streamingReady: false,
    thinkingReady: false,
    visionReady: false,
  });
});
