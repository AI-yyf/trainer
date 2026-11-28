// Restored behavioral regression test. Original file: extension/tests/providerQuota.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Quota diagnosis in streaming and connection recovery for every UI language.
//
// Restoration: partial - 1 of 2 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "P0 redirect: quota exhaustion stays a hard-blocking category for real failures, while a historical quota test result is only a diagnostic warning"
//       fails at HEAD: isCoachProviderBlockingCategory is not a function
// Target: compiled shared modules (extension/dist/shared/src).
// Note: 1 kept test definition expands to one test per UI language at runtime.

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
