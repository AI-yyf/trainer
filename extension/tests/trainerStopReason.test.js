'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  describeTrainerStopReason,
  findCoachVisibleStatusPart,
  normalizeTrainerMessageParts,
} = require('../dist/shared/src/protocol.js');

test('describeTrainerStopReason keeps coach stop labels human and strips error suffixes', () => {
  assert.equal(describeTrainerStopReason('coach_finalize', 'en-US'), 'Coach wrapped up');
  assert.equal(describeTrainerStopReason('no_progress', 'en-US'), 'No new evidence');
  assert.equal(describeTrainerStopReason('agent_error: RuntimeError', 'en-US'), 'Execution error');
  assert.equal(describeTrainerStopReason('language_corruption', 'en-US'), 'Input corrupted');
  assert.equal(describeTrainerStopReason('invalid_key_or_permission', 'en-US'), 'API key blocked');
  assert.equal(describeTrainerStopReason('model_not_found', 'en-US'), 'Model unavailable');
  assert.equal(describeTrainerStopReason('timeout', 'zh-CN'), '超时');
  assert.equal(describeTrainerStopReason('provider_error', 'zh-CN'), '模型错误');
  assert.equal(describeTrainerStopReason('completed', 'en-US'), undefined);
});

test('normalizeTrainerMessageParts preserves visible resume guidance on recovery cards', () => {
  const parts = normalizeTrainerMessageParts([
    {
      type: 'coach_visible_status',
      status: 'degraded',
      summary: 'The provider returned an empty visible answer, so I kept the recovery path visible.',
      nextStep: 'Retry the turn with a visible conclusion.',
      resume_thread: 'Resume the live thread around the current slice. Next: Retry the turn with a visible conclusion.',
      stopReason: 'empty_response',
      source: 'agent_loop',
    },
  ]);

  const part = findCoachVisibleStatusPart(parts);
  assert.ok(part);
  assert.equal(
    part.resumeThread,
    'Resume the live thread around the current slice. Next: Retry the turn with a visible conclusion.',
  );
});
