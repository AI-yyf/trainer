'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const testControllerModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'testing',
  'testController.js',
);
const trainingAttestationModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'testing',
  'trainingAttestation.js',
);

const ATTEST_PATH = '/training/verification/attest';

function createCollection() {
  const values = new Map();
  return {
    add(item) {
      values.set(item.id, item);
    },
    get(id) {
      return values.get(id);
    },
    replace(items) {
      values.clear();
      for (const item of items) {
        values.set(item.id, item);
      }
    },
    values() {
      return Array.from(values.values());
    },
    size: values.size,
    forEach(callback) {
      for (const item of values.values()) {
        callback(item, this);
      }
    },
  };
}

function createTestItem(id, label, uri) {
  return {
    id,
    label,
    uri,
    error: undefined,
    description: undefined,
    children: createCollection(),
  };
}

function createVscodeMock() {
  const controller = {
    items: createCollection(),
    createTestItem,
    runHandler: undefined,
    runCalls: [],
    createRunProfile(label, kind, runHandler) {
      this.runHandler = runHandler;
      this.runProfile = { label, kind };
    },
    createTestRun(request) {
      const run = {
        passed(item) {
          this.runCalls.push({ state: 'passed', id: item.id });
        },
        failed(item, message) {
          this.runCalls.push({ state: 'failed', id: item.id, message });
        },
        end() {
          this.runCalls.push({ state: 'end' });
        },
        runCalls: [],
      };
      controller.runCalls.push(run);
      return run;
    },
    disposeCalled: false,
    dispose() {
      this.disposeCalled = true;
    },
  };

  return {
    Uri: {
      file(filePath) {
        return {
          fsPath: filePath,
          path: filePath.replace(/\\/g, '/'),
          toString() {
            return `file://${filePath.replace(/\\/g, '/')}`;
          },
        };
      },
    },
    TestRunProfileKind: { Run: 1 },
    TestMessage: class TestMessage {
      constructor(message) {
        this.value = message;
      }
    },
    tests: {
      createTestController() {
        return controller;
      },
    },
    __controller: controller,
  };
}

function createHostState({ trainingState }) {
  return {
    workspace: {
      workspaceFolder: 'F:\\trainer',
      trusted: true,
    },
    sessionId: undefined,
    bootstrap: {
      workspaceTrainingState: trainingState,
    },
  };
}

function createRuntimeMock(vscodeMock, hostState, overrides = {}) {
  const calls = {
    posts: [],
    logs: [],
  };
  const runtime = {
    sidecarClient: {
      postJson(port, requestPath, body) {
        calls.posts.push({ port, path: requestPath, body });
        if (overrides.rejectPost) {
          return Promise.reject(overrides.rejectPost);
        }
        return Promise.resolve({ ok: true });
      },
    },
    sidecarManager: {
      ensureRunning() {
        calls.ensureRunning = (calls.ensureRunning ?? 0) + 1;
        return Promise.resolve(overrides.sidecarStatus ?? { lifecycle: 'ready', port: 8765 });
      },
    },
    outputChannel: {
      appendLine(line) {
        calls.logs.push(line);
      },
    },
    getHostState() {
      return hostState;
    },
    getSessionId() {
      return 'session-1';
    },
  };
  return { runtime, calls };
}

function livePracticeTrainingState(overrides = {}) {
  return {
    workspaceId: 'F:\\trainer',
    selectedCardId: 'card-practice-1',
    selectedCardType: 'practice',
    selectedCardTitle: 'Implement the retry helper',
    selectedCardStatus: 'implemented',
    latestLearningFocusArea: 'async error handling',
    activeTrainingCardRouting: {
      selectedCardId: 'card-practice-1',
      selectedCard: {
        cardId: 'card-practice-1',
        title: 'Implement the retry helper',
        focusArea: 'async error handling',
      },
    },
    ...overrides,
  };
}

async function flushAsyncWork() {
  for (let i = 0; i < 6; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

async function runAllTests(vscodeMock) {
  await vscodeMock.__controller.runHandler(
    { include: undefined, exclude: undefined },
    undefined,
  );
  await flushAsyncWork();
}

test('successful run with a live practice card posts a test_runner attestation', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const { resolveLivePracticeCardId } = require(trainingAttestationModulePath);
  const hostState = createHostState({ trainingState: livePracticeTrainingState() });
  const { runtime, calls } = createRuntimeMock(vscodeMock, hostState);

  const tests = new TrainerTestController(runtime);
  assert.equal(resolveLivePracticeCardId(hostState), 'card-practice-1');

  tests.publishReport(
    {
      static_checks: [{ id: 'ruff', label: 'Ruff', status: 'passed', detail: 'clean' }],
      dynamic_checks: [{ id: 'pytest', label: 'Pytest', status: 'passed', detail: '3 examples green' }],
      semantic_checks: [],
    },
    vscodeMock.Uri.file('F:\\trainer\\sample.py'),
  );

  await runAllTests(vscodeMock);

  const run = vscodeMock.__controller.runCalls[0];
  assert.deepEqual(
    run.runCalls.filter((entry) => entry.state !== 'end'),
    [
      { state: 'passed', id: 'ruff' },
      { state: 'passed', id: 'pytest' },
    ],
  );

  assert.equal(calls.posts.length, 1);
  const post = calls.posts[0];
  assert.equal(post.port, 8765);
  assert.equal(post.path, ATTEST_PATH);
  assert.deepEqual(post.body, {
    card_id: 'card-practice-1',
    passed: true,
    evidence_source: 'test_runner',
    summary: 'Test run passed: 2 test(s)',
    tests_output: 'PASS Ruff: clean PASS Pytest: 3 examples green',
    focus_area: 'async error handling',
    card_title: 'Implement the retry helper',
    session_id: 'session-1',
    // Raw Windows-style workspace id: normalizeFsPath keeps it verbatim on
    // every platform instead of joining it onto the host cwd.
    workspace_id: 'F:\\trainer',
  });
});

test('failed run does not post an attestation', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const hostState = createHostState({ trainingState: livePracticeTrainingState() });
  const { runtime, calls } = createRuntimeMock(vscodeMock, hostState);

  const tests = new TrainerTestController(runtime);
  tests.publishReport(
    {
      static_checks: [{ id: 'ruff', label: 'Ruff', status: 'passed', detail: 'clean' }],
      dynamic_checks: [{ id: 'pytest', label: 'Pytest', status: 'failed', detail: '1 failing example' }],
      semantic_checks: [],
    },
    vscodeMock.Uri.file('F:\\trainer\\sample.py'),
  );

  await runAllTests(vscodeMock);

  const run = vscodeMock.__controller.runCalls[0];
  assert.equal(run.runCalls.filter((entry) => entry.state === 'failed').length, 1);
  assert.equal(calls.posts.length, 0);
});

test('no live practice card means no attestation post', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const { resolveLivePracticeCardId } = require(trainingAttestationModulePath);

  const noCardHostState = createHostState({ trainingState: undefined });
  const closedCardHostState = createHostState({
    trainingState: livePracticeTrainingState({ selectedCardStatus: 'archived' }),
  });
  const flashCardHostState = createHostState({
    trainingState: livePracticeTrainingState({ selectedCardType: 'flash' }),
  });
  assert.equal(resolveLivePracticeCardId(noCardHostState), undefined);
  assert.equal(resolveLivePracticeCardId(closedCardHostState), undefined);
  assert.equal(resolveLivePracticeCardId(flashCardHostState), undefined);

  for (const hostState of [noCardHostState, closedCardHostState, flashCardHostState]) {
    const { runtime, calls } = createRuntimeMock(vscodeMock, hostState);
    const tests = new TrainerTestController(runtime);
    tests.publishReport(
      {
        static_checks: [{ id: 'ruff', label: 'Ruff', status: 'passed', detail: 'clean' }],
        dynamic_checks: [],
        semantic_checks: [],
      },
      vscodeMock.Uri.file('F:\\trainer\\sample.py'),
    );
    await runAllTests(vscodeMock);
    assert.equal(calls.posts.length, 0, `no post expected for ${hostState.bootstrap.workspaceTrainingState}`);
  }
});

test('attestation post rejection is swallowed, logged, and never throws', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const hostState = createHostState({ trainingState: livePracticeTrainingState() });
  const { runtime, calls } = createRuntimeMock(vscodeMock, hostState, {
    rejectPost: new Error('sidecar exploded'),
  });

  const tests = new TrainerTestController(runtime);
  tests.publishReport(
    {
      static_checks: [{ id: 'ruff', label: 'Ruff', status: 'passed', detail: 'clean' }],
      dynamic_checks: [],
      semantic_checks: [],
    },
    vscodeMock.Uri.file('F:\\trainer\\sample.py'),
  );

  await runAllTests(vscodeMock);

  assert.equal(calls.posts.length, 1);
  assert.equal(
    calls.logs.some(
      (line) =>
        line.includes('[training-attestation]') &&
        line.includes('card-practice-1') &&
        line.includes('sidecar exploded'),
    ),
    true,
    'expected the attestation failure to be logged to the output channel',
  );
});

test('attestation is skipped when the sidecar is unavailable and the failure is logged', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const hostState = createHostState({ trainingState: livePracticeTrainingState() });
  const { runtime, calls } = createRuntimeMock(vscodeMock, hostState, {
    sidecarStatus: { lifecycle: 'starting', detail: 'Sidecar is starting.' },
  });

  const tests = new TrainerTestController(runtime);
  tests.publishReport(
    {
      static_checks: [{ id: 'ruff', label: 'Ruff', status: 'passed', detail: 'clean' }],
      dynamic_checks: [],
      semantic_checks: [],
    },
    vscodeMock.Uri.file('F:\\trainer\\sample.py'),
  );

  await runAllTests(vscodeMock);

  assert.equal(calls.posts.length, 0);
  assert.equal(calls.logs.length, 1);
  assert.match(calls.logs[0], /\[training-attestation\]/);
  assert.match(calls.logs[0], /Sidecar is starting\./);
});

test('tests_output longer than the limit is truncated', async () => {
  const vscodeMock = createVscodeMock();
  const { truncateTestsOutput, TEST_RUNNER_ATTESTATION_OUTPUT_LIMIT } = require(
    trainingAttestationModulePath,
  );

  const longOutput = Array.from(
    { length: 80 },
    (_, index) => `PASS Check ${index + 1}: scenario detail line ${index + 1}`,
  ).join('\n');

  const truncated = truncateTestsOutput(longOutput);
  assert.ok(truncated.length <= TEST_RUNNER_ATTESTATION_OUTPUT_LIMIT + 1);
  assert.ok(truncated.startsWith('PASS Check 1'));
});
