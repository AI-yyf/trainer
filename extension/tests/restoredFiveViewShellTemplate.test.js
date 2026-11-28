// Restored behavioral regression test. Original file: extension/tests/fiveViewFirstViewportSource.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Five-view shell: three-layer shell without identity chrome. navigation template: templateAssertions.navigation() renders templates/AppShell.tsx per route and asserts on the markup.
//
// Restoration: partial - 1 of 4 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "production workbench views consume CSS variables rather than hardcoded hex colors" [source-text guard]
//   - "plan first viewport keeps a work-surface object without a governance dump" [source-text guard]
//   - "training first viewport is the current card plus one primary, with skip/grade on the composer" [source-text guard]
// Target: webview components rendered to static markup through templateAssertions.render.

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
const sharedRoot = path.resolve(__dirname, '..', '..', 'shared', 'src');

function read(relativePath, root = webviewRoot) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

test('five views stay the Codex three-layer shell without identity chrome', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});


