'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const settingsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

test('template setup carries a host focus request into the Settings API key field', () => {
  const app = readAppModuleSource();
  const settings = fs.readFileSync(settingsPath, 'utf8');
  // Round 2: the counter lives in the provider-connection controller; App
  // requests an increment through the controller action.
  const controllerPath = path.resolve(
    __dirname,
    '..',
    'webview',
    'src',
    'app',
    'useProviderConnectionController.ts',
  );
  const controller = fs.readFileSync(controllerPath, 'utf8');

  assert.match(controller, /const \[providerApiKeyFocusRequest, setProviderApiKeyFocusRequest\] = useState\(0\);/);
  assert.match(
    app,
    /resolvedMessage\.type === "ui\/restoreView"\s*&&\s*resolvedMessage\.payload\.focusProviderApiKey/,
  );
  assert.match(app, /requestProviderApiKeyFocus\(\);/);
  assert.match(controller, /setProviderApiKeyFocusRequest\(\(request\) => request \+ 1\);/);
  // §props-debt redirect: the focus counter still lives in App's controller
  // instance, but the settings boundary now receives it through the
  // App-published provider-connection context, so the JSX hand-off lives in
  // the settings shell. Regex preserved verbatim.
  assert.match(settings, /providerApiKeyFocusRequest=\{providerApiKeyFocusRequest\}/);
  assert.match(settings, /providerApiKeyFocusRequest\?: number;/);
  assert.match(
    settings,
    /if \(!providerApiKeyFocusRequest\) \{\s*return;\s*\}[\s\S]*?setConnectionView\("edit"\);[\s\S]*?setProviderApiKeyFocusRequested\(true\);/,
  );
});
