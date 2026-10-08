'use strict';

const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');
const modulePath = path.resolve(__dirname, '../../scripts/provision-vscode.mjs');
const load = () => import(pathToFileURL(modulePath).href);
const fixtureCommit = 'a'.repeat(40);

function metadata(bytes) {
  return { productVersion: '1.127.0', version: fixtureCommit,
    url: 'https://vscode.download.prss.microsoft.com/test/code.zip',
    sha256hash: createHash('sha256').update(bytes).digest('hex') };
}

test('native VS Code archive targets select real platform CLI entrypoints', async () => {
  const { resolveVsCodeArchiveTarget } = await load();
  assert.equal(resolveVsCodeArchiveTarget('linux', 'x64').updatePlatform, 'linux-x64');
  assert.equal(resolveVsCodeArchiveTarget('darwin', 'arm64').updatePlatform, 'darwin-arm64');
  assert.equal(resolveVsCodeArchiveTarget('win32', 'x64').cli, 'bin/code.cmd');
  assert.throws(() => resolveVsCodeArchiveTarget('linux', 'ia32'), /Unsupported/);
});

test('official Code metadata requires pinned version, commit, checksum and Microsoft HTTPS archive', async () => {
  const { verifyVsCodeMetadata } = await load();
  const good = metadata(Buffer.from('verified archive'));
  assert.equal(verifyVsCodeMetadata(good), good);
  for (const changed of [{ productVersion: '1.128.0' }, { version: '' }, { sha256hash: '' },
    { url: 'https://example.com/code.zip' }, { url: 'http://vscode.download.prss.microsoft.com/code.zip' }]) {
    assert.throws(() => verifyVsCodeMetadata({ ...good, ...changed }));
  }
});

test('Code provisioning rejects corrupt bytes before extraction or CLI execution', async () => {
  const { provisionVsCode } = await load();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-code-integrity-'));
  const expected = Buffer.from('verified archive');
  const calls = [];
  try {
    await assert.rejects(provisionVsCode({ baseDir: root, platform: 'darwin', arch: 'arm64',
      fetchImpl: async (url) => url.startsWith('https://update.code.visualstudio.com/')
        ? Response.json(metadata(expected)) : new Response('corrupted archive'),
      runCommand: (...args) => calls.push(args),
    }), /SHA-256 mismatch/);
    assert.deepEqual(calls, []);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('Code provisioning checks archive and executable identity before returning its isolated CLI', async () => {
  const { provisionVsCode } = await load();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-code-verified-'));
  const bytes = Buffer.from('verified archive');
  const calls = [];
  try {
    const report = await provisionVsCode({ baseDir: root, platform: 'linux', arch: 'x64',
      fetchImpl: async (url) => url.startsWith('https://update.code.visualstudio.com/')
        ? Response.json(metadata(bytes)) : new Response(bytes),
      runCommand: (command, args) => {
        calls.push([command, args]);
        if (command === 'tar') {
          const bin = path.join(args.at(-1), 'bin'); fs.mkdirSync(bin);
          fs.writeFileSync(path.join(bin, 'code'), 'fixture');
          return '';
        }
        return `1.127.0\n${fixtureCommit}\nx64\n`;
      },
    });
    assert.equal(report.sha256, metadata(bytes).sha256hash);
    assert.equal(report.commit, fixtureCommit);
    assert.ok(report.codeCli.startsWith(root + path.sep));
    assert.equal(calls[0][0], 'tar');
    assert.deepEqual(calls[1], [report.codeCli, ['--version']]);
    assert.equal(fs.existsSync(path.join(path.dirname(path.dirname(report.codeCli)), '../code.tar.gz')), false);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

for (const platform of ['darwin', 'win32']) {
  test(`verified ${platform} Code extraction uses its native archive tool and checks CLI identity`, async () => {
    const { provisionVsCode } = await load();
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-code-native-'));
    const bytes = Buffer.from('verified native archive');
    const calls = [];
    try {
      const report = await provisionVsCode({ baseDir: root, platform, arch: 'x64',
        fetchImpl: async (url) => url.startsWith('https://update.code.visualstudio.com/')
          ? Response.json(metadata(bytes)) : new Response(bytes),
        runCommand: (command, args, options) => {
          calls.push([command, args]);
          const installDir = platform === 'darwin' ? args.at(-1) : options?.env?.TRAINER_CODE_INSTALL;
          if (calls.length === 1) {
            const cli = platform === 'darwin'
              ? path.join(installDir, 'Visual Studio Code.app/Contents/Resources/app/bin/code')
              : path.join(installDir, 'bin/code.cmd');
            fs.mkdirSync(path.dirname(cli), { recursive: true }); fs.writeFileSync(cli, 'fixture');
            return '';
          }
          return `1.127.0\n${fixtureCommit}\nx64\n`;
        },
      });
      assert.equal(calls[0][0], platform === 'darwin' ? '/usr/bin/ditto' : 'powershell.exe');
      assert.equal(report.commit, fixtureCommit);
      assert.ok(report.codeCli.startsWith(root + path.sep));
      assert.equal(calls.length, 2);
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  });
}
