'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const { zip } = require('./fixtures/zip');

const repoRoot = path.resolve(__dirname, '..', '..');
const extensionDir = path.resolve(__dirname, '..');
const bundleModulePath = path.join(extensionDir, 'scripts', 'bundle-browser-capture.mjs');
const prepublishModulePath = path.join(extensionDir, 'scripts', 'prepublish-vsix.mjs');
const verifyPackageModulePath = path.join(extensionDir, 'scripts', 'verify-package.mjs');
const packageVsixModulePath = path.join(extensionDir, 'scripts', 'package-vsix.mjs');
const rootPackageBrowserModulePath = path.join(repoRoot, 'scripts', 'package-browser-extension.mjs');

let modulePromise;

function loadBundleModule() {
  if (!modulePromise) {
    modulePromise = import(pathToFileURL(bundleModulePath).href);
  }
  return modulePromise;
}

function writeFile(targetPath, content = '') {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(targetPath, content, 'utf8');
}

function createFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-capture-package-'));
  const sourceDir = path.join(root, 'browser-extension');
  const stagedDir = path.join(root, 'extension', 'browser-capture');
  writeFile(path.join(sourceDir, 'manifest.json'), JSON.stringify({ name: 'Trainer Capture', version: '0.1.0' }));
  writeFile(path.join(sourceDir, 'background.js'), '// service worker\n');
  writeFile(path.join(sourceDir, 'shared.js'), '// shared\n');
  writeFile(path.join(sourceDir, 'popup', 'popup.html'), '<html></html>\n');
  writeFile(path.join(sourceDir, 'icons', 'icon16.png'), 'png');
  writeFile(path.join(sourceDir, 'README.md'), '# Trainer Capture\n');
  // Packaging junk must never be staged into the VSIX.
  writeFile(path.join(sourceDir, '._ghost.js'), 'ghost');
  writeFile(path.join(sourceDir, '.DS_Store'), 'junk');
  writeFile(path.join(sourceDir, 'trainer-capture-extension.zip'), 'zip');
  writeFile(path.join(sourceDir, 'bundle.js.map'), 'map');
  return {
    root,
    extensionDir: path.join(root, 'extension'),
    repoRoot: root,
    sourceDir,
    stagedDir,
  };
}

test('syncBrowserCaptureExtension stages the unpacked extension with a version marker', async () => {
  const { syncBrowserCaptureExtension } = await loadBundleModule();
  const fixture = createFixture();
  try {
    // A stale tree (including a removed script) is replaced, not merged.
    writeFile(path.join(fixture.stagedDir, 'removed-script.js'), '// stale\n');
    writeFile(path.join(fixture.stagedDir, 'nested', 'old.html'), '<html></html>\n');

    const result = syncBrowserCaptureExtension({
      extensionDir: fixture.extensionDir,
      repoRoot: fixture.repoRoot,
      env: { TRAINER_VSIX_CAPTURE_QUIET: '1' },
    });

    assert.equal(result.staged, true);
    assert.equal(result.fileCount, 6);
    assert.equal(result.version, '0.1.0');
    for (const relative of [
      'manifest.json',
      'background.js',
      'shared.js',
      'popup/popup.html',
      'icons/icon16.png',
      'README.md',
    ]) {
      assert.equal(fs.existsSync(path.join(fixture.stagedDir, relative)), true, relative);
    }
    assert.equal(fs.existsSync(path.join(fixture.stagedDir, 'removed-script.js')), false);
    assert.equal(fs.existsSync(path.join(fixture.stagedDir, 'nested', 'old.html')), false);
    assert.equal(fs.existsSync(path.join(fixture.stagedDir, '._ghost.js')), false);
    assert.equal(fs.existsSync(path.join(fixture.stagedDir, '.DS_Store')), false);
    assert.equal(fs.existsSync(path.join(fixture.stagedDir, 'trainer-capture-extension.zip')), false);
    assert.equal(fs.existsSync(path.join(fixture.stagedDir, 'bundle.js.map')), false);

    const marker = JSON.parse(
      fs.readFileSync(path.join(fixture.stagedDir, 'trainer-browser-capture.json'), 'utf8'),
    );
    assert.deepEqual(marker, {
      schemaVersion: 1,
      name: 'trainer-capture',
      version: '0.1.0',
      fileCount: 6,
      generatedFrom: 'browser-extension',
    });

    const verified = (await loadBundleModule()).verifyBrowserCaptureBundle({
      extensionDir: fixture.extensionDir,
      repoRoot: fixture.repoRoot,
    });
    assert.equal(verified.staged, true);
    assert.equal(verified.ok, true);
    assert.deepEqual(verified.errors, []);
    assert.equal(verified.version, '0.1.0');
  } finally {
    fs.rmSync(fixture.root, { recursive: true, force: true });
  }
});

test('missing browser-extension source is skipped; a missing staged tree fails closed', async () => {
  const { syncBrowserCaptureExtension, verifyBrowserCaptureBundle } = await loadBundleModule();
  const fixture = createFixture();
  try {
    const withoutSource = {
      extensionDir: fixture.extensionDir,
      repoRoot: path.join(fixture.root, 'empty-repo'),
    };
    const skippedSync = syncBrowserCaptureExtension({ ...withoutSource, env: {} });
    assert.equal(skippedSync.staged, false);
    assert.match(skippedSync.reason, /source directory is missing/);

    const skippedVerify = verifyBrowserCaptureBundle(withoutSource);
    assert.equal(skippedVerify.staged, false);
    assert.equal(skippedVerify.ok, true);
    assert.deepEqual(skippedVerify.errors, []);

    // The source exists but nothing was staged: verification must fail closed.
    const missingStaged = verifyBrowserCaptureBundle({
      extensionDir: fixture.extensionDir,
      repoRoot: fixture.repoRoot,
    });
    assert.equal(missingStaged.staged, true);
    assert.equal(missingStaged.ok, false);
    assert.match(missingStaged.errors.join('\n'), /Staged browser capture bundle is missing/);
    assert.match(missingStaged.errors.join('\n'), /bundle:browser-capture/);
  } finally {
    fs.rmSync(fixture.root, { recursive: true, force: true });
  }
});

test('verifyBrowserCaptureBundle detects staged drift, stale files and a stale marker', async () => {
  const { syncBrowserCaptureExtension, verifyBrowserCaptureBundle } = await loadBundleModule();
  const fixture = createFixture();
  try {
    syncBrowserCaptureExtension({
      extensionDir: fixture.extensionDir,
      repoRoot: fixture.repoRoot,
      env: { TRAINER_VSIX_CAPTURE_QUIET: '1' },
    });

    writeFile(path.join(fixture.stagedDir, 'background.js'), '// drifted\n');
    writeFile(path.join(fixture.stagedDir, 'extra.js'), '// unexpected\n');
    writeFile(
      path.join(fixture.stagedDir, 'trainer-browser-capture.json'),
      JSON.stringify({ schemaVersion: 1, name: 'trainer-capture', version: '0.0.1', fileCount: 6 }),
    );

    const report = verifyBrowserCaptureBundle({
      extensionDir: fixture.extensionDir,
      repoRoot: fixture.repoRoot,
    });

    assert.equal(report.ok, false);
    assert.deepEqual(report.contentMismatches, ['background.js']);
    assert.deepEqual(report.unexpectedFiles, ['extra.js']);
    const errors = report.errors.join('\n');
    assert.match(errors, /drift detected: browser-capture\/background\.js/);
    assert.match(errors, /unexpected file: browser-capture\/extra\.js/);
    assert.match(errors, /version marker does not match/);
  } finally {
    fs.rmSync(fixture.root, { recursive: true, force: true });
  }
});

test('the VSIX archive gate requires every staged browser-capture entry', async () => {
  const { collectBrowserCaptureVsixEntries, verifyBrowserCaptureVsixArtifact } =
    await loadBundleModule();
  const fixture = createFixture();
  try {
    const { syncBrowserCaptureExtension } = await loadBundleModule();
    syncBrowserCaptureExtension({
      extensionDir: fixture.extensionDir,
      repoRoot: fixture.repoRoot,
      env: { TRAINER_VSIX_CAPTURE_QUIET: '1' },
    });
    const bundleEntries = collectBrowserCaptureVsixEntries({ extensionDir: fixture.extensionDir });
    assert.ok(bundleEntries.includes('browser-capture/manifest.json'));
    assert.ok(bundleEntries.includes('browser-capture/trainer-browser-capture.json'));

    const completeEntries = Object.fromEntries(
      bundleEntries.map((relative) => [`extension/${relative}`, 'payload']),
    );
    const completePath = path.join(fixture.root, 'complete.vsix');
    fs.writeFileSync(completePath, zip(completeEntries));
    const complete = verifyBrowserCaptureVsixArtifact({
      vsixPath: completePath,
      bundleEntries,
    });
    assert.equal(complete.required, true);
    assert.deepEqual(complete.errors, []);
    assert.deepEqual(complete.missingEntries, []);

    const incompletePath = path.join(fixture.root, 'incomplete.vsix');
    fs.writeFileSync(
      incompletePath,
      zip({ 'extension/package.json': '{}', 'extension/browser-capture/manifest.json': '{}' }),
    );
    const incomplete = verifyBrowserCaptureVsixArtifact({
      vsixPath: incompletePath,
      bundleEntries,
    });
    assert.equal(incomplete.required, true);
    assert.ok(incomplete.errors.length > 0);
    assert.ok(
      incomplete.missingEntries.includes('browser-capture/trainer-browser-capture.json'),
    );

    // A tree with no staged bundle reports required=false (fixtures, partial checkouts).
    const notRequired = verifyBrowserCaptureVsixArtifact({ vsixPath: completePath, bundleEntries: [] });
    assert.deepEqual(notRequired, { required: false, bundleEntries: [], missingEntries: [], errors: [] });
  } finally {
    fs.rmSync(fixture.root, { recursive: true, force: true });
  }
});

test('prepublish stages the capture bundle before package verification', () => {
  const prepublishSource = fs.readFileSync(prepublishModulePath, 'utf8');
  assert.match(
    prepublishSource,
    /import \{ syncBrowserCaptureExtension \} from "\.\/bundle-browser-capture\.mjs";/,
  );
  const stageCall = prepublishSource.indexOf('const browserCapture = syncBrowserCaptureExtension(');
  const verifyCall = prepublishSource.indexOf('const packageReport = assertPackageVerified(');
  assert.notEqual(stageCall, -1);
  assert.notEqual(verifyCall, -1);
  assert.ok(stageCall < verifyCall, 'staging must run before the package verification gate');
  assert.match(prepublishSource, /browserCapture,/);

  const verifySource = fs.readFileSync(verifyPackageModulePath, 'utf8');
  assert.match(
    verifySource,
    /import \{ verifyBrowserCaptureBundle \} from "\.\/bundle-browser-capture\.mjs";/,
  );
  assert.match(verifySource, /const browserCapture = verifyBrowserCaptureBundle\(\{ extensionDir, repoRoot \}\);/);
  assert.match(verifySource, /\(browserCapture\.ok \|\| !browserCapture\.staged\)/);
  assert.match(verifySource, /for \(const message of report\.browserCapture\?\.errors \?\? \[\]\)/);

  const packageSource = fs.readFileSync(packageVsixModulePath, 'utf8');
  assert.match(packageSource, /assertBrowserCaptureVsixArtifact,/);
  assert.match(packageSource, /const browserCaptureArtifact = assertBrowserCaptureVsixArtifact\(\{/);
  assert.match(packageSource, /bundleEntries: collectBrowserCaptureVsixEntries\(\{ extensionDir \}\),/);
  assert.match(packageSource, /browserCaptureArtifact,/);
});

test('the staged bundle mirrors the browser extension packaging include list', async () => {
  const { BROWSER_CAPTURE_REQUIRED_ENTRIES } = await loadBundleModule();
  const browserPackagingSource = fs.readFileSync(rootPackageBrowserModulePath, 'utf8');
  const includeMatch = /const INCLUDE_ROOTS = \[([^\]]+)\];/.exec(browserPackagingSource);
  assert.ok(includeMatch, 'package-browser-extension.mjs declares INCLUDE_ROOTS');
  const includeRoots = includeMatch[1]
    .split(',')
    .map((entry) => entry.trim().replace(/^['"]|['"]$/g, ''))
    .filter(Boolean);

  for (const entry of BROWSER_CAPTURE_REQUIRED_ENTRIES) {
    const root = entry.split('/')[0];
    assert.ok(includeRoots.includes(root), `INCLUDE_ROOTS should cover ${root}`);
  }
  assert.deepEqual(BROWSER_CAPTURE_REQUIRED_ENTRIES, [
    'manifest.json',
    'background.js',
    'shared.js',
    'popup/popup.html',
    'README.md',
  ]);
});
