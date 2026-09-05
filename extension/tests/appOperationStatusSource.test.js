'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');

function sourceSection(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start);

  assert.ok(start >= 0, `expected ${startMarker}`);
  assert.ok(end > start, `expected ${endMarker} after ${startMarker}`);
  return source.slice(start, end);
}

test('operation-status errors preserve only local recovery copy', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const parser = sourceSection(
    source,
    'function parsePartialResourceDeletionFailure(',
    'function partialResourceDeletionFailureMessage(',
  );
  const formatter = sourceSection(
    source,
    'function partialResourceDeletionFailureMessage(',
    'function sanitizeHostFailureMessage(',
  );
  const sanitizer = sourceSection(
    source,
    'function sanitizeHostFailureMessage(',
    'function sanitizeOperationFailureMessage(',
  );

  // This is intentionally an anchored whitelist for the host's aggregate-delete summary.
  // Arbitrary backend error text must never become user-visible operation feedback.
  assert.match(
    parser,
    /\^Deleted\\s\+\(\\d\+\)\\s\+resources\?\\\.\\s\+\(\\d\+\)\\s\+resources\?\\s\+could not be deleted\\\.\$\/i/,
  );
  assert.match(parser, /message\.trim\(\)/);
  assert.match(parser, /Number\.(?:parseInt|parseFloat)\(/);
  assert.match(parser, /Number\.isSafeInteger\(/);
  assert.match(parser, /deletedCount\s*<\s*1/);
  assert.match(parser, /failedCount\s*<\s*1/);

  // Counts are reformatted locally in both supported operation-status languages;
  // the original host payload must not be interpolated back into the notice.
  assert.match(formatter, /language === "zh-CN"/);
  assert.match(formatter, /\u5df2\u5220\u9664/);
  assert.match(formatter, /\u672a\u80fd\u5220\u9664/);
  assert.match(formatter, /Deleted \$\{deletedCount\}/);
  assert.match(formatter, /\$\{failedCount\} could not be deleted\./);
  assert.doesNotMatch(formatter, /message\.payload|rawMessage|originalMessage/);

  // Error operation/status messages may use only local copy: a narrowly parsed
  // resource count, a locally classified resource recovery, a live-plan task-gate
  // marker, a Provider recovery hint while that action is pending, or the generic
  // operation recovery. Host error prose must never pass through.
  assert.match(
    sanitizer,
    /message\.type !== "operation\/status" \|\| message\.payload\.tone !== "error"/,
  );
  assert.match(sanitizer, /parsePartialResourceDeletionFailure\(message\.payload\.message\)/);
  assert.match(sanitizer, /partialResourceDeletionFailureMessage\(partialDeletion, language\)/);
  assert.match(sanitizer, /isProviderAction\s*=\s*false/);
  assert.match(sanitizer, /resourceOperationKind\?: ResourceOperationKind/);
  assert.match(sanitizer, /resourceOperationFailureMessage\(resourceOperationKind, language\)/);
  assert.match(sanitizer, /parseLivePlanTaskGateMarker\(message\.payload\.message\)/);
  assert.match(sanitizer, /livePlanTaskGateFailureMessage\(livePlanGate, language\)/);
  assert.match(sanitizer, /providerRecoveryMessage\(language\)/);
  assert.match(sanitizer, /recoverableFailureMessage\("operation", language\)/);
  assert.match(
    sanitizer,
    /partialDeletion\s*\?\s*partialResourceDeletionFailureMessage\(partialDeletion, language\)\s*:\s*resourceRecovery\s*\?\s*resourceRecovery\s*:\s*livePlanGate\s*\?\s*livePlanTaskGateFailureMessage\(livePlanGate, language\)\s*:\s*isProviderAction\s*\?\s*providerRecoveryMessage\(language\)\s*:\s*recoverableFailureMessage\("operation", language\)/,
  );
  assert.doesNotMatch(sanitizer, /message:\s*message\.payload\.message/);
});

test('live-plan task mint 409 markers map to local copy and keep composer draft until ack', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  assert.match(source, /trainer-live-plan-task-gate:\(no_live\|leftover\)/);
  assert.match(source, /function livePlanTaskGateFailureMessage\(/);
  assert.match(source, /function livePlanTaskMintPendingMessage\(/);
  assert.match(source, /function livePlanUpdatePendingMessage\(/);
  assert.match(source, /function trainingGenerateCardPendingMessage\(/);
  assert.match(source, /pendingLivePlanTaskMintRef/);
  assert.match(source, /trainerCommands\.nextTask/);
  assert.match(source, /trainerCommands\.taskSpecify/);
  assert.match(source, /trainerCommands\.trainingGenerateCard/);
  assert.match(source, /trainerCommands\.updatePlan/);
  assert.match(source, /isLivePlanTaskMint/);
  assert.match(source, /isGenerateCard/);
  assert.match(source, /isPlanUpdate/);
  assert.match(source, /livePlanTaskMintPendingMessage\(layout\.composerLanguage\)/);
  assert.match(source, /livePlanUpdatePendingMessage\(layout\.composerLanguage\)/);
  assert.match(source, /trainingGenerateCardPendingMessage\(layout\.composerLanguage\)/);
  assert.match(
    source,
    /Keep draft until authoritative success\/failure ack/,
  );
  assert.match(source, /will not invent a task or mutate leftover as live/);
  assert.match(source, /will not resurrect leftover as live/);
});

test('local Provider recovery copy remains actionable without passing through arbitrary errors', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const localSanitizer = sourceSection(
    source,
    'function sanitizeOperationFailureMessage(',
    'interface SettingsActionState',
  );

  assert.match(localSanitizer, /message\.tone !== "error"/);
  assert.match(localSanitizer, /Object\.values\(\s*recoverableFailureCopy\[language\]/);
  assert.match(localSanitizer, /localRecoveryMessages\.push\(providerRecoveryMessage\(language\)\)/);
  assert.match(localSanitizer, /livePlanTaskGateFailureMessage\("no_live", language\)/);
  assert.match(localSanitizer, /parseLivePlanTaskGateMarker\(message\.message\)/);
  assert.match(localSanitizer, /localRecoveryMessages\.includes\(message\.message\)/);
  assert.match(localSanitizer, /recoverableFailureMessage\("operation", language\)/);
  assert.doesNotMatch(localSanitizer, /message:\s*message\.message\s*,/);
});
