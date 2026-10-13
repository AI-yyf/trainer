'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');

test('Chinese connection recovery uses plain labels and keeps file inputs out of assistive navigation', () => {
  const copySource = fs.readFileSync(path.join(webviewRoot, 'lib', 'i18n', 'copy.ts'), 'utf8');
  // The settings label/phrase tables moved verbatim into the i18n segment
  // file; their Chinese phrase assertions slice there.
  const settingsInlineCopy = fs.readFileSync(
    path.join(webviewRoot, 'lib', 'i18n', 'segments', 'settingsInlineText.ts'),
    'utf8',
  );
  const appSource = fs.readFileSync(path.join(webviewRoot, 'app', 'App.tsx'), 'utf8');

  assert.match(copySource, /provider: "连接服务"/);
  assert.match(copySource, /protocol: "连接方式"/);
  assert.match(copySource, /baseUrl: "服务地址"/);
  assert.match(copySource, /apiKey: "访问密钥"/);
  assert.match(settingsInlineCopy, /protocol: "连接方式"/);
  assert.match(settingsInlineCopy, /connectionVerified: "连接、模型和访问密钥都已通过检查。"/);
  assert.match(appSource, /ref=\{uploadFilesInputRef\}[\s\S]{0,180}hidden/);
  assert.match(appSource, /ref=\{uploadFolderInputRef\}[\s\S]{0,180}hidden/);
});
