'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');
function uri(value) {
  const u = new URL(value);
  return { scheme: u.protocol.slice(0, -1), authority: u.host, path: u.pathname, fsPath: u.pathname,
    query: u.search.slice(1), fragment: u.hash.slice(1), toString: () => u.toString() };
}
const root = uri('vscode-remote://ssh-remote+owned/project');
const safe = uri(root.toString() + '/practice.py');
const link = uri(root.toString() + '/outside-link.txt');
const foreign = uri('vscode-remote://ssh-remote+other/project/secret.txt');
const modulePath = path.resolve(__dirname, '../dist/extension/src/core/workspaceFileSnapshot.js');
function fixture() {
  let directCalls = 0;
  const reads = [];
  const gateway = {
    capabilities: async () => ({ companionAvailable: true, protocolVersion: 2 }),
    findFiles: async () => [safe, link, foreign],
    stat: async u => { if (u.toString() === link.toString()) throw new Error('Canonical escape'); return { size: 21 }; },
    readFile: async u => { reads.push(u.toString()); if (u.toString() === link.toString()) throw new Error('Canonical escape'); return Buffer.from('assert 6 * 7 == 42\n'); },
  };
  const mock = { env: { remoteName: 'ssh-remote' },
    Uri: { joinPath: (base, ...parts) => uri(base.toString() + '/' + parts.join('/')) },
    workspace: { workspaceFolders: [{ uri: root }], asRelativePath: u => path.posix.relative(root.path, u.path),
      findFiles: async () => { directCalls++; return [link]; },
      fs: { readFile: async () => { directCalls++; return Buffer.from('owned outside sentinel'); },
        stat: async () => { directCalls++; return { size: 99 }; } } },
    window: { activeTextEditor: { document: { uri: foreign, languageId: 'plaintext' } } },
  };
  return { gateway, mock, reads, directCalls: () => directCalls };
}
test('remote context snapshots use guarded gateway bytes and reject outside or foreign editor files', async () => {
  const f = fixture();
  const { buildWorkspaceFileSnapshot, rememberRequestedWorkspaceFiles } = loadWithVscodeMock(modulePath, f.mock);
  const owner = { workspaceGateway: f.gateway };
  rememberRequestedWorkspaceFiles(owner, ['../outside.txt', 'outside-link.txt']);
  const snapshot = await buildWorkspaceFileSnapshot(owner);
  assert.equal(snapshot.is_remote, true);
  assert.deepEqual(Object.keys(snapshot.contents), ['practice.py']);
  assert.equal(snapshot.contents['practice.py'].content, 'assert 6 * 7 == 42\n');
  assert.equal(JSON.stringify(snapshot).includes('owned outside sentinel'), false);
  assert.equal(f.reads.includes(foreign.toString()), false);
  assert.equal(f.directCalls(), 0);
});
test('unavailable Companion never falls back to direct remote filesystem reads', async () => {
  const f = fixture();
  f.gateway.capabilities = async () => ({ companionAvailable: false, protocolVersion: 2 });
  const { buildWorkspaceFileSnapshot } = loadWithVscodeMock(modulePath, f.mock);
  const snapshot = await buildWorkspaceFileSnapshot({ workspaceGateway: f.gateway });
  assert.deepEqual(snapshot, { is_remote: true, root_uri: root.toString(), files: [], contents: {} });
  assert.equal(f.directCalls(), 0);
  assert.deepEqual(f.reads, []);
});
test('local snapshots keep local file reads and have no Companion dependency', async () => {
  const f = fixture();
  const localRoot = uri('file:///project');
  const localFile = uri('file:///project/notes.md');
  f.mock.env.remoteName = undefined;
  f.mock.workspace.workspaceFolders = [{ uri: localRoot }];
  f.mock.workspace.findFiles = async () => [localFile];
  f.mock.workspace.asRelativePath = u => path.posix.relative(localRoot.path, u.path);
  f.mock.window.activeTextEditor = undefined;
  const { buildWorkspaceFileSnapshot } = loadWithVscodeMock(modulePath, f.mock);
  const snapshot = await buildWorkspaceFileSnapshot();
  assert.equal(snapshot.is_remote, false);
  assert.equal(snapshot.contents['notes.md'].content, 'owned outside sentinel');
  assert.equal(f.directCalls(), 2);
});
