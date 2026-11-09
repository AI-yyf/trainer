'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  resolveResourceOpenTarget,
  resolveResourceReadCandidates,
  resolveResourceOriginalCandidates,
  hasDistinctOriginal,
} = require('../dist/shared/src/resourceOpen.js');

test('document resources open the original file, not the Markdown digest', () => {
  const resource = {
    kind: 'docx',
    source: '/workspace/docs/notes.docx',
    canonicalSource: '/workspace/docs/notes.docx',
    canonicalMarkdownPath: 'Trainer Library/resources/markdown/resource-1.md',
    canonicalOriginalPath: 'Trainer Library/resources/originals/resource-1/notes.docx',
  };
  assert.deepEqual(resolveResourceReadCandidates(resource), [
    'Trainer Library/resources/markdown/resource-1.md',
  ]);
  assert.deepEqual(resolveResourceOriginalCandidates(resource), [
    'Trainer Library/resources/originals/resource-1/notes.docx',
  ]);
  assert.deepEqual(resolveResourceOpenTarget(resource), {
    kind: 'vscode',
    source: 'Trainer Library/resources/originals/resource-1/notes.docx',
  });
  assert.equal(hasDistinctOriginal(resource), true);
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
  assert.equal(hasDistinctOriginal(resource), false);
});

test('URL resources stay browser-openable and never claim a local file', () => {
  const resource = { kind: 'url', source: 'https://example.org/a', canonicalSource: 'https://example.org/a' };
  assert.deepEqual(resolveResourceReadCandidates(resource), []);
  assert.deepEqual(resolveResourceOriginalCandidates(resource), []);
  assert.deepEqual(resolveResourceOpenTarget(resource), {
    kind: 'browser',
    source: 'https://example.org/a',
  });
});

test('a captured URL still opens the live web source, not the Markdown snapshot', () => {
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
    kind: 'browser',
    source: 'https://example.org/a',
  });
});
