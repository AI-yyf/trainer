'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  composePlanEvidenceCandidate,
  filterPlanEvidenceItems,
  filterPlanHistoryItems,
  rankPlanHistoryMatches,
  resolveGovernedPlanActionGuard,
  resolveRestoreOrchestrationItems,
  resolvePlanChangeFields,
  resolvePlanEvidenceAdoptionState,
  resolvePlanHistoryCompareState,
  summarizeRestoreOrchestrationItems,
  summarizePlanChangeAlignment,
  summarizePlanEvidenceSelection,
  summarizePlanHistorySelection,
} = require('../dist/shared/src/planGovernance.js');

const evidenceFixtures = [
  {
    id: 'plan-evidence-1',
    title: 'Routing verification',
    summary: 'Keep the routing slice narrow.',
    rationale: 'The learner still widens scope.',
    focusArea: 'routing',
    source: 'learning_signal',
    reviewState: 'captured',
    diffSummary: 'current step -> verify route wiring first',
    changedFields: ['current_step', 'verify_method'],
  },
  {
    id: 'plan-evidence-2',
    title: 'Architecture drift',
    summary: 'Delay broader architecture churn.',
    rationale: 'The current slice still needs proof.',
    focusArea: 'architecture',
    source: 'evaluation',
    reviewState: 'queued',
    changedFields: [],
  },
  {
    id: 'plan-evidence-3',
    title: 'Routing summary',
    summary: 'Keep the summary tied to routing.',
    rationale: 'A second routing clue should stay visible.',
    focusArea: 'routing',
    source: 'evaluation',
    reviewState: 'reviewed',
    diffSummary: 'summary -> narrow routing verification first',
    changedFields: ['summary'],
  },
];

const historyFixtures = [
  {
    id: 'plan-history-1',
    title: 'Plan updated',
    detail: 'Tightened the routing verification slice.',
    note: 'Stay narrow before widening.',
    level: 'project',
    action: 'plan_update',
    diffSummary: 'current step -> verify route wiring first',
    changedFields: ['current_step', 'verify_method'],
  },
  {
    id: 'plan-history-2',
    title: 'Master frozen',
    detail: 'Pause cross-project formal updates.',
    note: 'Wait for stronger transfer evidence.',
    level: 'master',
    action: 'freeze_master',
    changedFields: [],
  },
  {
    id: 'plan-history-3',
    title: 'Evidence adopted',
    detail: 'Adopted the routing checkpoint evidence.',
    note: 'Routing evidence is now formalized.',
    level: 'project',
    action: 'evidence_adopt',
    diffSummary: 'summary -> narrow routing verification first',
    changedFields: ['summary'],
  },
];

test('filterPlanEvidenceItems combines source, focus, query, and diff filters', () => {
  const filtered = filterPlanEvidenceItems(evidenceFixtures, {
    source: 'evaluation',
    reviewState: 'reviewed',
    focusArea: 'routing',
    query: 'summary',
    diffMode: 'with_diff',
  });

  assert.deepEqual(
    filtered.map((item) => item.id),
    ['plan-evidence-3'],
  );
});

test('summarizePlanEvidenceSelection reports selection breadth', () => {
  const summary = summarizePlanEvidenceSelection(
    new Set(['plan-evidence-1', 'plan-evidence-2']),
    evidenceFixtures,
  );

  assert.equal(summary.totalSelected, 2);
  assert.equal(summary.selectedWithDiff, 1);
  assert.equal(summary.selectedCaptured, 1);
  assert.equal(summary.selectedQueued, 1);
  assert.equal(summary.selectedReviewed, 0);
  assert.equal(summary.selectedStale, 0);
  assert.deepEqual(summary.focusAreas, ['architecture', 'routing']);
});

test('filterPlanEvidenceItems can isolate queued review-state evidence', () => {
  const filtered = filterPlanEvidenceItems(evidenceFixtures, {
    source: 'all',
    reviewState: 'queued',
    focusArea: 'all',
    query: '',
    diffMode: 'all',
  });

  assert.deepEqual(
    filtered.map((item) => item.id),
    ['plan-evidence-2'],
  );
});

test('resolvePlanEvidenceAdoptionState prefers the single selected evidence item', () => {
  const state = resolvePlanEvidenceAdoptionState(
    evidenceFixtures,
    new Set(['plan-evidence-2']),
    'plan-evidence-1',
  );

  assert.equal(state.adoptable, false);
  assert.equal(state.mode, 'review_blocked');
  assert.equal(state.candidateId, 'plan-evidence-2');
});

test('resolvePlanEvidenceAdoptionState falls back to compare focus when nothing is selected', () => {
  const state = resolvePlanEvidenceAdoptionState(
    evidenceFixtures,
    new Set(),
    'plan-evidence-3',
  );

  assert.equal(state.adoptable, true);
  assert.equal(state.mode, 'compare_focus');
  assert.equal(state.candidateId, 'plan-evidence-3');
});

test('resolvePlanEvidenceAdoptionState blocks unreviewed captured evidence from formal adoption', () => {
  const state = resolvePlanEvidenceAdoptionState(
    evidenceFixtures,
    new Set(['plan-evidence-1']),
    'plan-evidence-1',
  );

  assert.equal(state.adoptable, false);
  assert.equal(state.mode, 'review_blocked');
  assert.equal(state.candidateId, 'plan-evidence-1');
  assert.match(state.reason, /captured/i);
});

test('resolvePlanEvidenceAdoptionState blocks formal adoption when multiple evidence items are selected', () => {
  const reviewedFixtures = [
    {
      ...evidenceFixtures[0],
      reviewState: 'reviewed',
      beforeSnapshot: {
        title: 'Coach-first trainer',
        current_step: 'Rebuild broadly.',
        summary: 'Keep moving forward.',
      },
      afterSnapshot: {
        title: 'Coach-first trainer',
        current_step: 'Verify one route branch first.',
        summary: 'Keep moving forward.',
      },
    },
    {
      ...evidenceFixtures[2],
      beforeSnapshot: {
        title: 'Coach-first trainer',
        current_step: 'Rebuild broadly.',
        summary: 'Keep moving forward.',
      },
      afterSnapshot: {
        title: 'Coach-first trainer',
        current_step: 'Verify one route branch first.',
        summary: 'Keep the routing summary narrow.',
      },
    },
  ];
  const state = resolvePlanEvidenceAdoptionState(
    reviewedFixtures,
    new Set(['plan-evidence-1', 'plan-evidence-3']),
    'plan-evidence-1',
  );

  assert.equal(state.adoptable, true);
  assert.equal(state.mode, 'selected_multi');
  assert.equal(state.selectedCount, 2);
  assert.deepEqual(state.candidateEvidenceIds, ['plan-evidence-1', 'plan-evidence-3']);
  assert.deepEqual(state.candidate?.changedFields, ['current_step', 'summary', 'verify_method']);
});

test('composePlanEvidenceCandidate reports conflicting fields across selected evidence', () => {
  const candidate = composePlanEvidenceCandidate([
    {
      id: 'evidence-a',
      summary: 'First candidate',
      reviewState: 'reviewed',
      beforeSnapshot: {
        current_step: 'Rebuild broadly.',
      },
      afterSnapshot: {
        current_step: 'Verify one route branch first.',
      },
    },
    {
      id: 'evidence-b',
      summary: 'Second candidate',
      reviewState: 'reviewed',
      beforeSnapshot: {
        current_step: 'Rebuild broadly.',
      },
      afterSnapshot: {
        current_step: 'Refactor the whole planner loop.',
      },
    },
  ]);

  assert.ok(candidate);
  assert.deepEqual(candidate.conflictFields, ['current_step']);
});

test('resolvePlanEvidenceAdoptionState blocks multi-select adoption on conflicting fields', () => {
  const state = resolvePlanEvidenceAdoptionState(
    [
      {
        id: 'evidence-a',
        summary: 'First candidate',
        reviewState: 'reviewed',
        beforeSnapshot: {
          current_step: 'Rebuild broadly.',
        },
        afterSnapshot: {
          current_step: 'Verify one route branch first.',
        },
      },
      {
        id: 'evidence-b',
        summary: 'Second candidate',
        reviewState: 'reviewed',
        beforeSnapshot: {
          current_step: 'Rebuild broadly.',
        },
        afterSnapshot: {
          current_step: 'Refactor the whole planner loop.',
        },
      },
    ],
    new Set(['evidence-a', 'evidence-b']),
    'evidence-a',
  );

  assert.equal(state.adoptable, false);
  assert.equal(state.mode, 'conflict_blocked');
  assert.match(state.reason, /conflicts on current_step/i);
});

test('resolveRestoreOrchestrationItems keeps multi-select restore work in preview and master history compare-only', () => {
  const formalItems = [
    {
      id: 'formal-1',
      title: 'Formal route checkpoint',
      level: 'project',
      changedFields: ['current_step'],
      diffSummary: 'current_step -> verify route branch first',
    },
    {
      id: 'formal-2',
      title: 'Formal summary checkpoint',
      level: 'project',
      changedFields: ['summary'],
      diffSummary: 'summary -> keep scope narrow',
    },
  ];
  const subplanItems = [
    {
      id: 'subplan-1',
      title: 'Subplan v3',
      level: 'project',
      changedFields: ['current_stage_id'],
      diffSummary: 'current stage -> verify lane branch',
      version: 3,
    },
  ];
  const masterItems = [
    {
      id: 'master-1',
      title: 'Master transfer checkpoint',
      level: 'master',
      changedFields: ['summary'],
      diffSummary: 'summary -> compare only',
    },
  ];

  const orchestration = resolveRestoreOrchestrationItems({
    formalHistory: {
      selectedIds: new Set(['formal-1', 'formal-2']),
      compareState: resolvePlanHistoryCompareState(formalItems, new Set(['formal-1', 'formal-2']), 'formal-1'),
      items: formalItems,
      guard: resolveGovernedPlanActionGuard({
        action: 'restore_formal_history',
        projectPlanFrozen: false,
        targetLevel: 'project',
      }),
    },
    subplanHistory: {
      selectedIds: new Set(['subplan-1']),
      compareState: resolvePlanHistoryCompareState(subplanItems, new Set(['subplan-1']), 'subplan-1'),
      items: subplanItems,
      guard: resolveGovernedPlanActionGuard({
        action: 'restore_project_subplan',
        projectPlanFrozen: false,
        masterPlanFrozen: false,
      }),
    },
    masterHistory: {
      selectedIds: new Set(['master-1']),
      compareState: resolvePlanHistoryCompareState(masterItems, new Set(['master-1']), 'master-1'),
      items: masterItems,
    },
  });

  const summary = summarizeRestoreOrchestrationItems(orchestration);
  const formalBatch = orchestration.find((item) => item.id === 'restore-formal-history-batch-preview');
  const masterFocus = orchestration.find((item) => item.source === 'master_history' && item.id === 'master-1');
  const subplanFocus = orchestration.find((item) => item.source === 'project_subplan_history' && item.id === 'subplan-1');

  assert.ok(formalBatch);
  assert.equal(formalBatch.allowed, false);
  assert.match(formalBatch.blockedReason, /only one formal-history entry/i);
  assert.deepEqual(formalBatch.changedFields, ['current_step', 'summary']);

  assert.ok(masterFocus);
  assert.equal(masterFocus.mode, 'compare_only');
  assert.equal(masterFocus.allowed, false);
  assert.match(masterFocus.blockedReason, /compare-only/i);

  assert.ok(subplanFocus);
  assert.equal(subplanFocus.allowed, true);
  assert.deepEqual(subplanFocus.execution, {
    action: 'restore_project_subplan',
    entryId: 'subplan-1',
    version: 3,
  });
  assert.equal(summary.allowedCount, 1);
  assert.equal(summary.compareOnlyCount, 1);
  assert.ok(summary.blockedCount >= 2);
});

test('resolveRestoreOrchestrationItems adds execution payload for single allowed formal restore', () => {
  const orchestration = resolveRestoreOrchestrationItems({
    formalHistory: {
      selectedIds: new Set(['formal-1']),
      compareState: resolvePlanHistoryCompareState(
        [
          {
            id: 'formal-1',
            title: 'Formal route checkpoint',
            level: 'project',
            changedFields: ['current_step'],
          },
        ],
        new Set(['formal-1']),
        'formal-1',
      ),
      items: [
        {
          id: 'formal-1',
          title: 'Formal route checkpoint',
          level: 'project',
          changedFields: ['current_step'],
        },
      ],
      guard: resolveGovernedPlanActionGuard({
        action: 'restore_formal_history',
        projectPlanFrozen: false,
        targetLevel: 'project',
      }),
    },
    subplanHistory: {
      selectedIds: new Set(),
      compareState: resolvePlanHistoryCompareState([], new Set(), undefined),
      items: [],
      guard: resolveGovernedPlanActionGuard({
        action: 'restore_project_subplan',
        projectPlanFrozen: false,
        masterPlanFrozen: false,
      }),
    },
    masterHistory: {
      selectedIds: new Set(),
      compareState: resolvePlanHistoryCompareState([], new Set(), undefined),
      items: [],
    },
  });

  const formalFocus = orchestration.find((item) => item.id === 'formal-1');
  assert.ok(formalFocus);
  assert.equal(formalFocus.allowed, true);
  assert.deepEqual(formalFocus.execution, {
    action: 'restore_formal_history',
    entryId: 'formal-1',
  });
});

test('resolveRestoreOrchestrationItems does not mark restore lanes as allowed when no compare focus exists', () => {
  const orchestration = resolveRestoreOrchestrationItems({
    formalHistory: {
      selectedIds: new Set(),
      compareState: resolvePlanHistoryCompareState([], new Set(), undefined),
      items: [],
      guard: resolveGovernedPlanActionGuard({
        action: 'restore_formal_history',
        projectPlanFrozen: false,
        targetLevel: 'project',
      }),
    },
    subplanHistory: {
      selectedIds: new Set(),
      compareState: resolvePlanHistoryCompareState([], new Set(), undefined),
      items: [],
      guard: resolveGovernedPlanActionGuard({
        action: 'restore_project_subplan',
        projectPlanFrozen: false,
        masterPlanFrozen: false,
      }),
    },
    masterHistory: {
      selectedIds: new Set(),
      compareState: resolvePlanHistoryCompareState([], new Set(), undefined),
      items: [],
    },
  });

  const formalFocus = orchestration.find((item) => item.id === 'restore-formal-history-focus');
  const subplanFocus = orchestration.find((item) => item.id === 'restore-subplan-history-focus');

  assert.ok(formalFocus);
  assert.equal(formalFocus.allowed, false);
  assert.ok(subplanFocus);
  assert.equal(subplanFocus.allowed, false);
});

test('resolvePlanEvidenceAdoptionState blocks stale evidence from formal adoption', () => {
  const staleFixtures = [
    ...evidenceFixtures,
    {
      id: 'plan-evidence-stale',
      title: 'Stale routing evidence',
      summary: 'This candidate is no longer current.',
      focusArea: 'routing',
      source: 'evaluation',
      reviewState: 'reviewed',
      freshness: 'stale',
      staleReason: 'Formal plan changed since this evidence was captured.',
      diffSummary: 'current step -> verify route wiring first',
      changedFields: ['current_step'],
    },
  ];

  const state = resolvePlanEvidenceAdoptionState(
    staleFixtures,
    new Set(['plan-evidence-stale']),
    'plan-evidence-stale',
  );

  assert.equal(state.adoptable, false);
  assert.equal(state.mode, 'stale_blocked');
  assert.equal(state.candidateId, 'plan-evidence-stale');
  assert.match(state.reason, /Formal plan changed/);
});

test('resolvePlanChangeFields falls back to snapshot comparison when changedFields are absent', () => {
  const fields = resolvePlanChangeFields({
    beforeSnapshot: {
      title: 'Coach-first trainer',
      current_step: 'Rebuild the whole planner loop at once.',
      why_now: 'Broaden the whole architecture now.',
    },
    afterSnapshot: {
      title: 'Coach-first trainer',
      current_step: 'Verify one route branch before widening.',
      why_now: 'Prove one branch before broadening the plan.',
    },
  });

  assert.deepEqual(fields, ['current_step', 'why_now']);
});

test('summarizePlanChangeAlignment reports overlap and divergence against compare focus history', () => {
  const summary = summarizePlanChangeAlignment(
    {
      changedFields: ['current_step', 'verify_method', 'why_now'],
      beforeSnapshot: {
        current_step: 'Rebuild broadly.',
      },
      afterSnapshot: {
        current_step: 'Verify one route branch first.',
      },
    },
    {
      changedFields: ['current_step', 'summary'],
      beforeSnapshot: {
        current_step: 'Rebuild broadly.',
      },
      afterSnapshot: {
        current_step: 'Keep routing narrow.',
      },
    },
  );

  assert.deepEqual(summary.primaryFields, ['current_step', 'verify_method', 'why_now']);
  assert.deepEqual(summary.compareFields, ['current_step', 'summary']);
  assert.deepEqual(summary.overlapFields, ['current_step']);
  assert.deepEqual(summary.primaryOnlyFields, ['verify_method', 'why_now']);
  assert.deepEqual(summary.compareOnlyFields, ['summary']);
});

test('filterPlanHistoryItems combines level, query, and diff filters', () => {
  const filtered = filterPlanHistoryItems(historyFixtures, {
    level: 'project',
    query: 'routing',
    diffMode: 'with_diff',
  });

  assert.deepEqual(
    filtered.map((item) => item.id),
    ['plan-history-1', 'plan-history-3'],
  );
});

test('summarizePlanHistorySelection reports selected levels and diff coverage', () => {
  const summary = summarizePlanHistorySelection(
    new Set(['plan-history-2', 'plan-history-3']),
    historyFixtures,
  );

  assert.equal(summary.totalSelected, 2);
  assert.equal(summary.selectedWithDiff, 1);
  assert.deepEqual(summary.levels, ['master', 'project']);
  assert.deepEqual(summary.actions, ['evidence_adopt', 'freeze_master']);
});

test('resolvePlanHistoryCompareState reports selected single and compare focus states', () => {
  const selectedState = resolvePlanHistoryCompareState(
    historyFixtures,
    new Set(['plan-history-1']),
    'plan-history-3',
  );

  assert.equal(selectedState.mode, 'selected_single');
  assert.equal(selectedState.candidateId, 'plan-history-1');
  assert.equal(selectedState.selectedCount, 1);

  const compareState = resolvePlanHistoryCompareState(historyFixtures, new Set(), 'plan-history-2');
  assert.equal(compareState.mode, 'compare_focus');
  assert.equal(compareState.candidateId, 'plan-history-2');
  assert.equal(compareState.selectedCount, 0);
});

test('resolvePlanHistoryCompareState blocks multiple selected history entries', () => {
  const state = resolvePlanHistoryCompareState(
    historyFixtures,
    new Set(['plan-history-1', 'plan-history-3']),
    'plan-history-2',
  );

  assert.equal(state.mode, 'selection_blocked');
  assert.equal(state.selectedCount, 2);
});

test('resolveGovernedPlanActionGuard blocks candidate adoption when plans are frozen', () => {
  const state = resolveGovernedPlanActionGuard({
    action: 'adopt_candidate',
    projectPlanFrozen: true,
    masterPlanFrozen: false,
    hasCandidate: true,
    adoptionReady: true,
  });

  assert.equal(state.allowed, false);
  assert.equal(state.reasonCode, 'project_frozen');
});

test('resolveGovernedPlanActionGuard blocks master-level formal history restore as compare-only', () => {
  const state = resolveGovernedPlanActionGuard({
    action: 'restore_formal_history',
    targetLevel: 'master',
  });

  assert.equal(state.allowed, false);
  assert.equal(state.reasonCode, 'compare_only');
});

test('resolveGovernedPlanActionGuard returns adoption blocker details when candidate is not ready', () => {
  const state = resolveGovernedPlanActionGuard({
    action: 'preview_candidate',
    hasCandidate: true,
    adoptionReady: false,
    adoptionReason: 'Selected evidence conflicts on current_step.',
  });

  assert.equal(state.allowed, false);
  assert.equal(state.reasonCode, 'adoption_blocked');
  assert.match(state.reason, /current_step/);
});

test('rankPlanHistoryMatches orders exact, partial, and disjoint formal history matches', () => {
  const matches = rankPlanHistoryMatches(
    {
      changedFields: ['current_step', 'verify_method'],
      beforeSnapshot: {
        current_step: 'Rebuild broadly.',
        verify_method: ['Open the full planner loop.'],
      },
      afterSnapshot: {
        current_step: 'Verify one route branch first.',
        verify_method: ['Run one routing-focused verification.'],
      },
    },
    [
      {
        id: 'history-disjoint',
        title: 'Disjoint history',
        level: 'master',
        changedFields: ['summary'],
        createdAt: '2026-05-10T00:00:00Z',
      },
      {
        id: 'history-partial',
        title: 'Partial history',
        level: 'project',
        changedFields: ['current_step', 'summary'],
        createdAt: '2026-05-11T00:00:00Z',
      },
      {
        id: 'history-exact',
        title: 'Exact history',
        level: 'project',
        changedFields: ['current_step', 'verify_method'],
        createdAt: '2026-05-09T00:00:00Z',
      },
    ],
  );

  assert.deepEqual(
    matches.map((item) => [item.historyId, item.matchKind]),
    [
      ['history-exact', 'exact'],
      ['history-partial', 'partial'],
      ['history-disjoint', 'disjoint'],
    ],
  );
  assert.deepEqual(matches[0].overlapFields, ['current_step', 'verify_method']);
  assert.deepEqual(matches[1].overlapFields, ['current_step']);
  assert.deepEqual(matches[1].historyOnlyFields, ['summary']);
  assert.equal(matches[2].overlapCount, 0);
});
