'use strict';

/**
 * The webview CSP nonce is the only thing that separates injected markup from
 * script execution, so it has to be unpredictable per build of the HTML.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const webviewContentModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'webviewContent.js',
);

function loadWebviewContent() {
  return loadWithVscodeMock(webviewContentModulePath, {});
}

test('the webview nonce is a fresh 32-character CSPRNG value on every build', () => {
  const { createNonce } = loadWebviewContent();

  const seen = new Set();
  for (let index = 0; index < 2000; index += 1) {
    const nonce = createNonce();
    assert.match(nonce, /^[A-Za-z0-9_-]{32}$/);
    seen.add(nonce);
  }

  assert.equal(seen.size, 2000);
});

test('the webview nonce does not come from Math.random', () => {
  // Math.random is made constant: a nonce derived from it would repeat.
  const originalRandom = Math.random;
  Math.random = () => 0.42;
  try {
    const { createNonce } = loadWebviewContent();
    assert.notEqual(createNonce(), createNonce());
  } finally {
    Math.random = originalRandom;
  }
});
