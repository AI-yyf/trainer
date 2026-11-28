// Restored behavioral regression test. Original file: extension/tests/resourceSearchTeachingSummaryExtra.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: formatSearchHitTeachingSummary with rank score and match summary.
//
// Restoration: partial - 1 of 2 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "resource search modes only advertise executable search behavior"
//       fails at HEAD: formatResourceSearchStatusSummary is not a function
// Target: compiled shared modules (extension/dist/shared/src).

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
    versionId: undefined,
    contentHash: undefined,
    location: { path: 'F:\\trainer\\notes.md' },
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
