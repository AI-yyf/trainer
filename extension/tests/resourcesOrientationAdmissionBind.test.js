// Product contract §4 (zero-interception cold start): a learner may start talking right away, and is
// guided — with one click — to bind a learning folder only the first time something must be saved.
// Before this, the Resources page of an un-admitted workspace offered "导入资料" as its one action,
// although that import cannot succeed until the workspace is admitted; the click only produced the
// host's refusal. The orientation now names the real blocker and offers the one action that moves the
// workspace forward: choose a learning folder, add the current project, or choose the project folder.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  deriveAdmissionBindOrientation,
  deriveResourcesOrientation,
} = require('../dist/shared/src/resourcesOrientationGovernance.js');

const PRODUCT_LANGUAGES = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

function orientation(admission, extra = {}) {
  return deriveResourcesOrientation({
    resourceCount: 0,
    language: 'zh-CN',
    admission,
    ...extra,
  });
}

test('without a learning folder the one action is choosing it, not an import that cannot succeed', () => {
  const record = orientation(deriveAdmissionBindOrientation({ status: 'root-missing', language: 'zh-CN' }));

  assert.equal(record.state, 'needs_setup');
  assert.equal(record.primaryAction, 'bind_learning_folder');
  assert.equal(record.admissionStep, 'choose_learning_folder');
  assert.equal(record.primaryActionLabel, '选择学习文件夹');
  assert.match(record.why, /学习文件夹/);
  assert.equal(record.nextStep, '选好后再回来导入资料。');
  assert.doesNotMatch(record.primaryActionLabel, /工作区|根目录/);
});

test('the binding step follows the admission status', () => {
  const step = (status, projectPath) =>
    deriveAdmissionBindOrientation({ status, projectPath, language: 'zh-CN' });

  assert.equal(step('root-missing', '/repo').step, 'choose_learning_folder');
  assert.equal(step('root-missing', '/repo').primaryActionLabel, '选择学习文件夹');

  const found = step('project-found', '/repo');
  assert.equal(found.step, 'add_current_project');
  assert.equal(found.primaryActionLabel, '把当前项目加入 Trainer');
  assert.equal(found.why, '先决定 Trainer 如何配合这个项目，才能导入资料。');

  const unresolved = step('project-found', '  ');
  assert.equal(unresolved.step, 'choose_project_folder');
  assert.equal(unresolved.primaryActionLabel, '选择项目文件夹');

  for (const status of ['browse', 'ignored']) {
    assert.equal(step(status, '/repo').step, 'add_current_project', status);
  }
});

test('a managed or unknown admission leaves the orientation alone', () => {
  for (const status of ['managed', '', undefined, 'something-new']) {
    assert.equal(deriveAdmissionBindOrientation({ status, projectPath: '/repo', language: 'zh-CN' }), undefined, String(status));
  }

  const managed = orientation(undefined);
  assert.equal(managed.primaryAction, 'import_resource');
  assert.equal(managed.primaryActionLabel, '导入资料');
  assert.equal(managed.admissionStep, undefined);
});

test('resources that already exist do not hide the binding action', () => {
  const record = orientation(deriveAdmissionBindOrientation({ status: 'browse', language: 'zh-CN' }), {
    resourceCount: 3,
    selectedResourceId: 'r1',
    selectedResourceTitle: 'Notes',
    indexState: 'indexed',
  });

  assert.equal(record.primaryAction, 'bind_learning_folder');
  assert.equal(record.admissionStep, 'add_current_project');
});

test('every product language carries its own binding copy', () => {
  const labels = new Set();
  const reasons = new Set();
  for (const language of PRODUCT_LANGUAGES) {
    const choose = deriveAdmissionBindOrientation({ status: 'root-missing', language });
    const add = deriveAdmissionBindOrientation({ status: 'project-found', projectPath: '/repo', language });
    const pick = deriveAdmissionBindOrientation({ status: 'project-found', projectPath: ' ', language });
    for (const value of [choose, add, pick]) {
      for (const field of ['why', 'primaryActionLabel', 'nextStep']) {
        assert.ok(value[field].trim().length > 0, `${language} ${field}`);
        assert.equal(/[{}]/.test(value[field]), false, `${language} ${field} keeps a placeholder`);
      }
    }
    assert.notEqual(choose.primaryActionLabel, add.primaryActionLabel, language);
    assert.notEqual(add.primaryActionLabel, pick.primaryActionLabel, language);
    labels.add(choose.primaryActionLabel);
    reasons.add(choose.why);
  }
  assert.equal(labels.size, PRODUCT_LANGUAGES.length);
  assert.equal(reasons.size, PRODUCT_LANGUAGES.length);
});
