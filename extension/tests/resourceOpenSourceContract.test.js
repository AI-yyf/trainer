'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const sharedOpenPath = path.join(root, 'shared', 'src', 'resourceOpen.ts');
const viewPath = path.join(root, 'extension', 'webview', 'src', 'components', 'resources', 'ResourcesWorkbenchView.tsx');
const commandPath = path.join(root, 'extension', 'src', 'commands', 'resourceCommands.ts');
const appPath = path.join(root, 'extension', 'webview', 'src', 'app', 'App.tsx');

test('resource open source contract keeps URL browser behavior and local VS Code behavior aligned', () => {
  const shared = fs.readFileSync(sharedOpenPath, 'utf8');
  const view = fs.readFileSync(viewPath, 'utf8');
  const commands = fs.readFileSync(commandPath, 'utf8');
  const app = fs.readFileSync(appPath, 'utf8');

  assert.match(shared, /resource\.kind === "url"/);
  assert.match(shared, /kind: "browser"/);
  assert.match(shared, /kind: "vscode"/);
  assert.match(shared, /kind: "unavailable"/);
  assert.match(view, /resolveResourceOpenTarget\(selectedResource\)/);
  assert.match(view, /openInBrowser/);
  assert.match(view, /disabled=\{selectedResourceOpenTarget\.kind === "unavailable"\}/);
  assert.match(commands, /resolveResourceOpenTarget\(resource\)/);
  assert.match(commands, /vscode\.env\.openExternal/);
  assert.match(app, /type: "resource\/open"/);
});
