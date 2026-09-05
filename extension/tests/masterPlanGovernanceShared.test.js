'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  filterMasterPlanAuditItems,
  resolveMasterPlanAuditCompareState,
  resolveRecommendedProjectLane,
  summarizeMasterPlanAuditSelection,
  summarizeMasterPlanAuditItems,
  summarizeMasterPlanRollup,
} = require('../dist/shared/src/masterPlanGovernance.js');

test('summarizeMasterPlanRollup surfaces an attention state when risks and blockers exist', () => {
  const summary = summarizeMasterPlanRollup({
    activeWorkspaceCount: 2,
    blockedWorkspaceCount: 1,
    completedWorkspaceCount: 0,
    averageProgressRatio: 0.36,
    pendingEvidenceCount: 4,
    focusAreas: ['routing', 'transfer'],
    riskAreas: ['api mismatch'],
    strongestCapabilities: ['project delivery'],
    capabilityGaps: ['cross-project transfer'],
    transferStage: 'emerging',
    transferSummary: 'Patterns are stable in one project and need transfer drills.',
    transferEvidenceCount: 1,
    transferWorkspacePairCount: 1,
    transferDependencyCount: 1,
    transferSourceWorkspaceCount: 1,
    transferTargetWorkspaceCount: 1,
    transferEvidenceSignals: ['workspace-a->workspace-b:fastapi'],
    evaluationSummary: 'One lane is blocked and still needs explicit recovery.',
    elasticityScore: 0.31,
    elasticityStage: 'fragile',
    elasticitySummary: 'Elasticity is fragile because one lane is blocked.',
    migrationEvidence: ['trainer-a: stable transfer signal'],
    migrationBlockers: ['trainer-b: scope widened too far'],
    recommendedWorkspaceId: 'workspace-a',
    recommendedWorkspaceLabel: 'trainer-a',
    recommendedFocusArea: 'routing',
    recommendedReason: 'Resume trainer-a because it carries the current routing risk.',
  });

  assert.equal(summary.health, 'attention');
  assert.equal(summary.activeWorkspaceCount, 2);
  assert.equal(summary.blockedWorkspaceCount, 1);
  assert.equal(summary.pendingEvidenceCount, 4);
  assert.deepEqual(summary.riskAreas, ['api mismatch']);
  assert.deepEqual(summary.capabilityGaps, ['cross-project transfer']);
  assert.equal(summary.transferEvidenceCount, 1);
  assert.equal(summary.transferWorkspacePairCount, 1);
  assert.equal(summary.transferDependencyCount, 1);
  assert.equal(summary.transferSourceWorkspaceCount, 1);
  assert.equal(summary.transferTargetWorkspaceCount, 1);
  assert.deepEqual(summary.transferEvidenceSignals, ['workspace-a->workspace-b:fastapi']);
  assert.equal(summary.elasticityStage, 'fragile');
  assert.equal(summary.elasticityScore, 0.31);
  assert.deepEqual(summary.migrationEvidence, ['trainer-a: stable transfer signal']);
  assert.deepEqual(summary.migrationBlockers, ['trainer-b: scope widened too far']);
  assert.equal(summary.recommendedWorkspaceId, 'workspace-a');
});

test('summarizeMasterPlanRollup surfaces a strong state when progress is stable and gaps are clear', () => {
  const summary = summarizeMasterPlanRollup({
    activeWorkspaceCount: 1,
    blockedWorkspaceCount: 0,
    completedWorkspaceCount: 2,
    averageProgressRatio: 0.82,
    pendingEvidenceCount: 0,
    strongestCapabilities: ['delivery', 'testing'],
    focusAreas: ['testing'],
    capabilityGaps: [],
    riskAreas: [],
    transferStage: 'portable',
    transferEvidenceCount: 2,
    transferWorkspacePairCount: 2,
    transferDependencyCount: 2,
    transferSourceWorkspaceCount: 2,
    transferTargetWorkspaceCount: 2,
    transferEvidenceSignals: ['workspace-a->workspace-b:fastapi', 'workspace-b->workspace-c:react'],
    elasticityScore: 0.84,
    elasticityStage: 'adaptive',
    migrationEvidence: ['trainer-a: portable transfer signal'],
    migrationBlockers: [],
  });

  assert.equal(summary.health, 'strong');
  assert.deepEqual(summary.strongestCapabilities, ['delivery', 'testing']);
  assert.equal(summary.transferEvidenceCount, 2);
  assert.equal(summary.transferWorkspacePairCount, 2);
  assert.equal(summary.transferDependencyCount, 2);
  assert.deepEqual(summary.transferEvidenceSignals, [
    'workspace-a->workspace-b:fastapi',
    'workspace-b->workspace-c:react',
  ]);
  assert.equal(summary.elasticityStage, 'adaptive');
});

test('summarizeMasterPlanRollup treats repeated weaknesses as first-class attention evidence', () => {
  const summary = summarizeMasterPlanRollup({
    activeWorkspaceCount: 2,
    blockedWorkspaceCount: 0,
    completedWorkspaceCount: 1,
    averageProgressRatio: 0.86,
    pendingEvidenceCount: 0,
    riskAreas: [],
    capabilityGaps: [],
    repeatedWeaknessCount: 1,
    repeatedWeaknessWorkspaceCount: 2,
    repeatedWeaknessSeverity: 3,
    repeatedWeaknesses: [
      'Scope control: repeats across 2 workspace(s); recurrence 2, severity 3.',
    ],
    repeatedWeaknessSignals: ['scope control|workspaces=2|recurrence=2|severity=3'],
    transferStage: 'portable',
    transferEvidenceCount: 2,
    transferWorkspacePairCount: 2,
    transferDependencyCount: 2,
    transferSourceWorkspaceCount: 2,
    transferTargetWorkspaceCount: 2,
    elasticityScore: 0.84,
    elasticityStage: 'adaptive',
    migrationBlockers: [],
  });

  assert.equal(summary.health, 'attention');
  assert.equal(summary.repeatedWeaknessCount, 1);
  assert.equal(summary.repeatedWeaknessWorkspaceCount, 2);
  assert.equal(summary.repeatedWeaknessSeverity, 3);
  assert.deepEqual(summary.repeatedWeaknessSignals, [
    'scope control|workspaces=2|recurrence=2|severity=3',
  ]);
});

test('resolveRecommendedProjectLane finds the recommended lane from rollup guidance', () => {
  const lane = resolveRecommendedProjectLane(
    [
      { workspaceId: 'workspace-a', workspaceLabel: 'trainer-a', workspacePath: 'H:\\trainer-a' },
      { workspaceId: 'workspace-b', workspaceLabel: 'trainer-b', workspacePath: 'H:\\trainer-b' },
    ],
    {
      recommendedWorkspaceId: 'workspace-b',
      recommendedWorkspaceLabel: 'trainer-b',
      recommendedFocusArea: 'transfer',
      recommendedReason: 'Use trainer-b for transfer drills.',
    },
  );

  assert.equal(lane.workspaceId, 'workspace-b');
  assert.equal(lane.workspaceLabel, 'trainer-b');
});

test('summarizeMasterPlanAuditItems merges history and lane governance into one audit summary', () => {
  const summary = summarizeMasterPlanAuditItems([
    {
      id: 'formal-1',
      source: 'formal_history',
      workspaceId: 'workspace-a',
      level: 'master',
      diffSummary: 'Updated long-term goals',
      changedFields: ['longTermGoals'],
      compareActive: true,
    },
    {
      id: 'subplan-1',
      source: 'project_subplan_history',
      workspaceId: 'workspace-a',
      level: 'project',
      pendingEvidenceCount: 2,
      diffSummary: 'Adjusted current step',
      changedFields: ['currentStep'],
    },
    {
      id: 'lane-1',
      source: 'project_lane',
      workspaceId: 'workspace-b',
      status: 'blocked',
      pendingEvidenceCount: 1,
      focusAreas: ['routing'],
      linkedLongTermGoals: ['ship coach-only workflow'],
      capabilityContributions: ['project delivery'],
      transferSignal: 'emerging',
    },
    {
      id: 'lane-2',
      source: 'project_lane',
      workspaceId: 'workspace-c',
      status: 'active',
      focusAreas: ['testing'],
      capabilityContributions: ['test hardening'],
      transferSignal: 'stable',
    },
  ]);

  assert.equal(summary.totalItems, 4);
  assert.equal(summary.formalHistoryCount, 1);
  assert.equal(summary.subplanHistoryCount, 1);
  assert.equal(summary.laneCount, 2);
  assert.equal(summary.workspaceCount, 3);
  assert.equal(summary.pendingEvidenceCount, 3);
  assert.equal(summary.diffItemCount, 2);
  assert.equal(summary.compareFocusCount, 1);
  assert.equal(summary.blockedLaneCount, 1);
  assert.equal(summary.activeLaneCount, 1);
  assert.deepEqual(summary.levels, ['master', 'project']);
  assert.deepEqual(summary.statuses, ['active', 'blocked']);
  assert.deepEqual(summary.focusAreas, ['routing', 'testing']);
  assert.deepEqual(summary.linkedLongTermGoals, ['ship coach-only workflow']);
  assert.deepEqual(summary.capabilityContributions, ['project delivery', 'test hardening']);
  assert.deepEqual(summary.transferSignals, ['emerging', 'stable']);
});

test('filterMasterPlanAuditItems filters by source, status, query, and diff mode', () => {
  const items = [
    {
      id: 'formal-1',
      source: 'formal_history',
      workspaceId: 'workspace-a',
      title: 'Formal restore',
      diffSummary: 'Changed title',
    },
    {
      id: 'subplan-1',
      source: 'project_subplan_history',
      workspaceId: 'workspace-a',
      title: 'Subplan sync',
    },
    {
      id: 'lane-1',
      source: 'project_lane',
      workspaceId: 'workspace-b',
      title: 'Lane B',
      status: 'blocked',
      focusAreas: ['routing'],
    },
  ];

  assert.deepEqual(
    filterMasterPlanAuditItems(items, {
      source: 'project_lane',
      status: 'blocked',
      query: 'routing',
      diffMode: 'all',
    }).map((item) => item.id),
    ['lane-1'],
  );
  assert.deepEqual(
    filterMasterPlanAuditItems(items, {
      source: 'all',
      status: 'all',
      query: '',
      diffMode: 'with_diff',
    }).map((item) => item.id),
    ['formal-1'],
  );
});

test('summarizeMasterPlanAuditSelection and compare state reflect selected and focused audit items', () => {
  const items = [
    {
      id: 'formal-1',
      source: 'formal_history',
      workspaceId: 'workspace-a',
      diffSummary: 'Changed title',
      focusAreas: ['planning'],
      compareActive: true,
    },
    {
      id: 'lane-1',
      source: 'project_lane',
      workspaceId: 'workspace-b',
      status: 'active',
      pendingEvidenceCount: 2,
      focusAreas: ['routing'],
    },
  ];

  const selection = summarizeMasterPlanAuditSelection(new Set(['formal-1']), items);
  assert.equal(selection.totalSelected, 1);
  assert.equal(selection.selectedWithDiff, 1);
  assert.equal(selection.workspaceCount, 1);
  assert.deepEqual(selection.sources, ['formal_history']);
  assert.deepEqual(selection.focusAreas, ['planning']);

  const compareState = resolveMasterPlanAuditCompareState(items, new Set(), 'lane-1');
  assert.equal(compareState.mode, 'compare_focus');
  assert.equal(compareState.candidateId, 'lane-1');
});

test('resolveMasterPlanAuditCompareState prefers a single selected item over an existing compare focus', () => {
  const items = [
    {
      id: 'formal-1',
      source: 'formal_history',
      workspaceId: 'workspace-a',
      title: 'Formal restore',
      diffSummary: 'Changed title',
    },
    {
      id: 'lane-1',
      source: 'project_lane',
      workspaceId: 'workspace-b',
      title: 'Lane B',
      status: 'blocked',
    },
  ];

  const compareState = resolveMasterPlanAuditCompareState(items, new Set(['formal-1']), 'lane-1');
  assert.equal(compareState.mode, 'selected_single');
  assert.equal(compareState.candidateId, 'formal-1');
  assert.equal(compareState.selectedCount, 1);
});
