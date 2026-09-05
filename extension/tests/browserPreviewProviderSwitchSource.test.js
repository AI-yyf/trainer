'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const browserSidecarPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserSidecar.ts',
);

test('browser preview provider switching can fall back to injected bootstrap provider state', () => {
  const source = fs.readFileSync(browserSidecarPath, 'utf8');

  assert.match(
    source,
    /import \{[\s\S]*getInjectedBootstrapState,[\s\S]*getPersistedState,[\s\S]*\} from "\.\/vscode";/,
  );
  assert.match(source, /function bootstrapPreviewProviderRecord\(\): Record<string, unknown> \| undefined \{/);
  assert.match(source, /return persistedPreviewProviderRecord\(\) \?\? bootstrapPreviewProviderRecord\(\);/);
  assert.match(source, /const current = buildPreviewProviderView\(activePreviewProviderRecord\(\)\);/);
});

test('browser preview uses fixture readiness only as a non-secret display marker', () => {
  const source = fs.readFileSync(browserSidecarPath, 'utf8');

  assert.match(
    source,
    /apiKeyConfigured:\s*Boolean\(secretStore\.apiKeysByProvider\[providerKey\]\?\.trim\(\)\)\s*\|\|\s*\(isBrowserPreviewFixture\(\) && asBoolean\(record\.apiKeyConfigured\) === true\)/,
  );
});
