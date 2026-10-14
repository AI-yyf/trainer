'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const os = require('node:os');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const installBundleModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'browserCapture',
  'installBundle.js',
);
const commandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'browserCaptureCommands.js',
);
const commandIndexModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'index.js',
);
const constantsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'constants.js',
);
const extensionPackageJsonPath = path.resolve(__dirname, '..', 'package.json');
const vscodeIgnorePath = path.resolve(__dirname, '..', '.vscodeignore');

const VSCODE_MOCK = { window: {}, workspace: {}, commands: {} };

function writeFile(targetPath, content = '') {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(targetPath, content, 'utf8');
}

function createTempRoot() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'trainer-browser-capture-'));
}

function createCaptureSource(rootDir) {
  writeFile(path.join(rootDir, 'manifest.json'), JSON.stringify({ version: '0.1.0' }));
  writeFile(path.join(rootDir, 'background.js'), '// service worker\n');
  writeFile(path.join(rootDir, 'shared.js'), '// shared helpers\n');
  writeFile(path.join(rootDir, 'popup', 'popup.html'), '<html></html>\n');
  writeFile(path.join(rootDir, 'popup', 'popup.js'), '// popup\n');
  writeFile(path.join(rootDir, 'icons', 'icon16.png'), 'png');
  writeFile(path.join(rootDir, 'README.md'), '# Trainer Capture\n');
}

function loadInstallBundle() {
  return loadWithVscodeMock(installBundleModulePath, VSCODE_MOCK);
}

test('installCaptureBundle copies the bundle and prunes files from an older version', () => {
  const { installCaptureBundle, readCaptureBundleMarker } = loadInstallBundle();
  const tempRoot = createTempRoot();
  try {
    const sourceDir = path.join(tempRoot, 'browser-capture');
    const targetDir = path.join(tempRoot, 'home', '.trainer', 'browser-capture');
    createCaptureSource(sourceDir);
    // Packaging junk never reaches the staged bundle, and must never arrive in
    // the install directory either.
    writeFile(path.join(sourceDir, '._ghost.js'), 'ghost');
    writeFile(path.join(sourceDir, '.DS_Store'), 'junk');
    writeFile(path.join(sourceDir, 'trainer-capture-extension.zip'), 'zip');
    writeFile(
      path.join(sourceDir, 'trainer-browser-capture.json'),
      JSON.stringify({ schemaVersion: 1, name: 'trainer-capture', version: '0.1.0', fileCount: 6 }),
    );
    // Stale content from a previous install.
    writeFile(path.join(targetDir, 'background.js'), '// old service worker\n');
    writeFile(path.join(targetDir, 'removed-script.js'), '// stale\n');
    writeFile(path.join(targetDir, 'legacy', 'old.html'), '<html>old</html>\n');

    const result = installCaptureBundle({ sourceDir, targetDir });

    assert.equal(result.targetDir, targetDir);
    assert.equal(result.version, '0.1.0');
    // Seven extension files plus the staging version marker.
    assert.equal(result.fileCount, 8);
    assert.equal(fs.readFileSync(path.join(targetDir, 'background.js'), 'utf8'), '// service worker\n');
    assert.equal(fs.existsSync(path.join(targetDir, 'popup', 'popup.js')), true);
    assert.equal(fs.existsSync(path.join(targetDir, 'icons', 'icon16.png')), true);
    assert.equal(fs.existsSync(path.join(targetDir, 'removed-script.js')), false);
    assert.equal(fs.existsSync(path.join(targetDir, 'legacy', 'old.html')), false);
    assert.equal(fs.existsSync(path.join(targetDir, '._ghost.js')), false);
    assert.equal(fs.existsSync(path.join(targetDir, '.DS_Store')), false);
    assert.equal(fs.existsSync(path.join(targetDir, 'trainer-capture-extension.zip')), false);
    assert.deepEqual(readCaptureBundleMarker(targetDir), {
      schemaVersion: 1,
      name: 'trainer-capture',
      version: '0.1.0',
      fileCount: 6,
    });
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('installCaptureBundle refuses a bundle without manifest.json', () => {
  const { installCaptureBundle, CaptureBundleSourceError } = loadInstallBundle();
  const tempRoot = createTempRoot();
  try {
    const sourceDir = path.join(tempRoot, 'browser-capture');
    fs.mkdirSync(sourceDir, { recursive: true });
    writeFile(path.join(sourceDir, 'background.js'), '// service worker\n');

    assert.throws(
      () => installCaptureBundle({ sourceDir, targetDir: path.join(tempRoot, 'target') }),
      (error) => error instanceof CaptureBundleSourceError && /manifest\.json/.test(error.message),
    );
    assert.equal(fs.existsSync(path.join(tempRoot, 'target')), false);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('the install directory resolves to ~/.trainer/browser-capture unless an absolute override is set', () => {
  const { resolveCaptureInstallDir, resolveInstalledCaptureDir } = loadInstallBundle();

  assert.equal(
    resolveInstalledCaptureDir('/home/trainer'),
    path.join('/home/trainer', '.trainer', 'browser-capture'),
  );
  assert.equal(
    resolveCaptureInstallDir({ homeDir: '/home/trainer', env: {} }),
    path.join('/home/trainer', '.trainer', 'browser-capture'),
  );
  assert.equal(
    resolveCaptureInstallDir({ homeDir: '/home/trainer', env: { TRAINER_BROWSER_CAPTURE_INSTALL_DIR: '/tmp/capture' } }),
    path.resolve('/tmp/capture'),
  );
  assert.throws(
    () => resolveCaptureInstallDir({ homeDir: '/home/trainer', env: { TRAINER_BROWSER_CAPTURE_INSTALL_DIR: 'relative-dir' } }),
    /must be an absolute directory/,
  );
});

test('the folder opener follows the platform and degrades without spawning', () => {
  const { resolveOpenFolderCommand, openCaptureFolder } = loadInstallBundle();

  assert.deepEqual(resolveOpenFolderCommand('/home/trainer/.trainer/browser-capture', 'darwin'), {
    command: 'open',
    args: ['/home/trainer/.trainer/browser-capture'],
  });
  assert.deepEqual(resolveOpenFolderCommand('C:\\Users\\trainer\\.trainer\\browser-capture', 'win32'), {
    command: 'explorer',
    args: ['C:\\Users\\trainer\\.trainer\\browser-capture'],
  });
  assert.deepEqual(resolveOpenFolderCommand('/home/trainer/.trainer/browser-capture', 'linux'), {
    command: 'xdg-open',
    args: ['/home/trainer/.trainer/browser-capture'],
  });

  const spawned = [];
  const spawnResult = { unref() {} };
  const open = openCaptureFolder('/tmp/capture', {
    platform: 'darwin',
    spawnFn: (command, args, options) => {
      spawned.push({ command, args, options });
      return spawnResult;
    },
  });
  assert.deepEqual(open, { command: 'open', args: ['/tmp/capture'], spawned: true });
  assert.equal(spawned.length, 1);
  assert.equal(spawned[0].options.detached, true);

  const failed = openCaptureFolder('/tmp/capture', {
    platform: 'linux',
    spawnFn: () => {
      throw new Error('xdg-open is not installed');
    },
  });
  assert.equal(failed.spawned, false);
  assert.equal(failed.command, 'xdg-open');
});

test('the three-step guide names chrome://extensions, Developer mode and Load unpacked', () => {
  const { captureInstallGuide } = loadInstallBundle();
  const guide = captureInstallGuide({ targetDir: '/home/trainer/.trainer/browser-capture', version: '0.1.0' });

  assert.match(guide, /Trainer Capture 0\.1\.0/);
  assert.match(guide, /1\. Open chrome:\/\/extensions/);
  assert.match(guide, /2\. Turn on Developer mode/);
  assert.match(guide, /3\. Choose "Load unpacked"/);
  assert.match(guide, /\/home\/trainer\/\.trainer\/browser-capture/);
});

function createInstallVscodeMock({ infoChoice, messages, clipboardWrites, registeredCommandIds }) {
  return {
    Uri: {
      joinPath(base, ...segments) {
        return { fsPath: path.join(base.fsPath, ...segments) };
      },
    },
    window: {
      showInformationMessage: async (message, ...actions) => {
        messages.push({ message, actions });
        return infoChoice;
      },
      showWarningMessage: async () => undefined,
      showErrorMessage: async () => undefined,
      showQuickPick: async () => undefined,
      showOpenDialog: async () => undefined,
    },
    env: { clipboard: { writeText: async (text) => clipboardWrites.push(text) } },
    commands: {
      registerCommand(commandId, handler) {
        registeredCommandIds?.push(commandId);
        return { dispose() {} };
      },
      executeCommand: async () => undefined,
    },
    workspace: { isTrusted: true },
  };
}

function loadInstallCommand(vscodeMock, spawned) {
  const originalLoad = Module._load;
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === 'node:child_process' || request === 'child_process') {
      return {
        spawn(command, args, options) {
          spawned.push({ command, args, options });
          return { unref() {} };
        },
        spawnSync() {
          return { status: 0, stdout: '', stderr: '' };
        },
      };
    }
    return originalLoad.call(this, request, parent, isMain);
  };
  try {
    return loadWithVscodeMock(commandsModulePath, vscodeMock);
  } finally {
    Module._load = originalLoad;
  }
}

test('the install command copies the bundled extension, opens the folder and shows the guide', async () => {
  const tempRoot = createTempRoot();
  const previousOverride = process.env.TRAINER_BROWSER_CAPTURE_INSTALL_DIR;
  try {
    const extensionDir = path.join(tempRoot, 'extension');
    createCaptureSource(path.join(extensionDir, 'browser-capture'));
    writeFile(
      path.join(extensionDir, 'browser-capture', 'trainer-browser-capture.json'),
      JSON.stringify({ schemaVersion: 1, name: 'trainer-capture', version: '0.1.0', fileCount: 7 }),
    );
    const installDir = path.join(tempRoot, 'sandboxed-install');
    process.env.TRAINER_BROWSER_CAPTURE_INSTALL_DIR = installDir;

    const messages = [];
    const clipboardWrites = [];
    const spawned = [];
    const vscodeMock = createInstallVscodeMock({
      infoChoice: 'Copy Folder Path',
      messages,
      clipboardWrites,
    });
    const { installBrowserCaptureCommand } = loadInstallCommand(vscodeMock, spawned);
    const context = {
      extensionContext: { extensionUri: { fsPath: extensionDir }, subscriptions: [] },
      outputChannel: { appendLine() {} },
    };

    const result = await installBrowserCaptureCommand(context);

    assert.equal(result.ok, true);
    assert.equal(result.data.targetDir, installDir);
    assert.equal(result.data.version, '0.1.0');
    assert.equal(fs.existsSync(path.join(installDir, 'manifest.json')), true);
    assert.equal(fs.existsSync(path.join(installDir, 'trainer-browser-capture.json')), true);
    assert.equal(spawned.length, 1);
    assert.equal(spawned[0].args[0], installDir);
    assert.equal(messages.length, 1);
    assert.match(messages[0].message, /chrome:\/\/extensions/);
    assert.match(messages[0].message, /Developer mode/);
    assert.match(messages[0].message, /Load unpacked/);
    assert.deepEqual(messages[0].actions, ['Copy Folder Path']);

    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(clipboardWrites, [installDir]);
  } finally {
    if (previousOverride === undefined) {
      delete process.env.TRAINER_BROWSER_CAPTURE_INSTALL_DIR;
    } else {
      process.env.TRAINER_BROWSER_CAPTURE_INSTALL_DIR = previousOverride;
    }
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('the install command fails closed when this build has no browser-capture bundle', async () => {
  const tempRoot = createTempRoot();
  try {
    const messages = [];
    const spawned = [];
    const vscodeMock = createInstallVscodeMock({ messages, clipboardWrites: [] });
    const { installBrowserCaptureCommand } = loadInstallCommand(vscodeMock, spawned);

    const result = await installBrowserCaptureCommand({
      extensionContext: { extensionUri: { fsPath: path.join(tempRoot, 'extension') }, subscriptions: [] },
      outputChannel: { appendLine() {} },
    });

    assert.equal(result.ok, false);
    assert.match(result.message, /does not bundle the browser capture extension/);
    assert.deepEqual(messages, []);
    assert.deepEqual(spawned, []);
    assert.equal(fs.existsSync(path.join(tempRoot, 'extension')), false);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('the capture commands are declared in the manifest and registered by the command table', () => {
  const { COMMAND_IDS } = require(constantsModulePath);
  const manifest = JSON.parse(fs.readFileSync(extensionPackageJsonPath, 'utf8'));
  const declared = manifest.contributes.commands.map((entry) => entry.command);
  const expected = [
    COMMAND_IDS.browserCaptureInstall,
    COMMAND_IDS.browserCapturePairingCode,
    COMMAND_IDS.browserCaptureRevokePairing,
  ];

  assert.deepEqual(expected, [
    'trainer.browserCapture.install',
    'trainer.browserCapture.pairingCode',
    'trainer.browserCapture.revokePairing',
  ]);
  for (const commandId of expected) {
    assert.ok(declared.includes(commandId), `manifest should declare ${commandId}`);
  }

  const registeredCommandIds = [];
  const messages = [];
  const vscodeMock = createInstallVscodeMock({
    messages,
    clipboardWrites: [],
    registeredCommandIds,
  });
  vscodeMock.window.createOutputChannel = () => ({ appendLine() {} });
  const { registerCommands } = loadWithVscodeMock(commandIndexModulePath, vscodeMock);
  registerCommands({ subscriptions: [] }, {
    outputChannel: { appendLine() {} },
    sidecarClient: {},
    getHostState: () => ({ workspace: {}, bootstrap: {} }),
    workbench: {
      show: async () => undefined,
      syncState: async () => undefined,
      postMessage: async () => undefined,
      setRefreshHandler: () => undefined,
    },
  });

  for (const commandId of expected) {
    assert.ok(registeredCommandIds.includes(commandId), `registry should register ${commandId}`);
  }
});

test('the packaged VSIX keeps browser-capture outside every .vscodeignore exclusion', () => {
  const vscodeIgnore = fs.readFileSync(vscodeIgnorePath, 'utf8');
  const manifest = JSON.parse(fs.readFileSync(extensionPackageJsonPath, 'utf8'));

  assert.equal(
    manifest.scripts['bundle:browser-capture'],
    'node ./scripts/bundle-browser-capture.mjs',
  );
  for (const line of vscodeIgnore.split(/\r?\n/)) {
    const pattern = line.trim();
    if (!pattern || pattern.startsWith('!')) {
      continue;
    }
    assert.equal(
      pattern.startsWith('browser-capture'),
      false,
      `browser-capture must not be ignored by "${pattern}"`,
    );
  }
});
