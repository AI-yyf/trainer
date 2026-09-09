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

test('coach composer keeps between-turn send state explainable after conversation turns', () => {
  const app = fs.readFileSync(appPath, 'utf8');
  const composer = fs.readFileSync(composerPath, 'utf8');

  assert.match(app, /explainBetweenTurns=/);
  assert.match(app, /data\.conversation\.length > 0/);
  assert.match(composer, /explainBetweenTurns/);
  assert.match(composer, /readyNextTurnLabel/);
  assert.match(composer, /readyIdleLabel/);
  assert.match(composer, /betweenTurnReadyLabel/);
  assert.match(composer, /data-send-state=\{sendState\}/);
  assert.match(
    composer,
    /explainBetweenTurns && sendState === "ready"[\s\S]*readyNextTurnLabel/,
  );
});
