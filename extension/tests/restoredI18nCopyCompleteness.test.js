// Restored behavioral regression test. Original file: extension/tests/i18nCopyCompleteness.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: undefined
//
// Restoration: partial - 4 of 7 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "every locale carries the complete key set with no English fallback"
//       source-text guard: reads extension/webview/src/lib/i18n/copy.ts and copyTypes.ts and asserts on
//       its text (out of scope by rule).
//   - "App delegates non-English copy to the central resolver"
//       source-text guard: reads the webview App module sources (appModuleSource helper) and asserts on
//       its text (out of scope by rule).
//   - "provider and feedback surfaces use central copy keys without hardcoded labels"
//       source-text guard: reads extension/webview/src/components/common/UserFeedbackDisclosure.tsx and
//       lib/i18n/copy.ts and asserts on its text (out of scope by rule).
// Target: webview TypeScript loaded through the inlined loadTsModule helper (in-memory transpile).
// Note: extension/tests/helpers/loadTsModule.js (deleted in df0a3e2a) is inlined above the tests: same in-memory TypeScript loader, logic unchanged.
// Note: the require of extension/tests/helpers/appModuleSource.js (deleted in df0a3e2a) is dropped: only omitted source-guard tests used it.

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
// Inlined replacement for the deleted test helper extension/tests/helpers/loadTsModule.js:
// minimal CommonJS loader for the webview's TypeScript sources. Resolves relative
// imports recursively and delegates everything else to Node's require.
const { loadTsModule } = (() => {
  const fs = require('node:fs');
  const path = require('node:path');
  const vm = require('node:vm');

  const typescript = require(require.resolve('typescript', {
    paths: [path.resolve(__dirname, '..', 'webview')], // helpers/ depth removed: this file lives in extension/tests
  }));

  const WEBVIEW_ROOT = path.resolve(__dirname, '..', 'webview');

  function resolveRelative(fromDirectory, specifier) {
    const base = path.resolve(fromDirectory, specifier);
    const candidates = [
      `${base}.ts`,
      `${base}.tsx`,
      path.join(base, 'index.ts'),
      path.join(base, 'index.tsx'),
    ];
    const found = candidates.find((candidate) => fs.existsSync(candidate));
    if (!found) {
      throw new Error(`cannot resolve ${specifier} from ${fromDirectory}`);
    }
    return found;
  }

  function loadTsModule(entryPath, cache = new Map()) {
    const resolved = path.resolve(entryPath);
    const cached = cache.get(resolved);
    if (cached) {
      return cached.exports;
    }

    const source = fs.readFileSync(resolved, 'utf8');
    const output = typescript.transpileModule(source, {
      compilerOptions: {
        module: typescript.ModuleKind.CommonJS,
        target: typescript.ScriptTarget.ES2020,
        jsx: typescript.JsxEmit.ReactJSX,
      },
    }).outputText;

    const module = { exports: {} };
    cache.set(resolved, module);
    const localRequire = (specifier) => {
      if (specifier.startsWith('.')) {
        return loadTsModule(resolveRelative(path.dirname(resolved), specifier), cache);
      }
      return require(specifier);
    };

    vm.runInNewContext(
      output,
      { exports: module.exports, module, require: localRequire },
      { filename: resolved },
    );
    return module.exports;
  }

  return { loadTsModule, WEBVIEW_ROOT };
})();
const copySourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'copy.ts',
);
const copyTypesPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'copyTypes.ts',
);
const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const appUiCopyPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'appUiCopy.ts',
);

const expectedLanguages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
const baseLanguage = 'en-US';

function loadCopyKeySet() {
  const source = fs.readFileSync(copyTypesPath, 'utf8');
  const sourceFile = ts.createSourceFile(
    copyTypesPath,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS,
  );
  let copyKeyType;

  function visit(node) {
    if (ts.isTypeAliasDeclaration(node) && node.name.text === 'CopyKey') {
      copyKeyType = node.type;
      return;
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  assert.ok(copyKeyType, 'expected CopyKey type alias in copyTypes.ts');

  const keys = new Set();
  function collect(node) {
    if (ts.isUnionTypeNode(node)) {
      node.types.forEach(collect);
      return;
    }
    if (ts.isLiteralTypeNode(node) && ts.isStringLiteralLike(node.literal)) {
      keys.add(node.literal.text);
    }
  }

  collect(copyKeyType);
  assert.ok(keys.size > 0, 'expected CopyKey to declare at least one key');
  return keys;
}

function loadCopyModule() {
  return loadTsModule(copySourcePath);
}

// Values that are legitimately identical across locales: brand names, short
// loanwords, and protocol/algorithm acronyms. Any other English-identical
// string in a non-English table is treated as a missing translation.
const IDENTICAL_VALUE_ALLOWLIST = new Set([
  'Coach',
  'Trainer',
  'Chat',
  'Auto',
  'Standard',
  'Simple',
  'Direct',
  'Diagnostics',
  'Source',
  'System',
  'Status',
  'Offline',
  'Personal',
  'Action',
  'Agent',
  'Observation',
  'Architecture',
  'Training',
  'Workspace',
  'Flashcards',
  'Insight',
  'DDPG',
  'PPO',
  'MCTS',
  'Deep Q-Network',
  'OpenAI effort',
  'Anthropic budget',
  'Gemini thinkingConfig',
]);

const APP_UI_IDENTICAL_ALLOWLIST = new Set([
  'Personal',
  'Coach',
  'Auto',
  'Standard',
  'System',
  'Plan: {v}',
]);

test('appUiCopy carries real translations, not English placeholders', () => {
  const { APP_UI_TEXT } = loadTsModule(appUiCopyPath);
  const placeholderOnly = /^[^A-Za-z]*(\{[a-zA-Z]+\}[^A-Za-z]*)+$/;

  for (const key of Object.keys(APP_UI_TEXT)) {
    const row = APP_UI_TEXT[key];
    assert.ok(row[baseLanguage], `${key} must define ${baseLanguage}`);
    for (const language of expectedLanguages) {
      if (language === 'zh-CN') {
        // The Chinese source string is the record key; there is no zh-CN row.
        continue;
      }
      assert.ok(
        typeof row[language] === 'string' && row[language].trim(),
        `${language}.${key} must be non-empty`,
      );
      if (language === baseLanguage) {
        continue;
      }
      const value = row[language];
      if (value === row[baseLanguage]) {
        assert.ok(
          APP_UI_IDENTICAL_ALLOWLIST.has(value) || placeholderOnly.test(value),
          `${language}.${key} still carries the English placeholder: ${JSON.stringify(value)}`,
        );
      }
    }
  }
});

test('localized copy preserves every placeholder in the English base', () => {
  const { copyTable } = loadCopyModule();
  const base = copyTable[baseLanguage];
  const placeholder = /\{[a-zA-Z]+\}/g;

  for (const language of expectedLanguages) {
    if (language === baseLanguage) {
      continue;
    }
    const entry = copyTable[language];
    for (const key of Object.keys(base)) {
      const expected = (base[key].match(placeholder) ?? []).sort();
      const actual = (entry[key].match(placeholder) ?? []).sort();
      assert.deepEqual(actual, expected, `${language}.${key} must keep the English placeholders`);
    }
  }
});

test('settings connection copy stays neutral when the model is already ready', () => {
  const { resolveCopy } = loadCopyModule();
  const chineseCopy = resolveCopy('zh-CN');

  assert.equal(chineseCopy.settingsSetupSection, '模型连接');
  assert.equal(chineseCopy.configureProviderFirst, '还不能开始对话。请在“设置”里完成模型连接。');
  assert.equal(chineseCopy.networkError, '没能连上服务，请检查网络后再试');

  for (const language of expectedLanguages) {
    assert.notEqual(
      resolveCopy(language).settingsSetupSection.trim(),
      '',
      `${language} should provide a neutral settings connection heading`,
    );
  }
});

test('workspace admission copy makes the choice and its persistence boundary clear', () => {
  const { resolveCopy } = loadCopyModule();
  const chineseCopy = resolveCopy('zh-CN');
  const englishCopy = resolveCopy('en-US');

  assert.match(chineseCopy.workspaceAdmissionProjectFoundDetail, /读取项目结构.*不会修改文件/);
  assert.match(chineseCopy.onboardingProjectDiscoveryNote, /连接模型后.*当前项目.*不会修改文件/);
  assert.match(chineseCopy.workspaceAdmissionBrowseDetail, /不会启动项目对话.*不会保存学习记录/);
  assert.match(chineseCopy.workspaceAdmissionIgnoredDetail, /不会读取或管理/);
  assert.match(chineseCopy.workspaceAdmissionDelete, /删除项目/);
  assert.match(englishCopy.workspaceAdmissionProjectFoundDetail, /read the project structure.*never modifies files/i);
  assert.match(englishCopy.workspaceAdmissionBrowseDetail, /coaching and saved learning records stay off/i);
  assert.match(englishCopy.workspaceAdmissionDelete, /Delete project/i);
  assert.notEqual(englishCopy.workspaceAdmissionDelete, englishCopy.workspaceAdmissionIgnore);
});
