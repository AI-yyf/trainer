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

test('coach composer keeps abort→resume send state explainable after cancel', () => {
  const app = fs.readFileSync(appPath, 'utf8');
  const composer = fs.readFileSync(composerPath, 'utf8');

  assert.match(app, /explainAfterAbort=/);
  assert.match(app, /completionStopReason === "cancelled"/);
  assert.match(composer, /explainAfterAbort/);
  assert.match(composer, /readyAfterAbortLabel/);
  assert.match(composer, /afterAbortReadyLabel/);
  assert.match(
    composer,
    /explainAfterAbort && \(sendState === "ready" \|\| sendState === "idle"\)/,
  );
  assert.match(composer, /已中止。草稿已恢复，再发送即可同会话续写/);
  assert.match(
    composer,
    /Stopped\. Draft restored — send again to continue this session/,
  );
});
