'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

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
  const app = fs.readFileSync(appPath, 'utf8');
  const settings = fs.readFileSync(settingsPath, 'utf8');

  assert.match(app, /const \[providerApiKeyFocusRequest, setProviderApiKeyFocusRequest\] = useState\(0\);/);
  assert.match(
    app,
    /resolvedMessage\.type === "ui\/restoreView"\s*&&\s*resolvedMessage\.payload\.focusProviderApiKey/,
  );
  assert.match(app, /setProviderApiKeyFocusRequest\(\(request\) => request \+ 1\);/);
  assert.match(app, /providerApiKeyFocusRequest=\{providerApiKeyFocusRequest\}/);
  assert.match(settings, /providerApiKeyFocusRequest\?: number;/);
  assert.match(
    settings,
    /if \(!providerApiKeyFocusRequest\) \{\s*return;\s*\}[\s\S]*?setProviderDetailRequested\(true\);[\s\S]*?setProviderApiKeyFocusRequested\(true\);/,
  );
});
