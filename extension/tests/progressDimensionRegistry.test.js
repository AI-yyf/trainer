'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const esbuild = require('../webview/node_modules/esbuild');

function compileAndLoad(entryPoint) {
  const compiled = esbuild.buildSync({
    entryPoints: [entryPoint], bundle: true, platform: 'node', format: 'cjs', write: false,
  });
  const mod = new Module(entryPoint, module);
  mod.filename = entryPoint;
  mod.paths = Module._nodeModulePaths(path.dirname(entryPoint));
  mod._compile(compiled.outputFiles[0].text, entryPoint);
  return mod.exports;
}

// P2 #21: the dimension registry module is pure and behavior-tested.
const progressDims = compileAndLoad(path.join(webviewRoot, 'lib', 'progressDimensions.ts'));

// Copy tables compile too — label completeness is a data contract.
const progressCopy = compileAndLoad(path.join(webviewRoot, 'lib', 'i18n', 'segments', 'progressInlineText.ts'));

const LANGUAGES = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
const REGISTRY_KEYS = ['comprehension', 'implementation', 'debugging', 'expression', 'appreciation', 'transfer'];

test('registry order is the six subject-scoped dimensions', () => {
  assert.deepEqual(progressDims.REGISTRY_ORDER, REGISTRY_KEYS);
  assert.deepEqual(progressDims.LEGACY_CODE_ORDER, [
    'comprehension', 'implementation', 'debugging', 'transfer',
  ]);
});

test('literature projection rows follow the registry-filtered order', () => {
  const projection = {
    dimensions: {
      appreciation: { state: 'independent', verifiedCount: 1 },
      comprehension: { state: 'repeat_verified', verifiedCount: 3 },
      transfer: { state: 'not_verified' },
      expression: { state: 'assisted', verifiedCount: 0 },
    },
  };
  assert.deepEqual(progressDims.dimensionKeysFor(projection), [
    'comprehension', 'expression', 'appreciation', 'transfer',
  ]);
});

test('legacy code-only snapshots keep the historical four rows', () => {
  const legacy = {
    dimensions: {
      comprehension: { state: 'independent' },
      implementation: { state: 'repeat_verified' },
      debugging: { state: 'needs_review' },
      transfer: { state: 'not_verified' },
    },
  };
  assert.deepEqual(progressDims.dimensionKeysFor(legacy), progressDims.LEGACY_CODE_ORDER);
});

test('unknown or missing projections fall back to the code rows', () => {
  assert.deepEqual(progressDims.dimensionKeysFor(undefined), progressDims.LEGACY_CODE_ORDER);
  assert.deepEqual(progressDims.dimensionKeysFor({}), progressDims.LEGACY_CODE_ORDER);
  assert.deepEqual(
    progressDims.dimensionKeysFor({ dimensions: { mystery: {}, gibberish: {} } }),
    progressDims.LEGACY_CODE_ORDER,
  );
});

test('dimension labels cover every registry key in all eight languages', () => {
  for (const language of LANGUAGES) {
    const labels = progressCopy.DIMENSION_LABELS[language];
    assert.ok(labels, `missing label table for ${language}`);
    for (const key of REGISTRY_KEYS) {
      assert.equal(typeof labels[key], 'string', `${language}/${key} label missing`);
      assert.ok(labels[key].length > 0, `${language}/${key} label empty`);
    }
  }
});

test('literature labels match the subject profile data (zh/en/anchor languages)', () => {
  const profilePath = path.resolve(__dirname, '..', '..', 'profiles', 'literature.profile.json');
  const profile = JSON.parse(fs.readFileSync(profilePath, 'utf8'));
  const labels = profile.dimension_labels;
  for (const language of LANGUAGES) {
    assert.ok(labels[language], `profile missing ${language} labels`);
    for (const key of ['comprehension', 'expression', 'appreciation', 'transfer']) {
      assert.equal(
        progressCopy.DIMENSION_LABELS[language][key],
        labels[language][key],
        `${language}/${key} label drifts from literature profile`,
      );
    }
  }
});
