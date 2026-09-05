import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createSidecarRuntimeSnapshot } from "./bundle-sidecar.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const SIDECAR_BINARY_MANIFEST_FILE = "trainer-sidecar-manifest.json";
export const SUPPORTED_SIDECAR_TARGETS = [
  "win32-x64",
  "win32-arm64",
  "darwin-x64",
  "darwin-arm64",
  "linux-x64",
  "linux-arm64",
];

export function resolveNativeSidecarTarget({
  platform = process.platform,
  arch = process.arch,
} = {}) {
  const targetPlatform = `${platform}-${arch}`;
  if (!SUPPORTED_SIDECAR_TARGETS.includes(targetPlatform)) {
    throw new Error(
      `Trainer does not support packaging a native sidecar for ${targetPlatform}. Build on a supported target: ${SUPPORTED_SIDECAR_TARGETS.join(", ")}.`,
    );
  }
  return targetPlatform;
}

function fail(message) {
  console.error(message);
  process.exit(1);
}

function ensureExists(targetPath, label) {
  if (!fs.existsSync(targetPath)) {
    fail(`Missing ${label}: ${targetPath}`);
  }
}

export function resolveBinaryBundlePaths({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
  serverDir = path.join(repoRoot, "server"),
  platform = resolveNativeSidecarTarget(),
  env = process.env,
} = {}) {
  const bundleRoot = path.join(extensionDir, "bundled", "bin", platform);
  const buildRoot = resolveSidecarBuildRoot({ extensionDir, env });
  const distRoot = path.join(buildRoot, "dist");
  const specRoot = path.join(buildRoot, "spec");
  const launcherPath = path.join(serverDir, "run_sidecar.py");
  const entryName = platform.startsWith("win32-") ? "trainer-sidecar.exe" : "trainer-sidecar";
  const manifestPath = path.join(bundleRoot, SIDECAR_BINARY_MANIFEST_FILE);

  return {
    extensionDir,
    repoRoot,
    serverDir,
    platform,
    bundleRoot,
    buildRoot,
    distRoot,
    specRoot,
    launcherPath,
    entryName,
    manifestPath,
  };
}

export function resolveSidecarBuildRoot({
  extensionDir = path.resolve(__dirname, ".."),
  env = process.env,
} = {}) {
  const configuredRoot = String(env.TRAINER_SIDECAR_BUILD_ROOT ?? "").trim();
  if (!configuredRoot) {
    return path.join(extensionDir, ".sidecar-build");
  }
  if (!path.isAbsolute(configuredRoot)) {
    throw new Error(
      "TRAINER_SIDECAR_BUILD_ROOT must be an absolute directory. Its dedicated trainer-sidecar-build child is the only directory that will be cleared.",
    );
  }
  return path.join(path.resolve(configuredRoot), "trainer-sidecar-build");
}

export function clearForeignSidecarBinaries({
  extensionDir = path.resolve(__dirname, ".."),
  targetPlatform = resolveNativeSidecarTarget(),
} = {}) {
  const binaryRoot = path.join(extensionDir, "bundled", "bin");
  if (!fs.existsSync(binaryRoot)) {
    return [];
  }

  const removedTargets = fs
    .readdirSync(binaryRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name !== targetPlatform)
    .map((entry) => entry.name)
    .sort((left, right) => left.localeCompare(right));
  for (const target of removedTargets) {
    fs.rmSync(path.join(binaryRoot, target), { recursive: true, force: true });
  }
  return removedTargets;
}

export function resolvePythonBin(serverDir, platform = process.platform) {
  const candidates = platform === "win32"
    ? [
        path.join(serverDir, ".venv", "Scripts", "python.exe"),
        path.join(serverDir, ".venv-mac", "Scripts", "python.exe"),
        path.join(serverDir, ".venv", "bin", "python"),
        path.join(serverDir, ".venv-mac", "bin", "python"),
      ]
    : [
        path.join(serverDir, ".venv-mac", "bin", "python"),
        path.join(serverDir, ".venv", "bin", "python"),
        path.join(serverDir, ".venv", "Scripts", "python.exe"),
        path.join(serverDir, ".venv-mac", "Scripts", "python.exe"),
      ];

  const python = candidates.find((candidate) => fs.existsSync(candidate));
  if (!python) {
    fail("Missing local Python environment for sidecar build. Expected server/.venv or server/.venv-mac.");
  }
  return python;
}

function ensurePyInstaller(serverDir) {
  const pythonBin = resolvePythonBin(serverDir);
  const check = spawnSync(pythonBin, ["-m", "PyInstaller", "--version"], {
    cwd: serverDir,
    stdio: "pipe",
    encoding: "utf8",
  });

  if (check.status === 0) {
    return;
  }

  console.log("PyInstaller is missing from the local Trainer Python environment. Installing it...");
  const install = spawnSync(pythonBin, ["-m", "pip", "install", "pyinstaller>=6.15.0"], {
    cwd: serverDir,
    stdio: "inherit",
  });
  if (install.status !== 0) {
    fail("Could not install PyInstaller for the local Trainer Python environment.");
  }
}

function runPyInstaller(paths) {
  const { serverDir, buildRoot, distRoot, specRoot, launcherPath } = paths;
  const pythonBin = resolvePythonBin(serverDir);
  fs.rmSync(buildRoot, { recursive: true, force: true });
  fs.mkdirSync(buildRoot, { recursive: true });

  const args = [
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name",
    "trainer-sidecar",
    "--distpath",
    distRoot,
    "--workpath",
    path.join(buildRoot, "work"),
    "--specpath",
    specRoot,
    "--hidden-import",
    "uvicorn.logging",
    "--hidden-import",
    "uvicorn.loops.auto",
    "--hidden-import",
    "uvicorn.protocols.http.auto",
    "--hidden-import",
    "uvicorn.protocols.websockets.auto",
    "--hidden-import",
    "uvicorn.lifespan.on",
    "--hidden-import",
    "pydantic.deprecated.decorator",
    "--hidden-import",
    "openai",
    "--hidden-import",
    "openai._client",
    "--hidden-import",
    "openai._base_client",
    "--hidden-import",
    "openai.types",
    launcherPath,
  ];

  const result = spawnSync(pythonBin, args, {
    cwd: serverDir,
    stdio: "inherit",
  });

  if (result.status !== 0) {
    fail("PyInstaller build failed.");
  }
}

function copyBundle(paths) {
  const { distRoot, bundleRoot, entryName } = paths;
  const sourceDir = path.join(distRoot, "trainer-sidecar");
  const sourceExecutable = path.join(sourceDir, entryName);

  ensureExists(sourceDir, "built sidecar directory");
  ensureExists(sourceExecutable, "built sidecar executable");

  fs.rmSync(bundleRoot, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(bundleRoot), { recursive: true });
  fs.cpSync(sourceDir, bundleRoot, { recursive: true });
  copyCondaRuntimeDlls({ serverDir: paths.serverDir, internalDir: path.join(bundleRoot, "_internal") });

  const bundledExecutable = path.join(bundleRoot, entryName);
  if (!paths.platform.startsWith("win32-")) {
    fs.chmodSync(bundledExecutable, 0o755);
  }
}

function copyCondaRuntimeDlls({ serverDir, internalDir }) {
  // Conda-style interpreters keep the DLLs that extension modules
  // (ctypes/_sqlite3/ssl) load at runtime in <base>/Library/bin, which
  // PyInstaller does not scan. Copy the known runtime set if present.
  if (!fs.existsSync(internalDir)) {
    return;
  }
  let baseDir = "";
  try {
    const cfgPath = path.join(serverDir, ".venv", "pyvenv.cfg");
    if (fs.existsSync(cfgPath)) {
      const cfg = fs.readFileSync(cfgPath, "utf8");
      baseDir = (cfg.match(/home\s*=\s*(.+)/) || [])[1]?.trim() || "";
    }
  } catch {
    return;
  }
  if (!baseDir) {
    return;
  }
  const condaBin = path.join(baseDir, "Library", "bin");
  if (!fs.existsSync(condaBin)) {
    return;
  }
  const runtimeDlls = [
    "ffi-8.dll",
    "sqlite3.dll",
    "liblzma.dll",
    "zlib1.dll",
    "libbz2.dll",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "libcrypto-1_1-x64.dll",
    "libssl-1_1-x64.dll",
  ];
  let copied = 0;
  for (const name of runtimeDlls) {
    const from = path.join(condaBin, name);
    if (fs.existsSync(from)) {
      fs.copyFileSync(from, path.join(internalDir, name));
      copied += 1;
    }
  }
  if (copied > 0) {
    console.log(`Copied ${copied} conda runtime DLL(s) into the sidecar bundle.`);
  }
}

export function createSidecarBinaryManifest(paths) {
  const { serverDir, platform, entryName } = paths;
  return {
    manifestVersion: 1,
    platform,
    entryName,
    generatedAt: new Date().toISOString(),
    sourceSnapshot: createSidecarRuntimeSnapshot({ serverDir }),
  };
}

export function writeSidecarBinaryManifest(paths) {
  const manifest = createSidecarBinaryManifest(paths);
  fs.mkdirSync(paths.bundleRoot, { recursive: true });
  fs.writeFileSync(paths.manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return manifest;
}

export function bundleSidecarBinary(options = {}) {
  const paths = resolveBinaryBundlePaths(options);

  ensureExists(paths.serverDir, "server directory");
  resolvePythonBin(paths.serverDir);
  ensureExists(paths.launcherPath, "server sidecar launcher");

  ensurePyInstaller(paths.serverDir);
  runPyInstaller(paths);
  copyBundle(paths);
  const manifest = writeSidecarBinaryManifest(paths);

  return {
    ...paths,
    manifest,
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  const result = bundleSidecarBinary();
  console.log(
    `Bundled Trainer sidecar binary into ${path.relative(result.extensionDir, result.bundleRoot)}`,
  );
}
