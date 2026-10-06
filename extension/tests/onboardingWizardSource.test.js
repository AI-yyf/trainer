'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webviewRoot = path.resolve(__dirname, '..', 'webview', 'src');
const sharedRoot = path.resolve(__dirname, '..', '..', 'shared', 'src');
const extensionRoot = path.resolve(__dirname, '..', 'src');

function read(root, relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

test('onboarding cold start is conversation-first: a two-row setup card, not a ladder (§十六)', () => {
  const wizard = read(webviewRoot, 'components/firstlook/OnboardingWizard.tsx');

  assert.match(wizard, /onboarding-setup__invite/);
  assert.match(wizard, /onboardingSetupInvite/);
  assert.match(wizard, /onboardingSetupCaption/);
  // The ladder is gone: no ordered step list, no numbered markers.
  assert.doesNotMatch(wizard, /onboarding-wizard__steps/);
  assert.doesNotMatch(wizard, /<ol /);
  // Both setup rows keep the honest done state and an expandable panel each.
  assert.match(wizard, /onboardingSetupModelDone/);
  assert.match(wizard, /onboardingSetupRootDone/);
  assert.match(wizard, /aria-expanded=\{expandedPanel === "model"\}/);
  assert.match(wizard, /aria-current=\{modelStep\?\.status === "active" && !modelDone \? "step" : undefined\}/);
  // Full capability is retained behind the rows: paste-to-use, trial, settings.
  assert.match(wizard, /onboardingStepWorkspaceRoot/);
  assert.match(wizard, /onboardingStepConnectModel/);
  assert.match(
    wizard,
    /import \{ parseProviderConnectionPaste \} from "\.\.\/\.\.\/\.\.\/\.\.\/\.\.\/shared\/src\/providerGateway";/,
  );
  assert.match(wizard, /const parsed = parseProviderConnectionPaste\(value\);/);
  assert.match(wizard, /onboardingTrialAction/);
  assert.match(wizard, /onOpenSettings/);
  assert.match(wizard, /onboardingTrustAction/);
});

test('App derives onboarding state from workbench data and wires every wizard action', () => {
  const app = read(webviewRoot, 'app/App.tsx');

  assert.match(
    app,
    /import \{\s*deriveOnboardingSteps,\s*resolveEffectiveTrustState,\s*\} from "\.\.\/\.\.\/\.\.\/\.\.\/shared\/src\/onboarding";/,
  );
  assert.match(
    app,
    /const effectiveWorkspaceTrustState = resolveEffectiveTrustState\(\s*readWorkspaceTrustStateFromCapabilitySummary\(/,
  );
  assert.match(
    app,
    /const onboarding = deriveOnboardingSteps\(\{\s*workspaceAdmissionStatus: trainerWorkspaceAdmission\?\.status,\s*workspaceTrustState: effectiveWorkspaceTrustState,/,
  );
  // Wizard covers true cold starts only; saved-connection recovery stays untouched.
  // A configured connection whose root went missing is recovery, not onboarding:
  // the governed WorkspaceAdmissionPanel owns that ask (e2e C31/C32).
  assert.match(
    app,
    /const onboardingActive =\s*!onboarding\.complete &&\s*!data\.providerConfig\.configured;/,
  );
  assert.match(app, /commandId: trainerCommands\.startProviderTrial/);
  assert.match(app, /onChooseWorkspaceRoot=\{\(\) =>\s*runWorkspaceAdmissionCommand\(trainerCommands\.chooseTrainerWorkspaceRoot\)\s*\}/);
  assert.match(app, /payload: \{ commandId: trainerCommands\.trustWorkspaceWindow \}/);
  assert.match(app, /onSaveConnection=\{saveProviderDraft\}/);
  assert.match(app, /onStartTrial=\{startOnboardingTrial\}/);
  // Rendered in both cold-start surfaces: the workspace-admission blocking
  // surface owns the wizard (the admission panel must not stack under it),
  // and the neutral empty state hands it the whole cold-start ladder.
  assert.match(
    app,
    /coachBlockingSurface === "workspace-admission" && onboardingWizard \? \([\s\S]*?<div className="coach-onboarding">\{onboardingWizard\}<\/div>/,
  );
  assert.match(app, /if \(onboardingWizard\) \{/);
  assert.match(app, /\{onboardingWizard\}\s*<\/div>\s*\);\s*\}/);
});

test('trial command, registry overrides and command id are all registered', () => {
  const commands = read(sharedRoot, 'commands.ts');
  const constants = read(extensionRoot, 'core/constants.ts');
  const registryConfig = read(extensionRoot, 'commands/registry.config.ts');
  const profileRegistry = read(extensionRoot, 'provider/providerProfileRegistry.ts');
  const trialServer = read(extensionRoot, 'provider/trialProviderServer.ts');

  assert.match(commands, /startProviderTrial: "trainer\.provider\.startTrial"/);
  assert.match(constants, /startProviderTrial: trainerCommands\.startProviderTrial/);
  assert.match(registryConfig, /\{ commandId: COMMAND_IDS\.startProviderTrial, register: \(ctx\) => startProviderTrialCommand\(ctx\) \}/);
  assert.match(
    profileRegistry,
    /async createFromTemplate\(\s*templateIndex: number,\s*apiKey\?: string,\s*overrides\?: Partial<Omit<ProviderProfileConfig, 'id'>>,\s*\)/,
  );
  assert.match(trialServer, /TRIAL_PROVIDER_TEMPLATE_INDEX = 5/);
  assert.match(trialServer, /http:\/\/127\.0\.0\.1:\$\{port\}\/v1/);
  assert.match(read(extensionRoot, 'extension.ts'), /await disposeTrialProviderServer\(\);/);
});

test('onboarding copy exists in every locale', () => {
  const copySource = read(webviewRoot, 'lib/i18n/copy.ts');
  const locales = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];
  for (const locale of locales) {
    assert.match(copySource, new RegExp(`"%s": \\{`.replace('%s', locale)));
    assert.ok(
      copySource.includes('onboardingTitle: "'),
      'onboardingTitle must exist in copy.ts',
    );
  }
  assert.ok(copySource.includes('onboardingTrialAction: "'));
  assert.ok(copySource.includes('onboardingModelPastePlaceholder: "'));
});
