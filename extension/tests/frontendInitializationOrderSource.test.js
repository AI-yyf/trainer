'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const settingsSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

test('App initializes browser preview flags before any callback or render branch reads them', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const declaration = source.indexOf('isBrowserPreview = inBrowserPreviewEnvironment();');
  const firstUse = source.search(/\bisBrowserPreview\b/);
  const fixtureDeclaration = source.indexOf('browserPreviewFixture =');
  const firstFixtureUse = source.search(/\bbrowserPreviewFixture\b/);

  assert.ok(declaration >= 0, 'browser preview declaration should remain explicit');
  assert.equal(firstUse, declaration, 'browser preview flag must not be read before initialization');
  assert.ok(fixtureDeclaration >= 0, 'fixture mode declaration should remain explicit');
  assert.equal(
    firstFixtureUse,
    fixtureDeclaration,
    'fixture mode flag must not be read before initialization',
  );
});

test('Coach settings normalizes model list status before model readiness branches', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');
  const declaration = source.indexOf('modelListStatus = provider.modelListStatus ?? "idle";');
  const firstUse = source.search(/\bmodelListStatus\b/);

  assert.ok(declaration >= 0, 'model list status declaration should remain explicit');
  assert.equal(firstUse, declaration, 'model list status must not be read before initialization');
});
