import { spawnSync } from "node:child_process";
import fs from "node:fs";
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

export function runServerTests(options = {}) {
  return runServerCommand({
    ...options,
    args: ["-m", "pytest", "tests", "-q"],
    label: "Trainer server tests",
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  runServerTests();
}
