'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function sourceSection(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0, `expected ${startMarker}`);
  assert.ok(end > start, `expected ${endMarker} after ${startMarker}`);
  return source.slice(start, end);
}

test('training answers and reflections keep authoritative commands before streamed Coach feedback', () => {
  const source = fs.readFileSync(appPath, 'utf8');
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
  assert.match(answerBranch, /handleSubmitTrainingEvidence\(normalizedDraft\)/);
  assert.match(answerBranch, /sendTrainingFeedback\(\{/);
  assert.match(answerBranch, /phase: trainingComposerReflectMode \? "reflection" : "evidence"/);
});

test('training card and Coach routes preserve separate drafts when the route changes', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const routeHandler = sourceSection(
    source,
    'const handleTrainingComposerRouteChange',
    'const trainingComposerPracticeInputMode',
  );
  assert.match(routeHandler, /trainingRouteDraftsRef\.current\[trainingComposerRoute\] = draft;/);
  assert.match(routeHandler, /const nextDraft = trainingRouteDraftsRef\.current\[nextRoute\] \?\? "";/);
  assert.match(routeHandler, /setTrainingComposerRoute\(nextRoute\);/);
  assert.match(routeHandler, /setComposerDraft\(nextDraft\);/);
  assert.doesNotMatch(source, /id: "training-composer-route"/);
});

test('Plan, Resources, and Training expose the complete latest Agent reply for later review', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const replyHelper = sourceSection(source, 'const renderViewAgentReply =', 'const renderDockedView');

  assert.match(replyHelper, /data-view-agent-reply/);
  assert.match(replyHelper, /localizedConversation/);
  assert.match(replyHelper, /message\.role !== "assistant"/);
  assert.match(replyHelper, /visibleReply\.body/);
  assert.match(replyHelper, /<CoachMessageBubble/);
  for (const view of ['plan', 'resources', 'training']) {
    assert.match(source, new RegExp(`renderViewAgentReply\\("${view}"\\)`));
  }
});
