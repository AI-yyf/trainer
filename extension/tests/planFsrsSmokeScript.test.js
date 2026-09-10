'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const scriptPath = path.resolve(__dirname, '..', '..', 'scripts', 'plan-fsrs-smoke.mjs');

function startMockTrainer({
  skipPlanAdvance = false,
  skipFsrs = false,
  failEvaluate = false,
} = {}) {
  const sessions = new Map();
  let sessionCounter = 0;
  let planBodies = [];
  let cardBodies = [];
  let evaluateBodies = [];

  const server = http.createServer((request, response) => {
    if (request.url === '/provider/test' && request.method === 'POST') {
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({
        ok: true,
        tools_ready: true,
      }));
      return;
    }

    if (request.url === '/session/start' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        sessionCounter += 1;
        const payload = JSON.parse(body);
        const sessionId = `session-${sessionCounter}`;
        sessions.set(sessionId, {
          workspaceId: payload.workspace_id,
          planId: null,
          cardId: null,
          evaluated: false,
        });
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({ session_id: sessionId }));
      });
      return;
    }

    if (request.url === '/plan/generate' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        planBodies.push(payload);
        const session = sessions.get(payload.session_id);
        const planId = 'plan-live-1';
        if (session) {
          session.planId = planId;
        }
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          plan: {
            id: planId,
            current_step: 'Land the first expiry slice',
            current_stage_id: 'stage-foundation',
            title: 'Trainer plan for token expiry',
          },
          memory: {
            workspace: {
              latest_plan_runtime: {
                plan_id: planId,
                current_step: 'Land the first expiry slice',
                current_stage_id: 'stage-foundation',
              },
            },
          },
        }));
      });
      return;
    }

    if (request.url === '/training/generate-card' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        cardBodies.push(payload);
        const session = sessions.get(payload.session_id);
        const card = {
          card_id: 'card-live-1',
          card_type: 'practice',
          title: 'Practice fail-closed token expiry',
        };
        if (session) {
          session.cardId = card.card_id;
        }
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          card,
          active_routing: {
            selected_card_id: card.card_id,
            selected_card: card,
          },
        }));
      });
      return;
    }

    if (request.url === '/evaluate/current-file' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        evaluateBodies.push(payload);
        const session = sessions.get(payload.session_id);
        if (session) {
          session.evaluated = true;
        }
        if (failEvaluate) {
          response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(JSON.stringify({ passed: false, summary: 'blocked' }));
          return;
        }
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          passed: true,
          summary: 'Expiry helper verified.',
          reflection: 'Empty tokens must fail closed.',
        }));
      });
      return;
    }

    if (request.url && request.url.startsWith('/memory/summary') && request.method === 'GET') {
      const url = new URL(request.url, 'http://127.0.0.1');
      const sessionId = url.searchParams.get('session_id') || '';
      const session = sessions.get(sessionId) || {};
      const planId = session.planId || 'plan-live-1';
      const cardId = session.cardId || 'card-live-1';
      const advanced = session.evaluated && !skipPlanAdvance;
      const fsrs = session.evaluated && !skipFsrs
        ? {
          [cardId]: {
            reps: 1,
            state: 'learning',
            stability: 1.2,
            difficulty: 5.0,
          },
        }
        : {};
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({
        memory: {
          workspace: {
            latest_plan_runtime: {
              plan_id: planId,
              current_step: advanced
                ? 'Add one expiry regression check'
                : 'Land the first expiry slice',
              current_stage_id: advanced ? 'stage-practice' : 'stage-foundation',
            },
            latest_training_fsrs_states: fsrs,
          },
        },
        plan_runtime_status: {
          verify_plan_advance: advanced
            ? {
              advanced: true,
              plan_id: planId,
              what: 'Advanced after verify',
              why: 'Evaluator ack',
              next: 'Add one expiry regression check',
            }
            : { advanced: false },
        },
      }));
      return;
    }

    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end(`unexpected ${request.method} ${request.url}`);
  });

  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        server,
        port,
        planBodies,
        cardBodies,
        evaluateBodies,
        close: () => new Promise((closeResolve, closeReject) => {
          server.close((error) => {
            if (error) {
              closeReject(error);
              return;
            }
            closeResolve();
          });
        }),
      });
    });
  });
}

function runSmoke(env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [scriptPath], {
      env: {
        ...process.env,
        ...env,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('error', reject);
    child.on('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

function parseLastJson(text) {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      return JSON.parse(lines[index]);
    } catch {
      // keep scanning
    }
  }
  return null;
}

test('plan-fsrs smoke script exists', () => {
  assert.equal(fs.existsSync(scriptPath), true);
});

test('plan-fsrs smoke passes plan advance + FSRS write-back on mock sidecar', async () => {
  const mock = await startMockTrainer();
  try {
    const result = await runSmoke({
      TRAINER_PLAN_FSRS_SMOKE_SIDECAR_URL: `http://127.0.0.1:${mock.port}`,
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_BASE_URL: 'http://127.0.0.1:9/v1',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_API_KEY: 'sk-test-not-a-real-key',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_MODEL: 'gpt-test',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_PROTOCOL: 'openai_chat_completions_compatible',
    });
    const report = parseLastJson(result.stdout);
    assert.equal(result.code, 0, result.stderr || result.stdout);
    assert.equal(report?.ok, true);
    assert.equal(report?.checks?.plan_stage_change, 'passed');
    assert.equal(report?.checks?.fsrs_writeback, 'passed');
    assert.equal(report?.checks?.session_continuity, 'passed');
    assert.equal(report?.sessionContinuity?.preserved, true);
    assert.ok(Number(report?.elapsedMs) >= 0);
    assert.equal(mock.planBodies.length, 1);
    assert.equal(mock.cardBodies.length, 1);
    assert.equal(mock.evaluateBodies.length, 1);
    assert.equal(mock.evaluateBodies[0].training_card_id, 'card-live-1');
    assert.ok(!JSON.stringify(report).includes('sk-test-not-a-real-key'));
  } finally {
    await mock.close();
  }
});

test('plan-fsrs smoke fails honestly when FSRS write-back is missing', async () => {
  const mock = await startMockTrainer({ skipFsrs: true });
  try {
    const result = await runSmoke({
      TRAINER_PLAN_FSRS_SMOKE_SIDECAR_URL: `http://127.0.0.1:${mock.port}`,
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_BASE_URL: 'http://127.0.0.1:9/v1',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_API_KEY: 'sk-test-not-a-real-key',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_MODEL: 'gpt-test',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_PROTOCOL: 'openai_chat_completions_compatible',
    });
    const report = parseLastJson(result.stderr) || parseLastJson(result.stdout);
    assert.notEqual(result.code, 0);
    assert.equal(report?.ok, false);
    assert.equal(report?.step, 'fsrs_writeback');
    assert.equal(report?.category, 'fsrs_schedule_missing');
  } finally {
    await mock.close();
  }
});

test('plan-fsrs smoke fails honestly when plan does not advance', async () => {
  const mock = await startMockTrainer({ skipPlanAdvance: true });
  try {
    const result = await runSmoke({
      TRAINER_PLAN_FSRS_SMOKE_SIDECAR_URL: `http://127.0.0.1:${mock.port}`,
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_BASE_URL: 'http://127.0.0.1:9/v1',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_API_KEY: 'sk-test-not-a-real-key',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_MODEL: 'gpt-test',
      TRAINER_PLAN_FSRS_SMOKE_PROVIDER_PROTOCOL: 'openai_chat_completions_compatible',
    });
    const report = parseLastJson(result.stderr) || parseLastJson(result.stdout);
    assert.notEqual(result.code, 0);
    assert.equal(report?.ok, false);
    assert.equal(report?.step, 'plan_stage_change');
    assert.equal(report?.category, 'plan_did_not_advance');
  } finally {
    await mock.close();
  }
});
