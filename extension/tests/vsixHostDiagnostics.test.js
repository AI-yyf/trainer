'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '../..');
const load = () => import(pathToFileURL(path.join(root, 'extension/scripts/vsix-host-diagnostics.mjs')).href);
const write = (file, text) => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
};

test('failure diagnostics copy bounded isolated Code logs and redact credentials without reading other profiles', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-host-diag-'));
  const tempRoot = path.join(directory, 'isolated');
  const userDataDir = path.join(tempRoot, 'user-data');
  const driverDir = path.join(tempRoot, 'driver');
  const extensionsDir = path.join(tempRoot, 'extensions');
  const outputDir = path.join(directory, 'evidence');
  const secret = 'synthetic-private-provider-value';
  try {
    write(path.join(userDataDir, 'logs/session/main.log'), `startup\nBearer abc-private\nTRAINER_SIDECAR_TOKEN=private-session\n${secret}\n`);
    write(path.join(userDataDir, 'logs/session/exthost.log'), 'x'.repeat(500) + '\nactivation failed');
    write(path.join(userDataDir, 'User/state.vscdb'), 'private database must not be copied');
    write(path.join(directory, 'private-profile/main.log'), 'outside profile must not be read');
    write(path.join(driverDir, 'package.json'), JSON.stringify({ main: './extension.js', activationEvents: ['onStartupFinished'], privateField: secret }));
    write(path.join(driverDir, 'extension.js'), 'module.exports = {};');
    fs.mkdirSync(extensionsDir);
    fs.symlinkSync(path.join(directory, 'private-profile'), path.join(userDataDir, 'logs/other-profile'), process.platform === 'win32' ? 'junction' : 'dir');
    const { captureVsixHostFailureDiagnostics } = await load();
    const result = captureVsixHostFailureDiagnostics({
      tempRoot, userDataDir, driverDir, extensionsDir, outputDir, secrets: [secret], maxLogBytes: 128,
      attempts: [{ error: { code: 'ETIMEDOUT' }, stderr: `api_key=${secret}`, status: null }],
      env: { DISPLAY: ':99', TRAINER_E2E_PROVIDER_API_KEY: secret, OTHER_PRIVATE_ENV: secret },
    });
    assert.equal(result.logCount, 2);
    const summaryText = fs.readFileSync(path.join(result.directory, 'diagnostics.json'), 'utf8');
    const summary = JSON.parse(summaryText);
    assert.deepEqual(summary.environment, { DISPLAY: ':99' });
    assert.equal(summary.attempts[0].error.code, 'ETIMEDOUT');
    assert.equal(summary.driver.mainExists, true);
    assert.ok(summary.logs.find((item) => item.path.endsWith('exthost.log')).truncated);
    const main = fs.readFileSync(path.join(result.directory, 'logs/session/main.log'), 'utf8');
    assert.match(main, /startup/);
    assert.match(main, /\[redacted\]/);
    for (const text of [main, summaryText]) assert.doesNotMatch(text, /private-session|abc-private|synthetic-private-provider-value/);
    assert.equal(fs.existsSync(path.join(result.directory, 'logs/other-profile')), false);
    assert.equal(fs.existsSync(path.join(result.directory, 'User')), false);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('actual host harness preserves launch failure and exports Code diagnostics before removing its temporary profile', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-host-failure-'));
  try {
    const fakeDriver = path.join(directory, 'fake-code.cjs');
    const fakeCli = path.join(directory, process.platform === 'win32' ? 'fake-code.cmd' : 'fake-code');
    const vsix = path.join(directory, 'fixture.vsix');
    const reportPath = path.join(directory, 'evidence/host-report.json');
    const secret = 'synthetic-private-provider-value';
    write(fakeDriver, `
      const fs = require('node:fs');
      const path = require('node:path');
      if (process.argv.includes('--install-extension')) process.exit(0);
      const profile = process.argv[process.argv.indexOf('--user-data-dir') + 1];
      const logs = path.join(profile, 'logs', 'startup');
      fs.mkdirSync(logs, { recursive: true });
      fs.writeFileSync(path.join(logs, 'main.log'), 'synthetic startup failure\\nBearer private-log-key');
      fs.writeFileSync(path.join(logs, 'renderer.log'), process.env.TRAINER_E2E_ARTIFACTS_DIR);
      // Execute the actual generated driver, then strand extension activation.
      // Its incremental report must distinguish this from a driver never started.
      const Module = require('node:module');
      const originalLoad = Module._load;
      Module._load = function(name, ...args) {
        if (name === 'vscode') return { extensions: { getExtension: () => ({
          id: 'local.trainer-extension', packageJSON: { name: 'trainer-extension', version: '1.3.4' },
          activate: () => new Promise(() => {}),
        }) } };
        return originalLoad.call(this, name, ...args);
      };
      const driver = process.argv[process.argv.indexOf('--extensionDevelopmentPath') + 1];
      require(path.join(driver, 'extension.js')).activate();
      setTimeout(() => {
        console.error('synthetic launch failed ' + process.env.TRAINER_E2E_PROVIDER_API_KEY);
        process.exit(23);
      }, 200);
    `);
    const quote = (value) => `'${value.replaceAll("'", "'\\''")}'`;
    write(fakeCli, process.platform === 'win32'
      ? `@echo off\r\n"${process.execPath}" "${fakeDriver}" %*\r\nexit /b %ERRORLEVEL%\r\n`
      : `#!/bin/sh\nexec ${quote(process.execPath)} ${quote(fakeDriver)} "$@"\n`);
    if (process.platform !== 'win32') fs.chmodSync(fakeCli, 0o755);
    write(vsix, 'not a product artifact: only the synthetic launch-failure path is exercised');
    const result = spawnSync(process.execPath, [path.join(root, 'extension/scripts/verify-vsix-e2e.mjs')], {
      cwd: root, encoding: 'utf8', timeout: 15000,
      env: {
        ...process.env, CODE_CLI_PATH: fakeCli, TRAINER_VSIX_OUTPUT_PATH: vsix,
        TRAINER_SKIP_VSIX_REBUILD: '1', TRAINER_E2E_EXPORT_REPORT_PATH: path.relative(root, reportPath),
        TRAINER_E2E_PROVIDER_BASE_URL: 'http://127.0.0.1:1/v1', TRAINER_E2E_PROVIDER_API_KEY: secret,
        TRAINER_E2E_PROVIDER_MODEL: 'synthetic-model', TRAINER_KEEP_VSIX_E2E: '0',
        TRAINER_KEEP_VSIX_E2E_ON_FAILURE: '0', TRAINER_VSIX_E2E_TEMP_ROOT: '',
      },
    });
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stderr, /synthetic launch failed/);
    assert.doesNotMatch(result.stderr, new RegExp(secret));
    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
    assert.equal(report.ok, false);
    assert.equal(report.report, null);
    assert.equal(fs.existsSync(report.tempRoot), false);
    const diagnostics = JSON.parse(fs.readFileSync(path.join(report.diagnostics.directory, 'diagnostics.json'), 'utf8'));
    assert.equal(diagnostics.attempts.length, 2);
    assert.equal(diagnostics.attempts[1].status, 23);
    assert.ok(diagnostics.attempts[1].args.includes('--extensionDevelopmentPath'));
    assert.deepEqual(diagnostics.driver.activationEvents, ['onStartupFinished']);
    assert.equal(diagnostics.driver.mainExists, true);
    assert.match(fs.readFileSync(path.join(report.diagnostics.directory, 'logs/startup/main.log'), 'utf8'), /synthetic startup failure/);
    assert.equal(fs.readFileSync(path.join(report.diagnostics.directory, 'logs/startup/renderer.log'), 'utf8'), path.join(path.dirname(reportPath), 'vsix-installed-state'));
    const progress = JSON.parse(fs.readFileSync(path.join(report.artifactsDir, 'host-progress.json'), 'utf8'));
    assert.deepEqual(progress.steps.map((step) => [step.name, step.state]), [
      ['find-installed-extension', 'passed'], ['activate-installed-extension', 'running'],
    ]);
    assert.ok(progress.steps.every((step) => Object.keys(step).every((key) => ['name', 'state', 'startedAt', 'finishedAt'].includes(key))));
    assert.doesNotMatch(JSON.stringify(report) + JSON.stringify(diagnostics), new RegExp(secret));
  } finally {
    fs.rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
});
