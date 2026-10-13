'use strict';

// §四十四: a module's failure localizes to its owning surface. Resource
// operation results only affect the Resources view; plan-state failures only
// render inside Learning; everything else stays global. This guard locks the
// surface-scoping mechanism: the union and the pure attribution rules live in
// lib/operationMessageGovernance.ts (extracted from App.tsx); App keeps the
// atomic banner write, the host-status interception and the banner gate.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const governancePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'operationMessageGovernance.ts',
);
// Round 2: the surface moved into the store's single banner channel and the
// banner interaction layer into the operation-status controller.
const storePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'useWorkbenchState.ts');
const statusControllerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'useOperationStatusController.ts',
);

test('operation message surface union and banner gate localize scoped messages to their own view', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const store = fs.readFileSync(storePath, 'utf8');
  const controller = fs.readFileSync(statusControllerPath, 'utf8');

  // The union lives in the governance module; the store carries message and
  // surface together, and the controller owns the gate rule.
  assert.match(
    source,
    /type OperationMessageSurface,/,
  );
  assert.match(
    store,
    /operationMessageSurface: OperationMessageSurface;/,
  );
  assert.match(
    controller,
    /operationMessageSurface === "global" \|\| operationMessageSurface === activeView/,
  );
  // The global banner renders only when the message is visible on the active view.
  assert.match(source, /\{operationMessage && operationMessageVisible \? \(/);
  assert.doesNotMatch(
    source,
    /operationMessageSurface === "training" && activeView !== "training"/,
  );
});

test('setOperationMessage writes message and surface atomically through the governance module', () => {
  const controller = fs.readFileSync(statusControllerPath, 'utf8');
  const store = fs.readFileSync(storePath, 'utf8');

  // One atomic entry point: surface attribution and failure sanitization both
  // come from the pure module; the controller then writes message + surface
  // through the store's single channel.
  assert.match(controller, /resolveOperationMessageSurface\(message\?\.message, surface\)/);
  assert.match(
    store,
    /setOperationMessage: \(operationMessage, surface\) =>\s*set\(operationBannerState\(operationMessage, surface\)\)/,
  );
  assert.match(store, /operationMessageSurface: resolveOperationMessageSurface\(operationMessage\?\.message, surface\)/);
  const { load } = require('./templateAssertions');
  const { resolveOperationMessageSurface } = load('lib/operationMessageGovernance.ts');
  assert.equal(resolveOperationMessageSurface({ message: 'Formal plan revision changed', planStateFailure: true }), 'plan');
  assert.equal(resolveOperationMessageSurface({ message: 'Later ordinary notice' }), 'global');
  assert.equal(resolveOperationMessageSurface({ message: 'Verify failure', explicitSurface: 'training' }), 'training');
});

test('host resource and plan statuses are intercepted before the store banner write', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const store = fs.readFileSync(storePath, 'utf8');

  assert.match(source, /const hostSurfaceScope = resolveOperationMessageSurface\(/);
  assert.match(source, /resourceOperation: Boolean\(resourceOperationStatus && resourceOperationStatus\.kind !== "search"\)/);
  // The scope derived from the RAW message travels into the store write
  // atomically with the message; stream-scoped non-errors keep the banner's
  // previous scope (no explicit surface).
  assert.match(
    source,
    /if \(!\(message\.payload\.surface === "stream" && message\.payload\.tone !== "error"\)\) \{\s*hostOperationSurface = hostSurfaceScope;\s*\}/,
  );
  assert.match(source, /\{ operationSurface: hostOperationSurface \}/);
  assert.match(store, /options\?\.operationSurface/);
});

test('resource operation feedback is scoped to the Library surface', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  // Browser preview upload / URL import outcomes (App-owned resource flows).
  assert.match(
    source,
    /message:\s*appUiCopy\(layout\.composerLanguage, "没有找到可导入的支持文件。"\),\s*\}, "resources"\);/,
  );
  assert.match(
    source,
    /message: recoverableFailureMessage\("upload", layout\.composerLanguage\),\s*\}, "resources"\);/,
  );
  assert.match(
    source,
    /appUiCopy\(layout\.composerLanguage, "网页已导入并完成索引。"\),\s*\}, "resources"\);/,
  );
});

test('plan freeze and plan composer feedback is scoped to the Learning surface', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(
    source,
    /message: livePlanUpdatePendingMessage\(layout\.composerLanguage\),\s*\}, "plan"\);/,
  );
  assert.equal(
    (source.match(/message: livePlanUpdatePendingMessage\(layout\.composerLanguage\),\s*\}, "plan"\);/g) ?? []).length,
    2,
  );
});

test('training verify notices stay card-owned; the following failure scopes itself by its own marker', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  // Round 2: the atomic channel has no surface pre-positioning — a notice must
  // carry its own surface with the message. The boundary notices are card
  // content, and the remote-verify failure that follows carries the training
  // marker, so it scopes itself to Training at host-message time.
  assert.match(source, /setTrainingVerifyNotice\(boundaryNotice\);/);
  assert.doesNotMatch(source, /setOperationMessageSurface\("training"\)/);
  assert.match(
    source,
    /planStateFailure: Boolean\(detectPlanRevisionConflict\(message\.payload\.message\) \|\| parseLivePlanTaskGateMarker\(message\.payload\.message\)\)/,
  );
});
