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

test('operation message surface union and banner gate localize scoped messages to their own view', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const governance = fs.readFileSync(governancePath, 'utf8');

  // The union and the pure surface rules moved to the governance module.
  assert.match(
    governance,
    /export type OperationMessageSurface = "global" \| "training" \| "plan" \| "resources";/,
  );
  assert.match(
    governance,
    /export function resolveOperationMessageSurface\(/,
  );
  assert.match(
    source,
    /const \[operationMessageSurface, setOperationMessageSurface\] = useState<OperationMessageSurface>\("global"\);/,
  );
  assert.match(
    source,
    /const operationMessageVisible =\s*operationMessageSurface === "global" \|\| operationMessageSurface === activeView;/,
  );
  // The global banner renders only when the message is visible on the active view.
  assert.match(source, /\{operationMessage && operationMessageVisible \? \(/);
  assert.doesNotMatch(
    source,
    /operationMessageSurface === "training" && activeView !== "training"/,
  );
});

test('setOperationMessage writes message and surface atomically through the governance module', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  // One atomic entry point: surface attribution and failure sanitization both
  // come from the pure module; App only performs the two state writes.
  assert.match(
    source,
    /const setOperationMessage = useCallback\(\s*\(message\?: OperationMessage, surface\?: OperationMessageSurface\) => \{\s*setOperationMessageSurface\(\s*resolveOperationMessageSurface\(message\?\.message, surface\),\s*\);\s*setRawOperationMessage\(/,
  );
  assert.match(
    source,
    /message \? sanitizeOperationFailureMessage\(message, layout\.composerLanguage\) : undefined,/,
  );
});

test('host resource and plan statuses are intercepted before the store banner write', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(
    source,
    /const hostSurfaceScope: OperationMessageSurface \| undefined =\s*detectAttestationUndelivered\(message\.payload\.message\)\s*\? "training"\s*: detectPlanRevisionConflict\(message\.payload\.message\) \|\|\s*parseLivePlanTaskGateMarker\(message\.payload\.message\)\s*\? "plan"\s*: resourceOperationStatus && resourceOperationStatus\.kind !== "search"\s*\? "resources"\s*: undefined;/,
  );
  assert.match(
    source,
    /hostSurfaceScope &&\s*!\(message\.payload\.surface === "stream" && message\.payload\.tone !== "error"\)\s*\) \{\s*setOperationMessageSurface\(hostSurfaceScope\);/,
  );
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

test('training verify pre-positioning keeps its existing surface behavior', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.equal(
    (source.match(/setOperationMessageSurface\("training"\);/g) ?? []).length,
    2,
  );
});
