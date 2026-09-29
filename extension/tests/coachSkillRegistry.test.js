'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const sharedSrc = path.resolve(__dirname, '..', '..', 'shared', 'src');
const tsc = path.resolve(__dirname, '..', '..', 'extension', 'node_modules', 'typescript', 'bin', 'tsc');

let mod;
test('setup', () => {
  const outDir = require('node:fs').mkdtempSync(require('node:os').tmpdir() + '/coach-skill-reg-');
  require('node:child_process').execFileSync(process.execPath, [
    tsc,
    path.join(sharedSrc, 'coachSkillRegistry.ts'),
    path.join(sharedSrc, 'agentSkill.ts'),
    '--outDir', outDir,
    '--module', 'commonjs', '--target', 'es2022',
    '--skipLibCheck', '--esModuleInterop',
    '--moduleResolution', 'node',
  ]);
  mod = require(path.join(outDir, 'coachSkillRegistry.js'));
});

function makeRecord(name, overrides = {}) {
  return {
    name,
    description: `Test skill: ${name}`,
    source: 'user',
    lifecycle: 'active',
    version: '1.0.0',
    path: `/skills/${name}`,
    trainerEnhanced: false,
    hasScripts: false,
    trusted: true,
    updatedAt: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

test('register + query', () => {
  const reg = new mod.CoachSkillRegistry();
  reg.register(makeRecord('ppo-coach'), () => '# PPO');
  reg.register(makeRecord('git-coach'), () => '# Git');

  assert.equal(reg.size(), 2);
  const results = reg.query({ searchText: 'ppo' });
  assert.equal(results.length, 1);
  assert.equal(results[0].name, 'ppo-coach');
});

test('duplicate name: higher lifecycle wins', () => {
  const reg = new mod.CoachSkillRegistry();
  reg.register(makeRecord('test', { lifecycle: 'draft' }), () => 'draft');
  reg.register(makeRecord('test', { lifecycle: 'active', updatedAt: '2026-01-02T00:00:00Z' }), () => 'active');
  const results = reg.query({ lifecycle: 'active' });
  assert.equal(results.length, 1);
  assert.equal(results[0].lifecycle, 'active');
});

test('duplicate name: same lifecycle, newer timestamp wins', () => {
  const reg = new mod.CoachSkillRegistry();
  reg.register(makeRecord('test', { updatedAt: '2026-01-01T00:00:00Z' }), () => 'v1');
  reg.register(makeRecord('test', { updatedAt: '2026-01-02T00:00:00Z' }), () => 'v2');
  assert.equal(reg.get('test').record.updatedAt, '2026-01-02T00:00:00Z');
});

test('source filter', () => {
  const reg = new mod.CoachSkillRegistry();
  reg.register(makeRecord('a', { source: 'built-in' }), () => 'a');
  reg.register(makeRecord('b', { source: 'user' }), () => 'b');
  reg.register(makeRecord('c', { source: 'generated' }), () => 'c');
  assert.equal(reg.query({ source: 'built-in' }).length, 1);
  assert.equal(reg.query({ source: 'generated' }).length, 1);
  assert.equal(reg.query().length, 3);
});

test('isTrainerEnhanced checks coach skill-type or pedagogy metadata', () => {
  assert.equal(mod.isTrainerEnhanced({ 'trainer.skill-type': 'coach' }), true);
  assert.equal(mod.isTrainerEnhanced({ 'trainer.pedagogy': 'ref' }), true);
  assert.equal(mod.isTrainerEnhanced({ 'some.other': 'value' }), false);
  assert.equal(mod.isTrainerEnhanced(undefined), false);
});

test('hasExecutableScripts detects scripts/ references', () => {
  assert.equal(mod.hasExecutableScripts(['scripts/run.py']), true);
  assert.equal(mod.hasExecutableScripts(['references/knowledge.md']), false);
  assert.equal(mod.hasExecutableScripts([]), false);
});

test('loadBody uses lazy loader (Progressive Disclosure §八)', () => {
  const reg = new mod.CoachSkillRegistry();
  let bodyLoaded = false;
  reg.register(makeRecord('lazy'), () => {
    bodyLoaded = true;
    return '# Body';
  });
  // Discovery does NOT load the body
  assert.equal(bodyLoaded, false);
  // Only loadBody triggers the loader
  const body = reg.loadBody('lazy');
  assert.equal(body, '# Body');
  assert.equal(bodyLoaded, true);
});
