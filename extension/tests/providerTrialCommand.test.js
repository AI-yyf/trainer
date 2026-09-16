'use strict';

const test = require('node:test');
const { after } = require('node:test');
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

const { disposeTrialProviderServer } = require(
  path.resolve(__dirname, '..', 'dist', 'extension', 'src', 'provider', 'trialProviderServer.js'),
);

after(async () => {
  // The trial service keeps the event loop alive; close it so node --test exits.
  await disposeTrialProviderServer();
});

function createContext() {
  const patches = [];
  const profile = {
    id: 'trial-profile-1',
    label: 'Trainer Practice (Local)',
    name: 'trainer-practice-local',
    protocol: 'openai_chat_completions_compatible',
    baseUrl: 'http://127.0.0.1:0/v1',
    model: 'trainer-trial-model',
    apiKeyRef: 'trainer.trial.default',
    mode: 'direct',
    capabilities: {
      chat: true,
      responses: false,
      vision: false,
      embeddings: true,
      tools: false,
      jsonSchema: false,
      streaming: true,
    },
  };
  const context = {
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
        return '/tmp/trainer-workspace';
      },
    },
    sidecarClient: {
      postRequests: [],
      async postJson(_port, requestPath, body) {
        this.postRequests.push({ requestPath, body });
        if (requestPath === '/provider/test') {
          return {
            ok: true,
            success: true,
            status: 'connected',
            detail: 'Practice service reachable.',
          };
        }
        return undefined;
      },
    },
    providerStore: {
      createdProfile: profile,
      templateCalls: [],
      switchCalls: [],
      async createProfileFromTemplate(templateIndex, apiKey, overrides) {
        this.templateCalls.push({ templateIndex, apiKey, overrides });
        return { ...this.createdProfile, ...overrides };
      },
      async switchActiveProfile(profileId, reason) {
        this.switchCalls.push({ profileId, reason });
        return true;
      },
      getResolvedConfig() {
        return { ...profile };
      },
      getConfig() {
        return { ...profile };
      },
      async getApiKey() {
        return 'trial-key';
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
          providerConfig: { configured: false },
          memory: {
            weakSpots: [],
            recentWins: [],
            dueReviews: [],
            teachingObservations: [],
            memoryEvidence: [],
            learningOutcomes: [],
            providerDiagnostics: [],
          },
          connection: {},
        },
        sidecar: { lifecycle: 'ready', port: 34891, host: '127.0.0.1', canStart: true },
        workspace: { workspaceFolder: '/tmp/trainer-a' },
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
  return context;
}

test('startProviderTrialCommand derives a local profile from the template, activates and verifies it', async () => {
  const { startProviderTrialCommand } = loadWithVscodeMock(providerCommandsModulePath, {
    window: {
      async showInformationMessage() {},
      async showWarningMessage() {},
      async showErrorMessage() {},
    },
  });
  const context = createContext();

  const result = await startProviderTrialCommand(context);

  assert.equal(result.ok, true);
  assert.match(result.message, /[Pp]ractice mode/);
  assert.match(result.message, /127\.0\.0\.1/);

  const templateCall = context.providerStore.templateCalls[0];
  assert.equal(templateCall.templateIndex, 5, 'trial derives from the local-compatible template');
  assert.match(templateCall.apiKey, /^trial-/);
  assert.equal(templateCall.overrides.label, 'Trainer Practice (Local)');
  assert.match(templateCall.overrides.baseUrl, /^http:\/\/127\.0\.0\.1:\d+\/v1$/);
  assert.equal(templateCall.overrides.model, 'trainer-trial-model');
  assert.equal(templateCall.overrides.catalogSource, 'manual');

  assert.deepEqual(context.providerStore.switchCalls, [
    { profileId: 'trial-profile-1', reason: 'zero_config_trial' },
  ]);
  assert.ok(
    context.sidecarClient.postRequests.some((request) => request.requestPath === '/provider/test'),
    'trial must verify the connection so the composer unblocks',
  );
  const providerPatch = context.__patches.find((patch) => patch.providerConfig);
  assert.ok(providerPatch, 'trial patches the provider view');
  assert.equal(providerPatch.providerConfig.model, 'trainer-trial-model');
  assert.equal(result.data.profileId, 'trial-profile-1');
});

test('startProviderTrialCommand reports failure when the practice service cannot start', async () => {
  const { startProviderTrialCommand } = loadWithVscodeMock(providerCommandsModulePath, {
    window: {
      async showInformationMessage() {},
      async showWarningMessage() {},
      async showErrorMessage() {},
    },
  });
  const context = createContext();
  context.providerStore.createProfileFromTemplate = async () => undefined;

  const result = await startProviderTrialCommand(context);

  assert.equal(result.ok, false);
  assert.match(result.message, /could not create the local practice profile/i);
  assert.equal(context.providerStore.switchCalls.length, 0);
});
