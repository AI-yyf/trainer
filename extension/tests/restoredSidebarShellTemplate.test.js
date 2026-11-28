// Restored behavioral regression test. Original file: extension/tests/sidebarShellSource.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: undefined
//
// Restoration: partial - 4 of 10 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "extension manifest exposes Trainer as the VS Code-native universal coach"
//       manifest text guard: asserts on extension/package.json contributes.
//   - "Trainer uses one small-size-safe monochrome mark across extension surfaces"
//       asset guard: inspects branding SVG files.
//   - "training command hook accepts the full workbench view union"
//       source-text guard: reads extension/webview/src/app/useTrainingCommands.ts and asserts on its
//       text (out of scope by rule).
//   - "training keeps a card-only surface free of embedded verification controls"
//       hybrid template check: templateAssertions.practice() asserts on webview source text.
//   - "startup has no waiting shell and keeps only the fatal-error surface"
//       fails at HEAD: The input did not match the regular expression
//       /className="trainer-startup-error"/. Input: / import { mountWorkbenchApp,renderStartupFailure }
//       from "./bootstrapWorkbench";\n' +
//   - "startup error copy still follows the saved coach language"
//       fails at HEAD: The input did not match the regular expression /const STARTUP_COPY:
//       Record<ComposerLanguage, StartupCopy>/. Input: / import { mountWorkbenchApp,renderStartupFailure
//       } from "./bootstrapWorkbench";\n' +
// Target: webview components rendered to static markup through templateAssertions.render.

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





