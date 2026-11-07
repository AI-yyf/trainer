'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');

const tsPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'rehypeChatScripts.ts');
const tsc = path.resolve(__dirname, '..', 'node_modules', 'typescript', 'bin', 'tsc');

let rehypeChatScripts;
test('setup', () => {
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-scripts-'));
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
  ({ rehypeChatScripts } = require(path.join(outDir, 'rehypeChatScripts.js')));
});

function text(value) {
  return { type: 'text', value };
}
function element(tagName, children, properties = {}) {
  return { type: 'element', tagName, properties, children };
}

test('short ^sup^ and ~sub~ runs become real elements', () => {
  const tree = {
    type: 'root',
    children: [element('p', [text('H~2~O 与 x^2^')])],
  };
  rehypeChatScripts()(tree);
  const tags = tree.children[0].children.filter((node) => node.type === 'element').map((node) => node.tagName);
  assert.deepEqual(tags, ['sub', 'sup']);
  assert.equal(tree.children[0].children[1].children[0].value, '2');
  assert.equal(tree.children[0].children[3].children[0].value, '2');
});

test('code, pre and KaTeX subtrees are unchanged', () => {
  const code = element('code', [text('H~2~O')]);
  const katex = element('span', [text('x^2^')], { className: ['katex'] });
  const tree = { type: 'root', children: [element('p', [code, katex])] };
  rehypeChatScripts()(tree);
  assert.equal(code.children[0].value, 'H~2~O');
  assert.equal(katex.children[0].value, 'x^2^');
});

test('long, spaced or path-like runs stay literal', () => {
  const source = 'a ~ b 与 ~/path 与 x^hello world^';
  const tree = { type: 'root', children: [element('p', [text(source)])] };
  rehypeChatScripts()(tree);
  assert.equal(tree.children[0].children[0].value, source);
});
