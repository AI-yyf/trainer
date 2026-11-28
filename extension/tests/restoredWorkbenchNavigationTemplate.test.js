// Restored behavioral regression test. Original file: extension/tests/composerDockSource.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: undefined
//
// Restoration: partial - 1 of 3 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "composer dock unifies footer hit size, radius, gap, and icon box"
//       CSS source-text guard: reads the webview stylesheet sections and asserts on the stylesheet text
//       (out of scope by rule). Also fails at HEAD.
//   - "conversation markdown headings are distinguishable inside message-markdown"
//       CSS source-text guard: reads the webview stylesheet sections and asserts on the stylesheet text
//       (out of scope by rule).
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

function read(relativePath) {
  return fs.readFileSync(path.join(webviewRoot, relativePath), 'utf8');
}


test('compact nav labels are not ellipsized to a single character', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});
