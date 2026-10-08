import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const logNames = new Set(["main.log", "renderer.log", "exthost.log", "sharedprocess.log"]);
const environmentKeys = ["DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "TRAINER_E2E_NO_SANDBOX"];
export const driverSecretDiagnosticRedactions = Object.freeze([
  "trainer-host-diagnostic-roundtrip", "isolated-driver-secret-storage-probe",
]);

export function resolveOwnedSidecarPackage({ profileDir, extensionsDir, extensionPath, target, expectedIdentity }) {
  const profile = fs.realpathSync(profileDir);
  const root = fs.realpathSync(path.dirname(profileDir));
  const extensions = fs.realpathSync(extensionsDir);
  const installed = fs.realpathSync(extensionPath);
  const inside = (base, candidate) => {
    const relative = path.relative(base, candidate);
    return relative !== "" && !path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(".." + path.sep);
  };
  if (!path.basename(root).startsWith("trainer-vsix-e2e-") ||
      !inside(root, profile) || !inside(root, extensions) || !inside(extensions, installed)) {
    throw new Error("The sidecar client is outside the driver-owned installed profile.");
  }
  const moduleFile = fs.realpathSync(path.join(installed, "dist/extension/src/core/httpClient.js"));
  const executable = fs.realpathSync(path.join(installed, "bundled/bin", target, "trainer-sidecar.exe"));
  if (!inside(installed, moduleFile) || !inside(installed, executable)) {
    throw new Error("The installed sidecar module or executable escapes its owned package.");
  }
  const manifestPath = fs.realpathSync(path.join(installed, "package.json"));
  if (!inside(installed, manifestPath)) throw new Error("The installed sidecar manifest escapes its owned package.");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (!expectedIdentity || manifest.publisher !== expectedIdentity.publisher ||
      manifest.name !== expectedIdentity.name || manifest.version !== expectedIdentity.version) {
    throw new Error("The owned installed sidecar package identity does not match the harness.");
  }
  return { moduleFile, executable };
}

export function validateOwnedWindowsSidecar(metadata, { pid, parentPid, port, executable, startedAt }) {
  const samePath = (left, right) => typeof left === "string" && typeof right === "string" &&
    left.replaceAll("\\", "/").toLowerCase() === right.replaceAll("\\", "/").toLowerCase();
  const command = /^\s*(?:"([^"]+)"|(\S+))\s+--host\s+127\.0\.0\.1\s+--port\s+(\d+)\s*$/.exec(metadata.commandLine ?? "");
  const createdAt = Date.parse(metadata.createdAt);
  if (!Number.isInteger(pid) || pid <= 0 || !Number.isInteger(port) || port < 1 || port > 65535 ||
      metadata.pid !== pid || metadata.parentPid !== parentPid ||
      !samePath(metadata.canonicalExecutable, executable) ||
      !samePath(metadata.canonicalCommandExecutable, executable) ||
      !command || Number(command[3]) !== port || !Number.isFinite(createdAt) || createdAt < startedAt) {
    throw new Error("The Windows sidecar does not match this driver's owned launch identity.");
  }
  return { pid, port, createdAt };
}

// The temporary wrapper delegates unchanged and retains only the real client,
// never its token. A new PID requires a new real setInstanceToken invocation.
export function captureInstalledSidecarClient(Client, { clock = Date.now, onHealthResult } = {}) {
  const original = Client?.prototype?.setInstanceToken;
  if (typeof original !== "function") throw new Error("The installed sidecar client has no authentication setter.");
  let client;
  let capturedAt;
  let generation = 0;
  let binding;
  let previousBinding;
  let active = true;
  const healthWrappers = new Map();
  const noteHealth = (data) => {
    try { onHealthResult?.(data); }
    catch { console.warn("The isolated sidecar health diagnostic could not be recorded."); }
  };
  function wrapper(...args) {
    const result = Reflect.apply(original, this, args);
    if (active && this instanceof Client) {
      client = this;
      capturedAt = clock();
      generation += 1;
      binding = undefined;
      if (onHealthResult && typeof this.requestJson === "function" && !healthWrappers.has(this)) {
        const owner = this;
        const descriptor = Object.getOwnPropertyDescriptor(owner, "requestJson");
        const request = owner.requestJson;
        function observedRequest(...requestArgs) {
          if (requestArgs[0] !== "GET" || requestArgs[2] !== "/health") return Reflect.apply(request, this, requestArgs);
          const startedAt = clock();
          const common = () => ({ port: requestArgs[1], startedAt, durationMs: clock() - startedAt });
          const failed = (error) => {
            const safeCodes = ["ECONNREFUSED", "ECONNRESET", "ETIMEDOUT", "ENOTFOUND", "EAI_AGAIN", "EHOSTUNREACH", "ENETUNREACH", "ABORT_ERR"];
            const safeNames = ["Error", "TypeError", "SyntaxError", "SidecarHttpError", "SidecarRequestAbortedError"];
            if (client === owner) noteHealth({ ...common(), ok: false, responseResolved: false,
              statusCode: Number.isInteger(error?.statusCode) && error.statusCode >= 100 && error.statusCode <= 599 ? error.statusCode : null,
              errorCode: safeCodes.includes(error?.code) ? error.code : null,
              errorName: safeNames.includes(error?.name) ? error.name : null });
            throw error;
          };
          let pending;
          try { pending = Reflect.apply(request, this, requestArgs); }
          catch (error) { return failed(error); }
          return Promise.resolve(pending).then((value) => {
            if (client === owner) noteHealth({ ...common(), ok: true, responseResolved: true, statusCode: null, errorCode: null, errorName: null });
            return value;
          }, failed);
        }
        owner.requestJson = observedRequest;
        healthWrappers.set(owner, { descriptor, observedRequest });
      }
    }
    return result;
  }
  Client.prototype.setInstanceToken = wrapper;
  return {
    request(method, launch, requestPath, body, timeoutMs) {
      if (!active || !client || !Number.isFinite(launch.createdAt) || launch.createdAt < capturedAt ||
          (previousBinding && previousBinding.pid !== launch.pid && previousBinding.generation === generation)) {
        throw new Error("No current authenticated client is bound to this owned sidecar launch.");
      }
      if (binding && (binding.pid !== launch.pid || binding.port !== launch.port || binding.createdAt !== launch.createdAt)) {
        throw new Error("The authenticated client belongs to a different sidecar launch.");
      }
      binding = { ...launch, generation };
      previousBinding = binding;
      if (method === "GET") return client.getJson(launch.port, requestPath, { timeoutMs });
      if (method === "POST") return client.postJson(launch.port, requestPath, body, { timeoutMs });
      throw new Error("Unsupported diagnostic sidecar method.");
    },
    restore() {
      active = false;
      client = undefined;
      binding = undefined;
      if (Client.prototype.setInstanceToken === wrapper) Client.prototype.setInstanceToken = original;
      for (const [owner, { descriptor, observedRequest }] of healthWrappers) {
        if (owner.requestJson !== observedRequest) continue;
        if (descriptor) Object.defineProperty(owner, "requestJson", descriptor);
        else delete owner.requestJson;
      }
      healthWrappers.clear();
    },
  };
}

export function observeOwnedSidecarSpawn(childProcess, { executable, profileRoot, invocationRoot, onFact }) {
  const original = childProcess.spawn;
  const listeners = new Map();
  const note = (value) => {
    try { onFact(value); }
    catch { console.warn("The isolated sidecar launch diagnostic could not be recorded."); }
  };
  function wrapper(...args) {
    const child = Reflect.apply(original, this, args);
    let canonical;
    try { canonical = fs.realpathSync(args[0]); } catch { return child; }
    if (canonical.toLowerCase() !== executable.toLowerCase()) return child;
    const argv = args[1];
    const options = args[2] ?? {};
    const env = options.env ?? {};
    const argumentShapeValid = Array.isArray(argv) && argv.length === 4 &&
      argv[0] === "--host" && argv[1] === "127.0.0.1" && argv[2] === "--port" && /^\d+$/.test(argv[3]);
    let dataDirInsideOwnedProfile = null;
    let dataDirInsideOwnedInvocation = null;
    try {
      const dataDir = fs.realpathSync(env.TRAINER_DATA_DIR);
      const inside = (base) => {
        const relative = path.relative(base, dataDir);
        return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(".." + path.sep));
      };
      dataDirInsideOwnedProfile = inside(profileRoot);
      dataDirInsideOwnedInvocation = inside(invocationRoot);
    } catch { /* A missing directory is recorded as unknown, not a scope verdict. */ }
    const keys = ["PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "ELECTRON_RUN_AS_NODE", "NODE_OPTIONS",
      "TRAINER_SIDECAR_TOKEN", "TRAINER_DATA_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "TMP", "TEMP", "PATH"];
    note({ event: "spawn", at: new Date().toISOString(), pid: child.pid ?? null, executable: canonical,
      cwd: options.cwd ?? null, argumentShapeValid, args: argumentShapeValid ? argv : null,
      environmentPresence: Object.fromEntries(keys.map((key) => [key, Boolean(env[key])])),
      dataDirInsideOwnedProfile, dataDirInsideOwnedInvocation });
    const onExit = (exitCode, signal) => {
      listeners.delete(child);
      note({ event: "exit", at: new Date().toISOString(), pid: child.pid ?? null,
        exitCode: Number.isInteger(exitCode) ? exitCode : null, signal: ["SIGTERM", "SIGKILL", "SIGINT"].includes(signal) ? signal : null });
    };
    listeners.set(child, onExit);
    child.once("exit", onExit);
    return child;
  }
  childProcess.spawn = wrapper;
  return () => {
    if (childProcess.spawn === wrapper) childProcess.spawn = original;
    for (const [child, listener] of listeners) child.removeListener("exit", listener);
    listeners.clear();
  };
}

export function linuxSecretDiagnosticLaunchArgs(platform, enabled) {
  return platform === "linux" && enabled
    ? ["--verbose", "--vmodule=*/components/os_crypt/*=1"]
    : [];
}

// Presence only: do not activate a service, enumerate credentials, or export a
// session bus address. The subprocess runs in the same session as Code.
export function inspectLinuxSecretService({ platform = process.platform, env = process.env, runCommand = spawnSync } = {}) {
  if (platform !== "linux") return null;
  const result = runCommand("gdbus", ["call", "--session", "--dest", "org.freedesktop.DBus",
    "--object-path", "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.NameHasOwner",
    "org.freedesktop.secrets"], { env, encoding: "utf8", timeout: 5000, maxBuffer: 16384 });
  const owned = /^\(\s*(true|false)\s*,?\s*\)\s*$/.exec(String(result.stdout ?? ""));
  return {
    checkedAt: new Date().toISOString(),
    sessionBusAddressPresent: Boolean(env.DBUS_SESSION_BUS_ADDRESS),
    displayPresent: Boolean(env.DISPLAY),
    probeCompleted: !result.error && result.status === 0 && Boolean(owned),
    secretServiceOwned: !result.error && result.status === 0 && owned ? owned[1] === "true" : null,
    status: result.status ?? null,
    errorCode: typeof result.error?.code === "string" ? result.error.code : null,
  };
}

// This function is serialized into the isolated driver. It uses that driver's
// own real ExtensionContext.secrets and reports booleans only. Never substitute
// this store for Trainer's provider store or log the key/value.
export async function probeDriverSecretStorage(secretStorage, record, { timeoutMs = 15000 } = {}) {
  if (!secretStorage) throw new Error("The diagnostic driver has no SecretStorage context.");
  const [key, value] = driverSecretDiagnosticRedactions;
  const bounded = async (stage, operation) => {
    let timer;
    try {
      return await Promise.race([
        Promise.resolve().then(operation).catch(() => { throw new Error("SecretStorage diagnostic " + stage + " rejected."); }),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("SecretStorage diagnostic " + stage + " timed out.")), timeoutMs); }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  };
  await record("diagnostic-secret-store", async () => {
    await bounded("store", () => secretStorage.store(key, value));
    return { stored: true };
  });
  await record("diagnostic-secret-get", async () => {
    const matched = await bounded("get", () => secretStorage.get(key)) === value;
    if (!matched) throw new Error("SecretStorage diagnostic get did not round-trip.");
    return { matched };
  });
  await record("diagnostic-secret-delete", async () => {
    await bounded("delete", () => secretStorage.delete(key));
    return { deleted: true };
  });
  await record("diagnostic-secret-confirm-deleted", async () => {
    const absent = await bounded("confirm-deleted", () => secretStorage.get(key)) === undefined;
    if (!absent) throw new Error("SecretStorage diagnostic delete did not remove the item.");
    return { absent };
  });
  return { roundTrip: true };
}

export function redactHostDiagnosticText(value, secrets = []) {
  let text = String(value ?? "");
  for (const secret of secrets.filter((item) => typeof item === "string" && item.length > 0)) {
    text = text.replaceAll(secret, "[redacted]");
  }
  return text
    .replace(/\bBearer\s+[^\s"',;]+/gi, "Bearer [redacted]")
    .replace(/((?:api[_-]?key|authorization|[\w-]*token|secret|password)["']?\s*[:=]\s*["']?)[^\s"',;]+/gi, "$1[redacted]")
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, "$1[redacted]@");
}

// Sanitize values before serialization so log quotes/escapes cannot alter the
// archive's JSON syntax. Keep field names and non-string diagnostic facts.
export function redactHostDiagnosticValue(value, secrets = []) {
  if (typeof value === "string") return redactHostDiagnosticText(value, secrets);
  if (Array.isArray(value)) return value.map((item) => redactHostDiagnosticValue(item, secrets));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key,
      typeof item === "string" && /^(?:api[_-]?key|authorization|[\w-]*token|secret|password)$/i.test(key)
        ? "[redacted]" : redactHostDiagnosticValue(item, secrets),
    ]));
  }
  return value;
}

// Only the fresh profile owned by this invocation is eligible. Never copy its
// databases, credentials, full environment, or a symlink to another profile.
export function captureVsixHostFailureDiagnostics({
  tempRoot, userDataDir, driverDir, extensionsDir, outputDir, attempts = [], secrets = [],
  env = process.env, maxLogBytes = 1024 * 1024, maxLogs = 32,
}) {
  const destination = path.join(outputDir, "host-failure");
  fs.mkdirSync(destination, { recursive: true });
  const root = fs.realpathSync(tempRoot);
  const inside = (candidate) => {
    const relative = path.relative(root, fs.realpathSync(candidate));
    return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`));
  };
  const summary = {
    platform: process.platform, nodeVersion: process.version,
    environment: Object.fromEntries(environmentKeys.filter((key) => env[key]).map((key) => [key, env[key]])),
    directories: {}, attempts, logs: [], errors: [],
  };
  for (const [name, directory] of Object.entries({ userDataDir, driverDir, extensionsDir })) {
    const exists = fs.existsSync(directory);
    summary.directories[name] = { path: directory, exists };
    if (!exists || !inside(directory)) continue;
    summary.directories[name].entries = fs.readdirSync(directory).slice(0, 100);
    if (name === "driverDir") {
      try {
        const manifestPath = path.join(directory, "package.json");
        if (!inside(manifestPath)) throw new Error("Driver manifest escapes the isolated profile.");
        const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
        summary.driver = { main: manifest.main, activationEvents: manifest.activationEvents, engines: manifest.engines };
        summary.driver.mainExists = typeof manifest.main === "string" &&
          fs.existsSync(path.resolve(directory, manifest.main)) && inside(path.resolve(directory, manifest.main));
      } catch (error) {
        summary.errors.push(String(error));
      }
    }
  }
  const logsRoot = path.join(userDataDir, "logs");
  const pending = fs.existsSync(logsRoot) && inside(logsRoot) ? [logsRoot] : [];
  while (pending.length && summary.logs.length < maxLogs) {
    const directory = pending.shift();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isSymbolicLink()) continue;
      const source = path.join(directory, entry.name);
      if (!inside(source)) continue;
      if (entry.isDirectory()) { pending.push(source); continue; }
      const trainerOutput = /^\d+-Trainer\.log$/.test(entry.name) && /^output_logging_/.test(path.basename(directory)) &&
        path.basename(path.dirname(directory)) === "exthost";
      if (!entry.isFile() || (!logNames.has(entry.name) && !trainerOutput) || summary.logs.length >= maxLogs) continue;
      const stat = fs.statSync(source);
      const bytes = Buffer.alloc(Math.min(stat.size, maxLogBytes));
      const descriptor = fs.openSync(source, "r");
      try { fs.readSync(descriptor, bytes, 0, bytes.length, Math.max(0, stat.size - bytes.length)); }
      finally { fs.closeSync(descriptor); }
      const relative = path.relative(logsRoot, source);
      const target = path.join(destination, "logs", relative);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, redactHostDiagnosticText(bytes.toString("utf8"), secrets));
      summary.logs.push({ path: relative, originalBytes: stat.size, truncated: stat.size > maxLogBytes });
    }
  }
  fs.writeFileSync(path.join(destination, "diagnostics.json"),
    JSON.stringify(redactHostDiagnosticValue(summary, secrets), null, 2) + "\n");
  return { directory: destination, logCount: summary.logs.length };
}
