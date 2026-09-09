'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const protocolPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'protocol.ts');
const composerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);

test('five-view busy/empty explainability: ViewFallback + Coach composer busy', () => {
  const app = fs.readFileSync(appPath, 'utf8');
  const composer = fs.readFileSync(composerPath, 'utf8');

  assert.match(app, /function ViewFallback/);
  assert.match(app, /aria-busy="true"/);
  assert.match(app, /正在加载\$\{label\}，请稍候/);
  assert.match(app, /Loading \$\{label\} — hang on a moment/);

  // Docked four views use Suspense ViewFallback
  assert.match(app, /ViewFallback label=\{resourcesViewLabel/);
  assert.match(app, /ViewFallback label=\{t\.training\}/);
  assert.match(app, /ViewFallback label=\{t\.plan\}/);
  assert.match(app, /ViewFallback label=\{t\.settings\}/);

  // Coach root is eager; busy stays explainable via composer busyLabel
  assert.match(app, /renderCoachRootView/);
  assert.match(composer, /busyLabel: "教练正在思考"/);
  assert.match(composer, /busyLabel: "Trainer is thinking"/);
});

test('training-card failure categories stay explainable and distinct', () => {
  const protocol = fs.readFileSync(protocolPath, 'utf8');
  assert.match(protocol, /normalizedCategory === "invalid_json"/);
  assert.match(protocol, /provider_request_failed_training_card/);
  assert.match(protocol, /训练卡回复不是有效 JSON/);
  assert.match(protocol, /训练卡生成时 provider 请求失败/);
  assert.match(protocol, /Empty stream: the model sent no content/);
});
