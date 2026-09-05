'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const coachTrainingViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'CoachTrainingView.tsx',
);
const trainingWorkbenchViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);
const practiceViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'practice',
  'CoachPracticeView.tsx',
);
const flashViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'flash',
  'CoachFlashView.tsx',
);
const guidedPacksSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'guidedTrainingScenarioPacks.ts',
);

test('training scenario packs stay localized and learn-first across training surfaces', () => {
  const coachTrainingViewSource = fs.readFileSync(coachTrainingViewSourcePath, 'utf8');
  const trainingWorkbenchViewSource = fs.readFileSync(trainingWorkbenchViewSourcePath, 'utf8');
  const practiceViewSource = fs.readFileSync(practiceViewSourcePath, 'utf8');
  const flashViewSource = fs.readFileSync(flashViewSourcePath, 'utf8');
  const guidedPacksSource = fs.readFileSync(guidedPacksSourcePath, 'utf8');

  assert.match(coachTrainingViewSource, /summarizeTrainingScenarioPack/);
  assert.match(coachTrainingViewSource, /scenario_pack\?: string;/);
  assert.match(coachTrainingViewSource, /scenarioPack\?: string;/);
  assert.match(coachTrainingViewSource, /const scenarioPackLabel = useMemo\(/);
  assert.match(coachTrainingViewSource, /Learn first/);
  assert.match(coachTrainingViewSource, /Scenario pack/);
  assert.match(coachTrainingViewSource, /scenarioPackLabel=\{scenarioPackLabel\}/);

  assert.match(trainingWorkbenchViewSource, /scenarioPackLabel\?: string;/);
  assert.match(trainingWorkbenchViewSource, /Scenario pack/);
  assert.match(trainingWorkbenchViewSource, /const needsPrimerState = trainingExecutionState\.needsPrimer;/);
  assert.match(trainingWorkbenchViewSource, /const isScenarioSubmode = normalizedTrainingSubmode === "scenario";/);
  assert.match(trainingWorkbenchViewSource, /const isTransferSubmode = normalizedTrainingSubmode === "transfer";/);
  assert.match(trainingWorkbenchViewSource, /const learnSectionLabel = learnPhaseActive/);
  assert.match(trainingWorkbenchViewSource, /const showLearnFirstPanel = learnPhaseActive && hasLearnFirstBlock;/);
  assert.match(trainingWorkbenchViewSource, /const showLearnPrimerNote = !cardOnly && !learnPhaseActive && hasLearnFirstBlock;/);
  assert.match(trainingWorkbenchViewSource, /training-next-move--adjust/);
  assert.match(trainingWorkbenchViewSource, /const showSourceDetails =[\s\S]*?!learnPhaseActive[\s\S]*?!cardOnly/);
  assert.match(trainingWorkbenchViewSource, /const showRouteDetails =[\s\S]*?!learnPhaseActive[\s\S]*?!cardOnly/);
  assert.match(trainingWorkbenchViewSource, /!learnPhaseActive && !cardOnly && adjustmentCopy/);
  assert.match(trainingWorkbenchViewSource, /!learnPhaseActive && hasGuidanceDetails/);

  assert.match(practiceViewSource, /scenarioPackLabel\?: string;/);
  assert.match(practiceViewSource, /Scenario pack/);

  assert.match(flashViewSource, /scenarioPackLabel\?: string;/);
  assert.match(flashViewSource, /Scenario pack/);
  assert.match(flashViewSource, /FlashStudyPhase/);
  assert.match(flashViewSource, /Learn first/);
  assert.match(flashViewSource, /Start check/);
  assert.match(flashViewSource, /showCheckSurface/);
  assert.match(flashViewSource, /studyPhase === "learn"/);

  assert.match(guidedPacksSource, /previewScenario: GuidedTrainingPreviewScenario;/);
  assert.match(guidedPacksSource, /whyNow: LocalizedValue<string>;/);
  assert.match(guidedPacksSource, /learnerDeliverables: LocalizedValue<string\[]>;/);
  assert.match(guidedPacksSource, /verificationSteps: LocalizedValue<string\[]>;/);
  assert.match(guidedPacksSource, /returnWith: LocalizedValue<string>;/);
  assert.match(guidedPacksSource, /nextAfterCompletion: string;/);
  assert.match(guidedPacksSource, /"ja-JP": \{[\s\S]*?"training-function": "関数の契約"/);
  assert.match(guidedPacksSource, /previewScenarioFocus\(raw\.previewScenario, language\)/);
});

test('training status normalization keeps every governed blocked and recovery state visible', () => {
  const coachTrainingViewSource = fs.readFileSync(coachTrainingViewSourcePath, 'utf8');
  const statusGuardStart = coachTrainingViewSource.indexOf('function isTrainingCardStatus');
  const statusGuardEnd = coachTrainingViewSource.indexOf('\n}\n\nfunction pickVisibleFlashAttempt', statusGuardStart);

  assert.ok(statusGuardStart >= 0 && statusGuardEnd > statusGuardStart, 'expected training status guard');
  const statusGuard = coachTrainingViewSource.slice(statusGuardStart, statusGuardEnd);
  for (const status of ['needs_primer', 'completed', 'skipped', 'blocked']) {
    assert.match(statusGuard, new RegExp(`value === "${status}"`));
  }
});
