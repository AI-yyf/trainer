'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { fileURLToPath, pathToFileURL } = require('node:url');
const Module = require('node:module');

const companionModulePath = path.resolve(
  __dirname,
  '..',
  '..',
  'remote-extension',
  'dist',
  'remote-extension',
  'src',
  'extension.js',
);

function remoteUriForPath(authority, fsPath) {
  const pathname = pathToFileURL(path.resolve(fsPath)).pathname;
  return `vscode-remote://${authority}${pathname}`;
}

function makeUri(value) {
  if (value.startsWith('file://')) {
    const url = new URL(value);
    const fsPath = fileURLToPath(url);
    return {
      scheme: 'file',
      authority: url.host || '',
      path: decodeURIComponent(url.pathname),
      fsPath,
      toString: () => url.toString(),
    };
  }
  const url = new URL(value);
  const p = decodeURIComponent(url.pathname);
  return {
    scheme: url.protocol.slice(0, -1),
    authority: url.host,
    path: p,
    fsPath: p,
    toString: () => value,
  };
}

function loadCompanionWithMock({ folders, remoteName }) {
  const commands = new Map();
  const vscodeMock = {
    env: { remoteName },
    Uri: {
      file: (fsPath) => makeUri(pathToFileURL(path.resolve(fsPath)).toString()),
      parse: (value) => makeUri(value),
    },
    RelativePattern: class RelativePattern {
      constructor(base, pattern) {
        this.base = base;
        this.pattern = pattern;
      }
    },
    workspace: {
      isTrusted: true,
      workspaceFolders: folders.map((folderPath) => ({
        name: path.basename(folderPath),
        uri: makeUri(pathToFileURL(path.resolve(folderPath)).toString()),
      })),
      fs: {
        async stat(uri) {
          const st = fs.statSync(uri.fsPath);
          return {
            type: st.isDirectory() ? 2 : 1,
            size: st.size,
            mtime: st.mtimeMs,
          };
        },
        async readFile(uri) {
          return new Uint8Array(fs.readFileSync(uri.fsPath));
        },
        async readDirectory(uri) {
          return fs.readdirSync(uri.fsPath, { withFileTypes: true }).map((entry) => [
            entry.name,
            entry.isDirectory() ? 2 : 1,
          ]);
        },
      },
      async findFiles() {
        return [];
      },
    },
    languages: {
      getDiagnostics() {
        return [];
      },
    },
    commands: {
      registerCommand(id, handler) {
        commands.set(id, handler);
        return { dispose() {} };
      },
    },
  };

  const originalLoad = Module._load;
  delete require.cache[companionModulePath];
  Module._load = function (request, parent, isMain) {
    if (request === 'vscode') {
      return vscodeMock;
    }
    return originalLoad.call(this, request, parent, isMain);
  };
  let mod;
  try {
    mod = require(companionModulePath);
  } finally {
    Module._load = originalLoad;
  }
  const subscriptions = [];
  mod.activate({ subscriptions });
  return {
    commands,
    deactivate: () => mod.deactivate(),
  };
}

test('remote Companion resolves UI-host vscode-remote://ssh-remote+... URIs against remote file:// folders and fails closed outside scope', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-companion-uri-'));
  const repoA = path.join(tempRoot, 'repo-a');
  const repoB = path.join(tempRoot, 'repo-b');
  const outsideDir = path.join(tempRoot, 'outside');
  fs.mkdirSync(repoA, { recursive: true });
  fs.mkdirSync(repoB, { recursive: true });
  fs.mkdirSync(outsideDir, { recursive: true });
  const fileA = path.join(repoA, 'payments.py');
  const fileB = path.join(repoB, 'worker.py');
  const outsideFile = path.join(outsideDir, 'secret.txt');
  fs.writeFileSync(fileA, 'def charge(key):\n    return key\n', 'utf8');
  fs.writeFileSync(fileB, 'def run():\n    return True\n', 'utf8');
  fs.writeFileSync(outsideFile, 'do not read\n', 'utf8');

  const companion = loadCompanionWithMock({
    folders: [repoA, repoB],
    remoteName: 'ssh-remote',
  });
  try {
    const request = companion.commands.get('trainer.remote.request');
    const capabilities = companion.commands.get('trainer.remote.capabilities');
    const caps = await capabilities();
    assert.equal(caps.protocol_version, 2);
    assert.equal(caps.available, true);

    // 1. UI-host vscode-remote URI for repoA resolves cleanly to remote file://
    const statRes = await request({
      protocol_version: 2,
      operation: 'stat',
      uri: remoteUriForPath('ssh-remote+141s', repoA),
    });
    assert.equal(statRes.ok, true, JSON.stringify(statRes));
    assert.equal(statRes.stat.type, 2);

    const readA = await request({
      protocol_version: 2,
      operation: 'read_file',
      uri: remoteUriForPath('ssh-remote+141s', fileA),
    });
    assert.equal(readA.ok, true, JSON.stringify(readA));
    assert.match(Buffer.from(readA.content_base64, 'base64').toString('utf8'), /def charge/);

    // 2. Multi-root: repoB also resolves cleanly via vscode-remote URI
    const readB = await request({
      protocol_version: 2,
      operation: 'read_file',
      uri: remoteUriForPath('ssh-remote+141s', fileB),
    });
    assert.equal(readB.ok, true, JSON.stringify(readB));
    assert.match(Buffer.from(readB.content_base64, 'base64').toString('utf8'), /def run/);

    // 3. Hash artifact works on vscode-remote URI
    const hashRes = await request({
      protocol_version: 2,
      operation: 'hash_artifact',
      uri: remoteUriForPath('ssh-remote+141s', fileA),
    });
    assert.equal(hashRes.ok, true, JSON.stringify(hashRes));
    assert.match(hashRes.artifact_hash, /^[a-f0-9]{64}$/);

    // 4. Environment returns real canonical_workspace_uri for the requested multi-root folder
    const envRes = await request({
      protocol_version: 2,
      operation: 'environment',
      uri: remoteUriForPath('ssh-remote+141s', repoB),
    });
    assert.equal(envRes.ok, true, JSON.stringify(envRes));
    assert.equal(envRes.environment.canonical_workspace_uri, pathToFileURL(fs.realpathSync(repoB)).toString());

    // 5. Fails closed on foreign remoteName authority
    const wrongRemote = await request({
      protocol_version: 2,
      operation: 'read_file',
      uri: remoteUriForPath('wsl+ubuntu', fileA),
    });
    assert.equal(wrongRemote.ok, false);
    assert.match(wrongRemote.error.detail, /different workspace authority/i);

    // 6. Fails closed on sibling / traversal escape outside workspace folders
    const escaped = await request({
      protocol_version: 2,
      operation: 'read_file',
      uri: remoteUriForPath('ssh-remote+141s', outsideFile),
    });
    assert.equal(escaped.ok, false);
    assert.match(escaped.error.detail, /outside the active workspace/i);
  } finally {
    companion.deactivate();
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});
