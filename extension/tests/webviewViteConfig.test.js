'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const viteConfigPath = path.resolve(__dirname, '..', 'webview', 'vite.config.ts');

test('production webview build keeps the browser preview behind its explicit build mode', () => {
  const source = fs.readFileSync(viteConfigPath, 'utf8');

  assert.match(source, /rollupOptions:\s*\{/);
  assert.ok(source.includes('index.html'));
  assert.ok(source.includes('vscode-preview.html'));
  assert.match(source, /input:\s*\{[\s\S]*?main: resolve\(rootDir, "index\.html"\),[\s\S]*?preview: resolve\(rootDir, "vscode-preview\.html"\),/);
  assert.match(source, /TRAINER_WEBVIEW_OUT_DIR/);
});
