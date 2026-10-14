import { spawn } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import type { ComposerLanguage } from '../../../shared/src/types';
import { BROWSER_CAPTURE } from '../core/constants';
import { browserCaptureHostCopy } from './hostCopy';

/**
 * Filesystem + platform helpers behind `trainer.browserCapture.install`.
 *
 * Kept free of the `vscode` module so the copy/open behaviour is unit-testable
 * without an extension host. The command layer owns every user-visible step
 * (information bars, clipboard, error surfacing).
 */

export interface CaptureBundleMarker {
  schemaVersion: number;
  name?: string;
  version?: string;
  fileCount?: number;
}

const BUNDLE_JUNK_PATTERNS = [/^\.DS_Store$/, /^\._/, /\.map$/, /\.zip$/, /\.tmp$/, /~$/];

export function resolveInstalledCaptureDir(homeDir: string): string {
  return path.join(homeDir, BROWSER_CAPTURE.installedRelativeDir);
}

/**
 * Managed install location. `TRAINER_BROWSER_CAPTURE_INSTALL_DIR` (absolute)
 * redirects it so automated runs — VSIX end-to-end harnesses, unit tests —
 * never touch the developer's real `~/.trainer/browser-capture`.
 */
export function resolveCaptureInstallDir({
  homeDir = os.homedir(),
  env = process.env,
}: {
  homeDir?: string;
  env?: NodeJS.ProcessEnv;
} = {}): string {
  const configured = String(env.TRAINER_BROWSER_CAPTURE_INSTALL_DIR ?? '').trim();
  if (!configured) {
    return resolveInstalledCaptureDir(homeDir);
  }
  if (!path.isAbsolute(configured)) {
    throw new Error(
      'TRAINER_BROWSER_CAPTURE_INSTALL_DIR must be an absolute directory so the capture install cannot land in an ambiguous location.',
    );
  }
  return path.resolve(configured);
}

function isBundleJunk(name: string): boolean {
  return BUNDLE_JUNK_PATTERNS.some((pattern) => pattern.test(name));
}

/** Relative file paths of one capture bundle tree, junk and stray archives excluded. */
export function collectCaptureBundleFiles(rootDir: string, prefix = ''): string[] {
  if (!fs.existsSync(rootDir)) {
    return [];
  }
  const files: string[] = [];
  for (const name of fs.readdirSync(rootDir).sort()) {
    if (isBundleJunk(name)) {
      continue;
    }
    const absolute = path.join(rootDir, name);
    const relative = prefix ? `${prefix}/${name}` : name;
    const stats = fs.statSync(absolute);
    if (stats.isDirectory()) {
      files.push(...collectCaptureBundleFiles(absolute, relative));
    } else if (stats.isFile()) {
      files.push(relative);
    }
  }
  return files;
}

export function readCaptureBundleMarker(bundleDir: string): CaptureBundleMarker | undefined {
  const markerPath = path.join(bundleDir, BROWSER_CAPTURE.versionFileName);
  try {
    const parsed: unknown = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return undefined;
    }
    const record = parsed as Record<string, unknown>;
    return {
      schemaVersion: Number(record.schemaVersion ?? 0),
      name: typeof record.name === 'string' ? record.name : undefined,
      version: typeof record.version === 'string' ? record.version : undefined,
      fileCount: typeof record.fileCount === 'number' ? record.fileCount : undefined,
    };
  } catch {
    return undefined;
  }
}

export class CaptureBundleSourceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CaptureBundleSourceError';
  }
}

/**
 * Overwrite the managed install directory with the bundle that shipped inside
 * the VSIX: every bundled file is (re)written, and files that belonged to an
 * older version are pruned so a stale manifest cannot resurrect a removed
 * script. The directory itself is reused, so a browser that already loaded it
 * can simply be reloaded.
 */
export function installCaptureBundle({
  sourceDir,
  targetDir,
}: {
  sourceDir: string;
  targetDir: string;
}): { targetDir: string; fileCount: number; version?: string } {
  const manifestRelative = 'manifest.json';
  if (!fs.existsSync(path.join(sourceDir, manifestRelative))) {
    throw new CaptureBundleSourceError(
      `Trainer Capture bundle is missing ${manifestRelative} in ${sourceDir}.`,
    );
  }

  const bundleFiles = collectCaptureBundleFiles(sourceDir);
  fs.mkdirSync(targetDir, { recursive: true });

  const copied = new Set<string>();
  for (const relative of bundleFiles) {
    const from = path.join(sourceDir, relative);
    const to = path.join(targetDir, relative);
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.copyFileSync(from, to);
    copied.add(relative);
  }

  for (const relative of collectCaptureBundleFiles(targetDir)) {
    if (!copied.has(relative)) {
      fs.rmSync(path.join(targetDir, relative), { force: true });
    }
  }

  const marker = readCaptureBundleMarker(sourceDir);
  return {
    targetDir,
    fileCount: copied.size,
    version: marker?.version,
  };
}

/** Platform command that opens a directory in the OS file manager. */
export function resolveOpenFolderCommand(
  targetDir: string,
  platform: string = process.platform,
): { command: string; args: string[] } {
  if (platform === 'darwin') {
    return { command: 'open', args: [targetDir] };
  }
  if (platform === 'win32') {
    return { command: 'explorer', args: [targetDir] };
  }
  return { command: 'xdg-open', args: [targetDir] };
}

/**
 * Open the folder best-effort: the caller always gets the directory path back
 * in the information bar, so a headless Linux host without xdg-open degrades
 * to "select this path manually" instead of failing the install.
 */
export function openCaptureFolder(
  targetDir: string,
  {
    platform = process.platform,
    spawnFn = spawn,
  }: {
    platform?: string;
    spawnFn?: typeof spawn;
  } = {},
): { command: string; args: string[]; spawned: boolean } {
  const { command, args } = resolveOpenFolderCommand(targetDir, platform);
  try {
    const child = spawnFn(command, args, { detached: true, stdio: 'ignore' });
    child.unref?.();
    return { command, args, spawned: true };
  } catch {
    return { command, args, spawned: false };
  }
}

/**
 * The three-step "Load unpacked" guide shown on the install information bar,
 * localized through the browser-capture host copy table (en-US by default).
 */
export function captureInstallGuide(steps: {
  targetDir: string;
  version?: string;
  language?: ComposerLanguage;
}): string {
  const label = steps.version ? `Trainer Capture ${steps.version}` : 'Trainer Capture';
  const language = steps.language ?? 'en-US';
  return [
    browserCaptureHostCopy(language, 'installReady', { label }),
    browserCaptureHostCopy(language, 'installStepExtensions'),
    browserCaptureHostCopy(language, 'installStepDeveloperMode'),
    browserCaptureHostCopy(language, 'installStepLoadUnpacked', { dir: steps.targetDir }),
  ].join('\n');
}
