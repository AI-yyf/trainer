
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const viewPath = path.join(webviewRoot, 'components', 'training', 'TrainingWorkbenchView.tsx');
const panelPath = path.join(webviewRoot, 'components', 'training', 'RemoteVerificationPanel.tsx');
const copyPath = path.join(webviewRoot, 'components', 'training', 'remoteVerificationCopy.ts');

test('the streaming remote verification panel ships with eight-language copy (§八/§十五)', () => {
  const view = fs.readFileSync(viewPath, 'utf8');
  const panel = fs.readFileSync(panelPath, 'utf8');
  const copy = fs.readFileSync(copyPath, 'utf8');

  // §十六 regression guard: this block was silently lost once — pin it.
  assert.match(view, /<RemoteVerificationPanel/);
  assert.match(view, /onStop=\{onStopRemoteVerification\}/);
  assert.match(view, /remoteVerifyCopy\(language\)\.verifyOn/);
  assert.match(panel, /remote-verify-panel__output/);
  assert.match(panel, /<SystemState kind="processing"/);
  assert.match(panel, /<VerificationResult/);
  // Completed runs show the honest verdict; anything else shows outcome-unknown.
  assert.match(panel, /copy\.passed/);
  assert.match(panel, /copy\.interrupted/);
  // §十五: the copy records cover all eight languages and never branch on zh.
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(copy, new RegExp(`"${language}": \{`));
    assert.match(panel, new RegExp(`"${language}": \{`));
  }
  assert.doesNotMatch(copy, /=== "zh-CN"/);
  assert.doesNotMatch(panel, /=== "zh-CN"/);
});
