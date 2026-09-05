'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  summarizeReviewArtifactGovernance,
  resolveReviewArtifactHistoryAction,
} = require('../dist/shared/src/reviewArtifactGovernance.js');

test('summarizeReviewArtifactGovernance marks an incomplete active artifact as fragile', () => {
  const summary = summarizeReviewArtifactGovernance({
    id: 'review-1',
    focusArea: 'dependency injection',
    summary: '',
    rootCause: '',
    guardrail: '',
    nextSelfImplementationRule: '',
    recommendedRecoveryMode: 'review',
    recommendedActions: [],
    linkedDependencyKeys: [],
    linkedReviewConcepts: [],
    status: 'active',
  });

  assert.equal(summary.readiness, 'fragile');
  assert.equal(summary.canResolve, false);
  assert.equal(summary.recommendedAction, 'reviewed');
  assert.ok(summary.missingFields.some((item) => item.key === 'summary'));
  assert.ok(summary.missingFields.some((item) => item.key === 'root_cause'));
});

test('summarizeReviewArtifactGovernance marks a complete active artifact as resolvable', () => {
  const summary = summarizeReviewArtifactGovernance({
    id: 'review-2',
    focusArea: 'routing',
    summary: 'The route boundary is now explicit.',
    rootCause: 'The learner widened scope before proving the first route slice.',
    guardrail: 'Keep the dependency inside one route until the check passes twice.',
    nextSelfImplementationRule: 'Rebuild the same route yourself before touching adjacent files.',
    recommendedRecoveryMode: 'practice',
    recommendedActions: ['Rebuild the same route slice yourself first.'],
    linkedDependencyKeys: ['fastapi'],
    linkedReviewConcepts: ['route boundary'],
    status: 'active',
  });

  assert.equal(summary.readiness, 'strong');
  assert.equal(summary.canResolve, true);
  assert.equal(summary.recommendedAction, 'resolved');
});

test('summarizeReviewArtifactGovernance recommends archive for a resolved artifact', () => {
  const summary = summarizeReviewArtifactGovernance({
    id: 'review-3',
    focusArea: 'testing',
    summary: 'The failing check is stable now.',
    verifiedResult: 'The focused test passes again.',
    rootCause: 'The setup boundary was wrong.',
    guardrail: 'Keep setup inside one fixture.',
    nextSelfImplementationRule: 'Recreate the same fixture once more before widening scope.',
    recommendedRecoveryMode: 'practice',
    recommendedActions: ['Rebuild the same fixture in isolation once more.'],
    linkedDependencyKeys: ['pytest'],
    linkedReviewConcepts: ['fixture'],
    status: 'resolved',
  });

  assert.equal(summary.canArchive, true);
  assert.equal(summary.recommendedAction, 'archived');
});

test('resolveReviewArtifactHistoryAction preserves lifecycle actions and defaults unknown values', () => {
  assert.equal(resolveReviewArtifactHistoryAction('reviewed'), 'reviewed');
  assert.equal(resolveReviewArtifactHistoryAction('resolved'), 'resolved');
  assert.equal(resolveReviewArtifactHistoryAction('reopened'), 'reopened');
  assert.equal(resolveReviewArtifactHistoryAction('archived'), 'archived');
  assert.equal(resolveReviewArtifactHistoryAction('restore_history'), 'restore_history');
  assert.equal(resolveReviewArtifactHistoryAction('unexpected'), 'updated');
});
