'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const workbenchDataPath = path.resolve(__dirname, '..', 'src', 'core', 'workbenchData.ts');
const webviewTypesPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'types.ts');
const coreTypesPath = path.resolve(__dirname, '..', 'src', 'core', 'types.ts');
const sharedHelperPath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'planVerifyExplainability.ts',
);
const coreReexportPath = path.resolve(__dirname, '..', 'src', 'core', 'planVerifyExplainability.ts');

test('App wires describePlanVerifyAdvanceState on verifyPlanAdvance and Plan nextStep label', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const helper = fs.readFileSync(sharedHelperPath, 'utf8');
  const reexport = fs.readFileSync(coreReexportPath, 'utf8');

  assert.match(helper, /export function describePlanVerifyAdvanceState/);
  assert.match(helper, /export function planVerifyAdvanceStageLabel/);
  assert.match(reexport, /describePlanVerifyAdvanceState/);
  assert.match(source, /describePlanVerifyAdvanceState/);
  assert.match(source, /planVerifyAdvanceStageLabel/);
  assert.match(source, /planVerifyAdvanceAnnounceKeyRef/);
  assert.match(
    source,
    /describePlanVerifyAdvanceState\(\s*layout\.composerLanguage/,
  );
  assert.match(source, /setOperationMessage\(explained\)/);
  assert.match(source, /setTrainingVerifyNotice\(explained\.message\)/);
  assert.match(source, /setOperationMessageSurface\(activeView === "training" \? "training"/);
  assert.match(source, /latestTrainingFsrsStates/);
  assert.match(source, /verifyPlanAdvanceLabel/);
  assert.match(
    source,
    /verifyPlanAdvanceLabel\s*\?[\s\S]*verifyPlanAdvanceNext/,
  );
});

test('workbench maps latestTrainingFsrsStates into bootstrap memory workspace', () => {
  const workbenchData = fs.readFileSync(workbenchDataPath, 'utf8');
  const webviewTypes = fs.readFileSync(webviewTypesPath, 'utf8');
  const coreTypes = fs.readFileSync(coreTypesPath, 'utf8');

  assert.match(webviewTypes, /latestTrainingFsrsStates\?:/);
  assert.match(coreTypes, /latestTrainingFsrsStates\?:/);
  assert.match(webviewTypes, /interface TrainingFsrsStateView/);
  assert.match(coreTypes, /interface TrainingFsrsStateView/);
  assert.match(workbenchData, /function mapLatestTrainingFsrsStates/);
  assert.match(
    workbenchData,
    /latestTrainingFsrsStates:\s*mapLatestTrainingFsrsStates/,
  );
  assert.match(
    workbenchData,
    /latest_training_fsrs_states\s*\?\?\s*record\.latestTrainingFsrsStates/,
  );
  assert.match(workbenchData, /intervalDays:/);
  assert.match(workbenchData, /masteryScore:/);
});
