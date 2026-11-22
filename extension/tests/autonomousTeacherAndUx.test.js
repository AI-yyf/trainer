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
});
