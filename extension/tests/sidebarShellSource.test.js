'use strict';

const test = require('node:test');

// PR-7: styles.css is an @import aggregator; rules live in styles/sections/*.
function readStylesSource() {
  const fsMod = require('node:fs');
  const pathMod = require('node:path');
  const root = pathMod.resolve(__dirname, '..', 'webview', 'src');
  const manifest = JSON.parse(fsMod.readFileSync(
    pathMod.join(root, 'styles', 'sections', 'manifest.json'), 'utf8'));
  return manifest.map(
    (entry) => fsMod.readFileSync(pathMod.join(root, entry.file), 'utf8'),
  ).join('');
}

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const viewTypesPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'types.ts');
const mainSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'main.tsx');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const packageJsonPath = path.resolve(__dirname, '..', 'package.json');
const activityBarMarkPath = path.resolve(__dirname, '..', 'media', 'trainer-icon.svg');
const webviewMarkPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'assets',
  'branding',
  'trainer-mark.svg',
);
const marketplaceIconPath = path.resolve(__dirname, '..', 'media', 'trainer-icon.png');
const trainingCommandsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'useTrainingCommands.ts',
);
const trainingViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);

test('app shell renders a text-only top navigation for the daily views', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});

test('header composes two intentional layers: utility row above primary nav', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});

test('top navigation swaps squeezed text for per-view icons', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});

test('header layers are laid out on purpose, not by flex-wrap accident', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').navigation();
});

test('extension manifest exposes Trainer as the VS Code-native universal coach', () => {
  const manifest = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));

  assert.equal(manifest.displayName, 'Trainer');
  assert.equal(manifest.description, 'A conversation-first universal learning coach for VS Code.');
  assert.equal(manifest.icon, 'media/trainer-icon.png');
  assert.equal(manifest.contributes.viewsContainers.activitybar[0].title, 'Trainer');
  assert.equal(manifest.contributes.viewsContainers.activitybar[0].icon, 'media/trainer-icon.svg');
  assert.equal(manifest.contributes.views.trainer[0].name, 'Trainer');
  assert.equal(manifest.contributes.configuration.title, 'Trainer');
  assert.ok(
    manifest.contributes.commands.some(
      (command) => command.command === 'trainer.session.resumeLatestCoachCheckpoint',
    ),
  );
  assert.ok(
    manifest.contributes.commands.some(
      (command) => command.command === 'trainer.session.replayLatestCoachCheckpoint',
    ),
  );
});

test('Trainer uses one small-size-safe monochrome mark across extension surfaces', () => {
  const activityBarMark = fs.readFileSync(activityBarMarkPath, 'utf8');
  const webviewMark = fs.readFileSync(webviewMarkPath, 'utf8');

  assert.equal(activityBarMark, webviewMark);
  assert.match(activityBarMark, /width="24" height="24" viewBox="0 0 24 24"/);
  assert.match(activityBarMark, /fill="currentColor"/);
  assert.doesNotMatch(activityBarMark, /<image\b|data:image/);
  assert.equal(fs.existsSync(marketplaceIconPath), true);
});

test('startup shell stays logo-free and uses text-only status copy', () => {
  const source = fs.readFileSync(mainSourcePath, 'utf8');

  assert.doesNotMatch(source, /trainerMarkUrl/);
  assert.doesNotMatch(source, /<img\s+src=/);
  assert.match(source, /className="trainer-startup-shell"/);
  assert.match(source, /className="trainer-startup-error"/);
});

test('startup shell follows the saved coach language before the app bundle is ready', () => {
  const source = fs.readFileSync(mainSourcePath, 'utf8');

  assert.match(source, /const STARTUP_COPY: Record<ComposerLanguage, StartupCopy>/);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(source, new RegExp(`"${language}"`));
  }
  assert.match(source, /injected\?\.memory\?\.workspace\?\.responseLanguage/);
  assert.match(source, /renderStartupShell\(\s*copy,/);
  assert.doesNotMatch(source, /Loading the coach shell/);
});

test('training command hook accepts the full workbench view union', () => {
  const source = fs.readFileSync(trainingCommandsPath, 'utf8');

  assert.match(source, /import type \{ ActiveWorkbenchView \} from "\.\.\/lib\/types";/);
  assert.match(source, /setActiveView: \(view: ActiveWorkbenchView\) => void,/);
});

test('training keeps a card-only surface free of embedded verification controls', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
});
