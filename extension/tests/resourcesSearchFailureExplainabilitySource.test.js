'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('path');

const viewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const sharedPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'resourceFailureExplainability.ts');

test('Resources search failure surfaces classifyResourceFailure category copy', () => {
  const view = fs.readFileSync(viewPath, 'utf8');
  const shared = fs.readFileSync(sharedPath, 'utf8');

  assert.match(shared, /"search_failed"/);
  assert.match(shared, /资料搜索失败/);
  assert.match(view, /classifyResourceFailure/);
  assert.match(view, /describeResourceFailureState/);
  assert.match(view, /category === "unknown" \? "search_failed"/);
  assert.match(view, /searchFailure\.category/);
  // generic searchFailed locale must not be the only failed label path
  assert.match(
    view,
    /describeResourceFailureState\([\s\S]*searchFailure\.category/,
  );
});
