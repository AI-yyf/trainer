'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const sharedProviderGatewayModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'providerGateway.js',
);
const settingsViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

const NEWAPI_CONNECTION_BLOB = JSON.stringify({
  _type: 'newapi_channel_conn',
  key: 'sk-K5DO7XzgBun6jFTLJZLF9UJE0W3bHRvcBugjUtpocmorrXMS',
  url: 'http://minimax.redfast.top',
});

test('relay connection blobs split into base URL plus API key in one paste', async () => {
  const { parseProviderConnectionPaste } = await import(pathToFileURL(sharedProviderGatewayModulePath).href);

  const parsed = parseProviderConnectionPaste(NEWAPI_CONNECTION_BLOB);
  assert.deepEqual(parsed, {
    baseUrl: 'http://minimax.redfast.top',
    apiKey: 'sk-K5DO7XzgBun6jFTLJZLF9UJE0W3bHRvcBugjUtpocmorrXMS',
    connectionType: 'newapi_channel_conn',
  });
});

test('connection blob parsing tolerates copy wrappers and field aliases', async () => {
  const { parseProviderConnectionPaste } = await import(pathToFileURL(sharedProviderGatewayModulePath).href);

  assert.deepEqual(parseProviderConnectionPaste('```json\n' + NEWAPI_CONNECTION_BLOB + '\n```'), {
    baseUrl: 'http://minimax.redfast.top',
    apiKey: 'sk-K5DO7XzgBun6jFTLJZLF9UJE0W3bHRvcBugjUtpocmorrXMS',
    connectionType: 'newapi_channel_conn',
  });
  assert.deepEqual(parseProviderConnectionPaste(`  ${NEWAPI_CONNECTION_BLOB}  `), {
    baseUrl: 'http://minimax.redfast.top',
    apiKey: 'sk-K5DO7XzgBun6jFTLJZLF9UJE0W3bHRvcBugjUtpocmorrXMS',
    connectionType: 'newapi_channel_conn',
  });
  assert.deepEqual(
    parseProviderConnectionPaste(
      JSON.stringify({ base_url: 'https://api.example.com/v1', api_key: 'rk-abcdef123456' }),
    ),
    {
      baseUrl: 'https://api.example.com/v1',
      apiKey: 'rk-abcdef123456',
    },
  );
});

test('values that are not a full connection blob are never claimed', async () => {
  const { parseProviderConnectionPaste } = await import(pathToFileURL(sharedProviderGatewayModulePath).href);

  assert.equal(parseProviderConnectionPaste('sk-K5DO7XzgBun6jFTLJZLF9UJE0W3bHRvcBugjUtpocmorrXMS'), null);
  assert.equal(parseProviderConnectionPaste('http://minimax.redfast.top'), null);
  assert.equal(parseProviderConnectionPaste(JSON.stringify({ url: 'http://x.y' })), null);
  assert.equal(parseProviderConnectionPaste(JSON.stringify({ key: 'sk-abc' })), null);
  assert.equal(
    parseProviderConnectionPaste(JSON.stringify({ url: 'not a host', key: 'sk-abc' })),
    null,
  );
  assert.equal(parseProviderConnectionPaste('{not json}'), null);
  assert.equal(parseProviderConnectionPaste('[]'), null);
  assert.equal(parseProviderConnectionPaste(''), null);
});

test('settings form wires smart paste into both provider fields', () => {
  const source = fs.readFileSync(settingsViewSourcePath, 'utf8');

  assert.match(source, /parseProviderConnectionPaste/);
  assert.match(source, /const applyProviderSmartPaste = \(/);
  // Both the base URL and the API key inputs route edits through the splitter.
  const baseUrlField = source.indexOf('"baseUrl"');
  const apiKeyField = source.indexOf('"apiKey"');
  assert.ok(baseUrlField > 0, 'expected the base URL smart paste call');
  assert.ok(apiKeyField > baseUrlField, 'expected the API key smart paste call');
  assert.match(
    source,
    /applyProviderSmartPaste\(event\.target\.value, "baseUrl"\)/,
  );
  assert.match(
    source,
    /applyProviderSmartPaste\(event\.target\.value, "apiKey"\)/,
  );
});

test('file store honors the isolation env override (multi-instance safety)', async () => {
  const os = require('node:os');
  const fsp = require('node:fs/promises');
  const pathMod = require('node:path');
  const modulePath = pathMod.resolve(__dirname, '..', 'dist', 'extension', 'src', 'core', 'trainerFileStore.js');
  const { TrainerFileStore } = require(modulePath);

  const tempRoot = await fsp.mkdtemp(pathMod.join(os.tmpdir(), 'trainer-store-isolation-'));
  const previous = process.env.TRAINER_FILE_STORE_ROOT;
  try {
    process.env.TRAINER_FILE_STORE_ROOT = tempRoot;
    const store = new TrainerFileStore();
    assert.equal(store.root, pathMod.resolve(tempRoot));
    store.writeJSON('config.json', { config: { name: 'iso' } });
    const written = await fsp.readFile(pathMod.join(tempRoot, 'config.json'), 'utf8');
    assert.match(written, /"name": "iso"/);
    // 显式覆盖优先于环境变量
    const other = await fsp.mkdtemp(pathMod.join(os.tmpdir(), 'trainer-store-explicit-'));
    const explicit = new TrainerFileStore(other);
    assert.notEqual(explicit.root, store.root);
  } finally {
    if (previous === undefined) delete process.env.TRAINER_FILE_STORE_ROOT;
    else process.env.TRAINER_FILE_STORE_ROOT = previous;
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
});
