'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const researchCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'researchCommands.js',
);

const FAKE_KEY = 'sk-test-not-a-real-key-aaaaaaaa';
const LEAK_TEXT = [
  'Traceback (most recent call last):',
  '  File "app.py", line 12, in run',
  'KeyError: boom',
  '{"choices":[{"message":{"content":"hidden","token":"fake-token-zzzz"}}]}',
  `api_key=${FAKE_KEY}`,
].join('\n');

function assertNoLeak(value) {
  const rendered = JSON.stringify(value);
  assert.doesNotMatch(rendered, /sk-test-not-a-real-key-aaaaaaaa/);
  assert.doesNotMatch(rendered, /Traceback \(most recent call last\)/i);
  assert.doesNotMatch(rendered, /File "app\.py"/);
  assert.doesNotMatch(rendered, /"choices"/);
  assert.doesNotMatch(rendered, /fake-token-zzzz/);
  assert.doesNotMatch(rendered, /api_key=sk-/i);
}

test('researchStreamMessageHandler posts a sanitized stream/error for leaking sidecar events', async () => {
  const vscodeMock = {
    window: {
      async showInformationMessage() {
        return undefined;
      },
    },
  };
  const { researchStreamMessageHandler } = loadWithVscodeMock(
    researchCommandsModulePath,
    vscodeMock,
  );
  const posts = [];
  const workbench = {
    async postMessage(message) {
      posts.push(message);
    },
  };
  const handler = researchStreamMessageHandler(
    {
      async *fetchSSE() {
        yield {
          event: 'error',
          data: JSON.stringify({ error: LEAK_TEXT }),
        };
      },
    },
    () => ({
      sidecar: {
        lifecycle: 'ready',
        port: 34891,
      },
    }),
    workbench,
  );

  const result = await handler({}, { projectId: 'research-1', message: 'What should I review next?' });

  assert.equal(result.ok, false);
  const streamError = posts.find((message) => message.type === 'stream/error');
  assert.ok(streamError);
  assertNoLeak(streamError);
  assertNoLeak(result.message);
  assert.match(String(streamError.payload.error), /failed|hidden|Settings|Try again|connection/i);
});

test('researchStreamMessageHandler sanitizes thrown stream failures before postMessage', async () => {
  const vscodeMock = {
    window: {
      async showInformationMessage() {
        return undefined;
      },
    },
  };
  const { researchStreamMessageHandler } = loadWithVscodeMock(
    researchCommandsModulePath,
    vscodeMock,
  );
  const posts = [];
  const handler = researchStreamMessageHandler(
    {
      async *fetchSSE() {
        throw new Error(LEAK_TEXT);
      },
    },
    () => ({
      sidecar: {
        lifecycle: 'ready',
        port: 34891,
      },
    }),
    {
      async postMessage(message) {
        posts.push(message);
      },
    },
  );

  const result = await handler({}, { projectId: 'research-1', message: 'What should I review next?' });

  assert.equal(result.ok, false);
  const streamError = posts.find((message) => message.type === 'stream/error');
  assert.ok(streamError);
  assertNoLeak(streamError);
  assertNoLeak(result.message);
  assert.match(String(streamError.payload.error), /failed|hidden|Settings|Try again|connection/i);
});
