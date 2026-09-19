'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const packagePath = path.resolve(__dirname, '..', 'package.json');
const managerPath = path.resolve(__dirname, '..', 'src', 'core', 'sidecarProcessManager.ts');

test('public learning-material research is explicit, configurable, and passed to the sidecar', () => {
  const manifest = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
  const property = manifest.contributes.configuration.properties['trainer.research.networkEnabled'];
  const source = fs.readFileSync(managerPath, 'utf8');

  assert.equal(property.type, 'boolean');
  assert.equal(property.default, true);
  assert.match(property.description, /public web sources/i);
  assert.match(source, /get<boolean>\('research\.networkEnabled', true\)/);
  assert.match(source, /TRAINER_ENABLE_NETWORK_FETCH:/);
});
