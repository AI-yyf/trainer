// Restored behavioral regression test. Original file: extension/tests/autonomousTeacherAndUx.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Resource export (?format=pdf) and workspace-selective upload import commands.
//
// Restoration: partial - 3 of 9 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "brand logos contain zero green-teal hues and no star polygon, PNGs are valid"
//       asset guard: inspects branding SVG/PNG files (not extension-host behaviour).
//   - "autonomous workspace path forwarding, streaming composer queue, and settings fixes stay wired"
//       fails at HEAD: The input did not match the regular expression /onImportWorkspace=/. Input: /
//       import {\n' +
//   - "settings capabilities dirty-check, Finder resources tree, and learning step sanitizer stay intact"
//       fails at HEAD: The input did not match the regular expression /function
//       providerCapabilitiesKey/. Input: / import { trainerCommands } from
//       "../../../../../shared/src/commands";\n' +
//   - "all 43 registered backend tools have 8-locale TOOL_LABELS and UX settings/resources polish stays intact"
//       fails at HEAD: Expected >= 43 tools, got 0
//   - "shared training card, review queue, and coach bridge helpers return 8-locale non-English text"
//       fails at HEAD: summarizeTrainingScenarioPack is not a function
//   - "library folder rename/delete commands sync workbench resources and v1.6.3 UX guards hold"
//       fails at HEAD: The input did not match the regular expression /settings-thinking-intensity/.
//       Input: / import { trainerCommands } from "../../../../../shared/src/commands";\n' +
// Target: extension host (extension/dist) with the vscode mock.

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



