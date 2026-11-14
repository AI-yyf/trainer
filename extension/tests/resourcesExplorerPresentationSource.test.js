'use strict';

// The Resources surface is an Explorer-like file tree, not a metadata reader.
// These guards keep row clicks as native opens and keep the Material Icon
// Theme assets wired instead of regressing to generic pages.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const viewPath = path.join(
  root,
  'extension',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const iconAssetsPath = path.join(
  root,
  'extension',
  'webview',
  'src',
  'components',
  'resources',
  'resourceIconAssets.ts',
);
const iconDir = path.join(root, 'extension', 'webview', 'src', 'assets', 'resource-icons');
const commandPath = path.join(root, 'extension', 'src', 'commands', 'resourceCommands.ts');

test('resource row click opens VS Code and does not switch the sidebar to the Reader', () => {
  const view = fs.readFileSync(viewPath, 'utf8');
  const start = view.indexOf('const openResourceInVsCode =');
  const end = view.indexOf('const focusFirstImportMenuItem', start);
  assert.ok(start >= 0 && end > start, 'expected the openResourceInVsCode handler');
  const handler = view.slice(start, end);
  assert.match(handler, /onOpenResource\?\.\(resource\.id, \{ \.\.\.options/);
  assert.doesNotMatch(handler, /resource\.location\?\.line_start/);
  assert.doesNotMatch(handler, /setSelectedResourceId/);
  assert.doesNotMatch(handler, /setResourceDetail/);
  assert.match(view, /onClick=\{\(\) => onOpen\(node\.resource!\)\}/);
  assert.match(view, /event\.key === " "[\s\S]*?onOpen\(node\.resource!\);/);
});

test('resource tree uses the vendored Material Icon Theme assets', () => {
  const view = fs.readFileSync(viewPath, 'utf8');
  const assets = fs.readFileSync(iconAssetsPath, 'utf8');
  assert.match(view, /resourceIconUrl\(resource\)/);
  assert.match(view, /resourceFolderIconUrl/);
  assert.match(view, /resourceFolderOpenIconUrl/);
  assert.match(view, /data-resource-icon=\{resourceIconKey\(resource\)\}/);
  assert.match(assets, /material-icons?|Material Icon Theme/i);
  for (const asset of [
    'LICENSE',
    'folder-resource.svg',
    'folder-resource-open.svg',
    'markdown.svg',
    'pdf.svg',
    'url.svg',
    'zip.svg',
    'python.svg',
    'typescript.svg',
    'document.svg',
  ]) {
    assert.ok(fs.existsSync(path.join(iconDir, asset)), `missing resource icon ${asset}`);
  }
});

test('opening a resource editor tab resets the cursor to the top of the file', () => {
  const commands = fs.readFileSync(commandPath, 'utf8');
  assert.match(
    commands,
    /let editorLine = requestedLine \? requestedLine - 1 : 0/,
  );
  assert.match(commands, /preview: false/);
  assert.match(commands, /preserveFocus: false/);
});
