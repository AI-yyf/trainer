'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const crypto = require('node:crypto');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const remoteWorkspaceModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'remoteWorkspace.js',
);
const remoteUriModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'workspace',
  'remoteUri.js',
);
const localGatewayModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'workspace',
  'localWorkspaceGateway.js',
);

function createUri(value) {
  const parsed = new URL(value);
  return {
    scheme: parsed.protocol.slice(0, -1),
    authority: decodeURIComponent(parsed.host),
    path: parsed.pathname,
    query: parsed.search.slice(1),
    fragment: parsed.hash.slice(1),
    fsPath: parsed.pathname,
    toString(includeQuery) {
      return includeQuery === false ? value.split('?')[0] : value;
    },
  };
}

function createVscodeMock({ remoteName, bytes = Buffer.from('trainer\n') } = {}) {
  const root = createUri(remoteName
    ? `vscode-remote://ssh-remote%2Bbuild-host/workspace`
    : 'file:///workspace');
  const files = new Map([[`${root.toString(true)}/README.md`, Uint8Array.from(bytes)]]);
  const Uri = {
    parse(value) {
      return createUri(value);
    },
    from(parts) {
      const query = parts.query ? `?${parts.query}` : '';
      const fragment = parts.fragment ? `#${parts.fragment}` : '';
      return createUri(`${parts.scheme}://${parts.authority}${parts.path}${query}${fragment}`);
    },
    file(value) {
      return createUri(`file://${value}`);
    },
    joinPath(base, name) {
      return createUri(`${base.toString(true).replace(/\/$/, '')}/${name}`);
    },
  };
  const fs = {
    async stat(uri) {
      return { type: 1, ctime: 10, mtime: 20, size: files.get(uri.toString(true))?.byteLength ?? bytes.byteLength };
    },
    async readFile(uri) {
      return files.get(uri.toString(true)) ?? Uint8Array.from(bytes);
    },
    async readDirectory() {
      return [['README.md', 1]];
    },
  };
  const workspace = {
    workspaceFolders: [{ uri: root }],
    fs,
    isTrusted: true,
    name: 'trainer',
    async findFiles() {
      return [...files.keys()].map((value) => Uri.parse(value));
    },
  };
  return {
    Uri,
    FileType: { Unknown: 0, File: 1, Directory: 2, SymbolicLink: 64 },
    workspace,
    env: { remoteName },
    languages: {
      getDiagnostics(uri) {
        if (uri) return [];
        return [];
      },
    },
  };
}

test('remote workspace detection reads SSH authority and remoteName', () => {
  const { detectRemoteWorkspaceType, detectRemoteWorkspaceTypeFromContext } = require(remoteWorkspaceModulePath);

  assert.equal(
    detectRemoteWorkspaceType('vscode-remote://ssh-remote+build-host/workspace'),
    'remote_ssh',
  );
  assert.equal(
    detectRemoteWorkspaceTypeFromContext({
      uri: { scheme: 'vscode-remote', authority: 'ssh-remote+build-host' },
    }),
    'remote_ssh',
  );
  assert.equal(
    detectRemoteWorkspaceTypeFromContext({ uri: 'file:///workspace', remoteName: 'ssh-remote' }),
    'remote_ssh',
  );
});

test('remote URI adapter preserves SSH authority and DTO fields', () => {
  const vscodeMock = createVscodeMock({ remoteName: 'ssh-remote+build-host' });
  const { toWorkspaceUri, toWorkspaceUriDto, detectWorkspaceUriType, isRemoteWorkspaceUri } =
    loadWithVscodeMock(remoteUriModulePath, vscodeMock);
  const uri = toWorkspaceUri('vscode-remote://ssh-remote%2Bbuild-host/workspace');

  assert.equal(uri.scheme, 'vscode-remote');
  assert.equal(uri.authority, 'ssh-remote+build-host');
  assert.equal(detectWorkspaceUriType(uri, 'ssh-remote+build-host'), 'remote_ssh');
  assert.equal(isRemoteWorkspaceUri(uri, 'ssh-remote+build-host'), true);
  assert.deepEqual(toWorkspaceUriDto(uri), {
    scheme: 'vscode-remote',
    authority: 'ssh-remote+build-host',
    path: '/workspace',
    query: '',
    fragment: '',
  });
});

test('local gateway exposes local capabilities and stable hash DTO', async () => {
  const bytes = Buffer.from('trainer\n');
  const vscodeMock = createVscodeMock({ bytes });
  const { LocalWorkspaceGateway } = loadWithVscodeMock(localGatewayModulePath, vscodeMock);
  const gateway = new LocalWorkspaceGateway();
  const uri = vscodeMock.workspace.workspaceFolders[0].uri;
  const capabilities = gateway.protocolCapabilities;
  const hash = await gateway.hashDto(uri);
  const response = await gateway.handle({
    requestId: 'hash-1',
    operation: 'hash',
    uri: {
      scheme: uri.scheme,
      authority: uri.authority,
      path: `${uri.path}/README.md`,
      query: '',
      fragment: '',
    },
  });

  assert.equal(capabilities.kind, 'local');
  assert.equal(capabilities.stat, true);
  assert.equal(capabilities.hash, true);
  assert.equal(hash.hash, crypto.createHash('sha256').update(bytes).digest('hex'));
  assert.equal(hash.size, bytes.byteLength);
  assert.equal(response.ok, true);
  assert.equal(response.requestId, 'hash-1');
});

test('remote local gateway reports remote capabilities from VS Code context', async () => {
  const vscodeMock = createVscodeMock({ remoteName: 'ssh-remote+build-host' });
  const { LocalWorkspaceGateway } = loadWithVscodeMock(localGatewayModulePath, vscodeMock);
  const gateway = new LocalWorkspaceGateway();
  const capabilities = await gateway.capabilities();

  assert.equal(capabilities.kind, 'remote');
  assert.equal(capabilities.remoteName, 'ssh-remote+build-host');
  assert.equal(capabilities.companionAvailable, false);
  assert.equal(gateway.environmentDto().isRemote, true);
});
