import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

import { resolveNativeSidecarTarget } from "./bundle-sidecar-binary.mjs";
import { assertPackageVerified } from "./verify-package.mjs";
import { readZipEntries, readZipEntry } from "./vsix-archive.mjs";
import { resolveNpmExecPath } from "./vsix-build-helpers.mjs";
export { resolveNpmExecPath, sanitizePackagedSymlinks } from "./vsix-build-helpers.mjs";

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
    "@vscode/vsce@4.0.0",
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
    "extension/package.json",
    "extension/dist/extension/src/extension.js",
    "extension/webview/dist/index.html",
    "extension/bundled/remote/trainer-workspace-companion.vsix",
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

export async function packageVsix({
  extensionDir = path.resolve(__dirname, ".."),
  env = process.env,
  prepare,
  runPackage = spawnSync,
} = {}) {
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(extensionDir, "package.json"), "utf8"),
  );
  const targetPlatform = resolveNativeSidecarTarget();
  const outputPath = resolveVsixOutputPath({ extensionDir, packageJson, targetPlatform, env });
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const repoRoot = path.resolve(extensionDir, "..");
  // Shared build helpers live outside both entrypoints so this lazy load
  // cannot wait on the currently evaluating CLI module. Missing inputs are
  // built before gating, and a failed dependency prevents vsce from running.
  const prepareInputs = prepare ?? (await import("./prepublish-vsix.mjs")).prepublishVsix;
  prepareInputs({ extensionDir, repoRoot, env });
  const packageReport = assertPackageVerified({ extensionDir, repoRoot, env });

  const npmExecPath = resolveNpmExecPath();
  const args = buildVscePackageArgs(outputPath, targetPlatform);
  const result = runPackage(process.execPath, [npmExecPath, ...args], {
    cwd: extensionDir,
    env: { ...env, TRAINER_VSIX_TARGET: targetPlatform, TRAINER_VSIX_PREPARED: "1" },
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
  const metadataPath = writeVsixBuildMetadata({ outputPath, targetPlatform, packageJson,
    packageReport, repoRoot, env });
  writeGitHubOutputs({ outputPath, targetPlatform, metadataPath, env });

  return {
    packageJson,
    outputPath,
    targetPlatform,
    targetArtifact,
    metadataPath,
  };
}

export function writeVsixBuildMetadata({ outputPath, targetPlatform, packageJson,
  packageReport, repoRoot, env = process.env }) {
  const revision = spawnSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" });
  const status = spawnSync("git", ["status", "--porcelain", "--untracked-files=no"],
    { cwd: repoRoot, encoding: "utf8" });
  if (revision.status !== 0 || status.status !== 0) {
    throw new Error("VSIX provenance requires a readable Git commit and working tree state.");
  }
  const metadata = {
    schemaVersion: 1,
    productVersion: packageJson.version,
    targetPlatform,
    sourceCommit: revision.stdout.trim(),
    sourceDirty: status.stdout.trim().length > 0,
    sourceSnapshot: packageReport.binaryManifest.manifest.sourceSnapshot,
    sidecarBuild: packageReport.binaryManifest.manifest,
    vsix: { file: path.basename(outputPath), bytes: fs.statSync(outputPath).size,
      sha256: crypto.createHash("sha256").update(fs.readFileSync(outputPath)).digest("hex") },
    tools: { node: process.version, vsce: "4.0.0" },
    runUrl: env.GITHUB_RUN_ID && env.GITHUB_REPOSITORY
      ? `${env.GITHUB_SERVER_URL ?? "https://github.com"}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}`
      : null,
  };
  const metadataPath = `${outputPath}.build.json`;
  fs.writeFileSync(metadataPath, `${JSON.stringify(metadata, null, 2)}\n`, "utf8");
  return metadataPath;
}

export function writeGitHubOutputs({ outputPath, targetPlatform, metadataPath, env = process.env }) {
  const githubOutputPath = String(env.GITHUB_OUTPUT ?? "").trim();
  if (!githubOutputPath) {
    return;
  }
  fs.appendFileSync(
    githubOutputPath,
    `vsix_path=${outputPath.replace(/[\r\n]/g, "")}\nvsix_target=${targetPlatform}\n` +
    (metadataPath ? `vsix_metadata_path=${metadataPath.replace(/[\r\n]/g, "")}\n` : ""),
    "utf8",
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  try {
    const result = await packageVsix();
    console.log(`Packaged Trainer VSIX at ${result.outputPath}`);
  } catch (error) {
    console.error(`Trainer VSIX packaging failed.\n${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}
