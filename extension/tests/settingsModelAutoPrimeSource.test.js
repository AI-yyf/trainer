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

/**
 * P0 redirect: the settings model list no longer auto-primes. Model discovery
 * is an explicit network operation — the picker/settings expose an explicit
 * "refresh models" action, and pure UI activity (opening Settings, saving,
 * switching) must keep the /provider/models boundary counter at zero. The
 * former auto-prime machinery (settingsModelAutoPrimeDecision + dedup ref)
 * was therefore removed instead of being redirected.
 */
test('settings never auto-prime provider models; refresh stays an explicit action', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const helpers = fs.readFileSync(helpersSourcePath, 'utf8');

  // The auto-prime machinery is gone from App and the helpers.
  assert.doesNotMatch(source, /settingsModelAutoPrimeKeyRef/);
  assert.doesNotMatch(source, /primeSettingsProviderModels/);
  assert.doesNotMatch(source, /settings\/primeProviderModels/);
  assert.doesNotMatch(source, /composerModelAutoRefreshDecision/);
  assert.doesNotMatch(helpers, /export function settingsModelAutoPrimeDecision/);
  assert.doesNotMatch(helpers, /export function composerModelAutoRefreshDecision/);

  // Model listing still exists as a local fact + explicit refresh affordance.
  assert.match(source, /appUiCopy\(layout\.composerLanguage, "刷新模型"\)/);
});
