'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const script = fs.readFileSync(path.join(__dirname, '../scripts/verify-vsix-e2e.mjs'), 'utf8');
const consumer = fs.readFileSync(path.join(__dirname, '../scripts/verify-vsix-e2e-resource-training-stability.mjs'), 'utf8');
const start = script.indexOf('function classifyNativeEvidenceStep(name)');
const end = script.indexOf('function captureVsCodeWindowArtifacts(', start);
assert.ok(start >= 0 && end > start);
const functions = script.slice(start, end);
const { classifyNativeEvidenceStep, scopeNativeEvidenceReceipt, summarizeNativeEvidence } = Function(
  `${functions}; return { classifyNativeEvidenceStep, scopeNativeEvidenceReceipt, summarizeNativeEvidence };`,
)();

const capture = { exists: true, windowScreenshotPath: '/opaque/window.png', sidebarScreenshotPath: '/opaque/sidebar.png' };
const skip = { skipped: true, captureRequired: false, capturePlatform: 'linux', reason: 'Unavailable window capture.', exists: false };

test('host, debug and capture stages never become a visual-target assertion', () => {
  const cases = [
    ['assert-training-review-queue-host-state', 'host-state'],
    ['assert-training-theory-drill-host-state', 'host-state'],
    ['assert-training-scenario-lab-webview-debug-state', 'webview-debug-state'],
    ['assert-resources-sandbox-restore-webview-debug-state', 'webview-debug-state'],
    ['capture-owned-workbench-after-review-queue-command', 'native-capture-artifact'],
    ['assert-title-configuration-and-theme-state', 'title-configuration-and-theme-state'],
    ['send-coach-message', 'host-command-state'],
    ['unknown-future-step', 'host-command-state'],
  ];
  for (const [name, expected] of cases) {
    assert.equal(classifyNativeEvidenceStep(name), expected);
    const original = { workspaceId: 'workspace-A', targetId: 'card-A', visualTargetAsserted: true, targetSurfaceConfirmed: true };
    const receipt = scopeNativeEvidenceReceipt(name, original);
    assert.equal(receipt.evidenceScope, expected);
    assert.equal(receipt.visualTargetAsserted, false);
    assert.equal(receipt.targetSurfaceConfirmed, null);
    assert.equal(receipt.workspaceId, original.workspaceId);
    assert.equal(receipt.targetId, original.targetId);
    assert.equal(original.visualTargetAsserted, true, 'classification must not mutate returned command data');
  }
});

test('native capture and theme artifacts are counted separately from visual checks', () => {
  const summary = summarizeNativeEvidence([
    { name: 'assert-training-review-queue-host-state', ok: true, data: { reviewArtifactId: 'review-A' } },
    { name: 'assert-training-scenario-lab-webview-debug-state', ok: true, data: { scenarioLabVisible: true } },
    { name: 'capture-owned-workbench-after-scenario-restore', ok: true, data: capture },
    { name: 'assert-title-configuration-and-theme-state', ok: true, data: { themeRuns: [
      { screenshot: capture }, { screenshot: capture }, { screenshot: capture },
    ] } },
  ]);
  assert.equal(summary.captureStepPassCount, 1);
  assert.equal(summary.themeCapturePairPassCount, 3);
  assert.equal(summary.visualChecksPerformed, 0);
  assert.equal(summary.visualTargetAsserted, false);
  assert.equal(summary.stepCountsByEvidenceScope['host-state'], 1);
  assert.equal(summary.stepCountsByEvidenceScope['webview-debug-state'], 1);
});

test('explicit platform skips and malformed capture failures remain distinct', () => {
  const summary = summarizeNativeEvidence([
    { name: 'capture-owned-workbench-after-review-queue-command', ok: true, data: skip },
    { name: 'capture-owned-workbench-after-theory-drill-command', ok: false, data: { ...skip, capturePlatform: 'win32' } },
    { name: 'capture-owned-workbench-after-scenario-restore', ok: false, data: { exists: false } },
    { name: 'assert-title-configuration-and-theme-state', ok: false, data: { themeRuns: [
      { screenshot: skip }, { screenshot: { exists: false } },
    ] } },
  ]);
  assert.equal(summary.captureStepPassCount, 0);
  assert.equal(summary.captureStepSkipCount, 1);
  assert.equal(summary.captureStepFailCount, 2);
  assert.equal(summary.themeCapturePairSkipCount, 1);
  assert.equal(summary.themeCapturePairFailCount, 1);
  assert.equal(summary.visualChecksPerformed, 0);
});

test('actual driver record keeps predicate failure, returned identity and data scope', async () => {
  const recordStart = script.indexOf('  const record = async (name, fn, options = {}) => {');
  const recordEnd = script.indexOf('  const readVisibleFacts', recordStart);
  assert.ok(recordStart >= 0 && recordEnd > recordStart);
  const steps = [];
  const record = Function('steps', 'writeProgress', 'sanitize',
    `${functions}; ${script.slice(recordStart, recordEnd)}; return record;`,
  )(steps, () => undefined, value => value);
  const original = { targetId: 'expected-card', actualTargetId: 'old-card' };
  const returned = await record('assert-training-scenario-lab-webview-debug-state', () => original, {
    ok: data => data.targetId === data.actualTargetId,
    errorMessage: () => 'Actual identity did not match.',
  });
  assert.equal(returned, original);
  assert.equal(steps[0].ok, false);
  assert.equal(steps[0].error, 'Actual identity did not match.');
  assert.equal(steps[0].data.targetId, 'expected-card');
  assert.equal(steps[0].data.actualTargetId, 'old-card');
  assert.equal(steps[0].data.visualTargetAsserted, false);
  assert.equal(steps[0].evidenceScope, 'webview-debug-state');
});

function loadConsumerFunctions() {
  const first = consumer.indexOf('function hasSandboxPreviewEvidence(');
  const last = consumer.indexOf('function summarizeCrossWorkspaceRound(', first);
  assert.ok(first >= 0 && last > first);
  const summariesStart = consumer.indexOf('function summarizeResourceDetailRound(');
  const summariesEnd = consumer.indexOf('function hasSidecarFaultRecoveryEvidence(', summariesStart);
  return Function(`${consumer.slice(first, last)}; ${consumer.slice(summariesStart, summariesEnd)};
    return { hasSandboxPreviewEvidence, hasSandboxCapabilityEvidence, summarizeSandboxCapabilityRound };`)();
}

test('stability preview gate rejects restore intent when the matched renderer preview is missing', () => {
  const { hasSandboxPreviewEvidence } = loadConsumerFunctions();
  const facts = { previewSucceeded: true, sandboxPath: '/owned/preview.md', selectedSandboxPath: '/owned/preview.md',
    sandboxPreviewVisible: true, sandboxPreviewEmbedded: true, sandboxPreviewPath: '/owned/preview.md',
    detailPaneVisible: true, sandboxPaneVisible: false, previewPaneVisible: false };
  assert.equal(hasSandboxPreviewEvidence(facts), true);
  assert.equal(hasSandboxPreviewEvidence({ ...facts, sandboxPreviewVisible: false }), false);
  assert.equal(hasSandboxPreviewEvidence({ ...facts, sandboxPreviewPath: '/owned/other.md' }), false);
  assert.equal(hasSandboxPreviewEvidence({ ...facts, sandboxPaneVisible: true }), false);
});

test('capability policy uses the real host payload, independently of reported reader restore state', () => {
  const { hasSandboxCapabilityEvidence, summarizeSandboxCapabilityRound } = loadConsumerFunctions();
  const reader = { hasVisibleFacts: true, surface: 'resources', activeView: 'resources', activeSurface: 'sandbox',
    singleWorkbenchSurface: true, compactMode: true, modebarHiddenInCompact: true,
    detailPaneVisible: true, sandboxPaneVisible: false, previewPaneVisible: false };
  const host = { hasCapabilitySummary: true, permissionState: 'coach_only', networkExecutionStatus: 'degraded',
    networkReasonCode: 'network_egress_os_container_image_missing' };
  assert.equal(hasSandboxCapabilityEvidence(reader, host), true);
  assert.equal(hasSandboxCapabilityEvidence(reader, undefined), false);
  assert.equal(hasSandboxCapabilityEvidence(undefined, host), false);
  assert.equal(hasSandboxCapabilityEvidence(reader, { ...host, networkReasonCode: '' }), false);
  const summary = summarizeSandboxCapabilityRound(reader, host, true, true);
  assert.equal(summary.permissionState, host.permissionState);
  assert.equal(summary.networkReasonCode, host.networkReasonCode);
  assert.equal(summary.evidenceScope, 'host-state-and-webview-debug-state');
  assert.equal(summary.visualTargetAsserted, false);
});
