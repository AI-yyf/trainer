
// PR-7: styles.css is an @import aggregator; the real rules live in
// styles/sections/*.css. Read them concatenated in manifest order so
// assertions see the same bytes the browser gets after bundling.
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

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

test('responsive sidebar labels retain the official five-view names', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    source,
    /function compactSidebarViewLabel\(\s*view: ActiveWorkbenchView,\s*language: ComposerLanguage,\s*fullLabel: string,\s*\): string \{\s*return fullLabel;\s*\}/s,
  );
  assert.match(source, /const displayLabel = headerSwitcherDensity === "compact" \? compactLabel : label;/);
  assert.doesNotMatch(source, /return "Res";/);
  assert.doesNotMatch(source, /return "Train";/);
  assert.doesNotMatch(source, /return "Setup";/);
});

test('responsive sidebar density swaps squeezed labels for icons', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const styles = readStylesSource();

  assert.match(styles, /\.header-switcher--compact\s*\{\s*gap:\s*0;/);
  assert.match(styles, /\.header-switcher--compact \.header-switcher__item\s*\{[\s\S]*?padding:\s*6px 2px 8px;[\s\S]*?font-size:\s*var\(--trainer-font-2xs\);/);
  assert.match(styles, /\.header-switcher--compact \.header-switcher__label\s*\{\s*font-size:\s*var\(--trainer-font-2xs\);/);
  // The narrowest tier hides the text label and shows the per-view icon;
  // the button keeps its aria-label so the accessible name is unchanged.
  assert.match(source, /"full" \| "compact" \| "icon"/);
  assert.match(source, /header-switcher__icon/);
  assert.match(source, /return "icon";/);
  assert.match(styles, /\.header-switcher--icon \.header-switcher__icon\s*\{[\s\S]*?display:\s*inline-flex;/);
  assert.match(styles, /\.header-switcher--icon \.header-switcher__label\s*\{[\s\S]*?display:\s*none;/);
});
