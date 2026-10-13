'use strict';

const test = require('node:test');

// PR-7: styles.css is an @import aggregator; rules live in styles/sections/*.
function readStylesSource() {
  const fsMod = require('node:fs');
  const pathMod = require('node:path');
  const root = pathMod.resolve(__dirname, '..', 'webview', 'src');
  const manifest = JSON.parse(fsMod.readFileSync(
    pathMod.join(root, 'styles', 'sections', 'manifest.json'), 'utf8'));
  return manifest.map(
    (entry) => fsMod.readFileSync(pathMod.join(root, entry.file), 'utf8'),
  ).join('');
}

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');

function read(relativePath) {
  return fs.readFileSync(path.join(webviewRoot, relativePath), 'utf8');
}

test('Codex-quiet motion tokens and required transitions live in styles.css', () => {
  const styles = readStylesSource();
  assert.match(styles, /--motion-fast:\s*120ms;/);
  assert.match(styles, /--motion-in:\s*160ms;/);
  assert.match(styles, /--motion-out:\s*120ms;/);
  assert.match(styles, /--motion-ease:\s*cubic-bezier\(0\.2,\s*0\.8,\s*0\.2,\s*1\)/);
  assert.match(styles, /animation:\s*messageFadeIn var\(--motion-in\) var\(--motion-ease\)/);
  assert.match(styles, /transform:\s*translateY\(6px\)/);
  assert.match(styles, /\.composer__send:active:not\(:disabled\)[\s\S]{0,80}transform:\s*scale\(0\.96\)/);
  assert.match(styles, /@media \(prefers-reduced-motion:\s*reduce\)/);
  assert.match(styles, /animation:\s*none !important;/);
  // Reduced motion is gentler, not zero: property changes stay wired but
  // land instantly, and movement keyframes are dropped.
  assert.match(styles, /transition-duration:\s*0\.01ms !important;/);
  assert.doesNotMatch(styles, /\.coach-action-pill__dot--pulse[\s\S]{0,80}animation:\s*coach-action-pulse/);
  assert.doesNotMatch(styles, /\.agent-activity-pill__dot--running[\s\S]{0,80}animation:\s*agent-activity-pulse/);

  const chromeChunks = [
    styles.slice(styles.indexOf('.header-switcher'), styles.indexOf('.header-switcher') + 2500),
    styles.slice(styles.indexOf('.composer__send {'), styles.indexOf('.composer__send {') + 1200),
    styles.slice(styles.indexOf('.button {'), styles.indexOf('.button {') + 800),
  ].join('\n');
  assert.doesNotMatch(chromeChunks, /transition:\s*all\b/);
});

test('composer action glyphs go through the unified TrainerIconBase stroke family', () => {
  // Icon grammar converged (2026-10-14): the legacy 16-box/1.55 IconBase is
  // gone; CoachIcons renders its historical 16-grid drawings on the single
  // TrainerIconBase grammar (1.4 currentColor stroke, optical size 16).
  const trainerBase = read('components/icons/TrainerIconBase.tsx');
  const coachIcons = read('components/icons/CoachIcons.tsx');
  const composer = read('components/composer/CoachComposer.tsx');
  const training = read('components/training/TrainingWorkbenchView.tsx');

  assert.match(trainerBase, /viewBox = "0 0 20 20"/);
  assert.match(trainerBase, /strokeWidth=\{1\.4\}/);
  assert.match(trainerBase, /stroke="currentColor"/);
  assert.match(trainerBase, /strokeLinecap="round"/);
  assert.match(coachIcons, /from "\.\/TrainerIconBase"/);
  assert.match(coachIcons, /viewBox="0 0 16 16"/);
  assert.doesNotMatch(coachIcons, /strokeWidth=\{1\.55\}/);
  assert.match(composer, /from ["']\.\.\/icons["']/);
  assert.match(coachIcons, /export function SparklesIcon/);
  const cardFace = training.slice(
    training.indexOf("training-current__sentence"),
    training.indexOf("{!cardOnly ? ("),
  );
  assert.doesNotMatch(cardFace, /<SparklesIcon|<FireIcon|<TrophyIcon/);
});
