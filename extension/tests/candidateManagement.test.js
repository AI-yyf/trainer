'use strict';

/**
 * P1.4 candidate management guards: merge / mark important / priority ride
 * the existing training command surface and the Training view's one candidate
 * disclosure — no second management surface, no new store.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..', '..');
const sharedCommands = fs.readFileSync(
  path.join(repoRoot, 'shared', 'src', 'commands.ts'),
  'utf8',
);
const trainingCommands = fs.readFileSync(
  path.join(repoRoot, 'extension', 'src', 'commands', 'trainingCommands.ts'),
  'utf8',
);
const constantsSource = fs.readFileSync(
  path.join(repoRoot, 'extension', 'src', 'core', 'constants.ts'),
  'utf8',
);
const registrySource = fs.readFileSync(
  path.join(repoRoot, 'extension', 'src', 'commands', 'registry.config.ts'),
  'utf8',
);
const viewSource = fs.readFileSync(
  path.join(repoRoot, 'extension', 'webview', 'src', 'components', 'training', 'TrainingWorkbenchView.tsx'),
  'utf8',
);
const appSource = fs.readFileSync(
  path.join(repoRoot, 'extension', 'webview', 'src', 'app', 'App.tsx'),
  'utf8',
);

test('candidate management commands are catalogued and mapped', () => {
  assert.match(sharedCommands, /trainingCardMarkImportant: "trainer\.trainingCard\.markImportant"/);
  assert.match(sharedCommands, /trainingCardSetPriority: "trainer\.trainingCard\.setPriority"/);
  assert.match(sharedCommands, /trainingCardMerge: "trainer\.trainingCard\.merge"/);
  for (const key of ['trainingCardMarkImportant', 'trainingCardSetPriority', 'trainingCardMerge']) {
    assert.match(constantsSource, new RegExp(`${key}: trainerCommands\\.${key},`));
  }
});

test('candidate management commands post to the server-owned endpoints', () => {
  assert.match(trainingCommands, /"\/training\/card\/importance"/);
  assert.match(trainingCommands, /"\/training\/card\/priority"/);
  assert.match(trainingCommands, /"\/training\/cards\/merge"/);
  // The host only forwards the learner's decision; the sidecar owns records.
  assert.match(trainingCommands, /export async function trainingCardMarkImportantCommand/);
  assert.match(trainingCommands, /export async function trainingCardSetPriorityCommand/);
  assert.match(trainingCommands, /export async function trainingCardMergeCommand/);
  for (const key of ['trainingCardMarkImportant', 'trainingCardSetPriority', 'trainingCardMerge']) {
    assert.match(registrySource, new RegExp(`commandId: COMMAND_IDS\\.${key},`));
  }
});

test('the candidate card discloses one management surface', () => {
  assert.match(viewSource, /data-candidate-management="true"/);
  assert.match(viewSource, /data-candidate-action="important"/);
  assert.match(viewSource, /data-candidate-priority="true"/);
  assert.match(viewSource, /data-candidate-merge=/);
  // Only candidate cards show it — the entry is gated on the candidate status.
  assert.match(viewSource, /selectedCardStatus === "candidate" && cardId/);
  assert.match(appSource, /handleMarkCandidateImportant/);
  assert.match(appSource, /handleSetCandidatePriority/);
  assert.match(appSource, /handleMergeCandidateDuplicates/);
});
