'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const practicePath = path.join(webviewRoot, 'components', 'practice', 'CoachPracticeView.tsx');
const coachTrainingPath = path.join(webviewRoot, 'components', 'training', 'CoachTrainingView.tsx');
const commandsPath = path.join(webviewRoot, 'app', 'useTrainingCommands.ts');
const appPath = path.join(webviewRoot, 'app', 'App.tsx');

test('practice completion verifies the current file instead of forging a completed status', () => {
  const source = fs.readFileSync(practicePath, 'utf8');
  const verifyStart = source.indexOf('function handleVerifyCurrentFile');
  const skipStart = source.indexOf('function handleSkip', verifyStart);

  assert.ok(verifyStart >= 0 && skipStart > verifyStart, 'expected practice verification handler');
  const verifyHandler = source.slice(verifyStart, skipStart);
  assert.match(verifyHandler, /onVerifyCurrentFile\(/);
  assert.match(verifyHandler, /acceptanceCriteria:/);
  assert.match(verifyHandler, /learnerDeliverables:/);
  assert.doesNotMatch(verifyHandler, /implemented|completed/);
  assert.match(source, /onClick=\{handleVerifyCurrentFile\}/);
  assert.match(source, /Verify current file/);
});

test('practice skipping uses the governed skipped transition', () => {
  const source = fs.readFileSync(practicePath, 'utf8');

  assert.match(source, /onCardStatusTransition\(task\.id, "skipped"/);
  assert.doesNotMatch(source, /onCardStatusTransition\(task\.id, "archived"/);
});

test('training keeps practice and flash bridges attached to the next action', () => {
  const coachTrainingSource = fs.readFileSync(coachTrainingPath, 'utf8');
  const commandsSource = fs.readFileSync(commandsPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');

  assert.match(coachTrainingSource, /onVerifyCurrentFile\?: \(request: PracticeFileVerificationRequest\)/);
  assert.match(coachTrainingSource, /onVerifyCurrentFile=\{onVerifyCurrentFile\}/);
  assert.match(commandsSource, /onOpenCoachWithBridge\?: \(bridge: TrainingCoachBridgeInput\)/);
  assert.match(commandsSource, /onOpenCoachWithBridge\(bridge\)/);
  assert.match(commandsSource, /source: "conversation_gap"/);
  assert.match(commandsSource, /focusArea: bridge\.focusArea/);
  assert.match(commandsSource, /targetSkill: bridge\.cardTitle/);
  assert.match(commandsSource, /prompt: bridge\.prompt/);
  assert.match(commandsSource, /trainerCommands\.evaluateCurrentFile/);
  assert.match(appSource, /const openTrainingCoachBridge = useCallback\(/);
  assert.match(appSource, /setComposerDraft\(composeTrainingCoachBridgeDraft\(bridge\)\)/);
  assert.match(
    appSource,
    /useTrainingCommands\(setActiveView, \{\s*onOpenCoachWithBridge: openTrainingCoachBridge,\s*requestTrainingPersistence,\s*\}\)/,
  );
});

test('useTrainingCommands card-status / reflect / return attach persistence wrapper', () => {
  const source = fs.readFileSync(commandsPath, 'utf8');

  assert.match(source, /const TRAINING_PERSISTENCE_REQUEST_ID_KEY = "__trainerTrainingPersistenceId"/);
  assert.match(source, /trainerCommands\.trainingCardStatusTransition/);
  assert.match(source, /trainerCommands\.trainingReflect/);
  assert.match(source, /trainerCommands\.trainingReturn/);
  assert.match(source, /requestTrainingPersistence/);
  assert.match(
    source,
    /sendDurableTrainingCommand\(trainerCommands\.trainingCardStatusTransition/,
  );
  assert.match(
    source,
    /\[TRAINING_PERSISTENCE_REQUEST_ID_KEY\]: persistenceId/,
  );
});

test('TrainingWorkbenchView skip uses hooked onCardStatusTransition persistence path', () => {
  const workbenchPath = path.join(webviewRoot, 'components', 'training', 'TrainingWorkbenchView.tsx');
  const cardPanelPath = path.join(webviewRoot, 'components', 'training', 'TrainingCardPanel.tsx');
  const workbenchSource = fs.readFileSync(workbenchPath, 'utf8');
  const cardPanelSource = fs.readFileSync(cardPanelPath, 'utf8');
  const appSource = fs.readFileSync(appPath, 'utf8');
  const commandsSource = fs.readFileSync(commandsPath, 'utf8');

  assert.match(appSource, /onCardStatusTransition: handleTrainingCardStatusTransition/);
  assert.match(
    appSource,
    /<TrainingWorkbenchView[\s\S]*?onCardStatusTransition=\{leftoverTrainingHandoffChromeNotLive \? undefined : handleTrainingCardStatusTransition\}/,
  );
  assert.match(appSource, /cardId=\{activeTrainingCardId\}/);
  assert.match(appSource, /<TrainingWorkbenchView[\s\S]*?onCardStatusTransition=/);
  assert.doesNotMatch(appSource, /<CoachTrainingView[\s\S]*?onCardStatusTransition=/);
  assert.doesNotMatch(appSource, /<TrainingCardPanel[\s\S]*?onCardStatusTransition=/);
  assert.doesNotMatch(appSource, /<CoachFlashView[\s\S]*?onCardStatusTransition=/);
  assert.doesNotMatch(appSource, /<CoachPracticeView[\s\S]*?onCardStatusTransition=/);

  assert.match(workbenchSource, /onCardStatusTransition\?: \(cardId: string, newStatus: TrainingCardStatus/);
  assert.match(workbenchSource, /onCardStatusTransition\(\s*normalizedCardId,\s*"skipped"/);
  assert.match(workbenchSource, /onCardStatusTransition\(normalizedCardId, "reviewed", reason\)/);
  assert.match(workbenchSource, /export function applyTrainingCardSkip/);
  assert.match(workbenchSource, /export function applyTrainingCardGrade/);
  assert.doesNotMatch(workbenchSource, /onClick=\{handleSkipCard\}/);
  assert.doesNotMatch(workbenchSource, /onClick=\{\(\) => handleGradeCard\(grade\)\}/);
  assert.match(appSource, /interpretTrainingComposerCardCommand\(normalizedDraft\)/);
  assert.match(appSource, /applyTrainingCardSkip\(/);
  assert.match(appSource, /applyTrainingCardGrade\(/);
  assert.doesNotMatch(workbenchSource, /postMessage\(\{\s*type:\s*"command\/execute"/);
  assert.doesNotMatch(workbenchSource, /trainerCommands\.trainingCardStatusTransition/);

  assert.match(cardPanelSource, /onCardStatusTransition\?/);
  assert.match(cardPanelSource, /onCardStatusTransition\(\s*card\.id,\s*"skipped"/);
  assert.match(cardPanelSource, /onCardStatusTransition\(card\.id, "reviewed"/);
  assert.doesNotMatch(cardPanelSource, /onSkip\?\.\(\)/);
  assert.doesNotMatch(cardPanelSource, /onRate\?\.\(/);
  assert.doesNotMatch(cardPanelSource, /disabled=\{!canTransitionCardStatus && !onRate\}/);
  assert.doesNotMatch(cardPanelSource, /disabled=\{!canTransitionCardStatus && !onSkip\}/);

  const flashPath = path.join(webviewRoot, 'components', 'flash', 'CoachFlashView.tsx');
  const flashSource = fs.readFileSync(flashPath, 'utf8');
  assert.match(flashSource, /onCardStatusTransition\(card\.cardId, "reviewed"/);
  assert.match(flashSource, /if \(!card\?\.cardId \|\| !onCardStatusTransition\)/);
  assert.match(flashSource, /disabled=\{cardStatusBusy \|\| !canTransitionCardStatus\}/);
  assert.doesNotMatch(flashSource, /setMasteryMark\(level\);\s*\n\s*if \(card && onCardStatusTransition\)/);

  assert.match(
    commandsSource,
    /sendDurableTrainingCommand\(trainerCommands\.trainingCardStatusTransition/,
  );
  assert.match(
    workbenchSource,
    /if \(!normalizedCardId \|\| !onCardStatusTransition \|\| leftoverStoredNote\)/,
  );
});

test('TrainingCardRenderer cannot skip or grade without persistence callback', () => {
  const rendererPath = path.join(webviewRoot, 'components', 'parts', 'TrainingCardRenderer.tsx');
  const partsPath = path.join(webviewRoot, 'components', 'parts', 'PartsRenderer.tsx');
  const rendererSource = fs.readFileSync(rendererPath, 'utf8');
  const partsSource = fs.readFileSync(partsPath, 'utf8');

  assert.match(
    rendererSource,
    /onCardStatusTransition\?: \(cardId: string, newStatus: "skipped" \| "reviewed"/,
  );
  assert.match(rendererSource, /const canTransitionCardStatus = Boolean\(cardId && onCardStatusTransition\)/);
  assert.match(rendererSource, /if \(!cardId \|\| !onCardStatusTransition\) \{\s*return;/);
  assert.match(rendererSource, /onCardStatusTransition\(\s*cardId,\s*"skipped"/);
  assert.match(rendererSource, /onCardStatusTransition\(cardId, "reviewed", reason\)/);
  assert.match(rendererSource, /onClick=\{handleSkip\}/);
  assert.match(rendererSource, /disabled=\{!canTransitionCardStatus\}/);
  assert.match(rendererSource, /\{canTransitionCardStatus \? \(/);
  assert.doesNotMatch(rendererSource, /onSkip\?\.\(\)/);
  assert.doesNotMatch(rendererSource, /onRate\?\.\(/);
  assert.doesNotMatch(rendererSource, /onClick=\{onSkip\}/);
  assert.doesNotMatch(rendererSource, /onRate\?\.\(rating\)/);

  assert.match(
    partsSource,
    /<TrainingCardRenderer part=\{part\} onClick=\{\(\) => context\.onTrainingCardClick\?\.\(part\.cardId\)\} \/>/,
  );
  assert.doesNotMatch(partsSource, /onSkip=/);
  assert.doesNotMatch(partsSource, /onRate=/);
  assert.doesNotMatch(partsSource, /onCardStatusTransition=/);
});

test('live reflect and return persist; leftover cannot fire them', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const commandsSource = fs.readFileSync(commandsPath, 'utf8');
  const workbenchPath = path.join(webviewRoot, 'components', 'training', 'TrainingWorkbenchView.tsx');
  const workbenchSource = fs.readFileSync(workbenchPath, 'utf8');

  assert.match(commandsSource, /trainerCommands\.trainingReflect/);
  assert.match(commandsSource, /trainerCommands\.trainingReturn/);
  assert.match(commandsSource, /requestTrainingPersistence/);
  assert.match(
    appSource,
    /await requestTrainingPersistence\(trainerCommands\.trainingReturn,/,
  );
  assert.match(
    appSource,
    /await requestTrainingPersistence\(trainerCommands\.trainingReflect,/,
  );
  assert.match(
    appSource,
    /const handleSubmitTrainingEvidence = useCallback\(async \(evidence: string\): Promise<boolean> => \{\s*if \(leftoverTrainingHandoffChromeNotLive\) \{\s*return false;/,
  );
  assert.match(
    appSource,
    /const handleResumeTrainingInCoach = useCallback\(\(\) => \{\s*if \(leftoverTrainingHandoffChromeNotLive\) \{\s*setActiveView\("coach"\);/,
  );
  assert.match(
    appSource,
    /const trainingHandoffReflectionRequired =\s*!leftoverTrainingHandoffChromeNotLive &&/,
  );
  assert.match(
    appSource,
    /const trainingHandoffReturnRequired =\s*!leftoverTrainingHandoffChromeNotLive &&/,
  );
  assert.match(
    appSource,
    /leftoverTrainingHandoffChromeNotLive \? \(\s*<button[\s\S]*?onClick=\{\(\) => setActiveView\("coach"\)\}/,
  );
  assert.doesNotMatch(
    appSource,
    /leftoverTrainingHandoffChromeNotLive \?[\s\S]{0,400}?handleResumeTrainingInCoach/,
  );

  assert.match(appSource, /onClick=\{handleResumeTrainingInCoach\}/);

  assert.doesNotMatch(workbenchSource, /trainerCommands\.trainingReflect/);
  assert.doesNotMatch(workbenchSource, /trainerCommands\.trainingReturn/);
  assert.doesNotMatch(workbenchSource, /postMessage\(\{\s*type:\s*"command\/execute"/);
});

test('live App training tree has no scenario skip or grade surface', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const workbenchPath = path.join(webviewRoot, 'components', 'training', 'TrainingWorkbenchView.tsx');
  const workbenchSource = fs.readFileSync(workbenchPath, 'utf8');

  assert.doesNotMatch(appSource, /<CoachTrainingView/);
  assert.doesNotMatch(appSource, /<CoachPracticeView/);
  assert.doesNotMatch(appSource, /<CoachFlashView/);
  assert.doesNotMatch(appSource, /<TrainingCardPanel/);
  assert.doesNotMatch(appSource, /<TrainingCardRenderer/);
  assert.doesNotMatch(appSource, /onScenarioLabAction=\{/);
  assert.doesNotMatch(workbenchSource, /onScenarioLabAction/);
  assert.doesNotMatch(workbenchSource, /trainerCommands\.trainingScenarioLabAction/);
  assert.match(workbenchSource, /export function applyTrainingCardSkip/);
  assert.match(workbenchSource, /export function applyTrainingCardGrade/);
  assert.doesNotMatch(workbenchSource, /onClick=\{handleSkipCard\}/);
  assert.doesNotMatch(workbenchSource, /onClick=\{\(\) => handleGradeCard\(grade\)\}/);
});

test('leftover-not-live context rail does not paint leftover dump as live activity', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const workbenchPath = path.join(webviewRoot, 'components', 'training', 'TrainingWorkbenchView.tsx');
  const workbenchSource = fs.readFileSync(workbenchPath, 'utf8');
  const railStart = appSource.indexOf('const renderContextualResultRail');
  const railEnd = appSource.indexOf('const renderViewAgentReply');
  const railSource = appSource.slice(railStart, railEnd);

  assert.match(railSource, /leftoverTrainingActivityNotLive/);
  assert.match(railSource, /leftoverTrainingHandoffChromeNotLive/);
  assert.match(
    railSource,
    /Boolean\(recoveredRuntime\) && !String\(trainingState\?\.selectedCardId \?\? ""\)\.trim\(\)/,
  );
  assert.match(
    railSource,
    /leftoverTrainingActivityNotLive\s*\?\s*undefined\s*:\s*pickLanguageAlignedTrainingText\([\s\S]*?latestLearningBlocker/,
  );
  assert.match(
    railSource,
    /leftoverTrainingActivityNotLive\s*\?\s*undefined\s*:\s*pickLanguageAlignedTrainingText\([\s\S]*?latestLearningVerifiedResult/,
  );
  assert.doesNotMatch(railSource, /id: "current"/);
  assert.doesNotMatch(railSource, /Generate a training card/);
  assert.match(workbenchSource, /data-training-leftover-not-live=\{leftoverStoredNote \? "true" : undefined\}/);
  assert.match(
    workbenchSource,
    /if \(!normalizedCardId \|\| !onCardStatusTransition \|\| leftoverStoredNote\)/,
  );
  assert.match(
    appSource,
    /<TrainingWorkbenchView[\s\S]*?onCardStatusTransition=\{leftoverTrainingHandoffChromeNotLive \? undefined : handleTrainingCardStatusTransition\}/,
  );
});

test('Coach leftover chrome does not mount live training-lifecycle chrome for a dump card', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const orientationStart = appSource.indexOf('const coachOrientation = useMemo');
  const orientationEnd = appSource.indexOf('const trainingSuggestedWorkspaceAction');
  const orientationSource = appSource.slice(orientationStart, orientationEnd);
  const inlineStart = appSource.indexOf('const coachTrainingInlineAction = useMemo');
  const inlineSource = appSource.slice(inlineStart, inlineStart + 900);

  assert.match(
    orientationSource,
    /trainingLearningPhase: leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined\s*:\s*training\?\.latestTrainingHandoff\?\.learningPhase/,
  );
  assert.match(
    orientationSource,
    /trainingHandoffStatus: leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined\s*:\s*training\?\.latestTrainingHandoff\?\.handoffStatus/,
  );
  assert.match(
    orientationSource,
    /selectedCardTitle: leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined/,
  );
  assert.match(
    orientationSource,
    /trainingReliabilityPhase: leftoverTrainingHandoffChromeNotLive\s*\?\s*undefined/,
  );
  assert.match(
    inlineSource,
    /const coachTrainingInlineAction = useMemo\(\(\) => \{\s*if \(leftoverTrainingHandoffChromeNotLive\) \{\s*return null;/,
  );
  assert.doesNotMatch(
    inlineSource,
    /leftoverTrainingHandoffChromeNotLive \? \{\s*label: t\.trainingOpenCurrentCard/,
  );
  assert.match(appSource, /data-coach-leftover-note="true"/);
  assert.match(appSource, /\{t\.leftoverNotLiveHint\}/);
});
