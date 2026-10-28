'use strict';

/**
 * copy.ts now imports one table per locale. Source guards that look for key
 * literals must read the logical module (base file + locale tables), not the
 * thin assembly file.
 */

const fs = require('node:fs');
const path = require('node:path');

const I18N_DIR = path.resolve(__dirname, '..', '..', 'webview', 'src', 'lib', 'i18n');
const COPY_PATH = path.join(I18N_DIR, 'copy.ts');
const LOCALES_DIR = path.join(I18N_DIR, 'locales');

function readCopyModuleSource() {
  const locales = fs
    .readdirSync(LOCALES_DIR)
    .filter((name) => name.endsWith('.ts'))
    .sort()
    .map((name) => fs.readFileSync(path.join(LOCALES_DIR, name), 'utf8'));
  return `${fs.readFileSync(COPY_PATH, 'utf8')}\n${locales.join('\n')}`;
}

module.exports = { readCopyModuleSource, COPY_PATH, LOCALES_DIR };
