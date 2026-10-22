'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const storeModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'provider',
  'providerConfigStore.js',
);

class FakeEventEmitter {
  constructor() { this.listeners = []; }
  event(listener) { this.listeners.push(listener); return { dispose() {} }; }
  fire(value) { for (const l of this.listeners) l(value); }
  dispose() {}
}

const VSCODE_MOCK = { EventEmitter: FakeEventEmitter, workspace: { workspaceFolders: [] } };

function baseConfig() {
  return {
    name: 'Local Test',
    baseUrl: 'http://127.0.0.1:9999',
    model: 'test-model',
    apiKeyRef: 'ref-1',
  };
}

function createContext(secrets) {
  const globalState = new Map();
  return {
    globalState: {
      get: (key) => globalState.get(key),
      update: (key, value) => {
        globalState.set(key, value);
        return Promise.resolve();
      },
      setKeysForSync: () => {},
    },
    secrets,
  };
}

function loadStore(secrets) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-secret-store-'));
  const { ProviderConfigStore } = loadWithVscodeMock(storeModulePath, VSCODE_MOCK);
  const store = new ProviderConfigStore(createContext(secrets), dir);
  return { store, cleanup: () => fs.rmSync(dir, { recursive: true, force: true }) };
}

test('a transient keyring failure keeps the stored credential and reports transient', async () => {
  const deletes = [];
  const secrets = {
    get: async () => {
      throw new Error('EACCES: permission denied, keyring is locked');
    },
    store: async () => {},
    delete: async (key) => {
      deletes.push(key);
    },
  };
  const { store, cleanup } = loadStore(secrets);
  try {
    await store.saveConfig(baseConfig());
    const value = await store.getApiKey();
    assert.equal(value, undefined);
    assert.equal(store.secretReadFailureKind('ref-1'), 'transient');
    assert.equal(deletes.length, 0, 'transient failures must not delete the credential');
  } finally {
    cleanup();
  }
});

test('a corrupted secret is cleaned up and flagged for re-entry', async () => {
  const deletes = [];
  const secrets = {
    get: async () => {
      throw new Error('libsecret: Bad decrypt / integrity check failed');
    },
    store: async () => {},
    delete: async (key) => {
      deletes.push(key);
    },
  };
  const { store, cleanup } = loadStore(secrets);
  try {
    await store.saveConfig(baseConfig());
    const value = await store.getApiKey();
    assert.equal(value, undefined);
    assert.equal(store.secretReadFailureKind('ref-1'), 'corrupted');
    assert.equal(store.hasDecryptionFailure('ref-1'), true);
    assert.equal(deletes.length > 0, true, 'definitive corruption cleans the dead ref');
  } finally {
    cleanup();
  }
});

test('a hung keyring read is bounded and degrades to no-key', async () => {
  const secrets = {
    get: () => new Promise(() => {}),
    store: async () => {},
    delete: async () => {},
  };
  const { store, cleanup } = loadStore(secrets);
  try {
    await store.saveConfig(baseConfig());
    const startedAt = Date.now();
    const value = await store.getApiKey();
    const elapsed = Date.now() - startedAt;
    assert.equal(value, undefined);
    assert.ok(elapsed < 4_000, `getApiKey must not hang (took ${elapsed}ms)`);
    assert.equal(store.secretReadFailureKind('ref-1'), 'transient');
  } finally {
    cleanup();
  }
});
