// The stage line shown while the coach waits on a tool must say what is actually happening. A
// `project_read` of the learner's file used to read "正在检索资料" (Searching resources), which is
// both vague and wrong: the coach is looking at a file in the project. Product contract §5 names
// "正在查看 `xxx.py`" as the kind of real progress a learner should see within two seconds.
const test = require('node:test');
const assert = require('node:assert/strict');

const { load } = require('./templateAssertions');

const { currentTrainerStage, trainerStageLabel } = load('lib/trainerStage.ts');
const PRODUCT_LANGUAGES = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

test('a running project read names the file being looked at', () => {
  for (const [language, expected] of [
    ['zh-CN', '正在查看 app.py'],
    ['en-US', 'Reading app.py'],
  ]) {
    const stage = currentTrainerStage(
      [{ name: 'project_read', status: 'running', args: { action: 'read', path: 'app.py' } }],
      language,
    );
    assert.equal(stage.kind, 'retrieve');
    assert.equal(stage.label, expected);
  }
});

test('only the file name is shown, never a folder path', () => {
  const stage = currentTrainerStage(
    [
      {
        name: 'project_read',
        status: 'running',
        args: { action: 'symbol', path: 'src/payments/retry.py' },
      },
    ],
    'zh-CN',
  );
  assert.equal(stage.label, '正在查看 retry.py');
});

test('a read that has finished no longer pins the stage to its file', () => {
  const stage = currentTrainerStage(
    [{ name: 'project_read', status: 'succeeded', args: { action: 'read', path: 'app.py' } }],
    'zh-CN',
  );
  assert.equal(stage.label, '正在检索资料');
});

test('retrievals without a single file keep the generic label', () => {
  for (const activity of [
    { name: 'library_read', status: 'running', args: { action: 'search', query: '幂等' } },
    { name: 'project_read', status: 'running', args: { action: 'modules' } },
    { name: 'project_read', status: 'running' },
    { name: 'project_verify', status: 'running', args: { action: 'verify_practice', path: 'app.py' } },
    { name: 'web_fetch', status: 'running', args: { action: 'fetch', url: 'https://example.com' } },
  ]) {
    assert.equal(currentTrainerStage([activity], 'zh-CN').label, '正在检索资料', JSON.stringify(activity));
    assert.equal(currentTrainerStage([activity], 'en-US').label, 'Searching resources');
  }
});

test('the inspect-file label exists in every product language with a file placeholder', () => {
  const seen = new Set();
  for (const language of PRODUCT_LANGUAGES) {
    const label = trainerStageLabel('inspect_file', language);
    assert.match(String(label), /\{file\}/, language);
    assert.equal(String(label).includes('{file}{file}'), false, language);
    seen.add(label);
  }
  assert.equal(seen.size, PRODUCT_LANGUAGES.length);
});
