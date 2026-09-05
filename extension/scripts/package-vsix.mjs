import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

import { resolveNativeSidecarTarget } from "./bundle-sidecar-binary.mjs";
import { assertPackageVerified } from "./verify-package.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

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
