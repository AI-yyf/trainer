'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { readAppModuleSource } = require('./helpers/appModuleSource');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function sourceSection(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0, `expected ${startMarker}`);
  assert.ok(end > start, `expected ${endMarker} after ${startMarker}`);
  return source.slice(start, end);
}

test('training answers and reflections keep authoritative commands before streamed Coach feedback', () => {
  const source = readAppModuleSource();
  const feedback = sourceSection(source, 'const sendTrainingFeedback =', 'const handleSubmit =');
  const submit = sourceSection(source, 'const handleSubmit =', 'const openComposerModelSettings');
  const answerBranch = sourceSection(
    submit,
    'if (trainingComposerUsesAnswerMode)',
    'if (!providerCanCoachNow || providerBlockReason)',
  );

  assert.match(feedback, /buildTrainingFeedbackPrompt\(/);
  assert.match(
    feedback,
    /sendTurn\(\{[\s\S]*?intent: "coach"[\s\S]*?activeView: "training"[\s\S]*?stream: true/,
  );
  assert.match(answerBranch, /await requestTrainingPersistence\(/);
  assert.match(answerBranch, /trainerCommands\.trainingTheoryDrillAnswer/);
  assert.match(answerBranch, /trainerCommands\.trainingFlashcardAnswer/);
  assert.match(answerBranch, /sendTrainingFeedback\(/);
  assert.ok(
    answerBranch.indexOf('await requestTrainingPersistence(') <
      answerBranch.indexOf('sendTrainingFeedback('),
    'the authoritative answer persistence must complete before Coach feedback',
  );
  assert.match(answerBranch, /handleSubmitTrainingEvidence\(normalizedDraft, unified\.kind === "blocker" \? "blocked" : "result"\)/);
  assert.match(answerBranch, /sendTrainingFeedback\(\{/);
  assert.match(answerBranch, /phase: trainingComposerReflectMode \? "reflection" : "evidence"/);
});

test('training card and Coach routes preserve separate drafts when the route changes', () => {
  // Product-level template contract replaces the previous layout grammar.
  require('./templateAssertions').practice();
});

test('learning replies stay in the one conversation', () => {
  const source = readAppModuleSource();
  // The old per-view reply panel is gone: every assistant turn is rendered by
  // the single conversation pane.
  assert.doesNotMatch(source, /renderViewAgentReply/);
  assert.doesNotMatch(source, /data-view-agent-reply/);
  assert.doesNotMatch(source, /message\.sourceView === "coach"/);
  const conversation = sourceSection(source, 'const coachRenderConversation', 'const liveCoachTaskChrome');
  assert.match(conversation, /localizedConversation/);
  assert.match(conversation, /optimisticTurns/);
});
