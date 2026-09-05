'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const sharedRoot = path.resolve(__dirname, '..', '..', 'shared', 'src');

function read(relativePath, root = webviewRoot) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

test('first-screen App source does not mount the orientation rail as chrome', () => {
  const app = read('app/App.tsx');
  const coach = read('coachOrientationGovernance.ts', sharedRoot);
  const plan = read('planOrientationGovernance.ts', sharedRoot);
  const resources = read('resourcesOrientationGovernance.ts', sharedRoot);

  assert.doesNotMatch(app, /<CoachOrientationRail/);
  assert.match(app, /deriveCoachOrientation\(/);
  assert.match(app, /derivePlanOrientation\(/);
  assert.match(app, /deriveResourcesOrientation\(/);
  assert.match(app, /language: layout\.composerLanguage/);
  assert.match(coach, /coachOrientationCopy\(/);
  assert.match(plan, /planOrientationCopy\(/);
  assert.match(resources, /resourcesOrientationCopy\(/);
});

test('work-surface clicks reveal objects instead of identity essays', () => {
  const plan = read('components/plan/CoachPlanView.tsx');
  const resources = read('components/resources/ResourcesWorkbenchView.tsx');
  const training = read('components/training/TrainingWorkbenchView.tsx');
  const app = read('app/App.tsx');

  assert.match(plan, /coach-plan-view__now-card/);
  assert.doesNotMatch(plan, /setEvidenceSurfaceOpen\(true\)/);
  assert.match(app, /openPlanComposerMode\("evidence"\)/);
  assert.match(resources, /selectedResource\.title/);
  assert.match(resources, /resources-knowledge__add-resource/);
  assert.doesNotMatch(app, /Trainer sandbox write authority has not been verified\./);
  assert.match(training, /training-current__verify-result/);
  assert.match(app, /预览不能验真实工作区文件/);
});
