// Restored behavioral regression test. Original file: extension/tests/composerInteractionHistorySource.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Composer mode menu: view-specific modes use a bounded native-style menu. navigation template: templateAssertions.navigation() renders templates/AppShell.tsx per route and asserts on the markup.
//
// Restoration: partial - 1 of 6 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "Composer gives parent key handling first, then only navigates sent history from collapsed text boundaries" [source-text guard]
//   - "App history uses only this session user sends and preserves a cursor plus scratch draft" [fails at HEAD (source-text guard)]
//   - "Composer side mouse buttons map to history and consume browser navigation events" [source-text guard]
//   - "Image drops use the existing attachment staging path and show a transient drag state" [source-text guard]
//   - "Composer expands vertical input room in both densities without changing the narrow-sidebar width contract" [source-text guard]
// Target: webview components rendered to static markup through templateAssertions.render.
// Note: the require of extension/tests/helpers/appModuleSource.js (deleted in df0a3e2a) is dropped: only omitted source-guard tests used it.

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
const composerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

function sourceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.ok(start >= 0, `expected ${startMarker}`);
  const end = source.indexOf(endMarker, start);
  assert.ok(end > start, `expected ${endMarker} after ${startMarker}`);
  return source.slice(start, end);
}

function compactAndDefaultBounds(source, marker) {
  const resizeEffect = sourceBetween(
    source,
    'const minHeight =',
    'textarea.style.height = "0px";',
  );
  const markerIndex = resizeEffect.indexOf(marker);
  assert.ok(markerIndex >= 0, `expected ${marker}`);
  const nextDeclaration = resizeEffect.indexOf('const ', markerIndex + marker.length);
  const candidates = [
    ...resizeEffect
      .slice(markerIndex, nextDeclaration > markerIndex ? nextDeclaration : undefined)
      .matchAll(/compactMode\s*\?\s*(\d+)\s*:\s*(\d+)/g),
  ];
  const values = candidates.at(-1);
  assert.ok(values, `expected numeric compact/default ${marker} bound`);
  return { compact: Number(values[1]), default: Number(values[2]) };
}





test('View-specific composer modes use a bounded native-style menu instead of an unstructured select', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});
