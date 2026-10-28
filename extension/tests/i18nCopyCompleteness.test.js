'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { loadTsModule } = require('./helpers/loadTsModule');
const { readAppModuleSource } = require('./helpers/appModuleSource');

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

test('every locale carries the complete key set with no English fallback', () => {
  const source = fs.readFileSync(copySourcePath, 'utf8');
  assert.equal(source.includes('as unknown as CopyTable'), false, 'copyTable must not bypass completeness checks');
  assert.equal(source.includes('} satisfies CopyTable;'), true, 'copyTable must be checked against CopyTable');

  const { copyTable, resolveCopy } = loadCopyModule();
  const copyKeys = loadCopyKeySet();
  const languages = Object.keys(copyTable);

  assert.deepEqual(languages, expectedLanguages, 'expected the 8 declared languages in stable order');

  const baseEntry = copyTable[baseLanguage];
  assert.ok(baseEntry && Object.keys(baseEntry).length > 0, 'expected en-US to define the base key set');
  const baseKeys = Object.keys(baseEntry);
  const baseSet = new Set(baseKeys);
  assert.deepEqual(
    [...copyKeys].filter((key) => !baseSet.has(key)),
    [],
    'en-US must define every CopyKey directly',
  );
  assert.deepEqual(
    baseKeys.filter((key) => !copyKeys.has(key)),
    [],
    'en-US must not define keys outside CopyKey',
  );

  for (const language of expectedLanguages) {
    const entry = copyTable[language];
    assert.ok(entry, `missing language block: ${language}`);
    assert.deepEqual(
      Object.keys(entry),
      baseKeys,
      `${language} must define every English key in the same order`,
    );

    const extraKeys = Object.keys(entry).filter((key) => !baseSet.has(key));
    assert.deepEqual(extraKeys, [], `${language} should not introduce keys outside the English base`);

    for (const key of baseKeys) {
      assert.equal(typeof entry[key], 'string', `${language}.${key} must be a string`);
      assert.ok(entry[key].trim(), `${language}.${key} must be non-empty`);
      if (
        language !== baseLanguage &&
        entry[key] === baseEntry[key] &&
        baseEntry[key] !== copyTable['zh-CN'][key]
      ) {
        assert.ok(
          IDENTICAL_VALUE_ALLOWLIST.has(entry[key]),
          `${language}.${key} still falls back to English (${JSON.stringify(entry[key])})`,
        );
      }
    }
  }

  for (const language of expectedLanguages) {
    const resolvedCopy = resolveCopy(language);
    for (const key of copyKeys) {
      assert.equal(typeof resolvedCopy[key], 'string', `${language}.${key} should resolve to a string`);
      assert.ok(resolvedCopy[key].trim(), `${language}.${key} should resolve to non-empty copy`);
    }
  }
});

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

test('App delegates non-English copy to the central resolver', () => {
  const appSource = readAppModuleSource();

  for (const language of ['es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.equal(
      new RegExp(`["']${language}["']\\s*:\\s*englishCopy\\b`).test(appSource),
      false,
      `${language} must not be hardcoded to App's English copy`,
    );
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

test('provider and feedback surfaces use central copy keys without hardcoded labels', () => {
  // CapabilityMatrix.tsx (the capability* keys' last component consumer) was
  // removed as dead code in the visual polish round; the keys themselves were
  // swept from copy.ts in the platform round 2 dead-copy pass (zero consumers
  // verified by grep before removal).
  const feedbackSource = fs.readFileSync(path.resolve(__dirname, '..', 'webview', 'src', 'components', 'common', 'UserFeedbackDisclosure.tsx'), 'utf8');
  for (const source of [feedbackSource]) {
    assert.match(source, /resolveCopy/);
    assert.doesNotMatch(source, /language === ["']zh-CN["']/);
  }
  const copySource = fs.readFileSync(path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'copy.ts'), 'utf8');
  assert.doesNotMatch(copySource, /"capabilityChat"/, 'swept capability keys must not return via the CopyKey union');
  const { resolveCopy } = loadCopyModule();
  for (const language of expectedLanguages) {
    const copy = resolveCopy(language);
    for (const key of [
      'feedbackTooHard', 'feedbackPlanMismatch', 'feedbackDisclosureSummary',
      'feedbackRecording', 'feedbackRecorded',
    ]) {
      assert.ok(copy[key].trim(), `${language}.${key} should be non-empty`);
    }
  }
});

test('workspace admission copy makes the choice and its persistence boundary clear', () => {
  const { resolveCopy } = loadCopyModule();
  const chineseCopy = resolveCopy('zh-CN');
  const englishCopy = resolveCopy('en-US');

  assert.match(chineseCopy.workspaceAdmissionProjectFoundDetail, /加入 Trainer.*仅浏览.*忽略/);
  assert.match(chineseCopy.workspaceAdmissionBrowseDetail, /不会启动项目对话.*不会保存学习记录/);
  assert.match(chineseCopy.workspaceAdmissionIgnoredDetail, /不会读取或管理/);
  assert.match(chineseCopy.workspaceAdmissionDelete, /删除项目/);
  assert.match(englishCopy.workspaceAdmissionProjectFoundDetail, /add it to Trainer, browse it, or ignore it/i);
  assert.match(englishCopy.workspaceAdmissionBrowseDetail, /coaching and saved learning records stay off/i);
  assert.match(englishCopy.workspaceAdmissionDelete, /Delete project/i);
  assert.notEqual(englishCopy.workspaceAdmissionDelete, englishCopy.workspaceAdmissionIgnore);
});
