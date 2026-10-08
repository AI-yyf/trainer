import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Trees that vsce packages into the VSIX. Symbolic links inside them are
// materialized or removed before packaging because the vsce secret scanner
// (@secretlint/node) reads every packaged file with fs.readFile, which throws
// on symlinked directories (EISDIR) and dangling links (ENOENT) and aborts
// `vsce package` with an opaque "Error occurred while scanning secrets"
// failure. The PyInstaller onedir bundle produced for macOS and Linux
// contains preserved dylib symlinks, so this must run before every
// target-specific VSIX build.
const PACKAGED_SYMLINK_SANITIZATION_TREES = ["bundled", "dist", "media", path.join("webview", "dist")];

export function sanitizePackagedSymlinks({
  extensionDir = path.resolve(__dirname, ".."),
  packagedTrees = PACKAGED_SYMLINK_SANITIZATION_TREES,
  log = console.log,
} = {}) {
  const materialized = [];
  const removed = [];
  const directories = [];
  // Real directories already copied while materializing symlinked
  // directories. Bounds the copy so cyclic or ancestor-pointing links cannot
  // recurse without end (fs.cpSync would follow junction loops on Windows).
  const copiedRealDirectories = new Set();

  for (const tree of packagedTrees) {
    const treeRoot = path.join(extensionDir, tree);
    if (!fs.existsSync(treeRoot)) {
      continue;
    }
    const pendingDirectories = [treeRoot];
    while (pendingDirectories.length > 0) {
      const currentDirectory = pendingDirectories.pop();
      for (const entry of fs.readdirSync(currentDirectory, { withFileTypes: true })) {
        const entryPath = path.join(currentDirectory, entry.name);
        if (entry.isSymbolicLink()) {
          sanitizeSymlinkEntry(entryPath, {
            extensionDir,
            materialized,
            removed,
            directories,
            copiedRealDirectories,
          });
          continue;
        }
        if (entry.isDirectory()) {
          pendingDirectories.push(entryPath);
        }
      }
    }
  }

  if (materialized.length > 0 || removed.length > 0 || directories.length > 0) {
    const details = [
      ...materialized.map((relativePath) => `- materialized regular file copy: ${relativePath}`),
      ...directories.map((relativePath) => `- materialized directory copy: ${relativePath}`),
      ...removed.map((relativePath) => `- removed dangling link: ${relativePath}`),
    ];
    log(
      [
        "Sanitized packaged trees for the vsce secret scanner (symlinks cannot be scanned):",
        ...details,
      ].join("\n"),
    );
  }

  return { materialized, removed, directories };
}

function resolveSymlinkTargetPath(linkPath) {
  const rawTarget = fs.readlinkSync(linkPath);
  // Windows junctions read back with an extended-length prefix
  // (\\?\C:\...); strip it so plain fs operations resolve the target.
  const normalizedTarget = rawTarget.startsWith("\\\\?\\") ? rawTarget.slice(4) : rawTarget;
  return path.resolve(path.dirname(linkPath), normalizedTarget);
}

// fs.rmSync(..., { recursive: true, force: true }) silently leaves a dangling
// symlink in place: its internal stat follows the link, force: true swallows
// the ENOENT as "already gone", and the link itself survives on macOS/Linux.
// A symlink (or Windows junction) is never a real directory, so it must be
// unlinked directly.
function removeSymlink(linkPath) {
  try {
    fs.unlinkSync(linkPath);
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }
}

function sanitizeSymlinkEntry(linkPath, { extensionDir, materialized, removed, directories, copiedRealDirectories }) {
  const relativePath = path.relative(extensionDir, linkPath);
  const resolvedTarget = resolveSymlinkTargetPath(linkPath);

  let targetStat;
  try {
    targetStat = fs.statSync(resolvedTarget);
  } catch {
    // Dangling links ship dead bytes and crash both the vsce secret scanner
    // (ENOENT) and the zip step; nothing in the bundle can resolve them.
    removeSymlink(linkPath);
    removed.push(relativePath);
    return;
  }

  if (targetStat.isFile()) {
    // Replace the link with a copy of its target content so the packaged
    // artifact stays self-contained on every extraction platform.
    removeSymlink(linkPath);
    fs.copyFileSync(resolvedTarget, linkPath);
    materialized.push(relativePath);
    return;
  }

  if (targetStat.isDirectory()) {
    removeSymlink(linkPath);
    materializeDirectoryCopy(resolvedTarget, linkPath, copiedRealDirectories);
    directories.push(relativePath);
    return;
  }

  throw new Error(
    `Packaged tree contains a symlink pointing at an unsupported target: ${linkPath} -> ${resolvedTarget}`,
  );
}

function containsPath(parentPath, candidatePath) {
  const relative = path.relative(parentPath, candidatePath);
  return Boolean(relative) && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function materializeDirectoryCopy(sourcePath, destinationPath, copiedRealDirectories) {
  const realSourcePath = fs.realpathSync(sourcePath);
  if (copiedRealDirectories.has(realSourcePath)) {
    return;
  }
  // Materializing must never write a tree into itself: a nested link can
  // point at one of the copy's own ancestors even when the top-level link
  // was benign. Such a link is broken by construction in a shipped bundle,
  // so fail loudly instead of recursing without end.
  const realDestinationDirectory = fs.realpathSync(path.dirname(destinationPath));
  if (
    realSourcePath === realDestinationDirectory ||
    containsPath(realSourcePath, realDestinationDirectory)
  ) {
    throw new Error(
      `Refusing to materialize a self-referential symlinked directory: ${destinationPath} -> ${sourcePath}`,
    );
  }
  copiedRealDirectories.add(realSourcePath);
  fs.mkdirSync(destinationPath, { recursive: true });
  for (const entry of fs.readdirSync(sourcePath, { withFileTypes: true })) {
    const entrySource = path.join(sourcePath, entry.name);
    const entryDestination = path.join(destinationPath, entry.name);
    if (entry.isSymbolicLink()) {
      const entryTarget = resolveSymlinkTargetPath(entrySource);
      let entryStat;
      try {
        entryStat = fs.statSync(entryTarget);
      } catch {
        continue; // drop dangling links inside the copied subtree
      }
      if (entryStat.isFile()) {
        fs.copyFileSync(entryTarget, entryDestination);
      } else if (entryStat.isDirectory()) {
        materializeDirectoryCopy(entryTarget, entryDestination, copiedRealDirectories);
      }
      continue;
    }
    if (entry.isDirectory()) {
      materializeDirectoryCopy(entrySource, entryDestination, copiedRealDirectories);
      continue;
    }
    if (entry.isFile()) {
      fs.copyFileSync(entrySource, entryDestination);
    }
  }
}

export function resolveNpmExecPath() {
  const npmExecPath = process.env.npm_execpath;
  if (npmExecPath && fs.existsSync(npmExecPath)) {
    return npmExecPath;
  }

  const candidate = process.platform === "win32"
    ? path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js")
    : path.join(
      path.dirname(path.dirname(process.execPath)),
      "lib",
      "node_modules",
      "npm",
      "bin",
      "npm-cli.js",
    );
  if (fs.existsSync(candidate)) {
    return candidate;
  }
  throw new Error(
    "Could not resolve npm_execpath for VSIX packaging. Run this script from an npm context or provide a standard npm installation.",
  );
}
