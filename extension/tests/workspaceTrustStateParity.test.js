'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  describeWorkspaceTrustState,
  normalizeWorkspaceTrustState,
  readWorkspaceTrustStateFromCapabilitySummary,
} = require('../dist/shared/src/workspaceTrustState.js');

const settingsViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'settings',
  'CoachSettingsView.tsx',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const resourceCommandsPath = path.resolve(__dirname, '..', 'src', 'commands', 'resourceCommands.ts');
const routersPath = path.resolve(__dirname, '..', '..', 'server', 'app', 'api', 'routers.py');

test('workspace trust states map to honest sentences (zh-CN + en-US)', () => {
  assert.equal(normalizeWorkspaceTrustState('trusted'), 'trusted');
  assert.equal(normalizeWorkspaceTrustState('REMOTE'), 'remote');
  assert.equal(normalizeWorkspaceTrustState('nope'), 'unknown');
  assert.equal(normalizeWorkspaceTrustState(undefined), 'unknown');

  assert.equal(
    describeWorkspaceTrustState('untrusted', 'zh-CN'),
    '这个工作区还不能写入。',
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
    '工作区还没确认。',
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

test('host list_state sends workspace_trusted + remote_name', () => {
  const source = fs.readFileSync(resourceCommandsPath, 'utf8');
  assert.match(source, /params\.set\('workspace_trusted', workspace\.trusted \? 'true' : 'false'\)/);
  assert.match(source, /params\.set\('remote_name', workspace\.remoteName \?\? ''\)/);
});

test('host workspace/authority sends workspace_trusted + remote_name (never omit)', () => {
  const memoryCommandsPath = path.resolve(__dirname, '..', 'src', 'commands', 'memoryCommands.ts');
  const source = fs.readFileSync(memoryCommandsPath, 'utf8');
  assert.match(source, /function buildWorkspaceAuthorityRequestPath/);
  assert.match(source, /params\.set\('workspace_trusted', workspace\.trusted \? 'true' : 'false'\)/);
  assert.match(source, /params\.set\('remote_name', workspace\.remoteName \?\? ''\)/);
  assert.match(source, /buildWorkspaceAuthorityRequestPath\(context\)/);
});

test('sidecar workspace_authority applies host trust before authority_summary', () => {
  const routers = fs.readFileSync(routersPath, 'utf8');
  const start = routers.indexOf('def workspace_authority(');
  assert.ok(start >= 0, 'expected workspace_authority route');
  const body = routers.slice(start, start + 1600);
  assert.match(body, /workspace_trusted: bool \| None = None/);
  assert.match(body, /remote_name: str \| None = None/);
  assert.match(body, /trust_patch\["workspace_trusted"\] = bool\(host_trusted\)/);
  assert.match(body, /runtime\.memory_service\.update_workspace_state\(resolved_workspace_id, \*\*trust_patch\)/);
});

test('host sandbox mutations send explicit_destructive_policy false (never pretend bypass)', () => {
  const source = fs.readFileSync(resourceCommandsPath, 'utf8');
  const trueMatches = source.match(/explicit_destructive_policy:\s*true/g) ?? [];
  const falseMatches = source.match(/explicit_destructive_policy:\s*false/g) ?? [];
  assert.equal(trueMatches.length, 0, 'ordinary Resources mutations must not send policy true');
  assert.equal(falseMatches.length, 5, 'expected five sandbox mutation posts to send policy false');
  assert.doesNotMatch(source, /explicit_destructive_policy:\s*(?:payload|options|undefined|[\w.]*\?)/);
});

test('host session/start sends workspace_trusted + remote_name (never JSON-omit)', () => {
  const sessionCommandsPath = path.resolve(__dirname, '..', 'src', 'commands', 'sessionCommands.ts');
  const runtimeRehydrationPath = path.resolve(__dirname, '..', 'src', 'core', 'runtimeRehydration.ts');
  const admissionPath = path.resolve(
    __dirname,
    '..',
    'src',
    'commands',
    'workspaceAdmissionCommands.ts',
  );
  for (const filePath of [sessionCommandsPath, runtimeRehydrationPath, admissionPath]) {
    const source = fs.readFileSync(filePath, 'utf8');
    assert.match(
      source,
      /remote_name:\s*context\.getHostState\(\)\.workspace\.remoteName\s*\?\?\s*''/,
      `${path.basename(filePath)} must send remote_name`,
    );
    assert.match(
      source,
      /workspace_trusted:\s*Boolean\(context\.getHostState\(\)\.workspace\.trusted\)/,
      `${path.basename(filePath)} must send workspace_trusted`,
    );
  }
});

test('sidecar sandbox_state applies host trust before list_state', () => {
  const routers = fs.readFileSync(routersPath, 'utf8');
  const start = routers.indexOf('def sandbox_state(');
  assert.ok(start >= 0, 'expected sandbox_state route');
  const body = routers.slice(start, start + 1800);
  assert.match(body, /workspace_trusted: bool \| None = None/);
  assert.match(body, /remote_name: str \| None = None/);
  assert.match(body, /trust_patch\["workspace_trusted"\] = bool\(host_trusted\)/);
  assert.match(body, /runtime\.memory_service\.update_workspace_state\(resolved_workspace_id, \*\*trust_patch\)/);
});

test('host sandbox/root sends workspace_trusted + remote_name (never JSON-omit)', () => {
  const source = fs.readFileSync(resourceCommandsPath, 'utf8');
  const start = source.indexOf("'/sandbox/root'");
  assert.ok(start >= 0, 'expected /sandbox/root post');
  const body = source.slice(start, start + 700);
  assert.match(body, /remote_name:\s*workspace\.remoteName\s*\?\?\s*''/);
  assert.match(body, /workspace_trusted:\s*Boolean\(workspace\.trusted\)/);
});

test('host sandbox mutation POSTs send workspace_trusted + remote_name (never JSON-omit)', () => {
  const source = fs.readFileSync(resourceCommandsPath, 'utf8');
  for (const route of ['/sandbox/mkdir', '/sandbox/write', '/sandbox/rename', '/sandbox/delete', '/sandbox/restore']) {
    const start = source.indexOf(`'${route}'`);
    assert.ok(start >= 0, `expected ${route} post`);
    const body = source.slice(start, start + 700);
    assert.match(body, /remote_name:\s*workspace\.remoteName\s*\?\?\s*''/, `${route} remote_name`);
    assert.match(body, /workspace_trusted:\s*Boolean\(workspace\.trusted\)/, `${route} workspace_trusted`);
  }
});

test('sidecar sandbox mutation routes apply host trust before op', () => {
  const routers = fs.readFileSync(routersPath, 'utf8');
  for (const marker of [
    'def sandbox_mkdir(',
    'def sandbox_write(',
    'def sandbox_rename(',
    'def sandbox_delete(',
    'def sandbox_restore(',
  ]) {
    const start = routers.indexOf(marker);
    assert.ok(start >= 0, `expected ${marker}`);
    const body = routers.slice(start, start + 900);
    assert.match(
      body,
      /apply_host_workspace_trust_attestation\(workspace_id, payload\)/,
      `${marker} must re-attest host trust`,
    );
  }
});

test('sidecar sandbox_root applies host trust before list_state', () => {
  const routers = fs.readFileSync(routersPath, 'utf8');
  const start = routers.indexOf('def sandbox_root(');
  assert.ok(start >= 0, 'expected sandbox_root route');
  const body = routers.slice(start, start + 2800);
  assert.match(body, /apply_host_workspace_trust_attestation\(resolved_workspace_id, payload\)/);
  assert.match(body, /return sandbox_service\.list_state\(/);
  assert.ok(
    body.indexOf('apply_host_workspace_trust_attestation') < body.indexOf('return sandbox_service.list_state'),
    'trust attestation must run before list_state',
  );
});

test('host turn/session/message sends workspace_trusted + remote_name (never JSON-omit)', () => {
  const sessionCommandsPath = path.resolve(__dirname, '..', 'src', 'commands', 'sessionCommands.ts');
  const source = fs.readFileSync(sessionCommandsPath, 'utf8');
  const nonStream = source.indexOf("usesSessionMessageRoute(sessionPayload) ? '/session/message' : '/turn'");
  assert.ok(nonStream >= 0, 'expected non-stream turn/message body');
  const nonStreamBody = source.slice(nonStream, nonStream + 2200);
  assert.match(
    nonStreamBody,
    /remote_name:\s*context\.getHostState\(\)\.workspace\.remoteName\s*\?\?\s*''/,
  );
  assert.match(
    nonStreamBody,
    /workspace_trusted:\s*Boolean\(context\.getHostState\(\)\.workspace\.trusted\)/,
  );
  const stream = source.indexOf("'/session/message/stream'");
  assert.ok(stream >= 0, 'expected stream turn/message body');
  const streamBody = source.slice(stream, stream + 2200);
  assert.match(
    streamBody,
    /remote_name:\s*context\.getHostState\(\)\.workspace\.remoteName\s*\?\?\s*''/,
  );
  assert.match(
    streamBody,
    /workspace_trusted:\s*Boolean\(context\.getHostState\(\)\.workspace\.trusted\)/,
  );
});

test('sidecar turn/session/message apply host trust before execute/ensure', () => {
  const routers = fs.readFileSync(routersPath, 'utf8');
  for (const marker of ['async def session_message(', 'async def turn(', 'async def session_message_stream(', 'async def turn_stream(']) {
    const start = routers.indexOf(marker);
    assert.ok(start >= 0, `expected ${marker}`);
    const body = routers.slice(start, start + 1600);
    assert.match(
      body,
      /apply_host_workspace_trust_attestation\(workspace_id, payload\)/,
      `${marker} must re-attest host trust`,
    );
  }
});

test('host evaluate commands never post target_path (verify-only; no project rewrite)', () => {
  const evaluationCommandsPath = path.resolve(
    __dirname,
    '..',
    'src',
    'commands',
    'evaluationCommands.ts',
  );
  const source = fs.readFileSync(evaluationCommandsPath, 'utf8');
  assert.doesNotMatch(source, /\btarget_path\b/);
  assert.match(source, /['"]\/evaluate\/current-file['"]/);
  assert.match(source, /['"]\/evaluate\/snippet['"]/);
  assert.match(source, /\bfile_path:\s*document\.uri\.fsPath/);
  assert.match(source, /\bcontent:\s*code/);
});

test('host coach/session command surface has no WorkspaceEdit project rewrite path', () => {
  const commandsDir = path.resolve(__dirname, '..', 'src', 'commands');
  const files = fs.readdirSync(commandsDir).filter((name) => name.endsWith('.ts'));
  for (const name of files) {
    const source = fs.readFileSync(path.join(commandsDir, name), 'utf8');
    assert.doesNotMatch(
      source,
      /\bWorkspaceEdit\b|\.applyEdit\b/,
      `${name} must not rewrite learner project files via WorkspaceEdit/applyEdit`,
    );
    if (name === 'providerWebviewCommands.ts') {
      // Sole intentional host writeFile: seed .vscode/trainer.json on open-config.
      assert.match(source, /workspace\.fs\.writeFile\(configUri/);
      assert.match(source, /\.vscode['"],\s*['"]trainer\.json['"]/);
      continue;
    }
    assert.doesNotMatch(
      source,
      /workspace\.fs\.writeFile/,
      `${name} must not write learner project files via workspace.fs.writeFile`,
    );
  }
});

test('Settings first screen paints live trust sentence, not leftover sandbox chrome', () => {
  const settings = fs.readFileSync(settingsViewPath, 'utf8');
  const app = fs.readFileSync(appPath, 'utf8');

  assert.match(settings, /data-workspace-trust-state=\{resolvedWorkspaceTrustState\}/);
  assert.match(settings, /data-settings-workspace-trust="true"/);
  assert.match(settings, /describeWorkspaceTrustState\(resolvedWorkspaceTrustState, language\)/);
  assert.match(
    settings,
    /data-settings-workspace-trust="true"\s*[\s\S]*?role="status"\s*[\s\S]*?aria-live="polite"/,
  );
  assert.doesNotMatch(settings, /data-workspace-trust-state=\{"trusted"\}/);

  assert.match(app, /readWorkspaceTrustStateFromCapabilitySummary\(/);
  assert.match(app, /workspaceAuthority=\{liveSandboxState\?\.authority\}/);
  assert.match(
    app,
    /workspaceTrustState=\{readWorkspaceTrustStateFromCapabilitySummary\(\s*liveSandboxState\?\.capabilitySummary/,
  );
  assert.match(app, /leftoverResourceSandboxStateIsNotLive\(/);
  assert.match(app, /const liveSandboxState = leftoverResourceSandboxStateNotLive/);
});
