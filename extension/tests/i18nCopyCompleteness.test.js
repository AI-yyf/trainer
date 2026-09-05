'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');

const copySourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'i18n',
  'copy.ts',
);
const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

const expectedLanguages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
const baseLanguage = 'en-US';

function loadCopyTable() {
  const source = fs.readFileSync(copySourcePath, 'utf8');
  const sourceFile = ts.createSourceFile(copySourcePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  let tableNode;

  function unwrapExpression(expression) {
    let current = expression;
    while (ts.isAsExpression(current) || ts.isSatisfiesExpression(current) || ts.isParenthesizedExpression(current)) {
      current = current.expression;
    }
    return current;
  }

  function visit(node) {
    if (
      ts.isVariableDeclaration(node) &&
      node.name.getText(sourceFile) === 'copyTable' &&
      node.initializer &&
      ts.isObjectLiteralExpression(unwrapExpression(node.initializer))
    ) {
      tableNode = unwrapExpression(node.initializer);
      return;
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  assert.ok(tableNode, 'expected copyTable object literal in copy.ts');
  return { sourceFile, tableNode };
}

function getCopyKeys(sourceFile) {
  let copyKeyType;

  function visit(node) {
    if (ts.isTypeAliasDeclaration(node) && node.name.text === 'CopyKey') {
      copyKeyType = node.type;
      return;
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  assert.ok(copyKeyType, 'expected CopyKey type alias in copy.ts');

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
  const source = fs.readFileSync(copySourcePath, 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  }).outputText;
  const module = { exports: {} };

  vm.runInNewContext(output, { exports: module.exports, module }, { filename: copySourcePath });
  return module.exports;
}

test('English copy is a complete base and every locale resolves through it', () => {
  const source = fs.readFileSync(copySourcePath, 'utf8');
  assert.equal(source.includes('as unknown as CopyTable'), false, 'copyTable must not bypass completeness checks');
  assert.equal(source.includes('} satisfies CopyTable;'), true, 'copyTable must be checked against CopyTable');

  const { sourceFile, tableNode } = loadCopyTable();
  const copyKeys = getCopyKeys(sourceFile);
  const languages = [];
  const languageEntries = new Map();

  for (const entry of tableNode.properties) {
    if (!ts.isPropertyAssignment(entry) || !ts.isStringLiteralLike(entry.name)) {
      continue;
    }
    const language = entry.name.text;
    assert.ok(
      ts.isObjectLiteralExpression(entry.initializer),
      `expected ${language} to map to an object literal`,
    );
    languages.push(language);

    const keys = [];
    const values = new Map();
    for (const item of entry.initializer.properties) {
      if (!ts.isPropertyAssignment(item)) {
        continue;
      }
      const key = item.name.getText(sourceFile);
      assert.ok(
        ts.isStringLiteralLike(item.initializer),
        `expected ${language}.${key} to be a string literal`,
      );
      assert.notEqual(item.initializer.text.trim(), '', `expected ${language}.${key} to be non-empty`);
      keys.push(key);
      values.set(key, item.initializer.text);
    }
    languageEntries.set(language, { keys, values });
  }

  assert.deepEqual(languages, expectedLanguages, 'expected the 8 declared languages in stable order');

  const baseEntry = languageEntries.get(baseLanguage);
  assert.ok(baseEntry && baseEntry.keys.length > 0, 'expected en-US to define the base key set');
  const baseSet = new Set(baseEntry.keys);
  assert.deepEqual(
    [...copyKeys].filter((key) => !baseSet.has(key)),
    [],
    'en-US must define every CopyKey directly',
  );
  assert.deepEqual(
    baseEntry.keys.filter((key) => !copyKeys.has(key)),
    [],
    'en-US must not define keys outside CopyKey',
  );

  for (const language of expectedLanguages) {
    const entry = languageEntries.get(language);
    assert.ok(entry, `missing language block: ${language}`);

    const extraKeys = entry.keys.filter((key) => !baseSet.has(key));
    assert.deepEqual(extraKeys, [], `${language} should not introduce keys outside the English base`);

    for (const key of baseEntry.keys) {
      const resolved = entry.values.get(key) ?? baseEntry.values.get(key);
      assert.ok(resolved && resolved.trim(), `${language}.${key} should resolve through direct text or en-US fallback`);
    }
  }

  const { resolveCopy } = loadCopyModule();
  for (const language of expectedLanguages) {
    const resolvedCopy = resolveCopy(language);
    for (const key of copyKeys) {
      assert.equal(typeof resolvedCopy[key], 'string', `${language}.${key} should resolve to a string`);
      assert.ok(resolvedCopy[key].trim(), `${language}.${key} should resolve to non-empty copy`);
    }
  }
});

test('App delegates non-English copy to the central resolver', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');

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
  const capabilitySource = fs.readFileSync(path.resolve(__dirname, '..', 'webview', 'src', 'components', 'settings', 'CapabilityMatrix.tsx'), 'utf8');
  const feedbackSource = fs.readFileSync(path.resolve(__dirname, '..', 'webview', 'src', 'components', 'common', 'UserFeedbackDisclosure.tsx'), 'utf8');
  for (const source of [capabilitySource, feedbackSource]) {
    assert.match(source, /resolveCopy/);
    assert.doesNotMatch(source, /language === ["']zh-CN["']/);
  }
  const { resolveCopy } = loadCopyModule();
  for (const language of expectedLanguages) {
    const copy = resolveCopy(language);
    for (const key of [
      'capabilityChat', 'capabilityTools', 'capabilityStreaming', 'capabilitySupported',
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
