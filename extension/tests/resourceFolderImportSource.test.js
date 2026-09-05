'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const resourceCommandsPath = path.resolve(__dirname, '..', 'src', 'commands', 'resourceCommands.ts');

function sourceBlock(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);

  assert.ok(start >= 0, `expected source block starting with ${startMarker}`);
  assert.ok(end > start, `expected source block ending with ${endMarker}`);
  return source.slice(start, end);
}

test('folder imports send a stable logical collection path with every nested file upload', () => {
  const source = fs.readFileSync(resourceCommandsPath, 'utf8');
  const folderImportSource = sourceBlock(
    source,
    "} else if (sourceMode.value === 'folder') {",
    '} else {',
  );
  const uploadSource = sourceBlock(
    source,
    'async function uploadLocalFiles(',
    'async function uploadInlineResources(',
  );

  assert.match(folderImportSource, /discoveredFiles,\s*folderPath,/);
  assert.match(uploadSource, /collectionRoot\?: string/);
  assert.match(uploadSource, /collectionPathForFile\(filePath, collectionRoot\)/);
  assert.match(uploadSource, /collection_path: collectionPath/);
  assert.match(uploadSource, /collection_root: collectionRoot/);
});

test('logical collection paths are relative, portable, and reject paths outside the imported root', () => {
  const source = fs.readFileSync(resourceCommandsPath, 'utf8');
  const helperSource = sourceBlock(
    source,
    'function collectionPathForFile(',
    'async function uploadInlineResources(',
  );

  assert.match(helperSource, /path\.relative\(root, file\)/);
  assert.match(helperSource, /relativePath\.startsWith\(`\.\.\$\{path\.sep\}`\)/);
  assert.match(helperSource, /path\.isAbsolute\(relativePath\)/);
  assert.ok(helperSource.includes('.split(/[\\\\/]+/)'));
  assert.match(helperSource, /return \[rootName, \.\.\.relativeSegments\]\.join\('\/'\)/);
});
