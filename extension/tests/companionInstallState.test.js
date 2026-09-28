'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const modulePath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'companionInstallState.ts',
);

let modulePromise;
function loadModule() {
  if (!modulePromise) {
    const ts = path.resolve(__dirname, '..', '..', 'extension', 'node_modules', 'typescript', 'lib', 'typescript.js');
    modulePromise = (async () => {
      const tsModule = await import(pathToFileURL(ts).href);
      const source = require('node:fs').readFileSync(modulePath, 'utf8');
      const js = tsModule.transpileModule(source, {
        compilerOptions: {
          module: tsModule.ModuleKind.CommonJS,
          target: tsModule.ScriptTarget.ES2022,
        },
      }).outputText;
      const tmp = require('node:os').tmpdir();
      const outPath = path.join(tmp, `companionInstallState-${process.pid}.js`);
      require('node:fs').writeFileSync(outPath, js);
      return require(outPath);
    })();
  }
  return modulePromise;
}

test('transient progress states take precedence in order', async () => {
  const { deriveCompanionInstallState } = await loadModule();
  const capabilities = { protocol_version: 2, available: true, capabilities: {} };

  assert.equal(deriveCompanionInstallState({ installing: true }), 'installing');
  assert.equal(
    deriveCompanionInstallState({ installing: true, capabilities }),
    'installing',
    'installing beats an existing handshake',
  );
  assert.equal(deriveCompanionInstallState({ reloadPending: true }), 'await_reload');
  assert.equal(
    deriveCompanionInstallState({ reloadPending: true, capabilities }),
    'await_reload',
    'reload request beats readiness',
  );
  assert.equal(deriveCompanionInstallState({ capabilities, preparing: true }), 'preparing');
});

test('a protocol-matched companion is ready; a mismatched one is incompatible', async () => {
  const { deriveCompanionInstallState } = await loadModule();
  assert.equal(
    deriveCompanionInstallState({
      capabilities: { protocol_version: 2, available: true, capabilities: {} },
    }),
    'ready',
  );
  assert.equal(
    deriveCompanionInstallState({
      capabilities: { protocol_version: 1, available: true, capabilities: {} },
    }),
    'version_incompatible',
  );
  // Protocol mismatch outranks connection_lost: the user must reload/upgrade
  // before reconnect attempts mean anything.
  assert.equal(
    deriveCompanionInstallState({
      capabilities: { protocol_version: 1, available: true, capabilities: {} },
      connectionLost: true,
    }),
    'version_incompatible',
  );
});

test('version drift flags an upgrade only when the protocol still matches', async () => {
  const { deriveCompanionInstallState } = await loadModule();
  const capabilities = { protocol_version: 2, available: true, capabilities: {} };
  assert.equal(
    deriveCompanionInstallState({
      capabilities,
      companionVersion: '1.2.0',
      mainVersion: '1.3.0',
    }),
    'upgrade_available',
  );
  assert.equal(
    deriveCompanionInstallState({
      capabilities,
      companionVersion: '1.3.0',
      mainVersion: '1.3.0',
    }),
    'ready',
  );
});

test('no companion and a dropped connection surface their own states', async () => {
  const { deriveCompanionInstallState } = await loadModule();
  assert.equal(deriveCompanionInstallState({}), 'not_installed');
  assert.equal(
    deriveCompanionInstallState({ connectionLost: true }),
    'connection_lost',
  );
  assert.equal(
    deriveCompanionInstallState({
      capabilities: { protocol_version: 2, available: false, capabilities: {} },
    }),
    'not_installed',
  );
});

test('readiness helper treats upgrade_available as ready (do not nag)', async () => {
  const { deriveCompanionInstallState, isCompanionReady } = await loadModule();
  const capabilities = { protocol_version: 2, available: true, capabilities: {} };
  const state = deriveCompanionInstallState({
    capabilities,
    companionVersion: '1.2.0',
    mainVersion: '1.3.0',
  });
  assert.equal(isCompanionReady(state), true);
  assert.equal(isCompanionReady('not_installed'), false);
});
