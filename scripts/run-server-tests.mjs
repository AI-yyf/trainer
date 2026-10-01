import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const serverDir = path.join(repoRoot, "server");

function fail(label, message) {
  console.error(`${label} failed.\n${message}`);
  process.exit(1);
}

function candidate(command, args, label) {
  return { command, args, label };
}

export function resolvePythonCandidates({
  serverRoot = serverDir,
  platform = process.platform,
  env = process.env,
} = {}) {
  const explicit = (env.TRAINER_SERVER_PYTHON ?? "").trim();
  if (explicit) {
    return [candidate(explicit, [], explicit)];
  }

  const candidates = [];
  const localExecutables = platform === "win32"
    ? [
        path.join(serverRoot, ".venv", "Scripts", "python.exe"),
        path.join(serverRoot, ".venv-mac", "Scripts", "python.exe"),
        path.join(serverRoot, ".venv", "bin", "python"),
        path.join(serverRoot, ".venv-mac", "bin", "python"),
      ]
    : [
        path.join(serverRoot, ".venv", "bin", "python"),
        path.join(serverRoot, ".venv-mac", "bin", "python"),
        path.join(serverRoot, ".venv", "Scripts", "python.exe"),
        path.join(serverRoot, ".venv-mac", "Scripts", "python.exe"),
      ];

  for (const executable of localExecutables) {
    if (fs.existsSync(executable)) {
      candidates.push(candidate(executable, [], path.relative(repoRoot, executable)));
    }
  }

  if (platform === "win32") {
    candidates.push(candidate("py", ["-3.12"], "py -3.12"));
    candidates.push(candidate("py", ["-3"], "py -3"));
    candidates.push(candidate("python", [], "python"));
  } else {
    candidates.push(candidate("python3.12", [], "python3.12"));
    candidates.push(candidate("python3", [], "python3"));
    candidates.push(candidate("python", [], "python"));
  }

  return candidates;
}

export function runServerCommand({
  args,
  label = "Trainer server command",
  serverRoot = serverDir,
  platform = process.platform,
  env = process.env,
} = {}) {
  if (!Array.isArray(args) || args.length === 0) {
    throw new Error("runServerCommand requires at least one Python argument.");
  }

  const attempted = [];

  for (const python of resolvePythonCandidates({ serverRoot, platform, env })) {
    if (path.isAbsolute(python.command) && !fs.existsSync(python.command)) {
      attempted.push(`${python.label}: missing`);
      continue;
    }

    const result = spawnSync(python.command, [...python.args, ...args], {
      cwd: serverRoot,
      stdio: "inherit",
      env,
    });

    if (result.error) {
      if (result.error.code === "ENOENT") {
        attempted.push(`${python.label}: not found`);
        continue;
      }

      fail(label, `${python.label} could not start: ${result.error.message}`);
    }

    if (result.status === 0) {
      return {
        python: python.label,
        status: 0,
      };
    }

    fail(label, `${python.label} exited with status ${result.status}.`);
  }

  fail(
    label,
    [
      "Could not find a usable Python interpreter.",
      "Checked candidates:",
      ...attempted.map((item) => `- ${item}`),
      "Set TRAINER_SERVER_PYTHON to override the interpreter if needed.",
    ].join("\n"),
  );
}

/**
 * Worker count for the pytest run.
 *
 * The suite is ~3000 tests whose cost is per-test app/SQLite setup rather than
 * any single hotspot, so it parallelises well. Every database in
 * tests/conftest.py lives in a per-test tmp_path and the HTTP paths use mock
 * transports, so spreading it across processes is safe.
 *
 * The load average is deliberately *not* an input. An earlier version backed
 * off when the machine looked busy, on the theory that adding workers to a
 * saturated box hurts. Measurement says the opposite: the work is CPU-bound
 * Python, so running it nearly serially costs far more than the contention.
 * Measured on this box at load 18: n=2 → 304s, n=4 → 258s, n=6 → 188s,
 * n=8 → 202s. The gentlest setting was the slowest by a wide margin.
 *
 * TRAINER_SERVER_TEST_WORKERS=1 restores the serial run; any non-numeric value
 * falls back to the computed default rather than disabling parallelism
 * silently.
 */
export function resolveTestWorkers({
  env = process.env,
  cpus = os.cpus().length,
} = {}) {
  const raw = (env.TRAINER_SERVER_TEST_WORKERS ?? "").trim();
  if (raw) {
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 8;
  }
  // Never below 4: a 2-worker run is measurably worse than any other setting.
  return Math.max(4, Math.min(8, cpus));
}

export function runServerTests(options = {}) {
  const workers = resolveTestWorkers(options);
  const parallel = workers > 1 ? ["-n", String(workers)] : [];
  return runServerCommand({
    ...options,
    // -p no:cacheprovider keeps workers from fighting over the pytest cache.
    //
    // The heartbeat keeps the run observable: under xdist the controller
    // prints a dot per test, and a slow integration test on a loaded machine
    // can leave 20-30s of complete silence — indistinguishable from a hang to
    // anything supervising the process. One line every 10s says "alive".
    // PYTHONPATH exposes the plugin module, and it stays quiet inside workers
    // so there is no eightfold echo.
    args: [
      "-m", "pytest", "tests", "-q",
      ...parallel,
      "-p", "no:cacheprovider",
      "-p", "trainer_suite_heartbeat",
    ],
    env: {
      ...(options.env ?? process.env),
      PYTHONPATH: [path.join(serverDir, "tests"), (options.env ?? process.env).PYTHONPATH ?? ""]
        .filter(Boolean)
        .join(path.delimiter),
    },
    label: "Trainer server tests",
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  runServerTests();
}
