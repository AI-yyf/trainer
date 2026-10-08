'use strict';

const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const { syncBuiltinESMExports } = require('node:module');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');

const capabilityModulePath = path.resolve(__dirname, '..', '..', 'scripts', 'vsix-ci-capability.mjs');
const workflowPath = path.resolve(__dirname, '..', '..', '.github', 'workflows', 'cross-platform-verify.yml');
const installSmokePath = path.resolve(__dirname, '..', 'scripts', 'verify-vsix-install.mjs');

async function loadCapabilityModule() {
  return import(pathToFileURL(capabilityModulePath).href);
}

function artifactUploadPaths(source, artifactName) {
  const step = source.split(/^      - /m).find((candidate) =>
    candidate.includes('uses: actions/upload-artifact@v4') &&
    candidate.includes(`name: ${artifactName}\n`));
  assert.ok(step, `Missing artifact upload: ${artifactName}`);
  const lines = step.split('\n');
  const pathLine = lines.findIndex((line) => /^          path: /.test(line));
  assert.ok(pathLine >= 0, `Missing paths for artifact: ${artifactName}`);
  const value = lines[pathLine].slice('          path: '.length).trim();
  if (value !== '|') return [value];
  const paths = [];
  for (const line of lines.slice(pathLine + 1)) {
    if (!line.startsWith('            ')) break;
    const entry = line.trim();
    if (entry) paths.push(entry);
  }
  return paths;
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

test('Windows capability probe preserves CMD quoting through the actual spawn dispatcher', async () => {
  const originalSpawnSync = childProcess.spawnSync;
  const codeCli = 'C:\\Program Files\\Microsoft VS Code\\bin\\code.cmd';
  const env = { CODE_CLI_PATH: codeCli, ComSpec: 'C:\\Windows\\System32\\cmd.exe' };
  const calls = [];
  childProcess.spawnSync = (command, args, options) => {
    calls.push({ command, args, options });
    // CMD must receive the quoted command unchanged. Node's default argument
    // escaping alters those embedded quotes and makes a usable CLI fail.
    return { status: options.windowsVerbatimArguments === true ? 0 : 1 };
  };
  syncBuiltinESMExports();
  try {
    const { detectVsixCiCapability } = await loadCapabilityModule();
    const result = detectVsixCiCapability({
      platform: 'win32',
      env,
      existsSync: (candidate) => candidate === codeCli,
    });
    assert.equal(result.codeCli, codeCli);
    assert.equal(result.installAvailable, true);
    assert.equal(result.hostE2EAvailable, true);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, env.ComSpec);
    assert.deepEqual(calls[0].args, ['/d', '/c', `call "${codeCli}" --version`]);
    assert.equal(calls[0].options.windowsVerbatimArguments, true);
    assert.equal(calls[0].options.env, env);
    assert.equal(calls[0].options.timeout, 10000);
  } finally {
    childProcess.spawnSync = originalSpawnSync;
    syncBuiltinESMExports();
  }
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
  // Parallel package jobs upload per-OS artifacts, so the matrix OS prefixes
  // the target-qualified name.
  const artifactName = 'trainer-vsix-${{ matrix.os }}-${{ steps.package-vsix.outputs.vsix_target }}';
  assert.deepEqual(artifactUploadPaths(source, artifactName), [
    '${{ steps.package-vsix.outputs.vsix_path }}',
    '${{ steps.package-vsix.outputs.vsix_metadata_path }}',
  ]);
});

test('installed VSIX smoke starts the extracted native sidecar', () => {
  const source = fs.readFileSync(installSmokePath, 'utf8');

  assert.match(source, /verifyBundledSidecarRuntime/);
  assert.match(source, /await verifyBundledSidecarRuntime\(\{ extensionDir: installedRoot \}\)/);
});

test('locked uv workflow jobs do not register an unused pip post-job cache', () => {
  const workflowDir = path.dirname(workflowPath);
  for (const name of fs.readdirSync(workflowDir).filter((name) => name.endsWith('.yml'))) {
    const source = fs.readFileSync(path.join(workflowDir, name), 'utf8');
    if (!source.includes('uses: astral-sh/setup-uv@')) continue;
    assert.doesNotMatch(source, /^\s+cache: pip\s*$/m,
      `${name}: uv does not populate the pip cache; setup-python post-job would fail`);
    assert.match(source, /uv sync [^\n]*--frozen/, `${name}: Python installation must use the lock`);
  }
});

test('workflow dispatch diagnostic scope selects one actual-host package without changing full matrices or their concurrency', () => {
  const source = fs.readFileSync(workflowPath, 'utf8');
  assert.match(source, /diagnostic_package_platform:\n[\s\S]*?default: none\n[\s\S]*?type: choice/);
  const job = (name) => source.split(new RegExp(`^  ${name}:\\n`, 'm'))[1].split(/^  [a-z]+:\n/m)[0];
  const expression = (value, github, inputs) => Function('github', 'inputs', 'fromJSON', 'format',
    `return (${value.match(/\$\{\{\s*([\s\S]*?)\s*\}\}/)[1]});`)(github, inputs, JSON.parse,
      (template, value) => template.replace('{0}', value));
  const group = (github, inputs) => source.match(/^  group: (.*)$/m)[1].replace(/\$\{\{.*?\}\}/g, (value) => expression(value, github, inputs));
  const cases = [
    ['push', 'none', 9], ['pull_request', 'none', 9], ['workflow_dispatch', 'none', 9],
    ['push', 'ubuntu-latest', 9], ['pull_request', 'windows-latest', 9],
    ...['ubuntu-latest', 'macos-latest', 'windows-latest'].map((runner) => ['workflow_dispatch', runner, 1]),
  ];
  for (const [event, diagnostic, expectedCount] of cases) {
    const github = { event_name: event, ref: 'refs/heads/main' };
    const inputs = { diagnostic_package_platform: diagnostic, run_vsix_host_e2e: true };
    let count = 0;
    for (const name of ['server', 'ui']) {
      const block = job(name);
      if (expression(block.match(/^    if: (.*)$/m)[1], github, inputs)) {
        assert.deepEqual([...block.matchAll(/^          - (.*)$/gm)].map((match) => match[1]), ['ubuntu-latest', 'macos-latest', 'windows-latest']);
        count += 3;
      }
    }
    const block = job('package');
    const runners = expression(block.match(/^        os: (.*)$/m)[1], github, inputs);
    assert.deepEqual(runners, expectedCount === 1 ? [diagnostic] : ['ubuntu-latest', 'macos-latest', 'windows-latest']);
    count += runners.length;
    assert.equal(count, expectedCount, `${event}/${diagnostic}`);
    const requireHost = block.split('- name: Require actual host acceptance')[1].match(/^        if: (.*)$/m)[1];
    assert.equal(expression(requireHost, github, { ...inputs, run_vsix_host_e2e: false }), expectedCount === 1);
    assert.match(block, /partial diagnostic scope[\s\S]*cannot establish full acceptance/i);
  }
  const github = { event_name: 'workflow_dispatch', ref: 'refs/heads/main' };
  assert.notEqual(group(github, { diagnostic_package_platform: 'none' }), group(github, { diagnostic_package_platform: 'ubuntu-latest' }));
  assert.equal(group({ ...github, event_name: 'push' }, {}), group(github, { diagnostic_package_platform: 'none' }));
  assert.match(job('package'), /Diagnostic package/);
});
