'use strict';

// The webview's startup cost is a product concern: VS Code loads it on every
// sidebar activation, so anything statically imported is parsed before the
// first message renders.
//
// Shiki was the worst offender. `import { codeToHtml } from "shiki"` sat at the
// top of ShikiCodeBlock.tsx even though codeToHtml is only called from an
// async function, which pulled every bundled grammar into the eager graph —
// cpp at 785 kB, emacs-lisp at 790 kB, wasm at 622 kB and dozens more. The
// eager main chunk fell from 878 kB to 737 kB once it became a dynamic import.
//
// A source-text assertion cannot hold that line, because a top-level import is
// exactly what the comment also rules out and the two are easy to confuse. So
// there is a second test that builds the bundle and measures the real entry
// chunk — the thing a regression would actually break.
//
// Building costs ~30s, which is more than the whole fast suite, so the
// measurement is opt-in: `TRAINER_CHECK_BUNDLE_SIZE=1 npm run test:extension`.
// The source assertion below always runs and costs nothing.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const webviewRoot = path.resolve(__dirname, '..', 'webview');
const shikiBlockPath = path.resolve(
  webviewRoot,
  'src',
  'components',
  'coach',
  'parts',
  'ShikiCodeBlock.tsx',
);

const run = (bin, args) =>
  spawnSync(process.execPath, [path.join(webviewRoot, 'node_modules', bin, 'bin', bin === 'vite' ? 'vite.js' : 'tsc'), ...args], {
    cwd: webviewRoot,
    encoding: 'utf8',
  });

const wantsBundleSize = process.env.TRAINER_CHECK_BUNDLE_SIZE === '1';

test('the eager webview chunk stays small enough to open a sidebar quickly', (t) => {
  if (!wantsBundleSize) {
    t.skip('set TRAINER_CHECK_BUNDLE_SIZE=1 to build the bundle and measure the entry chunk');
    return;
  }
  if (!fs.existsSync(path.join(webviewRoot, 'node_modules', 'vite'))) {
    t.skip('webview dependencies are not installed');
    return;
  }

  assert.equal(run('typescript', ['-b']).status, 0);
  const vite = run('vite', ['build', '--mode', 'preview', '--logLevel', 'error']);
  assert.equal(vite.status, 0, vite.stderr || vite.stdout);
  const distDir = path.join(webviewRoot, 'dist', 'assets');

  const assets = fs
    .readdirSync(distDir)
    .map((file) => ({ file, bytes: fs.statSync(path.join(distDir, file)).size }))
    .filter((entry) => entry.file.startsWith('App-') && entry.file.endsWith('.js'));

  assert.equal(assets.length, 1, `expected exactly one App entry chunk, got ${assets.map((a) => a.file).join(', ')}`);
  const kib = assets[0].bytes / 1024;

  // 737 kB after the fix. The pre-fix bundle was 878 kB, so this sits close
  // enough to catch a regression while leaving room for unrelated growth.
  assert.ok(
    kib < 820,
    `App entry chunk is ${kib.toFixed(0)} kB — a heavy dependency is back in the eager graph ` +
      '(shiki grammars, a full linter, a graph renderer). VS Code re-parses this on every sidebar activation.',
  );
});

test('Shiki is loaded lazily, not pulled in at module scope', () => {
  const source = fs.readFileSync(shikiBlockPath, 'utf8');
  const staticImport = /^\s*import\s[^;]*from\s+['"]shiki['"]/m;
  assert.doesNotMatch(
    source,
    staticImport,
    'ShikiCodeBlock must not statically import shiki — every bundled grammar ends up in the eager chunk',
  );
  assert.match(
    source,
    /await import\(["']shiki["']\)/,
    'ShikiCodeBlock should load shiki through the lazy loader',
  );
});
