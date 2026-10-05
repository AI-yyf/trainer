
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

const resourcesSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

test('Resources prioritizes case-preserving logical collection paths', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');

  assert.match(source, /function collectionPathSegments\([\s\S]*?collectionRoot: string \| undefined/);
  assert.match(source, /const logicalCollectionSegments = collectionPathSegments\([\s\S]*?resource\.collectionPath,[\s\S]*?resource\.collectionRoot/);
  assert.match(source, /!String\(collectionRoot \?\? ""\)\.trim\(\)/);
  assert.match(source, /return logicalCollectionSegments\.slice\(0, -1\);/);
  assert.match(source, /idSegments\.push\(encodeURIComponent\(collectionSegment\)\);/);
  assert.doesNotMatch(source, /idSegments\.push\(normalizedSegment\)/);
});

test('Resources uses a single roving tree stop and standard parent-child navigation', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');

  assert.match(source, /function visibleTreeItemIds\(nodes: ResourceTreeNode\[\], expandedIds: Set<string>\)/);
  assert.match(source, /tabIndex=\{activeTreeItemId === node\.id \? 0 : -1\}/);
  assert.match(source, /data-resource-tree-item-id=\{node\.id\}/);
  // Reading-first tree: no checkboxes in the roving-tabindex tree.
  assert.doesNotMatch(source, /type="checkbox"/);
  assert.match(source, /event\.key === "ArrowRight"[\s\S]*?onMoveTreeFocus\(firstChildId\)/);
  assert.match(source, /event\.key === "ArrowLeft"[\s\S]*?onMoveTreeFocus\(parentId\)/);
  assert.match(source, /const nextIndex = Math\.min\(Math\.max\(currentIndex \+ delta, 0\), items\.length - 1\);/);
});

test('Resources lets its workspace tree fill the unused primary panel area', () => {
  // Product-level template contract replaces the previous layout grammar.
  const { read } = require('./templateAssertions');
  const source = read('components/resources/ResourcesWorkbenchView.tsx');
  for (const marker of ['<Library', '<ResourceReader', 'type="search"', 'onSelect={selectResource}', 'onRestore', 'onStartTrainingFromResource', 'openResourceInVsCode']) assert.ok(source.includes(marker), marker);
  assert.ok(!source.includes('didAutoSelectResource'));
  assert.ok(source.includes('onAskCoach([selectedResource.id])'));
});

test('Resources keeps complete local copy for every supported workbench language', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');

  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(source, new RegExp(`"${language}"|${language === 'zh-CN' ? 'zh:' : language === 'en-US' ? 'en:' : `"${language}":`}`));
  }
  assert.match(source, /resourceTextLocaleOverrides\[language\]\[key\]/);
  assert.match(source, /deleteConfirmation/);
});
