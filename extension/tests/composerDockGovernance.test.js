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

test('dock composer mounts only in the three primary destinations', () => {
  assert.deepEqual(dock.DOCK_SURFACES, ['coach', 'plan', 'resources']);
  assert.equal(dock.docksComposer('coach'), true);
  assert.equal(dock.docksComposer('plan'), true);
  assert.equal(dock.docksComposer('resources'), true);
  assert.equal(dock.docksComposer('training'), true);
  assert.equal(dock.docksComposer('progress'), true);
  assert.equal(dock.docksComposer('settings'), false);
});

test('draft scopes are surface-keyed; coach keeps the legacy session key', () => {
  const sessionKey = '/workspace\u0000session-1';
  assert.equal(dock.composerDockDraftScope('coach', sessionKey), sessionKey);
  assert.equal(dock.composerDockDraftScope('plan', sessionKey), `${sessionKey}\u0000dock:plan`);
  assert.equal(dock.composerDockDraftScope('resources', sessionKey), `${sessionKey}\u0000dock:resources`);
  assert.equal(dock.composerDockDraftScope('training', sessionKey), dock.composerDockDraftScope('plan', sessionKey));
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
  assert.equal(fallback.title, 'Coach replied');
});

test('visible send-preference switch copy covers all eight UI languages', () => {
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const copy = dock.dockSendPreferenceCopy(language);
    assert.ok(copy.label.length > 0);
    assert.ok(copy.jump.length > 0);
    assert.ok(copy.stay.length > 0);
    assert.notEqual(copy.jump, copy.stay);
  }
  const fallback = dock.dockSendPreferenceCopy('xx-XX');
  assert.equal(fallback.label, 'After send');
});

test('the shared composer writes scoped drafts and leaves results in the originating workspace', () => {
  const app = read('app/App.tsx');
  assert.match(app, /showComposerShell = docksComposer\(activeView\)/);
  assert.equal((app.match(/<CoachComposer\b/g) ?? []).length, 1);
  assert.match(app, /selectComposerDraftScope\(composerDraftScope\)/);
  assert.match(app, /<CoachComposer[\s\S]*?composerUsesTrainingFlow \? activityDraft : draft/);
  assert.doesNotMatch(app, /<PracticeResponse\b/);
  assert.match(app, /const activityDraftKey =/);
  assert.match(app, /const messageText = appendDockAnchor\(rawMessageText, dockAnchor\);/);
  assert.match(app, /primaryDestinationForRoute\(message\.sourceView\) === destination/);
  assert.match(app, /renderViewAgentReply\("resources"\)/);
  assert.doesNotMatch(app, /dockSendNavigation\(/);
});
