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
  const labelsStart = catalogSource.indexOf('export const PROVIDER_TEMPLATE_LABELS');
  assert.ok(labelsStart >= 0, 'PROVIDER_TEMPLATE_LABELS array not found');
  const labelsEnd = catalogSource.indexOf('\n];', labelsStart);
  assert.ok(labelsEnd > labelsStart, 'PROVIDER_TEMPLATE_LABELS array not terminated');
  const catalogBody = catalogSource.slice(labelsStart, labelsEnd);
  const catalogLabels = [...catalogBody.matchAll(/^\s*'(.+)',$/gm)].map((match) => match[1]);

  assert.ok(registryLabels.length >= 5, 'registry template labels were not parsed');
  assert.deepEqual(catalogLabels, registryLabels);
});

test('the settings template picker consumes the shared catalog through the host template command', () => {
  const settingsSource = fs.readFileSync(settingsViewSourcePath, 'utf8');
  const catalogSource = fs.readFileSync(catalogSourcePath, 'utf8');

  assert.match(settingsSource, /PROVIDER_TEMPLATE_GROUP_ORDER\.map/);
  assert.match(settingsSource, /PROVIDER_TEMPLATE_LABELS\.filter\(\s*\(templateLabel\) => PROVIDER_TEMPLATE_GROUPS\[templateLabel\] === group,?\s*\)/);
  assert.match(settingsSource, /onUseProviderTemplateLabel\?\.\(templateLabel\)/);
  assert.match(catalogSource, /PROVIDER_PROFILE_TEMPLATES\[\]\.label/);
});
