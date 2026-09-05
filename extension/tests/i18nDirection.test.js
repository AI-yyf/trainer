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

test('the provider synchronizes root language and direction while App keeps preview overrides isolated', () => {
  const contextSource = fs.readFileSync(contextSourcePath, 'utf8');
  const appSource = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(contextSource, /useLayoutEffect/);
  assert.match(contextSource, /document\.documentElement\.setAttribute\("lang", language\)/);
  assert.match(contextSource, /document\.documentElement\.setAttribute\("dir", direction\)/);
  assert.match(contextSource, /document\.body\?\.setAttribute\("dir", direction\)/);
  assert.match(contextSource, /direction: TextDirection/);
  assert.match(appSource, /const requestedDirection = search\.get\("dir"\)/);
  assert.match(appSource, /requestedDirection === "rtl" \|\| requestedDirection === "ltr"/);
  assert.match(appSource, /const previewDirectionOverride = isBrowserPreview/);
  assert.match(appSource, /resolveTextDirection\(layout\.composerLanguage\)/);
  assert.match(
    appSource,
    /<I18nProvider language=\{layout\.composerLanguage\} direction=\{uiDirection\}>/,
  );
  assert.match(appSource, /className="trainer-shell"[\s\S]*?lang=\{layout\.composerLanguage\}[\s\S]*?dir=\{uiDirection\}/);
});

test('RTL shell uses logical text direction while source code stays LTR', () => {
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');

  assert.match(stylesSource, /\.trainer-shell\[dir="rtl"\]\s*\{\s*direction:\s*rtl;/);
  assert.match(stylesSource, /\.trainer-shell\[dir="rtl"\][\s\S]*?text-align:\s*start;/);
  assert.match(stylesSource, /\.message-bubble-v2--assistant[\s\S]*?border-inline-start:/);
  assert.match(stylesSource, /\.trainer-shell :where\(pre, code, kbd, samp\)[\s\S]*?direction:\s*ltr;/);
});
