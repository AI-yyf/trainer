import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveVsixOutputPath } from "./package-vsix.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const extensionDir = path.resolve(__dirname, "..");
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

  return {
    packageJson,
    vsixPath,
    rebuilt: !skipRebuild,
  };
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

  fail(
    "Could not resolve npm_execpath for current VSIX packaging. " +
      "Run this script from an npm context or provide a standard npm installation.",
  );
}

function withVsixBuildLock(run) {
  const startedAt = Date.now();
  while (true) {
    try {
      const fd = fs.openSync(vsixLockPath, "wx");
      fs.writeFileSync(fd, `${process.pid}\n`, "utf8");
      fs.closeSync(fd);
      try {
        return run();
      } finally {
        fs.rmSync(vsixLockPath, { force: true });
      }
    } catch (error) {
      if (!isAlreadyExistsError(error)) {
        throw error;
      }
      const recovered = cleanupStaleVsixBuildLock(vsixLockPath);
      if (recovered.removed) {
        continue;
      }
      if (Date.now() - startedAt > vsixLockWaitMs) {
        fail(
          `Timed out waiting for VSIX build lock: ${vsixLockPath}. ` +
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
