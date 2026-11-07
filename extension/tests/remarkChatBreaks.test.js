'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');

const tsPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'remarkChatBreaks.ts');
const tsc = path.resolve(__dirname, '..', 'node_modules', 'typescript', 'bin', 'tsc');

let remarkChatBreaks;
test('setup', () => {
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-breaks-'));
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
  ({ remarkChatBreaks } = require(path.join(outDir, 'remarkChatBreaks.js')));
});

test('single newlines inside a paragraph become break nodes', () => {
  const tree = {
    type: 'root',
    children: [
      {
        type: 'paragraph',
        children: [{ type: 'text', value: '第一行\n第二行' }],
      },
    ],
  };
  remarkChatBreaks()(tree);
  assert.deepEqual(
    tree.children[0].children.map((node) => node.type),
    ['text', 'break', 'text'],
  );
  assert.deepEqual(
    tree.children[0].children.filter((node) => node.type === 'text').map((node) => node.value),
    ['第一行', '第二行'],
  );
});

test('code and math leaves are untouched', () => {
  const tree = {
    type: 'root',
    children: [
      { type: 'code', value: 'a\nb' },
      { type: 'inlineMath', value: 'a\nb' },
      { type: 'inlineCode', value: 'a\nb' },
    ],
  };
  remarkChatBreaks()(tree);
  assert.equal(tree.children[0].value, 'a\nb');
  assert.equal(tree.children[1].value, 'a\nb');
  assert.equal(tree.children[2].value, 'a\nb');
});
