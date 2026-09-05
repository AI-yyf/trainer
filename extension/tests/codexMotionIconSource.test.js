'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');

function read(relativePath) {
  return fs.readFileSync(path.join(webviewRoot, relativePath), 'utf8');
}

test('Codex-quiet motion tokens and required transitions live in styles.css', () => {
  const styles = read('styles.css');
  assert.match(styles, /--motion-fast:\s*120ms;/);
  assert.match(styles, /--motion-in:\s*160ms;/);
  assert.match(styles, /--motion-out:\s*120ms;/);
  assert.match(styles, /--motion-ease:\s*cubic-bezier\(0\.2,\s*0\.8,\s*0\.2,\s*1\)/);
  assert.match(styles, /animation:\s*messageFadeIn var\(--motion-in\) var\(--motion-ease\)/);
  assert.match(styles, /transform:\s*translateY\(6px\)/);
  assert.match(styles, /\.composer__send:active:not\(:disabled\)[\s\S]{0,80}transform:\s*scale\(0\.96\)/);
  assert.match(styles, /@media \(prefers-reduced-motion:\s*reduce\)/);
  assert.match(styles, /animation:\s*none !important;/);
  assert.match(styles, /transition:\s*none !important;/);
  assert.doesNotMatch(styles, /\.coach-action-pill__dot--pulse[\s\S]{0,80}animation:\s*coach-action-pulse/);
  assert.doesNotMatch(styles, /\.agent-activity-pill__dot--running[\s\S]{0,80}animation:\s*agent-activity-pulse/);

  const chromeChunks = [
    styles.slice(styles.indexOf('.header-switcher'), styles.indexOf('.header-switcher') + 2500),
    styles.slice(styles.indexOf('.composer__send {'), styles.indexOf('.composer__send {') + 1200),
    styles.slice(styles.indexOf('.button {'), styles.indexOf('.button {') + 800),
  ].join('\n');
  assert.doesNotMatch(chromeChunks, /transition:\s*all\b/);
});

test('composer action glyphs go through IconBase stroke family', () => {
  const iconBase = read('components/icons/IconBase.tsx');
  const composer = read('components/composer/CoachComposer.tsx');
  const icons = read('components/icons/CoachIcons.tsx');
  const training = read('components/training/TrainingWorkbenchView.tsx');

  assert.match(iconBase, /viewBox = "0 0 16 16"/);
  assert.match(iconBase, /strokeWidth=\{1\.55\}/);
  assert.match(iconBase, /stroke="currentColor"/);
  assert.match(iconBase, /strokeLinecap="round"/);
  assert.match(composer, /from ["']\.\.\/icons["']/);
  assert.match(icons, /export function SparklesIcon/);
  const cardFace = training.slice(
    training.indexOf("training-current__sentence"),
    training.indexOf("{!cardOnly ? ("),
  );
  assert.doesNotMatch(cardFace, /<SparklesIcon|<FireIcon|<TrophyIcon/);
});
