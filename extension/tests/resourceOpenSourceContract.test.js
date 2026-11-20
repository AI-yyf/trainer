'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const root = path.resolve(__dirname, '..', '..');
const sharedOpenPath = path.join(root, 'shared', 'src', 'resourceOpen.ts');
const viewPath = path.join(root, 'extension', 'webview', 'src', 'components', 'resources', 'ResourcesWorkbenchView.tsx');
const commandPath = path.join(root, 'extension', 'src', 'commands', 'resourceCommands.ts');
const appPath = path.join(root, 'extension', 'webview', 'src', 'app', 'App.tsx');

test('resource open source contract routes library files through the VS Code editor', () => {
  const shared = fs.readFileSync(sharedOpenPath, 'utf8');
  const view = fs.readFileSync(viewPath, 'utf8');
  const commands = fs.readFileSync(commandPath, 'utf8');
  const app = readAppModuleSource();

  assert.match(shared, /resource\.kind === "url"/);
  assert.doesNotMatch(shared, /kind: "browser"/);
  assert.match(shared, /kind: "vscode"/);
  assert.match(shared, /kind: "unavailable"/);
  assert.match(view, /resolveResourceOpenTarget\(selectedResource\)/);
  assert.doesNotMatch(view, /openInBrowser|openWithDefaultApp/);
  assert.match(view, /disabled=\{!onOpenResource \|\| target\.kind === "unavailable"\}/);
  assert.match(commands, /resolveResourceOpenTarget\(resource\)/);
  assert.doesNotMatch(commands, /vscode\.env\.openExternal/);
  assert.match(app, /type: "resource\/open"/);
});
