'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('training flash answers use the persisted learnerAnswer contract before feedback streaming', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const answerHandlerStart = source.indexOf('if (trainingComposerUsesAnswerMode)');
  const answerHandlerEnd = source.indexOf('} else {', answerHandlerStart);
  const answerHandler = source.slice(answerHandlerStart, answerHandlerEnd);

  assert.notEqual(answerHandlerStart, -1);
  assert.notEqual(answerHandlerEnd, -1);
  assert.match(answerHandler, /await requestTrainingPersistence\(/);
  assert.match(answerHandler, /trainerCommands\.trainingFlashcardAnswer/);
  assert.match(answerHandler, /trainerCommands\.trainingTheoryDrillAnswer/);
  assert.match(answerHandler, /activeTheoryDrill\?\.id/);
  assert.match(answerHandler, /theoryDrillId: activeTheoryDrill\.id,/);
  assert.match(answerHandler, /learnerAnswer: normalizedAnswer,/);
  assert.match(answerHandler, /await requestTrainingPersistence\([\s\S]*?sendTrainingFeedback\(/);
  assert.match(answerHandler, /sendTrainingFeedback\([\s\S]*?setComposerDraft\(""\);/);
  assert.doesNotMatch(answerHandler, /answer: normalizedAnswer,/);
});
