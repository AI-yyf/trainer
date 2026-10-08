import { spawn, spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(scriptPath), "..");
const tools = Object.freeze({
  bus: "/usr/bin/dbus-run-session", display: "/usr/bin/xvfb-run",
  daemon: "/usr/bin/gnome-keyring-daemon", dbus: "/usr/bin/gdbus",
  secret: "/usr/bin/secret-tool",
});
const paths = Object.freeze({
  XDG_CONFIG_HOME: "config", XDG_DATA_HOME: "data", XDG_CACHE_HOME: "cache",
  XDG_RUNTIME_DIR: "runtime", GNOME_KEYRING_CONTROL: "runtime/keyring",
});
const busDigest = (env) => createHash("sha256").update(env.DBUS_SESSION_BUS_ADDRESS ?? "").digest("hex");

export function randomKeyringPassword() {
  const entropy = randomBytes(48);
  try { return Buffer.from(entropy.toString("base64")); }
  finally { entropy.fill(0); }
}

// References: dbus-run-session(1) owns a fresh bus until its child exits;
// GNOME --foreground --unlock reads the password from stdin and does not fork.
// https://dbus.freedesktop.org/doc/dbus-run-session.1.html
// https://manpages.debian.org/trixie/gnome-keyring/gnome-keyring-daemon.1.en.html
export function createLinuxKeyringScope({ env = process.env, baseDir = os.tmpdir() } = {}) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(baseDir, "trainer-ci-keyring-")));
  fs.chmodSync(root, 0o700);
  const scoped = { ...env, TRAINER_E2E_LINUX_KEYRING_ROOT: root };
  for (const [key, relative] of Object.entries(paths)) {
    const directory = path.join(root, relative);
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    fs.chmodSync(directory, 0o700);
    scoped[key] = directory;
  }
  fs.mkdirSync(path.join(scoped.XDG_DATA_HOME, "keyrings"), { mode: 0o700 });
  for (const key of ["DBUS_SESSION_BUS_ADDRESS", "DBUS_SESSION_BUS_PID", "DBUS_STARTER_ADDRESS",
    "DBUS_STARTER_BUS_TYPE", "GNOME_KEYRING_PID", "TRAINER_E2E_LINUX_KEYRING_READY", "TRAINER_E2E_LINUX_KEYRING_PID"])
    delete scoped[key];
  const stat = fs.lstatSync(root);
  return { root, env: scoped, rootIdentity: Object.freeze({ dev: stat.dev, ino: stat.ino, uid: stat.uid }) };
}

export function privateUnixPermissions(mode, { directory = false, platform = process.platform } = {}) {
  // Windows has no POSIX permission bits. The public launcher accepts Linux
  // only; tests on Windows still exercise canonical ownership and Unix policy.
  return platform === "win32" || (directory ? (mode & 0o777) === 0o700 : (mode & 0o077) === 0);
}

export function assertLinuxKeyringRoot(supplied, { uid = process.getuid?.(), identity } = {}) {
  if (typeof supplied !== "string" || !path.isAbsolute(supplied)) throw new Error("Missing owned Linux keyring scope.");
  const root = fs.realpathSync(supplied);
  if (root !== supplied || !path.basename(root).startsWith("trainer-ci-keyring-"))
    throw new Error("Linux keyring root is not the canonical owned temporary directory.");
  const stat = fs.lstatSync(root);
  if (!stat.isDirectory() || stat.isSymbolicLink() || !privateUnixPermissions(stat.mode, { directory: true }) ||
      (uid !== undefined && stat.uid !== uid) ||
      (identity && (identity.dev !== stat.dev || identity.ino !== stat.ino || identity.uid !== stat.uid)))
    throw new Error("Linux keyring root no longer matches its original private owned directory.");
  return root;
}

export function assertLinuxKeyringScope(env, { uid = process.getuid?.() } = {}) {
  const root = assertLinuxKeyringRoot(env.TRAINER_E2E_LINUX_KEYRING_ROOT, { uid });
  for (const directory of [root, ...Object.entries(paths).map(([key, relative]) => {
    const expected = path.join(root, relative);
    if (env[key] !== expected) throw new Error("Linux keyring XDG directory is outside its owned scope.");
    return expected;
  }), path.join(root, "data/keyrings")]) {
    const stat = fs.lstatSync(directory);
    if (!stat.isDirectory() || stat.isSymbolicLink() || fs.realpathSync(directory) !== directory ||
        !privateUnixPermissions(stat.mode, { directory: true }) || (uid !== undefined && stat.uid !== uid))
      throw new Error("Linux keyring scope must contain only private directories owned by this user.");
  }
  return root;
}

export function removeLinuxKeyringScope(scope) {
  if (!scope.rootIdentity) throw new Error("The original owned Linux keyring root identity is missing.");
  const root = assertLinuxKeyringRoot(scope.root, { identity: scope.rootIdentity });
  // GNOME removes its control directory on exit. Cleanup owns the original
  // root, not the lifetime of each XDG child; recursive rm never follows links.
  fs.rmSync(root, { recursive: true, force: true });
  if (fs.existsSync(root)) throw new Error("The owned Linux keyring root was not removed.");
  return { originalOwnedRootVerified: true, rootRemoved: true };
}

export function ownedKeyringProcess(pid, env) {
  try {
    if (!Number.isInteger(pid) || pid <= 0 || fs.statSync(`/proc/${pid}`).uid !== process.getuid()) return false;
    const executable = fs.realpathSync(`/proc/${pid}/exe`);
    const argv = fs.readFileSync(`/proc/${pid}/cmdline`, "utf8").split("\0").filter(Boolean);
    return executable === tools.daemon && argv.includes("--foreground") && argv.includes("--components=secrets") &&
      argv.includes(`--control-directory=${env.GNOME_KEYRING_CONTROL}`);
  } catch { return false; }
}

// This option is restricted to the prepared CI session. It selects a genuine
// Secret Service backend, never Chromium basic text or in-memory SecretStorage.
// https://code.visualstudio.com/docs/configure/settings-sync#_configure-a-keyring-backend
export function linuxSecureKeyringLaunchArgs(platform, env, { checkProcess = ownedKeyringProcess } = {}) {
  if (platform !== "linux" || env.TRAINER_E2E_LINUX_KEYRING_READY === undefined) return [];
  const root = assertLinuxKeyringScope(env);
  if (env.TRAINER_E2E_LINUX_KEYRING_READY !== "1" || !env.DBUS_SESSION_BUS_ADDRESS || !env.DISPLAY)
    throw new Error("The owned Linux keyring session is not ready.");
  const receipt = JSON.parse(fs.readFileSync(path.join(root, "ready.json"), "utf8"));
  const pid = Number(env.TRAINER_E2E_LINUX_KEYRING_PID);
  if (receipt.ready !== true || receipt.unlocked !== true || receipt.roundTrip !== true || receipt.deleted !== true || receipt.encryptedKeyring !== true ||
      receipt.pid !== pid || receipt.busDigest !== busDigest(env) || !checkProcess(pid, env))
    throw new Error("The Linux keyring backend no longer matches this owned session.");
  return ["--password-store=gnome-libsecret"];
}

export function runPrivateTool(command, args, { env, input, run = spawnSync } = {}) {
  const result = run(command, args, { env, input, timeout: 5000, maxBuffer: 16384, encoding: "buffer" });
  if (result.error || result.status !== 0)
    throw new Error(`Linux keyring prerequisite ${path.basename(command)} failed.`);
  return Buffer.isBuffer(result.stdout) ? result.stdout : Buffer.from(result.stdout ?? "");
}

export function verifyKeyringBackend(env, pid, { run = spawnSync, secret = randomBytes(48) } = {}) {
  let value;
  let stored = false;
  let primaryFailure;
  let attributes;
  try {
    attributes = ["trainer-ci-scope", path.basename(env.TRAINER_E2E_LINUX_KEYRING_ROOT)];
    const call = (method, ...args) => runPrivateTool(tools.dbus, ["call", "--session", "--dest", "org.freedesktop.DBus",
      "--object-path", "/org/freedesktop/DBus", "--method", method, ...args], { env, run }).toString("utf8").trim();
    const owner = call("org.freedesktop.DBus.GetConnectionUnixProcessID", "org.freedesktop.secrets");
    if (!new RegExp(`^\\(uint32 ${pid},?\\)$`).test(owner)) throw new Error("Secret Service is not the owned keyring process.");
    const alias = runPrivateTool(tools.dbus, ["call", "--session", "--dest", "org.freedesktop.secrets",
      "--object-path", "/org/freedesktop/secrets", "--method", "org.freedesktop.Secret.Service.ReadAlias", "default"], { env, run });
    const collection = /^\(objectpath '([^']+)',?\)$/.exec(alias.toString("utf8").trim())?.[1];
    if (!collection || !/^\/org\/freedesktop\/secrets\/collection\/[A-Za-z0-9_]+$/.test(collection) || collection.endsWith("/session"))
      throw new Error("The owned keyring has no default persistent collection.");
    const locked = runPrivateTool(tools.dbus, ["call", "--session", "--dest", "org.freedesktop.secrets",
      "--object-path", collection, "--method", "org.freedesktop.DBus.Properties.Get",
      "org.freedesktop.Secret.Collection", "Locked"], { env, run });
    if (locked.toString("utf8").trim() !== "(<false>,)") throw new Error("The owned default keyring is locked.");
    value = Buffer.from(secret.toString("base64"));
    runPrivateTool(tools.secret, ["store", "--label=Trainer isolated CI prerequisite", ...attributes], { env, input: value, run });
    stored = true;
    const found = runPrivateTool(tools.secret, ["lookup", ...attributes], { env, run });
    try {
      if (!found.equals(value) && !found.equals(Buffer.concat([value, Buffer.from("\n")])))
        throw new Error("The owned Secret Service did not round-trip its private prerequisite item.");
    } finally { found.fill(0); }
    runPrivateTool(tools.secret, ["clear", ...attributes], { env, run });
    const absent = run(tools.secret, ["lookup", ...attributes], { env, timeout: 5000, maxBuffer: 16384, encoding: "buffer" });
    const absentValue = Buffer.from(absent.stdout ?? "");
    try {
      if (absent.error || absent.status !== 1 || absentValue.length !== 0)
        throw new Error("The private keyring prerequisite item was not deleted.");
    } finally { absentValue.fill(0); }
    stored = false;
    return { ready: true, unlocked: true, roundTrip: true, deleted: true };
  } catch (error) {
    primaryFailure = error;
    throw error;
  } finally {
    value?.fill(0); secret.fill(0);
    if (stored) {
      try { runPrivateTool(tools.secret, ["clear", ...attributes], { env, run }); }
      catch (cleanupFailure) {
        if (primaryFailure) throw new AggregateError([primaryFailure, cleanupFailure],
          "The keyring prerequisite failed and its owned private item could not be deleted.");
        throw cleanupFailure;
      }
    }
  }
}

export function inspectEncryptedKeyring(env) {
  const root = assertLinuxKeyringScope(env);
  const directory = path.join(root, "data/keyrings");
  // GNOME's binary encrypted format, not its unencrypted [keyring] format.
  // https://github.com/GNOME/gnome-keyring/blob/master/pkcs11/secret-store/gkm-secret-binary.c
  const header = Buffer.from("GnomeKeyring\n\r\0\n\0");
  const files = fs.readdirSync(directory).filter((name) => name.endsWith(".keyring"));
  if (!files.length || files.length > 10) throw new Error("The owned persistent encrypted keyring was not created.");
  for (const name of files) {
    const file = path.join(directory, name);
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink() || fs.realpathSync(file) !== file || !privateUnixPermissions(stat.mode))
      throw new Error("The owned keyring file is not private.");
    const bytes = Buffer.alloc(header.length);
    const descriptor = fs.openSync(file, "r");
    try {
      if (fs.readSync(descriptor, bytes, 0, bytes.length, 0) !== header.length || !bytes.equals(header))
        throw new Error("The owned keyring is not in GNOME's encrypted persistent format.");
    } finally { fs.closeSync(descriptor); bytes.fill(0); }
  }
  return true;
}

export async function stopOwnedProcess(child, { group = false, graceMs = 3000, signalProcess = process.kill.bind(process) } = {}) {
  if (!child?.pid) return;
  if (group) {
    const alive = () => {
      try { signalProcess(-child.pid, 0); return true; }
      catch (error) { if (error.code === "ESRCH") return false; throw error; }
    };
    const send = (signal) => {
      try { signalProcess(-child.pid, signal); }
      catch (error) { if (error.code !== "ESRCH") throw error; }
    };
    for (const signal of ["SIGTERM", "SIGKILL"]) {
      if (!alive()) return;
      send(signal);
      const until = Date.now() + graceMs;
      while (Date.now() < until) {
        if (!alive()) return;
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
    }
    throw new Error("Owned Linux acceptance process group did not stop.");
  }
  if (child.exitCode !== null || child.signalCode) return;
  let onExit;
  const exited = new Promise((resolve) => { onExit = resolve; child.once("exit", onExit); });
  const signal = (name) => {
    try { child.kill(name); }
    catch (error) { if (error.code !== "ESRCH") throw error; }
  };
  let timer;
  try {
    signal("SIGTERM");
    const timedOut = await Promise.race([exited.then(() => false), new Promise((resolve) => {
      timer = setTimeout(() => resolve(true), graceMs);
    })]);
    clearTimeout(timer);
    if (timedOut) {
      signal("SIGKILL");
      await Promise.race([exited, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Owned Linux acceptance process did not stop.")), graceMs);
      })]);
    }
  } finally {
    clearTimeout(timer);
    child.removeListener("exit", onExit);
  }
}

async function waitForOwner(env, daemon) {
  const until = Date.now() + 10000;
  while (Date.now() < until) {
    if (daemon.exitCode !== null || daemon.signalCode) throw new Error("The owned keyring daemon exited before readiness.");
    const output = runPrivateTool(tools.dbus, ["call", "--session", "--dest", "org.freedesktop.DBus",
      "--object-path", "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.secrets"], { env });
    if (output.toString("utf8").trim() === "(true,)") return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("The owned keyring daemon did not claim Secret Service within its preparation window.");
}

async function runBounded(command, args, { env, timeoutMs = 660000 } = {}) {
  const child = spawn(command, args, { env, cwd: repoRoot, stdio: "inherit", detached: true });
  let timer;
  let interruptedRun = false;
  let signalCleanup;
  const interrupted = () => {
    interruptedRun = true;
    signalCleanup = stopOwnedProcess(child, { group: true }).then(() => null, (error) => error);
  };
  process.once("SIGINT", interrupted); process.once("SIGTERM", interrupted);
  try {
    return await Promise.race([
      new Promise((resolve, reject) => {
        child.once("error", () => reject(new Error("Owned Linux acceptance process could not launch.")));
        child.once("exit", (code, signal) => resolve(signal || interruptedRun ? 1 : (code ?? 1)));
      }),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Owned Linux acceptance wrapper exceeded its bounded runtime.")), timeoutMs); }),
    ]);
  } finally {
    clearTimeout(timer); process.removeListener("SIGINT", interrupted); process.removeListener("SIGTERM", interrupted);
    await stopOwnedProcess(child, { group: true });
    const cleanupFailure = await signalCleanup;
    if (cleanupFailure) throw cleanupFailure;
  }
}

export function writeKeyringPassword(stream, password, { timeoutMs = 5000 } = {}) {
  // Writable.end's completion callback owns this Buffer until the queued write
  // finishes (including a destroyed pipe). Do not wipe it on an earlier error
  // or timeout: doing so can silently send a zeroed unlock password.
  return new Promise((resolve, reject) => {
    let timer;
    const failed = () => reject(new Error("The owned keyring password pipe could not close."));
    stream.once("error", failed);
    timer = setTimeout(() => {
      stream.destroy();
      reject(new Error("The owned keyring password pipe timed out."));
    }, timeoutMs);
    try {
      stream.end(password, (error) => {
        password.fill(0);
        clearTimeout(timer);
        stream.removeListener("error", failed);
        if (error) failed(); else resolve();
      });
    } catch {
      // A synchronous end failure never queued the Buffer.
      password.fill(0);
      clearTimeout(timer);
      stream.removeListener("error", failed);
      failed();
    }
  });
}

export async function runPreparedLinuxHost({ env = process.env, spawnProcess = spawn, runTool = spawnSync,
  waitReady = waitForOwner, runHost = runBounded, checkProcess = ownedKeyringProcess } = {}) {
  const root = assertLinuxKeyringScope(env);
  if (!env.DBUS_SESSION_BUS_ADDRESS || !env.DISPLAY) throw new Error("The isolated keyring and Code require the same bus and display session.");
  const previousOwner = runPrivateTool(tools.dbus, ["call", "--session", "--dest", "org.freedesktop.DBus",
    "--object-path", "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.NameHasOwner", "org.freedesktop.secrets"], { env, run: runTool });
  if (previousOwner.toString("utf8").trim() !== "(false,)")
    throw new Error("The prepared D-Bus session already has a Secret Service; no existing keyring will be touched.");
  let daemon;
  const password = randomKeyringPassword();
  let passwordQueued = false;
  try {
    daemon = spawnProcess(tools.daemon, ["--foreground", "--components=secrets", `--control-directory=${env.GNOME_KEYRING_CONTROL}`, "--unlock"],
      { env, stdio: ["pipe", "ignore", "ignore"] });
    const launchFailure = new Promise((_, reject) => {
      daemon.once("error", () => reject(new Error("The owned keyring daemon could not launch.")));
    });
    passwordQueued = true;
    await Promise.race([writeKeyringPassword(daemon.stdin, password), launchFailure]);
    await waitReady(env, daemon);
    const verified = { ...verifyKeyringBackend(env, daemon.pid, { run: runTool }), encryptedKeyring: inspectEncryptedKeyring(env) };
    fs.writeFileSync(path.join(root, "ready.json"), JSON.stringify({ ...verified, pid: daemon.pid, busDigest: busDigest(env) }) + "\n", { mode: 0o600 });
    const childEnv = { ...env, TRAINER_E2E_LINUX_KEYRING_READY: "1", TRAINER_E2E_LINUX_KEYRING_PID: String(daemon.pid) };
    linuxSecureKeyringLaunchArgs("linux", childEnv, { checkProcess });
    const receiptPath = path.resolve(path.dirname(env.TRAINER_E2E_EXPORT_REPORT_PATH || "output/maturity/ci-installed/host-report.json"), "linux-keyring-environment.json");
    fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
    fs.writeFileSync(receiptPath, JSON.stringify({ ...verified, backend: "gnome-libsecret", sessionBusPresent: true, displayPresent: true, ownedPrivateXdg: true }) + "\n");
    return await runHost(process.execPath, [path.join(repoRoot, "extension/scripts/verify-vsix-e2e.mjs")], { env: childEnv });
  } finally {
    if (!passwordQueued) password.fill(0);
    await stopOwnedProcess(daemon);
  }
}

export async function runLinuxHostInOwnedSession({ env = process.env, platform = process.platform, runSession = runBounded } = {}) {
  if (platform !== "linux" || env.CI !== "true") throw new Error("This secure keyring launcher is restricted to the disposable Linux CI runner.");
  const scope = createLinuxKeyringScope({ env });
  let sessionExitCode;
  let sessionFailure;
  try {
    // Preparation/CLI install/cleanup have their own bounds. The actual Code
    // launch retains verify-vsix-e2e's original ten-minute timeout unchanged.
    sessionExitCode = await runSession(tools.bus, ["--", tools.display, "--auto-servernum", process.execPath, scriptPath, "--session"], { env: scope.env, timeoutMs: 720000 });
    return sessionExitCode;
  } catch (error) {
    sessionFailure = error;
    throw error;
  } finally {
    let cleanupFailure;
    let cleanup = { originalOwnedRootVerified: false, rootRemoved: false };
    try { cleanup = removeLinuxKeyringScope(scope); }
    catch (error) { cleanupFailure = error; }
    const receiptPath = path.resolve(path.dirname(env.TRAINER_E2E_EXPORT_REPORT_PATH || "output/maturity/ci-installed/host-report.json"), "linux-keyring-cleanup.json");
    try {
      fs.mkdirSync(path.dirname(receiptPath), { recursive: true });
      fs.writeFileSync(receiptPath, JSON.stringify({ ...cleanup, ok: !cleanupFailure,
        sessionExitCode: Number.isInteger(sessionExitCode) ? sessionExitCode : null,
        sessionFailed: Boolean(sessionFailure) || (Number.isInteger(sessionExitCode) && sessionExitCode !== 0),
        cleanupFailed: Boolean(cleanupFailure) }) + "\n");
    } catch (receiptFailure) {
      cleanupFailure = cleanupFailure ? new AggregateError([cleanupFailure, receiptFailure],
        "Owned Linux keyring cleanup and its receipt could not complete.") : receiptFailure;
    }
    if (cleanupFailure) {
      if (sessionFailure) throw new AggregateError([sessionFailure, cleanupFailure],
        "The Linux host session failed and owned keyring cleanup also failed; native facts remain in the host report.");
      throw new Error("Owned Linux keyring cleanup failed; the native session result remains in the host report.", { cause: cleanupFailure });
    }
  }
}

async function main() {
  if (process.platform !== "linux" || process.env.CI !== "true") throw new Error("This secure keyring launcher is restricted to the disposable Linux CI runner.");
  return process.argv[2] === "--session" ? runPreparedLinuxHost() : runLinuxHostInOwnedSession();
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  try { process.exitCode = await main(); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
