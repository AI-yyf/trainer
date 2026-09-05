'use strict';

const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const webviewNodeModules = path.resolve(__dirname, '..', 'webview', 'node_modules');
if (!process.env.NODE_PATH?.split(path.delimiter).includes(webviewNodeModules)) {
  process.env.NODE_PATH = process.env.NODE_PATH
    ? `${webviewNodeModules}${path.delimiter}${process.env.NODE_PATH}`
    : webviewNodeModules;
  Module._initPaths();
}

const typescript = require(path.join(webviewNodeModules, 'typescript'));

for (const extension of ['.ts', '.tsx']) {
  if (!require.extensions[extension]) {
    require.extensions[extension] = (module, filename) => {
      const source = fs.readFileSync(filename, 'utf8');
      const { outputText } = typescript.transpileModule(source, {
        compilerOptions: {
          module: typescript.ModuleKind.CommonJS,
          target: typescript.ScriptTarget.ES2020,
          jsx: typescript.JsxEmit.ReactJSX,
          esModuleInterop: true,
        },
        fileName: filename,
      });
      module._compile(outputText, filename);
    };
  }
}

const previewBodyModulePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'preview',
  'PreviewBody.tsx',
);

function collectText(node) {
  if (node == null || typeof node === 'boolean') {
    return [];
  }
  if (Array.isArray(node)) {
    return node.flatMap(collectText);
  }
  if (typeof node === 'string' || typeof node === 'number') {
    return [String(node)];
  }
  if (typeof node === 'object' && node.props) {
    return collectText(node.props.children);
  }
  return [];
}

test('renderPreviewBody prefers html over structured and text bodies', () => {
  const { renderPreviewBody } = require(previewBodyModulePath);
  const { sanitizePreviewHtml } = require(path.resolve(
    __dirname,
    '..',
    'webview',
    'src',
    'lib',
    'htmlSanitizer.ts',
  ));

  const rawHtml = '<section><p>HTML preview</p></section>';
  const node = renderPreviewBody({
    html: rawHtml,
    structuredPreview: {
      type: 'div',
      props: { children: ['Structured preview'] },
    },
    textBody: {
      type: 'div',
      props: { children: ['Text preview'] },
    },
    emptyMessage: 'No preview',
    htmlClassName: 'preview__html',
    structuredClassName: 'preview__structured',
    emptyClassName: 'preview__empty',
  });

  assert.ok(node);
  assert.equal(node.type, 'div');
  assert.equal(node.props.className, 'preview__html');
  assert.equal(node.props.dangerouslySetInnerHTML.__html, sanitizePreviewHtml(rawHtml));
});

test('renderPreviewBody falls back to structured, then text, then empty', () => {
  const { renderPreviewBody } = require(previewBodyModulePath);

  const structuredNode = renderPreviewBody({
    structuredPreview: {
      type: 'div',
      props: { className: 'structured', children: ['Structured preview'] },
    },
    textBody: {
      type: 'div',
      props: { children: ['Text preview'] },
    },
    emptyMessage: 'No preview',
    htmlClassName: 'preview__html',
    structuredClassName: 'preview__structured',
    emptyClassName: 'preview__empty',
  });
  const textNode = renderPreviewBody({
    textBody: {
      type: 'div',
      props: { className: 'preview__text', children: ['Text preview'] },
    },
    emptyMessage: 'No preview',
    htmlClassName: 'preview__html',
    structuredClassName: 'preview__structured',
    emptyClassName: 'preview__empty',
  });
  const emptyNode = renderPreviewBody({
    emptyMessage: 'No preview',
    htmlClassName: 'preview__html',
    structuredClassName: 'preview__structured',
    emptyClassName: 'preview__empty',
  });

  assert.ok(structuredNode);
  assert.ok(textNode);
  assert.ok(emptyNode);
  assert.equal(structuredNode.props.className, 'preview__structured');
  assert.deepEqual(collectText(structuredNode), ['Structured preview']);
  assert.equal(textNode.props.className, 'preview__text');
  assert.deepEqual(collectText(textNode), ['Text preview']);
  assert.equal(emptyNode.props.className, 'preview__empty');
  assert.deepEqual(collectText(emptyNode), ['No preview']);
});
