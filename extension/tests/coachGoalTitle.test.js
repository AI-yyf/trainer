'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');

const tsPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'coachGoalTitle.ts');
const tsc = path.resolve(__dirname, '..', 'node_modules', 'typescript', 'bin', 'tsc');
let helper;

test('setup', () => {
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coach-goal-title-'));
  execFileSync(process.execPath, [
    tsc, tsPath, '--outDir', outDir, '--module', 'commonjs',
    '--target', 'es2022', '--skipLibCheck', '--declaration', 'false',
  ]);
  helper = require(path.join(outDir, 'coachGoalTitle.js'));
});

test('uses the preceding user turn, not the assistant reply', () => {
  const conversation = [
    { id: 'u1', role: 'user', body: '我想真正学会实现 PPO' },
    { id: 'a1', role: 'assistant', body: '好的，我们从一个最小实现开始。' },
  ];
  assert.equal(helper.goalTitleFromConversation(conversation, 'a1'), '我想真正学会实现 PPO');
});

test('falls back to the reply only when no user turn exists', () => {
  const conversation = [{ id: 'a1', role: 'assistant', body: '## 当前学习目标\n先实现 PPO Clip' }];
  assert.equal(helper.goalTitleFromConversation(conversation, 'a1'), '当前学习目标');
});

test('strips markdown lead-in and bounds the title', () => {
  const conversation = [
    { id: 'u1', role: 'user', body: '> - 系统学习强化学习\n第二行' },
  ];
  assert.equal(helper.goalTitleFromConversation(conversation, 'u1'), '系统学习强化学习');
  const long = 'x'.repeat(200);
  assert.equal(helper.goalTitleFromConversation([{ id: 'u1', role: 'user', body: long }], 'u1').length, 80);
});
