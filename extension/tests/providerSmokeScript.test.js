'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const smokeScriptPath = path.resolve(__dirname, '..', '..', 'scripts', 'provider-smoke.mjs');
const smokePowerShellPath = path.resolve(__dirname, '..', '..', 'scripts', 'smoke.ps1');

function startOpenAiMockProvider({
  onChatRequest,
  onResponsesRequest,
  chatFailure,
  models = ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
}) {
  const server = http.createServer((request, response) => {
    if (request.url === '/v1/models' && request.method === 'GET') {
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ data: models.map((id) => ({ id })) }));
      return;
    }

    if (request.url === '/v1/chat/completions' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        const failure = chatFailure?.(payload);
        if (failure) {
          response.writeHead(failure.status, { 'Content-Type': 'application/json; charset=utf-8' });
          response.end(failure.body);
          return;
        }
        const content = onChatRequest(payload);
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(
          JSON.stringify({
            choices: [
              {
                message: {
                  content,
                },
              },
            ],
          }),
        );
      });
      return;
    }

    if (request.url === '/v1/responses' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        const content = onResponsesRequest(payload);
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(
          JSON.stringify({
            output_text: content,
            output: [
              {
                content: [
                  {
                    text: content,
                  },
                ],
              },
            ],
          }),
        );
      });
      return;
    }

    response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ error: { message: 'not found' } }));
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      resolve({
        baseUrl: `http://127.0.0.1:${address.port}/v1`,
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

function startAnthropicMockProvider({
  onMessageRequest,
  models = ['MiniMax-M2.7-highspeed', 'MiniMax-M3'],
}) {
  const server = http.createServer((request, response) => {
    if (request.url === '/v1/models' && request.method === 'GET') {
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ data: models.map((id) => ({ id })) }));
      return;
    }

    if (request.url === '/v1/messages' && request.method === 'POST') {
      let body = '';
      request.setEncoding('utf8');
      request.on('data', (chunk) => {
        body += chunk;
      });
      request.on('end', () => {
        const payload = JSON.parse(body);
        const content = onMessageRequest(payload);
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(
          JSON.stringify({
            content: [
              {
                type: 'text',
                text: content,
              },
            ],
          }),
        );
      });
      return;
    }

    response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ error: { message: 'not found' } }));
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      resolve({
        baseUrl: `http://127.0.0.1:${address.port}`,
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
    const child = spawn(process.execPath, [smokeScriptPath], {
      env: {
        ...process.env,
        TRAINER_PROVIDER_SMOKE_API_KEY: 'sk-test',
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

test('provider smoke script requires explicit endpoint and model for real UTF-8 language integrity', () => {
  const source = fs.readFileSync(smokeScriptPath, 'utf8');

  assert.doesNotMatch(source, /https:\/\/api\.minimaxi\.com\/v1/);
  assert.doesNotMatch(source, /const defaultModel = "MiniMax-M3"/);
  assert.match(source, /TRAINER_PROVIDER_SMOKE_BASE_URL/);
  assert.match(source, /TRAINER_PROVIDER_SMOKE_MODEL/);
  assert.match(source, /openai_responses/);
  assert.match(source, /anthropic_messages/);
  assert.match(source, /gemini_generate_content/);
  assert.match(source, /\\u4e0d\\u8981\\u76f4\\u63a5\\u8003\\u8bd5/);
  assert.match(source, /\\u8bfb\\u8fd9\\u53e5\\u8bdd/);
  assert.match(source, /\\u95ee\\u53f7/);
  assert.match(source, /Learn first, then verify\. Use a tiny remote workspace checkpoint\. ABC123/);
  assert.match(source, /language_corruption/);
  assert.match(source, /language_probe_inconclusive/);
  assert.match(source, /reasoning_leak/);
  assert.match(source, /thinking:\s*\{\s*type:\s*"disabled"\s*\}/);
  assert.match(source, /\/responses/);
  assert.match(source, /\/v1\/messages/);
  assert.doesNotMatch(source, /47\.107\.101\.18/);
});

test('provider smoke script reports missing live configuration without contacting a default provider', async () => {
  const result = await runSmokeScript({
    TRAINER_PROVIDER_SMOKE_BASE_URL: '',
    TRAINER_PROVIDER_SMOKE_MODEL: '',
  });

  assert.equal(result.code, 1);
  const report = JSON.parse(result.stderr);
  assert.equal(report.category, 'configuration_missing');
  assert.deepEqual(report.missing, [
    'TRAINER_PROVIDER_SMOKE_BASE_URL',
    'TRAINER_PROVIDER_SMOKE_MODEL',
  ]);
  assert.doesNotMatch(result.stderr, /api\.minimaxi\.com/);
});

test('provider smoke script fails zh-CN smoke when the provider turns Chinese into question marks', async () => {
  const provider = await startOpenAiMockProvider({
    onChatRequest(payload) {
      assert.equal(
        payload.messages[1].content,
        'Repeat exactly: \u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u5b66\u518d\u6d4b\u3002\u8bf7\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\u3002ABC123',
      );
      return '??????????????? VS Code ????????ABC123';
    },
    onResponsesRequest() {
      throw new Error('responses should not be used for chat-completions smoke');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M3',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'zh-CN',
    });

    assert.equal(result.code, 1);
    const report = JSON.parse(result.stderr);
    assert.equal(report.ok, false);
    assert.equal(report.category, 'language_corruption');
    assert.equal(report.model, 'MiniMax-M3');
    assert.equal(report.protocol, 'openai_chat_completions_compatible');
    assert.equal(typeof report.elapsedMs, 'number');
  } finally {
    await provider.close();
  }
});

test('provider smoke script redacts credentials and upstream bodies from failure reports', async () => {
  const provider = await startOpenAiMockProvider({
    onChatRequest() {
      throw new Error('chat reply should not be used after the mock failure');
    },
    onResponsesRequest() {
      throw new Error('responses should not be used for chat-completions smoke');
    },
    chatFailure() {
      return {
        status: 401,
        body: JSON.stringify({
          error: {
            message:
              'Authorization: Bearer echoed-secret; https://gateway.example/v1?api_key=sk-test&access_token=query-secret',
          },
          body: 'raw upstream response body',
        }),
      };
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M3',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'en-US',
    });

    assert.equal(result.code, 1);
    const report = JSON.parse(result.stderr);
    const serialized = JSON.stringify(report);
    assert.equal(report.category, 'authentication_failed');
    assert.equal(report.model, 'MiniMax-M3');
    assert.equal(report.protocol, 'openai_chat_completions_compatible');
    assert.equal(typeof report.elapsedMs, 'number');
    assert.doesNotMatch(serialized, /echoed-secret|query-secret|raw upstream response body|sk-test/);
  } finally {
    await provider.close();
  }
});

test('provider smoke script can verify an English-only fallback path even when the provider omits the echo prefix', async () => {
  const provider = await startOpenAiMockProvider({
    onChatRequest(payload) {
      return payload.messages[1].content.replace(/^Repeat exactly:\s*/, '');
    },
    onResponsesRequest() {
      throw new Error('responses should not be used for chat-completions smoke');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M3',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'en-US',
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.model, 'MiniMax-M3');
    assert.equal(report.protocol, 'openai_chat_completions_compatible');
    assert.equal(typeof report.elapsedMs, 'number');
  } finally {
    await provider.close();
  }
});

test('provider smoke script gives reasoning-first MiniMax probes enough visible output budget', async () => {
  const observedBudgets = [];
  const provider = await startOpenAiMockProvider({
    models: ['MiniMax-M2.7'],
    onChatRequest(payload) {
      observedBudgets.push(payload.max_tokens);
      return payload.messages[1].content;
    },
    onResponsesRequest() {
      throw new Error('responses should not be used for chat-completions smoke');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M2.7',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'en-US',
    });

    assert.equal(result.code, 0);
    assert.ok(observedBudgets.length > 0);
    // Reasoning-first MiniMax probes use the generous tier budget (1024), not the default 96.
    assert.deepEqual(observedBudgets, observedBudgets.map(() => 1024));
  } finally {
    await provider.close();
  }
});

test('provider smoke script keeps the default probe budget for ordinary models', async () => {
  const observedBudgets = [];
  const provider = await startOpenAiMockProvider({
    models: ['ordinary-chat-model'],
    onChatRequest(payload) {
      observedBudgets.push(payload.max_tokens);
      return payload.messages[1].content;
    },
    onResponsesRequest() {
      throw new Error('responses should not be used for chat-completions smoke');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'ordinary-chat-model',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'en-US',
    });

    assert.equal(result.code, 0);
    assert.ok(observedBudgets.length > 0);
    assert.deepEqual(observedBudgets, observedBudgets.map(() => 96));
  } finally {
    await provider.close();
  }
});

test('provider smoke script normalizes openai-compatible root gateways to /v1 for models and chat probes', async () => {
  const provider = await startOpenAiMockProvider({
    onChatRequest(payload) {
      return payload.messages[1].content;
    },
    onResponsesRequest() {
      throw new Error('responses should not be used for chat-completions smoke');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl.replace(/\/v1$/, ''),
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M3',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'zh-CN',
      TRAINER_PROVIDER_SMOKE_PROTOCOL: 'openai_chat_completions_compatible',
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.model, 'MiniMax-M3');
    assert.equal(typeof report.elapsedMs, 'number');
  } finally {
    await provider.close();
  }
});

test('provider smoke script supports openai_responses probes when the gateway exposes /responses', async () => {
  const provider = await startOpenAiMockProvider({
    onChatRequest() {
      throw new Error('chat/completions should not be used for openai_responses smoke');
    },
    onResponsesRequest(payload) {
      return payload.input.replace(/^Repeat exactly:\s*/, '');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M3',
      TRAINER_PROVIDER_SMOKE_PROTOCOL: 'openai_responses',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'en-US',
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.protocol, 'openai_responses');
    assert.equal(typeof report.elapsedMs, 'number');
  } finally {
    await provider.close();
  }
});

test('provider smoke script supports anthropic_messages probes', async () => {
  const provider = await startAnthropicMockProvider({
    onMessageRequest(payload) {
      assert.equal(payload.model, 'MiniMax-M3');
      assert.match(payload.system, /Return exactly the requested text/i);
      return payload.messages[0].content.replace(/^Repeat exactly:\s*/, '');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M3',
      TRAINER_PROVIDER_SMOKE_PROTOCOL: 'anthropic_messages',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'en-US',
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.protocol, 'anthropic_messages');
    assert.equal(typeof report.elapsedMs, 'number');
  } finally {
    await provider.close();
  }
});

test('provider smoke script tolerates raw <think> leakage when Trainer-style sanitization leaves valid visible text', async () => {
  const provider = await startOpenAiMockProvider({
    onChatRequest(payload) {
      return `<think>hidden</think>${payload.messages[1].content}`;
    },
    onResponsesRequest() {
      throw new Error('responses should not be used for chat-completions smoke');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M3',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'en-US',
    });

    assert.equal(result.code, 0);
    const report = JSON.parse(result.stdout);
    assert.equal(report.ok, true);
    assert.equal(report.model, 'MiniMax-M3');
    assert.equal(typeof report.elapsedMs, 'number');
  } finally {
    await provider.close();
  }
});

test('provider smoke script still fails when the provider returns only hidden reasoning and no visible text', async () => {
  const provider = await startOpenAiMockProvider({
    onChatRequest() {
      return '<think>hidden only</think>';
    },
    onResponsesRequest() {
      throw new Error('responses should not be used for chat-completions smoke');
    },
  });

  try {
    const result = await runSmokeScript({
      TRAINER_PROVIDER_SMOKE_BASE_URL: provider.baseUrl,
      TRAINER_PROVIDER_SMOKE_MODEL: 'MiniMax-M3',
      TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE: 'en-US',
    });

    assert.equal(result.code, 1);
    const report = JSON.parse(result.stderr);
    assert.equal(report.category, 'reasoning_leak');
    assert.equal(report.model, 'MiniMax-M3');
    assert.equal(typeof report.elapsedMs, 'number');
  } finally {
    await provider.close();
  }
});

test('smoke.ps1 exposes an opt-in provider smoke gate with response-language and protocol control', () => {
  const source = fs.readFileSync(smokePowerShellPath, 'utf8');

  assert.match(source, /\[switch\]\$ProviderSmoke/);
  assert.match(source, /\[string\]\$ProviderSmokeApiKey/);
  assert.match(source, /\[string\]\$ProviderSmokeBaseUrl/);
  assert.match(source, /\[string\]\$ProviderSmokeModel/);
  assert.match(source, /\[string\]\$ProviderSmokeProtocol/);
  assert.match(source, /\[string\]\$ProviderSmokeResponseLanguage/);
  assert.match(source, /TRAINER_PROVIDER_SMOKE_API_KEY/);
  assert.match(source, /TRAINER_PROVIDER_SMOKE_BASE_URL/);
  assert.match(source, /TRAINER_PROVIDER_SMOKE_MODEL/);
  assert.match(source, /TRAINER_PROVIDER_SMOKE_PROTOCOL/);
  assert.match(source, /TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE/);
  assert.match(source, /Live provider smoke via scripts\/provider-smoke\.mjs/);
  assert.match(source, /"failed"/);
});

test('smoke.ps1 exposes an opt-in trainer turn smoke gate with sidecar, provider, and protocol controls', () => {
  const source = fs.readFileSync(smokePowerShellPath, 'utf8');

  assert.match(source, /\[switch\]\$TrainerTurnSmoke/);
  assert.match(source, /\[string\]\$TrainerTurnSmokeSidecarUrl/);
  assert.match(source, /\[string\]\$TrainerTurnSmokeApiKey/);
  assert.match(source, /\[string\]\$TrainerTurnSmokeBaseUrl/);
  assert.match(source, /\[string\]\$TrainerTurnSmokeModel/);
  assert.match(source, /\[string\]\$TrainerTurnSmokeProtocol/);
  assert.match(source, /\[string\]\$TrainerTurnSmokeResponseLanguage/);
  assert.match(source, /TRAINER_TURN_SMOKE_SIDECAR_URL/);
  assert.match(source, /TRAINER_TURN_SMOKE_PROVIDER_API_KEY/);
  assert.match(source, /TRAINER_TURN_SMOKE_PROVIDER_BASE_URL/);
  assert.match(source, /TRAINER_TURN_SMOKE_PROVIDER_MODEL/);
  assert.match(source, /TRAINER_TURN_SMOKE_PROVIDER_PROTOCOL/);
  assert.match(source, /TRAINER_TURN_SMOKE_RESPONSE_LANGUAGE/);
  assert.match(source, /Live trainer turn smoke via scripts\/trainer-turn-smoke\.mjs/);
});
