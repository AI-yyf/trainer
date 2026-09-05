'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const evaluationCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'evaluationCommands.js',
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

function createContext(options = {}) {
  const { createDefaultBootstrapData } = require(workbenchDataModulePath);
  const expectedTrustReason = options.expectedTrustReason ?? 'evaluate the current file';
  const posts = [];
  const gets = [];
  const patches = [];
  const publishedReports = [];
  const outputLines = [];
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    {
      name: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      apiKeyRef: 'trainer.default',
      model: 'demo-model',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: true,
        tools: true,
        jsonSchema: true,
        streaming: true,
      },
    },
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  bootstrap.providerConfig.apiKeyConfigured = true;
  bootstrap.providerConfig.availableModels = ['demo-model'];
  bootstrap.providerConfig.modelListStatus = 'ready';
  bootstrap.providerConfig.lastTestResult = {
    ok: true,
    status: 'passed',
    checkedAt: new Date().toISOString(),
    providerName: 'Local Compatible',
    baseUrl: 'http://localhost:1234/v1',
    model: 'demo-model',
    responseLanguage: 'en-US',
  };
  bootstrap.task.id = 'bootstrap-task';

  return {
    trustGuard: {
      async ensureTrusted(reason) {
        assert.equal(reason, expectedTrustReason);
        return true;
      },
    },
    providerStore: {
      getConfig() {
        return {
          name: 'Local Compatible',
          baseUrl: 'http://localhost:1234/v1',
          model: 'demo-model',
        };
      },
      async getApiKey() {
        return 'sk-test';
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        posts.push({ port, requestPath, body });
        return {
          workspace_id: body.workspace_id,
          task_spec_id: body.task_spec_id,
          summary: 'Practice verification completed.',
          static_checks: [
            {
              id: 'current-file',
              label: 'Active editor content was evaluated',
              status: 'passed',
              detail: 'IDE file content and diagnostics were included.',
            },
          ],
          dynamic_checks: [],
          semantic_checks: [],
          next_step: 'Keep the next change small.',
          reflection: 'ok',
          passed: true,
        };
      },
      async getJson(port, requestPath) {
        gets.push({ port, requestPath });
        if (options.failMemorySummary) {
          throw new Error('memory summary unavailable');
        }
        return {
          memory: {
            workspace: {
              workspace_id: 'F:\\trainer\\workspace-a',
              latest_training_submode: 'practice',
              latest_learning_verified_result: 'Practice verification completed.',
              selected_card_id: 'card-practice-1',
              selected_card_type: 'practice',
              selected_card_title: 'Refactor the async boundary',
              selected_card_status: 'implemented',
              latest_training_handoff: {
                candidate_id: 'card-practice-1',
                candidate_type: 'practice_candidate',
                target_kind: 'training_card',
                target_id: 'card-practice-1',
                continue_in: 'training',
                handoff_status: 'resolved',
                handoff_summary: 'Practice result was verified from the active IDE file.',
                card_type: 'practice',
                card_title: 'Refactor the async boundary',
                return_mode: 'result',
                return_summary: 'Current file verification passed.',
              },
            },
          },
        };
      },
    },
    tests: {
      publishReport(report, uri) {
        publishedReports.push({ report, uri });
      },
    },
    outputChannel: {
      appendLine(line) {
        outputLines.push(line);
      },
    },
    getHostState() {
      return {
        bootstrap,
        workspace: {
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __posts: posts,
    __gets: gets,
    __patches: patches,
    __publishedReports: publishedReports,
    __outputLines: outputLines,
  };
}

test('evaluateCurrentFileCommand reads IDE file content and diagnostics for training practice verification', async () => {
  const document = {
    uri: { fsPath: 'F:\\trainer\\workspace-a\\src\\exercise.ts' },
    languageId: 'typescript',
    getText(range) {
      assert.equal(range, undefined);
      return 'export const answer: number = 42;\n';
    },
  };
  const vscodeMock = {
    DiagnosticSeverity: {
      Error: 0,
      Warning: 1,
      Information: 2,
      Hint: 3,
    },
    window: {
      activeTextEditor: {
        document,
      },
      async showWarningMessage() {
        throw new Error('showWarningMessage should not run when an editor is active');
      },
    },
    languages: {
      getDiagnostics(uri) {
        assert.equal(uri, document.uri);
        return [
          {
            severity: 0,
            range: { start: { line: 6 } },
            message: 'Type mismatch from the active editor.',
          },
          {
            severity: 1,
            range: { start: { line: 7 } },
            message: 'Unused local helper.',
          },
        ];
      },
    },
  };
  const { evaluateCurrentFileCommand } = loadWithVscodeMock(
    evaluationCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();

  const result = await evaluateCurrentFileCommand(context, {
    source: 'training',
    cardId: 'card-practice-1',
    cardTitle: 'Refactor the async boundary',
    taskSpecId: 'task-from-card',
    acceptanceCriteria: [
      'Implement debounceSearch in the active editor.',
      'Use normalizedQuery before filtering results.',
      'Use normalizedQuery before filtering results.',
    ],
    learnerDeliverables: [
      'A current-file implementation that includes debounceSearch.',
      '',
    ],
    expectedSymbols: ['debounceSearch', 'normalizedQuery'],
  });

  assert.equal(result.ok, true);
  assert.equal(context.__posts.length, 1);
  assert.deepEqual(context.__posts[0], {
    port: 34891,
    requestPath: '/evaluate/current-file',
    body: {
      session_id: 'session-1',
      workspace_id: 'F:\\trainer\\workspace-a',
      task_spec_id: 'task-from-card',
      file_path: 'F:\\trainer\\workspace-a\\src\\exercise.ts',
      language_id: 'typescript',
      content: 'export const answer: number = 42;\n',
      diagnostics: [
        '[Error] line 7: Type mismatch from the active editor.',
        '[Warning] line 8: Unused local helper.',
      ],
      evaluation_source: 'training',
      training_card_id: 'card-practice-1',
      training_card_title: 'Refactor the async boundary',
      acceptance_criteria: [
        'Implement debounceSearch in the active editor.',
        'Use normalizedQuery before filtering results.',
      ],
      learner_deliverables: [
        'A current-file implementation that includes debounceSearch.',
      ],
      expected_symbols: ['debounceSearch', 'normalizedQuery'],
    },
  });
  // Fail-closed: host must never pass target_path (server rewrite surface).
  assert.equal(Object.hasOwn(context.__posts[0].body, 'target_path'), false);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath: '/memory/summary?workspace_id=F%3A%5Ctrainer%5Cworkspace-a&session_id=session-1',
    },
  ]);
  assert.equal(context.__patches.length, 2);
  assert.equal(context.__patches[0].evaluation.headline, '1 of 1 checks passed');
  assert.equal(context.__patches[0].evaluation.summary, 'Practice verification completed.');
  assert.equal(context.__patches[0].evaluation.passRate, 1);
  assert.equal(context.__patches[1].workspaceTrainingState.selectedCardId, 'card-practice-1');
  assert.equal(context.__patches[1].workspaceTrainingState.selectedCardType, 'practice');
  assert.equal(context.__patches[1].workspaceTrainingState.selectedCardStatus, 'implemented');
  assert.equal(
    context.__patches[1].workspaceTrainingState.latestLearningVerifiedResult,
    'Practice verification completed.',
  );
  assert.equal(
    context.__patches[1].workspaceTrainingState.latestTrainingHandoff.returnSummary,
    'Current file verification passed.',
  );
  assert.equal(context.__publishedReports.length, 1);
  assert.equal(context.__publishedReports[0].uri, document.uri);
});

test('evaluateCurrentFileCommand uses the managed workspace context for evaluation and refresh', async () => {
  const document = {
    uri: { fsPath: 'F:\\trainer\\workspace-a\\src\\exercise.ts' },
    languageId: 'typescript',
    getText() {
      return 'export const answer: number = 42;\n';
    },
  };
  const vscodeMock = {
    DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
    window: { activeTextEditor: { document } },
    languages: { getDiagnostics() { return []; } },
  };
  const { evaluateCurrentFileCommand } = loadWithVscodeMock(
    evaluationCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  const managedContextId = 'context-evaluation-123';
  context.getHostState().bootstrap.memory.workspace = {
    ...(context.getHostState().bootstrap.memory.workspace ?? {}),
    trainerWorkspace: {
      status: 'managed',
      contextId: managedContextId,
      canonicalProjectPath: 'f:\\trainer\\workspace-a',
      rootId: 'root-evaluation',
      projectId: 'project-evaluation',
    },
  };

  const result = await evaluateCurrentFileCommand(context);

  assert.equal(result.ok, true);
  assert.equal(context.__posts[0].body.workspace_id, managedContextId);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath: `/memory/summary?workspace_id=${managedContextId}&session_id=session-1`,
    },
  ]);
});

test('evaluateCurrentFileCommand keeps the evaluation result when training state refresh is temporarily unavailable', async () => {
  const document = {
    uri: { fsPath: 'F:\\trainer\\workspace-a\\src\\exercise.ts' },
    languageId: 'typescript',
    getText() {
      return 'export const answer: number = 42;\n';
    },
  };
  const vscodeMock = {
    DiagnosticSeverity: {
      Error: 0,
      Warning: 1,
      Information: 2,
      Hint: 3,
    },
    window: {
      activeTextEditor: {
        document,
      },
    },
    languages: {
      getDiagnostics() {
        return [];
      },
    },
  };
  const { evaluateCurrentFileCommand } = loadWithVscodeMock(
    evaluationCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ failMemorySummary: true });

  const result = await evaluateCurrentFileCommand(context, {
    source: 'training',
    cardId: 'card-practice-1',
    cardTitle: 'Refactor the async boundary',
  });

  assert.equal(result.ok, true);
  assert.match(result.message, /evaluation completed/i);
  assert.match(result.message, /Training state refresh will recover/i);
  assert.equal(context.__posts.length, 1);
  assert.equal(context.__gets.length, 1);
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__patches[0].evaluation.summary, 'Practice verification completed.');
  assert.equal(context.__publishedReports.length, 1);
  assert.match(context.__outputLines[0], /Memory summary refresh failed/);
});

test('evaluateSelectionCommand rejects training practice verification before posting snippets', async () => {
  const document = {
    uri: { fsPath: 'F:\\trainer\\workspace-a\\src\\exercise.ts' },
    languageId: 'typescript',
    getText() {
      return 'export const answer: number = 42;\n';
    },
  };
  const vscodeMock = {
    DiagnosticSeverity: {
      Error: 0,
      Warning: 1,
      Information: 2,
      Hint: 3,
    },
    window: {
      activeTextEditor: {
        document,
        selection: {},
      },
    },
    languages: {
      getDiagnostics() {
        throw new Error('diagnostics should not be read for rejected training snippet verification');
      },
    },
  };
  const { evaluateSelectionCommand } = loadWithVscodeMock(
    evaluationCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({ expectedTrustReason: 'evaluate the current selection' });

  const result = await evaluateSelectionCommand(context, {
    source: 'training',
    cardId: 'card-practice-1',
    cardTitle: 'Refactor the async boundary',
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /active IDE file and diagnostics/i);
  assert.equal(context.__posts.length, 0);
  assert.equal(context.__gets.length, 0);
  assert.equal(context.__patches.length, 0);
  assert.equal(context.__publishedReports.length, 0);
});

test('evaluateCurrentFileCommand prefers filesToTouch over an unrelated editor', async () => {
  const editorDocument = {
    uri: { fsPath: 'F:\\trainer\\workspace-a\\src\\other.ts' },
    languageId: 'typescript',
    getText() {
      return 'export const other = true;\n';
    },
  };
  const targetDocument = {
    uri: { fsPath: 'F:\\trainer\\workspace-a\\src\\exercise.ts' },
    languageId: 'typescript',
    getText() {
      return 'export function debounceSearch() {}\n';
    },
  };
  const vscodeMock = {
    DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
    Uri: {
      file(fsPath) {
        return { fsPath: String(fsPath).replace(/\//g, '\\'), scheme: 'file' };
      },
    },
    window: {
      activeTextEditor: { document: editorDocument },
      async showWarningMessage() {
        throw new Error('should not warn when a filesToTouch path opens');
      },
    },
    languages: {
      getDiagnostics() {
        return [];
      },
    },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: 'F:\\trainer\\workspace-a' } }],
      async openTextDocument(uri) {
        const normalized = String(uri.fsPath).replace(/\\/g, '/');
        if (normalized.endsWith('src/exercise.ts')) {
          return targetDocument;
        }
        throw new Error(`unexpected document ${uri.fsPath}`);
      },
    },
  };
  const { evaluateCurrentFileCommand } = loadWithVscodeMock(
    evaluationCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();

  const result = await evaluateCurrentFileCommand(context, {
    source: 'training',
    cardId: 'card-practice-1',
    cardTitle: 'Refactor the async boundary',
    filesToTouch: ['src/exercise.ts'],
  });

  assert.equal(result.ok, true);
  assert.equal(context.__posts[0].body.file_path, targetDocument.uri.fsPath);
  assert.equal(context.__posts[0].body.content, 'export function debounceSearch() {}\n');
  assert.notEqual(context.__posts[0].body.content, editorDocument.getText());
});

test('evaluateCurrentFileCommand fails honestly without filesToTouch or an editor', async () => {
  const vscodeMock = {
    DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
    Uri: {
      file(fsPath) {
        return { fsPath, scheme: 'file' };
      },
    },
    window: {
      activeTextEditor: undefined,
      async showWarningMessage() {
        return undefined;
      },
    },
    languages: {
      getDiagnostics() {
        return [];
      },
    },
    workspace: {
      workspaceFolders: [],
    },
  };
  const { evaluateCurrentFileCommand } = loadWithVscodeMock(
    evaluationCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();

  const result = await evaluateCurrentFileCommand(context, { source: 'training' });

  assert.equal(result.ok, false);
  assert.match(result.message, /No active editor/);
  assert.equal(context.__posts.length, 0);
});

