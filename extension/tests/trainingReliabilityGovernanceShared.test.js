'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  canTransitionTrainingReliability,
  describeTrainingReliability,
  isTrainingReliabilityExpired,
  shouldCoalesceTrainingReliability,
  shouldReplayTrainingReliability,
} = require('../dist/shared/src/trainingReliabilityGovernance.js');

test('allows the reliability path and blocks illegal jumps', () => {
  assert.equal(canTransitionTrainingReliability('intent', 'pending'), true);
  assert.equal(canTransitionTrainingReliability('pending', 'executing'), true);
  assert.equal(canTransitionTrainingReliability('executing', 'succeeded'), true);
  assert.equal(canTransitionTrainingReliability('succeeded', 'acked'), true);
  assert.equal(canTransitionTrainingReliability('failed', 'pending'), true);
  assert.equal(canTransitionTrainingReliability('cancelled', 'pending'), true);
  assert.equal(canTransitionTrainingReliability('acked', 'failed'), false);
  assert.equal(canTransitionTrainingReliability('succeeded', 'failed'), false);
});

test('replays acknowledged requests and coalesces in-flight duplicates', () => {
  const acked = {
    requestId: 'req-1',
    idempotencyKey: 'req-1',
    commandId: 'trainer.training.reflect',
    cardId: 'card-1',
    phase: 'acked',
    revision: 1,
  };
  assert.equal(shouldReplayTrainingReliability(acked, 'req-1', 'req-1'), true);
  assert.equal(shouldReplayTrainingReliability(acked, 'req-2', 'other'), false);

  const executing = {
    requestId: 'req-3',
    idempotencyKey: 'req-3',
    commandId: 'trainer.training.return',
    cardId: 'card-2',
    phase: 'executing',
    revision: 1,
  };
  assert.equal(
    shouldCoalesceTrainingReliability(executing, 'req-other', 'trainer.training.return', 'card-2'),
    true,
  );
  assert.equal(
    shouldCoalesceTrainingReliability(executing, 'req-other', 'trainer.training.reflect', 'card-2'),
    false,
  );
});

test('expires in-flight records and describes recovery copy from snapshot truth', () => {
  const timedOut = {
    requestId: 'req-4',
    idempotencyKey: 'req-4',
    commandId: 'trainer.training.practiceReturn',
    cardId: 'card-3',
    phase: 'executing',
    revision: 1,
    timeoutAt: new Date(Date.now() - 1_000).toISOString(),
  };
  assert.equal(isTrainingReliabilityExpired(timedOut), true);

  const failedCopy = describeTrainingReliability({
    record: {
      ...timedOut,
      phase: 'failed',
      outcome: 'timeout',
      recoverable: true,
    },
    language: 'en-US',
  });
  assert.ok(failedCopy);
  assert.match(failedCopy.what, /timed out/i);
  assert.match(failedCopy.next, /recover|again/i);

  const localOnly = describeTrainingReliability({
    localInFlight: true,
    language: 'zh-CN',
  });
  assert.ok(localOnly);
  assert.match(localOnly.why, /真相/);
});
