import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runServerCommand, runServerTests } from "./run-server-tests.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const serverRoot = path.join(repoRoot, "server");

function fail(message) {
  console.error(`Trainer workspace verification failed.\n${message}`);
  process.exit(1);
}

export function resolveNpmCliPath({
  execPath = process.execPath,
  platform = process.platform,
  env = process.env,
} = {}) {
  const npmExecPath = env.npm_execpath;
  if (npmExecPath && fs.existsSync(npmExecPath)) {
    return npmExecPath;
  }

  const candidates = platform === "win32"
    ? [path.join(path.dirname(execPath), "node_modules", "npm", "bin", "npm-cli.js")]
    : [
        path.join(
          path.dirname(path.dirname(execPath)),
          "lib",
          "node_modules",
          "npm",
          "bin",
          "npm-cli.js",
        ),
      ];
  const npmCliPath = candidates.find((candidate) => fs.existsSync(candidate));
  if (!npmCliPath) {
    throw new Error(
      "Could not resolve npm-cli.js. Run this script through npm or use a standard npm installation.",
    );
  }

  return npmCliPath;
}

function runNpm(args, label) {
  let npmCliPath;
  try {
    npmCliPath = resolveNpmCliPath();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    fail(message);
  }

  const result = spawnSync(process.execPath, [npmCliPath, ...args], {
    cwd: repoRoot,
    stdio: "inherit",
  });
  if (result.error) {
    fail(`${label} could not start: ${result.error.message}`);
  }
  if (result.status !== 0) {
    fail(`${label} exited with status ${result.status}.`);
  }
}

export function verifyWorkspace() {
  runNpm(["run", "build"], "Root build");
  runNpm(["run", "check"], "Root typecheck");
  runNpm(["run", "test:extension"], "Extension tests");
  runServerCommand({
    serverRoot,
    args: ["-m", "ruff", "check", "app", "tests"],
    label: "Server Ruff check",
  });
  runServerCommand({
    serverRoot,
    args: ["-m", "pyright", "app"],
    label: "Server Pyright check",
  });
  return runServerTests({ serverRoot });
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  verifyWorkspace();
}
