'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildTransferEvidenceDraft,
  buildTransferWorkspaceOptions,
} = require('../dist/shared/src/transferEvidenceGovernance.js');

test('buildTransferWorkspaceOptions excludes current workspace, deduplicates, and prioritizes recommended target', () => {
  const options = buildTransferWorkspaceOptions({
    currentWorkspaceId: 'workspace-a',
    currentProject: {
      workspaceId: 'workspace-a',
      workspaceLabel: 'Current project',
      topFocusArea: 'FastAPI routing',
    },
    otherProjects: [
      {
        workspaceId: 'workspace-b',
        workspaceLabel: 'Billing API',
        status: 'active',
        topFocusArea: 'response_model',
        latestSummary: 'Needs transfer proof',
      },
      {
        workspaceId: 'workspace-c',
        title: 'Docs sandbox',
        status: 'blocked',
        latestSummary: 'Waiting on resource trust',
      },
      {
        workspaceId: 'workspace-b',
        workspaceLabel: 'Billing API duplicate',
        status: 'completed',
      },
    ],
    recommendedWorkspaceId: 'workspace-c',
  });

  assert.deepEqual(
    options.map((option) => option.workspaceId),
    ['workspace-c', 'workspace-b'],
  );
  assert.equal(options[0].recommended, true);
  assert.equal(options[0].label, 'Docs sandbox');
  assert.match(options[0].detail, /Waiting on resource trust/);
  assert.match(options[0].detail, /Blocked/);
  assert.equal(options[1].label, 'Billing API');
  assert.match(options[1].detail, /response_model/);
});

test('buildTransferEvidenceDraft reuses latest valid transfer target and explicit evidence', () => {
  const draft = buildTransferEvidenceDraft({
    currentWorkspaceId: 'workspace-a',
    coachFocus: 'FastAPI response models',
    dependency: {
      dependencyKey: 'fastapi',
      dependencyName: 'FastAPI',
      projectFirstCut: 'Apply response_model in the current route.',
      suggestedScenarioLab: 'Build a minimum route with response_model.',
    },
    workspaceOptions: [
      { workspaceId: 'workspace-b', label: 'Billing API' },
      { workspaceId: 'workspace-c', label: 'Docs sandbox' },
    ],
    latestTransfer: {
      targetWorkspaceId: 'workspace-c',
      verifiedResult: 'The learner applied response_model in a new docs sandbox route and verified schema output.',
    },
    latestEvidence: {
      sourceWorkspaceId: 'workspace-a',
      targetWorkspaceId: 'workspace-c',
      sourceContext: 'Original route exercise',
      targetContext: 'Docs sandbox route',
      evidenceSummary: 'Cross-project route schema proof',
      relatedApi: 'response_model',
      scenario: 'Route schema migration',
    },
    weakItem: {
      key: 'response-model-transfer',
      label: 'response_model transfer',
      nextAction: 'Repeat the route schema decision in another project.',
    },
  });

  assert.equal(draft.dependencyKey, 'fastapi');
  assert.equal(draft.sourceWorkspaceId, 'workspace-a');
  assert.equal(draft.targetWorkspaceId, 'workspace-c');
  assert.equal(draft.sourceContext, 'Original route exercise');
  assert.equal(draft.targetContext, 'Docs sandbox route');
  assert.equal(draft.verifiedResult, 'The learner applied response_model in a new docs sandbox route and verified schema output.');
  assert.equal(draft.evidenceSummary, 'Cross-project route schema proof');
  assert.equal(draft.focusItemKey, 'response-model-transfer');
  assert.equal(draft.relatedApi, 'response_model');
  assert.equal(draft.scenario, 'Route schema migration');
});

test('buildTransferEvidenceDraft falls back to first different workspace and never selects same-workspace transfer', () => {
  const draft = buildTransferEvidenceDraft({
    currentWorkspaceId: 'workspace-a',
    coachFocus: 'Depends boundary',
    returnTarget: 'Verify the dependency boundary in a different service.',
    dependency: {
      dependencyKey: 'fastapi',
      dependencyName: 'FastAPI',
      prioritySummary: 'Transfer is still unproven.',
    },
    workspaceOptions: [
      { workspaceId: 'workspace-a', label: 'Current project' },
      { workspaceId: 'workspace-b', label: 'Billing API' },
    ],
    latestTransfer: {
      targetWorkspaceId: 'workspace-a',
      verifiedResult: 'Same workspace result should not prove transfer.',
    },
  });

  assert.equal(draft.sourceWorkspaceId, 'workspace-a');
  assert.equal(draft.targetWorkspaceId, 'workspace-b');
  assert.equal(draft.sourceContext, 'FastAPI | Depends boundary');
  assert.equal(draft.targetContext, 'Verify the dependency boundary in a different service.');
  assert.equal(draft.verifiedResult, 'Same workspace result should not prove transfer.');
  assert.match(draft.evidenceSummary, /FastAPI/);
  assert.match(draft.evidenceSummary, /different service/);
});

