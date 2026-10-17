'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');

function read(relativePath) {
  return fs.readFileSync(path.join(webviewRoot, relativePath), 'utf8');
}

// Compile the pure dock governance module and exercise its contract.
const dockEntry = path.join(webviewRoot, 'lib', 'composerDock.ts');
const compiled = require('../webview/node_modules/esbuild').buildSync({
  entryPoints: [dockEntry], bundle: true, platform: 'node', format: 'cjs', write: false,
});
const mod = new Module(dockEntry, module);
mod.filename = dockEntry;
mod.paths = Module._nodeModulePaths(path.dirname(dockEntry));
mod._compile(compiled.outputFiles[0].text, dockEntry);
const dock = mod.exports;

test('dock composer mounts exactly on the three primary destinations', () => {
  assert.deepEqual(dock.DOCK_SURFACES, ['coach', 'plan', 'resources']);
  assert.equal(dock.docksComposer('coach'), true);
  assert.equal(dock.docksComposer('plan'), true);
  assert.equal(dock.docksComposer('resources'), true);
  // Training never docks: FocusedPractice owns phase inputs, the 5-phase
  // state machine and the verification gate must not be bypassed.
  assert.equal(dock.docksComposer('training'), false);
  assert.equal(dock.docksComposer('progress'), false);
  assert.equal(dock.docksComposer('settings'), false);
});

test('draft scopes are surface-keyed; coach keeps the legacy session key', () => {
  const sessionKey = '/workspace\u0000session-1';
  assert.equal(dock.composerDockDraftScope('coach', sessionKey), sessionKey);
  assert.equal(dock.composerDockDraftScope('plan', sessionKey), `${sessionKey}\u0000dock:plan`);
  assert.equal(dock.composerDockDraftScope('resources', sessionKey), `${sessionKey}\u0000dock:resources`);
  // Hidden surfaces resolve to the plain session key and never write drafts.
  assert.equal(dock.composerDockDraftScope('training', sessionKey), sessionKey);
  // Surface scopes never collide with each other.
  assert.notEqual(
    dock.composerDockDraftScope('plan', sessionKey),
    dock.composerDockDraftScope('resources', sessionKey),
  );
});

test('send preference normalizes fail-closed to the jump default', () => {
  assert.equal(dock.normalizeDockSendPreference(undefined), 'jump');
  assert.equal(dock.normalizeDockSendPreference('jump'), 'jump');
  assert.equal(dock.normalizeDockSendPreference('stay'), 'stay');
  assert.equal(dock.normalizeDockSendPreference('garbage'), 'jump');

  assert.equal(dock.dockSendNavigation('jump', 'plan'), 'jump_to_coach');
  assert.equal(dock.dockSendNavigation('stay', 'plan'), 'stay');
  // Coach sends never navigate and never need a return banner.
  assert.equal(dock.dockSendNavigation('stay', 'coach'), 'jump_to_coach');
});

test('context anchors: stage for Learning, resource for Resources, none on Coach', () => {
  const stage = dock.resolveDockContextAnchor('plan', {
    stageTitle: '精读《孔乙己》', stageProgress: '第 2 / 3 段',
  });
  assert.equal(stage.label, '第 2 / 3 段 · 精读《孔乙己》');
  assert.equal(stage.text, '[当前学习阶段] 第 2 / 3 段 · 精读《孔乙己》');
  assert.ok(stage.id.startsWith('stage:'));

  const resource = dock.resolveDockContextAnchor('resources', { resourceLabel: 'kongyiji.epub' });
  assert.equal(resource.text, '[当前资料] kongyiji.epub');
  assert.ok(resource.id.startsWith('resource:'));

  assert.equal(dock.resolveDockContextAnchor('coach', { stageTitle: 'X' }), null);
  // Missing context and suppressed chips produce no anchor.
  assert.equal(dock.resolveDockContextAnchor('plan', {}), null);
  const stage2 = dock.resolveDockContextAnchor('plan', { stageTitle: 'S' });
  assert.equal(dock.resolveDockContextAnchor('plan', { stageTitle: 'S' }, true), null);
  assert.ok(stage2);
});

test('anchor text joins the learner message without duplication', () => {
  const anchor = { id: 'stage:x', label: 'x', text: '[当前学习阶段] x' };
  assert.equal(dock.appendDockAnchor('注意叙述视角', anchor), '注意叙述视角\n\n[当前学习阶段] x');
  assert.equal(dock.appendDockAnchor('', anchor), '[当前学习阶段] x');
  assert.equal(dock.appendDockAnchor('  ', anchor), '[当前学习阶段] x');
  assert.equal(dock.appendDockAnchor('已是锚点\n[当前学习阶段] x', anchor), '已是锚点\n[当前学习阶段] x');
  assert.equal(dock.appendDockAnchor('no anchor', null), 'no anchor');
});

test('returnToSurface banner copy covers all eight UI languages', () => {
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const plan = dock.dockReturnBannerCopy(language, 'plan');
    assert.ok(plan.title.length > 0);
    assert.ok(plan.action.length > 0);
    assert.ok(plan.back.length > 0);
    const resources = dock.dockReturnBannerCopy(language, 'resources');
    assert.equal(resources.title, plan.title);
    assert.notEqual(resources.back, plan.back);
  }
  const fallback = dock.dockReturnBannerCopy('xx-XX', 'plan');
  assert.equal(fallback.title, 'Coach replied · view it');
});

test('App wiring: dock gate, surface-keyed scope effect, anchor chip, stay banner', () => {
  const app = read('app/App.tsx');
  const hook = read('app/useComposerDockAnchor.ts');
  const types = read('lib/types.ts');
  const state = read('app/useWorkbenchState.ts');

  // Single shared composer instance gates on the dock rule (not coach-only).
  assert.match(app, /showComposerShell = docksComposer\(activeView\)/);
  assert.doesNotMatch(app, /showComposerShell = ownsCoachComposer\(activeView\)/);

  // Draft scope is selected per surface, and the effect re-runs on view change.
  assert.match(app, /selectComposerDraftScope\(\s*composerDockDraftScope\(activeView, composerSessionKey\),?\s*\)/);
  assert.match(app, /\[activeView, composerSessionKey, data\.sessionLabel, hasReceivedHostState\]/);

  // Anchor chip strip renders only outside Coach and is removable.
  assert.match(app, /dockAnchorControl\.anchor && activeView !== "coach" \? <div className="template-context" role="group" data-dock-anchor="true">/);
  assert.match(app, /onClick=\{dockAnchorControl\.suppress\}/);

  // Sends from Learning/Resources append the anchor line to the outgoing message.
  assert.match(app, /const messageText = appendDockAnchor\(rawMessageText, dockAnchor\);/);
  assert.match(app, /const dockAnchor = activeView === "coach" \? null : resolveDockContextAnchor\(/);

  // Default jump-to-coach; stay mode records the surface for the return banner.
  assert.match(app, /dockSendNavigation\(dockSendPreference, activeView\) === "jump_to_coach"/);
  assert.match(app, /dockStaySendRef\.current = \{ surface: activeView \};/);
  assert.match(app, /message: dockReturnBannerCopy\(layout\.composerLanguage, dockStay\.surface\)\.title,/);

  // Preference persists in the workbench layout state, default jump.
  assert.match(app, /normalizeDockSendPreference\(layout\.composerSendPreference\)/);
  assert.match(types, /composerSendPreference\?: "jump" \| "stay";/);
  assert.match(state, /setComposerSendPreference: \(preference\) =>/);
  assert.match(state, /composerSendPreference: "jump",/);

  // Suppression is re-armed when the anchored context changes.
  assert.match(hook, /useEffect\(\(\) => \{\s*setSuppressedId\(null\);\s*\}, \[anchorId\]\);/);
});
