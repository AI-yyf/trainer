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

test('promotes an inline formula that was wrapped in backticks', () => {
  assert.equal(
    normalizeLatexDelimiters('成本期望 `E = p * c_retry + (1 - p) * c_success`。'),
    '成本期望 $E = p * c_retry + (1 - p) * c_success$。',
  );
});

test('promotes code-wrapped latex delimiters only when they carry math', () => {
  assert.equal(
    normalizeLatexDelimiters('代码 `\\( E = mc^2 \\)` 与 `\\[ a = b \\]`。'),
    '代码 $E = mc^2$ 与 $$\na = b\n$$。',
  );
  assert.equal(
    normalizeLatexDelimiters('正则 `\\[x\\]` 匹配方括号。'),
    '正则 `\\[x\\]` 匹配方括号。',
  );
});

test('promotes macro-only and simple subscript formulas', () => {
  assert.equal(
    normalizeLatexDelimiters('分数 `\\frac{1}{2}` 与定义 `c_t = 1`。'),
    '分数 $\\frac{1}{2}$ 与定义 $c_t = 1$。',
  );
  assert.equal(
    normalizeLatexDelimiters('正则 `\\d+` 仍为代码。'),
    '正则 `\\d+` 仍为代码。',
  );
});

test('keeps snake_case and plain code spans byte-identical', () => {
  const markdown = '代码 `foo_bar = baz + 1`、`x = y + 1`、`c_retry = compute()`。';
  assert.equal(normalizeLatexDelimiters(markdown), markdown);
});

test('turns a math fence into a display-math block', () => {
  assert.equal(
    normalizeLatexDelimiters('推导：\n```math\nE = mc^2\n```\n结束。'),
    '推导：\n$$\nE = mc^2\n$$\n结束。',
  );
  const python = '```python\nx = 1\n```';
  assert.equal(normalizeLatexDelimiters(python), python);
});

test('strips colour commands inside math but not inside code', () => {
  assert.equal(
    normalizeLatexDelimiters('颜色 $' + '\\textcolor{red}{x} + \\color{blue} y' + '$ 结束。'),
    '颜色 ${x} +  y$ 结束。',
  );
  const code = '代码 `' + '\\textcolor{red}{x}' + '` 不变。';
  assert.equal(normalizeLatexDelimiters(code), code);
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
