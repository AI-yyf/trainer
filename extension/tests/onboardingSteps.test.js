'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const onboardingModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'onboarding.js',
);

const { deriveOnboardingSteps, isOnboardingStepDone, ONBOARDING_STEP_ORDER } = require(
  onboardingModulePath,
);

test('onboarding walks workspace root → trust → model and completes only when all done', () => {
  assert.deepEqual(ONBOARDING_STEP_ORDER, ['workspace_root', 'trust_window', 'connect_model']);

  const coldStart = deriveOnboardingSteps({});
  assert.equal(coldStart.complete, false);
  assert.equal(coldStart.activeStepId, 'workspace_root');
  assert.deepEqual(
    coldStart.steps.map((step) => [step.id, step.status]),
    [
      ['workspace_root', 'active'],
      ['trust_window', 'pending'],
      ['connect_model', 'pending'],
    ],
  );

  const afterRoot = deriveOnboardingSteps({ workspaceAdmissionStatus: 'project-found' });
  assert.equal(afterRoot.activeStepId, 'trust_window');

  const afterTrust = deriveOnboardingSteps({
    workspaceAdmissionStatus: 'managed',
    workspaceTrustState: 'trusted',
  });
  assert.equal(afterTrust.activeStepId, 'connect_model');

  const complete = deriveOnboardingSteps({
    workspaceAdmissionStatus: 'managed',
    workspaceTrustState: 'trusted',
    providerConfigured: true,
    providerApiKeyConfigured: true,
    providerSendBlocked: false,
  });
  assert.equal(complete.complete, true);
  assert.equal(complete.activeStepId, undefined);
  assert.ok(complete.steps.every((step) => step.status === 'done'));
});

test('workspace root step treats every non-missing admission status as done', () => {
  assert.equal(isOnboardingStepDone('workspace_root', {}), false);
  assert.equal(isOnboardingStepDone('workspace_root', { workspaceAdmissionStatus: 'root-missing' }), false);
  for (const status of ['project-found', 'managed', 'browse', 'ignored']) {
    assert.equal(isOnboardingStepDone('workspace_root', { workspaceAdmissionStatus: status }), true);
  }
});

test('trust step only accepts trusted or remote states', () => {
  assert.equal(isOnboardingStepDone('trust_window', {}), false);
  assert.equal(isOnboardingStepDone('trust_window', { workspaceTrustState: 'unknown' }), false);
  assert.equal(isOnboardingStepDone('trust_window', { workspaceTrustState: 'untrusted' }), false);
  assert.equal(isOnboardingStepDone('trust_window', { workspaceTrustState: 'trusted' }), true);
  assert.equal(isOnboardingStepDone('trust_window', { workspaceTrustState: 'remote' }), true);
});

test('model step requires a configured, keyed, unblocked provider', () => {
  assert.equal(isOnboardingStepDone('connect_model', {}), false);
  assert.equal(
    isOnboardingStepDone('connect_model', { providerConfigured: true }),
    false,
    'configured without key must stay pending',
  );
  assert.equal(
    isOnboardingStepDone('connect_model', {
      providerConfigured: true,
      providerApiKeyConfigured: true,
      providerSendBlocked: true,
    }),
    false,
    'blocked send must stay pending',
  );
  assert.equal(
    isOnboardingStepDone('connect_model', {
      providerConfigured: true,
      providerApiKeyConfigured: true,
      providerSendBlocked: false,
    }),
    true,
  );
});
