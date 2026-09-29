'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const appUiCopySourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'appUiCopy.ts',
);

test('browser preview reports partial resource uploads without presenting them as full success', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const uploadStart = source.indexOf('const handleBrowserUploads = async (files: File[]) => {');
  const uploadEnd = source.indexOf('\n  const persistCoachSettings', uploadStart);

  assert.ok(uploadStart >= 0 && uploadEnd > uploadStart, 'expected browser upload handler');
  const uploadHandler = source.slice(uploadStart, uploadEnd);

  // §十五: the zh/en upload fragment pair became one record-driven assembly —
  // the handler composes appUiCopy fragments; the en copy lives in the record.
  assert.match(uploadHandler, /const uploadFailureText =/);
  assert.match(
    uploadHandler,
    /appUiCopy\(layout\.composerLanguage, "其中 \{n\} 个没有导入成功，其他资料已经可以使用。"\)/,
  );
  assert.match(uploadHandler, /uploadFailureText,/);
  assert.match(
    uploadHandler,
    /tone: failedUploadCount > 0 \|\| failedIndexCount > 0 \? "info" : "success"/,
  );
  const appUiCopySource = fs.readFileSync(appUiCopySourcePath, 'utf8');
  assert.match(appUiCopySource, /the others are ready to use/);
  assert.match(uploadHandler, /catch \{[\s\S]*?tone: "error"/);
});
