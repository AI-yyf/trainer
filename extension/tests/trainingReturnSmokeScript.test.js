'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const scriptPath = path.resolve(__dirname, '..', '..', 'scripts', 'training-return-smoke.mjs');
const smokePowerShellPath = path.resolve(__dirname, '..', '..', 'scripts', 'smoke.ps1');

function startMockTrainer({
  corruptPassReturn = false,
  passNextHopStatus = 'continued_in_chat',
  evaluationFailureBody = '',
} = {}) {
  const sessions = new Map();
  const turnBodies = [];
  const trainingCardBodies = [];
  const evaluateBodies = [];
  const reflectBodies = [];
  const returnBodies = [];
  let sessionCounter = 0;

  const server = http.createServer((request, response) => {
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
          workspace: null,
        });
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({ session_id: sessionId }));
      });
      return;
    }

    if (request.url === '/turn' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        turnBodies.push(payload);
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(
          JSON.stringify({
            coach_turn: {
              scenario: 'remote_workspace',
            },
            reply: {
              content: 'I will keep this learn-first and use one real remote workspace checkpoint.',
            },
            snapshot: {
              memory: {},
            },
          }),
        );
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
        trainingCardBodies.push(payload);
        const card = {
          card_id: `explicit-card-${trainingCardBodies.length}`,
          card_type: 'practice',
          scenario_pack: 'remote_workspace',
          title: 'Practice: Verify the remote workspace boundary',
        };
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
      if (evaluationFailureBody) {
        response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
        response.end(evaluationFailureBody);
        return;
      }
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        evaluateBodies.push(payload);
        const session = sessions.get(payload.session_id);
        const isBlocked = Array.isArray(payload.diagnostics)
          && payload.diagnostics.some((item) => String(item).toLowerCase().includes('[error]'));

        const passedWorkspace = {
          selected_card_status: 'active',
          latest_learning_verified_result: 'Implementation satisfies the available signals.',
          latest_learning_blocker: '',
          latest_training_handoff: {
            handoff_id: `handoff-${payload.session_id}`,
            continue_in: 'training',
            accepted_into: 'training',
          },
          latest_training_next_hop: {
            continue_in: 'training',
            accepted_into: 'training',
            status: 'reflection_required',
          },
        };
        const blockedWorkspace = {
          selected_card_status: 'blocked',
          latest_learning_verified_result: '',
          latest_learning_blocker: 'Fix the VS Code diagnostics attached to the current file, then re-run evaluation.',
          latest_training_handoff: {
            continue_in: 'training',
            accepted_into: 'training',
          },
          latest_training_next_hop: {
            continue_in: 'training',
            accepted_into: 'training',
            status: 'blocked',
          },
        };
        session.workspace = isBlocked ? blockedWorkspace : passedWorkspace;

        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(
          JSON.stringify({
            passed: !isBlocked,
            summary: !isBlocked
              ? 'Implementation satisfies the available signals.'
              : 'Evaluation failed on: vscode-diagnostics.',
            next_step: !isBlocked
              ? 'Return to Coach and route the next training card.'
              : 'Fix the VS Code diagnostics attached to the current file, then re-run evaluation.',
            reflection: !isBlocked
              ? 'The practice card has verified evidence.'
              : 'The practice card still has a verification blocker.',
            static_checks: [],
            dynamic_checks: [],
            semantic_checks: [],
          }),
        );
      });
      return;
    }

    if (request.url === '/training/reflect' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        reflectBodies.push(payload);
        const session = [...sessions.values()].find((candidate) => candidate.workspaceId === payload.workspace_id);
        session.workspace.latest_training_handoff = {
          ...session.workspace.latest_training_handoff,
          handoff_id: payload.handoff_id,
          continue_in: 'training',
          accepted_into: 'training',
          handoff_status: 'ready_to_return',
        };
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({ ok: true, workspace: session.workspace }));
      });
      return;
    }

    if (request.url === '/training/return' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        returnBodies.push(payload);
        const session = [...sessions.values()].find((candidate) => candidate.workspaceId === payload.workspace_id);
        session.workspace = {
          ...session.workspace,
          selected_card_status: 'implemented',
          latest_training_handoff: {
            handoff_id: payload.handoff_id,
            continue_in: corruptPassReturn ? 'training' : 'chat',
            accepted_into: corruptPassReturn ? 'training' : 'coach',
          },
          latest_training_next_hop: {
            continue_in: corruptPassReturn ? 'training' : 'chat',
            accepted_into: corruptPassReturn ? 'training' : 'coach',
            status: corruptPassReturn ? 'blocked' : passNextHopStatus,
          },
        };
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({ ok: true, workspace: session.workspace }));
      });
      return;
    }

    if (request.url && request.url.startsWith('/memory/summary') && request.method === 'GET') {
      const url = new URL(request.url, 'http://127.0.0.1');
      const sessionId = url.searchParams.get('session_id');
      const session = sessions.get(sessionId);
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(
        JSON.stringify({
          memory: {
            workspace: session ? session.workspace : null,
          },
        }),
      );
      return;
    }

    response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ error: 'not found' }));
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      resolve({
        sidecarUrl: `http://127.0.0.1:${address.port}`,
        turnBodies,
        trainingCardBodies,
        evaluateBodies,
        reflectBodies,
        returnBodies,
        close: () =>
          new Promise((closeResolve, closeReject) => {
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

function runSmokeScript(envOverrides = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [scriptPath], {
      env: {
        ...process.env,
        TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_BASE_URL: 'http://provider.example/v1',
        TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_API_KEY: 'sk-test',
        TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_MODEL: 'MiniMax-M3',
        TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_PROTOCOL: 'openai_chat_completions_compatible',
        ...envOverrides,
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
    child.once('error', reject);
    child.once('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

test('training return smoke script stays env-driven and never hardcodes the hidden trainer gateway', () => {
  const source = fs.readFileSync(scriptPath, 'utf8');

  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_BASE_URL/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_API_KEY/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_MODEL/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_PROTOCOL/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_RESPONSE_LANGUAGE/);
  assert.match(source, /\/training\/reflect/);
  assert.match(source, /\/training\/return/);
  assert.match(source, /\/training\/generate-card/);
  assert.match(source, /chat_training_routing_absent/);
  assert.match(source, /continued_in_chat/);
  assert.match(source, /Blocked practice verification did not stay in Training/);
  assert.doesNotMatch(source, /47\.107\.101\.18/);
});

test('training return smoke script passes when verified practice returns to Coach and blocked practice stays in Training', async () => {
  const trainer = await startMockTrainer();

  try {
    const result = await runSmokeScript({
      TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.checks.passReturn, 'passed');
    assert.equal(report.checks.failBlock, 'passed');
    assert.equal(trainer.turnBodies.length, 2);
    assert.equal(trainer.trainingCardBodies.length, 2);
    assert.equal(trainer.evaluateBodies.length, 2);
    assert.equal(trainer.reflectBodies.length, 1);
    assert.equal(trainer.returnBodies.length, 1);
    assert.equal(trainer.turnBodies[0].provider.baseUrl, 'http://provider.example/v1');
    assert.equal(trainer.turnBodies[0].provider.model, 'MiniMax-M3');
    assert.equal(trainer.turnBodies[0].provider.protocol, 'openai_chat_completions_compatible');
    assert.equal(trainer.trainingCardBodies[0].card_type, 'practice');
    assert.equal(trainer.trainingCardBodies[0].focus_area, 'VS Code remote workspace');
    assert.equal(trainer.evaluateBodies[0].expected_symbols[0], 'ok');
    assert.match(trainer.evaluateBodies[0].content, /def test_ok\(\)/);
    assert.equal(Array.isArray(trainer.evaluateBodies[1].diagnostics), true);
    assert.match(trainer.evaluateBodies[1].diagnostics[0], /\[error\]/);
  } finally {
    await trainer.close();
  }
});

test('training return smoke script can pass through anthropic_messages protocol without OpenAI-only request defaults', async () => {
  const trainer = await startMockTrainer();

  try {
    const result = await runSmokeScript({
      TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
      TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_PROTOCOL: 'anthropic_messages',
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.providerProtocol, 'anthropic_messages');
    assert.equal(trainer.turnBodies[0].provider.protocol, 'anthropic_messages');
    assert.equal('requestDefaults' in trainer.turnBodies[0].provider, false);
  } finally {
    await trainer.close();
  }
});

test('training return smoke script accepts the newer accepted handoff status when Coach return semantics are already correct', async () => {
  const trainer = await startMockTrainer({ passNextHopStatus: 'accepted' });

  try {
    const result = await runSmokeScript({
      TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.checks.passReturn, 'passed');
  } finally {
    await trainer.close();
  }
});

test('training return smoke script fails when a successful practice verification still points back to Training', async () => {
  const trainer = await startMockTrainer({ corruptPassReturn: true });

  try {
    const result = await runSmokeScript({
      TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
    });

    assert.equal(result.code, 1);
    const report = JSON.parse(result.stderr);
    assert.equal(report.ok, false);
    assert.equal(report.category, 'pass_handoff_mismatch');
    assert.equal(report.step, 'pass_summary');
    assert.equal(report.error, 'Smoke check failed. See step and category.');
  } finally {
    await trainer.close();
  }
});

test('training return smoke script redacts a failed evaluation response body', async () => {
  const secret = 'training-return-upstream-secret';
  const trainer = await startMockTrainer({ evaluationFailureBody: secret });

  try {
    const result = await runSmokeScript({
      TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
    });

    assert.equal(result.code, 1);
    const report = JSON.parse(result.stderr);
    assert.equal(report.step, 'pass_evaluate');
    assert.equal(report.category, 'evaluation_request_failed');
    assert.equal(report.status, 500);
    assert.equal(report.responseBodyRedacted, true);
    assert.equal('preview' in report, false);
    assert.doesNotMatch(result.stderr, new RegExp(secret));
  } finally {
    await trainer.close();
  }
});

test('smoke.ps1 exposes an opt-in training return smoke gate with sidecar and provider controls', () => {
  const source = fs.readFileSync(smokePowerShellPath, 'utf8');

  assert.match(source, /\[switch\]\$TrainingReturnSmoke/);
  assert.match(source, /\[string\]\$TrainingReturnSmokeSidecarUrl/);
  assert.match(source, /\[string\]\$TrainingReturnSmokeApiKey/);
  assert.match(source, /\[string\]\$TrainingReturnSmokeBaseUrl/);
  assert.match(source, /\[string\]\$TrainingReturnSmokeModel/);
  assert.match(source, /\[string\]\$TrainingReturnSmokeProtocol/);
  assert.match(source, /\[string\]\$TrainingReturnSmokeResponseLanguage/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_API_KEY/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_BASE_URL/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_MODEL/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_PROTOCOL/);
  assert.match(source, /TRAINER_TRAINING_RETURN_SMOKE_RESPONSE_LANGUAGE/);
  assert.match(source, /Live training return smoke via scripts\/training-return-smoke\.mjs/);
});
