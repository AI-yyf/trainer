'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const browserHarnessPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewHarness.ts',
);

function sourceBlock(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);

  assert.ok(start >= 0, `expected source block starting with ${startMarker}`);
  assert.ok(end > start, `expected source block ending with ${endMarker}`);
  return source.slice(start, end);
}

test('Resources browser preview uses explicit case-preserving collection paths', () => {
  const source = fs.readFileSync(browserHarnessPath, 'utf8');
  const fixture = sourceBlock(
    source,
    'if (scenario === "resource-preview-loaded") {',
    'if (scenario === "done") {',
  );

  assert.match(
    fixture,
    /collectionPath: "knowledge\/Docs\/coach\/patterns\/coach-patterns\.md"/,
  );
  assert.match(
    fixture,
    /collectionPath: "knowledge\/docs\/training\/evidence\/training-matrix\.csv"/,
  );
  assert.match(
    fixture,
    /collectionPath: "projects\/Refactor\/briefs\/refactor-brief\.pdf"/,
  );

  assert.match(
    fixture,
    /sandboxPath: "H:\/trainer_final\/\.trainer\/sandbox\/knowledge\/coach\/patterns\/coach-patterns\.md"/,
  );
  assert.match(
    fixture,
    /sandboxPath: "H:\/trainer_final\/\.trainer\/sandbox\/knowledge\/training\/evidence\/training-matrix\.csv"/,
  );
});
