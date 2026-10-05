'use strict';

// §四十四: a module's failure localizes to its owning surface. Resource
// operation results only affect the Resources view; plan-state failures only
// render inside Learning; everything else stays global. This guard locks the
// surface-scoping mechanism in App.tsx: the union, the atomic helper, the
// host-status interception and the banner gate.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('operation message surface union and banner gate localize scoped messages to their own view', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(
    source,
    /type OperationMessageSurface = "global" \| "training" \| "plan" \| "resources";/,
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

test('setOperationMessage sets message and surface atomically with a global default', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(
    source,
    /const setOperationMessage = useCallback\(\s*\(message\?: OperationMessage, surface\?: OperationMessageSurface\) => \{[\s\S]*?setOperationMessageSurface\(nextSurface\);[\s\S]*?setRawOperationMessage\(/,
  );
  // Default keeps unscoped calls global; a later global message resets any scope.
  assert.match(
    source,
    /let nextSurface: OperationMessageSurface = "global";\s*if \(message\) \{\s*if \(surface\) \{\s*nextSurface = surface;/,
  );
  // Plan-state failures relayed by generic callers stay inside Learning.
  assert.match(
    source,
    /detectPlanRevisionConflict\(message\.message\) \|\|\s*parseLivePlanTaskGateMarker\(message\.message\)\s*\) \{\s*nextSurface = "plan";/,
  );
});

test('host resource and plan statuses are intercepted before the store banner write', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(
    source,
    /const hostSurfaceScope: OperationMessageSurface \| undefined =\s*detectPlanRevisionConflict\(message\.payload\.message\) \|\|\s*parseLivePlanTaskGateMarker\(message\.payload\.message\)\s*\? "plan"\s*: resourceOperationStatus && resourceOperationStatus\.kind !== "search"\s*\? "resources"\s*: undefined;/,
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
