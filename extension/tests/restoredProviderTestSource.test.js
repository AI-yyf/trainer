// Restored behavioral regression test. Original file: extension/tests/providerTestSource.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Provider capability truth from observed tool and streaming probes.
//
// Restoration: partial - 3 of 4 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "shared provider test copy keeps visible Chinese labels intact"
//       source-text guard: reads shared/src/providerTest.ts and asserts on its text (out of scope by
//       rule).
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const providerTestSourcePath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'providerTest.ts');
const providerTestModulePath = path.resolve(__dirname, '..', 'dist', 'shared', 'src', 'providerTest.js');

test('provider capability truth requires observed structured tool evidence', () => {
  const { normalizeProviderCapabilityTruth } = require(providerTestModulePath);

  const verified = normalizeProviderCapabilityTruth({
    capability_evidence: [{ name: 'tools', declared: true, observed: true, state: 'verified' }],
    tools_ready: true,
    tool_probe_status: 'verified',
  });
  const declaredOnly = normalizeProviderCapabilityTruth({
    capabilityEvidence: [{ name: 'tools', declared: true, observed: null, state: 'unverified' }],
    toolsReady: true,
    toolProbeStatus: 'verified',
  });

  assert.equal(verified.toolsReady, true);
  assert.equal(verified.toolProbeStatus, 'verified');
  assert.equal(declaredOnly.toolsReady, false);
  assert.equal(declaredOnly.toolProbeStatus, 'unverified');
});

test('provider capability truth keeps an observed unsupported tool probe distinct', () => {
  const { normalizeProviderCapabilityTruth } = require(providerTestModulePath);
  const result = normalizeProviderCapabilityTruth({
    capabilityEvidence: [{ name: 'tools', declared: true, observed: false, state: 'unsupported' }],
    toolsReady: false,
  });

  assert.equal(result.toolsReady, false);
  assert.equal(result.toolProbeStatus, 'unsupported');
});

test('provider capability truth keeps streaming verification independent from tools', () => {
  const { normalizeProviderCapabilityTruth } = require(providerTestModulePath);
  const result = normalizeProviderCapabilityTruth({
    capabilityEvidence: [
      { name: 'tools', declared: true, observed: false, state: 'unsupported' },
      { name: 'streaming', declared: true, observed: true, state: 'verified' },
    ],
    toolsReady: false,
    streamingReady: true,
    streamProbeStatus: 'verified',
  });

  assert.equal(result.toolsReady, false);
  assert.equal(result.toolProbeStatus, 'unsupported');
  assert.equal(result.streamingReady, true);
  assert.equal(result.streamProbeStatus, 'verified');
});
