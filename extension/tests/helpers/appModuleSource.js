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
  // P2 modularization: composer menu panels moved to components/composer/,
  // so the logical module includes the extracted slice.
  const composerDir = path.resolve(__dirname, '..', '..', 'webview', 'src', 'components', 'composer');
  const composerSlices = ['ComposerResourcesMenu.tsx', 'ComposerModelMenu.tsx'];
  const trashPanelPath = path.resolve(
    __dirname, '..', '..', 'webview', 'src', 'components', 'resources', 'ResourcesTrashPanel.tsx',
  );
  return [
    fs.readFileSync(APP_SOURCE_PATH, 'utf8'),
    fs.readFileSync(APP_HELPERS_PATH, 'utf8'),
    ...composerSlices.map((name) => fs.readFileSync(path.join(composerDir, name), 'utf8')),
    fs.readFileSync(trashPanelPath, 'utf8'),
  ].join('\n');
}

module.exports = { readAppModuleSource, APP_SOURCE_PATH, APP_HELPERS_PATH };
