'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('Settings gemini protocol labels do not claim Google-native googleapis', () => {
  const protocols = fs.readFileSync(
    path.resolve(__dirname, '..', '..', 'shared', 'src', 'providerProtocols.ts'),
    'utf8',
  );
  const settings = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'components', 'settings', 'CoachSettingsView.tsx'),
    'utf8',
  );
  const matrix = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'components', 'settings', 'CapabilityMatrix.tsx'),
    'utf8',
  );

  assert.match(protocols, /not Google-native by default/);
  assert.match(settings, /非 Google 原生默认/);
  assert.match(settings, /not Google-native by default/);
  assert.match(settings, /不默认当作 Google 原生 googleapis/);
  assert.match(matrix, /非原生默认/);
  assert.doesNotMatch(settings, /googleapis\.google\.com/);
});
