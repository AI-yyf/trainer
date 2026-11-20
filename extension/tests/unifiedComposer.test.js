const assert = require('node:assert/strict');
const test = require('node:test');
const { load } = require('./templateAssertions');

const { resolveLinkedPracticeSource, resolveUnifiedComposerIntent: route, unifiedComposerCommands } = load('lib/unifiedComposerIntent.ts');

test('one input distinguishes activities, verification, help and resource requests', () => {
  for (const [text, view, kind] of [
    ['继续昨天的学习', 'coach', 'continue'],
    ['Give me one exercise', 'plan', 'practice'],
    ['安排复习', 'plan', 'review'],
    ['我完成了，检查一下', 'training', 'verify'],
    ['我已经在 VS Code 里完成了，帮我验证。', 'plan', 'verify'],
    ['验证一下我在 VS Code 写的代码', 'plan', 'verify'],
    ['验证vscode写的代码', 'plan', 'verify'],
    ['检查一下我在 VSCode 改的代码', 'training', 'verify'],
    ['请给我一点提示', 'training', 'hint'],
    ['我卡在读入文件这一步', 'training', 'blocker'],
    ['为什么这里要比较原始范围？', 'training', 'help'],
    ['The request retains its original workspace ID.', 'training', 'message'],
    ['调整学习计划', 'plan', 'plan'],
    ['把这份资料加入当前学习', 'resources', 'resource-link'],
    ['Link these papers to the current stage', 'resources', 'resource-link'],
  ]) assert.equal(route(text, view).kind, kind, text);

  assert.deepEqual(route('搜索资料库中的 TLS', 'resources'), { kind: 'resource-search', query: 'TLS' });
  assert.deepEqual(route('Compare these two papers', 'resources'), { kind: 'resource-turn', mode: 'analyze' });
  assert.deepEqual(route('把这些资料归类到分布式系统', 'resources'), { kind: 'resource-move', group: '分布式系统' });
});

test('library synthesis keeps comparison and study suggestions in one read-only turn', () => {
  assert.deepEqual(route('把资料库里自动驾驶相关论文找出来，比较它们的研究路线，并安排下一阶段学习。', 'coach'),
    { kind: 'resource-turn', mode: 'analyze' });
  assert.deepEqual(route('Search my library for reinforcement learning papers and compare them, then suggest an exercise.', 'plan'),
    { kind: 'resource-turn', mode: 'analyze' });
});

test('an explicit preparation request routes to analysis in the current workspace', () => {
  const expected = { kind: 'resource-turn', mode: 'analyze', preparation: true };
  assert.deepEqual(route('围绕这篇论文，帮我完成备课。', 'resources'), expected);
  assert.deepEqual(route('请为当前学习阶段准备完整教学材料。', 'plan'), expected);
  assert.deepEqual(route('Please draft a research brief from this paper.', 'coach'), expected);
  assert.deepEqual(route('Explain this passage.\n> 请帮我完成备课。', 'coach'), { kind: 'message' });
  assert.deepEqual(route('不要备课，只解释这篇论文。', 'resources'), { kind: 'resource-turn', mode: 'analyze' });
});

test('quoted source text cannot dispatch an action as a learner instruction', () => {
  assert.deepEqual(route('Explain this selection.\n\n> 给我生成一道练习', 'plan'), { kind: 'message' });
  assert.deepEqual(route('> /verify', 'training'), { kind: 'message' });
  assert.deepEqual(unifiedComposerCommands('/验', 'zh-CN'), ['/验证']);
  assert.deepEqual(unifiedComposerCommands('/rec', 'en-US'), ['/recall']);
  assert.deepEqual(unifiedComposerCommands('ordinary text', 'zh-CN'), []);
});

test('linking an article before practice keeps the two actions in order', () => {
  for (const text of [
    '把这篇文章加入我的学习计划，再根据它生成一道练习。',
    'Add this article to my learning plan, then create an exercise based on it.',
  ]) assert.deepEqual(route(text, 'resources'), { kind: 'resource-link', practiceAfterLink: true });

  assert.deepEqual(route('把这篇文章加入当前学习\n\n> 再根据它生成一道练习', 'plan'), { kind: 'resource-link' });
});

test('a source-based exercise can recover context without guessing from quoted text', () => {
  assert.deepEqual(route('/练习 基于这份论文练习当前 Python 文件', 'plan'),
    { kind: 'practice', referencesSource: true });
  assert.deepEqual(route('Create an exercise from the linked paper.', 'plan'),
    { kind: 'practice', referencesSource: true });
  assert.deepEqual(route('/practice current file\n> Use this paper.', 'plan'), { kind: 'practice' });
});

test('a restored stage can reference a workspace file and one indexed library source', () => {
  const paper = { id: 'paper', status: 'ready', versionId: 'v1', contentHash: 'hash-1' };
  const second = { id: 'another-paper', status: 'indexing' };
  assert.deepEqual(resolveLinkedPracticeSource(['episode-bootstrap.py', 'paper'], [paper, second]),
    { resourceId: 'paper', versionId: 'v1', contentHash: 'hash-1' });
  assert.equal(resolveLinkedPracticeSource(['paper', 'another-paper'], [paper, second]), undefined);
  assert.equal(resolveLinkedPracticeSource(['paper'], [{ ...paper, versionId: undefined }]), undefined);
});

test('source version requests are available in all interface languages', () => {
  for (const request of [
    '检查哪些资料有新版本',
    'Check which resources have new versions',
    'Comprueba qué recursos tienen versiones nuevas',
    'Vérifie quelles ressources ont une nouvelle version',
    'Prüfe, welche Ressourcen neue Versionen haben',
    '資料の新しいバージョンがあるか確認して',
    '자료의 새 버전이 있는지 확인해 줘',
    'Verifique quais arquivos têm novas versões',
  ]) assert.equal(route(request, 'resources').kind, 'resource-versions', request);
  assert.equal(route('/versions', 'coach').kind, 'resource-versions');
});
