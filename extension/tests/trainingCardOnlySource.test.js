'use strict';

const test = require('node:test');

// PR-7: styles.css is an @import aggregator; rules live in styles/sections/*.
function readStylesSource() {
  const fsMod = require('node:fs');
  const pathMod = require('node:path');
  const root = pathMod.resolve(__dirname, '..', 'webview', 'src');
  const manifest = JSON.parse(fsMod.readFileSync(
    pathMod.join(root, 'styles', 'sections', 'manifest.json'), 'utf8'));
  return manifest.map(
    (entry) => fsMod.readFileSync(pathMod.join(root, entry.file), 'utf8'),
  ).join('');
}

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

function trainingCardGenerationHandler(source) {
  const start = source.indexOf('  const handleGenerateTrainingCard = useCallback(');
  const end = source.indexOf('  const composerUsesTrainingFlow', start);

  assert.ok(start >= 0, 'expected the training-card generation handler');
  assert.ok(end > start, 'expected the training-card generation handler to end before composer routing');
  return source.slice(start, end);
}

test('training card-only mode keeps one current card and moves response controls to the composer', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
});

test('training empty state creates the first small card without redirecting to Coach', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const trainingActionsStart = source.indexOf('actions={hasTrainingCard ? trainingCoachAction : undefined}');
  const emptyStateStart = source.indexOf('emptyState={', trainingActionsStart);
  const emptyStateEnd = source.indexOf('onNextCard={handleGenerateTrainingCard}', emptyStateStart);

  assert.ok(trainingActionsStart >= 0, 'expected Coach handoff to be gated by a training card');
  assert.ok(emptyStateStart >= 0 && emptyStateEnd > emptyStateStart, 'expected the training empty state');
  const emptyState = source.slice(emptyStateStart, emptyStateEnd);

  assert.match(emptyState, /onClick: \(\) => workspaceSessionBlocked \? openWorkspaceAdmission\(\) : handleGenerateTrainingCard\(\)/);
  assert.match(emptyState, /t\.startTraining/);
  assert.doesNotMatch(emptyState, /trainingCoachAction/);
  assert.match(source, /actions=\{hasTrainingCard \? trainingCoachAction : undefined\}/);
});

test('training card-only mode keeps secondary primer and guidance surfaces out of the floating card face', () => {
  const source = fs.readFileSync(trainingViewSourcePath, 'utf8');

  // Focus mode: the secondary primer/guidance/route surfaces shipped only in
  // the removed non-card-only branch; they must not grow back silently.
  assert.doesNotMatch(source, /const showSourceDetails/);
  assert.doesNotMatch(source, /const showRouteDetails/);
  assert.doesNotMatch(source, /const hasGuidanceDetails/);
  assert.doesNotMatch(source, /const showLearnPrimerNote/);
  assert.doesNotMatch(source, /training-guidance-details/);
  assert.doesNotMatch(source, /training-source-details/);
  assert.doesNotMatch(source, /training-card-route-details/);
});

test('training cards preserve their explicit deliverable and verification contract', () => {
  const source = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const appSource = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(appSource, /const trainingDeliverable = pickLanguageAlignedTrainingText/);
  assert.match(appSource, /const trainingValidationMethod = pickLanguageAlignedTrainingText/);
  assert.match(appSource, /const trainingVerificationMethod = pickLanguageAlignedTrainingText/);
  assert.match(appSource, /trainingDeliverable,[\s\S]*?learnerDeliverables/);
  assert.match(appSource, /trainingValidationMethod,[\s\S]*?trainingVerificationMethod,[\s\S]*?verificationSteps/);
  assert.match(appSource, /hasTrainingCard \? boundTrainingCardFacts\?\.text\.deliverable \?\? trainingDeliverable : undefined/);
  assert.match(appSource, /hasTrainingCard \? boundTrainingCardFacts\?\.text\.validationMethod \?\? trainingValidationMethod : undefined/);
  assert.match(appSource, /hasTrainingCard \? boundTrainingCardFacts\?\.text\.verificationMethod \?\? trainingVerificationMethod : undefined/);

  assert.match(source, /deliverable\?: string;/);
  assert.match(source, /validationMethod\?: string;/);
  assert.match(source, /verificationMethod\?: string;/);
  assert.match(source, /const resolvedDeliverables = uniqueTrainingCardItems\(\[deliverable, \.\.\.deliverables\]\);/);
  assert.match(source, /const resolvedVerifyItems = uniqueTrainingCardItems\(\[[\s\S]*?validationMethod,[\s\S]*?verificationMethod,[\s\S]*?\.\.\.verifyItems,/);
  assert.match(source, /const cardOnlyVerification = resolvedVerifyItems\.length > 1/);
  assert.match(source, /firstText\(\s*resolvedVerifyItems\[0\],/);
});

test('training card-only mode replaces the full phase rail with the active phase at the narrowest sidebar width', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
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
  assert.match(source, /const visibleTrainingCardTitle =[\s\S]*?liveTrainingNextChallengeTitle\(/);
  assert.match(source, /trainingRestoreForeground/);
  assert.match(
    source,
    /cardId: activeTrainingCardId,[\s\S]*?taskTitle: visibleTrainingCardTitle \?\? liveTrainingTitle,[\s\S]*?cardTitle: visibleTrainingCardTitle,/,
  );
  assert.match(source, /visibleTitle: visibleTrainingCardTitle,/);
  assert.match(source, /const trainingRestoreReplacesSelectedCard = Boolean\(/);
  assert.match(
    source,
    /nextHop=\{\s*hasRenderableTrainingCard && !trainingRestoreForeground && !reviewArtifactForeground\s*\? trainingNextHopCard\s*:\s*undefined\s*\}/,
  );
  assert.match(source, /scenarioLabVisible,/);
  assert.match(source, /nextHopVisible,/);
  assert.match(source, /singleCardImmersive: true,/);
  assert.match(source, /cardOnlyMode: true,/);
  assert.match(source, /postDebugVisibleFacts\(\{ activeView: "training", training: facts \}\);/);
  const trainingSource = fs.readFileSync(trainingViewSourcePath, "utf8");
  assert.doesNotMatch(trainingSource, /data-training-next-hop="true"/);
  assert.doesNotMatch(trainingSource, /function TrainingNextHopLine/);
  // Focus mode renders the single current card; the carryover row stack
  // (restored focus / outcome / next hop) shipped only in the removed
  // non-card-only branch and must not grow back.
  assert.doesNotMatch(trainingSource, /const carryoverCards/);
  assert.doesNotMatch(trainingSource, /function TrainingCarryoverRow/);
  assert.doesNotMatch(trainingSource, /<details className="training-current__more">/);
  // Queue access and its layout beside a current card are exercised by the
  // Start review scenario in trainer-session-recovery.spec.js.
});
