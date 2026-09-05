'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');

const capabilityModulePath = path.resolve(__dirname, '..', '..', 'scripts', 'vsix-ci-capability.mjs');
const workflowPath = path.resolve(__dirname, '..', '..', '.github', 'workflows', 'cross-platform-verify.yml');
const installSmokePath = path.resolve(__dirname, '..', 'scripts', 'verify-vsix-install.mjs');

async function loadCapabilityModule() {
  return import(pathToFileURL(capabilityModulePath).href);
}

test('VSIX CI capability distinguishes installation from Linux host-E2E readiness', async () => {
  const { detectVsixCiCapability } = await loadCapabilityModule();
  const result = detectVsixCiCapability({
    platform: 'linux',
    env: {},
    runCommand(command) {
      if (command === 'code') {
        return { status: 0 };
      }
      if (command === 'xvfb-run') {
        return { status: 0 };
      }
      return { status: 1 };
    },
  });

  assert.equal(result.installAvailable, true);
  assert.equal(result.hostE2EAvailable, true);
  assert.equal(result.linuxUseXvfb, true);
});

test('VSIX CI capability leaves missing host support visible instead of treating it as a pass', async () => {
  const { detectVsixCiCapability, formatVsixCiGate } = await loadCapabilityModule();
  const result = detectVsixCiCapability({
    platform: 'linux',
    env: {},
    runCommand() {
      return { status: 1 };
    },
  });

  assert.equal(result.installAvailable, false);
  assert.equal(result.hostE2EAvailable, false);
  assert.match(formatVsixCiGate(result, 'install'), /not run/);
  assert.match(formatVsixCiGate(result, 'host'), /manual release gate/);
});

test('cross-platform workflow keeps all experience layers and an explicit VSIX host gate', () => {
  const source = fs.readFileSync(workflowPath, 'utf8');

  for (const runner of ['ubuntu-latest', 'macos-latest', 'windows-latest']) {
    assert.match(source, new RegExp(`- ${runner}`));
  }
  assert.match(source, /npm run test:experience-matrix/);
  assert.match(source, /npm run test:experience-sidecar/);
  assert.match(source, /node extension\/scripts\/verify-vsix-install\.mjs/);
  assert.match(source, /npm run test:vsix-e2e/);
  assert.match(source, /run_vsix_host_e2e/);
  assert.match(source, /--manual-host-e2e-gate/);
  assert.match(source, /--require-host-e2e/);
  assert.match(source, /id: package-vsix/);
  assert.match(source, /uses: actions\/upload-artifact@v4/);
  assert.match(source, /trainer-vsix-\$\{\{ steps\.package-vsix\.outputs\.vsix_target \}\}/);
  assert.match(source, /path: \$\{\{ steps\.package-vsix\.outputs\.vsix_path \}\}/);
});

test('installed VSIX smoke starts the extracted native sidecar', () => {
  const source = fs.readFileSync(installSmokePath, 'utf8');

  assert.match(source, /verifyBundledSidecarRuntime/);
  assert.match(source, /await verifyBundledSidecarRuntime\(\{ extensionDir: installedRoot \}\)/);
});
