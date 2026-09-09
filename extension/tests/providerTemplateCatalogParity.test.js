'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const registrySourcePath = path.resolve(
  __dirname,
  '..',
  'src',
  'provider',
  'providerProfileRegistry.ts',
);
const catalogSourcePath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'providerTemplateCatalog.ts',
);
const settingsViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

test('webview template picker labels match the extension provider profile registry', () => {
  const registrySource = fs.readFileSync(registrySourcePath, 'utf8');
  const catalogSource = fs.readFileSync(catalogSourcePath, 'utf8');

  const templatesStart = registrySource.indexOf('export const PROVIDER_PROFILE_TEMPLATES');
  assert.ok(templatesStart >= 0, 'PROVIDER_PROFILE_TEMPLATES array not found');
  const templatesEnd = registrySource.indexOf('\n];', templatesStart);
  assert.ok(templatesEnd > templatesStart, 'PROVIDER_PROFILE_TEMPLATES array not terminated');
  const registryBody = registrySource.slice(templatesStart, templatesEnd);

  const registryLabels = [...registryBody.matchAll(/^\s{4}label: '(.+)',$/gm)].map(
    (match) => match[1],
  );
  const catalogLabels = [...catalogSource.matchAll(/^\s*'(.+)',$/gm)].map((match) => match[1]);

  assert.ok(registryLabels.length >= 5, 'registry template labels were not parsed');
  assert.deepEqual(catalogLabels, registryLabels);
});

test('the settings template picker consumes the shared catalog through the host template command', () => {
  const settingsSource = fs.readFileSync(settingsViewSourcePath, 'utf8');
  const catalogSource = fs.readFileSync(catalogSourcePath, 'utf8');

  assert.match(settingsSource, /PROVIDER_TEMPLATE_LABELS\.map\(\(templateLabel\) =>/);
  assert.match(settingsSource, /onUseProviderTemplateLabel\(templateLabel\)/);
  assert.match(catalogSource, /PROVIDER_PROFILE_TEMPLATES\[\]\.label/);
});
