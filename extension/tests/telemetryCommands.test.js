'use strict';

/**
 * P2 #18: behavior gates for the telemetry consent commands.
 *
 * The sidecar owns consent truth. The host:
 *  - POSTs /telemetry/consent and mirrors the server's answer into bootstrap
 *    (never a locally decided value);
 *  - refuses to show a state the server did not answer (fail-closed on
 *    mismatch);
 *  - reads status WITHOUT waking a dark sidecar (getStatus only, never
 *    ensureRunning);
 *  - patch #1 keeps workbench syncState() so the webview converges.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const telemetryCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'telemetryCommands.js',
);

function createContext(options = {}) {
  const sidecarStatus = options.sidecarStatus ?? {
    lifecycle: 'ready',
    host: '127.0.0.1',
    port: 34891,
    canStart: true,
  };
  const managerCalls = [];
  const patches = [];
  const syncs = [];
  const posted = [];
  const got = [];
  return {
    sidecarManager: {
      async ensureRunning() {
        managerCalls.push('ensureRunning');
        return sidecarStatus;
      },
      getStatus() {
        managerCalls.push('getStatus');
        return sidecarStatus;
      },
    },
    sidecarClient: {
      async postJson(_port, requestPath, body) {
        if (options.failConsent) throw new Error('consent endpoint down');
        posted.push({ requestPath, body });
        return options.consent ?? { opt_in: true, consent_updated_at: '2026-10-17T00:00:00+00:00' };
      },
      async getJson(_port, requestPath) {
        if (options.failStatus) throw new Error('status endpoint down');
        got.push({ requestPath });
        return options.statusResponse ?? { opt_in: false, consent_updated_at: null, consent_changes: 0 };
      },
    },
    patchWorkbenchData: async (patch) => patches.push(patch),
    workbench: { syncState: async () => syncs.push(true) },
    managerCalls,
    patches,
    syncs,
    posted,
    got,
  };
}

test('setTelemetryOptInCommand posts consent and mirrors the server answer', async () => {
  const { setTelemetryOptInCommand } = loadWithVscodeMock(telemetryCommandsModulePath, {});
  const context = createContext({
    consent: { opt_in: true, consent_updated_at: '2026-10-17T00:00:00+00:00', consent_changes: 1 },
  });
  const result = await setTelemetryOptInCommand(context, { enabled: true });
  assert.equal(result.ok, true);
  assert.deepEqual(context.posted, [
    { requestPath: '/telemetry/consent', body: { opt_in: true, source: 'settings' } },
  ]);
  assert.deepEqual(context.patches, [{ telemetryOptIn: true }]);
  assert.equal(context.syncs.length, 1);
});

test('setTelemetryOptInCommand refuses to show a state the server did not answer', async () => {
  const { setTelemetryOptInCommand } = loadWithVscodeMock(telemetryCommandsModulePath, {});
  const context = createContext({ consent: { opt_in: false } });
  const result = await setTelemetryOptInCommand(context, { enabled: true });
  assert.equal(result.ok, false);
  assert.match(result.message, /did not apply/);
  assert.deepEqual(context.patches, []);
  assert.deepEqual(context.syncs, []);
});

test('setTelemetryOptInCommand fails closed when the sidecar is unavailable', async () => {
  const { setTelemetryOptInCommand } = loadWithVscodeMock(telemetryCommandsModulePath, {});
  const context = createContext({
    sidecarStatus: { lifecycle: 'idle', host: '127.0.0.1', port: undefined, canStart: true },
  });
  const result = await setTelemetryOptInCommand(context, { enabled: false });
  assert.equal(result.ok, false);
  assert.deepEqual(context.posted, []);
  assert.deepEqual(context.patches, []);
});

test('setTelemetryOptInCommand treats a consent endpoint failure as not-ok without patching', async () => {
  const { setTelemetryOptInCommand } = loadWithVscodeMock(telemetryCommandsModulePath, {});
  const context = createContext({ failConsent: true });
  const result = await setTelemetryOptInCommand(context, { enabled: false });
  assert.equal(result.ok, false);
  assert.match(result.message, /could not be recorded/);
  assert.deepEqual(context.patches, []);
});

test('refreshTelemetryStatusCommand reads without waking a dark sidecar', async () => {
  const { refreshTelemetryStatusCommand } = loadWithVscodeMock(telemetryCommandsModulePath, {});
  const context = createContext({
    sidecarStatus: { lifecycle: 'idle', host: '127.0.0.1', port: undefined, canStart: true },
  });
  const result = await refreshTelemetryStatusCommand(context);
  assert.equal(result.ok, false);
  assert.deepEqual(context.managerCalls, ['getStatus']);
  assert.deepEqual(context.got, []);
  assert.deepEqual(context.patches, []);
});

test('refreshTelemetryStatusCommand mirrors the server fact when the sidecar is ready', async () => {
  const { refreshTelemetryStatusCommand } = loadWithVscodeMock(telemetryCommandsModulePath, {});
  const context = createContext({
    statusResponse: { opt_in: true, consent_updated_at: '2026-10-17T00:00:00+00:00', consent_changes: 2 },
  });
  const result = await refreshTelemetryStatusCommand(context);
  assert.equal(result.ok, true);
  assert.deepEqual(context.managerCalls, ['getStatus']);
  assert.deepEqual(context.got, [{ requestPath: '/telemetry/status' }]);
  assert.deepEqual(context.patches, [{ telemetryOptIn: true }]);
  assert.equal(context.syncs.length, 1);
});
