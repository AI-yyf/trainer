'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  resolveConversationCandidateActionGovernance,
  shouldRenderConversationCandidateAlongsideStatus,
} = require('../dist/shared/src/conversationCandidateGovernance.js');
const { buildTrainingCardRouting } = require('../dist/shared/src/trainingCardRouting.js');

test('closed conversation candidates expose no ordinary chat actions', () => {
  for (const status of ['accepted', 'continued_in_chat', 'dismissed', 'expired', 'archived']) {
    const result = resolveConversationCandidateActionGovernance({ status });

    assert.equal(result.isClosed, true, status);
    assert.equal(result.isRecoverable, false, status);
    assert.equal(result.shouldRenderOrdinaryActions, false, status);
    assert.equal(result.canAccept, false, status);
    assert.equal(result.canDefer, false, status);
    assert.equal(result.canDismiss, false, status);
    assert.equal(result.canBlock, false, status);
  }
});

test('recoverable conversation candidates keep only sensible next actions', () => {
  assert.deepEqual(resolveConversationCandidateActionGovernance({ status: 'deferred' }), {
    isClosed: false,
    isRecoverable: true,
    shouldRenderOrdinaryActions: true,
    canAccept: true,
    canDefer: false,
    canDismiss: true,
    canBlock: true,
  });

  assert.deepEqual(resolveConversationCandidateActionGovernance({ status: 'blocked' }), {
    isClosed: false,
    isRecoverable: true,
    shouldRenderOrdinaryActions: true,
    canAccept: true,
    canDefer: true,
    canDismiss: true,
    canBlock: false,
  });
});

test('new or surfaced conversation candidates remain actionable', () => {
  for (const status of ['created', 'surfaced', undefined]) {
    assert.deepEqual(resolveConversationCandidateActionGovernance({ status }), {
      isClosed: false,
      isRecoverable: false,
      shouldRenderOrdinaryActions: true,
      canAccept: true,
      canDefer: true,
      canDismiss: true,
      canBlock: true,
    });
  }
});

test('pure conversation routing remains chat-first even when a practice card exists', () => {
  const route = buildTrainingCardRouting({
    pureConversationMode: true,
    currentSubmode: 'practice',
    candidates: [
      {
        id: 'practice-thin-slice',
        type: 'practice',
        title: 'Implement one thin slice yourself',
        prompt: 'Open one file and implement the learner-owned thin slice.',
        createdFrom: 'plan',
        sourceChain: ['plan:thin-slice'],
        scoreFactors: {
          planRelevance: 0.8,
          blockingPower: 0.7,
          evidenceGap: 0.72,
          recencyNeed: 0.4,
          resourceTrust: 0.9,
          difficultyFit: 0.82,
          projectFit: 0.86,
          transferValue: 0.3,
          recoveryPriority: 0.2,
          repeatedWeaknessPriority: 0,
        },
        coachOnly: true,
        hasPrompt: true,
        hasDeliverable: true,
        hasVerification: true,
      },
    ],
  });

  assert.equal(route.selectedCardId, undefined);
  assert.equal(route.eligibleCount, 0);
  assert.match(route.whyThisCard, /pure conversation/i);
  assert.match(route.fallbackAction, /coach chat/i);
});

test('conversation status and candidate strip do not both render the same selected card', () => {
  assert.equal(
    shouldRenderConversationCandidateAlongsideStatus(
      { title: 'Route verification card' },
      { selectedCardTitle: 'Route verification card' },
    ),
    false,
  );

  assert.equal(
    shouldRenderConversationCandidateAlongsideStatus(
      { title: 'FastAPI response contract card' },
      { selectedCardTitle: 'Route verification card' },
    ),
    true,
  );
});
