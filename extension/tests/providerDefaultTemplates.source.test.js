'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const registryPath = path.resolve(
  __dirname,
  '..',
  'src',
  'provider',
  'providerProfileRegistry.ts',
);
const statusPath = path.resolve(
  __dirname,
  '..',
  '..',
  'shared',
  'src',
  'providerStatus.ts',
);

test('default Kimi OpenAI and OpenRouter templates use live model ids and Moonshot Kimi URL', () => {
  const source = fs.readFileSync(registryPath, 'utf8');
  assert.match(source, /label: 'Kimi'/);
  assert.match(source, /baseUrl: 'https:\/\/api\.moonshot\.cn\/v1'/);
  assert.match(source, /model: 'kimi-k3'/);
  assert.doesNotMatch(source, /model: 'moonshot-v1-8k'/);
  assert.doesNotMatch(source, /llm\.longai\.vip/);
  assert.match(source, /label: 'OpenAI'/);
  assert.match(source, /model: 'gpt-5-mini'/);
  assert.doesNotMatch(source, /model: 'gpt-5\.1-mini'/);
  assert.match(source, /label: 'OpenRouter'/);
  assert.match(source, /model: 'openai\/gpt-5-mini'/);
  assert.doesNotMatch(source, /model: 'openai\/gpt-5\.1-mini'/);
});

test('New API empty URL and model is not treated as a configured transport', () => {
  const registry = fs.readFileSync(registryPath, 'utf8');
  const status = fs.readFileSync(statusPath, 'utf8');
  assert.match(registry, /label: 'New API'/);
  assert.match(registry, /baseUrl: ''/);
  assert.match(registry, /model: ''/);
  assert.match(status, /export function providerTransportIsConfigured/);
  assert.match(status, /const transportMissing =/);
  assert.match(status, /!provider\.configured \|\| transportMissing/);
});
