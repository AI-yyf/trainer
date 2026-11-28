// Restored behavioral regression test. Original file: extension/tests/workspaceTrustStateParity.test.js at df0a3e2a^
// (removed in df0a3e2a; restored against the current compiled extension/dist build).
//
// Coverage: Workspace trust state sentences and fail-closed capability summary trust.
//
// Restoration: partial - 2 of 17 original test definitions kept, their code and assertions unchanged.
// Omitted original tests:
//   - "host list_state sends workspace_trusted + remote_name"
//       source-text guard: reads extension/src/commands/resourceCommands.ts and asserts on its text (out
//       of scope by rule).
//   - "host workspace/authority sends workspace_trusted + remote_name (never omit)"
//       source-text guard: reads extension/src/commands/memoryCommands.ts and asserts on its text (out
//       of scope by rule).
//   - "sidecar workspace_authority applies host trust before authority_summary"
//       source-text guard: reads server/app/api route sources and asserts on its text (out of scope by
//       rule).
//   - "host sandbox mutations send explicit_destructive_policy false (never pretend bypass)"
//       source-text guard: reads extension/src/commands/resourceCommands.ts and asserts on its text (out
//       of scope by rule).
//   - "host session/start sends workspace_trusted + remote_name (never JSON-omit)"
//       source-text guard: reads extension/src/commands/sessionCommands.ts and runtimeRehydration.ts and
//       asserts on its text (out of scope by rule).
//   - "sidecar sandbox_state applies host trust before list_state"
//       source-text guard: reads server/app/api route sources and asserts on its text (out of scope by
//       rule).
//   - "host sandbox/root sends workspace_trusted + remote_name (never JSON-omit)"
//       source-text guard: reads extension/src/commands/resourceCommands.ts and asserts on its text (out
//       of scope by rule).
//   - "host sandbox mutation POSTs send workspace_trusted + remote_name (never JSON-omit)"
//       source-text guard: reads extension/src/commands/resourceCommands.ts and asserts on its text (out
//       of scope by rule).
//   - "sidecar sandbox mutation routes apply host trust before op"
//       source-text guard: reads server/app/api route sources and asserts on its text (out of scope by
//       rule).
//   - "sidecar sandbox_root applies host trust before list_state"
//       source-text guard: reads server/app/api route sources and asserts on its text (out of scope by
//       rule).
//   - "host turn/session/message sends workspace_trusted + remote_name (never JSON-omit)"
//       source-text guard: reads extension/src/commands/sessionCommands.ts and asserts on its text (out
//       of scope by rule). Also fails at HEAD: input did not match
//       /workspace_trusted:\s*Boolean\(context\.getHostState\(\)\.workspace\.trusted\)/.
//   - "sidecar turn/session/message apply host trust before execute/ensure"
//       source-text guard: reads server/app/api route sources and asserts on its text (out of scope by
//       rule).
//   - "host evaluate commands never post target_path (verify-only; no project rewrite)"
//       source-text guard: reads extension/src/commands/evaluationCommands.ts and asserts on its text
//       (out of scope by rule).
//   - "host coach/session command surface has no WorkspaceEdit project rewrite path"
//       source-text guard: reads extension/src/commands/*.ts and asserts on its text (out of scope by
//       rule).
//   - "Settings first screen paints live trust sentence, not leftover sandbox chrome"
//       source-text guard: reads extension/webview settings and app sources and asserts on its text (out
//       of scope by rule). Also fails at HEAD: input did not match
//       /describeWorkspaceTrustState\(resolvedWorkspaceTrustState, language\)/.
// Target: compiled shared modules (extension/dist/shared/src).
// Note: the require of extension/tests/helpers/appModuleSource.js (deleted in df0a3e2a) is dropped: only omitted source-guard tests used it.

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  describeWorkspaceTrustState,
  normalizeWorkspaceTrustState,
  readWorkspaceTrustStateFromCapabilitySummary,
} = require('../dist/shared/src/workspaceTrustState.js');


test('workspace trust states map to honest sentences (zh-CN + en-US)', () => {
  assert.equal(normalizeWorkspaceTrustState('trusted'), 'trusted');
  assert.equal(normalizeWorkspaceTrustState('REMOTE'), 'remote');
  assert.equal(normalizeWorkspaceTrustState('nope'), 'unknown');
  assert.equal(normalizeWorkspaceTrustState(undefined), 'unknown');

  assert.equal(
    describeWorkspaceTrustState('untrusted', 'zh-CN'),
    '此工作区未受信任，Trainer 只会读取，不会写入。',
  );
  assert.equal(
    describeWorkspaceTrustState('remote', 'en-US'),
    'Remote workspace; destructive actions stay off.',
  );
  assert.equal(
    describeWorkspaceTrustState('trusted', 'en-US'),
    'This workspace is trusted.',
  );
  assert.equal(
    describeWorkspaceTrustState('unknown', 'zh-CN'),
    '需要信任此工作区后，Trainer 才能读取项目文件。',
  );
});

test('capability summary trust is fail-closed when missing or leftover', () => {
  assert.equal(readWorkspaceTrustStateFromCapabilitySummary(undefined), 'unknown');
  assert.equal(readWorkspaceTrustStateFromCapabilitySummary({}), 'unknown');
  assert.equal(
    readWorkspaceTrustStateFromCapabilitySummary({
      platform: { workspace_trust_state: 'trusted' },
    }),
    'trusted',
  );
  assert.equal(
    readWorkspaceTrustStateFromCapabilitySummary({
      platform: { workspaceTrustState: 'untrusted' },
    }),
    'untrusted',
  );
  assert.equal(
    readWorkspaceTrustStateFromCapabilitySummary({
      platform: { workspace_trust_state: 'Ready' },
    }),
    'unknown',
  );
});














