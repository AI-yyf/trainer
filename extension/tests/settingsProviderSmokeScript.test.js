'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const scriptPath = path.resolve(__dirname, '..', '..', 'scripts', 'settings-provider-smoke.mjs');

function startMockSidecar({
  authCategory = 'invalid_key_or_permission',
  networkCategory = 'network',
  liveOk = true,
} = {}) {
  const server = http.createServer((request, response) => {
    if (request.url !== '/provider/test' || request.method !== 'POST') {
      response.writeHead(404);
      response.end('missing');
      return;
    }
    let body = '';
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      body += chunk;
    });
    request.on('end', () => {
      const payload = JSON.parse(body);
      const apiKey = String(payload.api_key || '');
      const provider = payload.provider || {};
      const protocol = String(provider.protocol || '');
      const baseUrl = String(provider.base_url || provider.baseUrl || '');

      let result;
      if (protocol === 'newapi_channel_conn') {
        result = {
          ok: false,
          status: 'unknown_protocol',
          error_category: 'unknown_protocol',
          detail: 'connection type is not a protocol',
        };
      } else if (baseUrl.includes('127.0.0.1:1')) {
        result = {
          ok: false,
          status: networkCategory,
          error_category: networkCategory,
          detail: 'Provider request failed.',
          retryable: true,
        };
      } else if (apiKey.includes('fake-settings-provider-auth-fail')) {
        result = {
          ok: false,
          status: authCategory,
          error_category: authCategory,
          status_code: authCategory === 'invalid_key_or_permission' ? 401 : null,
          detail: 'Provider rejected the API key.',
          retryable: false,
        };
      } else if (liveOk) {
        result = {
          ok: true,
          status: 'connected',
          error_category: null,
          tools_ready: true,
          streaming_ready: true,
          detail: 'Provider test passed.',
        };
      } else {
        result = {
          ok: false,
          status: 'empty_response',
          error_category: 'empty_response',
          detail: 'empty',
        };
      }
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify(result));
    });
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        server,
        url: `http://127.0.0.1:${port}`,
      });
    });
  });
}

function runSmoke(env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [scriptPath], {
      env: { ...process.env, ...env },
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

test('settings-provider smoke script stays local and redacts secrets', () => {
  const source = fs.readFileSync(scriptPath, 'utf8');
  assert.match(source, /authentication_failed/);
  assert.match(source, /provider_capability_test_failed/);
  assert.match(source, /sk-\*\*\*/);
  assert.match(source, /FAKE_AUTH_KEY/);
  assert.doesNotMatch(source, /sk-[a-zA-Z0-9]{20,}/);
  assert.match(source, /TRAINER_PROVIDER_SMOKE_API_KEY/);
});

test('settings-provider smoke classifies auth + capability + network failures honestly', async () => {
  const mock = await startMockSidecar();
  try {
    const result = await runSmoke({
      TRAINER_SETTINGS_PROVIDER_SMOKE_SIDECAR_URL: mock.url,
      TRAINER_SETTINGS_PROVIDER_SMOKE_BASE_URL: 'http://relay.example.test',
      TRAINER_SETTINGS_PROVIDER_SMOKE_API_KEY: 'sk-live-fixture-not-used-when-skip',
      TRAINER_SETTINGS_PROVIDER_SMOKE_SKIP_LIVE: '1',
      TRAINER_PROVIDER_SMOKE_API_KEY: '',
      TRAINER_PROVIDER_SMOKE_BASE_URL: '',
    });
    assert.equal(result.code, 0, result.stdout + result.stderr);
    const report = JSON.parse(result.stdout.trim().split('\n').at(-1));
    assert.equal(report.ok, true);
    assert.equal(report.checks.auth_failure, 'passed');
    assert.equal(report.checks.capability_unknown_protocol, 'passed');
    assert.equal(report.checks.capability_network, 'passed');
    assert.equal(report.auth_failure.category, 'authentication_failed');
    assert.equal(report.capability_failure.category, 'provider_capability_test_failed');
    assert.equal(report.network_failure.category, 'network');
    assert.equal(typeof report.auth_failure.elapsedMs, 'number');
    assert.doesNotMatch(result.stdout, /sk-fake-settings-provider-auth-fail/);
  } finally {
    mock.server.close();
  }
});

test('settings-provider smoke fails closed when auth is misclassified', async () => {
  const mock = await startMockSidecar({ authCategory: 'unknown' });
  try {
    const result = await runSmoke({
      TRAINER_SETTINGS_PROVIDER_SMOKE_SIDECAR_URL: mock.url,
      TRAINER_SETTINGS_PROVIDER_SMOKE_BASE_URL: 'http://relay.example.test',
      TRAINER_SETTINGS_PROVIDER_SMOKE_SKIP_LIVE: '1',
      TRAINER_PROVIDER_SMOKE_API_KEY: '',
      TRAINER_PROVIDER_SMOKE_BASE_URL: '',
    });
    assert.equal(result.code, 1);
    const report = JSON.parse(result.stdout.trim().split('\n').at(-1));
    assert.equal(report.ok, false);
    assert.equal(report.honest_failure, true);
    assert.equal(report.step, 'auth_failure');
    assert.equal(report.category, 'provider_capability_test_failed');
  } finally {
    mock.server.close();
  }
});

test('settings-provider smoke source maps invalid_key_or_permission to authentication_failed', () => {
  const source = fs.readFileSync(scriptPath, 'utf8');
  assert.match(source, /rawCategory === "invalid_key_or_permission"/);
  assert.match(
    source,
    /category: "authentication_failed"/,
  );
});
