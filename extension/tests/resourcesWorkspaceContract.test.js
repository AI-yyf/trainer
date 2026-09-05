'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const resourcesWorkbenchPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const browserHarnessPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewHarness.ts',
);
const workbenchStatePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'useWorkbenchState.ts',
);

function sourceBlock(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);

  assert.ok(start >= 0, `expected source block starting with ${startMarker}`);
  assert.ok(end > start, `expected source block ending with ${endMarker}`);
  return source.slice(start, end);
}

test('Resources bulk-select control stays scoped to the current visible search result set', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const selectAllSource = sourceBlock(
    source,
    'const selectAllVisibleResources =',
    'const clearResourceSelection =',
  );
  const toolbarSource = sourceBlock(
    source,
    '<div className="resources-knowledge__actions"',
    '<div\n        className="resources-knowledge__tree"',
  );

  assert.match(selectAllSource, /visibleResources\.forEach\(\(resource\) => next\.add\(resource\.id\)\)/);
  assert.doesNotMatch(selectAllSource, /\bresources\.forEach\(/);
  assert.match(toolbarSource, /onClick=\{selectAllVisibleResources\}/);
  assert.match(toolbarSource, /disabled=\{allVisibleResourcesSelected\}/);
  assert.match(toolbarSource, /onClick=\{clearResourceSelection\}/);
  assert.match(toolbarSource, /aria-live="polite"/);
});

test('Resources batch deletion confirms and preserves only the visible selection for recovery', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const requestDeleteSource = sourceBlock(
    source,
    'const deleteSelectedResources =',
    'const confirmDeleteSelectedResources =',
  );
  const confirmDeleteSource = sourceBlock(
    source,
    'const confirmDeleteSelectedResources =',
    'const restoreDeletedResources =',
  );

  assert.match(
    requestDeleteSource,
    /const resourceIds = \[\.\.\.selectedResourceIds\]\.filter\(\(resourceId\) => visibleResourceIds\.has\(resourceId\)\);/,
  );
  assert.match(requestDeleteSource, /setDeleteConfirmationResourceIds\(resourceIds\);/);
  assert.match(source, /Move \{count\} selected resources to Trash/);
  assert.match(confirmDeleteSource, /const resourceIds = deleteConfirmationResourceIds \?\? \[\];/);
  assert.match(confirmDeleteSource, /setPendingDeletedResourceIds\(resourceIds\);/);
  assert.match(confirmDeleteSource, /onDeleteResources\(resourceIds\)/);
  assert.match(source, /onRestoreResources\?: \(resourceIds: string\[\]\) => void \| Promise<void>;/);
  assert.match(source, /deletedResources\?: DeletedResource\[\];/);
  assert.doesNotMatch(source, /recentDeletedResourceIds/);
  assert.doesNotMatch(source, /window\.confirm/);
  assert.match(source, /role="alertdialog"/);
  assert.match(source, /onKeyDown=\{\(event\) => \{[\s\S]*?event\.key === "Escape"/);
  assert.match(source, /onClick=\{confirmDeleteSelectedResources\}/);
  assert.doesNotMatch(confirmDeleteSource, /clearResourceSelection\(/);
});

test('Resources keeps its narrow toolbar and tree dense without reserving an empty workspace panel', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const stylesSource = fs.readFileSync(stylesPath, 'utf8');

  assert.match(viewSource, /<div className="resources-knowledge__toolbar">/);
  assert.match(
    stylesSource,
    /\.resources-knowledge__toolbar\s*\{\s*display: grid;\s*grid-template-columns: minmax\(0, 1fr\) auto;\s*align-items: center;\s*gap: 6px;/,
  );
  assert.match(
    stylesSource,
    /\.resources-knowledge__actions\s*\{\s*display: flex;\s*align-items: center;\s*align-self: auto;\s*justify-content: flex-end;\s*gap: 2px;\s*min-height: 30px;/,
  );
  assert.match(
    stylesSource,
    /\.resources-knowledge__actions \.resources-knowledge__icon-button\s*\{\s*width: 30px;\s*height: 30px;/,
  );
  assert.match(
    stylesSource,
    /\.resources-knowledge__tree\s*\{\s*display: flex;\s*min-height: 0;\s*flex: 0 1 auto;[\s\S]*?max-height: min\(360px, 46vh\);\s*overflow-y: auto;/,
  );
  assert.match(
    stylesSource,
    /\.resources-knowledge__sandbox\s*\{\s*flex: 0 0 auto;/,
  );
  assert.match(
    stylesSource,
    /\.resources-knowledge--workspace-tree > \.resources-knowledge__tree\s*\{[\s\S]*?flex: 1 1 0;[\s\S]*?max-height: none;/,
  );
});

test('browser preview provides a four-level Resources fixture for multi-directory sidebar QA', () => {
  const source = fs.readFileSync(browserHarnessPath, 'utf8');
  const resourcePreviewSource = sourceBlock(
    source,
    'if (scenario === "resource-preview-loaded") {',
    'if (scenario === "done") {',
  );

  assert.match(resourcePreviewSource, /bootstrap\.resources = \[/);
  assert.match(
    resourcePreviewSource,
    /source: "H:\/trainer_final\/docs\/trainer-ideal\/resources\/coach\/patterns\/coach-patterns\.md"/,
  );
  assert.match(
    resourcePreviewSource,
    /sandboxPath: "H:\/trainer_final\/\.trainer\/sandbox\/knowledge\/coach\/patterns\/coach-patterns\.md"/,
  );
  assert.match(resourcePreviewSource, /relativePath: "knowledge\/coach\/patterns\/coach-patterns\.md"/);
});

test('Resources restores one requested surface and keeps it through ordinary view switches', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const stateSource = fs.readFileSync(workbenchStatePath, 'utf8');

  assert.match(viewSource, /surface: "detail" \| "sandbox";/);
  assert.match(viewSource, /restoreContext\?\.surface !== "detail" \|\| !restoreContext\.resourceId/);
  assert.match(viewSource, /setSelectedResourceId\(restoreContext\.resourceId\);/);
  assert.match(viewSource, /onRestoreContextChange\?: \(context\?: ResourceRestoreContext\) => void;/);
  assert.match(viewSource, /const setResourceDetail = \(resourceId: string \| null\) => \{/);
  assert.match(viewSource, /onRestoreContextChange\?\.\(\s*resourceId\s*\?/);
  assert.match(
    viewSource,
    /useEffect\(\(\) => \{\s*if \(restoreContext\?\.surface !== "sandbox"\) \{\s*return;\s*\}\s*setSelectedResourceId\(\(current\) => \(current \? null : current\)\);\s*\}, \[restoreContext\]\);/,
  );
  assert.match(viewSource, /onDebugVisibleFacts\?: \(facts: DebugVisibleResourcesFacts\) => void;/);
  assert.match(viewSource, /activeSurface,/);
  assert.match(viewSource, /resourceDetailVisible: Boolean\(selectedResource\)/);
  assert.match(viewSource, /singleWorkbenchSurface: true,/);
  assert.match(viewSource, /sandboxPaneVisible: activeSurface === "sandbox",/);
  assert.match(stateSource, /resourceSurface === "detail"/);
  assert.match(stateSource, /resourceId: payload\.resourceDetailId \?\? payload\.resourceId,/);
  assert.match(stateSource, /setResourceRestoreContext: \(context\?: ResourceRestoreContext\) => void;/);
  assert.match(
    stateSource,
    /setResourceRestoreContext: \(resourceRestoreContext\) => set\(\{ resourceRestoreContext \}\),/,
  );
  assert.match(
    stateSource,
    /resourceRestoreContext:\s*requestedView === "resources" \? resourceRestoreContext : state\.resourceRestoreContext,/,
  );
  assert.match(
    stateSource,
    /trainingRestoreContext:\s*requestedView === "training" \? trainingRestoreContext : state\.trainingRestoreContext,/,
  );
  assert.doesNotMatch(
    stateSource,
    /resourceRestoreContext:\s*nextLayout\.activeView === "resources" \? state\.resourceRestoreContext : undefined,/,
  );
});
