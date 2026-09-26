'use strict';

// PR-7 batch 1: coach session-history state and actions live in a dedicated
// feature hook instead of App.tsx. Behavior contract:
//   * host "session/list" messages land in applySessionList
//   * browser preview builds a synthetic "current conversation" entry
//   * preview never activates sessions or creates new chats (honest no-op)
//   * opening the history menu always refreshes the list first

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const hookPath = path.join(webviewRoot, 'app', 'useCoachHistory.ts');
const appPath = path.join(webviewRoot, 'app', 'App.tsx');

test('coach history state and actions live in the useCoachHistory hook', () => {
  const hook = fs.readFileSync(hookPath, 'utf8');

  assert.match(hook, /export function useCoachHistory/);
  // Pure helpers stay testable without a React renderer.
  assert.match(hook, /export function buildPreviewSessionEntry/);
  assert.match(hook, /export function applySessionListPayload/);
  // Preview honesty: the synthetic entry is marked active, preview blocks
  // activation and new chats.
  assert.match(hook, /is_active: true/);
  assert.match(hook, /Preview mode does not create new conversations/);
});

test('App.tsx consumes the hook and drops the inline history state', () => {
  const app = fs.readFileSync(appPath, 'utf8');

  assert.match(app, /useCoachHistory\(\{/);
  assert.match(app, /applySessionList\(/);
  assert.doesNotMatch(app, /const \[coachSessions, setCoachSessions\] = useState/);
  assert.doesNotMatch(app, /const \[coachSessionsStatus, setCoachSessionsStatus\] = useState/);
  assert.doesNotMatch(app, /const requestCoachSessions = useCallback/);
});
