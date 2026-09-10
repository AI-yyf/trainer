'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const protocolPath = path.resolve(__dirname, '..', '..', 'shared', 'src', 'protocol.ts');

test('nonempty_sse_no_visible_content stays distinct from empty_stream Coach copy', () => {
  const protocol = fs.readFileSync(protocolPath, 'utf8');
  const nonemptyIdx = protocol.indexOf('nonempty_sse_no_visible_content');
  const emptyIdx = protocol.indexOf('normalizedCategory === "empty_stream"');
  assert.ok(nonemptyIdx > 0);
  assert.ok(emptyIdx > nonemptyIdx, 'nonempty_sse branch must precede empty_stream');
  assert.match(protocol, /without visible reply text/);
  assert.match(protocol, /没有可见回复/);
  assert.match(protocol, /Empty stream: the model sent no content/);
  assert.match(protocol, /空流：模型没有返回任何内容/);
});
