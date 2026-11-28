// Restored behavioral regression test. Original file: extension/tests/transferSkillGovernanceShared.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Transfer skill orientation overlay on a ready plan and A/B demotion.
//
// Restoration: partial - 2 of 6 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "single scene and same-workspace cards do not promote"
//       fails at HEAD: shouldPromoteTransferableSkill is not a function
//   - "second workspace can promote; same-workspace leftover scene cannot"
//       fails at HEAD: shouldPromoteTransferableSkill is not a function
//   - "bare transfer ids without evidence stay fail-closed"
//       fails at HEAD: resolveSkillSceneKey is not a function
//   - "copy never claims global mastery from one scene"
//       fails at HEAD: buildTransferSkillStateRecord is not a function
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  applyTransferSkillToCoachOrientation,
  buildTransferSkillStateRecord,
  demoteTransferSkillAfterExcludedWorkspaces,
  resolveSkillSceneKey,
  shouldPromoteTransferableSkill,
} = require('../dist/shared/src/transferSkillGovernance.js');




test('orientation overlay keeps blockers and reflects transfer on ready plan', () => {
  const blocked = applyTransferSkillToCoachOrientation(
    {
      objectKind: 'provider',
      state: 'needs_setup',
      nextStep: 'Save and test a provider first.',
      advancedWhere: 'Settings · provider',
    },
    {
      concept: 'tool calling',
      state: 'transferable',
      sceneCount: 2,
      workspaceIds: ['project-a', 'project-b'],
      sceneKeys: ['default'],
      why: 'This skill has evidence in more than one scene.',
      next: 'Schedule a review, or apply it in a new challenge.',
    },
  );
  assert.equal(blocked.nextStep, 'Save and test a provider first.');

  const ready = applyTransferSkillToCoachOrientation(
    {
      objectKind: 'plan',
      state: 'ready',
      nextStep: 'Continue on this object, or check Plan.',
      advancedWhere: 'Plan · current step',
    },
    {
      concept: 'tool calling',
      state: 'transferable',
      sceneCount: 2,
      workspaceIds: ['project-a', 'project-b'],
      sceneKeys: ['default'],
      why: 'This skill has evidence in more than one scene.',
      next: 'Schedule a review, or apply it in a new challenge.',
    },
  );
  assert.equal(ready.nextStep, 'Schedule a review, or apply it in a new challenge.');
  assert.match(ready.advancedWhere, /more than one scene/);
});

test('excluding A demotes B transferable to awaiting_second_scene', () => {
  const transferable = {
    concept: 'Keep one auth check',
    state: 'transferable',
    sceneCount: 2,
    workspaceIds: ['workspace-a', 'workspace-b'],
    sceneKeys: ['default', 'workspace:workspace-a'],
    why: '"Keep one auth check" has evidence in more than one scene.',
    next: 'Schedule a review, or apply it in a new challenge.',
  };
  const demoted = demoteTransferSkillAfterExcludedWorkspaces(transferable, ['workspace-a'], {
    language: 'en-US',
    currentWorkspaceId: 'workspace-b',
  });
  assert.equal(demoted?.state, 'awaiting_second_scene');
  assert.notEqual(demoted?.state, 'transferable');
  assert.deepEqual(demoted?.workspaceIds, ['workspace-b']);
  assert.equal(demoted?.sceneCount, 1);
  assert.notEqual(demoted?.why, transferable.why);
  const untouched = demoteTransferSkillAfterExcludedWorkspaces(transferable, ['workspace-c']);
  assert.equal(untouched?.state, 'transferable');
  assert.deepEqual(untouched?.workspaceIds, ['workspace-a', 'workspace-b']);
});
