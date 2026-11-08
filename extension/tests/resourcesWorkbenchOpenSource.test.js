'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const resourcesWorkbenchPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const browserPreviewHarnessPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewHarness.ts',
);

test('Resources opens library files in VS Code or the default app without an in-Trainer content pane', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');
  const appSource = readAppModuleSource();
  const resourcesStart = appSource.indexOf('<ResourcesWorkbenchView');
  const resourcesEnd = appSource.indexOf('/>', resourcesStart);
  const resourcesView = appSource.slice(resourcesStart, resourcesEnd);

  assert.match(
    source,
    /const openResourceInVsCode = \(\s*resource: ResourceRecord,\s*options\?: \{ openOriginal\?: boolean; openExternal\?: boolean; line\?: number \},\s*\) =>/,
  );
  assert.match(source, /onOpenResource\?\.\(resource\.id, \{ \.\.\.options/);
  assert.match(source, /onClick=\{\(\) => openResourceInVsCode\(selectedResource\)\}/);
  assert.match(source, /openInVsCode/);
  assert.match(source, /openWithDefaultApp/);
  assert.match(source, /<dl className="resources-knowledge__facts">/);
  assert.match(source, /resource\.status === "attention"/);
  assert.match(source, /<ResourceReader/);
  assert.match(source, /openInEditor=\{/);
  assert.match(source, /openExternally=\{/);

  // No Trainer-owned content preview lives in the library surface: no reader
  // document, no sandbox HTML/Markdown body, no automatic preview request.
  assert.doesNotMatch(source, /onPreviewResource/);
  assert.doesNotMatch(source, /selectedResourceDocument/);
  assert.doesNotMatch(source, /selectedResourcePreviewMode/);
  assert.doesNotMatch(source, /selectedResourcePreviewSummary/);
  assert.doesNotMatch(source, /autoPreviewedResourceRef/);
  assert.doesNotMatch(source, /sandboxPreview/);
  assert.doesNotMatch(source, /MessageRichContent/);
  assert.doesNotMatch(source, /resources-knowledge__content-preview/);
  assert.doesNotMatch(source, /resourcePreviewMode|resourcePreviewSummary/);

  assert.ok(resourcesStart >= 0, 'expected the Resources render call');
  assert.ok(resourcesEnd > resourcesStart, 'expected the Resources render call to close');
  assert.match(resourcesView, /onOpenResource=\{\(resourceId, options\) =>/);
  assert.doesNotMatch(resourcesView, /onPreviewResource=/);
  assert.doesNotMatch(resourcesView, /sandboxPreview=/);
  assert.doesNotMatch(resourcesView, /resourceDocument=/);
  assert.match(appSource, /type: "resource\/open",/);
  assert.doesNotMatch(appSource, /trainerCommands\.previewSandbox/);
});

test('resource detail does not revive any Trainer-owned document or media preview surface', () => {
  const source = fs.readFileSync(resourcesWorkbenchPath, 'utf8');

  assert.doesNotMatch(source, /resources-preview-workbench/);
  assert.doesNotMatch(source, /resource-preview-pane__/);
  assert.doesNotMatch(source, /AudioPreview|PdfPreview|DocxPreview|resourcePreviewBody/);
  assert.doesNotMatch(source, /resourceDocument/);
});

test('loaded resource fixture keeps readiness compatibility without a Reader body', () => {
  const harnessSource = fs.readFileSync(browserPreviewHarnessPath, 'utf8');
  const scenarioStart = harnessSource.indexOf('if (scenario === "resource-preview-loaded")');
  const scenarioEnd = harnessSource.indexOf('\n  if (scenario ===', scenarioStart + 1);
  const scenarioSource = harnessSource.slice(scenarioStart, scenarioEnd);

  assert.ok(scenarioStart >= 0, 'expected the loaded-resource fixture');
  assert.match(scenarioSource, /status: "ready",[\s\S]*?trustScore: 0\.92,[\s\S]*?freshness: "fresh",[\s\S]*?indexState: "indexed"/);
  assert.doesNotMatch(scenarioSource, /trustState:/);
});
