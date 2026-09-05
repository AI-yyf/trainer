'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  filterProjectLaneItems,
  resolveProjectLaneCompareState,
  summarizeProjectLaneSelection,
  summarizeProjectLaneItems,
} = require('../dist/shared/src/projectLaneGovernance.js');

const laneFixtures = [
  {
    workspaceId: 'project-a',
    workspaceLabel: 'Project A',
    workspacePath: 'H:\\project-a',
    resumeSessionId: 'session-a',
    status: 'active',
    progressRatio: 0.42,
    pendingEvidenceCount: 2,
    topFocusArea: 'routing',
    latestSummary: 'Stabilize route verification.',
    capabilityContributions: ['routing discipline'],
  },
  {
    workspaceId: 'project-b',
    workspaceLabel: 'Project B',
    workspacePath: 'H:\\project-b',
    status: 'blocked',
    progressRatio: 0.18,
    pendingEvidenceCount: 3,
    topFocusArea: 'dependency mastery',
    latestSummary: 'Blocked on API transfer.',
    riskSignals: ['api mismatch'],
  },
  {
    workspaceId: 'project-c',
    workspaceLabel: 'Project C',
    workspacePath: 'H:\\project-c',
    status: 'completed',
    progressRatio: 0.91,
    pendingEvidenceCount: 0,
    topFocusArea: 'testing',
    latestSummary: 'Ready for cross-project transfer.',
    transferSignal: 'portable',
  },
];

test('filterProjectLaneItems combines status, progress, and query filters', () => {
  const filtered = filterProjectLaneItems(laneFixtures, {
    status: 'blocked',
    progress: 'attention',
    query: 'transfer',
  });

  assert.deepEqual(
    filtered.map((item) => item.workspaceId),
    ['project-b'],
  );
});

test('summarizeProjectLaneItems reports visible cross-project lane state', () => {
  const summary = summarizeProjectLaneItems(laneFixtures, 'project-a');

  assert.equal(summary.totalVisible, 3);
  assert.equal(summary.activeCount, 1);
  assert.equal(summary.blockedCount, 1);
  assert.equal(summary.resumableCount, 3);
  assert.equal(summary.pendingEvidenceCount, 5);
  assert.deepEqual(summary.focusAreas, ['dependency mastery', 'routing', 'testing']);
});

test('summarizeProjectLaneSelection reports selection-level governance state', () => {
  const summary = summarizeProjectLaneSelection(
    new Set(['project-a', 'project-c']),
    laneFixtures,
    'project-a',
  );

  assert.equal(summary.totalSelected, 2);
  assert.equal(summary.resumableCount, 2);
  assert.equal(summary.pendingEvidenceCount, 2);
  assert.deepEqual(summary.statuses, ['active', 'completed']);
  assert.deepEqual(summary.focusAreas, ['routing', 'testing']);
  assert.deepEqual(summary.transferSignals, ['portable']);
});

test('resolveProjectLaneCompareState prefers single selection, then compare focus', () => {
  const selected = resolveProjectLaneCompareState(
    laneFixtures,
    new Set(['project-b']),
    'project-c',
  );
  assert.equal(selected.mode, 'selected_single');
  assert.equal(selected.candidateId, 'project-b');

  const compareFocus = resolveProjectLaneCompareState(
    laneFixtures,
    new Set(),
    'project-c',
  );
  assert.equal(compareFocus.mode, 'compare_focus');
  assert.equal(compareFocus.candidateId, 'project-c');

  const blocked = resolveProjectLaneCompareState(
    laneFixtures,
    new Set(['project-a', 'project-b']),
    undefined,
  );
  assert.equal(blocked.mode, 'selection_blocked');
  assert.equal(blocked.selectedCount, 2);
});
