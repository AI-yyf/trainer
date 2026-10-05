
// PR-7: styles.css is an @import aggregator; the real rules live in
// styles/sections/*.css. Read them concatenated in manifest order so
// assertions see the same bytes the browser gets after bundling.
function readStylesSource() {
  const fsMod = require('node:fs');
  const pathMod = require('node:path');
  const root = pathMod.resolve(__dirname, '..', 'webview', 'src');
  const manifest = JSON.parse(fsMod.readFileSync(
    pathMod.join(root, 'styles', 'sections', 'manifest.json'), 'utf8'));
  return manifest.map(
    (entry) => fsMod.readFileSync(pathMod.join(root, entry.file), 'utf8'),
  ).join('');
}

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

test('Resources toolbar stays reading-first: search plus one import entry, no batch controls', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const toolbarSource = sourceBlock(
    source,
    '<div className="resources-knowledge__actions"',
    '<div\n        className="resources-knowledge__tree"',
  );

  // Batch selection is fully removed from the library first screen.
  assert.doesNotMatch(source, /selectAllVisibleResources|clearResourceSelection/);
  assert.doesNotMatch(toolbarSource, /resources-knowledge__batch-actions/);
  assert.doesNotMatch(source, /resources-knowledge__refresh-button/);
  assert.match(toolbarSource, /resources-knowledge__add-resource/);
  assert.match(toolbarSource, /aria-haspopup="menu"/);
  assert.match(source, /<div className="resources-knowledge__toolbar">/);
});

test('Resources deletion confirms per resource and preserves recovery through the trash', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const requestDeleteSource = sourceBlock(
    source,
    'const requestResourceDelete =',
    'const confirmDeleteSelectedResources =',
  );
  const confirmDeleteSource = sourceBlock(
    source,
    'const confirmDeleteSelectedResources =',
    'const cancelDeleteSelectedResources =',
  );

  // One resource per request; the shared confirm flow still guards the write.
  assert.match(requestDeleteSource, /setDeleteConfirmationResourceIds\(\[resourceId\]\);/);
  assert.match(source, /Move this resource to Trash/);
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
});

test('Resources keeps its narrow toolbar and tree dense without reserving an empty workspace panel', () => {
  const viewSource = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const stylesSource = readStylesSource();

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
  assert.match(viewSource, /const path = restoreContext.previewPath \?\? restoreContext.sandboxPath/);
  assert.match(viewSource, /resources.find\(\(item\) => item.sandboxPath === path\)/);
  assert.match(viewSource, /setSelectedResourceId\(resource\?\.id \?\? null\)/);
  assert.match(viewSource, /standaloneSandboxPreview/);
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
