'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const extensionDir = path.resolve(__dirname, '..');
const fixtureModulePath = path.resolve(extensionDir, 'scripts', 'vsix-e2e-fixture-provider.mjs');
const runtimeModulePath = path.resolve(extensionDir, 'scripts', 'vsix-e2e-provider-runtime.mjs');

async function loadFixtureHelpers() {
  return import(pathToFileURL(fixtureModulePath).href);
}

async function loadRuntimeHelpers() {
  return import(pathToFileURL(runtimeModulePath).href);
}

async function fixtureRequest(baseUrl, apiKey, requestPath, options = {}) {
  const response = await fetch(new URL(requestPath, `${baseUrl.replace(/\/+$/, '')}/`), {
    ...options,
    headers: {
      authorization: `Bearer ${apiKey}`,
      ...(options.headers ?? {}),
    },
  });
  return {
    response,
    body: await response.json(),
  };
}

test('VSIX E2E fixture provider exposes a deterministic OpenAI-compatible model and preserves Chinese probes', async () => {
  const { VSIX_E2E_FIXTURE_PROVIDER_MODEL, startVsixE2EFixtureProvider } = await loadFixtureHelpers();
  const apiKey = `test-${randomUUID()}`;
  const fixture = await startVsixE2EFixtureProvider({ apiKey });

  try {
    const models = await fixtureRequest(fixture.baseUrl, apiKey, 'models');
    assert.equal(models.response.status, 200);
    assert.deepEqual(models.body.data.map((model) => model.id), [VSIX_E2E_FIXTURE_PROVIDER_MODEL]);

    const completion = await fixtureRequest(fixture.baseUrl, apiKey, 'chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        model: VSIX_E2E_FIXTURE_PROVIDER_MODEL,
        messages: [
          { role: 'system', content: 'Reply in Chinese only. Keep required phrases exactly.' },
          { role: 'user', content: '只用简体中文回答一句话，并完整保留“先学再测”和“VS Code”。' },
        ],
      }),
    });
    assert.equal(completion.response.status, 200);
    assert.match(completion.body.choices[0].message.content, /先学再测/);
    assert.match(completion.body.choices[0].message.content, /VS Code/);
  } finally {
    await fixture.stop();
  }
});

test('VSIX E2E fixture provider verifies the forced tool-call contract without a stored credential', async () => {
  const { VSIX_E2E_FIXTURE_PROVIDER_MODEL, startVsixE2EFixtureProvider } = await loadFixtureHelpers();
  const apiKey = `test-${randomUUID()}`;
  const fixture = await startVsixE2EFixtureProvider({ apiKey });

  try {
    const unauthorized = await fetch(new URL('models', `${fixture.baseUrl}/`));
    assert.equal(unauthorized.status, 401);

    const completion = await fixtureRequest(fixture.baseUrl, apiKey, 'chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        model: VSIX_E2E_FIXTURE_PROVIDER_MODEL,
        messages: [{ role: 'user', content: 'Call the supplied tool.' }],
        tools: [{ type: 'function', function: { name: 'trainer_capability_probe' } }],
        tool_choice: { type: 'function', function: { name: 'trainer_capability_probe' } },
      }),
    });
    assert.equal(completion.response.status, 200);
    assert.equal(completion.body.choices[0].finish_reason, 'tool_calls');
    assert.equal(completion.body.choices[0].message.tool_calls[0].function.name, 'trainer_capability_probe');
  } finally {
    await fixture.stop();
  }
});

test('VSIX E2E uses an external provider only when its complete override is present', async () => {
  const { resolveVsixE2EProviderRuntime } = await loadRuntimeHelpers();
  let fixtureStarted = false;
  const runtime = await resolveVsixE2EProviderRuntime({
    extensionDir,
    requestedProtocol: 'openai_chat_completions_compatible',
    env: {
      TRAINER_E2E_PROVIDER_BASE_URL: 'https://provider.example/v1',
      TRAINER_E2E_PROVIDER_API_KEY: 'runtime-only-key',
      TRAINER_E2E_PROVIDER_MODEL: 'external-model',
    },
    startFixture: async () => {
      fixtureStarted = true;
      throw new Error('fixture should not start for an external override');
    },
  });

  assert.equal(fixtureStarted, false);
  assert.equal(runtime.source, 'external');
  assert.equal(runtime.baseUrl, 'https://provider.example/v1');
  assert.equal(runtime.model, 'external-model');
  await runtime.stop();
});

test('VSIX E2E falls back to the local fixture for empty or partial provider environment', async () => {
  const { resolveVsixE2EProviderRuntime } = await loadRuntimeHelpers();
  const fixture = {
    baseUrl: 'http://127.0.0.1:45678/v1',
    apiKey: `test-${randomUUID()}`,
    model: 'trainer-e2e-fixture-model',
    protocol: 'openai_chat_completions_compatible',
    stop: async () => {},
    readStats: async () => ({ modelsRequests: 1, chatCompletionRequests: 1 }),
  };
  const runtime = await resolveVsixE2EProviderRuntime({
    extensionDir,
    requestedProtocol: 'anthropic_messages',
    env: { TRAINER_E2E_PROVIDER_BASE_URL: 'https://incomplete.example/v1' },
    startFixture: async () => fixture,
  });

  assert.equal(runtime.source, 'fixture');
  assert.equal(runtime.usedPartialExternalOverride, true);
  assert.equal(runtime.configuration.protocol, 'openai_chat_completions_compatible');
  assert.equal(runtime.model, fixture.model);
  await runtime.stop();
});

test('VSIX E2E fixture mode preserves existing proxy exclusions and always bypasses loopback', async () => {
  const { withVsixE2EFixtureLoopbackBypass } = await loadRuntimeHelpers();
  const environment = withVsixE2EFixtureLoopbackBypass({
    NO_PROXY: 'internal.example,localhost',
    no_proxy: '127.0.0.1',
  });

  assert.equal(environment.NO_PROXY, 'internal.example,localhost,127.0.0.1');
  assert.equal(environment.no_proxy, environment.NO_PROXY);
});
