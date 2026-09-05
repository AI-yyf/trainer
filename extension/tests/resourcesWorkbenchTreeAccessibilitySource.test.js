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
  assert.match(source, /type="checkbox"[\s\S]*?tabIndex=\{-1\}/);
  assert.match(source, /event\.key === "ArrowRight"[\s\S]*?onMoveTreeFocus\(firstChildId\)/);
  assert.match(source, /event\.key === "ArrowLeft"[\s\S]*?onMoveTreeFocus\(parentId\)/);
  assert.match(source, /const nextIndex = Math\.min\(Math\.max\(currentIndex \+ delta, 0\), items\.length - 1\);/);
});

test('Resources lets its workspace tree fill the unused primary panel area', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.match(source, /resources-knowledge--workspace-tree/);
  assert.match(
    styles,
    /\.resources-knowledge--workspace-tree > \.resources-knowledge__tree\s*\{[\s\S]*?flex: 1 1 0;[\s\S]*?min-height: 0;[\s\S]*?max-height: none;/,
  );
  assert.doesNotMatch(styles, /\.resources-knowledge--workspace-tree\.is-empty/);
  assert.doesNotMatch(source, /isResourceLibraryEmpty/);
  assert.match(
    styles,
    /\.resources-knowledge--workspace-tree\.is-detail-open > \.resources-knowledge__tree\s*\{[\s\S]*?flex: 0 1 auto;[\s\S]*?min-height: 0;[\s\S]*?max-height: min\(46vh, 420px\);/,
  );
  const detailStart = source.indexOf('className="resources-knowledge__detail"');
  const treeStart = source.indexOf('className="resources-knowledge__tree"');
  assert.ok(detailStart >= 0, 'expected selected resource detail');
  assert.ok(treeStart >= 0 && detailStart > treeStart, 'expected the file list to precede the selected preview');
  assert.doesNotMatch(source, /className="resources-knowledge__more"/);
  assert.match(source, /resources-library-tree__trash/);
  assert.match(source, /MessageRichContent/);
  assert.match(source, /previewKind === "markdown"/);
  assert.match(source, /function pickInitialResourceId\(/);
  assert.match(source, /pickInitialResourceId\(resources, initialResourceContextIds, sandboxPreviewInput\)/);
  assert.match(
    styles,
    /\.resources-library-tree__node strong\s*\{[\s\S]*?white-space:\s*normal;/,
  );
  assert.match(
    styles,
    /\.resources-library-tree__node\s*\{[\s\S]*?grid-template-columns: 18px 18px minmax\(0, 1fr\) auto;/,
  );
  assert.doesNotMatch(
    styles,
    /\.resources-knowledge__tree\s*\{[\s\S]*?order:\s*1;/,
  );
});

test('Resources keeps complete local copy for every supported workbench language', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');

  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(source, new RegExp(`"${language}"|${language === 'zh-CN' ? 'zh:' : language === 'en-US' ? 'en:' : `"${language}":`}`));
  }
  assert.match(source, /resourceTextLocaleOverrides\[language\]\[key\]/);
  assert.match(source, /deleteConfirmation/);
});
