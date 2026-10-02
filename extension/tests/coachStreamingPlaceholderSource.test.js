'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const appUiCopyPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'appUiCopy.ts');

test('coach streaming placeholder stays descriptive before the first chunk arrives', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const appUiCopySource = fs.readFileSync(appUiCopyPath, 'utf8');

  assert.match(source, /const streamingPlaceholderBody = useMemo\(\(\) => \{/);
  assert.match(
    source,
    /appUiCopy\(layout\.composerLanguage, "正在整理当前步骤，然后给出第一段可见回复。"\)/,
  );
  assert.match(
    source,
    /appUiCopy\(layout\.composerLanguage, "正在梳理你的问题，然后给出第一段可见回复。"\)/,
  );
  assert.match(
    appUiCopySource,
    /"en-US": "Working through the current step, then writing the first visible reply\."/,
  );
  assert.match(
    appUiCopySource,
    /"en-US": "Thinking through your prompt, then writing the first visible reply\."/,
  );
  assert.match(source, /: streaming\.streamedContent \|\| streamingPlaceholderBody,/);
  assert.doesNotMatch(source, /body: streaming\.streamedContent \|\| "\.\.\.",/);
});

test('every direct composer turn keeps streaming, even when intent analysis finds a task-shaped request', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /stream: true,/);
  assert.doesNotMatch(source, /stream: intent === "coach",/);
});
