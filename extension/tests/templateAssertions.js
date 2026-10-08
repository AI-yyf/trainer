'use strict';
// Behavioral template checks replace obsolete layout/source assumptions. Integration
// coverage lives in trainer-template-navigation.spec.js and native VSIX E2E.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const root = path.resolve(__dirname, '../webview/src');
const runtime = Module.createRequire(path.join(root, '../package.json'));
const React = runtime('react');
const { renderToStaticMarkup } = runtime('react-dom/server');
const { buildSync } = runtime('esbuild');
const cache = new Map();
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
function load(file) {
  if (cache.has(file)) return cache.get(file);
  const filename = path.join(root, file);
  const { outputFiles } = buildSync({ entryPoints: [filename], bundle: true, platform: 'node', format: 'cjs', write: false, external: ['react', 'react-dom', 'react/jsx-runtime', '*?worker&inline'] });
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const requireModule = mod.require.bind(mod);
  // Vite owns worker asset compilation. Static HTML checks must never execute
  // attachment processing; the browser attachment tests exercise the real worker.
  mod.require = (id) => id.endsWith('?worker&inline')
    ? class BrowserWorkerOnly { constructor() { throw new Error('Image staging requires its real browser worker'); } }
    : requireModule(id);
  mod._compile(outputFiles[0].text, filename);
  cache.set(file, mod.exports);
  return mod.exports;
}
const render = (file, symbol, props) => renderToStaticMarkup(React.createElement(load(file)[symbol], props));
function learningFacts(overrides = {}) {
  return { scope: { workspaceId: 'workspace', sessionId: 'session', generation: 'g1' }, language: 'en-US',
    workspace: { ready: true }, provider: { ready: true, canGeneratePlan: true }, freshness: 'current', connection: 'ready',
    plan: { state: 'active', id: 'plan', revision: 3, currentStep: 'Write boundary tests' },
    evidence: { pending: [] }, ...overrides };
}
function learningAction(overrides = {}) {
  return load('lib/learningActionResolver.ts').resolveLearningPrimaryAction(learningFacts(overrides));
}
function learningPlan(action, extra = {}) {
  const previousWindow = globalThis.window;
  globalThis.window ??= { acquireVsCodeApi: undefined, location: { search: '', hash: '', origin: 'http://localhost' },
    localStorage: { getItem() { return null; }, setItem() {} } };
  try {
    const key = 'resolved-learning-plan';
    if (!cache.has(key)) {
      const filename = path.join(root, 'learning-plan-render-test.tsx');
      const { outputFiles } = buildSync({ stdin: { resolveDir: root, contents:
        'export { CoachPlanView } from "./components/plan/CoachPlanView"; export { I18nContext } from "./lib/i18n/context";', loader: 'tsx' },
        bundle: true, platform: 'node', format: 'cjs', write: false, external: ['react','react-dom','react/jsx-runtime'] });
      const mod = new Module(filename, module); mod.filename = filename;
      mod.paths = Module._nodeModulePaths(root); mod._compile(outputFiles[0].text, filename);
      cache.set(key, mod.exports);
    }
    const { CoachPlanView, I18nContext } = cache.get(key);
    return renderToStaticMarkup(React.createElement(I18nContext.Provider, {
      value: { language: extra.language ?? 'en-US', direction: 'ltr' },
    }, React.createElement(CoachPlanView, {
    plan: { id: 'plan', title: 'Boundary rules', frozen: false, stages: [], currentStep: 'Write boundary tests' },
    primaryAction: { label: 'Next', title: action.title, detail: action.detail,
      action: { ...action, id: action.intent, onClick() {} } },
    primaryEvidenceId: action.target.evidenceId, compactPrimary: true, ...extra,
  }))); } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
}
function navigation() {
  const mapping = load('lib/workbenchDestinations.ts');
  assert.deepEqual(mapping.PRIMARY_DESTINATIONS, ['coach', 'plan', 'resources']);
  for (const route of ['coach', 'plan', 'resources', 'training', 'progress', 'settings']) {
    const html = render('templates/AppShell.tsx', 'AppShell', { language: 'en-US', direction: 'ltr', activeView: route, historyOpen: false, onHistory() {}, onNavigate() {}, children: null });
    const nav = html.slice(html.indexOf('<nav'), html.indexOf('</nav>'));
    assert.equal((nav.match(/<button/g) || []).length, 3);
    assert.ok(html.includes('trainer-history-toggle'));
    assert.ok(html.includes('trainer-view-nav-settings'));
    assert.equal(mapping.ownsCoachComposer(route), route === 'coach');
    assert.equal(mapping.primaryDestinationForRoute(route), route === 'settings' ? null : ['training', 'progress'].includes(route) ? 'plan' : route);
  }
}
function practice() {
  for (const [index, phase] of ['learn', 'try', 'verify', 'reflect', 'return'].entries()) {
    const html = render('templates/FocusedPractice.tsx', 'FocusedPractice', { parent: 'Learning', title: 'Current card', phase, phaseLabel: phase, onBack() {}, children: 'current-phase-content' });
    assert.ok(html.includes(`${index + 1}/5`) || html.includes(`${index + 1} / 5`));
    assert.ok(html.includes('current-phase-content'));
    assert.ok(html.includes('Current card'));
  }
  const form = render('templates/PracticeResponse.tsx', 'PracticeResponse', { language: 'en-US', label: 'Reflection', value: 'My response', submitLabel: 'Record', onChange() {}, onSubmit() {} });
  assert.ok(form.includes('training-response'));
  assert.equal((form.match(/data-primary-action="true"/g) || []).length, 1);
  assert.ok(!form.includes('coach-composer'));
  assert.ok(read('app/App.tsx').includes('activityDrafts?.[activityDraftKey]'));
}
function learning() {
  const html = render('templates/LearningHome.tsx', 'LearningHome', { currentLabel: 'Current learning', title: 'Goal', stage: '2 / 4', next: {label: 'Next step', title: 'Repair mapping', detail: 'Done when checks pass', action: {label:'Continue',onClick(){}}}, ...Object.fromEntries(['review','route','growth','evidence'].map(key => [key,{label:key,content:key+'-content'}])) });
  assert.equal((html.match(/data-primary-action="true"/g) || []).length, 1);
  assert.equal((html.match(/<details/g) || []).length, 4);
  assert.ok(!html.includes('<details open'));
  assert.ok(html.indexOf('Goal') < html.indexOf('Repair mapping'));
  const plan = read('components/plan/CoachPlanView.tsx');
  for (const marker of ['evidenceActions?.onAdoptEvidence', 'evidenceActions?.onRejectEvidence', 'evidenceActions?.onDeferEvidence', 'plan.frozen', '<PlanStageSection', '<LearningHome']) assert.ok(plan.includes(marker), marker);
  assert.ok(!plan.includes('<textarea'));
}
function reply() {
  const html = render('templates/CoachReply.tsx','CoachReply',{body:'BODY',evidence:'EVIDENCE',nextAction:'NEXT',tools:'TOOLS'});
  assert.ok(html.indexOf('BODY') < html.indexOf('EVIDENCE'));
  assert.ok(html.indexOf('EVIDENCE') < html.indexOf('NEXT'));
  assert.ok(html.indexOf('NEXT') < html.indexOf('TOOLS'));
  const source = read('components/coach/CoachMessageBubble.tsx');
  for (const action of ['copy','share','save-resource','training-card','retry']) assert.ok(source.includes(`"${action}"`));
  assert.ok(source.includes('<OverflowActions'));
  assert.ok(source.includes('message.role === "assistant"'));
}
function settings() {
  const html = render('templates/SettingsIndex.tsx','SettingsIndex',{title:'Settings',items:['connection','teaching','workspace','preferences'].map(id=>({id,label:id,summary:'Actual configuration'})),onSelect(){}});
  assert.equal((html.match(/<button/g)||[]).length,4);
  assert.ok(!html.includes('role="tab"'));
  const source=read('components/settings/CoachSettingsView.tsx');
  assert.ok(source.includes('<SettingsDetail'));
  assert.ok(!source.includes('<nav'));
  assert.ok(!source.includes('settingsNavMeasurement'));
  for (const marker of ['data-settings-section="connection"','data-settings-section="workspace"','data-settings-section="skills"','data-settings-section="preferences"']) assert.ok(source.includes(marker),marker);
}
function palette() {
  const html=render('templates/CommandPalette.tsx','CommandPalette',{label:'Skills',entries:[{id:'review',trigger:'$review',title:'Review current file',detail:'Read diagnostics',onSelect(){}}],selectedIndex:0,onHighlight(){},empty:'No matches'});
  assert.ok(html.includes('role="listbox"'));
  assert.ok(html.includes('role="option"'));
  assert.ok(html.includes('aria-selected="true"'));
  assert.ok(html.includes('$review'));
  assert.ok(html.includes('Read diagnostics'));
  const app=read('app/App.tsx');
  assert.ok(app.includes('triggerToken === "$" ? 6 : 10'));
  assert.ok(app.includes('skillSharing={renderSkillSharing()}'));
  assert.ok(app.includes('setActiveView("settings")'));
}
module.exports={load,read,render,learningFacts,learningAction,learningPlan,navigation,practice,learning,reply,settings,palette};
