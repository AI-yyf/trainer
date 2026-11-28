// Restored behavioral regression test. Original file: extension/tests/i18nDirection.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: undefined
//
// Restoration: partial - 1 of 3 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "RTL shell uses logical text direction while source code stays LTR"
//       source-text guard: reads extension/webview/src/templates/AppShell.tsx (templateAssertions.read)
//       and asserts on its text (out of scope by rule).
//   - "the provider synchronizes root language and direction while App keeps preview overrides isolated"
//       fails at HEAD: The input did not match the regular expression /const previewDirectionOverride =
//       isBrowserPreview/. Input: / import {\n' +
// Target: webview TypeScript transpiled in memory with typescript.transpileModule.
// Note: the require of extension/tests/helpers/appModuleSource.js (deleted in df0a3e2a) is dropped: only omitted source-guard tests used it.

// PR-7: styles.css is an @import aggregator; the real rules live in
// styles/sections/*.css. Read them concatenated in manifest order so
// assertions see the same bytes the browser gets after bundling.
function readStylesSource() {
  const fsMod = require('node:fs');
  const pathMod = require('node:path');
  const root = pathMod.resolve(__dirname, '..', 'webview', 'src');
  const manifest = JSON.parse(fsMod.readFileSync(
    pathMod.join(root, 'styles', 'sections', 'manifest.json'), 'utf8'));
  return manifest.map(
    (entry) => fsMod.readFileSync(pathMod.join(root, entry.file), 'utf8'),
  ).join('');
}

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const typescript = require(require.resolve('typescript', {
  paths: [path.resolve(__dirname, '..', 'webview')],
}));

const directionSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'direction.ts',
);
const contextSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'context.tsx',
);
const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const stylesSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

function loadDirectionModule() {
  const source = fs.readFileSync(directionSourcePath, 'utf8');
  const output = typescript.transpileModule(source, {
    compilerOptions: {
      module: typescript.ModuleKind.CommonJS,
      target: typescript.ScriptTarget.ES2020,
    },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(output, { exports: module.exports, module }, { filename: directionSourcePath });
  return module.exports;
}

test('language direction recognizes future RTL locales without adding them to the copy table', () => {
  const { isRtlLanguage, resolveTextDirection } = loadDirectionModule();

  for (const language of ['ar', 'ar-EG', 'AR_sa', 'he-IL', 'fa-IR', 'ur-PK']) {
    assert.equal(resolveTextDirection(language), 'rtl', `${language} should use RTL`);
    assert.equal(isRtlLanguage(language), true, `${language} should be recognized as RTL`);
  }

  for (const language of ['zh-CN', 'en-US', 'ja-JP', 'xx-Unknown', '', undefined, null]) {
    assert.equal(resolveTextDirection(language), 'ltr', `${String(language)} should safely use LTR`);
    assert.equal(isRtlLanguage(language), false, `${String(language)} should not claim RTL`);
  }
});

