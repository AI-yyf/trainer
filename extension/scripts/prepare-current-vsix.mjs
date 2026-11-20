import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveVsixOutputPath } from "./package-vsix.mjs";
import {
  describeVsixFreshness,
  resolveVsixFreshness,
} from "../../scripts/vsix-freshness.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionDir, "..");
const vsixLockPath = path.join(extensionDir, ".vsix-build.lock");
const vsixLockWaitMs = 5 * 60 * 1000;
const vsixLockPollMs = 1000;

export function ensureCurrentVsix(options = {}) {
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(extensionDir, "package.json"), "utf8"),
  );
  const vsixPath = resolveVsixOutputPath({ extensionDir, packageJson });
  const skipRebuild = process.env.TRAINER_SKIP_VSIX_REBUILD === "1";

  if (!skipRebuild) {
    withVsixBuildLock(() => {
      const args = ["run", "package:vsix"];
      const npmExecPath = resolveNpmExecPath();
      const result = spawnSync(process.execPath, [npmExecPath, ...args], {
        cwd: extensionDir,
        encoding: "utf8",
      });
      if (result.status !== 0) {
        fail(
          [
            `Could not build the current Trainer VSIX via node ${npmExecPath} ${args.join(" ")}.`,
            options.reason ? `Reason: ${options.reason}` : "",
            result.error ? `${result.error.name}: ${result.error.message}` : "",
            (result.stdout ?? "").trim(),
            (result.stderr ?? "").trim(),
          ]
            .filter(Boolean)
            .join("\n"),
        );
      }
    });
  }

  if (!fs.existsSync(vsixPath)) {
    fail(
      [
        `Current Trainer VSIX is missing: ${vsixPath}`,
        skipRebuild
          ? "TRAINER_SKIP_VSIX_REBUILD=1 skipped the rebuild, so no current VSIX is available."
          : "The package step finished without producing the expected VSIX.",
      ].join("\n"),
    );
  }

  // A rebuild makes the artifact current by construction; a skipped rebuild
  // does not, so prove it before the caller installs it.
  const freshness = resolveVsixFreshness({ repoRoot, vsixPath });
  if (freshness.stale) {
    fail(
      [
        describeVsixFreshness({ repoRoot, vsixPath }),
        skipRebuild
          ? "TRAINER_SKIP_VSIX_REBUILD=1 skipped the rebuild, so this artifact cannot stand in for the current source."
          : "The package step finished without producing an artifact that matches the current sources.",
      ].join("\n"),
    );
  }

  return {
    packageJson,
    vsixPath,
    rebuilt: !skipRebuild,
  };
}

/**
 * Make sure the packaged artifact a gate is about to install still reflects
 * the source tree.
 *
 * A gate that installs a stale VSIX verifies the wrong code: the report it
 * writes describes an artifact the sources no longer match. This repackages
 * under the shared build lock and then proves the result is current;
 * `TRAINER_SKIP_VSIX_REBUILD=1` skips the repackage and instead refuses to
 * continue with a stale artifact.
 *
 * Throws when the artifact cannot be trusted — the gate decides how to exit.
 *
 * @param {{
 *   vsixPath?: string,
 *   reason?: string,
 *   env?: NodeJS.ProcessEnv,
 *   extensionDir?: string,
 *   repoRoot?: string,
 * }} options
 */
export function ensureFreshVsix(options = {}) {
  const env = options.env ?? process.env;
  const targetExtensionDir = options.extensionDir ?? extensionDir;
  const targetRepoRoot = options.repoRoot ?? repoRoot;
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(targetExtensionDir, "package.json"), "utf8"),
  );
  const vsixPath = options.vsixPath
    ? path.resolve(options.vsixPath)
    : resolveVsixOutputPath({ extensionDir: targetExtensionDir, packageJson, env });
  const skipRebuild = env.TRAINER_SKIP_VSIX_REBUILD === "1";

  if (!skipRebuild) {
    withVsixBuildLock(() => {
      const args = ["run", "package:vsix"];
      const npmExecPath = resolveNpmExecPath();
      const result = spawnSync(process.execPath, [npmExecPath, ...args], {
        cwd: targetExtensionDir,
        // The repackage must land exactly where the gate is going to look.
        env: { ...env, TRAINER_VSIX_OUTPUT_PATH: vsixPath },
        encoding: "utf8",
      });
      if (result.status !== 0) {
        throw new Error(
          [
            `Could not build the current Trainer VSIX via node ${npmExecPath} ${args.join(" ")}.`,
            options.reason ? `Reason: ${options.reason}` : "",
            result.error ? `${result.error.name}: ${result.error.message}` : "",
            (result.stdout ?? "").trim(),
            (result.stderr ?? "").trim(),
          ]
            .filter(Boolean)
            .join("\n"),
        );
      }
    }, targetExtensionDir);
  }

  if (!fs.existsSync(vsixPath)) {
    throw new Error(
      [
        `Current Trainer VSIX is missing: ${vsixPath}`,
        skipRebuild
          ? "TRAINER_SKIP_VSIX_REBUILD=1 skipped the rebuild, so no current VSIX is available."
          : "The package step finished without producing the expected VSIX.",
      ].join("\n"),
    );
  }

  const freshness = resolveVsixFreshness({ repoRoot: targetRepoRoot, vsixPath });
  if (freshness.stale) {
    throw new Error(
      [
        describeVsixFreshness({ repoRoot: targetRepoRoot, vsixPath }),
        skipRebuild
          ? "TRAINER_SKIP_VSIX_REBUILD=1 kept the gate from repacking, so it cannot verify the current source."
          : "The repackage finished without producing an artifact that matches the current sources.",
      ].join("\n"),
    );
  }

  return {
    packageJson,
    vsixPath,
    rebuilt: !skipRebuild,
    freshness,
  };
}

/**
 * The gate-side wrapper: report the failure the way the other VSIX tooling
 * does and stop, instead of dumping a stack trace.
 *
 * @param {Parameters<typeof ensureFreshVsix>[0]} options
 */
export function ensureFreshVsixOrExit(options = {}) {
  try {
    return ensureFreshVsix(options);
  } catch (error) {
    console.error(`Trainer VSIX preparation failed.\n${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}

export function cleanupStaleVsixBuildLock(lockPath = vsixLockPath) {
  if (!fs.existsSync(lockPath)) {
    return {
      removed: false,
      reason: "missing",
    };
  }

  const pidText = fs.readFileSync(lockPath, "utf8").trim();
  const pid = Number(pidText);
  if (!Number.isInteger(pid) || pid <= 0) {
    fs.rmSync(lockPath, { force: true });
    return {
      removed: true,
      reason: "invalid-pid",
    };
  }

  try {
    process.kill(pid, 0);
    return {
      removed: false,
      reason: "active-process",
      pid,
    };
  } catch (error) {
    if (
      error &&
      typeof error === "object" &&
      "code" in error &&
      (error.code === "ESRCH" || error.code === "EINVAL")
    ) {
      fs.rmSync(lockPath, { force: true });
      return {
        removed: true,
        reason: "dead-process",
        pid,
      };
    }
    if (error && typeof error === "object" && "code" in error && error.code === "EPERM") {
      return {
        removed: false,
        reason: "active-process",
        pid,
      };
    }
    throw error;
  }
}

function resolveNpmExecPath() {
  const npmExecPath = process.env.npm_execpath;
  if (npmExecPath && fs.existsSync(npmExecPath)) {
    return npmExecPath;
  }

  const candidate = process.platform === "win32"
    ? path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js")
    : path.join(path.dirname(path.dirname(process.execPath)), "lib", "node_modules", "npm", "bin", "npm-cli.js");
  if (fs.existsSync(candidate)) {
    return candidate;
  }

  throw new Error(
    "Could not resolve npm_execpath for current VSIX packaging. " +
      "Run this script from an npm context or provide a standard npm installation.",
  );
}

function withVsixBuildLock(run, targetExtensionDir = extensionDir) {
  const lockPath = path.join(targetExtensionDir, ".vsix-build.lock");
  const startedAt = Date.now();
  while (true) {
    try {
      const fd = fs.openSync(lockPath, "wx");
      fs.writeFileSync(fd, `${process.pid}\n`, "utf8");
      fs.closeSync(fd);
      try {
        return run();
      } finally {
        fs.rmSync(lockPath, { force: true });
      }
    } catch (error) {
      if (!isAlreadyExistsError(error)) {
        throw error;
      }
      const recovered = cleanupStaleVsixBuildLock(lockPath);
      if (recovered.removed) {
        continue;
      }
      if (Date.now() - startedAt > vsixLockWaitMs) {
        throw new Error(
          `Timed out waiting for VSIX build lock: ${lockPath}. ` +
            "Another packaging process may be stuck or the previous build did not clean up.",
        );
      }
      sleep(vsixLockPollMs);
    }
  }
}

function isAlreadyExistsError(error) {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "EEXIST");
}

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function fail(message) {
  console.error(`Trainer VSIX preparation failed.\n${message}`);
  process.exit(1);
}
