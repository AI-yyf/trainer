'use strict';

// T-0027 source contract: the coach_finalize next_step must be extracted from
// THIS turn's evidence (concrete file/command/check + success signal), never a
// goal restatement or generic "do a small action" filler. Prompt-level fix for
// the real-provider divergence captured in
// .trainer-convergence/evidence/real-provider-latency-glm53-*.json.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const toolsSource = fs.readFileSync(
  path.resolve(__dirname, '..', '..', 'server', 'app', 'llm', 'tools.py'),
  'utf8',
);
const promptsSource = fs.readFileSync(
  path.resolve(__dirname, '..', '..', 'server', 'app', 'llm', 'prompts.py'),
  'utf8',
);

test('coach_finalize next_step schema demands an evidence-extracted concrete move', () => {
  assert.match(toolsSource, /The ONE concrete verifiable move from this turn's evidence/);
  assert.match(toolsSource, /name the exact/);
  assert.match(toolsSource, /success signal/);
  assert.match(toolsSource, /Never restate/);
  assert.match(toolsSource, /never say 'do a small action and bring the /);
  assert.match(toolsSource, /never invent a step you did not ground in /);
});

test('finalize prompt forbids goal restatement and generic filler in next_step', () => {
  assert.match(promptsSource, /The `next_step` must be extracted from THIS turn's evidence/);
  assert.match(promptsSource, /the observable success signal/);
  assert.match(promptsSource, /the same specific move your visible reply will end with/);
  assert.match(promptsSource, /Never restate the learner's/);
  assert.match(promptsSource, /never use filler like 'do a small action and bring the result back'/);
  assert.match(promptsSource, /introduce a new ungrounded step/);
});
