'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const trainingViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);
const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function cardOnlyRender(source) {
  const start = source.indexOf('{cardOnly ? (');
  const end = source.indexOf('{!cardOnly ? (', start);

  assert.ok(start >= 0, 'expected the card-only render branch');
  assert.ok(end > start, 'expected the card-only branch to close before secondary content');
  return source.slice(start, end);
}

function cardOnlyFace(source) {
  const start = source.indexOf('{cardOnly ? (');
  const end = source.indexOf('{!cardOnly ? (', start);
  assert.ok(start >= 0 && end > start, 'expected the card-only face before secondary content');
  return source.slice(start, end);
}

function trainingCardGenerationHandler(source) {
  const start = source.indexOf('  const handleGenerateTrainingCard = useCallback(');
  const end = source.indexOf('  const composerUsesTrainingFlow', start);

  assert.ok(start >= 0, 'expected the training-card generation handler');
  assert.ok(end > start, 'expected the training-card generation handler to end before composer routing');
  return source.slice(start, end);
}

test('training card-only mode keeps one current card and moves response controls to the composer', () => {
  const source = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const cardOnly = cardOnlyRender(source);
  const trainingCardHandler = trainingCardGenerationHandler(appSource);
  const cardSectionsStart = source.indexOf('const cardOnlyBodySections');
  const cardSectionsEnd = source.indexOf('const hasAdjustmentOutcome', cardSectionsStart);
  const cardSections = source.slice(cardSectionsStart, cardSectionsEnd);

  assert.match(source, /type TrainingLoopStepKey = "learn" \| "try" \| "verify" \| "reflect" \| "return";/);
  assert.match(source, /const order: TrainingLoopStepKey\[\] = \["learn", "try", "verify", "reflect", "return"\];/);
  assert.match(appSource, /<TrainingWorkbenchView[\s\S]*?cardOnly=\{true\}/);
  assert.match(source, /!\s*cardOnly\s*\?\s*\(\s*<div className="training-card-nav"/);
  assert.match(source, /onClick=\{onPreviousCard\}/);
  assert.match(source, /onClick=\{onNextCard\}/);
  assert.match(source, /<span className="training-card-nav__counter">/);
  assert.match(cardOnly, /training-current__card-stack--card-only/);
  assert.match(cardOnly, /training-current__sentence/);
  assert.match(cardOnly, /data-view-object=""/);
  assert.match(cardOnly, /data-view-why=""/);
  assert.match(cardOnly, /data-view-primary=""/);
  assert.match(cardOnly, /training-current__card-section/);
  assert.match(cardOnly, /cardOnlyBodySections/);
  assert.doesNotMatch(cardOnly, /training-current__more/);
  assert.doesNotMatch(cardOnly, /training-loop-rail/);
  assert.doesNotMatch(cardOnly, /TrainingNextHopLine/);
  assert.match(cardOnly, /data-training-card-fact=\{section\.key\}/);
  assert.match(source, /export function interpretTrainingComposerCardCommand/);
  assert.match(source, /export function applyTrainingCardSkip/);
  assert.match(appSource, /interpretTrainingComposerCardCommand\(normalizedDraft\)/);
  assert.doesNotMatch(
    source,
    /\{cardOnly && nextHop \? \(\s*<div className="training-carryover-stack">\s*<TrainingCarryoverRow card=\{nextHop\}/,
  );
  assert.match(cardSections, /key: "current"/);
  assert.match(cardSections, /key: "why-now"/);
  assert.match(cardSections, /key: "deliverable"/);
  assert.match(cardSections, /key: "verify"/);
  assert.match(cardSections, /key: "return"/);
  assert.match(cardSections, /detail: routeVerifySummary/);
  assert.match(cardSections, /detail: routeReturnSummary/);
  assert.doesNotMatch(cardOnlyFace(source), /<(?:button|input|textarea|form)\b/);
  assert.doesNotMatch(cardOnly, /(?:flashProofSurface|practiceProofSurface|training-current__response-shell)/);
  assert.match(appSource, /const trainingComposerEnabled = activeView === "training" && hasTrainingCard;/);
  assert.match(appSource, /useState<TrainingComposerRoute>\("card"\)/);
  assert.match(appSource, /const trainingComposerTalkMode = trainingComposerEnabled && trainingComposerRoute === "coach";/);
  assert.match(appSource, /const composerUsesTrainingFlow = trainingComposerEnabled && !trainingComposerTalkMode;/);
  assert.match(appSource, /const trainingPrimaryAction = !hasTrainingCard \? undefined/);
  assert.match(appSource, /id: "composer-verify-file"/);
  assert.match(appSource, /onClick: handleVerifyTrainingFromIde/);
  assert.match(appSource, /if \(composerUsesTrainingFlow\) \{/);
  assert.match(appSource, /const trainingComposerUsesAnswerMode = trainingComposerPhase === "answer";/);
  assert.match(appSource, /onSubmitFlashAnswer: handleSubmitFlashAnswer/);
  assert.match(appSource, /renderTrainingComposerAccessory\(\)/);
  assert.match(appSource, /setTrainingComposerPracticeReturnMode\("result"\)/);
  assert.match(appSource, /setTrainingComposerPracticeReturnMode\("blocked"\)/);
  assert.doesNotMatch(appSource, /id: "training-verify-current-file"/);
  assert.match(appSource, /const handleGenerateTrainingCard = useCallback\(/);
  assert.match(
    trainingCardHandler,
    /if \(workspaceSessionBlocked\) \{\s*openWorkspaceAdmission\(\);\s*setOperationMessage\(\{\s*tone: "info",\s*message: workspaceSessionBlockMessage \?\? blockedComposerGuidance,\s*\}\);\s*return;\s*\}/,
  );
  assert.match(
    trainingCardHandler,
    /if \(!providerCanCoachNow \|\| providerBlockReason\) \{\s*setOperationMessage\(\{\s*tone: "info",\s*message: blockedComposerGuidance,\s*\}\);\s*return;\s*\}[\s\S]*?requestTrainingCardGeneration\(focusArea\);/,
  );
  assert.doesNotMatch(
    trainingCardHandler,
    /if \(!providerCanCoachNow \|\| providerBlockReason\) \{[\s\S]*?setActiveView\("settings"\)/,
  );
});

test('training empty state creates the first small card without redirecting to Coach', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const trainingActionsStart = source.indexOf('actions={hasTrainingCard ? trainingCoachAction : undefined}');
  const emptyStateStart = source.indexOf('emptyState={', trainingActionsStart);
  const emptyStateEnd = source.indexOf('onNextCard={handleGenerateTrainingCard}', emptyStateStart);

  assert.ok(trainingActionsStart >= 0, 'expected Coach handoff to be gated by a training card');
  assert.ok(emptyStateStart >= 0 && emptyStateEnd > emptyStateStart, 'expected the training empty state');
  const emptyState = source.slice(emptyStateStart, emptyStateEnd);

  assert.match(emptyState, /onClick=\{\(\) => handleGenerateTrainingCard\(\)\}/);
  assert.match(emptyState, /\{t\.startTraining\}/);
  assert.doesNotMatch(emptyState, /trainingCoachAction/);
  assert.match(source, /actions=\{hasTrainingCard \? trainingCoachAction : undefined\}/);
});

test('training card-only mode keeps secondary primer and guidance surfaces out of the floating card face', () => {
  const source = fs.readFileSync(trainingViewSourcePath, 'utf8');

  assert.match(source, /const showSourceDetails =\s*!learnPhaseActive &&\s*!cardOnly/);
  assert.match(source, /const showRouteDetails =\s*!learnPhaseActive &&\s*!cardOnly/);
  assert.match(source, /const hasGuidanceDetails =\s*!cardOnly &&/);
  assert.match(source, /const showLearnPrimerNote = !cardOnly && !learnPhaseActive && hasLearnFirstBlock;/);
});

test('training cards preserve their explicit deliverable and verification contract', () => {
  const source = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const appSource = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(appSource, /const trainingDeliverable = pickLanguageAlignedTrainingText/);
  assert.match(appSource, /const trainingValidationMethod = pickLanguageAlignedTrainingText/);
  assert.match(appSource, /const trainingVerificationMethod = pickLanguageAlignedTrainingText/);
  assert.match(appSource, /trainingDeliverable,[\s\S]*?learnerDeliverables/);
  assert.match(appSource, /trainingValidationMethod,[\s\S]*?trainingVerificationMethod,[\s\S]*?verificationSteps/);
  assert.match(appSource, /deliverable=\{hasTrainingCard \? trainingDeliverable : undefined\}/);
  assert.match(appSource, /validationMethod=\{hasTrainingCard \? trainingValidationMethod : undefined\}/);
  assert.match(appSource, /verificationMethod=\{hasTrainingCard \? trainingVerificationMethod : undefined\}/);

  assert.match(source, /deliverable\?: string;/);
  assert.match(source, /validationMethod\?: string;/);
  assert.match(source, /verificationMethod\?: string;/);
  assert.match(source, /const resolvedDeliverables = uniqueTrainingCardItems\(\[deliverable, \.\.\.deliverables\]\);/);
  assert.match(source, /const resolvedVerifyItems = uniqueTrainingCardItems\(\[[\s\S]*?validationMethod,[\s\S]*?verificationMethod,[\s\S]*?\.\.\.verifyItems,/);
  assert.match(source, /const routeVerifySummary = resolvedVerifyItems\[0\]/);
});

test('training card-only mode replaces the full phase rail with the active phase at the narrowest sidebar width', () => {
  const source = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const styles = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'styles.css'),
    'utf8',
  );
  const cardOnly = cardOnlyRender(source);

  assert.doesNotMatch(cardOnly, /training-loop-rail/);
  assert.doesNotMatch(cardOnly, /training-current__phase/);
  assert.match(cardOnly, /data-view-object=""/);
  assert.match(cardOnly, /data-view-why=""/);
  assert.match(cardOnly, /data-view-primary=""/);
  assert.match(styles, /\.training-current__card-face h2\s*\{[\s\S]*?overflow-wrap:\s*anywhere/);
  assert.match(
    styles,
    /\.training-current__card-section p\s*\{[\s\S]*?overflow-wrap:\s*anywhere/,
  );
});

test('training restore targets become the current card and publish the visible single-card truth', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const selectionStart = source.indexOf('const selectedTrainingCardCandidate = useMemo');
  const selectionEnd = source.indexOf('const trainingRestoreForeground', selectionStart);

  assert.ok(selectionStart >= 0 && selectionEnd > selectionStart, 'expected current-card selection');
  const selection = source.slice(selectionStart, selectionEnd);

  assert.match(source, /function restoredTrainingCard\(/);
  assert.match(source, /const scenarioLabCard =/);
  assert.match(source, /const theoryDrillCard =/);
  assert.match(source, /const reviewArtifactCard =/);
  assert.match(source, /const nextHopCard =/);
  assert.match(source, /if \(trainingRestoreContext\?\.target && restoredCard\)/);
  assert.ok(
    selection.indexOf('if (trainingRestoreContext?.target && restoredCard)') <
      selection.indexOf('if (shouldPrioritizeReviewArtifact'),
    'an explicit restore target must win over automatic review prioritization',
  );
  assert.match(
    source,
    /const restoredTrainingCardCandidate = useMemo\([\s\S]*?restoredTrainingCard\(trainingState, trainingRestoreContext\)/,
  );
  assert.match(
    source,
    /const trainingRestoreForeground = Boolean\([\s\S]*?selectedTrainingCardCandidate\?\.cardId === restoredTrainingCardCandidate\.cardId/,
  );
  assert.match(
    source,
    /const activeTrainingCardId = reviewArtifactForeground \|\| trainingRestoreForeground[\s\S]*?selectedTrainingCardCandidate\?\.cardId/,
  );
  assert.match(source, /const visibleTrainingCardTitle = liveTrainingNextChallengeTitle\(/);
  assert.match(source, /trainingRestoreForeground/);
  assert.match(
    source,
    /cardId: activeTrainingCardId,[\s\S]*?taskTitle: visibleTrainingCardTitle \?\? liveTrainingTitle,[\s\S]*?cardTitle: visibleTrainingCardTitle,/,
  );
  assert.match(source, /visibleTitle: visibleTrainingCardTitle,/);
  assert.match(source, /const trainingRestoreReplacesSelectedCard = Boolean\(/);
  assert.match(
    source,
    /nextHop=\{\s*hasRenderableTrainingCard && !trainingRestoreForeground\s*\? trainingNextHopCard\s*:\s*undefined\s*\}/,
  );
  assert.match(source, /scenarioLabVisible,/);
  assert.match(source, /nextHopVisible,/);
  assert.match(source, /singleCardImmersive: true,/);
  assert.match(source, /cardOnlyMode: true,/);
  assert.match(source, /postDebugVisibleFacts\(\{ activeView: "training", training: facts \}\);/);
  const trainingSource = fs.readFileSync(trainingViewSourcePath, "utf8");
  assert.doesNotMatch(trainingSource, /data-training-next-hop="true"/);
  assert.doesNotMatch(trainingSource, /function TrainingNextHopLine/);
  assert.match(
    trainingSource,
    /const carryoverCards = \[restoredFocus, outcome, cardOnly \? undefined : nextHop\]/,
  );
  assert.doesNotMatch(trainingSource, /<details className="training-current__more">/);
  assert.match(
    trainingSource,
    /!cardOnly && \(carryoverCards\.length > 0 \|\|[\s\S]*?<details className="training-details">/,
  );
});
