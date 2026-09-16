'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const http = require('node:http');

const serverModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'provider',
  'trialProviderServer.js',
);

const {
  TrialProviderServer,
  ensureTrialProviderServer,
  disposeTrialProviderServer,
  buildTrialCoachReply,
  TRIAL_PROVIDER_MODEL_ID,
} = require(serverModulePath);

function postJson(port, requestPath, body) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const request = http.request(
      {
        host: '127.0.0.1',
        port,
        method: 'POST',
        path: requestPath,
        headers: { 'content-type': 'application/json' },
      },
      (response) => {
        const chunks = [];
        response.on('data', (chunk) => chunks.push(chunk));
        response.on('end', () =>
          resolve({ status: response.statusCode, body: Buffer.concat(chunks).toString('utf8') }),
        );
      },
    );
    request.on('error', reject);
    request.end(payload);
  });
}

function getJson(port, requestPath) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: '127.0.0.1', port, path: requestPath }, (response) => {
        const chunks = [];
        response.on('data', (chunk) => chunks.push(chunk));
        response.on('end', () =>
          resolve({ status: response.statusCode, body: Buffer.concat(chunks).toString('utf8') }),
        );
      })
      .on('error', reject);
  });
}

test('trial provider serves models and non-streaming chat completions on loopback', async () => {
  const server = new TrialProviderServer();
  try {
    await server.listen();
    assert.match(server.baseUrl, /^http:\/\/127\.0\.0\.1:\d+\/v1$/);
    assert.match(server.secretApiKey, /^trial-[0-9a-f]{32}$/);

    const models = await getJson(server.port, '/v1/models');
    assert.equal(models.status, 200);
    assert.equal(JSON.parse(models.body).data[0].id, TRIAL_PROVIDER_MODEL_ID);

    const completion = await postJson(server.port, '/v1/chat/completions', {
      model: TRIAL_PROVIDER_MODEL_ID,
      messages: [{ role: 'user', content: '帮我把这个函数改对' }],
    });
    assert.equal(completion.status, 200);
    const parsed = JSON.parse(completion.body);
    assert.equal(parsed.object, 'chat.completion');
    assert.equal(parsed.choices[0].message.role, 'assistant');
    assert.match(parsed.choices[0].message.content, /练习模式/);
    assert.match(parsed.choices[0].message.content, /帮我把这个函数改对/);
  } finally {
    await server.close();
  }
});

test('trial provider streams SSE chunks and finishes with [DONE]', async () => {
  const server = new TrialProviderServer();
  try {
    await server.listen();
    const response = await postJson(server.port, '/v1/chat/completions', {
      stream: true,
      messages: [{ role: 'user', content: 'explain fsrs in english please' }],
    });
    assert.equal(response.status, 200);
    assert.match(response.body, /chat\.completion\.chunk/);
    const lines = response.body.split('\n').filter((line) => line.startsWith('data: '));
    assert.ok(lines.length >= 3);
    assert.equal(lines[lines.length - 1], 'data: [DONE]');
    const content = lines
      .slice(1, -1)
      .map((line) => {
        const parsed = JSON.parse(line.slice('data: '.length));
        return parsed.choices[0].delta.content ?? '';
      })
      .join('');
    assert.match(content, /\[Trainer practice mode\]/);
    assert.match(content, /explain fsrs in english please/);
  } finally {
    await server.close();
  }
});

test('trial replies stay honest about being local-only and 404 unknown routes', async () => {
  assert.match(buildTrialCoachReply({ messages: [{ role: 'user', content: '你好' }] }), /设置/);
  const server = new TrialProviderServer();
  try {
    await server.listen();
    const missing = await getJson(server.port, '/v1/unknown');
    assert.equal(missing.status, 404);
  } finally {
    await server.close();
  }
});

test('ensure/dispose keep a single shared trial server', async () => {
  const first = await ensureTrialProviderServer();
  const second = await ensureTrialProviderServer();
  assert.equal(first, second);
  await disposeTrialProviderServer();
  assert.equal(first.isListening, false);
});
