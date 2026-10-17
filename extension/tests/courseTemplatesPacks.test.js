'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const entryPoint = path.join(webviewRoot, 'lib', 'courseTemplates.ts');
const esbuild = require('../webview/node_modules/esbuild');

function compileToFile(modPath) {
  const compiled = esbuild.buildSync({
    entryPoints: [modPath],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    write: false,
  });
  const mod = new Module(modPath, module);
  mod.filename = modPath;
  mod.paths = Module._nodeModulePaths(path.dirname(modPath));
  mod._compile(compiled.outputFiles[0].text, modPath);
  return mod.exports;
}

const templates = compileToFile(entryPoint);

const LANGUAGES = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

// P2 #16: one code pack plus three literature packs, all three-stage and
// eight-language complete.
test('starter templates ship one code pack and three literature packs', () => {
  assert.equal(templates.starterTemplates.length, 4);
  const ids = templates.starterTemplates.map((def) => def.id);
  assert.ok(new Set(ids).size === 4, 'pack ids must be unique');
  assert.equal(
    templates.starterTemplates.filter((def) => def.subjectFamily === 'literature').length,
    3,
  );
  assert.ok(ids.includes('code-fix-bug-three-steps'));
  for (const pack of ['literature-close-reading-three-steps', 'literature-imitation-writing-three-steps', 'literature-one-theory-concept']) {
    assert.ok(ids.includes(pack), pack);
  }
});

test('every pack carries three verifiable stages in all eight languages', () => {
  for (const def of templates.starterTemplates) {
    assert.equal(Object.keys(def.byLanguage).length, 8);
    for (const language of LANGUAGES) {
      const template = def.byLanguage[language];
      assert.ok(template.title.length > 0, `${def.id}/${language} title`);
      assert.ok(template.summary.length > 0, `${def.id}/${language} summary`);
      assert.equal(template.stages.length, 3);
      for (const [index, stage] of template.stages.entries()) {
        assert.ok(stage.title.length > 0, `${def.id}/${language}/stage${index}/title`);
        assert.ok(stage.objective.length > 0, `${def.id}/${language}/stage${index}/objective`);
      }
    }
  }
});

test('template lookup filters by subject family and fails closed to code', () => {
  const literature = templates.starterTemplateDefsFor('literature');
  assert.equal(literature.length, 3);
  assert.ok(literature.every((def) => def.subjectFamily === 'literature'));

  for (const unknown of [undefined, '', 'gibberish', 'theory']) {
    const fallback = templates.starterTemplateDefsFor(unknown);
    assert.equal(fallback.length, 1);
    assert.equal(fallback[0].id, 'code-fix-bug-three-steps');
  }
});

test('the projection dimensions determine the starter subject family', () => {
  // P2 #21 handshake: literature-only dimensions mark a literature workspace.
  assert.equal(
    templates.resolveStarterSubjectFamily({ dimensions: { comprehension: {}, appreciation: {} } }),
    'literature',
  );
  assert.equal(
    templates.resolveStarterSubjectFamily({ dimensions: { comprehension: {}, implementation: {} } }),
    'code',
  );
  assert.equal(templates.resolveStarterSubjectFamily({}), 'code');
  assert.equal(templates.resolveStarterSubjectFamily(undefined), 'code');
});

test('the legacy single-template export stays the code starter for compatibility', () => {
  assert.equal(templates.starterTemplate['zh-CN'].title, '三步修一个 Bug');
  assert.equal(templates.starterTemplate['en-US'].stages.length, 3);
});
