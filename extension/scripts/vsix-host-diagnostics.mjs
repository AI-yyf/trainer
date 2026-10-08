import fs from "node:fs";
import path from "node:path";

const logNames = new Set(["main.log", "renderer.log", "exthost.log", "sharedprocess.log"]);
const environmentKeys = ["DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "TRAINER_E2E_NO_SANDBOX"];

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
      if (!entry.isFile() || !logNames.has(entry.name) || summary.logs.length >= maxLogs) continue;
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
    redactHostDiagnosticText(JSON.stringify(summary, null, 2), secrets) + "\n");
  return { directory: destination, logCount: summary.logs.length };
}
