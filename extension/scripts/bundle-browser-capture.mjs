import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { readZipEntries } from "./vsix-archive.mjs";

/**
 * Stage the browser capture extension (repo root `browser-extension/`) inside
 * the extension directory as `browser-capture/`, so vsce ships it in the VSIX
 * and `trainer.browserCapture.install` can copy it to ~/.trainer/browser-capture.
 *
 * The staged tree is the *unpacked* extension (manifest + scripts + popup +
 * icons): the install flow loads it with "Load unpacked", so an archive would
 * not be usable. Junk patterns mirror scripts/package-browser-extension.mjs.
 */

export const BROWSER_CAPTURE_DIRNAME = "browser-capture";
export const BROWSER_CAPTURE_VERSION_FILE = "trainer-browser-capture.json";
export const BROWSER_CAPTURE_REQUIRED_ENTRIES = [
  "manifest.json",
  "background.js",
  "shared.js",
  "popup/popup.html",
  "README.md",
];

const EXCLUDED_PATTERNS = [/^\.DS_Store$/, /^\._/, /\.map$/, /\.zip$/, /\.tmp$/, /~$/];

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function isExcludedEntry(name) {
  return EXCLUDED_PATTERNS.some((pattern) => pattern.test(name));
}

export function resolveBrowserCaptureDirs({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
} = {}) {
  return {
    sourceDir: path.join(repoRoot, "browser-extension"),
    targetDir: path.join(extensionDir, BROWSER_CAPTURE_DIRNAME),
  };
}

export function collectBrowserCaptureFiles(rootDir, prefix = "") {
  if (!fs.existsSync(rootDir)) {
    return [];
  }
  const files = [];
  for (const name of fs.readdirSync(rootDir).sort()) {
    if (isExcludedEntry(name)) {
      continue;
    }
    const absolute = path.join(rootDir, name);
    const relative = prefix ? `${prefix}/${name}` : name;
    const stats = fs.statSync(absolute);
    if (stats.isDirectory()) {
      files.push(...collectBrowserCaptureFiles(absolute, relative));
    } else if (stats.isFile()) {
      files.push(relative);
    }
  }
  return files;
}

function readCaptureManifestVersion(sourceDir) {
  try {
    const manifest = JSON.parse(
      fs.readFileSync(path.join(sourceDir, "manifest.json"), "utf8"),
    );
    const version = String(manifest?.version ?? "").trim();
    return version || undefined;
  } catch {
    return undefined;
  }
}

function buildVersionMarker(sourceDir, fileCount) {
  return {
    schemaVersion: 1,
    name: "trainer-capture",
    version: readCaptureManifestVersion(sourceDir),
    fileCount,
    generatedFrom: "browser-extension",
  };
}

/**
 * Copy the source extension into the extension directory, replacing any older
 * staged tree so a removed script cannot survive into the VSIX. Missing source
 * (the browser extension has not been checked out) is reported, not fatal:
 * callers decide whether that is acceptable for their verification depth.
 */
export function syncBrowserCaptureExtension({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
  sourceDir = resolveBrowserCaptureDirs({ extensionDir, repoRoot }).sourceDir,
  targetDir = resolveBrowserCaptureDirs({ extensionDir, repoRoot }).targetDir,
  env = process.env,
} = {}) {
  if (!fs.existsSync(sourceDir)) {
    return {
      staged: false,
      reason: `Browser capture source directory is missing: ${sourceDir}`,
      sourceDir,
      targetDir,
      fileCount: 0,
      version: undefined,
    };
  }

  const files = collectBrowserCaptureFiles(sourceDir);
  const marker = buildVersionMarker(sourceDir, files.length);
  fs.rmSync(targetDir, { recursive: true, force: true });
  fs.mkdirSync(targetDir, { recursive: true });
  for (const relative of files) {
    const destination = path.join(targetDir, relative);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(path.join(sourceDir, relative), destination);
  }
  fs.writeFileSync(
    path.join(targetDir, BROWSER_CAPTURE_VERSION_FILE),
    `${JSON.stringify(marker, null, 2)}\n`,
    "utf8",
  );

  const summary = {
    staged: true,
    sourceDir,
    targetDir,
    fileCount: files.length,
    version: marker.version,
  };
  if (env.TRAINER_VSIX_CAPTURE_QUIET !== "1") {
    console.log(
      `Staged browser capture extension (${marker.version ?? "unknown version"}) at ${path.relative(extensionDir, targetDir)} with ${files.length} files.`,
    );
  }
  return summary;
}

/**
 * Tree-level verification for `verify:package`: when the repo carries the
 * browser extension source, the staged tree must exist, carry every required
 * entry plus the version marker, and match the source bytes.
 */
export function verifyBrowserCaptureBundle({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
} = {}) {
  const { sourceDir, targetDir } = resolveBrowserCaptureDirs({ extensionDir, repoRoot });
  const targetRelative = path.relative(extensionDir, targetDir).split(path.sep).join("/");
  const errors = [];

  if (!fs.existsSync(sourceDir)) {
    return {
      staged: false,
      ok: true,
      reason: `Browser capture source directory is missing: ${sourceDir}`,
      sourceDir,
      targetDir,
      targetRelative,
      missingEntries: [],
      unexpectedFiles: [],
      contentMismatches: [],
      version: undefined,
      errors,
    };
  }

  if (!fs.existsSync(targetDir)) {
    errors.push(
      `Staged browser capture bundle is missing: ${targetRelative}. Run "npm run bundle:browser-capture" first.`,
    );
    return {
      staged: true,
      ok: false,
      sourceDir,
      targetDir,
      targetRelative,
      missingEntries: [...BROWSER_CAPTURE_REQUIRED_ENTRIES],
      unexpectedFiles: [],
      contentMismatches: [],
      version: undefined,
      errors,
    };
  }

  const sourceFiles = collectBrowserCaptureFiles(sourceDir);
  const targetFiles = collectBrowserCaptureFiles(targetDir).filter(
    (relative) => relative !== BROWSER_CAPTURE_VERSION_FILE,
  );
  const missingEntries = [
    ...BROWSER_CAPTURE_REQUIRED_ENTRIES.filter(
      (relative) => !fs.existsSync(path.join(targetDir, relative)),
    ),
    ...BROWSER_CAPTURE_REQUIRED_ENTRIES.filter(
      (relative) => !sourceFiles.includes(relative),
    ).map((relative) => `../browser-extension/${relative}`),
  ];
  for (const entry of BROWSER_CAPTURE_REQUIRED_ENTRIES) {
    if (!sourceFiles.includes(entry)) {
      errors.push(`Browser capture source is missing required entry: browser-extension/${entry}`);
    }
  }
  for (const relative of sourceFiles) {
    if (!targetFiles.includes(relative)) {
      errors.push(`Staged browser capture bundle is missing: ${targetRelative}/${relative}`);
    }
  }

  const unexpectedFiles = targetFiles.filter((relative) => !sourceFiles.includes(relative));
  for (const relative of unexpectedFiles) {
    errors.push(`Staged browser capture bundle has an unexpected file: ${targetRelative}/${relative}`);
  }

  const contentMismatches = sourceFiles.filter(
    (relative) =>
      targetFiles.includes(relative) &&
      !fs.readFileSync(path.join(sourceDir, relative)).equals(
        fs.readFileSync(path.join(targetDir, relative)),
      ),
  );
  for (const relative of contentMismatches) {
    errors.push(`Staged browser capture drift detected: ${targetRelative}/${relative}`);
  }

  const markerPath = path.join(targetDir, BROWSER_CAPTURE_VERSION_FILE);
  if (!fs.existsSync(markerPath)) {
    errors.push(`Staged browser capture bundle is missing its version marker: ${targetRelative}/${BROWSER_CAPTURE_VERSION_FILE}`);
  }
  const manifestVersion = readCaptureManifestVersion(sourceDir);
  let version;
  if (fs.existsSync(markerPath)) {
    try {
      const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"));
      version = typeof marker?.version === "string" ? marker.version : undefined;
      if (marker?.schemaVersion !== 1) {
        errors.push(`Staged browser capture version marker has an unsupported schema: ${targetRelative}/${BROWSER_CAPTURE_VERSION_FILE}`);
      }
      if (!manifestVersion || version !== manifestVersion) {
        errors.push("Staged browser capture version marker does not match browser-extension/manifest.json.");
      }
    } catch (error) {
      errors.push(
        `Staged browser capture version marker is unreadable: ${targetRelative}/${BROWSER_CAPTURE_VERSION_FILE} (${error instanceof Error ? error.message : String(error)})`,
      );
    }
  }

  return {
    staged: true,
    ok: errors.length === 0,
    sourceDir,
    targetDir,
    targetRelative,
    missingEntries,
    unexpectedFiles,
    contentMismatches,
    version,
    manifestVersion,
    errors,
  };
}

/** Staged bundle entries relative to the extension directory (VSIX paths). */
export function collectBrowserCaptureVsixEntries({
  extensionDir = path.resolve(__dirname, ".."),
} = {}) {
  const targetDir = path.join(extensionDir, BROWSER_CAPTURE_DIRNAME);
  return collectBrowserCaptureFiles(targetDir).map(
    (relative) => `${BROWSER_CAPTURE_DIRNAME}/${relative}`,
  );
}

export function inspectBrowserCaptureVsixContents({ entryNames = [], bundleEntries = [] }) {
  const entries = new Set(entryNames);
  const required = bundleEntries.length > 0;
  const missingEntries = required
    ? bundleEntries.filter((relative) => !entries.has(`extension/${relative}`))
    : [];
  const errors = missingEntries.map(
    (relative) => `VSIX is missing the bundled browser capture entry: extension/${relative}.`,
  );
  return { required, bundleEntries, missingEntries, errors };
}

/** Archive-level gate for `package:vsix`, mirroring the target-runtime check. */
export function verifyBrowserCaptureVsixArtifact({
  vsixPath,
  bundleEntries = [],
} = {}) {
  if (bundleEntries.length === 0) {
    return { required: false, bundleEntries, missingEntries: [], errors: [] };
  }
  if (!vsixPath || !fs.existsSync(vsixPath)) {
    return {
      required: true,
      bundleEntries,
      missingEntries: [],
      errors: [`VSIX artifact is missing: ${vsixPath ?? "(none)"}.`],
    };
  }
  try {
    const entryNames = [...readZipEntries(fs.readFileSync(vsixPath)).keys()];
    return { vsixPath, ...inspectBrowserCaptureVsixContents({ entryNames, bundleEntries }) };
  } catch (error) {
    return {
      required: true,
      vsixPath,
      bundleEntries,
      missingEntries: [],
      errors: [
        `Could not inspect the VSIX for browser capture entries: ${error instanceof Error ? error.message : String(error)}`,
      ],
    };
  }
}

export function assertBrowserCaptureVsixArtifact(options = {}) {
  const report = verifyBrowserCaptureVsixArtifact(options);
  if (report.errors.length > 0) {
    throw new Error(
      [
        "Trainer VSIX browser capture verification failed.",
        ...report.errors.map((message) => `- ${message}`),
      ].join("\n"),
    );
  }
  return report;
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  const result = syncBrowserCaptureExtension();
  if (!result.staged) {
    console.error(`Browser capture staging failed.\n${result.reason}`);
    process.exit(1);
  }
}
