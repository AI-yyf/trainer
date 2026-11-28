// Restored behavioral regression test. Original file: extension/tests/acceptanceFeedback.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Acceptance feedback parsing from verify_practice_current_file tool results.
//
// Restoration: partial - 2 of 4 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "parses training-acceptance check detail lines"
//       fails at HEAD: parseAcceptanceFeedbackFromCheckDetail is not a function
//   - "returns null when the detail carries no acceptance breakdown"
//       fails at HEAD: parseAcceptanceFeedbackFromCheckDetail is not a function
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const parserPath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'acceptanceFeedback.js',
);

const {
  parseAcceptanceFeedbackFromToolResult,
  parseAcceptanceFeedbackFromCheckDetail,
} = require(parserPath);

test('parses verify_practice_current_file tool results into progress feedback', () => {
  const feedback = parseAcceptanceFeedbackFromToolResult({
    tool: 'verify_practice_current_file',
    passed: false,
    status: 'needs_review',
    next_step: 'Implement the missing acceptance signals (starting with "debounceSearch"), then run Verify current file again.',
    criteria: [
      { text: 'Implement debounceSearch for the search input.', status: 'matched', matched_signals: ['debounceSearch'] },
      { text: 'Keep the search function pure.', status: 'missing', missing_signals: ['pure'] },
      { text: 'debounceSearch', status: 'missing', missing_signals: ['debounceSearch'] },
    ],
  });

  assert.ok(feedback);
  assert.equal(feedback.matched, 1);
  assert.equal(feedback.total, 3);
  assert.deepEqual(feedback.matchedItems, ['Implement debounceSearch for the search input.']);
  assert.deepEqual(feedback.missingItems, ['Keep the search function pure.', 'debounceSearch']);
  assert.match(feedback.nextStep, /debounceSearch/);
});

test('returns null for non-verification tool results', () => {
  assert.equal(parseAcceptanceFeedbackFromToolResult({ ok: true, tool: 'read_file' }), null);
  assert.equal(parseAcceptanceFeedbackFromToolResult(null), null);
  assert.equal(parseAcceptanceFeedbackFromToolResult({ tool: 'verify_practice_current_file', criteria: [] }), null);
});

