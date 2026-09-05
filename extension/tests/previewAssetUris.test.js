'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const previewAssetUrisModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'previewAssetUris.js',
);

test('attachPreviewAssetUris adds assetUri for sandbox media preview and file preview parts', async () => {
  const { attachPreviewAssetUris } = require(previewAssetUrisModulePath);

  const patch = attachPreviewAssetUris(
    {
      memory: {
        sandboxPreview: {
          path: 'F:\\trainer\\workspace-a\\diagram.png',
          previewKind: 'image',
        },
      },
      conversation: [
        {
          id: 'assistant-1',
          role: 'assistant',
          author: 'Trainer',
          body: 'Look at this clip.',
          timestamp: '2026-06-09T08:01:00Z',
          parts: [
            {
              type: 'file_preview',
              resourceId: 'resource-video',
              path: 'F:\\trainer\\workspace-a\\demo.mp4',
              previewKind: 'video',
            },
            {
              type: 'file_preview',
              resourceId: 'resource-pdf',
              path: 'F:\\trainer\\workspace-a\\guide.pdf',
              previewKind: 'document',
            },
          ],
        },
      ],
    },
    (filePath) =>
      filePath.endsWith('diagram.png')
        ? 'vscode-webview-resource://trainer/workspace-a/diagram.png'
        : filePath.endsWith('demo.mp4')
          ? 'vscode-webview-resource://trainer/workspace-a/demo.mp4'
          : filePath.endsWith('guide.pdf')
            ? 'vscode-webview-resource://trainer/workspace-a/guide.pdf'
          : undefined,
  );

  assert.equal(
    patch.memory.sandboxPreview.assetUri,
    'vscode-webview-resource://trainer/workspace-a/diagram.png',
  );
  assert.equal(
    patch.conversation[0].parts[0].assetUri,
    'vscode-webview-resource://trainer/workspace-a/demo.mp4',
  );
  assert.equal(
    patch.conversation[0].parts[1].assetUri,
    'vscode-webview-resource://trainer/workspace-a/guide.pdf',
  );
});

test('attachPreviewAssetUris adds assetUri for sandbox pdf previews', async () => {
  const { attachPreviewAssetUris } = require(previewAssetUrisModulePath);

  const patch = attachPreviewAssetUris(
    {
      memory: {
        sandboxPreview: {
          path: 'F:\\trainer\\workspace-a\\handbook.pdf',
          previewKind: 'document',
        },
      },
    },
    (filePath) =>
      filePath.endsWith('handbook.pdf')
        ? 'vscode-webview-resource://trainer/workspace-a/handbook.pdf'
        : undefined,
  );

  assert.equal(
    patch.memory.sandboxPreview.assetUri,
    'vscode-webview-resource://trainer/workspace-a/handbook.pdf',
  );
});

test('attachPreviewAssetUris adds assetUri for docx document sandbox and file_preview parts', async () => {
  const { attachPreviewAssetUris } = require(previewAssetUrisModulePath);

  const patch = attachPreviewAssetUris(
    {
      memory: {
        sandboxPreview: {
          path: 'F:\\trainer\\workspace-a\\notes.docx',
          previewKind: 'document',
        },
      },
      conversation: [
        {
          id: 'assistant-docx',
          role: 'assistant',
          author: 'Trainer',
          body: 'Open this doc.',
          timestamp: '2026-06-09T08:03:00Z',
          parts: [
            {
              type: 'file_preview',
              resourceId: 'resource-docx',
              path: 'F:\\trainer\\workspace-a\\guide.docx',
              previewKind: 'document',
            },
          ],
        },
      ],
    },
    (filePath) =>
      filePath.endsWith('notes.docx')
        ? 'vscode-webview-resource://trainer/workspace-a/notes.docx'
        : filePath.endsWith('guide.docx')
          ? 'vscode-webview-resource://trainer/workspace-a/guide.docx'
          : undefined,
  );

  assert.equal(
    patch.memory.sandboxPreview.assetUri,
    'vscode-webview-resource://trainer/workspace-a/notes.docx',
  );
  assert.equal(
    patch.conversation[0].parts[0].assetUri,
    'vscode-webview-resource://trainer/workspace-a/guide.docx',
  );
});

test('attachPreviewAssetUris leaves non-media previews unchanged', async () => {
  const { attachPreviewAssetUris } = require(previewAssetUrisModulePath);

  const input = {
    conversation: [
      {
        id: 'assistant-2',
        role: 'assistant',
        author: 'Trainer',
        body: 'Read this note.',
        timestamp: '2026-06-09T08:02:00Z',
        parts: [
          {
            type: 'file_preview',
            resourceId: 'resource-note',
            path: 'F:\\trainer\\workspace-a\\note.md',
            previewKind: 'markdown',
          },
        ],
      },
    ],
  };

  const patch = attachPreviewAssetUris(input, () => 'unused');

  assert.equal(patch.conversation[0].parts[0].assetUri, undefined);
});

test('attachPreviewAssetUris invents conversation file_preview for live docx sandbox preview', async () => {
  const { attachPreviewAssetUris } = require(previewAssetUrisModulePath);

  const patch = attachPreviewAssetUris(
    {
      conversation: [
        {
          id: 'user-1',
          role: 'user',
          author: 'you',
          body: 'preview this',
          timestamp: '2026-06-09T08:04:00Z',
        },
      ],
      memory: {
        selectedResourceDetail: { id: 'res-docx-1', title: 'notes.docx' },
        sandboxPreview: {
          path: 'F:\\trainer\\workspace-a\\notes.docx',
          title: 'notes.docx',
          previewKind: 'document',
          previewTier: 'converted',
        },
      },
    },
    (filePath) =>
      filePath.endsWith('notes.docx')
        ? 'vscode-webview-resource://trainer/workspace-a/notes.docx'
        : undefined,
  );

  assert.equal(
    patch.memory.sandboxPreview.assetUri,
    'vscode-webview-resource://trainer/workspace-a/notes.docx',
  );
  const hostMessage = patch.conversation.find((message) => message.id === 'host-file-preview-docx');
  assert.ok(hostMessage);
  assert.equal(hostMessage.parts.length, 1);
  assert.equal(hostMessage.parts[0].type, 'file_preview');
  assert.equal(hostMessage.parts[0].previewKind, 'document');
  assert.equal(hostMessage.parts[0].path, 'F:\\trainer\\workspace-a\\notes.docx');
  assert.equal(
    hostMessage.parts[0].assetUri,
    'vscode-webview-resource://trainer/workspace-a/notes.docx',
  );
  assert.equal(hostMessage.parts[0].resourceId, 'res-docx-1');
});

test('attachPreviewAssetUris does not invent file_preview without conversation opt-in', async () => {
  const { attachPreviewAssetUris } = require(previewAssetUrisModulePath);

  const patch = attachPreviewAssetUris(
    {
      memory: {
        sandboxPreview: {
          path: 'F:\\trainer\\workspace-a\\notes.docx',
          previewKind: 'document',
        },
      },
    },
    () => 'vscode-webview-resource://trainer/workspace-a/notes.docx',
  );

  assert.equal(
    patch.memory.sandboxPreview.assetUri,
    'vscode-webview-resource://trainer/workspace-a/notes.docx',
  );
  assert.equal(patch.conversation, undefined);
});

test('attachPreviewAssetUris does not invent file_preview for non-docx sandbox dumps', async () => {
  const { attachPreviewAssetUris } = require(previewAssetUrisModulePath);

  const patch = attachPreviewAssetUris(
    {
      conversation: [
        {
          id: 'user-2',
          role: 'user',
          author: 'you',
          body: 'preview md',
          timestamp: '2026-06-09T08:05:00Z',
        },
      ],
      memory: {
        sandboxPreview: {
          path: 'F:\\trainer\\workspace-a\\note.md',
          previewKind: 'markdown',
        },
      },
    },
    () => 'unused',
  );

  assert.equal(patch.conversation.length, 1);
  assert.equal(patch.conversation[0].parts, undefined);
});

test('attachPreviewAssetUris maps snake_case file_preview fields to camelCase for Coach', async () => {
  const { attachPreviewAssetUris } = require(previewAssetUrisModulePath);
  const sandboxPath = 'F:\\trainer\\workspace-a\\notes.docx';

  const patch = attachPreviewAssetUris(
    {
      conversation: [
        {
          id: 'assistant-snake',
          role: 'assistant',
          author: 'Trainer',
          body: 'snake part',
          timestamp: '2026-08-27T09:00:00Z',
          parts: [
            {
              type: 'file_preview',
              resource_id: 'resource-docx',
              path: sandboxPath,
              preview_kind: 'document',
              preview_tier: 'converted',
            },
          ],
        },
      ],
    },
    (filePath) =>
      filePath === sandboxPath
        ? 'vscode-webview-resource://trainer/workspace-a/notes.docx'
        : undefined,
  );

  const part = patch.conversation[0].parts[0];
  assert.equal(part.type, 'file_preview');
  assert.equal(part.resourceId, 'resource-docx');
  assert.equal(part.previewKind, 'document');
  assert.equal(part.previewTier, 'converted');
  assert.equal(part.assetUri, 'vscode-webview-resource://trainer/workspace-a/notes.docx');
  // Coach gate shape: document + assetUri + docx path
  assert.equal(part.previewKind === 'document' && Boolean(part.assetUri) && /\.docx$/i.test(part.path), true);
});
