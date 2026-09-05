'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const sourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'parts',
  'PartsRenderer.tsx',
);

function source() {
  return fs.readFileSync(sourcePath, 'utf8');
}

test('typed markdown parts keep table and math rendering enabled', () => {
  const text = source();
  assert.match(text, /import remarkGfm from ["']remark-gfm["']/);
  assert.match(text, /import remarkMath from ["']remark-math["']/);
  assert.match(text, /import rehypeKatex from ["']rehype-katex["']/);
  assert.match(text, /rehypePlugins=\{\[rehypeKatex\]\}/);
  assert.match(text, /remarkPlugins=\{\[remarkGfm, remarkMath\]\}/);
});

test('part disclosure controls are localized, explicit buttons', () => {
  const text = source();
  assert.match(text, /aria-expanded=\{!shouldCollapse\}/);
  assert.match(text, /aria-label=\{shouldCollapse \? copy\.expand : copy\.collapse\}/);
  assert.match(text, /type="button"/);
  assert.match(text, /"展开详情"/);
  assert.match(text, /"Expand details"/);
});

test('unknown parts never render raw payload JSON', () => {
  const text = source();
  assert.match(text, /Unsupported message content/);
  assert.doesNotMatch(text, /JSON\.stringify\(part/);
  assert.doesNotMatch(text, /unknown-part-json/);
});
