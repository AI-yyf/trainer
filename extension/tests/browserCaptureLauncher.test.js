'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadWithVscodeMock } = require('./helpers/loadWithVscodeMock');

const launcherModulePath = path.resolve(
  __dirname,
  '..',
  'dist',
  'extension',
  'src',
  'browserCapture',
  'browserLauncher.js',
);

function loadLauncher() {
  return loadWithVscodeMock(launcherModulePath, {});
}

test('detects installed macOS Chromium browsers from app bundles', () => {
  const { detectChromiumBrowsers } = loadLauncher();
  const present = new Set([
    '/Applications/Google Chrome.app',
    '/Applications/Brave Browser.app',
    '/Applications/Arc.app',
  ]);
  const browsers = detectChromiumBrowsers({
    platform: 'darwin',
    homeDir: '/Users/tester',
    existsSync: (candidate) => present.has(candidate),
  });

  assert.deepEqual(browsers.map((browser) => browser.id), ['chrome', 'brave', 'arc']);
  assert.equal(browsers[0].extensionsUrl, 'chrome://extensions');
  assert.equal(browsers[1].extensionsUrl, 'brave://extensions');
  assert.equal(browsers[2].extensionsUrl, 'arc://extensions');
  assert.equal(browsers[0].launchKind, 'mac-app');
});

test('detects Windows browsers under LOCALAPPDATA and Program Files', () => {
  const { detectChromiumBrowsers } = loadLauncher();
  const chromePath = 'C:\\Users\\tester\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe';
  const edgePath = 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe';
  const present = new Set([chromePath, edgePath]);
  const browsers = detectChromiumBrowsers({
    platform: 'win32',
    env: {
      LOCALAPPDATA: 'C:\\Users\\tester\\AppData\\Local',
      ProgramFiles: 'C:\\Program Files',
      'ProgramFiles(x86)': 'C:\\Program Files (x86)',
    },
    existsSync: (candidate) => present.has(candidate),
  });

  assert.deepEqual(browsers.map((browser) => browser.id), ['chrome', 'edge']);
  assert.equal(browsers[0].launchTarget, chromePath);
  assert.equal(browsers[1].extensionsUrl, 'edge://extensions');
});

test('detects Linux browsers from PATH without invoking a shell', () => {
  const { detectChromiumBrowsers } = loadLauncher();
  const present = new Set(['/usr/bin/brave-browser', '/usr/bin/vivaldi-stable']);
  const browsers = detectChromiumBrowsers({
    platform: 'linux',
    env: { PATH: '/usr/local/bin:/usr/bin' },
    existsSync: (candidate) => present.has(candidate),
  });

  assert.deepEqual(browsers.map((browser) => browser.id), ['brave', 'vivaldi']);
  assert.equal(browsers[0].launchTarget, '/usr/bin/brave-browser');
});

test('launches mac app bundles with open -a and executables directly', () => {
  const { resolveBrowserLaunch } = loadLauncher();
  assert.deepEqual(
    resolveBrowserLaunch({
      id: 'chrome',
      label: 'Google Chrome',
      extensionsUrl: 'chrome://extensions',
      launchTarget: 'Google Chrome',
      launchKind: 'mac-app',
    }),
    { command: 'open', args: ['-a', 'Google Chrome', 'chrome://extensions'] },
  );
  assert.deepEqual(
    resolveBrowserLaunch({
      id: 'brave',
      label: 'Brave',
      extensionsUrl: 'brave://extensions',
      launchTarget: '/usr/bin/brave-browser',
      launchKind: 'executable',
    }),
    { command: '/usr/bin/brave-browser', args: ['brave://extensions'] },
  );
});

test('the install guide names every major Chromium extensions page', () => {
  const { captureInstallGuide } = loadWithVscodeMock(
    path.resolve(
      __dirname,
      '..',
      'dist',
      'extension',
      'src',
      'browserCapture',
      'installBundle.js',
    ),
    {},
  );
  const guide = captureInstallGuide({
    targetDir: '/Users/tester/.trainer/browser-capture',
    version: '0.1.0',
    language: 'en-US',
  });
  for (const url of [
    'chrome://extensions',
    'edge://extensions',
    'brave://extensions',
    'opera://extensions',
    'vivaldi://extensions',
    'arc://extensions',
  ]) {
    assert.match(guide, new RegExp(url.replace(/[./]/g, '\\$&')));
  }
});
