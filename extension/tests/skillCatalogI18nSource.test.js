'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const skillCatalogPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'skillCatalog.ts');
const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const coachComposerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'composer',
  'CoachComposer.tsx',
);

test('skill catalog keeps localized text and a readable fallback for every product language', () => {
  const source = fs.readFileSync(skillCatalogPath, 'utf8');

  assert.match(source, /export type TrainerSkillText = Partial<Record<ComposerLanguage, string>>;/);
  assert.match(
    source,
    /value\[language\] \?\?\s*value\["en-US"\] \?\?\s*value\["zh-CN"\] \?\?\s*Object\.values\(value\)\.find\(/s,
  );
  assert.match(source, /export function trainerSkillSectionLabel\([\s\S]*?language: ComposerLanguage,/);
  assert.match(source, /case "Coach":\s*return "\u6559\u7ec3";/);
  assert.match(source, /case "Plan":\s*return "\u8ba1\u5212";/);
  assert.match(source, /case "Training":\s*return "\u8bad\u7ec3";/);
  assert.match(source, /case "Resources":\s*return "\u8d44\u6599";/);
  assert.match(source, /case "Workspace":\s*return "\u5de5\u4f5c\u533a";/);
  assert.match(source, /case "Provider":\s*return "\u6a21\u578b";/);
  assert.match(source, /"zh-CN": "\u89e3\u91ca\u539f\u7406"/);
  assert.match(source, /"en-US": "Explain principle"/);
});

test('app recovery and common copy receive the active language with a defined fallback', () => {
  const source = readAppModuleSource();

  assert.match(
    source,
    /import \{ resolveCopy as resolveWorkbenchCopy, type Copy \} from "\.\.\/lib\/i18n\/copy";/,
  );
  assert.match(source, /const t = resolveWorkbenchCopy\(layout\.composerLanguage\);/);
  assert.doesNotMatch(source, /const englishCopy =/);
  assert.doesNotMatch(source, /"(?:es-ES|fr-FR|de-DE|ja-JP|ko-KR|pt-BR)": englishCopy/);
  // moved into providerRecoveryCopy.ts (batch 7)
  assert.match(
    fs.readFileSync(path.resolve(__dirname, "..", "webview", "src", "app", "providerRecoveryCopy.ts"), "utf8"),
    /function providerSetupSummary\([\s\S]*?language: ComposerLanguage,/,
  );
  // moved into providerRecoveryCopy.ts (batch 7)
  assert.match(
    fs.readFileSync(path.resolve(__dirname, "..", "webview", "src", "app", "providerRecoveryCopy.ts"), "utf8"),
    /function blockedComposerPresenceMessage\([\s\S]*?language: ComposerLanguage,/,
  );
  // moved into useOperationStatusController.ts (round 2): the controller reads the
  // live composer language and sanitizes every operation failure with it.
  const operationStatusControllerSource = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'app', 'useOperationStatusController.ts'),
    'utf8',
  );
  assert.match(
    operationStatusControllerSource,
    /const composerLanguage = useWorkbenchState\(\(state\) => state\.layout\.composerLanguage\);/,
  );
  assert.match(
    operationStatusControllerSource,
    /sanitizeOperationFailureMessage\(message, composerLanguage\)/,
  );
  assert.match(source, /providerSetupSummary\(data\.providerConfig, layout\.composerLanguage, data\.connection\.state\)/);
  assert.match(source, /blockedComposerPresenceMessage\([\s\S]*?layout\.composerLanguage,[\s\S]*?data\.connection\.state,/s);
  assert.match(source, /<CoachComposer[\s\S]*?language=\{layout\.composerLanguage\}/s);
  assert.doesNotMatch(source, /type CopyKey =/);
});

test('coach composer accepts the full product language set and keeps drag attachment fallbacks readable', () => {
  const source = fs.readFileSync(coachComposerPath, 'utf8');

  assert.match(source, /import type \{ ComposerLanguage, MessageAttachment \} from "\.\.\/\.\.\/lib\/types";/);
  assert.match(source, /density\?: "default" \| "compact";/);
  assert.match(source, /density = "default",/);
  assert.match(source, /const compactMode = density === "compact";/);
  assert.match(source, /compactMode \? "composer--compact" : ""/);
  assert.match(source, /language\?: ComposerLanguage;/);
  assert.ok(source.includes('const dropPromptText = attachmentsInteractive'));
  assert.match(source, /attachmentsUnavailableReason\?\.trim\(\) \|\|/);
  assert.match(source, /aria-label=\{localizedCopy\.removeAttachment\}/);
  // composerLocaleCopy migrated to the i18n home (2026-10-14): its entry
  // values are asserted against the segment file, the call sites stay here.
  const composerTableSource = fs.readFileSync(
    path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'i18n', 'segments', 'coachInlineText.ts'),
    'utf8',
  );
  assert.ok(composerTableSource.includes('Drop to attach image'));
  assert.ok(composerTableSource.includes('Image input is unavailable for this connection'));
  assert.match(composerTableSource, /removeAttachment: "移除附件"/);
  assert.match(composerTableSource, /removeAttachment: "Remove attachment"/);
  assert.match(composerTableSource, /clear: "清空"/);
  assert.match(composerTableSource, /clear: "Clear"/);
  assert.match(source, /title=\{localizedCopy\.clear\}/);
  assert.doesNotMatch(source, /type="file"/);
  assert.doesNotMatch(source, /composer__attach-btn/);
});
