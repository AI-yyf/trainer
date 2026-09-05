'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  clearHostLastTest,
  selectHostLastTest,
  stripHostLastTestSecrets,
  writeHostLastTest,
} = require('../dist/shared/src/hostLastTestGovernance.js');

const fingerprint = 'openai_chat_completions_compatible::minimax::http://example.test/v1::minimax-m2.7::ref';

function lastTest(overrides = {}) {
  return {
    ok: true,
    status: 'connected',
    detail: 'Provider reachable.',
    checkedAt: '2026-08-25T00:00:00.000Z',
    providerName: 'minimax',
    baseUrl: 'http://example.test/v1',
    model: 'MiniMax-M2.7',
    ...overrides,
  };
}

test('workspace switch does not treat previous host last-test as current', () => {
  const store = {};
  writeHostLastTest(store, { workspaceId: 'workspace-a', providerProfileId: 'profile-a' }, fingerprint, lastTest());
  assert.equal(
    selectHostLastTest(store, { workspaceId: 'workspace-b', providerProfileId: 'profile-a' }, fingerprint),
    undefined,
  );
  assert.equal(
    selectHostLastTest(store, { workspaceId: 'workspace-a', providerProfileId: 'profile-a' }, fingerprint)?.ok,
    true,
  );
});

test('provider switch does not treat previous host last-test as current', () => {
  const store = {};
  writeHostLastTest(store, { workspaceId: 'workspace-shared', providerProfileId: 'profile-a' }, fingerprint, lastTest());
  assert.equal(
    selectHostLastTest(store, { workspaceId: 'workspace-shared', providerProfileId: 'profile-b' }, fingerprint),
    undefined,
  );
  assert.equal(
    selectHostLastTest(store, { workspaceId: 'workspace-shared', providerProfileId: 'profile-a' }, fingerprint)?.profileId,
    'profile-a',
  );
});

test('legacy fingerprint leftover without scope is not current after a switch', () => {
  const store = {
    [fingerprint]: lastTest({ apiKey: 'should-never-survive' }),
  };
  assert.equal(
    selectHostLastTest(store, { workspaceId: 'workspace-b', providerProfileId: 'profile-b' }, fingerprint),
    undefined,
  );
  assert.equal('apiKey' in stripHostLastTestSecrets(store[fingerprint]), false);
});

test('provider snapshot strip removes raw apiKey from view and nested last-test', () => {
  const {
    stripProviderSnapshotSecrets,
  } = require('../dist/shared/src/hostLastTestGovernance.js');
  const cleaned = stripProviderSnapshotSecrets({
    name: 'MiniMax',
    apiKey: 'should-never-persist-in-snapshot',
    api_key: 'should-never-persist-snake',
    lastTestResult: lastTest({ apiKey: 'should-never-survive-nested' }),
  });
  assert.equal('apiKey' in cleaned, false);
  assert.equal('api_key' in cleaned, false);
  assert.equal('apiKey' in (cleaned.lastTestResult ?? {}), false);
  assert.equal(cleaned.name, 'MiniMax');
});

test('last-test detail key-shaped strings are redacted on write and select', () => {
  const FAKE_KEY = 'sk-test-not-a-real-key-aaaaaaaa';
  const FAKE_BEARER = 'Bearer fake-token-zzzzzzzzzzzz';
  const store = {};
  writeHostLastTest(
    store,
    { workspaceId: 'workspace-a', providerProfileId: 'profile-a' },
    fingerprint,
    lastTest({
      ok: false,
      status: 'failed',
      detail: `Upstream rejected key ${FAKE_KEY} with ${FAKE_BEARER}`,
      message: `api_key=${FAKE_KEY}`,
    }),
  );
  const stored = selectHostLastTest(
    store,
    { workspaceId: 'workspace-a', providerProfileId: 'profile-a' },
    fingerprint,
  );
  assert.ok(stored);
  assert.doesNotMatch(String(stored.detail ?? ''), /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(String(stored.detail ?? ''), /fake-token-zzzzzzzzzzzz/);
  assert.doesNotMatch(String(stored.message ?? ''), /sk-test-not-a-real-key-aaaaaaaa/);
  assert.match(JSON.stringify(stored), /redacted/i);

  const stripped = stripHostLastTestSecrets(
    lastTest({
      detail: `Authorization failed for ${FAKE_KEY}`,
    }),
  );
  assert.doesNotMatch(String(stripped.detail ?? ''), /sk-test-not-a-real-key-aaaaaaaa/);
});

test('writing a failed last-test does not invent success', () => {
  const store = {};
  writeHostLastTest(
    store,
    { workspaceId: 'workspace-a', providerProfileId: 'profile-a' },
    fingerprint,
    lastTest(),
  );
  writeHostLastTest(
    store,
    { workspaceId: 'workspace-a', providerProfileId: 'profile-a' },
    fingerprint,
    lastTest({ ok: false, status: 'failed', detail: 'Provider test failed.' }),
  );
  const stored = selectHostLastTest(
    store,
    { workspaceId: 'workspace-a', providerProfileId: 'profile-a' },
    fingerprint,
  );
  assert.equal(stored?.ok, false);
  assert.equal(stored?.status, 'failed');
});

test('clear removes only the scoped host last-test', () => {
  const store = {};
  writeHostLastTest(store, { workspaceId: 'workspace-a', providerProfileId: 'profile-a' }, fingerprint, lastTest());
  writeHostLastTest(store, { workspaceId: 'workspace-b', providerProfileId: 'profile-a' }, fingerprint, lastTest({ detail: 'B' }));
  clearHostLastTest(store, { workspaceId: 'workspace-a', providerProfileId: 'profile-a' }, fingerprint);
  assert.equal(
    selectHostLastTest(store, { workspaceId: 'workspace-a', providerProfileId: 'profile-a' }, fingerprint),
    undefined,
  );
  assert.equal(
    selectHostLastTest(store, { workspaceId: 'workspace-b', providerProfileId: 'profile-a' }, fingerprint)?.detail,
    'B',
  );
});
