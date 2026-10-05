'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const planPath = path.resolve(__dirname, '..', 'webview', 'src', 'components', 'plan', 'CoachPlanView.tsx');
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('Plan renders no memory-scope diagram (Settings owns memory scope)', () => {
  const source = fs.readFileSync(planPath, 'utf8');
  assert.doesNotMatch(source, /memoryScopeContext/);
  assert.doesNotMatch(source, /coach-plan-view__memory-scope/);
  assert.doesNotMatch(source, /Global memory/);
  assert.doesNotMatch(source, /Current project memory/);
  assert.doesNotMatch(source, /Project evidence stays here first/);
});

test('Plan still receives authoritative global plan and current project link state', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(source, /globalPlan=\{data\.globalPlan\}/);
  assert.match(source, /projectPlanLink=\{data\.projectPlanLink\}/);
});
