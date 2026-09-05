'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const resourceCommandsModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'commands',
  'resourceCommands.js',
);
const workbenchDataModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'core',
  'workbenchData.js',
);
const { createDefaultBootstrapData } = require(workbenchDataModulePath);

function createContext() {
  const patches = [];
  const gets = [];
  const bootstrap = createDefaultBootstrapData(
    {
      trusted: true,
      workspaceFolder: 'F:\\trainer\\workspace-a',
    },
    {
      name: 'Local Compatible',
      baseUrl: 'http://localhost:1234/v1',
      apiKeyRef: 'trainer.default',
      model: 'demo-model',
      capabilities: {
        chat: true,
        responses: true,
        vision: false,
        embeddings: true,
        tools: false,
        jsonSchema: false,
        streaming: true,
      },
    },
    {
      lifecycle: 'ready',
      host: '127.0.0.1',
      port: 34891,
      canStart: true,
    },
  );
  bootstrap.resources = [
    {
      id: 'resource-1',
      title: 'Sandbox notes',
      kind: 'markdown',
      status: 'ready',
      summary: 'Notes for the sandbox surface',
      source: 'F:\\trainer\\notes.md',
      sandboxPath: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\notes.md',
    },
  ];
  bootstrap.memory.selectedResourceDetail = {
    id: 'resource-1',
    title: 'Sandbox notes',
    kind: 'markdown',
    status: 'ready',
    summary: 'Notes for the sandbox surface',
    source: 'F:\\trainer\\notes.md',
    sandboxPath: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\notes.md',
  };

  return {
    workbench: {
      resolveWebviewUriForPath() {
        return undefined;
      },
    },
    trustGuard: {
      async ensureTrusted() {
        return true;
      },
    },
    sidecarManager: {
      async ensureRunning() {
        return { lifecycle: 'ready', port: 34891 };
      },
    },
    sidecarClient: {
      async getJson(port, requestPath) {
        gets.push({ port, requestPath });
        return {
          workspace_id: 'F:\\trainer\\workspace-a',
          root_path: 'F:\\trainer\\workspace-a',
          sandbox_root_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a',
          workspace_root_path: 'F:\\trainer\\workspace-a',
          active_workspace_root: 'F:\\trainer\\workspace-a',
          trash_root_path: 'F:\\trainer\\workspace-a\\.trainer\\trash',
          ready: true,
          linked_resource_count: 1,
          total_files: 1,
          total_directories: 0,
          total_size_bytes: 128,
          last_updated_at: '2026-06-20T08:00:00Z',
          selected_path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\notes.md',
          preview: {
            path: 'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\notes.md',
            title: 'Sandbox notes',
            preview_kind: 'markdown',
            preview_tier: 'rich',
            content: '# Sandbox notes',
          },
          capability_summary: {
            permission_state: 'coach_only',
            network_execution_status: {
              status: 'degraded',
              reason_code: 'network_egress_enforcement_missing',
              network_facts: {
                non_python: {
                  current_enforcement: 'node_socket_guard',
                },
                os_container: {
                  required_executor: 'os_container_egress',
                },
              },
            },
          },
        };
      },
    },
    getHostState() {
      return {
        bootstrap,
        workspace: {
          workspaceFolder: 'F:\\trainer\\workspace-a',
          activeWorkspaceRoot: 'F:\\trainer\\workspace-a',
        },
      };
    },
    getSessionId() {
      return 'session-1';
    },
    async patchWorkbenchData(patch) {
      patches.push(patch);
    },
    __patches: patches,
    __gets: gets,
  };
}

test('refreshSandboxCommand loads the authoritative sandbox state route and patches memory state', async () => {
  const vscodeMock = {};
  const { refreshSandboxCommand } = loadWithVscodeMock(resourceCommandsModulePath, vscodeMock);
  const context = createContext();

  const result = await refreshSandboxCommand(context);

  assert.equal(result.ok, true);
  assert.match(result.message ?? '', /sandbox capability refreshed/i);
  assert.deepEqual(context.__gets, [
    {
      port: 34891,
      requestPath:
        '/sandbox/state?workspace_id=F%3A%5Ctrainer%5Cworkspace-a&session_id=session-1&selected_path=F%3A%5Ctrainer%5Cworkspace-a%5C.trainer%5Csandboxes%5Cworkspace-a%5Cnotes.md&workspace_trusted=false&remote_name=',
    },
  ]);
  assert.equal(context.__patches.length, 1);
  assert.equal(
    context.__patches[0].memory.sandboxState.selectedPath,
    'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\notes.md',
  );
  assert.equal(
    context.__patches[0].memory.sandboxPreview.path,
    'F:\\trainer\\workspace-a\\.trainer\\sandboxes\\workspace-a\\notes.md',
  );
  assert.equal(context.__patches[0].memory.selectedResourceDetail?.id, 'resource-1');
  assert.equal(
    context.__patches[0].memory.sandboxState.capabilitySummary.permission_state,
    'coach_only',
  );
  assert.equal(
    context.__patches[0].memory.sandboxState.capabilitySummary.network_execution_status.status,
    'degraded',
  );
  assert.equal(
    context.__patches[0].memory.sandboxState.capabilitySummary.network_execution_status.network_facts.non_python.current_enforcement,
    'node_socket_guard',
  );
  assert.equal(
    context.__patches[0].memory.sandboxState.capabilitySummary.network_execution_status.network_facts.os_container.required_executor,
    'os_container_egress',
  );
  assert.equal(context.__patches[0].memory.sandboxState.linked_resource_count, 1);
  assert.equal(
    result.data.capabilitySummary.network_execution_status.reason_code,
    'network_egress_enforcement_missing',
  );
});
