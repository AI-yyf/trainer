'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const trainingViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);

test('Training targetSkill does not backfill leftover formal title or focus', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const viewSource = fs.readFileSync(trainingViewPath, 'utf8');

  assert.match(appSource, /liveTrainingTargetSkill\(/);
  assert.match(appSource, /targetSkill=\{liveTrainingSkill\}/);
  assert.doesNotMatch(appSource, /targetSkill=\{trainingTargetSkill\}/);
  assert.match(viewSource, /const resolvedTargetSkill = firstText\(targetSkill\?\.trim\(\)\);/);
  assert.doesNotMatch(
    viewSource,
    /const resolvedTargetSkill = firstText\(targetSkill\?\.trim\(\), currentFocus\?\.trim\(\)\);/,
  );
});
