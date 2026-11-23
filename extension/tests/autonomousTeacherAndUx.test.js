'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const repoRoot = path.resolve(__dirname, '..', '..');
const resourceCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'resourceCommands.js',
);
const workbenchDataModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchData.js',
);
const { createDefaultBootstrapData } = require(workbenchDataModulePath);

test('brand logos contain zero green-teal hues and no star polygon, PNGs are valid', () => {
  const svgPaths = [
    path.join(repoRoot, 'extension', 'media', 'trainer.svg'),
    path.join(repoRoot, 'extension', 'media', 'trainer-icon.svg'),
    path.join(repoRoot, 'extension', 'webview', 'public', 'favicon.svg'),
    path.join(repoRoot, 'extension', 'webview', 'src', 'assets', 'branding', 'trainer-mark.svg'),
    path.join(repoRoot, 'browser-extension', 'icons', 'trainer-capture.svg'),
  ];
  for (const svgPath of svgPaths) {
    const raw = fs.readFileSync(svgPath, 'utf8');
    assert.doesNotMatch(raw, /#009d9a|#24cecc/i, `Legacy teal found in ${svgPath}`);
    assert.doesNotMatch(raw, /<polygon/i, `Star polygon found in ${svgPath}`);
  }
  const pngBytes = fs.readFileSync(path.join(repoRoot, 'extension', 'media', 'trainer-icon.png'));
  assert.deepEqual(Array.from(pngBytes.subarray(0, 4)), [0x89, 0x50, 0x4e, 0x47]);
});

test('exportResourceCommand requests ?format=pdf and writes PDF bytes to chosen path', async () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-pdf-export-'));
  const targetFile = path.join(tempDir, 'brief.pdf');
  const getBytesCalls = [];
  const writtenFiles = [];
  const { exportResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, {
    window: {
      showSaveDialog: async () => ({ fsPath: targetFile, scheme: 'file' }),
    },
    workspace: {
      fs: {
        writeFile: async (uri, buf) => {
          writtenFiles.push({ path: uri.fsPath, buf });
          fs.writeFileSync(uri.fsPath, buf);
        },
      },
    },
  });

  const context = {
    trustGuard: { ensureTrusted: async () => true },
    getHostState: () => ({
      workspace: { activeWorkspaceRoot: tempDir, remoteName: undefined },
      bootstrap: {
        resources: [{ id: 'res-pdf-1', title: 'World Models Brief', kind: 'markdown' }],
      },
    }),
    getSessionId: () => 'sess-pdf-1',
    getWorkspaceId: () => 'ws-pdf-1',
    sidecarManager: { ensureRunning: async () => ({ lifecycle: 'ready', port: 4555 }) },
    sidecarClient: {
      getBytes: async (port, reqPath) => {
        getBytesCalls.push({ port, reqPath });
        return {
          bytes: Buffer.from('%PDF-1.7 mock pdf content'),
          filename: 'World Models Brief.pdf',
        };
      },
    },
  };

  const result = await exportResourceCommand(context, {
    resource_id: 'res-pdf-1',
    format: 'pdf',
  });

  assert.equal(result.ok, true);
  assert.equal(getBytesCalls.length, 1);
  assert.match(getBytesCalls[0].reqPath, /format=pdf/);
  assert.equal(writtenFiles.length, 1);
  assert.ok(fs.readFileSync(targetFile).subarray(0, 5).equals(Buffer.from('%PDF-')));
});

test('uploadResourceCommand supports workspace selective quick-pick import without touching source files', async (t) => {
  const projectDir = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-ws-pick-'));
  t.after(() => fs.rmSync(projectDir, { recursive: true, force: true }));
  const fileA = path.join(projectDir, 'README.md');
  const fileB = path.join(projectDir, 'app.py');
  fs.writeFileSync(fileA, '# Project README\n', 'utf8');
  fs.writeFileSync(fileB, 'print("hi")\n', 'utf8');

  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: projectDir },
    {
      name: 'Local Compatible',
      baseUrl: 'http://127.0.0.1:1234/v1',
      apiKeyRef: 'trainer.default',
      model: 'demo-model',
      capabilities: {},
    },
    { lifecycle: 'ready', host: '127.0.0.1', port: 4556, canStart: true },
  );

  const uploadedBodies = [];
  const { uploadResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, {
    workspace: {
      workspaceFolders: [{ uri: { fsPath: projectDir } }],
      findFiles: async () => [
        { fsPath: fileA, scheme: 'file' },
        { fsPath: fileB, scheme: 'file' },
      ],
    },
    window: {
      showQuickPick: async (items) => [items.find((entry) => entry.label === 'README.md')],
    },
  });

  const context = {
    trustGuard: { ensureTrusted: async () => true },
    getHostState: () => ({
      workspace: { activeWorkspaceRoot: projectDir, workspaceFolder: projectDir, remoteName: undefined },
      bootstrap,
    }),
    getSessionId: () => 'sess-ws-pick',
    getWorkspaceId: () => 'ws-pick-1',
    sidecarManager: { ensureRunning: async () => ({ lifecycle: 'ready', port: 4556 }) },
    sidecarClient: {
      postJson: async (_port, route, body) => {
        if (route === '/resource/upload') {
          uploadedBodies.push(body);
          return {
            id: `res-${uploadedBodies.length}`,
            workspace_id: 'ws-pick-1',
            kind: body.kind,
            name: body.name,
            title: body.name,
            status: 'ready',
            source: body.source,
            source_type: body.source_type,
          };
        }
        return { id: 'res-1', status: 'ready' };
      },
      getJson: async () => ({ memory: { recent_summary: 'Workspace selection imported.' } }),
    },
    patchWorkbenchData: async () => {},
  };

  const result = await uploadResourceCommand(context, { mode: 'workspace' });
  assert.equal(result.ok, true);
  assert.equal(uploadedBodies.length, 1);
  assert.equal(uploadedBodies[0].name, 'README.md');
  assert.equal(fs.readFileSync(fileA, 'utf8'), '# Project README\n');
  assert.equal(fs.readFileSync(fileB, 'utf8'), 'print("hi")\n');
});

test('autonomous workspace path forwarding, streaming composer queue, and settings fixes stay wired', () => {
  const sessionCommands = fs.readFileSync(
    path.join(repoRoot, 'extension', 'src', 'commands', 'sessionCommands.ts'),
    'utf8',
  );
  const composerSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'composer', 'CoachComposer.tsx'),
    'utf8',
  );
  const appSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'app', 'App.tsx'),
    'utf8',
  );
  const snapshotSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'src', 'core', 'workspaceFileSnapshot.ts'),
    'utf8',
  );

  assert.match(sessionCommands, /workspace_path:\s*getRuntimeWorkspaceContext\(context\)\.canonicalProjectPath/);
  assert.match(snapshotSource, /LIST_LIMIT_LOCAL = 300;/);
  assert.match(snapshotSource, /INCLUDE_GLOB = '\*\*\/\*';/);
  assert.match(composerSource, /const areActionsDisabled = disabled;/);
  assert.match(composerSource, /queueBanner\?: ReactNode;/);
  assert.match(appSource, /queuedFollowUps/);
  assert.match(appSource, /onQueueSubmit=/);
  assert.match(appSource, /providerToolsExplicitlyUnsupported/);
  assert.match(appSource, /onImportWorkspace=/);
  assert.match(appSource, /sanitizeBogusLearningStep/);
});

test('uploadResourceCommand files uploads into requested targetFolder using set_group', async (t) => {
  const projectDir = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-folder-import-'));
  t.after(() => fs.rmSync(projectDir, { recursive: true, force: true }));
  const docFile = path.join(projectDir, 'spec.md');
  fs.writeFileSync(docFile, '# API Spec\n', 'utf8');

  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: projectDir },
    {
      name: 'Local Compatible',
      baseUrl: 'http://127.0.0.1:1234/v1',
      apiKeyRef: 'trainer.default',
      model: 'demo-model',
      capabilities: {},
    },
    { lifecycle: 'ready', host: '127.0.0.1', port: 4557, canStart: true },
  );

  const organizeCalls = [];
  const { uploadResourceCommand } = loadWithVscodeMock(resourceCommandsModulePath, {
    window: {
      showOpenDialog: async () => [{ fsPath: docFile, scheme: 'file' }],
    },
  });

  const context = {
    trustGuard: { ensureTrusted: async () => true },
    getHostState: () => ({
      workspace: { activeWorkspaceRoot: projectDir, workspaceFolder: projectDir, remoteName: undefined },
      bootstrap,
    }),
    getSessionId: () => 'sess-folder-import',
    getWorkspaceId: () => 'ws-folder-import',
    sidecarManager: { ensureRunning: async () => ({ lifecycle: 'ready', port: 4557 }) },
    sidecarClient: {
      postJson: async (_port, route, body) => {
        if (route === '/resource/upload') {
          return {
            id: 'res-folder-1',
            workspace_id: 'ws-folder-import',
            kind: body.kind,
            name: body.name,
            title: body.name,
            status: 'ready',
            source: body.source,
          };
        }
        if (route === '/resource/organize') {
          organizeCalls.push(body);
          return {
            id: body.resource_id,
            workspace_id: 'ws-folder-import',
            name: 'spec.md',
            title: 'spec.md',
            status: 'ready',
            collection_path: 'API/spec.md',
          };
        }
        return { id: 'res-folder-1', status: 'ready' };
      },
      getJson: async () => ({ memory: { recent_summary: 'Imported into folder API.' } }),
    },
    patchWorkbenchData: async () => {},
  };

  const result = await uploadResourceCommand(context, { mode: 'files', targetFolder: 'API' });
  assert.equal(result.ok, true);
  assert.equal(organizeCalls.length, 1);
  assert.equal(organizeCalls[0].action, 'set_group');
  assert.equal(organizeCalls[0].group, 'API');
});

test('settings capabilities dirty-check, Finder resources tree, and learning step sanitizer stay intact', () => {
  const settingsSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'settings', 'CoachSettingsView.tsx'),
    'utf8',
  );
  const resourcesSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'resources', 'ResourcesWorkbenchView.tsx'),
    'utf8',
  );
  const learningSummarySource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'lib', 'learningSummary.ts'),
    'utf8',
  );

  assert.match(settingsSource, /function providerCapabilitiesKey/);
  assert.match(settingsSource, /providerCapabilitiesKey\(providerDraft\.capabilities/);
  assert.match(settingsSource, /应用推荐能力/);
  assert.doesNotMatch(resourcesSource, /data-library-folders/);
  assert.match(resourcesSource, /mergeLibraryFolderTrees/);
  assert.match(resourcesSource, /mode:\s*"rename-resource"/);
  assert.match(resourcesSource, /resources-finder-bar/);
  assert.match(learningSummarySource, /export function sanitizeBogusLearningStep/);
  assert.match(learningSummarySource, /CASUAL_GREETING_TOKENS/);
});

test('all 37 registered backend tools have 8-locale TOOL_LABELS and UX settings/resources polish stays intact', () => {
  const toolsSource = fs.readFileSync(
    path.join(repoRoot, 'server', 'app', 'llm', 'tools.py'),
    'utf8',
  );
  const stripCopySource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'lib', 'i18n', 'segments', 'agentActivityStripCopy.ts'),
    'utf8',
  );
  const settingsSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'settings', 'CoachSettingsView.tsx'),
    'utf8',
  );
  const resourcesInlineSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'lib', 'i18n', 'segments', 'resourcesInlineText.ts'),
    'utf8',
  );

  const registeredTools = Array.from(
    toolsSource.matchAll(/ToolDefinition\(\s*name="([a-z0-9_]+)"/g),
    (m) => m[1],
  );
  assert.ok(registeredTools.length >= 37, `Expected >= 37 tools, got ${registeredTools.length}`);
  const locales = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
  const toolLabelsIdx = stripCopySource.indexOf('export const TOOL_LABELS');
  assert.ok(toolLabelsIdx >= 0);
  const toolLabelsBlock = stripCopySource.slice(toolLabelsIdx);

  for (const toolName of registeredTools) {
    const start = toolLabelsBlock.indexOf(`  ${toolName}: {`);
    assert.ok(start >= 0, `Missing TOOL_LABELS entry for ${toolName}`);
    const end = toolLabelsBlock.indexOf('  },', start);
    const slice = toolLabelsBlock.slice(start, end);
    for (const locale of locales) {
      assert.match(slice, new RegExp(`"${locale}":\\s*"[^"]+"`), `${toolName} missing locale ${locale}`);
    }
  }

  assert.match(settingsSource, /const CAPABILITY_VERDICT_LABELS/);
  assert.match(settingsSource, /settings-token-presets-panel/);

  // Verify every ResourceTextKey in resourceText is translated across all 6 override locales
  const resourceTextStart = resourcesInlineSource.indexOf('export const resourceText:');
  const overridesStart = resourcesInlineSource.indexOf('export const resourceTextLocaleOverrides:');
  assert.ok(resourceTextStart >= 0 && overridesStart > resourceTextStart);
  const baseBlock = resourcesInlineSource.slice(resourceTextStart, overridesStart);
  const overridesBlock = resourcesInlineSource.slice(overridesStart);
  const resourceKeys = Array.from(
    baseBlock.matchAll(/^\s{2}([A-Za-z0-9_]+):\s*\{/gm),
    (m) => m[1],
  );
  assert.ok(resourceKeys.length >= 150, `Expected >= 150 resource keys, got ${resourceKeys.length}`);
  for (const locale of ['es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const locStart = overridesBlock.indexOf(`"${locale}": {`);
    assert.ok(locStart >= 0, `Missing override block for ${locale}`);
    const nextLocMatch = overridesBlock.slice(locStart + 10).match(/\r?\n\s{2}"(?:es-ES|fr-FR|de-DE|ja-JP|ko-KR|pt-BR)":\s*\{|\r?\n\};/);
    const locEnd = nextLocMatch ? locStart + 10 + nextLocMatch.index : overridesBlock.length;
    const locSlice = overridesBlock.slice(locStart, locEnd);
    for (const key of resourceKeys) {
      assert.match(locSlice, new RegExp(`\\b${key}:`), `resourcesInlineText ${locale} missing key ${key}`);
    }
  }
});

test('shared training card, review queue, and coach bridge helpers return 8-locale non-English text', () => {
  const { buildTrainingCoachBridge } = require('../dist/shared/src/trainingCoachBridge.js');
  const { summarizeTrainingScenarioPack } = require('../dist/shared/src/trainingCardCopy.js');
  const { summarizeReviewQueueTruth } = require('../dist/shared/src/reviewQueueGovernance.js');

  for (const locale of ['es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    const bridge = buildTrainingCoachBridge({
      language: locale,
      cardId: 'card-1',
      taskTitle: 'Router contract',
      cardTitle: 'Check response_model',
      latestVerifiedResult: 'pytest passed',
    });
    assert.equal(bridge.mode, 'report_result');
    assert.notEqual(bridge.ctaLabel, 'Bring result to Coach');
    assert.notEqual(bridge.title, 'Verified result ready to return to Coach');

    const packLabel = summarizeTrainingScenarioPack(locale, 'debug_loop');
    assert.ok(packLabel);
    assert.notEqual(packLabel, 'Minimal debug loop');

    const queue = summarizeReviewQueueTruth(
      [{ concept: 'response_model', reason: 'weakness', source: 'weakness', fsrsState: 'review', intervalDays: 3, retrievability: 0.85, dueAt: '2026-11-25T10:00:00Z' }],
      undefined,
      locale,
    );
    assert.ok(queue && queue.headline);
    assert.ok(queue.detail);
    assert.ok(queue.meta.length >= 2);
    assert.doesNotMatch(queue.detail, /Estimated retrievability/);
  }
});

test('library folder rename/delete commands sync workbench resources and v1.6.3 UX guards hold', async () => {
  const libraryFolderCommandsPath = path.resolve(
    __dirname,
    '..',
    'dist',
    'extension',
    'src',
    'commands',
    'libraryFolderCommands.js',
  );
  const {
    libraryFoldersRenameCommand,
    libraryFoldersDeleteCommand,
  } = loadWithVscodeMock(libraryFolderCommandsPath, {});

  const patches = [];
  const getPaths = [];
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: '/ws/project' },
    {
      name: 'MiniMax',
      baseUrl: 'https://api.minimaxi.com/v1',
      apiKeyRef: 'trainer.minimax',
      model: 'MiniMax-M3.1-Flash',
      capabilities: { chat: true, tools: true, thinking: true },
    },
    { lifecycle: 'ready', host: '127.0.0.1', port: 4588, canStart: true },
  );

  const mockContext = {
    trustGuard: { ensureTrusted: async () => true },
    sidecarManager: { ensureRunning: async () => ({ lifecycle: 'ready', port: 4588 }) },
    sidecarClient: {
      postJson: async () => ({ ok: true, moved_resource_count: 1 }),
      deleteJson: async () => ({ ok: true, recoverable: true }),
      getJson: async (_port, reqPath) => {
        getPaths.push(reqPath);
        if (reqPath.startsWith('/library/groups')) {
          return {
            managed_root: 'Trainer Library',
            exists: true,
            total_resource_count: 1,
            groups: [{ path: 'InfraDocs', name: 'InfraDocs', resource_count: 1 }],
          };
        }
        return {
          memory: {
            recent_summary: 'Folder synchronized.',
            resources: [
              {
                id: 'res-sync-1',
                name: 'world-model.md',
                title: 'world-model.md',
                kind: 'markdown',
                status: 'ready',
                collection_path: 'InfraDocs/world-model.md',
              },
            ],
          },
        };
      },
    },
    workbench: { postMessage: async () => {} },
    getSessionId: () => 'sess-folder-sync',
    getWorkspaceId: () => 'ws-folder-sync',
    getHostState: () => ({
      bootstrap,
      workspace: { workspaceFolder: '/ws/project', activeWorkspaceRoot: '/ws/project' },
    }),
    patchWorkbenchData: async (nextData) => {
      patches.push(nextData);
    },
  };

  const renameResult = await libraryFoldersRenameCommand(mockContext, {
    operationId: 'op-rename-sync',
    path: 'WorldModels',
    new_path: 'InfraDocs',
  });
  assert.equal(renameResult.ok, true);
  assert.ok(getPaths.some((p) => p.startsWith('/library/groups')));
  assert.ok(getPaths.some((p) => p.startsWith('/memory/summary')));
  assert.equal(patches.length, 1);
  assert.equal(patches[0].resources[0].collectionPath, 'InfraDocs/world-model.md');

  const deleteResult = await libraryFoldersDeleteCommand(mockContext, {
    operationId: 'op-delete-sync',
    path: 'InfraDocs',
  });
  assert.equal(deleteResult.ok, true);
  assert.equal(patches.length, 2);

  const workbenchStateSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'app', 'useWorkbenchState.ts'),
    'utf8',
  );
  const settingsViewSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'settings', 'CoachSettingsView.tsx'),
    'utf8',
  );
  const folderRowCss = fs.readFileSync(
    path.join(
      repoRoot,
      'extension',
      'webview',
      'src',
      'styles',
      'sections',
      'resources-workbench-w1-collapsesection-collections-row.css',
    ),
    'utf8',
  );

  assert.match(workbenchStateSource, /beginOptimisticStream:/);
  assert.match(settingsViewSource, /settings-thinking-intensity/);
  const coachBubbleSource = fs.readFileSync(
    path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'coach', 'CoachMessageBubble.tsx'),
    'utf8',
  );
  const quietSurfaceCss = fs.readFileSync(
    path.join(
      repoRoot,
      'extension',
      'webview',
      'src',
      'styles',
      'sections',
      'surface-materials-document-column-hairline-chrome-crafted-disclosure.css',
    ),
    'utf8',
  );
  assert.match(coachBubbleSource, /message-bubble__assistant-rail--with-activity/);
  assert.match(
    quietSurfaceCss,
    /\.coach-conversation-view--quiet-surface \.message-bubble__assistant-rail:not\(\.message-bubble__assistant-rail--with-activity\)/,
  );
  assert.match(
    folderRowCss,
    /\.collapse-section__header-row:hover \.resources-finder-folder-actions/,
  );
});
