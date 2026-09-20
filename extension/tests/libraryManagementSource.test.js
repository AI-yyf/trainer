'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const appSource = fs.readFileSync(
  path.join(root, 'extension', 'webview', 'src', 'app', 'App.tsx'),
  'utf8',
);
const resourcesSource = fs.readFileSync(
  path.join(
    root,
    'extension',
    'webview',
    'src',
    'components',
    'resources',
    'ResourcesWorkbenchView.tsx',
  ),
  'utf8',
);
const bridgeSource = fs.readFileSync(
  path.join(root, 'extension', 'src', 'core', 'webviewBridge.ts'),
  'utf8',
);

test('library deletion is correlated by an explicit acknowledgement instead of a timer', () => {
  assert.match(appSource, /message\.type === "library\/mutation"/);
  assert.match(appSource, /libraryPendingMutation/);
  assert.match(appSource, /const requestId = `library-mutation-/);
  assert.doesNotMatch(appSource, /setTimeout\(\(\) => requestLibraryOverview\(\), 600\)/);
  assert.match(bridgeSource, /type: 'library\/mutation'/);
});

test('library deletion requires confirmation and protects the active conversation', () => {
  assert.match(resourcesSource, /libraryDeleteConfirmation/);
  assert.match(resourcesSource, /Confirm delete/);
  assert.match(resourcesSource, /disabled=\{item\.isActive \|\| libraryPendingDeleteId === item\.id\}/);
  assert.match(resourcesSource, /Switch to another conversation first/);
});
