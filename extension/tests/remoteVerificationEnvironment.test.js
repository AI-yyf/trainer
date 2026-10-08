'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('../webview/node_modules/esbuild');

function fixture({ cancelFails = false, firstStatusFails = false, laterStatusFails = false } = {}) {
  const filename = path.resolve(__dirname, '../src/workspace/remoteWorkspaceGateway.ts');
  const { outputFiles } = buildSync({ entryPoints: [filename], bundle: true, platform: 'node', format: 'cjs', write: false, external: ['vscode'] });
  const remoteEnvironment = { os: 'remote-test-linux', arch: 'remote-test-x64', node_version: 'remote-test-node' };
  let polls = 0;
  const uri = value => { const u = new URL(value); return { scheme: u.protocol.slice(0,-1), authority: decodeURIComponent(u.host), path: u.pathname, toString: () => value }; };
  const vscode = { Uri: { parse: uri }, env: { remoteName: 'ssh-remote' }, workspace: { workspaceFolders: [{ uri: uri('vscode-remote://ssh-remote+owned/fixture') }] }, commands: {
    async executeCommand(_name, request) {
      if (_name === 'trainer.remote.capabilities') return { available: true, workspace_uri: 'file:///fixture', protocol_version: 2 };
      if (request.operation === 'verify_start') return { ok: true, verification_session: { session_id: 'owned-session', state: 'running' } };
      if (request.operation === 'verify_cancel') {
        if (cancelFails) throw new Error('actual bridge lost during cancellation');
        return { ok: true, verification_cancelled: { session_id: 'owned-session', state: 'cancelled' } };
      }
      if (request.operation === 'verify_status') {
        polls++;
        if (firstStatusFails || (laterStatusFails && polls > 1)) throw new Error('actual bridge lost during poll');
        return { ok: true, verification_status: { session_id: 'owned-session', state: 'running', started_at: 'remote-started-at', stdout_chunk: 'remote chunk', stderr_chunk: '', environment: remoteEnvironment } };
      }
      throw new Error('unexpected request '+request.operation);
    },
  } };
  const mod = new Module(filename, module); mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const originalRequire = mod.require.bind(mod);
  mod.require = name => name === 'vscode' ? vscode : originalRequire(name);
  mod._compile(outputFiles[0].text, filename);
  return { gateway: new mod.exports.RemoteWorkspaceGateway('ssh-remote'), remoteEnvironment };
}
const spec = { executable: 'owned-explicit-command', args: [] };

test('lost first poll and lost cancellation ACK report unknown remote environment', async () => {
  for (const options of [{ firstStatusFails: true }, { cancelFails: true }]) {
    const { gateway } = fixture(options);
    const result = await gateway.runVerification(spec, { signal: { aborted: options.cancelFails === true }, pollIntervalMs: 1 });
    assert.equal(result.state, 'connection_lost'); assert.equal(result.result, undefined);
    assert.deepEqual(result.environment, { remote_name: 'ssh-remote', os: 'unknown', arch: 'unknown', node_version: 'unknown' });
  }
});

test('lost later poll preserves actual remote environment, start time and streamed bytes', async () => {
  const { gateway, remoteEnvironment } = fixture({ laterStatusFails: true });
  const result = await gateway.runVerification(spec, { pollIntervalMs: 1 });
  assert.equal(result.state, 'connection_lost'); assert.equal(result.result, undefined);
  assert.deepEqual(result.environment, remoteEnvironment);
  assert.equal(result.started_at, 'remote-started-at'); assert.equal(result.stdout, 'remote chunk');
});

test('acknowledged cancellation keeps observed remote facts when final status is unavailable', async () => {
  const { gateway, remoteEnvironment } = fixture({ laterStatusFails: true });
  const signal = { aborted: false };
  const result = await gateway.runVerification(spec, { signal, pollIntervalMs: 1, onChunk: () => { signal.aborted = true; } });
  assert.equal(result.state, 'cancelled'); assert.equal(result.result, undefined);
  assert.deepEqual(result.environment, remoteEnvironment); assert.equal(result.started_at, 'remote-started-at');
});
