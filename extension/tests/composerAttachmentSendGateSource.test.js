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

test('image attachments keep staging separate from the verified send gate', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const composerSource = fs.readFileSync(composerSourcePath, 'utf8');

  assert.match(
    appSource,
    /const imageAttachmentSendBlocked =\s*composerAttachments\.length > 0 && !providerImageInputState\.supported;/,
  );
  assert.match(appSource, /submitDisabled=\{[\s\S]*composerSendBlocked \|\| imageAttachmentSendBlocked/);
  assert.match(
    appSource,
    /busy=\{\s*streaming\.isStreaming \|\|\s*isOperationReliabilityInFlight\(streaming\.reliabilityPhase\) \|\|\s*trainingPersistencePending\s*\}/,
  );
  assert.match(appSource, /operationReliabilityPhase: streaming\.reliabilityPhase,/);
  assert.match(appSource, /submitBlockedReason=\{imageAttachmentBlockedReason\}/);
  assert.match(appSource, /attachments=\{composerAttachments\}[\s\S]*onAttachmentsChange=\{setComposerAttachments\}/);
  assert.match(
    appSource,
    /const requiresVerifiedAgentTools = Boolean\(resolvedFormalPlanMutation\);[\s\S]*if \(requiresVerifiedAgentTools && !providerSupportsFormalPlanTools\)/,
  );
  assert.match(appSource, /providerImageInputState=\{providerImageInputState\}/);
  assert.match(composerSource, /submitBlockedReason\?: string;/);
  assert.match(composerSource, /const resolvedSubmitBlockedReason = submitBlockedReason\?\.trim\(\) \|\| "";/);
  assert.match(composerSource, /stagedAttachments\.length > 0 && resolvedSubmitBlockedReason/);
  assert.match(composerSource, /aria-describedby=\{\[[\s\S]*submitBlockedReasonId/);
});
