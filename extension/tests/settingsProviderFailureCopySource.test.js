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
const providerStatusPath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'providerStatus.ts',
);

test('Settings providerFailureCopy covers auth capability and network categories', () => {
  const source = fs.readFileSync(settingsPath, 'utf8');
  const providerStatus = fs.readFileSync(providerStatusPath, 'utf8');

  assert.match(source, /case "authentication_failed"/);
  assert.match(source, /case "provider_capability_test_failed"/);
  assert.match(source, /case "network"/);
  assert.match(source, /能力未通过|Capability failed/);

  assert.match(
    providerStatus,
    /provider_capability_test_failed: 'provider_capability_test_failed'/,
  );
  assert.match(providerStatus, /authentication_failed: 'invalid_key_or_permission'/);
  assert.match(providerStatus, /network: 'network'/);
  assert.match(providerStatus, /能力检查未通过/);
});
