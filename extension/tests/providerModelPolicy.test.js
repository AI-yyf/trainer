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
