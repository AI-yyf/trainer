'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const { EventEmitter } = require('node:events');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '../..');
const load = () => import(pathToFileURL(path.join(root, 'extension/scripts/vsix-host-diagnostics.mjs')).href);
const write = (file, text) => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
};

test('Linux secret diagnostics use official encryption logging and bounded presence without credentials or service activation', async () => {
  const { inspectLinuxSecretService, linuxSecretDiagnosticLaunchArgs } = await load();
  assert.deepEqual(linuxSecretDiagnosticLaunchArgs('linux', true), ['--verbose', '--vmodule=*/components/os_crypt/*=1']);
  for (const platform of ['darwin', 'win32']) assert.deepEqual(linuxSecretDiagnosticLaunchArgs(platform, true), []);
  assert.deepEqual(linuxSecretDiagnosticLaunchArgs('linux', false), []);
  const env = { DISPLAY: ':99', DBUS_SESSION_BUS_ADDRESS: 'private-address', API_KEY: 'private-provider-key' };
  const calls = [];
  const runCommand = (command, args, options) => {
    calls.push({ command, args, options });
    return { status: 0, stdout: '(false,)\n', stderr: 'private-provider-key' };
  };
  const result = inspectLinuxSecretService({ platform: 'linux', env, runCommand });
  assert.equal(result.probeCompleted, true);
  assert.equal(result.secretServiceOwned, false);
  assert.equal(result.sessionBusAddressPresent, true);
  assert.equal(result.displayPresent, true);
  assert.deepEqual(calls[0].args, ['call', '--session', '--dest', 'org.freedesktop.DBus',
    '--object-path', '/org/freedesktop/DBus', '--method', 'org.freedesktop.DBus.NameHasOwner', 'org.freedesktop.secrets']);
  assert.equal(calls[0].options.timeout, 5000);
  assert.equal(calls[0].options.env, env);
  assert.doesNotMatch(JSON.stringify(result), /private-address|private-provider-key/);
  const timedOut = inspectLinuxSecretService({ platform: 'linux', env, runCommand: () => ({
    status: null, error: { code: 'ETIMEDOUT', message: 'private-address' }, stdout: '(true,)',
  }) });
  assert.equal(timedOut.secretServiceOwned, null);
  assert.equal(timedOut.probeCompleted, false);
  assert.equal(timedOut.errorCode, 'ETIMEDOUT');
  assert.equal(inspectLinuxSecretService({ platform: 'win32', runCommand: () => assert.fail('non-Linux must not probe') }), null);
});

function diagnosticRecorder(steps) {
  return async (name, operation) => {
    const step = { name, state: 'running' };
    steps.push(step);
    try { step.data = await operation(); step.state = 'passed'; return step.data; }
    catch (error) { step.state = 'failed'; step.error = error.message; throw error; }
  };
}

test('driver SecretStorage probe verifies actual round-trip and deletion while reporting booleans only', async () => {
  const { probeDriverSecretStorage, driverSecretDiagnosticRedactions, redactHostDiagnosticText } = await load();
  const items = new Map();
  const calls = [];
  const storage = {
    store: async (key, value) => { calls.push(['store', key, value]); items.set(key, value); },
    get: async (key) => { calls.push(['get', key]); return items.get(key); },
    delete: async (key) => { calls.push(['delete', key]); items.delete(key); },
  };
  const steps = [];
  assert.deepEqual(await probeDriverSecretStorage(storage, diagnosticRecorder(steps)), { roundTrip: true });
  assert.deepEqual(calls.map((call) => call[0]), ['store', 'get', 'delete', 'get']);
  assert.deepEqual(steps.map((step) => step.data), [{ stored: true }, { matched: true }, { deleted: true }, { absent: true }]);
  assert.ok(steps.every((step) => step.state === 'passed'));
  assert.equal(items.size, 0);
  for (const value of calls[0].slice(1)) assert.equal(JSON.stringify(steps).includes(value), false);
  assert.deepEqual(calls[0].slice(1), [...driverSecretDiagnosticRedactions]);
  assert.equal(redactHostDiagnosticText(calls[0].slice(1).join(' '), driverSecretDiagnosticRedactions), '[redacted] [redacted]');
});

test('driver SecretStorage diagnostic times out at the actual pending stage and never continues after failure', async (t) => {
  const { probeDriverSecretStorage } = await load();
  for (const stage of ['store', 'get', 'delete']) await t.test(stage, async () => {
    let storedValue;
    const calls = [];
    const storage = {
      store: async (_, value) => { calls.push('store'); storedValue = value; if (stage === 'store') await new Promise(() => {}); },
      get: async () => { calls.push('get'); if (stage === 'get') await new Promise(() => {}); return storedValue; },
      delete: async () => { calls.push('delete'); if (stage === 'delete') await new Promise(() => {}); storedValue = undefined; },
    };
    const steps = [];
    await assert.rejects(probeDriverSecretStorage(storage, diagnosticRecorder(steps), { timeoutMs: 15 }), new RegExp(stage + ' timed out'));
    assert.equal(steps.at(-1).name, 'diagnostic-secret-' + stage);
    assert.equal(steps.at(-1).state, 'failed');
    assert.deepEqual(calls, ['store', 'get', 'delete'].slice(0, ['store', 'get', 'delete'].indexOf(stage) + 1));
    assert.equal(JSON.stringify(steps).includes(storedValue ?? 'isolated-driver-secret-storage-probe'), false);
  });
});

test('driver SecretStorage probe rejects mismatched and rejected operations without leaking their payloads', async () => {
  const { probeDriverSecretStorage } = await load();
  const steps = [];
  await assert.rejects(probeDriverSecretStorage({ store: async () => {}, get: async () => 'other-secret', delete: async () => assert.fail('must not continue') }, diagnosticRecorder(steps)), /did not round-trip/);
  assert.equal(steps.at(-1).state, 'failed');
  const rejected = [];
  await assert.rejects(probeDriverSecretStorage({ store: async () => { throw new Error('private-provider-value'); } }, diagnosticRecorder(rejected)), /store rejected/);
  assert.doesNotMatch(JSON.stringify(steps) + JSON.stringify(rejected), /other-secret|private-provider-value/);
  let value;
  const retained = [];
  await assert.rejects(probeDriverSecretStorage({
    store: async (_, stored) => { value = stored; }, get: async () => value, delete: async () => {},
  }, diagnosticRecorder(retained)), /delete did not remove/);
  assert.equal(retained.at(-1).name, 'diagnostic-secret-confirm-deleted');
  assert.equal(retained.at(-1).state, 'failed');
  assert.equal(JSON.stringify(retained).includes(value), false);
});

test('failure diagnostics copy bounded isolated Code logs and redact credentials without reading other profiles', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-host-diag-'));
  const tempRoot = path.join(directory, 'isolated');
  const userDataDir = path.join(tempRoot, 'user-data');
  const driverDir = path.join(tempRoot, 'driver');
  const extensionsDir = path.join(tempRoot, 'extensions');
  const outputDir = path.join(directory, 'evidence');
  const secret = 'synthetic-private-provider-value';
  try {
    write(path.join(userDataDir, 'logs/session/main.log'), `startup\nBearer abc-private\nTRAINER_SIDECAR_TOKEN=private-session\n${secret}\n`);
    write(path.join(userDataDir, 'logs/session/exthost.log'), 'x'.repeat(500) + '\nactivation failed');
    write(path.join(userDataDir, 'logs/session/window1/exthost/output_logging_now/1-Trainer.log'), `sidecar starting\nTRAINER_SIDECAR_TOKEN=private-instance\n${secret}`);
    write(path.join(userDataDir, 'logs/session/window1/exthost/output_logging_now/2-Other.log'), 'other channel is private');
    write(path.join(userDataDir, 'logs/session/output_logging_now/3-Trainer.log'), 'spoofed outside exthost must not be copied');
    write(path.join(userDataDir, 'User/state.vscdb'), 'private database must not be copied');
    write(path.join(directory, 'private-profile/main.log'), 'outside profile must not be read');
    write(path.join(driverDir, 'package.json'), JSON.stringify({ main: './extension.js', activationEvents: ['onStartupFinished'], privateField: secret }));
    write(path.join(driverDir, 'extension.js'), 'module.exports = {};');
    fs.mkdirSync(extensionsDir);
    fs.symlinkSync(path.join(directory, 'private-profile'), path.join(userDataDir, 'logs/other-profile'), process.platform === 'win32' ? 'junction' : 'dir');
    const { captureVsixHostFailureDiagnostics } = await load();
    const result = captureVsixHostFailureDiagnostics({
      tempRoot, userDataDir, driverDir, extensionsDir, outputDir, secrets: [secret], maxLogBytes: 128,
      attempts: [{ error: { code: 'ETIMEDOUT' }, stderr: `api_key=${secret}`, status: null }],
      env: { DISPLAY: ':99', TRAINER_E2E_PROVIDER_API_KEY: secret, OTHER_PRIVATE_ENV: secret },
    });
    assert.equal(result.logCount, 3);
    const summaryText = fs.readFileSync(path.join(result.directory, 'diagnostics.json'), 'utf8');
    const summary = JSON.parse(summaryText);
    assert.deepEqual(summary.environment, { DISPLAY: ':99' });
    assert.equal(summary.attempts[0].error.code, 'ETIMEDOUT');
    assert.equal(summary.driver.mainExists, true);
    assert.ok(summary.logs.find((item) => item.path.endsWith('exthost.log')).truncated);
    const main = fs.readFileSync(path.join(result.directory, 'logs/session/main.log'), 'utf8');
    assert.match(main, /startup/);
    assert.match(main, /\[redacted\]/);
    for (const text of [main, summaryText]) assert.doesNotMatch(text, /private-session|abc-private|synthetic-private-provider-value/);
    assert.equal(fs.existsSync(path.join(result.directory, 'logs/other-profile')), false);
    assert.equal(fs.existsSync(path.join(result.directory, 'User')), false);
    const trainer = fs.readFileSync(path.join(result.directory, 'logs/session/window1/exthost/output_logging_now/1-Trainer.log'), 'utf8');
    assert.match(trainer, /sidecar starting/);
    assert.doesNotMatch(trainer, /private-instance|synthetic-private-provider-value/);
    assert.equal(fs.existsSync(path.join(result.directory, 'logs/session/window1/exthost/output_logging_now/2-Other.log')), false);
    assert.equal(fs.existsSync(path.join(result.directory, 'logs/session/output_logging_now')), false);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('structured failure archive redacts escaped log strings and credential values while preserving JSON fields and types', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-host-diag-json-'));
  const userDataDir = path.join(directory, 'user-data');
  const driverDir = path.join(directory, 'driver');
  const extensionsDir = path.join(directory, 'extensions');
  const secret = 'synthetic-private-value';
  const attempts = [{
    status: null, timeoutMs: 15000, ok: false,
    error: { code: 'ETIMEDOUT', message: 'secret: "{\\"encrypted\\":\\"opaque-fixture\\"}"\nactual pending store' },
    stdout: 'OSCrypt secret: "{\\"encrypted\\":\\"opaque-fixture\\"}"\nnext line',
    stderr: 'private=' + secret + '\nBearer escaped-token\\\\value\npath="C:\\owned\\profile"',
    nested: [{ API_KEY: 'unlisted-private-key', password: 'unlisted-private-password', secret: secret,
      name: 'diagnostic-secret-store', timeout: true, count: 7, value: null }],
  }];
  try {
    for (const owned of [userDataDir, driverDir, extensionsDir]) fs.mkdirSync(owned);
    write(path.join(driverDir, 'package.json'), JSON.stringify({ main: './extension.js', activationEvents: ['onStartupFinished'] }));
    write(path.join(driverDir, 'extension.js'), 'module.exports = {};');
    const { captureVsixHostFailureDiagnostics } = await load();
    const result = captureVsixHostFailureDiagnostics({ tempRoot: directory, userDataDir, driverDir,
      extensionsDir, outputDir: path.join(directory, 'evidence'), attempts, secrets: [secret], env: {} });
    const text = fs.readFileSync(path.join(result.directory, 'diagnostics.json'), 'utf8');
    const summary = JSON.parse(text);
    const attempt = summary.attempts[0];
    assert.deepEqual(Object.keys(attempt), Object.keys(attempts[0]));
    assert.deepEqual(Object.keys(attempt.nested[0]), Object.keys(attempts[0].nested[0]));
    assert.equal(attempt.status, null); assert.equal(attempt.timeoutMs, 15000); assert.equal(attempt.ok, false);
    assert.equal(attempt.error.code, 'ETIMEDOUT');
    assert.equal(attempt.nested[0].name, 'diagnostic-secret-store');
    assert.equal(attempt.nested[0].timeout, true); assert.equal(attempt.nested[0].count, 7); assert.equal(attempt.nested[0].value, null);
    assert.equal(attempt.nested[0].API_KEY, '[redacted]'); assert.equal(attempt.nested[0].password, '[redacted]');
    assert.match(attempt.stderr, /path="C:\\owned\\profile"/);
    assert.doesNotMatch(text, /synthetic-private-value|unlisted-private-key|unlisted-private-password|escaped-token/);
    assert.equal(attempts[0].nested[0].API_KEY, 'unlisted-private-key', 'sanitizing the archive must not mutate caller data');
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('installed package scope requires canonical owned profile, manifest identity, and in-package executable/module', async () => {
  const { resolveOwnedSidecarPackage } = await load();
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-vsix-e2e-owned-'));
  const profileDir = path.join(directory, 'user-data');
  const extensionsDir = path.join(directory, 'extensions');
  const extensionPath = path.join(extensionsDir, 'local.trainer-extension');
  const moduleFile = path.join(extensionPath, 'dist/extension/src/core/httpClient.js');
  const executable = path.join(extensionPath, 'bundled/bin/win32-x64/trainer-sidecar.exe');
  const expectedIdentity = { publisher: 'local', name: 'trainer-extension', version: '1.3.4' };
  const input = { profileDir, extensionsDir, extensionPath, target: 'win32-x64', expectedIdentity };
  try {
    fs.mkdirSync(profileDir);
    write(moduleFile, 'fixture module'); write(executable, 'fixture executable');
    write(path.join(extensionPath, 'package.json'), JSON.stringify(expectedIdentity));
    assert.deepEqual(resolveOwnedSidecarPackage(input), { moduleFile: fs.realpathSync(moduleFile), executable: fs.realpathSync(executable) });
    assert.throws(() => resolveOwnedSidecarPackage({ ...input, expectedIdentity: { ...expectedIdentity, version: 'other' } }), /identity/);
    const outside = path.join(directory, 'outside-package');
    fs.mkdirSync(outside);
    assert.throws(() => resolveOwnedSidecarPackage({ ...input, extensionPath: outside }), /outside/);
    const external = path.join(directory, 'outside-module'); write(path.join(external, 'httpClient.js'), 'must not be loaded');
    fs.rmSync(path.dirname(moduleFile), { recursive: true });
    fs.symlinkSync(external, path.dirname(moduleFile), process.platform === 'win32' ? 'junction' : 'dir');
    assert.throws(() => resolveOwnedSidecarPackage(input), /escapes/);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('Windows exact process gate rejects unrelated PID/parent/image/command/port and earlier launch', async () => {
  const { validateOwnedWindowsSidecar } = await load();
  const executable = 'C:\\owned\\extensions\\local.trainer\\bundled\\bin\\win32-x64\\trainer-sidecar.exe';
  const metadata = { pid: 123, parentPid: 55, canonicalExecutable: executable, canonicalCommandExecutable: executable,
    commandLine: `"${executable}" --host 127.0.0.1 --port 34900`, createdAt: new Date(2000).toISOString() };
  const expected = { pid: 123, parentPid: 55, port: 34900, executable, startedAt: 1000 };
  assert.deepEqual(validateOwnedWindowsSidecar(metadata, expected), { pid: 123, port: 34900, createdAt: 2000 });
  for (const mutation of [
    { pid: 124 }, { parentPid: 56 }, { canonicalExecutable: 'C:\\other\\trainer-sidecar.exe' },
    { canonicalCommandExecutable: 'C:\\other\\trainer-sidecar.exe' },
    { commandLine: `"${executable}" --host 0.0.0.0 --port 34900` },
    { commandLine: `"${executable}" --host 127.0.0.1 --port 34901` },
    { commandLine: `"${executable}" --host 127.0.0.1 --port 34900 --unexpected` },
    { createdAt: new Date(500).toISOString() }, { createdAt: 'invalid' },
  ]) assert.throws(() => validateOwnedWindowsSidecar({ ...metadata, ...mutation }, expected), /owned launch identity/);
});

test('actual Windows driver requires fresh exact CIM identity, owned spawn scope, and unchanged public ready PID before its real client', async () => {
  const { validateOwnedWindowsSidecar } = await load();
  const source = fs.readFileSync(path.join(root, 'extension/scripts/verify-vsix-e2e.mjs'), 'utf8');
  const actualFunction = source.match(/function requestThroughOwnedWindowsClient\([^)]*\) \{[\s\S]*?\n\}/)[0];
  const executable = 'C:\\owned\\trainer-vsix-e2e-one\\extensions\\local.trainer\\bundled\\bin\\win32-x64\\trainer-sidecar.exe';
  const ready = { lifecycle: 'ready', host: '127.0.0.1', pid: 123, port: 34900 };
  let metadata = { pid: 123, parentPid: 55, executable, commandLine: `"${executable}" --host 127.0.0.1 --port 34900`, createdAt: new Date(2000).toISOString() };
  let latest = ready;
  let lookups = 0;
  const requests = [];
  const queries = [];
  const facts = [];
  let queryFailure;
  let rawOverride;
  const scope = { argumentShapeValid: true, dataDirInsideOwnedInvocation: true, args: ['--host', '127.0.0.1', '--port', '34900'], cwd: path.win32.dirname(executable) };
  const context = {
    process: { pid: 55, env: { SystemRoot: 'C:\\Windows' } }, path: path.win32,
    fs: { realpathSync: (value) => value },
    vscode: { extensions: { getExtension: () => ({ exports: { getDebugState: () => ({ sidecar: ++lookups === 1 ? ready : latest }) } }) } },
    windowsSidecarCapture: { request: (...args) => { requests.push(args); return { verifiedClient: true }; } },
    windowsSidecarScope: { executable }, windowsSidecarCaptureStartedAt: 1000,
    windowsOwnedLaunches: new Map([[123, scope]]), validateOwnedWindowsSidecar,
    recordWindowsSidecarIdentity: (stage, state, code) => facts.push({ stage, state, code }),
    execFileSync: (command, args, options) => { queries.push({ command, args, options }); if (queryFailure) throw queryFailure; return rawOverride ?? JSON.stringify(metadata); },
  };
  const invoke = () => { lookups = 0; return vm.runInNewContext(actualFunction + '; requestThroughOwnedWindowsClient("POST",34900,"/fixture",{fixture:true},500)', context); };
  assert.deepEqual(invoke(), { verifiedClient: true });
  assert.equal(queries[0].command, 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe');
  assert.match(queries[0].args[3], /Get-CimInstance Win32_Process -Filter/);
  assert.equal(queries[0].options.env.TRAINER_E2E_OWNED_PID, '123');
  assert.equal(queries[0].options.timeout, 10000);
  assert.equal(requests[0][0], 'POST'); assert.equal(requests[0][1].pid, 123);
  assert.equal(requests[0][2], '/fixture'); assert.equal(requests[0][4], 500);
  const canonicalCwd = scope.cwd;
  scope.cwd = canonicalCwd.replace(/^C:/, 'c:');
  assert.deepEqual(invoke(), { verifiedClient: true }, 'canonical Windows paths differing only in drive case retain the exact owned directory');
  scope.cwd = canonicalCwd;
  invoke(); assert.equal(queries.length, 3, 'CIM identity must be fresh for each request');
  assert.deepEqual(facts.slice(-10).map((fact) => fact.stage), ['ready-state', 'observed-launch', 'canonical-cwd',
    'cim-query', 'cim-json', 'cim-executable', 'cim-command', 'identity-fields', 'latest-state', 'authenticated-client-call']);
  assert.ok(facts.every((fact) => fact.state === 'passed' && fact.code === null));
  for (const mutation of [{ parentPid: 56 }, { pid: 124 }, { executable: 'C:\\other.exe' }]) {
    const original = metadata; metadata = { ...metadata, ...mutation };
    assert.throws(invoke, (error) => error.stage === 'identity-fields' && error.code === 'REJECTED'); metadata = original;
  }
  latest = { ...ready, pid: 124 }; assert.throws(invoke, (error) => error.stage === 'latest-state'); latest = ready;
  scope.cwd = 'C:\\other'; assert.throws(invoke, (error) => error.stage === 'canonical-cwd'); scope.cwd = canonicalCwd;
  const beforeQueryFailure = queries.length;
  queryFailure = Object.assign(new Error('private-process-output'), { code: 'ETIMEDOUT' });
  assert.throws(invoke, (error) => error.stage === 'cim-query' && error.code === 'ETIMEDOUT' && !error.message.includes('private-process-output'));
  queryFailure = undefined; rawOverride = 'private-invalid-process-json';
  assert.throws(invoke, (error) => error.stage === 'cim-json' && error.code === 'REJECTED'); rawOverride = undefined;
  assert.equal(queries.length, beforeQueryFailure + 2);
  context.windowsOwnedLaunches.clear(); assert.throws(invoke, (error) => error.stage === 'observed-launch');
  assert.doesNotMatch(JSON.stringify(facts), /private-process-output|private-invalid-process-json/);
  assert.equal(requests.length, 3, 'failed identity never reaches the authenticated client');
});

test('Windows driver selects only a unique loaded canonical cached installed client without loading a copy', () => {
  const source = fs.readFileSync(path.join(root, 'extension/scripts/verify-vsix-e2e.mjs'), 'utf8');
  const actualFunction = source.match(/function resolveOwnedCachedSidecarClient\([^)]*\) \{[\s\S]*?\n\}/)[0];
  const expected = 'C:\\owned\\extensions\\local.trainer\\dist\\extension\\src\\core\\httpClient.js';
  class Client {}
  let cache = { [expected.toLowerCase()]: { filename: expected.toLowerCase(), loaded: true, exports: { SidecarHttpClient: Client } } };
  const resolve = () => vm.runInNewContext(actualFunction + '; resolveOwnedCachedSidecarClient(cache, expected)',
    { fs: { realpathSync: (filename) => filename }, path: path.win32, cache, expected });
  assert.equal(resolve(), Client, 'case-varied cache key uses the existing activated class');
  cache[expected] = { filename: expected, loaded: true, exports: { SidecarHttpClient: Client } };
  assert.throws(resolve, (error) => error.code === 'CACHE_AMBIGUOUS');
  delete cache[expected]; cache[expected.toLowerCase()].loaded = false;
  assert.throws(resolve, (error) => error.code === 'CACHE_EXPORT_INVALID');
  cache[expected.toLowerCase()].loaded = true; cache[expected.toLowerCase()].filename = 'C:\\outside\\httpClient.js';
  assert.throws(resolve, (error) => error.code === 'CACHE_MISSING');
  cache = {}; assert.throws(resolve, (error) => error.code === 'CACHE_MISSING');
  const actualPath = require.resolve('../dist/extension/src/core/httpClient.js');
  const { SidecarHttpClient } = require(actualPath);
  assert.equal(vm.runInNewContext(actualFunction + '; resolveOwnedCachedSidecarClient(cache, expected)',
    { fs, path, cache: require.cache, expected: fs.realpathSync(actualPath) }), SidecarHttpClient);
});

test('Windows harness setter-count observer delegates unchanged and restores after authenticated capture', async () => {
  const source = fs.readFileSync(path.join(root, 'extension/scripts/verify-vsix-e2e.mjs'), 'utf8');
  const actualBlock = source.match(/        const originalSetter = Client\.prototype\.setInstanceToken;[\s\S]*?        restoreSidecarSetterObserver = \(\) => \{[\s\S]*?\n        \};/)[0];
  const { captureInstalledSidecarClient } = await load();
  const marker = {}; const calls = []; const facts = { authSetterObservationCount: 0 };
  class Client { setInstanceToken(...args) { calls.push({ receiver: this, args }); return marker; } }
  const original = Client.prototype.setInstanceToken;
  const context = { Client, facts, saveFacts: () => {}, restoreSidecarSetterObserver: undefined };
  vm.runInNewContext(actualBlock, context);
  const capture = captureInstalledSidecarClient(Client);
  const client = new Client();
  assert.equal(client.setInstanceToken('synthetic-private-token'), marker);
  assert.equal(calls[0].receiver, client); assert.deepEqual(calls[0].args, ['synthetic-private-token']);
  assert.equal(facts.authSetterObservationCount, 1);
  assert.doesNotMatch(JSON.stringify(facts), /synthetic-private-token/);
  capture.restore(); context.restoreSidecarSetterObserver();
  assert.equal(Client.prototype.setInstanceToken, original);
});

test('real installed client keeps per-instance authentication, rejects stale launches, and observes real health failures without secrets', async () => {
  const { captureInstalledSidecarClient } = await load();
  const { SidecarHttpClient } = require('../dist/extension/src/core/httpClient.js');
  let token = 'synthetic-first-instance';
  let forbidden = false;
  let requests = 0;
  const health = [];
  const server = http.createServer((request, response) => {
    requests += 1;
    assert.equal(request.headers['x-trainer-token'], token);
    response.writeHead(forbidden ? 401 : 200, { 'content-type': 'application/json' });
    response.end(JSON.stringify(forbidden ? { detail: 'private-payload-must-not-be-recorded' } : { ok: true }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  let now = 100;
  const originalSetter = SidecarHttpClient.prototype.setInstanceToken;
  const capture = captureInstalledSidecarClient(SidecarHttpClient, { clock: () => now, onHealthResult: (fact) => health.push(fact) });
  try {
    const first = new SidecarHttpClient();
    first.setInstanceToken(token);
    const launch = { pid: 123, port, createdAt: 200 };
    assert.deepEqual(await capture.request('GET', launch, '/health', undefined, 500), { ok: true });
    assert.deepEqual(await capture.request('POST', launch, '/memory', { fixture: true }, 500), { ok: true });
    assert.equal(health.length, 1, 'only actual GET /health is observed');
    assert.equal(health[0].responseResolved, true);
    assert.equal(health[0].statusCode, null, 'resolved JSON carries no real response status');
    assert.throws(() => capture.request('GET', { ...launch, pid: 124 }, '/health', undefined, 500), /current authenticated|different sidecar/);
    assert.equal(requests, 2);
    now = 300;
    token = 'synthetic-second-instance';
    const second = new SidecarHttpClient();
    second.setInstanceToken(token);
    assert.throws(() => capture.request('GET', launch, '/health', undefined, 500), /current authenticated/);
    assert.deepEqual(await capture.request('GET', { pid: 124, port, createdAt: 400 }, '/health', undefined, 500), { ok: true });
    forbidden = true;
    assert.equal(await second.probeHealth(port), false, 'original production probe still catches the real HTTP rejection');
    assert.equal(health.at(-1).statusCode, 401);
    assert.equal(health.at(-1).errorName, 'SidecarHttpError');
    assert.doesNotMatch(JSON.stringify(health), /synthetic-first-instance|synthetic-second-instance|private-payload/);
    capture.restore();
    assert.equal(SidecarHttpClient.prototype.setInstanceToken, originalSetter);
    assert.equal(Object.hasOwn(second, 'requestJson'), false);
    assert.throws(() => capture.request('GET', { pid: 124, port, createdAt: 400 }, '/health', undefined, 500), /current authenticated/);
  } finally { capture.restore(); await new Promise((resolve) => server.close(resolve)); }
});

test('client wrapper preserves receiver/arguments/return and immediate health execution with original failure identity', async () => {
  const { captureInstalledSidecarClient } = await load();
  const marker = {};
  const calls = [];
  const failure = Object.assign(new Error('private-error-message'), { statusCode: 503 });
  class Client {
    setInstanceToken(...args) { calls.push({ receiver: this, args }); return marker; }
    requestJson(...args) { calls.push({ started: true, args }); return Promise.reject(failure); }
    getJson(port, route, options) { return this.requestJson('GET', port, route, undefined, options); }
  }
  const facts = [];
  const capture = captureInstalledSidecarClient(Client, { clock: () => 100, onHealthResult: (fact) => facts.push(fact) });
  const client = new Client();
  try {
    assert.equal(client.setInstanceToken('private-token'), marker);
    assert.equal(calls[0].receiver, client);
    assert.deepEqual(calls[0].args, ['private-token']);
    const pending = capture.request('GET', { pid: 1, port: 123, createdAt: 200 }, '/health', undefined, 500);
    assert.equal(calls[1].started, true, 'request starts synchronously before returning its promise');
    await assert.rejects(pending, (error) => error === failure);
    assert.equal(facts[0].statusCode, 503);
    assert.doesNotMatch(JSON.stringify(facts), /private-token|private-error-message/);
  } finally { capture.restore(); }
});

test('spawn observer records only exact packaged child and boolean isolated environment facts and restores ownership', async () => {
  const { observeOwnedSidecarSpawn } = await load();
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-vsix-e2e-spawn-'));
  const executable = path.join(directory, 'trainer-sidecar.exe');
  const profileRoot = path.join(directory, 'profile');
  const data = path.join(directory, 'trainer-workspace/.trainer');
  write(executable, 'fixture executable'); write(path.join(data, 'marker'), 'fixture'); fs.mkdirSync(profileRoot);
  const calls = [];
  const child = Object.assign(new EventEmitter(), { pid: 321 });
  const original = function(...args) { calls.push({ receiver: this, args }); return child; };
  const childProcess = { spawn: original };
  const facts = [];
  const restore = observeOwnedSidecarSpawn(childProcess, { executable: fs.realpathSync(executable), profileRoot,
    invocationRoot: fs.realpathSync(directory), onFact: (fact) => facts.push(fact) });
  const options = { cwd: directory, env: { TRAINER_SIDECAR_TOKEN: 'private-instance-token', TRAINER_DATA_DIR: data, OTHER_PRIVATE: 'private-env' } };
  try {
    assert.equal(childProcess.spawn(executable, ['--host', '127.0.0.1', '--port', '34900'], options), child);
    assert.equal(calls[0].receiver, childProcess);
    assert.equal(calls[0].args[2], options);
    assert.equal(facts[0].dataDirInsideOwnedProfile, false);
    assert.equal(facts[0].dataDirInsideOwnedInvocation, true);
    assert.equal(facts[0].environmentPresence.TRAINER_SIDECAR_TOKEN, true);
    child.emit('exit', 3, null);
    assert.equal(facts.at(-1).exitCode, 3);
    childProcess.spawn(path.join(directory, 'not-owned.exe'), [], {});
    assert.equal(facts.length, 2);
    assert.doesNotMatch(JSON.stringify(facts), /private-instance-token|private-env|OTHER_PRIVATE/);
    restore(); assert.equal(childProcess.spawn, original);
  } finally { restore(); fs.rmSync(directory, { recursive: true, force: true }); }
});

test('actual host harness preserves launch failure and exports Code diagnostics before removing its temporary profile', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-host-failure-'));
  try {
    const fakeDriver = path.join(directory, 'fake-code.cjs');
    const fakeCli = path.join(directory, process.platform === 'win32' ? 'fake-code.cmd' : 'fake-code');
    const vsix = path.join(directory, 'fixture.vsix');
    const reportPath = path.join(directory, 'evidence/host-report.json');
    const secret = 'synthetic-private-provider-value';
    write(fakeDriver, `
      const fs = require('node:fs');
      const path = require('node:path');
      if (process.argv.includes('--install-extension')) process.exit(0);
      const profile = process.argv[process.argv.indexOf('--user-data-dir') + 1];
      const logs = path.join(profile, 'logs', 'startup');
      fs.mkdirSync(logs, { recursive: true });
      fs.writeFileSync(path.join(logs, 'main.log'), 'synthetic startup failure\\nBearer private-log-key');
      fs.writeFileSync(path.join(logs, 'renderer.log'), process.env.TRAINER_E2E_ARTIFACTS_DIR);
      // Execute the actual generated driver, then strand extension activation.
      // Its incremental report must distinguish this from a driver never started.
      const Module = require('node:module');
      const originalLoad = Module._load;
      Module._load = function(name, ...args) {
        if (name === 'vscode') return { extensions: { getExtension: () => ({
          id: 'local.trainer-extension', packageJSON: { name: 'trainer-extension', version: '1.3.4' },
          activate: () => new Promise(() => {}),
        }) } };
        return originalLoad.call(this, name, ...args);
      };
      const driver = process.argv[process.argv.indexOf('--extensionDevelopmentPath') + 1];
      require(path.join(driver, 'extension.js')).activate();
      setTimeout(() => {
        console.error('synthetic launch failed ' + process.env.TRAINER_E2E_PROVIDER_API_KEY);
        process.exit(23);
      }, 200);
    `);
    const quote = (value) => `'${value.replaceAll("'", "'\\''")}'`;
    write(fakeCli, process.platform === 'win32'
      ? `@echo off\r\n"${process.execPath}" "${fakeDriver}" %*\r\nexit /b %ERRORLEVEL%\r\n`
      : `#!/bin/sh\nexec ${quote(process.execPath)} ${quote(fakeDriver)} "$@"\n`);
    if (process.platform !== 'win32') fs.chmodSync(fakeCli, 0o755);
    write(vsix, 'not a product artifact: only the synthetic launch-failure path is exercised');
    const result = spawnSync(process.execPath, [path.join(root, 'extension/scripts/verify-vsix-e2e.mjs')], {
      cwd: root, encoding: 'utf8', timeout: 15000,
      env: {
        ...process.env, CODE_CLI_PATH: fakeCli, TRAINER_VSIX_OUTPUT_PATH: vsix,
        TRAINER_SKIP_VSIX_REBUILD: '1', TRAINER_E2E_EXPORT_REPORT_PATH: path.relative(root, reportPath),
        TRAINER_E2E_PROVIDER_BASE_URL: 'http://127.0.0.1:1/v1', TRAINER_E2E_PROVIDER_API_KEY: secret,
        TRAINER_E2E_PROVIDER_MODEL: 'synthetic-model', TRAINER_KEEP_VSIX_E2E: '0',
        TRAINER_KEEP_VSIX_E2E_ON_FAILURE: '0', TRAINER_VSIX_E2E_TEMP_ROOT: '',
      },
    });
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stderr, /synthetic launch failed/);
    assert.doesNotMatch(result.stderr, new RegExp(secret));
    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
    assert.equal(report.ok, false);
    assert.equal(report.report, null);
    assert.equal(fs.existsSync(report.tempRoot), false);
    const diagnostics = JSON.parse(fs.readFileSync(path.join(report.diagnostics.directory, 'diagnostics.json'), 'utf8'));
    assert.equal(diagnostics.attempts.length, 2);
    assert.equal(diagnostics.attempts[1].status, 23);
    assert.ok(diagnostics.attempts[1].args.includes('--extensionDevelopmentPath'));
    assert.deepEqual(diagnostics.driver.activationEvents, ['onStartupFinished']);
    assert.equal(diagnostics.driver.mainExists, true);
    assert.match(fs.readFileSync(path.join(report.diagnostics.directory, 'logs/startup/main.log'), 'utf8'), /synthetic startup failure/);
    assert.equal(fs.readFileSync(path.join(report.diagnostics.directory, 'logs/startup/renderer.log'), 'utf8'), path.join(path.dirname(reportPath), 'vsix-installed-state'));
    const progress = JSON.parse(fs.readFileSync(path.join(report.artifactsDir, 'host-progress.json'), 'utf8'));
    assert.deepEqual(progress.steps.map((step) => [step.name, step.state]), [
      ['find-installed-extension', 'passed'], ['activate-installed-extension', 'running'],
    ]);
    assert.ok(progress.steps.every((step) => Object.keys(step).every((key) => ['name', 'state', 'startedAt', 'finishedAt'].includes(key))));
    assert.doesNotMatch(JSON.stringify(report) + JSON.stringify(diagnostics), new RegExp(secret));
  } finally {
    fs.rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
});
