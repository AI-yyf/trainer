'use strict';

const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const governanceModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'trainingExecutionGovernance.js',
);

test('next-hop-only reflection and return reuse the execution phase that drives the training composer', () => {
  const { deriveTrainingExecutionState } = require(governanceModulePath);
  const reflection = deriveTrainingExecutionState({
    cardType: 'practice',
    selectedCardStatus: 'active',
    latestTrainingNextHopStatus: 'reflection_required',
  });
  const returnFlow = deriveTrainingExecutionState({
    cardType: 'practice',
    selectedCardStatus: 'active',
    latestTrainingNextHopStatus: 'return_required',
  });

  assert.equal(reflection.composerPhase, 'reflect');
  assert.equal(returnFlow.composerPhase, 'return');

  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  assert.match(appSource, /const trainingComposerPhase = trainingExecutionState\.composerPhase;/);
  assert.match(
    appSource,
    /normalizedTrainingNextHopStatus === "reflection_required"/,
  );
  assert.match(appSource, /normalizedTrainingNextHopStatus === "return_required"/);
});

test('reflection and return phases keep their dedicated placeholder and persistence barrier', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    appSource,
    /trainingComposerReturnMode\s*\?\s*trainingHandoffComposerTextCopy\.returnPlaceholder\s*:\s*trainingComposerReflectMode\s*\?\s*trainingHandoffComposerTextCopy\.reflectPlaceholder/s,
  );
  assert.match(
    appSource,
    /trainingComposerReflectMode[\s\S]*?trainingHandoffReflectionRequired[\s\S]*?await requestTrainingPersistence\(trainerCommands\.trainingReflect/s,
  );
  assert.match(
    appSource,
    /trainingComposerReturnMode[\s\S]*?trainingHandoffReturnRequired[\s\S]*?await requestTrainingPersistence\(trainerCommands\.trainingReturn/s,
  );
});
