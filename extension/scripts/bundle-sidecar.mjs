import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const SIDECAR_BUNDLE_IGNORED_NAMES = new Set([
  "__pycache__",
  ".pytest_cache",
  ".ruff_cache",
  ".hypothesis",
  ".trainer",
  ".trainer-memory",
  ".tmp-test",
  ".venv",
  ".venv-mac",
  "trainer_sidecar.egg-info",
  ".DS_Store",
]);

function ensureExists(targetPath) {
  if (!fs.existsSync(targetPath)) {
    throw new Error(`Missing required sidecar asset: ${targetPath}`);
  }
}

function resetDirectory(directoryPath) {
  fs.rmSync(directoryPath, { recursive: true, force: true });
  fs.mkdirSync(directoryPath, { recursive: true });
}

export function shouldSkipBundledSidecarPath(itemPath) {
  const name = path.basename(itemPath);
  return name.startsWith("._") || SIDECAR_BUNDLE_IGNORED_NAMES.has(name);
}

export function normalizeSidecarRelativePath(value) {
  return value.replace(/\\/g, "/");
}

export function walkSidecarFiles(rootPath, { skip } = {}) {
  if (!fs.existsSync(rootPath)) {
    return [];
  }
  const files = [];
  const pending = [rootPath];
  while (pending.length > 0) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (skip && skip(entryPath)) {
        continue;
      }
      if (entry.isDirectory()) {
        pending.push(entryPath);
        continue;
      }
      if (entry.isFile()) {
        files.push(entryPath);
      }
    }
  }
  files.sort((left, right) => left.localeCompare(right));
  return files;
}

export function resolveSidecarBundleTargets({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
} = {}) {
  const sourceServerDir = path.join(repoRoot, "server");
  const targetServerDir = path.join(extensionDir, "bundled", "server");
  return {
    extensionDir,
    repoRoot,
    sourceServerDir,
    targetServerDir,
    copyTargets: [
      { source: path.join(sourceServerDir, "app"), target: path.join(targetServerDir, "app") },
      { source: path.join(sourceServerDir, "pyproject.toml"), target: path.join(targetServerDir, "pyproject.toml") },
      { source: path.join(sourceServerDir, "README.md"), target: path.join(targetServerDir, "README.md") },
      { source: path.join(sourceServerDir, "run_sidecar.py"), target: path.join(targetServerDir, "run_sidecar.py") },
    ],
  };
}

export function resolveSidecarRuntimeManifestTargets(serverDir) {
  return [
    path.join(serverDir, "app"),
    path.join(serverDir, "pyproject.toml"),
    path.join(serverDir, "run_sidecar.py"),
  ];
}

export function expandSidecarSnapshotEntries({
  rootDir,
  targets,
  skip = shouldSkipBundledSidecarPath,
} = {}) {
  const entries = [];
  for (const targetPath of targets) {
    ensureExists(targetPath);
    const targetStat = fs.statSync(targetPath);
    if (targetStat.isDirectory()) {
      const files = walkSidecarFiles(targetPath, { skip });
      for (const filePath of files) {
        entries.push({
          absolutePath: filePath,
          relativePath: normalizeSidecarRelativePath(path.relative(rootDir, filePath)),
        });
      }
      continue;
    }
    entries.push({
      absolutePath: targetPath,
      relativePath: normalizeSidecarRelativePath(path.relative(rootDir, targetPath)),
    });
  }
  entries.sort((left, right) => left.relativePath.localeCompare(right.relativePath));
  return entries;
}

export function createSidecarRuntimeSnapshot({ serverDir } = {}) {
  if (!serverDir) {
    throw new Error("createSidecarRuntimeSnapshot requires a serverDir.");
  }

  const entries = expandSidecarSnapshotEntries({
    rootDir: serverDir,
    targets: resolveSidecarRuntimeManifestTargets(serverDir),
  });
  const digest = crypto.createHash("sha256");
  for (const entry of entries) {
    digest.update(entry.relativePath);
    digest.update("\0");
    digest.update(fs.readFileSync(entry.absolutePath));
    digest.update("\0");
  }

  return {
    fileCount: entries.length,
    sha256: digest.digest("hex"),
  };
}

function copyEntry(sourcePath, targetPath) {
  const stat = fs.statSync(sourcePath);
  if (stat.isDirectory()) {
    fs.cpSync(sourcePath, targetPath, {
      recursive: true,
      filter: (item) => !shouldSkipBundledSidecarPath(item),
    });
    return;
  }

  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.copyFileSync(sourcePath, targetPath);
}

export function bundleSidecar({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
} = {}) {
  const {
    sourceServerDir,
    targetServerDir,
    copyTargets,
  } = resolveSidecarBundleTargets({ extensionDir, repoRoot });

  for (const { source } of copyTargets) {
    ensureExists(source);
  }

  resetDirectory(targetServerDir);

  for (const target of copyTargets) {
    copyEntry(target.source, target.target);
  }

  return {
    extensionDir,
    repoRoot,
    sourceServerDir,
    targetServerDir,
    copyTargets,
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  const result = bundleSidecar();
  console.log(
    `Bundled Trainer sidecar into ${path.relative(result.extensionDir, result.targetServerDir)}`,
  );
}
