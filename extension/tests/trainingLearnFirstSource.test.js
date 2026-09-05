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
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

test('training view keeps the learn-first loop explicit in source', () => {
  const source = fs.readFileSync(trainingViewPath, 'utf8');

  assert.match(source, /type TrainingLoopStepKey = "learn" \| "try" \| "verify" \| "reflect" \| "return";/);
  assert.match(source, /function buildTrainingLoopSteps\(/);
  assert.match(source, /input\.composerPhase === "answer" \? "try" : input\.composerPhase/);
  assert.match(source, /className="training-loop-rail"/);
  assert.match(source, /const needsPrimerState = trainingExecutionState\.needsPrimer;/);
  assert.match(source, /needsPrimerState\s*\?\s*trainingSurfaceLabel\(language, "primer"\)/);
  assert.match(
    source,
    /const learnPhaseActive =\s*\(needsPrimerState \|\| isFlashCard\) && hasLearnFirstBlock && verificationReturn\.kind === "waiting";/,
  );
  assert.match(source, /aria-label=\{trainingSurfaceLabel\(language, "trainingLoop"\)\}/);
  assert.match(source, /verificationReturn\.kind === "verified"/);
  assert.match(source, /verificationReturn\.kind === "blocked"\s*\?/);
  assert.match(source, /kind: "needs-review"/);
  assert.match(source, /kind: selectedStatus === "blocked" \? "blocked" : "needs-review",/);
  assert.match(source, /"Return"/);
  assert.match(source, /"Reflect"/);
});

test('training loop rail styles stay compact for the VS Code sidebar', () => {
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.match(styles, /\.training-loop-rail\s*\{[\s\S]*?grid-template-columns:\s*repeat\(5,\s*minmax\(0,\s*1fr\)\);/);
  assert.match(styles, /\.training-loop-step\s*\{[\s\S]*?min-height:\s*26px;/);
  assert.match(styles, /\.training-loop-step__label\s*\{[\s\S]*?font-size:\s*var\(--trainer-font-3xs\);/);
  assert.match(styles, /\.training-loop-step\.is-active\s*\{[\s\S]*?background:\s*color-mix/);
});

test('training rail exposes complete localized labels and narrow-layout hooks', () => {
  const source = fs.readFileSync(trainingViewPath, 'utf8');

  assert.match(source, /data-training-loop-layout="3-plus-2"/);
  assert.match(source, /data-training-loop-step-count=\{trainingLoopSteps\.length\}/);
  assert.match(source, /data-training-loop-step=\{step\.key\}/);
  assert.match(source, /data-training-loop-state=\{step\.state\}/);
  assert.match(source, /data-training-loop-label=\{step\.label\}/);
  assert.match(source, /data-training-loop-step-label=\{step\.label\}/);
  assert.match(source, /data-training-context-layout="optional-second-line"/);
  assert.match(source, /className="training-current__learning-family"/);
  assert.doesNotMatch(source, /compactCardText\(headerContextSource/);
});
