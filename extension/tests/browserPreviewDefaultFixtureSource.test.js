'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const previewEntryPath = path.resolve(__dirname, '..', 'webview', 'src', 'preview.ts');
const harnessPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'browserPreviewHarness.ts');
const sidecarPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'browserSidecar.ts');

test('standalone preview uses a fixture unless a live sidecar is explicitly requested', () => {
  const source = fs.readFileSync(previewEntryPath, 'utf8');

  assert.match(source, /const previewSearch = new URLSearchParams\(window\.location\.search\);/);
  assert.match(source, /previewSearch\.get\("live"\) === "1"/);
  assert.match(
    source,
    /if \(previewSearch\.get\("live"\) === "1"\) \{\s*installBrowserPreviewEnvironment\(\);\s*\} else \{\s*installBrowserPreviewHarness\(\);\s*\}/,
  );
});

test('live preview never becomes a fixture after sidecar bootstrap injects state', () => {
  const source = fs.readFileSync(sidecarPath, 'utf8');

  assert.match(source, /function isBrowserPreviewFixture\(\): boolean \{[\s\S]*?new URLSearchParams\(window\.location\.search\)[\s\S]*?previewSearch\.get\("live"\) === "1"[\s\S]*?return false;/);
  assert.match(source, /return Boolean\(window\.__TRAINER_BOOTSTRAP__\) && typeof window\.__TRAINER_BOOTSTRAP__ === "object";/);
});

test('ready and connected preview last tests carry the same workspace and profile scope the settings surface reads', () => {
  const source = fs.readFileSync(harnessPath, 'utf8');

  assert.match(source, /function bindPreviewWorkspaceScope\(/);
  assert.match(source, /function stampPreviewLastTest/);
  assert.match(source, /PREVIEW_FIXTURE_WORKSPACE_ID/);
  assert.match(source, /lastTestResult: stampPreviewLastTest\(bootstrap,/);
  assert.match(source, /bootstrap\.memory\.workspace\?\.workspaceId/);
  assert.match(source, /profileId: \(lastTest\.profileId as string \| undefined\) \?\? bootstrap\.providerConfig\.profileId/);
});

test('the deep provider audit case maps to an offline fixture instead of starting a live request', () => {
  const source = fs.readFileSync(harnessPath, 'utf8');

  assert.match(source, /function resolvePreviewScenarioCase\(/);
  assert.match(source, /case "deep-audit-provider-empty":\s*return "blocked";/);
  assert.match(
    source,
    /const requestedScenario = search\.get\("scenario"\) \?\? resolvePreviewScenarioCase\(search\.get\("case"\)\);/,
  );
});
