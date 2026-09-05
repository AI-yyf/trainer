'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const workspaceAuthorityModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'workspaceAuthority.js',
);

test('describeWorkspaceAuthoritySummary surfaces the active root and core sovereignty facts', () => {
  const { describeWorkspaceAuthoritySummary } = require(workspaceAuthorityModulePath);

  const summary = describeWorkspaceAuthoritySummary(
    {
      activeWorkspaceRoot: 'H:\\trainer_final',
      rootUri: 'file:///H:/trainer_final',
      authoritySource: 'workspace_authority_service',
      remoteName: 'ssh-remote+devbox',
      authorityMode: 'level_apply',
      permissionLevel: 'APPLY',
      permissionLabel: 'Apply',
      allowedOperations: ['read', 'list', 'search', 'read', 'write', 'delete'],
      ledgerEntryCount: 12,
      checkpointCount: 4,
      trashRoot: 'H:\\trainer_final\\trash',
    },
    'en-US',
  );

  assert.equal(summary.hasWorkspaceRoot, true);
  assert.equal(summary.root, 'H:\\trainer_final');
  assert.equal(summary.permission, 'Apply');
  assert.equal(summary.permissionDetail, 'level_apply');
  assert.equal(summary.source, 'workspace_authority_service');
  assert.match(summary.rootDetail, /rootUri: file:\/\/\/H:\/trainer_final/);
  assert.match(summary.rootDetail, /source: workspace_authority_service/);
  assert.match(summary.sourceDetail, /remote: ssh-remote\+devbox/);
  assert.equal(summary.allowedOperationsText, 'Read / List / Search / Write / Delete');
  assert.equal(summary.countsText, '12 / 4');
  assert.equal(summary.trashDetail, 'trash: H:\\trainer_final\\trash');
  assert.equal(summary.summaryText, 'H:\\trainer_final · Apply · workspace_authority_service');
});

test('describeWorkspaceAuthoritySummary compacts mounted sources and accepts mountPoints aliases', () => {
  const { describeWorkspaceAuthoritySummary } = require(workspaceAuthorityModulePath);

  const summary = describeWorkspaceAuthoritySummary(
    {
      activeWorkspaceRoot: 'H:\\trainer_final',
      permissionLabel: 'Inspect',
      mountPoints: ['workspace-notes', 'remote-specs', 'remote-specs'],
    },
    'en-US',
  );

  assert.equal(summary.mountedSourceCount, 2);
  assert.deepEqual(summary.mountedSources, ['workspace-notes', 'remote-specs']);
  assert.equal(summary.mountedSourcesText, '2 mounted sources');
  assert.equal(summary.mountedSourcesDetail, 'workspace-notes | remote-specs');
});

test('describeWorkspaceAuthoritySummary defaults the source to workspace authority when rooted', () => {
  const { describeWorkspaceAuthoritySummary } = require(workspaceAuthorityModulePath);

  const summary = describeWorkspaceAuthoritySummary(
    {
      activeWorkspaceRoot: 'H:\\trainer_final',
      permissionLabel: 'Inspect',
    },
    'en-US',
  );

  assert.equal(summary.source, 'workspace_authority_service');
  assert.match(summary.rootDetail, /source: workspace_authority_service/);
  assert.equal(summary.summaryText, 'H:\\trainer_final · Inspect · workspace_authority_service');
});

test('describeWorkspaceAuthoritySummary preserves a separately reported remote identity without adding local detail', () => {
  const { describeWorkspaceAuthoritySummary } = require(workspaceAuthorityModulePath);
  const remoteName = `ssh-remote+${'lab-'.repeat(48)}host`;

  const remoteSummary = describeWorkspaceAuthoritySummary(
    {
      activeWorkspaceRoot: 'H:\\trainer_final',
      authoritySource: 'workspace_authority_service',
      remoteName,
      permissionLabel: 'Inspect',
    },
    'en-US',
  );
  const localSummary = describeWorkspaceAuthoritySummary(
    {
      activeWorkspaceRoot: 'H:\\trainer_final',
      authoritySource: 'workspace_authority_service',
      permissionLabel: 'Inspect',
    },
    'en-US',
  );

  assert.equal(remoteSummary.source, 'workspace_authority_service');
  assert.equal(remoteSummary.sourceDetail, `remote: ${remoteName}`);
  assert.equal(localSummary.sourceDetail, '');
});

test('describeWorkspaceAuthoritySummary falls back cleanly when the workspace is not configured', () => {
  const { describeWorkspaceAuthoritySummary } = require(workspaceAuthorityModulePath);

  const summary = describeWorkspaceAuthoritySummary({}, 'zh-CN');

  assert.equal(summary.hasWorkspaceRoot, false);
  assert.equal(summary.root, '');
  assert.equal(summary.permission, '未配置');
  assert.equal(summary.source, '未知来源');
  assert.equal(summary.allowedOperationsText, '');
  assert.equal(summary.trashDetail, '');
  assert.equal(summary.nextSafeAction, '先打开或连接工作区根目录，再让我读取边界并决定下一步。');
});

test('describeWorkspaceAuthoritySummary can fall back to sandbox state roots', () => {
  const { describeWorkspaceAuthoritySummary } = require(workspaceAuthorityModulePath);

  const summary = describeWorkspaceAuthoritySummary(
    {
      workspaceRootFallback: 'H:\\trainer_final\\sandbox-root',
      trashRootFallback: 'H:\\trainer_final\\trash',
      permissionLabel: 'Inspect',
    },
    'en-US',
  );

  assert.equal(summary.hasWorkspaceRoot, true);
  assert.equal(summary.root, 'H:\\trainer_final\\sandbox-root');
  assert.equal(summary.trashRoot, 'H:\\trainer_final\\trash');
  assert.equal(summary.permission, 'Inspect');
});

test('describeWorkspaceAuthoritySummary localizes non-canonical mixed permission badges from allowed operations', () => {
  const { describeWorkspaceAuthoritySummary } = require(workspaceAuthorityModulePath);

  const summary = describeWorkspaceAuthoritySummary(
    {
      activeWorkspaceRoot: '/workspace/.trainer-sandbox',
      permissionLevel: 'read_write',
      permissionLabel: 'Read / write',
      allowedOperations: ['read', 'write', 'preview', 'refresh'],
    },
    'zh-CN',
  );

  assert.equal(summary.permission, '读取 / 写入');
});
