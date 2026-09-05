'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const extensionSourcePath = path.resolve(__dirname, '..', 'src', 'extension.ts');

test('workspace folder changes reset session state before restoring and rehydrating the target workspace', () => {
  const source = fs.readFileSync(extensionSourcePath, 'utf8');
  const listenerStart = source.indexOf('vscode.workspace.onDidChangeWorkspaceFolders(() => {');
  const listenerEnd = source.indexOf('}),', listenerStart);
  const listenerSource = source.slice(listenerStart, listenerEnd);

  assert.ok(listenerStart >= 0 && listenerEnd > listenerStart, 'workspace folder listener must exist');
  assert.match(source, /import \{ invalidateActiveTrainerStreams \} from '\.\/commands\/sessionCommands';/);
  assert.match(listenerSource, /void invalidateActiveTrainerStreams\(commandContext\)\.catch\(/);
  assert.match(listenerSource, /sessionId:\s*undefined/);
  assert.match(listenerSource, /streamingState:\s*createEmptyTrainerStreamingState\(\)/);
  assert.match(listenerSource, /bootstrap:\s*createDefaultBootstrapData\(/);
  assert.match(listenerSource, /persistWorkspaceSessionId\(/);
  assert.match(listenerSource, /getPersistedWorkspaceSessionId\(/);
  assert.match(listenerSource, /rehydrateWorkbenchRuntime\(commandContext/);
  assert.match(listenerSource, /syncLiveContext\(\)/);
  assert.ok(
    listenerSource.indexOf('invalidateActiveTrainerStreams(commandContext)') <
      listenerSource.indexOf('sessionId: undefined'),
    'active streams must be invalidated before the target workspace state is installed',
  );
});
