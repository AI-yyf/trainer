'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const settingsViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);
const workspaceAuthoritySummaryPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'parts',
  'WorkspaceAuthoritySummary.tsx',
);
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function readSettingsSource() {
  return fs.readFileSync(settingsViewPath, 'utf8');
}

function readAppSource() {
  return fs.readFileSync(appPath, 'utf8');
}

function readWorkspaceAuthoritySummarySource() {
  return fs.readFileSync(workspaceAuthoritySummaryPath, 'utf8');
}

function readStylesSource() {
  return fs.readFileSync(stylesPath, 'utf8');
}

function availabilityFactsSource(source) {
  const start = source.indexOf('const availabilityFacts = [');
  const end = source.indexOf('const showAvailabilityChecklist =', start);

  assert.ok(start >= 0, 'expected the availability facts declaration');
  assert.ok(end > start, 'expected the availability facts declaration to be bounded');
  return source.slice(start, end);
}

function availabilityStripSource(source) {
  const start = source.indexOf('className={`settings-availability-strip');
  // The strip stays a self-contained read-only region; the provider
  // configuration section (required trio + key + test) is anchored right
  // after it, so bound the extraction there to keep the secret-scan exact.
  const end = source.indexOf('data-settings-section="connection"', start);

  assert.ok(start >= 0, 'expected the availability strip render');
  assert.ok(end > start, 'expected provider configuration after the availability strip');
  return source.slice(start, end);
}

test('settings receives and renders the final capability verdict without replacing probe facts', () => {
  const settings = readSettingsSource();
  const app = readAppSource();

  assert.match(app, /const capabilityVerdict = useMemo\(/);
  assert.match(app, /<CoachSettingsView[\s\S]*capabilityVerdict=\{capabilityVerdict\}/);
  assert.match(settings, /capabilityVerdict: TrainerCapabilityVerdict;/);
  assert.match(settings, /settingsPhrase\(language, "finalCapabilities"\)/);
  assert.match(settings, /finalCapabilities: "Final capabilities"/);
  assert.match(settings, /data-capability-verdict=\{name\}/);
  assert.match(settings, /data-capability-verdict-status=/);
  assert.match(settings, /capabilityChipsAllowed \? \(/);
  assert.doesNotMatch(settings, /label=\{language === "zh-CN" \? "最终能力" : "Final capabilities"\}/);
  for (const capability of ['chat', 'streaming', 'tools', 'image-input', 'formal-plan', 'resource-write']) {
    assert.match(settings, new RegExp(`\\["${capability}", ${capability === 'image-input' ? 'capabilityVerdict.imageInput' : 'capabilityVerdict\\.'}`));
  }
  assert.doesNotMatch(settings, /modelCapability: provider\.modelCapabilities/);
  assert.doesNotMatch(settings, /profileCapability: provider\.capabilities\?\.thinking/);
  assert.match(settings, /toolsVerificationFact/);
  assert.match(settings, /streamingVerificationFact/);
  assert.match(settings, /selectScopedSettingsLastTest/);
  assert.match(settings, /data-settings-capability-chip="tools"/);
  assert.match(settings, /data-settings-capability-chip="streaming"/);
  assert.match(settings, /data-settings-capability-chip="thinking"/);
  assert.match(settings, /data-settings-capability-chip="vision"/);
  assert.match(app, /scopedSettingsCapabilityTruth/);
  assert.match(app, /workspaceId=\{settingsWorkspaceId\}/);
  assert.match(app, /authority: workspaceAuthority/);
  assert.match(app, /const resourceWriteAccess = trainerWorkspaceAdmission/);
  assert.match(
    app,
    /workspaceAuthority\?\.resourceWriteAllowed === true[\s\S]*?workspaceAuthority\.authorityScope === "trainer_sandbox"[\s\S]*?workspaceAuthority\.resourceWriteEvidence\?\.operation === "write"[\s\S]*?workspaceAuthority\.resourceWriteEvidence\.scope === "trainer_sandbox"[\s\S]*?workspaceAuthority\.resourceWriteEvidence\.allowed === true/,
  );
  assert.match(settings, /resourceWriteEvidence/);
  assert.match(settings, /Trainer sandbox artifact writes/);
});

test('settings language selector routes shared labels through every supported locale', () => {
  const source = readSettingsSource();

  assert.match(source, /const defaultLabels: Partial<CoachSettingsLabels> =/);
  assert.match(source, /const englishLabels: Partial<CoachSettingsLabels> =/);
  assert.match(source, /import \{ resolveCopy as resolveWorkbenchCopy \} from "\.\.\/\.\.\/lib\/i18n\/copy";/);
  assert.match(source, /function localizedSettingsLabels\(language: ComposerLanguage\)/);
  assert.match(source, /\.\.\.localizedSettingsLabels\(language\)/);
  assert.match(source, /auto: adaptiveBehaviorLabel\(language, "both"\)/);
  assert.match(source, /SUPPORTED_LANGUAGES\.map\(\(value\) => \(\{\s*label: LANGUAGE_LABELS\[value\],\s*value,\s*\}\)\)/);
  assert.match(source, /onChange=\{onLanguageChange\}/);
});

test('settings workspace authority keeps a separately reported remote identity visible', () => {
  const source = readWorkspaceAuthoritySummarySource();

  assert.match(source, /const rootDetail = summary\.rootDetail\.trim\(\);/);
  assert.match(source, /const sourceDetail = summary\.sourceDetail\.trim\(\);/);
  assert.match(
    source,
    /const hasSeparateRemoteIdentity = Boolean\(\s*authority\.remoteName\?\.trim\(\) && authority\.authoritySource\?\.trim\(\) && sourceDetail,\s*\);/,
  );
  assert.match(source, /<strong title=\{rootDetail \|\| summary\.root\}>\{summary\.root\}<\/strong>/);
  assert.match(source, /<strong title=\{sourceDetail \|\| source\}>\{source\}<\/strong>/);
  assert.match(source, /\{hasSeparateRemoteIdentity \? \(/);
  assert.match(source, /data-workspace-authority-remote title=\{sourceDetail\}/);
  assert.match(source, /\{sourceDetail\}/);
});

test('settings keeps availability as the compact source of provider truth', () => {
  const source = readSettingsSource();
  const facts = availabilityFactsSource(source);
  const strip = availabilityStripSource(source);

  assert.match(
    source,
    /const availabilityMode: ProviderSendStateStatus \| "draft" \| "recent_failure" \| "needs_test" =/,
  );
  assert.match(source, /const localizedResolvedAvailabilityStatusLabel =/);
  assert.match(source, /const localizedResolvedAvailabilityHeadline =/);
  assert.match(source, /const localizedResolvedAvailabilityDetail =/);
  assert.match(source, /const effectiveAvailabilityPrimaryCta:/);
  assert.match(facts, /id: "provider"/);
  assert.match(facts, /id: "model"/);
  assert.match(facts, /id: "test"/);
  assert.match(facts, /value: appliedProviderFactValue,/);
  assert.match(facts, /value: appliedModelFactValue,/);
  assert.match(strip, /<StatusPill tone=\{resolvedAvailabilityTone\}>\{localizedResolvedAvailabilityStatusLabel\}<\/StatusPill>/);
  assert.match(strip, /effectiveAvailabilityPrimaryCta\.label/);
  assert.match(strip, /availabilityFacts\.map\(\(fact\) =>/);
  assert.match(source, /open=\{providerDetailRequested\}/);
  assert.match(source, /onToggle=\{setProviderDetailRequested\}/);
  assert.doesNotMatch(source, /const providerDetailOpen =/);
  assert.doesNotMatch(source, /settings-sheet__setup-card/);
});

test('settings maps provider failures to retestable recovery states', () => {
  const source = readSettingsSource();

  assert.match(source, /function providerFailureCopy\(/);
  assert.match(source, /case "test_failed":/);
  assert.match(source, /Connection test failed/);
  assert.match(source, /API key rejected/);
  assert.match(source, /Model name rejected/);
  assert.match(source, /Model is unavailable right now/);
  assert.match(source, /Try again, or choose another model/);
  assert.match(source, /const shouldSurfaceRecentTestFailure =/);
  assert.match(source, /!shouldSurfaceRecentTestFailure/);
  assert.match(source, /shouldSurfaceRecentTestFailure\s*\? "recent_failure"\s*:\s*providerNeedsRetest/);
  assert.match(source, /coachSendState\.status === "blocked_error"/);
  assert.match(source, /coachSendState\.status === "degraded_error"/);
  assert.match(source, /coachSendState\.status === "warming"/);
  assert.match(source, /const providerTestRecoveryDetail =/);
  assert.match(source, /providerTestFeedback\?\.actionKind === "test-provider"/);
  assert.match(source, /lastTestFailure\?\.status === "failed" \? "test_failed"/);
  assert.match(source, /providerSaved\s*\? safeProviderFailureHint/);
  assert.match(source, /settingsStatusPhrase\(language, "connectionSavedApiKeyMissing"\)/);
  assert.match(
    source,
    /const providerNeedsFirstTest =\s*providerSaved && provider\.apiKeyConfigured && !providerHasDraftChanges && !lastTest\?\.checkedAt;/,
  );
  assert.match(source, /const canRetestProvider = providerDraftReadyForTest && !providerTestPending;/);
  assert.match(source, /const canApplyMiniMaxRecovery =/);
  assert.match(source, /const shouldOfferMiniMaxDefaults =/);
  assert.match(source, /const shouldOfferMiniMaxKeyReset =/);
  assert.match(source, /action: onUseProviderTemplate,/);
  assert.match(
    source,
    /const canFindDraftModels = draftNeedsModelChoice && !hasDiscoveredDraftModels && canRefreshModels;/,
  );
  assert.match(source, /canFindDraftModels\s*\? onRefreshProviderModels/);
  assert.match(
    source,
    /const shouldCompleteDraftSetup =\s*providerHasDraftChanges &&\s*!providerDraftReadyForTest &&\s*!canFindDraftModels &&\s*!hasDiscoveredDraftModels;/,
  );
  assert.match(source, /shouldCompleteDraftSetup\s*\? openProviderDetails/);
});

test('settings offers the recommended template before manual setup for a blank provider', () => {
  const source = readSettingsSource();
  const ctaStart = source.indexOf('const effectiveAvailabilityPrimaryCta:');
  const ctaEnd = source.indexOf('const showProviderDetailTestAction =', ctaStart);

  assert.ok(ctaStart >= 0 && ctaEnd > ctaStart, 'expected the primary availability CTA');
  const cta = source.slice(ctaStart, ctaEnd);

  assert.match(
    source,
    /const shouldOfferRecommendedProviderTemplate =\s*Boolean\(onUseProviderTemplate\) &&\s*!providerSaved &&\s*!providerHasDraftChanges &&\s*!savedProviderProfilesAvailable;/,
  );
  assert.match(
    source,
    /const shouldOpenProviderDetails =\s*!providerHasDraftChanges &&\s*!providerSaved &&\s*!shouldRoutePrimaryToSavedProfiles &&\s*!shouldOfferRecommendedProviderTemplate;/,
  );
  assert.match(
    source,
    /const workspaceRootMissing =\s*!trainerWorkspace\?\.rootPath\?\.trim\(\) \|\| trainerWorkspace\?\.status === "root-missing";/,
  );
  assert.match(
    source,
    /const displayAvailabilityHeadline = workspaceRootMissing[\s\S]*shouldOfferRecommendedProviderTemplate/,
  );
  assert.match(
    source,
    /const displayAvailabilityDetail = workspaceRootMissing[\s\S]*shouldOfferRecommendedProviderTemplate\s*\? settingsPhrase\(language, "useMiniMaxProfileDetail"\)/,
  );
  assert.match(
    cta,
    /workspaceRootMissing && onChooseTrainerWorkspaceRoot[\s\S]*shouldOfferRecommendedProviderTemplate/,
  );
  assert.match(source, /shouldOfferRecommendedProviderTemplate/);
  assert.match(source, /shouldRoutePrimaryToSavedProfiles/);
});

test('settings details give draft requirements precedence over saved-connection requirements', () => {
  const source = readSettingsSource();
  const draftNoteStart = source.indexOf('const providerDetailRequirementNote =');
  const draftNoteEnd = source.indexOf('return (', draftNoteStart);

  assert.ok(draftNoteStart >= 0 && draftNoteEnd > draftNoteStart, 'expected draft requirement guidance');
  const draftNote = source.slice(draftNoteStart, draftNoteEnd);

  assert.match(draftNote, /currentDraftModelPolicyMessage \?\?/);
  assert.match(draftNote, /!providerDraft\.baseUrl\.trim\(\)\s*\? settingsStatusPhrase\(language, "fillProviderFields"\)/);
  assert.match(draftNote, /!providerDraft\.model\.trim\(\)\s*\? settingsPhrase\(language, "chooseModelDetail"\)/);
  assert.match(
    draftNote,
    /!providerDraftHasApiKey && !providerDraftCanReuseSavedApiKey\s*\? settingsStatusPhrase\(language, "connectionSavedApiKeyMissing"\)/,
  );
  assert.match(draftNote, /: localizedResolvedAvailabilityDetail\)/);
  assert.match(source, /const providerRequirementNote = providerNeedsApiKey/);
  assert.match(source, /\{providerDetailRequirementNote\}/);
  assert.match(source, /const providerApiKeyDraftStatus =/);
});

test('settings routes incomplete drafts back to the form and only tests ready drafts', () => {
  const source = readSettingsSource();
  const ctaStart = source.indexOf('const resolvedAvailabilityPrimaryLabel =');
  const ctaEnd = source.indexOf('const canOfferMiniMaxRecoveryAction =', ctaStart);

  assert.ok(ctaStart >= 0 && ctaEnd > ctaStart, 'expected availability CTA resolution');
  const cta = source.slice(ctaStart, ctaEnd);
  assert.match(
    cta,
    /shouldCompleteDraftSetup\s*\? settingsPhrase\(language, "connectionFieldsAndKey"\)/,
  );
  assert.match(cta, /shouldCompleteDraftSetup\s*\? modelDiscoveryBlockedReason/);
  assert.match(cta, /shouldCompleteDraftSetup\s*\? openProviderDetails/);
  assert.match(source, /const shouldWaitForDraftTest = providerHasDraftChanges && providerTestPending;/);
  assert.match(cta, /shouldWaitForDraftTest\s*\? settingsStatusPhrase\(language, "checking"\)/);
  assert.match(cta, /shouldWaitForDraftTest\s*\? undefined/);
  assert.match(
    cta,
    /providerHasDraftChanges\s*\? settingsPhrase\(language, "testDraftConnection"\)/,
  );
  assert.match(
    cta,
    /providerHasDraftChanges\s*\? settingsPhrase\(language, "testDraftConnectionDetail"\)/,
  );
  assert.match(cta, /canRetestProvider\s*\? onTestProvider/);
  assert.match(
    source,
    /const showProviderDetailTestAction =\s*!canRetestProvider \|\| effectiveAvailabilityPrimaryCta\.action !== onTestProvider;/,
  );
});

test('settings takes a complete draft that only lacks its API key straight to that field', () => {
  const source = readSettingsSource();
  const ctaStart = source.indexOf('const resolvedAvailabilityPrimaryLabel =');
  const ctaEnd = source.indexOf('const canOfferMiniMaxRecoveryAction =', ctaStart);

  assert.ok(ctaStart >= 0 && ctaEnd > ctaStart, 'expected availability CTA resolution');
  const cta = source.slice(ctaStart, ctaEnd);

  assert.match(
    source,
    /const shouldFocusDraftApiKey =\s*providerHasDraftChanges &&\s*providerDraftFieldsReady &&\s*!providerDraftHasApiKey &&\s*!providerDraftCanReuseSavedApiKey;/,
  );
  assert.match(cta, /shouldFocusDraftApiKey\s*\? settingsPhrase\(language, "addApiKey"\)/);
  assert.match(cta, /shouldFocusDraftApiKey\s*\? settingsPhrase\(language, "addApiKeyDetail"\)/);
  assert.match(cta, /shouldFocusDraftApiKey\s*\? openProviderApiKey/);
});

test('settings blocks a draft model that conflicts with its connection policy before save or test', () => {
  const source = readSettingsSource();
  const ctaStart = source.indexOf('const resolvedAvailabilityPrimaryLabel =');
  const ctaEnd = source.indexOf('const canOfferMiniMaxRecoveryAction =', ctaStart);

  assert.ok(ctaStart >= 0 && ctaEnd > ctaStart, 'expected availability CTA resolution');
  const cta = source.slice(ctaStart, ctaEnd);
  assert.match(source, /const currentDraftModelPolicyMessage =\s*currentDraftModel && !currentDraftModelPolicy\.allowed/);
  assert.match(source, /const currentDraftModelBlockedByPolicy = Boolean\(currentDraftModelPolicyMessage\);/);
  assert.match(
    source,
    /const providerDraftReadyForTest =\s*providerDraftReadyForTestBase &&\s*!currentDraftModelBlockedByPolicy &&\s*!providerDraftEditorBlocked;/,
  );
  assert.match(
    source,
    /const canSaveProviderConnection = Boolean\(\s*onSaveProvider &&\s*providerDraftFieldsReady &&\s*!currentDraftModelBlockedByPolicy &&/,
  );
  assert.match(source, /const modelDiscoveryBlockedReason =\s*currentDraftModelPolicyMessage \?\?/);
  assert.match(
    source,
    /const shouldRepairDraftModelPolicy =\s*providerHasDraftChanges && currentDraftModelBlockedByPolicy;/,
  );
  assert.match(cta, /shouldRepairDraftModelPolicy\s*\? settingsPhrase\(language, "chooseModel"\)/);
  assert.match(cta, /shouldRepairDraftModelPolicy\s*\? currentDraftModelPolicyMessage \?\? modelDiscoveryBlockedReason/);
  assert.match(cta, /shouldRepairDraftModelPolicy\s*\? focusDraftModelPicker/);
  assert.match(source, /currentDraftModelPolicyMessage \?\?\s*settingsPhrase\(language, "saveConnectionDetail"\)/);
  assert.match(source, /currentDraftModelPolicyMessage \?\?\s*settingsPhrase\(language, "verifyConnectionDetail"\)/);
});

test('settings takes rejected credentials directly to the API key field', () => {
  const source = readSettingsSource();

  assert.match(source, /const apiKeyInputRef = useRef<HTMLInputElement \| null>\(null\);/);
  assert.match(
    source,
    /const \[providerApiKeyFocusRequested, setProviderApiKeyFocusRequested\] = useState\(false\);/,
  );
  assert.match(source, /const providerCredentialsRejected =/);
  assert.match(source, /const shouldRepairProviderCredentials =/);
  assert.match(source, /const openProviderApiKey = \(\) => openProviderDetails\(true\);/);
  assert.match(
    source,
    /apiKeyInput\?\.closest<HTMLDetailsElement>\(\s*"\.coach-settings-view__provider-detail",/,
  );
  assert.match(source, /providerDetails\.open = true;/);
  assert.match(source, /apiKeyInput\?\.scrollIntoView\(\{ block: "center" \}\);/);
  assert.match(source, /apiKeyInput\?\.focus\(\{ preventScroll: true \}\);/);
  assert.match(source, /setProviderApiKeyFocusRequested\(false\);/);
  assert.match(
    source,
    /const openProviderDetails = \(focusApiKey = false\) => \{\s*setProviderDetailRequested\(true\);\s*if \(focusApiKey\) \{\s*setProviderApiKeyFocusRequested\(true\);/,
  );
  assert.match(source, /shouldRepairProviderCredentials\s*\? openProviderApiKey/);
});

test('settings opens and focuses saved profiles from the offline recovery action', () => {
  const source = readSettingsSource();

  assert.match(
    source,
    /const \[providerProfilesFocusRequested, setProviderProfilesFocusRequested\] = useState\(false\);/,
  );
  assert.match(
    source,
    /if \(!providerProfilesFocusRequested\) \{\s*return;\s*\}[\s\S]*?panel\.closest<HTMLDetailsElement>\([\s\S]*?"\.coach-settings-view__provider-detail"/,
  );
  assert.match(source, /providerDetails\.open = true;/);
  assert.match(source, /panel\.open = true;/);
  assert.match(source, /panel\.scrollIntoView\(\{ block: "nearest" \}\);/);
  assert.match(source, /\.settings-provider-profile:not\(:disabled\)/);
  assert.match(source, /nextButton\?\.focus\(\);/);
  assert.match(source, /\}, \[providerProfiles\.length, providerProfilesFocusRequested\]\);/);
  assert.match(
    source,
    /const openSavedProviderProfiles = \(\) => \{\s*setProviderDetailRequested\(true\);\s*setProviderProfilesFocusRequested\(true\);\s*\};/,
  );
  assert.match(source, /shouldRoutePrimaryToSavedProfiles\s*\? openSavedProviderProfiles/);
});

test('settings localizes the visible model-card actions in all supported languages', () => {
  const source = readSettingsSource();
  const start = source.indexOf('function providerModelCardCopy(');
  const end = source.indexOf('\nfunction normalizeComparablePath', start);

  assert.ok(start >= 0 && end > start, 'expected model-card locale copy');
  const modelCardCopy = source.slice(start, end);
  for (const language of ["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"]) {
    assert.match(modelCardCopy, new RegExp(`"${language}": \\{`));
  }
  assert.match(source, /modelCardCopy\.remove/);
  assert.match(source, /modelCardCopy\.liveFetch/);
  assert.match(source, /modelCardCopy\.cached/);
  assert.match(source, /modelCardCopy\.manual/);
});

test('settings keeps draft model discovery scoped to its current connection', () => {
  const source = readSettingsSource();

  assert.match(source, /const draftModelListingMatches =/);
  assert.match(source, /asString\(modelListing\?\.source\) === "draft"/);
  assert.match(source, /normalizeProviderBaseUrlDraft\(draftListingBaseUrl \?\? "", draftProtocol\) === normalizedDraftBaseUrl/);
  assert.match(
    source,
    /const availableModels = providerHasDraftChanges\s*\?\s*draftModelListingMatches\s*\?\s*asStringArray\(modelListing\?\.availableModels\)\s*:\s*sameDraftTransportAsSaved\s*\?\s*provider\.availableModels \?\? \[\]\s*:\s*\[\]\s*:\s*provider\.availableModels \?\? \[\];/,
  );
  assert.doesNotMatch(source, /!providerSaved\s*\|\|\s*sameDraftTransportAsSaved/);
  assert.match(
    source,
    /const draftModelPolicy = \{\s*allowedModels: providerDraft\.allowedModels \?\? provider\.allowedModels \?\? \[\],\s*deniedModels: providerDraft\.deniedModels \?\? provider\.deniedModels \?\? \[\],\s*\};/,
  );
  assert.match(
    source,
    /const selectableModelOptions = filterProviderModelOptions\(\s*mergeDraftStringList\(\s*currentDraftModel,\s*draftCatalogModels,\s*liveCatalogModels,\s*availableModels,\s*\),\s*draftModelPolicy,\s*\{ retainModels: currentDraftModel \? \[currentDraftModel\] : \[\] \},\s*\);/,
  );
  assert.match(source, /availableModels\.length > 0/);
});

test('settings makes the connection name explicitly optional in every supported locale', () => {
  const source = readSettingsSource();

  assert.match(source, /function providerConnectionNameLabel\(language: ComposerLanguage\)/);
  for (const language of ["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"]) {
    assert.match(source, new RegExp(`case "${language}"|${language === "en-US" ? "default:" : ""}`));
  }
  assert.match(source, /<span>\{providerConnectionNameLabel\(language\)\}<\/span>/);
});

test('availability exposes only non-secret provider facts', () => {
  const source = readSettingsSource();
  const facts = availabilityFactsSource(source);
  const strip = availabilityStripSource(source);

  assert.match(strip, /data-availability-fact=\{fact\.id\}/);
  assert.match(strip, /data-availability-value=\{fact\.value\}/);
  assert.match(strip, /data-secret="false"/);
  assert.match(strip, /data-availability-fact-value=\{fact\.value\}/);
  assert.doesNotMatch(facts, /apiKey|baseUrl|providerDraft/);
  assert.doesNotMatch(strip, /providerDraft\.apiKey/);
  assert.match(
    source,
    /<input\s+ref=\{apiKeyInputRef\}\s+type="password"\s+value=\{providerDraft\.apiKey\}/,
  );
});

test('availability fact values stay readable in a narrow sidebar', () => {
  const styles = readStylesSource();
  const narrowMediaStart = styles.lastIndexOf('@media (max-width: 420px)');
  const narrowFactRule = styles.slice(narrowMediaStart).match(
    /\.settings-availability-fact__text \{([\s\S]*?)\n  \}/,
  );

  assert.ok(narrowMediaStart >= 0, 'expected narrow sidebar media query');
  assert.ok(narrowFactRule, 'expected narrow availability fact styling');
  assert.match(narrowFactRule[1], /display: block;/);
  assert.match(narrowFactRule[1], /overflow: visible;/);
  assert.match(narrowFactRule[1], /white-space: normal;/);
  assert.match(narrowFactRule[1], /overflow-wrap: anywhere;/);
  assert.doesNotMatch(narrowFactRule[1], /-webkit-line-clamp/);
});

test('settings keeps Chinese default summaries from splitting a short phrase across lines', () => {
  const styles = readStylesSource();

  assert.match(
    styles,
    /\.trainer-shell:lang\(zh-CN\) \.settings-sheet__defaults-preview\s*\{[\s\S]*?word-break: keep-all;/,
  );
});

test('settings keeps connection fields in a semantic form with a guarded Enter action', () => {
  const source = readSettingsSource();

  assert.match(
    source,
    /<form\s+className="settings-sheet__minor-body"\s+onSubmit=\{\(event\) => \{\s*event\.preventDefault\(\);\s*if \(canSaveProviderConnection\) \{\s*onSaveProvider\?\.\(\);\s*\}\s*\}\}/,
  );
  assert.match(
    source,
    /<input\s+ref=\{apiKeyInputRef\}\s+type="password"\s+value=\{providerDraft\.apiKey\}/,
  );
});

test('settings does not hardcode provider credentials or endpoints', () => {
  const source = readSettingsSource();

  assert.match(source, /value=\{providerDraft\.baseUrl\}/);
  assert.match(source, /DEFAULT_PROVIDER_CONNECTION_NAME/);
  assert.match(source, /baseUrl: event\.target\.value,/);
  assert.match(source, /name: DEFAULT_PROVIDER_CONNECTION_NAME/);
  assert.doesNotMatch(source, /https?:\/\/[^\s"'`]+/);
  assert.doesNotMatch(source, /\b(?:\d{1,3}\.){3}\d{1,3}\b/);
  assert.doesNotMatch(source, /\b(?:sk|rk|AIza)[-_][A-Za-z0-9_-]{12,}\b/);
  assert.doesNotMatch(source, /aikey\.redfast|47\.107\.101\.18/);
});

test('settings derives readiness from the shared provider test truth source', () => {
  const source = readSettingsSource();

  assert.match(source, /describeProviderTestReadiness,/);
  assert.match(source, /PROVIDER_TEST_FRESHNESS_WINDOW_MS,/);
  assert.match(
    source,
    /const providerTestReadiness = describeProviderTestReadiness\(scopedProvider, language, providerTestClock\);/,
  );
  assert.match(
    source,
    /const coachSendState = describeProviderSendState\(scopedProvider, language, providerTestClock\);/,
  );
  assert.match(source, /const providerTestPassed =\s*providerTestReadiness\.ready/);
});

test('settings uses plain-language localized recovery copy for unavailable connections', () => {
  const source = readSettingsSource();
  const strip = availabilityStripSource(source);

  assert.match(strip, /<span className="eyebrow">\{copy\.setupSection\}<\/span>/);
  assert.match(source, /setupModelAccess: "设置模型连接"/);
  assert.match(source, /fillProviderFields: "填写连接信息和 API key 后即可测试。"/);
  assert.match(source, /\{providerDetailRequirementNote\}/);
  assert.doesNotMatch(source, /setupModelAccess: "先连上模型"/);
});

test('settings capability chips appear only from a verified live last-test', () => {
  const source = readSettingsSource();
  const app = readAppSource();

  assert.match(source, /settingsCapabilityChipsVisible/);
  assert.match(source, /settingsCapabilitySurfaceStatus/);
  assert.match(source, /const capabilityChipsAllowed =/);
  assert.match(source, /!providerHasDraftChanges &&/);
  assert.match(source, /data-settings-capability-status=/);
  assert.match(source, /capabilityNeverTested/);
  assert.match(source, /capabilityTestFailed/);
  assert.match(source, /capabilityUnknownProtocol/);
  assert.match(source, /capabilitiesFromLiveTest/);
  assert.match(source, /finalCapabilities/);
  assert.match(source, /data-capability-verdict-status=/);
  assert.doesNotMatch(source, /defaultCapabilities/);
  assert.doesNotMatch(source, /CapabilitySummary/);
  assert.doesNotMatch(source, /defaultCapabilitiesForProtocol/);
  assert.doesNotMatch(source, /this shows the protocol defaults/);
  assert.doesNotMatch(source, /Until the model list and test are complete, this shows the protocol defaults/);
  assert.match(app, /lastTestOk: scopedProviderLastTest\?\.ok === true/);
});

test('settings final-capability Ready/Unavailable use 8-lang status phrases when chips allowed', () => {
  const source = readSettingsSource();

  assert.match(source, /capabilityChipsAllowed \? \(/);
  assert.match(
    source,
    /enabled\s*\?\s*settingsStatusPhrase\(language, "ready"\)\s*:\s*settingsStatusPhrase\(language, "unavailable"\)/,
  );
  assert.match(source, /unavailable: "不可用"/);
  assert.match(source, /unavailable: "Unavailable"/);
  assert.match(source, /unavailable: "No disponible"/);
  assert.match(source, /unavailable: "Indisponible"/);
  assert.match(source, /unavailable: "Nicht verfügbar"/);
  assert.match(source, /unavailable: "利用不可"/);
  assert.match(source, /unavailable: "사용 불가"/);
  assert.match(source, /unavailable: "Indisponível"/);
  assert.doesNotMatch(
    source,
    /enabled \? \(language === "zh-CN" \? "可用" : "Ready"\) : language === "zh-CN" \? "不可用" : "Unavailable"/,
  );
});
