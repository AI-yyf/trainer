'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const goalCommandsPath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'goalCommands.js',
);

let moduleUnderTest;

test('setup', () => {
  moduleUnderTest = loadWithVscodeMock(goalCommandsPath, {});
});

function createContext(options = {}) {
  const posts = [];
  const patches = [];
  let trusted = options.trusted !== false;
  return {
    trustGuard: {
      async ensureTrusted() {
        return trusted;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return options.sidecarUnavailable
          ? { lifecycle: 'error', detail: 'Sidecar is unavailable.' }
          : { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async postJson(port, requestPath, body) {
        posts.push({ port, requestPath, body });
        if (options.response !== undefined) return options.response;
        return {
          ok: true,
          goal: {
            goalId: 'goal-1',
            workspaceId: body.workspace_id,
            sessionId: body.session_id,
            title: body.title ?? '实现 PPO',
            concept: '实现 PPO',
            capability: '',
            planId: null,
            stageId: null,
            status: 'active',
            source: 'user_explicit',
            currentPosition: '',
            latestActivity: null,
            activities: [],
            activityCount: 0,
            evidenceCount: 0,
            startedAt: '2026-11-08T05:00:00+00:00',
            updatedAt: '2026-11-08T05:00:00+00:00',
            lastActivityAt: null,
            completedAt: null,
          },
        };
      },
    },
    outputChannel: {
      appendLine() {},
    },
    getHostState() {
      return {
        bootstrap: { memory: { workspace: {} } },
        workspace: { workspaceFolder: '/tmp/trainer-goal-workspace' },
      };
    },
    getSessionId() {
      return 'session-goal';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __posts: posts,
    __patches: patches,
    setTrusted(value) {
      trusted = value;
    },
  };
}

test('goal start posts the server action and hydrates the host snapshot', async () => {
  const context = createContext();
  const result = await moduleUnderTest.goalControlCommand(context, {
    action: 'start',
    title: '实现 PPO',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__posts.length, 1);
  assert.equal(context.__posts[0].requestPath, '/goal/action');
  assert.deepEqual(context.__posts[0].body, {
    session_id: 'session-goal',
    workspace_id: '/tmp/trainer-goal-workspace',
    action: 'start',
    title: '实现 PPO',
  });
  assert.equal(context.__patches[0].goal.goalId, 'goal-1');
  assert.equal(context.__patches[0].goal.status, 'active');
});

test('goal complete mirrors the authoritative null goal', async () => {
  const context = createContext({ response: { ok: true, goal: null } });
  const result = await moduleUnderTest.goalControlCommand(context, {
    action: 'complete',
    goalId: 'goal-1',
  });

  assert.equal(result.ok, true);
  assert.equal(context.__posts[0].body.goal_id, 'goal-1');
  assert.ok('goal' in context.__patches[0]);
  assert.equal(context.__patches[0].goal, undefined);
});

test('invalid actions, empty titles and untrusted workspaces never reach the sidecar', async () => {
  const invalid = createContext();
  assert.equal((await moduleUnderTest.goalControlCommand(invalid, { action: 'dance' })).ok, false);
  assert.equal(invalid.__posts.length, 0);

  const empty = createContext();
  assert.equal((await moduleUnderTest.goalControlCommand(empty, { action: 'start', title: ' ' })).ok, false);
  assert.equal(empty.__posts.length, 0);

  const untrusted = createContext({ trusted: false });
  assert.equal(
    (await moduleUnderTest.goalControlCommand(untrusted, { action: 'pause' })).ok,
    false,
  );
  assert.equal(untrusted.__posts.length, 0);
});

test('an unavailable sidecar fails closed without patching goal state', async () => {
  const context = createContext({ sidecarUnavailable: true });
  const result = await moduleUnderTest.goalControlCommand(context, { action: 'pause' });
  assert.equal(result.ok, false);
  assert.equal(context.__posts.length, 0);
  assert.equal(context.__patches.length, 0);
});
