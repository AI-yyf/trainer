'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { WebviewStateTransport } = require('../dist/extension/src/core/webviewStateTransport');
const { decideWebviewSync, emptyWebviewSyncCursor, appliedWebviewSyncCursor } = require('../dist/shared/src/webviewSync');

const flushTimers = async (t, ms) => {
  t.mock.timers.tick(ms);
  // Delivery promises settle before the next retry timer is registered.
  await Promise.resolve();
  await Promise.resolve();
};
function fixture(send) {
  const messages = [], statuses = [], acknowledged = [];
  const transport = new WebviewStateTransport({
    retryMs: 8, maxAttempts: 2,
    send: async message => { messages.push(message); return send ? send(message) : true; },
    status: value => statuses.push(value), acknowledged: value => acknowledged.push(value),
  });
  return { transport, messages, statuses, acknowledged };
}
function snapshot(value, scope = {}) {
  return { payload: { task: { title: value }, stable: [1, 2] }, workspaceId: 'w1', sessionId: 's1',
    runtimeGeneration: 'db1', hostState: { value }, ...scope };
}
function ack(message, status = 'applied') {
  return { ...message.sync, status, appliedRevision: message.sync.revision };
}

test('transport commits its delta base only after actual application ACK, coalescing newer state', async () => {
  const f = fixture();
  try {
    await f.transport.publish(snapshot('one'));
    await f.transport.publish(snapshot('two'));
    await f.transport.publish(snapshot('three'));
    assert.equal(f.messages.length, 1);
    assert.equal(f.transport.debug.appliedRevision, 0);
    f.transport.acknowledge({ ...ack(f.messages[0]), status: 'received', appliedRevision: 0 });
    assert.equal(f.transport.debug.receivedRevision, 1);
    assert.equal(f.transport.debug.appliedRevision, 0, 'receipt does not commit the base');
    f.transport.acknowledge({ ...ack(f.messages[0]), status: 'invented-status' });
    assert.equal(f.transport.debug.appliedRevision, 0, 'unknown inbound status cannot claim application');
    f.transport.acknowledge(ack(f.messages[0]));
    assert.equal(f.messages.length, 2);
    assert.equal(f.messages[1].type, 'state/patch');
    assert.deepEqual(f.messages[1].payload, { task: { title: 'three' } });
    assert.equal(f.messages[1].sync.baseRevision, f.messages[0].sync.revision);
    f.transport.acknowledge(ack(f.messages[1]));
    assert.equal(f.transport.debug.appliedRevision, 2);
    assert.equal(f.acknowledged.at(-1).value, 'three');
  } finally { f.transport.dispose(); }
});

test('removing a value uses a replacing snapshot so JSON omission cannot retain stale data', async () => {
  const f = fixture();
  try {
    await f.transport.publish(snapshot('one', { payload: { task: { title: 'one' }, coachOrientation: { state: 'ready' } } }));
    f.transport.acknowledge(ack(f.messages[0]));
    await f.transport.publish(snapshot('two', { payload: { task: { title: 'two' }, coachOrientation: undefined } }));
    const wire = JSON.parse(JSON.stringify(f.messages[1]));
    assert.equal(wire.type, 'bootstrap');
    assert.equal(wire.sync.baseRevision, 0);
    assert.equal('coachOrientation' in wire.payload, false);
  } finally { f.transport.dispose(); }
});

test('lost delivery and lost ACK retry the identical identity, then recover from a fresh full snapshot', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const f = fixture(() => false);
  try {
    await f.transport.publish(snapshot('one'));
    await f.transport.publish(snapshot('latest'));
    await flushTimers(t, 8);
    assert.equal(f.messages[0].sync.messageId, f.messages[1].sync.messageId);
    await flushTimers(t, 8);
    assert.equal(f.messages[2].type, 'bootstrap');
    assert.equal(f.messages[2].sync.baseRevision, 0);
    assert.equal(f.messages[2].payload.task.title, 'latest');
    assert.ok(f.messages[2].sync.revision > f.messages[0].sync.revision);
    f.transport.acknowledge(ack(f.messages[2]));
    assert.equal(f.transport.debug.status, 'current');
  } finally { f.transport.dispose(); }
});

test('unresponsive webview exhausts bounded retries, unchanged navigation does not restart it', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const f = fixture(() => { throw new Error('disposed'); });
  const state = snapshot('one');
  try {
    await f.transport.publish(state);
    for (let attempt = 0; attempt < 4; attempt += 1) await flushTimers(t, 8);
    assert.equal(f.messages.length, 4);
    assert.equal(f.transport.debug.status, 'stale');
    assert.equal(await f.transport.whenApplied(), false);
    await f.transport.publish(state);
    await flushTimers(t, 32);
    assert.equal(f.messages.length, 4);
    await f.transport.publish(state, true);
    assert.equal(f.messages.length, 5);
  } finally { f.transport.dispose(); }
});

test('workspace/session/runtime replacement invalidates pending ACK and waiters', async () => {
  const f = fixture();
  try {
    await f.transport.publish(snapshot('one'));
    const old = f.messages[0];
    const waited = f.transport.whenApplied();
    await f.transport.publish(snapshot('two', { workspaceId: 'w2', sessionId: 's2', runtimeGeneration: 'db2' }));
    assert.equal(await waited, false);
    const current = f.messages.at(-1);
    assert.ok(current.sync.generation > old.sync.generation);
    f.transport.acknowledge(ack(old));
    assert.equal(f.transport.debug.appliedRevision, 0);
    f.transport.acknowledge(ack(current));
    assert.equal(f.acknowledged.at(-1).value, 'two');
  } finally { f.transport.dispose(); }
});

test('whenApplied does not resolve against an older in-flight state', async () => {
  const f = fixture();
  try {
    await f.transport.publish(snapshot('one'));
    await f.transport.publish(snapshot('two'));
    let resolved = false;
    const waiting = f.transport.whenApplied().then(value => { resolved = value; return value; });
    f.transport.acknowledge(ack(f.messages[0]));
    await Promise.resolve();
    assert.equal(resolved, false);
    f.transport.acknowledge(ack(f.messages[1]));
    assert.equal(await waiting, true);
  } finally { f.transport.dispose(); }
});

test('receiver rejects delta gaps, old scopes, duplicate/conflicting revisions and preserves monotonic generations', () => {
  const initial = { generation: 1, revision: 1, baseRevision: 0, messageId: '1:1', workspaceId: 'w', sessionId: 's' };
  assert.equal(decideWebviewSync(emptyWebviewSyncCursor(), initial), 'apply');
  const cursor = appliedWebviewSyncCursor(initial);
  assert.equal(decideWebviewSync(cursor, initial), 'duplicate');
  assert.equal(decideWebviewSync(cursor, { ...initial, messageId: 'collision' }), 'recover');
  assert.equal(decideWebviewSync(cursor, { ...initial, revision: 4, baseRevision: 3, messageId: '1:4' }), 'recover');
  assert.equal(decideWebviewSync(cursor, { ...initial, revision: 2, baseRevision: 1, messageId: '1:2' }), 'apply');
  assert.equal(decideWebviewSync(cursor, { ...initial, revision: 2, generation: 2, sessionId: 'new', messageId: '2:2' }), 'apply');
  const newer = { ...cursor, generation: 3, revision: 8 };
  assert.equal(decideWebviewSync(newer, { ...initial, generation: 2, revision: 9 }), 'ignore');
  assert.equal(decideWebviewSync(newer, { ...initial, generation: 4, revision: 7 }), 'ignore');
});
