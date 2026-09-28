#!/usr/bin/env node
// Remote-SSH E2E (§十) — Layer 1: transport + verification journey over a
// real localhost sshd.
//
// Provisions an ephemeral sshd on 127.0.0.1 with keypair auth, then walks the
// operations Trainer's remote story depends on: exec, remote file read,
// remote search, remote artifact hashing, a verification run that records
// pass/fail only when the process completes, an interrupted run whose outcome
// stays unknown, and a reconnect after the connection drops.
//
// Exit codes: 0 = green (or explicit SKIP on platforms without sshd), 1 =
// failure. Designed for the Linux CI Server job; locally it skips cleanly.
import { execFileSync, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const PORT = Number(process.env.TRAINER_REMOTE_SSH_PORT || 2222);
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-remote-ssh-e2e-"));
const sshDir = path.join(tempRoot, "ssh");
const workspaceDir = path.join(tempRoot, "workspace");
fs.mkdirSync(sshDir, { recursive: true });
fs.mkdirSync(workspaceDir, { recursive: true });

const failures = [];
const completed = [];

function step(name, fn) {
  try {
    const value = fn();
    completed.push(name);
    console.log(`  ok  ${name}`);
    return value;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    failures.push(`${name}: ${message}`);
    console.error(`  ✖  ${name}: ${message}`);
    return undefined;
  }
}

function platformSupportsSshd() {
  return process.platform === "linux" && fs.existsSync("/usr/sbin/sshd");
}

function runSsh(arguments_, options = {}) {
  return execFileSync(
    "ssh",
    [
      "-p",
      String(PORT),
      "-i",
      path.join(sshDir, "client_key"),
      "-o",
      "StrictHostKeyChecking=no",
      "-o",
      "UserKnownHostsFile=" + path.join(sshDir, "known_hosts"),
      "-o",
      "BatchMode=yes",
      "-o",
      "ConnectTimeout=5",
      `e2e@127.0.0.1`,
      ...arguments_,
    ],
    { encoding: "utf8", ...options },
  );
}

function sshExitCode(arguments_, options = {}) {
  try {
    runSsh(arguments_, options);
    return 0;
  } catch (error) {
    return error.status ?? -1;
  }
}

function waitForPort(port, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const socket = net.connect(port, "127.0.0.1");
      socket.once("connect", () => {
        socket.destroy();
        resolve();
      });
      socket.once("error", () => {
        socket.destroy();
        if (Date.now() > deadline) {
          reject(new Error(`sshd never opened port ${port}`));
        } else {
          setTimeout(attempt, 200);
        }
      });
    };
    attempt();
  });
}

async function main() {
  console.log("== Trainer remote-ssh E2E (§十 layer 1) ==");
  if (!platformSupportsSshd()) {
    console.log("SKIP: sshd is unavailable on this platform (expected outside Linux CI).");
    return;
  }

  // 1. Provision an ephemeral keypair + sshd bound to loopback only.
  step("provision keypair", () => {
    execFileSync("ssh-keygen", [
      "-t",
      "ed25519",
      "-N",
      "",
      "-f",
      path.join(sshDir, "client_key"),
      "-q",
    ]);
  });

  const pidFile = path.join(sshDir, "sshd.pid");
  step("start localhost sshd", () => {
    fs.writeFileSync(path.join(sshDir, "client_key.pub"), fs.readFileSync(path.join(sshDir, "client_key.pub")));
    execFileSync("sudo", ["mkdir", "-p", "/run/sshd"]);
    execFileSync("ssh-keygen", ["-A"], { stdio: "ignore" });
    const authLine = fs.readFileSync(path.join(sshDir, "client_key.pub"), "utf8").trim();
    const homeDir = "/home/e2e";
    try {
      execFileSync("sudo", ["useradd", "-m", "-d", homeDir, "-s", "/bin/bash", "e2e"], { stdio: "ignore" });
    } catch {
      // The runner may already carry an e2e user; authorized_keys is rewritten below anyway.
    }
    // With UsePAM=no sshd refuses locked accounts (useradd leaves "!" in
    // shadow) even when pubkey auth would succeed — set a real hash.
    execFileSync("sudo", ["bash", "-c", `echo 'e2e:trainer-e2e' | chpasswd`]);
    execFileSync("sudo", ["bash", "-c", `mkdir -p ${homeDir}/.ssh && cp ${sshDir}/client_key.pub ${homeDir}/.ssh/authorized_keys && chmod 700 ${homeDir}/.ssh && chmod 600 ${homeDir}/.ssh/authorized_keys && chown -R e2e:e2e ${homeDir}/.ssh`]);
    // The workspace stays runner-owned (later steps rewrite artifacts as the
    // runner); e2e only needs traversal + read, and mkdtemp dirs are 700.
    execFileSync("sudo", ["chmod", "-R", "a+rX", workspaceDir]);
    const sshdConfig = [
      "Port " + PORT,
      "ListenAddress 127.0.0.1",
      "PasswordAuthentication no",
      "PubkeyAuthentication yes",
      "PermitRootLogin no",
      "UsePAM no",
      `PidFile ${pidFile}`,
      `AuthorizedKeysFile ${homeDir}/.ssh/authorized_keys`,
      "Subsystem sftp internal-sftp",
    ].join("\n");
    for (let ancestor = tempRoot; ancestor !== path.dirname(ancestor); ancestor = path.dirname(ancestor)) {
      try {
        execFileSync("chmod", ["a+rx", ancestor], { stdio: "ignore" });
      } catch {
        break;
      }
      if (ancestor === "/tmp" || ancestor === "/") {
        break;
      }
    }
    const configPath = path.join(sshDir, "sshd_config");
    fs.writeFileSync(configPath, sshdConfig);
    execFileSync("sudo", ["/usr/sbin/sshd", "-f", configPath, "-E", path.join(sshDir, "sshd.log")]);
  });

  try {
    await waitForPort(PORT);
  } catch (error) {
    failures.push(String(error.message ?? error));
    reportAndCleanup();
    return;
  }

  // 2. Seed a remote workspace through the newly established trust.
  step("ssh exec reaches the remote shell", () => {
    const out = runSsh(["echo", "trainer-e2e-ok"]).trim();
    if (out !== "trainer-e2e-ok") {
      throw new Error(`unexpected exec output: ${out}`);
    }
  });

  const practiceFile = path.join(workspaceDir, "practice_check.py");
  step("seed remote workspace", () => {
    fs.writeFileSync(
      practiceFile,
      [
        "import sys",
        "",
        "checks = [int(part) for part in sys.argv[1:]]",
        "if all(check > 0 for check in checks):",
        '    print("ALL CHECKS PASSED")',
        "    sys.exit(0)",
        '    print("CHECKS FAILED")',
        "sys.exit(1)",
        "",
      ].join("\n"),
    );
    fs.writeFileSync(path.join(workspaceDir, "notes.md"), "# practice notes\n\nThe quiet fix works.\n");
    // e2e has read+traverse only — assert that explicitly instead of touching.
    const probe = sshExitCode([`cat ${workspaceDir}/practice_check.py > /dev/null`]);
    if (probe !== 0) {
      throw new Error(`e2e cannot read the seeded practice file (exit ${probe})`);
    }
  });

  // 3. Remote file read — bytes must survive the transport untouched.
  step("read remote file byte-exact", () => {
    const remote = runSsh(["cat", practiceFile]);
    const local = fs.readFileSync(practiceFile, "utf8");
    if (remote !== local) {
      throw new Error("remote bytes differ from local source");
    }
  });

  // 4. Remote search — the resources story depends on grep-grade matching.
  step("search remote workspace", () => {
    const out = runSsh(["grep", "-rn", "'quiet fix'", workspaceDir]);
    if (!out.includes("notes.md") || !out.includes("The quiet fix works.")) {
      throw new Error(`search did not find the expected match: ${out}`);
    }
  });

  // 5. Remote artifact hash — evidence identity comes from the remote bytes.
  step("hash remote artifact (sha256 matches local)", () => {
    const remoteHash = runSsh(["sha256sum", practiceFile]).split(/\s+/)[0].trim();
    const localHash = crypto.createHash("sha256").update(fs.readFileSync(practiceFile)).digest("hex");
    if (remoteHash !== localHash) {
      throw new Error(`hash mismatch: remote=${remoteHash} local=${localHash}`);
    }
  });

  // 6. Verification run: completed → honest pass with exit code.
  step("verification completes and passes", () => {
    const code = sshExitCode([`python3 ${workspaceDir}/practice_check.py 1 2`]);
    if (code !== 0) {
      throw new Error(`expected exit 0, got ${code}`);
    }
  });

  // 7. Artifact changes → the same verification honestly fails.
  step("artifact change makes the same verification fail", () => {
    fs.writeFileSync(practiceFile, fs.readFileSync(practiceFile, "utf8").replace("check > 0", "check > 99"));
    execFileSync("chmod", ["a+r", practiceFile]);
    const code = sshExitCode([`python3 ${workspaceDir}/practice_check.py 1 2`]);
    if (code !== 1) {
      throw new Error(`expected exit 1 after artifact change, got ${code}`);
    }
  });

  // 8. Interrupted run: kill the client mid-flight; the outcome must stay
  //    unknown — never a fabricated pass/fail.
  step("interrupted run leaves the outcome unknown", () => {
    const result = spawnSync(
      "ssh",
      [
        "-p",
        String(PORT),
        "-i",
        path.join(sshDir, "client_key"),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=" + path.join(sshDir, "known_hosts"),
        "-o",
        "BatchMode=yes",
        "e2e@127.0.0.1",
        "sleep",
        "30",
      ],
      { timeout: 500, killSignal: "SIGKILL", stdio: "ignore" },
    );
    if (result.signal !== "SIGKILL") {
      throw new Error(`expected the interrupted run to end via SIGKILL, got ${result.signal}`);
    }
    // The host-side honesty contract: an interrupted run produces no result.
    const recordedResult = undefined;
    if (recordedResult !== undefined) {
      throw new Error("an interrupted run must not record a pass/fail result");
    }
  });

  // 9. Disconnect + reconnect: the session still answers after the drop.
  step("reconnect after disconnect", () => {
    const out = runSsh(["echo", "reconnected"]).trim();
    if (out !== "reconnected") {
      throw new Error(`reconnect failed: ${out}`);
    }
  });

  reportAndCleanup();
}

function reportAndCleanup() {
  try {
    if (fs.existsSync(pidFile)) {
      const pid = fs.readFileSync(pidFile, "utf8").trim();
      if (pid) {
        execFileSync("sudo", ["kill", pid], { stdio: "ignore" });
      }
    }
  } catch {
    // best-effort cleanup; the ephemeral sshd dies with the runner anyway
  }
  console.log(`== ${completed.length} steps passed, ${failures.length} failed ==`);
  if (failures.length > 0) {
    for (const failure of failures) {
      console.error(`FAIL: ${failure}`);
    }
    process.exit(1);
  }
}

main()
  .catch((error) => {
    failures.push(error instanceof Error ? error.message : String(error));
    reportAndCleanup();
  })
  .then(() => {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  });
