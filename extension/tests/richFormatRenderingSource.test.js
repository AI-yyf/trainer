'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...parts) => fs.readFileSync(path.join(__dirname, '..', 'webview', 'src', ...parts), 'utf8');

test('code and diagrams keep their library-generated styling', () => {
  const shiki = read('components', 'coach', 'parts', 'ShikiCodeBlock.tsx');
  const mermaid = read('components', 'coach', 'MermaidBlock.tsx');

  // Shiki inline token colors are the syntax highlight; the model-HTML
  // sanitizer strips style attributes, so trusted library output must bypass it.
  assert.doesNotMatch(shiki, /sanitizePreviewHtml/);
  assert.match(shiki, /createJavaScriptRegexEngine/);
  assert.match(shiki, /engine: javaScriptEngine/);
  assert.match(shiki, /loadLanguage/);
  assert.doesNotMatch(shiki, /className\?: string/);
  assert.doesNotMatch(mermaid, /sanitizePreviewHtml/);
  assert.match(mermaid, /securityLevel: "strict"/);
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
