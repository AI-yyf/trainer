// Restored behavioral regression test. Original file: extension/tests/providerModelPolicy.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Provider model policy: case-insensitive rules with deny priority and recoverable current model.
//
// Restoration: partial - 2 of 4 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "pickDefaultModelFromList prefers fast tiers then alphabetical order"
//       fails at HEAD: pickDefaultModelFromList is not a function
//   - "pickFreshConnectionModel never overrides explicit or still-offered models"
//       fails at HEAD: pickFreshConnectionModel is not a function
// Target: compiled shared modules (extension/dist/shared/src).

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

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

