'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const sharedStatusPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'providerStatus.ts');
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

/**
 * P0 redirect: the send-state vocabulary is now exactly three states
 * (ready / needs_configuration / request_failed). Missing configuration still
 * blocks sending — but historical test results and model-list states are
 * diagnostics only and never create a block.
 */
test('unconfigured or missing-key providers cannot send as a live coach', () => {
  const status = fs.readFileSync(sharedStatusPath, 'utf8');
  const app = fs.readFileSync(appPath, 'utf8');

  // Unconfigured/transport-missing and missing-key both produce a blocked
  // needs_configuration state; no lastTestResult gate exists at all.
  assert.match(status, /if \(!provider\.configured \|\| transportMissing\) \{[\s\S]*?blocked:\s*true/);
  assert.match(status, /status: 'needs_configuration',\s*reasonKind: 'missing_provider'/);
  assert.match(status, /if \(!provider\.apiKeyConfigured\) \{[\s\S]*?blocked:\s*true/);
  assert.match(status, /status: 'needs_configuration',\s*reasonKind: 'missing_api_key'/);
  // The historical gate is gone: no branch reads lastTestResult for blocking.
  assert.doesNotMatch(status, /if \(!provider\.lastTestResult\) \{[\s\S]{0,280}blocked:\s*true/);
  assert.doesNotMatch(status, /'blocked_error'|'degraded_error'|'warming'|'refreshing'/);

  // The sidecar connection pill is informational only: sending is gated by
  // provider configuration/health, never by transport state.
  assert.match(app, /const providerCanCoachNow = !providerSendState\.blocked;/);
  assert.doesNotMatch(app, /providerTransportConnected && !providerSendState/);
  const sendTurn = app.slice(app.indexOf('const sendTurn = ('), app.indexOf('const handleBrowserUploads'));
  assert.match(
    sendTurn,
    /if \(!providerCanCoachNow \|\| providerBlockReason \|\| capabilitySendBlocked\) \{/,
  );
  assert.match(sendTurn, /return;/);
  assert.match(app, /if \(!providerCanCoachNow \|\| providerBlockReason\) \{[\s\S]*?requestTrainingCardGeneration/);
});
