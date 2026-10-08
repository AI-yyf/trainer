'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const { zip } = require('./fixtures/zip');

const root = path.resolve(__dirname, '../..');
const load = (relative) => import(pathToFileURL(path.join(root, relative)).href);
const write = (file, bytes) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, bytes); };

test('actual package CLI reaches its fail-closed version gate without an import deadlock', () => {
  const result = spawnSync(process.execPath, [path.join(root, 'extension/scripts/package-vsix.mjs')], {
    cwd: root,
    env: { ...process.env, GITHUB_REF: 'refs/tags/v99.99.99' },
    encoding: 'utf8',
    timeout: 10_000,
  });
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stderr, /Tag v99\.99\.99 differs from product v/);
  assert.doesNotMatch(result.stderr, /unsettled top-level await/);
});

function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-delivery-'));
  const product = { name: 'trainer-extension', version: '1.3.4' };
  for (const file of ['package.json', 'package-lock.json', 'extension/package.json', 'extension/package-lock.json']) {
    write(path.join(directory, file), JSON.stringify(product));
  }
  write(path.join(directory, 'server/run_sidecar.py'), 'print("fixture")');
  write(path.join(directory, 'server/app/__init__.py'), '');
  write(path.join(directory, 'server/pyproject.toml'), '[project]\nname="trainer-sidecar"');
  write(path.join(directory, 'server/README.md'), '# Sidecar');
  const companion = { name: 'trainer-workspace-companion', version: '1.0.0',
    main: './dist/remote-extension/src/extension.js', extensionKind: ['workspace'] };
  write(path.join(directory, 'remote-extension/package.json'), JSON.stringify(companion));
  write(path.join(directory, '.gitignore'), 'extension/bundled/\nextension/dist/\nextension/webview/dist/\n*.vsix*\n');
  const git = (args) => {
    const result = spawnSync('git', args, { cwd: directory, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
  };
  git(['init', '-q']); git(['add', '.']);
  git(['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture']);
  return { directory, product, companion, extensionDir: path.join(directory, 'extension') };
}

async function prepareFixture(f) {
  const { bundleSidecar } = await load('extension/scripts/bundle-sidecar.mjs');
  const { resolveBinaryBundlePaths, writeSidecarBinaryManifest } = await load('extension/scripts/bundle-sidecar-binary.mjs');
  const prepare = () => {
  bundleSidecar({ extensionDir: f.extensionDir, repoRoot: f.directory });
  const paths = resolveBinaryBundlePaths({ extensionDir: f.extensionDir, repoRoot: f.directory });
  write(path.join(paths.bundleRoot, paths.entryName), 'executable fixture');
  writeSidecarBinaryManifest(paths);
  write(path.join(f.extensionDir, 'dist/extension/src/extension.js'), 'exports.activate = () => {};');
  write(path.join(f.extensionDir, 'webview/dist/index.html'), '<html></html>');
  write(path.join(f.extensionDir, 'webview/dist/vscode-preview.html'), '<html></html>');
  write(path.join(f.extensionDir, 'bundled/remote/trainer-workspace-companion.vsix'), zip({
    'extension/package.json': JSON.stringify(f.companion),
    'extension/dist/remote-extension/src/extension.js': 'exports.activate = () => {};',
  }));
  };
  prepare();
  return prepare;
}

function targetArchive(target, version = '1.3.4') {
  const manifest = { platform: target, sourceSnapshot: { sha256: 'source-hash' },
    buildEnvironment: { python: '3.12.14', dependencies: { pyinstaller: '6.22.2' } } };
  const entry = target.startsWith('win32-') ? 'trainer-sidecar.exe' : 'trainer-sidecar';
  return zip({
    'extension.vsixmanifest': `<Identity Version="${version}" TargetPlatform="${target}"/>`,
    'extension/package.json': JSON.stringify({ version }),
    'extension/dist/extension/src/extension.js': 'exports.activate = () => {};',
    'extension/webview/dist/index.html': '<html></html>',
    'extension/bundled/remote/trainer-workspace-companion.vsix': 'companion archive',
    [`extension/bundled/bin/${target}/${entry}`]: 'executable',
    [`extension/bundled/bin/${target}/trainer-sidecar-manifest.json`]: JSON.stringify(manifest),
  });
}

test('clean package entrypoint prepares all dependencies before gating and records the exact archive', async () => {
  const { packageVsix } = await load('extension/scripts/package-vsix.mjs');
  const f = fixture();
  try {
    const buildInputs = await prepareFixture(f);
    for (const directory of ['bundled', 'dist', 'webview']) fs.rmSync(path.join(f.extensionDir, directory), { recursive: true });
    const steps = [];
    const result = await packageVsix({ extensionDir: f.extensionDir, env: {},
      prepare() { steps.push('prepare'); buildInputs(); },
      runPackage(command, args, options) {
        assert.deepEqual(steps, ['prepare']);
        assert.equal(options.env.TRAINER_VSIX_PREPARED, '1');
        steps.push('archive');
        const target = args[args.indexOf('--target') + 1];
        write(args[args.indexOf('--out') + 1], targetArchive(target));
        return { status: 0, stdout: '', stderr: '' };
      },
    });
    const metadata = JSON.parse(fs.readFileSync(result.metadataPath, 'utf8'));
    assert.deepEqual(steps, ['prepare', 'archive']);
    assert.equal(metadata.productVersion, f.product.version);
    assert.equal(metadata.sourceDirty, false);
    assert.match(metadata.sourceCommit, /^[a-f0-9]{40}$/);
    assert.equal(metadata.vsix.sha256, crypto.createHash('sha256').update(fs.readFileSync(result.outputPath)).digest('hex'));
  } finally { fs.rmSync(f.directory, { recursive: true, force: true }); }
});

test('a failed native dependency or missing Companion prevents the archive command', async () => {
  const { packageVsix } = await load('extension/scripts/package-vsix.mjs');
  const f = fixture();
  let invoked = false;
  try {
    await assert.rejects(packageVsix({ extensionDir: f.extensionDir,
      prepare() { throw new Error('native build failed'); }, runPackage() { invoked = true; } }), /native build failed/);
    await prepareFixture(f);
    fs.rmSync(path.join(f.extensionDir, 'bundled/remote/trainer-workspace-companion.vsix'));
    await assert.rejects(packageVsix({ extensionDir: f.extensionDir,
      prepare() {}, runPackage() { invoked = true; } }), /Companion VSIX is missing/);
    assert.equal(invoked, false);
  } finally { fs.rmSync(f.directory, { recursive: true, force: true }); }
});

test('a malformed or outdated Companion archive fails closed even if it contains an entrypoint string', async () => {
  const { verifyRemoteCompanionBundle } = await load('extension/scripts/verify-package.mjs');
  const f = fixture();
  try {
    const output = path.join(f.extensionDir, 'bundled/remote/trainer-workspace-companion.vsix');
    write(output, 'PK extension/dist/remote-extension/src/extension.js');
    assert.equal(verifyRemoteCompanionBundle({ extensionDir: f.extensionDir }).ok, false);
    await prepareFixture(f);
    write(output, zip({ 'extension/package.json': JSON.stringify({ ...f.companion, version: '0.9.0' }),
      'extension/dist/remote-extension/src/extension.js': 'code' }));
    assert.match(verifyRemoteCompanionBundle({ extensionDir: f.extensionDir }).errors.join(), /version differs/);
  } finally { fs.rmSync(f.directory, { recursive: true, force: true }); }
});

test('product version gate rejects both lock drift and wrong tags', async () => {
  const { verifyProductVersion } = await load('scripts/verify-version.mjs');
  const f = fixture();
  try {
    assert.equal(verifyProductVersion({ repoRoot: f.directory, ref: 'refs/tags/v1.3.4' }).version, '1.3.4');
    assert.throws(() => verifyProductVersion({ repoRoot: f.directory, ref: 'refs/tags/v1.0.3' }), /Tag.*differs/);
    write(path.join(f.directory, 'package-lock.json'), JSON.stringify({ version: '1.0.3' }));
    assert.throws(() => verifyProductVersion({ repoRoot: f.directory }), /package-lock.json version differs/);
  } finally { fs.rmSync(f.directory, { recursive: true, force: true }); }
});

test('formal release requires every target with matching tag, commit, hash, and clean source', async () => {
  const { verifyReleaseArtifacts, RELEASE_TARGETS } = await load('scripts/verify-release-artifacts.mjs');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-release-artifacts-'));
  const commit = 'a'.repeat(40);
  try {
    for (const target of RELEASE_TARGETS) {
      const archive = targetArchive(target);
      const file = `trainer-extension-1.3.4-${target}.vsix`;
      write(path.join(directory, file), archive);
      write(path.join(directory, `${file}.build.json`), JSON.stringify({ schemaVersion: 1,
        productVersion: '1.3.4', targetPlatform: target, sourceCommit: commit, sourceDirty: false,
        sourceSnapshot: { sha256: 'source-hash' }, vsix: { file, bytes: archive.length,
          sha256: crypto.createHash('sha256').update(archive).digest('hex') } }));
    }
    const options = { directory, ref: 'refs/tags/v1.3.4', commit };
    assert.equal(verifyReleaseArtifacts(options).artifacts.length, 3);
    assert.throws(() => verifyReleaseArtifacts({ ...options, ref: 'refs/heads/main' }), /product version tag/);
    assert.throws(() => verifyReleaseArtifacts({ ...options, commit: 'b'.repeat(40) }), /provenance/);
    const metadataFile = path.join(directory, `trainer-extension-1.3.4-${RELEASE_TARGETS[0]}.vsix.build.json`);
    const good = fs.readFileSync(metadataFile, 'utf8');
    for (const patch of [{ sourceDirty: true }, { productVersion: '1.3.3' }, { vsix: { sha256: 'wrong' } }]) {
      write(metadataFile, JSON.stringify({ ...JSON.parse(good), ...patch }));
      assert.throws(() => verifyReleaseArtifacts(options), /provenance/);
    }
    write(metadataFile, good);
    fs.rmSync(path.join(directory, `trainer-extension-1.3.4-${RELEASE_TARGETS[0]}.vsix`));
    assert.throws(() => verifyReleaseArtifacts(options), /exactly three/);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});
