'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  describeCoachToolActivitySendBusy,
  describeCoachThinkingSendBusy,
} = require('../dist/shared/src/coachToolActivitySendState.js');

test('tool-call busy send state names the running tool', () => {
  const zh = describeCoachToolActivitySendBusy('zh-CN', [
    { name: 'search_resources', status: 'running' },
  ]);
  const en = describeCoachToolActivitySendBusy('en-US', [
    { name: 'search_resources', status: 'running' },
  ]);
  assert.match(zh, /正在调用工具：搜索资料/);
  assert.match(en, /Calling tool: search resources/i);
  assert.match(zh, /发送暂不可用/);
  assert.match(en, /send paused/i);
});

test('tool failure busy send state stays explainable', () => {
  const zh = describeCoachToolActivitySendBusy('zh-CN', [
    { name: 'debug_loop', status: 'failed' },
  ]);
  assert.match(zh, /工具失败：调试闭环/);
  assert.match(zh, /重试/);
});

test('thinking-only busy send state is distinct from tool-call', () => {
  assert.equal(describeCoachToolActivitySendBusy('zh-CN', []), undefined);
  assert.match(describeCoachThinkingSendBusy('zh-CN'), /正在思考/);
  assert.match(describeCoachThinkingSendBusy('en-US'), /Thinking/);
});
