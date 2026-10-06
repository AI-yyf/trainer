
// PR-7: styles.css is an @import aggregator; the real rules live in
// styles/sections/*.css. Read them concatenated in manifest order so
// assertions see the same bytes the browser gets after bundling.
function readStylesSource() {
  const fsMod = require('node:fs');
  const pathMod = require('node:path');
  const root = pathMod.resolve(__dirname, '..', 'webview', 'src');
  const manifest = JSON.parse(fsMod.readFileSync(
    pathMod.join(root, 'styles', 'sections', 'manifest.json'), 'utf8'));
  return manifest.map(
    (entry) => fsMod.readFileSync(pathMod.join(root, entry.file), 'utf8'),
  ).join('');
}

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const viewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');

test('training first screen keeps the five core facts in a stable order', () => {
  const source = fs.readFileSync(viewPath, 'utf8');

  // Focus mode: the card face shows the task; every supporting fact lives in
  // ONE collapsed "Task details" disclosure in reading order — why-now
  // (reason), deliverable, verify, return (+ after-this when present).
  const detailsStart = source.indexOf('data-training-card-details="true"');
  const detailsEnd = source.indexOf('</details>', detailsStart);
  assert.ok(detailsStart >= 0 && detailsEnd > detailsStart, 'expected the single task-details disclosure');

  assert.doesNotMatch(source, /data-training-core-section/);
  assert.doesNotMatch(source, /training-current__core-label/);
  const details = source.slice(detailsStart, detailsEnd);
  const factOrder = [...details.matchAll(/data-training-card-fact="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(factOrder.slice(0, 4), ['why-now', 'deliverable', 'verify', 'return']);
  assert.match(details, /\{resolvedWhyNow \?/);
  assert.match(details, /\{visibleNextAfterCompletion \?/);
  assert.doesNotMatch(details, /response/);
});

test('secondary guidance and review data use native nested disclosures without removing actions', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
});

test('training disclosure summaries remain keyboard visible and token-driven', () => {
  const styles = readStylesSource();

  assert.match(styles, /training-guidance-details__nested summary:focus-visible/);
  assert.match(styles, /training-review-row__fsrs summary:focus-visible/);
  // Focus-idiom pass (visual polish round R2) converged outlines onto the
  // --focus-ring token; --accent remains its fallback, not the direct value.
  assert.match(styles, /outline:\s*2px solid var\(--focus-ring\)/);
  assert.match(styles, /training-guidance-details__nested\s*>\s*summary::before/);
  assert.match(styles, /color-mix\(in srgb, var\(--line\)/);
});
