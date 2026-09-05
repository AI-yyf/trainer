'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const skillCatalogModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'skillCatalog.js',
);

const {
  filterTrainerSkills,
  normalizeSkillQuery,
  trainerSkillCatalog,
} = require(skillCatalogModulePath);

function createContext(overrides = {}) {
  return {
    activeView: 'coach',
    hasActiveFile: true,
    hasSelection: true,
    relatedFilesCount: 2,
    resourceCount: 1,
    ...overrides,
  };
}

test('normalizeSkillQuery trims the skill prefix and whitespace', () => {
  assert.equal(normalizeSkillQuery('   $review   file  '), 'review file');
});

test('filterTrainerSkills prefers review skills when the query asks for review', () => {
  const skills = filterTrainerSkills('$review', createContext({ hasSelection: false }), 4);

  assert.equal(skills[0]?.id, 'review-file');
  assert.ok(skills.some((skill) => skill.id === 'review-file'));
  assert.ok(skills.every((skill) => skill.id !== 'review-selection'));
});

test('filterTrainerSkills keeps selection review only when selection exists', () => {
  const visible = filterTrainerSkills('$review', createContext({ hasSelection: true }), 4);
  const hidden = filterTrainerSkills('$review', createContext({ hasSelection: false }), 4);

  assert.ok(visible.some((skill) => skill.id === 'review-selection'));
  assert.ok(!hidden.some((skill) => skill.id === 'review-selection'));
});

test('filterTrainerSkills surfaces practice and flash skills as first-class actions', () => {
  const practice = filterTrainerSkills('$practice', createContext(), 3);
  const flash = filterTrainerSkills('$flash', createContext(), 3);

  assert.equal(practice[0]?.id, 'practice-card');
  assert.equal(flash[0]?.id, 'flash-card');
});

test('filterTrainerSkills surfaces the deep lecture skill for theory walkthroughs', () => {
  const lecture = filterTrainerSkills('$lecture', createContext(), 3);

  assert.equal(lecture[0]?.id, 'deep-lecture');
});

test('filterTrainerSkills surfaces retrieval-first resource skills for reach and distill', () => {
  const reach = filterTrainerSkills('$reach', createContext(), 3);
  const distill = filterTrainerSkills('$distill', createContext(), 3);

  assert.equal(reach[0]?.id, 'reach-pass');
  assert.equal(distill[0]?.id, 'distill-sources');
});

test('filterTrainerSkills can find the source-map skill through map queries', () => {
  const skills = filterTrainerSkills('$map', createContext(), 3);

  assert.equal(skills[0]?.id, 'source-map');
});

test('filterTrainerSkills surfaces bundle and settings skills', () => {
  const bundle = filterTrainerSkills('$bundle', createContext(), 3);
  const settings = filterTrainerSkills('$settings', createContext(), 3);

  assert.equal(bundle[0]?.id, 'bundle-skill');
  assert.equal(settings[0]?.id, 'settings-audit');
});

test('GitHub-inspired built-in skills keep source metadata', () => {
  const reach = trainerSkillCatalog.find((skill) => skill.id === 'reach-pass');
  const map = trainerSkillCatalog.find((skill) => skill.id === 'source-map');
  const distill = trainerSkillCatalog.find((skill) => skill.id === 'distill-sources');
  const bundle = trainerSkillCatalog.find((skill) => skill.id === 'bundle-skill');

  assert.equal(reach?.source?.repo, 'https://github.com/Panniantong/agent-reach');
  assert.equal(reach?.source?.license, 'MIT');
  assert.equal(map?.source?.repo, 'https://github.com/heilcheng/awesome-agent-skills');
  assert.equal(distill?.source?.repo, 'https://github.com/microsoft/markitdown');
  assert.equal(bundle?.source?.repo, 'https://github.com/numman-ali/openskills');
});

test('filterTrainerSkills does not leak unrelated skills for an unknown trigger', () => {
  const skills = filterTrainerSkills('$does-not-exist', createContext(), 6);

  assert.deepEqual(skills, []);
});
