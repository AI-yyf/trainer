'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const previewPath = path.join(webviewRoot, 'lib', 'browserPreviewHarness.ts');
const appPath = path.join(webviewRoot, 'app', 'App.tsx');
const copyPath = path.join(webviewRoot, 'lib', 'i18n', 'copy.ts');

test('recovery previews keep provider facts and locale-owned copy aligned', () => {
  const preview = fs.readFileSync(previewPath, 'utf8');
  const app = fs.readFileSync(appPath, 'utf8');
  const copy = fs.readFileSync(copyPath, 'utf8');
  const recoveryCopyStart = preview.indexOf('const recoveryPreviewCopy');
  const recoveryCopyEnd = preview.indexOf('\n};', recoveryCopyStart);

  assert.ok(recoveryCopyStart >= 0 && recoveryCopyEnd > recoveryCopyStart);
  const recoveryCopy = preview.slice(recoveryCopyStart, recoveryCopyEnd);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(recoveryCopy, new RegExp(`"${language}":\\s*\\{[\\s\\S]*?artifactTitle:`));
  }

  assert.match(preview, /const recovery = recoveryPreviewCopy\[language\];/);
  assert.match(preview, /apiKeyConfigured: false,/);
  assert.match(preview, /blockedReason: recovery\.blocker,/);
  assert.match(preview, /isStreaming: false,/);
  assert.match(preview, /if \(state\.activeView === "plan" && state\.scenario !== "recovery"\)/);

  assert.match(app, /const providerRecoveryReason =\s*providerBlockReason \?\?/);
  assert.match(app, /providerRecoverySummary\([\s\S]*?data\.connection\.state,[\s\S]*?\)\.detail/);
  assert.match(app, /\$\{t\.openSettings\}: \$\{blockedComposerPresenceDetail\}/);
  assert.match(app, /aria-label=\{[\s\S]*?`\$\{t\.openSettings\}: \$\{blockedComposerPresenceDetail\}`[\s\S]*?\}/);
  assert.match(app, /: t\.openSettings,/);
  assert.match(copy, /type ContextRailCopy = Pick<[\s\S]*?"composerPlaceholderPlan"/);
});
