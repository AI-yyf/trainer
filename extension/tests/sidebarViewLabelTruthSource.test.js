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

test('responsive sidebar density only tightens text spacing and never switches to icons', () => {
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.match(styles, /\.header-switcher--compact\s*\{\s*gap:\s*0;/);
  assert.match(styles, /\.header-switcher--compact \.header-switcher__item\s*\{[\s\S]*?padding:\s*6px 2px 8px;[\s\S]*?font-size:\s*var\(--trainer-font-2xs\);/);
  assert.match(styles, /\.header-switcher--compact \.header-switcher__label\s*\{\s*font-size:\s*var\(--trainer-font-2xs\);/);
  assert.doesNotMatch(styles, /\.header-switcher--icons/);
  assert.doesNotMatch(styles, /\.header-switcher--compact[\s\S]{0,300}display:\s*none;/);
});
