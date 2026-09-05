'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const configPath = path.resolve(__dirname, '..', '..', 'playwright.config.js');

function loadConfig({ port, reuseExistingServer } = {}) {
  const previousPort = process.env.TRAINER_E2E_PORT;
  const previousReuse = process.env.TRAINER_E2E_REUSE_EXISTING_SERVER;

  try {
    if (port === undefined) {
      delete process.env.TRAINER_E2E_PORT;
    } else {
      process.env.TRAINER_E2E_PORT = port;
    }
    if (reuseExistingServer === undefined) {
      delete process.env.TRAINER_E2E_REUSE_EXISTING_SERVER;
    } else {
      process.env.TRAINER_E2E_REUSE_EXISTING_SERVER = reuseExistingServer;
    }
    delete require.cache[configPath];
    return require(configPath);
  } finally {
    if (previousPort === undefined) {
      delete process.env.TRAINER_E2E_PORT;
    } else {
      process.env.TRAINER_E2E_PORT = previousPort;
    }
    if (previousReuse === undefined) {
      delete process.env.TRAINER_E2E_REUSE_EXISTING_SERVER;
    } else {
      process.env.TRAINER_E2E_REUSE_EXISTING_SERVER = previousReuse;
    }
    delete require.cache[configPath];
  }
}

test('Playwright starts a fresh isolated Trainer preview by default', () => {
  const config = loadConfig();

  assert.equal(config.use.baseURL, 'http://127.0.0.1:4175');
  assert.equal(config.webServer.url, 'http://127.0.0.1:4175');
  assert.match(config.webServer.command, /--port 4175/);
  assert.equal(config.webServer.reuseExistingServer, false);
});

test('Playwright supports an explicit isolated port and opt-in server reuse', () => {
  const config = loadConfig({ port: '4199', reuseExistingServer: '1' });

  assert.equal(config.use.baseURL, 'http://127.0.0.1:4199');
  assert.match(config.webServer.command, /--port 4199/);
  assert.equal(config.webServer.reuseExistingServer, true);
});
