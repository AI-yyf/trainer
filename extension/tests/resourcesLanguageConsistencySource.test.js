'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const resourcesSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);

const resourcesInlineTextPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'segments',
  'resourcesInlineText.ts',
);

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function readResourcesInlineCopy() {
  // §十五: the zh/en base record (resourceText) and its locale overrides moved
  // verbatim into the i18n segment file; copy-content assertions slice there
  // while call-site assertions keep reading the view.
  return fs.readFileSync(resourcesInlineTextPath, 'utf8');
}

test('Resources owns fallback-safe library copy without retired cross-view labels', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');
  const inlineCopy = readResourcesInlineCopy();

  assert.match(inlineCopy, /const resourceText: Record<ResourceTextKey, \{ zh: string; en: string \}>/);
  assert.match(source, /function localize\(language: ComposerLanguage, key: ResourceTextKey\)/);
  assert.match(source, /searchPlaceholder/);
  assert.match(inlineCopy, /addResource: \{ zh: "\\u6dfb\\u52a0\\u8d44\\u6599", en: "Add resource" \}/);
  assert.match(inlineCopy, /"es-ES": \{[\s\S]*?addResource: "Agregar recurso"/);
  assert.match(inlineCopy, /"fr-FR": \{[\s\S]*?addResource: "Ajouter une ressource"/);
  assert.match(inlineCopy, /"de-DE": \{[\s\S]*?addResource: "Ressource hinzufugen"/);
  assert.match(inlineCopy, /"ja-JP": \{[\s\S]*?addResource:/);
  assert.match(inlineCopy, /"ko-KR": \{[\s\S]*?addResource:/);
  assert.match(inlineCopy, /"pt-BR": \{[\s\S]*?addResource: "Adicionar recurso"/);
  assert.match(source, /openInVsCode/);
  assert.match(inlineCopy, /sandboxBoundary/);
  assert.match(source, /function collectionLabel\(/);
  assert.match(source, /collectionSegmentPrefix/);
  assert.match(source, /webSnapshots/);
  assert.match(source, /localize\(language, "webSnapshots"\)/);
  assert.match(source, /captureWebSnapshot/);
  assert.doesNotMatch(source, /language === "zh-CN" \? "\\u94fe\\u63a5" : "Links"/);
  assert.match(source, /language === "zh-CN"/);
  assert.doesNotMatch(source, /resource(?:Coach|Plan|Training)ViewLabel/);
  assert.doesNotMatch(source, /Use in Coach/);
});

test('Resources localizes read-only, preview-mutation, and generic search failures in every supported language', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');
  const inlineCopy = readResourcesInlineCopy();
  const baseCopyStart = inlineCopy.indexOf('const resourceText:');
  const baseCopyEnd = inlineCopy.indexOf('const resourceTextLocaleOverrides:', baseCopyStart);

  assert.ok(baseCopyStart >= 0 && baseCopyEnd > baseCopyStart, 'expected the base Resources copy');
  const baseCopy = inlineCopy.slice(baseCopyStart, baseCopyEnd);
  for (const key of ['searchIncomplete', 'readOnlyNotice', 'browserPreviewMutationNotice']) {
    assert.match(baseCopy, new RegExp(`${key}:`));
  }

  for (const language of ['es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const start = inlineCopy.indexOf(`  "${language}": {`, baseCopyEnd);
    const end = inlineCopy.indexOf('\n  },', start);
    assert.ok(start >= 0 && end > start, `expected ${language} Resources copy`);
    const localeCopy = inlineCopy.slice(start, end);
    for (const key of ['searchIncomplete', 'readOnlyNotice', 'browserPreviewMutationNotice']) {
      assert.match(localeCopy, new RegExp(`${key}:`), `${language} must localize ${key}`);
    }
  }

  assert.match(source, /return localize\(language, "readOnlyNotice"\);/);
  assert.match(source, /localize\(language, "searchFailed"\)/);
  assert.match(source, /!canWriteResources \|\| isBrowserPreview \|\| !onDeleteResources/);
  assert.match(source, /!canWriteResources \|\|\s*isBrowserPreview \|\|\s*!onRestoreResources/);
  assert.match(source, /isBrowserPreview\s*\? localize\(language, "browserPreviewMutationNotice"\)/);
});

test('Resources localizes review-card handoff actions and replaces duplicate generation with the current training', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');
  const inlineCopy = readResourcesInlineCopy();

  assert.match(inlineCopy, /createReviewCard: \{ zh: "\\u751f\\u6210\\u590d\\u4e60\\u5361", en: "Create review card" \}/);
  assert.match(inlineCopy, /openCurrentTraining: \{ zh: "\\u67e5\\u770b\\u5f53\\u524d\\u8bad\\u7ec3", en: "Open current training" \}/);
  const overridesStart = inlineCopy.indexOf('const resourceTextLocaleOverrides:');
  assert.ok(overridesStart >= 0, 'expected the Resources locale overrides');
  for (const language of ['es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const start = inlineCopy.indexOf(`  "${language}": {`, overridesStart);
    const end = inlineCopy.indexOf('\n  },', start);
    assert.ok(start >= 0 && end > start, `expected ${language} Resources copy`);
    const localeCopy = inlineCopy.slice(start, end);
    assert.match(
      localeCopy,
      /createReviewCard: "[^"]+"/,
      `${language} must localize the review-card action`,
    );
    assert.match(
      localeCopy,
      /openCurrentTraining: "[^"]+"/,
      `${language} must localize the current-training action`,
    );
  }

  assert.match(inlineCopy, /createReviewCard: "\u5fa9\u7fd2\u30ab\u30fc\u30c9\u3092\u4f5c\u308b"/);
  assert.match(inlineCopy, /openCurrentTraining: "\u73fe\u5728\u306e\u30c8\u30ec\u30fc\u30cb\u30f3\u30b0\u3092\u958b\u304f"/);
  assert.match(source, /return localize\(language, "createReviewCard"\);/);
  assert.match(source, /localize\(language, "openCurrentTraining"\)/);
  assert.match(
    source,
    /const selectedResourceTrainingIsAvailable =\s*selectedResourceTrainingState\?\.phase === "ready"\s*\|\|\s*selectedResourceTrainingState\?\.phase === "not-current"/,
  );
  assert.match(source, /onClick: selectedResourceTrainingIsAvailable \? \(\) => onOpenTraining\?\.\(\) : startTrainingFromSelectedResource/);
});

test('Resources keeps host failure details out of ordinary search feedback', () => {
  const source = fs.readFileSync(resourcesSourcePath, 'utf8');
  const inlineCopy = readResourcesInlineCopy();

  assert.match(inlineCopy, /searchFailed: \{ zh: "\\u6682\\u65f6\\u65e0\\u6cd5\\u641c\\u7d22\\u8d44\\u6599\\uff0c\\u8bf7\\u7a0d\\u540e\\u91cd\\u8bd5\\u3002", en: "Couldn't search resources\. Try again\." \}/);
  assert.match(source, /label: localize\(language, "searchFailed"\),/);
  assert.match(source, /Promise\.resolve\(onSearchResources\(\{ query: trimmedQuery, requestId \}\)\)\.catch\(\(\) =>/);
  assert.match(source, /setSearchRequestState\(\{ phase: "failed", requestId \}\);/);
  assert.doesNotMatch(source, /searchFailure\.message/);
  assert.doesNotMatch(source, /error\.message/);
  assert.doesNotMatch(source, /searchFailed: .*\{message\}/);
});

test('app preserves the shared localized recovery copy for cross-view notices', () => {
  const source = readAppModuleSource();

  assert.match(source, /function localizeUiViewReferences\(/);
  assert.match(source, /localizeUiViewReferences\(\s*blockedComposerSetupMessage/);
  assert.match(source, /localizeUiViewReferences\(\s*blockedComposerPresenceMessage/);
});
