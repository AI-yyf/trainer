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

test('production workbench views consume CSS variables rather than hardcoded hex colors', () => {
  const styles = readStylesSource();
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
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').learning();
});

test('training first viewport is the current card plus one primary, with skip/grade on the composer', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
});
