'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const commandModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'coachScenarioCommands.js',
);

function createContext(language = 'en-US') {
  const calls = [];
  return {
    calls,
    getHostState() {
      return {
        bootstrap: {
          memory: {
            workspace: {
              responseLanguage: language,
            },
          },
        },
      };
    },
    workbench: {
      async show() {
        calls.push('show');
      },
      async syncState() {
        calls.push('sync');
      },
      async postMessage(message) {
        calls.push(message);
      },
    },
  };
}

test('native coach scenario command opens Coach with a localized prefilled prompt', async () => {
  const { openCoachScenarioCommand } = require(commandModulePath);
  const context = createContext('zh-CN');

  const result = await openCoachScenarioCommand(context, 'remoteBoundary');

  assert.equal(result.ok, true);
  assert.deepEqual(context.calls.slice(0, 2), ['show', 'sync']);
  assert.equal(context.calls[2].type, 'ui/coachPrompt');
  assert.equal(context.calls[2].payload.source, 'commandPalette');
  assert.match(context.calls[2].payload.draft, /VS Code/);
  assert.match(context.calls[2].payload.draft, /不要修改正式计划/);
});
