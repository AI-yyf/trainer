'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { load } = require('./templateAssertions');
const { remoteVerificationEventMatchesDisplayedCard } = load('lib/remoteVerificationIdentity.ts');

test('remote results can appear only on their authoritative displayed card', () => {
  assert.equal(remoteVerificationEventMatchesDisplayedCard('live-card', 'live-card'), true);
  assert.equal(remoteVerificationEventMatchesDisplayedCard(' live-card ', 'live-card'), true);
  assert.equal(remoteVerificationEventMatchesDisplayedCard('old-live-formal-card', 'restored-scenario'), false);
  assert.equal(remoteVerificationEventMatchesDisplayedCard('card-A', 'card-a'), false);
});

test('unbound or blank frames cannot claim a displayed-card verification result', () => {
  for (const eventId of [undefined, '', '   ']) {
    for (const displayedId of [undefined, '', '   ', 'displayed-card']) {
      assert.equal(remoteVerificationEventMatchesDisplayedCard(eventId, displayedId), false);
    }
  }
  assert.equal(remoteVerificationEventMatchesDisplayedCard('host-card', undefined), false);
});

test('switching displayed cards hides an old run without changing host evidence truth', () => {
  const frame = { cardId: 'card-A', state: 'completed', passed: true, attestation: 'delivered' };
  const original = structuredClone(frame);
  assert.equal(remoteVerificationEventMatchesDisplayedCard(frame.cardId, 'card-B'), false);
  assert.deepEqual(frame, original);
  assert.equal(remoteVerificationEventMatchesDisplayedCard(frame.cardId, 'card-A'), true);
});
