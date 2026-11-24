'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...parts) => fs.readFileSync(path.join(__dirname, '..', 'webview', 'src', ...parts), 'utf8');

test('code and diagrams keep their library-generated styling', () => {
  const shiki = read('components', 'coach', 'parts', 'ShikiCodeBlock.tsx');
  const mermaid = read('components', 'coach', 'MermaidBlock.tsx');
  const mermaidRenderer = read('lib', 'mermaidDiagram.ts');

  // Shiki inline token colors are the syntax highlight; the model-HTML
  // sanitizer strips style attributes, so trusted library output must bypass it.
  assert.doesNotMatch(shiki, /sanitizePreviewHtml/);
  assert.match(shiki, /createJavaScriptRegexEngine/);
  assert.match(shiki, /engine: javaScriptEngine/);
  assert.match(shiki, /loadLanguage/);
  assert.doesNotMatch(shiki, /className\?: string/);
  assert.doesNotMatch(mermaid, /sanitizePreviewHtml/);
  // Mermaid runs strict from its one owner; the diagram keeps its theme
  // because it is rebuilt and shadow-isolated rather than HTML-sanitized.
  assert.match(mermaidRenderer, /securityLevel: "strict"/);
  assert.match(mermaidRenderer, /htmlLabels: true/);
  assert.match(shiki, /new MutationObserver/);
  assert.match(mermaid, /new MutationObserver/);
});

test('coach replies cannot submit forms to an external action', () => {
  const content = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'core', 'webviewContent.ts'),
    'utf8',
  );
  assert.match(content, /form-action 'none'/);
});

test('markdown links open externally with rel hardening', () => {
  const rich = read('components', 'coach', 'MessageRichContent.tsx');
  assert.match(rich, /target="_blank"/);
  assert.match(rich, /rel="noopener noreferrer"/);
});
