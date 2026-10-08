'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const runtime = Module.createRequire(path.resolve(__dirname, '../webview/package.json'));
const entry = path.resolve(__dirname, '../webview/src/lib/boundTrainingCardFacts.ts');
const compiled = runtime('esbuild').buildSync({ entryPoints: [entry], bundle: true,
  platform: 'node', format: 'cjs', write: false });
const mod = { exports: {} };
const evaluate = new Function('module', 'exports', 'require',
  `${compiled.outputFiles[0].text}\nreturn module.exports;`);
const { resolveBoundTrainingCardFacts: resolve } = evaluate(mod, mod.exports, runtime);

const authored = { cardId: 'active', title: '练习 workspace_id isolation',
  problemStatement: '比较原始 workspace_id。', suggestedWorkspaceAction: '先写一次边界断言。',
  deliverable: '不匹配的结果被拒绝。', learnerDeliverables: ['说明原始 workspace_id。'],
  validationMethod: '执行边界测试。', verificationMethod: '检查返回值。',
  verificationSteps: ['验证同一 workspace_id。'] };

test('eligible exact identity preserves authored text independent of any UI locale', () => {
  const result = resolve({ eligible: true, activeCardId: 'active', candidate: authored });
  assert.equal(result.cardId, 'active');
  for (const field of ['title', 'problemStatement', 'suggestedWorkspaceAction',
    'deliverable', 'validationMethod', 'verificationMethod']) {
    assert.equal(result.text[field], authored[field]);
  }
  assert.deepEqual(result.lists.learnerDeliverables, authored.learnerDeliverables);
  assert.deepEqual(result.lists.verificationSteps, authored.verificationSteps);
});

test('caller freshness and card eligibility cannot be bypassed by populated content', () => {
  assert.equal(resolve({ eligible: false, activeCardId: 'active', candidate: authored }), undefined);
  for (const activeCardId of [undefined, '', '  ', 'other', ' active ']) {
    assert.equal(resolve({ eligible: true, activeCardId, candidate: authored }), undefined);
  }
});

test('a foreign candidate is never read; a matching route supplies its own facts', () => {
  const foreign = { cardId: 'foreign', get title() { throw new Error('Foreign content read'); } };
  const result = resolve({ eligible: true, activeCardId: 'active', candidate: foreign, routeCard: authored });
  assert.equal(result.text.title, authored.title);
  assert.equal(result.text.problemStatement, authored.problemStatement);
});

test('a foreign route cannot fill missing candidate fields', () => {
  const result = resolve({ eligible: true, activeCardId: 'active',
    candidate: { cardId: 'active', title: 'Candidate title' },
    routeCard: { ...authored, cardId: 'foreign' } });
  assert.deepEqual(result.text, { title: 'Candidate title' });
  assert.deepEqual(result.lists, {});
});

test('same-ID candidate wins per populated field, with same-ID route fallback only', () => {
  const result = resolve({ eligible: true, activeCardId: 'active',
    candidate: { cardId: 'active', title: '  原始标题  ', problemStatement: ' \n ',
      deliverable: 'Candidate completion', learnerDeliverables: [], verificationSteps: ['  '],
      validationMethod: 'Candidate validation' }, routeCard: authored });
  assert.equal(result.text.title, '  原始标题  ');
  assert.equal(result.text.problemStatement, authored.problemStatement);
  assert.equal(result.text.deliverable, 'Candidate completion');
  assert.equal(result.text.validationMethod, 'Candidate validation');
  assert.deepEqual(result.lists.learnerDeliverables, authored.learnerDeliverables);
  assert.deepEqual(result.lists.verificationSteps, authored.verificationSteps);
});

test('candidate lists replace route lists without merging another task into the card', () => {
  const result = resolve({ eligible: true, activeCardId: 'active',
    candidate: { ...authored, verificationSteps: ['Candidate check', '  original spacing  '] },
    routeCard: { ...authored, verificationSteps: ['Route-only check'] } });
  assert.deepEqual(result.lists.verificationSteps, ['Candidate check', '  original spacing  ']);
});

test('title equality and unbound selected-card scalars never establish identity', () => {
  const input = { eligible: true, activeCardId: 'active',
    candidate: { ...authored, cardId: undefined }, routeCard: { ...authored, cardId: 'foreign' },
    get selectedCardTitle() { throw new Error('Unbound scalar read'); },
    get ambientFocus() { throw new Error('Ambient focus read'); } };
  assert.equal(resolve(input), undefined);
});

test('snapshot facts are never mutated and returned lists do not alias the snapshot', () => {
  const candidate = Object.freeze({ ...authored,
    learnerDeliverables: Object.freeze([...authored.learnerDeliverables]),
    verificationSteps: Object.freeze([...authored.verificationSteps]) });
  const before = JSON.stringify(candidate);
  const result = resolve({ eligible: true, activeCardId: 'active', candidate });
  assert.notEqual(result.lists.learnerDeliverables, candidate.learnerDeliverables);
  result.lists.learnerDeliverables.push('Consumer-local edit');
  assert.equal(JSON.stringify(candidate), before);
  assert.deepEqual(candidate.learnerDeliverables, authored.learnerDeliverables);
});

test('identity, phase, evidence, review and flash prompts are outside authored presentation facts', () => {
  const result = resolve({ eligible: true, activeCardId: 'active', candidate: {
    ...authored, status: 'completed', learningPhase: 'return', question: 'Special flash prompt',
    evidence: ['fake'], selectedCardTitle: 'Legacy scalar', updatedAt: 'changed' } });
  for (const field of ['status', 'learningPhase', 'question', 'evidence', 'selectedCardTitle', 'updatedAt']) {
    assert.equal(result.text[field], undefined);
    assert.equal(result.lists[field], undefined);
  }
});
