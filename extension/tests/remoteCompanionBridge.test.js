'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');
const { pathToFileURL } = require('node:url');
const { buildSync } = require('../webview/node_modules/esbuild');

const root = path.resolve(__dirname, '../..');
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-companion-bridge-'));
fs.writeFileSync(path.join(fixture, 'notes.md'), 'Keep the quiet fix in this workspace.\n');
const hostRoot = `vscode-remote://ssh-remote+bridge-host${fixture}`;
const workspaceRoot = pathToFileURL(fixture).href;

function uri(value) {
  const parsed = new URL(value);
  return { scheme: parsed.protocol.slice(0, -1), authority: decodeURIComponent(parsed.host), path: decodeURIComponent(parsed.pathname),
    fsPath: decodeURIComponent(parsed.pathname), toString: () => parsed.href };
}
const Uri = { parse: uri, joinPath: (base, relative) => uri(`${base.scheme}://${base.authority}${path.posix.join(base.path, relative)}`) };
function load(source, vscode) {
  const filename = path.join(root, source);
  const { outputFiles } = buildSync({ entryPoints: [filename], bundle: true, platform: 'node', format: 'cjs', write: false, external: ['vscode'] });
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const originalRequire = mod.require.bind(mod);
  mod.require = request => request === 'vscode' ? vscode : originalRequire(request);
  mod._compile(outputFiles[0].text, filename);
  return mod.exports;
}
const handlers = new Map();
const companion = load('remote-extension/src/extension.ts', {
  Uri, env: { remoteName: 'ssh-remote' }, languages: { getDiagnostics: () => [] },
  commands: { registerCommand: (name, handler) => { handlers.set(name, handler); return { dispose() {} }; } },
  workspace: { workspaceFolders: [{ uri: uri(workspaceRoot) }],
    fs: { readFile: value => fs.promises.readFile(value.fsPath) },
    findFiles: async () => [uri(pathToFileURL(path.join(fixture, 'notes.md')).href)] },
});
companion.activate({ subscriptions: [] });
const calls = [];
const { RemoteWorkspaceGateway } = load('extension/src/workspace/remoteWorkspaceGateway.ts', {
  Uri, env: { remoteName: 'ssh-remote' }, workspace: { workspaceFolders: [{ uri: uri(hostRoot) }] },
  commands: { executeCommand: async (name, payload) => { calls.push({ name, payload }); return handlers.get(name)(payload); } },
});
const gateway = new RemoteWorkspaceGateway('ssh-remote');

test('UI and workspace hosts exchange real file bytes, search results and hashes through protocol v2', async () => {
  const file = Uri.joinPath(uri(hostRoot), 'notes.md');
  assert.equal(await gateway.readText(file), 'Keep the quiet fix in this workspace.\n');
  assert.match(await gateway.hashArtifact(file), /^[a-f0-9]{64}$/);
  const matches = await gateway.searchText({ text: 'quiet fix', pattern: '**/*.md' });
  assert.equal(matches.length, 1);
  assert.equal(matches[0].uri, file.toString());
  assert.equal((await gateway.findFiles({ pattern: '**/*.md' }))[0].toString(), file.toString());
  assert.ok(calls.some(call => call.payload?.uri === pathToFileURL(path.join(fixture, 'notes.md')).href));
});

test('foreign authority and outside paths are rejected before a file request crosses the bridge', async () => {
  const before = calls.filter(call => call.name === 'trainer.remote.request').length;
  await assert.rejects(gateway.readFile(uri(`vscode-remote://ssh-remote+other-host${fixture}/notes.md`)), /different workspace authority/);
  await assert.rejects(gateway.readFile(uri('vscode-remote://ssh-remote+bridge-host/tmp/outside.md')), /outside the active workspace/);
  assert.equal(calls.filter(call => call.name === 'trainer.remote.request').length, before);
});

test('structured verification launches a real process and preserves pass, fail and cancellation facts', async () => {
  const spec = { executable: process.execPath, args: ['-e', 'process.stdout.write(process.argv[1]);', 'literal space $value'], cwd: uri(hostRoot).toString() };
  const passed = await gateway.runVerification(spec, { pollIntervalMs: 10 });
  assert.equal(passed.state, 'completed'); assert.equal(passed.result, 'passed'); assert.equal(passed.exit_code, 0);
  assert.equal(passed.stdout, 'literal space $value');
  const failed = await gateway.runVerification({ ...spec, args: ['-e', 'process.exit(7)'] }, { pollIntervalMs: 10 });
  assert.equal(failed.state, 'completed'); assert.equal(failed.result, 'failed'); assert.equal(failed.exit_code, 7);
  const cancelled = await gateway.runVerification({ ...spec, args: ['-e', 'setTimeout(()=>{},30000)'] }, { signal: { aborted: true } });
  assert.equal(cancelled.state, 'cancelled'); assert.equal(cancelled.result, undefined);
});

test.after(() => { companion.deactivate(); fs.rmSync(fixture, { recursive: true, force: true }); });
