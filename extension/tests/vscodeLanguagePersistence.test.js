'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const ts = require('typescript');

const vscodeSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'vscode.ts');
const webviewTypesPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'types.ts');
const sharedTypesPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'types.ts');
const supportedLanguages = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

function compileTypeScript(sourcePath) {
  return ts.transpileModule(fs.readFileSync(sourcePath, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: sourcePath,
  }).outputText;
}

function loadVscodeModule(windowShim) {
  const previousWindow = global.window;
  const previousTsLoader = Module._extensions['.ts'];
  delete require.cache[webviewTypesPath];
  delete require.cache[sharedTypesPath];
  global.window = windowShim;
  Module._extensions['.ts'] = (target, filename) => {
    target._compile(compileTypeScript(filename), filename);
  };

  function restoreEnvironment() {
    if (previousWindow === undefined) {
      delete global.window;
    } else {
      global.window = previousWindow;
    }
    if (previousTsLoader === undefined) {
      delete Module._extensions['.ts'];
    } else {
      Module._extensions['.ts'] = previousTsLoader;
    }
    delete require.cache[webviewTypesPath];
    delete require.cache[sharedTypesPath];
  }

  try {
    const target = new Module(vscodeSourcePath, module);
    target.filename = vscodeSourcePath;
    target.paths = Module._nodeModulePaths(path.dirname(vscodeSourcePath));
    target._compile(compileTypeScript(vscodeSourcePath), vscodeSourcePath);
    return {
      module: target.exports,
      restore() {
        restoreEnvironment();
      },
    };
  } catch (error) {
    restoreEnvironment();
    throw error;
  }
}

function createLayout(composerLanguage) {
  return {
    themePreference: 'system',
    activeView: 'coach',
    composerLanguage,
    composerAnswerMode: 'auto',
    teachingStyle: 'guided',
    resourceSearchMode: 'lexical',
    includeCurrentFile: true,
    includeSelection: true,
    includeDiagnostics: true,
    includeRelatedFiles: true,
    contextDetail: 'balanced',
    followCurrentFile: true,
    coachDefaults: {
      memoryScope: 'project',
      workingSetMode: 'balanced',
      reviewCadence: 'steady',
      reviewReminderMode: 'due',
      workspaceMemoryToggles: {
        decisions: true,
        patterns: true,
        resources: true,
      },
    },
    composerDraft: '',
  };
}

test('VS Code bootstrap restores every supported composer language without collapsing it to English', () => {
  for (const composerLanguage of supportedLanguages) {
    let savedState;
    const loaded = loadVscodeModule({
      acquireVsCodeApi: () => ({
        getState: () => createLayout(composerLanguage),
        setState: (state) => {
          savedState = state;
        },
        postMessage() {},
      }),
    });

    try {
      assert.equal(loaded.module.getPersistedState().composerLanguage, composerLanguage);
      loaded.module.setPersistedState(createLayout(composerLanguage));
      assert.equal(savedState.composerLanguage, composerLanguage);
    } finally {
      loaded.restore();
    }
  }
});

test('browser saved layout state round-trips every supported composer language', () => {
  for (const composerLanguage of supportedLanguages) {
    const storage = new Map();
    const loaded = loadVscodeModule({
      localStorage: {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, value),
      },
    });

    try {
      loaded.module.setPersistedState(createLayout(composerLanguage));
      assert.equal(JSON.parse(storage.get('trainer:webview')).composerLanguage, composerLanguage);
      assert.equal(loaded.module.getPersistedState().composerLanguage, composerLanguage);
    } finally {
      loaded.restore();
    }
  }
});

test('late browser preview API is captured after the module graph has loaded', () => {
  let posted;
  let api;
  const loaded = loadVscodeModule({
    localStorage: {
      getItem: () => null,
      setItem: () => {},
    },
  });

  try {
    api = {
      getState: () => createLayout('en-US'),
      setState: () => {},
      postMessage: (message) => {
        posted = message;
      },
    };
    global.window.acquireVsCodeApi = () => api;
    loaded.module.postMessage({ type: 'command/execute', payload: { commandId: 'trainer.evidence.adopt' } });
    assert.deepEqual(posted, {
      type: 'command/execute',
      payload: { commandId: 'trainer.evidence.adopt' },
    });
  } finally {
    loaded.restore();
  }
});
