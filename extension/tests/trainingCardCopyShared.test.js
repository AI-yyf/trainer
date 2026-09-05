'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  compactTrainingCardList,
  compactTrainingCardText,
  compactNarrowSidebarList,
  compactNarrowSidebarText,
  normalizeNarrowSidebarCopy,
  summarizeTrainingCardLead,
  summarizeTrainingScenarioPack,
  summarizeNarrowSidebarLead,
} = require('../dist/shared/src/trainingCardCopy.js');
const {
  summarizePlanCandidateReason,
  summarizeTrainingNextHopCopy,
  summarizeWaitingCoachJudgment,
} = require('../dist/shared/src/coachLanguage.js');

const trainingCardCopySourcePath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'trainingCardCopy.ts');

test('summarizeTrainingCardLead compresses long zh practice descriptions for first screen', () => {
  const lead = summarizeTrainingCardLead(
    'zh-CN',
    '??????????????????????????????????????????????????????????',
    { maxLength: 44 },
  );

  assert.ok(lead);
  assert.ok(lead.length <= 44);
});

test('compactTrainingCardText localizes known english status copy for zh cards', () => {
  const localized = compactTrainingCardText(
    'zh-CN',
    'Route returns the expected model and the focused test passes.',
    { maxLength: 200 },
  );

  assert.ok(localized);
  assert.doesNotMatch(localized, /Route returns the expected model/i);
});

test('compactTrainingCardList deduplicates and clamps practice contract items', () => {
  const items = compactTrainingCardList(
    'en-US',
    [
      'Implement one route slice yourself.',
      'Implement one route slice yourself.',
      'Run the focused test and verify the response payload shape before widening the route logic.',
      'Do not widen extra business logic in this card.',
    ],
    { maxItems: 2, maxLength: 44 },
  );

  assert.deepEqual(items, [
    'Implement one route slice yourself.',
    'Run the focused test and verify the response',
  ]);
});

test('compactNarrowSidebarText compresses long plan preview summaries for narrow sidebars', () => {
  const summary = compactNarrowSidebarText(
    'en-US',
    'This candidate keeps the formal plan unchanged, compares project lane evidence, and waits for explicit review before any governed adoption happens.',
    { maxLength: 72 },
  );

  assert.ok(summary);
  assert.ok(summary.length <= 72, `expected <= 72 chars, got ${summary.length}`);
});

test('summarizeNarrowSidebarLead localizes known english resource status copy for zh sidebars', () => {
  const lead = summarizeNarrowSidebarLead(
    'zh-CN',
    'Route returns the expected model and the focused test passes. Bring back the verification output and one open question.',
    { maxLength: 56 },
  );

  assert.ok(lead);
  assert.ok(lead.length <= 56);
  assert.doesNotMatch(lead, /Route returns the expected model/i);
});

test('compactNarrowSidebarList clamps noisy bilingual sidebar facts', () => {
  const facts = compactNarrowSidebarList(
    'zh-CN',
    [
      'Route returns the expected model and the focused test passes.',
      'Route returns the expected model and the focused test passes.',
      'Bring back the verification output, the response payload, and one open question for the coach.',
      'Do not widen extra business logic in this card.',
    ],
    { maxItems: 2, maxLength: 42 },
  );

  assert.equal(facts.length, 2);
  assert.ok(facts.every((item) => item.length <= 42));
  assert.ok(facts.every((item) => !/Route returns the expected model/i.test(item)));
});

test('normalizeNarrowSidebarCopy localizes known coach-return phrases before truncation', () => {
  const normalized = normalizeNarrowSidebarCopy(
    'zh-CN',
    'Bring back the focused test output, the response payload, and one open question.',
  );

  assert.ok(normalized);
  assert.doesNotMatch(normalized, /Bring back the focused test output/i);
  assert.match(normalized, /[^\x00-\x7F]/u);
});

test('summarizePlanCandidateReason keeps plan candidate notes compact and learner-readable', () => {
  const note = summarizePlanCandidateReason(
    'en-US',
    'Formal plan changes only after an explicit plan action, so keep this as reviewed evidence first and let the learner decide whether to adopt it.',
  );

  assert.ok(note.summary);
  assert.ok(note.summary.length <= 90);
  assert.match(note.line, /^Candidate note:/);
});

test('summarizeTrainingNextHopCopy aligns title and detail for zh narrow sidebars', () => {
  const nextHop = summarizeTrainingNextHopCopy('zh-CN', {
    title: '????????????????????????????',
    summary: '?????????????????????????????????',
    whyNow: '??????????????????????????????????????',
  });

  assert.ok(nextHop.title);
  assert.ok(nextHop.detail);
  assert.ok(nextHop.title.length <= 54);
  assert.ok(nextHop.detail.length <= 88);
});

test('summarizeWaitingCoachJudgment returns one compact waiting summary', () => {
  const waiting = summarizeWaitingCoachJudgment('en-US', {
    returnSummary: 'Bring back the focused test output, the response payload, and one open question.',
  });

  assert.equal(waiting.title, 'Returned to coach');
  assert.ok(waiting.summary);
  assert.ok(waiting.summary.length <= 96);
});

test('summarizeTrainingScenarioPack keeps guided teaching families readable', () => {
  assert.equal(summarizeTrainingScenarioPack('en-US', 'remote_workspace'), 'Remote boundary');
  assert.equal(summarizeTrainingScenarioPack('zh-CN', 'debug_loop'), '\u8c03\u8bd5\u95ed\u73af');
  assert.equal(
    summarizeTrainingScenarioPack('en-US', 'function_guidance'),
    'Function contract recovery',
  );
  assert.equal(summarizeTrainingScenarioPack('en-US', 'unknown_pack'), undefined);
});


test('training card copy source keeps zh labels free of private-use mojibake', () => {
  const source = fs.readFileSync(trainingCardCopySourcePath, 'utf8');
  assert.doesNotMatch(source, /[\uE000-\uF8FF]/u);
  assert.match(source, /zh:\s*"\u8fdc\u7a0b\u8fb9\u754c"/u);
  assert.match(source, /zh:\s*"\u8c03\u8bd5\u95ed\u73af"/u);
  assert.match(source, /zh:\s*"\u51fd\u6570\u5951\u7ea6\u6062\u590d"/u);
});
