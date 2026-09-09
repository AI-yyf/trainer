'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const sharedPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'coachToolActivitySendState.ts');
const indexPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'index.ts');

test('App busyLabel prefers tool activity then thinking send state', () => {
  const app = fs.readFileSync(appPath, 'utf8');
  const shared = fs.readFileSync(sharedPath, 'utf8');
  const index = fs.readFileSync(indexPath, 'utf8');

  assert.match(index, /coachToolActivitySendState/);
  assert.match(shared, /describeCoachToolActivitySendBusy/);
  assert.match(shared, /describeCoachThinkingSendBusy/);
  assert.match(app, /describeCoachToolActivitySendBusy/);
  assert.match(app, /streaming\.agentActivity/);
  assert.match(app, /describeCoachThinkingSendBusy/);
});
