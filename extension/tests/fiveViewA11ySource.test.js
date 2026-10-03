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

test('composer and five-view navigation have accessible names and visible focus', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});

test('language switch keeps the active view and composer stays the super-entry', () => {
  const state = read('app/useWorkbenchState.ts');
  const app = read('app/App.tsx');
  const types = read('lib/types.ts');
  const settings = read('components/settings/CoachSettingsView.tsx');

  assert.match(
    state,
    /setComposerLanguage:\s*\(composerLanguage\)\s*=>\s*set\(\(state\)\s*=>\s*\(\{\s*layout:\s*persistLayout\(\{\s*\.\.\.state\.layout,\s*composerLanguage,/,
  );
  assert.match(app, /showComposerShell = ownsCoachComposer\(activeView\)/);
  assert.match(settings, /data-settings-language="true"/);
  assert.doesNotMatch(
    types,
    /export const COACH_FIRST_SIDEBAR_VIEWS = \[[^\]]*"research"/s,
  );
});
