// Restored behavioral regression test. Original file: extension/tests/browserCaptureShared.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Browser-capture shared module: URL normalization, pairing, queue, payloads, localization, and the compiled host copy.
//
// Restoration: partial - 59 of 76 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "the host copy source declares the eight-language table and the pinned English guide"
//       source-text guard: reads extension/src/browserCapture/hostCopy.ts and asserts on its text (out
//       of scope by rule).
//   - "host copy resolves the eight languages by prefix with an en-US fallback"
//       contains a t.skip() build-artifact guard ("compiled hostCopy.js is absent"); the current suite
//       carries no skip markers, so the skip-marker rule excludes it although it passes when dist is
//       built.
//   - "the host copy table covers every key in all eight languages"
//       contains a t.skip() build-artifact guard ("compiled hostCopy.js is absent"); the current suite
//       carries no skip markers, so the skip-marker rule excludes it although it passes when dist is
//       built.
//   - "host copy formats placeholders and keeps the pinned English values"
//       contains a t.skip() build-artifact guard ("compiled hostCopy.js is absent"); the current suite
//       carries no skip markers, so the skip-marker rule excludes it although it passes when dist is
//       built.
//   - "popup actually hides inactive panels and refreshes the library count after capture"
//       source-text guard: reads browser-extension/popup/popup.css and popup.js and asserts on its text
//       (out of scope by rule).
//   - "the popup connects by itself and pairs with a code only when Trainer asks for one"
//       source-text guard: reads browser-extension/popup and background.js and asserts on its text (out
//       of scope by rule). Fails at HEAD: input expected not to match /trainer:auto-pair/.
//   - "every data-copy key used by the popup exists in the copy map"
//       source-text guard: reads browser-extension/popup/popup.html and asserts on its text (out of
//       scope by rule).
//   - "every id the popup script looks up exists in the popup markup"
//       source-text guard: reads browser-extension/popup/popup.html and popup.js and asserts on its text
//       (out of scope by rule).
//   - "the popup is a monochrome icon-led card (no legacy brand chrome)"
//       source-text guard: reads browser-extension/popup/popup.css and popup.html and asserts on its
//       text (out of scope by rule).
//   - "the worker registers the PDF and GitHub download menu entries"
//       source-text guard: reads browser-extension/background.js and asserts on its text (out of scope
//       by rule).
//   - "the manifest advertises the regenerated PNG icon set"
//       asset/manifest guard: inspects browser-extension/manifest.json and PNG icon headers.
//   - "the manifest localizes its own name/description for all eight languages"
//       data guard over browser-extension/manifest.json and _locales message files (not extension-host
//       behaviour).
//   - "the packaged bundle covers every file the manifest references"
//       packaging guard: reads scripts/package-browser-extension.mjs and the staged browser-capture
//       bundle.
//   - "T-0030: capture enqueue persists inside the queue-mutation critical section"
//       source-text guard: reads browser-extension/background.js and asserts on its text (out of scope
//       by rule).
//   - "T-0041: every background queue writer runs inside the queue lock"
//       source-text guard: reads browser-extension/background.js and asserts on its text (out of scope
//       by rule).
//   - "stale-credential recovery keeps the base URL and does not silently pair a sibling window"
//       source-text guard: reads browser-extension/background.js and shared.js and asserts on its text
//       (out of scope by rule).
//   - "the sidecar that asked for a pairing code is remembered across worker restarts"
//       source-text guard: reads browser-extension/background.js and asserts on its text (out of scope
//       by rule).
// Target: browser-capture shared module (browser-extension/shared.js) and compiled extension/dist host copy.

'use strict';

/**
 * Pure-logic tests for the Trainer Capture browser extension.
 *
 * browser-extension/shared.js is deliberately chrome-free in its pure section,
 * so it can be required here in plain Node. Everything asserted below is the
 * client half of the capture contract: URL normalization, dedup keys, queue
 * operations, probe candidates, payload shapes, deep links and the copy map
 * (all eight languages: zh, en, es, fr, de, ja, ko, pt).
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const TrainerCapture = require(path.resolve(__dirname, '..', '..', 'browser-extension', 'shared.js'));

const SUPPORTED_LOCALES = ['zh', 'en', 'es', 'fr', 'de', 'ja', 'ko', 'pt'];

const HOST_COPY_SOURCE_PATH = path.resolve(__dirname, '..', 'src', 'browserCapture', 'hostCopy.ts');
const HOST_COPY_MODULE_PATH = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'browserCapture',
  'hostCopy.js'
);

// The compiled host copy module is only required when the extension build has
// run (the other browserCapture tests load dist/ the same way); the source-text
// guard below always runs.
function loadHostCopyModule() {
  try {
    return require(HOST_COPY_MODULE_PATH);
  } catch {
    return null;
  }
}

const hostCopyModule = loadHostCopyModule();

test('shared module loads without chrome and exposes the pure API', () => {
  assert.equal(typeof TrainerCapture.normalizeCaptureUrl, 'function');
  assert.equal(typeof TrainerCapture.enqueueCapture, 'function');
  assert.equal(typeof TrainerCapture.buildProbeCandidates, 'function');
  assert.equal(typeof TrainerCapture.copyFor, 'function');
  assert.ok(Array.isArray(TrainerCapture.buildProbeCandidates({})));
});

test('normalizeCaptureUrl strips tracking parameters, hash and trailing slash', () => {
  assert.equal(
    TrainerCapture.normalizeCaptureUrl('https://Example.com/Path/?utm_source=news&utm_medium=x&id=7#section'),
    'https://example.com/Path?id=7'
  );
  assert.equal(
    TrainerCapture.normalizeCaptureUrl('https://example.com/post/?fbclid=abc&gclid=def'),
    'https://example.com/post'
  );
  assert.equal(TrainerCapture.normalizeCaptureUrl('https://example.com/a//'), 'https://example.com/a');
  assert.equal(TrainerCapture.normalizeCaptureUrl('https://example.com'), 'https://example.com/');
  assert.equal(TrainerCapture.normalizeCaptureUrl('https://example.com:443/a/'), 'https://example.com/a');
  assert.equal(TrainerCapture.normalizeCaptureUrl('http://example.com:80/'), 'http://example.com/');
  assert.equal(
    TrainerCapture.normalizeCaptureUrl('https://example.com/p?ref=hn&mc_cid=1'),
    'https://example.com/p?ref=hn'
  );
  assert.equal(
    TrainerCapture.normalizeCaptureUrl('https://example.com/p?q=Hello%20World'),
    'https://example.com/p?q=Hello+World'
  );
});

test('normalizeCaptureUrl rejects non-http sources and malformed input', () => {
  assert.equal(TrainerCapture.normalizeCaptureUrl('chrome://extensions'), '');
  assert.equal(TrainerCapture.normalizeCaptureUrl('file:///tmp/paper.pdf'), '');
  assert.equal(TrainerCapture.normalizeCaptureUrl('not a url'), '');
  assert.equal(TrainerCapture.normalizeCaptureUrl(''), '');
  assert.equal(TrainerCapture.normalizeCaptureUrl(null), '');
  assert.equal(TrainerCapture.normalizeCaptureUrl('mailto:someone@example.com'), '');
});

test('isTrackingParam recognizes utm variants and known click ids', () => {
  assert.equal(TrainerCapture.isTrackingParam('utm_campaign'), true);
  assert.equal(TrainerCapture.isTrackingParam('UTM_Source'), true);
  assert.equal(TrainerCapture.isTrackingParam('fbclid'), true);
  assert.equal(TrainerCapture.isTrackingParam('mc_eid'), true);
  assert.equal(TrainerCapture.isTrackingParam('id'), false);
  assert.equal(TrainerCapture.isTrackingParam('referrer'), false);
  assert.equal(TrainerCapture.isTrackingParam(''), false);
});

test('buildDedupKey collapses cosmetic URL variants', () => {
  const base = TrainerCapture.buildDedupKey({ url: 'https://example.com/p?a=1&b=2', kind: 'web' });
  assert.ok(base.startsWith('web|base|'));
  assert.equal(base, TrainerCapture.buildDedupKey({ url: 'https://example.com/p?b=2&a=1', kind: 'web' }));
  assert.equal(
    base,
    TrainerCapture.buildDedupKey({ url: 'https://EXAMPLE.com/p/?a=1&b=2&utm_source=x#top', kind: 'web' })
  );
});

test('buildDedupKey separates kinds and GitHub capture variants', () => {
  const readme = TrainerCapture.buildDedupKey({ url: 'https://github.com/acme/tool', kind: 'github_repo' });
  const docs = TrainerCapture.buildDedupKey({
    url: 'https://github.com/acme/tool',
    kind: 'github_repo',
    includeDocs: true
  });
  assert.notEqual(readme, docs);
  assert.ok(docs.includes('|docs|'));
  assert.ok(readme.includes('|base|'));
  assert.notEqual(readme, TrainerCapture.buildDedupKey({ url: 'https://github.com/acme/tool', kind: 'web' }));
  assert.equal(TrainerCapture.buildDedupKey({ url: 'chrome://x', kind: 'web' }), '');
});

test('detectKind classifies PDFs, GitHub repositories and plain pages', () => {
  assert.equal(TrainerCapture.detectKind('https://example.com/paper.pdf'), 'pdf');
  assert.equal(TrainerCapture.detectKind('https://example.com/paper.PDF?download=1'), 'pdf');
  assert.equal(TrainerCapture.detectKind('https://arxiv.org/pdf/2407.17032v3#page=5'), 'pdf');
  assert.equal(TrainerCapture.detectKind('https://arxiv.org/abs/2407.17032v3'), 'web');
  assert.equal(TrainerCapture.detectKind('https://arxiv.org.example.com/pdf/2407.17032v3'), 'web');
  assert.equal(TrainerCapture.detectKind('https://example.com/docs'), 'web');
  assert.equal(TrainerCapture.detectKind('https://github.com/acme/tool'), 'github_repo');
  assert.equal(TrainerCapture.detectKind('https://www.github.com/acme/tool.git'), 'github_repo');
  // A deep GitHub page is a page capture; only the repository root is a repo capture.
  assert.equal(TrainerCapture.detectKind('https://github.com/acme/tool/tree/main/src'), 'web');
  assert.equal(TrainerCapture.detectKind('https://github.com/acme/tool/blob/main/README.md'), 'web');
  assert.equal(TrainerCapture.detectKind('https://github.com/acme/tool/blob/5b6c5280e1e23a6f41b3cdfb297a26e349f6ef73/docs/guide.py#L20'), 'web');
  assert.equal(TrainerCapture.detectKind('https://github.com/settings/profile'), 'web');
  assert.equal(TrainerCapture.detectKind('https://github.com/marketplace/actions/checkout'), 'web');
});

test('githubRepoLabel extracts owner/repo and rejects reserved paths', () => {
  assert.equal(TrainerCapture.githubRepoLabel('https://github.com/acme/tool'), 'acme/tool');
  assert.equal(TrainerCapture.githubRepoLabel('https://github.com/acme/tool.git'), 'acme/tool');
  assert.equal(TrainerCapture.githubRepoLabel('https://github.com/acme/tool?tab=readme'), 'acme/tool');
  assert.equal(TrainerCapture.githubRepoLabel('https://github.com/explore'), null);
  assert.equal(TrainerCapture.githubRepoLabel('https://gitlab.com/acme/tool'), null);
  assert.equal(TrainerCapture.githubRepoLabel(''), null);
});

test('normalizeCaptureUrl output is stable for capture-payload use', () => {
  const url = TrainerCapture.normalizeCaptureUrl('https://example.com/p/?utm_term=a#x');
  assert.equal(url, 'https://example.com/p');
  assert.equal(TrainerCapture.normalizeCaptureUrl(url), url);
});

test('normalizePairCode accepts human-typed six-digit codes', () => {
  assert.equal(TrainerCapture.normalizePairCode('123456'), '123456');
  assert.equal(TrainerCapture.normalizePairCode('123 456'), '123456');
  assert.equal(TrainerCapture.normalizePairCode('12-34-56'), '123456');
  assert.equal(TrainerCapture.normalizePairCode(' 123456 '), '123456');
  assert.equal(TrainerCapture.normalizePairCode('12345'), '');
  assert.equal(TrainerCapture.normalizePairCode('1234567'), '');
  assert.equal(TrainerCapture.normalizePairCode('abcdef'), '');
  assert.equal(TrainerCapture.isValidPairCode('098765'), true);
  assert.equal(TrainerCapture.isValidPairCode('9876'), false);
});

/** Answer the extension's fetch calls from a script instead of a sidecar. */
async function withScriptedFetch(responses, run) {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const call = { url: String(url), method: String(init.method || 'GET'), body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    const scripted = responses.shift() || { status: 500, body: {} };
    return new Response(JSON.stringify(scripted.body), {
      status: scripted.status,
      headers: { 'Content-Type': 'application/json' }
    });
  };
  try {
    return await run(calls);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test('autoPairSidecar reports a sidecar that is waiting for a one-time pairing code', async () => {
  await withScriptedFetch(
    [
      {
        status: 403,
        body: {
          detail: {
            code: 'extension_not_paired',
            message: 'Pair this browser once with a pairing code from Trainer.'
          }
        }
      }
    ],
    async (calls) => {
      const refused = await TrainerCapture.autoPairSidecar('http://127.0.0.1:34891');
      assert.equal(refused.ok, false);
      assert.equal(refused.status, 403);
      assert.equal(refused.code, 'extension_not_paired');
      // The popup offers the pairing form on exactly this flag.
      assert.equal(refused.needsPairing, true);
      assert.deepEqual(calls, [
        { url: 'http://127.0.0.1:34891/browser/auto-pair', method: 'POST', body: {} }
      ]);
    }
  );
});

test('autoPairSidecar does not mistake another refusal for a pairing request', async () => {
  await withScriptedFetch(
    [
      { status: 403, body: { detail: { code: 'loopback_only', message: 'Local only.' } } },
      { status: 403, body: { detail: { code: 'extension_origin_required', message: 'Extension only.' } } }
    ],
    async () => {
      const loopback = await TrainerCapture.autoPairSidecar('http://127.0.0.1:34891');
      assert.equal(loopback.ok, false);
      assert.equal(loopback.needsPairing, false);
      const origin = await TrainerCapture.autoPairSidecar('http://127.0.0.1:34891');
      assert.equal(origin.ok, false);
      assert.equal(origin.needsPairing, false);
    }
  );
});

test('autoPairSidecar connects an extension the sidecar already trusts', async () => {
  await withScriptedFetch(
    [
      {
        status: 200,
        body: { credential: 'trcb_paired', workspace_id: 'ws-1', workspace_name: 'Focus A' }
      }
    ],
    async () => {
      const paired = await TrainerCapture.autoPairSidecar('http://127.0.0.1:34891');
      assert.equal(paired.ok, true);
      assert.equal(paired.credential, 'trcb_paired');
      assert.equal(paired.workspaceName, 'Focus A');
      assert.equal(paired.needsPairing, undefined);
    }
  );
});

test('pairSidecar redeems a code and returns the workspace it belongs to', async () => {
  await withScriptedFetch(
    [
      {
        status: 200,
        body: { credential: 'trcb_once', workspace_id: 'ws-2', workspace_name: 'Focus B' }
      }
    ],
    async (calls) => {
      const paired = await TrainerCapture.pairSidecar('http://127.0.0.1:34891', '12 34 56');
      assert.equal(paired.ok, true);
      assert.equal(paired.credential, 'trcb_once');
      assert.equal(paired.workspaceId, 'ws-2');
      assert.equal(paired.workspaceName, 'Focus B');
      assert.deepEqual(calls, [
        { url: 'http://127.0.0.1:34891/browser/pair', method: 'POST', body: { code: '123456' } }
      ]);
    }
  );
});

test('pairSidecar rejects a code that is not six digits without calling the sidecar', async () => {
  await withScriptedFetch([], async (calls) => {
    const rejected = await TrainerCapture.pairSidecar('http://127.0.0.1:34891', '12345');
    assert.equal(rejected.ok, false);
    assert.equal(rejected.reason, 'invalid_code');
    assert.equal(calls.length, 0);
  });
});

test('buildProbeCandidates probes the default port then the managed range', () => {
  const candidates = TrainerCapture.buildProbeCandidates({});
  assert.equal(candidates[0], 'http://127.0.0.1:8765');
  assert.equal(candidates[1], 'http://127.0.0.1:34891');
  assert.equal(candidates[candidates.length - 1], 'http://127.0.0.1:34911');
  assert.equal(candidates.length, 22);
  assert.equal(new Set(candidates).size, candidates.length);
});

test('discoverSidecar returns every reachable Trainer window, not just the default port', async () => {
  const originalFetch = global.fetch;
  const reachable = new Set(['http://127.0.0.1:8765', 'http://127.0.0.1:34892']);
  global.fetch = async (url) => {
    const baseUrl = String(url).replace(/\/health$/, '');
    if (!reachable.has(baseUrl)) {
      throw new TypeError('connect ECONNREFUSED');
    }
    return new Response(JSON.stringify({ status: 'ok' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  try {
    const discovery = await TrainerCapture.discoverSidecar({});
    assert.equal(discovery.found, true);
    assert.equal(discovery.baseUrl, 'http://127.0.0.1:8765');
    assert.deepEqual(discovery.baseUrls, [
      'http://127.0.0.1:8765',
      'http://127.0.0.1:34892',
    ]);
  } finally {
    global.fetch = originalFetch;
  }
});

test('buildProbeCandidates prefers the stored URL and de-duplicates it', () => {
  const stored = TrainerCapture.buildProbeCandidates({ storedBaseUrl: 'http://127.0.0.1:34899' });
  assert.equal(stored[0], 'http://127.0.0.1:34899');
  assert.equal(stored.length, 22);

  const bare = TrainerCapture.buildProbeCandidates({ storedBaseUrl: '127.0.0.1:34905' });
  assert.equal(bare[0], 'http://127.0.0.1:34905');

  const sameAsDefault = TrainerCapture.buildProbeCandidates({ storedBaseUrl: 'http://127.0.0.1:8765/' });
  assert.equal(sameAsDefault[0], 'http://127.0.0.1:8765');
  assert.equal(sameAsDefault.length, 22);
});

test('buildProbeCandidates supports custom ranges and hosts', () => {
  const custom = TrainerCapture.buildProbeCandidates({
    portStart: 40000,
    portEnd: 40002,
    host: 'localhost'
  });
  assert.deepEqual(custom, [
    'http://127.0.0.1:8765',
    'http://localhost:40000',
    'http://localhost:40001',
    'http://localhost:40002'
  ]);
  const reversed = TrainerCapture.buildProbeCandidates({ portStart: 34893, portEnd: 34891 });
  assert.deepEqual(reversed.slice(1), [
    'http://127.0.0.1:34891',
    'http://127.0.0.1:34892',
    'http://127.0.0.1:34893'
  ]);
  assert.deepEqual(TrainerCapture.buildProbeCandidates({ storedBaseUrl: '', defaultBaseUrl: '' })[0], 'http://127.0.0.1:8765');
});

test('normalizeBaseUrl accepts bare host:port and rejects garbage', () => {
  assert.equal(TrainerCapture.normalizeBaseUrl('127.0.0.1:8765'), 'http://127.0.0.1:8765');
  assert.equal(TrainerCapture.normalizeBaseUrl('http://127.0.0.1:34891/'), 'http://127.0.0.1:34891');
  assert.equal(TrainerCapture.normalizeBaseUrl('  http://127.0.0.1:8765///  '), 'http://127.0.0.1:8765');
  assert.equal(TrainerCapture.normalizeBaseUrl(''), '');
  assert.equal(TrainerCapture.normalizeBaseUrl('http://'), '');
});

test('createClientCaptureId is unique per call and coach drafts use their own prefix', () => {
  const first = TrainerCapture.createClientCaptureId(1700000000000, () => 0.5);
  const second = TrainerCapture.createClientCaptureId(1700000000000, () => 0.5);
  assert.match(first, /^bc-[0-9a-z]+-[0-9a-z]{3}-[0-9a-z]{4}$/);
  assert.notEqual(first, second);
  assert.match(TrainerCapture.createCoachDraftId(1700000000000, () => 0), /^bd-/);
});

test('createQueueItem normalizes fields and fills idempotency defaults', () => {
  const item = TrainerCapture.createQueueItem({
    url: 'https://Example.com/a/?utm_source=x#y',
    kind: 'WEB',
    title: '  Example  ',
    focusId: 'focus-1'
  });
  assert.equal(item.url, 'https://example.com/a');
  assert.equal(item.kind, 'web');
  assert.equal(item.title, 'Example');
  assert.equal(item.focusId, 'focus-1');
  assert.equal(item.includeDocs, false);
  assert.match(item.clientCaptureId, /^bc-/);
  assert.equal(
    item.dedupKey,
    TrainerCapture.buildDedupKey({ url: 'https://example.com/a', kind: 'web', focusId: 'focus-1' })
  );
  assert.equal(item.attempts, 0);
  assert.ok(item.createdAt);
});

test('enqueueCapture is idempotent by client id and dedup key', () => {
  const item = TrainerCapture.createQueueItem({ url: 'https://example.com/a', kind: 'web' });
  const first = TrainerCapture.enqueueCapture([], item);
  assert.equal(first.added, true);
  assert.equal(first.queue.length, 1);

  const sameKey = TrainerCapture.createQueueItem({
    url: 'https://example.com/a?utm_source=newsletter',
    kind: 'web'
  });
  const second = TrainerCapture.enqueueCapture(first.queue, sameKey);
  assert.equal(second.added, false);
  assert.equal(second.queue.length, 1);

  const sameId = TrainerCapture.createQueueItem({ url: 'https://example.com/b', kind: 'web' });
  sameId.clientCaptureId = item.clientCaptureId;
  const third = TrainerCapture.enqueueCapture(first.queue, sameId);
  assert.equal(third.added, false);
  assert.equal(third.queue.length, 1);
});

test('enqueueCapture never silently evicts accepted work; a full queue rejects', () => {
  let queue = [];
  const first = TrainerCapture.enqueueCapture(
    queue,
    TrainerCapture.createQueueItem({ url: 'https://example.com/a', kind: 'web' }),
    2
  );
  assert.equal(first.added, true);
  queue = first.queue;
  const second = TrainerCapture.enqueueCapture(
    queue,
    TrainerCapture.createQueueItem({ url: 'https://example.com/b', kind: 'web' }),
    2
  );
  assert.equal(second.added, true);
  queue = second.queue;

  const overflow = TrainerCapture.enqueueCapture(
    queue,
    TrainerCapture.createQueueItem({ url: 'https://example.com/c', kind: 'web' }),
    2
  );
  // The third capture is refused instead of dropping the oldest accepted task.
  assert.equal(overflow.rejectedFull, true);
  assert.equal(overflow.added, false);
  assert.equal(overflow.dropped.length, 0);
  assert.equal(queue.length, 2);
  assert.equal(queue[0].url, 'https://example.com/a');
  assert.equal(queue[1].url, 'https://example.com/b');
});

test('dequeueCapture and markQueueAttempt operate on client capture ids', () => {
  const item = TrainerCapture.createQueueItem({ url: 'https://example.com/a', kind: 'web' });
  const queue = [item];
  const attempted = TrainerCapture.markQueueAttempt(queue, item.clientCaptureId, 'offline', '2026-10-14T00:00:00.000Z');
  assert.equal(attempted[0].attempts, 1);
  assert.equal(attempted[0].lastError, 'offline');
  assert.equal(attempted[0].lastAttemptAt, '2026-10-14T00:00:00.000Z');
  assert.equal(queue[0].attempts, 0, 'markQueueAttempt must not mutate the input queue');

  const emptied = TrainerCapture.dequeueCapture(attempted, item.clientCaptureId);
  assert.equal(emptied.length, 0);
  assert.equal(TrainerCapture.takeNextQueueItem(emptied), null);
  assert.equal(TrainerCapture.dequeueCapture([item], 'bc-other').length, 1);
});

test('summarizeQueue reports count and the next FIFO item', () => {
  assert.deepEqual(TrainerCapture.summarizeQueue([]), { count: 0, next: null });
  const item = TrainerCapture.createQueueItem({ url: 'https://example.com/a', kind: 'web' });
  assert.deepEqual(TrainerCapture.summarizeQueue([item]), { count: 1, next: item });
  assert.deepEqual(TrainerCapture.summarizeQueue(null), { count: 0, next: null });
});

test('findLocalDuplicate checks the queue first, then successful history', () => {
  const key = TrainerCapture.buildDedupKey({ url: 'https://example.com/a', kind: 'web' });
  const queued = { dedupKey: key, clientCaptureId: 'bc-q' };
  const recorded = { dedupKey: key, clientCaptureId: 'bc-h', status: 'ok', resourceId: 'res-1' };
  const failed = { dedupKey: key, clientCaptureId: 'bc-f', status: 'failed' };

  assert.deepEqual(TrainerCapture.findLocalDuplicate({ queue: [queued], history: [recorded] }, key), {
    where: 'queue',
    entry: queued
  });
  assert.deepEqual(TrainerCapture.findLocalDuplicate({ queue: [], history: [recorded] }, key), {
    where: 'history',
    entry: recorded
  });
  assert.deepEqual(
    TrainerCapture.findLocalDuplicate({ queue: [], history: [{ ...recorded, status: 'duplicated' }] }, key),
    { where: 'history', entry: { ...recorded, status: 'duplicated' } }
  );
  assert.equal(TrainerCapture.findLocalDuplicate({ queue: [], history: [failed] }, key), null);
  assert.equal(TrainerCapture.findLocalDuplicate({ queue: [queued], history: [] }, 'web|base|https://other'), null);
  assert.equal(TrainerCapture.findLocalDuplicate({ queue: [queued], history: [] }, ''), null);
});

test('buildCapturePayload follows the sidecar contract', () => {
  const payload = TrainerCapture.buildCapturePayload({
    url: 'https://Example.com/a/?utm_source=x#y',
    kind: 'pdf',
    clientCaptureId: 'bc-1'
  });
  assert.deepEqual(payload, {
    url: 'https://example.com/a',
    kind: 'pdf',
    client_capture_id: 'bc-1'
  });
  assert.equal('title' in payload, false);
  assert.equal('selection' in payload, false);
  assert.equal('bind_focus_id' in payload, false);
  assert.equal('include_docs' in payload, false);

  const full = TrainerCapture.buildCapturePayload({
    url: 'https://github.com/acme/tool',
    kind: 'github_repo',
    title: ' acme/tool ',
    selection: 'quoted text',
    focusId: 'focus-9',
    includeDocs: true,
    clientCaptureId: 'bc-2'
  });
  assert.deepEqual(full, {
    url: 'https://github.com/acme/tool',
    kind: 'github_repo',
    client_capture_id: 'bc-2',
    title: 'acme/tool',
    selection: 'quoted text',
    bind_focus_id: 'focus-9',
    include_docs: true
  });
});

test('buildCapturePayload never sends include_docs for non-repo kinds', () => {
  const payload = TrainerCapture.buildCapturePayload({
    url: 'https://example.com/a',
    kind: 'web',
    includeDocs: true,
    clientCaptureId: 'bc-3'
  });
  assert.equal('include_docs' in payload, false);
});

test('browser draft payload preserves the source location and retry identity', () => {
  assert.equal(TrainerCapture.buildCoachDraftPayload({ selection: '   ' }), null);
  const payload = TrainerCapture.buildCoachDraftPayload({
    selection: '  explain this closure  ',
    url: 'https://example.com/a/?utm_source=x',
    title: ' Example ',
    clientId: 'bd-1'
  });
  assert.deepEqual(payload, {
    selection: 'explain this closure',
    url: 'https://example.com/a/?utm_source=x',
    title: 'Example',
    client_id: 'bd-1'
  });
  const page = TrainerCapture.buildCoachDraftPayload({ url: 'https://example.com/paper.pdf#page=7' });
  assert.equal(page.selection, '');
  assert.equal(page.url, 'https://example.com/paper.pdf#page=7');
  const generated = TrainerCapture.buildCoachDraftPayload({ selection: 'hi' });
  assert.match(generated.client_id, /^bd-/);
});

test('ask trainer question rides the draft payload and the offline queue item', () => {
  // P4: the learner's typed question travels with the staged page context.
  const payload = TrainerCapture.buildCoachDraftPayload({
    selection: 'Episode boundaries decide reward accumulation.',
    url: 'https://rl.example.com/episodes',
    question: '  解释截断与终止的区别  ',
    clientId: 'ask-1'
  });
  assert.equal(payload.question, '解释截断与终止的区别');

  const capped = TrainerCapture.buildCoachDraftPayload({
    selection: 'long question',
    url: 'https://rl.example.com/second',
    question: '长'.repeat(600)
  });
  assert.equal(capped.question.length, 500);

  // No question: the field stays absent, so the wire shape is unchanged.
  const bare = TrainerCapture.buildCoachDraftPayload({ selection: 'plain', url: 'https://x.example.com' });
  assert.equal('question' in bare, false);

  const queued = TrainerCapture.createDraftQueueItem({
    clientDraftId: 'ask-q-1',
    selection: 'Selection text.',
    url: 'https://rl.example.com/third',
    question: '为什么会这样？',
    sourceKind: 'pdf'
  });
  assert.equal(queued.question, '为什么会这样？');
  assert.equal(queued.sourceKind, 'pdf');
  // P4: PDF and GitHub pages carry their source kind on the wire.
  const pdfPayload = TrainerCapture.buildCoachDraftPayload({
    selection: 'clip saturates',
    url: 'https://papers.example.com/ppo.pdf',
    sourceKind: TrainerCapture.detectKind('https://papers.example.com/ppo.pdf')
  });
  assert.equal(pdfPayload.source_kind, 'pdf');
  const githubPayload = TrainerCapture.buildCoachDraftPayload({
    url: 'https://github.com/example/repo',
    sourceKind: TrainerCapture.detectKind('https://github.com/example/repo')
  });
  assert.equal(githubPayload.source_kind, 'github_repo');
  const webPayload = TrainerCapture.buildCoachDraftPayload({
    selection: 'plain page',
    url: 'https://docs.example.com',
    sourceKind: TrainerCapture.detectKind('https://docs.example.com')
  });
  assert.equal('source_kind' in webPayload, false);
  const queuedBare = TrainerCapture.createDraftQueueItem({
    clientDraftId: 'ask-q-2',
    selection: 'Selection text.'
  });
  assert.equal(queuedBare.question, '');
});

test('buildDeepLink points at the Trainer library route', () => {
  assert.equal(
    TrainerCapture.buildDeepLink('res 1/2'),
    'vscode://local.trainer-extension/library/res%201%2F2'
  );
  assert.equal(TrainerCapture.buildDeepLink('resource-9'), 'vscode://local.trainer-extension/library/resource-9');
  assert.equal(TrainerCapture.buildDeepLink(''), '');
  assert.equal(TrainerCapture.buildDeepLink(null), '');
  assert.equal(TrainerCapture.HOST_DEEP_LINK, 'vscode://local.trainer-extension/');
});

test('normalizeCaptureResponse prefers the server deep link and reads saved_path', () => {
  assert.deepEqual(
    TrainerCapture.normalizeCaptureResponse({
      resource_id: 'res-1',
      deduped: true,
      deep_link: 'vscode://local.trainer-extension/library/res-1?from=server'
    }),
    {
      resourceId: 'res-1',
      deduped: true,
      deepLink: 'vscode://local.trainer-extension/library/res-1?from=server',
      savedPath: ''
    }
  );
  assert.deepEqual(TrainerCapture.normalizeCaptureResponse({ resource_id: 'res-2' }), {
    resourceId: 'res-2',
    deduped: false,
    deepLink: 'vscode://local.trainer-extension/library/res-2',
    savedPath: ''
  });
  assert.deepEqual(TrainerCapture.normalizeCaptureResponse(null), {
    resourceId: '',
    deduped: false,
    deepLink: '',
    savedPath: ''
  });
  assert.deepEqual(
    TrainerCapture.normalizeCaptureResponse({
      resource_id: 'res-3',
      saved_path: 'Trainer Library/paper.pdf',
      deep_link: 'vscode://local.trainer-extension/library/res-3'
    }),
    {
      resourceId: 'res-3',
      deduped: false,
      deepLink: 'vscode://local.trainer-extension/library/res-3',
      savedPath: 'Trainer Library/paper.pdf'
    }
  );
  assert.equal(
    TrainerCapture.normalizeCaptureResponse({ resource_id: 'res-4', savedPath: 'docs/notes.pdf' }).savedPath,
    'docs/notes.pdf',
    'the camelCase alias is accepted too'
  );
});

test('normalizeStatusPayload maps /browser/status and filters bad focus options', () => {
  assert.deepEqual(
    TrainerCapture.normalizeStatusPayload({
      workspace_name: ' Trainer Repo ',
      library_count: 12,
      focus_options: [
        { id: 'f1', label: 'Async Rust' },
        { id: '', label: 'broken' },
        { id: 'f2' },
        { id: 'f3', label: 'FSRS' }
      ]
    }),
    {
      workspaceId: '',
      workspaceName: 'Trainer Repo',
      downloadTarget: '',
      libraryCount: 12,
      focusOptions: [
        { id: 'f1', label: 'Async Rust' },
        { id: 'f3', label: 'FSRS' }
      ]
    }
  );
  assert.deepEqual(TrainerCapture.normalizeStatusPayload(null), {
    workspaceId: '',
    workspaceName: '',
    downloadTarget: '',
    libraryCount: 0,
    focusOptions: []
  });
});

test('normalizeStatusPayload is idempotent so caching cannot strip values', () => {
  const raw = {
    workspace_name: ' Trainer Repo ',
    library_count: 7,
    focus_options: [{ id: 'f1', label: 'Async Rust' }]
  };
  const once = TrainerCapture.normalizeStatusPayload(raw);
  assert.deepEqual(TrainerCapture.normalizeStatusPayload(once), once);
  assert.deepEqual(TrainerCapture.normalizeStatusPayload({ ...once }), once);
});

test('copy resolves eight locales by simple prefix match with an en fallback', () => {
  const cases = [
    ['zh', 'zh'],
    ['zh-CN', 'zh'],
    ['zh-TW', 'zh'],
    ['zh-Hant-HK', 'zh'],
    ['en', 'en'],
    ['en-US', 'en'],
    ['en-GB', 'en'],
    ['es', 'es'],
    ['es-ES', 'es'],
    ['es-419', 'es'],
    ['fr', 'fr'],
    ['fr-FR', 'fr'],
    ['fr-CA', 'fr'],
    ['de', 'de'],
    ['de-DE', 'de'],
    ['de-AT', 'de'],
    ['ja', 'ja'],
    ['ja-JP', 'ja'],
    ['ko', 'ko'],
    ['ko-KR', 'ko'],
    ['pt', 'pt'],
    ['pt-BR', 'pt'],
    ['pt-PT', 'pt']
  ];
  for (const [input, expected] of cases) {
    assert.equal(TrainerCapture.resolveLocale(input), expected, input);
  }
  assert.equal(TrainerCapture.resolveLocale('sv-SE'), 'en');
  assert.equal(TrainerCapture.resolveLocale('xx'), 'en');
  assert.equal(TrainerCapture.resolveLocale(''), 'en');
  assert.equal(TrainerCapture.resolveLocale(null), 'en');
  assert.equal(TrainerCapture.resolveLocale(undefined), 'en');
});

test('resolveLanguageTag maps every locale to a BCP 47 tag for the popup root', () => {
  assert.equal(TrainerCapture.resolveLanguageTag('zh-CN'), 'zh-CN');
  assert.equal(TrainerCapture.resolveLanguageTag('zh-TW'), 'zh-CN');
  assert.equal(TrainerCapture.resolveLanguageTag('en-GB'), 'en');
  assert.equal(TrainerCapture.resolveLanguageTag('es-419'), 'es-ES');
  assert.equal(TrainerCapture.resolveLanguageTag('fr'), 'fr-FR');
  assert.equal(TrainerCapture.resolveLanguageTag('de-DE'), 'de-DE');
  assert.equal(TrainerCapture.resolveLanguageTag('ja-JP'), 'ja-JP');
  assert.equal(TrainerCapture.resolveLanguageTag('ko'), 'ko-KR');
  assert.equal(TrainerCapture.resolveLanguageTag('pt-PT'), 'pt-BR');
  assert.equal(TrainerCapture.resolveLanguageTag('sv-SE'), 'en');
  assert.equal(TrainerCapture.resolveLanguageTag(null), 'en');
});

test('the copy map carries all eight languages with identical key sets', () => {
  assert.deepEqual(Object.keys(TrainerCapture.COPY).sort(), [...SUPPORTED_LOCALES].sort());
  const enKeys = Object.keys(TrainerCapture.COPY.en).sort();
  for (const locale of SUPPORTED_LOCALES) {
    assert.deepEqual(
      Object.keys(TrainerCapture.COPY[locale]).sort(),
      enKeys,
      `${locale} must cover every key`
    );
  }
});

test('every translation is a non-empty string with the same placeholders as English', () => {
  const tokens = (value) => (String(value).match(/\{(\w+)\}/g) || []).sort();
  for (const locale of SUPPORTED_LOCALES) {
    for (const key of Object.keys(TrainerCapture.COPY.en)) {
      const value = TrainerCapture.COPY[locale][key];
      assert.equal(typeof value, 'string', `${locale}.${key} must be a string`);
      assert.ok(value.trim().length > 0, `${locale}.${key} must not be empty`);
      assert.deepEqual(
        tokens(value),
        tokens(TrainerCapture.COPY.en[key]),
        `${locale}.${key} must keep the English placeholders`
      );
    }
  }
});

test('no language leaks another language script (no zh/en fallback mixed in)', () => {
  const cjk = /[\u4e00-\u9fff]/;
  const hangul = /[\uac00-\ud7af]/;
  for (const locale of ['en', 'es', 'fr', 'de', 'ko', 'pt']) {
    for (const [key, value] of Object.entries(TrainerCapture.COPY[locale])) {
      assert.equal(cjk.test(value), false, `${locale}.${key} must not contain CJK text`);
    }
  }
  for (const locale of ['en', 'es', 'fr', 'de', 'ja', 'pt']) {
    for (const [key, value] of Object.entries(TrainerCapture.COPY[locale])) {
      assert.equal(hangul.test(value), false, `${locale}.${key} must not contain Hangul text`);
    }
  }
});

test('copyFor returns the selected language and falls back to English per key', () => {
  assert.equal(TrainerCapture.copyFor('zh-CN').pairAction, '配对');
  assert.equal(TrainerCapture.copyFor('zh-TW').needsPair, '需要先配对');
  assert.equal(TrainerCapture.copyFor('en-US').pairAction, 'Pair');
  assert.equal(TrainerCapture.copyFor('en-GB').pairAction, 'Pair');
  assert.equal(TrainerCapture.copyFor('es-ES').pairAction, 'Emparejar');
  assert.equal(TrainerCapture.copyFor('es-419').pairAction, 'Emparejar');
  assert.equal(TrainerCapture.copyFor('fr-FR').pairAction, 'Associer');
  assert.equal(TrainerCapture.copyFor('de-DE').pairAction, 'Koppeln');
  assert.equal(TrainerCapture.copyFor('ja-JP').pairAction, 'ペアリング');
  assert.equal(TrainerCapture.copyFor('ko-KR').pairAction, '페어링');
  assert.equal(TrainerCapture.copyFor('pt-BR').pairAction, 'Emparelhar');
  assert.equal(TrainerCapture.copyFor('sv-SE').pairAction, 'Pair');
  // A few marker keys per language, to catch copy blocks pasted from English.
  const markers = {
    zh: { pdfButton: '加入 Trainer', menuLink: '加入资料库（链接）', statusOk: '成功' },
    en: { pdfButton: 'Add to Trainer', menuLink: 'Add to library (link)', statusOk: 'Added' },
    es: { pdfButton: 'Añadir a Trainer', menuLink: 'Añadir a la biblioteca (enlace)', statusOk: 'Añadido' },
    fr: { pdfButton: 'Ajouter à Trainer', menuLink: 'Ajouter à la bibliothèque (lien)', statusOk: 'Ajouté' },
    de: { pdfButton: 'Zu Trainer hinzufügen', menuLink: 'Zur Bibliothek hinzufügen (Link)', statusOk: 'Hinzugefügt' },
    ja: { pdfButton: 'Trainer に追加', menuLink: 'ライブラリに追加（リンク）', statusOk: '追加済み' },
    ko: { pdfButton: 'Trainer에 추가', menuLink: '라이브러리에 추가(링크)', statusOk: '추가됨' },
    pt: { pdfButton: 'Adicionar ao Trainer', menuLink: 'Adicionar à biblioteca (link)', statusOk: 'Adicionado' }
  };
  for (const [locale, expected] of Object.entries(markers)) {
    const dict = TrainerCapture.copyFor(locale);
    for (const [key, value] of Object.entries(expected)) {
      assert.equal(dict[key], value, `${locale}.${key}`);
    }
  }
  for (const locale of ['zh', 'es', 'fr', 'de', 'ja', 'ko', 'pt']) {
    assert.notEqual(
      TrainerCapture.COPY[locale].pairAction,
      TrainerCapture.COPY.en.pairAction,
      `${locale} must translate pairAction`
    );
  }
});

test('formatCopy fills placeholders and keeps unknown ones intact', () => {
  assert.equal(TrainerCapture.formatCopy('已投递 {count} 条', { count: 3 }), '已投递 3 条');
  assert.equal(TrainerCapture.formatCopy('Found Trainer at {url}', { url: 'http://127.0.0.1:8765' }), 'Found Trainer at http://127.0.0.1:8765');
  assert.equal(TrainerCapture.formatCopy('value {missing}', {}), 'value {missing}');
  assert.equal(TrainerCapture.formatCopy('plain'), 'plain');
  assert.equal(TrainerCapture.formatCopy(null, {}), '');
});

test('describeHttpError maps sidecar failure codes to localized copy', () => {
  const zh = TrainerCapture.copyFor('zh-CN');
  const en = TrainerCapture.copyFor('en-US');
  assert.equal(TrainerCapture.describeHttpError(401, null, en), en.errUnauthorized);
  assert.equal(TrainerCapture.describeHttpError(403, null, zh), zh.errUnauthorized);
  assert.equal(
    TrainerCapture.describeHttpError(409, { detail: { code: 'network_disabled' } }, en),
    en.errNetworkDisabled
  );
  assert.equal(
    TrainerCapture.describeHttpError(409, { detail: { code: 'browse_only_persistence_blocked' } }, zh),
    zh.errBrowseOnly
  );
  assert.equal(
    TrainerCapture.describeHttpError(404, { detail: { code: 'readme_not_found' } }, en),
    en.errReadmeNotFound
  );
  assert.equal(
    TrainerCapture.describeHttpError(404, { detail: { code: 'readme_not_found', message: 'no README on main' } }, en),
    'no README on main'
  );
  assert.equal(
    TrainerCapture.describeHttpError(422, { detail: 'bad url' }, en),
    'Capture failed (HTTP 422): bad url'
  );
  assert.equal(TrainerCapture.describeHttpError(500, null, en), 'Capture failed: Trainer returned HTTP 500.');
});

test('describeTransportError distinguishes timeouts from unreachable sidecar', () => {
  const zh = TrainerCapture.copyFor('zh');
  assert.equal(TrainerCapture.describeTransportError({ name: 'AbortError' }, zh), zh.errTimeout);
  assert.equal(TrainerCapture.describeTransportError({ name: 'TypeError' }, zh), zh.errUnreachable);
  assert.equal(TrainerCapture.describeTransportError(null, zh), zh.errUnreachable);
});

test('isRetryableStatus only queues transient failures', () => {
  assert.equal(TrainerCapture.isRetryableStatus(0, 'network'), true);
  assert.equal(TrainerCapture.isRetryableStatus(0, 'timeout'), true);
  assert.equal(TrainerCapture.isRetryableStatus(500, ''), true);
  assert.equal(TrainerCapture.isRetryableStatus(503, ''), true);
  assert.equal(TrainerCapture.isRetryableStatus(408, ''), true);
  assert.equal(TrainerCapture.isRetryableStatus(429, ''), true);
  assert.equal(TrainerCapture.isRetryableStatus(409, ''), false);
  assert.equal(TrainerCapture.isRetryableStatus(401, ''), false);
  assert.equal(TrainerCapture.isRetryableStatus(404, ''), false);
});

test('captureLabel prefers the title and falls back to the URL', () => {
  assert.equal(TrainerCapture.captureLabel({ title: ' Async Rust ', url: 'https://example.com' }), 'Async Rust');
  assert.equal(TrainerCapture.captureLabel({ title: '', url: 'https://example.com' }), 'https://example.com');
  assert.equal(TrainerCapture.captureLabel(null), '');
});

test('kindCopyKey and statusCopyKey map to display copy keys', () => {
  assert.equal(TrainerCapture.kindCopyKey('web'), 'kindWeb');
  assert.equal(TrainerCapture.kindCopyKey('pdf'), 'kindPdf');
  assert.equal(TrainerCapture.kindCopyKey('github_repo'), 'kindGithub');
  assert.equal(TrainerCapture.kindCopyKey('other'), 'kindUnknown');
  assert.equal(TrainerCapture.statusCopyKey('ok'), 'statusOk');
  assert.equal(TrainerCapture.statusCopyKey('duplicated'), 'statusDuplicated');
  assert.equal(TrainerCapture.statusCopyKey('queued'), 'statusQueued');
  assert.equal(TrainerCapture.statusCopyKey('failed'), 'statusFailed');
  assert.equal(TrainerCapture.statusCopyKey(''), 'statusFailed');
});

test('formatTimestamp renders local time and rejects invalid values', () => {
  assert.equal(TrainerCapture.formatTimestamp('not-a-date'), '');
  const rendered = TrainerCapture.formatTimestamp('2026-10-14T08:03:00.000Z');
  assert.match(rendered, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
});

test('limits keep the popup list short and the queue bounded', () => {
  assert.equal(TrainerCapture.LIMITS.historyDisplay, 5);
  assert.ok(TrainerCapture.LIMITS.historyStore >= TrainerCapture.LIMITS.historyDisplay);
  assert.ok(TrainerCapture.LIMITS.queue >= 1);
  assert.equal(TrainerCapture.SIDECAR.managedPortStart, 34891);
  assert.equal(TrainerCapture.SIDECAR.managedPortEnd, 34911);
  assert.equal(TrainerCapture.API.pair, '/browser/pair');
  assert.equal(TrainerCapture.API.status, '/browser/status');
  assert.equal(TrainerCapture.API.capture, '/resources/capture');
  assert.equal(TrainerCapture.API.coachDraft, '/browser/coach-draft');
});




// ---------------------------------------------------------------------------
// Download-to-project-folder entries (task 二)
// ---------------------------------------------------------------------------

test('supportsDownload and isDownloadTarget only accept PDF and GitHub sources', () => {
  assert.equal(TrainerCapture.supportsDownload('pdf'), true);
  assert.equal(TrainerCapture.supportsDownload('github_repo'), true);
  assert.equal(TrainerCapture.supportsDownload('web'), false);
  assert.equal(TrainerCapture.supportsDownload(''), false);

  assert.equal(TrainerCapture.isDownloadTarget({ download: true, kind: 'pdf' }), true);
  assert.equal(TrainerCapture.isDownloadTarget({ download: true, kind: 'github_repo' }), true);
  assert.equal(TrainerCapture.isDownloadTarget({ download: true, kind: 'web' }), false);
  assert.equal(TrainerCapture.isDownloadTarget({ download: false, kind: 'pdf' }), false);
  assert.equal(TrainerCapture.isDownloadTarget(null), false);
});

test('normalizeTargetDir keeps project-relative folders and rejects escapes', () => {
  const D = TrainerCapture.DEFAULT_TARGET_DIR;
  assert.equal(D, 'Trainer Library/');

  // Empty input means "the default folder".
  assert.equal(TrainerCapture.normalizeTargetDir(''), D);
  assert.equal(TrainerCapture.normalizeTargetDir('   '), D);
  assert.equal(TrainerCapture.normalizeTargetDir(null), D);
  assert.equal(TrainerCapture.normalizeTargetDir(undefined), D);

  // Normalization: backslashes, redundant slashes and trailing separators.
  assert.equal(TrainerCapture.normalizeTargetDir('Trainer Library'), 'Trainer Library/');
  assert.equal(TrainerCapture.normalizeTargetDir('docs/papers/'), 'docs/papers/');
  assert.equal(TrainerCapture.normalizeTargetDir('/docs//papers/'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('docs\\papers\\'), 'docs/papers/');
  assert.equal(TrainerCapture.normalizeTargetDir('  notes/  '), 'notes/');

  // Anything that could leave the project is invalid, not silently repaired.
  assert.equal(TrainerCapture.normalizeTargetDir('/etc'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('..'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('docs/../../etc'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('.hidden/../up'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('~/Documents'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('C:/Windows'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('C:\\Windows'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('bad:name'), '');

  assert.equal(TrainerCapture.targetDirIsValid(''), true);
  assert.equal(TrainerCapture.targetDirIsValid('   '), true);
  assert.equal(TrainerCapture.targetDirIsValid('Trainer Library/'), true);
  assert.equal(TrainerCapture.targetDirIsValid('docs\\papers'), true);
  assert.equal(TrainerCapture.targetDirIsValid('..'), false);
  assert.equal(TrainerCapture.targetDirIsValid('/abs'), false);
  assert.equal(TrainerCapture.targetDirIsValid('C:/x'), false);
  assert.equal(TrainerCapture.targetDirIsValid('a/../../b'), false);

  // The client mirrors the sidecar's library path rules (server/app/resources/
  // library.py): hidden and reserved segments, depth, and length limits.
  assert.equal(TrainerCapture.normalizeTargetDir('notes'), 'notes/');
  assert.equal(TrainerCapture.normalizeTargetDir('.notes'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('docs/.hidden'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('.git'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('sandbox'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('Inline-Resources'), '', 'reserved names are case-insensitive');
  assert.equal(TrainerCapture.normalizeTargetDir('.trainer'), '');
  assert.equal(TrainerCapture.normalizeTargetDir('a/b/c/d/e/f'), 'a/b/c/d/e/f/');
  assert.equal(TrainerCapture.normalizeTargetDir('a/b/c/d/e/f/g'), '', 'depth is capped at six segments');
  assert.equal(TrainerCapture.normalizeTargetDir('x'.repeat(61)), '', 'a segment is capped at 60 characters');
  assert.equal(TrainerCapture.normalizeTargetDir('ok/' + 'y'.repeat(60)), `ok/${'y'.repeat(60)}/`);
  assert.equal(TrainerCapture.targetDirIsValid('.notes'), false);
  assert.equal(TrainerCapture.targetDirIsValid('ok/' + 'y'.repeat(60)), true);
});

test('buildDedupKey keeps download and library actions apart', () => {
  const url = 'https://example.com/paper.pdf';
  const library = TrainerCapture.buildDedupKey({ url, kind: 'pdf' });
  const download = TrainerCapture.buildDedupKey({ url, kind: 'pdf', download: true });
  const otherFolder = TrainerCapture.buildDedupKey({
    url,
    kind: 'pdf',
    download: true,
    targetDir: 'Papers/'
  });
  const sameFolder = TrainerCapture.buildDedupKey({
    url,
    kind: 'pdf',
    download: true,
    targetDir: 'Papers/'
  });

  assert.ok(library.includes('|base|'));
  assert.ok(download.includes('|download+trainer library/|'));
  assert.notEqual(library, download);
  assert.notEqual(download, otherFolder);
  assert.equal(otherFolder, sameFolder);
  assert.equal(TrainerCapture.buildDedupKey({ url, kind: 'pdf', download: true, targetDir: 'Papers' }), sameFolder);

  // A download flag on a web capture stays a plain library capture.
  assert.equal(
    TrainerCapture.buildDedupKey({ url: 'https://example.com/page', kind: 'web', download: true }),
    TrainerCapture.buildDedupKey({ url: 'https://example.com/page', kind: 'web' })
  );

  // The GitHub docs variant composes with the download variant.
  const docsDownload = TrainerCapture.buildDedupKey({
    url: 'https://github.com/acme/tool',
    kind: 'github_repo',
    includeDocs: true,
    download: true
  });
  assert.ok(docsDownload.startsWith('github_repo|docs+download+'));
});

test('queue items carry the download fields and stay deduplicated per folder', () => {
  const item = TrainerCapture.createQueueItem({
    url: 'https://example.com/paper.pdf',
    kind: 'pdf',
    download: true,
    targetDir: 'Papers/'
  });
  assert.equal(item.download, true);
  assert.equal(item.targetDir, 'Papers/');
  assert.ok(item.dedupKey.includes('|download+papers/|'));

  const defaulted = TrainerCapture.createQueueItem({
    url: 'https://example.com/other.pdf',
    kind: 'pdf',
    download: true
  });
  assert.equal(defaulted.targetDir, TrainerCapture.DEFAULT_TARGET_DIR);

  const plain = TrainerCapture.createQueueItem({ url: 'https://example.com/page', kind: 'web' });
  assert.equal(plain.download, false);
  assert.equal(plain.targetDir, '');

  const webWithFlag = TrainerCapture.createQueueItem({
    url: 'https://example.com/page',
    kind: 'web',
    download: true
  });
  assert.equal(webWithFlag.download, false, 'web captures have no download variant');

  const first = TrainerCapture.enqueueCapture([], item);
  const duplicate = TrainerCapture.enqueueCapture(
    first.queue,
    TrainerCapture.createQueueItem({
      url: 'https://example.com/paper.pdf',
      kind: 'pdf',
      download: true,
      targetDir: 'Papers/'
    })
  );
  assert.equal(duplicate.added, false, 'the same download into the same folder is a duplicate');

  const elsewhere = TrainerCapture.enqueueCapture(
    first.queue,
    TrainerCapture.createQueueItem({
      url: 'https://example.com/paper.pdf',
      kind: 'pdf',
      download: true,
      targetDir: 'Archive/'
    })
  );
  assert.equal(elsewhere.added, true, 'a download into another folder is a new action');
});

test('buildCapturePayload sends download and target_dir only for supported kinds', () => {
  const download = TrainerCapture.buildCapturePayload({
    url: 'https://example.com/paper.pdf',
    kind: 'pdf',
    clientCaptureId: 'bc-1',
    download: true,
    targetDir: 'docs/papers'
  });
  assert.deepEqual(download, {
    url: 'https://example.com/paper.pdf',
    kind: 'pdf',
    client_capture_id: 'bc-1',
    download: true,
    target_dir: 'docs/papers/'
  });

  const defaultDir = TrainerCapture.buildCapturePayload({
    url: 'https://example.com/paper.pdf',
    kind: 'pdf',
    clientCaptureId: 'bc-2',
    download: true
  });
  assert.equal(defaultDir.target_dir, TrainerCapture.DEFAULT_TARGET_DIR);

  const library = TrainerCapture.buildCapturePayload({
    url: 'https://example.com/paper.pdf',
    kind: 'pdf',
    clientCaptureId: 'bc-3'
  });
  assert.equal('download' in library, false);
  assert.equal('target_dir' in library, false);

  const webDownload = TrainerCapture.buildCapturePayload({
    url: 'https://example.com/page',
    kind: 'web',
    clientCaptureId: 'bc-4',
    download: true
  });
  assert.equal('download' in webDownload, false);

  const githubDocsDownload = TrainerCapture.buildCapturePayload({
    url: 'https://github.com/acme/tool',
    kind: 'github_repo',
    clientCaptureId: 'bc-5',
    includeDocs: true,
    download: true,
    targetDir: 'vendor/'
  });
  assert.equal(githubDocsDownload.include_docs, true);
  assert.equal(githubDocsDownload.download, true);
  assert.equal(githubDocsDownload.target_dir, 'vendor/');
});

test('removeQueueItem and clearQueue back the popup queue manager', () => {
  const first = TrainerCapture.createQueueItem({ url: 'https://example.com/a', kind: 'web' });
  const second = TrainerCapture.createQueueItem({ url: 'https://example.com/b', kind: 'pdf' });
  const queue = [first, second];

  assert.deepEqual(
    TrainerCapture.removeQueueItem(queue, first.clientCaptureId).map((entry) => entry.url),
    ['https://example.com/b']
  );
  assert.deepEqual(
    TrainerCapture.removeQueueItem(queue, 'missing').map((entry) => entry.url),
    ['https://example.com/a', 'https://example.com/b']
  );
  assert.equal(queue.length, 2, 'the source queue is never mutated');
  assert.deepEqual(TrainerCapture.clearQueue(), []);
});

test('historySavedPath reads the recorded download path defensively', () => {
  assert.equal(TrainerCapture.historySavedPath({ savedPath: ' Trainer Library/a.pdf ' }), 'Trainer Library/a.pdf');
  assert.equal(TrainerCapture.historySavedPath({}), '');
  assert.equal(TrainerCapture.historySavedPath(null), '');
});

test('every download/offline/queue copy key exists in all eight languages', () => {
  const keys = [
    'menuPdfGroup',
    'menuPdfLibrary',
    'menuPdfDownload',
    'menuGithubDownload',
    'downloadHeading',
    'downloadLabel',
    'downloadAction',
    'downloadBusy',
    'downloadUnsupported',
    'captureDownloaded',
    'captureDownloadedDeduped',
    'captureDownloadQueued',
    'notifyDownloadTitle',
    'savedPathLabel',
    'openInVsCode',
    'statusOffline',
    'statusOfflineDetail',
    'workspaceLabel',
    'queueClear',
    'queueClearConfirm',
    'queueDelete',
    'queueDeleteTitle',
    'queueAttempts'
  ];
  const markers = {
    zh: { menuPdfDownload: '下载 PDF 到资料库', statusOffline: 'Trainer 未运行', queueClear: '清空队列' },
    en: { menuPdfDownload: 'Download PDF to library', statusOffline: 'Trainer is not running', queueClear: 'Clear queue' },
    es: { menuPdfDownload: 'Descargar el PDF a la biblioteca', statusOffline: 'Trainer no está en ejecución', queueClear: 'Vaciar la cola' },
    fr: { menuPdfDownload: 'Télécharger le PDF dans la bibliothèque', statusOffline: 'Trainer n’est pas démarré', queueClear: 'Vider la file' },
    de: { menuPdfDownload: 'PDF in die Bibliothek laden', statusOffline: 'Trainer läuft nicht', queueClear: 'Warteschlange leeren' },
    ja: { menuPdfDownload: 'PDF をライブラリにダウンロード', statusOffline: 'Trainer が起動していません', queueClear: 'キューを空にする' },
    ko: { menuPdfDownload: 'PDF를 라이브러리로 다운로드', statusOffline: 'Trainer가 실행 중이 아닙니다', queueClear: '대기열 비우기' },
    pt: { menuPdfDownload: 'Baixar o PDF para a biblioteca', statusOffline: 'O Trainer não está em execução', queueClear: 'Limpar a fila' }
  };
  // Keys that may legitimately equal English in a given locale: the folder
  // placeholder is a literal path, and pt-BR keeps the webview glossary's
  // "Workspace" (lib/i18n/copy.ts) instead of translating it.
  const englishIdentical = new Set(['pt.workspaceLabel']);
  for (const locale of SUPPORTED_LOCALES) {
    const dict = TrainerCapture.COPY[locale];
    for (const key of keys) {
      assert.equal(typeof dict[key], 'string', `${locale}.${key} must exist`);
      assert.ok(dict[key].trim().length > 0, `${locale}.${key} must not be empty`);
      if (
        locale !== 'en' &&
        !englishIdentical.has(key) &&
        !englishIdentical.has(`${locale}.${key}`)
      ) {
        assert.notEqual(dict[key], TrainerCapture.COPY.en[key], `${locale}.${key} must be translated`);
      }
    }
    for (const [key, value] of Object.entries(markers[locale])) {
      assert.equal(dict[key], value, `${locale}.${key}`);
    }
  }
  // The download folder comes from the sidecar and is always the library
  // root, so the copy map carries no path placeholder.
  assert.equal(TrainerCapture.COPY.en.downloadPlaceholder, undefined);
});

test('queued copy describes an unfinished capture, not an offline Trainer', () => {
  const offlineClaim =
    /not running|未运行|no está en ejecución|n’est pas démarré|läuft nicht|起動していない|실행 중이 아니|não está em execução/i;
  for (const locale of SUPPORTED_LOCALES) {
    for (const key of [
      'captureQueued',
      'captureDownloadQueued',
      'notifyQueuedTitle',
    ]) {
      assert.doesNotMatch(
        TrainerCapture.COPY[locale][key],
        offlineClaim,
        `${locale}.${key} must not claim Trainer is offline; the sidecar may have answered with 5xx`,
      );
    }
  }
});

// ---------------------------------------------------------------------------
// Popup / worker static guards (task 三 and 四)
// ---------------------------------------------------------------------------

const POPUP_HTML_PATH = path.resolve(__dirname, '..', '..', 'browser-extension', 'popup', 'popup.html');
const POPUP_JS_PATH = path.resolve(__dirname, '..', '..', 'browser-extension', 'popup', 'popup.js');
const POPUP_CSS_PATH = path.resolve(__dirname, '..', '..', 'browser-extension', 'popup', 'popup.css');
const BACKGROUND_JS_PATH = path.resolve(__dirname, '..', '..', 'browser-extension', 'background.js');
const MANIFEST_PATH = path.resolve(__dirname, '..', '..', 'browser-extension', 'manifest.json');











test('a stale credential keeps the paired base URL so reconnect hits the same window', async () => {
  const store = {
    'trainerCapture.baseUrl': 'http://127.0.0.1:34892',
    'trainerCapture.credential': 'trcb_stale_token',
    'trainerCapture.connection': 'ok',
    'trainerCapture.statusCache': { libraryCount: 3 },
    'trainerCapture.workspaceId': 'browser-capture-e2e',
  };
  global.chrome = {
    storage: {
      local: {
        async get(defaults) {
          const result = {};
          for (const [key, fallback] of Object.entries(defaults || {})) {
            result[key] = Object.prototype.hasOwnProperty.call(store, key) ? store[key] : fallback;
          }
          return result;
        },
        async remove(keys) {
          for (const key of keys) delete store[key];
        },
        async set(values) {
          Object.assign(store, values);
        },
      },
    },
  };
  try {
    await TrainerCapture.clearStaleCredential();
  } finally {
    delete global.chrome;
  }
  assert.equal(store['trainerCapture.baseUrl'], 'http://127.0.0.1:34892');
  assert.equal(store['trainerCapture.workspaceId'], 'browser-capture-e2e');
  assert.equal(store['trainerCapture.credential'], undefined);
  assert.equal(store['trainerCapture.connection'], undefined);
  assert.equal(store['trainerCapture.statusCache'], undefined);
});

