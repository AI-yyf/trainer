/**
 * Resolve the VS Code / Electron executable used by the real-GUI journeys.
 *
 * VS Code renamed the macOS app binary from `Electron` to `Code` in the 1.10x
 * line. The journey scripts used to hardcode `MacOS/Electron`, so on a current
 * install they failed with "Run npm run package:vsix first" even though the
 * VSIX existed. Resolution order:
 *
 *   1. `TRAINER_VSCODE_ELECTRON` (explicit override)
 *   2. the platform's conventional install locations, current and legacy names
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const DARWIN_APP = "/Applications/Visual Studio Code.app/Contents/MacOS";
const DARWIN_BINARIES = ["Electron", "Code"];

function darwinCandidates(home) {
  const roots = [DARWIN_APP, path.join(home, "Applications/Visual Studio Code.app/Contents/MacOS")];
  return roots.flatMap((root) => DARWIN_BINARIES.map((name) => path.join(root, name)));
}

function windowsCandidates(env) {
  const localAppData = String(env.LOCALAPPDATA ?? "").trim();
  const roots = [
    localAppData ? `${localAppData}\\Programs\\Microsoft VS Code` : "",
    "C:\\Program Files\\Microsoft VS Code",
  ].filter(Boolean);
  return roots.map((root) => `${root}\\Code.exe`);
}

const LINUX_BINARIES = ["/usr/share/code/code", "/usr/bin/code", "/snap/bin/code"];

export function vscodeElectronCandidates({
  platform = process.platform,
  env = process.env,
  home = os.homedir(),
} = {}) {
  const override = String(env.TRAINER_VSCODE_ELECTRON ?? "").trim();
  const platformCandidates =
    platform === "darwin"
      ? darwinCandidates(home)
      : platform === "win32"
        ? windowsCandidates(env)
        : LINUX_BINARIES;
  return override ? [override, ...platformCandidates] : platformCandidates;
}

export function resolveVSCodeElectronBinary({
  platform = process.platform,
  env = process.env,
  home = os.homedir(),
  exists = fs.existsSync,
} = {}) {
  const candidates = vscodeElectronCandidates({ platform, env, home });
  return candidates.find((candidate) => candidate && exists(candidate)) ?? null;
}

export function requireVSCodeElectronBinary(options = {}) {
  const binary = resolveVSCodeElectronBinary(options);
  if (!binary) {
    throw new Error(
      "VS Code executable not found. Install Visual Studio Code or set " +
        "TRAINER_VSCODE_ELECTRON to its binary path.",
    );
  }
  return binary;
}
