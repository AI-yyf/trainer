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
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').learning();
});
