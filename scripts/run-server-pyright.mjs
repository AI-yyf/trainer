#!/usr/bin/env node
// CI-equivalent server type gate: `python -m pyright app` from server/ with the
// project venv interpreter, cross-platform (.venv/bin/python or
// .venv/Scripts/python.exe). Exit code is passed through unchanged — zero
// tolerance, no partial credit.
//
// Mirrors .github/workflows/ci.yml:51-53.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const serverRoot = path.join(repoRoot, "server");

export function resolveServerPython({
  env = process.env,
  exists = fs.existsSync,
} = {}) {
  const candidates = [
    path.join(serverRoot, ".venv", "bin", "python"),
    path.join(serverRoot, ".venv", "Scripts", "python.exe"),
    path.join(serverRoot, ".venv-mac", "bin", "python"),
    path.join(serverRoot, ".venv-mac", "Scripts", "python.exe"),
  ];
  const found = candidates.find((candidate) => exists(candidate));
  if (found) return found;
  const override = String(env.TRAINER_SERVER_PYTHON ?? "").trim();
  if (override) return override;
  return null;
}

function main() {
  const python = resolveServerPython();
  if (!python) {
    console.error(
      "Server pyright gate: could not resolve the server virtualenv interpreter " +
        "(expected server/.venv/bin/python or server/.venv/Scripts/python.exe; " +
        "set TRAINER_SERVER_PYTHON to override).",
    );
    process.exit(2);
  }
  const result = spawnSync(python, ["-m", "pyright", "app"], {
    cwd: serverRoot,
    stdio: "inherit",
    env: process.env,
  });
  if (result.error) {
    console.error(`Server pyright gate could not start ${python}: ${result.error.message}`);
    process.exit(2);
  }
  process.exit(result.status ?? 1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
