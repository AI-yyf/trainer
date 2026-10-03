
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
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});

test('responsive sidebar density swaps squeezed labels for icons', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});
