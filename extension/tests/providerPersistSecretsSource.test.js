'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('webview layout persist strips provider snapshot secrets', () => {
  const stateSource = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'app', 'useWorkbenchState.ts'),
    'utf8',
  );
  assert.match(
    stateSource,
    /previewProviderConfig:\s*stripProviderSnapshotSecrets\(data\.providerConfig\)/,
  );
});

test('sanitizeHostFailureMessage never forwards host error prose', () => {
  const appSource = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx'),
    'utf8',
  );
  // The store-side sanitizeOperationFailureMessage moved to the governance
  // module; the host-status chain stays in App and ends at the next top-level
  // declaration after it.
  const start = appSource.indexOf('function sanitizeHostFailureMessage(');
  const end = appSource.indexOf('interface SettingsActionState', start);
  assert.ok(start >= 0 && end > start);
  const sanitizer = appSource.slice(start, end);
  assert.doesNotMatch(sanitizer, /message:\s*message\.payload\.message/);
  assert.match(sanitizer, /providerRecoveryMessage\(language\)/);
  assert.match(sanitizer, /recoverableFailureMessage\("operation", language\)/);
});
