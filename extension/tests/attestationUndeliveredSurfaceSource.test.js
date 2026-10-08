'use strict';

// §四十四 + R1: a completed verification whose evidence delivery failed is a
// Training-surface fact, not a global banner. The host ships only the
// language-neutral [[trainer-attestation-undelivered]] marker; the webview
// governance module owns the eight-language copy and the Training scoping,
// and App's host-status interception attributes the scope. This guard locks
// all three ends of that contract.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const governancePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'operationMessageGovernance.ts',
);
const attestationPath = path.resolve(__dirname, '..', 'src', 'testing', 'trainingAttestation.ts');
const remoteVerifyPath = path.resolve(
  __dirname,
  '..',
  'src',
  'commands',
  'remoteVerificationCommands.ts',
);

test('governance module maps the undelivered marker to eight-language copy and the Training surface', () => {
  const governance = fs.readFileSync(governancePath, 'utf8');

  assert.match(governance, /export const ATTESTATION_UNDELIVERED_MARKER =/);
  // The regex literal escapes the brackets in source; the marker name itself
  // must be present and its exact shape is locked by the host-side export.
  assert.ok(
    governance.includes('trainer-attestation-undelivered'),
    'governance must reference the attestation-undelivered marker',
  );
  assert.match(governance, /export function detectAttestationUndelivered\(/);
  assert.match(governance, /export function attestationUndeliveredMessage\(/);
  for (const language of [
    '"zh-CN"',
    '"en-US"',
    '"es-ES"',
    '"fr-FR"',
    '"de-DE"',
    '"ja-JP"',
    '"ko-KR"',
    '"pt-BR"',
  ]) {
    assert.ok(
      governance.includes(language),
      `attestationUndeliveredMessage must cover ${language}`,
    );
  }
  // Pure surface attribution: the marker stays inside Training even when the
  // message is relayed by a generic caller.
  assert.match(
    governance,
    /if \(detectAttestationUndelivered\(message\)\) \{\s*return "training";\s*\}/,
  );
  // The store-side sanitizer maps the marker to local copy before the generic
  // operation-recovery fallback can swallow it.
  assert.match(
    governance,
    /detectAttestationUndelivered\(message\.message\)\s*\?\s*attestationUndeliveredMessage\(language\)/,
  );
});

test('App host-status interception scopes the undelivered marker to Training', () => {
  const source = fs.readFileSync(appPath, 'utf8');
  const { load } = require('./templateAssertions');
  const { resolveOperationMessageSurface } = load('lib/operationMessageGovernance.ts');

  assert.match(source, /detectAttestationUndelivered\(/);
  assert.match(source, /const hostSurfaceScope = resolveOperationMessageSurface\(\{ message: message\.payload\.message/);
  assert.equal(resolveOperationMessageSurface({ message: '[[trainer-attestation-undelivered]] transport detail',
    resourceOperation: true, planStateFailure: true }), 'training');
  assert.match(source, /attestationUndeliveredMessage\(language\)/);
});

test('the host emits the marker only through the attestation delivery failure path', () => {
  const attestation = fs.readFileSync(attestationPath, 'utf8');
  const remoteVerify = fs.readFileSync(remoteVerifyPath, 'utf8');

  assert.match(attestation, /export const ATTESTATION_UNDELIVERED_MARKER =/);
  assert.match(attestation, /notifyAttestationUndelivered\?: \(\) => void;/);
  assert.match(
    attestation,
    /classifyAttestationDeliveryFailure\(\s*error: unknown\s*\): AttestationDeliveryFailureKind/,
  );
  // The undelivered notice fires only after classification (and the single
  // connect-class retry) failed — never on a delivered attestation.
  assert.match(remoteVerify, /notifyAttestationUndelivered: \(\) => \{/);
  assert.match(remoteVerify, /ATTESTATION_UNDELIVERED_MARKER/);
});
