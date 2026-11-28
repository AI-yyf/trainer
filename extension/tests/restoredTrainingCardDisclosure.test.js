// Restored behavioral regression test. Original file: extension/tests/trainingWorkbenchDisclosureSource.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: undefined
//
// Restoration: partial - 1 of 3 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "secondary guidance and review data use native nested disclosures without removing actions"
//       hybrid template check: templateAssertions.practice() asserts on webview source text.
//   - "training disclosure summaries remain keyboard visible and token-driven"
//       CSS source-text guard: reads the webview stylesheet sections and asserts on the stylesheet text
//       (out of scope by rule).
// Target: webview components rendered to static markup through templateAssertions.render.

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
        language: 'en-US', cardId: 'restored-card-exact',
        cardOnly: true, cardType: 'practice', selectedCardStatus: 'active',
        card: {
          title: 'Restored card', currentStep: 'Try one boundary', currentFocus, whyNow: 'One late result',
          deliverable: 'A scoped result', verifyItems: ['Run the boundary check'],
          returnWith: 'Bring the current result back', nextAfterCompletion: 'Inspect the same boundary',
        },
        handoff: { latestTrainingLearningPhase: 'try' },
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

