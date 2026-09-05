'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

test('coach streaming placeholder stays descriptive before the first chunk arrives', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /const streamingPlaceholderBody = useMemo\(\(\) => \{/);
  assert.match(
    source,
    /Working through the current step, then writing the first visible reply\./,
  );
  assert.match(
    source,
    /Thinking through your prompt, then writing the first visible reply\./,
  );
  assert.match(source, /body: streaming\.streamedContent \|\| streamingPlaceholderBody,/);
  assert.doesNotMatch(source, /body: streaming\.streamedContent \|\| "\.\.\.",/);
});

test('every direct composer turn keeps streaming, even when intent analysis finds a task-shaped request', () => {
  const source = fs.readFileSync(appPath, 'utf8');

  assert.match(source, /stream: true,/);
  assert.doesNotMatch(source, /stream: intent === "coach",/);
});
