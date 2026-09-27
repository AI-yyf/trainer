'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const helpersSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'composerModelHelpers.ts',
);

test('settings view quietly primes provider models when the saved connection needs a list refresh', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  // §四十八: the prime decision internals live in lib/composerModelHelpers.ts.
  const helpers = fs.readFileSync(helpersSourcePath, 'utf8');

  assert.match(source, /const settingsModelAutoPrimeKeyRef = useRef\(""\);/);
  assert.match(source, /const primeSettingsProviderModels = useCallback\(\(\) => \{/);
  assert.match(source, /type: "settings\/primeProviderModels"/);
  assert.match(source, /messages\.filter\(\(message\) => message\.type !== "operation\/status"\)/);
  assert.match(helpers, /export function settingsModelAutoPrimeDecision/);
  assert.match(helpers, /providerDraftHasChanges \|\|/);
  assert.match(helpers, /provider\.modelListStatus === "error" &&/);
  assert.match(helpers, /provider\.modelRetryable !== false/);
  assert.match(helpers, /const needsPrime =/);
  assert.match(source, /settingsModelAutoPrimeDecision\(\s*data\.providerConfig,\s*providerDraftHasChanges,/);
  assert.match(source, /settingsModelAutoPrimeKeyRef\.current = decision\.primeKey;/);
  assert.match(source, /primeSettingsProviderModels\(\);/);
});
