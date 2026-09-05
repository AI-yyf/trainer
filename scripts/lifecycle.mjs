import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { resolveNpmCliPath } from "./verify-workspace.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const managedSidecarPorts = Array.from({ length: 21 }, (_, index) => 34891 + index);

const booleanFlags = new Map([
  ["--skip-extension", "skipExtension"],
  ["--skip-webview", "skipWebview"],
  ["--skip-server", "skipServer"],
  ["--strict", "strict"],
  ["--frozen", "frozen"],
  ["--use-uv", "useUv"],
  ["--skip-install", "skipInstall"],
  ["--start-sidecar", "startSidecar"],
  ["--auto-port", "autoPort"],
  ["--provider-smoke", "providerSmoke"],
  ["--trainer-turn-smoke", "trainerTurnSmoke"],
  ["--training-return-smoke", "trainingReturnSmoke"],
]);

const valueFlags = new Map([
  ["--port", "port"],
  ["--host", "host"],
  ["--sidecar-url", "sidecarUrl"],
  ["--provider-api-key", "providerApiKey"],
  ["--provider-base-url", "providerBaseUrl"],
  ["--provider-model", "providerModel"],
  ["--provider-protocol", "providerProtocol"],
  ["--provider-response-language", "providerResponseLanguage"],
]);

function fail(message) {
  throw new Error(message);
}

function commandResult(command, args, { cwd = repoRoot, env = process.env } = {}) {
  return spawnSync(command, args, { cwd, env, encoding: "utf8" });
}

function run(command, args, { cwd = repoRoot, env = process.env, label = command } = {}) {
  const result = spawnSync(command, args, { cwd, env, stdio: "inherit" });
  if (result.error) {
    fail(`${label} could not start: ${result.error.message}`);
  }
  if (result.status !== 0) {
    fail(`${label} exited with status ${result.status}.`);
  }
}

function npmAvailable() {
  try {
    resolveNpmCliPath();
    return true;
  } catch {
    return false;
  }
}

function runNpm(args, { cwd = repoRoot, label = "npm" } = {}) {
  let npmCliPath;
  try {
    npmCliPath = resolveNpmCliPath();
  } catch (error) {
    fail(error instanceof Error ? error.message : String(error));
  }
  run(process.execPath, [npmCliPath, ...args], { cwd, label });
}

function commandExists(command) {
  const result = commandResult(command, ["--version"]);
  return !result.error && result.status === 0;
}

function requireFile(targetPath, label, strict) {
  if (fs.existsSync(targetPath)) {
    return true;
  }
  if (strict) {
    fail(`${label} is missing at ${path.relative(repoRoot, targetPath)}.`);
  }
  console.log(`[SKIP] ${label} is missing.`);
  return false;
}

export function parseLifecycleArgs(argv) {
  const [command, ...rawArgs] = argv;
  if (!new Set(["bootstrap", "dev", "smoke"]).has(command)) {
    fail("Usage: node scripts/lifecycle.mjs <bootstrap|dev|smoke> [options]");
  }

  const options = { command, host: "127.0.0.1", port: 8765, ports: [] };
  for (let index = 0; index < rawArgs.length; index += 1) {
    const argument = rawArgs[index];
    const equalsIndex = argument.indexOf("=");
    const flag = equalsIndex === -1 ? argument : argument.slice(0, equalsIndex);
    const inlineValue = equalsIndex === -1 ? undefined : argument.slice(equalsIndex + 1);
    const booleanKey = booleanFlags.get(flag);
    if (booleanKey) {
      if (inlineValue !== undefined) {
        fail(`${flag} does not accept a value.`);
      }
      options[booleanKey] = true;
      continue;
    }
    const valueKey = valueFlags.get(flag);
    if (!valueKey) {
      fail(`Unknown option: ${argument}`);
    }
    const value = inlineValue ?? rawArgs[++index];
    if (!value) {
      fail(`${flag} requires a value.`);
    }
    if (valueKey === "port") {
      const ports = value.split(",").map((item) => Number(item.trim()));
      if (ports.some((port) => !Number.isInteger(port) || port < 1 || port > 65535)) {
        fail(`Invalid port: ${value}`);
      }
      options.ports.push(...ports);
      options.port = options.ports[0];
      continue;
    }
    options[valueKey] = value;
  }

  const port = Number(options.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    fail(`Invalid port: ${options.port}`);
  }
  options.port = port;
  return options;
}

export function getVenvPythonPath(root = repoRoot, platform = process.platform) {
  return platform === "win32"
    ? path.join(root, "server", ".venv", "Scripts", "python.exe")
    : path.join(root, "server", ".venv", "bin", "python");
}

export function getSystemPythonCandidates({ platform = process.platform, env = process.env } = {}) {
  const explicit = String(env.TRAINER_SERVER_PYTHON ?? "").trim();
  if (explicit) {
    return [{ command: explicit, args: [], label: "TRAINER_SERVER_PYTHON" }];
  }
  if (platform === "win32") {
    return [
      { command: "py", args: ["-3.12"], label: "py -3.12" },
      { command: "py", args: ["-3"], label: "py -3" },
      { command: "python", args: [], label: "python" },
    ];
  }
  return [
    { command: "python3.12", args: [], label: "python3.12" },
    { command: "python3", args: [], label: "python3" },
    { command: "python", args: [], label: "python" },
  ];
}

function supportsRequiredPython(output) {
  const match = /Python\s+(\d+)\.(\d+)\.(\d+)/.exec(output);
  if (!match) {
    return false;
  }
  const major = Number(match[1]);
  const minor = Number(match[2]);
  return major > 3 || (major === 3 && minor >= 12);
}

export function resolveSystemPython({ platform = process.platform, env = process.env } = {}) {
  const attempted = [];
  for (const candidate of getSystemPythonCandidates({ platform, env })) {
    const result = commandResult(candidate.command, [...candidate.args, "--version"], { env });
    const output = `${result.stdout ?? ""}\n${result.stderr ?? ""}`.trim();
    if (!result.error && result.status === 0 && supportsRequiredPython(output)) {
      return candidate;
    }
    attempted.push(`${candidate.label}: ${output || result.error?.code || "unavailable"}`);
  }
  fail(`Python 3.12+ is required. Checked:\n${attempted.map((item) => `- ${item}`).join("\n")}`);
}

function installNpmPackage(prefix, label, { frozen, strict }) {
  const manifest = path.join(repoRoot, prefix, "package.json");
  if (!requireFile(manifest, `${label} manifest`, strict)) {
    return;
  }
  const lockfile = path.join(repoRoot, prefix, "package-lock.json");
  const command = frozen && fs.existsSync(lockfile) ? "ci" : "install";
  console.log(`[RUN] npm ${command} --prefix ${prefix}`);
  runNpm([command, "--prefix", prefix], { label: `${label} dependency install` });
}

function bootstrapServer({ root, options }) {
  const serverDir = path.join(root, "server");
  if (!requireFile(path.join(serverDir, "pyproject.toml"), "Server manifest", options.strict)) {
    return;
  }
  if (!requireFile(path.join(serverDir, "app", "main.py"), "Server entrypoint", options.strict)) {
    return;
  }

  if (options.useUv && commandExists("uv")) {
    const args = ["sync", "--project", serverDir, "--extra", "dev"];
    if (options.frozen) {
      args.push("--frozen");
    }
    console.log("[RUN] uv sync --project server --extra dev");
    run("uv", args, { cwd: root, label: "Server uv sync" });
    return;
  }
  if (options.useUv) {
    console.log("[WARN] uv was requested but is unavailable; using venv + pip.");
  }

  const pythonPath = getVenvPythonPath(root);
  if (!fs.existsSync(pythonPath)) {
    const systemPython = resolveSystemPython();
    console.log(`[RUN] ${systemPython.label} -m venv server/.venv`);
    run(systemPython.command, [...systemPython.args, "-m", "venv", path.join(root, "server", ".venv")], {
      cwd: root,
      label: "Server virtual environment creation",
    });
  }
  console.log("[RUN] server/.venv Python -m pip install -e .[dev]");
  run(pythonPath, ["-m", "pip", "install", "-e", ".[dev]"], {
    cwd: serverDir,
    label: "Server editable dependency install",
  });
}

export function bootstrap({ root = repoRoot, options = {} } = {}) {
  if (!npmAvailable()) {
    fail("npm is required.");
  }
  if (!options.skipExtension) {
    installNpmPackage("extension", "Extension", options);
  }
  if (!options.skipWebview) {
    installNpmPackage("extension/webview", "Webview", options);
  }
  if (!options.skipServer) {
    bootstrapServer({ root, options });
  }
  console.log("[OK] Bootstrap completed.");
}

function buildWorkspace(root) {
  runNpm(["run", "build", "--prefix", "extension/webview"], {
    cwd: root,
    label: "Webview build",
  });
  runNpm(["run", "build", "--prefix", "extension"], {
    cwd: root,
    label: "Extension build",
  });
}

function portAvailable(host, port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen(port, host, () => server.close(() => resolve(true)));
  });
}

export async function findSidecarPort({ host = "127.0.0.1", port = 8765, autoPort = false } = {}) {
  const candidates = autoPort ? [port, ...managedSidecarPorts.filter((candidate) => candidate !== port)] : [port];
  for (const candidate of candidates) {
    if (await portAvailable(host, candidate)) {
      return candidate;
    }
  }
  fail(`No available sidecar port found for ${host} across ${candidates.join(", ")}.`);
}

function runSidecar({ root, host, port }) {
  const pythonPath = getVenvPythonPath(root);
  if (!fs.existsSync(pythonPath)) {
    fail("Server virtual environment is missing. Run `npm run bootstrap` first.");
  }
  return new Promise((resolve, reject) => {
    const child = spawn(
      pythonPath,
      [path.join(root, "server", "run_sidecar.py"), "--host", host, "--port", String(port), "--reload"],
      { cwd: root, stdio: "inherit", env: { ...process.env, TRAINER_PORT: String(port) } },
    );
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
}

export async function dev({ root = repoRoot, options = {} } = {}) {
  if (!options.skipInstall) {
    bootstrap({ root, options });
  }
  buildWorkspace(root);
  if (!options.startSidecar) {
    console.log("[OK] Build completed. Start the sidecar with `npm run dev -- --start-sidecar`.");
    return 0;
  }
  const port = await findSidecarPort(options);
  console.log(`[RUN] Starting Trainer sidecar on ${options.host}:${port}`);
  return runSidecar({ root, host: options.host, port });
}

async function healthCheck(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch(url, { signal: controller.signal });
    return response.ok ? `HTTP ${response.status}` : undefined;
  } catch {
    return undefined;
  } finally {
    clearTimeout(timeout);
  }
}

function smokeEnvironment(prefix, options) {
  const environment = { ...process.env };
  const providerSmoke = prefix === "PROVIDER";
  const environmentNames = providerSmoke
    ? {
        providerApiKey: "TRAINER_PROVIDER_SMOKE_API_KEY",
        providerBaseUrl: "TRAINER_PROVIDER_SMOKE_BASE_URL",
        providerModel: "TRAINER_PROVIDER_SMOKE_MODEL",
        providerProtocol: "TRAINER_PROVIDER_SMOKE_PROTOCOL",
        providerResponseLanguage: "TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE",
      }
    : {
        providerApiKey: `TRAINER_${prefix}_PROVIDER_API_KEY`,
        providerBaseUrl: `TRAINER_${prefix}_PROVIDER_BASE_URL`,
        providerModel: `TRAINER_${prefix}_PROVIDER_MODEL`,
        providerProtocol: `TRAINER_${prefix}_PROVIDER_PROTOCOL`,
        providerResponseLanguage: `TRAINER_${prefix}_RESPONSE_LANGUAGE`,
      };
  for (const option of [
    "providerApiKey",
    "providerBaseUrl",
    "providerModel",
    "providerProtocol",
    "providerResponseLanguage",
  ]) {
    if (options[option]) {
      environment[environmentNames[option]] = options[option];
    }
  }
  if (options.sidecarUrl) {
    environment[`TRAINER_${prefix}_SIDECAR_URL`] = options.sidecarUrl;
  }
  return environment;
}

function runOptionalSmoke(script, prefix, options) {
  const environment = smokeEnvironment(prefix, options);
  const key = environment[`TRAINER_${prefix}_PROVIDER_API_KEY`];
  if (!key) {
    return { status: "missing", detail: "Provider API key is required for this live smoke." };
  }
  if (prefix !== "PROVIDER" && !environment[`TRAINER_${prefix}_PROVIDER_BASE_URL`]) {
    return { status: "missing", detail: "Provider base URL is required for this live smoke." };
  }
  const result = spawnSync("node", [path.join(repoRoot, "scripts", script)], {
    cwd: repoRoot,
    env: environment,
    stdio: "inherit",
  });
  return result.error || result.status !== 0
    ? { status: "failed", detail: `${script} did not pass.` }
    : { status: "ok", detail: `${script} passed.` };
}

function addReport(report, area, status, detail) {
  report.push({ area, status, detail });
  console.log(`[${status.toUpperCase()}] ${area}: ${detail}`);
}

export function getSmokePorts(options = {}) {
  const ports = options.ports?.length
    ? options.ports
    : [options.port ?? 8765, ...managedSidecarPorts];
  return [...new Set(ports)];
}

export async function smoke({ root = repoRoot, options = {} } = {}) {
  const report = [];
  addReport(report, "Node", "ok", process.version);
  addReport(report, "npm", npmAvailable() ? "ok" : "missing", "npm command");
  try {
    const python = resolveSystemPython();
    addReport(report, "Python", "ok", python.label);
  } catch (error) {
    addReport(report, "Python", "missing", error.message);
  }
  for (const [area, relativePath] of [
    ["Root manifest", "package.json"],
    ["Extension manifest", "extension/package.json"],
    ["Webview manifest", "extension/webview/package.json"],
    ["Server manifest", "server/pyproject.toml"],
    ["Server entrypoint", "server/app/main.py"],
    ["Webview build", "extension/webview/dist/index.html"],
    ["Extension build", "extension/dist/extension/src/extension.js"],
  ]) {
    addReport(report, area, fs.existsSync(path.join(root, relativePath)) ? "ok" : "pending", relativePath);
  }
  addReport(
    report,
    "Server virtual environment",
    fs.existsSync(getVenvPythonPath(root)) ? "ok" : "pending",
    path.relative(root, getVenvPythonPath(root)),
  );

  const ports = getSmokePorts(options);
  let health;
  for (const port of ports) {
    const result = await healthCheck(`http://${options.host}:${port}/health`);
    if (result) {
      health = { port, result };
      break;
    }
  }
  addReport(
    report,
    "Sidecar health",
    health ? "ok" : "pending",
    health ? `${health.result} on port ${health.port}` : `No sidecar answered on ${ports.join(", ")}.`,
  );

  if (options.providerSmoke) {
    const result = runOptionalSmoke("provider-smoke.mjs", "PROVIDER", options);
    addReport(report, "Provider smoke", result.status, result.detail);
  }
  if (options.trainerTurnSmoke) {
    const result = runOptionalSmoke("trainer-turn-smoke.mjs", "TURN_SMOKE", options);
    addReport(report, "Trainer turn smoke", result.status, result.detail);
  }
  if (options.trainingReturnSmoke) {
    const result = runOptionalSmoke("training-return-smoke.mjs", "TRAINING_RETURN_SMOKE", options);
    addReport(report, "Training return smoke", result.status, result.detail);
  }

  const failures = report.filter((item) => item.status === "missing" || item.status === "failed");
  const pending = report.filter((item) => item.status === "pending");
  return { ok: failures.length === 0 && (!options.strict || pending.length === 0), report };
}

async function main() {
  const options = parseLifecycleArgs(process.argv.slice(2));
  if (options.command === "bootstrap") {
    bootstrap({ options });
    return;
  }
  if (options.command === "dev") {
    const code = await dev({ options });
    if (code !== 0) {
      process.exitCode = code;
    }
    return;
  }
  const result = await smoke({ options });
  if (!result.ok) {
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch((error) => {
    console.error(`Trainer lifecycle failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}
