'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { readCopyModuleSource } = require('./helpers/copyModuleSource');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const copyPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'copy.ts');
const copyTypesPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'copyTypes.ts');

test('a missing workspace root preserves a typed goal instead of disabling the Coach input', () => {
  const source = readAppModuleSource();
  const copy = readCopyModuleSource();
  const copyTypes = fs.readFileSync(copyTypesPath, 'utf8');

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
  assert.match(copyTypes, /\| "workspaceAdmissionGoalSaved"/);
  assert.equal((copy.match(/workspaceAdmissionGoalSaved:/g) ?? []).length, 8);
});
