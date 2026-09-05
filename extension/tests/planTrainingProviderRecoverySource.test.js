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

  assert.match(source, /const providerCanCoachNow = providerTransportConnected && !providerSendState\.blocked;/);
  assert.match(source, /const providerBlockReason = useMemo\(/);
  assert.match(
    source,
    /const sendBlocked =\s*workspaceSessionBlocked \|\| !providerCanCoachNow \|\| Boolean\(providerBlockReason\);/,
  );
  assert.match(
    source,
    /const sendTurn = \(\{[\s\S]*?if \(workspaceSessionBlocked\) \{\s*openWorkspaceAdmission\(\);[\s\S]*?return;\s*\}\s*if \(!providerCanCoachNow \|\| providerBlockReason \|\| capabilitySendBlocked\) \{\s*setActiveView\("settings"\);\s*setOperationMessage\(\{\s*tone: "info",\s*message: blockedComposerGuidance,[\s\S]*?return;/,
  );
  assert.match(source, /const scenario = providerRecoveryScenario\(provider, language, connectionState\);/);
  assert.match(source, /const showComposerBlockingNotice =\s*sendBlocked &&/);
  assert.match(source, /!hasFullCoachRecoverySurface &&/);
  assert.match(source, /!hasCoachWorkspaceAdmissionSurface;/);
  assert.match(source, /const showComposerPresenceBar =\s*!suppressComposerRecoverySurface\s*&&/);
  assert.match(source, /\(\!hasCoachWorkspaceAdmissionSurface && workspaceSessionBlocked\)/);
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
  assert.match(
    planView,
    /\.\.\.\(sendBlocked\s*\?\s*\[[\s\S]*?id: "open-settings",[\s\S]*?onClick: \(\) => \{\s*if \(workspaceSessionBlocked\) \{\s*openWorkspaceAdmission\(\);\s*return;\s*\}\s*setActiveView\("settings"\);\s*\}/,
  );
  assert.match(
    planView,
    /id: "refresh-plan",[\s\S]*?tone:\s*recoveredPlanPrimary \|\| firstLookContinuePrimary[\s\S]*?\? \("ghost" as const\)[\s\S]*?: \("accent" as const\),[\s\S]*?onClick: \(\) => handlePlanOrientationAction\("generate_plan"\)/,
  );
  assert.match(planView, /payload: \{ frozen: !livePlanFrozen \}/);
  assert.doesNotMatch(source, /47\.107\.101\.18/);
  assert.doesNotMatch(source, /aikey\.redfast/);
});
