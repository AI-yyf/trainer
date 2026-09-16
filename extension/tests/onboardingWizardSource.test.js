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

test('onboarding wizard keeps the fixed three-step ladder and paste-to-use behavior', () => {
  const wizard = read(webviewRoot, 'components/firstlook/OnboardingWizard.tsx');

  assert.match(wizard, /onboardingStepWorkspaceRoot/);
  assert.match(wizard, /onboardingStepTrust/);
  assert.match(wizard, /onboardingStepConnectModel/);
  assert.match(
    wizard,
    /import \{ parseProviderConnectionPaste \} from "\.\.\/\.\.\/\.\.\/\.\.\/\.\.\/shared\/src\/providerGateway";/,
  );
  assert.match(wizard, /const parsed = parseProviderConnectionPaste\(value\);/);
  assert.match(wizard, /aria-current=\{step\.status === "active" \? "step" : undefined\}/);
  // The model step keeps the zero-config trial path next to the paste form.
  assert.match(wizard, /onboardingTrialAction/);
  assert.match(wizard, /onOpenSettings/);
});

test('App derives onboarding state from workbench data and wires every wizard action', () => {
  const app = read(webviewRoot, 'app/App.tsx');

  assert.match(
    app,
    /import \{ deriveOnboardingSteps \} from "\.\.\/\.\.\/\.\.\/\.\.\/shared\/src\/onboarding";/,
  );
  assert.match(
    app,
    /const onboarding = deriveOnboardingSteps\(\{\s*workspaceAdmissionStatus: trainerWorkspaceAdmission\?\.status,\s*workspaceTrustState: readWorkspaceTrustStateFromCapabilitySummary\(/,
  );
  // Wizard covers true cold starts only; saved-connection recovery stays untouched.
  assert.match(
    app,
    /const onboardingActive =\s*!onboarding\.complete &&\s*\(!data\.providerConfig\.configured \|\| trainerWorkspaceAdmission\?\.status === "root-missing"\);/,
  );
  assert.match(app, /commandId: trainerCommands\.startProviderTrial/);
  assert.match(app, /onChooseWorkspaceRoot=\{\(\) =>\s*runWorkspaceAdmissionCommand\(trainerCommands\.chooseTrainerWorkspaceRoot\)\s*\}/);
  assert.match(app, /payload: \{ commandId: trainerCommands\.trustWorkspaceWindow \}/);
  assert.match(app, /onSaveConnection=\{saveProviderDraft\}/);
  assert.match(app, /onStartTrial=\{startOnboardingTrial\}/);
  // Rendered in both cold-start surfaces: blocked workspace root view and neutral empty state.
  assert.match(app, /\{onboardingWizard \? <div className="coach-onboarding">\{onboardingWizard\}<\/div> : null\}/);
  assert.match(app, /if \(onboardingWizard\) \{/);
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
