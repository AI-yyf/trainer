'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const settingsSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

test('settings summary compaction removes duplicate labels before joining the connection summary', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');

  assert.match(source, /const seen = new Set<string>\(\);/);
  assert.match(source, /if \(!key \|\| seen\.has\(key\)\)/);
});

test('settings model cache status is rendered once', () => {
  const source = fs.readFileSync(settingsSourcePath, 'utf8');
  const start = source.indexOf('label={copy.modelCache}');
  const end = source.indexOf('label={copy.lastTest}', start);
  const cacheSummary = source.slice(start, end);

  assert.ok(start >= 0 && end > start);
  assert.doesNotMatch(cacheSummary, /<span>\{modelCacheStatusLabel\}<\/span>/);
  assert.match(cacheSummary, /<StatusPill tone=\{modelCacheTone\}>\{modelCacheStatusLabel\}<\/StatusPill>/);
});
