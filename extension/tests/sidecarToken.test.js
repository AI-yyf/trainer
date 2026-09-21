'use strict';

/**
 * TR-077 acceptance: the extension generates a per-instance token at every
 * sidecar launch, passes it to the child via TRAINER_SIDECAR_TOKEN, and every
 * HTTP client request presents it as the x-trainer-token header.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const httpClientModulePath = path.resolve(__dirname, '..', 'dist', 'extension', 'src', 'core', 'httpClient.js');
const managerSourcePath = path.resolve(__dirname, '..', 'src', 'core', 'sidecarProcessManager.ts');

const { SidecarHttpClient } = require(httpClientModulePath);

function createCaptureServer() {
  const seen = [];
  const server = http.createServer((request, response) => {
    seen.push({
      path: request.url,
      token: request.headers['x-trainer-token'],
    });
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ ok: true }));
  });
  return { server, seen };
}

test('httpClient presents the per-instance token on every request', async () => {
  const { server, seen } = createCaptureServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  const client = new SidecarHttpClient();
  client.setInstanceToken('token-abc');

  await client.getJson(port, '/health');
  assert.equal(seen.length, 1);
  assert.equal(seen[0].token, 'token-abc');

  client.setInstanceToken('token-def');
  await client.getJson(port, '/health');
  assert.equal(seen[1].token, 'token-def');

  await new Promise((resolve) => server.close(resolve));
});

test('httpClient resolves late-bound token providers', async () => {
  const { server, seen } = createCaptureServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  const client = new SidecarHttpClient();
  let current;
  client.setInstanceTokenProvider(() => current);

  current = 'late-token';
  await client.getJson(port, '/health');
  assert.equal(seen[0].token, 'late-token');

  // No token configured: the header must be absent entirely.
  current = undefined;
  client.setInstanceToken(undefined);
  await client.getJson(port, '/health');
  assert.equal(seen[1].token, undefined);

  await new Promise((resolve) => server.close(resolve));
});

test('sidecar launcher forwards TRAINER_SIDECAR_TOKEN and exposes it', () => {
  const source = fs.readFileSync(managerSourcePath, 'utf8');

  // The spawn environment forwards the token to the sidecar child.
  assert.match(source, /TRAINER_SIDECAR_TOKEN: this\.instanceToken/);
  // Fresh per-launch token generation feeds both the child env and the client.
  assert.match(source, /this\.instanceToken = randomUUID\(\)/);
  assert.match(source, /this\.client\.setInstanceToken\(this\.instanceToken\)/);
  assert.match(source, /getInstanceToken\(\)/);
});
