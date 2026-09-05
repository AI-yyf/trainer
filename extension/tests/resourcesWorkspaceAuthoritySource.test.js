'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const resourcesPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);

test('Resources puts searchable knowledge records in a resource-only navigation tree before guarded sandbox state', () => {
  const source = fs.readFileSync(resourcesPath, 'utf8');

  assert.match(source, /resources-pane--library resources-knowledge/);
  assert.match(source, /className="resources-search resources-search--hero resources-knowledge__search"/);
  assert.match(source, /const visibleResources = useMemo/);
  assert.match(source, /function sourceChain\(resource: ResourceRecord\)/);
  assert.match(source, /resource\.trustState/);
  assert.match(source, /const selectedResourceFreshness = selectedResource\?\.freshness/);
  assert.match(source, /function resourceIndexNotice\(/);
  assert.match(source, /resource\.indexState/);
  assert.match(source, /function toSandboxNodePaths\(/);
  assert.match(source, /function resourceTreeSegments\(/);
  assert.match(source, /function buildResourceTree\(/);
  assert.match(source, /const resourceTree = useMemo/);
  assert.match(source, /role="tree"/);
  assert.match(source, /hasSearchQuery/);
  assert.match(source, /sandboxPreview\s*\?\s*\(/);

  const treeIndex = source.indexOf('className="resources-knowledge__tree"');
  const sandboxPreviewIndex = source.indexOf('{sandboxPreview ? (');
  assert.ok(treeIndex >= 0, 'expected a knowledge-resource tree');
  assert.ok(sandboxPreviewIndex > treeIndex, 'sandbox preview must remain after the knowledge tree');
});

test('the sandbox copy keeps the project-workspace boundary explicit', () => {
  const source = fs.readFileSync(resourcesPath, 'utf8');

  assert.match(source, /sandboxBoundary/);
  assert.match(source, /sandboxRootPath \?\? sandboxState\?\.rootPath/);
  assert.match(source, /linkedResourceCount/);
  assert.match(source, /totalFiles/);
  assert.match(source, /nodeKind === "directory"/);
  assert.doesNotMatch(source, /onOpenSandboxNode/);
  assert.doesNotMatch(source, /managedRoots/);
});
