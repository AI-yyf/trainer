'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const browserSidecarPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserSidecar.ts',
);
const settingsViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

test('browser preview detection honors the preview flag even when the VS Code shim exists', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    source,
    /window\.__TRAINER_BROWSER_PREVIEW__ === true \|\| !window\.acquireVsCodeApi/,
  );
});

test('production workbench does not treat mockData or browserSidecar fixtures as host truth', () => {
  const app = fs.readFileSync(appSourcePath, 'utf8');
  const sidecar = fs.readFileSync(browserSidecarPath, 'utf8');
  const settings = fs.readFileSync(settingsViewPath, 'utf8');

  assert.doesNotMatch(app, /from ["'].*mockData["']/);
  assert.match(app, /isBrowserPreviewFixtureMode/);
  assert.match(sidecar, /function isBrowserPreviewFixtureMode\(\)/);
  assert.match(sidecar, /previewSearch\.get\("live"\) === "1"/);
  assert.match(settings, /SUPPORTED_PROVIDER_PROTOCOLS/);
  assert.match(settings, /isNewApiConnectionType/);
  assert.doesNotMatch(settings, /SUPPORTED_PROVIDER_PROTOCOLS[^\n]*newapi_channel_conn/);
});

test('browserSidecar protocol defaults stay fail-closed for VS Code webview', () => {
  const sidecar = fs.readFileSync(browserSidecarPath, 'utf8');
  const settings = fs.readFileSync(settingsViewPath, 'utf8');
  const app = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(sidecar, /function browserPreviewMayUseProtocolCapabilityDefaults\(\)/);
  assert.match(
    sidecar,
    /typeof window\.acquireVsCodeApi === "function" &&\s*window\.__TRAINER_BROWSER_PREVIEW__ !== true/,
  );
  assert.match(sidecar, /function previewProtocolCapabilityDefaults\(/);
  assert.match(sidecar, /previewProtocolCapabilityDefaults\(protocol\)/);
  assert.doesNotMatch(settings, /defaultCapabilitiesForProtocol/);
  assert.doesNotMatch(settings, /from ["'].*browserSidecar["']/);
  assert.match(app, /lastTestOk: scopedProviderLastTest\?\.ok === true/);
  assert.match(
    app,
    /if \(isBrowserPreview\) \{\s*[\s\S]*?loadBrowserPreviewModule\(\)/,
  );
});

test('browser preview language URL overrides are applied once and choice buttons use one click path', () => {
  const app = fs.readFileSync(appSourcePath, 'utf8');
  const settings = fs.readFileSync(settingsViewPath, 'utf8');

  assert.match(app, /browserPreviewLocationOverridesAppliedRef = useRef\(false\)/);
  assert.match(
    app,
    /if \(browserPreviewLocationOverridesAppliedRef\.current\) \{\s*return;\s*\}/,
  );
  assert.match(app, /browserPreviewLocationOverridesAppliedRef\.current = true/);
  assert.doesNotMatch(settings, /onMouseUp=\{\(\) => onChange\?\.\(item\.value\)\}/);
  assert.match(settings, /onClick=\{\(\) => onChange\?\.\(item\.value\)\}/);
});
