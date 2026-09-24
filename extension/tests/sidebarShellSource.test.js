'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const appSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'app', 'App.tsx');
const viewTypesPath = path.resolve(__dirname, '..', 'webview', 'src', 'lib', 'types.ts');
const mainSourcePath = path.resolve(__dirname, '..', 'webview', 'src', 'main.tsx');
const stylesPath = path.resolve(__dirname, '..', 'webview', 'src', 'styles.css');
const packageJsonPath = path.resolve(__dirname, '..', 'package.json');
const activityBarMarkPath = path.resolve(__dirname, '..', 'media', 'trainer-icon.svg');
const webviewMarkPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'assets',
  'branding',
  'trainer-mark.svg',
);
const marketplaceIconPath = path.resolve(__dirname, '..', 'media', 'trainer-icon.png');
const trainingCommandsPath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'app',
  'useTrainingCommands.ts',
);
const trainingViewSourcePath = path.resolve(
  __dirname,
  '..',
  'webview',
  'src',
  'components',
  'training',
  'TrainingWorkbenchView.tsx',
);

test('app shell renders a text-only top navigation for the daily views', () => {
  const source = fs.readFileSync(appSourcePath, 'utf8');
  const viewTypes = fs.readFileSync(viewTypesPath, 'utf8');

  assert.match(
    viewTypes,
    /export const COACH_FIRST_SIDEBAR_VIEWS = \[\s*"coach",\s*"plan",\s*"resources",\s*"training",\s*"progress",\s*"settings",\s*\] as const;/s,
  );
  // Phase-C nav: three daily tabs, training appears on activity, Settings
  // lives in the header gear. All five views stay routable.
  assert.match(
    source,
    /const sidebarViewTabs = COACH_FIRST_SIDEBAR_VIEWS\.filter\(\(view\) =>\s*view === "training" \? trainingNavVisible : view !== "settings",\s*\)\.map\(\(view\) => \{/,
  );
  assert.match(source, /const trainingNavVisible =\s*activeView === "training" \|\|/);
  assert.match(source, /const label = coachViewLabel\(layout\.composerLanguage\);/);
  // The plan-composer mode menu keeps the dedicated composer word (计划/Plan)
  // while the sidebar tab itself switched to the 学习/Learning label.
  assert.match(source, /label: resolvePlanComposerCopy\(layout\.composerLanguage\)\.planLabel,/);
  assert.match(source, /const label = resourcesViewLabel\(layout\.composerLanguage\);/);
  assert.match(source, /const label = trainingViewLabel\(layout\.composerLanguage\);/);
  assert.match(source, /data-testid="trainer-view-nav-settings"/);
  assert.match(source, /aria-label=\{settingsViewLabel\(layout\.composerLanguage\)\}/);
  assert.match(source, /className=\{`header-switcher header-switcher--\$\{headerSwitcherDensity\}`\}/);
  assert.match(source, /aria-label=\{t\.viewNavigation\}/);
  assert.match(source, /\{sidebarViewTabs\.map\(\(\{ view, label, compactLabel \}\) => \{/);
  assert.match(source, /data-testid=\{`trainer-view-nav-\$\{view\}`\}/);
  assert.match(source, /aria-label=\{label\}/);
  assert.match(source, /title=\{label\}/);
  assert.match(source, /aria-pressed=\{activeView === view\}/);
  assert.match(source, /aria-current=\{activeView === view \? "page" : undefined\}/);
  assert.match(source, /<span className="header-switcher__label">\{displayLabel\}<\/span>/);
  assert.match(source, /<span className="header-switcher__icon" aria-hidden="true">/);
  assert.match(source, /\{SIDEBAR_VIEW_ICONS\[view\]\}/);
  assert.match(source, /aria-label=\{label\}/);
});

test('top navigation swaps squeezed text for per-view icons', () => {
  const styles = fs.readFileSync(stylesPath, 'utf8');
  const switcherStart = styles.indexOf('\n.header-switcher {');
  const switcherBlock = styles.slice(switcherStart, switcherStart + 520);

  assert.match(switcherBlock, /display:\s*grid;/);
  assert.match(switcherBlock, /grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(0,\s*1fr\)\);/);
  assert.match(switcherBlock, /width:\s*100%;/);
  assert.match(switcherBlock, /padding:\s*8px 0 0;/);
  assert.match(styles, /\.header-switcher__item\s*\{[\s\S]*?border-bottom:\s*1px solid transparent;[\s\S]*?background:\s*transparent;[\s\S]*?border-radius:\s*0;[\s\S]*?font-size:\s*var\(--trainer-font-xs\);/);
  assert.match(styles, /\.header-switcher__item\.is-active\s*\{[\s\S]*?border-bottom-color:\s*var\(--fg-0\);[\s\S]*?font-weight:\s*400;/);
  assert.match(styles, /\.header-switcher--compact\s*\{\s*gap:\s*0;/);
  assert.match(styles, /\.header-switcher--compact \.header-switcher__item\s*\{[\s\S]*?font-size:\s*var\(--trainer-font-2xs\);/);
  assert.match(styles, /\.header-switcher--compact \.header-switcher__label\s*\{\s*font-size:\s*var\(--trainer-font-2xs\);/);
  assert.match(styles, /\.header-switcher__icon\s*\{[\s\S]*?display:\s*none;/);
  assert.match(styles, /\.header-switcher--icon \.header-switcher__icon\s*\{[\s\S]*?display:\s*inline-flex;/);
  assert.match(styles, /\.header-switcher--icon \.header-switcher__label\s*\{[\s\S]*?display:\s*none;/);
});

test('extension manifest exposes Trainer as the VS Code-native universal coach', () => {
  const manifest = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));

  assert.equal(manifest.displayName, 'Trainer');
  assert.equal(manifest.description, 'A conversation-first universal learning coach for VS Code.');
  assert.equal(manifest.icon, 'media/trainer-icon.png');
  assert.equal(manifest.contributes.viewsContainers.activitybar[0].title, 'Trainer');
  assert.equal(manifest.contributes.viewsContainers.activitybar[0].icon, 'media/trainer-icon.svg');
  assert.equal(manifest.contributes.views.trainer[0].name, 'Trainer');
  assert.equal(manifest.contributes.configuration.title, 'Trainer');
  assert.ok(
    manifest.contributes.commands.some(
      (command) => command.command === 'trainer.session.resumeLatestCoachCheckpoint',
    ),
  );
  assert.ok(
    manifest.contributes.commands.some(
      (command) => command.command === 'trainer.session.replayLatestCoachCheckpoint',
    ),
  );
});

test('Trainer uses one small-size-safe monochrome mark across extension surfaces', () => {
  const activityBarMark = fs.readFileSync(activityBarMarkPath, 'utf8');
  const webviewMark = fs.readFileSync(webviewMarkPath, 'utf8');

  assert.equal(activityBarMark, webviewMark);
  assert.match(activityBarMark, /viewBox="0 0 16 16"/);
  assert.match(activityBarMark, /fill="currentColor"/);
  assert.equal(fs.existsSync(marketplaceIconPath), true);
});

test('startup shell stays logo-free and uses text-only status copy', () => {
  const source = fs.readFileSync(mainSourcePath, 'utf8');

  assert.doesNotMatch(source, /trainerMarkUrl/);
  assert.doesNotMatch(source, /<img\s+src=/);
  assert.match(source, /className="trainer-startup-shell"/);
  assert.match(source, /className="trainer-startup-error"/);
});

test('startup shell follows the saved coach language before the app bundle is ready', () => {
  const source = fs.readFileSync(mainSourcePath, 'utf8');

  assert.match(source, /const STARTUP_COPY: Record<ComposerLanguage, StartupCopy>/);
  for (const language of ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR']) {
    assert.match(source, new RegExp(`"${language}"`));
  }
  assert.match(source, /injected\?\.memory\?\.workspace\?\.responseLanguage/);
  assert.match(source, /renderStartupShell\(\s*copy,/);
  assert.doesNotMatch(source, /Loading the coach shell/);
});

test('training command hook accepts the full workbench view union', () => {
  const source = fs.readFileSync(trainingCommandsPath, 'utf8');

  assert.match(source, /import type \{ ActiveWorkbenchView \} from "\.\.\/lib\/types";/);
  assert.match(source, /setActiveView: \(view: ActiveWorkbenchView\) => void,/);
});

test('training keeps a card-only surface free of embedded verification controls', () => {
  const source = fs.readFileSync(trainingViewSourcePath, 'utf8');

  assert.match(source, /const shouldElevateReturnAction = Boolean\(actions\) && isReadyToReturn;/);
  assert.match(source, /\{!cardOnly && verificationReturn\.kind !== "waiting" \? \(/);
  assert.match(source, /<div className="training-verification-return__actions">\{actions\}<\/div>/);
  assert.match(source, /\{cardOnly \? \(/);
  assert.match(source, /training-current__card-stack--card-only/);
  assert.match(source, /\{!cardOnly \? \(isFlashCard \? flashProofSurface : practiceProofSurface\) : null\}/);
  assert.doesNotMatch(source, /training-current__composer-result-actions/);
});
