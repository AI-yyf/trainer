'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');

// Compile shared/src/latexDelimiters.ts to a temp CJS module for testing.
const tsPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'latexDelimiters.ts');
const tsc = path.resolve(__dirname, '..', 'node_modules', 'typescript', 'bin', 'tsc');

let normalizeLatexDelimiters;
test('setup', () => {
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'latex-delims-'));
  execFileSync(process.execPath, [
    tsc,
    tsPath,
    '--outDir',
    outDir,
    '--module',
    'commonjs',
    '--target',
    'es2022',
    '--skipLibCheck',
    '--declaration',
    'false',
  ]);
  ({ normalizeLatexDelimiters } = require(path.join(outDir, 'latexDelimiters.js')));
});

test('converts display and inline delimiters to parseable math', () => {
  assert.equal(
    normalizeLatexDelimiters('回报是 [ G_t = r_{t+1} + \\gamma r_{t+2} + \\dots ]，注意折扣。'),
    '回报是 [ G_t = r_{t+1} + \\gamma r_{t+2} + \\dots ]，注意折扣。',
  );
  assert.equal(
    normalizeLatexDelimiters('\\[ G_t = r_{t+1} + \\gamma r_{t+2} \\]'),
    '$$ G_t = r_{t+1} + \\gamma r_{t+2} $$',
  );
  assert.equal(
    normalizeLatexDelimiters('价值函数 \\( V(s) \\) 的定义如下。'),
    '价值函数 $ V(s) $ 的定义如下。',
  );
});

test('leaves fenced code blocks byte-identical', () => {
  const markdown = ['说明。', '```python', 'pattern = "\\[x\\]"  # regex markers', '```', '结束。'].join('\n');
  assert.equal(normalizeLatexDelimiters(markdown), markdown);
});

test('leaves inline code spans byte-identical', () => {
  const markdown = '正则 `\\[x\\]` 用来匹配方括号。';
  assert.equal(normalizeLatexDelimiters(markdown), markdown);
});

test('returns the input when no delimiters are present', () => {
  const markdown = '纯文本，没有公式。';
  assert.equal(normalizeLatexDelimiters(markdown), markdown);
  assert.equal(normalizeLatexDelimiters(''), '');
});

test('a mixed document converts only the prose', () => {
  const markdown = ['\\[ a = b \\]', '```js', 'const re = "\\[";', '```', '行内 \\( c \\) 与 `\\(d\\)`。'].join('\n');
  assert.equal(
    normalizeLatexDelimiters(markdown),
    ['$$ a = b $$', '```js', 'const re = "\\[";', '```', '行内 $ c $ 与 `\\(d\\)`。'].join('\n'),
  );
});
