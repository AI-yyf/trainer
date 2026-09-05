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

test('shared provider test copy keeps visible Chinese labels intact', () => {
  const source = fs.readFileSync(providerTestSourcePath, 'utf8');

  assert.match(source, /未提供 API key/u);
  assert.match(source, /中文输入已损坏/u);
  assert.match(source, /provider 返回空响应/u);
  assert.match(source, /测试成功/u);
  assert.doesNotMatch(source, /鏈彁渚|璁よ瘉澶辫触|鏈煡閿欒/u);
});
