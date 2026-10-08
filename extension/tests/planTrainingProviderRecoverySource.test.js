'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function sourceSection(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);

  assert.ok(start >= 0, `expected ${startMarker}`);
  assert.ok(end > start, `expected ${endMarker} after ${startMarker}`);
  return source.slice(start, end);
}

test('workspace admission takes priority over provider recovery across coaching and plan actions', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const planView = sourceSection(
    source,
    '  const renderPlanView = () => (',
    '  const renderSettingsView = () => (',
  );

  // Connection state never gates sending; provider configuration does.
  assert.match(source, /const providerCanCoachNow = !providerSendState\.blocked;/);
  assert.match(source, /const providerBlockReason = useMemo\(/);
  assert.match(
    source,
    /const sendBlocked =\s*workspaceSessionBlocked \|\| !providerCanCoachNow \|\| Boolean\(providerBlockReason\);/,
  );
  assert.match(
    source,
    /const sendTurn = \(\{[\s\S]*?if \(workspaceSessionBlocked\) \{\s*openWorkspaceAdmission\(\);[\s\S]*?return;\s*\}\s*if \(!providerCanCoachNow \|\| providerBlockReason \|\| capabilitySendBlocked\) \{\s*useWorkbenchState\.getState\(\)\.requestSettingsCategory\("connection"\);\s*setActiveView\("settings"\);\s*setOperationMessage\(\{\s*tone: "info",\s*message: blockedComposerGuidance,[\s\S]*?return;/,
  );
  // providerCoachBanner (holding this line) moved into providerRecoveryCopy.ts.
const recoveryCopySource = fs.readFileSync(
  path.resolve(__dirname, '..', 'webview', 'src', 'app', 'providerRecoveryCopy.ts'),
  'utf8',
  );
  assert.match(recoveryCopySource, /const scenario = providerRecoveryScenario\(provider, language, connectionState\);/);
  // §六 arbitration: admission is decided before any provider surface, so the
  // workspace takeover always outranks provider recovery (the former
  // suppression flags were folded into resolveCoachBlockingSurface).
  const arbitration = source.slice(
    source.indexOf('function resolveCoachBlockingSurface'),
    source.indexOf('function planStageStatusLabel'),
  );
  assert.ok(arbitration.length > 0, 'expected resolveCoachBlockingSurface');
  const admissionAt = arbitration.indexOf('return "workspace-admission";');
  const setupAt = arbitration.indexOf('return "provider-setup";');
  const noticeAt = arbitration.indexOf('return "provider-notice";');
  assert.ok(
    admissionAt > -1 && setupAt > admissionAt && noticeAt > setupAt,
    'expected admission to outrank provider setup and provider notice',
  );
  assert.match(source, /const showComposerBlockingNotice = coachBlockingSurface === "provider-notice";/);
  assert.match(
    source,
    /const showComposerPresenceBar =\s*\(coachBlockingSurface === null \|\| coachBlockingSurface === "provider-notice"\) &&/,
  );
  assert.match(
    source,
    /showComposerBlockingNotice[\s\S]*?showComposerProviderPill[\s\S]*?showComposerProviderNote/,
  );
  assert.match(source, /className="composer-presencebar__blocked"/);
  const sendTurn = sourceSection(source, 'const sendTurn = (', 'const handleBrowserUploads');
  assert.doesNotMatch(
    sendTurn,
    /if \(!providerCanCoachNow \|\| providerBlockReason\) \{[\s\S]*?setActiveView\("settings"\)/,
  );
  assert.match(source, /providerRecoverySummary|providerRecoveryScenario/);
  const { learningFacts, load } = require('./templateAssertions');
  const { resolveLearningPrimaryAction, executeLearningPrimaryAction } = load('lib/learningActionResolver.ts');
  for (const state of ['absent', 'active', 'frozen']) {
    const current = learningFacts({ workspace: { ready: false, detail: 'Choose an admitted workspace' },
      provider: { ready: false, canGeneratePlan: false }, freshness: 'stale',
      plan: { state, id: 'plan', currentStep: 'Check boundaries', blocker: 'Missing test runner' },
      training: { workspaceId: 'workspace', cardId: 'current-card', title: 'Practice', status: 'return_pending' },
      evidence: { pending: [{ id: 'pending', summary: 'Result to inspect' }], blockingId: 'pending' } });
    const action = resolveLearningPrimaryAction(current);
    assert.equal(action.intent, 'choose_workspace', 'admission precedes model, recovery, and work');
    const called = [];
    assert.equal(executeLearningPrimaryAction(action, current, {
      chooseWorkspace: () => called.push('workspace'), configureProvider: () => called.push('provider'),
    }), true);
    assert.deepEqual(called, ['workspace']);
  }
  const admitted = learningFacts({ provider: { ready: false, canGeneratePlan: false } });
  assert.equal(resolveLearningPrimaryAction(admitted).intent, 'configure_provider');
  // App supplies admission truth and dispatches the controller's selected
  // target. Learning's template receives no independent button ranker.
  assert.match(source, /workspace: \{ ready: !workspaceSessionBlocked, detail: workspaceSessionBlockMessage \}/);
  assert.match(source, /chooseWorkspace: openWorkspaceAdmission/);
  assert.match(source, /configureProvider: openProviderSetup/);
  assert.match(planView, /onClick: runLearningPrimaryAction/);
  assert.match(planView, /id: "refresh-plan",[\s\S]{0,300}tone: "ghost" as const/);
  assert.match(planView, /disabled: !providerCanMutateFormalPlan \|\| workspaceSessionBlocked \|\| syncStatus !== "current"/);
  assert.match(planView, /payload: \{ frozen: !livePlanFrozen \}/);
  assert.doesNotMatch(source, /47\.107\.101\.18/);
  assert.doesNotMatch(source, /aikey\.redfast/);
});
