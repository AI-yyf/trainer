'use strict';

/**
 * The subject profiles must be inside every package that can start a sidecar.
 *
 * They used to live at the repository root, outside everything that ships, so
 * a packaged Trainer loaded none and every language-learning subject fell back
 * to the code profile. The package verifier now refuses such a package.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const verifyPackageModulePath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'verify-package.mjs',
);

async function loadVerifier() {
  return import(verifyPackageModulePath);
}

function writeProfiles(directory, names) {
  fs.mkdirSync(directory, { recursive: true });
  for (const name of names) {
    fs.writeFileSync(path.join(directory, `${name}.profile.json`), `{"id": "${name}"}\n`);
  }
}

test('the verifier lists the five subjects a package must teach', async () => {
  const { SHIPPED_SUBJECT_PROFILES } = await loadVerifier();
  assert.deepEqual([...SHIPPED_SUBJECT_PROFILES], [
    'code',
    'literature',
    'french-writing',
    'german-grammar',
    'japanese-learning',
  ]);
});

test('a package with the profiles in both layouts passes', async (t) => {
  const { verifySubjectProfilesShipped, SHIPPED_SUBJECT_PROFILES } = await loadVerifier();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-profiles-ok-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const sourceServer = path.join(root, 'bundled', 'server');
  writeProfiles(path.join(sourceServer, 'app', 'training', 'profiles'), SHIPPED_SUBJECT_PROFILES);
  // PyInstaller's onedir layout: the executable beside an `_internal` tree.
  const binary = path.join(root, 'bundled', 'bin', 'darwin-arm64', 'trainer-sidecar');
  fs.mkdirSync(path.dirname(binary), { recursive: true });
  fs.writeFileSync(binary, '#!/usr/bin/env placeholder\n');
  fs.mkdirSync(path.join(path.dirname(binary), '_internal', 'app'), { recursive: true });
  writeProfiles(
    path.join(path.dirname(binary), '_internal', 'app', 'training', 'profiles'),
    SHIPPED_SUBJECT_PROFILES,
  );

  const report = verifySubjectProfilesShipped({ targetServerDir: sourceServer, bundledBinaryPath: binary });
  assert.deepEqual(report, { ok: true, errors: [] });
});

test('the layout that shipped before the fix is refused, naming what is missing', async (t) => {
  const { verifySubjectProfilesShipped, SHIPPED_SUBJECT_PROFILES } = await loadVerifier();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-profiles-missing-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  // The repository-root `profiles/` folder of the old layout: outside the bundle.
  writeProfiles(path.join(root, 'profiles'), SHIPPED_SUBJECT_PROFILES);
  const sourceServer = path.join(root, 'bundled', 'server');
  fs.mkdirSync(path.join(sourceServer, 'app', 'training'), { recursive: true });
  const binary = path.join(root, 'bundled', 'bin', 'darwin-arm64', 'trainer-sidecar');
  // A frozen build that carries package data: the profiles must be in it too.
  fs.mkdirSync(path.join(path.dirname(binary), '_internal', 'app', 'training'), { recursive: true });
  fs.writeFileSync(binary, '#!/usr/bin/env placeholder\n');

  const report = verifySubjectProfilesShipped({ targetServerDir: sourceServer, bundledBinaryPath: binary });

  assert.equal(report.ok, false);
  assert.equal(report.errors.length, 10, 'every missing profile is named in both layouts');
  assert.match(report.errors[0], /Bundled sidecar source lacks the "code" subject profile \(app\/training\/profiles\/code\.profile\.json\)/);
  assert.ok(report.errors.some((message) => /frozen sidecar lacks the "japanese-learning" subject profile/.test(message)));
});

test('a frozen binary without package data is left to the binary manifest check', async (t) => {
  const { verifySubjectProfilesShipped, SHIPPED_SUBJECT_PROFILES } = await loadVerifier();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-profiles-stub-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const sourceServer = path.join(root, 'bundled', 'server');
  writeProfiles(path.join(sourceServer, 'app', 'training', 'profiles'), SHIPPED_SUBJECT_PROFILES);
  // A stand-in executable (as in packaging tests) has no PyInstaller tree.
  const binary = path.join(root, 'bundled', 'bin', 'win32-x64', 'trainer-sidecar.exe');
  fs.mkdirSync(path.dirname(binary), { recursive: true });
  fs.writeFileSync(binary, 'stub');

  const report = verifySubjectProfilesShipped({ targetServerDir: sourceServer, bundledBinaryPath: binary });
  assert.deepEqual(report, { ok: true, errors: [] });
});

test('an empty or truncated profile file does not count as shipped', async (t) => {
  const { verifySubjectProfilesShipped, SHIPPED_SUBJECT_PROFILES } = await loadVerifier();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-profiles-empty-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const sourceServer = path.join(root, 'bundled', 'server');
  const profiles = path.join(sourceServer, 'app', 'training', 'profiles');
  writeProfiles(profiles, SHIPPED_SUBJECT_PROFILES);
  fs.writeFileSync(path.join(profiles, 'german-grammar.profile.json'), '');

  const report = verifySubjectProfilesShipped({ targetServerDir: sourceServer });
  assert.equal(report.ok, false);
  assert.deepEqual(report.errors, ['Bundled sidecar source lacks the "german-grammar" subject profile (app/training/profiles/german-grammar.profile.json).']);
});

test('the real package verifier reports the profiles', async () => {
  const { verifyPackage } = await loadVerifier();
  const report = verifyPackage();
  assert.ok('subjectProfiles' in report, 'verifyPackage carries a subject-profiles verdict');
  assert.ok(Array.isArray(report.subjectProfiles.errors));
});
