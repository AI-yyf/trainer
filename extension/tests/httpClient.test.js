'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');

const httpClientModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'httpClient.js',
);
const constantsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'constants.js',
);

function waitFor(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test('provider request timeout is extended but remains bounded', () => {
  const { SIDECAR_DEFAULTS } = require(constantsModulePath);

  assert.equal(SIDECAR_DEFAULTS.requestTimeoutMs, 15_000);
  assert.ok(SIDECAR_DEFAULTS.providerRequestTimeoutMs > SIDECAR_DEFAULTS.requestTimeoutMs);
  assert.ok(SIDECAR_DEFAULTS.providerRequestTimeoutMs <= SIDECAR_DEFAULTS.maxRequestTimeoutMs);
  assert.ok(SIDECAR_DEFAULTS.maxRequestTimeoutMs <= 90_000);
});

test('postJson exposes only allow-listed workspace conflict metadata', async (t) => {
  const server = http.createServer((_request, response) => {
    response.writeHead(409, { 'content-type': 'application/json' });
    response.end(JSON.stringify({
      detail: {
        code: 'root_id_mismatch',
        category: 'workspace_root',
        path_state: 'unknown',
        message: 'C:\\Users\\secret\\project sk-live-should-not-appear',
      },
    }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient, SidecarHttpError } = require(httpClientModulePath);

  await assert.rejects(
    () => new SidecarHttpClient().postJson(address.port, '/workspace/classify', { folder_path: 'project' }),
    (error) => {
      assert.ok(error instanceof SidecarHttpError);
      assert.equal(error.statusCode, 409);
      assert.deepEqual(error.metadata, {
        code: 'root_id_mismatch',
        category: 'workspace_root',
        pathState: 'unknown',
      });
      assert.doesNotMatch(error.message, /secret|sk-live|project/i);
      return true;
    },
  );
});

test('putJson sends a JSON PUT request for explicit plan links', async (t) => {
  const requests = [];
  const server = http.createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      requests.push({
        method: request.method,
        path: request.url,
        body: JSON.parse(Buffer.concat(chunks).toString('utf8')),
      });
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ok: true }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);
  const response = await new SidecarHttpClient().putJson(address.port, '/plan/global/projects', {
    workspace_id: 'workspace-a',
    project_plan_id: 'plan-a',
  });

  assert.deepEqual(response, { ok: true });
  assert.deepEqual(requests, [
    {
      method: 'PUT',
      path: '/plan/global/projects',
      body: { workspace_id: 'workspace-a', project_plan_id: 'plan-a' },
    },
  ]);
});

test('browse admission is sent on JSON and streaming sidecar requests', async (t) => {
  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push({
      method: request.method,
      path: request.url,
      admission: request.headers['x-trainer-admission-mode'],
    });
    if (request.url === '/stream') {
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      response.end('event: complete\ndata: {"ok":true}\n\n');
      return;
    }
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ ok: true }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);
  const client = new SidecarHttpClient();
  client.setTrainerAdmissionMode('browse');

  assert.deepEqual(await client.getJson(address.port, '/memory/summary'), { ok: true });
  const events = [];
  for await (const event of client.fetchSSE(address.port, '/stream', { message: 'test' })) {
    events.push(event);
  }

  assert.deepEqual(events, [{ event: 'complete', data: '{"ok":true}' }]);
  assert.deepEqual(requests, [
    { method: 'GET', path: '/memory/summary', admission: 'browse' },
    { method: 'POST', path: '/stream', admission: 'browse' },
  ]);
});

test('ignored admission is preserved on every sidecar request', async (t) => {
  const requests = [];
  const server = http.createServer((request, response) => {
    requests.push({
      method: request.method,
      path: request.url,
      admission: request.headers['x-trainer-admission-mode'],
    });
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ ok: true }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);
  const client = new SidecarHttpClient();
  client.setTrainerAdmissionMode('ignored');

  assert.deepEqual(await client.getJson(address.port, '/resource/search'), { ok: true });
  assert.deepEqual(await client.postJson(address.port, '/resource/upload', { name: 'notes' }), { ok: true });
  assert.deepEqual(await client.putJson(address.port, '/sandbox/root', { clear: true }), { ok: true });

  assert.deepEqual(requests, [
    { method: 'GET', path: '/resource/search', admission: 'ignored' },
    { method: 'POST', path: '/resource/upload', admission: 'ignored' },
    { method: 'PUT', path: '/sandbox/root', admission: 'ignored' },
  ]);
});

test('postJson accepts a bounded extended timeout for a delayed coach message', async (t) => {
  const server = http.createServer((_request, response) => {
    setTimeout(() => {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ok: true, delayed: true }));
    }, 80);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);

  const response = await new SidecarHttpClient().postJson(
    address.port,
    '/session/message',
    { message: 'Continue the coach session.' },
    { timeoutMs: 200 },
  );

  assert.deepEqual(response, { ok: true, delayed: true });
});

test('postJson aborts a delayed coach message once its finite deadline elapses', async (t) => {
  let resolveAborted;
  const serverObservedAbort = new Promise((resolve) => {
    resolveAborted = resolve;
  });
  const server = http.createServer((request, response) => {
    const responseTimer = setTimeout(() => {
      if (!response.destroyed) {
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(JSON.stringify({ ok: true }));
      }
    }, 250);
    request.once('aborted', () => {
      clearTimeout(responseTimer);
      resolveAborted(true);
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);

  await assert.rejects(
    new SidecarHttpClient().postJson(
      address.port,
      '/session/message',
      { message: 'Continue the coach session.' },
      { timeoutMs: 50 },
    ),
    /timed out after 50ms: POST \/session\/message/i,
  );
  assert.equal(
    await Promise.race([serverObservedAbort, waitFor(150).then(() => false)]),
    true,
  );
});

test('fetchSSE accepts a bounded extended timeout for a delayed coach stream', async (t) => {
  const server = http.createServer((_request, response) => {
    setTimeout(() => {
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      response.end('event: complete\ndata: {"ok":true,"delayed":true}\n\n');
    }, 80);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);
  const events = [];

  for await (const event of new SidecarHttpClient().fetchSSE(
    address.port,
    '/session/message/stream',
    { message: 'Continue the coach session.' },
    { timeoutMs: 200 },
  )) {
    events.push(event);
  }

  assert.deepEqual(events, [{ event: 'complete', data: '{"ok":true,"delayed":true}' }]);
});

test('fetchSSE preserves recoverable SSE error frames before completion', async (t) => {
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/event-stream' });
    response.end(
      'event: error\n' +
        'data: {"error":"buffered provider","recoverable":true,"terminal":false,"degraded":true}\n\n' +
        'event: complete\n' +
        'data: {"ok":true}\n\n',
    );
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);
  const events = [];

  for await (const event of new SidecarHttpClient().fetchSSE(
    address.port,
    '/session/message/stream',
    { message: 'Continue the coach session.' },
  )) {
    events.push(event);
  }

  assert.deepEqual(events, [
    {
      event: 'error',
      data: '{"error":"buffered provider","recoverable":true,"terminal":false,"degraded":true}',
    },
    { event: 'complete', data: '{"ok":true}' },
  ]);
});

test('fetchSSE parses LF and CRLF frames when delimiters cross response chunks', async (t) => {
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/event-stream' });
    response.write('event: status\r');
    setTimeout(() => {
      response.write('\ndata: {"phase":"requesting_model"}\r\n\r');
      setTimeout(() => {
        response.end(
          '\nevent: complete\n' +
            'data: {"ok":true}\n\n',
        );
      }, 5);
    }, 5);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);
  const events = [];

  for await (const event of new SidecarHttpClient().fetchSSE(
    address.port,
    '/session/message/stream',
    { message: 'Continue the coach session.' },
  )) {
    events.push(event);
  }

  assert.deepEqual(events, [
    { event: 'status', data: '{"phase":"requesting_model"}' },
    { event: 'complete', data: '{"ok":true}' },
  ]);
});

test('fetchSSE aborts a delayed coach stream once its finite deadline elapses', async (t) => {
  let resolveAborted;
  const serverObservedAbort = new Promise((resolve) => {
    resolveAborted = resolve;
  });
  const server = http.createServer((request, response) => {
    const responseTimer = setTimeout(() => {
      if (!response.destroyed) {
        response.writeHead(200, { 'content-type': 'text/event-stream' });
        response.end('event: complete\ndata: {"ok":true}\n\n');
      }
    }, 250);
    request.once('aborted', () => {
      clearTimeout(responseTimer);
      resolveAborted(true);
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  assert.equal(typeof address, 'object');
  assert.ok(address && 'port' in address);
  const { SidecarHttpClient } = require(httpClientModulePath);

  await assert.rejects(
    async () => {
      for await (const _event of new SidecarHttpClient().fetchSSE(
        address.port,
        '/session/message/stream',
        { message: 'Continue the coach session.' },
        { timeoutMs: 50 },
      )) {
        // This response should be aborted before the server emits an event.
      }
    },
    /timed out after 50ms: POST \/session\/message\/stream/i,
  );
  assert.equal(
    await Promise.race([serverObservedAbort, waitFor(150).then(() => false)]),
    true,
  );
});
