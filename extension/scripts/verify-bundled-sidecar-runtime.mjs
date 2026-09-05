import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { resolveNativeSidecarTarget } from "./bundle-sidecar-binary.mjs";
import { resolveBundledBinaryCandidates } from "./verify-package.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const HEALTH_TIMEOUT_MS = 30_000;
const HEALTH_POLL_INTERVAL_MS = 250;
const HEALTH_REQUEST_TIMEOUT_MS = 1_500;
const CHILD_STOP_TIMEOUT_MS = 5_000;
const OUTPUT_LIMIT = 4_000;

export function resolveBundledSidecarRuntime({
  extensionDir = path.resolve(__dirname, ".."),
  targetPlatform = resolveNativeSidecarTarget(),
} = {}) {
  const { bundledBinaryDir, candidates } = resolveBundledBinaryCandidates(
    extensionDir,
    targetPlatform,
  );
  const binaryPath = candidates.find((candidate) => fs.existsSync(candidate));
  if (!binaryPath) {
    throw new Error(
      `Cannot run the bundled sidecar smoke because ${targetPlatform} has no sidecar executable in ${bundledBinaryDir}.`,
    );
  }
  return { binaryPath, bundledBinaryDir, targetPlatform };
}

export async function findAvailableLoopbackPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close(() => reject(new Error("Could not allocate a loopback port for the sidecar smoke.")));
        return;
      }
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve(address.port);
      });
    });
  });
}

export async function probeBundledSidecarHealth(port, timeoutMs = HEALTH_REQUEST_TIMEOUT_MS) {
  return new Promise((resolve) => {
    const request = http.get(
      {
        hostname: "127.0.0.1",
        port,
        path: "/health",
        timeout: timeoutMs,
      },
      (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          if (body.length < OUTPUT_LIMIT) {
            body += chunk;
          }
        });
        response.on("end", () => {
          if (response.statusCode !== 200) {
            resolve(false);
            return;
          }
          try {
            const payload = JSON.parse(body);
            resolve(payload?.status === "ok");
          } catch {
            resolve(false);
          }
        });
      },
    );
    request.once("timeout", () => request.destroy());
    request.once("error", () => resolve(false));
  });
}

export async function waitForBundledSidecarHealth({
  child,
  port,
  startupTimeoutMs = HEALTH_TIMEOUT_MS,
  pollIntervalMs = HEALTH_POLL_INTERVAL_MS,
  probeHealth = probeBundledSidecarHealth,
} = {}) {
  let launchError;
  let exitDetail;
  const onError = (error) => {
    launchError = error;
  };
  const onExit = (code, signal) => {
    exitDetail = `code=${code}, signal=${signal}`;
  };
  child.once("error", onError);
  child.once("exit", onExit);

  try {
    const startedAt = Date.now();
    while (Date.now() - startedAt < startupTimeoutMs) {
      if (launchError) {
        throw launchError;
      }
      if (exitDetail) {
        throw new Error(`Bundled sidecar exited before readiness (${exitDetail}).`);
      }
      if (await probeHealth(port)) {
        return;
      }
      await delay(pollIntervalMs);
    }
    throw new Error(`Bundled sidecar did not answer /health within ${startupTimeoutMs}ms.`);
  } finally {
    child.removeListener("error", onError);
    child.removeListener("exit", onExit);
  }
}

export async function stopBundledSidecar(child, timeoutMs = CHILD_STOP_TIMEOUT_MS) {
  if (!child || child.exitCode !== null) {
    return;
  }

  const exited = new Promise((resolve) => child.once("exit", resolve));
  try {
    child.kill();
  } catch {
    return;
  }
  await Promise.race([exited, delay(timeoutMs)]);
}

export async function verifyBundledSidecarRuntime({
  extensionDir = path.resolve(__dirname, ".."),
  targetPlatform = resolveNativeSidecarTarget(),
  env = process.env,
  startupTimeoutMs = HEALTH_TIMEOUT_MS,
  pollIntervalMs = HEALTH_POLL_INTERVAL_MS,
  spawnProcess = spawn,
  findPort = findAvailableLoopbackPort,
  probeHealth = probeBundledSidecarHealth,
} = {}) {
  const runtime = resolveBundledSidecarRuntime({ extensionDir, targetPlatform });
  const dataDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "trainer-sidecar-runtime-"));
  const port = await findPort();
  let child;
  let output = "";

  try {
    child = spawnProcess(
      runtime.binaryPath,
      ["--host", "127.0.0.1", "--port", String(port)],
      {
        cwd: path.dirname(runtime.binaryPath),
        env: {
          ...env,
          TRAINER_DATA_DIR: dataDirectory,
        },
        stdio: "pipe",
        windowsHide: true,
      },
    );
    const appendOutput = (chunk) => {
      output = `${output}${String(chunk)}`.slice(-OUTPUT_LIMIT);
    };
    child.stdout?.on("data", appendOutput);
    child.stderr?.on("data", appendOutput);

    await waitForBundledSidecarHealth({
      child,
      port,
      startupTimeoutMs,
      pollIntervalMs,
      probeHealth,
    });
    return {
      ...runtime,
      port,
    };
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    const outputDetail = output.trim() ? `\nSidecar output:\n${output.trim()}` : "";
    throw new Error(
      `Bundled ${runtime.targetPlatform} sidecar runtime smoke failed: ${reason}${outputDetail}`,
    );
  } finally {
    await stopBundledSidecar(child);
    fs.rmSync(dataDirectory, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  }
}

function delay(timeoutMs) {
  return new Promise((resolve) => setTimeout(resolve, timeoutMs));
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  try {
    const result = await verifyBundledSidecarRuntime();
    console.log(`Bundled ${result.targetPlatform} sidecar started and answered /health.`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(message);
    process.exit(1);
  }
}
