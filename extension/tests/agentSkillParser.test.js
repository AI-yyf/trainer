'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');

// Compile shared/src/agentSkill.ts to a temp CJS module for testing
const sharedRoot = path.resolve(__dirname, '..', '..', 'shared', 'src');
const tsPath = path.join(sharedRoot, 'agentSkill.ts');
const tsc = path.resolve(__dirname, '..', '..', 'extension', 'node_modules', 'typescript', 'bin', 'tsc');

let mod;
test('setup', () => {
  const outDir = require('node:fs').mkdtempSync(require('node:os').tmpdir() + '/agent-skill-');
  require('node:child_process').execFileSync(process.execPath, [
    tsc, tsPath, '--outDir', outDir,
    '--module', 'commonjs', '--target', 'es2022', '--skipLibCheck', '--declaration', 'false',
  ]);
  mod = require(path.join(outDir, 'agentSkill.js'));
});

const VALID_FM = `---
name: ppo-coach
description: Teaches PPO concepts, implementation, debugging, and transfer through evidence-based guided practice. Use when learning, implementing, debugging, or reviewing PPO.
---

# PPO Coach

## Purpose

Teach PPO from fundamentals to transfer.

## Common misconceptions

Advantage normalization is not reward normalization.
`;

test('parse valid SKILL.md', () => {
  const result = mod.parseSkillMd(VALID_FM, 'ppo-coach');
  assert.equal(result.errors.length, 0);
  assert.equal(result.skill.frontmatter.name, 'ppo-coach');
  assert.ok(result.skill.frontmatter.description.includes('PPO'));
  assert.ok(result.skill.body.includes('# PPO Coach'));
  assert.ok(result.skill.body.includes('Advantage normalization'));
});

test('reject missing frontmatter', () => {
  const result = mod.parseSkillMd('# No frontmatter\n');
  assert.equal(result.errors.length, 1);
  assert.match(result.errors[0].message, /frontmatter/);
});

test('reject invalid name (uppercase)', () => {
  const content = `---\nname: PPO-Coach\ndescription: Test\n---\nbody`;
  const result = mod.parseSkillMd(content);
  assert.ok(result.errors.some((e) => e.field === 'name'));
});

test('reject missing description', () => {
  const content = `---\nname: test-skill\n---\nbody`;
  const result = mod.parseSkillMd(content);
  assert.ok(result.errors.some((e) => e.field === 'description'));
});

test('reject too-long description', () => {
  const longDesc = 'x'.repeat(1025);
  const content = `---\nname: test\ndescription: ${longDesc}\n---\nbody`;
  const result = mod.parseSkillMd(content);
  assert.ok(result.errors.some((e) => e.field === 'description'));
});

test('preserve unknown metadata for round-trip', () => {
  const content = `---\nname: test\ndescription: Test skill\nmetadata:\n  trainer.version: "1.0"\n  some-client.foo: "bar"\n---\nbody`;
  const result = mod.parseSkillMd(content);
  assert.equal(result.skill.frontmatter.metadata['some-client.foo'], 'bar');
  assert.equal(result.skill.unknownMetadata['some-client.foo'], 'bar');
  assert.equal(result.skill.frontmatter.metadata['trainer.version'], '1.0');
});

test('resolve references from body', () => {
  const content = `---\nname: test\ndescription: Test\n---\nSee [misconceptions](references/misconceptions.md) and [practice](references/practice.md).`;
  const result = mod.parseSkillMd(content);
  assert.deepEqual(result.skill.references, ['references/misconceptions.md', 'references/practice.md']);
});

test('serialize round-trip preserves name and description', () => {
  const parse = mod.parseSkillMd(VALID_FM, 'ppo-coach');
  const serialized = mod.serializeSkillMd(parse.skill);
  const reparse = mod.parseSkillMd(serialized, 'ppo-coach');
  assert.equal(reparse.errors.length, 0);
  assert.equal(reparse.skill.frontmatter.name, 'ppo-coach');
  assert.equal(reparse.skill.frontmatter.description, parse.skill.frontmatter.description);
  assert.ok(reparse.skill.body.includes('PPO Coach'));
});
