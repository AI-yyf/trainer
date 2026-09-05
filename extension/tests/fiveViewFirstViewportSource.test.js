'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const sharedRoot = path.resolve(__dirname, '..', '..', 'shared', 'src');

function read(relativePath, root = webviewRoot) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

test('five views stay the Codex three-layer shell without identity chrome', () => {
  const app = read('app/App.tsx');
  const types = read('lib/types.ts');
  const styles = read('styles.css');

  assert.match(
    types,
    /export const COACH_FIRST_SIDEBAR_VIEWS = \[\s*"coach",\s*"plan",\s*"resources",\s*"training",\s*"settings",\s*\] as const;/s,
  );
  assert.doesNotMatch(types, /"research"/);
  assert.match(app, /const sidebarViewTabs = COACH_FIRST_SIDEBAR_VIEWS\.map\(/);
  assert.match(app, /data-testid=\{`trainer-view-nav-\$\{view\}`\}/);
  assert.doesNotMatch(app, /from ["'].*mockData["']/);
  assert.doesNotMatch(app, /<CoachOrientationRail/);
  assert.doesNotMatch(app, /startSpeak/);
  assert.doesNotMatch(app, />开始说</);

  assert.doesNotMatch(
    styles,
    /\.view-stack--plan > \.view-stack__primary > \.plan-view[\s\S]{0,220}inline-size:\s*fit-content/,
  );
  assert.doesNotMatch(
    styles,
    /--view-stack-max-inline-size,\s*720px/,
  );
  assert.doesNotMatch(
    styles,
    /\.view-stack--plan\.view-stack--content-left > \.view-stack__primary/,
  );
  assert.doesNotMatch(styles, /max-inline-size:\s*min\(100%,\s*80ch\)/);
  assert.match(
    styles,
    /\.view-stack--plan > \.view-stack__primary > \.plan-view[\s\S]{0,280}max-inline-size:\s*none/,
  );
});

test('production workbench views consume CSS variables rather than hardcoded hex colors', () => {
  const styles = read('styles.css');
  const tokens = read('tokens.ts', sharedRoot);
  const resources = read('components/resources/ResourcesWorkbenchView.tsx');
  const training = read('components/training/TrainingWorkbenchView.tsx');
  const settings = read('components/settings/CoachSettingsView.tsx');
  const composer = read('components/composer/CoachComposer.tsx');

  assert.match(tokens, /bg0:/);
  assert.match(tokens, /accent:/);
  assert.match(styles, /--bg-0:/);
  assert.match(styles, /--accent:/);
  assert.match(styles, /--trainer-fallback-bg-0:\s*#/);

  for (const [name, source] of [
    ['resources', resources],
    ['training', training],
    ['settings', settings],
    ['composer', composer],
  ]) {
    assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b/, `${name} hardcoded hex`);
    assert.doesNotMatch(source, /rgb\(/, `${name} hardcoded rgb`);
  }

  const withoutFallbacks = styles.replace(/--trainer-fallback-[^;]+;/g, '');
  const hexInRules = withoutFallbacks.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
  const allowedFallbackCount = (styles.match(/--trainer-fallback-[^:]+:\s*#/g) || []).length;
  assert.ok(allowedFallbackCount >= 8, 'expected :root token fallbacks');
  assert.equal(
    hexInRules.length,
    0,
    `hex colors must stay in :root token fallbacks: ${hexInRules.join(',')}`,
  );
});

test('plan first viewport keeps a work-surface object without a governance dump', () => {
  const app = read('app/App.tsx');
  const plan = read('components/plan/CoachPlanView.tsx');
  assert.match(app, /derivePlanOrientation\(/);
  assert.doesNotMatch(app, /<CoachOrientationRail/);
  assert.match(plan, /data-plan-leftover-not-live=\{leftoverNote \? "true" : undefined\}/);
  assert.match(plan, /leftoverNotLive/);
  assert.match(plan, /coach-plan-view__now-card/);
  assert.doesNotMatch(plan, /coach-plan-view__compact-more/);
  const compactStart = plan.indexOf('className="coach-plan-view__compact-summary"');
  const compactEnd = plan.indexOf('!hideDecisionStrip && !shouldShowDecisionCard && !compactPrimary', compactStart);
  assert.ok(compactStart >= 0 && compactEnd > compactStart, 'expected compact first viewport');
  const compactSummary = plan.slice(compactStart, compactEnd);
  assert.doesNotMatch(compactSummary, /data-plan-evidence-list/);
  assert.doesNotMatch(compactSummary, /coach-plan-view__compact-fact/);
  assert.doesNotMatch(compactSummary, /memoryScopeContext/);
  assert.match(compactSummary, /coach-plan-view__now-done/);
  assert.match(compactSummary, /coach-plan-view__now-next/);
  assert.match(app, /openPlanComposerMode\("evidence"\)/);
});

test('training first viewport is the current card plus one primary, with skip/grade on the composer', () => {
  const training = read('components/training/TrainingWorkbenchView.tsx');
  const app = read('app/App.tsx');
  const cardOnlyStart = training.indexOf('{cardOnly ? (');
  const cardOnlyEnd = training.indexOf('{!cardOnly ? (', cardOnlyStart);
  assert.ok(cardOnlyStart >= 0 && cardOnlyEnd > cardOnlyStart, 'expected card-only first viewport');
  const cardOnly = training.slice(cardOnlyStart, cardOnlyEnd);
  assert.match(cardOnly, /data-view-object=""/);
  assert.match(cardOnly, /data-view-why=""/);
  assert.match(cardOnly, /data-view-primary=""/);
  assert.match(cardOnly, /training-current__card-section/);
  assert.doesNotMatch(cardOnly, /training-current__more/);
  assert.doesNotMatch(cardOnly, /training-loop-rail/);
  assert.doesNotMatch(cardOnly, /card-status-nav/);
  assert.doesNotMatch(cardOnly, /handleSkipCard/);
  assert.doesNotMatch(cardOnly, /handleGradeCard/);
  assert.doesNotMatch(cardOnly, /TrainingNextHopLine/);
  assert.match(training, /training-current__verify-result/);
  assert.match(training, /export function interpretTrainingComposerCardCommand/);
  assert.match(training, /export function applyTrainingCardSkip/);
  assert.match(training, /export function applyTrainingCardGrade/);
  assert.match(app, /interpretTrainingComposerCardCommand\(normalizedDraft\)/);
  assert.match(app, /applyTrainingCardSkip\(/);
  assert.match(app, /applyTrainingCardGrade\(/);
  assert.doesNotMatch(app, /onClick=\{handleVerifyTrainingFromIde\}[\s\S]{0,80}trainingFilePracticeTextCopy\.verifyCurrentFile/);
  assert.match(app, /id: "composer-verify-file"/);
  assert.match(app, /onClick: handleVerifyTrainingFromIde/);
});
