const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');
const { generateStageMaterialCommand } = loadWithVscodeMock(
  path.resolve(__dirname, '../dist/extension/src/commands/stageMaterialCommands.js'),
  { workspace: { workspaceFolders: [] }, window: {} },
);
const item = { id: 'material-1', planStageId: 'stage-1', kind: 'code_examples', title: '代码',
  summary: '运行两段代码', content: '```python\nif True:\n    print(1)\n```', generationSource: 'model' };
function fixture(postJson) {
  const messages = [], logs = [], patches = [];
  const state = { workspace: {}, bootstrap: { plan: { id: 'plan-1' },
    stageMaterials: { 'stage-2': [{ ...item, planStageId: 'stage-2' }] },
    memory: { workspace: { responseLanguage: 'zh-CN' } } } };
  return { messages, logs, patches, state, context: {
    getHostState: () => state,
    getSessionId: () => 'session-1',
    trustGuard: { ensureTrusted: async () => true },
    sidecarManager: { ensureRunning: async () => ({ lifecycle: 'ready', port: 8765 }) },
    providerStore: { getConfig: () => ({ model: 'saved-model' }), getApiKey: async () => 'fixture-key' },
    sidecarClient: { postJson }, outputChannel: { appendLine: line => logs.push(line) },
    patchWorkbenchData: async patch => patches.push(patch),
    workbench: { postMessage: async message => messages.push(message) },
  } };
}
test('stage generation forwards saved credentials/language and retains other stage materials', async () => {
  const { context, patches, messages } = fixture(async (port, route, payload, options) => {
    assert.equal(payload.provider.model, 'saved-model'); assert.equal(payload.api_key, 'fixture-key');
    assert.equal(payload.response_language, 'zh-CN'); assert.equal(payload.workspace_id, 'workspace-default');
    assert.equal(payload.session_id, 'session-1'); assert.equal(options.timeoutMs, 100000);
    return { materials: [item] };
  });
  assert.equal((await generateStageMaterialCommand(context, { planId: 'plan-1', stageId: 'stage-1' })).ok, true);
  assert.equal(Object.keys(patches[0].stageMaterials).length, 2);
  assert.equal(patches[0].stageMaterials['stage-1'][0].content, item.content);
  assert.deepEqual(messages[0], { type: 'stageMaterials/settled', payload: {
    workspaceId: 'workspace-default', planId: 'plan-1', stageId: 'stage-1' } });
});
test('failure and empty result release the matching stage without exposing upstream details', async () => {
  for (const response of [async () => { throw new Error('secret-fixture'); }, async () => ({ materials: [] })]) {
    const { context, messages, logs, patches } = fixture(response);
    const result = await generateStageMaterialCommand(context, { planId: 'plan-1', stageId: 'stage-1' });
    assert.equal(result.ok, false); assert.equal(messages[0].payload.stageId, 'stage-1');
    assert.equal(patches.length, 0); assert.equal(JSON.stringify({ result, messages, logs }).includes('secret-fixture'), false);
  }
});
test('late results do not contaminate a replacement plan', async () => {
  const f = fixture(async () => { f.state.bootstrap.plan.id = 'plan-2'; return { materials: [item] }; });
  const result = await generateStageMaterialCommand(f.context, { planId: 'plan-1', stageId: 'stage-1' });
  assert.equal(result.cancelled, true); assert.equal(f.patches.length, 0);
});
test('template fallback is identified instead of claiming a complete model generation', async () => {
  const { context } = fixture(async () => ({ materials: [{ ...item, generationSource: 'template' }] }));
  const result = await generateStageMaterialCommand(context, { planId: 'plan-1', stageId: 'stage-1' });
  assert.match(result.message, /模板/); assert.doesNotMatch(result.message, /已生成/);
});
