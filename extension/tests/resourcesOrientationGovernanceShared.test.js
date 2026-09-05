'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  deriveResourcesOrientation,
  resolveResourcesBindingIds,
} = require('../dist/shared/src/resourcesOrientationGovernance.js');

test('material recommendation is honest and fail-closed', () => {
  const simpler = deriveResourcesOrientation({
    resourceCount: 2,
    language: 'en-US',
    materialRecommendation: 'simpler',
    transferSceneCount: 1,
  });
  assert.match(simpler.nextStep, /easier recovery|this project/i);

  const current = deriveResourcesOrientation({
    resourceCount: 2,
    language: 'en-US',
    materialRecommendation: 'current',
    transferSceneCount: 1,
  });
  assert.match(current.nextStep, /current-scene|this project's/i);

  const blocked = deriveResourcesOrientation({
    resourceCount: 2,
    language: 'en-US',
    materialRecommendation: 'transfer',
    transferSceneCount: 1,
    transferState: 'awaiting_second_scene',
  });
  assert.match(blocked.nextStep, /one scene|cannot pick/i);
  assert.doesNotMatch(blocked.nextStep, /eligible/i);

  const allowed = deriveResourcesOrientation({
    resourceCount: 2,
    language: 'en-US',
    materialRecommendation: 'transfer',
    transferSceneCount: 2,
    transferState: 'transferable',
  });
  assert.match(allowed.nextStep, /second scene|eligible/i);
});

test('empty library is not ready', () => {
  const orientation = deriveResourcesOrientation({
    resourceCount: 0,
    selectedResourceTitle: 'Theater leftover.pdf',
    indexState: 'indexed',
    boundTrainingCardId: 'invented-card',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'needs_setup');
  assert.equal(orientation.primaryAction, 'import_resource');
  assert.notEqual(orientation.objectLabel, 'Theater leftover.pdf');
  assert.match(orientation.why, /empty/i);
});

test('failed index is not success', () => {
  const orientation = deriveResourcesOrientation({
    resourceCount: 2,
    selectedResourceId: 'res-1',
    selectedResourceTitle: 'Broken notes',
    indexState: 'failed',
    resourceStatus: 'attention',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'blocked');
  assert.equal(orientation.primaryAction, 'retry_index');
  assert.match(orientation.why, /failed/i);
  assert.notEqual(orientation.state, 'ready');
});

test('attention status is treated as failed index, not ready', () => {
  const orientation = deriveResourcesOrientation({
    resourceCount: 1,
    selectedResourceId: 'res-2',
    selectedResourceTitle: 'Needs attention',
    resourceStatus: 'attention',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'blocked');
  assert.equal(orientation.primaryAction, 'retry_index');
});

test('bindings do not invent plan or training links', () => {
  const invented = resolveResourcesBindingIds({
    selectedResourceId: 'res-1',
    selectedCitationId: 'cite-1',
    planEvidenceBinding: undefined,
    trainingTargetId: undefined,
    trainingTargetKind: 'training_card',
    trainingSourceChain: ['other-resource'],
  });
  assert.equal(invented.boundPlanId, undefined);
  assert.equal(invented.boundTrainingCardId, undefined);

  const orientation = deriveResourcesOrientation({
    resourceCount: 1,
    selectedResourceId: 'res-1',
    selectedResourceTitle: 'Indexed notes',
    indexState: 'indexed',
    resourceStatus: 'ready',
    trustState: 'trusted',
    freshness: 'fresh',
    hasPreview: true,
    language: 'en-US',
  });
  assert.equal(orientation.primaryAction, 'preview_resource');
  assert.notEqual(orientation.primaryAction, 'open_training');
  assert.notEqual(orientation.primaryAction, 'open_plan');
  assert.doesNotMatch(orientation.why, /Bound to/);
});

test('real plan and training bindings are used only when they name the resource', () => {
  const leftover = resolveResourcesBindingIds({
    selectedResourceId: 'ev-old-auth',
    selectedCitationId: 'ev-old-auth',
    planEvidenceBinding: 'ev-old-auth',
    livePendingEvidenceIds: [],
    recoveredRuntime: true,
    currentStep: 'Add a token expiry test',
  });
  assert.equal(leftover.boundPlanId, undefined);

  const planBound = resolveResourcesBindingIds({
    selectedResourceId: 'res-1',
    selectedCitationId: 'cite-1',
    planEvidenceBinding: 'cite-1',
    livePendingEvidenceIds: ['cite-1'],
    recoveredRuntime: true,
    currentStep: 'Keep one auth check',
  });
  assert.equal(planBound.boundPlanId, 'cite-1');

  const trainingBound = resolveResourcesBindingIds({
    selectedResourceId: 'res-1',
    trainingTargetId: 'card-9',
    trainingTargetKind: 'training_card',
    trainingSourceChain: ['res-1'],
  });
  assert.equal(trainingBound.boundTrainingCardId, 'card-9');

  const orientation = deriveResourcesOrientation({
    resourceCount: 1,
    selectedResourceId: 'res-1',
    selectedResourceTitle: 'Bound notes',
    indexState: 'indexed',
    boundPlanId: 'cite-1',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'ready');
  assert.equal(orientation.primaryAction, 'open_plan');
});

test('leftover A library dump is not the current B object', () => {
  const orientation = deriveResourcesOrientation({
    resourceCount: 0,
    selectedResourceTitle: 'Keep the leftover A notes',
    searchQuery: 'parser',
    searchHitCount: 4,
    searchWorkspaceId: 'workspace-a',
    currentWorkspaceId: 'workspace-b',
    language: 'en-US',
  });
  assert.equal(orientation.state, 'needs_setup');
  assert.equal(orientation.primaryAction, 'import_resource');
  assert.notEqual(orientation.objectLabel, 'Keep the leftover A notes');
  assert.doesNotMatch(orientation.why, /4 hit/);
  assert.match(orientation.why, /empty/i);
});

test('search leftover from another workspace is ignored', () => {
  const orientation = deriveResourcesOrientation({
    resourceCount: 1,
    searchQuery: 'parser',
    searchHitCount: 4,
    searchWorkspaceId: 'workspace-a',
    currentWorkspaceId: 'workspace-b',
    language: 'en-US',
  });
  assert.equal(orientation.primaryAction, 'select_resource');
  assert.doesNotMatch(orientation.why, /4 hit/);
});

test('untrusted source stays blocked and is not a training binding', () => {
  const orientation = deriveResourcesOrientation({
    resourceCount: 1,
    selectedResourceId: 'res-bad',
    selectedResourceTitle: 'Blocked page',
    indexState: 'indexed',
    qualityFlags: ['fetch_failed'],
    boundTrainingCardId: undefined,
    language: 'en-US',
  });
  assert.equal(orientation.state, 'blocked');
  assert.equal(orientation.primaryAction, 'retry_index');
});
