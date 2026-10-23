'use strict';

// T-0038: browser-capture UX contract — focus management, jargon-free copy,
// liveActiveView authority, and token-only colors in the popup.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const popupJs = fs.readFileSync(path.join(root, 'browser-extension', 'popup', 'popup.js'), 'utf8');
const sharedJs = fs.readFileSync(path.join(root, 'browser-extension', 'shared.js'), 'utf8');
const hostCopy = fs.readFileSync(path.join(root, 'extension', 'src', 'browserCapture', 'hostCopy.ts'), 'utf8');
const workbenchState = fs.readFileSync(
  path.join(root, 'extension', 'webview', 'src', 'app', 'useWorkbenchState.ts'),
  'utf8',
);
const popupCss = fs.readFileSync(path.join(root, 'browser-extension', 'popup', 'popup.css'), 'utf8');

test('popup panel reveal moves focus out of the hidden panel', () => {
  const revealStart = popupJs.indexOf('function revealPanel(');
  assert.ok(revealStart > 0, 'revealPanel must exist');
  const revealBody = popupJs.slice(revealStart, popupJs.indexOf('\n}', revealStart));
  assert.match(revealBody, /\.focus\(/, 'revealPanel must move focus to the shown panel');
});

test('pair transport copy names Trainer, never the sidecar', () => {
  const transportLines = sharedJs.split('\n').filter((line) => line.includes('pairTransport:'));
  assert.ok(transportLines.length >= 8, 'all eight locales carry pairTransport');
  for (const line of transportLines) {
    assert.doesNotMatch(line, /sidecar/i, line.trim());
  }
});

test('host capture copy never exposes the sidecar term', () => {
  const unavailableLines = hostCopy.split('\n').filter((line) => line.includes('sidecarUnavailable:'));
  assert.ok(unavailableLines.length >= 8, 'all eight locales carry sidecarUnavailable');
  for (const line of unavailableLines) {
    const value = line.slice(line.indexOf(':') + 1);
    assert.doesNotMatch(value, /sidecar/i, line.trim());
  }
});

test('every webview activeView writer keeps liveActiveView authoritative', () => {
  const lines = workbenchState.split('\n');
  const writers = [
    'openTrainingReviewQueue: () => set((state)',
    'beginTrainingReview: () => set((state)',
    'message.type === "ui/coachDraftPrefill"',
    "message.type === \"ui/coachPrompt\"",
  ];
  for (const writer of writers) {
    // The implementation site, not the type declaration.
    let anchorIndex = -1;
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      if (lines[i].includes(writer)) {
        anchorIndex = i;
        break;
      }
    }
    assert.ok(anchorIndex > 0, `${writer} must exist`);
    const window = lines.slice(anchorIndex, anchorIndex + 24).join('\n');
    assert.match(window, /liveActiveView/, `${writer} must update liveActiveView`);
  }
});

test('popup css uses tokens, not raw hex outside the token block', () => {
  for (const line of popupCss.split('\n')) {
    if (/#[0-9a-fA-F]{3,8}\b/.test(line)) {
      assert.match(line, /--[a-z]/i, `raw hex outside a token definition: ${line.trim()}`);
    }
  }
});
