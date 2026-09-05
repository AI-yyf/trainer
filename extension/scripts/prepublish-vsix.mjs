import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { resolveNpmExecPath } from "./package-vsix.mjs";
import {
  clearForeignSidecarBinaries,
  resolveNativeSidecarTarget,
} from "./bundle-sidecar-binary.mjs";
import {
  assertPackageVerified,
  verifyBundledBinaryManifest,
} from "./verify-package.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function shouldReuseVerifiedSidecarBinary(env = process.env) {
  return env.TRAINER_REUSE_VERIFIED_SIDECAR_BINARY === "1";
}

export function assertReusableSidecarBinary({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
} = {}) {
  const report = verifyBundledBinaryManifest({ extensionDir, repoRoot });
  const executablePath = report.executableCandidates.find((candidate) => fs.existsSync(candidate));
  if (report.errors.length > 0 || !executablePath) {
    const reasons = [
      ...report.errors.map((message) => `- ${message}`),
      !executablePath
        ? `- Bundled sidecar binary executable missing: ${report.executableCandidates[0]}`
        : "",
    ].filter(Boolean);
    throw new Error(
      [
        "TRAINER_REUSE_VERIFIED_SIDECAR_BINARY=1 requires a sidecar binary whose manifest matches the current server source.",
        ...reasons,
      ].join("\n"),
    );
  }
  return {
    ...report,
    executablePath,
  };
}

function runNpmScript(scriptName, { extensionDir, env }) {
  const npmExecPath = resolveNpmExecPath();
  const result = spawnSync(process.execPath, [npmExecPath, "run", scriptName], {
    cwd: extensionDir,
    env,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(
      [
        `VSIX prepublish step failed: npm run ${scriptName}`,
        result.error ? `${result.error.name}: ${result.error.message}` : "",
        (result.stdout ?? "").trim(),
        (result.stderr ?? "").trim(),
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
}

export function prepublishVsix({
  extensionDir = path.resolve(__dirname, ".."),
  repoRoot = path.resolve(extensionDir, ".."),
  env = process.env,
  runScript = runNpmScript,
} = {}) {
  for (const scriptName of ["clean", "build", "build:webview"]) {
    runScript(scriptName, { extensionDir, env });
  }

  const targetPlatform = resolveNativeSidecarTarget();
  const reusedBinary = shouldReuseVerifiedSidecarBinary(env);
  let binaryReport;
  if (reusedBinary) {
    binaryReport = assertReusableSidecarBinary({ extensionDir, repoRoot });
  } else {
    runScript("bundle:sidecar:binary", { extensionDir, env });
  }

  const removedForeignTargets = clearForeignSidecarBinaries({ extensionDir, targetPlatform });
  runScript("bundle:sidecar", { extensionDir, env });
  runScript("verify:sidecar-runtime", { extensionDir, env });
  const packageReport = assertPackageVerified({ extensionDir, repoRoot, env });
  return {
    targetPlatform,
    removedForeignTargets,
    reusedBinary,
    binaryReport,
    packageReport,
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  try {
    const result = prepublishVsix();
    const detail = result.reusedBinary
      ? `Reused verified bundled sidecar binary at ${result.binaryReport.executablePath}.`
      : "Rebuilt bundled sidecar binary.";
    console.log(`Trainer VSIX prepublish verification passed. ${detail}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Trainer VSIX prepublish failed.\n${message}`);
    process.exit(1);
  }
}
