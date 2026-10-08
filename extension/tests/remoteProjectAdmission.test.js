'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
function uri(value) {
  const url = new URL(value);
  return { scheme: url.protocol.slice(0, -1), authority: url.host, path: decodeURIComponent(url.pathname),
    toString: () => url.toString(), with: (change) => { const next = new URL(url); next.pathname = change.path; return uri(next.toString()); } };
}
const root = uri('vscode-remote://ssh-remote+owned/tmp/alias');
const vscode = { workspace: { name: 'owned', workspaceFolders: [{ uri: root }] },
  Uri: { parse: uri }, FileType: { Directory: 2 } };
const original = Module._load;
Module._load = function(request, parent, isMain) {
  return request === 'vscode' ? vscode : original.call(this, request, parent, isMain);
};
const { provisionRemoteProject } = require(path.resolve(__dirname, '../dist/extension/src/commands/remoteProjectAdmission.js'));
Module._load = original;
function fixture() {
  const workspace = { trusted: true, remoteName: 'ssh-remote', workspaceScheme: 'vscode-remote',
    workspaceAuthority: 'ssh-remote+owned', workspaceUri: root.toString(), workspaceFolder: root.path };
  const context = { getHostState: () => ({ workspace }), trainerWorkspace: { getRoot: () => '/local/brain' }, workspaceGateway: {
    capabilities: async () => ({ companionAvailable: true, protocolVersion: 2 }),
    stat: async () => ({ type: 2 }), environment: async () => ({ canonical_workspace_uri: 'file:///tmp/project' }),
  } };
  const identity = { rootId: 'root-owned', projectId: 'project-owned', contextId: 'context-owned',
    canonicalRootPath: '/local/brain', canonicalProjectPath: 'vscode-remote://ssh-remote+owned/tmp/project' };
  const calls = [];
  const post = async (route, body) => { calls.push({ route, body }); return { project_identity: identity,
    project_provisioning: { agent_session_id: 'session-owned' } }; };
  return { context, workspace, identity, calls, post };
}
test('host remote admission derives the canonical directory from the actual gateway', async () => {
  const f = fixture();
  const identity = await provisionRemoteProject(f.context, root.toString(), { canonicalRootPath: '/local/brain' }, f.post);
  assert.equal(identity.agentSessionId, 'session-owned');
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].route, '/workspace/remote/adopt');
  assert.equal(f.calls[0].body.remote_project.canonical_uri, f.identity.canonicalProjectPath);
  assert.equal(f.calls[0].body.root_path, '/local/brain');
  assert.match(f.calls[0].body.workspace_id, /^remote-[a-f0-9]{64}$/);
  assert.equal(JSON.stringify(f.calls[0].body).includes('api_key'), false);
});
test('host remote admission rejects missing Companion facts and a workspace switch before provisioning', async () => {
  for (const failure of ['protocol', 'directory', 'canonical', 'scope', 'root', 'trust']) {
    const f = fixture();
    if (failure === 'protocol') f.context.workspaceGateway.capabilities = async () => ({ companionAvailable: true, protocolVersion: 1 });
    if (failure === 'directory') f.context.workspaceGateway.stat = async () => ({ type: 1 });
    if (failure === 'canonical') f.context.workspaceGateway.environment = async () => ({});
    if (failure === 'scope') f.context.workspaceGateway.environment = async () => { f.workspace.workspaceUri = 'vscode-remote://ssh-remote+other/tmp/alias'; return { canonical_workspace_uri: 'file:///tmp/project' }; };
    if (failure === 'root') f.context.workspaceGateway.environment = async () => { f.context.trainerWorkspace.getRoot = () => '/local/other'; return { canonical_workspace_uri: 'file:///tmp/project' }; };
    if (failure === 'trust') f.workspace.trusted = false;
    await assert.rejects(provisionRemoteProject(f.context, root.toString(), { canonicalRootPath: '/local/brain' }, f.post));
    assert.equal(f.calls.length, 0);
  }
});
test('host remote admission rejects a stale or foreign backend identity', async () => {
  const f = fixture();
  await assert.rejects(provisionRemoteProject(f.context, root.toString(), { canonicalRootPath: '/local/brain' }, async () => ({
    project_identity: { ...f.identity, canonicalProjectPath: 'vscode-remote://ssh-remote+other/tmp/project' },
    project_provisioning: { agent_session_id: 'session-owned' },
  })), /stale or mismatched/);
});
