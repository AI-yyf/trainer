'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const copyPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'copy.ts');
const trainingCoachBridgePath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'trainingCoachBridge.ts',
);
const trainingViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);
const previewHarnessPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewHarness.ts',
);

test('training card content has a stricter language boundary than ambient coach UI', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /function pickLanguageAlignedTrainingText\([\s\S]*?isLanguageAlignedUiText\(language, resolved\)/);
  assert.match(source, /function pickLanguageAlignedTrainingList\([\s\S]*?filter\(\(value\) => isLanguageAlignedUiText\(language, value\)\)/);

  assert.match(source, /const trainingDeliverables = pickLanguageAlignedTrainingList/);
  assert.match(source, /const cardScopedVerifyItems = pickLanguageAlignedTrainingList/);
  assert.match(source, /trainingWhyThisCard = leftoverTrainingHandoffChromeNotLive/);
  assert.match(source, /const trainingProblemStatement = pickLanguageAlignedTrainingText/);
  assert.match(source, /const trainingReturnWithText = leftoverTrainingHandoffChromeNotLive[\s\S]*?:\s*pickLanguageAlignedTrainingText/);
  assert.match(source, /const trainingSuccessSignal = leftoverTrainingHandoffChromeNotLive[\s\S]*?:\s*pickLanguageAlignedTrainingText/);

  assert.match(source, /whyThisCard=\{localizedWhyNow\}/);
  assert.match(
    source,
    /latestVerifiedResult=\{\s*trainingRestoreReplacesSelectedCard\s*\? undefined\s*:\s*pickLanguageAlignedTrainingText/,
  );
  assert.match(
    source,
    /latestLearningBlocker=\{\s*trainingVerifyNotice \?\?\s*\(leftoverTrainingHandoffChromeNotLive \|\| trainingRestoreReplacesSelectedCard\s*\? undefined\s*:\s*pickLanguageAlignedTrainingText/,
  );
  assert.match(source, /recentWins=\{pickLanguageAlignedTrainingList/);
  assert.doesNotMatch(source, /whyThisCard=\{trainingWhyThisCard\}/);
});

test('zh-CN training rejects mixed English prose with a single Chinese token', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /function hasExcessiveEnglishProseForChinese/);
  assert.match(source, /function containsJapaneseText/);
  assert.match(source, /function containsKoreanText/);
  assert.match(source, /!containsJapaneseText\(normalized\)[\s\S]*?!containsKoreanText\(normalized\)[\s\S]*?containsChineseText\(normalized\)[\s\S]*?!hasExcessiveEnglishProseForChinese\(normalized\)/);
  assert.match(source, /language === "ja-JP"[\s\S]*?containsJapaneseText\(normalized\)/);
  assert.match(source, /language === "ko-KR"[\s\S]*?containsKoreanText\(normalized\)/);
});

test('training contextual status and Coach jump actions resolve through all locale copy paths', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const copySource = fs.readFileSync(copyPath, 'utf8');
  const previewSource = fs.readFileSync(previewHarnessPath, 'utf8');
  const overrideStart = copySource.indexOf('const contextRailLocaleOverrides');
  const overrideEnd = copySource.indexOf('\n};', overrideStart);
  const reviewStart = previewSource.indexOf('const reviewSummary = previewText');
  const reviewEnd = previewSource.indexOf('\n  );', reviewStart);

  assert.ok(overrideStart >= 0 && overrideEnd > overrideStart, 'expected context rail locale overrides');
  assert.ok(reviewStart >= 0 && reviewEnd > reviewStart, 'expected localized preview review summary');
  assert.match(appSource, /t\.viewContextWorking/);
  assert.match(appSource, /t\.viewContextBlocker/);
  assert.match(appSource, /t\.viewContextLatest/);
  assert.match(appSource, /t\.viewContextCoach/);

  const overrideSource = copySource.slice(overrideStart, overrideEnd);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(overrideSource, new RegExp(`"${language}":\\s*\\{[\\s\\S]*?openCoach:`));
  }

  const reviewSource = previewSource.slice(reviewStart, reviewEnd);
  for (const language of ['es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(reviewSource, new RegExp(`"${language}":`));
  }
});

test('training review actions do not fall back to English in supported locales', () => {
  const copySource = fs.readFileSync(copyPath, 'utf8');

  for (const label of [
    '开始复习',
    'Start Review',
    'Revisar',
    'Commencer la révision',
    'Wiederholung starten',
    '復習を始める',
    '복습 시작',
    'Iniciar revisão',
  ]) {
    assert.match(copySource, new RegExp(`runReview: "${label}"`));
  }
});

test('guided training preview reuses localized card copy for cross-card and progress summaries', () => {
  const source = fs.readFileSync(previewHarnessPath, 'utf8');
  const nextHopStart = source.indexOf('const nextHopSummary =');
  const nextHopEnd = source.indexOf('\n  const taskDescription', nextHopStart);
  const progressStart = source.indexOf('latestLearningPartialProgress:', nextHopEnd);
  const progressEnd = source.indexOf('\n    selectedCardId:', progressStart);

  assert.ok(nextHopStart >= 0 && nextHopEnd > nextHopStart, 'expected next-hop summary');
  assert.ok(progressStart >= 0 && progressEnd > progressStart, 'expected learning progress summary');

  const nextHopSource = source.slice(nextHopStart, nextHopEnd);
  const progressSource = source.slice(progressStart, progressEnd);
  assert.match(
    nextHopSource,
    /nextCard\.problemStatement \|\|[\s\S]*?nextCard\.suggestedWorkspaceAction \|\|[\s\S]*?nextCard\.deliverable/,
  );
  assert.match(
    progressSource,
    /selectedCard\.returnWith \|\|[\s\S]*?selectedCard\.problemStatement \|\|[\s\S]*?selectedCard\.suggestedWorkspaceAction \|\|[\s\S]*?coachSummary/,
  );
  assert.doesNotMatch(nextHopSource, /nextCard\.nextAfterCompletion/);
  assert.doesNotMatch(progressSource, /selectedCard\.nextAfterCompletion/);
  assert.doesNotMatch(nextHopSource, /Lock the current rule into memory/);
  assert.doesNotMatch(progressSource, /The single-card training surface is aligned/);
});

test('training card-only fallback copy stays complete across every supported language', () => {
  const source = fs.readFileSync(trainingViewPath, 'utf8');
  const surfaceStart = source.indexOf('const trainingCardOnlySurfaceCopy');
  const surfaceEnd = source.indexOf('function trainingCardOnlySurfaceText', surfaceStart);
  const manualStart = source.indexOf('const manualPracticeFallbackCopy');
  const manualEnd = source.indexOf('function resolvePracticeVerificationMode', manualStart);
  const languages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

  assert.ok(surfaceStart >= 0 && surfaceEnd > surfaceStart, 'expected card-only fallback copy');
  assert.ok(manualStart >= 0 && manualEnd > manualStart, 'expected manual practice fallback copy');

  const surfaceCopy = source.slice(surfaceStart, surfaceEnd);
  const manualCopy = source.slice(manualStart, manualEnd);
  for (const language of languages) {
    assert.match(
      surfaceCopy,
      new RegExp(`"${language}":\\s*\\{[\\s\\S]*?flashAnswerMethod:[\\s\\S]*?returnResultOrBlocker:[\\s\\S]*?afterThis:`),
    );
    assert.match(
      manualCopy,
      new RegExp(`"${language}":\\s*\\{[\\s\\S]*?tryNote:[\\s\\S]*?verifyNote:[\\s\\S]*?composerHint:[\\s\\S]*?fallbackHint:`),
    );
  }

  assert.match(source, /const defaultReturnPath = trainingCardOnlySurfaceText\(language, "returnResultOrBlocker"\);/);
  assert.match(source, /trainingCardOnlySurfaceText\(language, "flashAnswerMethod"\)/);
  assert.match(source, /trainingCardOnlySurfaceText\(language, "currentFileDiagnostics"\)/);
  assert.match(source, /trainingCardOnlySurfaceText\(language, "afterThis"\)/);
  assert.match(source, /const cardOnlyWhyNowSummary = compactCardText\(firstText\(resolvedWhyNow\), 120\);/);
  assert.match(source, /label: trainingSurfaceLabel\(language, "currentCard"\)/);
  assert.match(source, /trainingLoopSteps\[0\] \?\? \{\s*key: "learn" as const,\s*label: trainingSurfaceLabel\(language, "currentCard"\),/);
  assert.match(
    source,
    /if \(language !== "zh-CN" && language !== "en-US"\) \{\s*return manualPracticeFallbackCopy\[language\] \?\? manualPracticeFallbackCopy\["en-US"\];\s*\}/,
  );
  assert.doesNotMatch(source, /isZh \? "\\u5f53\\u524d\\uff1a" : "Current:"/);
});

test('training entry actions and empty state use complete locale copy', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const copySource = fs.readFileSync(copyPath, 'utf8');
  const keys = [
    'trainingOpenCurrentCard',
    'trainingReturnToCoach',
    'trainingAnswerNow',
    'trainingRecordStep',
    'trainingStartStep',
    'trainingEmptyTitle',
    'trainingEmptyDescription',
  ];
  const usedKeys = [
    'trainingOpenCurrentCard',
    'trainingReturnToCoach',
    'trainingRecordStep',
    'trainingEmptyTitle',
    'trainingEmptyDescription',
  ];
  const languages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
  const overrideStart = copySource.indexOf('const trainingUiLocaleOverrides');
  const overrideEnd = copySource.indexOf('type ComposerAccessibilityCopy', overrideStart);

  assert.ok(overrideStart >= 0 && overrideEnd > overrideStart, 'expected training UI locale overrides');
  assert.match(copySource, /\.\.\.trainingUiLocaleOverrides\[language\]/);
  for (const key of usedKeys) {
    assert.match(appSource, new RegExp(`t\\.${key}`));
  }

  const overrides = copySource.slice(overrideStart, overrideEnd);
  for (const [index, language] of languages.entries()) {
    const start = overrides.indexOf(`"${language}": {`);
    const nextLanguage = languages[index + 1];
    const end = nextLanguage ? overrides.indexOf(`"${nextLanguage}": {`, start + 1) : overrides.length;

    assert.ok(start >= 0 && end > start, `expected ${language} training action copy`);
    const localeCopy = overrides.slice(start, end);
    for (const key of keys) {
      assert.match(localeCopy, new RegExp(`${key}:`));
    }
  }
});

test('training card navigation uses the shared locale copy', () => {
  const source = fs.readFileSync(trainingViewPath, 'utf8');
  const navStart = source.indexOf('<div className="training-card-nav"');
  const navEnd = source.indexOf('</div>', navStart);

  assert.ok(navStart >= 0 && navEnd > navStart, 'expected training card navigation');
  const nav = source.slice(navStart, navEnd);
  assert.match(nav, /aria-label=\{t\.training\}/);
  assert.match(nav, /title=\{t\.previousCard\}/);
  assert.match(nav, /<span>\{t\.previousCard\}<\/span>/);
  assert.match(nav, /title=\{t\.nextCard\}/);
  assert.match(nav, /<span>\{t\.nextCard\}<\/span>/);
  assert.doesNotMatch(nav, /Review previous card|Generate or move to the next card/);
});

test('training composer labels and placeholders stay localized across every card state', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const languages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
  const modeCopyStart = appSource.indexOf('const trainingComposerModeCopy');
  const modeCopyEnd = appSource.indexOf('function trainingComposerModeText', modeCopyStart);
  const placeholderStart = appSource.indexOf('const resolvedTrainingComposerPlaceholder');
  const placeholderEnd = appSource.indexOf('const resolvedCompactUtilityComposerPlaceholder', placeholderStart);
  const accessibilityStart = appSource.indexOf('const resolvedComposerAccessibilityLabel');
  const accessibilityEnd = appSource.indexOf('const refinedComposerAccessibilityLabel', accessibilityStart);
  const keys = [
    'talkPlaceholder',
    'talkAccessibilityLabel',
    'choicePlaceholder',
    'fillPlaceholder',
    'shortAnswerPlaceholder',
    'answerAccessibilityLabel',
    'studyPlaceholder',
    'studyAccessibilityLabel',
    'manualResultPlaceholder',
    'manualBlockerPlaceholder',
    'verificationPlaceholder',
    'genericPlaceholder',
    'genericAccessibilityLabel',
  ];

  assert.ok(modeCopyStart >= 0 && modeCopyEnd > modeCopyStart, 'expected training composer locale copy');
  assert.ok(placeholderStart >= 0 && placeholderEnd > placeholderStart, 'expected training composer placeholder branch');
  assert.ok(accessibilityStart >= 0 && accessibilityEnd > accessibilityStart, 'expected training composer accessibility branch');

  const modeCopy = appSource.slice(modeCopyStart, modeCopyEnd);
  for (const [index, language] of languages.entries()) {
    const start = modeCopy.indexOf(`"${language}": {`);
    const nextLanguage = languages[index + 1];
    const end = nextLanguage ? modeCopy.indexOf(`"${nextLanguage}": {`, start + 1) : modeCopy.length;

    assert.ok(start >= 0 && end > start, `expected ${language} composer copy`);
    const localeCopy = modeCopy.slice(start, end);
    for (const key of keys) {
      assert.match(localeCopy, new RegExp(`${key}:`));
    }
  }

  const placeholderSource = appSource.slice(placeholderStart, placeholderEnd);
  const accessibilitySource = appSource.slice(accessibilityStart, accessibilityEnd);
  for (const reference of [
    'trainingComposerModeTextCopy.choicePlaceholder',
    'trainingComposerModeTextCopy.fillPlaceholder',
    'trainingComposerModeTextCopy.shortAnswerPlaceholder',
    'trainingComposerModeTextCopy.studyPlaceholder',
    'trainingComposerModeTextCopy.manualResultPlaceholder',
    'trainingComposerModeTextCopy.manualBlockerPlaceholder',
    'trainingComposerModeTextCopy.verificationPlaceholder',
    'trainingComposerModeTextCopy.genericPlaceholder',
    'trainingHandoffComposerTextCopy.returnPlaceholder',
    'trainingHandoffComposerTextCopy.reflectPlaceholder',
  ]) {
    assert.ok(placeholderSource.includes(reference), `expected localized placeholder ${reference}`);
  }
  for (const reference of [
    'trainingComposerModeTextCopy.talkAccessibilityLabel',
    'trainingComposerModeTextCopy.answerAccessibilityLabel',
    'trainingComposerModeTextCopy.studyAccessibilityLabel',
    'trainingComposerModeTextCopy.genericAccessibilityLabel',
    'trainingHandoffComposerTextCopy.returnAccessibilityLabel',
    'trainingHandoffComposerTextCopy.reflectAccessibilityLabel',
  ]) {
    assert.ok(accessibilitySource.includes(reference), `expected localized label ${reference}`);
  }
  assert.doesNotMatch(placeholderSource, /Answer in one or two sentences\.|Study the card first, then note one rule|Write the grounded result|Name the blocker, the weakest proof/);
  assert.doesNotMatch(accessibilitySource, /Submit the current training answer|Submit the current training study note|Submit the current training return|Submit the current training reflection/);
});

test('training no-card and recoverable states keep actions, labels, and errors localized', () => {
  const appSource = fs.readFileSync(appPath, 'utf8');
  const bridgeSource = fs.readFileSync(trainingCoachBridgePath, 'utf8');
  const languages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
  const ctaStart = bridgeSource.indexOf('const trainingCoachCtaCopy');
  const ctaEnd = bridgeSource.indexOf('function trainingCoachCtaLabel', ctaStart);
  const failureStart = appSource.indexOf('const recoverableFailureCopy');
  const failureEnd = appSource.indexOf('const RESOURCE_OPERATION_STATUS_PATTERN', failureStart);
  const refinedAccessibilityStart = appSource.indexOf('const refinedComposerAccessibilityLabel');
  const refinedAccessibilityEnd = appSource.indexOf('const laneAwareComposerAccessibilityLabel', refinedAccessibilityStart);
  const submitAccessibilityStart = appSource.indexOf('const localizedTrainingComposerSubmitAriaLabel');
  const submitAccessibilityEnd = appSource.indexOf('const localizedTrainingComposerSummary', submitAccessibilityStart);

  assert.ok(ctaStart >= 0 && ctaEnd > ctaStart, 'expected localized Coach CTA copy');
  assert.ok(failureStart >= 0 && failureEnd > failureStart, 'expected recoverable failure copy');
  assert.ok(
    refinedAccessibilityStart >= 0 && refinedAccessibilityEnd > refinedAccessibilityStart,
    'expected no-card accessibility branch',
  );
  assert.ok(
    submitAccessibilityStart >= 0 && submitAccessibilityEnd > submitAccessibilityStart,
    'expected no-card submit label branch',
  );

  const ctaCopy = bridgeSource.slice(ctaStart, ctaEnd);
  const failureCopy = appSource.slice(failureStart, failureEnd);
  for (const [index, language] of languages.entries()) {
    const nextLanguage = languages[index + 1];
    const ctaLocaleStart = ctaCopy.indexOf(`"${language}": {`);
    const ctaLocaleEnd = nextLanguage
      ? ctaCopy.indexOf(`"${nextLanguage}": {`, ctaLocaleStart + 1)
      : ctaCopy.length;
    const failureLocaleStart = failureCopy.indexOf(`"${language}": {`);
    const failureLocaleEnd = nextLanguage
      ? failureCopy.indexOf(`"${nextLanguage}": {`, failureLocaleStart + 1)
      : failureCopy.length;

    assert.ok(ctaLocaleStart >= 0 && ctaLocaleEnd > ctaLocaleStart, `expected ${language} Coach CTA copy`);
    assert.ok(
      failureLocaleStart >= 0 && failureLocaleEnd > failureLocaleStart,
      `expected ${language} recoverable failure copy`,
    );
    const ctaLocaleCopy = ctaCopy.slice(ctaLocaleStart, ctaLocaleEnd);
    const failureLocaleCopy = failureCopy.slice(failureLocaleStart, failureLocaleEnd);
    for (const key of ['continue', 'result', 'blocker']) {
      assert.match(ctaLocaleCopy, new RegExp(`${key}:`));
    }
    for (const key of ['bootstrap', 'send', 'upload', 'provider', 'operation']) {
      assert.match(failureLocaleCopy, new RegExp(`${key}:`));
    }
  }

  assert.match(bridgeSource, /ctaLabel: trainingCoachCtaLabel\(input\.language, "continue"\)/);
  assert.match(bridgeSource, /ctaLabel: trainingCoachCtaLabel\(input\.language, "result"\)/);
  assert.match(bridgeSource, /ctaLabel: trainingCoachCtaLabel\(input\.language, "blocker"\)/);
  assert.match(appSource, /return recoverableFailureCopy\[language\]\?\.\[kind\] \?\? recoverableFailureCopy\["en-US"\]\[kind\];/);
  assert.ok(
    appSource.slice(refinedAccessibilityStart, refinedAccessibilityEnd).includes(
      'trainingComposerModeTextCopy.genericAccessibilityLabel',
    ),
  );
  assert.ok(
    appSource.slice(submitAccessibilityStart, submitAccessibilityEnd).includes(
      'trainingComposerModeTextCopy.genericAccessibilityLabel',
    ),
  );
});
