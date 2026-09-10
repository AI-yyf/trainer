'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  describePlanVerifyAdvanceState,
  planVerifyAdvanceStageLabel,
} = require('../dist/extension/src/core/planVerifyExplainability.js');

test('describePlanVerifyAdvanceState explains advanced stage with optional FSRS', () => {
  const zh = describePlanVerifyAdvanceState('zh-CN', {
    advanced: true,
    what: '落地 expiry guard',
    next: '补一条回归检查',
    fsrs: { reps: 1, state: 'Learning', intervalDays: 0 },
  });
  assert.equal(zh.tone, 'success');
  assert.match(zh.message, /计划阶段已推进/);
  assert.match(zh.message, /落地 expiry guard/);
  assert.match(zh.message, /下一步：补一条回归检查/);
  assert.match(zh.message, /FSRS 写回/);
  assert.match(zh.message, /reps=1/);
  assert.match(zh.message, /state=Learning/);

  const en = describePlanVerifyAdvanceState('en-US', {
    advanced: true,
    what: 'Land the expiry guard',
    next: 'Add one regression check',
    fsrs: { reps: 1, state: 'Learning' },
  });
  assert.equal(en.tone, 'success');
  assert.match(en.message, /plan stage advanced/i);
  assert.match(en.message, /FSRS write-back/i);
  assert.match(en.message, /reps=1/);
});

test('describePlanVerifyAdvanceState explains verify done without stage advance', () => {
  const zh = describePlanVerifyAdvanceState('zh-CN', {
    advanced: false,
    why: '当前步骤验证未通过，仍停在原阶段。',
    what: '落地 expiry guard',
  });
  assert.equal(zh.tone, 'info');
  assert.match(zh.message, /未推进/);
  assert.match(zh.message, /原因：当前步骤验证未通过/);

  const en = describePlanVerifyAdvanceState('en-US', {
    advanced: false,
    why: 'Verify did not clear the live step gate.',
    next: 'Retry the focused check',
  });
  assert.equal(en.tone, 'info');
  assert.match(en.message, /did not advance/i);
  assert.match(en.message, /Why: Verify did not clear/);
  assert.match(en.message, /Next: Retry the focused check/);
});

test('planVerifyAdvanceStageLabel prefixes Plan nextStep honestly', () => {
  assert.equal(planVerifyAdvanceStageLabel('zh-CN', true), '已推进');
  assert.equal(planVerifyAdvanceStageLabel('zh-CN', false), '未推进');
  assert.equal(planVerifyAdvanceStageLabel('en-US', true), 'Advanced');
  assert.equal(planVerifyAdvanceStageLabel('en-US', false), 'Not advanced');
  assert.equal(planVerifyAdvanceStageLabel('en-US', undefined), '');
});
