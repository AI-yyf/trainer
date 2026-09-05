'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const sessionCommandsSourcePath = path.resolve(
  __dirname,
  '..',
  'src',
  'commands',
  'sessionCommands.ts',
);

test('nextTask, specifyTask, and updatePlan return live-plan gate markers on 409 instead of swallowing', () => {
  const source = fs.readFileSync(sessionCommandsSourcePath, 'utf8');
  assert.match(source, /function livePlanTaskGateCommandFailure\(/);
  assert.match(source, /\[\[trainer-live-plan-task-gate:\$\{kind\}\]\]/);
  assert.match(source, /SidecarHttpError/);
  assert.match(source, /error\.statusCode !== 409/);
  assert.match(source, /leftover-not-live\|no live learning plan/);

  const specifyStart = source.indexOf('export async function specifyTaskCommand(');
  const nextStart = source.indexOf('export async function nextTaskCommand(');
  const saveStart = source.indexOf('export async function saveCoachSettingsCommand(');
  assert.ok(specifyStart >= 0 && nextStart > specifyStart && saveStart > nextStart);

  const specifyBody = source.slice(specifyStart, nextStart);
  const nextBody = source.slice(nextStart, saveStart);
  assert.match(specifyBody, /livePlanTaskGateCommandFailure\(error\)/);
  assert.match(specifyBody, /\/task\/specify/);
  assert.match(nextBody, /livePlanTaskGateCommandFailure\(error\)/);
  assert.match(nextBody, /\/task\/next/);
  assert.doesNotMatch(specifyBody, /ok:\s*true[\s\S]*catch\s*\(/);

  const runPlanStart = source.indexOf('async function runPlanCommand(');
  const runGlobalStart = source.indexOf('async function runGlobalPlanCommand(');
  assert.ok(runPlanStart >= 0 && runGlobalStart > runPlanStart);
  const runPlanBody = source.slice(runPlanStart, runGlobalStart);
  assert.match(runPlanBody, /\/plan\/update|path/);
  assert.match(runPlanBody, /livePlanTaskGateCommandFailure\(error\)/);
});
