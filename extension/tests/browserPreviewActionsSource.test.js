'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const sourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewActions.ts',
);

function readSource() {
  return fs.readFileSync(sourcePath, 'utf8');
}

test('browser preview action reducer covers the Plan and Resources journey without production commands', () => {
  const source = readSource();

  assert.match(source, /export function buildGoalAwarePreviewPlan\(/);
  assert.match(source, /export function buildGoalAwarePreviewPlanPatch\(/);
  assert.match(source, /trainerCommands\.generatePlan/);
  assert.match(source, /trainerCommands\.updatePlan/);
  assert.match(source, /trainerCommands\.nextTask/);
  assert.match(source, /trainerCommands\.openResource/);
  assert.match(source, /trainerCommands\.indexResources/);
  assert.match(source, /hasFormalPlan: true/);
  assert.match(source, /indexState: "indexed"/);
  assert.match(source, /This browser preview action does not change real data/);
  assert.match(source, /evaluateCurrentFileMissing:/);
  assert.match(source, /copy\.evaluateCurrentFileMissing/);
  assert.match(
    source,
    /\\u6d4f\\u89c8\\u5668\\u9884\\u89c8\\u4e2d\\u6ca1\\u6709\\u5f53\\u524d IDE \\u6587\\u4ef6/,
  );
});

test('goal-aware preview copy covers every supported Trainer language', () => {
  const source = readSource();

  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(source, new RegExp(`"${language}":\\s*\\{`));
  }
});
