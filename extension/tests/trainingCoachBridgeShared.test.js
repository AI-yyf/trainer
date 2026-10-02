'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildTrainingCoachBridge,
  composeTrainingCoachBridgeDraft,
} = require('../dist/extension/src/core/trainingCoachBridge.js');

test('buildTrainingCoachBridge reports a completed practice result back to coach', () => {
  const bridge = buildTrainingCoachBridge({
    language: 'en-US',
    taskTitle: 'Recover response_model through one route',
    focusArea: 'response_model',
    latestVerifiedResult: 'The focused route test now passes.',
    successSignal: 'One focused route check passes.',
    returnWith: 'Bring back the verification output and one open question.',
    learnerDeliverables: ['Implement one route slice yourself.'],
    verificationSteps: ['Run one focused route verification.'],
    reviewStatus: 'resolved',
  });

  assert.equal(bridge.mode, 'report_result');
  assert.match(bridge.title, /Bring/i);
  assert.match(bridge.prompt, /The focused route test now passes/i);
  assert.match(bridge.prompt, /coach-only/i);
  assert.match(bridge.detail, /verification result/i);
  assert.ok(
    bridge.summaryLines.some((line) => /verification result/i.test(line)),
    'expected verification summary line',
  );
});

test('buildTrainingCoachBridge brings blockers back to coach when the loop is stuck', () => {
  const bridge = buildTrainingCoachBridge({
    language: 'en-US',
    taskTitle: 'Recover response_model through one route',
    focusArea: 'response_model',
    latestLearningFollowup: 'Bring back the exact blocker.',
    reviewBlocker: 'The route still fails because the response model shape is wrong.',
    reviewPartialProgress: 'The route body was narrowed to one file.',
    reviewStatus: 'active',
  });

  assert.equal(bridge.mode, 'unstick');
  assert.match(bridge.prompt, /current blocker/i);
  assert.match(bridge.prompt, /response model shape is wrong/i);
  assert.match(bridge.detail, /diagnose/i);
  assert.ok(
    bridge.summaryLines.some((line) => /Current blocker/i.test(line)),
    'expected blocker summary line',
  );
});

test('buildTrainingCoachBridge keeps zh summary lines aligned with zh status copy', () => {
  const bridge = buildTrainingCoachBridge({
    language: 'zh-CN',
    taskTitle: '实现一个 response_model 路由切片',
    focusArea: 'response_model',
    latestVerifiedResult: '目标模型已返回，聚焦测试通过。',
    successSignal: '目标模型已返回，聚焦测试通过。',
    returnWith: '聚焦测试输出、响应载荷，以及你实际改动的路由文件',
    learnerDeliverables: ['你亲手改动过的路由切片'],
    verificationSteps: ['运行聚焦测试'],
    reviewStatus: 'resolved',
  });

  assert.equal(bridge.mode, 'report_result');
  assert.match(bridge.title, /带回教练/);
  assert.ok(
    bridge.summaryLines.some((line) => /验证结果：目标模型已返回，聚焦测试通过。/.test(line)),
    'expected zh verification summary line',
  );
  assert.ok(
    bridge.summaryLines.every((line) => !/Route returns the expected model/i.test(line)),
    'zh summary lines should not leak english status copy',
  );
  assert.ok(
    bridge.summaryLines.every((line) => line.length <= 72),
    'coach summary lines should stay compact for the sidebar',
  );
});

test('buildTrainingCoachBridge compacts long result-return guidance into coach-readable lines', () => {
  const bridge = buildTrainingCoachBridge({
    language: 'en-US',
    taskTitle: 'Recover response_model through one route',
    focusArea: 'response_model',
    latestVerifiedResult:
      'The focused route test now passes and the returned shape finally matches the governed response contract.',
    successSignal: 'Route returns the expected model and the focused test passes.',
    returnWith:
      'Bring back the focused test output, the response payload, and one open question about whether this should become plan evidence or flash reinforcement.',
    reviewStatus: 'resolved',
  });

  assert.ok(bridge.title.length <= 54);
  assert.ok(bridge.detail.length <= 86);
  assert.ok(bridge.summaryLines.every((line) => line.length <= 72));
});

test('buildTrainingCoachBridge includes explicit flash card identity in training returns', () => {
  const bridge = buildTrainingCoachBridge({
    language: 'en-US',
    cardId: 'flash-depends-boundary',
    cardType: 'flash',
    cardTitle: 'Depends boundary recall',
    taskTitle: 'Depends boundary recall',
    focusArea: 'Depends boundary',
    latestVerifiedResult: 'I can now explain when Depends belongs in the route.',
    reviewStatus: 'resolved',
  });

  assert.equal(bridge.mode, 'report_result');
  assert.equal(bridge.trainingReturn?.cardId, 'flash-depends-boundary');
  assert.equal(bridge.trainingReturn?.cardType, 'flash');
  assert.equal(bridge.trainingReturn?.cardTitle, 'Depends boundary recall');
  assert.equal(bridge.trainingReturn?.returnMode, 'result');
});

test('composeTrainingCoachBridgeDraft sends the complete prompt without shortened sidebar summaries', () => {
  const draft = composeTrainingCoachBridgeDraft({
    title: 'Bring "response_model" back to coach',
    prompt:
      'Keep coaching around "response_model" and stay coach-only. Do not edit code for me.',
    detail:
      'Let the coach judge whether this was a pass, partial pass, downgrade, plan evidence, or flash reinforcement.',
    summaryLines: [
      'Verification result: The focused route test now passes.',
      'Bring back: One verification output and one open question.',
    ],
  });

  assert.match(draft, /Keep coaching around "response_model"/i);
  assert.doesNotMatch(draft, /Verification result:|Bring back:|Bring "response_model"/);
});


test('card requirements alone never become a completed training result', () => {
  const bridge = buildTrainingCoachBridge({
    language: 'zh-CN', cardId: 'tuple-flash', cardType: 'flash', cardTitle: '元组引用',
    successSignal: '解释列表可变、元组绑定不变。', returnWith: '带回运行结果。',
  });
  assert.equal(bridge.mode, 'continue_task');
  assert.equal(bridge.trainingReturn, undefined);
  assert.doesNotMatch(bridge.prompt, /已经完成|按要求带回的是/);
});

test('submitted answers return as submissions without claimed verification', () => {
  const bridge = buildTrainingCoachBridge({
    language: 'zh-CN', cardId: 'tuple-flash', cardType: 'flash', cardTitle: '元组引用',
    successSignal: '解释列表可变、元组绑定不变。', returnWith: '带回运行结果。',
    latestSubmittedResult: 'append 合法，替换元素会抛出 TypeError。',
  });
  assert.equal(bridge.mode, 'report_result');
  assert.match(bridge.prompt, /我的提交是：\s+append 合法/);
  assert.match(bridge.prompt, /这张卡要求带回的内容是：带回运行结果/);
  assert.doesNotMatch(bridge.prompt, /已经完成|按要求带回的是/);
  assert.equal(bridge.trainingReturn.summary, 'append 合法，替换元素会抛出 TypeError。');
  assert.equal(bridge.trainingReturn.verifiedResult, undefined);
});

test('return drafts preserve multiline submitted code exactly once without claiming verification', () => {
  const answer = '```python\ntry:\n    pair[1] = 9\nexcept TypeError:\n    print("expected")\n```';
  const bridge = buildTrainingCoachBridge({
    language: 'zh-CN', cardTitle: '元组引用', latestSubmittedResult: answer,
  });
  const draft = composeTrainingCoachBridgeDraft(bridge);
  assert.ok(draft.includes(answer));
  assert.equal(draft.split(answer).length - 1, 1);
  assert.doesNotMatch(draft, /验证结果：|已经完成|coach-only/);
});

test('verified returns also carry the complete submission and reflection', () => {
  const answer = '```python\nassert pair[0] == [1, 2, 4]\n```';
  const reflection = '位置赋值触发 TypeError，append 修改内层 list。\nbefore: ([1, 2], 3)\nafter: ([1, 2, 4], 3)';
  for (const language of ['zh-CN', 'en-US']) {
    const draft = composeTrainingCoachBridgeDraft(buildTrainingCoachBridge({
      language, cardId: 'tuple-boundary', cardType: 'practice', cardTitle: 'Tuple boundary',
      latestVerifiedResult: 'Executable checks passed: ruff, pyright, pytest.',
      latestSubmittedResult: answer, reflection, reviewStatus: 'resolved',
    }));
    assert.ok(draft.includes(answer));
    assert.ok(draft.includes(reflection));
    assert.equal(draft.split(reflection).length - 1, 1);
    assert.match(draft, /Executable checks passed/);
  }
});
