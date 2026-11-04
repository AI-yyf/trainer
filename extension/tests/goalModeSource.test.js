'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), 'utf8');

test('goal mode reaches the sidecar only as an explicit opt-in flag', () => {
  const app = read('webview', 'src', 'app', 'App.tsx');
  const hostTypes = read('src', 'core', 'types.ts');
  const sessionCommands = read('src', 'commands', 'sessionCommands.ts');

  // Webview: visible mode + payload flag; the copy is language-owned.
  assert.match(app, /GOAL_MODE_COPY/);
  assert.match(app, /goalMode: turnGoalMode === true/);
  assert.match(app, /goalMode: intent === "coach" \? goalMode && !goalPaused : undefined/);
  // Goal mode is entered from a reply ("设为目标"), not a composer toolbar icon.
  assert.doesNotMatch(app, /id: "composer-goal-mode"/);
  assert.match(app, /action === "set-goal"/);
  assert.match(app, /startGoal\(title\)/);
  assert.match(app, /data-goal-entry="true"/);
  assert.match(app, /startGoal\(""\)/);

  // Host: payload accepts the flag and both request paths forward it.
  assert.match(hostTypes, /goalMode\?: boolean;/);
  assert.equal(
    (sessionCommands.match(/goal_mode: (?:sessionPayload\?|streamPayload)\.goalMode === true,/g) || []).length,
    2,
  );
});

test('goal state is restored from the active session', () => {
  const store = read('webview', 'src', 'app', 'useWorkbenchState.ts');
  const app = read('webview', 'src', 'app', 'App.tsx');
  assert.match(store, /trainer\.goal\.v1/);
  assert.match(store, /restoreGoalForSession/);
  assert.match(store, /persistGoalState/);
  assert.match(app, /restoreGoalForSession\(nextSessionId\)/);
});

test('goal mode copy exists for all eight languages', () => {
  const copy = read('webview', 'src', 'lib', 'i18n', 'segments', 'coachInlineText.ts');
  const start = copy.indexOf('export const GOAL_MODE_COPY');
  const end = copy.indexOf('export const COACH_WORKING_LABELS');
  assert.ok(start >= 0 && end > start, 'expected GOAL_MODE_COPY block');
  const block = copy.slice(start, end);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(block, new RegExp(`"${language}":`), `missing ${language}`);
  }
});
