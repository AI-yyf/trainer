'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('Training currentFocus does not use leftover formal title or coach focus', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const focusStart = source.indexOf('const localizedCurrentFocus = hasRenderableTrainingCard');
  const focusEnd = source.indexOf('return (', focusStart);

  assert.ok(focusStart >= 0 && focusEnd > focusStart, 'expected Training currentFocus picker');
  const focusBlock = source.slice(focusStart, focusEnd);
  assert.match(source, /liveTrainingFocusFallback\(/);
  assert.match(source, /leftoverTrainingFocusChromeIsNotLive\(/);
  assert.match(source, /preferRecoveredTrainingFocusChrome\(/);
  assert.match(source, /teachingDecisionFocusArea: data\.teachingDecision\?\.focusArea/);
  assert.match(source, /learnerStateActiveFocus: data\.learnerState\?\.activeFocus/);
  assert.match(focusBlock, /liveTrainingCurrentFocus/);
  assert.match(focusBlock, /leftoverTrainingFocusChromeNotLive/);
  assert.doesNotMatch(focusBlock, /resolvedCoachFocus/);
  assert.doesNotMatch(focusBlock, /data\.memory\.currentFocus/);
  assert.match(source, /liveTrainingFocus,/);
});

test('Training and Practice views gate leftover teachingDecision.focusArea', () => {
  // The standalone CoachTrainingView / CoachPracticeView panels are gone; the
  // focus chrome is assembled once in App and handed to the single-card view.
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(source, /preferRecoveredTrainingFocusChrome\(/);
  assert.match(source, /teachingDecisionFocusArea: data\.teachingDecision\?\.focusArea/);
  assert.match(source, /liveTrainingFocusChrome\.teachingDecisionFocusArea/);
  assert.doesNotMatch(
    source,
    /workspaceTrainingState\?\.latestLearningFocusArea \|\|\s*teachingDecision\?\.focusArea/,
  );
});

test('Training first screen gates leftover handoff card chrome', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(source, /leftoverTrainingHandoffChromeIsNotLive\(/);
  assert.match(source, /preferRecoveredTrainingHandoffChrome\(/);
  assert.match(source, /successSignal: pickFirstText\(/);
  assert.match(source, /returnWith: pickFirstText\(/);
  assert.match(
    source,
    /leftoverTrainingHandoffChromeNotLive \? undefined : trainingState\?\.selectedCardTitle/,
  );
  assert.match(
    source,
    /leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined\s*:\s*trainingState\?\.latestTrainingHandoff\?\.cardTitle/,
  );
  assert.match(
    source,
    /successSignal: leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined\s*:\s*\(\(/,
  );
  assert.match(
    source,
    /leftoverTrainingHandoffChromeNotLive \|\| trainingRestoreReplacesSelectedCard/,
  );
  assert.match(
    source,
    /const trainingNextAfterCompletionText = leftoverTrainingHandoffChromeNotLive/,
  );
  assert.match(
    source,
    /const trainingFallbackActionText = leftoverTrainingHandoffChromeNotLive/,
  );
  assert.match(source, /leftoverTrainingHandoffChromeNotLive \|\|/);
  assert.match(source, /!trainingState\?\.latestTrainingNextHop/);
  assert.match(
    source,
    /leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined\s*:\s*liveTrainingHandoffChrome\.handoffSummary/,
  );
  assert.match(
    source,
    /const trainingWhyThisCard = leftoverTrainingHandoffChromeNotLive/,
  );
  assert.match(source, /leftoverResourceSelectedDetailIsNotLive\(/);
  assert.match(source, /leftoverResourceSelectedDetailNotLive/);
  assert.match(source, /leftoverResourceSandboxPreviewIsNotLive\(/);
  assert.match(source, /leftoverSandboxPreviewNotLive/);
  assert.match(source, /leftoverResourceSandboxStateIsNotLive\(/);
  assert.match(source, /leftoverResourceSandboxStateNotLive/);
  assert.match(source, /leftoverResourceLibraryListIsNotLive\(/);
  assert.match(source, /leftoverResourceLibraryListNotLive/);
  assert.match(source, /leftoverCoachConversationIsNotLive\(/);
  assert.match(source, /leftoverCoachConversationNotLive/);
  assert.match(source, /leftoverSuggestedActionsIsNotLive\(/);
  assert.match(source, /leftoverSuggestedActionsNotLive/);
  assert.match(source, /leftoverMintingSuggestedActionsAreNotLive\(/);
  assert.match(source, /leftoverFirstLookHeadlineIsNotLive\(/);
  assert.match(source, /leftoverFirstLookHeadlineNotLive/);
  assert.match(source, /leftoverEvaluationHeadlineIsNotLive\(/);
  assert.match(source, /leftoverEvaluationHeadlineNotLive/);
  assert.match(source, /leftoverStreamingCheckpointIsNotLive\(/);
  assert.match(source, /leftoverStreamingCheckpointNotLive/);
  assert.match(source, /leftoverTransferSkillIsNotLive\(/);
  assert.match(source, /leftoverTransferSkillNotLive/);
  assert.match(source, /preferRecoveredTransferSkill\(/);
  assert.match(source, /liveTransferState/);
  assert.match(source, /leftoverSettingsProfileRhythmIsNotLive\(/);
  assert.match(source, /leftoverSettingsProfileRhythmNotLive/);
  assert.match(source, /leftoverSettingsLearnerProjectOnboardingIsNotLive\(/);
  assert.match(source, /leftoverSettingsLearnerProjectOnboardingNotLive/);
});
