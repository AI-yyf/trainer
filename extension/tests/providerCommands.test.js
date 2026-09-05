'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const providerCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'providerCommands.js',
);

function createContext(workspace = { workspaceFolder: 'F:\\trainer-a' }, trainerWorkspaceStatus) {
  const patches = [];
  const trainerWorkspace =
    typeof trainerWorkspaceStatus === 'string'
      ? { status: trainerWorkspaceStatus }
      : trainerWorkspaceStatus;
  return {
    extensionContext: {
      globalState: {
        async update() {
          return undefined;
        },
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    trainerWorkspace: {
      getRoot() {
        return 'F:\\trainer-workspace';
      },
    },
    sidecarClient: {
      async postJson() {
        return undefined;
      },
    },
    providerStore: {
      getResolvedConfig() {
        return {
          name: 'Local Compatible',
          baseUrl: 'http://localhost:1234/v1',
          model: 'demo-model',
          protocol: 'openai_chat_completions_compatible',
          apiKeyRef: 'trainer.default',
          capabilities: {
            chat: true,
            responses: true,
            vision: false,
            embeddings: true,
            tools: false,
            jsonSchema: false,
            streaming: true,
          },
        };
      },
      async getApiKey() {
        return 'sk-test';
      },
      getConfig() {
        return {
          name: 'Local Compatible',
          baseUrl: 'http://localhost:1234/v1',
          model: 'demo-model',
          protocol: 'openai_chat_completions_compatible',
          apiKeyRef: 'trainer.default',
          capabilities: {
            chat: true,
            responses: true,
            vision: false,
            embeddings: true,
            tools: false,
            jsonSchema: false,
            streaming: true,
          },
        };
      },
      async saveLastTestResult() {
        return undefined;
      },
      getLastTestResult() {
        return undefined;
      },
    },
    getHostState() {
      return {
        bootstrap: {
          providerConfig: {
            configured: true,
            name: 'Local Compatible',
            baseUrl: 'http://localhost:1234/v1',
            model: 'demo-model',
            apiKeyConfigured: true,
            capabilities: {
              chat: true,
              responses: true,
              vision: false,
              embeddings: true,
              tools: false,
              jsonSchema: false,
              streaming: true,
            },
            availableModels: [],
            modelListStatus: 'ready',
          },
          memory: {
            weakSpots: [],
            recentWins: [],
            dueReviews: [],
            teachingObservations: [],
            memoryEvidence: [],
          learningOutcomes: [],
          providerDiagnostics: [],
          ...(trainerWorkspace
            ? { workspace: { trainerWorkspace } }
            : {}),
        },
          connection: {},
        },
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace,
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    workbench: {
      async syncState() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    __patches: patches,
  };
}

test('configureProviderCommand keeps a restricted connection unchanged when its chosen model is blocked', async () => {
  const vscodeMock = {
    window: {
      async showInputBox(options) {
        if (options.title === 'Provider name') return 'Local Compatible';
        if (options.title === 'Base URL') return 'http://localhost:1234/v1';
        if (options.title === 'Chat model') return 'blocked-model';
        if (options.title === 'API key (leave blank to keep current or store none)') return '';
        return '';
      },
      async showQuickPick(items) {
        return items.filter((item) => item.picked);
      },
    },
  };
  const { configureProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  const savedConfigs = [];
  context.providerStore = {
    getConfig() {
      return {
        name: 'Local Compatible',
        baseUrl: 'http://localhost:1234/v1',
        model: 'allowed-model',
        apiKeyRef: 'trainer.default',
        allowedModels: ['allowed-model', 'blocked-model'],
        deniedModels: ['BLOCKED-MODEL'],
        capabilities: {
          chat: true,
          responses: true,
          vision: false,
          embeddings: false,
          tools: false,
          jsonSchema: false,
          streaming: true,
        },
      };
    },
    async saveConfig(config) {
      savedConfigs.push(config);
    },
    async getApiKey() {
      return 'sk-test';
    },
  };

  const result = await configureProviderCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message, /blocked for this connection/i);
  assert.equal(savedConfigs.length, 0);
});

test('testProviderCommand refuses a blocked draft before it contacts the provider', async () => {
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, {
    window: {
      async showInformationMessage() {},
      async showWarningMessage() {},
      async showErrorMessage() {},
    },
  });
  const context = createContext();
  let requests = 0;
  context.sidecarClient.postJson = async () => {
    requests += 1;
    return { ok: true, status: 'connected' };
  };

  const result = await testProviderCommand(context, {
    draft: {
      name: 'Draft gateway',
      baseUrl: 'https://draft.example/v1',
      model: 'blocked-model',
      allowedModels: ['blocked-model'],
      deniedModels: ['BLOCKED-MODEL'],
      apiKey: 'sk-draft',
    },
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /blocked for this connection/i);
  assert.equal(requests, 0);
  assert.equal(context.__patches.length, 0);
});

test('createProviderProfileFromDraftCommand rejects a blocked model before creating a profile', async () => {
  const { createProviderProfileFromDraftCommand } = loadWithVscodeMock(providerCommandsModulePath, {});
  const context = createContext();
  const createdProfiles = [];
  context.providerStore.createProfileFromConfig = async (config) => {
    createdProfiles.push(config);
    return config;
  };

  const result = await createProviderProfileFromDraftCommand(context, {
    name: 'Draft gateway',
    baseUrl: 'https://draft.example/v1',
    model: 'blocked-model',
    allowedModels: ['blocked-model'],
    deniedModels: ['BLOCKED-MODEL'],
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /blocked for this connection/i);
  assert.equal(createdProfiles.length, 0);
});

test('switchProviderProfileCommand refuses a blocked profile before changing the active profile', async () => {
  const { switchProviderProfileCommand } = loadWithVscodeMock(providerCommandsModulePath, {});
  const context = createContext();
  let switches = 0;
  context.providerStore.getProfileRegistrySnapshot = () => ({
    activeProfileId: 'current-profile',
    profiles: [
      {
        id: 'blocked-profile',
        model: 'blocked-model',
        allowedModels: ['blocked-model'],
        deniedModels: ['BLOCKED-MODEL'],
      },
    ],
  });
  context.providerStore.switchActiveProfile = async () => {
    switches += 1;
    return true;
  };

  const result = await switchProviderProfileCommand(context, { profileId: 'blocked-profile' });

  assert.equal(result.ok, false);
  assert.match(result.message, /blocked for this connection/i);
  assert.equal(switches, 0);
  assert.equal(context.__patches.length, 0);
});

test('switchProviderProfileCommand restores the previous profile when the target becomes blocked during activation', async () => {
  const { switchProviderProfileCommand } = loadWithVscodeMock(providerCommandsModulePath, {});
  const context = createContext();
  const capabilities = {
    chat: true,
    responses: true,
    vision: false,
    embeddings: false,
    tools: false,
    jsonSchema: false,
    streaming: true,
  };
  const previousConfig = {
    name: 'Previous',
    baseUrl: 'https://previous.example/v1',
    model: 'previous-model',
    apiKeyRef: 'previous.key',
    profileId: 'previous-profile',
    capabilities,
  };
  let targetProfile = {
    id: 'target-profile',
    model: 'target-model',
    allowedModels: ['target-model'],
    deniedModels: [],
  };
  let activeProfileId = 'previous-profile';
  let activeConfig = previousConfig;
  const switches = [];
  context.providerStore = {
    getProfileRegistrySnapshot() {
      return {
        activeProfileId,
        profiles: [
          {
            id: 'previous-profile',
            model: 'previous-model',
            allowedModels: [],
            deniedModels: [],
          },
          targetProfile,
        ],
      };
    },
    getActiveProfileConfig() {
      return activeConfig;
    },
    getConfig() {
      return activeConfig;
    },
    async switchActiveProfile(profileId) {
      switches.push(profileId);
      if (profileId === 'target-profile') {
        targetProfile = {
          ...targetProfile,
          model: 'blocked-model',
          allowedModels: ['blocked-model'],
          deniedModels: ['BLOCKED-MODEL'],
        };
        activeProfileId = profileId;
        activeConfig = {
          ...previousConfig,
          name: 'Target',
          baseUrl: 'https://target.example/v1',
          model: 'blocked-model',
          apiKeyRef: 'target.key',
          profileId,
          allowedModels: targetProfile.allowedModels,
          deniedModels: targetProfile.deniedModels,
        };
        return true;
      }
      activeProfileId = profileId;
      activeConfig = previousConfig;
      return true;
    },
  };

  const result = await switchProviderProfileCommand(context, { profileId: 'target-profile' });

  assert.equal(result.ok, false);
  assert.match(result.message, /restored your previous connection/i);
  assert.deepEqual(switches, ['target-profile', 'previous-profile']);
  assert.equal(activeProfileId, 'previous-profile');
  assert.equal(context.__patches.length, 0);
});

test('switchProviderProfileCommand lets a later profile choice win after recovering a failed activation', async () => {
  const { switchProviderProfileCommand } = loadWithVscodeMock(providerCommandsModulePath, {});
  const context = createContext();
  const capabilities = {
    chat: true,
    responses: true,
    vision: false,
    embeddings: false,
    tools: false,
    jsonSchema: false,
    streaming: true,
  };
  const previousConfig = {
    name: 'Previous',
    baseUrl: 'https://previous.example/v1',
    model: 'previous-model',
    apiKeyRef: 'previous.key',
    profileId: 'previous-profile',
    capabilities,
  };
  const newerConfig = {
    name: 'Newer',
    baseUrl: 'https://newer.example/v1',
    model: 'newer-model',
    apiKeyRef: 'newer.key',
    profileId: 'newer-profile',
    capabilities,
  };
  let targetProfile = {
    id: 'target-profile',
    model: 'target-model',
    allowedModels: ['target-model'],
    deniedModels: [],
  };
  let activeProfileId = 'previous-profile';
  let activeConfig = previousConfig;
  let releaseTargetActivation;
  let markTargetActivationStarted;
  const targetActivationStarted = new Promise((resolve) => {
    markTargetActivationStarted = resolve;
  });
  const switches = [];
  context.providerStore = {
    getProfileRegistrySnapshot() {
      return {
        activeProfileId,
        profiles: [
          {
            id: 'previous-profile',
            model: 'previous-model',
            allowedModels: [],
            deniedModels: [],
          },
          targetProfile,
          {
            id: 'newer-profile',
            model: 'newer-model',
            allowedModels: [],
            deniedModels: [],
          },
        ],
      };
    },
    getActiveProfileConfig() {
      return activeConfig;
    },
    getConfig() {
      return activeConfig;
    },
    async getApiKey() {
      return undefined;
    },
    async switchActiveProfile(profileId) {
      switches.push(profileId);
      if (profileId === 'target-profile') {
        markTargetActivationStarted();
        await new Promise((resolve) => {
          releaseTargetActivation = resolve;
        });
        targetProfile = {
          ...targetProfile,
          model: 'blocked-model',
          allowedModels: ['blocked-model'],
          deniedModels: ['BLOCKED-MODEL'],
        };
        activeProfileId = profileId;
        activeConfig = {
          ...previousConfig,
          name: 'Target',
          baseUrl: 'https://target.example/v1',
          model: 'blocked-model',
          apiKeyRef: 'target.key',
          profileId,
          allowedModels: targetProfile.allowedModels,
          deniedModels: targetProfile.deniedModels,
        };
        return true;
      }
      activeProfileId = profileId;
      activeConfig = profileId === 'newer-profile' ? newerConfig : previousConfig;
      return true;
    },
  };

  const failedSwitch = switchProviderProfileCommand(context, { profileId: 'target-profile' });
  await targetActivationStarted;
  const newerSwitch = switchProviderProfileCommand(context, { profileId: 'newer-profile' });
  releaseTargetActivation();

  const [failedResult, newerResult] = await Promise.all([failedSwitch, newerSwitch]);

  assert.equal(failedResult.ok, false);
  assert.equal(newerResult.ok, true);
  assert.deepEqual(switches, ['target-profile', 'previous-profile', 'newer-profile']);
  assert.equal(activeProfileId, 'newer-profile');
});

test('switchProviderProfileCommand does not restore over a newer profile choice', async () => {
  const { switchProviderProfileCommand } = loadWithVscodeMock(providerCommandsModulePath, {});
  const context = createContext();
  const capabilities = {
    chat: true,
    responses: true,
    vision: false,
    embeddings: false,
    tools: false,
    jsonSchema: false,
    streaming: true,
  };
  const targetConfig = {
    name: 'Target',
    baseUrl: 'https://target.example/v1',
    model: 'blocked-model',
    apiKeyRef: 'target.key',
    profileId: 'target-profile',
    allowedModels: ['blocked-model'],
    deniedModels: ['BLOCKED-MODEL'],
    capabilities,
  };
  const newerConfig = {
    name: 'Newer',
    baseUrl: 'https://newer.example/v1',
    model: 'newer-model',
    apiKeyRef: 'newer.key',
    profileId: 'newer-profile',
    capabilities,
  };
  let activeProfileId = 'previous-profile';
  let activeConfig = targetConfig;
  let returnBlockedTargetOnce = false;
  const switches = [];
  context.providerStore = {
    getProfileRegistrySnapshot() {
      return {
        activeProfileId,
        profiles: [
          {
            id: 'previous-profile',
            model: 'previous-model',
            allowedModels: [],
            deniedModels: [],
          },
          {
            id: 'target-profile',
            model: 'target-model',
            allowedModels: ['target-model'],
            deniedModels: [],
          },
          {
            id: 'newer-profile',
            model: 'newer-model',
            allowedModels: [],
            deniedModels: [],
          },
        ],
      };
    },
    getActiveProfileConfig() {
      if (returnBlockedTargetOnce) {
        returnBlockedTargetOnce = false;
        activeProfileId = 'newer-profile';
        activeConfig = newerConfig;
        return targetConfig;
      }
      return activeConfig;
    },
    getConfig() {
      return activeConfig;
    },
    async switchActiveProfile(profileId) {
      switches.push(profileId);
      activeProfileId = profileId;
      if (profileId === 'target-profile') {
        returnBlockedTargetOnce = true;
      }
      return true;
    },
  };

  const result = await switchProviderProfileCommand(context, { profileId: 'target-profile' });

  assert.equal(result.ok, true);
  assert.match(result.message, /kept your newer choice/i);
  assert.deepEqual(switches, ['target-profile']);
  assert.equal(activeProfileId, 'newer-profile');
  assert.equal(context.__patches.length, 0);
});

test('testProviderCommand distinguishes reachable empty replies from unreachable providers', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        return {
          ok: false,
          configured: true,
          api_key_supplied: true,
          reachable: true,
          success: false,
          status: 'language_corruption',
          provider_name: 'Local Compatible',
          detail:
            'Provider reachable, but it corrupted Chinese input into question marks before the model saw it.',
          diagnostics: ['Language integrity probe failed.'],
          error_category: 'language_corruption',
          retryable: false,
          status_code: 200,
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };

  const result = await testProviderCommand(context);
  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /reachable, but chinese input was corrupted/i);
});

test('testProviderCommand keeps a temporary sidecar failure recoverable', async () => {
  const warnings = [];
  const vscodeMock = {
    window: {
      async showWarningMessage(message) {
        warnings.push(message);
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        throw new Error('A recoverable sidecar failure should not show a hard error.');
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient = {
    async postJson() {
      throw new Error('connection reset by peer');
    },
  };

  const result = await testProviderCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /could not finish the connection check/i);
  assert.equal(warnings.length, 1);
  assert.doesNotMatch(JSON.stringify(context.__patches), /sk-test/);
});

test('testProviderCommand redacts key-shaped detail from toast and persist', async () => {
  const FAKE_KEY = 'sk-test-not-a-real-key-bbbbbbbb';
  const FAKE_BEARER = 'Bearer fake-token-yyyyyyyyyyyy';
  const errors = [];
  const saved = [];
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage(message) {
        errors.push(message);
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.providerStore.saveLastTestResult = async (_config, result) => {
    saved.push(result);
    return result;
  };
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        return {
          ok: false,
          configured: true,
          api_key_supplied: true,
          reachable: true,
          success: false,
          status: 'failed',
          provider_name: 'Local Compatible',
          detail: `Rejected credential ${FAKE_KEY} (${FAKE_BEARER})`,
          error_category: 'invalid_key_or_permission',
          retryable: false,
          status_code: 401,
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };

  const result = await testProviderCommand(context);
  assert.equal(result.ok, false);
  assert.doesNotMatch(result.message ?? '', /sk-test-not-a-real-key-bbbbbbbb/);
  assert.doesNotMatch(result.message ?? '', /fake-token-yyyyyyyyyyyy/);
  assert.equal(errors.length, 1);
  assert.doesNotMatch(errors[0], /sk-test-not-a-real-key-bbbbbbbb/);
  assert.doesNotMatch(errors[0], /fake-token-yyyyyyyyyyyy/);
  assert.equal(saved.length, 1);
  assert.doesNotMatch(String(saved[0].detail ?? ''), /sk-test-not-a-real-key-bbbbbbbb/);
  assert.doesNotMatch(String(saved[0].detail ?? ''), /fake-token-yyyyyyyyyyyy/);
  assert.doesNotMatch(JSON.stringify(context.__patches), /sk-test-not-a-real-key-bbbbbbbb/);
  assert.doesNotMatch(JSON.stringify(context.__patches), /fake-token-yyyyyyyyyyyy/);
});

test('diagnoseProviderCommand redacts key-shaped detail from message and persist', async () => {
  const FAKE_KEY = 'sk-test-not-a-real-key-cccccccc';
  const FAKE_BEARER = 'Bearer fake-token-zzzzzzzzzzzz';
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { diagnoseProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        return {
          ok: false,
          configured: true,
          reachable: true,
          detail: `Diagnostics rejected ${FAKE_KEY} (${FAKE_BEARER})`,
          error_category: 'invalid_key_or_permission',
          status_code: 401,
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson() {
      return { memory: {} };
    },
  };

  const result = await diagnoseProviderCommand(context);
  assert.equal(result.ok, false);
  assert.doesNotMatch(result.message ?? '', /sk-test-not-a-real-key-cccccccc/);
  assert.doesNotMatch(result.message ?? '', /fake-token-zzzzzzzzzzzz/);
  assert.doesNotMatch(JSON.stringify(context.__patches), /sk-test-not-a-real-key-cccccccc/);
  assert.doesNotMatch(JSON.stringify(context.__patches), /fake-token-zzzzzzzzzzzz/);
  const providerPatch = context.__patches.find((patch) => patch.providerConfig)?.providerConfig;
  assert.ok(providerPatch);
  assert.doesNotMatch(String(providerPatch.modelTest?.detail ?? ''), /sk-test-not-a-real-key-cccccccc/);
  assert.doesNotMatch(String(providerPatch.modelListing?.detail ?? ''), /sk-test-not-a-real-key-cccccccc/);
  assert.doesNotMatch(
    String(providerPatch.modelTest?.diagnosticsSummary ?? ''),
    /sk-test-not-a-real-key-cccccccc/,
  );
});

test('testProviderCommand persists only observed tool capability evidence', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  let savedResult;
  context.providerStore.saveLastTestResult = async (_config, result) => {
    savedResult = result;
    return result;
  };
  context.sidecarClient = {
    async postJson(_port, requestPath, _body, options) {
      assert.equal(requestPath, '/provider/test');
      assert.deepEqual(options, { timeoutMs: 90_000 });
      return {
        ok: true,
        success: true,
        status: 'connected',
        detail: 'Provider reachable. Structured tool probe succeeded.',
        capabilityEvidence: [{ name: 'tools', declared: true, observed: true, state: 'verified' }],
        toolsReady: true,
        toolProbeStatus: 'verified',
      };
    },
  };

  const result = await testProviderCommand(context);

  assert.equal(result.ok, true);
  assert.equal(savedResult.toolsReady, true);
  assert.equal(savedResult.toolProbeStatus, 'verified');
  assert.deepEqual(savedResult.capabilityEvidence, [
    { name: 'tools', declared: true, observed: true, state: 'verified' },
  ]);
});

test('testProviderCommand keeps a resolved API key out of the provider payload', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.providerStore.getResolvedConfig = async () => ({
    ...context.providerStore.getConfig(),
    apiKey: 'sk-resolved-test-key',
  });
  context.sidecarClient = {
    async postJson(_port, requestPath, body) {
      assert.equal(requestPath, '/provider/test');
      assert.equal(body.apiKey, 'sk-resolved-test-key');
      assert.equal(Object.hasOwn(body.provider, 'apiKey'), false);
      return {
        ok: true,
        success: true,
        status: 'connected',
        detail: 'Provider reachable. Chat probe succeeded.',
      };
    },
  };

  const result = await testProviderCommand(context);
  assert.equal(result.ok, true);
});

test('testProviderCommand uses the managed workspace context for the sidecar probe', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const managedContextId = 'context-provider-123';
  const context = createContext(undefined, {
    status: 'managed',
    contextId: managedContextId,
    canonicalProjectPath: 'f:\\trainer-a',
    rootId: 'root-provider',
    projectId: 'project-provider',
  });
  let requestBody;
  context.sidecarClient = {
    async postJson(_port, requestPath, body) {
      assert.equal(requestPath, '/provider/test');
      requestBody = body;
      return {
        ok: true,
        success: true,
        status: 'connected',
        detail: 'Provider connected.',
      };
    },
  };

  const result = await testProviderCommand(context);

  assert.equal(result.ok, true);
  assert.equal(requestBody.workspace_id, managedContextId);
});

test('testProviderCommand keeps inconclusive zh-CN integrity as a warning instead of a fake green state', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        return {
          ok: false,
          configured: true,
          api_key_supplied: true,
          reachable: true,
          success: false,
          status: 'language_probe_inconclusive',
          provider_name: 'Local Compatible',
          detail:
            'Language integrity probe was inconclusive. The provider replied, but it did not preserve the mixed CJK/ASCII probe text exactly enough for Trainer to trust it.',
          diagnostics: ['Language integrity probe was inconclusive.'],
          error_category: 'language_probe_inconclusive',
          retryable: false,
          status_code: 200,
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };

  const result = await testProviderCommand(context);
  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /zh-cn integrity is not fully verified yet/i);
  assert.doesNotMatch(result.message ?? '', /connected\./i);
});

test('testProviderCommand keeps reachable auth failures distinct from network failures', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.sidecarClient = {
    async postJson(port, requestPath) {
      if (requestPath === '/provider/test') {
        return {
          ok: false,
          configured: true,
          api_key_supplied: true,
          reachable: true,
          success: false,
          status: 'invalid_key_or_permission',
          provider_name: 'MiniMax Gateway',
          detail: 'Provider rejected the API key or permissions. Check the key, scope, and model access.',
          diagnostics: ['Chat probe failed.'],
          error_category: 'invalid_key_or_permission',
          retryable: false,
          status_code: 401,
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
  };

  const result = await testProviderCommand(context);
  assert.equal(result.ok, false);
  assert.match(result.message ?? '', /responded, but Trainer still cannot use it yet/i);
  assert.doesNotMatch(result.message ?? '', /could not be reached/i);
  assert.doesNotMatch(result.message ?? '', /该令牌状态不可用/);
});

test('diagnoseProviderCommand maps diagnostics payload into provider view state', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { diagnoseProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.providerStore.getResolvedConfig = function getResolvedConfig() {
    return {
      name: 'Local Compatible',
      profileId: 'local-compatible',
      baseUrl: 'http://localhost:1234/v1',
      model: 'demo-model',
      apiKeyRef: 'trainer.default',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: true,
        tools: false,
        jsonSchema: false,
        streaming: true,
      },
    };
  };
  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      if (requestPath === '/provider/test') {
        assert.equal(body.workspace_id, 'F:\\trainer-a');
        assert.equal(body.api_key_ref, 'trainer.default');
        assert.equal(body.apiKey, 'sk-test');
        return {
          ok: true,
          detail: 'Diagnostics complete.',
          provider_name: 'Local Compatible',
          profile_id: 'local-compatible',
          protocol: 'openai_chat_completions_compatible',
          protocol_family: 'openai',
          base_url: 'http://localhost:1234/v1',
          credential_mode: 'workspace_secret',
          workspace_secret_configured: true,
          api_key_supplied: true,
          configured: true,
          protocol_diagnostic: {
            protocol: 'openai_chat_completions_compatible',
            protocol_family: 'openai',
            base_url: 'http://localhost:1234/v1',
            transport: 'direct',
            endpoint_hint: '/v1/chat/completions',
            supported: true,
            notes: ['Compatible mode assumes an OpenAI-style chat.completions surface.'],
          },
          available_models: ['demo-model', 'demo-model-mini'],
          resolved_model: 'demo-model',
          task_binding_diagnostics: [
            {
              task_binding_key: 'coach_reply',
              alias: 'coach-fast',
              resolved_model: 'demo-model',
              fallback_aliases: ['coach-deep'],
              required_capabilities: ['streaming', 'jsonSchema'],
              missing_capabilities: [],
              supported: true,
              notes: ['Task binding resolves to the active coach model.'],
            },
          ],
          model_capabilities: {
            'demo-model': {
              chat: true,
              responses: true,
              vision: false,
              embeddings: false,
              tools: true,
              jsonSchema: true,
              streaming: true,
            },
          },
          model_diagnostics: [
            {
              model: 'demo-model',
              aliases: ['coach-fast'],
              task_bindings: ['coach_reply'],
              capabilities: {
                chat: true,
                responses: true,
                vision: false,
                embeddings: false,
                tools: true,
                jsonSchema: true,
                streaming: true,
              },
              missing_capabilities: [],
              supported: true,
              notes: ['Model supports the active task bindings.'],
            },
          ],
          model_test: {
            ok: true,
            detail: 'Live probe succeeded.',
            provider_reachable: true,
            model_supported: true,
            protocol: 'openai_chat_completions_compatible',
            protocol_family: 'openai',
            resolved_model: 'demo-model',
            task_binding_key: 'coach_reply',
            task_binding_supported: true,
            model_capabilities: {
              'demo-model': {
                chat: true,
                responses: true,
                vision: false,
                embeddings: false,
                tools: true,
                jsonSchema: true,
                streaming: true,
              },
            },
            diagnostics_summary: 'Live probe succeeded.',
          },
          model_listing: {
            ok: true,
            detail: 'Model list refreshed.',
            available_models: ['demo-model', 'demo-model-mini'],
            resolved_model: 'demo-model',
            resolved_from_input: true,
            listed: true,
            retryable: false,
            diagnostics: ['Model list refreshed.'],
            cache_hit: false,
            protocol: 'openai_chat_completions_compatible',
            protocol_family: 'openai',
            model_capabilities: {
              'demo-model': {
                chat: true,
                responses: true,
                vision: false,
                embeddings: false,
                tools: true,
                jsonSchema: true,
                streaming: true,
              },
            },
            task_binding_key: 'coach_reply',
            diagnostics_summary: 'Model list refreshed.',
          },
          diagnostics: ['Protocol family: openai', 'Endpoint hint: /v1/chat/completions'],
          warnings: ['No models listed from provider.'],
        };
      }
      throw new Error(`Unexpected POST ${requestPath}`);
    },
    async getJson(port, requestPath) {
      assert.equal(requestPath, '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-1');
      return {
        memory: {
          provider_diagnostics: [
            {
              provider_fingerprint: 'local-compatible|http://localhost:1234/v1|demo-model',
              provider_name: 'Local Compatible',
              protocol: 'openai_chat_completions_compatible',
              protocol_family: 'openai',
              base_url: 'http://localhost:1234/v1',
              model: 'demo-model',
              credential_mode: 'workspace_secret',
              workspace_secret_configured: true,
              status: 'diagnostics',
              ok: true,
              detail: 'Diagnostics complete.',
              notes: ['Protocol family: openai'],
              capability_summary: ['streaming', 'jsonSchema'],
              task_binding_summary: ['coach_reply -> demo-model'],
              checked_at: '2026-06-12T00:00:00.000Z',
            },
          ],
        },
      };
    },
  };

  const result = await diagnoseProviderCommand(context);
  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /Diagnostics complete/i);
  assert.equal(context.__patches.length, 2);
  assert.equal(context.__patches[0].providerConfig.protocolDiagnostic.supported, true);
  assert.equal(context.__patches[0].providerConfig.taskBindingDiagnostics[0].taskBindingKey, 'coach_reply');
  assert.equal(context.__patches[0].providerConfig.taskBindingDiagnostics[0].fallbackAliases[0], 'coach-deep');
  assert.equal(
    context.__patches[0].providerConfig.modelCapabilities['demo-model'].jsonSchema,
    true,
  );
  assert.equal(context.__patches[0].providerConfig.profileId, 'local-compatible');
  assert.equal(context.__patches[0].providerConfig.modelDiagnostics[0].model, 'demo-model');
  assert.equal(context.__patches[0].providerConfig.modelDiagnostics[0].taskBindings[0], 'coach_reply');
  assert.equal(context.__patches[0].providerConfig.modelTest.ok, true);
  assert.equal(context.__patches[0].providerConfig.modelTest.taskBindingKey, 'coach_reply');
  assert.equal(context.__patches[0].providerConfig.modelListing.listed, true);
  assert.equal(context.__patches[0].providerConfig.modelListing.taskBindingKey, 'coach_reply');
  assert.equal(context.__patches[0].providerConfig.credentialMode, 'workspace_secret');
  assert.equal(context.__patches[0].providerConfig.workspaceSecretConfigured, true);
  assert.equal(context.__patches[1].memory.providerDiagnostics[0].providerFingerprint, 'local-compatible|http://localhost:1234/v1|demo-model');
  assert.equal(context.__patches[1].memory.providerDiagnostics[0].providerName, 'Local Compatible');
  assert.equal(context.__patches[1].memory.providerDiagnostics[0].protocolFamily, 'openai');
  assert.equal(context.__patches[1].memory.providerDiagnostics[0].credentialMode, 'workspace_secret');
  assert.equal(context.__patches[1].memory.providerDiagnostics[0].workspaceSecretConfigured, true);
  assert.deepEqual(context.__patches[1].memory.providerDiagnostics[0].capabilitySummary, ['streaming', 'jsonSchema']);
  assert.deepEqual(
    context.__patches[1].memory.providerDiagnostics[0].taskBindingSummary,
    ['coach_reply -> demo-model'],
  );
});

test('diagnoseProviderCommand preserves profile and model state when sidecar returns ProviderTestResponse fields only', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { diagnoseProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.providerStore.getResolvedConfig = function getResolvedConfig() {
    return {
      name: 'Profile Gateway',
      profileId: 'profile-gateway',
      baseUrl: 'http://localhost:4321/v1',
      model: 'profile-model',
      apiKeyRef: 'trainer.profile',
      availableModels: ['profile-model', 'fallback-model'],
      modelCapabilities: {
        'profile-model': { chat: true, responses: true, streaming: true },
      },
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: false,
        tools: false,
        jsonSchema: false,
        streaming: true,
      },
    };
  };
  context.sidecarClient = {
    async postJson(port, requestPath) {
      assert.equal(requestPath, '/provider/test');
      return {
        ok: true,
        detail: 'Provider reachable.',
        reachable: true,
        model_supported: true,
        diagnostics: [],
      };
    },
    async getJson() {
      return { memory: { provider_diagnostics: [] } };
    },
  };

  const result = await diagnoseProviderCommand(context);

  assert.equal(result.ok, true);
  const provider = context.__patches[0].providerConfig;
  assert.equal(provider.profileId, 'profile-gateway');
  assert.equal(provider.baseUrl, 'http://localhost:4321/v1');
  assert.deepEqual(provider.availableModels, ['profile-model', 'fallback-model']);
  assert.equal(provider.modelCapabilities['profile-model'].streaming, true);
  assert.deepEqual(provider.taskBindingDiagnostics, []);
  assert.deepEqual(provider.modelDiagnostics, []);
});

test('diagnoseProviderCommand skips memory refresh before workspace admission is complete or its root is absent', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { diagnoseProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);

  const blockedAdmissions = [
    { label: 'root-missing', status: 'root-missing' },
    { label: 'project-found', status: 'project-found' },
    { label: 'ignored', status: 'ignored' },
    { label: 'missing root', status: undefined, root: undefined },
  ];
  for (const blockedAdmission of blockedAdmissions) {
    const context = createContext(undefined, blockedAdmission.status);
    if (blockedAdmission.label === 'missing root') {
      context.trainerWorkspace = {
        getRoot() {
          return undefined;
        },
      };
    }
    const requestPaths = [];
    context.sidecarClient = {
      async postJson(_port, requestPath) {
        requestPaths.push(requestPath);
        assert.equal(requestPath, '/provider/test');
        return {
          ok: true,
          detail: `Diagnostics complete while workspace admission is ${blockedAdmission.label}.`,
        };
      },
      async getJson(_port, requestPath) {
        requestPaths.push(requestPath);
        throw new Error(`Unexpected memory refresh: ${requestPath}`);
      },
    };

    const result = await diagnoseProviderCommand(context);

    assert.equal(result.ok, true, blockedAdmission.label);
    assert.deepEqual(requestPaths, ['/provider/test'], blockedAdmission.label);
    assert.equal(context.__patches.length, 1, blockedAdmission.label);
    assert.ok(context.__patches[0].providerConfig, blockedAdmission.label);
    assert.equal(Object.hasOwn(context.__patches[0], 'memory'), false, blockedAdmission.label);
  }
});

test('testProviderCommand sends the SecretStorage apiKey to the local sidecar without exposing it in patches', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.providerStore = {
    getResolvedConfig() {
      return {
        name: 'Remote Compatible',
        baseUrl: 'https://example.com/v1',
        model: 'demo-model',
        protocol: 'openai_chat_completions_compatible',
        apiKeyRef: 'trainer.remote',
        credentialMode: 'workspace_secret',
        capabilities: {
          chat: true,
          responses: true,
          vision: false,
          embeddings: true,
          tools: false,
          jsonSchema: false,
          streaming: true,
        },
        apiKey: 'sk-local-fallback',
      };
    },
    async getApiKey() {
      return 'sk-local-fallback';
    },
    getConfig() {
      return {
        name: 'Remote Compatible',
        baseUrl: 'https://example.com/v1',
        model: 'demo-model',
        protocol: 'openai_chat_completions_compatible',
        apiKeyRef: 'trainer.remote',
        credentialMode: 'workspace_secret',
        capabilities: {
          chat: true,
          responses: true,
          vision: false,
          embeddings: true,
          tools: false,
          jsonSchema: false,
          streaming: true,
        },
      };
    },
    async saveLastTestResult() {
      return undefined;
    },
    getLastTestResult() {
      return undefined;
    },
  };
  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      assert.equal(requestPath, '/provider/test');
      assert.equal(body.workspace_id, 'F:\\trainer-a');
      assert.equal(body.api_key_ref, 'trainer.remote');
      assert.equal(body.apiKey, 'sk-local-fallback');
      return {
        ok: true,
        configured: true,
        api_key_supplied: true,
        reachable: true,
        success: true,
        status: 'connected',
        provider_name: 'Remote Compatible',
        detail: 'Connected.',
      };
    },
  };

  const result = await testProviderCommand(context);
  assert.equal(result.ok, true);
  assert.doesNotMatch(JSON.stringify(context.__patches), /sk-local-fallback/);
});

test('testProviderCommand can probe an alternate protocol without mutating the active profile state', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  const savedResults = [];
  context.providerStore = {
    getResolvedConfig() {
      return {
        name: 'Local Compatible',
        protocol: 'openai_chat_completions_compatible',
        baseUrl: 'http://localhost:1234/v1',
        model: 'demo-model',
        apiKeyRef: 'trainer.default',
        capabilities: {
          chat: true,
          responses: true,
          vision: false,
          embeddings: true,
          tools: false,
          jsonSchema: false,
          streaming: true,
        },
      };
    },
    async getApiKey() {
      return 'sk-test';
    },
    getConfig() {
      return {
        name: 'Local Compatible',
        protocol: 'openai_chat_completions_compatible',
        baseUrl: 'http://localhost:1234/v1',
        model: 'demo-model',
        apiKeyRef: 'trainer.default',
        capabilities: {
          chat: true,
          responses: true,
          vision: false,
          embeddings: true,
          tools: false,
          jsonSchema: false,
          streaming: true,
        },
      };
    },
    async saveLastTestResult(config, result) {
      savedResults.push({ config, result });
      return result;
    },
    getLastTestResult() {
      return undefined;
    },
  };
  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      assert.equal(requestPath, '/provider/test');
      assert.equal(body.provider.protocol, 'anthropic_messages');
      assert.equal(body.workspace_id, 'F:\\trainer-a');
      assert.equal(body.apiKey, 'sk-test');
      return {
        ok: true,
        configured: true,
        api_key_supplied: true,
        reachable: true,
        success: true,
        status: 'connected',
        provider_name: 'Local Compatible',
        detail: 'Connected.',
        protocol: 'anthropic_messages',
        protocol_family: 'anthropic',
      };
    },
  };

  const result = await testProviderCommand(context, { protocol: 'anthropic_messages' });
  assert.equal(result.ok, true);
  assert.equal(context.__patches.length, 0);
  assert.equal(savedResults.length, 0);
});

test('diagnoseProviderCommand sends the SecretStorage apiKey to the local sidecar without exposing it in patches', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { diagnoseProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.providerStore = {
    getResolvedConfig() {
      return {
        name: 'Remote Compatible',
        baseUrl: 'https://example.com/v1',
        model: 'demo-model',
        apiKeyRef: 'trainer.remote',
        credentialMode: 'workspace_secret',
        capabilities: {
          chat: true,
          responses: true,
          vision: false,
          embeddings: true,
          tools: false,
          jsonSchema: false,
          streaming: true,
        },
        apiKey: 'sk-local-fallback',
      };
    },
    async getApiKey() {
      return 'sk-local-fallback';
    },
    getConfig() {
      return {
        name: 'Remote Compatible',
        baseUrl: 'https://example.com/v1',
        model: 'demo-model',
        apiKeyRef: 'trainer.remote',
        credentialMode: 'workspace_secret',
        capabilities: {
          chat: true,
          responses: true,
          vision: false,
          embeddings: true,
          tools: false,
          jsonSchema: false,
          streaming: true,
        },
      };
    },
    async saveLastTestResult() {
      return undefined;
    },
    getLastTestResult() {
      return undefined;
    },
  };
  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      assert.equal(requestPath, '/provider/test');
      assert.equal(body.workspace_id, 'F:\\trainer-a');
      assert.equal(body.api_key_ref, 'trainer.remote');
      assert.equal(body.apiKey, 'sk-local-fallback');
      return {
        ok: true,
        detail: 'Diagnostics complete.',
        provider_name: 'Remote Compatible',
        profile_id: 'remote-compatible',
        protocol: 'openai_chat_completions_compatible',
        protocol_family: 'openai',
        base_url: 'https://example.com/v1',
        workspace_secret_configured: false,
        api_key_supplied: true,
        configured: true,
        protocol_diagnostic: {
          protocol: 'openai_chat_completions_compatible',
          protocol_family: 'openai',
          base_url: 'https://example.com/v1',
          transport: 'direct',
          endpoint_hint: '/v1/chat/completions',
          supported: true,
          notes: [],
        },
        available_models: ['demo-model'],
        resolved_model: 'demo-model',
        diagnostics: [],
        warnings: [],
      };
    },
    async getJson(port, requestPath) {
      assert.equal(requestPath, '/memory/summary?workspace_id=F%3A%5Ctrainer-a&session_id=session-1');
      return { memory: { provider_diagnostics: [] } };
    },
  };

  const result = await diagnoseProviderCommand(context);
  assert.equal(result.ok, true);
  assert.equal(context.__patches[0].providerConfig.workspaceSecretConfigured, false);
  assert.doesNotMatch(JSON.stringify(context.__patches), /sk-local-fallback/);
});

test('switchProviderProfileCommand rehydrates host state from the active profile config', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { switchProviderProfileCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const syncCalls = [];
  const synced = [];
  const context = createContext();
  context.providerStore = {
    async switchActiveProfile(profileId, reason) {
      syncCalls.push(['switch', profileId, reason]);
      return true;
    },
    getActiveProfileConfig() {
      return {
        name: 'Anthropic',
        label: 'Anthropic',
        protocol: 'anthropic_messages',
        baseUrl: 'https://api.anthropic.com',
        model: 'claude-sonnet-4-20250514',
        apiKeyRef: 'anthropic.default',
        capabilities: {
          chat: true,
          responses: false,
          vision: true,
          embeddings: false,
          tools: true,
          jsonSchema: false,
          streaming: true,
        },
        modelCapabilities: {
          'claude-sonnet-4-20250514': {
            chat: true,
            responses: false,
            vision: true,
            embeddings: false,
            tools: true,
            jsonSchema: false,
            streaming: true,
          },
        },
        profileId: 'anthropic-profile',
        profileLabel: 'Anthropic',
        profileMode: 'direct',
        profileCount: 2,
        providerProfiles: [
          {
            id: 'openai-profile',
            label: 'OpenAI',
            protocol: 'openai_responses',
            model: 'gpt-4.1-mini',
            mode: 'direct',
          },
          {
            id: 'anthropic-profile',
            label: 'Anthropic',
            protocol: 'anthropic_messages',
            model: 'claude-sonnet-4-20250514',
            mode: 'direct',
          },
        ],
      };
    },
    getConfig() {
      throw new Error('stale workspace override should not be used after switching profiles');
    },
    async getApiKey() {
      return undefined;
    },
    async syncWorkspaceProviderOverride(config) {
      syncCalls.push(['sync', config]);
    },
  };
  context.workbench = {
    async syncState() {
      synced.push(true);
    },
  };

  const result = await switchProviderProfileCommand(context, { profileId: 'anthropic-profile' });

  assert.equal(result.ok, true);
  assert.deepEqual(syncCalls[0], ['switch', 'anthropic-profile', 'manual_switch']);
  assert.equal(syncCalls[1][0], 'sync');
  assert.equal(syncCalls[1][1].profileId, 'anthropic-profile');
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__patches[0].providerConfig.name, 'Anthropic');
  assert.equal(context.__patches[0].providerConfig.profileId, 'anthropic-profile');
  assert.equal(
    context.__patches[0].providerConfig.modelCapabilities['claude-sonnet-4-20250514'].vision,
    true,
  );
  assert.equal(synced.length, 1);
});

test('switchProviderProfileCommand auto-refreshes models and restores resolved-model limits for the activated profile', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { switchProviderProfileCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const syncCalls = [];
  const savedConfigs = [];
  const savedCaches = [];
  const synced = [];
  let activeConfig = {
    name: 'MiniMax',
    label: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://47.107.101.18:3000/v1',
    model: 'MiniMax-M3',
    apiKeyRef: 'minimax.default',
    availableModels: ['MiniMax-M3'],
    contextWindowTokens: 64000,
    maxOutputTokens: 8000,
    modelTokenLimits: {
      'MiniMax-M3': {
        contextWindowTokens: 64000,
        maxOutputTokens: 8000,
      },
    },
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    profileId: 'minimax-profile',
    profileLabel: 'MiniMax',
    profileMode: 'direct',
    profileCount: 1,
    providerProfiles: [
      {
        id: 'minimax-profile',
        label: 'MiniMax',
        protocol: 'openai_chat_completions_compatible',
        model: 'MiniMax-M3',
        mode: 'direct',
      },
    ],
  };
  const context = createContext();
  context.providerStore = {
    async switchActiveProfile(profileId, reason) {
      syncCalls.push(['switch', profileId, reason]);
      return true;
    },
    getActiveProfileConfig() {
      return activeConfig;
    },
    getConfig() {
      return activeConfig;
    },
    async getApiKey() {
      return 'sk-minimax';
    },
    async syncWorkspaceProviderOverride(config) {
      syncCalls.push(['sync', config]);
    },
    async saveConfig(config) {
      savedConfigs.push(config);
      activeConfig = { ...activeConfig, ...config };
    },
    async saveModelCache(config, payload) {
      savedCaches.push({ config, payload });
      return {
        ...payload,
        fetchedAt: payload.fetchedAt ?? '2026-07-01T10:00:00.000Z',
        expiresAt: '2026-07-01T22:00:00.000Z',
      };
    },
    getModelCache() {
      return undefined;
    },
    isModelCacheFresh() {
      return false;
    },
    isModelCacheCompatible() {
      return false;
    },
    getLastTestResult() {
      return undefined;
    },
  };
  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      assert.equal(port, 34891);
      assert.equal(requestPath, '/provider/models');
      assert.equal(body.provider.model, 'MiniMax-M3');
      return {
        ok: true,
        detail: 'Fetched 2 models. Resolved configured model to MiniMax-M2.7-highspeed.',
        available_models: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
        resolved_model: 'MiniMax-M2.7-highspeed',
        model_token_limits: {
          'MiniMax-M2.7-highspeed': {
            context_window_tokens: 128000,
            max_output_tokens: 12000,
          },
        },
      };
    },
  };
  context.workbench = {
    async syncState() {
      synced.push(true);
    },
  };

  const result = await switchProviderProfileCommand(context, { profileId: 'minimax-profile' });

  assert.equal(result.ok, true);
  assert.deepEqual(syncCalls[0], ['switch', 'minimax-profile', 'manual_switch']);
  assert.equal(savedConfigs.length, 1);
  assert.equal(savedConfigs[0].model, 'MiniMax-M2.7-highspeed');
  assert.equal(savedConfigs[0].contextWindowTokens, 128000);
  assert.equal(savedConfigs[0].maxOutputTokens, 12000);
  assert.equal(
    savedConfigs[0].modelTokenLimits['MiniMax-M2.7-highspeed'].contextWindowTokens,
    128000,
  );
  assert.equal(savedCaches.length, 1);
  assert.equal(savedCaches[0].payload.modelTokenLimits['MiniMax-M2.7-highspeed'].contextWindowTokens, 128000);
  assert.equal(syncCalls[2][0], 'sync');
  assert.equal(syncCalls[2][1].model, 'MiniMax-M2.7-highspeed');
  assert.equal(syncCalls[2][1].contextWindowTokens, 128000);
  assert.equal(context.__patches.length, 1);
  assert.equal(context.__patches[0].providerConfig.model, 'MiniMax-M2.7-highspeed');
  assert.equal(context.__patches[0].providerConfig.contextWindowTokens, 128000);
  assert.equal(context.__patches[0].providerConfig.maxOutputTokens, 12000);
  assert.deepEqual(
    context.__patches[0].providerConfig.availableModels,
    ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
  );
  assert.equal(synced.length, 1);
});

test('switchProviderProfileCommand keeps newer model and connection choices when an earlier lookup finishes late', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { switchProviderProfileCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const initialConfig = {
    name: 'First connection',
    label: 'First connection',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://first.example.test/v1',
    model: 'first-model',
    apiKeyRef: 'first-profile-key',
    capabilities: {
      chat: true,
      responses: true,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    profileId: 'shared-profile',
    profileLabel: 'Shared profile',
    profileMode: 'direct',
  };
  let activeConfig = initialConfig;
  let activeApiKey = 'first-test-key';
  let releaseLookup;
  let markLookupStarted;
  const lookupStarted = new Promise((resolve) => {
    markLookupStarted = resolve;
  });
  const lookupResponse = new Promise((resolve) => {
    releaseLookup = resolve;
  });
  const savedConfigs = [];
  const workbenchSyncs = [];
  const context = createContext();
  context.providerStore = {
    async switchActiveProfile(profileId) {
      assert.equal(profileId, 'shared-profile');
      activeConfig = initialConfig;
      activeApiKey = 'first-test-key';
      return true;
    },
    getActiveProfileConfig() {
      return activeConfig;
    },
    getConfig() {
      return activeConfig;
    },
    getProfileRegistrySnapshot() {
      return { activeProfileId: activeConfig.profileId };
    },
    async getApiKey() {
      return activeApiKey;
    },
    async syncWorkspaceProviderOverride() {
      return undefined;
    },
    async saveConfig(config) {
      savedConfigs.push(config);
      activeConfig = config;
    },
    async saveModelCache(_config, payload) {
      return {
        ...payload,
        fetchedAt: payload.fetchedAt ?? '2026-07-17T00:00:00.000Z',
        expiresAt: '2026-07-17T12:00:00.000Z',
      };
    },
    getModelCache() {
      return undefined;
    },
    isModelCacheFresh() {
      return false;
    },
    isModelCacheCompatible() {
      return false;
    },
    getLastTestResult() {
      return undefined;
    },
  };
  context.sidecarClient = {
    async postJson(port, requestPath, body) {
      assert.equal(port, 34891);
      assert.equal(requestPath, '/provider/models');
      assert.equal(body.provider.model, 'first-model');
      markLookupStarted();
      return lookupResponse;
    },
  };
  context.workbench = {
    async syncState() {
      workbenchSyncs.push(true);
    },
  };

  const pendingSwitch = switchProviderProfileCommand(context, { profileId: 'shared-profile' });
  await lookupStarted;

  activeConfig = {
    ...initialConfig,
    baseUrl: 'https://newer.example.test/v1',
    model: 'newer-model',
    apiKeyRef: 'newer-profile-key',
  };
  activeApiKey = 'newer-test-key';
  releaseLookup({
    ok: true,
    detail: 'Fetched models for the first connection.',
    available_models: ['first-model', 'first-model-latest'],
    resolved_model: 'first-model-latest',
  });

  const result = await pendingSwitch;

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /kept your newer choice/i);
  assert.equal(result.data.profileId, 'shared-profile');
  assert.equal(result.data.baseUrl, 'https://newer.example.test/v1');
  assert.equal(result.data.model, 'newer-model');
  assert.equal(savedConfigs.length, 0);
  assert.equal(context.__patches.length, 0);
  assert.equal(workbenchSyncs.length, 0);
});

test('createProviderProfileFromDraftCommand stores the current draft as a reusable profile', async () => {
  const { createProviderProfileFromDraftCommand } = loadWithVscodeMock(providerCommandsModulePath, {});
  const synced = [];
  let createdConfigArg;
  let createdApiKeyArg;
  let createdReasonArg;
  const context = createContext();
  context.providerStore = {
    getResolvedConfig() {
      return {
        name: 'MiniMax',
        label: 'MiniMax',
        protocol: 'openai_chat_completions_compatible',
        baseUrl: 'http://47.107.101.18:3000/v1',
        model: 'MiniMax-M3',
        apiKeyRef: 'minimax.default',
        credentialMode: 'ui_proxy',
        availableModels: ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
        contextWindowTokens: 64000,
        maxOutputTokens: 8000,
        modelTokenLimits: {
          'MiniMax-M3': {
            contextWindowTokens: 64000,
            maxOutputTokens: 8000,
          },
          'MiniMax-M2.7-highspeed': {
            contextWindowTokens: 128000,
            maxOutputTokens: 12000,
          },
        },
        requestDefaults: {
          extra_body: {
            thinking: {
              type: 'disabled',
            },
          },
        },
        taskBindings: {
          coach_reply: {
            alias: 'coach-fast',
          },
        },
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
        modelCapabilities: {
          'MiniMax-M3': {
            chat: true,
            responses: true,
            vision: false,
            embeddings: false,
            tools: false,
            jsonSchema: false,
            structuredOutput: false,
            streaming: true,
          },
        },
      };
    },
    async getApiKey() {
      return 'sk-copied';
    },
    async createProfileFromConfig(config, apiKey, reason) {
      createdConfigArg = config;
      createdApiKeyArg = apiKey;
      createdReasonArg = reason;
      return {
        ...config,
        profileId: 'minimax-profile',
        profileLabel: 'MiniMax',
        profileCount: 1,
        providerProfiles: [
          {
            id: 'minimax-profile',
            label: 'MiniMax',
            protocol: 'openai_chat_completions_compatible',
            model: 'MiniMax-M2.7-highspeed',
            mode: 'direct',
          },
        ],
      };
    },
    getLastTestResult() {
      return {
        ok: true,
        status: 'connected',
        detail: 'Provider reachable. Chat probe succeeded.',
        checkedAt: '2026-06-30T00:00:00.000Z',
        providerName: 'MiniMax',
        baseUrl: 'http://47.107.101.18:3000/v1',
        model: 'MiniMax-M2.7-highspeed',
      };
    },
  };
  context.workbench = {
    async syncState() {
      synced.push(true);
    },
  };

  const result = await createProviderProfileFromDraftCommand(context, {
    name: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://47.107.101.18:3000/v1',
    model: 'MiniMax-M2.7-highspeed',
  });

  assert.equal(result.ok, true);
  assert.equal(createdApiKeyArg, 'sk-copied');
  assert.equal(createdReasonArg, 'manual_create_from_draft');
  assert.deepEqual(createdConfigArg.availableModels, ['MiniMax-M2.7-highspeed', 'MiniMax-M3']);
  assert.equal(createdConfigArg.contextWindowTokens, 128000);
  assert.equal(createdConfigArg.maxOutputTokens, 12000);
  assert.equal(
    createdConfigArg.modelTokenLimits['MiniMax-M2.7-highspeed'].contextWindowTokens,
    128000,
  );
  assert.deepEqual(createdConfigArg.requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
  assert.equal(context.__patches[0].providerConfig.profileId, 'minimax-profile');
  assert.equal(context.__patches[0].providerConfig.model, 'MiniMax-M2.7-highspeed');
  assert.equal(context.__patches[0].providerConfig.lastTestResult.status, 'connected');
  assert.equal(context.__patches[0].connection.provider.model, 'MiniMax-M2.7-highspeed');
  assert.equal(synced.length, 1);
});

test('createProviderProfileFromTemplateCommand creates and activates a template profile', async () => {
  const pickedTemplates = [];
  const vscodeMock = {
    window: {
      async showQuickPick(items) {
        pickedTemplates.push(items);
        return items[0];
      },
      async showInputBox() {
        return 'sk-template';
      },
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { createProviderProfileFromTemplateCommand } = loadWithVscodeMock(
    providerCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  const patches = [];
  const syncedConfigs = [];
  const created = [];
  const switched = [];
  let currentConfig = {
    name: 'OpenAI',
    label: 'OpenAI',
    protocol: 'openai_responses',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyRef: 'openai.default',
    credentialMode: 'ui_proxy',
    model: 'gpt-4.1-mini',
    capabilities: {
      chat: true,
      responses: true,
      vision: true,
      embeddings: false,
      tools: true,
      jsonSchema: true,
      streaming: true,
    },
    profileId: 'openai-template',
    profileLabel: 'OpenAI',
    profileMode: 'direct',
    profileCount: 1,
    profileHistory: [],
    providerProfiles: [
      {
        id: 'openai-template',
        label: 'OpenAI',
        protocol: 'openai_responses',
        model: 'gpt-4.1-mini',
        mode: 'direct',
      },
    ],
  };
  context.providerStore = {
    ...context.providerStore,
    async createProfileFromTemplate(templateIndex, apiKey) {
      created.push([templateIndex, apiKey]);
      return {
        id: 'openai-template',
        label: 'OpenAI',
        protocol: 'openai_responses',
        mode: 'direct',
        credentialMode: 'ui_proxy',
        baseUrl: 'https://api.openai.com/v1',
        apiKeyRef: 'openai.default',
        model: 'gpt-4.1-mini',
        catalogSource: 'provider_live',
        cacheTtlSeconds: 43200,
        modelAliases: {},
        availableModels: [],
        allowedModels: [],
        deniedModels: [],
        taskBindings: {},
        requestDefaults: {},
        capabilities: currentConfig.capabilities,
        modelCapabilities: {},
      };
    },
    async switchActiveProfile(profileId, reason) {
      switched.push([profileId, reason]);
      currentConfig = {
        ...currentConfig,
        profileId,
      };
      return true;
    },
    async getResolvedConfig() {
      return currentConfig;
    },
    async getApiKey() {
      return 'sk-template';
    },
    getConfig() {
      return currentConfig;
    },
    async syncWorkspaceProviderOverride(config) {
      syncedConfigs.push(config);
    },
  };
  context.patchWorkbenchData = async function patchWorkbenchData(patch) {
    patches.push(patch);
  };

  const result = await createProviderProfileFromTemplateCommand(context);

  assert.equal(result.ok, true);
  assert.equal(pickedTemplates.length, 1);
  assert.match(pickedTemplates[0][0].description, /API key now or later/);
  assert.match(pickedTemplates[0][0].detail, /change the model later/i);
  assert.equal(created.length, 1);
  assert.deepEqual(created[0], [0, 'sk-template']);
  assert.deepEqual(switched[0], ['openai-template', 'template_create']);
  assert.equal(syncedConfigs.length, 1);
  assert.equal(syncedConfigs[0].profileId, 'openai-template');
  assert.equal(patches.length, 1);
});

test('createProviderProfileFromTemplateCommand shows workspace_secret as the remote default', async () => {
  const pickedTemplates = [];
  const vscodeMock = {
    window: {
      async showQuickPick(items) {
        pickedTemplates.push(items);
        return items[0];
      },
      async showInputBox() {
        return 'sk-template';
      },
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { createProviderProfileFromTemplateCommand } = loadWithVscodeMock(
    providerCommandsModulePath,
    vscodeMock,
  );
  const context = createContext({
    workspaceFolder: 'F:\\trainer-a',
    remoteName: 'ssh-remote',
    isRemoteWorkspace: true,
  });
  context.providerStore = {
    ...context.providerStore,
    async createProfileFromTemplate() {
      return {
        id: 'remote-template',
        label: 'OpenAI',
        protocol: 'openai_responses',
        mode: 'direct',
        credentialMode: 'workspace_secret',
        baseUrl: 'https://api.openai.com/v1',
        apiKeyRef: 'openai.default',
        model: 'gpt-4.1-mini',
        catalogSource: 'provider_live',
        cacheTtlSeconds: 43200,
        modelAliases: {},
        availableModels: [],
        allowedModels: [],
        deniedModels: [],
        taskBindings: {},
        requestDefaults: {},
        capabilities: {
          chat: true,
          responses: true,
          vision: true,
          embeddings: false,
          tools: true,
          jsonSchema: true,
          streaming: true,
        },
        modelCapabilities: {},
      };
    },
    async switchActiveProfile() {
      return true;
    },
    async getResolvedConfig() {
      return {
        name: 'OpenAI',
        label: 'OpenAI',
        protocol: 'openai_responses',
        baseUrl: 'https://api.openai.com/v1',
        apiKeyRef: 'openai.default',
        credentialMode: 'workspace_secret',
        model: 'gpt-4.1-mini',
        capabilities: {
          chat: true,
          responses: true,
          vision: true,
          embeddings: false,
          tools: true,
          jsonSchema: true,
          streaming: true,
        },
        profileId: 'remote-template',
        profileLabel: 'OpenAI',
        profileMode: 'direct',
        profileCount: 1,
        profileHistory: [],
        providerProfiles: [],
      };
    },
    async getApiKey() {
      return 'sk-template';
    },
    getConfig() {
      return {
        name: 'OpenAI',
        label: 'OpenAI',
        protocol: 'openai_responses',
        baseUrl: 'https://api.openai.com/v1',
        apiKeyRef: 'openai.default',
        credentialMode: 'workspace_secret',
        model: 'gpt-4.1-mini',
        capabilities: {
          chat: true,
          responses: true,
          vision: true,
          embeddings: false,
          tools: true,
          jsonSchema: true,
          streaming: true,
        },
        profileId: 'remote-template',
        profileLabel: 'OpenAI',
        profileMode: 'direct',
        profileCount: 1,
        profileHistory: [],
        providerProfiles: [],
      };
    },
    async syncWorkspaceProviderOverride() {
      return undefined;
    },
  };
  context.patchWorkbenchData = async function patchWorkbenchData() {
    return undefined;
  };

  const result = await createProviderProfileFromTemplateCommand(context);

  assert.equal(result.ok, true);
  assert.equal(pickedTemplates.length, 1);
  assert.match(pickedTemplates[0][0].description, /API key now or later/);
  assert.match(pickedTemplates[0][0].detail, /change the model later/i);
});

test('createProviderProfileFromTemplateCommand treats dismissed native setup prompts as cancellation', async () => {
  const pickerDismissedMock = {
    window: {
      async showQuickPick() {
        return undefined;
      },
      async showInputBox() {
        throw new Error('The API key prompt should not open after dismissing the template picker');
      },
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { createProviderProfileFromTemplateCommand: dismissPicker } = loadWithVscodeMock(
    providerCommandsModulePath,
    pickerDismissedMock,
  );

  const pickerResult = await dismissPicker(createContext());

  assert.equal(pickerResult.ok, false);
  assert.equal(pickerResult.cancelled, true);

  const keyDismissedMock = {
    window: {
      async showQuickPick(items) {
        return items.find((item) => item.label === 'MiniMax');
      },
      async showInputBox() {
        return undefined;
      },
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { createProviderProfileFromTemplateCommand: dismissKey } = loadWithVscodeMock(
    providerCommandsModulePath,
    keyDismissedMock,
  );

  const keyResult = await dismissKey(createContext());

  assert.equal(keyResult.ok, false);
  assert.equal(keyResult.cancelled, true);
});

test('createProviderProfileFromTemplateCommand applies a webview-selected MiniMax template without native setup prompts', async () => {
  let quickPickCalls = 0;
  let apiKeyPromptCalls = 0;
  const vscodeMock = {
    window: {
      async showQuickPick() {
        quickPickCalls += 1;
        throw new Error('showQuickPick should not run when the template is preselected');
      },
      async showInputBox() {
        apiKeyPromptCalls += 1;
        throw new Error('showInputBox should not run when the webview will collect the API key');
      },
      async showWarningMessage() {
        return undefined;
      },
      async showInformationMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { createProviderProfileFromTemplateCommand } = loadWithVscodeMock(
    providerCommandsModulePath,
    vscodeMock,
  );
  const context = createContext();
  const created = [];
  const switched = [];
  let currentConfig = {
    name: 'MiniMax',
    label: 'MiniMax',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'https://api.minimaxi.com/v1',
    apiKeyRef: 'minimax.default',
    credentialMode: 'ui_proxy',
    model: 'MiniMax-M3',
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: false,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
    profileId: 'minimax-template',
    profileLabel: 'MiniMax',
    profileMode: 'direct',
    profileCount: 1,
    profileHistory: [],
    providerProfiles: [],
  };
  context.providerStore = {
    ...context.providerStore,
    async createProfileFromTemplate(templateIndex, apiKey) {
      created.push([templateIndex, apiKey]);
      return {
        id: 'minimax-template',
        label: 'MiniMax',
        protocol: 'openai_chat_completions_compatible',
        mode: 'direct',
        credentialMode: 'ui_proxy',
        baseUrl: 'https://api.minimaxi.com/v1',
        apiKeyRef: 'minimax.default',
        model: 'MiniMax-M3',
        catalogSource: 'provider_live',
        cacheTtlSeconds: 43200,
        modelAliases: {
          'coach-fast': 'MiniMax-M2.7-highspeed',
        },
        availableModels: [],
        allowedModels: [],
        deniedModels: [],
        taskBindings: {},
        requestDefaults: {
          extra_body: {
            thinking: {
              type: 'disabled',
            },
          },
        },
        capabilities: currentConfig.capabilities,
        modelCapabilities: {},
      };
    },
    async switchActiveProfile(profileId, reason) {
      switched.push([profileId, reason]);
      currentConfig = {
        ...currentConfig,
        profileId,
      };
      return true;
    },
    async getResolvedConfig() {
      return currentConfig;
    },
    async getApiKey() {
      return undefined;
    },
    getConfig() {
      return currentConfig;
    },
    async syncWorkspaceProviderOverride() {
      return undefined;
    },
  };
  context.patchWorkbenchData = async function patchWorkbenchData() {
    return undefined;
  };

  const result = await createProviderProfileFromTemplateCommand(context, {
    templateLabel: 'MiniMax',
    skipPicker: true,
  });

  assert.equal(result.ok, true);
  assert.equal(quickPickCalls, 0);
  assert.equal(apiKeyPromptCalls, 0);
  assert.equal(created.length, 1);
  assert.equal(created[0][1], '');
  assert.deepEqual(switched[0], ['minimax-template', 'template_create']);
  assert.deepEqual(result.ui, { focusProviderApiKey: true });
});

test('configureProviderCommand does not seed protocol-default capability picks', async () => {
  const pickedStates = [];
  const vscodeMock = {
    window: {
      async showInputBox(options) {
        switch (options.title) {
          case 'Provider name':
            return 'OpenAI';
          case 'Base URL':
            return 'https://api.openai.com/v1';
          case 'Chat model':
            return 'gpt-4.1-mini';
          case 'Context window tokens':
          case 'Max output tokens':
            return '';
          case 'API key (leave blank to keep current or store none)':
            return '';
          default:
            return '';
        }
      },
      async showQuickPick(items) {
        pickedStates.push(items.map((item) => ({ label: item.label, picked: item.picked })));
        return items.filter((item) => item.picked);
      },
      async showInformationMessage() {
        return undefined;
      },
    },
  };
  const { configureProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  context.providerStore = {
    getConfig() {
      return undefined;
    },
    async saveConfig() {
      return undefined;
    },
    async getApiKey() {
      return undefined;
    },
  };
  context.patchWorkbenchData = async () => undefined;
  context.workbench = {
    async syncState() {
      return undefined;
    },
  };

  const result = await configureProviderCommand(context);

  assert.equal(result.ok, true);
  assert.ok(pickedStates.length > 0);
  // Fail-closed / last-test-only: no protocol-default theater pre-picks.
  assert.deepEqual(pickedStates[0], [
    { label: 'chat', picked: false },
    { label: 'responses', picked: false },
    { label: 'vision', picked: false },
    { label: 'embeddings', picked: false },
    { label: 'tools', picked: false },
    { label: 'jsonSchema', picked: false },
    { label: 'structuredOutput', picked: false },
    { label: 'streaming', picked: false },
  ]);
});

test('configureProviderCommand preserves existing requestDefaults when rewriting provider settings', async () => {
  const vscodeMock = {
    window: {
      async showInputBox(options) {
        switch (options.title) {
          case 'Provider name':
            return 'OpenAI';
          case 'Base URL':
            return 'https://api.openai.com/v1';
          case 'Chat model':
            return 'gpt-4.1-mini';
          case 'Context window tokens':
          case 'Max output tokens':
            return '';
          case 'API key (leave blank to keep current or store none)':
            return '';
          default:
            return '';
        }
      },
      async showQuickPick(items) {
        return items.filter((item) => item.picked);
      },
      async showInformationMessage() {
        return undefined;
      },
    },
  };
  const { configureProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const savedConfigs = [];
  const context = createContext();
  context.providerStore = {
    getConfig() {
      return {
        name: 'OpenAI',
        baseUrl: 'https://api.openai.com/v1',
        model: 'gpt-4.1-mini',
        apiKeyRef: 'openai.default',
        requestDefaults: {
          extra_body: {
            thinking: {
              type: 'disabled',
            },
          },
        },
        capabilities: {
          chat: true,
          responses: true,
          vision: true,
          embeddings: false,
          tools: true,
          jsonSchema: true,
          streaming: true,
        },
      };
    },
    async saveConfig(config) {
      savedConfigs.push(config);
    },
    async getApiKey() {
      return undefined;
    },
  };
  context.patchWorkbenchData = async () => undefined;
  context.workbench = {
    async syncState() {
      return undefined;
    },
  };

  const result = await configureProviderCommand(context);

  assert.equal(result.ok, true);
  assert.deepEqual(savedConfigs[0].requestDefaults, {
    extra_body: {
      thinking: {
        type: 'disabled',
      },
    },
  });
});

test('testProviderCommand probes an unsaved draft without mutating the saved provider', async () => {
  const vscodeMock = {
    window: {
      async showInformationMessage() {
        return undefined;
      },
      async showWarningMessage() {
        return undefined;
      },
      async showErrorMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  let savedTestResults = 0;
  let sidecarStarts = 0;
  let requestBody;
  context.providerStore = {
    async getResolvedConfig() {
      return {
        name: 'Saved Provider',
        baseUrl: 'https://saved.example/v1',
        model: 'saved-model',
        protocol: 'openai_chat_completions_compatible',
        apiKeyRef: 'saved.provider',
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
      savedTestResults += 1;
    },
    getLastTestResult() {
      return undefined;
    },
  };
  context.sidecarManager = {
    async ensureRunning() {
      sidecarStarts += 1;
      return { lifecycle: 'ready', port: 34891 };
    },
  };
  context.sidecarClient = {
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
  };

  const result = await testProviderCommand(context, {
    responseLanguage: 'zh-CN',
    draft: {
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://draft.example/v1',
      model: 'draft-model',
      apiKey: 'sk-draft',
    },
  });

  assert.equal(result.ok, true);
  assert.equal(sidecarStarts, 1);
  assert.equal(savedTestResults, 0);
  assert.equal(context.__patches.length, 0);
  assert.equal(requestBody.apiKey, 'sk-draft');
  assert.equal(requestBody.provider.name, 'Saved Provider');
  assert.equal(requestBody.provider.baseUrl, 'https://draft.example/v1');
  assert.equal(requestBody.response_language, 'zh-CN');
  assert.equal(Object.hasOwn(requestBody.provider, 'apiKey'), false);
  assert.match(result.message ?? '', /saved connection was not changed/i);
});

test('testProviderCommand refuses to reuse a saved key for a different draft endpoint', async () => {
  const vscodeMock = {
    window: {
      async showWarningMessage() {
        return undefined;
      },
    },
  };
  const { testProviderCommand } = loadWithVscodeMock(providerCommandsModulePath, vscodeMock);
  const context = createContext();
  let sidecarStarts = 0;
  let requests = 0;
  context.sidecarManager = {
    async ensureRunning() {
      sidecarStarts += 1;
      return { lifecycle: 'ready', port: 34891 };
    },
  };
  context.sidecarClient = {
    async postJson() {
      requests += 1;
      return { ok: true };
    },
  };

  const result = await testProviderCommand(context, {
    draft: {
      name: 'Different Endpoint',
      protocol: 'openai_chat_completions_compatible',
      baseUrl: 'https://different.example/v1',
      model: 'draft-model',
    },
  });

  assert.equal(result.ok, false);
  assert.equal(sidecarStarts, 0);
  assert.equal(requests, 0);
  assert.equal(context.__patches.length, 0);
  assert.match(result.message ?? '', /did not reuse the saved key/i);
});
