
// PR-7: styles.css is an @import aggregator; the real rules live in
// styles/sections/*.css. Read them concatenated in manifest order so
// assertions see the same bytes the browser gets after bundling.
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

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const coachMessageBubblePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachMessageBubble.tsx',
);
const coachConversationViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'coach',
  'CoachConversationView.tsx',
);
const browserPreviewHarnessPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'browserPreviewHarness.ts',
);

test('coach reply quick actions render only under assistant messages', () => {
  const source = fs.readFileSync(coachMessageBubblePath, 'utf8');

  assert.match(source, /export type CoachMessageAction = "share" \| "save-resource" \| "training-card"/);
  assert.match(source, /onMessageAction\?: \(action: CoachMessageAction, message: ConversationMessage\)/);
  assert.match(source, /pendingMessageAction\?: string \| null/);
  assert.match(
    source,
    /const showAssistantActions =\s*message\.role === "assistant" &&\s*!streaming &&\s*Boolean\(onMessageAction\)/,
  );
  const actionsStart = source.indexOf('message-bubble__actions');
  assert.ok(actionsStart > -1, 'expected the actions row markup');
  const actionsBlock = source.slice(actionsStart);
  assert.match(actionsBlock, /onMessageAction\?\.\("share", message\)/);
  assert.match(actionsBlock, /onMessageAction\?\.\("save-resource", message\)/);
  assert.match(actionsBlock, /onMessageAction\?\.\("training-card", message\)/);
  assert.match(actionsBlock, /disabled=\{pendingAssistantAction === "share"\}/);
  assert.match(actionsBlock, /disabled=\{pendingAssistantAction === "save-resource"\}/);
  assert.match(actionsBlock, /disabled=\{pendingAssistantAction === "training-card"\}/);
  assert.match(actionsBlock, /role="group"/);
});

test('coach reply action styles stay on theme tokens', () => {
  const styles = readStylesSource();
  const actionsRow = styles.match(/\.message-bubble__actions\s*\{[\s\S]*?\n\}/);
  const action = styles.match(/\.message-bubble__action\s*\{[\s\S]*?\n\}/);
  const actionHover = styles.match(/\.message-bubble__action:hover:not\(:disabled\)\s*\{[\s\S]*?\n\}/);
  const actionFocus = styles.match(/\.message-bubble__action:focus-visible\s*\{[\s\S]*?\n\}/);

  assert.ok(actionsRow, 'expected .message-bubble__actions styles');
  assert.ok(action, 'expected .message-bubble__action styles');
  assert.ok(actionHover, 'expected hover styles');
  assert.ok(actionFocus, 'expected focus-visible styles');
  for (const block of [actionsRow[0], action[0], actionHover[0], actionFocus[0]]) {
    assert.doesNotMatch(block, /#[0-9a-fA-F]{3,8}\b/, 'hardcoded color leaked into message actions');
    assert.doesNotMatch(block, /rgba?\(/, 'rgb() color leaked into message actions');
  }
  assert.match(action[0], /var\(--fg-muted\)/);
  assert.match(actionFocus[0], /var\(--focus-ring\)/);
});

test('conversation view threads message actions into each bubble', () => {
  const source = fs.readFileSync(coachConversationViewPath, 'utf8');

  assert.match(source, /onMessageAction\?: \(action: CoachMessageAction, message: ConversationMessage\)/);
  assert.match(source, /pendingMessageAction\?: string \| null/);
  assert.match(source, /onMessageAction=\{onMessageAction\}/);
  assert.match(source, /pendingMessageAction=\{pendingMessageAction\}/);
});

test('save-to-resources posts a markdown inline upload bound to the selected reply', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /const requestCoachReplyUpload = useCallback\(/);
  const uploadStart = source.indexOf('const requestCoachReplyUpload');
  const uploadEnd = source.indexOf('const handleCoachMessageAction', uploadStart);
  assert.ok(uploadStart > -1 && uploadEnd > uploadStart, 'expected the upload request helper');
  const upload = source.slice(uploadStart, uploadEnd);

  assert.match(upload, /commandId: trainerCommands\.uploadResource/);
  assert.match(upload, /uploads:\s*\[/);
  assert.match(upload, /kind: "markdown"/);
  assert.match(upload, /source: "coach-reply"/);
  assert.match(upload, /content: replyDoc\.markdown/);
  assert.match(upload, /name: replyDoc\.title/);
  assert.match(upload, /tags: \["coach-reply"\]/);
  assert.match(upload, /__trainerResourceOperationId: requestId/);
  assert.match(upload, /kind: "upload"/);

  assert.match(source, /function coachReplyMarkdown\(/);
  assert.match(source, /function coachReplyTitle\(/);
});

test('training-card action sends the reply through the real card generator', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const handlerStart = source.indexOf('const handleCoachMessageAction');
  assert.ok(handlerStart > -1, 'expected handleCoachMessageAction');
  const handler = source.slice(handlerStart, handlerStart + 8000);

  assert.match(handler, /commandId: trainerCommands\.trainingGenerateCard/);
  assert.match(handler, /source: "conversation_gap"/);
  assert.match(handler, /cardType: "practice"/);
  assert.match(handler, /prompt: excerpt/);
  assert.match(handler, /contextHint: excerpt/);
  assert.match(handler, /focusArea: replyDoc\.title/);
  assert.match(handler, /COACH_REPLY_BODY_MAX_CHARS/);
});

test('share action copies the selected reply to the clipboard', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const handlerStart = source.indexOf('const handleCoachMessageAction');
  assert.ok(handlerStart > -1, 'expected handleCoachMessageAction');
  const handler = source.slice(handlerStart, handlerStart + 2500);

  assert.match(handler, /action === "share"/);
  assert.match(handler, /navigator\.clipboard\.writeText\(replyDoc\.markdown\)/);
  assert.match(handler, /Coach reply copied to clipboard/);
});

test('message action pending state clears on stream or operation acknowledgements', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const dispatchStart = source.indexOf('const applyHostMessage = useCallback(');
  assert.ok(dispatchStart > -1, 'expected applyHostMessage');
  const dispatch = source.slice(dispatchStart, dispatchStart + 1400);

  assert.match(dispatch, /message\.type === "operation\/status" \|\| message\.type === "stream\/start"/);
  assert.match(dispatch, /setPendingMessageAction\(null\)/);
  assert.match(source, /setPendingMessageAction\(`\$\{message\.id\}:\$\{action\}`\)/);
  assert.match(source, /pendingMessageActionTimeoutRef/);
});

test('quick actions are wired into the coach conversation pane and docked reply', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  const paneStart = source.indexOf('const renderCoachConversationPane');
  assert.ok(paneStart > -1, 'expected renderCoachConversationPane');
  const pane = source.slice(paneStart, paneStart + 2500);
  assert.match(pane, /onMessageAction=\{handleCoachMessageAction\}/);
  assert.match(pane, /pendingMessageAction=\{pendingMessageAction\}/);

  const dockedStart = source.indexOf('const renderContextualResultRail');
  assert.ok(dockedStart > -1, 'expected renderContextualResultRail');
  const docked = source.slice(dockedStart, dockedStart + 9000);
  assert.match(docked, /onMessageAction=\{handleCoachMessageAction\}/);
});

test('browser preview mirrors the inline upload and card generation paths', () => {
  const harness = fs.readFileSync(browserPreviewHarnessPath, 'utf8');

  assert.match(harness, /const isResourceUpload = commandId === trainerCommands\.uploadResource/);
  assert.match(harness, /\/resource\/upload/);
  assert.match(harness, /\/resource\/index/);
  assert.match(harness, /content_encoding: browserPreviewString\(upload\.contentEncoding\)/);
  assert.match(harness, /isResourceUpload\s*\?\s*"upload"/);
  assert.match(harness, /trainerCommands\.trainingGenerateCard/);

  const appSource = fs.readFileSync(appPath, 'utf8');
  const handlerStart = appSource.indexOf('const handleCoachMessageAction');
  const handler = appSource.slice(handlerStart, handlerStart + 3000);
  assert.match(handler, /browserPreview\.uploadBrowserPreviewResources/);
});

test('share resources and training actions moved off the header into each reply', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const headerStart = source.indexOf('className="header-actions"');
  assert.ok(headerStart > -1, 'expected the header actions container');
  const headerBlock = source.slice(headerStart, headerStart + 1200);

  assert.doesNotMatch(headerBlock, /handleShareSession/);
  assert.doesNotMatch(headerBlock, /setActiveView\("resources"\)/);
  assert.doesNotMatch(headerBlock, /setActiveView\("training"\)/);
  assert.doesNotMatch(source, /headerActionLabels/);
});
