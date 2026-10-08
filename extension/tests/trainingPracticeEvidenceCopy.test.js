
// PR-7: styles.css is an @import aggregator; the real rules live in
// styles/sections/*.css. Read them concatenated in manifest order so
// assertions see the same bytes the browser gets after bundling.
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

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const appUiCopySourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'appUiCopy.ts',
);
const trainingViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);
const stylesSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const composerSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);

function cssBlockForSelector(source, selector) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = source.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`));
  assert.ok(match, `expected CSS block for ${selector}`);
  return match[1];
}

function assertNoCssOrderProperty(source, selector) {
  assert.doesNotMatch(cssBlockForSelector(source, selector), /(^|[;\s])order\s*:/);
}

test('training pasted proof stays hidden until it can change the verdict', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');

  assert.match(appSource, /const handleSubmitTrainingEvidence = useCallback\(/);
  assert.match(
    appSource,
    /requestTrainingPersistence\(trainerCommands\.trainingCardStatusTransition,\s*\{\s*cardId: activeTrainingCardId,\s*newStatus: "active",\s*reason: "study_note_submitted",/,
  );
  assert.match(
    appSource,
    /const shouldReviewAnsweredFlash =\s*trainingComposerReflectMode\s*&&\s*trainingComposerReflectReason === "flash_answered"\s*&&\s*activeTrainingCardId;/,
  );
  assert.match(
    appSource,
    /requestTrainingPersistence\(trainerCommands\.trainingCardStatusTransition,\s*\{\s*cardId: activeTrainingCardId,\s*newStatus: "reviewed",\s*reason: "flash_reflection_submitted",/,
  );
  assert.match(
    appSource,
    /requestTrainingPersistence\(trainerCommands\.evidenceEnqueue,\s*\{\s*source: "learning_signal",\s*summary: normalizedEvidence,/,
  );
  assert.match(appSource, /const trainingComposerPhase = trainingExecutionState\.composerPhase;/);
  assert.match(appSource, /const trainingComposerStudyMode =\s*trainingCardType === "practice" && trainingComposerPhase === "learn";/);
  assert.match(appSource, /const trainingComposerPracticeInputMode =\s*trainingCardType === "practice" && trainingComposerPhase === "try";/);
  assert.match(
    appSource,
    /setTrainingComposerPracticeReturnMode\(\s*trainingCardBlocked && !trainingCardVerified \? "blocked" : "result",/,
  );
  assert.match(appSource, /const trainingPrimaryAction = !hasTrainingCard \? undefined : \(/);
  assert.match(appSource, /id: "composer-verify-file"/);
  assert.match(appSource, /onClick: handleVerifyTrainingFromIde/);
  assert.doesNotMatch(appSource, /onClick=\{handleVerifyTrainingFromIde\}/);
  // The pasted-proof facts live in the single collapsed task-details
  // disclosure; the separate body-section plumbing and the flash/practice
  // proof cards shipped only in the removed secondary branch.
  assert.doesNotMatch(trainingViewSource, /const cardOnlyBodySections/);
  assert.doesNotMatch(trainingViewSource, /flashProofSurface/);
  assert.doesNotMatch(trainingViewSource, /practiceProofSurface/);
  assert.match(trainingViewSource, /data-training-card-fact="deliverable"/);
  assert.match(trainingViewSource, /data-training-card-fact="verify"/);
  assert.match(trainingViewSource, /data-training-card-fact="return"/);
  assert.doesNotMatch(trainingViewSource, /training-current__response-shell/);
});

test('training single-card keeps the knowledge card separate from composer verification', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
});

test('training structured guidance is wired from App into a collapsed single-card helper layer', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const stylesSource = readStylesSource();

  assert.match(appSource, /suggestedWorkspaceAction=\{localizedSuggestedWorkspaceAction\}/);
  assert.match(appSource, /scenario=\{localizedScenario\}/);
  assert.match(appSource, /apiHints=\{!reviewArtifactForeground && hasTrainingCard \? readTrainingCardList\(boundTrainingCardFacts, "apiHints", \(\) => trainingApiHints\) : \[\]\}/);
  assert.match(appSource, /cardOnly=\{true\}/);
  assert.match(appSource, /constraints=\{!reviewArtifactForeground && hasTrainingCard \? readTrainingCardList\(boundTrainingCardFacts, "constraints", \(\) => trainingConstraints\) : \[\]\}/);
  assert.match(appSource, /selfCheck=\{!reviewArtifactForeground && hasTrainingCard \? readTrainingCardList\(boundTrainingCardFacts, "selfCheck", \(\) => trainingSelfCheck\) : \[\]\}/);
  assert.match(appSource, /filesToTouch=\{!reviewArtifactForeground && hasTrainingCard \? readTrainingCardList\(boundTrainingCardFacts, "filesToTouch", \(\) => trainingFilesToTouch\) : \[\]\}/);
  assert.match(appSource, /hintLadder=\{!reviewArtifactForeground && hasTrainingCard && !trainingComposerReturnMode \? readTrainingCardList\(boundTrainingCardFacts, "hintLadder", \(\) => trainingHintLadder\) : \[\]\}/);
  assert.match(appSource, /commonMistakes=\{!reviewArtifactForeground && hasTrainingCard \? readTrainingCardList\(boundTrainingCardFacts, "commonMistakes", \(\) => trainingCommonMistakes\) : \[\]\}/);
  assert.match(appSource, /stuckRecovery=\{reviewArtifactForeground \? trainingState\?\.reviewArtifact\?\.guardrail : hasTrainingCard \? readTrainingCardText\(boundTrainingCardFacts, "stuckRecovery", \(\) => trainingStuckRecovery\) : undefined\}/);
  assert.match(appSource, /reflectionPrompt=\{reviewArtifactForeground \? trainingState\?\.reviewArtifact\?\.guardrail : hasTrainingCard \? readTrainingCardText\(boundTrainingCardFacts, "reflectionPrompt", \(\) => trainingReflectionPrompt\) : undefined\}/);

  // Focus mode keeps App's structured-guidance wiring, but the view surfaces
  // only the hint ladder inline (try phase); the guardrails/next-move helper
  // disclosures shipped only in the removed secondary branch.
  assert.doesNotMatch(trainingViewSource, /className="training-next-move"/);
  assert.doesNotMatch(trainingViewSource, /className="training-guidance-details"/);
  assert.match(trainingViewSource, /cardOnly\?: boolean;/);
  assert.match(
    trainingViewSource,
    /scenarioPackLabel\s*\?\s*`\$\{trainingWorkbenchText\(language, "scenarioPack"\)\}: \$\{scenarioPackLabel\}`/,
  );
  assert.match(trainingViewSource, /hintLadder\.length && cardType === "practice" \? <HintLadderReveal/);
  assert.match(trainingViewSource, /Hints and guardrails/);
  assert.match(trainingViewSource, /Files to touch/);
  assert.match(trainingViewSource, /API hints/);
  assert.match(trainingViewSource, /stuckRecovery\?\.trim\(\)/);

  assert.match(stylesSource, /\.training-code-list\s*\{/);
});

test('training verification-return strip is driven by snapshot status, not summary guessing', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const stylesSource = readStylesSource();

  assert.match(appSource, /selectedCardStatus=\{effectiveSelectedTrainingCardStatus\}/);
  assert.match(
    appSource,
    /latestTrainingHandoffStatus=\{\s*reviewArtifactForeground \|\| trainingRestoreReplacesSelectedCard\s*\? undefined\s*:\s*trainingState\?\.latestTrainingHandoff\?\.handoffStatus\s*\}/,
  );
  assert.match(
    appSource,
    /latestTrainingNextHopStatus=\{\s*reviewArtifactForeground \|\| trainingRestoreReplacesSelectedCard\s*\? undefined\s*:\s*trainingState\?\.latestTrainingNextHop\?\.status\s*\}/,
  );
  assert.match(
    appSource,
    /latestVerifiedResult=\{\s*reviewArtifactForeground\s*\? undefined\s*:\s*trainingRestoreReplacesSelectedCard\s*\? undefined\s*:\s*pickLanguageAlignedTrainingText\(/,
  );
  assert.match(appSource, /verificationNotice=\{trainingVerifyNotice\}/);
  assert.match(
    appSource,
    /latestLearningBlocker=\{\s*\(reviewArtifactForeground \? trainingState\?\.reviewArtifact\?\.blockedReason : undefined\) \?\?[\s\S]*?trainingRestoreReplacesSelectedCard[\s\S]*?pickLanguageAlignedTrainingText\(/,
  );
  assert.match(appSource, /const trainingComposerManualPracticeMode =/);
  assert.match(appSource, /const trainingComposerFilePracticeMode =/);
  assert.match(appSource, /const trainingComposerReflectMode = trainingComposerPhase === "reflect";/);
  assert.match(appSource, /const trainingComposerReturnMode = trainingComposerPhase === "return";/);
  assert.match(
    appSource,
    /requestTrainingPersistence\(trainerCommands\.trainingPracticeReturn,\s*\{\s*cardId: activeTrainingCardId,\s*passed,\s*summary: normalizedEvidence,/,
  );
  assert.match(
    appSource,
    /requestTrainingPersistence\(trainerCommands\.trainingReflect,\s*\{\s*cardId: activeTrainingCardId,\s*handoffId: trainingHandoffId \?\? "",\s*reflection: normalizedEvidence,/,
  );
  assert.match(
    appSource,
    /requestTrainingPersistence\(trainerCommands\.trainingReturn,\s*\{\s*cardId: activeTrainingCardId,\s*handoffId: trainingHandoffId \?\? "",\s*\}\);/,
  );
  assert.match(appSource, /const trainingHandoffReflectionRequired =/);
  assert.match(appSource, /const trainingHandoffReturnRequired =/);
  assert.match(appSource, /trainingPracticeVerificationMode === "file"/);
  assert.match(appSource, /const shouldSubmitBlockedFilePracticeReturn =/);

  assert.match(trainingViewSource, /function resolveVerificationReturnState/);
  assert.match(trainingViewSource, /practiceVerificationMode: PracticeVerificationMode;/);
  assert.match(trainingViewSource, /learningSubtype\?: string;/);
  assert.match(trainingViewSource, /deriveTrainingExecutionState\(\{/);
  assert.match(trainingViewSource, /nextHopStatus === "blocked" \? input\.latestTrainingNextHopReason : undefined/);
  assert.match(trainingViewSource, /const blockedLike = trainingExecutionState\.blocked;/);
  assert.match(trainingViewSource, /const skippedLike = trainingExecutionState\.skipped;/);
  assert.match(trainingViewSource, /const verifiedLike = trainingExecutionState\.verified;/);
  assert.match(trainingViewSource, /const flashAnsweredLike = trainingExecutionState\.flashAnswered;/);
  assert.doesNotMatch(trainingViewSource, /nextHopStatus === "accepted"/);
  assert.doesNotMatch(trainingViewSource, /nextHopStatus === "continued_in_chat"/);
  assert.doesNotMatch(appSource, /latestTrainingNextHop\?\.status === "accepted"/);
  assert.match(trainingViewSource, /manualPracticeCopy\?\.verifyNote/);
  assert.match(trainingViewSource, /manualPracticeCopy\?\.fallbackHint/);
  assert.match(trainingViewSource, /Real pass\/fail still comes from Verify current file\./);
  assert.match(trainingViewSource, /This explanation or example is grounded enough to continue\./);
  assert.match(trainingViewSource, /Pass\/fail comes from the current file and diagnostics\./);
  assert.match(trainingViewSource, /Read current IDE file/);
  assert.match(trainingViewSource, /Practice verification/);

  assert.match(stylesSource, /\.training-verification-return\.is-verified/);
  assert.match(stylesSource, /\.training-verification-return\.is-needs-review/);
  assert.match(stylesSource, /\.training-verification-return\.is-blocked/);
  assert.match(trainingViewSource, /pendingPlanConfirmationLike/);
  assert.match(trainingViewSource, /formal plan is not complete/);
  assert.match(appSource, /pendingPlanConfirmation/);
});

test('training composer uses explicit try reflect return phases for practice', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(appSource, /const trainingComposerPhase = trainingExecutionState\.composerPhase;/);
  assert.match(
    appSource,
    /deriveTrainingExecutionState\(\{[\s\S]*?latestTrainingNextHopStatus:\s*reviewArtifactForeground \|\| trainingRestoreReplacesSelectedCard\s*\? undefined\s*:\s*trainingState\?\.latestTrainingNextHop\?\.status,/,
  );
  assert.match(appSource, /const trainingComposerReflectReason = trainingExecutionState\.reflectReason;/);
  assert.match(appSource, /const resolvedComposerSummary = trainingComposerTalkMode/);
  assert.match(appSource, /:\s*composerUsesTrainingFlow\s*\?/);
  assert.match(appSource, /trainingComposerPracticeInputMode\s*\?\s*trainingComposerFilePracticeMode/);
  assert.match(appSource, /trainingComposerReturnMode\s*\?\s*trainingHandoffComposerTextCopy\.returnPlaceholder/);
  assert.match(appSource, /trainingComposerReflectMode\s*\?\s*trainingComposerReflectReason === "flash_answered"/);
  assert.match(
    appSource,
    /trainingComposerPracticeReturnMode === "result" \? "动手：结果记录" : "动手：遇到的问题"/,
  );
  assert.match(
    appSource,
    /trainingComposerPracticeReturnMode === "result" \? "动手：结果" : "动手：遇到的问题"/,
  );
  assert.match(appSource, /appUiCopy\(layout\.composerLanguage, "回流：\{v\}"\)\.replace\("\{v\}", \(\) => returnModeText\)/);
  assert.match(appSource, /appUiCopy\(layout\.composerLanguage, "复盘：\{v\}"\)\.replace\("\{v\}", \(\) => reflectFallbackText\)/);
  assert.match(
    appSource,
    /trainingComposerReflectReason === "flash_answered"\s*\?\s*appUiCopy\(layout\.composerLanguage, /,
  );
  const appUiCopySource = fs.readFileSync(appUiCopySourcePath, 'utf8');
  assert.match(appUiCopySource, /"en-US": "Reflect: One rule"/);
  assert.match(appUiCopySource, /"en-US": "Reflect: Smaller slice"/);
  assert.match(appUiCopySource, /"en-US": "Reflect: Verified rule"/);
  assert.match(appSource, /State the rule you just confirmed and how you will reuse it\./);
});

test('training return is an empty-draft command and handoff composer copy is localized', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const composerSource = fs.readFileSync(composerSourcePath, 'utf8');
  const stylesSource = readStylesSource();

  assert.match(appSource, /const trainingHandoffComposerCopy: Record<ComposerLanguage, TrainingHandoffComposerCopy>/);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(appSource, new RegExp('"' + language + '": \\{[\\s\\S]*?reflectAccessibilityLabel:'));
  }
  assert.match(appSource, /const allowEmptyTrainingReturnSubmission =\s*composerUsesTrainingFlow\s*&&\s*trainingComposerReturnMode\s*&&\s*trainingHandoffReturnRequired/);
  assert.match(appSource, /if \(!normalizedDraft && !hasImageAttachments && !allowEmptyTrainingReturnSubmission\)/);
  assert.match(
    appSource,
    /if \(allowEmptyTrainingReturnSubmission\) \{\s*try \{\s*await handleSubmitTrainingEvidence\(""\);/,
  );
  assert.match(appSource, /const shouldSubmitTrainingHandoffReturn =\s*trainingComposerReturnMode\s*&&\s*trainingHandoffReturnRequired/);
  assert.match(
    appSource,
    /requestTrainingPersistence\(trainerCommands\.trainingReturn,\s*\{\s*cardId: activeTrainingCardId,\s*handoffId: trainingHandoffId \?\? "",/,
  );
  assert.match(appSource, /allowEmptySubmit=\{allowEmptyTrainingReturnSubmission\}/);
  assert.match(appSource, /inputReadOnly=\{allowEmptyTrainingReturnSubmission\}/);
  assert.match(appSource, /submitAriaLabel=\{localizedTrainingComposerSubmitAriaLabel\}/);

  assert.match(composerSource, /allowEmptySubmit\?: boolean;/);
  assert.match(composerSource, /inputReadOnly\?: boolean;/);
  assert.match(composerSource, /const hasSubmissionPermission = allowEmptySubmit \|\| hasSubmissionContent;/);
  assert.match(composerSource, /readOnly=\{inputReadOnly\}/);
  assert.match(stylesSource, /@media \(max-width: 480px\) \{[\s\S]*?data-training-loop-layout="3-plus-2"/);
  assert.match(stylesSource, /white-space: normal;/);
});

test('training practice verification sends expected symbols while flash stays local-answer based', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const stylesSource = readStylesSource();

  assert.match(appSource, /function trainingExpectedSymbols/);
  assert.match(appSource, /selectedTrainingCardCandidate\?\.expectedSymbols/);
  assert.match(appSource, /selectedTrainingRouteCard\?\.expectedSymbols/);
  assert.match(appSource, /trainingLedgerEntry\?\.expectedSymbols/);
  assert.match(appSource, /expectedSymbols: trainingCardType === "practice" \? readTrainingCardList\(boundTrainingCardFacts, "expectedSymbols", \(\) => practiceExpectedSymbols\) : \[\]/);
  assert.match(appSource, /expectedSymbols=\{trainingCardType === "practice" \? readTrainingCardList\(boundTrainingCardFacts, "expectedSymbols", \(\) => practiceExpectedSymbols\) : \[\]\}/);

  assert.match(appSource, /const handleVerifyTrainingFromIde = useCallback\(\(\) => \{/);
  assert.match(
    appSource,
    /postMessage\(\{\s*type: "command\/execute",\s*payload: \{\s*commandId: trainerCommands\.evaluateCurrentFile,\s*payload: \{\s*source: "training",\s*cardId: activeTrainingCardId,/,
  );
  assert.match(appSource, /if \(trainingComposerUsesAnswerMode\) \{[\s\S]*?await requestTrainingPersistence\([\s\S]*?sendTrainingFeedback\(/);

  assert.match(trainingViewSource, /expectedSymbols\?: string\[\]/);
  assert.match(trainingViewSource, /visibleExpectedSymbols/);
  assert.match(trainingViewSource, /Code symbols to check/);
  assert.match(stylesSource, /\.training-proof-card__symbols/);
});

test('training app prefers practice when selection is ambiguous and passes real flash card payload through', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(appSource, /function firstTrainingCardOfType/);
  assert.match(appSource, /routeSelectedCardId/);
  assert.match(appSource, /selectedTrainingCardCandidate\?\.type \?\? "practice"/);
  assert.match(appSource, /const trainingScenarioPackLabel = pickLanguageAlignedTrainingText\(/);
  assert.match(appSource, /const selectedTrainingFlashCard =/);
  assert.match(appSource, /selectedTrainingFlashCard\?\.question/);
  assert.match(appSource, /selectedTrainingFlashCard\?\.choices\?\.length/);
  assert.match(appSource, /scenarioPackLabel=\{hasTrainingCard \? readTrainingCardText\(boundTrainingCardFacts, "scenarioPack", \(\) => trainingScenarioPackLabel\) : undefined\}/);
  assert.match(appSource, /flashPrompt=\{trainingFlashPrompt\}/);
  assert.match(appSource, /const trainingFlashChoices =/);
  assert.match(appSource, /const normalizedTrainingFlashChoices = useMemo\(/);
});

test('training view stays truthful when no governed card exists and keeps verification card-scoped first', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');

  assert.match(
    appSource,
    /const authoritativeVerifyItems =\s*cardScopedVerifyItems\.length > 0 \? cardScopedVerifyItems : contextualTrainingVerifyItems;/,
  );
  assert.match(
    appSource,
    /const visibleTrainingCardTitle = reviewArtifactForeground\s*\? selectedTrainingCardCandidate\?\.title\s*:\s*liveTrainingNextChallengeTitle\([\s\S]*?trainingRestoreForeground \? selectedTrainingCardCandidate\?\.title : undefined,/,
  );
  assert.match(
    appSource,
    /const title = hasRenderableTrainingCard[\s\S]*?visibleTrainingCardTitle,[\s\S]*?trainingState\?\.latestTrainingHandoff\?\.cardTitle,/,
  );
  assert.match(
    appSource,
    /const currentStep = hasRenderableTrainingCard[\s\S]*?trainingProblemStatement,[\s\S]*?trainingSuggestedWorkspaceAction,[\s\S]*?trainingDeliverables\[0\],/,
  );
  assert.match(appSource, /deliverables=\{reviewArtifactForeground \? selectedTrainingCardCandidate\?\.learnerDeliverables \?\? \[\] : hasTrainingCard \? readTrainingCardList\(boundTrainingCardFacts, "learnerDeliverables", \(\) => trainingDeliverables\) : \[\]\}/);
  assert.match(appSource, /verifyItems=\{reviewArtifactForeground \? selectedTrainingCardCandidate\?\.verificationSteps \?\? \[\] : hasTrainingCard \? boundTrainingCardFacts \? boundTrainingCardFacts\.lists\.verificationSteps \?\? boundTrainingCardFacts\.lists\.acceptanceCriteria \?\? \[\] : authoritativeVerifyItems : \[\]\}/);
  assert.match(appSource, /outcome=\{!reviewArtifactForeground && hasTrainingCard \? trainingOutcomeCard : undefined\}/);
  assert.match(
    appSource,
    /nextHop=\{\s*hasRenderableTrainingCard && !trainingRestoreForeground && !reviewArtifactForeground\s*\? trainingNextHopCard\s*:\s*undefined\s*\}/,
  );

  assert.match(trainingViewSource, /successSignal\?: string;/);
  assert.match(trainingViewSource, /const resolvedSuccessSignal = firstText\(successSignal\?\.trim\(\)\);/);
  // Verification stays card-scoped: the task-details disclosure renders the
  // card's own verify fact and return fact, never a global next-hop summary.
  assert.match(trainingViewSource, /data-training-card-fact="verify"><span className="template-metadata">/);
  assert.match(trainingViewSource, /\{cardOnlyVerification \?\? ""\}/);
  assert.match(trainingViewSource, /data-training-card-fact="return"><MessageRichContent body=\{resolvedReturnWith \|\| defaultReturnPath\}/);
});

test('training current card never borrows a global action or another card\'s next-hop copy', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const currentStepStart = appSource.indexOf('const currentStep = hasRenderableTrainingCard');
  const currentStepEnd = appSource.indexOf('const localizedSuggestedWorkspaceAction', currentStepStart);
  const visibleNextStart = trainingViewSource.indexOf('const visibleNextAfterCompletion =');
  const visibleNextEnd = trainingViewSource.indexOf('const hasPrimaryLoop', visibleNextStart);

  assert.ok(currentStepStart >= 0 && currentStepEnd > currentStepStart, 'expected current-card copy');
  assert.ok(visibleNextStart >= 0 && visibleNextEnd > visibleNextStart, 'expected completion-copy guard');

  const currentStep = appSource.slice(currentStepStart, currentStepEnd);
  const visibleNext = trainingViewSource.slice(visibleNextStart, visibleNextEnd);

  assert.match(currentStep, /trainingProblemStatement,[\s\S]*?trainingSuggestedWorkspaceAction,[\s\S]*?trainingDeliverables\[0\]/);
  assert.doesNotMatch(
    currentStep,
    /latestTrainingNextHop\?\.summary|implementationGuide\?\.currentStep|resolvedCoachNextStep|data\.task\.nextActionLabel/,
  );
  assert.doesNotMatch(appSource, /returnPath=\{returnPath\}/);
  assert.doesNotMatch(trainingViewSource, /returnPath\?: string;/);
  assert.match(trainingViewSource, /function isCurrentCardActionLabel\(value: string\): boolean/);
  assert.match(visibleNext, /!isCurrentCardActionLabel\(resolvedNextAfterCompletion\)/);
  assert.doesNotMatch(visibleNext, /isFlashCard/);
});
