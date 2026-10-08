const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { test } = require('node:test');

const load = () => import(pathToFileURL(path.resolve(__dirname, '../../scripts/run-linux-vsix-host.mjs')).href);
const header = Buffer.from('GnomeKeyring\n\r\0\n\0');

function commandFixture({ locked = false, owner = 123, collection = 'login', mismatch = false, existing = false } = {}) {
  const calls = [];
  let stored;
  const run = (command, args, options) => {
    calls.push({ command, args, timeout: options.timeout, inputPresent: Boolean(options.input) });
    assert.equal(options.timeout, 5000);
    if (command.endsWith('/gdbus')) {
      let value;
      if (args.includes('org.freedesktop.DBus.NameHasOwner')) value = `(${existing},)`;
      else if (args.includes('org.freedesktop.DBus.GetConnectionUnixProcessID')) value = `(uint32 ${owner},)`;
      else if (args.includes('org.freedesktop.Secret.Service.ReadAlias')) value = `(objectpath '/org/freedesktop/secrets/collection/${collection}',)`;
      else if (args.includes('org.freedesktop.DBus.Properties.Get')) value = `(<${locked}>,)`;
      else assert.fail('unexpected DBus method');
      return { status: 0, stdout: Buffer.from(value) };
    }
    assert.ok(command.endsWith('/secret-tool'));
    if (args[0] === 'store') { stored = Buffer.from(options.input); return { status: 0, stdout: Buffer.alloc(0) }; }
    if (args[0] === 'clear') { stored?.fill(0); stored = undefined; return { status: 0, stdout: Buffer.alloc(0) }; }
    if (args[0] === 'lookup') return stored
      ? { status: 0, stdout: mismatch ? Buffer.from('different') : Buffer.concat([stored, Buffer.from('\n')]) }
      : { status: 1, stdout: Buffer.alloc(0) };
    assert.fail('unexpected secret-tool action');
  };
  return { run, calls };
}

test('private Linux XDG scope preserves HOME and isolates inherited session/keyring pointers', async () => {
  const { createLinuxKeyringScope, assertLinuxKeyringScope, privateUnixPermissions } = await load();
  const original = { HOME: '/original/home', CI: 'true', DBUS_SESSION_BUS_ADDRESS: 'original-bus',
    GNOME_KEYRING_CONTROL: '/original/keyring', GNOME_KEYRING_PID: '999', TRAINER_E2E_LINUX_KEYRING_READY: '1' };
  const before = { ...original };
  const scope = createLinuxKeyringScope({ env: original });
  try {
    assert.equal(assertLinuxKeyringScope(scope.env), scope.root);
    assert.deepEqual(original, before);
    assert.equal(scope.env.HOME, original.HOME);
    assert.equal(scope.env.DBUS_SESSION_BUS_ADDRESS, undefined);
    assert.equal(scope.env.GNOME_KEYRING_PID, undefined);
    assert.equal(scope.env.TRAINER_E2E_LINUX_KEYRING_READY, undefined);
    assert.equal(privateUnixPermissions(fs.statSync(scope.env.XDG_RUNTIME_DIR).mode, { directory: true }), true);
    assert.equal(privateUnixPermissions(0o700, { directory: true, platform: 'linux' }), true);
    assert.equal(privateUnixPermissions(0o755, { directory: true, platform: 'linux' }), false);
    assert.throws(() => assertLinuxKeyringScope({ ...scope.env, XDG_DATA_HOME: '/original/data' }), /outside/);
    fs.chmodSync(scope.env.XDG_CACHE_HOME, 0o755);
    if (process.platform !== 'win32') assert.throws(() => assertLinuxKeyringScope(scope.env), /private/);
    fs.chmodSync(scope.env.XDG_CACHE_HOME, 0o700);
  } finally { fs.rmSync(scope.root, { recursive: true, force: true }); }
});

test('secure backend gate binds current private scope, bus, owned daemon, unlocked encrypted keyring and actual round trip', async () => {
  const { createLinuxKeyringScope, linuxSecureKeyringLaunchArgs } = await load();
  const scope = createLinuxKeyringScope();
  const env = { ...scope.env, DBUS_SESSION_BUS_ADDRESS: 'owned-bus', DISPLAY: ':99',
    TRAINER_E2E_LINUX_KEYRING_READY: '1', TRAINER_E2E_LINUX_KEYRING_PID: '123' };
  const receipt = { pid: 123, ready: true, unlocked: true, roundTrip: true, deleted: true, encryptedKeyring: true,
    busDigest: createHash('sha256').update(env.DBUS_SESSION_BUS_ADDRESS).digest('hex') };
  const write = value => fs.writeFileSync(path.join(scope.root, 'ready.json'), JSON.stringify(value));
  try {
    assert.deepEqual(linuxSecureKeyringLaunchArgs('win32', env), []);
    assert.deepEqual(linuxSecureKeyringLaunchArgs('linux', {}), []);
    write(receipt);
    assert.deepEqual(linuxSecureKeyringLaunchArgs('linux', env, { checkProcess: () => true }), ['--password-store=gnome-libsecret']);
    assert.throws(() => linuxSecureKeyringLaunchArgs('linux', env, { checkProcess: () => false }), /no longer matches/);
    assert.throws(() => linuxSecureKeyringLaunchArgs('linux', { ...env, DISPLAY: '' }, { checkProcess: () => true }), /not ready/);
    assert.throws(() => linuxSecureKeyringLaunchArgs('linux', { ...env, DBUS_SESSION_BUS_ADDRESS: 'other-bus' }, { checkProcess: () => true }), /no longer matches/);
    for (const key of ['ready', 'unlocked', 'roundTrip', 'deleted', 'encryptedKeyring']) {
      write({ ...receipt, [key]: false });
      assert.throws(() => linuxSecureKeyringLaunchArgs('linux', env, { checkProcess: () => true }), /no longer matches/);
    }
  } finally { fs.rmSync(scope.root, { recursive: true, force: true }); }
});

test('Secret Service prerequisite uses only exact owned PID/default collection and private stdin with bounded delete', async () => {
  const { verifyKeyringBackend } = await load();
  const fixture = commandFixture();
  const entropy = Buffer.from('private-entropy-never-exported');
  const result = verifyKeyringBackend({ TRAINER_E2E_LINUX_KEYRING_ROOT: '/tmp/trainer-ci-keyring-fixture' }, 123,
    { run: fixture.run, secret: entropy });
  assert.deepEqual(result, { ready: true, unlocked: true, roundTrip: true, deleted: true });
  assert.equal(entropy.every(byte => byte === 0), true);
  assert.equal(fixture.calls.filter(call => call.inputPresent).length, 1);
  assert.doesNotMatch(JSON.stringify({ result, calls: fixture.calls }), /private-entropy/);
  assert.deepEqual(fixture.calls.filter(call => call.command.endsWith('/secret-tool')).map(call => call.args[0]), ['store', 'lookup', 'clear', 'lookup']);
});

test('foreign PID, locked/default session collection and failed round trip prevent host admission', async () => {
  const { verifyKeyringBackend } = await load();
  const env = { TRAINER_E2E_LINUX_KEYRING_ROOT: '/tmp/trainer-ci-keyring-fixture' };
  for (const [options, message] of [[{ owner: 456 }, /owned keyring process/], [{ locked: true }, /locked/],
    [{ collection: 'session' }, /persistent collection/], [{ collection: '' }, /persistent collection/],
    [{ mismatch: true }, /round-trip/]]) {
    const fixture = commandFixture(options);
    const entropy = Buffer.from('early-rejection-private-entropy');
    assert.throws(() => verifyKeyringBackend(env, 123, { run: fixture.run, secret: entropy }), message);
    assert.equal(entropy.every(byte => byte === 0), true);
    const secretCalls = fixture.calls.filter(call => call.command.endsWith('/secret-tool'));
    if (options.mismatch) assert.equal(secretCalls.at(-1).args[0], 'clear');
    else assert.equal(secretCalls.length, 0);
  }
});

test('early DBus failure wipes its buffer and owned-item cleanup failure preserves both static failures', async () => {
  const { verifyKeyringBackend } = await load();
  const env = { TRAINER_E2E_LINUX_KEYRING_ROOT: '/tmp/trainer-ci-keyring-fixture' };
  const entropy = Buffer.from('private-before-owner-gate');
  assert.throws(() => verifyKeyringBackend(env, 123, { secret: entropy,
    run: () => ({ status: 1, stdout: Buffer.from('private-error-output') }) }), /gdbus failed/);
  assert.equal(entropy.every(byte => byte === 0), true);
  const fixture = commandFixture({ mismatch: true });
  assert.throws(() => verifyKeyringBackend(env, 123, { run: (command, args, options) => args[0] === 'clear'
    ? { status: 1, stdout: Buffer.from('private-cleanup-output') } : fixture.run(command, args, options) }), error => {
    assert.ok(error instanceof AggregateError);
    assert.equal(error.errors.length, 2);
    assert.match(error.errors[0].message, /round-trip/);
    assert.equal(error.errors[1].message, 'Linux keyring prerequisite secret-tool failed.');
    assert.doesNotMatch(error.message, /private-cleanup-output|private-error-output/);
    return true;
  });
});

test('encrypted keyring proof rejects absent, plaintext and public files without exporting their contents', async () => {
  const { createLinuxKeyringScope, inspectEncryptedKeyring, privateUnixPermissions } = await load();
  const scope = createLinuxKeyringScope();
  const file = path.join(scope.root, 'data/keyrings/login.keyring');
  try {
    assert.throws(() => inspectEncryptedKeyring(scope.env), /not created/);
    fs.writeFileSync(file, '[keyring]\nprivate=must-not-appear-in-errors', { mode: 0o600 });
    assert.throws(() => inspectEncryptedKeyring(scope.env), error => /encrypted persistent format/.test(error.message) && !error.message.includes('private='));
    fs.writeFileSync(file, header);
    assert.equal(inspectEncryptedKeyring(scope.env), true);
    fs.chmodSync(file, 0o644);
    assert.equal(privateUnixPermissions(0o644, { platform: 'linux' }), false);
    assert.equal(privateUnixPermissions(0o600, { platform: 'linux' }), true);
    if (process.platform !== 'win32') assert.throws(() => inspectEncryptedKeyring(scope.env), /not private/);
  } finally { fs.rmSync(scope.root, { recursive: true, force: true }); }
});

test('owned outer session runs bus, Xvfb and inner host together and removes scope on success or failure', async () => {
  const { runLinuxHostInOwnedSession, assertLinuxKeyringScope } = await load();
  for (const fail of [false, true]) {
    let root;
    const promise = runLinuxHostInOwnedSession({ env: { CI: 'true', HOME: '/unchanged/home' }, platform: 'linux',
      runSession: async (command, args, options) => {
        root = assertLinuxKeyringScope(options.env);
        assert.equal(command, '/usr/bin/dbus-run-session');
        assert.deepEqual(args.slice(0, 3), ['--', '/usr/bin/xvfb-run', '--auto-servernum']);
        assert.equal(args.at(-1), '--session');
        assert.equal(options.env.HOME, '/unchanged/home');
        assert.equal(options.env.TRAINER_E2E_LINUX_KEYRING_READY, undefined);
        if (fail) throw new Error('fixture session failure');
        return 0;
      } });
    if (fail) await assert.rejects(promise, /fixture session failure/); else assert.equal(await promise, 0);
    assert.equal(fs.existsSync(root), false);
  }
  await assert.rejects(runLinuxHostInOwnedSession({ env: {}, platform: 'linux' }), /disposable Linux CI/);
});

test('prepared lifecycle unlocks only through stdin, gates real backend before unchanged host and stops exact child', async () => {
  const { createLinuxKeyringScope, runPreparedLinuxHost } = await load();
  const scope = createLinuxKeyringScope();
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-ci-keyring-evidence-'));
  const env = { ...scope.env, CI: 'true', DISPLAY: ':99', DBUS_SESSION_BUS_ADDRESS: 'owned-bus',
    TRAINER_E2E_EXPORT_REPORT_PATH: path.join(output, 'host-report.json') };
  const fixture = commandFixture();
  const child = Object.assign(new EventEmitter(), { pid: 123, exitCode: null, signalCode: null });
  let password;
  let killed = false;
  let hostStarted = false;
  child.stdin = Object.assign(new EventEmitter(), { end(value, callback) { password = Buffer.from(value); callback(); } });
  child.kill = signal => { killed = true; child.signalCode = signal; child.emit('exit', null, signal); return true; };
  try {
    const result = await runPreparedLinuxHost({ env, runTool: fixture.run, waitReady: async () => {}, checkProcess: () => true,
      spawnProcess: (command, args, options) => {
        assert.equal(command, '/usr/bin/gnome-keyring-daemon');
        assert.ok(args.includes('--unlock')); assert.ok(args.includes('--foreground')); assert.ok(args.includes('--components=secrets'));
        assert.equal(options.env, env); assert.deepEqual(options.stdio, ['pipe', 'ignore', 'ignore']);
        fs.writeFileSync(path.join(scope.root, 'data/keyrings/login.keyring'), header, { mode: 0o600 });
        return child;
      }, runHost: async (command, args, options) => {
        hostStarted = true;
        assert.equal(command, process.execPath); assert.match(args[0], /verify-vsix-e2e\.mjs$/);
        assert.equal(options.env.TRAINER_E2E_LINUX_KEYRING_READY, '1');
        assert.equal(options.env.TRAINER_E2E_TIMEOUT_MS, undefined, 'does not widen existing Code/host deadlines');
        assert.ok(password.length >= 64); assert.equal(password.includes(0), false);
        assert.equal(JSON.stringify(options.env).includes(password.toString()), false);
        return 0;
      } });
    assert.equal(result, 0); assert.equal(hostStarted, true); assert.equal(killed, true);
    const receipt = JSON.parse(fs.readFileSync(path.join(output, 'linux-keyring-environment.json'), 'utf8'));
    assert.equal(receipt.backend, 'gnome-libsecret'); assert.equal(receipt.encryptedKeyring, true);
    assert.equal(JSON.stringify(receipt).includes(password.toString()), false);
  } finally { password?.fill(0); fs.rmSync(scope.root, { recursive: true, force: true }); fs.rmSync(output, { recursive: true, force: true }); }
});

test('existing Secret Service or incomplete prepared environment never spawns daemon or host', async () => {
  const { createLinuxKeyringScope, runPreparedLinuxHost } = await load();
  const scope = createLinuxKeyringScope();
  try {
    const env = { ...scope.env, DISPLAY: ':99', DBUS_SESSION_BUS_ADDRESS: 'owned-bus' };
    const forbidden = () => assert.fail('must not start anything');
    await assert.rejects(runPreparedLinuxHost({ env, runTool: commandFixture({ existing: true }).run,
      spawnProcess: forbidden, runHost: forbidden }), /already has a Secret Service/);
    await assert.rejects(runPreparedLinuxHost({ env: scope.env, spawnProcess: forbidden, runHost: forbidden }), /same bus and display/);
  } finally { fs.rmSync(scope.root, { recursive: true, force: true }); }
});

test('preparation failure stops the owned daemon and never starts Code or emits a successful receipt', async () => {
  const { createLinuxKeyringScope, runPreparedLinuxHost } = await load();
  const scope = createLinuxKeyringScope();
  const env = { ...scope.env, DISPLAY: ':99', DBUS_SESSION_BUS_ADDRESS: 'owned-bus' };
  const child = Object.assign(new EventEmitter(), { pid: 123, exitCode: null, signalCode: null });
  child.stdin = Object.assign(new EventEmitter(), { end(value, callback) { callback(); } });
  let killed = false;
  child.kill = signal => { killed = true; child.signalCode = signal; child.emit('exit', null, signal); return true; };
  try {
    await assert.rejects(runPreparedLinuxHost({ env, runTool: commandFixture().run,
      spawnProcess: () => child, waitReady: async () => { throw new Error('fixture readiness failure'); },
      runHost: () => assert.fail('must not run Code') }), /fixture readiness failure/);
    assert.equal(killed, true);
    assert.equal(fs.existsSync(path.join(scope.root, 'ready.json')), false);
  } finally { fs.rmSync(scope.root, { recursive: true, force: true }); }
});

test('private tool timeout errors never copy command output, environment or secret input', async () => {
  const { runPrivateTool, randomKeyringPassword } = await load();
  const password = randomKeyringPassword();
  const second = randomKeyringPassword();
  try {
    assert.ok(password.length >= 64); assert.equal(password.equals(second), false);
    assert.throws(() => runPrivateTool('/usr/bin/secret-tool', ['store'], { input: password,
      run: () => ({ status: null, error: new Error('private-output'), stdout: password, stderr: password }) }),
      error => error.message === 'Linux keyring prerequisite secret-tool failed.');
  } finally { password.fill(0); second.fill(0); }
});

test('queued unlock password remains intact until asynchronous end callback and is wiped only afterward', async () => {
  const { writeKeyringPassword } = await load();
  const password = Buffer.from('fixture-password-not-an-environment-variable');
  const pipe = new EventEmitter();
  let callback;
  pipe.end = (value, finished) => { assert.equal(value, password); callback = finished; };
  const pending = writeKeyringPassword(pipe, password);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(password.toString(), 'fixture-password-not-an-environment-variable');
  callback();
  await pending;
  assert.equal(password.every(byte => byte === 0), true);
  assert.equal(pipe.listenerCount('error'), 0);
});

test('bounded broken-pipe handling destroys the pipe but never zeroes an unfinished queued password', async () => {
  const { writeKeyringPassword } = await load();
  const password = Buffer.from('fixture-unlock-password');
  const pipe = new EventEmitter();
  let callback;
  let destroyed = false;
  pipe.end = (_value, finished) => { callback = finished; };
  pipe.destroy = () => { destroyed = true; };
  const pending = writeKeyringPassword(pipe, password, { timeoutMs: 10 });
  await assert.rejects(pending, /password pipe timed out/);
  assert.equal(destroyed, true);
  assert.equal(password.toString(), 'fixture-unlock-password');
  callback(new Error('private error that must not be copied'));
  assert.equal(password.every(byte => byte === 0), true);
});

test('cleanup targets only its owned process group including children after the leader exits', async () => {
  const { stopOwnedProcess } = await load();
  const liveGroups = new Set([-123, -456]);
  const signals = [];
  await stopOwnedProcess({ pid: 123, exitCode: 0 }, { group: true, graceMs: 5,
    signalProcess: (pid, signal) => {
      signals.push({ pid, signal });
      if (!liveGroups.has(pid)) throw Object.assign(new Error('no process'), { code: 'ESRCH' });
      if (signal === 'SIGKILL') liveGroups.delete(pid);
    } });
  assert.equal(liveGroups.has(-123), false);
  assert.equal(liveGroups.has(-456), true);
  assert.ok(signals.every(call => call.pid === -123));
  assert.deepEqual(signals.filter(call => call.signal !== 0).map(call => call.signal), ['SIGTERM', 'SIGKILL']);
});

test('child cleanup removes exit listeners and reports a process that refuses both bounded stop signals', async () => {
  const { stopOwnedProcess } = await load();
  const child = Object.assign(new EventEmitter(), { pid: 123, exitCode: null, signalCode: null });
  const signals = [];
  child.kill = signal => { signals.push(signal); return true; };
  await assert.rejects(stopOwnedProcess(child, { graceMs: 5 }), /did not stop/);
  assert.deepEqual(signals, ['SIGTERM', 'SIGKILL']);
  assert.equal(child.listenerCount('exit'), 0);
});

test('owned root removal does not follow an external directory link or remove an unrelated sentinel', async () => {
  const { runLinuxHostInOwnedSession } = await load();
  const external = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-keyring-unrelated-')));
  const sentinel = path.join(external, 'sentinel.txt');
  fs.writeFileSync(sentinel, 'outside-unchanged');
  let root;
  try {
    await runLinuxHostInOwnedSession({ env: { CI: 'true' }, platform: 'linux',
      runSession: async (_command, _args, { env }) => {
        root = env.TRAINER_E2E_LINUX_KEYRING_ROOT;
        fs.symlinkSync(external, path.join(root, 'cache/external'), process.platform === 'win32' ? 'junction' : 'dir');
        return 0;
      } });
    assert.equal(fs.existsSync(root), false);
    assert.equal(fs.readFileSync(sentinel, 'utf8'), 'outside-unchanged');
  } finally { fs.rmSync(external, { recursive: true, force: true }); }
});
