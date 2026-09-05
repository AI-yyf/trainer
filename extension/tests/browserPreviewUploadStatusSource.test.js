'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('browser preview reports partial resource uploads without presenting them as full success', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const uploadStart = source.indexOf('const handleBrowserUploads = async (files: File[]) => {');
  const uploadEnd = source.indexOf('\n  const persistCoachSettings', uploadStart);

  assert.ok(uploadStart >= 0 && uploadEnd > uploadStart, 'expected browser upload handler');
  const uploadHandler = source.slice(uploadStart, uploadEnd);

  assert.match(uploadHandler, /failedUploadCount,/);
  assert.match(uploadHandler, /const uploadFailureTextZh =/);
  assert.match(uploadHandler, /const uploadFailureTextEn =/);
  assert.match(
    uploadHandler,
    /tone: failedUploadCount > 0 \|\| failedIndexCount > 0 \? "info" : "success"/,
  );
  assert.match(uploadHandler, /其他资料已经可以使用/);
  assert.match(uploadHandler, /the others are ready to use/);
  assert.match(uploadHandler, /catch \{[\s\S]*?tone: "error"/);
});
