// Restored behavioral regression test. Original file: extension/tests/structuredPreview.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: undefined
//
// Restoration: partial - 5 of 9 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "FilePreviewRenderer surfaces a table-specific teaching hint"
//       fails at HEAD: Cannot find module
//       'extension/webview/src/components/coach/parts/FilePreviewRenderer.tsx /
//   - "FilePreviewRenderer labels spreadsheet previews explicitly"
//       fails at HEAD: Cannot find module
//       'extension/webview/src/components/coach/parts/FilePreviewRenderer.tsx /
//   - "FilePreviewRenderer renders an xlsx fixture with explicit format and teaching copy"
//       fails at HEAD: Cannot find module
//       'extension/webview/src/components/coach/parts/FilePreviewRenderer.tsx /
//   - "FilePreviewRenderer gives notebooks archive and presentation previews distinct guidance"
//       fails at HEAD: Cannot find module
//       'extension/webview/src/components/coach/parts/FilePreviewRenderer.tsx /
// Target: webview TypeScript transpiled in memory with typescript.transpileModule.

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
const React = require(path.join(webviewNodeModules, 'react'));
const { renderToStaticMarkup } = require(path.join(webviewNodeModules, 'react-dom', 'server'));

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

const structuredPreviewModulePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'parts',
  'StructuredPreview.tsx',
);
const filePreviewRendererModulePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'parts',
  'FilePreviewRenderer.tsx',
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

function findElementByClass(node, className) {
  if (!node || typeof node !== 'object' || Array.isArray(node)) {
    return undefined;
  }
  if (node.props?.className === className) {
    return node;
  }
  const children = node.props?.children;
  if (Array.isArray(children)) {
    for (const child of children) {
      const match = findElementByClass(child, className);
      if (match) {
        return match;
      }
    }
  } else if (children) {
    const match = findElementByClass(children, className);
    if (match) {
      return match;
    }
  }
  return undefined;
}

test('renderStructuredPreview renders document previews from fallback text', () => {
  const { renderStructuredPreview } = require(structuredPreviewModulePath);

  const node = renderStructuredPreview(undefined, 'document', 'Alpha paragraph\n\nBeta paragraph');

  assert.ok(node);
  assert.equal(node.type, 'div');
  assert.equal(node.props.className, 'structured-preview structured-preview--document');

  const documentBody = findElementByClass(node, 'structured-preview__document');
  assert.ok(documentBody);
  assert.deepEqual(collectText(documentBody), ['Alpha paragraph', 'Beta paragraph']);
});

test('renderStructuredPreview renders structured document metadata and content', () => {
  const { renderStructuredPreview } = require(structuredPreviewModulePath);

  const node = renderStructuredPreview(
    {
      kind: 'document',
      format: 'pdf',
      pageCount: 3,
      sectionCount: 7,
      wordCount: 1280,
      truncated: true,
    },
    'document',
    'Converted training note',
  );

  assert.ok(node);
  const meta = findElementByClass(node, 'structured-preview__meta');
  const documentBody = findElementByClass(node, 'structured-preview__document');
  assert.ok(meta);
  assert.ok(documentBody);
  assert.equal(
    collectText(meta).join(' ').replace(/\s+/g, ' ').trim(),
    'PDF 3 pages 7 sections 1280 words Quick preview only',
  );
  assert.deepEqual(collectText(documentBody), ['Converted training note']);
});

test('renderStructuredPreview renders structured text and markup fallbacks as tier b previews', () => {
  const { renderStructuredPreview } = require(structuredPreviewModulePath);

  const structuredTextNode = renderStructuredPreview(
    {
      kind: 'structured-text',
      format: 'json',
      truncated: true,
      content: '{\n  "coach": true,\n  "mode": "guided"\n}',
    },
    'structured-text',
  );
  const markupNode = renderStructuredPreview(
    {
      kind: 'markup',
      format: 'html',
      content: '<section><p>Trainer keeps this grounded.</p></section>',
    },
    'markup',
  );

  assert.ok(structuredTextNode);
  assert.ok(markupNode);
  assert.equal(structuredTextNode.props.className, 'structured-preview structured-preview--document');
  assert.equal(markupNode.props.className, 'structured-preview structured-preview--document');

  const structuredTextBody = findElementByClass(structuredTextNode, 'structured-preview__document');
  const markupBody = findElementByClass(markupNode, 'structured-preview__document');
  assert.ok(structuredTextBody);
  assert.ok(markupBody);
  assert.equal(
    collectText(structuredTextBody).join(' ').replace(/\s+/g, ' ').trim(),
    '{ "coach": true, "mode": "guided" }',
  );
  assert.equal(
    collectText(markupBody).join(' ').replace(/\s+/g, ' ').trim(),
    '<section><p>Trainer keeps this grounded.</p></section>',
  );
});

test('renderStructuredPreview renders table previews for csv and xlsx style payloads', () => {
  const { renderStructuredPreview } = require(structuredPreviewModulePath);

  const node = renderStructuredPreview(
    {
      kind: 'table',
      format: 'xlsx',
      rowCount: 2,
      columnCount: 2,
      truncated: true,
      columns: ['Name', 'Score'],
      rows: [
        ['alpha', '1'],
        ['beta', '2'],
      ],
    },
    'table',
  );

  assert.ok(node);
  assert.equal(node.props.className, 'structured-preview structured-preview--table');

  const text = renderToStaticMarkup(node).replace(/\s+/g, ' ').trim();
  assert.match(text, /2 rows/);
  assert.match(text, /2 columns/);
  assert.match(text, /Quick preview only/);
  assert.match(text, /Name/);
  assert.match(text, /Score/);
  assert.match(text, /alpha/);
  assert.match(text, /beta/);
});

test('renderStructuredPreview renders archive previews as structured entries', () => {
  const { renderStructuredPreview } = require(structuredPreviewModulePath);

  const node = renderStructuredPreview(
    {
      kind: 'archive',
      format: 'zip',
      entryCount: 2,
      truncated: false,
      previewEntries: [
        { path: 'notes/readme.md', kind: 'file', sizeBytes: 16, preview: '# Archive Preview' },
        { path: 'data/values.csv', kind: 'file', sizeBytes: 11, preview: 'name,value' },
      ],
    },
    'archive',
  );

  assert.ok(node);
  assert.equal(node.props.className, 'structured-preview structured-preview--archive');

  const text = collectText(node).join(' ').replace(/\s+/g, ' ').trim();
  assert.match(text, /ZIP/);
  assert.match(text, /2 entries/);
  assert.match(text, /notes\/readme\.md/);
  assert.match(text, /data\/values\.csv/);
  assert.match(text, /# Archive Preview/);
  assert.match(text, /name,value/);
});



