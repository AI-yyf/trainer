'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require(require.resolve('typescript', {
  paths: [path.resolve(__dirname, '..', 'webview')],
}));
const vm = require('node:vm');

const composerSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);
const copySourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'copy.ts');
const supportedLanguages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
const composerCopyKeys = [
  'placeholder',
  'busyLabel',
  'accessibilityLabel',
  'submitLabel',
  'emptySubmitLabel',
  'blockedSubmitLabel',
  'attachmentCount',
  'attachmentCapability',
  'dropToAttach',
  'imageUnavailable',
  'image',
  'removeAttachment',
  'clear',
];
const expectedEmptySubmitLabels = {
  'zh-CN': '\u8f93\u5165\u6d88\u606f\u6216\u62d6\u5165\u56fe\u7247\u540e\u53d1\u9001',
  'en-US': 'Write a message or drop an image to send',
  'es-ES': 'Escribe un mensaje o suelta una imagen para enviarlo',
  'fr-FR': '\u00c9crivez un message ou d\u00e9posez une image pour l\u2019envoyer',
  'de-DE': 'Schreibe eine Nachricht oder ziehe ein Bild hierher, um es zu senden',
  'ja-JP': '\u30e1\u30c3\u30bb\u30fc\u30b8\u3092\u5165\u529b\u3059\u308b\u304b\u3001\u753b\u50cf\u3092\u30c9\u30ed\u30c3\u30d7\u3057\u3066\u9001\u4fe1',
  'ko-KR': '\uba54\uc2dc\uc9c0\ub97c \uc785\ub825\ud558\uac70\ub098 \uc774\ubbf8\uc9c0\ub97c \ub193\uc544 \ubcf4\ub0b4\uc138\uc694',
  'pt-BR': 'Escreva uma mensagem ou solte uma imagem para enviar',
};

function findObjectLiteral(sourcePath, variableName, scriptKind) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const sourceFile = ts.createSourceFile(sourcePath, source, ts.ScriptTarget.Latest, true, scriptKind);
  let objectLiteral;

  function visit(node) {
    if (
      ts.isVariableDeclaration(node) &&
      node.name.getText(sourceFile) === variableName &&
      node.initializer &&
      ts.isObjectLiteralExpression(node.initializer)
    ) {
      objectLiteral = node.initializer;
      return;
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  assert.ok(objectLiteral, `expected ${variableName} object literal`);
  return { source, sourceFile, objectLiteral };
}

function propertyMap(sourceFile, objectLiteral) {
  return new Map(
    objectLiteral.properties
      .filter(ts.isPropertyAssignment)
      .map((property) => [property.name.getText(sourceFile).replaceAll('"', ''), property.initializer]),
  );
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

test('Composer fallback labels are complete for every supported language', () => {
  const { source, sourceFile, objectLiteral } = findObjectLiteral(
    composerSourcePath,
    'composerLocaleCopy',
    ts.ScriptKind.TSX,
  );
  const locales = propertyMap(sourceFile, objectLiteral);

  assert.deepEqual([...locales.keys()], supportedLanguages);
  for (const language of supportedLanguages) {
    const locale = locales.get(language);
    assert.ok(locale && ts.isObjectLiteralExpression(locale), `expected ${language} Composer copy`);
    const entries = propertyMap(sourceFile, locale);

    for (const key of composerCopyKeys) {
      const value = entries.get(key);
      assert.ok(value, `expected ${language}.${key}`);
      assert.ok(
        ts.isStringLiteralLike(value) || ts.isArrowFunction(value),
        `expected ${language}.${key} to be localized copy`,
      );
    }

    const emptySubmitLabel = entries.get('emptySubmitLabel');
    assert.ok(emptySubmitLabel && ts.isStringLiteralLike(emptySubmitLabel));
    assert.equal(emptySubmitLabel.text, expectedEmptySubmitLabels[language]);
  }

  assert.doesNotMatch(source, /language === "zh-CN"/);
  assert.match(source, /const emptySubmitLabel = emptySubmitAriaLabel\?\.trim\(\) \|\| localizedCopy\.emptySubmitLabel/);
  assert.match(source, /aria-label=\{localizedCopy\.removeAttachment\}/);
});

test('central Composer field labels resolve in every supported language', () => {
  const { resolveCopy } = loadCopyModule();
  const expectedLabels = {
    'zh-CN': '\u6d88\u606f\u8f93\u5165\u6846',
    'en-US': 'Message composer',
    'es-ES': 'Campo de mensaje',
    'fr-FR': 'Zone de message',
    'de-DE': 'Nachrichtenfeld',
    'ja-JP': '\u30e1\u30c3\u30bb\u30fc\u30b8\u5165\u529b\u6b04',
    'ko-KR': '\uba54\uc2dc\uc9c0 \uc785\ub825\ub780',
    'pt-BR': 'Campo de mensagem',
  };

  for (const language of supportedLanguages) {
    assert.equal(resolveCopy(language).composerAccessibility, expectedLabels[language]);
  }
});
