'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const repoRoot = path.resolve(__dirname, '../..');
const distExtRoot = path.join(repoRoot, 'extension', 'dist', 'extension', 'src');
const distSharedRoot = path.join(repoRoot, 'extension', 'dist', 'shared', 'src');

const constantsMod = require(path.join(distExtRoot, 'core', 'constants.js'));
const pairingCodeMod = require(path.join(distExtRoot, 'browserCapture', 'pairingCode.js'));
const installBundleMod = require(path.join(distExtRoot, 'browserCapture', 'installBundle.js'));
const browserLauncherMod = require(path.join(distExtRoot, 'browserCapture', 'browserLauncher.js'));
const draftPollerMod = require(path.join(distExtRoot, 'browserCapture', 'draftPoller.js'));
const libraryPollerMod = require(path.join(distExtRoot, 'browserCapture', 'libraryPoller.js'));
const eventStreamMod = require(path.join(distExtRoot, 'browserCapture', 'eventStream.js'));
const hostCopyMod = require(path.join(distExtRoot, 'browserCapture', 'hostCopy.js'));
const commandsMod = require(path.join(distSharedRoot, 'commands.js'));
const sharedCaptureMod = require(
  path.join(repoRoot, 'extension', constantsMod.BROWSER_CAPTURE.bundleDirName, 'shared.js'),
);

test('single-use bootstrap handshake token generation, seed persistence, and MV3 parser match cleanly', () => {
  const token = pairingCodeMod.generateBootstrapPairToken();
  assert.match(token, /^trbp-[0-9a-f]{32}$/);
  assert.equal(pairingCodeMod.isBootstrapPairTokenShape(token), true);
  assert.equal(pairingCodeMod.isPairingSecretShape(token), true);
  assert.equal(pairingCodeMod.isPairingSecretShape('482910'), true);
  assert.equal(pairingCodeMod.isPairingSecretShape('bad-token'), false);

  assert.equal(sharedCaptureMod.isValidBootstrapToken(token), true);
  assert.equal(sharedCaptureMod.normalizePairSecret(`  ${token.toUpperCase()}  `), token);
  assert.equal(sharedCaptureMod.normalizePairSecret('123 456'), '123456');
  assert.equal(sharedCaptureMod.normalizePairSecret('12345'), '');

  const scratchRoot = path.join(repoRoot, 'extension', 'dist', 'phase2-seed-fixture');
  fs.mkdirSync(scratchRoot, { recursive: true });
  try {
    const now = 1_760_000_000_000;
    const seed = {
      schemaVersion: 1,
      code: token,
      baseUrl: 'http://localhost:8765/',
      workspaceId: 'ws-phase2',
      workspaceName: 'Phase 2 Workspace',
      issuedAt: now,
      expiresAt: now + 600_000,
    };
    const writtenPath = installBundleMod.writeBootstrapPairSeed(scratchRoot, seed);
    assert.equal(path.basename(writtenPath), 'bootstrap-pair.json');

    const roundTrip = installBundleMod.readBootstrapPairSeedFile(scratchRoot);
    assert.equal(roundTrip.code, token);
    assert.equal(roundTrip.workspaceId, 'ws-phase2');
    assert.equal(roundTrip.workspaceName, 'Phase 2 Workspace');

    const parsedLive = sharedCaptureMod.parseBootstrapPairSeed(
      JSON.parse(fs.readFileSync(writtenPath, 'utf8')),
      now + 5_000,
    );
    assert.equal(parsedLive.code, token);
    assert.equal(parsedLive.baseUrl, 'http://localhost:8765');
    assert.equal(parsedLive.workspaceId, 'ws-phase2');

    const parsedExpired = sharedCaptureMod.parseBootstrapPairSeed(
      JSON.parse(fs.readFileSync(writtenPath, 'utf8')),
      now + 600_001,
    );
    assert.equal(parsedExpired, null, 'Expired seed must be rejected');
  } finally {
    fs.rmSync(scratchRoot, { recursive: true, force: true });
  }
});

test('BrowserPairingSession.issueBootstrapToken registers single-use trbp-* secret and rotates cleanly', async () => {
  const registered = [];
  let revocations = 0;
  const session = new pairingCodeMod.BrowserPairingSession({
    now: () => 1_000_000,
    ttlMs: 600_000,
    transport: {
      async registerPairingCode(req) {
        registered.push(req);
      },
      async revokePairing() {
        revocations += 1;
      },
    },
  });

  const first = await session.issueBootstrapToken();
  assert.match(first.code, /^trbp-[0-9a-f]{32}$/);
  assert.equal(first.regenerated, false);
  assert.equal(registered.length, 1);
  assert.equal(registered[0].code, first.code);
  assert.equal(registered[0].expires_in, 600);
  assert.equal(session.isCodeActive(first.code, 1_001_000), true);

  const second = await session.issueBootstrapToken();
  assert.equal(second.regenerated, true);
  assert.equal(revocations, 1);
  assert.notEqual(second.code, first.code);
  assert.equal(session.consumePairingCode(second.code, 1_002_000), true);
  assert.equal(session.consumePairingCode(second.code, 1_002_500), false);
});

test('browserLauncher builds isolated profile and unpacked flags across mac-app and executable targets', () => {
  const mockExtDir = path.join(repoRoot, 'extension', 'dist', 'mock-ext');
  const mockProfileDir = path.join(repoRoot, 'extension', 'dist', 'mock-profile');
  const macTarget = {
    id: 'mock',
    label: 'MockApp',
    extensionsUrl: 'about:blank',
    launchTarget: 'MockApp',
    launchKind: 'mac-app',
  };
  const macCmd = browserLauncherMod.resolveBrowserWithExtensionLaunch(macTarget, {
    extensionDir: mockExtDir,
    profileDir: mockProfileDir,
    initialUrl: 'https://example.org',
  });
  assert.equal(macCmd.args.includes('MockApp'), true);
  assert.equal(macCmd.args.some((item) => item.includes(mockProfileDir)), true);
  assert.equal(macCmd.args.some((item) => item.includes(mockExtDir)), true);
  assert.equal(macCmd.args.at(-1), 'https://example.org');

  const execTarget = {
    id: 'mock-bin',
    label: 'MockBin',
    extensionsUrl: 'about:blank',
    launchTarget: 'mock-bin',
    launchKind: 'executable',
  };
  let mkdirTarget = null;
  let spawnedCall = null;
  const launched = browserLauncherMod.launchBrowserWithExtension(
    execTarget,
    {
      extensionDir: mockExtDir,
      profileDir: mockProfileDir,
    },
    {
      mkdirSyncFn(dir) {
        mkdirTarget = dir;
      },
      spawnFn(command, args) {
        spawnedCall = { command, args };
        return { unref() {} };
      },
    },
  );
  assert.equal(launched.spawned, true);
  assert.equal(mkdirTarget, mockProfileDir);
  assert.equal(spawnedCall.command, 'mock-bin');
  assert.equal(spawnedCall.args.some((item) => item.includes(mockExtDir)), true);
});

test('BrowserWorkspaceEventStream pushes real-time drafts and library updates while suppressing idle HTTP polling', async () => {
  let draftHttpCalls = 0;
  let libraryHttpCalls = 0;
  const ackedBatches = [];
  const deliveredDraftIds = [];
  const refreshedLibraryRevisions = [];
  let visible = true;

  let draftTimerTick = null;
  let libraryTimerTick = null;

  const receipts = new draftPollerMod.DraftReceiptChannel();
  let eventsRef = null;
  const draftsPoller = new draftPollerMod.BrowserDraftPoller({
    getSidecarPort: () => 8765,
    isWorkbenchVisible: () => visible,
    getWorkspaceId: () => 'ws-sse-1',
    fetchPendingDrafts: async () => {
      draftHttpCalls += 1;
      return { drafts: [] };
    },
    acknowledgeDrafts: async (_port, workspaceId, ids) => {
      ackedBatches.push({ workspaceId, ids });
    },
    forwardDraft: async (draft) => {
      deliveredDraftIds.push(draft.id);
      const receiptPromise = receipts.waitForReceipt(draft.id, 1000);
      receipts.notify(draft.id);
      await receiptPromise;
    },
    shouldSkipTimerPoll: () => Boolean(eventsRef && eventsRef.connected),
    setIntervalFn: (fn) => {
      draftTimerTick = fn;
      return { unref() {} };
    },
    clearIntervalFn: () => {},
  });

  const libraryPoller = new libraryPollerMod.BrowserLibraryPoller({
    getSidecarPort: () => 8765,
    isWorkbenchVisible: () => visible,
    getWorkspaceId: () => 'ws-sse-1',
    fetchLibraryRevision: async () => {
      libraryHttpCalls += 1;
      return { workspace_id: 'ws-sse-1', requested_workspace_id: 'ws-sse-1', revision: 'http-fallback', count: 0 };
    },
    refreshLibrary: async (rev) => {
      refreshedLibraryRevisions.push(rev.revision);
    },
    shouldSkipTimerPoll: () => Boolean(eventsRef && eventsRef.connected),
    setIntervalFn: (fn) => {
      libraryTimerTick = fn;
      return { unref() {} };
    },
    clearIntervalFn: () => {},
  });

  let releaseStream;
  const keepStreamOpen = new Promise((resolve) => {
    releaseStream = resolve;
  });

  const eventStream = new eventStreamMod.BrowserWorkspaceEventStream({
    getSidecarPort: () => 8765,
    isWorkbenchVisible: () => visible,
    getWorkspaceId: () => 'ws-sse-1',
    onDraftsPayload: async (payload) => {
      await draftsPoller.pushDraftsPayload(payload);
    },
    onLibraryPayload: async (payload) => {
      await libraryPoller.pushLibraryPayload(payload);
    },
    setIntervalFn: () => ({ unref() {} }),
    clearIntervalFn: () => {},
    async *openEventStream(_port, requestPath, options) {
      assert.equal(requestPath, '/browser/events/stream?workspace_id=ws-sse-1');
      yield {
        event: 'snapshot',
        data: JSON.stringify({
          workspace_id: 'ws-sse-1',
          paired_credentials: 1,
          drafts: [],
          library: {
            workspace_id: 'ws-sse-1',
            requested_workspace_id: 'ws-sse-1',
            revision: 'rev-0',
            count: 0,
          },
        }),
      };
      yield {
        event: 'workspace_event',
        data: JSON.stringify({
          seq: 1,
          kind: 'draft_queued',
          workspace_id: 'ws-sse-1',
          drafts: [
            {
              id: 'draft-rt-1',
              workspace_id: 'ws-sse-1',
              text: 'Explain the key invariant',
              url: 'https://example.com/article',
              title: 'Article',
              selection: 'invariant',
            },
          ],
        }),
      };
      yield {
        event: 'workspace_event',
        data: JSON.stringify({
          seq: 2,
          kind: 'library_changed',
          workspace_id: 'ws-sse-1',
          library: {
            workspace_id: 'ws-sse-1',
            requested_workspace_id: 'ws-sse-1',
            revision: 'rev-1',
            count: 1,
          },
        }),
      };
      await Promise.race([
        keepStreamOpen,
        new Promise((resolve) => options?.signal?.addEventListener('abort', resolve, { once: true })),
      ]);
    },
  });
  eventsRef = eventStream;

  draftsPoller.start();
  libraryPoller.start();
  eventStream.start();

  await new Promise((resolve) => setTimeout(resolve, 40));

  assert.equal(eventStream.connected, true);
  assert.deepEqual(deliveredDraftIds, ['draft-rt-1']);
  assert.deepEqual(ackedBatches, [{ workspaceId: 'ws-sse-1', ids: ['draft-rt-1'] }]);
  assert.deepEqual(refreshedLibraryRevisions, ['rev-0', 'rev-1']);

  draftTimerTick();
  libraryTimerTick();
  await new Promise((resolve) => setTimeout(resolve, 15));
  assert.equal(draftHttpCalls, 0, 'Draft HTTP polling must stay completely idle while SSE stream is connected');
  assert.equal(libraryHttpCalls, 0, 'Library HTTP polling must stay completely idle while SSE stream is connected');

  visible = false;
  eventStream.wake();
  releaseStream();
  await new Promise((resolve) => setTimeout(resolve, 15));
  assert.equal(eventStream.connected, false);

  eventStream.dispose();
  draftsPoller.dispose();
  libraryPoller.dispose();
});

test('Commands catalog, 8-locale host copy, and CoachSettingsView expose one-click launch and zero-code install', () => {
  assert.equal(commandsMod.trainerCommands.launchBrowserCapture, 'trainer.browserCapture.launch');
  for (const lang of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const launchText = hostCopyMod.browserCaptureHostCopy(lang, 'launchBrowserDone', { browser: 'DemoBrowser' });
    assert.ok(launchText.includes('DemoBrowser'), `Missing launchBrowserDone for ${lang}`);
  }
  const settingsSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'settings', 'CoachSettingsView.tsx'),
    'utf8',
  );
  assert.ok(settingsSource.includes('trainerCommands.launchBrowserCapture'));
  assert.ok(settingsSource.includes('trainerCommands.installBrowserCaptureForBrowser'));
});
