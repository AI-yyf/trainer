'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const recoveryCopySourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'providerRecoveryCopy.ts');

function providerRecoveryLocaleSection(source, language) {
  const copyStart = source.indexOf('const providerRecoveryCopy');
  const localeFn = source.indexOf('function providerRecoveryLocale', copyStart);
  const copyEnd = localeFn >= 0 ? source.lastIndexOf('};', localeFn) : -1;
  const localeStart = source.indexOf('  "' + language + '": {', copyStart);
  const nextLocale = source.indexOf('\n  "', localeStart + 1);
  const localeEnd = nextLocale > localeStart && nextLocale < localeFn ? nextLocale : copyEnd;

  assert.ok(copyStart >= 0 && copyEnd > copyStart, 'expected the provider recovery locale table');
  assert.ok(localeStart >= 0 && localeStart < copyEnd, 'expected ' + language + ' recovery copy');
  return source.slice(localeStart, localeEnd > localeStart ? localeEnd : copyEnd);
}

test('coach provider setup recovery owns complete, action-oriented copy for all supported languages', () => {
  // Batch 7 moved the recovery copy table and scenario helpers into
  // providerRecoveryCopy.ts; App keeps the wiring (providerSetupState, gates).
  const source = fs.readFileSync(recoveryCopySourcePath, 'utf8');
  const app = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /const providerRecoveryCopy: Record<ComposerLanguage, ProviderRecoveryLocale> = \{/);
  assert.match(source, /function providerRecoveryScenario\(/);
  assert.match(source, /function providerRecoverySummary\(/);
  assert.match(source, /function providerRecoveryStatusLabel\(/);
  assert.match(source, /function providerSetupSummary\(/);
  assert.match(source, /function blockedComposerSetupMessage\(/);
  assert.match(source, /connectionState\?: "starting" \| "connected" \| "offline"/);
  assert.match(
    source,
    /function providerSetupSummary\([\s\S]*?return providerRecoverySummary\(provider, language, connectionState\);/,
  );
  assert.match(
    source,
    /function blockedComposerSetupMessage\([\s\S]*?return providerRecoverySummary\(provider, language, connectionState\)\.detail;/,
  );
  assert.match(
    source,
    /function blockedComposerPresenceMessage\([\s\S]*?providerRecoveryLocale\(language\)\.languageIntegrityDetail/,
  );
  assert.match(
    app,
    /function providerModelRuntimeNote\([\s\S]*?providerRecoverySummary\(provider, language\)\.detail;/,
  );
  assert.match(
    app,
    /function providerModelMenuNote\([\s\S]*?providerRecoverySummary\(provider, language\)\.title;/,
  );

  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const locale = providerRecoveryLocaleSection(source, language);
    for (const scenario of [
      'offline',
      'starting',
      'saved_connection',
      'connection_setup',
      'missing_key',
      'checking',
      'needs_attention',
    ]) {
      assert.match(
        locale,
        new RegExp('\\b' + scenario + ':\\s*\\{[\\s\\S]*?title:[\\s\\S]*?detail:[\\s\\S]*?actionLabel:'),
      );
    }
    assert.match(locale, /status:\s*\{/);
    assert.match(locale, /stillAvailableDetail:/);
    assert.match(locale, /languageIntegrityDetail:/);
    assert.match(locale, /draftWhilePaused:/);
    assert.match(locale, /connectionStillWorks:/);
  }
  assert.doesNotMatch(source, /47\.107\.101\.18/);
  assert.doesNotMatch(source, /aikey\.redfast/);
});

test('coach recovery keeps workspace admission primary and exposes provider recovery beside it', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    source,
    /const shouldShowNeutralEmptyState =\s*data\.conversation\.length === 0 && \(!providerCanCoachNow \|\| Boolean\(providerBlockReason\)\);/,
  );
  assert.match(source, /const hasDurableCoachContext = Boolean\(/);
  assert.match(source, /data\.memory\.activeThread/);
  assert.match(source, /data\.memory\.workspaceUnderstanding/);
  // r2-g0-1: first-run starters gate on "no user turn yet" — a coach-only
  // greeting seed must not hide them; durable context still does.
  assert.match(
    source,
    /const isFirstCoachConversation =\s*!data\.conversation\.some\(\(message\) => message\.role === "user"\) &&\s*!hasDurableCoachContext;/,
  );
  assert.match(source, /const providerSetupAction = \{/);
  assert.match(source, /label: providerSetupState\.actionLabel,/);
  assert.match(
    source,
    /const openProviderSetup = useCallback\(\(\) => \{[\s\S]{0,200}?useWorkbenchState\.getState\(\)\.requestSettingsCategory\("connection"\);\s*setActiveView\("settings"\);\s*if \(!data\.providerConfig\.apiKeyConfigured\) \{\s*setProviderApiKeyFocusRequest\(\(request\) => request \+ 1\);/,
  );
  assert.doesNotMatch(source, /coach-empty-state__truth-rail/);
  assert.doesNotMatch(source, /moreContent=\{/);
  assert.match(source, /const blockedComposerGuidance = useMemo\(/);
  assert.match(source, /const blockedCoachGuidance = useMemo\(/);
  assert.match(
    source,
    /const workspaceSessionBlocked =\s*[\s\S]{0,500}?trainerWorkspaceAdmission\?\.status === "browse"/,
  );
  assert.match(source, /providerCoachBanner\([\s\S]*?blockedCoachGuidance[\s\S]*?\)/);
  assert.match(
    fs.readFileSync(recoveryCopySourcePath, 'utf8'),
    /function blockedComposerPresenceMessage\(/,
  );
  assert.match(source, /const blockedComposerPresenceCopy =/);
  // §六: one arbitration function decides the single visible blocking surface
  // (the former suppression flags were folded into resolveCoachBlockingSurface).
  assert.match(
    source,
    /function resolveCoachBlockingSurface\(input: \{\s*coachViewActive: boolean;\s*workspaceSessionBlocked: boolean;\s*neutralSetupTakeover: boolean;\s*providerSendBlocked: boolean;\s*streamRecovering: boolean;\s*\}\): CoachBlockingSurface \| null \{/,
  );
  const arbitration = source.slice(
    source.indexOf('function resolveCoachBlockingSurface'),
    source.indexOf('function planStageStatusLabel'),
  );
  assert.ok(arbitration.length > 0, 'expected resolveCoachBlockingSurface');
  const admissionAt = arbitration.indexOf('return "workspace-admission";');
  const setupAt = arbitration.indexOf('return "provider-setup";');
  const noticeAt = arbitration.indexOf('return "provider-notice";');
  const recoveringAt = arbitration.indexOf('return "recovering";');
  const nullAt = arbitration.indexOf('return null;', arbitration.indexOf('if (input.streamRecovering)'));
  assert.ok(
    admissionAt > -1 &&
      setupAt > admissionAt &&
      noticeAt > setupAt &&
      recoveringAt > noticeAt &&
      nullAt > recoveringAt,
    'expected precedence workspace-admission > provider-setup > provider-notice > recovering > null',
  );
  assert.match(
    source,
    /const coachBlockingSurface = resolveCoachBlockingSurface\(\{\s*coachViewActive: activeView === "coach",\s*workspaceSessionBlocked,\s*neutralSetupTakeover: shouldShowNeutralEmptyState,\s*providerSendBlocked: sendBlocked,/,
  );
  assert.match(source, /const showComposerBlockingNotice = coachBlockingSurface === "provider-notice";/);
  // The presence bar renders only with no blocking surface or the provider
  // notice — it stays suppressed under admission and provider setup.
  assert.match(
    source,
    /const showComposerPresenceBar =\s*\(coachBlockingSurface === null \|\| coachBlockingSurface === "provider-notice"\) &&/,
  );
  assert.match(
    source,
    /const blockedComposerPresenceCopy = workspaceSessionBlocked\s*\? workspaceSessionBlockMessage \?\? blockedComposerPresenceDetail\s*:\s*blockedComposerPresenceDetail;/,
  );
  assert.match(source, /providerRecoveryLocale\(layout\.composerLanguage\)\.draftWhilePaused/);
  assert.match(source, /\{providerSendState\.warning\}/);
  assert.doesNotMatch(
    source,
    /<span>\{providerRecoveryLocale\(layout\.composerLanguage\)\.connectionStillWorks\}<\/span>/,
  );
  assert.match(source, /<strong>\{providerSetupState\.actionLabel\}<\/strong>/);
  assert.match(
    fs.readFileSync(recoveryCopySourcePath, 'utf8'),
    /providerRecoveryLocale\(language\)\.languageIntegrityDetail/,
  );
  assert.match(
    source,
    /coachBlockingSurface === "provider-notice" && providerCoachNotice \?/,
  );
  assert.match(
    source,
    /coachBlockingSurface === "workspace-admission" && workspaceAdmissionContent[\s\S]*?!providerCanCoachNow && providerCoachNotice[\s\S]*?coach-workspace-admission__provider-action[\s\S]*?onClick=\{openProviderSetup\}/,
  );
  assert.match(
    source,
    /coach-workspace-admission__provider-action[\s\S]*?<span>\{providerSetupState\.actionLabel\}<\/span>[\s\S]*?<strong>\{providerCoachNotice\.message\}<\/strong>/,
  );
  assert.match(source, /const compactUtilityComposerPlaceholder =\s*sendBlocked\s*\?\s*blockedComposerFallback/);
  assert.match(
    source,
    /const coachSuperEntryContent = \(embedded = false\) => \{\s*if \(embedded \|\| workspaceSessionBlocked\) \{\s*return null;\s*\}\s*if \(shouldShowNeutralEmptyState\) \{/,
  );
  assert.match(
    source,
    /displayConnectionState === "starting"\s*\?\s*"coach-empty-state--welcome"\s*:\s*"coach-empty-state--blocked"/,
  );
  assert.match(source, /providerSetupState\.title/);
  assert.match(source, /providerSetupState\.detail/);
  assert.match(source, /providerSetupState\.actionLabel/);
  assert.match(source, /providerSetupAction\.primary\.label/);
  assert.match(source, /onClick=\{\(\) => openProviderSetup\(\)\}/);
  assert.match(
    source,
    /const sendTurn = \(\{[\s\S]*?if \(workspaceSessionBlocked\) \{\s*openWorkspaceAdmission\(\);[\s\S]*?return;\s*\}\s*if \(!providerCanCoachNow \|\| providerBlockReason \|\| capabilitySendBlocked\) \{\s*useWorkbenchState\.getState\(\)\.requestSettingsCategory\("connection"\);\s*setActiveView\("settings"\);\s*setOperationMessage\(\{\s*tone: "info",\s*message: blockedComposerGuidance,/,
  );
  assert.match(
    source,
    /className="composer-presencebar__blocked"[\s\S]*?onClick=\{\(\) => \{\s*if \(workspaceSessionBlocked\) \{\s*openWorkspaceAdmission\(\);\s*return;\s*\}\s*useWorkbenchState\.getState\(\)\.requestSettingsCategory\("connection"\);\s*setActiveView\("settings"\);\s*\}\}/,
  );
  assert.doesNotMatch(source, /summaryBar=\{/);
  assert.match(
    source,
    /emptyState=\{embedded \|\| workspaceSessionBlocked \? null : coachSuperEntryContent\(false\)\}/,
  );
  assert.match(source, /footer=\{embedded \? undefined : coachCheckpointRecoveryActions\}/);
  assert.match(source, /message: blockedComposerGuidance,/);
  assert.match(
    source,
    /<span>\s*\{workspaceSessionBlocked\s*\?\s*workspaceSessionBlockMessage\s*:\s*blockedComposerPresenceCopy\}\s*<\/span>/,
  );
  assert.match(
    source,
    /const refinedUtilityComposerHint =\s*activeView === "coach" && providerCanCoachNow && !providerBlockReason/,
  );
  assert.match(
    source,
    /hintText=\{activeView === "coach" && !composerUsesTrainingFlow && Boolean\(laneAwareUtilityComposerHint\) \? laneAwareUtilityComposerHint : undefined\}/,
  );
});

test('provider test action sends an unsaved draft to the isolated test path', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(source, /import \{ normalizeProviderProtocol \} from "\.\.\/\.\.\/\.\.\/\.\.\/shared\/src\/providerProtocols";/);
  assert.match(source, /const providerDraftHasUnsavedApiKey = providerDraft\.apiKey\.trim\(\)\.length > 0;/);
  assert.match(source, /const providerDraftHasChanges = useMemo\(/);
  assert.match(source, /normalizeProviderProtocol\(providerDraft\.protocol\) !==/);
  assert.match(
    source,
    /browserPreview\.testBrowserPreviewProvider\(\s*providerDraftHasChanges \? providerSavePayload : undefined,\s*previewSessionId,\s*\)/,
  );
  assert.match(
    source,
    /commandId: trainerCommands\.testProvider,\s*payload: \{\s*responseLanguage: layout\.composerLanguage,\s*\.\.\.\(providerDraftHasChanges \? \{ draft: providerSavePayload \} : \{\}\),\s*\},/,
  );
  assert.doesNotMatch(
    source.slice(source.indexOf('onTestProvider={() =>'), source.indexOf('onClearProvider={() =>')),
    /trainer\.provider\.save/,
  );
});

test('startup can scope a restored provider proof before sidecar memory finishes hydrating', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');

  assert.match(
    source,
    /const settingsWorkspaceId =\s*data\.memory\.workspace\?\.workspaceId \?\?\s*data\.workspaceTrainingState\?\.workspaceId \?\?\s*data\.providerConfig\.lastTestResult\?\.workspaceId;/,
  );
  assert.match(source, /selectScopedSettingsLastTest\(\s*data\.providerConfig\.lastTestResult,/);
});
