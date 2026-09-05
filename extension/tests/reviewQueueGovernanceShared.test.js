'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  filterReviewQueueItems,
  groupReviewQueueByFocusArea,
  prioritizeReviewQueueItems,
  resolveReviewQueueRecoveryCandidate,
  summarizeReviewQueueItems,
  summarizeReviewQueueTruth,
} = require('../dist/shared/src/reviewQueueGovernance.js');

const reviewItems = [
  {
    concept: 'route handler',
    reason: 'Return to the live thread and verify the handler boundary.',
    source: 'reflection',
    severity: 'medium',
    surfaceMode: 'due',
    focusArea: 'routing',
    taskHint: 'Finish the route test first.',
    masteryScore: 0.62,
    dueAt: '2026-05-14T08:00:00Z',
  },
  {
    concept: 'Depends',
    reason: 'The dependency still breaks when parameters change.',
    source: 'weakness',
    severity: 'high',
    surfaceMode: 'due',
    focusArea: 'dependency injection',
    taskHint: 'Rebuild the smallest injection slice yourself.',
    masteryScore: 0.21,
    dueAt: '2026-05-14T07:00:00Z',
  },
  {
    concept: 'Depends misuse',
    reason: 'The last recovery loop still ended in a parameter misuse.',
    source: 'weakness',
    severity: 'high',
    surfaceMode: 'ahead',
    focusArea: 'dependency injection',
    taskHint: 'Re-check parameter wiring before widening scope.',
    masteryScore: 0.24,
    dueAt: '2026-05-15T07:00:00Z',
  },
  {
    concept: 'plan stage',
    reason: 'Restate why the current stage boundary still holds.',
    source: 'plan',
    severity: 'medium',
    surfaceMode: 'digest',
    focusArea: 'planning',
    taskHint: 'Tie the next patch back to the current stage.',
    masteryScore: 0.8,
    dueAt: '2026-05-16T07:00:00Z',
  },
];

const recentActions = [
  {
    actionId: 'qa-1',
    concept: 'Depends',
    action: 'reset',
    outcome: 'needs_more_practice',
    focusArea: 'dependency injection',
    createdAt: '2026-05-14T09:00:00Z',
  },
  {
    actionId: 'qa-2',
    concept: 'Depends misuse',
    action: 'snooze',
    outcome: 'deferred',
    focusArea: 'dependency injection',
    createdAt: '2026-05-14T08:00:00Z',
  },
  {
    actionId: 'qa-3',
    concept: 'route handler',
    action: 'done',
    outcome: 'completed',
    focusArea: 'routing',
    createdAt: '2026-05-14T07:00:00Z',
  },
];

test('prioritizeReviewQueueItems prefers due high-risk weakness items with low mastery', () => {
  const prioritized = prioritizeReviewQueueItems(reviewItems, recentActions);

  assert.equal(prioritized[0].concept, 'Depends');
  assert.equal(prioritized[1].concept, 'route handler');
  assert.equal(prioritized[2].concept, 'Depends misuse');
});

test('groupReviewQueueByFocusArea surfaces recovery-heavy focus groups first', () => {
  const prioritized = prioritizeReviewQueueItems(reviewItems, recentActions);
  const groups = groupReviewQueueByFocusArea(prioritized, recentActions);

  assert.equal(groups[0].focusArea, 'dependency injection');
  assert.equal(groups[0].items.length, 2);
  assert.equal(groups[0].highCount, 2);
  assert.equal(groups[0].needsMorePracticeCount, 1);
  assert.equal(groups[0].recentActionCount, 2);
});

test('summarizeReviewQueueItems and filterReviewQueueItems expose governance counts', () => {
  const prioritized = prioritizeReviewQueueItems(reviewItems, recentActions);
  const groups = groupReviewQueueByFocusArea(prioritized, recentActions);
  const summary = summarizeReviewQueueItems(prioritized, recentActions);

  assert.equal(summary.totalItems, 4);
  assert.equal(summary.highCount, 2);
  assert.equal(summary.dueCount, 2);
  assert.equal(summary.aheadCount, 1);
  assert.equal(summary.digestCount, 1);
  assert.equal(summary.focusGroupCount, 3);
  assert.equal(summary.needsMorePracticeCount, 1);
  assert.deepEqual(summary.bySource, {
    weakness: 2,
    mastery: 0,
    reflection: 1,
    plan: 1,
  });

  assert.deepEqual(
    filterReviewQueueItems(prioritized, 'focus', groups).map((item) => item.concept),
    ['Depends', 'Depends misuse'],
  );
  assert.deepEqual(
    filterReviewQueueItems(prioritized, 'due', groups).map((item) => item.concept),
    ['Depends', 'route handler'],
  );
});

test('resolveReviewQueueRecoveryCandidate recommends a focus batch when one weak area keeps resurfacing', () => {
  const prioritized = prioritizeReviewQueueItems(reviewItems, recentActions);
  const groups = groupReviewQueueByFocusArea(prioritized, recentActions);
  const candidate = resolveReviewQueueRecoveryCandidate(prioritized, groups);

  assert.equal(candidate.mode, 'focus_area_batch');
  assert.equal(candidate.focusArea, 'dependency injection');
  assert.equal(candidate.itemCount, 2);
  assert.equal(candidate.highCount, 2);
  assert.equal(candidate.needsMorePracticeCount, 1);
});

test('summarizeReviewQueueTruth exposes FSRS-backed review truth for the current card flow', () => {
  const truth = summarizeReviewQueueTruth(
    [
      {
        concept: 'Depends',
        reason: 'The dependency still breaks when parameters change.',
        source: 'weakness',
        severity: 'high',
        surfaceMode: 'due',
        focusArea: 'dependency injection',
        taskHint: 'Rebuild the smallest injection slice yourself.',
        dueAt: '2026-05-14T07:00:00Z',
        intervalDays: 3,
        retrievability: 0.42,
        fsrsState: 'review',
      },
    ],
    'Latest review move: Depends, reset into a smaller review loop.',
    'en-US',
  );

  assert.ok(
    truth.headline.startsWith(
      'Next suggested review for Rebuild the smallest injection slice yourself.: May 14,',
    ),
  );
  assert.equal(truth.detail, 'Estimated recall right now is 42%.');
  assert.deepEqual(truth.meta, ['Recall 42%', '3d interval', 'Review']);
  assert.equal(
    truth.latestAction,
    'Latest review move: Depends, reset into a smaller review loop.',
  );
});
