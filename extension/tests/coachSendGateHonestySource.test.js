'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const composerSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);

test('coach send gate disables submit when blocked and surfaces the reason', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const composerSource = fs.readFileSync(composerSourcePath, 'utf8');

  assert.match(appSource, /const composerSendBlocked = sendBlocked;/);
  assert.match(appSource, /const composerSubmitBlockedReason =/);
  assert.match(appSource, /submitBlockedReason=\{composerSubmitBlockedReason\}/);
  assert.match(
    appSource,
    /imageAttachmentBlockedReason \?\?\s*\(sendBlocked\s*\?[\s\S]*providerRecoveryReason/,
  );
  assert.match(
    composerSource,
    /resolvedSubmitBlockedReason && \(submitDisabled \|\| stagedAttachments\.length > 0\)/,
  );
  assert.match(
    composerSource,
    /submitDisabled && \(hasSubmissionContent \|\| Boolean\(resolvedSubmitBlockedReason\)\)/,
  );
});
