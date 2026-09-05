import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  createSidecarRuntimeSnapshot,
  normalizeSidecarRelativePath,
  resolveSidecarBundleTargets,
  shouldSkipBundledSidecarPath,
  walkSidecarFiles,
} from "./bundle-sidecar.mjs";
import {
  SIDECAR_BINARY_MANIFEST_FILE,
  resolveNativeSidecarTarget,
} from "./bundle-sidecar-binary.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const EXPECTED_SIDECAR_BINARY_TARGETS = ["win32-x64", "darwin-arm64", "darwin-x64", "linux-x64"];

export function resolveBundledBinaryCandidates(
  extensionDir,
  targetPlatform = resolveNativeSidecarTarget(),
) {
  const executableName =
    targetPlatform.startsWith("win32-") ? "trainer-sidecar.exe" : "trainer-sidecar";
  const bundledBinaryDir = path.join(
    extensionDir,
    "bundled",
    "bin",
    targetPlatform,
  );
  return {
    bundledBinaryDir,
    candidates: [
      path.join(bundledBinaryDir, executableName),
      path.join(bundledBinaryDir, "trainer-sidecar", executableName),
    ],
  };
}

function collectBundledMetadataJunk(rootPath) {
  return walkSidecarFiles(rootPath, { skip: () => false })
    .filter((entryPath) => shouldSkipBundledSidecarPath(entryPath))
    .map((entryPath) => normalizeSidecarRelativePath(path.relative(rootPath, entryPath)));
}

function expandSidecarBundleEntries({ copyTargets, targetServerDir }) {
  const entries = [];
  for (const target of copyTargets) {
    const sourceStat = fs.statSync(target.source);
    if (sourceStat.isDirectory()) {
      const sourceFiles = walkSidecarFiles(target.source, {
        skip: shouldSkipBundledSidecarPath,
      });
      for (const sourceFile of sourceFiles) {
        const relativeFromSource = path.relative(target.source, sourceFile);
        const bundledTarget = path.join(target.target, relativeFromSource);
        entries.push({
          bundledRelativePath: normalizeSidecarRelativePath(
            path.relative(targetServerDir, bundledTarget),
          ),
          sourcePath: sourceFile,
          bundledPath: bundledTarget,
        });
      }
      continue;
    }
    entries.push({
      bundledRelativePath: normalizeSidecarRelativePath(
        path.relative(targetServerDir, target.target),
      ),
      sourcePath: target.source,
      bundledPath: target.target,
    });
  }
  entries.sort((left, right) =>
    left.bundledRelativePath.localeCompare(right.bundledRelativePath),
  );
  return entries;
}

export function verifySidecarBundleParity({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
} = {}) {
  const bundleTargets = resolveSidecarBundleTargets({ extensionDir, repoRoot });
  const expectedEntries = expandSidecarBundleEntries(bundleTargets);
  const expectedRelativePaths = new Set(
    expectedEntries.map((entry) => entry.bundledRelativePath),
  );
  const actualBundledFiles = walkSidecarFiles(bundleTargets.targetServerDir, {
    skip: shouldSkipBundledSidecarPath,
  }).map((entryPath) =>
    normalizeSidecarRelativePath(path.relative(bundleTargets.targetServerDir, entryPath)),
  );

  const missingBundledFiles = expectedEntries
    .filter((entry) => !fs.existsSync(entry.bundledPath))
    .map((entry) => entry.bundledRelativePath);

  const unexpectedBundledFiles = actualBundledFiles.filter(
    (relativePath) => !expectedRelativePaths.has(relativePath),
  );

  const contentMismatches = expectedEntries
    .filter((entry) => fs.existsSync(entry.bundledPath))
    .filter((entry) => {
      const sourceBytes = fs.readFileSync(entry.sourcePath);
      const bundledBytes = fs.readFileSync(entry.bundledPath);
      return !sourceBytes.equals(bundledBytes);
    })
    .map((entry) => entry.bundledRelativePath);

  return {
    sourceServerDir: bundleTargets.sourceServerDir,
    targetServerDir: bundleTargets.targetServerDir,
    checkedFileCount: expectedEntries.length,
    missingBundledFiles,
    unexpectedBundledFiles,
    contentMismatches,
  };
}

function snapshotsMatch(expectedSnapshot, actualSnapshot) {
  return (
    Boolean(actualSnapshot) &&
    expectedSnapshot.fileCount === actualSnapshot.fileCount &&
    expectedSnapshot.sha256 === actualSnapshot.sha256
  );
}

function normalizeSnapshot(value) {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const fileCount = Number(value.fileCount);
  const sha256 = typeof value.sha256 === "string" ? value.sha256.trim() : "";
  if (!Number.isInteger(fileCount) || fileCount < 0 || !/^[a-f0-9]{64}$/i.test(sha256)) {
    return undefined;
  }
  return {
    fileCount,
    sha256,
  };
}

export function verifyBundledBinaryManifest({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
  serverDir = path.join(repoRoot, "server"),
  targetPlatform = `${process.platform}-${process.arch}`,
} = {}) {
  const binaryPaths = resolveBundledBinaryTargetPaths({ extensionDir, targetPlatform, serverDir });
  const manifestRelativePath = normalizeSidecarRelativePath(
    path.relative(extensionDir, binaryPaths.manifestPath),
  );
  const reportBase = {
    targetPlatform: binaryPaths.targetPlatform,
    executableCandidates: binaryPaths.executableCandidates,
  };
  const errors = [];
  let expectedSourceSnapshot;

  if (!fs.existsSync(binaryPaths.serverDir)) {
    errors.push(
      `Expected sidecar source directory missing for binary verification: ${normalizeSidecarRelativePath(path.relative(extensionDir, binaryPaths.serverDir))}`,
    );
    return {
      ...reportBase,
      manifestPath: binaryPaths.manifestPath,
      manifestRelativePath,
      exists: fs.existsSync(binaryPaths.manifestPath),
      expectedSourceSnapshot: undefined,
      actualSourceSnapshot: undefined,
      manifest: undefined,
      errors,
    };
  }

  try {
    expectedSourceSnapshot = createSidecarRuntimeSnapshot({
      serverDir: binaryPaths.serverDir,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    errors.push(
      `Expected sidecar source snapshot could not be computed: ${normalizeSidecarRelativePath(path.relative(extensionDir, binaryPaths.serverDir))} (${message})`,
    );
    return {
      ...reportBase,
      manifestPath: binaryPaths.manifestPath,
      manifestRelativePath,
      exists: fs.existsSync(binaryPaths.manifestPath),
      expectedSourceSnapshot: undefined,
      actualSourceSnapshot: undefined,
      manifest: undefined,
      errors,
    };
  }

  if (!fs.existsSync(binaryPaths.manifestPath)) {
    errors.push(`Bundled sidecar binary manifest missing: ${manifestRelativePath}`);
    return {
      ...reportBase,
      manifestPath: binaryPaths.manifestPath,
      manifestRelativePath,
      exists: false,
      expectedSourceSnapshot,
      actualSourceSnapshot: undefined,
      manifest: undefined,
      errors,
    };
  }

  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(binaryPaths.manifestPath, "utf8"));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    errors.push(
      `Bundled sidecar binary manifest is invalid JSON: ${manifestRelativePath} (${message})`,
    );
    return {
      ...reportBase,
      manifestPath: binaryPaths.manifestPath,
      manifestRelativePath,
      exists: true,
      expectedSourceSnapshot,
      actualSourceSnapshot: undefined,
      manifest: undefined,
      errors,
    };
  }

  const actualSourceSnapshot = normalizeSnapshot(manifest?.sourceSnapshot);
  if (manifest?.manifestVersion !== 1) {
    errors.push(
      `Bundled sidecar binary manifest has unsupported version: ${manifestRelativePath}`,
    );
  }
  if (manifest?.platform !== binaryPaths.targetPlatform) {
    errors.push(
      `Bundled sidecar binary manifest targets ${String(manifest?.platform ?? "") || "unknown"}, expected ${binaryPaths.targetPlatform}: ${manifestRelativePath}`,
    );
  }
  if (manifest?.entryName !== binaryPaths.entryName) {
    errors.push(
      `Bundled sidecar binary manifest entry mismatch: ${manifestRelativePath}`,
    );
  }
  if (!actualSourceSnapshot) {
    errors.push(
      `Bundled sidecar binary manifest is missing a valid source snapshot: ${manifestRelativePath}`,
    );
  } else if (!snapshotsMatch(expectedSourceSnapshot, actualSourceSnapshot)) {
    errors.push(
      `Bundled sidecar binary drift detected: ${manifestRelativePath} (${actualSourceSnapshot.sha256} != ${expectedSourceSnapshot.sha256})`,
    );
  }

  return {
    ...reportBase,
    manifestPath: binaryPaths.manifestPath,
    manifestRelativePath,
    exists: true,
    expectedSourceSnapshot,
    actualSourceSnapshot,
    manifest,
    errors,
  };
}

function resolveBundledBinaryTargetPaths({ extensionDir, targetPlatform, serverDir }) {
  const entryName = targetPlatform.startsWith("win32-")
    ? "trainer-sidecar.exe"
    : "trainer-sidecar";
  const bundleRoot = path.join(extensionDir, "bundled", "bin", targetPlatform);
  return {
    targetPlatform,
    serverDir,
    entryName,
    bundleRoot,
    manifestPath: path.join(bundleRoot, SIDECAR_BINARY_MANIFEST_FILE),
    executableCandidates: [
      path.join(bundleRoot, entryName),
      path.join(bundleRoot, "trainer-sidecar", entryName),
    ],
  };
}

function listBundledBinaryTargets(extensionDir) {
  const binaryRoot = path.join(extensionDir, "bundled", "bin");
  if (!fs.existsSync(binaryRoot)) {
    return [];
  }
  return fs
    .readdirSync(binaryRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort((left, right) => left.localeCompare(right));
}

export function verifyBundledBinaryTargets({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
  serverDir = path.join(repoRoot, "server"),
} = {}) {
  const targets = listBundledBinaryTargets(extensionDir);
  const reports = targets.map((targetPlatform) => {
    const report = verifyBundledBinaryManifest({
      extensionDir,
      repoRoot,
      serverDir,
      targetPlatform,
    });
    const executablePath = report.executableCandidates.find((candidate) => fs.existsSync(candidate));
    if (!executablePath) {
      report.errors.push(
        `Bundled sidecar binary executable missing: ${normalizeSidecarRelativePath(path.relative(extensionDir, report.executableCandidates[0]))}`,
      );
    }
    return {
      ...report,
      executablePath,
    };
  });
  const presentTargets = new Set(targets);
  const missingExpectedTargets = EXPECTED_SIDECAR_BINARY_TARGETS.filter(
    (targetPlatform) => !presentTargets.has(targetPlatform),
  );
  const invalidTargets = reports.filter((report) => report.errors.length > 0).map((report) => report.targetPlatform);
  return {
    expectedTargets: [...EXPECTED_SIDECAR_BINARY_TARGETS],
    reports,
    missingExpectedTargets,
    invalidTargets,
    complete: missingExpectedTargets.length === 0 && invalidTargets.length === 0,
  };
}

export function verifyWebviewDist({
  webviewDistDir,
} = {}) {
  const requiredEntries = ["index.html", "vscode-preview.html"];
  const missingEntries = requiredEntries.filter((entry) => !fs.existsSync(path.join(webviewDistDir, entry)));
  const missingAssets = [];
  const invalidReferences = [];
  const references = [];
  for (const entry of requiredEntries) {
    const entryPath = path.join(webviewDistDir, entry);
    if (!fs.existsSync(entryPath)) continue;
    const html = fs.readFileSync(entryPath, "utf8");
    for (const match of html.matchAll(/(?:src|href)=["']([^"']+)["']/gi)) {
      const reference = match[1];
      if (/^(?:[a-z]+:|\/\/|data:|#)/i.test(reference)) continue;
      const cleanReference = reference.split(/[?#]/, 1)[0];
      const resolved = path.resolve(path.dirname(entryPath), cleanReference);
      if (resolved !== webviewDistDir && !resolved.startsWith(`${path.resolve(webviewDistDir)}${path.sep}`)) {
        invalidReferences.push({ entry, reference });
        continue;
      }
      references.push({ entry, reference });
      if (!fs.existsSync(resolved)) missingAssets.push({ entry, reference });
    }
  }
  return {
    requiredEntries,
    missingEntries,
    missingAssets,
    invalidReferences,
    references,
    ok: missingEntries.length === 0 && missingAssets.length === 0 && invalidReferences.length === 0,
  };
}

export function verifyPackage({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
  targetPlatform,
  env = process.env,
} = {}) {
  const { targetServerDir } = resolveSidecarBundleTargets({ extensionDir, repoRoot });
  const nativeTarget = resolveNativeSidecarTarget();
  const packageTarget = resolvePackageTarget({ targetPlatform, env, nativeTarget });
  const { bundledBinaryDir, candidates: bundledBinaryCandidates } =
    resolveBundledBinaryCandidates(extensionDir, packageTarget);
  const bundledBinaryPath = bundledBinaryCandidates.find((candidate) =>
    fs.existsSync(candidate),
  );
  const requiredPaths = [
    {
      label: "extension entrypoint",
      path: path.join(extensionDir, "dist", "extension", "src", "extension.js"),
    },
    {
      label: "webview bundle html",
      path: path.join(extensionDir, "webview", "dist", "index.html"),
    },
    {
      label: "bundled sidecar source",
      path: path.join(targetServerDir, "run_sidecar.py"),
    },
    {
      label: "bundled sidecar binary directory",
      path: bundledBinaryDir,
    },
    {
      label: "bundled sidecar executable",
      path:
        bundledBinaryPath ??
        bundledBinaryCandidates[0],
    },
  ];

  const missingRequiredPaths = requiredPaths
    .filter((item) => !fs.existsSync(item.path))
    .map((item) => ({
      label: item.label,
      relativePath: normalizeSidecarRelativePath(path.relative(extensionDir, item.path)),
    }));

  const webviewDist = verifyWebviewDist({
    webviewDistDir: path.join(extensionDir, "webview", "dist"),
  });
  const sidecarParity = verifySidecarBundleParity({ extensionDir, repoRoot });
  const binaryManifest = verifyBundledBinaryManifest({
    extensionDir,
    repoRoot,
    targetPlatform: packageTarget,
  });
  const binaryTargetCoverage = verifyBundledBinaryTargets({ extensionDir, repoRoot });
  const metadataJunk = [
    ...collectBundledMetadataJunk(targetServerDir).map((relativePath) => ({
      scope: "bundled/server",
      relativePath,
    })),
    ...collectBundledMetadataJunk(bundledBinaryDir).map((relativePath) => ({
      scope: `bundled/bin/${packageTarget}`,
      relativePath,
    })),
  ];

  const ok =
    missingRequiredPaths.length === 0 &&
    webviewDist.ok &&
    metadataJunk.length === 0 &&
    sidecarParity.missingBundledFiles.length === 0 &&
    sidecarParity.unexpectedBundledFiles.length === 0 &&
    sidecarParity.contentMismatches.length === 0 &&
    binaryManifest.errors.length === 0;

  return {
    ok,
    extensionDir,
    repoRoot,
    missingRequiredPaths,
    webviewDist,
    metadataJunk,
    sidecarParity,
    binaryManifest,
    nativeTarget,
    targetPlatform: packageTarget,
    binaryTargetCoverage,
  };
}

export function resolvePackageTarget({
  targetPlatform,
  env = process.env,
  nativeTarget = resolveNativeSidecarTarget(),
} = {}) {
  const configuredTarget = String(env.TRAINER_VSIX_TARGET ?? "").trim();
  const requestedTarget = (targetPlatform ?? configuredTarget) || nativeTarget;
  if (requestedTarget !== nativeTarget) {
    throw new Error(
      `Trainer packages a native sidecar for ${nativeTarget}; refusing to label it as ${requestedTarget}. Build the VSIX on its target platform instead.`,
    );
  }
  return nativeTarget;
}

export function formatPackageVerificationErrors(report) {
  const lines = [];
  for (const item of report.missingRequiredPaths) {
    lines.push(`- Missing ${item.label}: ${item.relativePath}`);
  }
  for (const entry of report.webviewDist?.missingEntries ?? []) {
    lines.push(`- Missing webview entry: webview/dist/${entry}`);
  }
  for (const item of report.webviewDist?.missingAssets ?? []) {
    lines.push(`- Missing webview asset referenced by ${item.entry}: ${item.reference}`);
  }
  for (const item of report.webviewDist?.invalidReferences ?? []) {
    lines.push(`- Invalid webview asset reference in ${item.entry}: ${item.reference}`);
  }
  for (const item of report.metadataJunk) {
    lines.push(`- Metadata junk in ${item.scope}: ${item.relativePath}`);
  }
  for (const relativePath of report.sidecarParity.missingBundledFiles) {
    lines.push(`- Bundled sidecar file missing: bundled/server/${relativePath}`);
  }
  for (const relativePath of report.sidecarParity.unexpectedBundledFiles) {
    lines.push(`- Unexpected bundled sidecar file: bundled/server/${relativePath}`);
  }
  for (const relativePath of report.sidecarParity.contentMismatches) {
    lines.push(`- Bundled sidecar drift detected: bundled/server/${relativePath}`);
  }
  for (const message of report.binaryManifest.errors) {
    lines.push(`- ${message}`);
  }
  return lines;
}

export function assertPackageVerified(options = {}) {
  const report = verifyPackage(options);
  if (!report.ok) {
    const detail = formatPackageVerificationErrors(report).join("\n");
    throw new Error(`Trainer package verification failed.\n${detail}`);
  }
  return report;
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  const report = assertPackageVerified();
  console.log(
    `Trainer package verification passed for ${report.targetPlatform}. Checked ${report.sidecarParity.checkedFileCount} bundled sidecar files and ${SIDECAR_BINARY_MANIFEST_FILE}.`,
  );
}
