'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const scriptPath = path.resolve(__dirname, '..', '..', 'scripts', 'trainer-turn-smoke.mjs');

function startMockTrainer({
  contaminateFunctionReply = false,
  omitZhTrainingCardTitle = false,
  sessionStartFailureBody = '',
} = {}) {
  const turnBodies = [];
  const trainingCardBodies = [];
  let sessionCounter = 0;

  const server = http.createServer((request, response) => {
    if (request.url === '/provider/test' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        const provider = payload.provider || {};
        const protocol = provider.protocol || 'openai_chat_completions_compatible';
        const disabled = new Set(
          protocol === 'anthropic_messages'
            ? ['responses', 'embeddings', 'json_schema', 'structured_output']
            : protocol === 'openai_chat_completions_compatible' || protocol === 'openai_chat_completions'
              ? ['responses', 'vision', 'embeddings']
              : protocol === 'openai_responses'
                ? ['embeddings']
                : [],
        );
        const capabilityEvidence = [
          'chat',
          'responses',
          'vision',
          'embeddings',
          'tools',
          'json_schema',
          'structured_output',
          'streaming',
        ].map((name) => ({
          name,
          declared: !disabled.has(name),
          observed: null,
          state: disabled.has(name) ? 'disabled' : 'unverified',
        }));
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(
          JSON.stringify({
            ok: true,
            configured: true,
            api_key_supplied: Boolean(payload.api_key),
            reachable: true,
            success: true,
            status: 'connected',
            provider_name: provider.name,
            base_url: provider.baseUrl,
            model: provider.model,
            protocol,
            protocol_family: protocol === 'anthropic_messages' ? 'anthropic' : 'openai',
            detail: `Provider reachable. Chat probe succeeded with model ${provider.model}.`,
            diagnostics: ['live connectivity check succeeded'],
            model_supported: true,
            capability_evidence: capabilityEvidence,
            tools_ready: false,
            tool_probe_status: 'unverified',
            streaming_ready: false,
            stream_probe_status: 'unverified',
            available_models: [],
            resolved_model: null,
            model_capabilities: {},
            warnings: [],
          }),
        );
      });
      return;
    }

    if (request.url === '/turn/stream' && request.method === 'POST') {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      });
      response.write('event: chunk\n');
      response.write(`data: ${JSON.stringify({ chunk: '我会先验证一个 breakpoint。' })}\n\n`);
      response.write('event: complete\n');
      response.write(`data: ${JSON.stringify({ done: true })}\n\n`);
      response.end();
      return;
    }

    if (request.url === '/session/start' && request.method === 'POST') {
      if (sessionStartFailureBody) {
        response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
        response.end(sessionStartFailureBody);
        return;
      }
      sessionCounter += 1;
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ session_id: `session-${sessionCounter}` }));
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
        const context = [payload.focus_area, payload.target_skill, payload.context_hint]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        const scenarioPack = context.includes('debug') || context.includes('breakpoint')
          ? 'debug_loop'
          : context.includes('function') || context.includes('typescript') || context.includes('call site')
            ? 'function_guidance'
            : 'remote_workspace';
        const localized = payload.response_language === 'zh-CN';
        const card = {
          card_id: `explicit-card-${trainingCardBodies.length}`,
          card_type: 'practice',
          scenario_pack: scenarioPack,
          title: localized && !omitZhTrainingCardTitle
            ? '\u7ec3\u4e60\uff1a\u9a8c\u8bc1\u5f53\u524d\u8bad\u7ec3\u8fb9\u754c'
            : `Practice: ${scenarioPack}`,
          problem_statement: localized
            ? '\u7528\u4e00\u4e2a\u53ef\u9a8c\u8bc1\u7684\u5c0f\u6b65\u8bf4\u6e05\u8fd9\u4e2a\u8bad\u7ec3\u8fb9\u754c\u3002'
            : 'Prove one small, observable step in this training lane.',
          suggested_workspace_action: localized
            ? '\u5148\u505a\u4e00\u4e2a\u53ef\u89c2\u5bdf\u7684\u5c0f\u52a8\u4f5c\uff0c\u518d\u628a\u7ed3\u679c\u5e26\u56de\u6765\u3002'
            : 'Take one observable workspace action and bring back the result.',
        };
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          card,
          active_routing: {
            selected_card: card,
            selected_card_id: card.card_id,
          },
        }));
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
        const message = String(payload.message || '');
        let responsePayload;

        if (message.includes('remote workflow for SSH')) {
          responsePayload = {
            coach_turn: { scenario: 'remote_workspace' },
            reply: {
              content:
                'I will keep this in the VS Code remote lane and prove one workspace boundary first.',
            },
            snapshot: {
              memory: {
                current_focus:
                  "Continue 'VS Code remote workspace' and do not open a new lane before this next move lands: prove one workspace boundary.",
              },
            },
          };
        } else if (message.includes('VS Code Remote SSH')) {
          if (payload.response_language === 'zh-CN') {
            responsePayload = {
              coach_turn: { scenario: 'remote_workspace' },
              reply: {
                content:
                  '\u597d\uff0c\u6211\u4eec\u5148\u6536\u7d27\u5230\u4e00\u4e2a\u6700\u5c0f\u7684 remote \u8fb9\u754c\u68c0\u67e5\uff0c\u5148\u5224\u65ad\u5f53\u524d\u5de5\u4f5c\u533a\u5230\u5e95\u5728\u54ea\u53f0\u673a\u5668\u4e0a\u3002',
              },
              snapshot: {
                memory: {
                  current_focus:
                    "\u7ee7\u7eed\u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fd9\u6761\u7ebf\uff0c\u5148\u8bc1\u660e\u5de5\u4f5c\u533a\u8fb9\u754c\u548c\u6587\u4ef6\u6240\u5728\u673a\u5668\u3002",
                  active_training_card_routing: {
                    selected_card: {
                      card_type: 'practice',
                      scenario_pack: 'remote_workspace',
                      title: omitZhTrainingCardTitle
                        ? 'Practice: Verify the remote workspace boundary'
                        : '\u7ec3\u4e60\uff1a\u9a8c\u8bc1\u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c',
                      problem_statement:
                        '\u8bc1\u660e\u54ea\u53f0\u673a\u5668\u62e5\u6709\u5de5\u4f5c\u533a\u6587\u4ef6\uff0cAPI key \u5e94\u8be5\u7559\u5728\u672c\u5730\u8fd8\u662f\u8fdc\u7aef\uff0c\u4ee5\u53ca Trainer \u5e94\u8be5\u5982\u4f55\u5148\u89e3\u91ca\u8fd9\u4e2a\u8fb9\u754c\u3002',
                      suggested_workspace_action:
                        '\u5148\u786e\u8ba4\u5f53\u524d\u5de5\u4f5c\u533a\u662f SSH\u3001tunnels\u3001dev container\u3001WSL \u8fd8\u662f local\uff0c\u518d\u51b3\u5b9a\u4f60\u8981\u5728\u54ea\u91cc\u5b58 credentials\u3002',
                    },
                    selected_card_id: 'card-4',
                    why_this_card:
                      '\u5148\u628a remote \u8fb9\u754c\u8bb2\u6e05\u695a\uff0c\u540e\u9762\u7684\u8d44\u6e90\u3001credentials \u548c\u8c03\u8bd5\u8def\u5f84\u624d\u4e0d\u4f1a\u4e71\u3002',
                  },
                },
              },
            };
          } else {
            responsePayload = {
              coach_turn: { scenario: 'remote_workspace' },
              reply: {
                content:
                  'I will turn this into one learn-first remote practice card before any quiz.',
              },
              snapshot: {
                memory: {
                  current_focus:
                    "Continue 'VS Code remote workspace' and do not open a new lane before this next move lands: prove one workspace path.",
                  active_training_card_routing: {
                    selected_card: {
                      card_type: 'practice',
                      scenario_pack: 'remote_workspace',
                      title: 'Practice: Verify the remote workspace boundary',
                    },
                    selected_card_id: 'card-1',
                    why_this_card: 'Remote boundary proof comes before deeper coaching.',
                  },
                },
              },
            };
          }
        } else if (message.includes('debug Python')) {
          if (payload.response_language === 'zh-CN') {
            responsePayload = {
              coach_turn: { scenario: 'debug_loop' },
              reply: {
                content:
                  '\u597d\uff0c\u6211\u4eec\u5148\u53ea\u642d\u4e00\u4e2a\u6700\u5c0f debug loop\uff1a\u4e00\u4e2a breakpoint\uff0c\u4e00\u4e2a\u4f60\u80fd\u4eb2\u773c\u770b\u5230\u7684 value\u3002',
              },
              snapshot: {
                memory: {
                  current_focus:
                    "\u7ee7\u7eed\u8c03\u8bd5\u95ed\u73af\u8fd9\u6761\u7ebf\uff0c\u5148\u5728\u7b2c\u4e00\u4e2a\u6709\u610f\u4e49\u7684 state change \u505c\u4e0b\u3002",
                  active_training_card_routing: {
                    selected_card: {
                      card_type: 'practice',
                      scenario_pack: 'debug_loop',
                      title: '\u7ec3\u4e60\uff1a\u6536\u7a84\u8c03\u8bd5\u95ed\u73af',
                      problem_statement:
                        '\u6784\u5efa\u4e00\u4e2a\u6700\u5c0f\u8c03\u8bd5\u95ed\u73af\uff1a\u53ef\u590d\u73b0\u95ee\u9898\u3001\u5728\u72b6\u6001\u7b2c\u4e00\u6b21\u51fa\u9519\u7684\u5730\u65b9\u6682\u505c\uff0c\u5e76\u5e26\u56de\u4e00\u4e2a\u88ab\u8bc1\u5b9e\u7684\u53d1\u73b0\u3002',
                      suggested_workspace_action:
                        '\u5148\u9009\u4e00\u4e2a breakpoint\uff0c\u7136\u540e\u51b3\u5b9a\u4f60\u8981\u5148\u770b\u54ea\u4e2a value\u3001branch \u6216 stack frame\u3002',
                    },
                    selected_card_id: 'card-5',
                    why_this_card:
                      '\u5148\u642d\u8d77\u4e00\u4e2a\u53ef\u4fe1\u7684 debug loop\uff0c\u540e\u9762\u624d\u80fd\u505a\u771f\u6b63\u7684\u5b9a\u4f4d\u548c\u9a8c\u8bc1\u3002',
                  },
                },
              },
            };
          } else {
            responsePayload = {
              coach_turn: { scenario: 'debug_loop' },
              reply: {
                content:
                  'I will keep this as one trustworthy debug loop and inspect one value first.',
              },
              snapshot: {
                memory: {
                  current_focus:
                    "Continue 'VS Code debug loop' and do not open a new lane before this next move lands: inspect one value.",
                },
              },
            };
          }
        } else if (message.includes('function hints')) {
          responsePayload = {
            coach_turn: { scenario: 'function_guidance' },
            reply: {
              content: contaminateFunctionReply
                ? 'I will keep this anchored to one live call site, but it still follows the debug loop.'
                : 'I will keep this anchored to one live call site and read one function contract first.',
            },
            snapshot: {
              memory: {
                current_focus:
                  "Continue 'function contract' and do not open a new lane before this next move lands: read one call site.",
              },
            },
          };
        } else if (message.includes('TypeScript fetch options')) {
          if (payload.response_language === 'zh-CN') {
            responsePayload = {
              coach_turn: { scenario: 'function_guidance' },
              reply: {
                content:
                  '\u597d\uff0c\u6211\u4eec\u5148\u628a\u6ce8\u610f\u529b\u6536\u7d27\u5230\u4e00\u4e2a\u771f\u5b9e\u7684 call site \u4e0a\uff0c\u518d\u53bb\u8bfb fetch \u7684\u51fd\u6570\u5951\u7ea6\u3002',
              },
              snapshot: {
                memory: {
                  current_focus:
                    "\u7ee7\u7eed\u51fd\u6570\u5951\u7ea6\u8fd9\u6761\u7ebf\uff0c\u5148\u7528\u4e00\u4e2a\u771f\u5b9e\u8c03\u7528\u70b9\u628a contract \u8bfb\u7a33\u3002",
                  active_training_card_routing: {
                    selected_card: {
                      card_type: 'practice',
                      scenario_pack: 'function_guidance',
                      title: '\u7ec3\u4e60\uff1a\u7528\u7f16\u8f91\u5668\u63d0\u793a\u6062\u590d\u51fd\u6570\u5951\u7ea6',
                      problem_statement:
                        '\u4f7f\u7528 VS Code \u7684\u51fd\u6570\u63d0\u793a\u6062\u590d\u4e00\u4e2a\u51fd\u6570\u5951\u7ea6\uff1a\u5b83\u63a5\u6536\u4ec0\u4e48\u3001\u8fd4\u56de\u4ec0\u4e48\uff0c\u4ee5\u53ca\u54ea\u4e2a\u8c03\u7528\u70b9\u80fd\u8bc1\u660e\u8fd9\u4e2a\u5224\u65ad\u3002',
                      suggested_workspace_action:
                        '\u4ece\u4e00\u4e2a\u771f\u5b9e\u8c03\u7528\u70b9\u51fa\u53d1\uff0c\u5728\u6539\u4efb\u4f55\u4ee3\u7801\u524d\u5148\u68c0\u67e5 hover\u3001signature help \u548c definition\u3002',
                    },
                    selected_card_id: 'card-3',
                    why_this_card:
                      '\u5148\u628a call site \u8bfb\u7a33\uff0c\u540e\u9762\u7684\u89e3\u91ca\u548c\u9a8c\u8bc1\u624d\u4e0d\u4f1a\u6f02\u3002',
                  },
                },
              },
            };
          } else {
            responsePayload = {
              coach_turn: { scenario: 'function_guidance' },
              reply: {
                content:
                  'I will turn this into one learn-first function-guidance practice card on a real call site before any quiz.',
              },
              snapshot: {
                memory: {
                  current_focus:
                    "Continue 'function contract' and do not open a new lane before this next move lands: prove one call site.",
                  active_training_card_routing: {
                    selected_card: {
                      card_type: 'practice',
                      scenario_pack: 'function_guidance',
                      title: 'Practice: Recover fetch options from one real call site',
                    },
                    selected_card_id: 'card-2',
                    why_this_card: 'A real call site should anchor the function contract before testing.',
                  },
                },
              },
            };
          }
        } else {
          responsePayload = {
            coach_turn: { scenario: 'general' },
            reply: { content: 'unexpected message' },
            snapshot: { memory: { current_focus: 'unexpected' } },
          };
        }

        // The chat contract is hint-only: explicit card requests are bound by
        // the separate /training/generate-card route above.
        if (message.includes('learn-first practice card')) {
          const memory = responsePayload?.snapshot?.memory;
          if (memory && typeof memory === 'object') {
            delete memory.active_training_card_routing;
          }
        }
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify(responsePayload));
      });
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

function runTurnSmoke(envOverrides = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [scriptPath], {
      env: {
        ...process.env,
        TRAINER_TURN_SMOKE_PROVIDER_BASE_URL: 'http://provider.example/v1',
        TRAINER_TURN_SMOKE_PROVIDER_API_KEY: 'sk-turn-test',
        TRAINER_TURN_SMOKE_PROVIDER_MODEL: 'MiniMax-M3',
        TRAINER_TURN_SMOKE_PROVIDER_PROTOCOL: 'openai_chat_completions_compatible',
        TRAINER_TURN_SMOKE_RESPONSE_LANGUAGE: 'en-US',
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

test('trainer turn smoke script stays env-driven and never hardcodes the hidden trainer gateway', () => {
  const source = fs.readFileSync(scriptPath, 'utf8');

  assert.match(source, /TRAINER_TURN_SMOKE_SIDECAR_URL/);
  assert.match(source, /TRAINER_TURN_SMOKE_PROVIDER_BASE_URL/);
  assert.match(source, /TRAINER_TURN_SMOKE_PROVIDER_API_KEY/);
  assert.match(source, /TRAINER_TURN_SMOKE_PROVIDER_MODEL/);
  assert.match(source, /TRAINER_TURN_SMOKE_PROVIDER_PROTOCOL/);
  assert.match(source, /TRAINER_TURN_SMOKE_RESPONSE_LANGUAGE/);
  assert.match(source, /active_training_card_routing/);
  assert.match(source, /lane_contamination/);
  assert.match(source, /function_guidance/);
  assert.doesNotMatch(source, /47\.107\.101\.18/);
  assert.doesNotMatch(source, /sk-[A-Za-z0-9_-]{24,}/);
});

test('trainer turn smoke script passes clean lane transitions and learn-first routing', async () => {
  const trainer = await startMockTrainer();

  try {
    const result = await runTurnSmoke({
      TRAINER_TURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.category, 'success');
    assert.equal(report.providerModel, 'MiniMax-M3');
    assert.equal(report.providerProtocol, 'openai_chat_completions_compatible');
    assert.equal(typeof report.elapsedMs, 'number');

    assert.equal(trainer.turnBodies.length, 8);
    for (const body of trainer.turnBodies) {
      assert.equal(body.provider.baseUrl, 'http://provider.example/v1');
      assert.equal(body.provider.model, 'MiniMax-M3');
      assert.equal(body.provider.protocol, 'openai_chat_completions_compatible');
      assert.equal(body.provider.requestDefaults.extra_body.thinking.type, 'disabled');
      assert.equal(body.api_key, 'sk-turn-test');
      assert.equal(body.use_agent_loop, true);
    }
    assert.equal(
      trainer.turnBodies.filter((body) => body.response_language === 'zh-CN').length,
      3,
    );
  } finally {
    await trainer.close();
  }
});

test('trainer turn smoke script can pass through anthropic_messages protocol without OpenAI-only request defaults', async () => {
  const trainer = await startMockTrainer();

  try {
    const result = await runTurnSmoke({
      TRAINER_TURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
      TRAINER_TURN_SMOKE_PROVIDER_PROTOCOL: 'anthropic_messages',
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.providerProtocol, 'anthropic_messages');
    assert.equal(typeof report.elapsedMs, 'number');
    assert.equal(trainer.turnBodies[0].provider.protocol, 'anthropic_messages');
    assert.equal('requestDefaults' in trainer.turnBodies[0].provider, false);
  } finally {
    await trainer.close();
  }
});

test('trainer turn smoke script fails when a fresh lane still leaks the previous lane into the visible reply', async () => {
  const trainer = await startMockTrainer({ contaminateFunctionReply: true });

  try {
    const result = await runTurnSmoke({
      TRAINER_TURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
    });

    assert.equal(result.code, 1);
    const report = JSON.parse(result.stderr);
    assert.equal(report.ok, false);
    assert.equal(report.category, 'lane_contamination');
    assert.equal(report.providerModel, 'MiniMax-M3');
    assert.equal(report.providerProtocol, 'openai_chat_completions_compatible');
    assert.equal(typeof report.elapsedMs, 'number');
    assert.equal('preview' in report, false);
    assert.equal('step' in report, false);
    assert.doesNotMatch(result.stderr, /debug loop/i);
  } finally {
    await trainer.close();
  }
});

test('trainer turn smoke script redacts a failed sidecar response body', async () => {
  const secret = 'turn-smoke-upstream-secret';
  const trainer = await startMockTrainer({ sessionStartFailureBody: secret });

  try {
    const result = await runTurnSmoke({
      TRAINER_TURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
    });

    assert.equal(result.code, 1);
    const report = JSON.parse(result.stderr);
    assert.equal(report.category, 'session_start_failed');
    assert.equal(report.providerModel, 'MiniMax-M3');
    assert.equal(report.providerProtocol, 'openai_chat_completions_compatible');
    assert.equal(typeof report.elapsedMs, 'number');
    assert.equal('preview' in report, false);
    assert.equal('step' in report, false);
    assert.doesNotMatch(result.stderr, new RegExp(secret));
  } finally {
    await trainer.close();
  }
});

test('trainer turn smoke script identifies the nonlocalized zh-CN training-card field', async () => {
  const trainer = await startMockTrainer({ omitZhTrainingCardTitle: true });

  try {
    const result = await runTurnSmoke({
      TRAINER_TURN_SMOKE_SIDECAR_URL: trainer.sidecarUrl,
    });

    assert.equal(result.code, 1);
    const report = JSON.parse(result.stderr);
    assert.equal(report.ok, false);
    assert.equal(report.category, 'training_card_language_mismatch');
    assert.equal(report.providerModel, 'MiniMax-M3');
    assert.equal(report.providerProtocol, 'openai_chat_completions_compatible');
    assert.equal(typeof report.elapsedMs, 'number');
    assert.equal('step' in report, false);
  } finally {
    await trainer.close();
  }
});
