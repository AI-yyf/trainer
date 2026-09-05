'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  deriveCoachOrientation,
  normalizeCoachOrientationRecord,
} = require('../dist/shared/src/coachOrientationGovernance.js');

test('provider and sidecar facts beat plan or conversation theater', () => {
  const planReady = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    conversationCount: 2,
    planCurrentStep: 'Ship the parser guard',
    language: 'en-US',
  });
  assert.equal(planReady.objectKind, 'plan');
  assert.equal(planReady.primaryAction, 'open_plan');

  const needsSetup = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: false,
    conversationCount: 2,
    planCurrentStep: 'Ship the parser guard',
    language: 'en-US',
  });
  assert.equal(needsSetup.objectKind, 'provider');
  assert.equal(needsSetup.state, 'needs_setup');
  assert.equal(needsSetup.primaryAction, 'open_settings');

  const sidecarDown = deriveCoachOrientation({
    sidecarStatus: 'error',
    hasProviderModel: true,
    conversationCount: 2,
    language: 'en-US',
  });
  assert.equal(sidecarDown.objectKind, 'workspace');
  assert.equal(sidecarDown.state, 'blocked');
});

test('training reliability and handoff drive the single primary action', () => {
  const waiting = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    trainingReliabilityPhase: 'executing',
    selectedCardTitle: 'Parser boundary',
    planCurrentStep: 'Ignore this plan step',
    language: 'en-US',
  });
  assert.equal(waiting.objectKind, 'training');
  assert.equal(waiting.state, 'waiting');
  assert.equal(waiting.primaryAction, 'wait');
  assert.equal(waiting.objectLabel, 'Parser boundary');

  const failed = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    trainingReliabilityPhase: 'failed',
    selectedCardTitle: 'Parser boundary',
    language: 'en-US',
  });
  assert.equal(failed.state, 'blocked');
  assert.equal(failed.primaryAction, 'retry');

  const returning = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    trainingLearningPhase: 'return',
    trainingHandoffStatus: 'ready_to_return',
    selectedCardTitle: 'Parser boundary',
    language: 'zh-CN',
  });
  assert.equal(returning.objectKind, 'training');
  assert.equal(returning.primaryAction, 'open_training');
});

test('operation reliability keeps the rail working and leftover plan unpainted', () => {
  const pending = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    operationReliabilityPhase: 'pending',
    planCurrentStep: 'Keep leftover stage',
    language: 'en-US',
  });
  assert.equal(pending.state, 'working');
  assert.notEqual(pending.state, 'ready');
  assert.notEqual(pending.objectKind, 'plan');

  const failed = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    operationReliabilityPhase: 'acked',
    operationReliabilityOutcome: 'failure',
    planCurrentStep: 'Keep leftover stage',
    language: 'en-US',
  });
  assert.equal(failed.objectKind, 'provider');
  assert.equal(failed.state, 'blocked');
  assert.equal(failed.primaryAction, 'open_settings');
  assert.notEqual(failed.objectKind, 'plan');
  assert.notEqual(failed.state, 'ready');
});

test('ready provider uses first-look next without inventing a plan', () => {
  const firstLookNext = 'Add a token expiry test';
  const firstLookWhy = 'auth.py already checks expired tokens.';
  const ready = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    conversationCount: 0,
    firstLookRecommendedNext: firstLookNext,
    firstLookWhy,
    language: 'en-US',
  });
  assert.equal(ready.objectKind, 'conversation');
  assert.equal(ready.primaryAction, 'compose');
  assert.equal(ready.nextStep, firstLookNext);
  assert.equal(ready.why, firstLookWhy);
  assert.notEqual(ready.objectKind, 'provider');
  assert.notEqual(ready.primaryAction, 'open_plan');
  assert.equal(ready.nextStep.includes('Save and test a model connection'), false);

  const needsSetup = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: false,
    conversationCount: 0,
    firstLookRecommendedNext: firstLookNext,
    firstLookWhy,
    language: 'en-US',
  });
  assert.equal(needsSetup.objectKind, 'provider');
  assert.equal(needsSetup.primaryAction, 'open_settings');
  assert.equal(needsSetup.nextStep, 'Save and test a model connection first.');

  const returning = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    trainingLearningPhase: 'return',
    trainingHandoffStatus: 'ready_to_return',
    selectedCardTitle: 'Keep one auth check',
    firstLookRecommendedNext: firstLookNext,
    language: 'en-US',
  });
  assert.equal(returning.objectKind, 'training');
  assert.equal(returning.primaryAction, 'open_training');
  assert.notEqual(returning.nextStep, firstLookNext);

  const waiting = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    trainingReliabilityPhase: 'executing',
    selectedCardTitle: 'Keep one auth check',
    firstLookRecommendedNext: firstLookNext,
    language: 'en-US',
  });
  assert.equal(waiting.objectKind, 'training');
  assert.equal(waiting.primaryAction, 'wait');
  assert.notEqual(waiting.nextStep, firstLookNext);

  const livePlan = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    planCurrentStep: 'Ship the parser guard',
    firstLookRecommendedNext: firstLookNext,
    language: 'en-US',
  });
  assert.equal(livePlan.objectKind, 'plan');
  assert.equal(livePlan.primaryAction, 'open_plan');
  assert.notEqual(livePlan.nextStep, firstLookNext);
});

test('incomplete records are not treated as current truth', () => {
  assert.equal(
    normalizeCoachOrientationRecord({ objectKind: 'conversation', state: 'ready' }),
    undefined,
  );
  const empty = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    conversationCount: 0,
    language: 'en-US',
  });
  assert.equal(empty.objectKind, 'conversation');
  assert.equal(empty.primaryAction, 'compose');
  assert.ok(normalizeCoachOrientationRecord(empty));
});

test('bound live plan without leftover card is the Coach current object', () => {
  const generatedStep = 'Inspect one refresh boundary';
  const orientation = deriveCoachOrientation({
    sidecarStatus: 'ready',
    hasProviderModel: true,
    planCurrentStep: generatedStep,
    planWhyNow: 'Refresh ownership still fails closed.',
    trainingLearningPhase: 'return',
    trainingHandoffStatus: 'ready_to_return',
    selectedCardTitle: '',
    language: 'en-US',
  });
  assert.equal(orientation.objectKind, 'plan');
  assert.equal(orientation.objectLabel, generatedStep);
  assert.notEqual(orientation.objectKind, 'training');
  assert.notEqual(orientation.objectLabel, 'Keep one auth check');
});
