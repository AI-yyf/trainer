'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const trainingViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);
const trainingInlineTextPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'segments',
  'trainingInlineText.ts',
);

test('training keeps Learn-first honest and makes card-only mode a focused card surface', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
});

test('training distinguishes verified evidence from formal plan confirmation', () => {
  const source = fs.readFileSync(trainingViewPath, 'utf8');
  // The verification-return copy table (including the pending-plan phrases)
  // moved verbatim into the i18n segment file; the phrase assertions slice
  // there while the state-machine assertions keep reading the view.
  const segmentSource = fs.readFileSync(trainingInlineTextPath, 'utf8');

  assert.match(source, /pendingPlanConfirmationLike/);
  assert.match(source, /kind: "pending-plan-confirmation"/);
  assert.match(segmentSource, /Verified, plan confirmation pending/);
  assert.match(segmentSource, /formal plan is not complete/);
  assert.doesNotMatch(source, /pending-plan-confirmation[\s\S]*?Card completed!/);
});
