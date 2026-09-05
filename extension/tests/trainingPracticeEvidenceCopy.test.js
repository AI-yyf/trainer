'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
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
  assert.match(appSource, /const trainingPrimaryAction = !hasTrainingCard \? undefined : undefined;/);
  assert.match(appSource, /id: "composer-verify-file"/);
  assert.match(appSource, /onClick: handleVerifyTrainingFromIde/);
  assert.doesNotMatch(appSource, /onClick=\{handleVerifyTrainingFromIde\}/);
  assert.match(trainingViewSource, /const cardOnlyBodySections: TrainingCardOnlySection\[\] = \[/);
  assert.match(trainingViewSource, /key: "current"/);
  assert.match(trainingViewSource, /key: "verify"/);
  assert.match(trainingViewSource, /key: "return"/);
  assert.match(trainingViewSource, /!cardOnly \? \(isFlashCard \? flashProofSurface : practiceProofSurface\) : null/);
  assert.doesNotMatch(trainingViewSource, /training-current__response-shell/);
});

test('training single-card keeps the knowledge card separate from composer verification', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');

  const cardFaceIndex = trainingViewSource.indexOf('className="training-current__card-face"');
  const whyIndex = trainingViewSource.indexOf('data-view-why=""');
  const cardOnlySectionsStart = trainingViewSource.indexOf('const cardOnlyBodySections');
  const cardOnlySectionsEnd = trainingViewSource.indexOf('const hasAdjustmentOutcome', cardOnlySectionsStart);
  const cardOnlySections = trainingViewSource.slice(cardOnlySectionsStart, cardOnlySectionsEnd);

  assert.notEqual(cardFaceIndex, -1, 'expected the current card face');
  assert.notEqual(whyIndex, -1, 'expected why-now on the card face');
  assert.ok(cardFaceIndex < whyIndex, 'why-now stays on the current card face');
  assert.match(cardOnlySections, /key: "current"/);
  assert.match(cardOnlySections, /key: "why-now"/);
  assert.match(cardOnlySections, /key: "deliverable"/);
  assert.match(cardOnlySections, /key: "verify"/);
  assert.match(cardOnlySections, /key: "return"/);
  assert.match(cardOnlySections, /detail: routeVerifySummary/);
  assert.match(cardOnlySections, /detail: routeReturnSummary/);
  assert.doesNotMatch(trainingViewSource, /training-current__card-footer/);
  assert.match(appSource, /const renderTrainingComposerAccessory = \(\) => \{/);
  assert.doesNotMatch(appSource, /id: "training-verify-current-file"/);
  const primaryActionStart = appSource.indexOf('const trainingPrimaryAction =');
  const primaryActionEnd = appSource.indexOf('const trainingCoachActionLabel =', primaryActionStart);
  assert.ok(primaryActionStart >= 0 && primaryActionEnd > primaryActionStart, 'expected current-card action');
  const primaryAction = appSource.slice(primaryActionStart, primaryActionEnd);
  assert.doesNotMatch(primaryAction, /onClick=\{handleVerifyTrainingFromIde\}/);
  assert.match(appSource, /id: "composer-verify-file"/);
  assert.match(appSource, /onClick: handleVerifyTrainingFromIde/);
  assert.match(appSource, /showComposerTrainingVerify/);
  assert.equal(
    (appSource.match(/onClick=\{handleVerifyTrainingFromIde\}/g) ?? []).length,
    0,
    'file verification lives on the composer, not the card primary',
  );
  assert.doesNotMatch(trainingViewSource, /training-current__response-shell/);
  assert.doesNotMatch(stylesSource, /\.training-current__response-shell/);
  assertNoCssOrderProperty(stylesSource, '.training-current__card-face');
});

test('training structured guidance is wired from App into a collapsed single-card helper layer', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');

  assert.match(appSource, /suggestedWorkspaceAction=\{localizedSuggestedWorkspaceAction\}/);
  assert.match(appSource, /scenario=\{localizedScenario\}/);
  assert.match(appSource, /apiHints=\{hasTrainingCard \? trainingApiHints : \[\]\}/);
  assert.match(appSource, /cardOnly=\{true\}/);
  assert.match(appSource, /constraints=\{hasTrainingCard \? trainingConstraints : \[\]\}/);
  assert.match(appSource, /selfCheck=\{hasTrainingCard \? trainingSelfCheck : \[\]\}/);
  assert.match(appSource, /filesToTouch=\{hasTrainingCard \? trainingFilesToTouch : \[\]\}/);
  assert.match(appSource, /hintLadder=\{hasTrainingCard \? trainingHintLadder : \[\]\}/);
  assert.match(appSource, /commonMistakes=\{hasTrainingCard \? trainingCommonMistakes : \[\]\}/);
  assert.match(appSource, /stuckRecovery=\{hasTrainingCard \? trainingStuckRecovery : undefined\}/);
  assert.match(appSource, /reflectionPrompt=\{hasTrainingCard \? trainingReflectionPrompt : undefined\}/);

  assert.match(trainingViewSource, /className="training-next-move"/);
  assert.match(trainingViewSource, /className="training-guidance-details"/);
  assert.match(trainingViewSource, /cardOnly\?: boolean;/);
  assert.match(trainingViewSource, /scenarioPackLabel \? `\$\{isZh \? "\\u573a\\u666f\\u5305" : "Scenario pack"\}/);
  assert.match(trainingViewSource, /isFlashCard && !cardOnly && nextMovePrimary && !learnPhaseActive/);
  assert.match(trainingViewSource, /Hints and guardrails/);
  assert.match(trainingViewSource, /Files to touch/);
  assert.match(trainingViewSource, /API hints/);
  assert.match(trainingViewSource, /constraints\.length > 0/);
  assert.match(trainingViewSource, /selfCheck\.length > 0/);
  assert.match(trainingViewSource, /hintLadder\.length > 0/);
  assert.match(trainingViewSource, /commonMistakes\.length > 0/);
  assert.match(trainingViewSource, /stuckRecovery\?\.trim\(\)/);
  assert.match(trainingViewSource, /reflectionPrompt\?\.trim\(\)/);
  assert.match(trainingViewSource, /open=\{verificationReturn\.kind === "blocked" && Boolean\(stuckRecovery\?\.trim\(\)\)\}/);

  assert.match(stylesSource, /\.training-next-move\s*\{/);
  assert.match(stylesSource, /\.training-guidance-details\s*\{/);
  assert.match(stylesSource, /\.training-code-list\s*\{/);
});

test('training verification-return strip is driven by snapshot status, not summary guessing', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');

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
    /latestVerifiedResult=\{\s*trainingRestoreReplacesSelectedCard\s*\? undefined\s*:\s*pickLanguageAlignedTrainingText\(/,
  );
  assert.match(
    appSource,
    /latestLearningBlocker=\{\s*trainingVerifyNotice \?\?[\s\S]*?trainingRestoreReplacesSelectedCard[\s\S]*?pickLanguageAlignedTrainingText\(/,
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
  assert.match(appSource, /trainingComposerReturnMode\s*\?\s*layout\.composerLanguage === "zh-CN"/);
  assert.match(appSource, /trainingComposerReflectMode\s*\?\s*trainingComposerReflectReason === "flash_answered"/);
  assert.match(appSource, /Try: \$\{trainingComposerPracticeReturnMode === "result" \? "Result note" : "Blocker"\}/);
  assert.match(appSource, /`Return: \$\{truncateInlineText\(trainingReturnWithText \?\? trainingSuccessSignal \?\? trainingCoachBridge\.ctaLabel,/);
  assert.match(appSource, /`Reflect: \$\{truncateInlineText\(trainingFallbackActionText \?\? trainingComposerSelectedVerifyItem \?\? trainingState\?\.latestLearningBlocker,/);
  assert.match(appSource, /Reflect: One rule/);
  assert.match(appSource, /Reflect: Smaller slice/);
  assert.match(appSource, /Reflect: Verified rule/);
  assert.match(appSource, /State the rule you just confirmed and how you will reuse it\./);
});

test('training return is an empty-draft command and handoff composer copy is localized', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const composerSource = fs.readFileSync(composerSourcePath, 'utf8');
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');

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
  const stylesSource = fs.readFileSync(stylesSourcePath, 'utf8');

  assert.match(appSource, /function trainingExpectedSymbols/);
  assert.match(appSource, /selectedTrainingCardCandidate\?\.expectedSymbols/);
  assert.match(appSource, /selectedTrainingRouteCard\?\.expectedSymbols/);
  assert.match(appSource, /trainingLedgerEntry\?\.expectedSymbols/);
  assert.match(appSource, /expectedSymbols: trainingCardType === "practice" \? practiceExpectedSymbols : \[\]/);
  assert.match(appSource, /expectedSymbols=\{trainingCardType === "practice" \? practiceExpectedSymbols : \[\]\}/);

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
  assert.match(appSource, /scenarioPackLabel=\{hasTrainingCard \? trainingScenarioPackLabel : undefined\}/);
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
    /const visibleTrainingCardTitle = liveTrainingNextChallengeTitle\([\s\S]*?trainingRestoreForeground \? selectedTrainingCardCandidate\?\.title : undefined,/,
  );
  assert.match(
    appSource,
    /const title = hasRenderableTrainingCard[\s\S]*?visibleTrainingCardTitle,[\s\S]*?trainingState\?\.latestTrainingHandoff\?\.cardTitle,/,
  );
  assert.match(
    appSource,
    /const currentStep = hasRenderableTrainingCard[\s\S]*?trainingProblemStatement,[\s\S]*?trainingSuggestedWorkspaceAction,[\s\S]*?trainingDeliverables\[0\],/,
  );
  assert.match(appSource, /deliverables=\{hasTrainingCard \? trainingDeliverables : \[\]\}/);
  assert.match(appSource, /verifyItems=\{hasTrainingCard \? authoritativeVerifyItems : \[\]\}/);
  assert.match(appSource, /outcome=\{hasTrainingCard \? trainingOutcomeCard : undefined\}/);
  assert.match(
    appSource,
    /nextHop=\{\s*hasRenderableTrainingCard && !trainingRestoreForeground\s*\? trainingNextHopCard\s*:\s*undefined\s*\}/,
  );

  assert.match(trainingViewSource, /successSignal\?: string;/);
  assert.match(trainingViewSource, /const resolvedSuccessSignal = firstText\(successSignal\?\.trim\(\)\);/);
  assert.match(trainingViewSource, /const cardOnlyBodySections: TrainingCardOnlySection\[\] = \[/);
  assert.match(trainingViewSource, /detail: routeVerifySummary/);
  assert.match(trainingViewSource, /detail: routeReturnSummary/);
  assert.match(trainingViewSource, /!cardOnly \? \(isFlashCard \? flashProofSurface : practiceProofSurface\) : null/);
});

test('training current card never borrows a global action or another card\'s next-hop copy', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const trainingViewSource = fs.readFileSync(trainingViewSourcePath, 'utf8');
  const currentStepStart = appSource.indexOf('const currentStep = hasRenderableTrainingCard');
  const currentStepEnd = appSource.indexOf('const localizedSuggestedWorkspaceAction', currentStepStart);
  const visibleNextStart = trainingViewSource.indexOf('const visibleNextAfterCompletion =');
  const visibleNextEnd = trainingViewSource.indexOf('const normalizedCardTitle', visibleNextStart);

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
