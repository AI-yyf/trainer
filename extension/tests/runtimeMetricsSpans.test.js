'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const metricsPath = path.resolve(__dirname, '..', 'dist', 'extension', 'src', 'core', 'runtimeMetrics.js');

function loadMetrics() {
  delete require.cache[require.resolve(metricsPath)];
  return require(metricsPath);
}

test('§三十六 spans record last samples and first-token count', () => {
  const m = loadMetrics();
  m.resetRuntimeMetrics();

  m.recordSendFirstTokenMs(412);
  m.recordSendFirstTokenMs(380);
  m.recordSidecarReadyMs(1544);
  m.recordProviderRestoreMs(96);

  const snap = m.snapshotRuntimeMetrics();
  assert.equal(snap.sendFirstTokenLastMs, 380);
  assert.equal(snap.sendFirstTokenSamples, 2);
  assert.equal(snap.sidecarReadyLastMs, 1544);
  assert.equal(snap.providerRestoreLastMs, 96);

  const line = m.formatRuntimeMetrics(snap);
  assert.match(line, /firstTokenMs=380\(n=2\)/);
  assert.match(line, /sidecarReadyMs=1544/);
  assert.match(line, /restoreMs=96/);
});
