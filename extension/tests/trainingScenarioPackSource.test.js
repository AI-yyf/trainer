'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const trainingWorkbenchViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);
const guidedPacksSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'guidedTrainingScenarioPacks.ts',
);
const sharedExecutionGovernanceSourcePath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'trainingExecutionGovernance.ts',
);

test('training scenario packs stay localized and learn-first across training surfaces', () => {
  const trainingWorkbenchViewSource = fs.readFileSync(trainingWorkbenchViewSourcePath, 'utf8');
  const guidedPacksSource = fs.readFileSync(guidedPacksSourcePath, 'utf8');

  assert.match(trainingWorkbenchViewSource, /scenarioPackLabel\?: string;/);
  assert.match(trainingWorkbenchViewSource, /Scenario pack/);
  assert.match(trainingWorkbenchViewSource, /const needsPrimerState = trainingExecutionState\.needsPrimer;/);
  assert.match(
    trainingWorkbenchViewSource,
    /scenarioPackLabel\s*\?\s*`\$\{trainingWorkbenchText\(language, "scenarioPack"\)\}: \$\{scenarioPackLabel\}`/,
  );

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
  // The former CoachTrainingView status guard moved into the shared execution
  // governance module; the view derives its state exclusively from it.
  const executionGovernanceSource = fs.readFileSync(sharedExecutionGovernanceSourcePath, 'utf8');
  const trainingWorkbenchViewSource = fs.readFileSync(trainingWorkbenchViewSourcePath, 'utf8');

  assert.match(
    trainingWorkbenchViewSource,
    /deriveTrainingExecutionState\(\{\s*cardType: isFlashCard \? "flash" : "practice",/,
  );
  assert.doesNotMatch(trainingWorkbenchViewSource, /function isTrainingCardStatus/);

  const statusGuardStart = executionGovernanceSource.indexOf('export function normalizeTrainingStatus');
  assert.ok(statusGuardStart >= 0, 'expected shared training status guard');
  for (const status of ['needs_primer', 'completed', 'skipped', 'blocked']) {
    assert.ok(
      executionGovernanceSource.includes(`"${status}"`),
      `expected governed status ${status} to stay visible in shared governance`,
    );
  }
});
