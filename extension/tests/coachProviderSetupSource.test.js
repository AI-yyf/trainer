'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

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
  const source = fs.readFileSync(appSourcePath, 'utf8');

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
    source,
    /function providerModelRuntimeNote\([\s\S]*?providerRecoverySummary\(provider, language\)\.detail;/,
  );
  assert.match(
    source,
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
    /const shouldShowNeutralEmptyState =\s*data\.conversation\.length === 0 && \(!providerCanCoachNow \|\| displayConnectionState !== "connected"\);/,
  );
  assert.match(source, /const isFirstCoachConversation = data\.conversation\.length === 0;/);
  assert.match(source, /const providerSetupAction = \{/);
  assert.match(source, /label: providerSetupState\.actionLabel,/);
  assert.match(
    source,
    /const openProviderSetup = useCallback\(\(\) => \{\s*setActiveView\("settings"\);\s*if \(!data\.providerConfig\.apiKeyConfigured\) \{\s*setProviderApiKeyFocusRequest\(\(request\) => request \+ 1\);/,
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
  assert.match(source, /function blockedComposerPresenceMessage\(/);
  assert.match(source, /const blockedComposerPresenceCopy =/);
  assert.match(source, /const hasFullCoachRecoverySurface = activeView === "coach" && shouldShowNeutralEmptyState;/);
  assert.match(source, /const hasCoachWorkspaceAdmissionSurface = activeView === "coach" && workspaceSessionBlocked;/);
  assert.match(
    source,
    /const showComposerBlockingNotice =\s*sendBlocked &&\s*!suppressComposerRecoverySurface &&\s*!hasFullCoachRecoverySurface &&\s*!hasCoachWorkspaceAdmissionSurface;/,
  );
  assert.match(
    source,
    /const showComposerPresenceBar =\s*!suppressComposerRecoverySurface &&\s*\(\s*\(!hasCoachWorkspaceAdmissionSurface && workspaceSessionBlocked\) \|\|/,
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
  assert.match(source, /providerRecoveryLocale\(language\)\.languageIntegrityDetail/);
  assert.match(
    source,
    /providerCoachNotice && \(sendBlocked || !shouldShowNeutralEmptyState\)/,
  );
  assert.match(
    source,
    /workspaceSessionBlocked && workspaceAdmissionContent[\s\S]*?!providerCanCoachNow && providerCoachNotice[\s\S]*?coach-workspace-admission__provider-action[\s\S]*?onClick=\{openProviderSetup\}/,
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
  assert.match(source, /coach-empty-state coach-empty-state--blocked/);
  assert.match(source, /providerSetupAction\.primary\.label/);
  assert.match(source, /onClick=\{\(\) => openProviderSetup\(\)\}/);
  assert.match(
    source,
    /const sendTurn = \(\{[\s\S]*?if \(workspaceSessionBlocked\) \{\s*openWorkspaceAdmission\(\);[\s\S]*?return;\s*\}\s*if \(!providerCanCoachNow \|\| providerBlockReason \|\| capabilitySendBlocked\) \{\s*setActiveView\("settings"\);\s*setOperationMessage\(\{\s*tone: "info",\s*message: blockedComposerGuidance,/,
  );
  assert.match(
    source,
    /className="composer-presencebar__blocked"[\s\S]*?onClick=\{\(\) => \{\s*if \(workspaceSessionBlocked\) \{\s*openWorkspaceAdmission\(\);\s*return;\s*\}\s*setActiveView\("settings"\);\s*\}\}/,
  );
  assert.match(source, /summaryBar=\{coachConversationSummaryBar\}/);
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
