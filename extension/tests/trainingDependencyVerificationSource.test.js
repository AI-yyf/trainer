'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const trainingViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'CoachTrainingView.tsx',
);

test('dependency mastery UI requests verification instead of sending a direct upgrade', () => {
  const source = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const handlerStart = source.indexOf('function submitDependencyAction');
  const handlerEnd = source.indexOf('function handleCardStatusTransition', handlerStart);
  const handler = source.slice(handlerStart, handlerEnd);
  const callbackStart = source.indexOf('onDependencySkillMapAction?:');
  const callbackEnd = source.indexOf('onTrainingRestoreOrchestration?:', callbackStart);
  const callback = source.slice(callbackStart, callbackEnd);

  assert.ok(handlerStart >= 0 && handlerEnd > handlerStart, 'expected dependency verification handler');
  assert.ok(callbackStart >= 0 && callbackEnd > callbackStart, 'expected dependency action callback contract');
  assert.match(handler, /onVerifyCurrentFile\(/);
  assert.match(handler, /action:\s*"request_verification"/);
  assert.doesNotMatch(handler, /action:\s*"mark_(practiced|applied|transferable)"/);
  assert.doesNotMatch(handler, /verifiedResult:/);
  assert.doesNotMatch(callback, /"mark_(practiced|applied|transferable)"/);
  assert.doesNotMatch(callback, /verifiedResult\?:/);
  assert.match(source, /填写说明不会直接改变掌握记录/);
});
