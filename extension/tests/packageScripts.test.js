'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const bundleSidecarModulePath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'bundle-sidecar.mjs',
);
const verifyPackageModulePath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'verify-package.mjs',
);
const bundleSidecarBinaryModulePath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'bundle-sidecar-binary.mjs',
);
const runServerTestsModulePath = path.resolve(
  __dirname,
  '..',
  '..',
  'scripts',
  'run-server-tests.mjs',
);
const prepareCurrentVsixModulePath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'prepare-current-vsix.mjs',
);
const packageVsixModulePath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'package-vsix.mjs',
);
const prepublishVsixModulePath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'prepublish-vsix.mjs',
);
const installVsixScriptPath = path.resolve(__dirname, '..', 'scripts', 'install-vsix.mjs');
const rootPackageJsonPath = path.resolve(__dirname, '..', '..', 'package.json');
const runServerTestsScriptPath = path.resolve(
  __dirname,
  '..',
  '..',
  'scripts',
  'run-server-tests.mjs',
);
const verifyWorkspaceScriptPath = path.resolve(
  __dirname,
  '..',
  '..',
  'scripts',
  'verify-workspace.mjs',
);
const lifecycleScriptPath = path.resolve(__dirname, '..', '..', 'scripts', 'lifecycle.mjs');
const extensionPackageJsonPath = path.resolve(__dirname, '..', 'package.json');
const webviewPackageJsonPath = path.resolve(__dirname, '..', 'webview', 'package.json');
const webviewVscodeIgnorePath = path.resolve(__dirname, '..', '.vscodeignore');
const buildWebviewPackageScriptPath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'build-webview-package.mjs',
);
const verifyWebviewRecoveryScriptPath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'verify-webview-recovery.mjs',
);
const verifyBundledSidecarRuntimeScriptPath = path.resolve(
  __dirname,
  '..',
  'scripts',
  'verify-bundled-sidecar-runtime.mjs',
);

let scriptsPromise;

function loadPackageScriptModules() {
  if (!scriptsPromise) {
    scriptsPromise = Promise.all([
      import(pathToFileURL(bundleSidecarModulePath).href),
      import(pathToFileURL(verifyPackageModulePath).href),
      import(pathToFileURL(bundleSidecarBinaryModulePath).href),
      import(pathToFileURL(runServerTestsModulePath).href),
      import(pathToFileURL(prepareCurrentVsixModulePath).href),
      import(pathToFileURL(packageVsixModulePath).href),
      import(pathToFileURL(prepublishVsixModulePath).href),
    ]).then(([
      bundleModule,
      verifyModule,
      binaryModule,
      runServerTestsModule,
      prepareModule,
      packageVsixModule,
      prepublishVsixModule,
    ]) => ({
      ...bundleModule,
      ...verifyModule,
      ...binaryModule,
      ...runServerTestsModule,
      ...prepareModule,
      ...packageVsixModule,
      ...prepublishVsixModule,
    }));
  }
  return scriptsPromise;
}

function writeFile(targetPath, content = '') {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(targetPath, content, 'utf8');
}

function bundledExecutableName() {
  return process.platform === 'win32' ? 'trainer-sidecar.exe' : 'trainer-sidecar';
}

function createFixtureRoot() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-package-scripts-'));
}

function createSidecarFixture(tempRoot) {
  const repoRoot = path.join(tempRoot, 'repo');
  const extensionDir = path.join(repoRoot, 'extension');
  const serverDir = path.join(repoRoot, 'server');

  writeFile(path.join(serverDir, 'run_sidecar.py'), 'print("sidecar")\n');
  writeFile(path.join(serverDir, 'README.md'), '# Trainer sidecar\n');
  writeFile(path.join(serverDir, 'pyproject.toml'), '[project]\nname="trainer-sidecar"\n');
  writeFile(path.join(serverDir, 'app', '__init__.py'), '');
  writeFile(
    path.join(serverDir, 'app', 'api', 'routers.py'),
    'def build_router():\n    return "ok"\n',
  );
  writeFile(
    path.join(serverDir, 'app', 'llm', 'provider_service.py'),
    'class ProviderService:\n    pass\n',
  );
  writeFile(path.join(serverDir, 'app', '._ghost.py'), 'ghost');
  writeFile(path.join(serverDir, 'app', '.DS_Store'), 'junk');
  writeFile(path.join(serverDir, 'app', '__pycache__', 'routers.cpython-312.pyc'), 'pyc');

  writeFile(path.join(extensionDir, 'dist', 'extension', 'src', 'extension.js'), 'export {};\n');
  writeFile(path.join(extensionDir, 'webview', 'dist', 'index.html'), '<html></html>\n');
  writeFile(path.join(extensionDir, 'webview', 'dist', 'vscode-preview.html'), '<html></html>\n');
  writeFile(
    path.join(
      extensionDir,
      'bundled',
      'bin',
      `${process.platform}-${process.arch}`,
      bundledExecutableName(),
    ),
    '',
  );

  return { repoRoot, extensionDir, serverDir };
}

test('package.json exposes the webview recovery verification script', () => {
  const packageJson = JSON.parse(fs.readFileSync(extensionPackageJsonPath, 'utf8'));
  assert.equal(
    packageJson.scripts['verify:coach-recovery'],
    'node --test ./tests/webviewBridge.test.js && npm run verify:webview-recovery',
  );
  assert.equal(
    packageJson.scripts['verify:webview-recovery'],
    'npm exec --yes --package playwright -- node ./scripts/verify-webview-recovery.mjs',
  );
  assert.equal(fs.existsSync(verifyWebviewRecoveryScriptPath), true);
});

test('webview builds keep the browserSidecar test contract separate from production packaging', () => {
  const webviewPackageJson = JSON.parse(fs.readFileSync(webviewPackageJsonPath, 'utf8'));
  assert.equal(webviewPackageJson.scripts.build, 'tsc -b && vite build');
  assert.equal(webviewPackageJson.scripts['build:preview'], 'tsc -b && vite build --mode preview');

  const ignoreEntries = fs.readFileSync(webviewVscodeIgnorePath, 'utf8');
  assert.match(ignoreEntries, /^webview\/browserSidecar-test\.js$/m);

  const buildSource = fs.readFileSync(buildWebviewPackageScriptPath, 'utf8');
  assert.match(buildSource, /removeTestOnlyEntries\(stagingDir\)/);
  assert.match(buildSource, /browserSidecar-test\.js/);
});

test('package scripts keep VSIX preparation and output routing explicit', () => {
  const packageJson = JSON.parse(fs.readFileSync(extensionPackageJsonPath, 'utf8'));

  assert.equal(packageJson.scripts['vscode:prepublish'], 'node ./scripts/prepublish-vsix.mjs');
  assert.equal(packageJson.scripts['package:vsix'], 'node ./scripts/package-vsix.mjs');
  assert.equal(
    packageJson.scripts['verify:sidecar-runtime'],
    'node ./scripts/verify-bundled-sidecar-runtime.mjs',
  );
  assert.equal(fs.existsSync(packageVsixModulePath), true);
  assert.equal(fs.existsSync(prepublishVsixModulePath), true);
  assert.equal(fs.existsSync(verifyBundledSidecarRuntimeScriptPath), true);
});

test('VSIX installer handles Windows code command wrappers', () => {
  const source = fs.readFileSync(installVsixScriptPath, 'utf8');

  assert.match(source, /process\.platform === "win32"\s*\? "code\.cmd"/);
  assert.match(source, /codeCli\.toLowerCase\(\)\.endsWith\("\.cmd"\)/);
  assert.match(source, /process\.env\.ComSpec \?\? "cmd\.exe"/);
  assert.match(source, /\["\/d", "\/c", buildWindowsCmd\(codeCli, installArgs\)\]/);
  assert.match(source, /return \["call", quoteWindowsCmdArg\(command\)/);
});

test('root package.json exposes the portable server test runner', () => {
  const packageJson = JSON.parse(fs.readFileSync(rootPackageJsonPath, 'utf8'));
  assert.equal(packageJson.scripts['test:server'], 'node ./scripts/run-server-tests.mjs');
  assert.equal(fs.existsSync(runServerTestsScriptPath), true);
});

test('root package.json exposes portable test and full verification entrypoints', () => {
  const packageJson = JSON.parse(fs.readFileSync(rootPackageJsonPath, 'utf8'));
  assert.equal(packageJson.scripts.test, 'npm run test:extension && npm run test:server');
  assert.equal(packageJson.scripts.verify, 'node ./scripts/verify-workspace.mjs');
  assert.equal(
    packageJson.scripts['verify:delivery'],
    'npm run verify && npm run test:experience-matrix && npm run package:vsix',
  );
  assert.equal(fs.existsSync(verifyWorkspaceScriptPath), true);

  const source = fs.readFileSync(verifyWorkspaceScriptPath, 'utf8');
  assert.match(source, /import \{ runServerCommand, runServerTests \} from "\.\/run-server-tests\.mjs"/);
  assert.match(source, /runNpm\(\["run", "build"\]/);
  assert.match(source, /runNpm\(\["run", "check"\]/);
  assert.match(source, /runNpm\(\["run", "test:extension"\]/);
  assert.match(source, /\["-m", "ruff", "check", "app", "tests"\]/);
  assert.match(source, /\["-m", "pyright", "app"\]/);
});

test('root package.json exposes portable lifecycle entrypoints', async () => {
  const packageJson = JSON.parse(fs.readFileSync(rootPackageJsonPath, 'utf8'));
  assert.equal(packageJson.scripts.bootstrap, 'node ./scripts/lifecycle.mjs bootstrap');
  assert.equal(packageJson.scripts.dev, 'node ./scripts/lifecycle.mjs dev');
  assert.equal(packageJson.scripts['dev:sidecar'], 'node ./scripts/lifecycle.mjs dev --start-sidecar');
  assert.equal(packageJson.scripts.smoke, 'node ./scripts/lifecycle.mjs smoke');
  assert.equal(packageJson.scripts['smoke:strict'], 'node ./scripts/lifecycle.mjs smoke --strict');
  assert.equal(fs.existsSync(lifecycleScriptPath), true);

  const lifecycle = await import(pathToFileURL(lifecycleScriptPath).href);
  assert.equal(
    lifecycle.getVenvPythonPath('H:/trainer', 'win32'),
    path.join('H:/trainer', 'server', '.venv', 'Scripts', 'python.exe'),
  );
  assert.equal(
    lifecycle.getVenvPythonPath('/tmp/trainer', 'linux'),
    path.join('/tmp/trainer', 'server', '.venv', 'bin', 'python'),
  );
  assert.deepEqual(
    lifecycle.parseLifecycleArgs(['smoke', '--strict', '--port', '8765,34891']),
    { command: 'smoke', host: '127.0.0.1', port: 8765, ports: [8765, 34891], strict: true },
  );
  assert.equal(
    lifecycle.parseLifecycleArgs(['smoke', '--provider-api-key=abc=def']).providerApiKey,
    'abc=def',
  );
  assert.equal(
    lifecycle.parseLifecycleArgs(['smoke', '--sidecar-url=https://example.test/v1?token=a=b']).sidecarUrl,
    'https://example.test/v1?token=a=b',
  );
  assert.deepEqual(lifecycle.getSmokePorts({ port: 8765, ports: [] }).slice(0, 3), [8765, 34891, 34892]);
  assert.deepEqual(lifecycle.getSmokePorts({ port: 8765, ports: [34911, 34911] }), [34911]);
  assert.equal(
    lifecycle.getSystemPythonCandidates({ platform: 'win32', env: {} })[0].label,
    'py -3.12',
  );
  assert.equal(
    lifecycle.getSystemPythonCandidates({ platform: 'linux', env: {} })[0].label,
    'python3.12',
  );
});

test('root package.json exposes explicit provider and trainer turn smoke script entrypoints', () => {
  const packageJson = JSON.parse(fs.readFileSync(rootPackageJsonPath, 'utf8'));
  assert.equal(packageJson.scripts['smoke:provider'], 'node ./scripts/provider-smoke.mjs');
  assert.equal(packageJson.scripts['smoke:trainer-turn'], 'node ./scripts/trainer-turn-smoke.mjs');
  assert.equal(packageJson.scripts['smoke:training-return'], 'node ./scripts/training-return-smoke.mjs');
});

test('resolvePythonCandidates prefers local virtualenvs before system fallbacks', async () => {
  const { resolvePythonCandidates } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const serverDir = path.join(tempRoot, 'server');
    const windowsPython = path.join(serverDir, '.venv', 'Scripts', 'python.exe');
    const posixPython = path.join(serverDir, '.venv-mac', 'bin', 'python');
    writeFile(windowsPython, '');
    writeFile(posixPython, '');

    const candidates = resolvePythonCandidates({
      serverRoot: serverDir,
      platform: 'win32',
      env: {},
    });

    assert.equal(candidates[0].command, windowsPython);
    assert.equal(candidates[1].command, posixPython);
    assert.equal(candidates.at(-1).command, 'python');
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('resolvePythonCandidates prefers POSIX virtualenvs on Linux and macOS', async () => {
  const { resolvePythonCandidates } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const serverDir = path.join(tempRoot, 'server');
    const windowsPython = path.join(serverDir, '.venv', 'Scripts', 'python.exe');
    const posixPython = path.join(serverDir, '.venv', 'bin', 'python');
    const legacyPosixPython = path.join(serverDir, '.venv-mac', 'bin', 'python');
    writeFile(windowsPython, '');
    writeFile(posixPython, '');
    writeFile(legacyPosixPython, '');

    for (const platform of ['linux', 'darwin']) {
      const candidates = resolvePythonCandidates({
        serverRoot: serverDir,
        platform,
        env: {},
      });

      assert.equal(candidates[0].command, posixPython);
      assert.equal(candidates[1].command, legacyPosixPython);
      assert.equal(candidates.at(-1).command, 'python');
    }
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('shouldSkipBundledSidecarPath ignores Apple metadata and cache junk only', async () => {
  const { shouldSkipBundledSidecarPath } = await loadPackageScriptModules();

  assert.equal(shouldSkipBundledSidecarPath('H:\\trainer\\server\\app\\._routers.py'), true);
  assert.equal(shouldSkipBundledSidecarPath('H:\\trainer\\server\\app\\.DS_Store'), true);
  assert.equal(shouldSkipBundledSidecarPath('H:\\trainer\\server\\app\\__pycache__'), true);
  assert.equal(shouldSkipBundledSidecarPath('H:\\trainer\\server\\app\\routers.py'), false);
});

test('bundleSidecar copies required sidecar files and drops metadata junk', async () => {
  const { bundleSidecar } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const { repoRoot, extensionDir } = createSidecarFixture(tempRoot);
    const result = bundleSidecar({ extensionDir, repoRoot });

    assert.equal(
      fs.existsSync(path.join(result.targetServerDir, 'run_sidecar.py')),
      true,
    );
    assert.equal(
      fs.existsSync(path.join(result.targetServerDir, 'app', 'api', 'routers.py')),
      true,
    );
    assert.equal(
      fs.existsSync(path.join(result.targetServerDir, 'app', '._ghost.py')),
      false,
    );
    assert.equal(
      fs.existsSync(path.join(result.targetServerDir, 'app', '.DS_Store')),
      false,
    );
    assert.equal(
      fs.existsSync(
        path.join(result.targetServerDir, 'app', '__pycache__', 'routers.cpython-312.pyc'),
      ),
      false,
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('resolvePythonBin prefers platform-appropriate local environments', async () => {
  const { resolvePythonBin } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const serverDir = path.join(tempRoot, 'server');
    const windowsPython = path.join(serverDir, '.venv', 'Scripts', 'python.exe');
    const posixPython = path.join(serverDir, '.venv-mac', 'bin', 'python');
    writeFile(windowsPython, '');
    writeFile(posixPython, '');

    const resolved = resolvePythonBin(serverDir, process.platform);
    const expected = process.platform === 'win32' ? windowsPython : posixPython;
    assert.equal(resolved, expected);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('sidecar binary packaging messages stay platform-neutral', () => {
  const source = fs.readFileSync(bundleSidecarBinaryModulePath, 'utf8');

  assert.match(
    source,
    /PyInstaller is missing from the local Trainer Python environment\. Installing it\.\.\./,
  );
  assert.match(
    source,
    /Could not install PyInstaller for the local Trainer Python environment\./,
  );
  assert.doesNotMatch(source, /PyInstaller not found in server\/\.venv-mac/);
  assert.doesNotMatch(source, /Failed to install PyInstaller into server\/\.venv-mac/);
});

test('sidecar binary build root confines an external scratch root to a dedicated child', async () => {
  const { resolveBinaryBundlePaths } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const extensionDir = path.join(tempRoot, 'extension');
    const scratchRoot = path.join(tempRoot, 'scratch');
    const paths = resolveBinaryBundlePaths({
      extensionDir,
      repoRoot: tempRoot,
      env: { TRAINER_SIDECAR_BUILD_ROOT: scratchRoot },
    });

    assert.equal(paths.buildRoot, path.join(scratchRoot, 'trainer-sidecar-build'));
    assert.equal(
      resolveBinaryBundlePaths({
        extensionDir,
        repoRoot: tempRoot,
        platform: 'win32-x64',
      }).entryName,
      'trainer-sidecar.exe',
    );
    assert.equal(
      resolveBinaryBundlePaths({
        extensionDir,
        repoRoot: tempRoot,
        platform: 'linux-x64',
      }).entryName,
      'trainer-sidecar',
    );
    assert.throws(
      () => resolveBinaryBundlePaths({ extensionDir, repoRoot: tempRoot, env: { TRAINER_SIDECAR_BUILD_ROOT: 'relative' } }),
      /must be an absolute directory/,
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('target-specific packaging removes inherited sidecar binaries for other targets', async () => {
  const { clearForeignSidecarBinaries, resolveNativeSidecarTarget } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();
  const extensionDir = path.join(tempRoot, 'extension');
  const targetPlatform = resolveNativeSidecarTarget();
  const foreignTarget = targetPlatform === 'win32-x64' ? 'darwin-arm64' : 'win32-x64';

  try {
    writeFile(path.join(extensionDir, 'bundled', 'bin', targetPlatform, 'trainer-sidecar'), 'native');
    writeFile(path.join(extensionDir, 'bundled', 'bin', foreignTarget, 'trainer-sidecar'), 'foreign');

    assert.deepEqual(clearForeignSidecarBinaries({ extensionDir, targetPlatform }), [foreignTarget]);
    assert.equal(
      fs.existsSync(path.join(extensionDir, 'bundled', 'bin', targetPlatform, 'trainer-sidecar')),
      true,
    );
    assert.equal(
      fs.existsSync(path.join(extensionDir, 'bundled', 'bin', foreignTarget, 'trainer-sidecar')),
      false,
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('VSIX output routing binds each package to its native target', async () => {
  const {
    buildVscePackageArgs,
    resolveNativeSidecarTarget,
    resolveVsixOutputPath,
  } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();
  const extensionDir = path.join(tempRoot, 'extension');
  const packageJson = { name: 'trainer-extension', version: '0.1.0' };
  const outputPath = path.join(tempRoot, 'artifacts', 'trainer-current.vsix');
  const targetPlatform = resolveNativeSidecarTarget();

  try {
    assert.equal(
      resolveVsixOutputPath({ extensionDir, packageJson, env: {} }),
      path.join(extensionDir, `trainer-extension-0.1.0-${targetPlatform}.vsix`),
    );
    assert.equal(
      resolveVsixOutputPath({ extensionDir, packageJson, env: { TRAINER_VSIX_OUTPUT_PATH: outputPath } }),
      outputPath,
    );
    const packageArgs = buildVscePackageArgs(outputPath, targetPlatform);
    assert.deepEqual(packageArgs.slice(-2), ['--out', outputPath]);
    assert.deepEqual(
      packageArgs.slice(packageArgs.indexOf('--target'), packageArgs.indexOf('--target') + 3),
      ['--target', targetPlatform, '--ignore-other-target-folders'],
    );
    assert.equal(resolveNativeSidecarTarget({ platform: 'darwin', arch: 'arm64' }), 'darwin-arm64');
    assert.throws(
      () => resolveNativeSidecarTarget({ platform: 'linux', arch: 'arm' }),
      /does not support packaging a native sidecar/i,
    );
    assert.throws(
      () => resolveVsixOutputPath({ extensionDir, packageJson, env: { TRAINER_VSIX_OUTPUT_PATH: 'trainer.vsix' } }),
      /must be an absolute .vsix path/,
    );
    assert.throws(
      () => resolveVsixOutputPath({ extensionDir, packageJson, env: { TRAINER_VSIX_OUTPUT_PATH: path.join(tempRoot, 'trainer.zip') } }),
      /must end in .vsix/,
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('VSIX target inspection requires the declared native runtime and rejects foreign targets', async () => {
  const { inspectVsixTargetContents } = await loadPackageScriptModules();
  const targetPlatform = 'win32-x64';
  const valid = inspectVsixTargetContents({
    targetPlatform,
    manifestXml: '<Identity Id="trainer-extension" TargetPlatform="win32-x64"/>',
    entryNames: [
      'extension.vsixmanifest',
      'extension/bundled/bin/win32-x64/trainer-sidecar.exe',
      'extension/bundled/bin/win32-x64/trainer-sidecar-manifest.json',
    ],
  });
  assert.deepEqual(valid.errors, []);

  const invalid = inspectVsixTargetContents({
    targetPlatform,
    manifestXml: '<Identity Id="trainer-extension" TargetPlatform="linux-x64"/>',
    entryNames: [
      'extension.vsixmanifest',
      'extension/bundled/bin/linux-x64/trainer-sidecar',
    ],
  });
  assert.ok(invalid.errors.some((message) => message.includes('declares target linux-x64')));
  assert.ok(invalid.errors.some((message) => message.includes('win32-x64 runtime entry')));
  assert.deepEqual(invalid.foreignRuntimeEntries, ['extension/bundled/bin/linux-x64/trainer-sidecar']);
});

test('package verification refuses a target label that cannot match the native binary', async () => {
  const { resolveNativeSidecarTarget, resolvePackageTarget } = await loadPackageScriptModules();
  const nativeTarget = resolveNativeSidecarTarget();
  const otherTarget = nativeTarget === 'win32-x64' ? 'linux-x64' : 'win32-x64';

  assert.equal(
    resolvePackageTarget({ nativeTarget, env: { TRAINER_VSIX_TARGET: nativeTarget } }),
    nativeTarget,
  );
  assert.throws(
    () => resolvePackageTarget({ nativeTarget, env: { TRAINER_VSIX_TARGET: otherTarget } }),
    /refusing to label it/i,
  );
});

test('VSIX packaging publishes the target-specific artifact path to CI', async () => {
  const { writeGitHubOutputs } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();
  const outputFile = path.join(tempRoot, 'github-output.txt');

  try {
    writeGitHubOutputs({
      outputPath: path.join(tempRoot, 'trainer-extension-0.1.0-win32-x64.vsix'),
      targetPlatform: 'win32-x64',
      env: { GITHUB_OUTPUT: outputFile },
    });

    assert.equal(
      fs.readFileSync(outputFile, 'utf8'),
      `vsix_path=${path.join(tempRoot, 'trainer-extension-0.1.0-win32-x64.vsix')}\nvsix_target=win32-x64\n`,
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('prepublish reuse refuses a bundled binary whose manifest no longer matches source', async () => {
  const {
    bundleSidecar,
    prepublishVsix,
    resolveBinaryBundlePaths,
    writeSidecarBinaryManifest,
  } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const { repoRoot, extensionDir, serverDir } = createSidecarFixture(tempRoot);
    const nativeTarget = `${process.platform}-${process.arch}`;
    const foreignTarget = nativeTarget === 'win32-x64' ? 'darwin-arm64' : 'win32-x64';
    bundleSidecar({ extensionDir, repoRoot });
    writeSidecarBinaryManifest(resolveBinaryBundlePaths({ extensionDir, repoRoot }));
    writeFile(path.join(extensionDir, 'bundled', 'bin', foreignTarget, 'trainer-sidecar'), 'foreign');
    writeFile(
      path.join(serverDir, 'app', 'llm', 'provider_service.py'),
      'class ProviderService:\n    fresh = True\n',
    );

    const scripts = [];
    assert.throws(
      () => prepublishVsix({
        extensionDir,
        repoRoot,
        env: { TRAINER_REUSE_VERIFIED_SIDECAR_BINARY: '1' },
        runScript(scriptName) {
          scripts.push(scriptName);
        },
      }),
      /requires a sidecar binary whose manifest matches the current server source/,
    );
    assert.deepEqual(scripts, ['clean', 'build', 'build:webview']);
    assert.equal(
      fs.existsSync(path.join(extensionDir, 'bundled', 'bin', foreignTarget, 'trainer-sidecar')),
      true,
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('prepublish reuse performs full package verification after source bundle parity', async () => {
  const {
    bundleSidecar,
    prepublishVsix,
    resolveBinaryBundlePaths,
    writeSidecarBinaryManifest,
  } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const { repoRoot, extensionDir } = createSidecarFixture(tempRoot);
    const nativeTarget = `${process.platform}-${process.arch}`;
    const foreignTarget = nativeTarget === 'win32-x64' ? 'darwin-arm64' : 'win32-x64';
    bundleSidecar({ extensionDir, repoRoot });
    writeSidecarBinaryManifest(resolveBinaryBundlePaths({ extensionDir, repoRoot }));
    writeFile(path.join(extensionDir, 'bundled', 'bin', foreignTarget, 'trainer-sidecar'), 'foreign');

    const scripts = [];
    const result = prepublishVsix({
      extensionDir,
      repoRoot,
      env: { TRAINER_REUSE_VERIFIED_SIDECAR_BINARY: '1' },
      runScript(scriptName) {
        scripts.push(scriptName);
        if (scriptName === 'bundle:sidecar') {
          bundleSidecar({ extensionDir, repoRoot });
        }
      },
    });

    assert.equal(result.reusedBinary, true);
    assert.deepEqual(result.removedForeignTargets, [foreignTarget]);
    assert.equal(result.packageReport.ok, true);
    assert.deepEqual(scripts, [
      'clean',
      'build',
      'build:webview',
      'bundle:sidecar',
      'verify:sidecar-runtime',
    ]);
    assert.equal(
      fs.existsSync(path.join(extensionDir, 'bundled', 'bin', foreignTarget, 'trainer-sidecar')),
      false,
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('cleanupStaleVsixBuildLock removes dead-process locks', async () => {
  const { cleanupStaleVsixBuildLock } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();
  const lockPath = path.join(tempRoot, '.vsix-build.lock');

  try {
    writeFile(lockPath, '999999\n');

    const result = cleanupStaleVsixBuildLock(lockPath);
    assert.equal(result.removed, true);
    assert.equal(result.reason, 'dead-process');
    assert.equal(fs.existsSync(lockPath), false);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('verifyWebviewDist requires both entries and every local asset', async () => {
  const { verifyWebviewDist } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();
  try {
    writeFile(path.join(tempRoot, 'index.html'), '<script src="./assets/app-123.js"></script>');
    writeFile(path.join(tempRoot, 'vscode-preview.html'), '<link href="./assets/app-123.css">');
    writeFile(path.join(tempRoot, 'assets', 'app-123.js'), 'ok');
    writeFile(path.join(tempRoot, 'assets', 'app-123.css'), 'ok');
    assert.equal(verifyWebviewDist({ webviewDistDir: tempRoot }).ok, true);
    fs.rmSync(path.join(tempRoot, 'assets', 'app-123.css'));
    const invalid = verifyWebviewDist({ webviewDistDir: tempRoot });
    assert.equal(invalid.ok, false);
    assert.deepEqual(invalid.missingAssets, [{ entry: 'vscode-preview.html', reference: './assets/app-123.css' }]);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('verifyPackage passes when bundled sidecar matches the source server', async () => {
  const {
    bundleSidecar,
    resolveBinaryBundlePaths,
    verifyPackage,
    writeSidecarBinaryManifest,
  } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const { repoRoot, extensionDir } = createSidecarFixture(tempRoot);
    bundleSidecar({ extensionDir, repoRoot });
    writeSidecarBinaryManifest(resolveBinaryBundlePaths({ extensionDir, repoRoot }));

    const report = verifyPackage({ extensionDir, repoRoot });
    assert.equal(report.ok, true);
    assert.equal(report.missingRequiredPaths.length, 0);
    assert.equal(report.metadataJunk.length, 0);
    assert.equal(report.sidecarParity.contentMismatches.length, 0);
    assert.equal(report.sidecarParity.unexpectedBundledFiles.length, 0);
    assert.equal(report.binaryManifest.errors.length, 0);
    assert.ok(report.sidecarParity.checkedFileCount >= 5);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('verifyPackage detects bundled sidecar drift and bundled metadata junk', async () => {
  const {
    bundleSidecar,
    resolveBinaryBundlePaths,
    verifyPackage,
    formatPackageVerificationErrors,
    writeSidecarBinaryManifest,
  } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const { repoRoot, extensionDir } = createSidecarFixture(tempRoot);
    bundleSidecar({ extensionDir, repoRoot });
    writeSidecarBinaryManifest(resolveBinaryBundlePaths({ extensionDir, repoRoot }));

    writeFile(
      path.join(extensionDir, 'bundled', 'server', 'app', 'api', 'routers.py'),
      'def build_router():\n    return "drifted"\n',
    );
    writeFile(
      path.join(extensionDir, 'bundled', 'server', 'app', '._metadata.py'),
      'junk',
    );

    const report = verifyPackage({ extensionDir, repoRoot });
    assert.equal(report.ok, false);
    assert.deepEqual(report.sidecarParity.contentMismatches, ['app/api/routers.py']);
    assert.deepEqual(report.metadataJunk, [
      {
        scope: 'bundled/server',
        relativePath: 'app/._metadata.py',
      },
    ]);
    const errorLines = formatPackageVerificationErrors(report);
    assert.ok(
      errorLines.some((line) => line.includes('Bundled sidecar drift detected: bundled/server/app/api/routers.py')),
    );
    assert.ok(
      errorLines.some((line) => line.includes('Metadata junk in bundled/server: app/._metadata.py')),
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('verifyPackage detects stale bundled sidecar binary manifests after source changes', async () => {
  const {
    bundleSidecar,
    formatPackageVerificationErrors,
    resolveBinaryBundlePaths,
    verifyPackage,
    writeSidecarBinaryManifest,
  } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const { repoRoot, extensionDir, serverDir } = createSidecarFixture(tempRoot);
    bundleSidecar({ extensionDir, repoRoot });
    writeSidecarBinaryManifest(resolveBinaryBundlePaths({ extensionDir, repoRoot }));

    writeFile(
      path.join(serverDir, 'app', 'llm', 'provider_service.py'),
      'class ProviderService:\n    fresh = True\n',
    );

    const report = verifyPackage({ extensionDir, repoRoot });
    assert.equal(report.ok, false);
    assert.equal(report.binaryManifest.errors.length, 1);
    assert.match(
      report.binaryManifest.errors[0],
      /Bundled sidecar binary drift detected: bundled\/bin\//,
    );
    const errorLines = formatPackageVerificationErrors(report);
    assert.ok(
      errorLines.some((line) => line.includes('Bundled sidecar binary drift detected: bundled/bin/')),
    );
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('verifyPackage keeps cross-target inventory diagnostic-only for a native package', async () => {
  const {
    bundleSidecar,
    formatPackageVerificationErrors,
    resolveBinaryBundlePaths,
    verifyPackage,
    writeSidecarBinaryManifest,
  } = await loadPackageScriptModules();
  const tempRoot = createFixtureRoot();

  try {
    const { repoRoot, extensionDir } = createSidecarFixture(tempRoot);
    bundleSidecar({ extensionDir, repoRoot });
    writeSidecarBinaryManifest(resolveBinaryBundlePaths({ extensionDir, repoRoot }));

    const nativeTarget = `${process.platform}-${process.arch}`;
    const unverifiedTarget = nativeTarget === 'darwin-arm64' ? 'linux-x64' : 'darwin-arm64';
    writeFile(path.join(extensionDir, 'bundled', 'bin', unverifiedTarget, 'trainer-sidecar'), '');

    const report = verifyPackage({ extensionDir, repoRoot });

    assert.equal(report.ok, true);
    assert.equal(report.binaryTargetCoverage.complete, false);
    assert.ok(report.binaryTargetCoverage.invalidTargets.includes(unverifiedTarget));
    assert.ok(report.binaryTargetCoverage.missingExpectedTargets.length >= 1);
    const errorLines = formatPackageVerificationErrors(report);
    assert.equal(
      errorLines.some((line) => line.includes(`bundled/bin/${unverifiedTarget}`)),
      false,
    );
    assert.equal(errorLines.some((line) => line.includes('Cross-target sidecar coverage')), false);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});
