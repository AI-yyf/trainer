'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const settingsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('Settings offers a direct sidecar restart and avoids duplicate model discovery actions', () => {
  const source = fs.readFileSync(settingsPath, 'utf8');

  assert.match(source, /onRestartSidecar\?: \(\) => void;/);
  assert.match(source, /function sidecarRestartCopy\(/);
  assert.match(
    source,
    /const canRestartSidecar =\s*providerFailureCategory === "sidecar_unavailable" && Boolean\(onRestartSidecar\);/,
  );
  assert.match(source, /canRestartSidecar\s*\? \{\s*\.\.\.sidecarRestartCopy\(language\),/);
  assert.match(source, /action: onRestartSidecar,/);
  assert.match(source, /const showSecondaryModelDiscoveryAction = !canFindDraftModels;/);
  assert.match(source, /\{showSecondaryModelDiscoveryAction \? \(/);
});

test('Settings routes the sidecar recovery action through the existing extension command', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /onRestartSidecar=\{\s*isBrowserPreview\s*\? undefined/);
  assert.match(source, /payload: \{ commandId: trainerCommands\.restartSidecar \}/);
});

test('provider errors retain a safe, actionable recovery message in Settings', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /function providerRecoveryMessage\(language: ComposerLanguage\)/);
  assert.match(source, /Check the service address, API key, and model name, then try again\./);
  assert.match(source, /if \(kind === "provider"\) \{\s*return providerRecoveryMessage\(language\);/);
  assert.match(
    source,
    /Boolean\(isProviderActionOverride \|\| settingsActionState\?\.targets\.includes\("provider"\)\)/,
  );
  assert.match(source, /\? providerRecoveryMessage\(language\)/);
});

test('browser preview keeps provider recovery context when actions resolve immediately', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const testProviderStart = source.indexOf('onTestProvider={() => {');
  const restartSidecarStart = source.indexOf('onRestartSidecar=', testProviderStart);

  assert.ok(testProviderStart >= 0, 'expected Settings provider-test handler');
  assert.ok(restartSidecarStart > testProviderStart, 'expected provider-test handler boundary');

  const testProviderHandler = source.slice(testProviderStart, restartSidecarStart);
  assert.match(testProviderHandler, /applyPreviewHostMessages\(messages, true\)/);
  assert.match(
    source,
    /\(messages: HostMessage\[\], isProviderAction = false\) => \{[\s\S]*?applyHostMessage\(message, isProviderAction\);/,
  );
  assert.match(
    source,
    /Boolean\(isProviderActionOverride \|\| settingsActionState\?\.targets\.includes\("provider"\)\)/,
  );
});
