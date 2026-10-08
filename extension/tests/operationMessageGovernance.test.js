'use strict';

// Behavior tests for the pure operation-message governance module
// (extension/webview/src/lib/operationMessageGovernance.ts), extracted from
// App.tsx in the controller-split round. These lock the already-shipped
// semantics so later moves cannot drift them:
//   - surface attribution: explicit surface wins; plan revision-conflict and
//     live-plan gate markers auto-scope to "plan" even from generic callers;
//     everything else (provider/settings domain included) stays "global".
//   - failure sanitization: only error-tone messages are rewritten; known
//     local recovery copy and structured plan markers survive verbatim,
//     everything else collapses to the generic operation recovery line.
// The 5-second self-dismiss timer for non-error banners remains an App-side
// effect; a source assertion below pins it.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const test = require('node:test');

const webviewNodeModules = path.resolve(__dirname, '..', 'webview', 'node_modules');
if (!process.env.NODE_PATH?.split(path.delimiter).includes(webviewNodeModules)) {
  process.env.NODE_PATH = process.env.NODE_PATH
    ? `${webviewNodeModules}${path.delimiter}${process.env.NODE_PATH}`
    : webviewNodeModules;
  Module._initPaths();
}

const typescript = require(path.join(webviewNodeModules, 'typescript'));
const governancePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'operationMessageGovernance.ts',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function loadGovernance() {
  const previousLoader = Module._extensions['.ts'];
  Module._extensions['.ts'] = (loadedModule, filename) => {
    const { outputText } = typescript.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: {
        module: typescript.ModuleKind.CommonJS,
        target: typescript.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
      fileName: filename,
    });
    loadedModule._compile(outputText, filename);
  };
  try {
    return require(governancePath);
  } finally {
    if (previousLoader === undefined) {
      delete Module._extensions['.ts'];
    } else {
      Module._extensions['.ts'] = previousLoader;
    }
    delete require.cache[governancePath];
  }
}

const governance = loadGovernance();

test('generic completion notices localize without changing errors or specific operation facts', () => {
  const marker = '[[trainer-operation-completed]]';
  const languages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
  const completion = { tone: 'success', message: marker, providerTest: { ok: false } };
  const original = structuredClone(completion);
  const copies = languages.map(language => governance.operationStatusMessageText(completion, language));
  assert.equal(new Set(copies).size, 8);
  assert.equal(copies[0], '操作已完成。');
  assert.equal(copies[1], 'Action completed.');
  for (const copy of copies) assert.doesNotMatch(copy, /\[\[|Trainer action completed/);
  assert.deepEqual(completion, original);
  for (const language of languages) {
    assert.equal(governance.operationStatusMessageText({ tone: 'error', message: marker }, language), marker);
    assert.equal(governance.operationStatusMessageText({ tone: 'success', message: 'Saved, but connection verification failed.' }, language), 'Saved, but connection verification failed.');
    assert.equal(governance.operationStatusMessageText({ tone: 'info', message: marker }, language), marker);
  }
});

test('rejected scope changes explain that the action did not run in all eight languages', () => {
  const languages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
  const copies = new Set();
  for (const language of languages) {
    const result = governance.sanitizeOperationFailureMessage({
      tone: 'error', message: '[[trainer-operation-scope-changed]] hidden host detail',
    }, language);
    assert.equal(result.message, governance.operationScopeChangedMessage(language));
    assert.ok(result.message.length > 20);
    assert.ok(!result.message.includes('[['));
    assert.ok(!result.message.includes('hidden host detail'));
    assert.equal(governance.resolveOperationMessageSurface(result.message), 'global');
    copies.add(result.message);
  }
  assert.equal(copies.size, 8);
  assert.equal(governance.detectOperationScopeChanged('an ordinary provider failure'), false);
});

test('surface attribution: explicit surface wins over plan markers', () => {
  assert.equal(
    governance.resolveOperationMessageSurface('[[trainer-plan-revision-conflict:7]] ', 'resources'),
    'resources',
  );
  assert.equal(
    governance.resolveOperationMessageSurface('[[trainer-live-plan-task-gate:no_live]]', 'training'),
    'training',
  );
});

test('surface attribution: plan conflict and live-plan gate markers auto-scope to plan', () => {
  assert.equal(
    governance.resolveOperationMessageSurface('[[trainer-plan-revision-conflict:12]] body'),
    'plan',
  );
  assert.equal(
    governance.resolveOperationMessageSurface('[[trainer-plan-revision-conflict]] body'),
    'plan',
  );
  assert.equal(
    governance.resolveOperationMessageSurface('[[trainer-live-plan-task-gate:no_live]] body'),
    'plan',
  );
  assert.equal(
    governance.resolveOperationMessageSurface('[[trainer-live-plan-task-gate:leftover]] body'),
    'plan',
  );
});

test('surface attribution: provider/settings domain calls without an explicit surface stay global', () => {
  // These are the exact shapes the provider/settings save-test flows emit —
  // no explicit surface, no plan marker, so the banner stays global.
  assert.equal(
    governance.resolveOperationMessageSurface('连接还没有通过。请检查服务地址、API key 和模型名称，然后再试一次。'),
    'global',
  );
  assert.equal(governance.resolveOperationMessageSurface('Coach settings saved.'), 'global');
  assert.equal(governance.resolveOperationMessageSurface(undefined), 'global');
});

test('plan revision conflict detection extracts the revision for the localized message', () => {
  assert.deepEqual(governance.detectPlanRevisionConflict('[[trainer-plan-revision-conflict:42]] x'), {
    revision: '42',
  });
  assert.deepEqual(governance.detectPlanRevisionConflict('[[trainer-plan-revision-conflict]] x'), {
    revision: '?',
  });
  assert.equal(governance.detectPlanRevisionConflict('no marker here'), undefined);
});

test('live-plan gate marker accepts only the governed kinds', () => {
  assert.equal(governance.parseLivePlanTaskGateMarker('[[trainer-live-plan-task-gate:no_live]]'), 'no_live');
  assert.equal(governance.parseLivePlanTaskGateMarker('[[trainer-live-plan-task-gate:LEFTOVER]]'), 'leftover');
  assert.equal(governance.parseLivePlanTaskGateMarker('[[trainer-live-plan-task-gate:other]]'), undefined);
});

test('failure sanitization leaves non-error messages untouched', () => {
  const message = { tone: 'info', message: 'Coach settings saved.' };
  assert.deepEqual(governance.sanitizeOperationFailureMessage(message, 'zh-CN'), message);
});

test('failure sanitization rewrites plan conflicts into the localized plan message', () => {
  const sanitized = governance.sanitizeOperationFailureMessage(
    { tone: 'error', message: '[[trainer-plan-revision-conflict:9]] stale payload' },
    'zh-CN',
  );
  assert.equal(sanitized.tone, 'error');
  assert.equal(sanitized.message, '计划已被另一个窗口修改（当前版本 9）。请刷新后重试，系统已阻止覆盖。');
});

test('failure sanitization rewrites live-plan gates into the localized plan message', () => {
  const sanitized = governance.sanitizeOperationFailureMessage(
    { tone: 'error', message: '[[trainer-live-plan-task-gate:no_live]] x' },
    'en-US',
  );
  assert.match(sanitized.message, /No live plan is bound/);
});

test('failure sanitization keeps known local recovery copy verbatim and collapses unknown errors', () => {
  const known = '还没连上模型。检查一下设置，再试一次。';
  assert.equal(
    governance.sanitizeOperationFailureMessage({ tone: 'error', message: known }, 'zh-CN').message,
    known,
  );
  const unknown = 'Some raw host error nobody should read';
  assert.equal(
    governance.sanitizeOperationFailureMessage({ tone: 'error', message: unknown }, 'zh-CN').message,
    '这一步暂时没完成。再试一次。',
  );
});

test('App keeps the 5-second self-dismiss for non-error banners (error stays until closed)', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(
    source,
    /if \(!operationMessage \|\| operationMessage\.tone === "error"\) \{\s*return;\s*\}\s*const timer = window\.setTimeout\(\(\) => dismissOperationMessage\(\), 5000\);/,
  );
});

test('App delegates surface attribution and sanitization to the governance module', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  assert.match(
    source,
    /setOperationMessageSurface\(\s*resolveOperationMessageSurface\(message\?\.message, surface\),\s*\)/,
  );
  assert.match(
    source,
    /setRawOperationMessage\(\s*message \? sanitizeOperationFailureMessage\(message, layout\.composerLanguage\) : undefined,\s*\)/,
  );
  // The union type now lives in the governance module; App imports it.
  const moduleSource = fs.readFileSync(governancePath, 'utf8');
  assert.match(
    moduleSource,
    /export type OperationMessageSurface = "global" \| "training" \| "plan" \| "resources";/,
  );
});

const { load } = require('./templateAssertions');
const { attestationDeliveryNotice, resolveOperationMessageSurface, ATTESTATION_UNDELIVERED_MARKER } = load('lib/operationMessageGovernance.ts');

test('uncertain attestation delivery is localized to Training in all eight languages', () => {
  const messages = new Set();
  for (const language of ['zh-CN','en-US','es-ES','fr-FR','de-DE','ja-JP','ko-KR','pt-BR']) {
    const notice = attestationDeliveryNotice(`${ATTESTATION_UNDELIVERED_MARKER} hidden transport detail`, language);
    assert.equal(notice.surface, 'training');
    assert.ok(notice.message.length > 15);
    assert.ok(!notice.message.includes('hidden transport detail'));
    assert.ok(!notice.message.includes(ATTESTATION_UNDELIVERED_MARKER));
    messages.add(notice.message);
  }
  assert.equal(messages.size, 8);
});

test('ordinary status cannot acquire attestation uncertainty or a Training scope', () => {
  for (const text of ['', 'Tests passed', 'Verification failed', 'Connection lost', 'Self-reported success']) {
    assert.equal(attestationDeliveryNotice(text, 'en-US'), undefined);
  }
});

test('uncertain delivery keeps operation identity and never guarantees a missing write or successful replay', () => {
  const operation = { tone: 'error', message: `${ATTESTATION_UNDELIVERED_MARKER} ambiguous timeout`,
    requestId: 'verify-request', workspaceId: 'current-workspace', sessionId: 'current-session', cardId: 'current-card' };
  const sanitized = governance.sanitizeOperationFailureMessage(operation, 'en-US');
  assert.equal(sanitized.requestId, operation.requestId);
  assert.equal(sanitized.workspaceId, operation.workspaceId);
  assert.equal(sanitized.sessionId, operation.sessionId);
  assert.equal(sanitized.cardId, operation.cardId);
  assert.match(sanitized.message, /not been confirmed as saved/);
  assert.doesNotMatch(sanitized.message, /did not reach|again to record|ambiguous timeout/);
});

test('operation notices resolve each new owner without inheriting a prior surface', () => {
  assert.equal(resolveOperationMessageSurface({ message: 'Upload complete', resourceOperation: true }), 'resources');
  assert.equal(resolveOperationMessageSurface({ message: 'Revision conflict', planStateFailure: true }), 'plan');
  assert.equal(resolveOperationMessageSurface({ message: 'Validation error', explicitSurface: 'training' }), 'training');
  assert.equal(resolveOperationMessageSurface({ message: 'Later global notice' }), 'global');
  assert.equal(resolveOperationMessageSurface({ explicitSurface: 'plan' }), 'global');
  assert.equal(resolveOperationMessageSurface({ message: ATTESTATION_UNDELIVERED_MARKER, explicitSurface: 'resources' }), 'training');
});

test('a refused verification target is a localized Training notice, even with another explicit surface', () => {
  const marker = '[[trainer-training-verification-target-mismatch]]';
  const messages = new Set();
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const operation = { requestId: 'request-owned', commandId: 'trainer.remote.verifyActiveFile', targetId: 'scenario',
      tone: 'error', message: marker + ' hidden raw host detail' };
    const sanitized = governance.sanitizeOperationFailureMessage(operation, language);
    assert.equal(sanitized.message, governance.trainingVerificationTargetMismatchMessage(language));
    assert.equal(sanitized.requestId, operation.requestId);
    assert.equal(sanitized.commandId, operation.commandId);
    assert.equal(sanitized.targetId, operation.targetId);
    assert.equal(governance.resolveOperationMessageSurface(operation.message, 'global'), 'training');
    assert.doesNotMatch(sanitized.message, /\[\[|hidden raw host detail|workspace or conversation|工作区或会话/);
    messages.add(sanitized.message);
  }
  assert.equal(messages.size, 8);
  assert.equal(governance.detectTrainingVerificationTargetMismatch('ordinary error'), false);
  assert.match(governance.trainingVerificationTargetMismatchMessage('en-US'), /Verification was not started/);
});
