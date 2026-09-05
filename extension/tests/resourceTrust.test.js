'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const compiledRoot = process.env.TRAINER_EXTENSION_DIST_ROOT ?? path.resolve(__dirname, '..', 'dist');
const { deriveResourceTrustState } = require(
  path.resolve(compiledRoot, 'shared', 'src', 'resourceTrust.js'),
);

test('deriveResourceTrustState matches the resource training contract', () => {
  assert.equal(
    deriveResourceTrustState({ trustScore: 0.75, freshness: 'fresh', qualityFlags: [] }),
    'trusted',
  );
  assert.equal(
    deriveResourceTrustState({ trustScore: 0.75, freshness: 'fresh', qualityFlags: ['  '] }),
    'trusted',
  );
  assert.equal(
    deriveResourceTrustState({ trustScore: 0.95, freshness: 'fresh', qualityFlags: ['thin_content'] }),
    'unknown',
  );
  assert.equal(
    deriveResourceTrustState({ trustScore: 0.95, freshness: 'stale', qualityFlags: [] }),
    'stale',
  );
  assert.equal(
    deriveResourceTrustState({ trustScore: 0.95, freshness: 'fresh', qualityFlags: ['blocked_source'] }),
    'untrusted',
  );
});
