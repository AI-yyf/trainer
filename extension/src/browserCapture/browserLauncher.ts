import { spawn } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

/**
 * Zero-network Chromium browser discovery for the "one more click" install
 * flow. Branded browsers refuse programmatic unpacked installs, but they do
 * accept a deep link to their own extensions page — opening the right page in
 * the right browser is the most we can remove from the manual step without
 * asking the user to publish to a Web Store.
 */

export interface ChromiumBrowser {
  id: string;
  label: string;
  /** URL the browser itself understands (chrome://, edge://, …). */
  extensionsUrl: string;
  /** macOS .app bundle name for `open -a`, or absolute executable otherwise. */
  launchTarget: string;
  /** Platform-specific launch kind. */
  launchKind: 'mac-app' | 'executable';
}

export interface DetectBrowserOptions {
  platform?: NodeJS.Platform;
  homeDir?: string;
  env?: NodeJS.ProcessEnv;
  existsSync?: (candidate: string) => boolean;
}

interface BrowserProbe {
  id: string;
  label: string;
  extensionsUrl: string;
  macApp?: string;
  windowsPaths?: Array<{ root: 'localAppData' | 'programFiles' | 'programFilesX86'; relative: string }>;
  linuxNames?: string[];
}

const PROBES: BrowserProbe[] = [
  {
    id: 'chrome',
    label: 'Google Chrome',
    extensionsUrl: 'chrome://extensions',
    macApp: 'Google Chrome',
    windowsPaths: [
      { root: 'localAppData', relative: 'Google/Chrome/Application/chrome.exe' },
      { root: 'programFiles', relative: 'Google/Chrome/Application/chrome.exe' },
      { root: 'programFilesX86', relative: 'Google/Chrome/Application/chrome.exe' },
    ],
    linuxNames: ['google-chrome', 'google-chrome-stable'],
  },
  {
    id: 'edge',
    label: 'Microsoft Edge',
    extensionsUrl: 'edge://extensions',
    macApp: 'Microsoft Edge',
    windowsPaths: [
      { root: 'localAppData', relative: 'Microsoft/Edge/Application/msedge.exe' },
      { root: 'programFiles', relative: 'Microsoft/Edge/Application/msedge.exe' },
      { root: 'programFilesX86', relative: 'Microsoft/Edge/Application/msedge.exe' },
    ],
    linuxNames: ['microsoft-edge', 'microsoft-edge-stable'],
  },
  {
    id: 'brave',
    label: 'Brave',
    extensionsUrl: 'brave://extensions',
    macApp: 'Brave Browser',
    windowsPaths: [
      { root: 'localAppData', relative: 'BraveSoftware/Brave-Browser/Application/brave.exe' },
      { root: 'programFiles', relative: 'BraveSoftware/Brave-Browser/Application/brave.exe' },
    ],
    linuxNames: ['brave-browser', 'brave'],
  },
  {
    id: 'arc',
    label: 'Arc',
    extensionsUrl: 'arc://extensions',
    macApp: 'Arc',
    windowsPaths: [
      { root: 'localAppData', relative: 'Programs/Arc/Arc.exe' },
      { root: 'localAppData', relative: 'Arc/Arc.exe' },
    ],
  },
  {
    id: 'opera',
    label: 'Opera',
    extensionsUrl: 'opera://extensions',
    macApp: 'Opera',
    windowsPaths: [
      { root: 'localAppData', relative: 'Programs/Opera/opera.exe' },
      { root: 'localAppData', relative: 'Opera/opera.exe' },
      { root: 'programFiles', relative: 'Opera/opera.exe' },
    ],
    linuxNames: ['opera'],
  },
  {
    id: 'vivaldi',
    label: 'Vivaldi',
    extensionsUrl: 'vivaldi://extensions',
    macApp: 'Vivaldi',
    windowsPaths: [
      { root: 'localAppData', relative: 'Vivaldi/Application/vivaldi.exe' },
      { root: 'programFiles', relative: 'Vivaldi/Application/vivaldi.exe' },
    ],
    linuxNames: ['vivaldi-stable', 'vivaldi'],
  },
  {
    id: 'chromium',
    label: 'Chromium',
    extensionsUrl: 'chrome://extensions',
    macApp: 'Chromium',
    windowsPaths: [{ root: 'localAppData', relative: 'Chromium/Application/chrome.exe' }],
    linuxNames: ['chromium', 'chromium-browser'],
  },
];

function executableInPath(
  name: string,
  pathValue: string,
  existsSync: (candidate: string) => boolean,
): string | undefined {
  for (const dir of pathValue.split(path.delimiter)) {
    if (!dir) {
      continue;
    }
    const candidate = path.join(dir, name);
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

function windowsRoot(
  root: 'localAppData' | 'programFiles' | 'programFilesX86',
  env: NodeJS.ProcessEnv,
): string | undefined {
  if (root === 'localAppData') {
    return env.LOCALAPPDATA;
  }
  if (root === 'programFiles') {
    return env.ProgramFiles;
  }
  return env['ProgramFiles(x86)'];
}

export function detectChromiumBrowsers({
  platform = process.platform,
  homeDir = os.homedir(),
  env = process.env,
  existsSync = fs.existsSync,
}: DetectBrowserOptions = {}): ChromiumBrowser[] {
  const detected: ChromiumBrowser[] = [];
  // Follow the *target* platform, not the host running this module: the pure
  // detector is exercised for all three platforms from one test process.
  const pathApi = platform === 'win32' ? path.win32 : path.posix;
  for (const probe of PROBES) {
    if (platform === 'darwin') {
      if (!probe.macApp) {
        continue;
      }
      const appPath = [
        pathApi.join('/Applications', `${probe.macApp}.app`),
        pathApi.join(homeDir, 'Applications', `${probe.macApp}.app`),
      ].find((candidate) => existsSync(candidate));
      if (appPath) {
        detected.push({
          id: probe.id,
          label: probe.label,
          extensionsUrl: probe.extensionsUrl,
          launchTarget: probe.macApp,
          launchKind: 'mac-app',
        });
      }
      continue;
    }
    if (platform === 'win32') {
      const candidate = (probe.windowsPaths ?? [])
        .map(({ root, relative }) => {
          const base = windowsRoot(root, env);
          return base ? pathApi.join(base, ...relative.split('/')) : undefined;
        })
        .find((value): value is string => Boolean(value) && existsSync(value as string));
      if (candidate) {
        detected.push({
          id: probe.id,
          label: probe.label,
          extensionsUrl: probe.extensionsUrl,
          launchTarget: candidate,
          launchKind: 'executable',
        });
      }
      continue;
    }
    // Linux (and other POSIX desktops): PATH is the only portable registry.
    const pathValue = env.PATH ?? '';
    for (const name of probe.linuxNames ?? []) {
      const executable = executableInPath(name, pathValue, existsSync);
      if (executable) {
        detected.push({
          id: probe.id,
          label: probe.label,
          extensionsUrl: probe.extensionsUrl,
          launchTarget: executable,
          launchKind: 'executable',
        });
        break;
      }
    }
  }
  return detected;
}

export function resolveBrowserLaunch(
  browser: ChromiumBrowser,
): { command: string; args: string[] } {
  if (browser.launchKind === 'mac-app') {
    return { command: 'open', args: ['-a', browser.launchTarget, browser.extensionsUrl] };
  }
  return { command: browser.launchTarget, args: [browser.extensionsUrl] };
}

export function openBrowserExtensionsPage(
  browser: ChromiumBrowser,
  {
    spawnFn = spawn,
  }: {
    spawnFn?: typeof spawn;
  } = {},
): { command: string; args: string[]; spawned: boolean } {
  const launch = resolveBrowserLaunch(browser);
  try {
    const child = spawnFn(launch.command, launch.args, { detached: true, stdio: 'ignore' });
    child.unref?.();
    return { ...launch, spawned: true };
  } catch {
    return { ...launch, spawned: false };
  }
}
