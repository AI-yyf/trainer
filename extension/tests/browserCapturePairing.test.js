'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const pairingModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'browserCapture',
  'pairingCode.js',
);
const commandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'browserCaptureCommands.js',
);
const constantsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'constants.js',
);

function createRecordingTransport({ failRegister = false, failRevoke = false } = {}) {
  const calls = [];
  return {
    calls,
    async registerPairingCode(request) {
      calls.push({ kind: 'register', ...request });
      if (failRegister) {
        throw new Error('sidecar unreachable');
      }
    },
    async revokePairing() {
      calls.push({ kind: 'revoke' });
      if (failRevoke) {
        throw new Error('revoke refused');
      }
    },
  };
}

function loadPairing() {
  return loadWithVscodeMock(pairingModulePath, {
    window: {},
    workspace: {},
    commands: {},
  });
}

test('pairing codes are six digits drawn from crypto bytes', () => {
  const { generatePairingCode } = loadPairing();

  // 0x000F4240 === 1_000_000 -> the zero-padded boundary code.
  assert.equal(generatePairingCode(() => Buffer.from([0x00, 0x0f, 0x42, 0x40])), '000000');
  // 0x000F423F === 999_999 -> the largest code.
  assert.equal(generatePairingCode(() => Buffer.from([0x00, 0x0f, 0x42, 0x3f])), '999999');

  for (let index = 0; index < 200; index += 1) {
    assert.match(generatePairingCode(), /^[0-9]{6}$/);
  }
});

test('a pairing code is active for ten minutes and expires afterwards', async () => {
  const { BrowserPairingSession, isPairingCodeShape } = loadPairing();
  const { BROWSER_CAPTURE } = require(constantsModulePath);
  let now = 1_700_000_000_000;
  const transport = createRecordingTransport();
  const session = new BrowserPairingSession({
    transport,
    now: () => now,
    generateCode: () => '123456',
  });

  const issue = await session.issuePairingCode();
  assert.equal(issue.code, '123456');
  assert.equal(isPairingCodeShape(issue.code), true);
  assert.equal(issue.expiresAt - now, BROWSER_CAPTURE.pairingCodeTtlMs);
  assert.equal(issue.expiresInSeconds, 600);
  assert.equal(issue.expiresInMinutes, 10);
  assert.deepEqual(transport.calls, [{ kind: 'register', code: '123456', expires_in: 600 }]);

  now += BROWSER_CAPTURE.pairingCodeTtlMs - 1;
  assert.equal(session.state(), 'active');
  assert.equal(session.activeCode(), '123456');
  assert.equal(session.isCodeActive('123456'), true);

  now += 1;
  assert.equal(session.state(), 'expired');
  assert.equal(session.activeCode(), undefined);
  assert.equal(session.isCodeActive('123456'), false);
  assert.equal(session.consumePairingCode('123456'), false);
});

test('a pairing code is single use: consuming it retires that code only', async () => {
  const { BrowserPairingSession } = loadPairing();
  let counter = 0;
  const transport = createRecordingTransport();
  const session = new BrowserPairingSession({
    transport,
    generateCode: () => `00000${(counter += 1)}`,
  });

  const first = await session.issuePairingCode();
  assert.equal(session.isCodeActive(first.code), true);
  assert.equal(session.consumePairingCode(first.code), true);
  assert.equal(session.state(), 'consumed');
  assert.equal(session.isCodeActive(first.code), false);
  assert.equal(session.consumePairingCode(first.code), false);
  assert.equal(session.activeCode(), undefined);

  const second = await session.issuePairingCode();
  assert.notEqual(second.code, first.code);
  assert.equal(second.regenerated, true);
  // Rotation deletes the previous registration before registering the new one.
  assert.deepEqual(
    transport.calls.map((call) => call.kind),
    ['register', 'revoke', 'register'],
  );
  assert.equal(session.isCodeActive(first.code), false);
  assert.equal(session.isCodeActive(second.code), true);
});

test('re-issuing rotates the code and tolerates a failing delete of the old registration', async () => {
  const { BrowserPairingSession } = loadPairing();
  const transport = createRecordingTransport({ failRevoke: true });
  let counter = 0;
  const session = new BrowserPairingSession({
    transport,
    generateCode: () => `10000${(counter += 1)}`,
  });

  const first = await session.issuePairingCode();
  const second = await session.issuePairingCode();

  assert.notEqual(second.code, first.code);
  assert.equal(session.isCodeActive(first.code), false);
  assert.equal(session.isCodeActive(second.code), true);
  assert.deepEqual(
    transport.calls.map((call) => call.kind),
    ['register', 'revoke', 'register'],
  );
});

test('revocation clears the ledger locally even when the remote delete fails', async () => {
  const { BrowserPairingSession } = loadPairing();
  const transport = createRecordingTransport();
  const session = new BrowserPairingSession({ transport, generateCode: () => '654321' });
  const issue = await session.issuePairingCode();

  const revoked = await session.revokePairing();
  assert.deepEqual(revoked, { revoked: true, hadRegistration: true });
  assert.equal(session.state(), 'revoked');
  assert.equal(session.isCodeActive(issue.code), false);
  assert.equal(transport.calls.at(-1).kind, 'revoke');

  const failing = new BrowserPairingSession({
    transport: createRecordingTransport({ failRevoke: true }),
    generateCode: () => '111111',
  });
  await failing.issuePairingCode();
  const refused = await failing.revokePairing();
  assert.equal(refused.revoked, false);
  assert.match(refused.error, /revoke refused/);
  assert.equal(failing.state(), 'revoked');
  assert.equal(failing.activeCode(), undefined);
});

test('a failed registration leaves no reusable code behind', async () => {
  const { BrowserPairingSession } = loadPairing();
  const session = new BrowserPairingSession({
    transport: createRecordingTransport({ failRegister: true }),
    generateCode: () => '222222',
  });

  await assert.rejects(() => session.issuePairingCode(), /sidecar unreachable/);
  assert.equal(session.state(), 'idle');
  assert.equal(session.activeCode(), undefined);
  assert.equal(session.isCodeActive('222222'), false);
});

function createPairingCommandContext({ deletePairingImpl, infoChoice } = {}) {
  const requests = [];
  const infoMessages = [];
  const clipboardWrites = [];
  const vscodeMock = {
    window: {
      showInformationMessage: async (message, ...actions) => {
        infoMessages.push({ message, actions });
        return infoChoice;
      },
      showErrorMessage: async () => undefined,
      showWarningMessage: async () => undefined,
    },
    env: {
      clipboard: {
        writeText: async (text) => {
          clipboardWrites.push(text);
        },
      },
    },
    commands: { registerCommand: () => ({ dispose() {} }) },
    workspace: { isTrusted: true },
  };
  const context = {
    outputChannel: { appendLine() {} },
    extensionContext: { subscriptions: [] },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        requests.push({ kind: 'postJson', port, requestPath, body });
        return {};
      },
      async deleteJson(port, requestPath) {
        requests.push({ kind: 'deleteJson', port, requestPath });
        if (deletePairingImpl) {
          return deletePairingImpl();
        }
        return {};
      },
    },
    workbench: {
      show: async () => undefined,
      syncState: async () => undefined,
      postMessage: async () => undefined,
      setRefreshHandler: () => undefined,
    },
    getHostState() {
      return { workspace: {}, bootstrap: {} };
    },
    getSessionId: () => undefined,
    patchWorkbenchData: async () => undefined,
  };
  return { context, requests, infoMessages, clipboardWrites, vscodeMock };
}

test('the pairing command registers a six-digit code and shows it with a copy action', async () => {
  const { BROWSER_CAPTURE } = require(constantsModulePath);
  const lane = createPairingCommandContext({ infoChoice: 'Copy Code' });
  const { browserCapturePairingCodeCommand } = loadWithVscodeMock(commandsModulePath, lane.vscodeMock);
  const { context, requests, infoMessages, clipboardWrites } = lane;

  const result = await browserCapturePairingCodeCommand(context);

  assert.equal(result.ok, true);
  const registration = requests.find((entry) => entry.kind === 'postJson');
  assert.equal(registration.requestPath, BROWSER_CAPTURE.pairCodePath);
  assert.equal(registration.port, 34891);
  assert.match(registration.body.code, /^[0-9]{6}$/);
  assert.equal(registration.body.expires_in, 600);
  // The registration binds the code to the host's runtime workspace, so the
  // credential (and every capture it makes) belongs to that project only.
  assert.equal(typeof registration.body.workspace_id, 'string');
  assert.ok(registration.body.workspace_id.length > 0);
  assert.equal(infoMessages.length, 1);
  assert.ok(infoMessages[0].message.includes(registration.body.code));
  assert.ok(infoMessages[0].message.includes('single use'));
  assert.deepEqual(infoMessages[0].actions, ['Copy Code']);
  // The command result never echoes the code into logs or the webview.
  assert.equal(result.message.includes(registration.body.code), false);
  assert.equal(result.data.code, undefined);
  assert.equal(typeof result.data.expiresAt, 'number');

  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(clipboardWrites, [registration.body.code]);
});

test('re-running the pairing command rotates the registered code', async () => {
  const { BROWSER_CAPTURE } = require(constantsModulePath);
  const lane = createPairingCommandContext();
  const { browserCapturePairingCodeCommand } = loadWithVscodeMock(commandsModulePath, lane.vscodeMock);

  const first = await browserCapturePairingCodeCommand(lane.context);
  const second = await browserCapturePairingCodeCommand(lane.context);

  assert.equal(first.ok, true);
  assert.equal(second.ok, true);
  const registrations = lane.requests.filter((entry) => entry.kind === 'postJson');
  assert.equal(registrations.length, 2);
  assert.equal(registrations[0].requestPath, BROWSER_CAPTURE.pairCodePath);
  assert.notEqual(registrations[0].body.code, registrations[1].body.code);
  // The previous registration is deleted first so exactly one code is live.
  assert.deepEqual(
    lane.requests.map((entry) => entry.kind),
    ['postJson', 'deleteJson', 'postJson'],
  );
  assert.equal(lane.requests[1].requestPath, BROWSER_CAPTURE.pairPath);
});

test('revoking the pairing calls DELETE /browser/pair and reports the failure honestly', async () => {
  const { BROWSER_CAPTURE } = require(constantsModulePath);
  const lane = createPairingCommandContext();
  const { revokeBrowserCapturePairingCommand } = loadWithVscodeMock(commandsModulePath, lane.vscodeMock);

  const result = await revokeBrowserCapturePairingCommand(lane.context);

  assert.equal(result.ok, true);
  assert.equal(lane.requests[0].kind, 'deleteJson');
  assert.equal(lane.requests[0].requestPath, BROWSER_CAPTURE.pairPath);

  const failing = createPairingCommandContext({
    deletePairingImpl: () => {
      throw new Error('sidecar refused');
    },
  });
  const { revokeBrowserCapturePairingCommand: failingCommand } = loadWithVscodeMock(
    commandsModulePath,
    failing.vscodeMock,
  );
  const failure = await failingCommand(failing.context);
  assert.equal(failure.ok, false);
  assert.match(failure.message, /sidecar refused/);
});

test('the pairing command reports an unavailable sidecar without minting a code', async () => {
  const lane = createPairingCommandContext();
  const { browserCapturePairingCodeCommand } = loadWithVscodeMock(commandsModulePath, lane.vscodeMock);
  lane.context.sidecarManager.ensureRunning = async () => ({
    lifecycle: 'stopped',
    host: '127.0.0.1',
    detail: 'Sidecar is not running.',
    canStart: true,
  });

  const result = await browserCapturePairingCodeCommand(lane.context);

  assert.equal(result.ok, false);
  assert.match(result.message, /Sidecar is not running/);
  assert.deepEqual(lane.requests, []);
  assert.deepEqual(lane.infoMessages, []);
});
