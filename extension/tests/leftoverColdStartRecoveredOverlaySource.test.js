'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  formalPlanIsLiveRuntimeIdentity,
  leftoverTaskGuideFocusIsNotLive,
  leftoverTrainingHandoffChromeIsNotLive,
  leftoverResourceLibraryListIsNotLive,
  leftoverSettingsProfileRhythmIsNotLive,
} = require('../dist/shared/src/planOrientationGovernance.js');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const coachPlanPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'plan',
  'CoachPlanView.tsx',
);
const trainingPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);
const resourcesPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const workbenchDataPath = path.resolve(__dirname, '..', 'src', 'core', 'workbenchData.ts');

test('cold-start recovered stamp lights leftover overlay without leftover plan object', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const coachPlanSource = fs.readFileSync(coachPlanPath, 'utf8');
  const trainingSource = fs.readFileSync(trainingPath, 'utf8');
  const resourcesSource = fs.readFileSync(resourcesPath, 'utf8');
  const workbenchData = fs.readFileSync(workbenchDataPath, 'utf8');

  // App: leftover overlay only when recovered && !formalPlanLive (not recovered alone).
  // Cold-start has no live plan → formalPlanLive false → leftoverNote lights.
  assert.match(
    appSource,
    /const leftoverPlanNotLive = Boolean\(recoveredRuntime\) && !formalPlanLive/,
  );
  assert.match(
    appSource,
    /leftoverNote=\{leftoverPlanNotLive \? t\.leftoverNotLive : undefined\}/,
  );
  assert.doesNotMatch(
    appSource,
    /leftoverPlanNotLive\s*=\s*.*hasFormalPlan/,
  );
  assert.doesNotMatch(
    appSource,
    /leftoverNote=\{[^}]*hasFormalPlan[^}]*leftoverPlanNotLive/,
  );
  assert.doesNotMatch(
    appSource,
    /leftoverNote=\{[^}]*data\.plan\.(id|title|currentStep)/,
  );
  // Empty recovered step must not paint snapshot.plan live.
  assert.match(
    appSource,
    /if \(leftoverPlanNotLive && !recoveredDisplayFacts\.currentStep\) \{\s*return null;/,
  );
  assert.match(
    appSource,
    /plan=\{shouldShowNeutralEmptyState \? null : visibleFormalPlan\}/,
  );

  // CoachPlanView: null plan + leftoverNote → leftover sentence (no plan object required).
  assert.match(coachPlanSource, /if \(!plan\) \{/);
  assert.match(coachPlanSource, /data-plan-leftover-not-live=\{leftoverNote \? "true" : undefined\}/);
  assert.match(
    coachPlanSource,
    /leftoverNote \? \(\s*<p[\s\S]*?data-plan-leftover-note="true"/,
  );

  // Training / Resources: leftover sentence from recovered chrome flags, Open Coach primary.
  assert.match(
    appSource,
    /leftoverNote=\{leftoverTrainingHandoffChromeNotLive \? t\.leftoverNotLive : undefined\}/,
  );
  assert.match(
    appSource,
    /leftoverNote=\{leftoverResourceLibraryListNotLive \? t\.leftoverNotLive : undefined\}/,
  );
  assert.match(
    trainingSource,
    /leftoverStoredNote \? \([\s\S]*?aria-label=\{t\.openCoach\}/,
  );
  assert.match(
    resourcesSource,
    /leftoverStoredNote \? \(\s*<p[\s\S]*?data-resources-leftover-note="true"/,
  );
  assert.match(appSource, /primaryAction: "open_coach"/);
  assert.match(appSource, /primaryActionLabel: t\.openCoach/);

  // Host cold start: recovered stamp with plan:null / empty host plan.
  assert.match(workbenchData, /mergeSessionStartSnapshot/);
  assert.match(workbenchData, /planRuntimeStatus/);
});

test('empty current.plan + recovered true is leftover-not-live (shared identity)', () => {
  const emptyIdentity = {
    recovered: true,
    runtimeCurrentStep: '',
    planCurrentStep: '',
    runtimePlanId: '',
    planId: '',
  };

  assert.equal(formalPlanIsLiveRuntimeIdentity(emptyIdentity), false);
  assert.equal(
    leftoverTaskGuideFocusIsNotLive({
      recovered: true,
      runtimeCurrentStep: '',
    }),
    true,
  );
  assert.equal(leftoverTrainingHandoffChromeIsNotLive(emptyIdentity), true);
  assert.equal(leftoverResourceLibraryListIsNotLive(emptyIdentity), true);
  assert.equal(
    leftoverSettingsProfileRhythmIsNotLive({
      recovered: true,
      runtimeCurrentStep: '',
    }),
    true,
  );

  // Leftover plan object on host must still not count as live when recovered stamp has no step.
  assert.equal(
    formalPlanIsLiveRuntimeIdentity({
      recovered: true,
      runtimeCurrentStep: '',
      planCurrentStep: 'Leftover stored step',
      runtimePlanId: '',
      planId: 'plan-leftover-host',
    }),
    false,
  );
});

test('recovered true + matching live plan_id keeps leftover overlay off (source)', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const coachPlanSource = fs.readFileSync(coachPlanPath, 'utf8');

  // Fail-closed: overlay must AND !formalPlanLive — never recovered alone.
  assert.match(
    appSource,
    /const leftoverPlanNotLive = Boolean\(recoveredRuntime\) && !formalPlanLive/,
  );
  assert.doesNotMatch(
    appSource,
    /const leftoverPlanNotLive = Boolean\(recoveredRuntime\)\s*;/,
  );
  assert.match(
    appSource,
    /leftoverNote=\{leftoverPlanNotLive \? t\.leftoverNotLive : undefined\}/,
  );
  assert.match(
    appSource,
    /plan=\{shouldShowNeutralEmptyState \? null : visibleFormalPlan\}/,
  );

  // Matching live plan_id → formalPlanLive true → leftoverPlanNotLive false → leftoverNote absent.
  const liveMatching = {
    recovered: true,
    runtimeCurrentStep: 'Keep one auth check',
    planCurrentStep: 'Keep one auth check',
    runtimePlanId: 'plan-live-match',
    planId: 'plan-live-match',
  };
  assert.equal(formalPlanIsLiveRuntimeIdentity(liveMatching), true);
  const leftoverPlanNotLive = Boolean(liveMatching.recovered) && !formalPlanIsLiveRuntimeIdentity(liveMatching);
  assert.equal(leftoverPlanNotLive, false);
  assert.equal(leftoverPlanNotLive ? 'leftover' : undefined, undefined);

  // visibleFormalPlan stays present when formalPlanLive (empty-step null only under leftoverPlanNotLive).
  assert.match(
    appSource,
    /if \(leftoverPlanNotLive && !recoveredDisplayFacts\.currentStep\) \{\s*return null;/,
  );
  assert.match(appSource, /const visibleFormalPlan = useMemo\(\(\) => \{/);
  assert.match(
    appSource,
    /shouldShowNeutralEmptyState \|\| !hasFormalPlan\s*\?\s*t\.plan\s*:\s*formalPlanLive\s*\?\s*data\.plan\.title/,
  );

  // CoachPlanView only paints leftover sentence when leftoverNote is truthy.
  assert.match(coachPlanSource, /data-plan-leftover-not-live=\{leftoverNote \? "true" : undefined\}/);
  assert.match(
    coachPlanSource,
    /leftoverNote \? \(\s*<p[\s\S]*?data-plan-leftover-note="true"/,
  );
});
