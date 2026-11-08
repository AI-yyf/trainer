'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const readerPath = path.resolve(__dirname, '..', 'webview', 'src', 'templates', 'ResourceReader.tsx');
const viewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);

test('ResourceReader exposes VS Code and default-app open actions', () => {
  const source = fs.readFileSync(readerPath, 'utf8');
  assert.match(source, /openInEditor\?: TemplateAction;/);
  assert.match(source, /openExternally\?: TemplateAction;/);
  assert.match(source, /data-reader-open=\{kind as string\}/);
  assert.match(source, /className="template-reader-open-actions"/);
});

test('Resources wires the reader actions to the host open command', () => {
  const source = fs.readFileSync(viewPath, 'utf8');
  assert.match(source, /openInEditor=\{/);
  assert.match(source, /openExternally=\{/);
  assert.match(source, /localize\(language, "openInVsCode"\)/);
  assert.match(source, /localize\(language, "openWithDefaultApp"\)/);
  assert.match(source, /openResourceInVsCode\(selectedResource, \{ openExternal: true \}\)/);
});
