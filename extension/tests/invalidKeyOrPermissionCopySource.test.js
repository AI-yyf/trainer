'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const protocolPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'protocol.ts');
const settingsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);

test('invalid_key_or_permission stays explainable for Coach and Settings', () => {
  const protocol = fs.readFileSync(protocolPath, 'utf8');
  const settings = fs.readFileSync(settingsPath, 'utf8');

  assert.match(protocol, /normalizedCategory === "invalid_key_or_permission"/);
  assert.match(protocol, /训练卡生成失败：API key 无效或没有权限/);
  assert.match(protocol, /Training card generation failed: API key invalid/);
  assert.match(settings, /case "invalid_key_or_permission"/);
});
