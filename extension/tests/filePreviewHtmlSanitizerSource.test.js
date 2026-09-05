'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const partsFilePreviewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'parts',
  'FilePreviewRenderer.tsx',
);

test('parts FilePreviewRenderer sanitizes HTML before dangerouslySetInnerHTML', () => {
  const source = fs.readFileSync(partsFilePreviewPath, 'utf8');
  assert.match(source, /import \{ sanitizePreviewHtml \} from ["']\.\.\/\.\.\/lib\/htmlSanitizer["']/);
  assert.match(source, /sanitizePreviewHtml\(html\)/);
  assert.match(source, /dangerouslySetInnerHTML=\{\{ __html: sanitizedHtml \}\}/);
  assert.doesNotMatch(source, /dangerouslySetInnerHTML=\{\{ __html: html \}\}/);
});
