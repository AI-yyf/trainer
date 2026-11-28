// Restored behavioral regression test. Original file: extension/tests/codingGapTracker.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: CodingGapTracker quiet-window behaviour.
//
// Restoration: whole - all 1 original test definitions, code and assertions unchanged.
// Target: extension host (extension/dist) with the vscode mock.

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const {
  CodingGapTracker,
  DEFAULT_TYPING_QUIET_WINDOW_MS,
} = require(path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'codingGapTracker.js',
));

test('CodingGapTracker treats edits inside the quiet window as actively typing and clears once quiet', () => {
  let clockMs = 1_000_000;
  const tracker = new CodingGapTracker(DEFAULT_TYPING_QUIET_WINDOW_MS, () => clockMs);

  assert.equal(tracker.isActivelyTyping(), false);
  assert.equal(tracker.quietDurationMs(), null);

  tracker.recordEdit();
  assert.equal(tracker.isActivelyTyping(), true);
  assert.equal(tracker.quietDurationMs(), 0);

  clockMs += DEFAULT_TYPING_QUIET_WINDOW_MS - 1;
  assert.equal(tracker.isActivelyTyping(), true);
  assert.equal(tracker.quietDurationMs(), DEFAULT_TYPING_QUIET_WINDOW_MS - 1);

  clockMs += 1;
  assert.equal(tracker.isActivelyTyping(), false);
  assert.equal(tracker.quietDurationMs(), DEFAULT_TYPING_QUIET_WINDOW_MS);

  tracker.reset();
  assert.equal(tracker.isActivelyTyping(), false);
  assert.equal(tracker.quietDurationMs(), null);
});
