'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const esbuild = require('../webview/node_modules/esbuild');

const modulePath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'providerModelAdaptation.ts');
const compiled = esbuild.buildSync({
  entryPoints: [modulePath], bundle: true, platform: 'node', format: 'cjs', write: false,
});
const mod = new Module(modulePath, module);
mod.filename = modulePath;
mod.paths = Module._nodeModulePaths(path.dirname(modulePath));
mod._compile(compiled.outputFiles[0].text, modulePath);
const { inferProviderModelAdaptation, recommendProviderModel } = mod.exports;

test('known model families get conservative starting capabilities', () => {
  const deepseek = inferProviderModelAdaptation({ model: 'deepseek-v4.1-flash' });
  assert.equal(deepseek.confidence, 'known');
  assert.equal(deepseek.supportsTools, true);
  assert.equal(deepseek.supportsThinking, true);
  assert.equal(deepseek.supportsVision, false);

  const minimax = inferProviderModelAdaptation({ model: 'minimax-m3' });
  assert.equal(minimax.supportsThinking, true);
  assert.equal(minimax.supportsTools, true);

  const glm = inferProviderModelAdaptation({ model: 'glm-5.3-flash' });
  assert.equal(glm.supportsThinking, true);
  assert.equal(glm.supportsTools, true);

  const claude = inferProviderModelAdaptation({ model: 'claude-3-7-sonnet' });
  assert.equal(claude.supportsVision, true);
  assert.equal(claude.supportsThinking, true);
});

test('unknown models stay fail-closed until a real test observes capabilities', () => {
  const unknown = inferProviderModelAdaptation({ model: 'mystery-chat-1' });
  assert.equal(unknown.family, 'unknown');
  assert.equal(unknown.confidence, 'unknown');
  assert.equal(unknown.supportsTools, false);
  assert.equal(unknown.supportsVision, false);
  assert.equal(unknown.supportsThinking, false);
});

test('recommended model skips embeddings and prefers chat models', () => {
  assert.equal(
    recommendProviderModel(
      ['text-embedding-3-small', 'deepseek-v4.1-flash', 'whisper-1'],
      { protocol: 'openai_chat_completions_compatible', providerName: 'LinkSub' },
    ),
    'deepseek-v4.1-flash',
  );
  assert.equal(
    recommendProviderModel(['text-embedding-3-small', 'rerank-v1'], { protocol: 'openai_chat_completions_compatible' }),
    undefined,
  );
});
