'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { deriveTrainerCapabilityVerdict } = require('../dist/shared/src/capabilityVerdict.js');

const readyInput = {
  providerConfigured: true,
  apiKeyConfigured: true,
  connectionState: 'connected',
  lastTestOk: true,
};

test('provider not configured keeps all provider capabilities unavailable', () => {
  const verdict = deriveTrainerCapabilityVerdict({});

  assert.equal(verdict.chat, false);
  assert.equal(verdict.streaming, false);
  assert.equal(verdict.verifiedTools, false);
  assert.equal(verdict.imageInput, false);
  assert.equal(verdict.formalPlan, false);
  assert.equal(verdict.reason, 'provider_not_configured');
});

test('never-tested provider does not claim chat or tools as live', () => {
  const verdict = deriveTrainerCapabilityVerdict({
    providerConfigured: true,
    apiKeyConfigured: true,
    connectionState: 'connected',
  });

  assert.equal(verdict.chat, false);
  assert.equal(verdict.streaming, false);
  assert.equal(verdict.verifiedTools, false);
  assert.equal(verdict.formalPlan, false);
  assert.equal(verdict.reason, 'provider_not_tested');
});

test('connected provider keeps chat usable while streaming remains independently unverified', () => {
  const verdict = deriveTrainerCapabilityVerdict(readyInput);

  assert.equal(verdict.chat, true);
  assert.equal(verdict.streaming, false);
  assert.equal(verdict.verifiedTools, false);
  assert.equal(verdict.imageInput, false);
  assert.equal(verdict.formalPlan, false);
  assert.equal(verdict.reason, 'tools_not_verified');
});

test('never-tested connected provider stays fail-closed for chat and chips', () => {
  const verdict = deriveTrainerCapabilityVerdict({
    providerConfigured: true,
    apiKeyConfigured: true,
    connectionState: 'connected',
  });

  assert.equal(verdict.chat, false);
  assert.equal(verdict.streaming, false);
  assert.equal(verdict.verifiedTools, false);
  assert.equal(verdict.imageInput, false);
  assert.equal(verdict.formalPlan, false);
  assert.equal(verdict.reason, 'provider_not_tested');
});

test('all-true capabilityTruth cannot bypass failed or missing last-test', () => {
  const claimedReady = {
    toolsReady: true,
    streamingReady: true,
    thinkingReady: true,
    visionReady: true,
  };
  for (const lastTestOk of [false, undefined]) {
    const verdict = deriveTrainerCapabilityVerdict({
      providerConfigured: true,
      apiKeyConfigured: true,
      connectionState: 'connected',
      lastTestOk,
      capabilityTruth: claimedReady,
      imageProtocolSupported: true,
    });
    assert.equal(verdict.chat, false);
    assert.equal(verdict.streaming, false);
    assert.equal(verdict.verifiedTools, false);
    assert.equal(verdict.imageInput, false);
    assert.equal(verdict.formalPlan, false);
  }
});

test('unverified tools do not enable formal plans', () => {
  const verdict = deriveTrainerCapabilityVerdict({
    ...readyInput,
    capabilityTruth: { streamingReady: true, toolsReady: false },
  });

  assert.equal(verdict.chat, true);
  assert.equal(verdict.streaming, true);
  assert.equal(verdict.verifiedTools, false);
  assert.equal(verdict.imageInput, false);
  assert.equal(verdict.formalPlan, false);
});

test('verified vision and protocol attachment support enable images without tools', () => {
  const verdict = deriveTrainerCapabilityVerdict({
    ...readyInput,
    capabilityTruth: { visionReady: true, toolsReady: false },
    imageProtocolSupported: true,
  });

  assert.equal(verdict.chat, true);
  assert.equal(verdict.imageInput, true);
  assert.equal(verdict.verifiedTools, false);
  assert.equal(verdict.formalPlan, false);
});

test('verified tools enable formal plans without streaming verification when workspace is admitted', () => {
  const verdict = deriveTrainerCapabilityVerdict({
    ...readyInput,
    capabilityTruth: { streamingReady: false, toolsReady: true },
    authority: {
      authorityScope: 'trainer_sandbox',
      resourceWriteAllowed: true,
      resourceWriteEvidence: { operation: 'write', scope: 'trainer_sandbox', allowed: true },
    },
  });

  assert.equal(verdict.chat, true);
  assert.equal(verdict.streaming, false);
  assert.equal(verdict.verifiedTools, true);
  assert.equal(verdict.formalPlan, true);
  assert.equal(verdict.reason, 'ready');
});

test('formal plans still require workspace admission', () => {
  const verdict = deriveTrainerCapabilityVerdict({
    ...readyInput,
    capabilityTruth: { streamingReady: false, toolsReady: true },
  });

  assert.equal(verdict.verifiedTools, true);
  assert.equal(verdict.formalPlan, false);
  assert.equal(verdict.reason, 'workspace_not_admitted');
});

test('managed admission alone never grants resource writes, and project scope stays read-only', () => {
  assert.equal(
    deriveTrainerCapabilityVerdict({ ...readyInput, workspaceManaged: true }).resourceWrite,
    false,
  );
  assert.equal(
    deriveTrainerCapabilityVerdict({
      ...readyInput,
      authority: {
        authorityScope: 'project',
        resourceWriteAllowed: true,
        resourceWriteEvidence: { operation: 'write', scope: 'project', allowed: true },
      },
    }).resourceWrite,
    false,
  );
  assert.equal(
    deriveTrainerCapabilityVerdict({
      ...readyInput,
      authority: {
        authorityScope: 'trainer_sandbox',
        resourceWriteAllowed: true,
        resourceWriteEvidence: { operation: 'write', scope: 'trainer_sandbox', allowed: true },
      },
    }).resourceWrite,
    true,
  );
  assert.equal(
    deriveTrainerCapabilityVerdict({
      ...readyInput,
      workspaceManaged: true,
      workspaceReadOnly: true,
    }).resourceWrite,
    false,
  );
});
