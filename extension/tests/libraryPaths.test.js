'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');

const tsPath = path.resolve(__dirname, '..', 'webview', 'src', 'components', 'resources', 'libraryPaths.ts');
const tsc = path.resolve(__dirname, '..', 'node_modules', 'typescript', 'bin', 'tsc');

let libraryPaths;
test('setup', () => {
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'library-paths-'));
  execFileSync(process.execPath, [
    tsc,
    tsPath,
    '--outDir',
    outDir,
    '--module',
    'commonjs',
    '--target',
    'es2022',
    '--skipLibCheck',
    '--declaration',
    'false',
  ]);
  libraryPaths = require(
    path.join(outDir, 'extension', 'webview', 'src', 'components', 'resources', 'libraryPaths.js'),
  );
});

test('normalizes slashes, trailing separators and drive prefixes', () => {
  const { normalizePath, pathSegments } = libraryPaths;
  assert.equal(normalizePath(' Docs\\Coach\\ '), 'Docs/Coach');
  assert.deepEqual(pathSegments('C:\\Work\\Docs\\a.md'), ['Work', 'Docs', 'a.md']);
  assert.deepEqual(pathSegments('/srv/../etc/passwd'), ['srv', 'etc', 'passwd']);
});

test('logical collection paths reject absolute or internal intake layouts', () => {
  const { collectionPathSegments, collectionSegmentPrefix } = libraryPaths;
  assert.deepEqual(
    collectionPathSegments('Docs/Coach', 'library'),
    ['Docs', 'Coach'],
  );
  assert.deepEqual(collectionPathSegments('/abs/Docs', 'library'), []);
  assert.deepEqual(collectionPathSegments('sources/inbox/context-1234abcd', 'library'), []);
  assert.equal(collectionSegmentPrefix, '__collection__:');
});

test('hidden trainer roots never become visible folder names', () => {
  const { trimHiddenCollectionRoots, visibleCollectionSegments } = libraryPaths;
  assert.deepEqual(
    trimHiddenCollectionRoots(['.trainer', 'memory', 'Docs']),
    ['memory', 'Docs'],
  );
  assert.deepEqual(
    visibleCollectionSegments(['sources', 'inbox', 'context-1234abcd', 'Docs']),
    ['Docs'],
  );
});

test('sandbox-relative paths and compact labels stay bounded', () => {
  const { relativeSandboxPath, compactSandboxPath } = libraryPaths;
  assert.equal(relativeSandboxPath('/sandbox/Docs/a.md', '/sandbox'), 'Docs/a.md');
  assert.equal(relativeSandboxPath('/other/Docs/a.md', '/sandbox'), undefined);
  assert.equal(compactSandboxPath('/sandbox/Docs/a.md', '/sandbox'), 'Docs/a.md');
  assert.equal(
    compactSandboxPath('/a/b/c/d/e/file.md', undefined),
    'd/e/file.md',
  );
});

test('fallback folder grouping keeps URLs, sandbox files and local folders distinct', () => {
  const { fallbackCollectionSegments, collectionSegmentPrefix } = libraryPaths;
  assert.deepEqual(
    fallbackCollectionSegments(
      { kind: 'url', source: 'https://learn.example.com/guide/page' },
      undefined,
    ),
    [`${collectionSegmentPrefix}web-snapshots`, 'learn.example.com'],
  );
  assert.deepEqual(
    fallbackCollectionSegments(
      { kind: 'file', source: 'src/module/notes.md' },
      undefined,
    ),
    ['src', 'module'],
  );
});

test('resource tree segments prefer logical collections, then sandbox nodes', () => {
  const { resourceTreeSegments } = libraryPaths;
  const logical = resourceTreeSegments(
    { kind: 'file', source: 'x.md', collectionPath: 'Docs/Coach', collectionRoot: 'library' },
    undefined,
    [],
  );
  assert.deepEqual(logical, ['Docs']);

  const sandbox = resourceTreeSegments(
    { kind: 'file', source: 'notes.md', sandboxPath: '/sandbox/Docs/notes.md' },
    '/sandbox',
    [{ normalizedPaths: ['/sandbox/Docs/notes.md'], relativeSegments: ['Docs', 'notes.md'] }],
  );
  assert.deepEqual(sandbox, ['Docs']);
});
