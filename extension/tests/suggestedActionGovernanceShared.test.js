'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  resolveSuggestedActionGovernance,
} = require('../dist/shared/src/suggestedActionGovernance.js');

test('plan suggested actions open the governed plan view without mutating the composer draft', () => {
  const result = resolveSuggestedActionGovernance({
    action: 'plan',
    prompt: '请把当前训练主线整理成正式计划。',
  });

  assert.deepEqual(result, {
    activeView: 'plan',
  });
});

test('review suggested actions route into training review mode and keep the prompt when present', () => {
  const result = resolveSuggestedActionGovernance({
    action: 'review',
    prompt: '基于当前代码检查这轮 coach-first 收口是否成立。',
  });

  assert.deepEqual(result, {
    activeView: 'practice',
    trainingSubmode: 'review',
    composerDraft: '基于当前代码检查这轮 coach-first 收口是否成立。',
  });
});

test('task-like suggested actions route into practice mode and trim empty prompts', () => {
  const result = resolveSuggestedActionGovernance({
    action: 'task',
    prompt: '   ',
  });

  assert.deepEqual(result, {
    activeView: 'practice',
    trainingSubmode: 'practice',
    composerDraft: undefined,
  });
});

test('hint suggested actions stay in coach view and forward the prompt', () => {
  const result = resolveSuggestedActionGovernance({
    action: 'hint',
    prompt: '结合当前代码，给我更小的下一步。',
  });

  assert.deepEqual(result, {
    activeView: 'coach',
    composerDraft: '结合当前代码，给我更小的下一步。',
  });
});
