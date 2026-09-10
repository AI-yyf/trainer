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

test('coach composer explains mid-tool abort send state for same-session resume', () => {
  const app = fs.readFileSync(appPath, 'utf8');
  const composer = fs.readFileSync(composerPath, 'utf8');

  assert.match(app, /abortedDuringToolUse/);
  assert.match(app, /explainAfterAbortMidTool=/);
  assert.match(app, /activity\.status === "running"/);
  assert.match(composer, /explainAfterAbortMidTool/);
  assert.match(composer, /readyAfterAbortMidToolLabel/);
  assert.match(composer, /工具调用中已中止/);
  assert.match(
    composer,
    /Stopped mid tool-call\. Draft restored — send again to continue this session/,
  );
});
