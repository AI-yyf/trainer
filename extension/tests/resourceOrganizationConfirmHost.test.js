'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const sessionCommandsPath = path.resolve(
  __dirname,
  '..',
  'src',
  'commands',
  'sessionCommands.ts',
);
const resourceCommandsPath = path.resolve(
  __dirname,
  '..',
  'src',
  'commands',
  'resourceCommands.ts',
);
const previewBodyPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'preview',
  'PreviewBody.tsx',
);
const htmlSanitizerPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'lib',
  'htmlSanitizer.ts',
);
const resourcesViewPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'resources',
  'ResourcesWorkbenchView.tsx',
);
const appPath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const modelsPath = path.resolve(__dirname, '..', '..', 'server', 'app', 'core', 'models.py');
const routersPath = path.resolve(__dirname, '..', '..', 'server', 'app', 'api', 'routers.py');
const toolsPath = path.resolve(__dirname, '..', '..', 'server', 'app', 'llm', 'tools.py');
const runtimePath = path.resolve(__dirname, '..', '..', 'server', 'app', 'api', 'runtime.py');

test('PreviewBody source routes HTML through sanitizePreviewHtml', () => {
  const source = fs.readFileSync(previewBodyPath, 'utf8');
  assert.match(source, /import \{ sanitizePreviewHtml \} from ["']\.\.\/\.\.\/lib\/htmlSanitizer["']/);
  assert.match(source, /const sanitizedHtml = sanitizePreviewHtml\(html\)/);
  assert.match(source, /dangerouslySetInnerHTML=\{\{\s*__html:\s*sanitizedHtml\s*\}\}/);
  assert.doesNotMatch(source, /dangerouslySetInnerHTML=\{\{\s*__html:\s*html\s*\}\}/);
});

test('htmlSanitizer drops script hosts and sanitizes unwrap children', () => {
  const source = fs.readFileSync(htmlSanitizerPath, 'utf8');
  assert.match(source, /typeof document === ["']undefined["']/);
  assert.match(source, /return ""/);
  assert.match(source, /tagName === ["']script["']|DROP_HOST_TAGS/);
  assert.match(source, /node\.remove\(\)/);
  assert.match(
    source,
    /for \(const child of Array\.from\(node\.children\)\) \{\s*sanitizeElement\(child\);/,
  );
});

test('host stamp required: organize_resources rejects model confirmed without host stamp', () => {
  const tools = fs.readFileSync(toolsPath, 'utf8');
  assert.match(tools, /def _resource_organization_host_confirmed/);
  assert.match(tools, /extra\.get\("resource_organization_confirmed"\) is True/);
  assert.match(tools, /host_confirmation_required/);
  assert.match(tools, /ignore args\.confirmed/);
  assert.match(tools, /args\.get\("confirmed"\) is True and not host_confirmed and not autonomous/);
  assert.match(tools, /_has_resource_organization_pending/);
  assert.match(tools, /_consume_resource_organization_pending/);
  assert.match(tools, /_record_resource_organization_pending/);
  assert.match(tools, /No pending organize_resources proposal/);
  assert.match(tools, /Consume pending atomically before any FS write/);
});

test('non-stream sendMessageCommand stamps the same host-armed extra as stream', () => {
  const session = fs.readFileSync(sessionCommandsPath, 'utf8');
  const sendMessageIdx = session.indexOf('export async function sendMessageCommand');
  const sendStreamIdx = session.indexOf('export async function sendStreamMessageCommand');
  assert.ok(sendMessageIdx >= 0);
  assert.ok(sendStreamIdx > sendMessageIdx);
  const nonStreamBody = session.slice(sendMessageIdx, sendStreamIdx);
  const streamBody = session.slice(sendStreamIdx);
  assert.match(
    nonStreamBody,
    /resource_organization_confirmed:\s*consumeResourceOrganizationConfirmed\(context\)/,
  );
  assert.match(
    streamBody,
    /resource_organization_confirmed:\s*consumeResourceOrganizationConfirmed\(context\)/,
  );
  assert.match(nonStreamBody, /['"]\/session\/message['"]/);
  assert.match(nonStreamBody, /['"]\/turn['"]/);
  assert.doesNotMatch(nonStreamBody, /resourceOrganizationConfirmed\s*===\s*true/);
});

test('non-stream response notes organize tool_result pending like stream', () => {
  const session = fs.readFileSync(sessionCommandsPath, 'utf8');
  const sendMessageIdx = session.indexOf('export async function sendMessageCommand');
  const sendStreamIdx = session.indexOf('export async function sendStreamMessageCommand');
  assert.ok(sendMessageIdx >= 0);
  assert.ok(sendStreamIdx > sendMessageIdx);
  const nonStreamBody = session.slice(sendMessageIdx, sendStreamIdx);
  assert.match(session, /export function noteResourceOrganizationFromSessionResponse/);
  assert.match(
    nonStreamBody,
    /noteResourceOrganizationFromSessionResponse\(\s*context,\s*response/,
  );
  assert.match(
    nonStreamBody,
    /notifyResourceOrganizationPending\(context,\s*organizationPending\)/,
  );
  assert.match(session, /visitToolEvents|tool_events/);
  assert.match(session, /requires_confirmation === true/);
});

test('cancel clears host pending and posts server organization cancel', () => {
  const resources = fs.readFileSync(resourceCommandsPath, 'utf8');
  const routers = fs.readFileSync(routersPath, 'utf8');
  const session = fs.readFileSync(sessionCommandsPath, 'utf8');
  assert.match(resources, /export async function cancelResourceOrganizationCommand/);
  assert.match(resources, /cancelResourceOrganizationConfirm\(context\)/);
  assert.match(resources, /['"]\/resource\/organization\/cancel['"]/);
  assert.match(resources, /workspace_id:\s*getRuntimeWorkspaceId\(context\)/);
  assert.match(resources, /type:\s*['"]resourceOrganization\/pending['"]/);
  assert.match(resources, /pending:\s*false/);
  assert.match(resources, /isResourceOrganizationConfirmInFlight\(context\)/);
  assert.match(resources, /cancelStreamMessageCommand\(context\)/);
  assert.match(resources, /markResourceOrganizationConfirmInFlight\(context,\s*true\)/);
  assert.match(session, /resourceOrganizationConfirmInFlightByContext/);
  assert.match(session, /record\.ok === false && record\.requires_confirmation === true/);
  assert.match(session, /record\.ok === true && record\.requires_confirmation === true/);
  assert.match(routers, /@router\.post\(["']\/resource\/organization\/cancel["']\)/);
  assert.match(routers, /cancel_resource_organization_pending/);
});

test('click path sets stamp: host arms only after pending; request body consumes host arm only', () => {
  const session = fs.readFileSync(sessionCommandsPath, 'utf8');
  const resources = fs.readFileSync(resourceCommandsPath, 'utf8');
  const app = fs.readFileSync(appPath, 'utf8');
  const view = fs.readFileSync(resourcesViewPath, 'utf8');
  const models = fs.readFileSync(modelsPath, 'utf8');
  const routers = fs.readFileSync(routersPath, 'utf8');
  const runtime = fs.readFileSync(runtimePath, 'utf8');

  assert.match(session, /export function noteResourceOrganizationToolResult/);
  assert.match(session, /export function armResourceOrganizationConfirm/);
  assert.match(session, /export function consumeResourceOrganizationConfirmed/);
  assert.match(session, /requires_confirmation === true/);
  assert.match(
    session,
    /resource_organization_confirmed:\s*consumeResourceOrganizationConfirmed\(context\)/,
  );
  assert.equal(
    (
      session.match(
        /resource_organization_confirmed:\s*consumeResourceOrganizationConfirmed\(context\)/g,
      ) || []
    ).length,
    2,
  );
  assert.doesNotMatch(session, /resourceOrganizationConfirmed\s*===\s*true/);
  assert.doesNotMatch(
    session,
    /resource_organization_confirmed:\s*(sessionPayload|streamPayload)/,
  );

  assert.match(resources, /export async function confirmResourceOrganizationCommand/);
  assert.match(resources, /armResourceOrganizationConfirm\(context\)/);
  assert.match(resources, /sendStreamMessageCommand\(context/);
  assert.match(resources, /mode:\s*['"]organize['"]/);
  assert.match(resources, /export async function cancelResourceOrganizationCommand/);
  assert.match(resources, /cancelResourceOrganizationConfirm\(context\)/);
  assert.match(resources, /['"]\/resource\/organization\/cancel['"]/);

  assert.match(app, /trainerCommands\.confirmResourceOrganization/);
  assert.match(app, /trainerCommands\.cancelResourceOrganization/);
  assert.match(
    app,
    /resourceOrganizationPending\?\.pending && !leftoverResourceLibraryListNotLive/,
  );
  assert.match(view, /organizationConfirm\?/);
  assert.match(view, /resources-knowledge__confirm-organization-action/);
  assert.match(view, /role="group"/);
  assert.match(view, /autoFocus/);
  assert.match(view, /aria-label=\{organizationCopy\.confirm\}/);
  assert.match(view, /aria-label=\{organizationCopy\.cancel\}/);
  assert.match(view, /aria-label=\{orientation\.primaryActionLabel\}/);

  assert.match(models, /resource_organization_confirmed: bool/);
  assert.match(runtime, /resource_organization_pending/);
  assert.match(routers, /resource_organization_pending/);
  assert.match(routers, /state\.workspace_id in pending/);
  assert.match(routers, /coach_context\["resource_organization_confirmed"\] = True/);
});
