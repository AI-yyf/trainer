'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const coachDefaultsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'coachDefaults.js',
);

const {
  matchesSavedCoachDefaults,
  sameCoachDefaults,
  sameCustomSkills,
} = require(coachDefaultsModulePath);

const NEUTRAL = {
  memoryScope: 'personal',
  workingSetMode: 'balanced',
  reviewCadence: 'steady',
  reviewReminderMode: 'due',
  workspaceMemoryToggles: { decisions: true, patterns: true, resources: true },
};

const fullSaved = { ...NEUTRAL };

const sampleSkill = {
  id: 'custom:recap',
  trigger: '$recap',
  title: 'Recap',
  detail: '',
  prompt: 'Summarize this session into five bullets.',
  keywords: ['recap'],
};

test('a payload matching the saved snapshot is deduplicated', () => {
  assert.equal(matchesSavedCoachDefaults({ ...NEUTRAL }, fullSaved), true);
});

test('a missing snapshot never blocks a save', () => {
  assert.equal(matchesSavedCoachDefaults({ ...NEUTRAL }, undefined), false);
});

test('a snapshot without customSkills does not swallow a new skill save', () => {
  // Regression: the field is new, so existing workspaces have saved snapshots
  // that lack it. Adding the first skill must reach the server.
  assert.equal(
    matchesSavedCoachDefaults({ ...NEUTRAL, customSkills: [sampleSkill] }, fullSaved),
    false,
  );
});

test('an absent customSkills field still matches an empty payload', () => {
  assert.equal(matchesSavedCoachDefaults({ ...NEUTRAL, customSkills: [] }, fullSaved), true);
  assert.equal(matchesSavedCoachDefaults({ ...NEUTRAL }, fullSaved), true);
});

test('a differing customSkills list blocks dedup', () => {
  const saved = { ...NEUTRAL, customSkills: [sampleSkill] };
  const changed = { ...sampleSkill, prompt: 'Different prompt.' };
  assert.equal(
    matchesSavedCoachDefaults({ ...NEUTRAL, customSkills: [changed] }, saved),
    false,
  );
  assert.equal(matchesSavedCoachDefaults({ ...NEUTRAL, customSkills: [] }, saved), false);
});

test('a snapshot field missing on the server matches only the neutral payload value', () => {
  // Sparse snapshots must not swallow real changes: a non-neutral value for a
  // field the server does not know is new information and must save.
  assert.equal(
    matchesSavedCoachDefaults({ ...NEUTRAL, memoryScope: 'project' }, { ...NEUTRAL, memoryScope: undefined }),
    false,
  );
  assert.equal(
    matchesSavedCoachDefaults({ ...NEUTRAL }, { ...NEUTRAL, memoryScope: undefined }),
    true,
  );
});

test('sparse toggle snapshots behave the same way', () => {
  const saved = { ...NEUTRAL, workspaceMemoryToggles: { decisions: true } };
  assert.equal(
    matchesSavedCoachDefaults(
      { ...NEUTRAL, workspaceMemoryToggles: { decisions: true, patterns: false, resources: true } },
      saved,
    ),
    false,
  );
  assert.equal(matchesSavedCoachDefaults({ ...NEUTRAL }, saved), true);
});

test('sameCoachDefaults treats missing fields as their neutral values', () => {
  assert.equal(sameCoachDefaults({ ...NEUTRAL }, {}), true);
  assert.equal(
    sameCoachDefaults({ ...NEUTRAL, customSkills: [sampleSkill] }, { customSkills: [sampleSkill] }),
    true,
  );
  assert.equal(
    sameCoachDefaults({ ...NEUTRAL, customSkills: [sampleSkill] }, { ...NEUTRAL }),
    false,
  );
});

test('sameCustomSkills normalizes absence to an empty list', () => {
  assert.equal(sameCustomSkills(undefined, []), true);
  assert.equal(sameCustomSkills([sampleSkill], undefined), false);
});
