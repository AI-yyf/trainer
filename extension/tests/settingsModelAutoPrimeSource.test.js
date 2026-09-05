'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('settings view quietly primes provider models when the saved connection needs a list refresh', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const settingsModelAutoPrimeKeyRef = useRef\(""\);/);
  assert.match(source, /const primeSettingsProviderModels = useCallback\(\(\) => \{/);
  assert.match(source, /type: "settings\/primeProviderModels"/);
  assert.match(source, /messages\.filter\(\(message\) => message\.type !== "operation\/status"\)/);
  assert.match(source, /if \(activeView !== "settings"\) \{\s*settingsModelAutoPrimeKeyRef\.current = "";/);
  assert.match(source, /providerDraftHasChanges \|\|/);
  assert.match(source, /data\.providerConfig\.modelListStatus === "error" &&/);
  assert.match(source, /data\.providerConfig\.modelRetryable !== false/);
  assert.match(source, /const needsPrime =/);
  assert.match(source, /settingsModelAutoPrimeKeyRef\.current = primeKey;/);
  assert.match(source, /primeSettingsProviderModels\(\);/);
});
