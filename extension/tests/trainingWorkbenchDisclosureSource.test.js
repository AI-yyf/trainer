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
  const sections = ['current', 'why-now', 'deliverable', 'verify', 'next'];
  const routeStart = source.indexOf('const routeStripItems = [');
  const routeEnd = source.indexOf('const showRouteDetails', routeStart);
  const routeSource = source.slice(routeStart, routeEnd);

  assert.ok(routeStart >= 0 && routeEnd > routeStart, 'expected the five-item core route');
  assert.deepEqual(
    [...sections.slice(1, 4), 'return'],
    [...routeSource.matchAll(/key: "([^"]+)"/g)].map((match) => match[1]),
  );
  assert.match(source, /data-training-core-section="current"/);
  assert.match(source, /data-training-core-section=\{item\.key === "return" \? "next" : item\.key\}/);
  assert.match(source, /training-current__core-label/);
  assert.match(source, /routeStripItems\.map/);
});

test('secondary guidance and review data use native nested disclosures without removing actions', () => {
  const source = fs.readFileSync(viewPath, 'utf8');

  assert.match(source, /className="training-guidance-details__nested"/);
  assert.match(source, /提示阶梯|Hint ladder/);
  assert.match(source, /常见错误|Common mistakes/);
  assert.match(source, /className="training-review-row__fsrs"/);
  assert.match(source, /className="training-review-row__actions-details" open/);
  assert.match(source, /onReviewQueueAction\?\.\(/);
  assert.match(source, /concept: item\.concept/);
  assert.match(source, /action,/);
  assert.match(source, /focusArea: item\.focusArea/);
  assert.match(source, /taskHint: item\.taskHint/);
  assert.match(source, /primaryAction/);
  assert.match(source, /actions/);
});

test('training disclosure summaries remain keyboard visible and token-driven', () => {
  const styles = fs.readFileSync(stylesPath, 'utf8');

  assert.match(styles, /training-guidance-details__nested summary:focus-visible/);
  assert.match(styles, /training-review-row__fsrs summary:focus-visible/);
  assert.match(styles, /outline:\s*2px solid var\(--accent\)/);
  assert.match(styles, /training-guidance-details__nested\s*>\s*summary::before/);
  assert.match(styles, /color-mix\(in srgb, var\(--line\)/);
});
