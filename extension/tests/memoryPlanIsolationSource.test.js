'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const planPath = path.resolve(__dirname, '..', 'webview', 'src', 'components', 'plan', 'CoachPlanView.tsx');
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('Plan visibly distinguishes global memory from isolated project memory', () => {
  const source = fs.readFileSync(planPath, 'utf8');
  assert.match(source, /const memoryScopeContext = \(/);
  assert.match(source, /Global memory/);
  assert.match(source, /Current project memory/);
  assert.match(source, /Connected/);
  assert.match(source, /Isolated/);
  assert.match(source, /Project evidence stays here first/);
  assert.match(source, /memoryScopeContext/);
});

test('Plan still receives authoritative global plan and current project link state', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(source, /globalPlan=\{data\.globalPlan\}/);
  assert.match(source, /projectPlanLink=\{data\.projectPlanLink\}/);
});
