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

test('single scene and same-workspace cards do not promote', () => {
  assert.equal(
    shouldPromoteTransferableSkill({
      concept: 'tool calling',
      workspaceId: 'project-a',
      outcomeSuccess: true,
      existingScenes: [],
    }),
    false,
  );
  assert.equal(
    shouldPromoteTransferableSkill({
      concept: 'tool calling',
      workspaceId: 'project-a',
      currentSceneKey: 'default',
      outcomeSuccess: true,
      existingScenes: [{ workspaceId: 'project-a', sceneKey: 'default' }],
    }),
    false,
  );
});

test('second workspace can promote; same-workspace leftover scene cannot', () => {
  assert.equal(
    shouldPromoteTransferableSkill({
      concept: 'tool calling',
      workspaceId: 'project-b',
      currentSceneKey: 'default',
      outcomeSuccess: true,
      existingScenes: [{ workspaceId: 'project-a', sceneKey: 'default' }],
    }),
    true,
  );
  const secondScene = resolveSkillSceneKey({
    transferSourceContext: 'billing route',
    transferTargetContext: 'docs sandbox',
    transferEvidenceSummary: 'Applied the same guard in a second task.',
  });
  assert.match(secondScene, /^transfer:/);
  assert.equal(
    shouldPromoteTransferableSkill({
      concept: 'response model',
      workspaceId: 'project-a',
      currentSceneKey: secondScene,
      outcomeSuccess: true,
      existingScenes: [{ workspaceId: 'project-a', sceneKey: 'default' }],
    }),
    false,
  );
});

test('bare transfer ids without evidence stay fail-closed', () => {
  assert.equal(
    resolveSkillSceneKey({
      transferSourceWorkspaceId: 'project-a',
      transferTargetWorkspaceId: 'project-b',
    }),
    'default',
  );
  assert.equal(
    shouldPromoteTransferableSkill({
      concept: 'tool calling',
      workspaceId: 'project-b',
      outcomeSuccess: true,
      transferSourceWorkspaceId: 'project-a',
      transferTargetWorkspaceId: 'project-b',
      existingScenes: [],
    }),
    false,
  );
});

test('copy never claims global mastery from one scene', () => {
  const awaiting = buildTransferSkillStateRecord({
    concept: 'tool calling',
    scenes: [{ workspaceId: 'project-a', sceneKey: 'default' }],
    language: 'en-US',
  });
  assert.equal(awaiting.state, 'awaiting_second_scene');
  assert.equal(/mastered|global mastery/i.test(awaiting.why), false);

  const transferable = buildTransferSkillStateRecord({
    concept: 'tool calling',
    scenes: [
      { workspaceId: 'project-a', sceneKey: 'default' },
      { workspaceId: 'project-b', sceneKey: 'default' },
    ],
    language: 'en-US',
  });
  assert.equal(transferable.state, 'transferable');
  assert.equal(/mastered/i.test(transferable.why), false);
});

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
