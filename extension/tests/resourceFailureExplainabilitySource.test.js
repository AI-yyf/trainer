'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const workbenchSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const sharedHelperPath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'resourceFailureExplainability.ts',
);
const coreReexportPath = path.resolve(
  __dirname,
  '..',
  'src',
  'core',
  'resourceFailureExplainability.ts',
);
const sharedIndexPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'index.ts');
const orientationPath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'resourcesOrientationGovernance.ts',
);

test('shared helper exports classify + describe with required categories', () => {
  const helper = fs.readFileSync(sharedHelperPath, 'utf8');
  const reexport = fs.readFileSync(coreReexportPath, 'utf8');
  const index = fs.readFileSync(sharedIndexPath, 'utf8');

  assert.match(helper, /export type ResourceFailureCategory/);
  assert.match(helper, /bad_file/);
  assert.match(helper, /no_content/);
  assert.match(helper, /missing/);
  assert.match(helper, /sidecar_down/);
  assert.match(helper, /corrupt_pdf/);
  assert.match(helper, /index_failed/);
  assert.match(helper, /export function classifyResourceFailure/);
  assert.match(helper, /export function describeResourceFailureState/);
  assert.match(reexport, /classifyResourceFailure/);
  assert.match(reexport, /describeResourceFailureState/);
  assert.match(index, /resourceFailureExplainability/);
});

test('App sanitize path uses classifyResourceFailure + describeResourceFailureState', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  assert.match(source, /classifyResourceFailure/);
  assert.match(source, /describeResourceFailureState/);
  assert.match(source, /from ["']\.\.\/\.\.\/\.\.\/\.\.\/shared\/src\/resourceFailureExplainability["']/);
  assert.match(
    source,
    /classifyResourceFailure\(\s*\{\s*message:\s*message\.payload\.message,\s*connectionState/,
  );
  assert.match(source, /describeResourceFailureState\(\s*language,\s*category\s*\)/);
  assert.match(source, /category !== ["']unknown["']/);
  assert.match(source, /resourceOperationFailureMessage\(resourceOperationKind,\s*language\)/);
  assert.match(source, /data\.connection\.state/);
});

test('ResourcesWorkbenchView surfaces no_content explainability via shared helper', () => {
  const source = fs.readFileSync(workbenchSourcePath, 'utf8');
  assert.match(source, /classifyResourceFailure/);
  assert.match(source, /describeResourceFailureState/);
  assert.match(source, /qualityFlags:\s*resource\.qualityFlags/);
  assert.match(source, /category === ["']no_content["']/);
  assert.match(
    source,
    /describeResourceFailureState\(\s*language,\s*category\s*\)\.message/,
  );
});

test('resourcesOrientationGovernance prefers shared helper for failed+no_content why', () => {
  const source = fs.readFileSync(orientationPath, 'utf8');
  assert.match(source, /classifyResourceFailure/);
  assert.match(source, /describeResourceFailureState/);
  assert.match(source, /failureCategory === ["']no_content["']/);
});
