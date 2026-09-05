'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const hostRoot = path.resolve(__dirname, '..', 'src');

function read(relativePath, root = webviewRoot) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

test('Coach tool and reasoning surfaces sanitize errors instead of dumping JSON', () => {
  const messageParts = read('components/coach/CoachMessageParts.tsx');
  const coachParts = read('components/coach/parts/index.tsx');
  const toolCall = read('components/coach/parts/ToolCallRenderer.tsx');

  assert.match(messageParts, /sanitizeErrorSurface/);
  assert.match(messageParts, /isAuthoritativeAck\(part\.result\)/);
  assert.doesNotMatch(messageParts, /renderJson\(part\.result\)/);
  assert.doesNotMatch(messageParts, /\{part\.error\}/);
  assert.match(coachParts, /sanitizeErrorSurfaceText\(part\.error/);
  assert.doesNotMatch(coachParts, /jsonText\(part\.result\)/);
  assert.doesNotMatch(coachParts, />OK</);
  assert.match(toolCall, /sanitizeErrorSurfaceJson/);
});

test('Plan candidate diffs are sanitized instead of JSON.stringified', () => {
  const plan = read('components/plan/CoachPlanView.tsx');
  assert.match(plan, /describeSafeStructuredValue\(/);
  assert.match(plan, /sanitizeErrorSurfaceText\(candidate\.reason/);
  assert.doesNotMatch(plan, /JSON\.stringify\(candidate\.diff\)/);
  assert.doesNotMatch(plan, /JSON\.stringify\(candidate\.impact\)/);
});

test('Settings and Training display host errors through the sanitizer', () => {
  const settings = read('components/settings/CoachSettingsView.tsx');
  const app = read('app/App.tsx');
  const training = read('components/training/TrainingWorkbenchView.tsx');
  const state = read('app/useWorkbenchState.ts');

  assert.match(settings, /sanitizeErrorSurfaceText\(status\.feedback\.detail/);
  assert.match(app, /sanitizeErrorSurfaceText\(message\.message, language\)/);
  assert.match(training, /sanitizeErrorSurfaceText\(latestTrainingReliability\.error/);
  assert.match(state, /sanitizeErrorSurfaceText\(/);
  assert.match(state, /message\.type === "operation\/status"/);
  assert.match(
    state.slice(state.indexOf('message.type === "operation/status"')),
    /sanitizeErrorSurfaceText\(/,
  );
  assert.match(app, /sanitizeErrorSurfaceText\(operationMessage\.message/);
  assert.match(app, /waitingComposerEnqueueFailureText\(error, layout\.composerLanguage\)/);
});

test('host-to-webview error strings are sanitized before display', () => {
  const workbenchData = read('core/workbenchData.ts', hostRoot);
  const sessionCommands = read('commands/sessionCommands.ts', hostRoot);
  const trainingCommands = read('commands/trainingCommands.ts', hostRoot);
  const researchCommands = read('commands/researchCommands.ts', hostRoot);

  assert.match(workbenchData, /sanitizeErrorSurfaceText\(recovered\.error/);
  assert.match(sessionCommands, /userFacingErrorText|sanitizeErrorSurfaceText/);
  assert.match(sessionCommands, /sanitizeHostToolResult\(parsed\.result/);
  assert.match(sessionCommands, /sanitizeHostToolResult\(parsed\.arguments/);
  assert.match(trainingCommands, /sanitizeErrorSurfaceText\(error\)/);
  const enqueueStart = trainingCommands.indexOf('function evidenceEnqueueFailureMessage');
  const enqueueEnd = trainingCommands.indexOf('export async function evidenceDeferCommand', enqueueStart);
  const enqueueSource = trainingCommands.slice(enqueueStart, enqueueEnd > enqueueStart ? enqueueEnd : enqueueStart + 3200);
  assert.match(enqueueSource, /waitingComposerEnqueueFailureText\(/);
  assert.doesNotMatch(enqueueSource, /String\(error\)/);
  assert.match(researchCommands, /sanitizeErrorSurfaceText\(/);
  assert.match(researchCommands, /payload: \{ error: safeError \}/);
  assert.doesNotMatch(
    trainingCommands.slice(trainingCommands.indexOf('Card generation error')),
    /streamError: String\(error\)/,
  );
});
