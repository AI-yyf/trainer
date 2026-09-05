'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const vscodeSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'vscode.ts');

test('persisted preview provider state survives normalizePersistedState', () => {
  const source = fs.readFileSync(vscodeSourcePath, 'utf8');

  assert.match(source, /previewProviderConfig:\s*stripProviderSnapshotSecrets\(state\.previewProviderConfig\)/);
  assert.match(source, /stripProviderSnapshotSecrets\(providerConfig\)/);
});
