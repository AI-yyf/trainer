'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  classifyResourceFailure,
  describeResourceFailureState,
} = require('../dist/extension/src/core/resourceFailureExplainability.js');

test('classifyResourceFailure maps smoke bad_file / no_content', () => {
  assert.equal(
    classifyResourceFailure({
      indexStatus: 'failed',
      qualityFlags: ['no_content'],
    }),
    'no_content',
  );
  assert.equal(
    classifyResourceFailure({
      message: 'bad_file: empty content, no usable content',
      indexStatus: 'failed',
    }),
    'bad_file',
  );
});

test('classifyResourceFailure maps missing HTTP 400/404', () => {
  assert.equal(
    classifyResourceFailure({
      statusCode: 400,
      message: 'Source path does not exist',
    }),
    'missing',
  );
  assert.equal(
    classifyResourceFailure({
      statusCode: 404,
      message: 'The selected resource could not be found.',
    }),
    'missing',
  );
});

test('classifyResourceFailure maps sidecar_down from offline and ECONNREFUSED', () => {
  assert.equal(
    classifyResourceFailure({
      connectionState: 'offline',
      message: 'Sidecar request failed (500).',
    }),
    'sidecar_down',
  );
  assert.equal(
    classifyResourceFailure({
      message: 'connect ECONNREFUSED 127.0.0.1:8765',
    }),
    'sidecar_down',
  );
  assert.equal(
    classifyResourceFailure({
      message: 'Sidecar is unavailable.',
    }),
    'sidecar_down',
  );
});

test('classifyResourceFailure maps corrupt_pdf and generic index_failed', () => {
  assert.equal(
    classifyResourceFailure({
      message: 'corrupt PDF: invalid xref table',
      indexStatus: 'failed',
    }),
    'corrupt_pdf',
  );
  assert.equal(
    classifyResourceFailure({
      indexStatus: 'failed',
      qualityFlags: ['corrupt_pdf'],
    }),
    'corrupt_pdf',
  );
  assert.equal(
    classifyResourceFailure({
      indexStatus: 'failed',
    }),
    'index_failed',
  );
  assert.equal(classifyResourceFailure({ message: 'something odd' }), 'unknown');
});

test('describeResourceFailureState is honest for four smoke categories in zh/en', () => {
  const cases = [
    {
      category: 'bad_file',
      zh: /没有可用内容|索引失败/,
      en: /no usable content|Indexing failed/i,
    },
    {
      category: 'missing',
      zh: /找不到|不存在/,
      en: /not found/i,
    },
    {
      category: 'sidecar_down',
      zh: /sidecar/,
      en: /sidecar|unreachable/i,
    },
    {
      category: 'no_content',
      zh: /没有可用内容/,
      en: /no usable content/i,
    },
  ];

  for (const row of cases) {
    const zh = describeResourceFailureState('zh-CN', row.category);
    const en = describeResourceFailureState('en-US', row.category);
    assert.equal(zh.tone, 'error');
    assert.equal(en.tone, 'error');
    assert.match(zh.message, row.zh);
    assert.match(en.message, row.en);
    assert.doesNotMatch(zh.message, /可用了|已就绪|成功导入/);
    assert.doesNotMatch(en.message, /available now|ready to use|imported successfully/i);
  }
});

test('classifyResourceFailure maps search_failed and describe keeps search copy', () => {
  assert.equal(
    classifyResourceFailure({
      message: 'Resource search timed out.',
    }),
    'search_failed',
  );
  assert.equal(
    classifyResourceFailure({
      message: 'Failed to search resources: sidecar unavailable',
    }),
    'sidecar_down',
  );
  const zh = describeResourceFailureState('zh-CN', 'search_failed');
  const en = describeResourceFailureState('en-US', 'search_failed');
  assert.match(zh.message, /搜索失败/);
  assert.match(en.message, /search failed/i);
  assert.doesNotMatch(zh.message, /暂时无法搜索资料，请稍后重试/);
});
