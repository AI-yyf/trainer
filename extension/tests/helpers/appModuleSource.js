'use strict';

/**
 * The workbench entry point is split into App.tsx (component orchestration)
 * and appHelpers.tsx (module-scope helpers). Source guards assert on the
 * logical module, so they must read both files rather than depending on which
 * side of the split a declaration currently lives on.
 */

const fs = require('node:fs');
const path = require('node:path');

const APP_SOURCE_PATH = path.resolve(
  __dirname,
  '..',
  '..',
  'webview',
  'src',
  'app',
  'App.tsx',
);
const APP_HELPERS_PATH = path.resolve(
  __dirname,
  '..',
  '..',
  'webview',
  'src',
  'app',
  'appHelpers.tsx',
);

function readAppModuleSource() {
  return `${fs.readFileSync(APP_SOURCE_PATH, 'utf8')}\n${fs.readFileSync(APP_HELPERS_PATH, 'utf8')}`;
}

module.exports = { readAppModuleSource, APP_SOURCE_PATH, APP_HELPERS_PATH };
