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
const routersSource = fs.readFileSync(
  path.resolve(__dirname, '..', '..', 'server', 'app', 'api', 'routers.py'),
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
  assert.match(promptsSource, /never copy[\s"']*the recalled coaching focus or any memory text into `next_step`/);
  assert.match(promptsSource, /introduce a new ungrounded step/);
});

test('fresh workspaces get no fabricated imperative coaching focus', () => {
  // glm-5.3 quoted the synthetic fallback focus verbatim as a fake next_step
  // on real relay samples; the fallback must stay honest-empty instead.
  const mixinSource = fs.readFileSync(
    path.resolve(__dirname, '..', '..', 'server', 'app', 'memory', 'coaching_adaptation_mixin.py'),
    'utf8',
  );
  assert.doesNotMatch(mixinSource, /reduce the work to one verifiable move/);
  assert.match(routersSource, /T-0027 repair/);
});

test('router repairs generic or pasted-prose next_step from the reply labelled action', () => {
  assert.match(routersSource, /T-0027 repair/);
  assert.match(routersSource, /把结果带回来/);
  assert.match(routersSource, /do a small action/);
  // Over-long or markdown-blob steps (code fences, headings) are also repaired.
  assert.match(routersSource, /len\(finalize_next_step\) > 240/);
  assert.match(routersSource, /"```" in finalize_next_step/);
  assert.match(routersSource, /"## " in finalize_next_step/);
  // Repair never fabricates: only replaces when the reply yields a labelled action.
  assert.match(routersSource, /reply_action = visible_next_step\(reply_content\)/);
  assert.match(routersSource, /if reply_action:\n\s+agent_meta\["next_step"\] = reply_action/);
});
