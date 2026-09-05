'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const trainerWorkspaceAdmissionModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'trainerWorkspaceAdmission.js',
);

test('workspace admission exposes a resumable pending reconciliation to the host', async () => {
  const { resolveTrainerWorkspaceAdmission } = loadWithVscodeMock(
    trainerWorkspaceAdmissionModulePath,
    { workspace: { workspaceFolders: [] }, window: {} },
  );
  const projectPath = path.resolve('C:\\trainer-workspace-tests\\current-project');
  const trainerWorkspace = {
    async toSnapshot() {
      return {
        rootPath: path.resolve('C:\\trainer-workspace-tests\\root'),
        workspaceReady: true,
        manifest: {
          rootId: 'root-admission',
          manifestRevision: 2,
          identityStatus: 'pending',
        },
      };
    },
    getManagedProvisioningPending(pathToLookUp) {
      assert.equal(pathToLookUp, projectPath);
      return {
        projectPath,
        workspaceRoot: path.resolve('C:\\trainer-workspace-tests\\root'),
        reason: 'Trainer adoption indexing was interrupted.',
        jobId: 'job-admission',
        state: 'waiting',
        availableActions: ['continue-waiting', 'retry', 'abandon'],
        updatedAt: '2026-07-31T12:00:00.000Z',
      };
    },
  };

  const admission = await resolveTrainerWorkspaceAdmission(trainerWorkspace, {
    workspaceFolder: projectPath,
  });

  assert.equal(admission.status, 'project-found');
  assert.deepEqual(admission.reconciliation, {
    reason: 'Trainer adoption indexing was interrupted.',
    jobId: 'job-admission',
    state: 'waiting',
    availableActions: ['continue-waiting', 'retry', 'abandon'],
    updatedAt: '2026-07-31T12:00:00.000Z',
  });
});
