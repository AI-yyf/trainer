'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const copyPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'resourceComposerCopy.ts',
);

test('Resources composer uses complete eight-language copy instead of a Chinese-or-English branch', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const copySource = fs.readFileSync(copyPath, 'utf8');
  const start = appSource.indexOf('  const resourceComposerModes = useMemo');
  const end = appSource.indexOf('  const activeResourcesComposerMode =', start);

  assert.ok(start >= 0 && end > start, 'expected the Resources composer mode block');
  const modesSource = appSource.slice(start, end);
  assert.match(appSource, /import \{ resolveResourceComposerCopy \} from "\.\.\/lib\/i18n\/resourceComposerCopy";/);
  assert.match(copySource, /const resourceComposerCopy: Record<ComposerLanguage, ResourceComposerCopy> = \{/);
  assert.match(copySource, /export function resolveResourceComposerCopy\(language: ComposerLanguage\)/);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(copySource, new RegExp(`"${language}": \\{`));
  }
  for (const mode of ['locate', 'download', 'organize', 'cards']) {
    assert.match(copySource, new RegExp(`${mode}: \\{`));
  }

  assert.match(modesSource, /const resourceComposerText = resolveResourceComposerCopy\(layout\.composerLanguage\);/);
  assert.match(modesSource, /const locateMode = resourceComposerText\.modes\.locate;/);
  assert.match(modesSource, /const downloadMode = resourceComposerText\.modes\.download;/);
  assert.match(modesSource, /const organizeMode = resourceComposerText\.modes\.organize;/);
  assert.match(modesSource, /const cardsMode = resourceComposerText\.modes\.cards;/);
  assert.match(modesSource, /placeholder: locateMode\.placeholder,/);
  assert.match(modesSource, /accessibilityLabel: locateMode\.accessibilityLabel,/);
  assert.match(modesSource, /\.\.\.locateMode\.primaryPrompt,/);
  assert.match(modesSource, /\.\.\.locateMode\.secondaryPrompt,/);
  assert.doesNotMatch(modesSource, /const isZh =/);
});

test('Resources composer renders localized guidance and uses the active mode for the send label', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');

  assert.match(
    appSource,
    /activeView === "resources"\s*\?\s*activeResourcesComposerMode\.accessibilityLabel/,
  );
  assert.match(appSource, /activeView === "resources"\s*\?\s*activeResourcesComposerMode\.hint/);
  assert.match(appSource, /activeView === "resources"\s*\?\s*activeResourcesComposerMode\.summary/);
});
