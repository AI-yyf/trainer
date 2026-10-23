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
  // T-0029: ImplementationCoach rescue/fallback template shapes are unanchored
  // by construction — the repair prefers the reply's labelled action for them.
  assert.match(routersSource, /压成一个很小的补丁目标/);
  assert.match(routersSource, /先交付一个小而可复盘的/);
  // Repair never fabricates: only replaces when the reply yields a labelled action.
  assert.match(routersSource, /reply_action = visible_next_step\(reply_content\)/);
  assert.match(routersSource, /agent_meta\["next_step"\] = reply_action/);
  // T-0048: the repair is a named helper invoked before grounding AND memory
  // persistence, so the recorded thread and the grounding gate see the same
  // shipped step as the response surfaces.
  assert.match(routersSource, /def repair_generic_finalize_next_step\(/);
  assert.match(routersSource, /coach_turn_payload = repair_generic_finalize_next_step\(\n\s+assistant_content,/);
  assert.match(routersSource, /refreshed_coach_turn_data = repair_generic_finalize_next_step\(/);
});

test('pedagogy rescue templates derive their target from the turn subject', () => {
  // T-0029 root fix: a lane label that never appears in the learner's message
  // must not become the template target; the message subject wins.
  const coachSource = fs.readFileSync(
    path.resolve(__dirname, '..', '..', 'server', 'app', 'pedagogy', 'implementation_coach.py'),
    'utf8',
  );
  assert.match(coachSource, /label\.casefold\(\) in str\(message or ""\)\.casefold\(\)/);
  assert.match(coachSource, /_message_subject/);
  // The extractor reads actions from label-headed sections (第一步代码 / Next steps).
  const continuitySource = fs.readFileSync(
    path.resolve(__dirname, '..', '..', 'server', 'app', 'llm', 'reply_continuity.py'),
    'utf8',
  );
  assert.match(continuitySource, /"代码", "练习", "实验", "检查", "步骤", "行动", "任务", "code", "s"/);
});

test('T-0035/T-0036: repair rebuilds resume_thread and keeps short CJK steps', () => {
  // The repair must not leave the pre-repair filler inside resume_thread or
  // the coach-turn summary, and the short-step threshold must be CJK-aware.
  assert.match(routersSource, /weighted_length < 12/);
  assert.match(routersSource, /repaired_resume = build_resume_thread_text/);
  assert.match(routersSource, /merge_agent_finalize_into_coach_turn\(\n\s+refreshed_coach_turn_data,\n\s+summary=/);
  const continuitySource = fs.readFileSync(
    path.resolve(__dirname, '..', '..', 'server', 'app', 'llm', 'reply_continuity.py'),
    'utf8',
  );
  assert.match(continuitySource, /已完成/);
});

test('T-0033: stream setup failures resolve the singleflight owner future', () => {
  // A sync failure after the singleflight claim must fail the inflight
  // future — otherwise a same-key retry waits forever without a failure.
  assert.match(
    routersSource,
    /except BaseException as exc:\n\s+# The owner already claimed the singleflight key \(T-0033\)[\s\S]*?_fail_stream_turn_singleflight\(exc\)\n\s+raise/,
  );
  assert.match(
    routersSource,
    /except BaseException as exc:\n\s+# Same singleflight fail-closed rule as \/turn\/stream \(T-0033\)\.\n\s+_fail_stream_session_singleflight\(exc\)\n\s+raise/,
  );
});
