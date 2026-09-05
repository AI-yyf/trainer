'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const contextSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'context.tsx');

test('the webview tree is wrapped in the i18n provider and the provider fails loud when missing', () => {
  const appSource = fs.readFileSync(appSourcePath, 'utf8');
  const contextSource = fs.readFileSync(contextSourcePath, 'utf8');

  assert.match(appSource, /import \{ I18nProvider \} from "\.\.\/lib\/i18n\/context";/);
  assert.match(
    appSource,
    /<I18nProvider language=\{layout\.composerLanguage\} direction=\{uiDirection\}>/,
  );
  assert.match(contextSource, /createContext<I18nContextValue \| undefined>\(undefined\)/);
  assert.match(contextSource, /direction: TextDirection/);
  assert.match(contextSource, /if \(!ctx\) \{/);
});
