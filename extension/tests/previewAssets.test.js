'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const previewAssetsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'previewAssets.js',
);

test('isPdfPreviewPath matches trimmed pdf paths only', () => {
  const { isPdfPreviewPath, isDocxPreviewPath } = require(previewAssetsModulePath);
  const {
    getPreviewFormatBadge,
    getPreviewModeSummary,
    isTabularPreviewPath,
    isSpreadsheetPreviewPath,
    isPresentationPreviewPath,
    isNotebookPreviewPath,
    isArchivePreviewPath,
  } = require(previewAssetsModulePath);

  assert.equal(isPdfPreviewPath('F:\\trainer\\guide.pdf'), true);
  assert.equal(isPdfPreviewPath('  F:\\trainer\\guide.PDF  '), true);
  assert.equal(isPdfPreviewPath('F:\\trainer\\guide.docx'), false);
  assert.equal(isPdfPreviewPath(undefined), false);
  assert.equal(isDocxPreviewPath('F:\\trainer\\guide.docx'), true);
  assert.equal(isDocxPreviewPath('  F:\\trainer\\guide.DOCM  '), true);
  assert.equal(isDocxPreviewPath('F:\\trainer\\guide.pdf'), false);
  assert.equal(isDocxPreviewPath(undefined), false);
  assert.equal(isTabularPreviewPath('F:\\trainer\\sheet.csv'), true);
  assert.equal(isTabularPreviewPath('F:\\trainer\\sheet.tsv'), true);
  assert.equal(isTabularPreviewPath('F:\\trainer\\sheet.xlsx'), true);
  assert.equal(isTabularPreviewPath('F:\\trainer\\sheet.json'), false);
  assert.equal(isSpreadsheetPreviewPath('F:\\trainer\\sheet.csv'), false);
  assert.equal(isSpreadsheetPreviewPath('F:\\trainer\\sheet.XLSX'), true);
  assert.equal(isSpreadsheetPreviewPath('F:\\trainer\\sheet.ods'), true);
  assert.equal(isPresentationPreviewPath('F:\\trainer\\deck.pptx'), true);
  assert.equal(isPresentationPreviewPath('F:\\trainer\\deck.odp'), true);
  assert.equal(isPresentationPreviewPath('F:\\trainer\\deck.pdf'), false);
  assert.equal(isNotebookPreviewPath('F:\\trainer\\notes.ipynb'), true);
  assert.equal(isNotebookPreviewPath('F:\\trainer\\notes.txt'), false);
  assert.equal(isArchivePreviewPath('F:\\trainer\\bundle.zip'), true);
  assert.equal(isArchivePreviewPath('F:\\trainer\\bundle.tar.gz'), true);
  assert.equal(isArchivePreviewPath('F:\\trainer\\bundle.csv'), false);
  assert.equal(getPreviewFormatBadge({ format: 'xlsx' }, 'F:\\trainer\\sheet.xlsx'), 'XLSX');
  assert.equal(getPreviewFormatBadge({ format: 'ipynb' }, 'F:\\trainer\\notes.ipynb'), 'IPYNB');
  assert.match(
    getPreviewModeSummary(
      {
        previewKind: 'table',
        previewTier: 'converted',
        path: 'F:\\trainer\\sheet.xlsx',
        structuredData: { format: 'xlsx' },
      },
      'en',
    ) ?? '',
    /XLSX spreadsheet/i,
  );
  assert.match(
    getPreviewModeSummary(
      {
        previewKind: 'notebook',
        previewTier: 'converted',
        path: 'F:\\trainer\\notes.ipynb',
        structuredData: { format: 'ipynb' },
      },
      'en',
    ) ?? '',
    /IPYNB notebook/i,
  );
  assert.match(
    getPreviewModeSummary(
      {
        previewKind: 'archive',
        previewTier: 'metadata',
        path: 'F:\\trainer\\bundle.zip',
        structuredData: { format: 'zip' },
      },
      'en',
    ) ?? '',
    /ZIP archive/i,
  );
});
