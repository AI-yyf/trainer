'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const mainSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'main.tsx');

test('bootstrap recovery reuses the existing VS Code bridge', () => {
  const source = fs.readFileSync(mainSourcePath, 'utf8');
  const recoveryStart = source.indexOf('function requestBootstrapRecovery(reason: string): void {');
  const recoveryEnd = source.indexOf('window.addEventListener("error"', recoveryStart);
  const recoverySource = source.slice(recoveryStart, recoveryEnd);

  assert.ok(recoveryStart >= 0 && recoveryEnd > recoveryStart, 'bootstrap recovery must exist');
  assert.match(source, /import \{[^}]*\bpostMessage\b[^}]*\} from "\.\/lib\/vscode";/);
  assert.match(recoverySource, /postMessage\(\{ type: "request\/bootstrap" \}\);/);
  assert.doesNotMatch(recoverySource, /acquireVsCodeApi/);
});
