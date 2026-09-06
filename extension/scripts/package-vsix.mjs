import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

import { resolveNativeSidecarTarget } from "./bundle-sidecar-binary.mjs";
import { assertPackageVerified } from "./verify-package.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

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

function sanitizeSymlinkEntry(linkPath, { extensionDir, materialized, removed, directories, copiedRealDirectories }) {
  const relativePath = path.relative(extensionDir, linkPath);
  const resolvedTarget = resolveSymlinkTargetPath(linkPath);

  let targetStat;
  try {
    targetStat = fs.statSync(resolvedTarget);
  } catch {
    // Dangling links ship dead bytes and crash both the vsce secret scanner
    // (ENOENT) and the zip step; nothing in the bundle can resolve them.
    fs.rmSync(linkPath, { recursive: true, force: true });
    removed.push(relativePath);
    return;
  }

  if (targetStat.isFile()) {
    // Replace the link with a copy of its target content so the packaged
    // artifact stays self-contained on every extraction platform.
    fs.rmSync(linkPath, { recursive: true, force: true });
    fs.copyFileSync(resolvedTarget, linkPath);
    materialized.push(relativePath);
    return;
  }

  if (targetStat.isDirectory()) {
    fs.rmSync(linkPath, { recursive: true, force: true });
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

export function resolveVsixOutputPath({
  extensionDir = path.resolve(__dirname, ".."),
  packageJson,
  targetPlatform = resolveNativeSidecarTarget(),
  env = process.env,
} = {}) {
  const manifest = packageJson ?? JSON.parse(
    fs.readFileSync(path.join(extensionDir, "package.json"), "utf8"),
  );
  const configuredPath = String(env.TRAINER_VSIX_OUTPUT_PATH ?? "").trim();
  if (!configuredPath) {
    return path.join(extensionDir, `${manifest.name}-${manifest.version}-${targetPlatform}.vsix`);
  }
  if (!path.isAbsolute(configuredPath)) {
    throw new Error(
      "TRAINER_VSIX_OUTPUT_PATH must be an absolute .vsix path so packaged output cannot be written to an ambiguous location.",
    );
  }

  const outputPath = path.resolve(configuredPath);
  if (path.extname(outputPath).toLowerCase() !== ".vsix") {
    throw new Error("TRAINER_VSIX_OUTPUT_PATH must end in .vsix.");
  }
  return outputPath;
}

export function buildVscePackageArgs(
  outputPath,
  targetPlatform = resolveNativeSidecarTarget(),
) {
  return [
    "exec",
    "--yes",
    "--package",
    "@vscode/vsce",
    "--",
    "vsce",
    "package",
    "--target",
    targetPlatform,
    "--ignore-other-target-folders",
    "--out",
    outputPath,
  ];
}

export function extractVsixTargetPlatform(manifestXml) {
  const installationTargetMatch = String(manifestXml).match(
    /<InstallationTarget\b[^>]*\bTargetPlatform="([^"]+)"[^>]*\/?\s*>/i,
  );
  if (installationTargetMatch?.[1]) {
    return installationTargetMatch[1];
  }
  const identityMatch = String(manifestXml).match(
    /<Identity\b[^>]*\bTargetPlatform="([^"]+)"[^>]*\/?\s*>/i,
  );
  return identityMatch?.[1];
}

export function inspectVsixTargetContents({ targetPlatform, manifestXml, entryNames }) {
  const expectedExecutable = targetPlatform.startsWith("win32-")
    ? "trainer-sidecar.exe"
    : "trainer-sidecar";
  const runtimeRoot = `extension/bundled/bin/${targetPlatform}`;
  const expectedEntries = [
    "extension.vsixmanifest",
    `${runtimeRoot}/${expectedExecutable}`,
    `${runtimeRoot}/trainer-sidecar-manifest.json`,
  ];
  const entries = new Set(entryNames);
  const errors = [];
  const declaredTarget = extractVsixTargetPlatform(manifestXml);

  if (declaredTarget !== targetPlatform) {
    errors.push(
      `VSIX declares target ${declaredTarget ?? "none"}, expected ${targetPlatform}.`,
    );
  }
  for (const expectedEntry of expectedEntries) {
    if (!entries.has(expectedEntry)) {
      errors.push(`VSIX is missing required ${targetPlatform} runtime entry: ${expectedEntry}.`);
    }
  }

  const foreignRuntimeEntries = [...entries]
    .filter((entryName) => entryName.startsWith("extension/bundled/bin/"))
    .filter((entryName) => {
      const runtimeTarget = entryName.split("/")[3];
      return runtimeTarget && runtimeTarget !== targetPlatform;
    })
    .sort((left, right) => left.localeCompare(right));
  if (foreignRuntimeEntries.length > 0) {
    errors.push(
      `VSIX includes runtime files for another target: ${foreignRuntimeEntries[0]}.`,
    );
  }

  return {
    targetPlatform,
    declaredTarget,
    expectedEntries,
    foreignRuntimeEntries,
    errors,
  };
}

export function verifyVsixTargetArtifact({ vsixPath, targetPlatform = resolveNativeSidecarTarget() }) {
  if (!fs.existsSync(vsixPath)) {
    return {
      targetPlatform,
      vsixPath,
      declaredTarget: undefined,
      expectedEntries: [],
      foreignRuntimeEntries: [],
      errors: [`VSIX target artifact is missing: ${vsixPath}.`],
    };
  }

  try {
    const archive = fs.readFileSync(vsixPath);
    const entries = readZipEntries(archive);
    const manifestEntry = entries.get("extension.vsixmanifest");
    if (!manifestEntry) {
      return {
        targetPlatform,
        vsixPath,
        declaredTarget: undefined,
        expectedEntries: [],
        foreignRuntimeEntries: [],
        errors: ["VSIX is missing extension.vsixmanifest."],
      };
    }
    return {
      vsixPath,
      ...inspectVsixTargetContents({
        targetPlatform,
        manifestXml: readZipEntry(archive, manifestEntry).toString("utf8"),
        entryNames: [...entries.keys()],
      }),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      targetPlatform,
      vsixPath,
      declaredTarget: undefined,
      expectedEntries: [],
      foreignRuntimeEntries: [],
      errors: [`Could not inspect VSIX target metadata: ${message}`],
    };
  }
}

export function assertVsixTargetArtifact(options = {}) {
  const report = verifyVsixTargetArtifact(options);
  if (report.errors.length > 0) {
    throw new Error(
      [
        `Trainer VSIX target verification failed for ${report.targetPlatform}.`,
        ...report.errors.map((message) => `- ${message}`),
      ].join("\n"),
    );
  }
  return report;
}

function readZipEntries(archive) {
  const endOfCentralDirectory = findEndOfCentralDirectory(archive);
  const entryCount = archive.readUInt16LE(endOfCentralDirectory + 10);
  let offset = archive.readUInt32LE(endOfCentralDirectory + 16);
  const entries = new Map();

  for (let index = 0; index < entryCount; index += 1) {
    assertZipRange(archive, offset, 46, "central directory entry");
    if (archive.readUInt32LE(offset) !== 0x02014b50) {
      throw new Error("VSIX central directory is invalid.");
    }
    const flags = archive.readUInt16LE(offset + 8);
    const compressionMethod = archive.readUInt16LE(offset + 10);
    const compressedSize = archive.readUInt32LE(offset + 20);
    const fileNameLength = archive.readUInt16LE(offset + 28);
    const extraLength = archive.readUInt16LE(offset + 30);
    const commentLength = archive.readUInt16LE(offset + 32);
    const localHeaderOffset = archive.readUInt32LE(offset + 42);
    assertZipRange(archive, offset + 46, fileNameLength, "central directory filename");
    const name = archive.subarray(offset + 46, offset + 46 + fileNameLength).toString("utf8");
    entries.set(name, { flags, compressionMethod, compressedSize, localHeaderOffset });
    offset += 46 + fileNameLength + extraLength + commentLength;
  }

  return entries;
}

function readZipEntry(archive, entry) {
  assertZipRange(archive, entry.localHeaderOffset, 30, "local file header");
  if (archive.readUInt32LE(entry.localHeaderOffset) !== 0x04034b50) {
    throw new Error("VSIX local file header is invalid.");
  }
  if ((entry.flags & 1) !== 0) {
    throw new Error("Encrypted VSIX entries are not supported.");
  }
  const fileNameLength = archive.readUInt16LE(entry.localHeaderOffset + 26);
  const extraLength = archive.readUInt16LE(entry.localHeaderOffset + 28);
  const payloadOffset = entry.localHeaderOffset + 30 + fileNameLength + extraLength;
  assertZipRange(archive, payloadOffset, entry.compressedSize, "VSIX entry data");
  const payload = archive.subarray(payloadOffset, payloadOffset + entry.compressedSize);

  if (entry.compressionMethod === 0) {
    return payload;
  }
  if (entry.compressionMethod === 8) {
    return zlib.inflateRawSync(payload);
  }
  throw new Error(`Unsupported VSIX compression method: ${entry.compressionMethod}.`);
}

function findEndOfCentralDirectory(archive) {
  const minimumOffset = Math.max(0, archive.length - 0xffff - 22);
  for (let offset = archive.length - 22; offset >= minimumOffset; offset -= 1) {
    if (
      archive.readUInt32LE(offset) === 0x06054b50 &&
      offset + 22 + archive.readUInt16LE(offset + 20) === archive.length
    ) {
      return offset;
    }
  }
  throw new Error("VSIX end-of-central-directory record is missing.");
}

function assertZipRange(archive, offset, length, label) {
  if (offset < 0 || length < 0 || offset + length > archive.length) {
    throw new Error(`VSIX ${label} is outside the archive bounds.`);
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

export function packageVsix({
  extensionDir = path.resolve(__dirname, ".."),
  env = process.env,
} = {}) {
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(extensionDir, "package.json"), "utf8"),
  );
  const targetPlatform = resolveNativeSidecarTarget();
  const outputPath = resolveVsixOutputPath({ extensionDir, packageJson, targetPlatform, env });
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const packageReport = assertPackageVerified({ extensionDir, repoRoot: path.resolve(extensionDir, ".."), env });

  const npmExecPath = resolveNpmExecPath();
  const args = buildVscePackageArgs(outputPath, targetPlatform);
  const result = spawnSync(process.execPath, [npmExecPath, ...args], {
    cwd: extensionDir,
    env: { ...env, TRAINER_VSIX_TARGET: targetPlatform },
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(
      [
        `VSIX packaging failed: node ${npmExecPath} ${args.join(" ")}`,
        result.error ? `${result.error.name}: ${result.error.message}` : "",
        (result.stdout ?? "").trim(),
        (result.stderr ?? "").trim(),
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
  if (!fs.existsSync(outputPath)) {
    throw new Error(`VSIX packaging completed without producing ${outputPath}.`);
  }
  const targetArtifact = assertVsixTargetArtifact({ vsixPath: outputPath, targetPlatform });
  writeGitHubOutputs({ outputPath, targetPlatform, env });

  return {
    packageJson,
    outputPath,
    targetPlatform,
    targetArtifact,
  };
}

export function writeGitHubOutputs({ outputPath, targetPlatform, env = process.env }) {
  const githubOutputPath = String(env.GITHUB_OUTPUT ?? "").trim();
  if (!githubOutputPath) {
    return;
  }
  fs.appendFileSync(
    githubOutputPath,
    `vsix_path=${outputPath.replace(/[\r\n]/g, "")}\nvsix_target=${targetPlatform}\n`,
    "utf8",
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  try {
    const result = packageVsix();
    console.log(`Packaged Trainer VSIX at ${result.outputPath}`);
  } catch (error) {
    console.error(`Trainer VSIX packaging failed.\n${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}
