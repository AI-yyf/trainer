'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const composerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);
const protocolPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'protocol.ts');

test('coach composer keeps empty_stream send state explainable with draft retry', () => {
  const app = fs.readFileSync(appPath, 'utf8');
  const composer = fs.readFileSync(composerPath, 'utf8');
  const protocol = fs.readFileSync(protocolPath, 'utf8');

  assert.match(app, /explainAfterEmptyStream=/);
  assert.match(app, /empty_stream/);
  assert.match(app, /streamResumeDraftRef/);
  assert.match(
    app,
    /streaming\.completionStopReason === "cancelled" \|\| Boolean\(streaming\.streamError\?\.trim\(\)\)/,
  );
  assert.match(composer, /explainAfterEmptyStream/);
  assert.match(composer, /readyAfterEmptyStreamLabel/);
  assert.match(composer, /afterEmptyStreamReadyLabel/);
  assert.match(composer, /空流。草稿已保留，可再发送重试/);
  assert.match(protocol, /Empty stream: the model sent no content/);
  assert.match(protocol, /空流：模型没有返回任何内容/);
  // empty_stream stays distinct from empty_response copy
  assert.match(protocol, /normalizedCategory === "empty_stream"/);
  assert.match(protocol, /normalizedCategory === "empty_response"/);
});
