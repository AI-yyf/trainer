'use strict';

// Owner-directed first-run onboarding (T-0050): when Trainer activates and the
// browser-capture extension has never been set up, VS Code should surface a
// one-time, dismissible prompt that leads to a detected-browser picker —
// exactly once, never blocking first paint, and never nagging an already
// prepared/paired user.

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const modulePath = (...parts) =>
  path.resolve(__dirname, '..', 'dist', 'extension', 'src', 'browserCapture', ...parts);

function loadOnboarding() {
  return loadWithVscodeMock(modulePath('onboarding.js'), {});
}

function loadHostCopy() {
  return loadWithVscodeMock(modulePath('hostCopy.js'), {});
}

const LOCALES = ['zh-CN', 'en-US', 'es-ES', 'fr-FR', 'de-DE', 'ja-JP', 'ko-KR', 'pt-BR'];

const ONBOARDING_KEYS = [
  'onboardingPrompt',
  'onboardingInstall',
  'onboardingNotNow',
  'pickBrowserPlaceholder',
  'installForBrowserDone',
];

test('first-run onboarding prompts exactly when nothing is set up yet', () => {
  const { shouldPromptCaptureOnboarding } = loadOnboarding();
  assert.equal(
    shouldPromptCaptureOnboarding({ prompted: false, prepared: false, paired: false }),
    true,
  );
  assert.equal(
    shouldPromptCaptureOnboarding({ prompted: true, prepared: false, paired: false }),
    false,
  );
  assert.equal(
    shouldPromptCaptureOnboarding({ prompted: false, prepared: true, paired: false }),
    false,
  );
  assert.equal(
    shouldPromptCaptureOnboarding({ prompted: false, prepared: false, paired: true }),
    false,
  );
});

test('onboarding flags survive defensive non-boolean input without prompting', () => {
  const { shouldPromptCaptureOnboarding } = loadOnboarding();
  assert.equal(shouldPromptCaptureOnboarding({ prompted: undefined, prepared: false }), true);
  assert.equal(shouldPromptCaptureOnboarding({ prompted: false, prepared: 'yes' }), false);
  assert.equal(shouldPromptCaptureOnboarding({ prompted: false, paired: 1 }), false);
});

test('onboarding copy exists in all eight languages', () => {
  const { browserCaptureHostCopyTable } = loadHostCopy();
  for (const locale of LOCALES) {
    const table = browserCaptureHostCopyTable[locale];
    for (const key of ONBOARDING_KEYS) {
      assert.ok(typeof table[key] === 'string' && table[key].length > 0, `${locale}.${key} missing`);
    }
  }
});

test('chosen browser launch targets that browser extensions page', () => {
  // The picker composes the existing pure launcher: the detected browser the
  // user picks must drive the launch target, not the first detected one.
  const launcherPath = modulePath('browserLauncher.js');
  const { loadWithVscodeMock: _loader } = { loadWithVscodeMock };
  // eslint-disable-next-line global-require
  const launcher = require(launcherPath);
  void _loader;
  const existsSync = (candidate) => candidate.includes('Chrome') || candidate.includes('Edge');
  const detected = launcher.detectChromiumBrowsers({
    platform: 'darwin',
    existsSync,
  });
  const chrome = detected.find((browser) => browser.id === 'chrome');
  const edge = detected.find((browser) => browser.id === 'edge');
  assert.ok(chrome && edge);
  assert.ok(
    launcher.resolveBrowserLaunch(chrome).args.some((arg) => arg === 'chrome://extensions'),
  );
  assert.ok(
    launcher.resolveBrowserLaunch(edge).args.some((arg) => arg === 'edge://extensions'),
  );
});
