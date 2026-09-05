'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('formal training handoff steps persist before opening Coach', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const trainingCoachBridge = useMemo\(/);
  assert.match(source, /buildTrainingCoachBridge\(\{/);
  assert.match(
    source,
    /const handleResumeTrainingInCoach = useCallback\(\(\) => \{[\s\S]*?if \(trainingHandoffReflectionRequired\) \{[\s\S]*?setTrainingComposerRoute\("card"\);[\s\S]*?return;[\s\S]*?if \(trainingHandoffReturnRequired && trainingState\?\.selectedCardId\) \{[\s\S]*?void handleSubmitTrainingEvidence\(""\)\.catch/,
  );
  assert.match(
    source,
    /if \(pending\.phase === "return"\) \{\s*setActiveView\("coach"\);\s*setComposerDraft\(composeTrainingCoachBridgeDraft\(trainingCoachBridge\)\);/,
  );
  assert.match(
    source,
    /const trainingCoachActionLabel = trainingHandoffReflectionRequired\s*\?\s*t\.trainingRecordStep\s*:\s*trainingHandoffReturnRequired\s*\?\s*t\.trainingReturnToCoach\s*:\s*trainingComposerPhase === "return"\s*\?\s*t\.trainingReturnToCoach\s*:\s*trainingCoachBridge\.ctaLabel;/,
  );
  assert.match(source, /onClick=\{handleResumeTrainingInCoach\}/);
});

test('practice return evidence uses the authoritative response status for both outcomes', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /pending\.resolve\(message\.payload\.data\)/);
  assert.match(source, /const response = await requestTrainingPersistence\(trainerCommands\.trainingPracticeReturn/);
  assert.match(source, /selected_card_status/);
  assert.match(source, /authoritativePracticeStatus === "blocked"/);
  assert.match(source, /authoritativePracticeStatus === "active"/);
  assert.match(source, /!authoritativePracticeStatus && trainingCardVerified/);
});

test('training return and evidence adopt do not mint a plan, card, or task turn', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingCommandsPath = path.resolve(
    __dirname,
    '..',
    'src',
    'commands',
    'trainingCommands.ts',
  );
  const trainingCommands = fs.readFileSync(trainingCommandsPath, 'utf8');
  const returnSubmit = appSource.slice(
    appSource.indexOf('const shouldSubmitTrainingHandoffReturn'),
    appSource.indexOf('const practiceResultMode'),
  );
  assert.match(
    returnSubmit,
    /await requestTrainingPersistence\(trainerCommands\.trainingReturn,/,
  );
  assert.doesNotMatch(returnSubmit, /sendTurn\(/);
  assert.doesNotMatch(returnSubmit, /trainerCommands\.generatePlan|formalPlanMutation:\s*true/);
  const returnStart = appSource.indexOf('if (pending.phase === "return")');
  const returnComplete = appSource.slice(
    returnStart,
    appSource.indexOf('setComposerDraft("");', returnStart),
  );
  assert.match(returnComplete, /setActiveView\("coach"\)/);
  assert.doesNotMatch(returnComplete, /sendTurn\(/);
  assert.doesNotMatch(returnComplete, /trainerCommands\.generatePlan/);
  const adoptStart = appSource.indexOf('if (action === "adopt_evidence")');
  const adoptBlock = appSource.slice(adoptStart, appSource.indexOf('if (action === "open_training")', adoptStart));
  assert.match(adoptBlock, /commandId: trainerCommands\.evidenceAdopt/);
  assert.doesNotMatch(adoptBlock, /sendTurn\(/);
  assert.doesNotMatch(adoptBlock, /trainerCommands\.generatePlan|intent:\s*"next_task"/);
  const adoptCommand = trainingCommands.slice(
    trainingCommands.indexOf('export async function evidenceAdoptCommand'),
    trainingCommands.indexOf('export async function evidenceRejectCommand'),
  );
  assert.match(adoptCommand, /\/evidence\/adopt/);
  assert.match(adoptCommand, /rehydrateTrainingSummary/);
  assert.doesNotMatch(adoptCommand, /\/plan\/generate|\/task\/next|sendTurn/);
  const returnCommand = trainingCommands.slice(
    trainingCommands.indexOf('export async function trainingReturnCommand'),
    trainingCommands.indexOf('export async function trainingReliabilityControlCommand'),
  );
  assert.match(returnCommand, /\/training\/return/);
  assert.match(returnCommand, /rehydrateTrainingSummary/);
  assert.doesNotMatch(returnCommand, /\/plan\/generate|\/task\/next/);
});
