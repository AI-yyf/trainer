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
        enqueued(item) { this.runCalls.push({ state: 'enqueued', id: item.id }); },
        started(item) { this.runCalls.push({ state: 'started', id: item.id }); },
        skipped(item) { this.runCalls.push({ state: 'skipped', id: item.id }); },
        errored(item, message) { this.runCalls.push({ state: 'errored', id: item.id, message }); },
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
    undeliveredNotices: [],
  };
  const rejectQueue = Array.isArray(overrides.rejectPostSequence)
    ? [...overrides.rejectPostSequence]
    : undefined;
  const ensureRunningQueue = Array.isArray(overrides.ensureRunningStatuses)
    ? [...overrides.ensureRunningStatuses]
    : undefined;
  const runtime = {
    sidecarClient: {
      postJson(port, requestPath, body) {
        calls.posts.push({ port, path: requestPath, body });
        const rejection = rejectQueue
          ? rejectQueue.shift()
          : overrides.rejectPost;
        if (rejection) {
          return Promise.reject(rejection);
        }
        return Promise.resolve({ ok: true });
      },
    },
    sidecarManager: {
      ensureRunning() {
        calls.ensureRunning = (calls.ensureRunning ?? 0) + 1;
        const status = ensureRunningQueue
          ? ensureRunningQueue.shift()
          : overrides.sidecarStatus;
        return Promise.resolve(status ?? { lifecycle: 'ready', port: 8765 });
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
    notifyAttestationUndelivered() {
      calls.undeliveredNotices.push('undelivered');
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

test('cached passing rows cannot attest a currently selected practice card', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const { runtime, calls } = createRuntimeMock(vscodeMock, createHostState({ trainingState: livePracticeTrainingState() }));
  const tests = new TrainerTestController(runtime);
  tests.publishReport({ dynamic_checks: [{ id: 'pytest', label: 'Pytest', status: 'passed', detail: 'old result' }] },
    vscodeMock.Uri.file('F:\\trainer\\sample.py'));
  await runAllTests(vscodeMock);
  assert.equal(calls.posts.length, 0);
  assert.equal(vscodeMock.__controller.runCalls[0].runCalls.filter(entry => entry.state === 'passed').length, 0);
});

test('cached failed rows do not run or post an attestation', async () => {
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
  assert.equal(run.runCalls.filter((entry) => entry.state === 'failed').length, 0);
  assert.equal(calls.posts.length, 0);
});

test('no live practice card means no attestation post', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const { resolveLivePracticeCardId } = loadWithVscodeMock(trainingAttestationModulePath, vscodeMock);

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

test('an ambiguous attestation failure is logged with a sanitized message and surfaced once, without retry', async () => {
  const vscodeMock = createVscodeMock();
  loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const { dispatchTestRunAttestation } = loadWithVscodeMock(trainingAttestationModulePath, vscodeMock);
  const { runtime, calls } = createRuntimeMock(vscodeMock, createHostState({ trainingState: livePracticeTrainingState() }), {
    // Secret-shaped fixture: the raw value must never reach the output channel.
    rejectPost: new Error('request failed: api_key=sk-fixture-secret-value'),
  });
  const outcome = await dispatchTestRunAttestation(runtime, { card_id: 'card-practice-1', passed: true, evidence_source: 'test_runner' });
  assert.equal(outcome, 'undelivered');
  // Ambiguous failure (no connect-class error code): no automatic resend.
  assert.equal(calls.posts.length, 1);
  assert.equal(calls.logs.length, 1);
  assert.match(calls.logs[0], /training-attestation/);
  assert.match(calls.logs[0], /ambiguous/);
  // The diagnostic message is logged, but secret-shaped values are redacted.
  assert.equal(calls.logs[0].includes('sk-fixture-secret-value'), false);
  assert.match(calls.logs[0], /request failed/);
  // The failure is never silent: the caller's undelivered notice fires.
  assert.equal(calls.undeliveredNotices.length, 1);
});

test('a connect-class failure is retried once and the resend delivers without a notice', async () => {
  const vscodeMock = createVscodeMock();
  loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const { dispatchTestRunAttestation } = loadWithVscodeMock(trainingAttestationModulePath, vscodeMock);
  const refused = Object.assign(new Error('connect ECONNREFUSED 127.0.0.1:8765'), { code: 'ECONNREFUSED' });
  const { runtime, calls } = createRuntimeMock(vscodeMock, createHostState({ trainingState: livePracticeTrainingState() }), {
    rejectPostSequence: [refused],
  });
  const outcome = await dispatchTestRunAttestation(runtime, { card_id: 'card-practice-1', passed: true, evidence_source: 'test_runner' });
  assert.equal(outcome, 'delivered');
  assert.equal(calls.posts.length, 2);
  assert.equal(calls.undeliveredNotices.length, 0);
  assert.equal(calls.logs.length, 1);
  assert.match(calls.logs[0], /not_arrived/);
});

test('a pre-send readiness failure retries after the sidecar recovers', async () => {
  const vscodeMock = createVscodeMock();
  loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const { dispatchTestRunAttestation } = loadWithVscodeMock(trainingAttestationModulePath, vscodeMock);
  const { runtime, calls } = createRuntimeMock(vscodeMock, createHostState({ trainingState: livePracticeTrainingState() }), {
    ensureRunningStatuses: [{ lifecycle: 'error', detail: 'Sidecar exited before readiness (code=1)' }],
  });
  const outcome = await dispatchTestRunAttestation(runtime, { card_id: 'card-practice-1', passed: true, evidence_source: 'test_runner' });
  assert.equal(outcome, 'delivered');
  assert.equal(calls.ensureRunning, 2);
  assert.equal(calls.posts.length, 1);
  assert.equal(calls.undeliveredNotices.length, 0);
});

test('a readiness failure that persists through the retry surfaces the undelivered notice', async () => {
  const vscodeMock = createVscodeMock();
  loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const { dispatchTestRunAttestation } = loadWithVscodeMock(trainingAttestationModulePath, vscodeMock);
  const { runtime, calls } = createRuntimeMock(vscodeMock, createHostState({ trainingState: livePracticeTrainingState() }), {
    sidecarStatus: { lifecycle: 'unavailable', detail: 'Sidecar is unavailable; training attestation not sent.' },
  });
  const outcome = await dispatchTestRunAttestation(runtime, { card_id: 'card-practice-1', passed: true, evidence_source: 'test_runner' });
  assert.equal(outcome, 'undelivered');
  assert.equal(calls.posts.length, 0);
  assert.equal(calls.ensureRunning, 2);
  assert.equal(calls.undeliveredNotices.length, 1);
});

test('the idempotency key is stable per run+card and ships on the attestation body', async () => {
  const vscodeMock = createVscodeMock();
  const { attestationIdempotencyKey, buildTestRunAttestationBody } = loadWithVscodeMock(
    trainingAttestationModulePath,
    vscodeMock,
  );

  const first = attestationIdempotencyKey({ cardId: 'card-1', runId: 'companion-session-7' });
  assert.equal(first, 'remote-verify:companion-session-7:card-1');
  // Deterministic: a resend of the same run reuses the key and replays.
  assert.equal(first, attestationIdempotencyKey({ cardId: 'card-1', runId: 'companion-session-7' }));
  // A genuinely new run gets a fresh key and records normally.
  assert.notEqual(first, attestationIdempotencyKey({ cardId: 'card-1', runId: 'companion-session-8' }));
  // Missing run identity never fabricates a key.
  assert.equal(attestationIdempotencyKey({ cardId: 'card-1', runId: '  ' }), '');

  const body = buildTestRunAttestationBody({
    card: { cardId: 'card-1' },
    summary: 'Remote verify passed',
    testsOutput: '1 passed',
    idempotencyKey: first,
  });
  assert.equal(body.idempotency_key, 'remote-verify:companion-session-7:card-1');
  const keyless = buildTestRunAttestationBody({
    card: { cardId: 'card-1' },
    summary: 'Remote verify passed',
    testsOutput: '1 passed',
  });
  assert.equal('idempotency_key' in keyless, false);
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


function freshRuntime(reportOrFunction) {
  const calls = [], logs = [];
  return { calls, logs, runtime: { outputChannel: { appendLine: line => logs.push(line) },
    evaluateFile: async uri => { calls.push(uri.fsPath); return typeof reportOrFunction === 'function'
      ? reportOrFunction(uri) : reportOrFunction; } } };
}

test('Testing Run reevaluates the file and uses fresh failures instead of old passing rows', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const f = freshRuntime({ dynamic_checks: [{ id: 'pytest', label: 'Pytest', status: 'failed', detail: 'new failure' }] });
  const tests = new TrainerTestController(f.runtime);
  tests.publishReport({ dynamic_checks: [{ id: 'pytest', label: 'Pytest', status: 'passed' }] }, vscodeMock.Uri.file('F:/trainer/sample.py'));
  await runAllTests(vscodeMock);
  assert.equal(f.calls.length, 1);
  assert.equal(vscodeMock.__controller.runCalls[0].runCalls.filter(row => row.state === 'passed').length, 0);
  assert.equal(vscodeMock.__controller.runCalls[0].runCalls.find(row => row.state === 'failed').message.value, 'new failure');
});

test('warnings and absent verifier results are skipped, never green passing tests', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const f = freshRuntime({ static_checks: [{ id: 'lint', status: 'warning' }], dynamic_checks: [{ id: 'pytest', status: 'warning' }] });
  const tests = new TrainerTestController(f.runtime);
  tests.publishReport({}, vscodeMock.Uri.file('F:/trainer/sample.py'));
  await runAllTests(vscodeMock);
  const rows = vscodeMock.__controller.runCalls[0].runCalls;
  assert.equal(rows.filter(row => row.state === 'passed').length, 0);
  assert.equal(rows.filter(row => row.state === 'skipped').length, 2);
});

test('include and exclude select only the requested file and check after a fresh report', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const report = { static_checks: [{ id: 'ruff', status: 'passed' }], dynamic_checks: [{ id: 'pytest', status: 'passed' }] };
  const f = freshRuntime(report), tests = new TrainerTestController(f.runtime);
  const first = vscodeMock.Uri.file('F:/trainer/first.py'), second = vscodeMock.Uri.file('F:/trainer/second.py');
  tests.publishReport(report, first); tests.publishReport(report, second);
  const firstRoot = vscodeMock.__controller.items.get(first.toString());
  const check = firstRoot.children.values()[1].children.values()[0];
  await vscodeMock.__controller.runHandler({ include: [check], exclude: [] });
  assert.deepEqual(f.calls, ['F:/trainer/first.py']);
  assert.deepEqual(vscodeMock.__controller.runCalls[0].runCalls.filter(row => row.state === 'enqueued').map(row => row.id), ['pytest']);
  assert.deepEqual(vscodeMock.__controller.runCalls[0].runCalls.filter(row => row.state === 'passed').map(row => row.id), ['pytest']);
  await vscodeMock.__controller.runHandler({ include: [firstRoot], exclude: [firstRoot] });
  assert.equal(f.calls.length, 1);
});

test('cancelled fresh evaluations do not report completed tests', async () => {
  const vscodeMock = createVscodeMock();
  const { TrainerTestController } = loadWithVscodeMock(testControllerModulePath, vscodeMock);
  const token = { isCancellationRequested: false };
  const f = freshRuntime(() => { token.isCancellationRequested = true; return { dynamic_checks: [{ id: 'pytest', status: 'passed' }] }; });
  const tests = new TrainerTestController(f.runtime);
  tests.publishReport({}, vscodeMock.Uri.file('F:/trainer/sample.py'));
  await vscodeMock.__controller.runHandler({ include: undefined, exclude: [] }, token);
  assert.equal(vscodeMock.__controller.runCalls[0].runCalls.filter(row => row.state === 'passed').length, 0);
  assert.equal(vscodeMock.__controller.runCalls[0].runCalls.at(-1).state, 'end');
});
