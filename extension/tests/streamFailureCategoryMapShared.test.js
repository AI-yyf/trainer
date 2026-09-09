'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const {
  buildTrainerStreamingErrorMessage,
} = require('../dist/shared/src/protocol.js');

/**
 * Matrix (smoke) categories ↔ Coach UI copy — keep one-to-one for acceptance.
 * Live-only gaps (real 429 storm, full per-protocol trainer-turn) stay out of this table.
 */
const MATRIX_TO_UI = [
  ['authentication_failed', /API key|Settings|权限|设置/i],
  ['invalid_key_or_permission', /API key|permission|Settings|权限|设置/i],
  ['rate_limit', /429|Rate limited|限流|稍等/i],
  ['timeout', /too long|太久|稍后再试/i],
  ['empty_stream', /empty stream|空流|草稿/i],
  ['nonempty_sse_no_visible_content', /without visible|没有可见|草稿/i],
  ['invalid_json', /valid JSON|有效 JSON|草稿/i],
  ['provider_request_failed_training_card', /Training card generation failed|训练卡生成|草稿/i],
  ['incomplete_stream', /cut off|截断|重试/i],
  ['stream_aborted_by_client', /stopped|中止|草稿/i],
  ['provider_capability_test_failed', /capability check|能力检查|Settings|设置/i],
  ['streaming_contract_failed', /contract|契约|Retry|重试/i],
  ['empty_response', /empty reply|空回复/i],
];

test('matrix failure categories map to explainable Coach UI copy', () => {
  for (const [category, expect] of MATRIX_TO_UI) {
    const en = buildTrainerStreamingErrorMessage('en-US', category, category);
    const zh = buildTrainerStreamingErrorMessage('zh-CN', category, category);
    assert.match(en, expect, `en-US missing for ${category}: ${en}`);
    assert.match(zh, expect, `zh-CN missing for ${category}: ${zh}`);
    assert.doesNotMatch(en, /sk-|api[_-]?key\s*=/i);
    assert.doesNotMatch(zh, /sk-|api[_-]?key\s*=/i);
  }
});
