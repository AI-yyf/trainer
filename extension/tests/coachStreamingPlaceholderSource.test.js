'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

// The in-flight body lives in the conversation view's own store subscription.
// App only forwards live chunks; it must not invent a canned sentence before
// the first chunk arrives (Copilot keeps a single quiet working line instead).
const conversationViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachConversationView.tsx',
);
const workingIndicatorPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachWorkingIndicator.tsx',
);

test('coach streaming shows one working label, never a canned placeholder sentence', () => {
  const source = readAppModuleSource();
  const conversationView = fs.readFileSync(conversationViewPath, 'utf8');
  const workingIndicator = fs.readFileSync(workingIndicatorPath, 'utf8');

  assert.doesNotMatch(source, /streamingPlaceholderBody/);
  assert.doesNotMatch(source, /正在梳理你的问题，然后给出第一段可见回复。/);
  assert.doesNotMatch(source, /正在整理当前步骤，然后给出第一段可见回复。/);
  assert.doesNotMatch(source, /streamingPlaceholder=\{/);
  assert.match(
    source,
    /: useWorkbenchState\.getState\(\)\.streaming\.streamedContent \|\| "", textLimit\)/,
  );
  // The live bubble falls back to live chunks only, never to fake copy.
  assert.match(
    conversationView,
    /storeStreamMessageId\?\.startsWith\("training_"\)\s*\?\s*""\s*:\s*storeStreamedContent \|\| ""/,
  );
  assert.doesNotMatch(conversationView, /body: .*"\.\.\."/);
  assert.match(
    conversationView,
    /<CoachWorkingIndicator language=\{language\} messageId=\{storeStreamMessageId \?\? undefined\} stage=\{activeTrainerStage\} \/>/,
  );
  assert.match(workingIndicator, /coach-working__label/);
  assert.match(workingIndicator, /coach-working__elapsed/);
});

test('every direct composer turn keeps streaming, even when intent analysis finds a task-shaped request', () => {
  const source = readAppModuleSource();

  assert.match(source, /stream: true,/);
  assert.doesNotMatch(source, /stream: intent === "coach",/);
});
