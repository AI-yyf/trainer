'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const copyPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'copy.ts');

test('a missing workspace root preserves a typed goal instead of disabling the Coach input', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const copy = fs.readFileSync(copyPath, 'utf8');

  assert.match(
    source,
    /const canCaptureGoalBeforeWorkspaceSetup =\s*trainerWorkspaceAdmission\?\.status === "root-missing";/,
  );
  assert.match(
    source,
    /if \(canCaptureGoalBeforeWorkspaceSetup && normalizedDraft\) \{\s*openWorkspaceAdmission\(\);\s*setOperationMessage\(\{\s*tone: "info",\s*message: t\.workspaceAdmissionGoalSaved,\s*\}\);\s*return;/,
  );
  assert.match(
    source,
    /disabled=\{workspaceSessionBlocked && !canCaptureGoalBeforeWorkspaceSetup\}/,
  );
  assert.match(
    source,
    /submitDisabled=\{\s*canCaptureGoalBeforeWorkspaceSetup\s*\?\s*!normalizedDraft\s*\|\|\s*imageAttachmentSendBlocked\s*:\s*composerSendBlocked\s*\|\|\s*imageAttachmentSendBlocked\s*\}/,
  );
  assert.match(copy, /\| "workspaceAdmissionGoalSaved"/);
  assert.equal((copy.match(/workspaceAdmissionGoalSaved:/g) ?? []).length, 8);
});
