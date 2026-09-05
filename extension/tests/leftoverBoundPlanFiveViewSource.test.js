'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const recoveryPath = path.resolve(
  __dirname,
  '..',
  '..',
  'server',
  'app',
  'memory',
  'workspace_recovery.py',
);
const routersPath = path.resolve(__dirname, '..', '..', 'server', 'app', 'api', 'routers.py');
const servicePath = path.resolve(__dirname, '..', '..', 'server', 'app', 'memory', 'service.py');
const orientationPath = path.resolve(
  __dirname,
  '..',
  '..',
  'server',
  'app',
  'pedagogy',
  'coach_orientation.py',
);
const repositoryPath = path.resolve(__dirname, '..', '..', 'server', 'app', 'db', 'repository.py');
const workbenchDataPath = path.resolve(__dirname, '..', 'src', 'core', 'workbenchData.ts');
const sharedOrientationPath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'planOrientationGovernance.ts',
);
const coachOrientationPath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'coachOrientationGovernance.ts',
);
const bundledRecoveryPath = path.resolve(
  __dirname,
  '..',
  'bundled',
  'server',
  'app',
  'memory',
  'workspace_recovery.py',
);
const bundledRoutersPath = path.resolve(
  __dirname,
  '..',
  'bundled',
  'server',
  'app',
  'api',
  'routers.py',
);
const bundledServicePath = path.resolve(
  __dirname,
  '..',
  'bundled',
  'server',
  'app',
  'memory',
  'service.py',
);
const bundledOrientationPath = path.resolve(
  __dirname,
  '..',
  'bundled',
  'server',
  'app',
  'pedagogy',
  'coach_orientation.py',
);
const bundledRepositoryPath = path.resolve(
  __dirname,
  '..',
  'bundled',
  'server',
  'app',
  'db',
  'repository.py',
);

test('leftover bound plan competing identity is omitted after generate on five views', () => {
  const recovery = fs.readFileSync(recoveryPath, 'utf8');
  const routers = fs.readFileSync(routersPath, 'utf8');
  const service = fs.readFileSync(servicePath, 'utf8');
  const orientation = fs.readFileSync(orientationPath, 'utf8');
  const repository = fs.readFileSync(repositoryPath, 'utf8');
  const workbenchData = fs.readFileSync(workbenchDataPath, 'utf8');
  const sharedOrientation = fs.readFileSync(sharedOrientationPath, 'utf8');
  const coachOrientation = fs.readFileSync(coachOrientationPath, 'utf8');
  const bundledRecovery = fs.readFileSync(bundledRecoveryPath, 'utf8');
  const bundledRouters = fs.readFileSync(bundledRoutersPath, 'utf8');
  const bundledService = fs.readFileSync(bundledServicePath, 'utf8');
  const bundledOrientation = fs.readFileSync(bundledOrientationPath, 'utf8');
  const bundledRepository = fs.readFileSync(bundledRepositoryPath, 'utf8');

  assert.match(recovery, /def leftover_bound_plan_competing_identity_labels\(/);
  assert.match(recovery, /leftover_plans/);
  assert.match(recovery, /def bound_plan_leftover_training_live_identity_updates\(/);
  assert.match(recovery, /competing_labels/);
  assert.match(recovery, /onboarding_request/);
  assert.match(repository, /def list_plans\(/);
  assert.match(service, /leftover_bound_plan_competing_identity_labels\(/);
  assert.match(service, /bound_plan_leftover_training_live_identity_updates\(/);
  assert.match(service, /competing_identity = leftover_bound_plan_competing_identity_labels\(/);
  assert.match(routers, /leftover_bound_plan_competing_identity_labels\(/);
  assert.match(routers, /leftover_plan_for_chrome/);
  assert.match(routers, /generated_plan_five_view_payload\(/);
  assert.match(routers, /leftover_plans=/);
  assert.match(routers, /hydrate_snapshot\(\s*response.snapshot,/);
  assert.match(recovery, /plan: Any \| None = None/);
  assert.match(recovery, /return not leftover_formal_plan_is_live_for_fill\(/);
  assert.match(workbenchData, /leftoverBoundPlanCompetingIdentityLabels\(/);
  assert.match(workbenchData, /function applyLeftoverBoundPlanFiveViewOmit</);
  assert.match(workbenchData, /leftoverFallbackTitleIsNotLiveForBoundPlan\(/);
  assert.match(orientation, /leftover_training_not_live_for_bound_plan/);
  assert.match(sharedOrientation, /export function leftoverBoundPlanCompetingIdentityLabels\(/);
  assert.match(workbenchData, /leftoverBoundPlanCompetingIdentityLabels\(/);
  assert.match(workbenchData, /function applyLeftoverBoundPlanFiveViewOmit</);
  assert.match(coachOrientation, /leftoverTrainingNotLiveForBoundPlan/);
  assert.match(bundledRecovery, /def leftover_bound_plan_competing_identity_labels\(/);
  assert.match(bundledRecovery, /leftover_plans/);
  assert.match(bundledService, /leftover_bound_plan_competing_identity_labels\(/);
  assert.match(bundledService, /competing_identity = leftover_bound_plan_competing_identity_labels\(/);
  assert.match(bundledRouters, /leftover_plan_for_chrome/);
  assert.match(bundledRouters, /generated_plan_five_view_payload\(/);
  assert.match(bundledRouters, /hydrate_snapshot\(\s*response.snapshot,/);
  assert.match(bundledRecovery, /return not leftover_formal_plan_is_live_for_fill\(/);
  assert.match(bundledOrientation, /leftover_training_not_live_for_bound_plan/);
  assert.match(bundledRepository, /def list_plans\(/);
});
