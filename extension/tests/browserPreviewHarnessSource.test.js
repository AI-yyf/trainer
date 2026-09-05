'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const harnessSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewHarness.ts',
);
const appSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'App.tsx',
);
const guidedTrainingPacksSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'guidedTrainingScenarioPacks.ts',
);
const browserSidecarSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserSidecar.ts',
);

function readHarnessSource() {
  return fs.readFileSync(harnessSourcePath, 'utf8');
}

function readAppSource() {
  return fs.readFileSync(appSourcePath, 'utf8');
}

function readGuidedTrainingPacksSource() {
  return fs.readFileSync(guidedTrainingPacksSourcePath, 'utf8');
}

function readBrowserSidecarSource() {
  return fs.readFileSync(browserSidecarSourcePath, 'utf8');
}

function extractScenarioBlock(source, startMarker, endMarkers) {
  const start = source.indexOf(startMarker);
  if (start < 0) {
    return null;
  }

  const contentStart = start + startMarker.length;
  const candidates = endMarkers
    .map((marker) => source.indexOf(marker, contentStart))
    .filter((index) => index >= 0);
  const end = candidates.length > 0 ? Math.min(...candidates) : source.length;
  return source.slice(contentStart, end);
}

test('browser preview connected mode configures provider readiness', () => {
  const source = readHarnessSource();
  const connectedBranch = source.match(
    /if \(connectionState === "offline"\) \{[\s\S]*?\} else \{([\s\S]*?)\n  \}/,
  );

  assert.ok(connectedBranch, 'expected offline/connected provider branch');
  assert.match(connectedBranch[1], /applyConnectedProviderBootstrap\(bootstrap, state\.composerLanguage\)/);
  assert.match(connectedBranch[1], /state: connectionState/);
});

test('browser preview offline mode does not offer mock connections as saved profiles', () => {
  const source = readHarnessSource();
  const offlineStart = source.indexOf('if (connectionState === "offline") {');
  const offlineEnd = source.indexOf('  } else {', offlineStart);
  const offlineBranch = source.slice(offlineStart, offlineEnd);

  assert.ok(offlineStart >= 0 && offlineEnd > offlineStart, 'expected offline provider branch');
  assert.match(offlineBranch, /configured: false,/);
  assert.match(offlineBranch, /profileId: undefined,/);
  assert.match(offlineBranch, /profileCount: 0,/);
  assert.match(offlineBranch, /providerProfiles: \[\],/);
  assert.match(offlineBranch, /providerDashboard: undefined,/);
});

test('browser preview routes ordinary Plan and Resources commands through local visible state', () => {
  const source = readHarnessSource();

  assert.match(source, /import \{[\s\S]*?runBrowserPreviewAction,[\s\S]*?\} from "\.\/browserPreviewActions";/);
  assert.match(source, /const PREVIEW_HOST_MESSAGE_EVENT = "trainer:host-message";/);
  assert.match(source, /function runBrowserPreviewWebviewAction\(/);
  assert.match(source, /action\.type === "request\/bootstrap"/);
  assert.match(source, /runBrowserPreviewAction\(action, bootstrap, language\)/);
  assert.match(source, /type: "state\/patch"/);
  assert.match(source, /type: "operation\/status"/);
  assert.match(source, /runBrowserPreviewWebviewAction\(message, state\.composerLanguage\)/);
});

test('browser preview sends live training commands to the real sidecar when connected', () => {
  const source = readHarnessSource();

  assert.match(source, /state\.connectionState !== "offline"/);
  assert.match(source, /LIVE_TRAINING_COMMAND_IDS\.has\(message\.payload\.commandId\)/);
  assert.match(source, /void runBrowserPreviewLiveTrainingAction\(message, state\.composerLanguage\);/);
  assert.match(source, /return;/);
});

test('browser preview resolves resource training handoffs from durable real training results', () => {
  const source = readHarnessSource();
  const appSource = readAppSource();
  const start = source.indexOf('async function runBrowserPreviewLiveTrainingAction(');
  const end = source.indexOf('\nfunction emitLivePreviewOperationStatus(', start);
  const trainingAction = source.slice(start, end);

  assert.ok(start >= 0 && end > start, 'expected live training action');
  assert.match(source, /const RESOURCE_TRAINING_HANDOFF_REQUEST_ID_KEY = "__trainerResourceTrainingHandoffId";/);
  assert.match(source, /function browserPreviewResourceTrainingHandoffRequest\(/);
  assert.match(source, /function browserPreviewResourceTrainingHandoffSuccess\(/);
  assert.match(source, /function browserPreviewResourceTrainingHandoffFailure\(/);
  assert.match(source, /type: "training\/resourceHandoff"/);
  assert.match(
    source,
    /failureReason === "resource_missing" \|\| failureReason === "resource_needs_refresh"\s*\? "blocked"\s*: "failed"/,
  );
  assert.match(
    source,
    /success && generatedCardId && selectedCardId === generatedCardId\s*\? "ready"/,
  );
  assert.match(trainingAction, /const resourceTrainingHandoff = browserPreviewResourceTrainingHandoffRequest\(action\);/);
  assert.match(trainingAction, /requestFor\(\s*"\/training\/generate-card\/stream"/);
  assert.match(
    trainingAction,
    /const refreshedSnapshot = await refreshLiveBrowserPreviewBootstrap\(\);[\s\S]*?browserPreviewResourceTrainingHandoffSuccess\(/,
  );
  assert.ok(
    trainingAction.indexOf('const refreshedSnapshot = await refreshLiveBrowserPreviewBootstrap();') <
      trainingAction.indexOf('browserPreviewResourceTrainingHandoffSuccess('),
    'resource handoff success must be derived after the durable snapshot refresh',
  );
  assert.match(trainingAction, /Training card stream cancelled\./);
  assert.match(trainingAction, /browserPreviewResourceTrainingHandoffFailure\(resourceTrainingHandoff, detail\)/);
  assert.match(appSource, /isBrowserPreview=\{browserPreviewFixture\}/);
  assert.match(
    appSource,
    /onStartTrainingFromResource=\{\s*browserPreviewFixture \? undefined : requestResourceTrainingHandoff\s*\}/,
  );
});

test('browser preview live mode bridges training command execute events to real sidecar routes', () => {
  const source = readHarnessSource();

  assert.match(source, /const PREVIEW_WEBVIEW_ACTION_EVENT = "trainer:webview-action";/);
  assert.match(source, /const LIVE_TRAINING_COMMAND_IDS = new Set<string>\(\[/);
  assert.match(source, /trainerCommands\.evidenceEnqueue/);
  assert.match(source, /trainerCommands\.trainingGenerateCard/);
  assert.match(source, /window\.addEventListener\(PREVIEW_WEBVIEW_ACTION_EVENT,/);
  assert.match(source, /void refreshLiveBrowserPreviewBootstrap\(\);/);
  assert.match(source, /fetchBrowserPreviewBootstrap\(livePreviewSessionId, true\)/);
  assert.match(source, /void runBrowserPreviewLiveTrainingAction\(action, state\.composerLanguage\);/);
  assert.match(source, /requestFor\(\s*"\/training\/generate-card\/stream"/);
  assert.match(source, /HTTP 502 \(and peers\): pending/);
  assert.match(source, /reliabilityOutcome:\s*"failure"/);
  assert.match(source, /The training card could not be prepared/);
  assert.match(source, /requestFor\(\s*"\/training\/practice-return"/);
  assert.match(source, /void runBrowserPreviewLiveAction\(action, state\.composerLanguage\);/);
});

test('browser preview acknowledges only durable live training persistence commands', () => {
  const source = readHarnessSource();
  const start = source.indexOf('async function runBrowserPreviewLiveTrainingAction(');
  const end = source.indexOf('\nfunction emitLivePreviewOperationStatus(', start);
  const trainingAction = source.slice(start, end);

  assert.ok(start >= 0 && end > start, 'expected live training action');
  assert.match(source, /const TRAINING_PERSISTENCE_REQUEST_ID_KEY = "__trainerTrainingPersistenceId";/);
  assert.match(source, /const LIVE_TRAINING_PERSISTENCE_COMMAND_IDS = new Set<string>\(\[/);
  assert.match(source, /function browserPreviewTrainingPersistenceRequest\(/);
  assert.match(source, /function browserPreviewReliabilityFields\(/);
  assert.match(source, /function emitBrowserPreviewTrainingPersistenceAck\(/);
  assert.match(trainingAction, /const persistence = browserPreviewTrainingPersistenceRequest\(action\);/);
  assert.match(trainingAction, /\.\.\.browserPreviewReliabilityFields\(payload\)/);
  assert.match(trainingAction, /requestFor\(\s*"\/training\/card-status"/);
  assert.match(trainingAction, /requestFor\(\s*"\/training\/reflect"/);
  assert.match(trainingAction, /requestFor\(\s*"\/training\/return"/);
  assert.match(trainingAction, /requestFor\(\s*"\/evidence\/enqueue"/);
  assert.match(trainingAction, /waiting_composer: true/);
  assert.match(trainingAction, /waitingComposerEnqueueFailureText/);
  assert.match(trainingAction, /source_card_id: browserPreviewString\(payload\?\.sourceCardId\)/);
  assert.match(trainingAction, /target_plan_stage_id: browserPreviewString\(payload\?\.targetPlanStageId\)/);
  assert.match(
    trainingAction,
    /await refreshLiveBrowserPreviewBootstrap\(\);[\s\S]*?emitBrowserPreviewTrainingPersistenceAck\(persistence, true, responseRecord\);/,
  );
  assert.ok(
    trainingAction.indexOf('await refreshLiveBrowserPreviewBootstrap();') <
      trainingAction.indexOf('emitBrowserPreviewTrainingPersistenceAck(persistence, true, responseRecord);'),
    'the acknowledgement must follow the refreshed durable snapshot',
  );
  assert.match(
    trainingAction,
    /emitBrowserPreviewTrainingPersistenceAck\(persistence, false, undefined, enqueueFailure\)/,
  );
});

test('browser preview live mode never falls back to fixture patches for non-training actions', () => {
  const source = readHarnessSource();
  const configureStart = source.indexOf('function configureBrowserPreviewEnvironment(');
  const configureEnd = source.indexOf('function persistExplicitBrowserPreviewTheme', configureStart);
  const configure = source.slice(configureStart, configureEnd);

  assert.match(configure, /void runBrowserPreviewLiveAction\(action, state\.composerLanguage\);/);
  assert.match(
    configure,
    /state\.connectionState === "offline"[\s\S]*?runBrowserPreviewWebviewAction\(action, state\.composerLanguage\);/,
  );
  assert.match(source, /trainerCommands\.indexResources/);
  assert.match(source, /fetch\(\x60\$\{sidecarBaseUrl\}\/plan\/update\x60/);
  assert.match(source, /fetch\(\x60\$\{sidecarBaseUrl\}\/resource\/index\x60/);
});

test('browser preview generates formal plans through the Agent stream with all plan context', () => {
  const source = readHarnessSource();
  const start = source.indexOf('if (isPlanGenerate) {');
  const end = source.indexOf('\n    if (isGlobalPlanCreate || isGlobalPlanLink) {', start);
  const planGeneration = source.slice(start, end);

  assert.ok(start >= 0 && end > start, 'expected live plan generation branch');
  assert.doesNotMatch(planGeneration, /\/plan\/generate/);
  assert.match(planGeneration, /await streamBrowserPreviewMessage\(request, livePreviewSessionId \?\? "", \{/);
  assert.match(planGeneration, /goals,/);
  assert.match(planGeneration, /intent: "plan",/);
  assert.match(planGeneration, /activeView: "plan",/);
  assert.match(planGeneration, /formalPlanMutation: true,/);
  assert.match(planGeneration, /useAgentLoop: true,/);
  assert.match(planGeneration, /snapshot\.resources\.map\(\(resource\) => resource\.id\)/);
  assert.match(planGeneration, /constraints\.join\("; "\)/);
  assert.match(planGeneration, /onStart: \(message\) => emitBrowserPreviewHostMessage\(message\)/);
  assert.match(planGeneration, /onChunk: \(message\) => emitBrowserPreviewHostMessage\(message\)/);
  assert.match(planGeneration, /onComplete: \(message, nextSessionId\) => \{/);
  assert.match(planGeneration, /onError: \(message\) => \{/);
  assert.match(planGeneration, /onCancelled: \(message\) => \{/);
  assert.match(planGeneration, /if \(completed\) \{\s*await refreshLiveBrowserPreviewBootstrap\(\);/);
  assert.match(planGeneration, /if \(cancelled\) \{/);
});

test('browser preview training streams always close after empty bodies or failures', () => {
  const source = readHarnessSource();
  const start = source.indexOf('async function consumeBrowserPreviewTrainingCardStream(');
  const end = source.indexOf('\nfunction runBrowserPreviewWebviewAction(', start);
  const streamConsumer = source.slice(start, end);

  assert.ok(start >= 0 && end > start, 'expected training stream consumer');
  assert.match(streamConsumer, /type: "stream\/start"/);
  assert.match(streamConsumer, /if \(!response\.body\) \{\s*return emitStreamError\(/);
  assert.match(streamConsumer, /type: "stream\/error"/);
  assert.match(streamConsumer, /Training card stream ended before completion\./);
  assert.match(streamConsumer, /catch \(error\) \{[\s\S]*?return emitStreamError\(/);
  assert.match(streamConsumer, /if \(completion\) \{\s*break;\s*\}/);
  assert.match(streamConsumer, /await reader\.cancel\(\)\.catch\(\(\) => undefined\)/);
  assert.match(streamConsumer, /reader\?\.releaseLock\(\);/);
  assert.match(streamConsumer, /terminal = "complete";[\s\S]*?type: "stream\/complete"/);
});

test('browser preview training streams join the shared cancellation registry', () => {
  const source = readHarnessSource();
  const start = source.indexOf('async function runBrowserPreviewLiveTrainingAction(');
  const end = source.indexOf('\nfunction emitLivePreviewOperationStatus(', start);
  const trainingAction = source.slice(start, end);
  const consumerStart = source.indexOf('async function consumeBrowserPreviewTrainingCardStream(');
  const consumerEnd = source.indexOf('\nfunction isCompletedLivePreviewResourceIndex(', consumerStart);
  const streamConsumer = source.slice(consumerStart, consumerEnd);

  assert.ok(start >= 0 && end > start, 'expected live training action');
  assert.match(source, /registerBrowserPreviewStream,/);
  assert.match(source, /attachBrowserPreviewStreamReader,/);
  assert.match(source, /releaseBrowserPreviewStream,/);
  assert.match(
    trainingAction,
    /registerBrowserPreviewStream\(activeTrainingStream\.messageId, activeTrainingStream\.controller, \{[\s\S]*?sidecarBaseUrl,[\s\S]*?streamId: activeTrainingStream\.messageId,[\s\S]*?\}\)/,
  );
  assert.match(trainingAction, /const providerOverride = browserPreviewProviderRequestOverride\(\)/);
  assert.match(trainingAction, /stream_id: activeTrainingStream\.messageId,/);
  assert.match(trainingAction, /provider: providerOverride\.provider,/);
  assert.match(trainingAction, /api_key: providerOverride\.apiKey,/);
  assert.match(trainingAction, /activeTrainingStream\.controller\.signal/);
  assert.match(trainingAction, /type: "stream\/cancelled"/);
  assert.match(trainingAction, /releaseBrowserPreviewStream\(activeTrainingStream\.messageId\)/);
  assert.match(streamConsumer, /attachBrowserPreviewStreamReader\(messageId, reader\)/);
  assert.match(streamConsumer, /if \(signal\.aborted\) \{\s*return emitStreamCancelled\(\);/);
  assert.match(streamConsumer, /type: "stream\/cancelled"/);
});

test('browser preview cancellation notifies the sidecar before aborting its local reader', () => {
  const source = readBrowserSidecarSource();
  const start = source.indexOf('export function cancelBrowserPreviewStream(');
  const end = source.indexOf('\nconst INTERNAL_COACH_META_MARKERS', start);
  const cancellation = source.slice(start, end);

  assert.ok(start >= 0 && end > start, 'expected browser preview cancellation helper');
  assert.match(source, /sidecarBaseUrl\?: string;/);
  assert.match(source, /streamId\?: string;/);
  assert.match(cancellation, /\$\{active\.sidecarBaseUrl\}\/stream\/cancel/);
  assert.match(cancellation, /body: JSON\.stringify\(\{ stream_id: active\.streamId \}\)/);
  assert.ok(
    cancellation.indexOf('/stream/cancel') < cancellation.indexOf('active.controller.abort()'),
    'remote cancellation should be requested before local abort',
  );
});

test('browser preview keeps VS Code-only live-follow sync silent', () => {
  const source = readAppSource();

  assert.match(
    source,
    /useEffect\(\(\) => \{\s*if \(isBrowserPreview\) \{\s*return;\s*\}\s*postMessage\(\{\s*type: "ui\/liveFollow"/,
  );
});

test('browser preview connected mode keeps provider, model, and profile identity aligned', () => {
  const source = readHarnessSource();
  const connectedFunction = extractScenarioBlock(
    source,
    'function applyConnectedProviderBootstrap(',
    ['if (language !== "zh-CN") {'],
  );

  assert.ok(connectedFunction, 'expected connected provider bootstrap');
  assert.match(connectedFunction, /const providerName = previewProviderLabel\(language, "local"\)/);
  assert.match(connectedFunction, /const model = "gpt-4\.1-mini-compatible"/);
  assert.match(connectedFunction, /const profile = \{/);
  assert.match(connectedFunction, /id: "preview-compatible-service"/);
  assert.match(connectedFunction, /profileId: profile\.id/);
  assert.match(connectedFunction, /profileLabel: profile\.label/);
  assert.match(connectedFunction, /providerProfiles: \[profile\]/);
  assert.match(connectedFunction, /currentProfile: profile/);
  assert.match(connectedFunction, /profileHistory: \[\]/);
});

test('browser preview includes a loaded resource preview scenario', () => {
  const source = readHarnessSource();

  assert.match(source, /resource-preview-loaded/);
  assert.match(source, /sandboxPreview:\s*\{/);
  assert.match(source, /content:\s*previewText/);
  assert.match(source, /selectedResourceDetail/);
  assert.match(source, /structuredData:\s*\{/);
});

test('browser preview includes a rich content scenario for coach rendering QA', () => {
  const source = readHarnessSource();
  const richBranch = extractScenarioBlock(source, 'if (scenario === "rich-content") {', [
    'if (scenario === "blocked") {',
  ]);

  assert.ok(richBranch, 'expected rich-content preview scenario');
  assert.match(source, /"rich-content"/);
  assert.match(richBranch, /```ts/);
  assert.match(richBranch, /\$\$/);
  assert.match(richBranch, /\| Phase \| Goal \| Verify \|/);
  assert.match(richBranch, /```mermaid/);
  assert.match(richBranch, /applyConnectedProviderBootstrap\(bootstrap, language\)/);
});

test('browser preview ready scenario localizes profile values for visual QA', () => {
  const source = readHarnessSource();
  const readyBranch = extractScenarioBlock(source, 'if (scenario === "ready" || scenario === "vision-ready") {', [
    'if (scenario === "provider-failure" || scenario === "provider-failure-empty") {',
  ]);

  assert.ok(readyBranch, 'expected ready preview scenario');
  assert.match(readyBranch, /bootstrap\.profile\s*=\s*\{/);
  assert.match(readyBranch, /learnerName:\s*previewText\(language,\s*"\u4f60",\s*"You"\)/);
  assert.match(readyBranch, /targetProject:\s*previewText/);
  assert.match(readyBranch, /Turn Trainer into a long-lived unified learning coach extension/);
  assert.match(readyBranch, /Lower sidebar friction, continuity gaps, and plan-reading cost first/);
  assert.match(
    readyBranch,
    /applyLocalizedConnectedPlanPreview\(bootstrap, language\);\s*return;/,
  );
});

test('vision-ready preview declares and verifies vision and tools truth for image send', () => {
  const source = readHarnessSource();
  const appSource = readAppSource();
  const readyBranch = extractScenarioBlock(source, 'if (scenario === "ready" || scenario === "vision-ready") {', [
    'if (scenario === "provider-failure" || scenario === "provider-failure-empty") {',
  ]);

  assert.ok(readyBranch, 'expected ready preview scenario');
  assert.match(readyBranch, /vision: true,/);
  assert.match(readyBranch, /tools: scenario === "vision-ready",/);
  assert.match(readyBranch, /streaming: true,/);
  assert.match(readyBranch, /name: "vision", declared: true, observed: true, state: "verified"/);
  assert.match(readyBranch, /name: "tools", declared: true, observed: true, state: "verified"/);
  assert.match(readyBranch, /toolsReady: scenario === "vision-ready",/);
  assert.match(readyBranch, /toolProbeStatus: scenario === "vision-ready" \? \("verified" as const\) : \("unverified" as const\),/);
  assert.match(appSource, /attachments=\{composerAttachments\}/);
  assert.match(appSource, /onAttachmentsChange=\{setComposerAttachments\}/);
  assert.match(appSource, /attachmentsAvailable=\{providerImageInputState\.supported\}/);
});

test('browser preview keeps saved coach defaults adaptive while runtime answer mode stays resolved', () => {
  const source = readHarnessSource();

  assert.match(source, /composerAnswerMode:\s*"auto"/);
  assert.match(source, /teachingStyle:\s*"auto"/);
  assert.match(source, /preferredStyle:\s*"auto"/);
  assert.match(source, /answerMode:\s*"guided"/);
  assert.doesNotMatch(source, /answerMode:\s*"coach-first"/);
});

test('browser preview done scenario exposes finalize metadata for transcript QA', () => {
  const source = readHarnessSource();
  const doneBranch = extractScenarioBlock(source, 'if (scenario === "done") {', [
    'if (scenario === "empty") {',
  ]);

  assert.ok(doneBranch, 'expected done preview scenario');
  assert.match(doneBranch, /decision:/);
  assert.match(doneBranch, /teachingNote:/);
  assert.match(doneBranch, /confidence:\s*"high"/);
  assert.match(doneBranch, /resumeThread:/);
  assert.match(doneBranch, /coach_visible_status/);
});

test('browser preview accepts explicit theme overrides for responsive QA', () => {
  const source = readHarnessSource();

  assert.match(source, /requestedTheme = search\.get\("theme"\)/);
  assert.match(source, /requestedVscodeTheme = search\.get\("vscodeTheme"\)/);
  assert.match(source, /themePreference: resolvedThemePreference/);
  assert.match(source, /document\.body\.classList\.add\(`vscode-\$\{state\.vscodeTheme \?\? "dark"\}`\)/);
});

test('browser preview keeps every supported language available to localized training packs', () => {
  const source = readHarnessSource();
  const packsSource = readGuidedTrainingPacksSource();

  assert.match(source, /import \{ SUPPORTED_LANGUAGES \} from "\.\.\/\.\.\/\.\.\/\.\.\/shared\/src\/types";/);
  assert.match(source, /language: ComposerLanguage,/);
  assert.match(
    source,
    /const resolvedLanguage = SUPPORTED_LANGUAGES\.includes\(requestedLanguage as ComposerLanguage\)\s*\?\s*\(requestedLanguage as ComposerLanguage\)\s*:\s*"zh-CN";/,
  );
  assert.match(packsSource, /type PreviewLanguage = ComposerLanguage;/);
  assert.match(packsSource, /const previewFallbackCopy: Partial<Record<ComposerLanguage, PreviewFallbackCopy>>/);
  assert.match(packsSource, /function buildLocalizedFallbackScenario\(/);
  assert.match(packsSource, /const fallbackCopy = previewFallbackCopy\[language\];/);
});

test('browser preview empty scenario clears the training lane for honest QA', () => {
  const source = readHarnessSource();
  const emptyBranch = extractScenarioBlock(source, 'if (scenario === "empty") {', [
    'if (scenario === "resource-preview-loaded") {',
  ]);

  assert.ok(emptyBranch, 'expected empty preview scenario');
  assert.match(emptyBranch, /bootstrap\.workspaceTrainingState = undefined;/);
  assert.match(emptyBranch, /currentFocus:\s*""/);
  assert.match(emptyBranch, /bootstrap\.resources = \[\];/);
  assert.match(emptyBranch, /bootstrap\.conversation = \[\];/);
});

test('browser preview includes a provider failure scenario for settings QA', () => {
  const source = readHarnessSource();
  const failureBranch = extractScenarioBlock(
    source,
    'if (scenario === "provider-failure" || scenario === "provider-failure-empty") {',
    ['if (scenario === "provider-auth-failure" || scenario === "provider-auth-failure-empty") {'],
  );

  assert.ok(failureBranch, 'expected provider-failure preview scenario');
  assert.match(failureBranch, /modelErrorCategory: "model_not_found"/);
  assert.match(failureBranch, /status: "model_not_found"/);
  assert.match(failureBranch, /demo-model/);
  assert.match(failureBranch, /http:\/\/localhost:1234\/v1/);
  assert.doesNotMatch(failureBranch, /47\.107\.101\.18|aikey\.redfast/);
  assert.match(failureBranch, /No model is available right now/i);
});

test('browser preview includes an empty provider failure scenario for coach blocked-state QA', () => {
  const source = readHarnessSource();

  assert.match(source, /"provider-failure-empty"/);
  assert.match(source, /requestedScenario === "provider-failure-empty"/);
  assert.match(source, /scenario === "provider-failure-empty"\s*\?\s*\[\]/);
  assert.match(
    source,
    /if \(scenario === "provider-failure-empty"\) \{[\s\S]*?bootstrap\.workspaceTrainingState = undefined;[\s\S]*?bootstrap\.memory = \{[\s\S]*?currentFocus:\s*""[\s\S]*?\};[\s\S]*?\}/,
  );
});

test('browser preview includes an auth failure scenario for rejected keys', () => {
  const source = readHarnessSource();
  const authBranch = extractScenarioBlock(
    source,
    'if (scenario === "provider-auth-failure" || scenario === "provider-auth-failure-empty") {',
    ['if (scenario === "empty") {', 'if (applyGuidedTrainingPreviewScenario(bootstrap, state)) {'],
  );

  assert.ok(authBranch, 'expected provider-auth-failure preview scenario');
  assert.match(authBranch, /modelErrorCategory: "invalid_key_or_permission"/);
  assert.match(authBranch, /status: "authentication_failed"/);
  assert.match(authBranch, /http:\/\/localhost:1234\/v1/);
  assert.doesNotMatch(authBranch, /47\.107\.101\.18|aikey\.redfast/);
  assert.match(authBranch, /key cannot be used right now/i);
  assert.match(
    authBranch,
    /if \(scenario === "provider-auth-failure-empty"\) \{[\s\S]*?bootstrap\.workspaceTrainingState = undefined;[\s\S]*?bootstrap\.memory = \{[\s\S]*?currentFocus:\s*""[\s\S]*?\};[\s\S]*?\}/,
  );
});

test('browser preview provider failure seeds keep zh-CN recovery copy distinct from English fallback', () => {
  const source = readHarnessSource();
  const failureBranch = extractScenarioBlock(
    source,
    'if (scenario === "provider-failure" || scenario === "provider-failure-empty") {',
    ['if (scenario === "provider-auth-failure" || scenario === "provider-auth-failure-empty") {'],
  );
  const authBranch = extractScenarioBlock(
    source,
    'if (scenario === "provider-auth-failure" || scenario === "provider-auth-failure-empty") {',
    ['if (scenario === "empty") {', 'if (applyGuidedTrainingPreviewScenario(bootstrap, state)) {'],
  );

  assert.ok(failureBranch, 'expected provider-failure preview scenario');
  assert.ok(authBranch, 'expected provider-auth-failure preview scenario');
  assert.match(failureBranch, /\u5f53\u524d\u6ca1\u6709\u53ef\u7528\u6a21\u578b/);
  assert.match(failureBranch, /\u5f53\u524d\u6a21\u578b\u6682\u65f6\u4e0d\u80fd\u7528/);
  assert.match(failureBranch, /\u6211\u5148\u4fee\u590d\u8fde\u63a5/);
  assert.doesNotMatch(failureBranch, /gateway|base URL/i);
  assert.match(authBranch, /\u8fd9\u7ec4\u8fde\u63a5\u6682\u65f6\u4e0d\u80fd\u7528/);
  assert.match(authBranch, /\u66f4\u65b0\u5bc6\u94a5\u540e\u91cd\u65b0\u6d4b\u8bd5/);
  assert.doesNotMatch(authBranch, /gateway|base URL/i);
});

test('browser preview localizes fixed provider labels and ready-plan fixture copy', () => {
  const source = readHarnessSource();
  const providerLabelsStart = source.indexOf('const previewProviderLabels:');
  const providerLabelsEnd = source.indexOf('function previewProviderLabel', providerLabelsStart);
  const planCopyStart = source.indexOf('const localizedConnectedPlanPreviewCopy:');
  const planCopyEnd = source.indexOf('function applyLocalizedConnectedPlanPreview', planCopyStart);

  assert.ok(providerLabelsStart >= 0 && providerLabelsEnd > providerLabelsStart);
  assert.ok(planCopyStart >= 0 && planCopyEnd > planCopyStart);

  const providerLabels = source.slice(providerLabelsStart, providerLabelsEnd);
  const planCopy = source.slice(planCopyStart, planCopyEnd);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(providerLabels, new RegExp(`"${language}":\\s*\\{`));
  }
  for (const language of ['es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(planCopy, new RegExp(`"${language}":\\s*\\{`));
  }

  assert.match(source, /previewProviderLabel\(language, "preview"\)/);
  assert.match(source, /previewProviderLabel\(state\.composerLanguage, "browser"\)/);
  assert.match(source, /applyLocalizedConnectedPlanPreview\(bootstrap, language\);/);
  assert.match(source, /currentMainThread:[\s\S]*?whyNow: copy\.whyNow/);
  assert.match(source, /acceptanceCriteria: \[\.\.\.copy\.acceptanceCriteria\]/);
});

test('browser preview keeps the connected plan preview on the locale-specific copy object', () => {
  const source = readHarnessSource();
  const connectedPlanStart = source.indexOf('function applyLocalizedConnectedPlanPreview(');
  const connectedPlanEnd = source.indexOf('type RecoveryPreviewCopy = {', connectedPlanStart);
  const connectedPlan = source.slice(connectedPlanStart, connectedPlanEnd);
  const blockedBranch = extractScenarioBlock(source, 'if (scenario === "plan-blocked") {', [
    'if (scenario === "resource-preview-loaded") {',
  ]);

  assert.ok(connectedPlan, 'expected connected plan preview function');
  assert.ok(blockedBranch, 'expected plan-blocked preview scenario');
  assert.match(connectedPlan, /currentStep:\s*copy\.nextStep/);
  assert.match(connectedPlan, /nextTrainingAction:\s*copy\.nextStep/);
  assert.match(connectedPlan, /nextAfterCurrent:\s*copy\.nextAfter/);
  assert.match(blockedBranch, /"de-DE":\s*"Die Überprüfung der aktuellen Datei unterstützt diesen Planschritt noch nicht\."/);
  assert.match(blockedBranch, /"ja-JP":\s*"現在のファイル検証では、この計画ステップはまだ対応していません。"/);
});

test('browser preview includes guided training scenarios for remote, debug, and function coaching', () => {
  const source = readHarnessSource();

  assert.match(source, /GuidedTrainingPreviewScenario/);
  assert.match(source, /const guidedTrainingPreviewScenarioAliasMap: Record<string, GuidedTrainingPreviewScenario> = \{/);
  assert.match(source, /function resolveGuidedTrainingPreviewScenarioAlias\(/);
  assert.match(source, /const requestedGuidedTrainingScenario = resolveGuidedTrainingPreviewScenarioAlias\(requestedScenario \?\? null\);/);
  assert.match(source, /applyGuidedTrainingPreviewScenario\(bootstrap, state\)/);
  assert.match(source, /guidedTrainingPreviewScenarios\.includes/);
  assert.match(source, /resolveGuidedTrainingPreviewScenarioData\(/);
  assert.doesNotMatch(source, /guidedTrainingPreviewScenarios\.find/);
  assert.match(source, /nextAfterCompletion:\s*selectedCard\.nextAfterCompletion/);
  assert.doesNotMatch(source, /Practice: Verify the remote workspace boundary/);
  assert.doesNotMatch(source, /Flash: Minimal debug loop/);
  assert.doesNotMatch(source, /Hover \/ Peek Definition/);
});

test('browser preview source keeps localized coaching copy free of private-use mojibake', () => {
  const source = readHarnessSource();

  assert.doesNotMatch(source, /[\uE000-\uF8FF]/u);
  assert.doesNotMatch(source, /\u6d93\u5b29\u7af4\u9352\u20ac/u);
  assert.match(source, /\u5148\u628a provider test \u7ed3\u679c\u548c\u7528\u6237\u771f\u5b9e\u70df\u6d4b\u8f93\u51fa\u5bf9\u6210\u4e00\u6761\u81ea\u6d3d\u7684\u5224\u65ad\u94fe\u3002/u);
});

test('browser preview protects restored provider strings and localizes transient preview states', () => {
  const source = readHarnessSource();

  assert.match(source, /import \{ sanitizeVisibleData, sanitizeVisibleText \} from "\.\/visibleText";/);
  assert.match(source, /return sanitizeVisibleData\(provider\) as PreviewProviderConfig;/);
  assert.match(source, /const trimmed = sanitizeVisibleText\(value\)\.trim\(\);/);
  assert.match(source, /\.map\(\(value\) => trimPreviewString\(value\)\)/);
  assert.match(source, /name: previewProviderLabel\(state\.composerLanguage, "browser"\)/);
  assert.match(source, /streamedContent: previewText\(/);
  assert.match(source, /\u6211\u6b63\u5728\u68c0\u67e5\u5f53\u524d\u5de5\u4f5c\u533a\u4e0a\u4e0b\u6587/);
  assert.match(source, /\u6ca1\u6709\u751f\u6210\u53ef\u7ee7\u7eed\u7684\u8bad\u7ec3\u5361/);
});

test('guided training preview defaults into the training lane with a connected provider surface', () => {
  const source = readHarnessSource();

  assert.match(
    source,
    /explicitPreviewView\s*\?\?\s*persistedActiveView\s*\?\?\s*\(\s*requestedGuidedTrainingScenario\s*\?\s*"training"\s*:\s*"coach"\s*\)/,
  );
  assert.match(source, /requestedGuidedTrainingScenario \|\| resolvedActiveView === "plan"/);
  assert.match(source, /\?\s*"connected"/);
});

test('plain training preview uses the localized guided fixture instead of the legacy demo card', () => {
  const source = readHarnessSource();

  assert.match(
    source,
    /const defaultGuidedTrainingScenario: GuidedTrainingPreviewScenario \| undefined =\s*requestedScenario === undefined && !requestedGuidedTrainingScenario && resolvedActiveView === "training"\s*\? "training-function"\s*:\s*undefined;/,
  );
  assert.match(
    source,
    /requestedGuidedTrainingScenario\s*\? requestedGuidedTrainingScenario\s*:\s*defaultGuidedTrainingScenario;/,
  );
});

test('guided training preview keeps active cards in learn-first mode', () => {
  const source = readHarnessSource();

  assert.match(
    source,
    /latestLearningFollowup:\s*selectedCard\.returnWith,\s*latestLearningVerifiedResult:\s*"",[\s\S]*?selectedCardStatus:\s*"active"/,
  );
  assert.doesNotMatch(
    source,
    /latestLearningFollowup:\s*selectedCard\.returnWith,\s*latestLearningVerifiedResult:\s*previewText\(/,
  );
});

test('browser preview applies the generic preview scenario pass only once', () => {
  const source = readHarnessSource();
  const matches = source.match(/applyPreviewScenario\(bootstrap, state\);/g) ?? [];

  assert.equal(matches.length, 1);
});

test('browser preview reapplies localized Plan copy after the generic Plan pass', () => {
  const source = readHarnessSource();
  const planPass = extractScenarioBlock(
    source,
    'if (state.activeView === "plan" && state.scenario !== "recovery") {',
    ['const guidedTrainingPreviewActive = applyGuidedTrainingPreviewScenario(bootstrap, state);'],
  );

  assert.ok(planPass, 'expected generic Plan preview pass');
  assert.match(planPass, /applyLocalizedConnectedPlanPreview\(bootstrap, language\);/);
  assert.ok(
    planPass.lastIndexOf('applyLocalizedConnectedPlanPreview(bootstrap, language);') >
      planPass.lastIndexOf('bootstrap.reviewQueueSummary ='),
    'expected localized copy to win over generic Plan fixture text',
  );
});

test('browser preview preserves scenario-owned coach seeds from the generic fallback pass', () => {
  const source = readHarnessSource();

  assert.match(source, /function scenarioOwnsCoachSeed/);
  assert.match(source, /case "rich-content":/);
  assert.match(source, /case "empty":/);
  assert.match(source, /case "workspace-admission":/);
  assert.match(source, /const preserveScenarioCoachSeed =/);
  assert.match(source, /if \(!preserveScenarioCoachSeed\) \{\s*bootstrap\.conversation =/);
  assert.match(source, /if \(state\.activeView === "coach" && !preserveScenarioCoachSeed\) \{/);
});

test('workspace admission preview localizes its next step and keeps it aligned with admission status', () => {
  const source = readHarnessSource();
  const copyStart = source.indexOf('const workspaceAdmissionPreviewCopy:');
  const copyEnd = source.indexOf('function applyPreviewScenario', copyStart);

  assert.ok(copyStart >= 0 && copyEnd > copyStart, 'expected workspace admission preview copy');
  const copy = source.slice(copyStart, copyEnd);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(copy, new RegExp(`"${language}": \\{`));
  }
  assert.match(copy, /managed: "このプロジェクトで達成したいことを教えてください。"/);
  assert.match(source, /const nextStep = copy\.nextSteps\[admissionStatus\];/);
  assert.match(source, /recommendedNextStep: nextStep,/);
  assert.match(source, /summary: admissionStatus === "managed" \? copy\.managedSummary : copy\.onboardingSummary,/);
});

test('browser preview provider override promotes configured model truth over seeded defaults', () => {
  const source = readHarnessSource();

  assert.match(source, /type PreviewProviderConfig = Partial<typeof mockBootstrapData\.providerConfig>;/);
  assert.match(
    source,
    /const resolvedModel =\s*trimPreviewString\(providerConfig\.resolvedModel\) \?\? trimPreviewString\(providerConfig\.model\);/,
  );
  assert.match(
    source,
    /const effectiveAvailableModels =\s*availableModels\.length > 0 \? availableModels : resolvedModel \? \[resolvedModel\] : \[\];/,
  );
  assert.match(source, /providerProfiles,|providerProfiles:\s*providerProfiles,/);
  assert.match(source, /modelListStatus:\s*providerConfig\.modelListStatus \?\? \(effectiveAvailableModels\.length > 0 \? "ready" : "idle"\),/);
  assert.match(
    source,
    /model:\s*bootstrap\.providerConfig\.resolvedModel\?\.trim\(\)\s*\|\|[\s\S]*?bootstrap\.providerConfig\.model\?\.trim\(\)\s*\|\|[\s\S]*?bootstrap\.connection\.provider\.model,/,
  );
});
