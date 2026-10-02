'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { generateSkillDraftCommand } = require('../dist/extension/src/commands/skillCommands');

function contextFor(postJson) {
  const messages = [];
  const logs = [];
  return { messages, logs, context: {
    getHostState: () => ({ bootstrap: { memory: { workspace: { responseLanguage: 'zh-CN' } } } }),
    trustGuard: { ensureTrusted: async () => true },
    providerStore: { getConfig: () => ({ model: 'test-model' }), getApiKey: async () => 'fixture-key' },
    sidecarManager: { ensureRunning: async () => ({ lifecycle: 'ready', port: 8765 }) },
    sidecarClient: { postJson },
    workbench: { postMessage: async message => messages.push(message) },
    outputChannel: { appendLine: line => logs.push(line) },
  } };
}

test('native skill draft forwards saved connection and returns matching acknowledgement', async () => {
  const draft = { trigger: '$check', title: '检查', detail: '检查提交', prompt: '检查当前提交', source: 'model' };
  const { context, messages } = contextFor(async (port, route, payload, options) => {
    assert.equal(port, 8765);
    assert.equal(route, '/provider/skill-draft');
    assert.equal(payload.api_key, 'fixture-key');
    assert.equal(payload.response_language, 'zh-CN');
    assert.equal(payload.description, '检查 Python');
    assert.equal(options.timeoutMs, 55000);
    return draft;
  });
  assert.equal((await generateSkillDraftCommand(context, { requestId: 'skill-test-1', description: ' 检查 Python ' })).ok, true);
  assert.deepEqual(messages, [{ type: 'skills/draftResult', payload: { requestId: 'skill-test-1', ok: true, draft } }]);
});

test('native skill failure acknowledges the request without exposing upstream secrets', async () => {
  const { context, messages, logs } = contextFor(async () => { throw new Error('fixture-secret-key'); });
  assert.equal((await generateSkillDraftCommand(context, { requestId: 'skill-fail', description: '检查 Python' })).ok, false);
  assert.equal(messages[0].payload.requestId, 'skill-fail');
  assert.equal(messages[0].payload.ok, false);
  assert.equal(JSON.stringify({ messages, logs }).includes('fixture-secret-key'), false);
});

test('native skill draft refuses untrusted workspace before requesting credentials or model', async () => {
  const { context, messages } = contextFor(async () => assert.fail('must not call model'));
  context.trustGuard.ensureTrusted = async () => false;
  context.providerStore.getApiKey = async () => assert.fail('must not request key');
  assert.equal((await generateSkillDraftCommand(context, { requestId: 'skill-untrusted', description: '检查 Python' })).ok, false);
  assert.equal(messages[0].payload.ok, false);
});

test('skill command palette entry opens settings without starting a model request', async () => {
  const { context, messages } = contextFor(async () => assert.fail('must not call model'));
  let shown = false;
  context.workbench.show = async () => { shown = true; };
  assert.equal((await generateSkillDraftCommand(context)).ok, true);
  assert.equal(shown, true);
  assert.deepEqual(messages, [{ type: 'ui/restoreView', payload: { activeView: 'settings' } }]);
});
