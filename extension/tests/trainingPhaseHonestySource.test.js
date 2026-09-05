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

test('training keeps Learn-first honest and makes card-only mode a focused card surface', () => {
  const source = fs.readFileSync(trainingViewPath, 'utf8');

  assert.match(source, /const hasLearnFirstBlock = Boolean\(/);
  assert.match(
    source,
    /const learnPhaseActive =\s*\(needsPrimerState \|\| isFlashCard\) && hasLearnFirstBlock && verificationReturn\.kind === "waiting";/,
  );
  assert.match(source, /const showLearnFirstPanel = learnPhaseActive && hasLearnFirstBlock;/);
  assert.match(source, /const showLearnPrimerNote = !cardOnly && !learnPhaseActive && hasLearnFirstBlock;/);
  assert.match(source, /const showCardOnlyTryStep = cardOnly && !isFlashCard;/);
  assert.match(source, /const cardOnlyBodySections: TrainingCardOnlySection\[\] = \[/);
  assert.match(source, /\{!cardOnly \? \(isFlashCard \? flashProofSurface : practiceProofSurface\) : null\}/);
  assert.match(source, /\{!learnPhaseActive && !cardOnly && adjustmentCopy \?/);
  assert.match(source, /data-training-card-fact=\{section\.key\}/);
  assert.doesNotMatch(source, /const showLearnStageBlock =/);
});

test('training distinguishes verified evidence from formal plan confirmation', () => {
  const source = fs.readFileSync(trainingViewPath, 'utf8');

  assert.match(source, /pendingPlanConfirmationLike/);
  assert.match(source, /kind: "pending-plan-confirmation"/);
  assert.match(source, /Verified, plan confirmation pending/);
  assert.match(source, /formal plan is not complete/);
  assert.doesNotMatch(source, /pending-plan-confirmation[\s\S]*?Card completed!/);
});
