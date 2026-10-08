'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const runtime = Module.createRequire(path.resolve(__dirname, '../webview/package.json'));
const entry = path.resolve(__dirname, '../webview/src/lib/learningActionResolver.ts');
const compiled = runtime('esbuild').buildSync({ entryPoints: [entry], bundle: true,
  platform: 'node', format: 'cjs', write: false });
const mod = new Module(entry, module);
mod.filename = entry;
mod.paths = Module._nodeModulePaths(path.dirname(entry));
mod._compile(compiled.outputFiles[0].text, entry);
const { resolveLearningPrimaryAction: resolve, executeLearningPrimaryAction: execute,
  learningActionIsCurrent } = mod.exports;

function facts(overrides = {}) {
  const base = { scope: { workspaceId: 'ws', sessionId: 'session', generation: 'generation-1' },
    language: 'en-US', workspace: { ready: true }, provider: { ready: true, canGeneratePlan: true },
    freshness: 'current', connection: 'ready',
    plan: { state: 'active', id: 'plan-1', revision: 7, currentStep: 'Add boundary tests', completion: ['Run pytest'] },
    evidence: { pending: [] } };
  return { ...base, ...overrides };
}

const cases = [
  ['workspace required before any action', { workspace: { ready: false, detail: 'Select an admitted root' } }, 'choose_workspace', false],
  ['stale state refresh never starts work', { freshness: 'stale' }, 'restore_state', false],
  ['recovering state disables work', { freshness: 'recovering' }, 'wait_for_restore', true],
  ['recovering connection disables work', { connection: 'recovering' }, 'wait_for_restore', true],
  ['offline connection points to setup', { connection: 'offline' }, 'configure_provider', false],
  ['provider missing points to actual setup', { provider: { ready: false, canGeneratePlan: false } }, 'configure_provider', false],
  ['a live frozen plan is resumed without replacement', { plan: { state: 'frozen', id: 'plan-1', revision: 7, currentStep: 'Add tests' } }, 'resume_plan', false],
  ['a genuine blocker precedes the current step', { plan: { state: 'active', id: 'plan-1', blocker: 'The test runner is missing', currentStep: 'Add tests' } }, 'resolve_blocker', false],
  ['pending evidence does not block useful work', { evidence: { pending: [{ id: 'e1', summary: 'Tests passed' }] } }, 'continue_step', false],
  ['the bound evidence gate is explicit', { evidence: { pending: [{ id: 'e1', summary: 'Tests passed' }], blockingId: 'e1' } }, 'adopt_evidence', false],
  ['an old evidence binding cannot gate this step', { evidence: { pending: [{ id: 'e1', summary: 'Tests passed' }], blockingId: 'old' } }, 'continue_step', false],
  ['active training resumes the same card', { training: { workspaceId: 'ws', cardId: 'card-1', title: 'Boundary practice', status: 'active' } }, 'resume_training', false],
  ['return is finished before new work', { training: { workspaceId: 'ws', cardId: 'card-1', title: 'Boundary practice', status: 'return_pending' } }, 'finish_training', false],
  ['completed training does not block the current step', { training: { workspaceId: 'ws', cardId: 'card-1', title: 'Boundary practice', status: 'completed' } }, 'continue_step', false],
  ['foreign training cannot preempt current work', { training: { workspaceId: 'other', cardId: 'card-1', title: 'Foreign practice', status: 'return_pending' } }, 'continue_step', false],
  ['a due review does not replace an active step', { dueReview: { id: 'review-1', title: 'Recall boundary rules' } }, 'continue_step', false],
  ['due review with no active step', { plan: { state: 'active', id: 'plan-1' }, dueReview: { id: 'review-1', title: 'Recall boundary rules' } }, 'start_review', false],
  ['no plan requests an explicit goal', { plan: { state: 'absent' } }, 'generate_plan', false],
  ['plan generation requires verified tools', { plan: { state: 'absent' }, provider: { ready: true, canGeneratePlan: false } }, 'configure_provider', false],
  ['no plan never forces a plan for a live question', { plan: { state: 'absent' }, firstLookStep: 'Explain the failing assertion' }, 'continue_without_plan', false],
  ['recovered plan with no authoritative step stays conversational', { plan: { state: 'active', id: 'plan-1' } }, 'confirm_step', false],
  ['evidence with no live step remains inspectable', { plan: { state: 'active', id: 'plan-1' }, evidence: { pending: [{ id: 'e1', summary: 'Check this result' }] } }, 'adopt_evidence', false],
  ['completed practice returns with no task mint', { plan: { state: 'active', id: 'plan-1' }, training: { workspaceId: 'ws', cardId: 'card-1', title: 'Boundary practice', status: 'completed' } }, 'return_to_coach', false],
  ['in-flight work disables its duplicate action', { operationPending: true }, 'continue_step', true],
];

for (const [name, overrides, intent, disabled] of cases) test(name, () => {
  const input = facts(overrides);
  const before = structuredClone(input);
  const action = resolve(input);
  assert.equal(action.intent, intent);
  assert.equal(action.disabled, disabled);
  assert.equal(action.busy, disabled);
  assert.ok(action.title && action.label && action.detail);
  assert.deepEqual(input, before, 'resolution must not mutate facts');
  assert.deepEqual(resolve(input), action, 'resolution must be deterministic');
});

test('priority combinations keep recovery, current work, and genuine blockers honest', () => {
  const training = { workspaceId: 'ws', cardId: 'card-1', title: 'Practice', status: 'return_pending' };
  const pending = { pending: [{ id: 'e1', summary: 'Result' }], blockingId: 'e1' };
  for (const recovery of ['recovering', 'stale']) {
    for (const state of ['absent', 'active', 'frozen']) {
      const action = resolve(facts({ freshness: recovery, training, evidence: pending,
        plan: { state, id: 'plan-1', currentStep: 'Add tests', blocker: 'Missing runner' } }));
      assert.equal(action.intent, recovery === 'stale' ? 'restore_state' : 'wait_for_restore');
    }
  }
  assert.equal(resolve(facts({ training, evidence: pending,
    plan: { state: 'frozen', id: 'plan-1', currentStep: 'Add tests' },
    provider: { ready: false, canGeneratePlan: false } })).intent, 'finish_training');
  assert.equal(resolve(facts({ evidence: pending,
    plan: { state: 'active', id: 'plan-1', currentStep: 'Add tests', blocker: 'Missing runner' } })).intent, 'resolve_blocker');
  assert.equal(resolve(facts({ evidence: pending,
    plan: { state: 'frozen', id: 'plan-1', currentStep: 'Add tests' } })).intent, 'resume_plan');
});

test('button copy, rendered disabled state, and dispatch agree in all eight languages', () => {
  const { render } = require('./templateAssertions');
  const handlerNames = ['chooseWorkspace','configureProvider','restoreState','openTraining','resumePlan',
    'resolveBlocker','adoptEvidence','continueStep','continueWithoutPlan','startReview','returnToCoach','generatePlan','confirmStep'];
  const languages = ['zh-CN','en-US','es-ES','fr-FR','de-DE','ja-JP','ko-KR','pt-BR'];
  const labels = new Set();
  for (const language of languages) {
    const current = facts({ language });
    const action = resolve(current);
    labels.add(action.label);
    assert.equal(action.title, current.plan.currentStep);
    const calls = [];
    const handlers = Object.fromEntries(handlerNames.map(name => [name, (...args) => calls.push([name, args])]));
    assert.equal(execute(action, current, handlers), true);
    assert.deepEqual(calls, [['continueStep', ['Add boundary tests']]]);
    for (const [, overrides] of cases) {
      const input = facts({ ...overrides, language });
      const descriptor = resolve(input);
      assert.ok(descriptor.title && descriptor.detail && descriptor.label);
      assert.equal(/\{\w+\}/.test(descriptor.label + descriptor.detail), false, 'no unresolved placeholder');
      const html = render('templates/NextAction.tsx', 'NextAction', { label: 'Next', title: descriptor.title,
        detail: descriptor.detail, action: { ...descriptor, onClick() {} } });
      assert.equal(html.includes('disabled=""'), descriptor.disabled);
      assert.equal((html.match(/data-primary-action="true"/g) || []).length, 1);
    }
  }
  assert.equal(labels.size, 8, 'each language has product-owned action copy');
});

test('click-time validation rejects replaced workspace, session, revision, card and evidence', () => {
  const original = facts(); const action = resolve(original);
  for (const next of [
    facts({ scope: { ...original.scope, workspaceId: 'other' } }),
    facts({ scope: { ...original.scope, sessionId: 'new-session' } }),
    facts({ scope: { ...original.scope, generation: 'generation-2' } }),
    facts({ plan: { ...original.plan, revision: 8 } }),
    facts({ plan: { ...original.plan, currentStep: 'New work' } }),
    facts({ freshness: 'stale' }), facts({ operationPending: true }),
  ]) assert.equal(learningActionIsCurrent(action, next), false);
  const evidence = facts({ evidence: { pending: [{ id: 'e1', summary: 'Result' }], blockingId: 'e1' } });
  assert.equal(learningActionIsCurrent(resolve(evidence), facts({ evidence: {
    pending: [{ id: 'e2', summary: 'Result' }], blockingId: 'e2' } })), false);
  const training = facts({ training: { workspaceId: 'ws', cardId: 'card-1', title: 'Practice', status: 'active' } });
  assert.equal(learningActionIsCurrent(resolve(training), facts({ training: {
    ...training.training, cardId: 'card-2' } })), false);
});

test('an approved evidence action targets the visible pending candidate exactly once', () => {
  const input = facts({ evidence: { pending: [{ id: 'e1', summary: 'Tests passed' }], blockingId: 'e1' } });
  const descriptor = resolve(input); const calls = [];
  assert.equal(descriptor.title, 'Tests passed');
  assert.equal(descriptor.label, 'Approve this evidence');
  const handlers = { adoptEvidence: id => calls.push(id) };
  assert.equal(execute(descriptor, input, handlers), true);
  assert.deepEqual(calls, ['e1']);
  assert.equal(execute(descriptor, facts({ evidence: { pending: [] } }), handlers), false);
  assert.deepEqual(calls, ['e1']);
});

test('backend recovery preserves its actual settings action and never restarts from a settings label', () => {
  const input = facts({ connection: 'offline', provider: { ready: false, canGeneratePlan: false },
    connectionRecovery: { title: 'Trainer cannot continue yet', label: 'Open Settings', detail: 'Check the local connection.' } });
  const action = resolve(input);
  assert.equal(action.title, input.connectionRecovery.title);
  assert.equal(action.label, 'Open Settings');
  assert.equal(action.detail, input.connectionRecovery.detail);
  const called = [];
  assert.equal(execute(action, input, { configureProvider: () => called.push('settings') }), true);
  assert.deepEqual(called, ['settings']);
});

test('only a typed verified training return gets a localized result title while keeping adoption identity', () => {
  const original = { id: 'verified-result', summary: 'Execution stdout /tmp/private-path/check.py exit 0',
    source: 'training_handoff_return', sourceCardId: 'same-card', verified: true,
    verificationSource: 'test_runner', outcome: 'pass' };
  const titles = new Set();
  for (const language of ['zh-CN','en-US','es-ES','fr-FR','de-DE','ja-JP','ko-KR','pt-BR']) {
    const input = facts({ language, plan: { state: 'absent' }, evidence: { pending: [original] } });
    const action = resolve(input);
    titles.add(action.title);
    assert.equal(action.intent, 'adopt_evidence');
    assert.notEqual(action.title, original.summary);
    assert.equal(action.title.includes('/tmp/'), false);
    const calls = [];
    assert.equal(execute(action, input, { adoptEvidence: id => calls.push(id) }), true);
    assert.deepEqual(calls, [original.id]);
    assert.equal(input.evidence.pending[0].summary, original.summary, 'raw evidence remains available');
    for (const change of [{ source: 'evaluation' }, { verified: false },
      { verificationSource: 'self_reported' }, { outcome: 'fail' }, { sourceCardId: '' }]) {
      const unverified = facts({ ...input, evidence: { pending: [{ ...original, ...change }] } });
      assert.equal(resolve(unverified).title, original.summary, 'no summary keyword guessing or global replacement');
    }
  }
  assert.equal(titles.size, 8);
});

test('an untitled restored practice keeps in-flight copy and the same card action in every language', () => {
  const activeTitles = new Set();
  const returnTitles = new Set();
  for (const language of ['zh-CN','en-US','es-ES','fr-FR','de-DE','ja-JP','ko-KR','pt-BR']) {
    const training = { workspaceId: 'ws', cardId: 'restored-same-card', title: '', status: 'completed' };
    const completed = resolve(facts({ language, plan: { state: 'absent' }, training }));
    for (const status of ['active', 'return_pending']) {
      for (const title of ['', '   ']) {
        const input = facts({ language, plan: { state: 'absent' }, training: { ...training, status, title } });
        const before = structuredClone(input);
        const action = resolve(input);
        assert.equal(action.intent, status === 'active' ? 'resume_training' : 'finish_training');
        assert.notEqual(action.title, completed.title, 'unfinished practice must never claim completion');
        assert.ok(action.title && action.detail && action.label);
        (status === 'active' ? activeTitles : returnTitles).add(action.title);
        if (language === 'en-US' && status === 'active') assert.equal(action.title, 'Current practice is in progress');
        if (language === 'zh-CN' && status === 'active') assert.equal(action.title, '当前练习进行中');
        const calls = [];
        assert.equal(execute(action, input, { openTraining: id => calls.push(id) }), true);
        assert.deepEqual(calls, ['restored-same-card']);
        assert.deepEqual(input, before, 'copy resolution and navigation must not change phase or evidence');
        assert.equal(learningActionIsCurrent(action, { ...input,
          training: { ...input.training, status: 'completed' } }), false);
        const named = resolve({ ...input, training: { ...input.training, title: 'Actual card task' } });
        assert.equal(named.title, 'Actual card task', 'a present card title remains authoritative');
      }
    }
  }
  assert.equal(activeTitles.size, 8);
  assert.equal(returnTitles.size, 8);
  assert.equal([...activeTitles].some(title => returnTitles.has(title)), false);
});
