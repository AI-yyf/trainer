'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const resourcesWorkbenchPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const browserPreviewHarnessPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewHarness.ts',
);

test('resource detail shows a governed indexed preview while delegating full rendering to VS Code', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');
  const resourcesStart = appSource.indexOf('<ResourcesWorkbenchView');
  const resourcesEnd = appSource.indexOf('/>', resourcesStart);
  const resourcesView = appSource.slice(resourcesStart, resourcesEnd);

  assert.match(source, /const openResourceInVsCode = \(resource: ResourceRecord\) =>/);
  assert.match(source, /onOpenResource\?\.\(resource\.id\)/);
  assert.match(source, /onClick=\{\(\) => openResourceInVsCode\(selectedResource\)\}/);
  assert.match(source, /openInVsCode/);
  assert.match(source, /<dl className="resources-knowledge__facts">/);
  assert.match(source, /function resourcePreviewMode\(resource: ResourceRecord, language: ComposerLanguage\)/);
  assert.match(source, /function resourcePreviewSummary\(resource: ResourceRecord\)/);
  assert.match(source, /resource\.status === "attention"/);
  assert.match(source, /selectedResourcePreviewMode/);
  assert.match(source, /selectedResourcePreviewSummary/);
  assert.match(source, /resources-knowledge__preview-summary/);
  assert.match(source, /sandboxPreview\?: SandboxPreview/);
  assert.match(source, /onPreviewResource\?: \(resourceId: string\)/);
  assert.match(source, /resources-knowledge__content-preview/);
  assert.match(source, /sandboxPreview\.content/);
  assert.match(source, /sandboxPreview\.html/);

  assert.ok(resourcesStart >= 0, 'expected the Resources render call');
  assert.ok(resourcesEnd > resourcesStart, 'expected the Resources render call to close');
  assert.match(resourcesView, /onOpenResource=\{\(resourceId\) =>/);
  assert.match(resourcesView, /sandboxPreview=\{leftoverSandboxPreviewNotLive \? undefined : data\.memory\.sandboxPreview\}/);
  assert.match(resourcesView, /onPreviewResource=/);
  assert.match(appSource, /type: "resource\/open",/);
  assert.match(appSource, /trainerCommands\.previewSandbox/);
});

test('resource detail does not revive any Trainer-owned document or media preview surface', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');

  assert.doesNotMatch(source, /resources-preview-workbench/);
  assert.doesNotMatch(source, /resource-preview-pane__/);
  assert.doesNotMatch(source, /AudioPreview|PdfPreview|DocxPreview|resourcePreviewBody/);
});

test('loaded resource preview keeps the legacy trusted-score fixture for readiness compatibility', () => {
  const harnessSource = fs.readFileSync(browserPreviewHarnessPath, 'utf8');
  const scenarioStart = harnessSource.indexOf('if (scenario === "resource-preview-loaded")');
  const scenarioEnd = harnessSource.indexOf('\n  if (scenario ===', scenarioStart + 1);
  const scenarioSource = harnessSource.slice(scenarioStart, scenarioEnd);

  assert.ok(scenarioStart >= 0, 'expected the loaded-resource preview fixture');
  assert.match(scenarioSource, /status: "ready",[\s\S]*?trustScore: 0\.92,[\s\S]*?freshness: "fresh",[\s\S]*?indexState: "indexed"/);
  assert.doesNotMatch(scenarioSource, /trustState:/);
});
