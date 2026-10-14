'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const extensionRoot = path.resolve(__dirname, '..', 'src');
const sharedRoot = path.resolve(__dirname, '..', '..', 'shared', 'src');

function read(root, relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

function readStylesSource() {
  const root = path.join(webviewRoot, 'styles', 'sections');
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
  return manifest
    .map((entry) => fs.readFileSync(path.join(webviewRoot, entry.file), 'utf8'))
    .join('');
}

test('the open-in-editor command is contributed by the shared catalog, the manifest, and the host router', () => {
  const commands = read(sharedRoot, 'commands.ts');
  const manifest = JSON.parse(read(path.resolve(__dirname, '..'), 'package.json'));
  const constants = read(extensionRoot, 'core/constants.ts');
  const registry = read(extensionRoot, 'commands/registry.config.ts');
  const handler = read(extensionRoot, 'commands/viewLayoutCommands.ts');

  assert.match(commands, /openViewInEditor: "trainer\.view\.openInEditor"/);
  assert.ok(
    manifest.contributes.commands.some((command) => command.command === 'trainer.view.openInEditor'),
  );
  assert.match(constants, /openViewInEditor: trainerCommands\.openViewInEditor/);
  assert.match(registry, /commandId: COMMAND_IDS\.openViewInEditor/);
  assert.match(handler, /context\.workbench\.openInEditor/);
  // The panel opens on the active column through the shared workbench view type.
  assert.match(read(extensionRoot, 'core/workbenchPanel.ts'), /vscode\.ViewColumn\.Active/);
});

test('the editor panel reuses the sidebar bundle, routing table, and state transport', () => {
  const panel = read(extensionRoot, 'core/workbenchPanel.ts');
  const bridge = read(extensionRoot, 'core/webviewBridge.ts');
  const routing = read(extensionRoot, 'core/webviewCommandRouting.ts');

  assert.match(panel, /buildWorkbenchHtml\(/);
  assert.match(panel, /WebviewStateTransport/);
  assert.match(panel, /\{ surface: 'editor' \}/);
  assert.match(panel, /resolveWebviewCommand\(message\)/);
  assert.match(panel, /toBootstrapPayload\(hostState\)/);
  assert.match(panel, /case 'ui\/collapseToSidebar':/);
  // Both surfaces share one routing table; the sidebar bridge delegates to it.
  assert.match(bridge, /import \{ resolveWebviewCommand \} from '\.\/webviewCommandRouting';/);
  assert.match(bridge, /return resolveWebviewCommand\(message\);/);
  assert.match(routing, /case 'resource\/open':/);
  assert.match(routing, /case 'research\/streamMessage':/);
});

test('the shell marks the webview surface and offers the matching surface control', () => {
  const html = read(extensionRoot, 'core/webviewContent.ts');
  const vscode = read(webviewRoot, 'lib/vscode.ts');
  const appShell = read(webviewRoot, 'templates/AppShell.tsx');
  const app = read(webviewRoot, 'app/App.tsx');

  assert.match(html, /window\.__TRAINER_SURFACE__ = "\$\{surface\}"/);
  assert.match(html, /options\?\.surface \?\? 'sidebar'/);
  assert.match(vscode, /export function getWorkbenchSurface\(\): "sidebar" \| "editor"/);
  assert.match(vscode, /postMessage\(\{ type: "ui\/collapseToSidebar" \}\)/);
  assert.match(appShell, /surfaceControl\?: ReactNode/);
  assert.match(appShell, /app-shell-header__surface/);
  assert.match(app, /const editorPanelSurface = getWorkbenchSurface\(\) === "editor";/);
  assert.match(app, /mode="collapse"/);
  assert.match(app, /onClick=\{requestCollapseToSidebar\}/);
});

test('Learning and Resources expose the expand control only when the host can open an editor tab', () => {
  const app = read(webviewRoot, 'app/App.tsx');
  const planView = read(webviewRoot, 'components/plan/CoachPlanView.tsx');
  const resourcesView = read(webviewRoot, 'components/resources/ResourcesWorkbenchView.tsx');
  const learningHome = read(webviewRoot, 'templates/LearningHome.tsx');
  const surfaceButton = read(webviewRoot, 'components/common/WorkbenchSurfaceButton.tsx');

  assert.match(app, /const canOpenInEditor = !editorPanelSurface && !isBrowserPreview;/);
  assert.match(
    app,
    /payload: \{ commandId: trainerCommands\.openViewInEditor, payload: \{ view \} \}/,
  );
  assert.match(app, /onExpandToEditor=\{canOpenInEditor \? \(\) => openViewInEditor\("plan"\) : undefined\}/);
  assert.match(app, /onExpandToEditor=\{canOpenInEditor \? \(\) => openViewInEditor\("resources"\) : undefined\}/);

  for (const source of [planView, resourcesView]) {
    assert.match(source, /onExpandToEditor\?: \(\) => void;/);
    assert.match(source, /expandToEditorLabel\?: string;/);
    assert.match(source, /<WorkbenchSurfaceButton\s+mode="expand"/);
  }
  assert.match(planView, /headerActions=\{expandToEditorControl\}/);
  assert.match(learningHome, /headerActions\?: ReactNode/);
  assert.match(learningHome, /template-learning-home__header-actions/);
  // The control is aria-labeled and hides its label first on narrow sidebars.
  assert.match(surfaceButton, /data-workbench-surface-action=\{mode\}/);
  assert.match(surfaceButton, /aria-label=\{label\}/);
});

test('the panel surface relaxes the sidebar reading caps through a wide container query', () => {
  const styles = readStylesSource();
  const manifest = JSON.parse(
    read(webviewRoot, path.join('styles', 'sections', 'manifest.json')),
  );
  const mainEntry = read(webviewRoot, 'main.tsx');

  assert.ok(
    manifest.some((entry) => entry.file === 'styles/sections/panel-surface.css'),
    'panel-surface.css must stay registered in the sections manifest',
  );
  assert.match(mainEntry, /import "\.\/styles\/sections\/panel-surface\.css";/);
  assert.match(styles, /@container trainer \(min-width: 720px\)/);
  assert.match(styles, /\.coach-plan-view__leftover-note,/);
  assert.match(styles, /\.resources-empty p \{\s*max-width: none;/);
  // Token-only: no raw hex or rgb colors anywhere in the section.
  const panelCss = read(webviewRoot, path.join('styles', 'sections', 'panel-surface.css'));
  assert.doesNotMatch(panelCss, /#[0-9a-fA-F]{3,8}\b/);
  assert.doesNotMatch(panelCss, /rgb\(/);
});

test('host wiring gives the sidebar and the panel one composed workbench host', () => {
  const extension = read(extensionRoot, 'extension.ts');
  const commandContext = read(extensionRoot, 'core/commandContext.ts');

  assert.match(extension, /new WorkbenchEditorPanel\(/);
  assert.match(extension, /openInEditor: \(view\) => editorPanel\.open\(view\)/);
  assert.match(extension, /collapseToSidebar: \(\) => editorPanel\.collapseToSidebar\(\)/);
  assert.match(extension, /await editorPanel\.syncState\(\);/);
  assert.match(extension, /await editorPanel\.postHostMessage\(message\);/);
  assert.match(commandContext, /openInEditor\?\(view: string\): Promise<void>;/);
  assert.match(commandContext, /collapseToSidebar\?\(\): Promise<void>;/);
});
