// Restored behavioral regression test. Original file: extension/tests/trainingCardCopyShared.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Training card copy compaction and localization of known English status copy.
//
// Restoration: partial - 5 of 12 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "summarizeTrainingCardLead compresses long zh practice descriptions for first screen"
//       fails at HEAD: summarizeTrainingCardLead is not a function
//   - "compactTrainingCardList deduplicates and clamps practice contract items"
//       fails at HEAD: compactTrainingCardList is not a function
//   - "summarizePlanCandidateReason keeps plan candidate notes compact and learner-readable"
//       fails at HEAD: summarizePlanCandidateReason is not a function
//   - "summarizeTrainingNextHopCopy aligns title and detail for zh narrow sidebars"
//       fails at HEAD: summarizeTrainingNextHopCopy is not a function
//   - "summarizeWaitingCoachJudgment returns one compact waiting summary"
//       fails at HEAD: summarizeWaitingCoachJudgment is not a function
//   - "summarizeTrainingScenarioPack keeps guided teaching families readable"
//       fails at HEAD: summarizeTrainingScenarioPack is not a function
//   - "training card copy source keeps zh labels free of private-use mojibake"
//       fails at HEAD: The input did not match the regular expression
//       /zh:\s*"\u8fdc\u7a0b\u8fb9\u754c"/u. Input: / import type { ComposerLanguage } from
//       "./types";\r\n' +
// Target: compiled shared modules (extension/dist/shared/src).

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



test('compactTrainingCardText localizes known english status copy for zh cards', () => {
  const localized = compactTrainingCardText(
    'zh-CN',
    'Route returns the expected model and the focused test passes.',
    { maxLength: 200 },
  );

  assert.ok(localized);
  assert.doesNotMatch(localized, /Route returns the expected model/i);
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










