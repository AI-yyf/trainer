'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const providerModelPolicyModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'shared',
  'src',
  'providerModelPolicy.js',
);

test('provider model policy is case-insensitive and gives deny rules priority', () => {
  const { evaluateProviderModelPolicy } = require(providerModelPolicyModulePath);
  const policy = {
    allowedModels: ['GPT-4.1', 'claude-sonnet'],
    deniedModels: ['gpt-4.1'],
  };

  assert.deepEqual(evaluateProviderModelPolicy(' gPt-4.1 ', policy), {
    model: 'gPt-4.1',
    allowed: false,
    reason: 'denied',
  });
  assert.equal(evaluateProviderModelPolicy('CLAUDE-SONNET', policy).allowed, true);
  assert.equal(evaluateProviderModelPolicy('gpt-4o', policy).reason, 'not_allowed');
  assert.equal(evaluateProviderModelPolicy('', policy).reason, 'empty');
});

test('provider model policy filters new choices while retaining a recoverable current model', () => {
  const { filterProviderModelOptions } = require(providerModelPolicyModulePath);
  const policy = {
    allowedModels: ['gpt-4.1', 'claude-sonnet'],
    deniedModels: ['claude-sonnet'],
  };

  assert.deepEqual(
    filterProviderModelOptions(
      ['gpt-4o', 'GPT-4.1', 'claude-sonnet', 'gpt-4.1'],
      policy,
      { retainModels: ['gpt-4o'] },
    ),
    ['gpt-4o', 'GPT-4.1'],
  );
});

test('pickDefaultModelFromList prefers fast tiers then alphabetical order', async () => {
  const { pickDefaultModelFromList } = await import(providerModelPolicyModulePath);

  assert.equal(
    pickDefaultModelFromList(['MiniMax-M3', 'MiniMax-M2.7', 'MiniMax-M2.7-highspeed']),
    'MiniMax-M2.7-highspeed',
  );
  assert.equal(pickDefaultModelFromList(['zeta-model', 'alpha-model']), 'alpha-model');
  assert.equal(pickDefaultModelFromList(['gpt-a', 'gpt-b']), 'gpt-a');
  assert.equal(pickDefaultModelFromList([]), undefined);
});

test('pickFreshConnectionModel never overrides explicit or still-offered models', async () => {
  const { pickFreshConnectionModel } = await import(providerModelPolicyModulePath);
  const models = ['MiniMax-M2.7', 'MiniMax-M2.7-highspeed', 'MiniMax-M3'];

  // Fresh paste without a model: adopt the quick pick.
  assert.equal(pickFreshConnectionModel(undefined, models, false), 'MiniMax-M2.7-highspeed');
  // Carried-over model the provider still offers: keep it.
  assert.equal(pickFreshConnectionModel('minimax-m2.7', models, false), undefined);
  // Carried-over model the provider no longer lists: adopt.
  assert.equal(pickFreshConnectionModel('gpt-4.1-mini', models, false), 'MiniMax-M2.7-highspeed');
  // Explicitly typed models are never overridden.
  assert.equal(pickFreshConnectionModel(undefined, models, true), undefined);
  assert.equal(pickFreshConnectionModel('gpt-4.1-mini', models, true), undefined);
  // Nothing to adopt from.
  assert.equal(pickFreshConnectionModel(undefined, [], false), undefined);
});
