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

test('production App does not treat mockData or browserSidecar fixtures as host truth', () => {
  const app = read('app/App.tsx');
  const harness = read('lib/browserPreviewHarness.ts');
  const sidecar = read('lib/browserSidecar.ts');

  assert.doesNotMatch(app, /from ["'].*mockData["']/);
  assert.match(app, /isBrowserPreviewFixtureMode/);
  assert.match(sidecar, /function isBrowserPreviewFixtureMode\(\)/);
  assert.match(harness, /from ["']\.\/mockData["']/);
  assert.match(app, /lastTestOk: scopedProviderLastTest\?\.ok === true/);
});

test('conversation, settings, and training do not paint raw JSON, traceback, keys, or hidden reasoning as success', () => {
  const parts = read('components/coach/CoachMessageParts.tsx');
  const settings = read('components/settings/CoachSettingsView.tsx');
  const training = read('components/training/TrainingWorkbenchView.tsx');
  const sanitizer = read('errorSurfaceSanitizer.ts', sharedRoot);
  const reliabilityOps = read('operationReliabilityGovernance.ts', sharedRoot);

  assert.match(parts, /sanitizeErrorSurface/);
  assert.match(parts, /isAuthoritativeAck\(part\.result\)/);
  assert.doesNotMatch(parts, /renderJson\(part\.result\)/);
  assert.match(settings, /sanitizeErrorSurfaceText/);
  assert.match(training, /sanitizeErrorSurfaceText\(latestTrainingReliability\.error/);
  assert.match(sanitizer, /TRACEBACK_PATTERN/);
  assert.match(sanitizer, /Traceback/);
  assert.match(sanitizer, /KEY_SHAPED_PATTERN/);
  assert.match(sanitizer, /sk\|rk\|pk\|ak/);
  assert.match(sanitizer, /THINK_PATTERN/);
  assert.match(sanitizer, /export function isAuthoritativeAck/);
  assert.match(reliabilityOps, /phase === ["']acked["']/);
});

test('pending reliability is distinct from acked success in shipped training chrome', () => {
  const training = read('components/training/TrainingWorkbenchView.tsx');
  const reliability = read('trainingReliabilityGovernance.ts', sharedRoot);

  assert.match(reliability, /"acked"/);
  assert.match(reliability, /"pending"/);
  assert.match(reliability, /isTrainingReliabilityAuthoritativeSuccess/);
  assert.match(reliability, /isTrainingReliabilityInFlight/);
  assert.match(reliability, /This is not current until the sidecar writes the snapshot/);
  assert.match(training, /describeTrainingReliability/);
  assert.match(training, /latestTrainingReliability/);
  assert.doesNotMatch(training, /pending-plan-confirmation[\s\S]*?Card completed!/);
});
