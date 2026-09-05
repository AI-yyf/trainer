'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const commandIndexModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'index.js',
);
const constantsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'constants.js',
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

function createVscodeMock() {
  const registeredCommandIds = [];
  const registeredCommands = new Map();
  return {
    commands: {
      registerCommand(commandId, handler) {
        registeredCommandIds.push(commandId);
        registeredCommands.set(commandId, handler);
        return { dispose() {} };
      },
    },
    window: {
      showQuickPick: async () => {
        throw new Error('showQuickPick should not run in command registration tests');
      },
      showOpenDialog: async () => {
        throw new Error('showOpenDialog should not run in command registration tests');
      },
      showInformationMessage: async () => undefined,
      showWarningMessage: async () => undefined,
      showErrorMessage: async () => undefined,
    },
    __registeredCommandIds: registeredCommandIds,
    __registeredCommands: registeredCommands,
  };
}

function createCommandContext() {
  return {
    outputChannel: { appendLine() {} },
    sidecarClient: {},
    getHostState() {
      return {
        workspace: {},
        bootstrap: {},
      };
    },
    workbench: {
      show: async () => undefined,
      syncState: async () => undefined,
      postMessage: async () => undefined,
      setRefreshHandler: () => undefined,
    },
  };
}

function createUploadCommandContext() {
  const requests = [];
  const { createDefaultBootstrapData } = require(workbenchDataModulePath);
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
        tools: false,
        jsonSchema: false,
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
  return {
    outputChannel: { appendLine() {} },
    trainerWorkspace: {
      getRoot() {
        return 'F:\\trainer\\trainer-workspace';
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        requests.push({ port, requestPath, body });
        if (requestPath === '/resource/upload') {
          return {
            id: 'resource-inline-1',
            title: 'inline-proof.md',
            kind: 'markdown',
            status: 'indexing',
            summary: 'Inline upload proof',
            source: 'C:\\temp\\inline-proof.md',
          };
        }
        if (requestPath === '/resource/index') {
          return {
            id: 'resource-inline-1',
            title: 'inline-proof.md',
            kind: 'markdown',
            status: 'ready',
            summary: 'Inline upload proof',
            source: 'C:\\temp\\inline-proof.md',
          };
        }
        throw new Error(`Unexpected request path: ${requestPath}`);
      },
      async getJson() {
        return {
          memory: {
            recent_summary: 'Inline upload indexed and available.',
          },
        };
      },
    },
    getHostState() {
      return {
        workspace: {
          workspaceFolder: 'F:\\trainer\\workspace-a',
        },
        bootstrap,
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData() {
      return undefined;
    },
    workbench: {
      show: async () => undefined,
      syncState: async () => undefined,
      postMessage: async () => undefined,
      setRefreshHandler: () => undefined,
    },
    __requests: requests,
  };
}

test('registerCommands wires internal recovery and training compatibility commands into runtime', () => {
  const vscodeMock = createVscodeMock();
  const { registerCommands } = loadWithVscodeMock(commandIndexModulePath, vscodeMock);
  const { COMMAND_IDS } = require(constantsModulePath);
  const extensionContext = { subscriptions: [] };

  registerCommands(extensionContext, createCommandContext());

  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingRestoreOrchestration));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.debugRestoreView));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.resumeLatestCoachCheckpoint));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.replayLatestCoachCheckpoint));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingCardStatusTransition));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingGenerateCard));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingFlashcardCreate));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingFlashcardAnswer));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingTheoryDrillAnswer));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingDependencySkillMapAction));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingReviewQueueAction));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingReviewArtifactAction));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.trainingScenarioLabAction));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.theoryDrillSubmitAnswer));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.reviewQueueAction));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.scenarioLabAction));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.useProviderTemplate));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.switchProviderProfile));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.saveProviderProfile));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.refreshProviderProfiles));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.refreshSandbox));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.refreshResourceTrash));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.grantMemoryShare));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.revokeMemoryShare));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.chooseSandboxRoot));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.resetSandboxRoot));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.chooseManagedDataFolder));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.resetManagedDataFolder));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.createGlobalPlan));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.linkCurrentProjectPlan));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.chooseTrainerWorkspaceRoot));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.migrateTrainerWorkspaceRoot));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.backupTrainerWorkspace));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.restoreTrainerWorkspaceBackup));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.adoptWorkspaceProject));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.browseWorkspaceProject));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.ignoreWorkspaceProject));
  assert.ok(vscodeMock.__registeredCommandIds.includes(COMMAND_IDS.deleteWorkspaceProject));
  assert.ok(extensionContext.subscriptions.length >= vscodeMock.__registeredCommandIds.length);
});

test('registerCommands forwards uploadResource payload into the registered command handler', async () => {
  const vscodeMock = createVscodeMock();
  const { registerCommands } = loadWithVscodeMock(commandIndexModulePath, vscodeMock);
  const { COMMAND_IDS } = require(constantsModulePath);
  const extensionContext = { subscriptions: [] };
  const context = createUploadCommandContext();

  registerCommands(extensionContext, context);

  const handler = vscodeMock.__registeredCommands.get(COMMAND_IDS.uploadResource);
  assert.equal(typeof handler, 'function');

  const result = await handler({
    mode: 'files',
    uploads: [
      {
        name: 'inline-proof.md',
        kind: 'markdown',
        source: 'inline://trainer/inline-proof.md',
        content: '# Inline proof\nTrainer should ingest this without a picker.\n',
        contentEncoding: 'utf-8',
        tags: ['vsix-e2e', 'inline'],
      },
    ],
  });

  assert.equal(result.ok, true);
  assert.deepEqual(context.__requests, [
    {
      port: 34891,
      requestPath: '/resource/upload',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        kind: 'markdown',
        name: 'inline-proof.md',
        source: 'inline://trainer/inline-proof.md',
        content: '# Inline proof\nTrainer should ingest this without a picker.\n',
        content_encoding: 'utf-8',
        tags: ['vsix-e2e', 'inline'],
        source_type: 'file',
        source_items: [],
      },
    },
    {
      port: 34891,
      requestPath: '/resource/index',
      body: {
        session_id: 'session-1',
        workspace_id: 'F:\\trainer\\workspace-a',
        resource_id: 'resource-inline-1',
        enable_network: false,
      },
    },
  ]);
});

test('registerCommands forwards an unsaved provider draft to the temporary test path', async () => {
  const vscodeMock = createVscodeMock();
  const { registerCommands } = loadWithVscodeMock(commandIndexModulePath, vscodeMock);
  const { COMMAND_IDS } = require(constantsModulePath);
  const extensionContext = { subscriptions: [] };
  let requestBody;
  const context = {
    ...createCommandContext(),
    providerStore: {
      async getResolvedConfig() {
        return {
          name: 'Saved Provider',
          baseUrl: 'https://saved.example/v1',
          model: 'saved-model',
          protocol: 'openai_chat_completions_compatible',
          apiKeyRef: 'saved.default',
          apiKey: 'sk-saved',
          capabilities: {
            chat: true,
            responses: false,
            vision: false,
            embeddings: false,
            tools: false,
            jsonSchema: false,
            structuredOutput: false,
            streaming: true,
          },
        };
      },
      async getApiKey() {
        return 'sk-saved';
      },
      async saveLastTestResult() {
        throw new Error('A temporary draft test must not save test history.');
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, requestPath, body) {
        assert.equal(requestPath, '/provider/test');
        requestBody = body;
        return {
          ok: true,
          status: 'connected',
          success: true,
          provider_name: 'Draft Provider',
          detail: 'Draft connection verified.',
        };
      },
    },
    getHostState() {
      return {
        workspace: { workspaceFolder: 'F:\\trainer\\workspace-a' },
        bootstrap: {
          memory: {},
          providerConfig: {
            configured: true,
            name: 'Saved Provider',
            baseUrl: 'https://saved.example/v1',
            model: 'saved-model',
            apiKeyConfigured: true,
            capabilities: {},
            availableModels: [],
            modelListStatus: 'ready',
          },
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData() {
      throw new Error('A temporary draft test must not patch saved provider state.');
    },
  };

  registerCommands(extensionContext, context);
  const handler = vscodeMock.__registeredCommands.get(COMMAND_IDS.testProvider);
  assert.equal(typeof handler, 'function');

  const result = await handler({
    draft: {
      name: 'Draft Provider',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://draft.example/v1',
      model: 'draft-model',
      apiKey: 'sk-draft',
    },
  });

  assert.equal(result.ok, true);
  assert.equal(requestBody.apiKey, 'sk-draft');
  assert.equal(requestBody.provider.baseUrl, 'https://draft.example/v1');
  assert.match(result.message ?? '', /saved connection was not changed/i);
});

test('registerCommands forwards an unsaved provider draft to model discovery without saving it', async () => {
  const vscodeMock = createVscodeMock();
  const { registerCommands } = loadWithVscodeMock(commandIndexModulePath, vscodeMock);
  const { COMMAND_IDS } = require(constantsModulePath);
  const { createDefaultBootstrapData } = require(workbenchDataModulePath);
  const extensionContext = { subscriptions: [] };
  const patches = [];
  const savedConfig = {
    name: 'Saved Provider',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://saved.example/v1',
    apiKeyRef: 'saved.default',
    model: 'saved-model',
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      structuredOutput: false,
      streaming: true,
    },
  };
  const bootstrap = createDefaultBootstrapData(
    { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
    savedConfig,
    { lifecycle: 'ready', host: '127.0.0.1', port: 34891, canStart: true },
  );
  const context = {
    ...createCommandContext(),
    providerStore: {
      getConfig() {
        return savedConfig;
      },
      getModelCache() {
        throw new Error('Draft discovery must not read the saved cache.');
      },
      async saveConfig() {
        throw new Error('Draft discovery must not save a provider.');
      },
      async saveModelCache() {
        throw new Error('Draft discovery must not save a model cache.');
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(_port, route, body) {
        assert.equal(route, '/provider/models');
        assert.equal(body.apiKey, 'sk-draft');
        assert.equal(body.provider.baseUrl, 'https://draft.example/v1');
        return {
          ok: true,
          detail: 'Loaded a draft model.',
          available_models: ['draft-model'],
        };
      },
    },
    getHostState() {
      return {
        workspace: { trusted: true, workspaceFolder: 'F:\\trainer\\workspace-a' },
        bootstrap,
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      show: async () => undefined,
      syncState: async () => undefined,
      postMessage: async () => undefined,
      setRefreshHandler: () => undefined,
    },
  };

  registerCommands(extensionContext, context);
  const handler = vscodeMock.__registeredCommands.get(COMMAND_IDS.refreshProviderModels);
  const result = await handler({
    draft: {
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://draft.example/v1/chat/completions',
      apiKey: 'sk-draft',
    },
  });

  assert.equal(result.ok, true);
  assert.equal(patches.length, 2);
  assert.equal(patches[0].providerConfig.modelListing.source, 'draft');
  assert.equal(patches[0].providerConfig.modelListing.status, 'loading');
  assert.equal(patches[1].providerConfig.modelListing.source, 'draft');
  assert.equal(patches[1].providerConfig.modelListing.baseUrl, 'https://draft.example/v1');
  assert.deepEqual(patches[1].providerConfig.modelListing.availableModels, ['draft-model']);
  assert.deepEqual(
    patches[1].providerConfig.availableModels,
    bootstrap.providerConfig.availableModels,
    'A draft lookup must not replace the saved connection model list.',
  );
  assert.equal(JSON.stringify(patches).includes('sk-draft'), false);
});
