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
