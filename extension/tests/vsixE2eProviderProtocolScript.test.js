'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const extensionDir = path.resolve(__dirname, '..');
const configModulePath = path.resolve(
  extensionDir,
  'scripts',
  'vsix-e2e-provider-config.mjs',
);
const e2eScriptPath = path.resolve(extensionDir, 'scripts', 'verify-vsix-e2e.mjs');

async function loadProviderConfigHelpers() {
  return import(pathToFileURL(configModulePath).href);
}

test('VSIX E2E provider template uses Anthropics protocol defaults without OpenAI thinking fields', async () => {
  const {
    buildVsixE2EProviderSavePayloadTemplate,
    resolveVsixE2EProviderConfiguration,
  } = await loadProviderConfigHelpers();

  const configuration = resolveVsixE2EProviderConfiguration({
    extensionDir,
    requestedProtocol: 'anthropic_messages',
  });
  const payload = buildVsixE2EProviderSavePayloadTemplate(configuration);

  assert.equal(payload.name, 'trainer-e2e-anthropic-messages');
  assert.equal(payload.protocol, 'anthropic_messages');
  assert.deepEqual(payload.capabilities, {
    chat: true,
    responses: false,
    vision: true,
    embeddings: false,
    tools: true,
    jsonSchema: false,
    streaming: true,
    structuredOutput: false,
  });
  assert.equal(Object.prototype.hasOwnProperty.call(payload, 'requestDefaults'), false);
  assert.doesNotMatch(JSON.stringify(payload), /thinking/i);
});

test('VSIX E2E provider template normalizes unknown protocols to the current OpenAI-compatible default', async () => {
  const {
    buildVsixE2EProviderSavePayloadTemplate,
    resolveVsixE2EProviderConfiguration,
  } = await loadProviderConfigHelpers();

  const configuration = resolveVsixE2EProviderConfiguration({
    extensionDir,
    requestedProtocol: 'unsupported-protocol',
  });
  const payload = buildVsixE2EProviderSavePayloadTemplate(configuration);

  assert.equal(payload.name, 'trainer-e2e-openai-compatible');
  assert.equal(payload.protocol, 'openai_chat_completions_compatible');
  assert.deepEqual(payload.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
});

test('VSIX E2E driver forwards the normalized protocol and provider payload template', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');

  assert.match(source, /TRAINER_E2E_PROVIDER_PROTOCOL/);
  assert.match(
    source,
    /requestedProtocol: process\.env\.TRAINER_E2E_PROVIDER_PROTOCOL/,
  );
  assert.match(source, /TRAINER_E2E_PROVIDER_PROTOCOL: providerConfiguration\.protocol/);
  assert.match(source, /writeDriverExtension\(providerConfiguration\)/);
  assert.match(source, /\.\.\.providerSavePayloadTemplate/);
});

test('VSIX E2E persists zh-CN before verifying a provider for a zh-CN coach turn', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const languageIndex = source.indexOf('"set-provider-verification-language"');
  const providerSaveIndex = source.indexOf('"save-provider"');
  const sendIndex = source.indexOf('"send-coach-message"');

  assert.ok(languageIndex >= 0, 'the driver must persist the language before provider verification');
  assert.ok(providerSaveIndex > languageIndex, 'provider verification must follow the language setting');
  assert.ok(sendIndex > providerSaveIndex, 'the coach send must follow provider verification');
  assert.match(source, /trainer\.memory\.saveCoachSettings/);
  assert.match(source, /set-provider-verification-language[\s\S]*?responseLanguage: "zh-CN"/);
});

test('VSIX E2E keeps direct provider-bound smoke calls within the bounded provider budget', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');

  assert.match(source, /TRAINER_E2E_PROVIDER_TIMEOUT_MS/);
  assert.match(source, /providerBoundTimeoutOverrideMs >= 30_000/);
  assert.match(source, /:\s*150_000;/);
  assert.match(
    source,
    /const postProviderBoundJson = \(port, requestPath, body\) =>\s*postJson\(port, requestPath, body, providerBoundRequestTimeoutMs\);/,
  );
  assert.match(
    source,
    /assert-training-next-hop-visible-truth[\s\S]*?postProviderBoundJson\(port, "\/session\/start"/,
  );
  assert.match(
    source,
    /assert-training-next-hop-visible-truth[\s\S]*?postProviderBoundJson\(port, "\/turn"/,
  );
  assert.match(
    source,
    /assert-cross-workspace-reopen-history-truth[\s\S]*?postProviderBoundJson\(port, "\/session\/message"/,
  );
  assert.match(source, /function postJson\(port, requestPath, body, timeoutMs = 15000\)/);
});

test('VSIX E2E resolves the live sidecar port before each direct smoke flow', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');

  assert.match(source, /const currentSidecarPort = \(\) =>/);
  assert.match(source, /getDebugState\(\)[\s\S]*?state\.sidecar\.port/);
  assert.doesNotMatch(
    source,
    /const port = sidecarResult && sidecarResult\.data && sidecarResult\.data\.port/,
  );
  for (const flow of [
    'probe-sidecar-health',
    'assert-training-theory-drill-visible-truth',
    'assert-training-scenario-lab-visible-truth',
    'assert-training-next-hop-visible-truth',
    'assert-cross-workspace-reopen-history-truth',
  ]) {
    assert.match(
      source,
      new RegExp(`${flow}[\\s\\S]*?const port = currentSidecarPort\\(\\);`),
    );
  }
});

test('VSIX E2E embeds its retry delay helper in the generated smoke driver', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const driverStart = source.indexOf('function sleep(ms)');
  const driverEnd = source.indexOf('module.exports = { activate, deactivate };');
  const driverSource = source.slice(driverStart, driverEnd);

  assert.ok(driverStart >= 0 && driverEnd > driverStart, 'the generated driver source must be present');
  assert.match(driverSource, /function sleepSync\(ms\)/);
  assert.match(driverSource, /sleepSync\(captureRetryDelayMs\)/);
});

test('VSIX E2E uses a longer default window and non-fatal Windows cleanup retries', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const cleanupStart = source.indexOf('function cleanupVsixE2ETempRoot(directory)');
  const cleanupEnd = source.indexOf('function writeUserSettings()', cleanupStart);
  const cleanupSource = source.slice(cleanupStart, cleanupEnd);

  assert.match(source, /TRAINER_E2E_TIMEOUT_MS \?\? "600000"/);
  assert.ok(cleanupStart >= 0 && cleanupEnd > cleanupStart, 'the temporary-directory cleanup helper must exist');
  assert.match(cleanupSource, /fs\.rmSync\(directory, \{/);
  assert.match(cleanupSource, /maxRetries: process\.platform === "win32" \? 5 : 0/);
  assert.match(cleanupSource, /retryDelay: process\.platform === "win32" \? 200 : 0/);
  assert.match(cleanupSource, /catch \{\s*console\.warn\(`/);
  assert.doesNotMatch(cleanupSource, /\bthrow\b/);
  assert.match(source, /if \(!shouldKeepArtifacts\) \{\s*cleanupVsixE2ETempRoot\(tempRoot\);/);
});

test('VSIX E2E treats unsupported non-Windows window capture as an explicit skip', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const verifierStart = source.indexOf('function isWindowCaptureVerified(data)');
  const captureStart = source.indexOf('function captureVsCodeWindowArtifacts(', verifierStart);

  assert.ok(verifierStart >= 0 && captureStart > verifierStart, 'window-capture verifier must exist');
  const { isWindowCaptureVerified } = Function(
    `${source.slice(verifierStart, captureStart)}; return { isWindowCaptureVerified };`,
  )();

  assert.equal(
    isWindowCaptureVerified({
      skipped: true,
      captureRequired: false,
      capturePlatform: 'linux',
      reason: 'Window capture is unavailable on this platform.',
      exists: false,
      windowScreenshotPath: null,
      sidebarScreenshotPath: null,
    }),
    true,
  );
  assert.equal(
    isWindowCaptureVerified({
      skipped: true,
      captureRequired: false,
      capturePlatform: 'win32',
      reason: 'Windows capture should not be skipped.',
      exists: false,
    }),
    false,
  );
  assert.equal(
    isWindowCaptureVerified({
      skipped: false,
      captureRequired: true,
      exists: false,
      windowScreenshotPath: null,
      sidebarScreenshotPath: null,
    }),
    false,
  );
  assert.equal(
    isWindowCaptureVerified({
      skipped: false,
      exists: true,
      windowScreenshotPath: '/tmp/window.png',
      sidebarScreenshotPath: '/tmp/sidebar.png',
    }),
    true,
  );

  const captureEnd = source.indexOf('function escapePowerShellLiteral(', captureStart);
  const captureSource = source.slice(captureStart, captureEnd);
  const loadCapture = (platform) =>
    Function(
      'process',
      `${captureSource}; return { captureVsCodeWindowArtifacts };`,
    )({ platform });
  const unsupportedCapture = loadCapture('linux').captureVsCodeWindowArtifacts({});
  const missingWindowsArtifacts = loadCapture('win32').captureVsCodeWindowArtifacts({});

  assert.deepEqual(unsupportedCapture, {
    skipped: true,
    captureRequired: false,
    capturePlatform: 'linux',
    reason: 'Window capture is only implemented for win32 in this smoke driver, current platform=linux.',
    windowScreenshotPath: null,
    sidebarScreenshotPath: null,
  });
  assert.equal(missingWindowsArtifacts.skipped, false);
  assert.equal(missingWindowsArtifacts.captureRequired, true);
  assert.equal(missingWindowsArtifacts.capturePlatform, 'win32');
  assert.match(captureSource, /captureRequired: false/);
  assert.match(captureSource, /capturePlatform: process\.platform/);
  assert.equal([...source.matchAll(/ok: isWindowCaptureVerified/g)].length, 7);
  assert.match(source, /isWindowCaptureVerified\(run\.screenshot\)/);
});

test('VSIX E2E provisions and admits an isolated Trainer Workspace before gated commands', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const provisionIndex = source.indexOf('provisionTemporaryTrainerWorkspace();');
  const admissionIndex = source.indexOf('"admit-temporary-trainer-workspace"');
  const refreshMemoryIndex = source.indexOf('"refresh-memory"');

  assert.ok(provisionIndex >= 0, 'the temporary Trainer Workspace must be created before VS Code launches');
  assert.ok(admissionIndex >= 0, 'the driver must explicitly admit the current project');
  assert.ok(refreshMemoryIndex > admissionIndex, 'memory refresh must wait for managed admission');
  assert.match(source, /DatabaseSync/);
  assert.match(source, /"trainer\.workspace\.root\.v1"/);
  assert.match(source, /TRAINER_E2E_TRAINER_WORKSPACE_DIR/);
  assert.match(source, /trainer\.workspace\.adoptProject/);
  assert.match(source, /data\.status === "managed"/);
  assert.match(source, /const tempRoot = createVsixE2ETempRoot\(\)/);
  assert.doesNotMatch(source, /trainer\.session\.resumeProjectLane/);
  assert.doesNotMatch(source, /resetWorkspaceIfPossible/);
  assert.doesNotMatch(source, /\/workspace\/reset/);
});

test('VSIX E2E seeds theory training through the managed context ID', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');

  assert.match(source, /const managedContextId =/);
  assert.match(source, /Managed Trainer Workspace did not return a contextId/);
  assert.match(
    source,
    /assert-training-theory-drill-visible-truth[\s\S]*?workspace_id: managedContextId/,
  );
  assert.match(
    source,
    /seed-dependency-mastery-through-public-command[\s\S]*?workspace_id: managedContextId/,
  );
});

test('VSIX E2E keeps host-visible scenario and next-hop flows in the managed context', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const scenarioStart = source.indexOf('await record("assert-training-scenario-lab-visible-truth"');
  const nextHopStart = source.indexOf('await record("assert-training-next-hop-visible-truth"');
  const nextHopEnd = source.indexOf('await record("capture-training-next-hop-installed-screenshot"');

  assert.ok(scenarioStart >= 0, 'the scenario-lab flow must exist');
  assert.ok(nextHopStart > scenarioStart, 'the next-hop flow must follow the scenario-lab flow');
  assert.ok(nextHopEnd > nextHopStart, 'the next-hop flow must have a bounded source region');

  const scenarioSource = source.slice(scenarioStart, nextHopStart);
  const nextHopSource = source.slice(nextHopStart, nextHopEnd);

  assert.match(scenarioSource, /workspace_id: managedContextId/);
  assert.doesNotMatch(scenarioSource, /workspace_id: smokeWorkspaceDir/);
  assert.match(scenarioSource, /bootstrap\.workspaceTrainingState/);
  assert.match(scenarioSource, /scenarioLabMaterialized: Boolean\(scenarioLab && scenarioLab\.id\)/);
  assert.match(scenarioSource, /sessionId,\s*workspaceId: managedContextId/);
  assert.match(scenarioSource, /const restoreResult = await vscode\.commands\.executeCommand\("trainer\.debug\.restoreView"/);
  assert.match(scenarioSource, /waitForVisibleFacts\(\s*"training"/);
  assert.match(scenarioSource, /data\.restoreSucceeded === true/);
  assert.match(scenarioSource, /data\.restoreKind === "scenario_lab"/);
  assert.match(scenarioSource, /data\.scenarioLabVisible === true/);
  assert.match(scenarioSource, /data\.visibleScenarioLabId === data\.scenarioLabId/);
  assert.match(scenarioSource, /data\.scenarioLabTitle === data\.expectedScenarioLabTitle/);
  assert.doesNotMatch(scenarioSource, /data\.scenarioLabVisible === false/);
  assert.match(nextHopSource, /workspace_id: managedContextId/);
  assert.match(nextHopSource, /workspaceId: managedContextId/);
  assert.match(nextHopSource, /encodeURIComponent\(managedContextId\)/);
  assert.match(nextHopSource, /provider: providerTransportConfig\(\)/);
  assert.match(nextHopSource, /api_key: providerApiKey/);
  assert.match(nextHopSource, /use_agent_loop: false/);
  assert.doesNotMatch(nextHopSource, /workspace_id: smokeWorkspaceDir/);
  assert.doesNotMatch(nextHopSource, /workspaceId: smokeWorkspaceDir/);
  assert.doesNotMatch(nextHopSource, /encodeURIComponent\(smokeWorkspaceDir\)/);
  assert.match(nextHopSource, /bootstrap\.workspaceTrainingState/);
});

test('VSIX E2E uses readable coach prompts', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');

  assert.match(source, /先给我一张不替我写代码的最小实战卡/);
  assert.match(source, /我完成了最小练习，并提交结果等待核验/);
  assert.doesNotMatch(source, /璇峰彧/);
  assert.doesNotMatch(source, /\uFFFD/);
});

test('VSIX E2E records next-hop truth through the public practice-return route', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const flowStart = source.indexOf('await record("assert-training-next-hop-visible-truth"');
  const flowEnd = source.indexOf('await record("capture-training-next-hop-installed-screenshot"', flowStart);
  const flowSource = source.slice(flowStart, flowEnd);

  assert.ok(flowStart >= 0 && flowEnd > flowStart, 'the next-hop flow must exist');
  assert.match(flowSource, /"\/training\/active-card\?workspace_id="/);
  assert.match(flowSource, /const activeCardId =/);
  assert.match(flowSource, /postJson\(port, "\/training\/practice-return"/);
  assert.match(flowSource, /card_id: activeCardId/);
  assert.match(flowSource, /practiceReturn\.ok === true/);
  assert.match(flowSource, /practice_evaluation_recorded/);
  assert.match(flowSource, /"verification_required"/);
  assert.doesNotMatch(flowSource, /training_return:/);
});

test('VSIX E2E reads reopened workspace state from its new session', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const flowStart = source.indexOf('await record("assert-cross-workspace-reopen-history-truth"');
  const flowEnd = source.indexOf('finalReport = {', flowStart);
  const flowSource = source.slice(flowStart, flowEnd);

  assert.ok(flowStart >= 0 && flowEnd > flowStart, 'the cross-workspace flow must be present');
  assert.match(flowSource, /session_id: newSessionId/);
  assert.match(
    flowSource,
    /"\/memory\/summary\?session_id="\s*\+\s*encodeURIComponent\(newSessionId\)/,
  );
  assert.match(
    flowSource,
    /"\/session\/history\?session_id="\s*\+\s*encodeURIComponent\(newSessionId\)/,
  );
  assert.match(flowSource, /"\/training\/generate-card"/);
  assert.match(flowSource, /routedCardId/);
  assert.match(flowSource, /trainingRouteCardId/);
  assert.match(flowSource, /assistantHasVisibleReply/);
  assert.doesNotMatch(flowSource, /assistantHasMinimalActionLanguage/);
});

test('VSIX E2E checks the public sandbox skill capability contract instead of an unpublished run route', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');

  assert.doesNotMatch(source, /\/sandbox\/skill\/run/);
  assert.match(source, /skill_manifest_status/);
  assert.match(source, /skill_runtime_status/);
  assert.match(source, /trainer\.resource_sandbox\.skill_manifest\.v1/);
  assert.match(source, /trainer\.resource_sandbox\.skill_runtime\.v1/);
});

test('VSIX E2E compares native-open paths with Windows case rules and checks actual resource state', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');
  const sandboxStart = source.indexOf('await record("assert-resources-sandbox-capability-visible-truth"');
  const sandboxEnd = source.indexOf('await record("capture-resources-sandbox-installed-screenshot"', sandboxStart);
  const sandboxSource = source.slice(sandboxStart, sandboxEnd);

  assert.ok(sandboxStart >= 0 && sandboxEnd > sandboxStart, 'the sandbox truth flow must exist');
  assert.match(source, /function pathsReferToSameFile\(left, right\)/);
  assert.match(source, /process\.platform === "win32"/);
  assert.match(source, /normalizedLeft\.toLowerCase\(\) === normalizedRight\.toLowerCase\(\)/);
  assert.match(source, /pathsReferToSameFile\(data\.nativeOpenPath, data\.sandboxPath\)/);
  assert.match(sandboxSource, /selectedSandboxPath: facts \? facts\.selectedSandboxPath \|\| null : null,/);
  assert.match(sandboxSource, /workspaceId: managedContextId/);
  assert.doesNotMatch(sandboxSource, /sessionId,\s*workspaceId: managedContextId/);
  assert.match(sandboxSource, /sandboxPath,/);
  assert.match(sandboxSource, /waitForVisibleFacts\(\s*"resources"/);
  assert.match(sandboxSource, /data\.restoreSucceeded === true/);
  assert.match(sandboxSource, /data\.activeSurface === "sandbox"/);
  assert.match(sandboxSource, /data\.selectedSandboxPath === data\.sandboxPath/);
  assert.match(sandboxSource, /data\.detailPaneVisible === false/);
  assert.match(sandboxSource, /data\.sandboxPaneVisible === true/);
  assert.match(sandboxSource, /data\.previewPaneVisible === false/);
  assert.doesNotMatch(sandboxSource, /data\.activeSurface === "detail"/);
  assert.doesNotMatch(sandboxSource, /data\.permissionState === "coach_only"/);
  assert.doesNotMatch(sandboxSource, /data\.networkExecutionStatus === "degraded"/);
});

test('VSIX E2E accepts a concise or coach-qualified sidebar command title', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');

  assert.match(source, /\/open\.\*sidebar\/i\.test\(data\.openCommandTitle\)/);
  assert.doesNotMatch(source, /\/open sidebar\/i\.test\(data\.openCommandTitle\)/);
});

test('VSIX E2E uses workspace resource fixtures and the public review-queue command', () => {
  const source = fs.readFileSync(e2eScriptPath, 'utf8');

  assert.match(source, /TRAINER_VSIX_E2E_TEMP_ROOT/);
  assert.match(source, /fs\.accessSync\(resolvedRoot, fs\.constants\.W_OK\)/);
  assert.match(source, /maxRootLength = 40/);
  assert.match(source, /const resourceFixtures = \[/);
  assert.match(source, /path\.join\(smokeWorkspaceDir, "vsix-e2e-sandbox-capability\.md"\)/);
  assert.match(source, /path\.join\(smokeWorkspaceDir, "vsix-resource-detail-proof\.md"\)/);
  assert.match(source, /path\.join\(smokeWorkspaceDir, "vsix-sandbox-preview-proof\.md"\)/);
  assert.match(source, /trainer\.training\.reviewQueueAction/);
  assert.match(source, /trainer\.training\.generateCard/);
  assert.match(source, /trainer\.training\.dependencySkillMapAction/);
  assert.match(source, /seed-dependency-mastery-through-public-command/);
  assert.match(source, /dependencyKey: "fastapi"/);
  assert.match(source, /responseScenarioLabId/);
  assert.match(source, /hostScenarioLabId/);
  assert.match(source, /repetition_count: 1/);
  assert.match(source, /repetition_count: 2/);
  assert.match(source, /bootstrap\.workspaceTrainingState/);
  assert.match(source, /const summaryResources =/);
  assert.doesNotMatch(source, /\/resource\/detail/);
  assert.doesNotMatch(source, /trainer\.reviewQueue\.action/);
  assert.doesNotMatch(source, /source: "inline:\/\//);
});
