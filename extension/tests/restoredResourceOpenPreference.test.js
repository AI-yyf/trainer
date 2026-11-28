// Restored behavioral regression test. Original file: extension/tests/resourceOpenPreference.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Resource open preference: canonical Markdown vs local capture for URLs and documents.
//
// Restoration: whole - all 4 original test definitions, code and assertions unchanged.
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  resolveResourceOpenTarget,
  resolveResourceReadCandidates,
} = require('../dist/shared/src/resourceOpen.js');

test('document resources open the complete canonical Markdown and have no original', () => {
  const resource = {
    kind: 'markdown',
    source: '/workspace/docs/notes.docx',
    canonicalSource: '/workspace/docs/notes.docx',
    canonicalMarkdownPath: 'Trainer Library/resources/markdown/resource-1.md',
    canonicalOriginalPath: 'Trainer Library/resources/originals/resource-1/notes.docx',
  };
  assert.deepEqual(resolveResourceReadCandidates(resource), [
    'Trainer Library/resources/markdown/resource-1.md',
  ]);
  assert.deepEqual(resolveResourceOpenTarget(resource), {
    kind: 'vscode',
    source: 'Trainer Library/resources/markdown/resource-1.md',
  });
});

test('resources without a canonical digest keep the previous local priority', () => {
  const resource = {
    kind: 'pdf',
    source: '/workspace/paper.pdf',
    sandboxPath: '/workspace/.trainer-sandbox/paper.pdf',
  };
  assert.deepEqual(resolveResourceReadCandidates(resource), [
    '/workspace/.trainer-sandbox/paper.pdf',
  ]);
});

test('an uncaptured URL requires a local capture', () => {
  const resource = { kind: 'url', source: 'https://example.org/a', canonicalSource: 'https://example.org/a' };
  assert.deepEqual(resolveResourceReadCandidates(resource), []);
  assert.deepEqual(resolveResourceOpenTarget(resource), {
    kind: 'unavailable',
    reason: 'capture_required',
  });
});

test('a captured URL opens its complete Markdown', () => {
  const resource = {
    kind: 'url',
    source: 'https://example.org/a',
    canonicalMarkdownPath: 'Trainer Library/resources/markdown/resource-2.md',
    canonicalOriginalPath: 'Trainer Library/resources/originals/resource-2/capture.md',
  };
  assert.deepEqual(resolveResourceReadCandidates(resource), [
    'Trainer Library/resources/markdown/resource-2.md',
  ]);
  assert.deepEqual(resolveResourceOpenTarget(resource), {
    kind: 'vscode',
    source: 'Trainer Library/resources/markdown/resource-2.md',
  });
});
