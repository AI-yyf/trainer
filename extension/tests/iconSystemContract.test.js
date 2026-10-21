'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const WEBVIEW_SRC = path.resolve(__dirname, '..', 'webview', 'src');
const BASE_CSS = path.join(
  WEBVIEW_SRC,
  'styles',
  'sections',
  'trainer-design-tokens-base-styles.css',
);
const TEMPLATES_CSS = path.join(WEBVIEW_SRC, 'templates', 'templates.css');
const APP_SHELL = path.join(WEBVIEW_SRC, 'templates', 'AppShell.tsx');

const ALLOWED_ICON_SIZES = new Set([12, 14, 16, 18, 20]);

function walk(dir) {
  const found = [];
  for (const name of fs.readdirSync(dir).sort()) {
    const absolute = path.join(dir, name);
    const stats = fs.statSync(absolute);
    if (stats.isDirectory()) {
      found.push(...walk(absolute));
    } else if (name.endsWith('.tsx') || name.endsWith('.ts')) {
      found.push(absolute);
    }
  }
  return found;
}

test('every Trainer icon uses the five-step optical size scale', () => {
  const violations = [];
  for (const file of walk(WEBVIEW_SRC)) {
    if (!file.endsWith('.tsx')) {
      continue;
    }
    const source = fs.readFileSync(file, 'utf8');
    const pattern = /<[A-Z][A-Za-z0-9]*Icon\b[^>]*?\bsize=\{(\d+)\}/gs;
    for (const match of source.matchAll(pattern)) {
      const size = Number(match[1]);
      if (!ALLOWED_ICON_SIZES.has(size)) {
        const line = source.slice(0, match.index).split('\n').length;
        violations.push(`${path.relative(WEBVIEW_SRC, file)}:${line} size=${size}`);
      }
    }
  }
  assert.deepEqual(violations, [], `off-scale icon sizes found:\n${violations.join('\n')}`);
});

test('header utilities use the header optical size and have real interaction states', () => {
  const shell = fs.readFileSync(APP_SHELL, 'utf8');
  assert.match(shell, /<HistoryIcon size=\{18\}/);
  assert.match(shell, /<SettingsIcon size=\{18\}/);

  const css = fs.readFileSync(TEMPLATES_CSS, 'utf8');
  assert.match(css, /\.app-shell-header__utility:hover/);
  assert.match(css, /\.app-shell-header__utility:active/);
  assert.match(css, /\.app-shell-header__utility:disabled/);
  assert.match(css, /\.app-shell-header__utility\[aria-pressed="true"\]/);
});

test('the icon base owns display/overflow normalization', () => {
  const css = fs.readFileSync(BASE_CSS, 'utf8');
  assert.match(css, /\.trainer-icon\s*\{[^}]*display:\s*inline-block/s);
  assert.match(css, /\.trainer-icon\s*\{[^}]*flex:\s*none/s);
  assert.match(css, /\.trainer-icon\s*\{[^}]*overflow:\s*visible/s);
});

test('icon-like SVGs render through TrainerIconBase (no ad-hoc raw icons)', () => {
  const violations = [];
  for (const file of walk(WEBVIEW_SRC)) {
    if (!file.endsWith('.tsx')) {
      continue;
    }
    const relative = path.relative(WEBVIEW_SRC, file);
    if (relative === path.join('components', 'icons', 'TrainerIconBase.tsx')) {
      continue;
    }
    const source = fs.readFileSync(file, 'utf8');
    if (!source.includes('<svg')) {
      continue;
    }
    // The composer context ring is a data visualisation, not an icon.
    if (relative === path.join('app', 'App.tsx')) {
      continue;
    }
    violations.push(relative);
  }
  assert.deepEqual(violations, [], `raw <svg> icons found:\n${violations.join('\n')}`);
});
