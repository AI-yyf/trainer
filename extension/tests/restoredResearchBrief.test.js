// Restored behavioral regression test. Original file: extension/tests/researchBrief.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Research brief: a brief uses the sources of its own reply; citation body lines resolve through Markdown front matter.
//
// Restoration: whole - all 2 original test definitions, code and assertions unchanged.
// Target: shared/src/researchBrief.ts bundled in memory with esbuild (templateAssertions.load).

const assert = require('node:assert/strict');
const test = require('node:test');
const { load } = require('./templateAssertions');

const { researchBriefResourceIds, resolveResearchCitationLine } = load('../../../shared/src/researchBrief.ts');

test('a brief uses the sources of its own reply', () => {
  const sourceResourceIds = ['attached', 'cited'];
  const parts = [
    { type: 'citation', resourceId: 'cited' },
    { type: 'citation', resourceId: 'external', url: 'https://example.com/paper' },
    { type: 'citation', resourceId: 'stale', stale: true },
  ];
  assert.deepEqual(researchBriefResourceIds({ sourceResourceIds, parts }), ['cited', 'attached']);
  assert.deepEqual(researchBriefResourceIds({}), []);
});

test('citation body line resolves through the stored Markdown front matter', () => {
  const body = '# Dynamics\r\n\r\nThe statement\r\ncontinues here.\r\n';
  const frontMatter = '---\r\nresource_id: dynamics\r\n---\r\n\r\n';
  const pin = { versionId: 'v1', contentHash: 'hash', excerpt: 'statement\ncontinues', lineEnd: 4 };
  assert.equal(resolveResearchCitationLine(frontMatter + body, 3, pin, true), 7);
  assert.equal(resolveResearchCitationLine(body, 3, pin, false), 3);
  assert.equal(resolveResearchCitationLine(frontMatter + body.replace('continues', 'ends'), 3, pin, true), undefined);
  assert.equal(resolveResearchCitationLine(body, 2, pin, false), undefined);
});
