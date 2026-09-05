'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const harnessSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewHarness.ts',
);
const vscodeSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'vscode.ts',
);

test('browser preview harness persists updated preview state when the VS Code shim setState runs', () => {
  const source = fs.readFileSync(harnessSourcePath, 'utf8');
  const vscodeSource = fs.readFileSync(vscodeSourcePath, 'utf8');
  const installStart = source.indexOf('export function installBrowserPreviewHarness(): void {');
  const installEnd = source.indexOf('\n}', installStart);

  assert.ok(installStart >= 0 && installEnd > installStart, 'expected browser preview harness installer');
  const installer = source.slice(installStart, installEnd);

  assert.match(
    installer,
    /const previewStorageKey = previewStorageKeyForLocation\(\);/,
  );
  assert.match(
    installer,
    /window\.localStorage\.setItem\(previewStorageKey,\s*JSON\.stringify\(toPreviewPersistedState\(state\)\)\);/,
  );
  assert.match(
    vscodeSource,
    /window\.__TRAINER_BOOTSTRAP__ = \{ \.\.\.bootstrap, providerConfig: safeProviderConfig \};/,
  );
});
