const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '../dist/shared/src');
const { providerErrorHint, describeProviderSendState, isCoachProviderBlockingCategory } = require(path.join(root, 'providerStatus.js'));
const { buildTrainerStreamingErrorMessage } = require(path.join(root, 'protocol.js'));

for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
  test(`${language}: explicit quota diagnosis wins over HTTP 403 in streaming and connection recovery`, () => {
    const hint = providerErrorHint({ modelErrorCategory: 'quota_exhausted' }, language);
    assert.ok(hint);
    assert.equal(buildTrainerStreamingErrorMessage(language, 'HTTP 403 Forbidden', 'quota_exhausted'), hint);
    assert.notEqual(hint, providerErrorHint({ modelErrorCategory: 'invalid_key_or_permission' }, language));
    if (language !== 'en-US') {
      assert.notEqual(hint, providerErrorHint({ modelErrorCategory: 'quota_exhausted' }, 'en-US'));
    }
  });
}

test('P0 redirect: quota exhaustion stays a hard-blocking category for real failures, while a historical quota test result is only a diagnostic warning', () => {
  // Real request failures with this category keep blocking recovery paths.
  assert.equal(isCoachProviderBlockingCategory('quota_exhausted'), true);
  // A *historical* failed test no longer gates sending: the state stays ready
  // with a non-blocking warning so the first real send is the proof.
  const state = describeProviderSendState({
    configured: true, apiKeyConfigured: true, model: 'model', baseUrl: 'https://example.test',
    availableModels: ['model'], modelListStatus: 'ready', modelErrorCategory: 'quota_exhausted',
    lastTestResult: { ok: false, errorCategory: 'quota_exhausted', retryable: false, model: 'model', baseUrl: 'https://example.test' },
  }, 'en-US');
  assert.equal(state.blocked, false);
  assert.equal(state.status, 'ready');
  assert.match(state.warning ?? '', /quota/i);
});
