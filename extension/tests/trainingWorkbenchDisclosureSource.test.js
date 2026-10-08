
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


test('the current card identity and focus remain available in one collapsed task disclosure', () => {
  const { render } = require('./templateAssertions');
  const previousWindow = globalThis.window;
  globalThis.window = { location: { search: '', hash: '', origin: 'http://localhost' },
    localStorage: { getItem() { return null; }, setItem() {} } };
  try {
    for (const currentFocus of [undefined, 'Keep the original workspace scope']) {
      const html = render('components/training/TrainingWorkbenchView.tsx', 'TrainingWorkbenchView', {
        language: 'en-US', cardId: 'restored-card-exact', title: 'Restored card',
        cardOnly: true, cardType: 'practice', selectedCardStatus: 'active', latestTrainingLearningPhase: 'try',
        currentStep: 'Try one boundary', currentFocus, whyNow: 'One late result',
        deliverable: 'A scoped result', verifyItems: ['Run the boundary check'],
        returnWith: 'Bring the current result back', nextAfterCompletion: 'Inspect the same boundary',
        reviewItems: [],
      });
      assert.match(html, /data-training-card-id="restored-card-exact"/);
      assert.doesNotMatch(html, /data-training-core-section|training-current__core-label/);
      const detailsStart = html.indexOf('data-training-card-details="true"');
      const detailsEnd = html.indexOf('</details>', detailsStart);
      assert.ok(detailsStart >= 0 && detailsEnd > detailsStart);
      const details = html.slice(detailsStart, detailsEnd);
      const openingTag = html.slice(html.lastIndexOf('<details', detailsStart), detailsStart);
      assert.doesNotMatch(openingTag, /\bopen\b/);
      assert.equal((html.match(/data-training-card-details="true"/g) ?? []).length, 1);
      const order = [...details.matchAll(/data-training-card-fact="([^"]+)"/g)].map(match => match[1]);
      assert.deepEqual(order.slice(0, currentFocus ? 5 : 4),
        [...(currentFocus ? ['focus'] : []), 'why-now', 'deliverable', 'verify', 'return']);
      if (currentFocus) assert.ok(details.includes(currentFocus));
      assert.doesNotMatch(details, /training-response|coach-composer/);
    }
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
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
