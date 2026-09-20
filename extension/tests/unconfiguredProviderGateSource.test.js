'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const sharedStatusPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'providerStatus.ts');
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('unconfigured providers stay blocked while a saved connection may revalidate on real send', () => {
  const status = fs.readFileSync(sharedStatusPath, 'utf8');
  const app = fs.readFileSync(appPath, 'utf8');

  const missingTest = status.indexOf('if (!provider.lastTestResult) {');
  assert.ok(missingTest >= 0, 'expected missing lastTestResult branch');
  const missingBlock = status.slice(missingTest, missingTest + 280);
  assert.match(missingBlock, /blocked:\s*true/);
  assert.match(missingBlock, /status:\s*'blocked_error'/);
  assert.doesNotMatch(missingBlock, /blocked:\s*false/);

  assert.match(status, /if \(!provider\.configured \|\| transportMissing\) \{[\s\S]*?blocked:\s*true/);
  assert.match(status, /if \(!provider\.apiKeyConfigured\) \{[\s\S]*?blocked:\s*true/);

  assert.match(app, /function providerProofCanBeRevalidatedBySend\(/);
  assert.match(
    app,
    /if \(!provider\.configured \|\| !provider\.apiKeyConfigured \|\| provider\.modelListStatus === "error"\) \{\s*return false;/,
  );
  assert.match(
    app,
    /const providerCanCoachNow =\s*providerTransportConnected && \(!providerSendState\.blocked \|\| providerProofMayRevalidateOnSend\);/,
  );
  const sendTurn = app.slice(app.indexOf('const sendTurn = ('), app.indexOf('const handleBrowserUploads'));
  assert.match(
    sendTurn,
    /if \(!providerCanCoachNow \|\| providerBlockReason \|\| capabilitySendBlocked\) \{/,
  );
  assert.match(sendTurn, /return;/);
  assert.match(app, /if \(!providerCanCoachNow \|\| providerBlockReason\) \{[\s\S]*?requestTrainingCardGeneration/);
});
