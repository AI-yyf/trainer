'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const sharedResourceSearchModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'resourceSearch.js',
);

test('formatSearchHitTeachingSummary includes rank score and match summary when present', () => {
  const { formatSearchHitTeachingSummary, summarizeSearchHitTeachingSignal } = require(
    sharedResourceSearchModulePath,
  );

  const summary = summarizeSearchHitTeachingSignal({
    title: 'Notes',
    source: 'F:\\trainer\\notes.md',
    project_scope: 'workspace-a',
    source_type: 'workspace-folder',
    index_state: 'indexed',
    trust_state: 'trusted',
    trust_score: 0.9,
    freshness: 'fresh',
    preview_tier: 'metadata',
    preview_kind: 'archive',
    citation_id: 'citation:resource-1',
    rank_score: 1.23,
    match_summary: 'matched title and freshness signals',
    matched_fields: ['title', 'freshness', 'path'],
    can_inject_training_card: true,
    rank_reasons: ['title match', 'freshness fresh'],
  });

  assert.deepEqual(summary, {
    title: 'Notes',
    source: 'F:\\trainer\\notes.md',
    projectScope: 'workspace-a',
    sourceType: 'workspace-folder',
    indexState: 'indexed',
    trustState: 'trusted',
    trustScore: 0.9,
    freshness: 'fresh',
    previewTier: 'metadata',
    previewKind: 'archive',
    citationId: 'citation:resource-1',
    rankScore: 1.23,
    matchSummary: 'matched title and freshness signals',
    matchedFields: ['title', 'freshness', 'path'],
    canInjectTrainingCard: true,
    reasons: ['title match', 'freshness fresh'],
  });

  const rendered = formatSearchHitTeachingSummary(summary, 'en');
  assert.match(rendered, /^Top hit: Notes \[source F:\\trainer\\notes\.md .+ project workspace-a/);
  assert.match(rendered, /preview Tier C .+ Archive/);
  assert.match(rendered, /rank 1\.23/);
  assert.match(rendered, /injectable training card/);
  assert.match(rendered, /match summary: matched title and freshness signals/);
  assert.match(rendered, /reasons: title match, freshness fresh/);
});

test('resource search modes only advertise executable search behavior', () => {
  const {
    formatResourceSearchStatusSummary,
    normalizeResourceSearchMode,
    resourceSearchModeRequest,
    resourceSearchModeLabel,
    resourceSearchModeHint,
  } = require(sharedResourceSearchModulePath);

  const status = formatResourceSearchStatusSummary(
    {
      hitCount: 3,
      mode: 'lexical',
      topHit: {
        title: 'Notes',
        source: 'F:\\trainer\\notes.md',
        project_scope: 'workspace-a',
        source_type: 'workspace-folder',
        index_state: 'indexed',
        trust_state: 'trusted',
        trust_score: 0.9,
        freshness: 'fresh',
        preview_tier: 'converted',
        preview_kind: 'document',
        citation_id: 'citation:resource-1',
        matched_fields: ['title', 'freshness'],
        can_inject_training_card: true,
        rank_reasons: ['title match', 'freshness fresh'],
      },
    },
    'en',
  );

  assert.match(status, /^3 full-text hits .+ Full-text search .+ Top hit: Notes/);
  assert.match(status, /injectable training card/);
  assert.doesNotMatch(status, /Coach rerank|backend hits/);

  assert.equal(normalizeResourceSearchMode('lexical'), 'lexical');
  assert.equal(normalizeResourceSearchMode('trusted'), 'trusted');
  assert.equal(normalizeResourceSearchMode('semantic'), 'lexical');
  assert.equal(normalizeResourceSearchMode('coach'), 'lexical');
  assert.equal(normalizeResourceSearchMode('unknown'), 'lexical');
  assert.deepEqual(resourceSearchModeRequest('lexical'), {});
  assert.deepEqual(resourceSearchModeRequest('trusted'), {
    trustState: 'trusted',
    indexState: 'indexed',
  });
  assert.equal(resourceSearchModeLabel('lexical', 'en'), 'Full-text search');
  assert.equal(resourceSearchModeLabel('trusted', 'en'), 'Trusted and indexed');
  assert.match(resourceSearchModeHint('lexical', 'en'), /indexed resource text/i);
  assert.match(resourceSearchModeHint('trusted', 'en'), /indexed and marked trusted/i);
  assert.ok(resourceSearchModeLabel('trusted', 'zh').trim());
  assert.ok(resourceSearchModeHint('trusted', 'zh').trim());
});
