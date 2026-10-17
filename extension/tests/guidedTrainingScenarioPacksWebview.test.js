'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const entryPoint = path.join(webviewRoot, 'lib', 'guidedTrainingScenarioPacks.ts');
const esbuild = require('../webview/node_modules/esbuild');

const compiled = esbuild.buildSync({
  entryPoints: [entryPoint],
  bundle: true,
  platform: 'node',
  format: 'cjs',
  write: false,
  loader: { '.json': 'json' },
});
const mod = new Module(entryPoint, module);
mod.filename = entryPoint;
mod.paths = Module._nodeModulePaths(path.dirname(entryPoint));
mod._compile(compiled.outputFiles[0].text, entryPoint);
const packs = mod.exports;

// P2 #16: the two literature scenario packs resolve through the same preview
// machinery as the engineering packs, including non-zh/en fallback copy.
test('literature scenarios are part of the preview scenario list', () => {
  assert.ok(packs.guidedTrainingPreviewScenarios.includes('training-close-reading'));
  assert.ok(packs.guidedTrainingPreviewScenarios.includes('training-theory-concept'));
  assert.equal(packs.guidedTrainingPreviewScenarios.length, 7);
});

test('training-close-reading resolves inline copy for zh and en', () => {
  const zh = packs.resolveGuidedTrainingPreviewScenarioData('training-close-reading', 'zh-CN');
  const en = packs.resolveGuidedTrainingPreviewScenarioData('training-close-reading', 'en-US');
  assert.ok(zh && en);
  assert.equal(zh.currentFocus, '锚定式精读');
  assert.equal(en.practiceCard.cardId, 'card-training-close-reading-practice');
  assert.ok(en.practiceCard.learnerDeliverables.join(' ').includes('¶ anchors'));
  assert.equal(en.id, 'literature_close_reading');
});

test('training-theory-concept resolves with non-zh/en fallback interpolation', () => {
  const ja = packs.resolveGuidedTrainingPreviewScenarioData('training-theory-concept', 'ja-JP');
  const de = packs.resolveGuidedTrainingPreviewScenarioData('training-theory-concept', 'de-DE');
  assert.ok(ja && de);
  assert.ok(ja.practiceCard.title.includes('文学理論の概念'));
  assert.ok(de.practiceCard.title.includes('Begriff der Literaturtheorie'));
  assert.ok(ja.practiceCard.constraints.length > 0);
});

test('the untouched engineering scenarios still resolve unchanged', () => {
  const en = packs.resolveGuidedTrainingPreviewScenarioData('training-remote', 'en-US');
  assert.ok(en);
  assert.equal(en.practiceCard.cardId, 'card-training-remote-practice');
});
