'use strict';

/**
 * Colour source guard: Trainer must not ship a hardcoded hue or a second
 * emphasis colour. Every visible colour resolves from --vscode-* theme
 * variables or the neutral token layer; the only literals allowed are CSS
 * system colours used by the browser-preview fallback.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..', '..');
const webviewRoot = path.join(repoRoot, 'extension', 'webview', 'src');
const sharedRoot = path.join(repoRoot, 'shared', 'src');

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'dist') continue;
      walk(full, out);
    } else if (/\.(css|tsx?|jsx?)$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

test('no hardcoded hex, rgb(), hsl() or named hues in the workbench source', () => {
  const failures = [];
  for (const file of walk(webviewRoot).concat(walk(sharedRoot))) {
    const source = stripComments(fs.readFileSync(file, 'utf8'));
    if (/#[0-9a-fA-F]{3,8}\b/.test(source)) {
      failures.push(`${path.relative(repoRoot, file)}: hex colour`);
    }
    if (/\b(rgba?|hsla?)\(/.test(source)) {
      failures.push(`${path.relative(repoRoot, file)}: rgb()/hsl() colour`);
    }
    if (/(?:color|background|border(?:-[a-z]+)?|fill|stroke)\s*:\s*(white|black|red|blue|green|yellow|orange|purple|pink|gray|grey)\b/.test(source)) {
      failures.push(`${path.relative(repoRoot, file)}: named colour`);
    }
  }
  assert.deepEqual(failures, []);
});

test('the token layer carries no accent hue and no coloured focus border', () => {
  const tokens = fs.readFileSync(
    path.join(
      webviewRoot,
      'styles',
      'sections',
      'trainer-design-tokens-base-styles.css',
    ),
    'utf8',
  );
  assert.doesNotMatch(tokens, /charts-orange|vscode-focusBorder|textLink-foreground/);
  assert.match(tokens, /--accent:\s*var\(--fg-0\);/);
  assert.match(tokens, /--focus-ring:\s*color-mix\(in srgb, var\(--fg-0\)/);
  assert.match(tokens, /--link:\s*var\(--fg-0\);/);
});
