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

test('formatSearchHitTeachingSummary summarizes the training signal for ranked hits', async () => {
  const { formatSearchHitTeachingSummary, summarizeSearchHitTeachingSignal } = require(
    sharedResourceSearchModulePath,
  );

  const summary = summarizeSearchHitTeachingSignal({
    title: 'Notes',
    source: 'F:\\trainer\\notes.md',
    project_scope: 'workspace-a',
    trust_state: 'trusted',
    trust_score: 0.9,
    freshness: 'fresh',
    preview_tier: 'converted',
    preview_kind: 'document',
    citation_id: 'citation:resource-1',
    can_inject_training_card: true,
    rank_reasons: ['title match', 'freshness fresh'],
  });

  assert.deepEqual(summary, {
    title: 'Notes',
    source: 'F:\\trainer\\notes.md',
    projectScope: 'workspace-a',
    sourceType: undefined,
    indexState: undefined,
    trustState: 'trusted',
    trustScore: 0.9,
    freshness: 'fresh',
    previewTier: 'converted',
    previewKind: 'document',
    citationId: 'citation:resource-1',
    rankScore: undefined,
    matchSummary: undefined,
    matchedFields: undefined,
    canInjectTrainingCard: true,
    reasons: ['title match', 'freshness fresh'],
  });

  assert.equal(
    formatSearchHitTeachingSummary(summary, 'en'),
    'Top hit: Notes [source F:\\trainer\\notes.md · project workspace-a · trust trusted 90% · freshness fresh · preview Tier B · Document · citation citation:resource-1 · injectable training card]; reasons: title match, freshness fresh',
  );
});
