'use strict';

const Module = require('node:module');
const path = require('node:path');

const EXTENSION_DIST_ROOT = path.resolve(__dirname, '..', '..', 'dist', 'extension', 'src');

function clearExtensionModuleCache() {
  for (const cacheKey of Object.keys(require.cache)) {
    if (cacheKey.startsWith(EXTENSION_DIST_ROOT)) {
      delete require.cache[cacheKey];
    }
  }
}

function loadWithVscodeMock(modulePath, vscodeMock) {
  clearExtensionModuleCache();

  const originalLoad = Module._load;
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === 'vscode') {
      return vscodeMock;
    }
    return originalLoad.call(this, request, parent, isMain);
  };

  try {
    return require(modulePath);
  } finally {
    Module._load = originalLoad;
  }
}

module.exports = {
  loadWithVscodeMock,
};
