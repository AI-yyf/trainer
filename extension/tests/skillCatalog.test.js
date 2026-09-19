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
  mergeSkillCatalog,
  normalizeCustomSkillTrigger,
  normalizeSkillQuery,
  normalizeTrainerCustomSkill,
  normalizeTrainerCustomSkills,
  parseTrainerSkillShare,
  serializeTrainerSkillShare,
  trainerSkillCatalog,
  trainerSkillTriggerToken,
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

test('normalizeCustomSkillTrigger accepts bare and prefixed triggers', () => {
  assert.equal(normalizeCustomSkillTrigger('$review'), '$review');
  assert.equal(normalizeCustomSkillTrigger('review'), '$review');
  assert.equal(normalizeCustomSkillTrigger('  $My-Thing  '), '$My-Thing');
  assert.equal(normalizeCustomSkillTrigger('$'), undefined);
  assert.equal(normalizeCustomSkillTrigger('with space'), undefined);
  assert.equal(normalizeCustomSkillTrigger(42), undefined);
});

test('normalizeTrainerCustomSkill requires a trigger and prompt', () => {
  assert.equal(normalizeTrainerCustomSkill({ trigger: '$x' }), undefined);
  assert.equal(normalizeTrainerCustomSkill({ prompt: 'do it' }), undefined);

  const skill = normalizeTrainerCustomSkill({
    trigger: 'retro',
    title: 'Retro notes',
    prompt: 'Summarize what I learned this session',
    detail: 'Session recap',
    keywords: ['recap', 'summary'],
  });
  assert.equal(skill?.trigger, '$retro');
  assert.equal(skill?.id, 'custom:retro');
  assert.equal(skill?.title, 'Retro notes');
  assert.deepEqual(skill?.keywords, ['recap', 'summary']);
});

test('normalizeTrainerCustomSkills dedupes triggers and caps the list', () => {
  const skills = normalizeTrainerCustomSkills([
    { trigger: '$a', prompt: 'first' },
    { trigger: '$A', prompt: 'duplicate' },
    { trigger: '$b', prompt: 'second' },
    { trigger: '', prompt: 'invalid' },
  ]);

  assert.equal(skills.length, 2);
  assert.equal(skills[0]?.prompt, 'first');
  assert.equal(skills[1]?.trigger, '$b');
});

test('mergeSkillCatalog appends custom skills without shadowing built-ins', () => {
  const merged = mergeSkillCatalog([
    { id: 'custom:mine', trigger: '$mine', title: 'Mine', detail: '', prompt: 'custom prompt', keywords: [] },
    { id: 'custom:explain', trigger: '$explain', title: 'Shadow', detail: '', prompt: 'shadow', keywords: [] },
  ]);

  const mine = merged.find((skill) => skill.trigger === '$mine');
  assert.equal(mine?.commandId, 'trainer.session.sendStreamMessage');
  assert.equal(mine?.prompt?.['en-US'], 'custom prompt');

  const explain = merged.filter((skill) => skill.trigger === '$explain');
  assert.equal(explain.length, 1);
  assert.equal(explain[0]?.id, 'explain-principle');
});

test('skill share payload round-trips through serialize and parse', () => {
  const skill = normalizeTrainerCustomSkill({
    trigger: '$review-tests',
    title: 'Review tests',
    prompt: 'Review my test coverage and name the weakest assertions.',
    keywords: ['tests'],
  });
  const blob = serializeTrainerSkillShare(skill);

  const parsed = parseTrainerSkillShare(blob);
  assert.equal(parsed?.trigger, '$review-tests');
  assert.equal(parsed?.prompt, 'Review my test coverage and name the weakest assertions.');

  assert.equal(parseTrainerSkillShare('{"_type":"other"}'), undefined);
  assert.equal(parseTrainerSkillShare('not json'), undefined);
  assert.equal(parseTrainerSkillShare('{"_type":"trainer_skill_share","trigger":"$x"}'), undefined);
});

test('trainerSkillTriggerToken returns only the leading $token of a draft', () => {
  assert.equal(trainerSkillTriggerToken('$explain'), '$explain');
  // Arguments after the trigger are not part of the lookup token.
  assert.equal(trainerSkillTriggerToken('$explain my last session'), '$explain');
  assert.equal(trainerSkillTriggerToken('  $review  file.ts  '), '$review');
  assert.equal(trainerSkillTriggerToken('$'), '$');
  assert.equal(trainerSkillTriggerToken('plain message'), undefined);
  assert.equal(trainerSkillTriggerToken('   '), undefined);
});

test('filtering on the trigger token keeps the resolved skill visible with args', () => {
  // The deck must keep confirming "$explain" while the user types arguments —
  // the full-draft query would score every catalog entry to zero and offer to
  // create a colliding skill.
  const skills = filterTrainerSkills(
    trainerSkillTriggerToken('$explain focus on the diff'),
    createContext(),
    10,
  );
  assert.equal(skills[0]?.trigger, '$explain');
});
